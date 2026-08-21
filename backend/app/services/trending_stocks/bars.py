"""Multi-timeframe bars for the basket — the constraint the whole module rests on.

THE PROBLEM THIS SOLVES
------------------------
The shared `bars` collection holds deep DAILY history for ~500 NSE symbols (backfilled by
`stocks_range`) and almost no intraday equity bars. Seven of this desk's eight timeframes
would therefore never fire, and the leaderboard would be a daily-only library wearing a
multi-timeframe label. Worse, it would be indistinguishable from "those strategies do not
work" — a data gap that reads as a result is the most expensive kind of bug in this app.

WHY IT IS AFFORDABLE HERE AND NOT IN THE FACTORY
-------------------------------------------------
Angel's candle endpoint throttles far harder than its quote endpoint — the commodity desk
measured 5 of 8 unpaced calls returning 403 — so it must be paced at seconds per request.
Backfilling five native intervals for the factory's 120-symbol equity universe is 600
paced requests and hours of wall clock. Doing it for the 10-30 names the USER NAMES is
~5 requests per symbol per pass. The small basket is not a limitation of this desk; it is
what makes honest intraday coverage possible at all.

WHAT IS STORED AND WHAT IS DERIVED
-----------------------------------
Only the five intervals Angel actually serves are stored: 1m, 5m, 15m, 1h, 1d. 30m, 45m
and 4h are RESAMPLED on read by `strategy_factory.sources.resample`, anchored to the NSE
09:15 open rather than to midnight — a midnight anchor puts a stub bar a third the normal
width at the start of every session, and the range and volatility templates would fire on
it every single morning. Angel does serve a native 30-minute interval, but storing it
would mean two producers of the same series that can drift apart, so it is derived like
the others.

Rows go into the SHARED `bars` collection with the shared schema, so every other module in
the app (the factory's equity source, the screener, Stocks Range) gets the deeper history
for free. `ts` is stored as a real UTC datetime, never its ISO string — that distinction
silently hid 88% of the daily bars in this app once already.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from pymongo import UpdateOne

from app.core.db import bars_collection, instruments_collection
from app.services.angel_client import AngelAPIError, angel_client
from app.services.strategy_factory.sources import (
    DERIVED_FROM, INDICES, NSE_SESSION_OPEN, TF_MINUTES, equity_load_bars, resample,
)

logger = logging.getLogger("trending_stocks.bars")

IST = timezone(timedelta(hours=5, minutes=30))

TIMEFRAMES = ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"]

# label -> Angel resolution key. Only these are fetched and stored.
NATIVE: dict[str, str] = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "1d": "D"}

# How far back to reach on a first backfill, and the largest window Angel will answer in
# one request for that interval. Both are per-interval because Angel's own caps are.
BACKFILL_DAYS = {"1m": 40, "5m": 120, "15m": 250, "1h": 500, "1d": 3650}
CHUNK_DAYS = {"1m": 25, "5m": 90, "15m": 190, "1h": 380, "1d": 1800}

# Bars kept per interval. Sized so the deepest strategy on each timeframe (the
# long-horizon high, at 750 bars on 1m) always has its full lookback plus headroom.
KEEP_BARS = {"1m": 4000, "5m": 3000, "15m": 2500, "1h": 1500, "1d": 3000}

# Pacing. The single knob that decides whether the backfill works at all, so it is
# deliberately conservative — the same value the commodity poller settled on.
CANDLE_MIN_INTERVAL_S = float(os.getenv("TS_CANDLE_INTERVAL_S", "3.0"))
CANDLE_MAX_RETRIES = int(os.getenv("TS_CANDLE_RETRIES", "4"))
CANDLE_BACKOFF_S = float(os.getenv("TS_CANDLE_BACKOFF_S", "6.0"))

# The relative-strength benchmark. NIFTY 50 unless overridden.
BENCHMARK_SYMBOL = os.getenv("TS_BENCHMARK", "NIFTY").upper()

# How far the live quote may sit from the last stored close before the symbol is
# quarantined. A bonus or split the backfilled bars have not been adjusted for — routine
# on NSE — halves the price while leaving every momentum statistic reading "very strong",
# and the desk would buy a 1:2 split at a momentum it never had. A bad tick does the same
# thing faster. 20% is far wider than any real intraday gap on a liquid name.
MAX_QUOTE_DEVIATION_PCT = float(os.getenv("TS_MAX_QUOTE_DEVIATION_PCT", "20"))

_last_call_at = 0.0
_call_lock = asyncio.Lock()
_LAST_ERRORS: dict[str, str] = {}


def _now_ist() -> datetime:
    return datetime.now(IST)


def is_market_open(now: datetime | None = None) -> bool:
    now = now or _now_ist()
    if now.weekday() >= 5:
        return False
    return "09:15" <= now.strftime("%H:%M") <= "15:30"


# --------------------------------------------------------------------------------
# Instrument resolution
# --------------------------------------------------------------------------------

# Angel's own index tokens. Indices are normally resolved from the instrument master like
# everything else; this map is the fallback for an install whose master has not been
# token-mapped yet, so a missing benchmark degrades the relative-strength strategies
# rather than the whole desk. Verified against Angel's scrip master (NSE segment).
INDEX_TOKEN_FALLBACK = {
    "NIFTY": ("NSE", "99926000"),
    "BANKNIFTY": ("NSE", "99926009"),
    "FINNIFTY": ("NSE", "99926037"),
    "MIDCPNIFTY": ("NSE", "99926074"),
}


async def resolve_instrument(symbol: str) -> dict | None:
    """The instrument row for a symbol, equity or index, or None if it cannot be traded.

    Requires an Angel token, because that is what the candle endpoint keys on — a symbol
    the instrument master knows but Angel cannot price is not a symbol this desk can
    honestly offer to trade."""
    sym = symbol.strip().upper()
    doc = await instruments_collection.find_one(
        {"symbol": sym, "asset_class": {"$in": ["EQUITY", "ETF", "INDEX"]},
         "angel_token": {"$ne": None}})
    if doc:
        doc.pop("_id", None)
        return doc
    if sym in INDEX_TOKEN_FALLBACK:
        ex, token = INDEX_TOKEN_FALLBACK[sym]
        return {"symbol": sym, "name": sym, "asset_class": "INDEX", "angel_token": token,
                "angel_exchange": ex, "exchange_segment": "IDX_I", "lot_size": 1,
                "security_id": None, "resolved_from": "index_fallback"}
    return None


# --------------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------------


async def _paced_candles(exchange: str, token: str, resolution: str,
                         from_dt: datetime, to_dt: datetime) -> list[list]:
    """One candle request, globally paced across the whole process and retried on
    throttling. The lock is module-global on purpose: pacing per symbol would still let
    thirty symbols hammer the endpoint in parallel."""
    global _last_call_at
    last_err: Exception | None = None
    for attempt in range(CANDLE_MAX_RETRIES):
        async with _call_lock:
            wait = CANDLE_MIN_INTERVAL_S - (time.monotonic() - _last_call_at)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call_at = time.monotonic()
        try:
            return await angel_client.candles(
                exchange, token, resolution,
                from_dt.strftime("%Y-%m-%d %H:%M"), to_dt.strftime("%Y-%m-%d %H:%M"))
        except AngelAPIError as exc:
            last_err = exc
            await asyncio.sleep(CANDLE_BACKOFF_S * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            break
    raise last_err or RuntimeError("candle fetch failed")


def _rows_to_ops(symbol: str, timeframe: str, rows: list[list], keep: int) -> list[UpdateOne]:
    """Angel rows -> upserts into the shared `bars` schema.

    `ts` is stored as a real UTC datetime. The shared collection is queried with date
    range filters, and a string timestamp matches none of them — that exact bug once made
    88% of this app's daily bars invisible to every loader."""
    parsed: list[tuple[datetime, list]] = []
    for r in rows or []:
        try:
            ts = datetime.fromisoformat(r[0])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            parsed.append((ts.astimezone(timezone.utc), r))
        except (TypeError, ValueError, IndexError):
            continue
    parsed.sort(key=lambda t: t[0])
    parsed = parsed[-keep:]

    ops: list[UpdateOne] = []
    for ts, r in parsed:
        try:
            ops.append(UpdateOne(
                {"symbol": symbol, "timeframe": timeframe, "ts": ts},
                {"$set": {"symbol": symbol, "timeframe": timeframe, "ts": ts,
                          "open": float(r[1]), "high": float(r[2]), "low": float(r[3]),
                          "close": float(r[4]), "volume": float(r[5] or 0), "oi": None,
                          "source": "angel", "updated_at": datetime.now(timezone.utc)}},
                upsert=True))
        except (TypeError, ValueError, IndexError):
            continue
    return ops


async def fetch_timeframe(symbol: str, inst: dict, timeframe: str,
                          since: datetime | None = None) -> int:
    """Pull one native interval for one symbol, chunked to Angel's per-request window.

    `since` makes this an incremental top-up: only bars newer than what is already stored
    are requested, which is what keeps the every-tick refresh to one small call per symbol
    per timeframe instead of a full re-download."""
    resolution = NATIVE.get(timeframe)
    if resolution is None:
        return 0
    exchange = inst.get("angel_exchange") or "NSE"
    token = str(inst.get("angel_token") or "")
    if not token:
        return 0

    to_dt = _now_ist()
    span = timedelta(days=BACKFILL_DAYS[timeframe])
    from_dt = to_dt - span
    if since is not None:
        # One bar of overlap so a partially-formed bar is re-fetched and corrected rather
        # than frozen half-built in the store.
        overlap = timedelta(minutes=TF_MINUTES[timeframe] * 2)
        candidate = since.astimezone(IST) - overlap
        from_dt = max(from_dt, candidate)
    if from_dt >= to_dt:
        return 0

    chunk = timedelta(days=CHUNK_DAYS[timeframe])
    written = 0
    cursor = from_dt
    while cursor < to_dt:
        window_end = min(cursor + chunk, to_dt)
        try:
            rows = await _paced_candles(exchange, token, resolution, cursor, window_end)
        except Exception as exc:  # noqa: BLE001 — one window must not kill the backfill
            _LAST_ERRORS[f"{symbol}/{timeframe}"] = str(exc)[:200]
            logger.warning("[trending_stocks] %s %s %s->%s fetch failed: %s", symbol,
                           timeframe, cursor.date(), window_end.date(), exc)
            cursor = window_end
            continue
        _LAST_ERRORS.pop(f"{symbol}/{timeframe}", None)
        ops = _rows_to_ops(symbol, timeframe, rows, KEEP_BARS[timeframe])
        if ops:
            await bars_collection.bulk_write(ops, ordered=False)
            written += len(ops)
        cursor = window_end
    return written


async def _latest_ts(symbol: str, timeframe: str) -> datetime | None:
    doc = await bars_collection.find_one({"symbol": symbol, "timeframe": timeframe},
                                         {"ts": 1}, sort=[("ts", -1)])
    if not doc:
        return None
    ts = doc.get("ts")
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return None
    if ts is not None and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


async def refresh_symbol(symbol: str, inst: dict, full: bool = False) -> dict[str, int]:
    """Every native interval for one symbol. `full=True` reaches back the whole window;
    otherwise only what is missing since the last stored bar."""
    out: dict[str, int] = {}
    for tf in NATIVE:
        since = None if full else await _latest_ts(symbol, tf)
        try:
            out[tf] = await fetch_timeframe(symbol, inst, tf, since)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[trending_stocks] %s %s refresh failed: %s", symbol, tf, exc)
            out[tf] = -1
    return out


async def refresh_many(symbols: dict[str, dict], full: bool = False) -> dict:
    """Refresh a whole basket, plus the benchmark. Paced end to end."""
    written: dict[str, dict[str, int]] = {}
    for sym, inst in symbols.items():
        written[sym] = await refresh_symbol(sym, inst, full=full)
    bench = await refresh_benchmark(full=full)
    return {"symbols": written, "benchmark": bench,
            "errors": dict(_LAST_ERRORS), "full": full}


async def refresh_benchmark(full: bool = False) -> dict[str, int]:
    inst = await resolve_instrument(BENCHMARK_SYMBOL)
    if inst is None:
        return {"error": -1}
    return await refresh_symbol(BENCHMARK_SYMBOL, inst, full=full)


# --------------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------------


async def load_bars(symbol: str, timeframe: str, limit: int):
    """Bars for (symbol, timeframe). Native intervals come from the store; 30m/45m/4h are
    resampled from their parent on the NSE 09:15 anchor.

    Delegates to the factory's equity source so there is one implementation of the
    resampling rule in the app rather than two that can disagree about where a session
    starts."""
    return await equity_load_bars(symbol, timeframe, limit)


async def load_benchmark(timeframe: str, limit: int):
    return await equity_load_bars(BENCHMARK_SYMBOL, timeframe, limit)


async def coverage(symbols: list[str]) -> dict[str, dict[str, dict]]:
    """Bars held per (symbol, timeframe), with first/last timestamps.

    Derived timeframes report their PARENT's count, because that is what actually limits
    them — advertising 45m coverage a 15m store cannot support would be the same lie in a
    different place. What a page does with this is show a data gap, never silence."""
    out: dict[str, dict[str, dict]] = {}
    for sym in symbols:
        per_tf: dict[str, dict] = {}
        for tf in NATIVE:
            pipeline = [{"$match": {"symbol": sym, "timeframe": tf}},
                        {"$group": {"_id": None, "n": {"$sum": 1},
                                    "first": {"$min": "$ts"}, "last": {"$max": "$ts"}}}]
            row = None
            async for r in bars_collection.aggregate(pipeline):
                row = r
            per_tf[tf] = {
                "bars": (row or {}).get("n", 0),
                "first": _iso((row or {}).get("first")),
                "last": _iso((row or {}).get("last")),
                "native": True,
                "error": _LAST_ERRORS.get(f"{sym}/{tf}"),
            }
        for tf, parent in DERIVED_FROM.items():
            p = per_tf.get(parent, {})
            factor = TF_MINUTES[tf] // TF_MINUTES[parent]
            per_tf[tf] = {"bars": p.get("bars", 0) // max(factor, 1),
                          "first": p.get("first"), "last": p.get("last"),
                          "native": False, "derived_from": parent,
                          "error": p.get("error")}
        out[sym] = {tf: per_tf[tf] for tf in TIMEFRAMES if tf in per_tf}
    return out


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        return v.astimezone(timezone.utc).isoformat()
    except (AttributeError, ValueError):
        return None


async def last_close(symbol: str) -> float | None:
    doc = await bars_collection.find_one({"symbol": symbol, "timeframe": "1d"},
                                         {"close": 1}, sort=[("ts", -1)])
    return float(doc["close"]) if doc and doc.get("close") else None


async def quote_sanity(symbol: str, ltp: float | None) -> tuple[bool, str]:
    """Is this live price consistent with the bars the strategies are reading?

    The cross-sectional and structural families gate on BAR statistics but fill at the
    LIVE price, so those two must describe the same instrument. Returns (ok, reason) and
    the reason is stored on the rejection — a quarantined symbol should say why."""
    if ltp is None or ltp <= 0:
        return False, "no live quote available"
    close = await last_close(symbol)
    if close is None or close <= 0:
        return True, "no stored close to compare against"
    dev = abs(ltp - close) / close * 100
    if dev > MAX_QUOTE_DEVIATION_PCT:
        return False, (f"live {ltp:,.2f} is {dev:.1f}% from the last stored close "
                       f"{close:,.2f} — corporate action or bad tick, not a move")
    return True, f"live quote {dev:.2f}% from the last close"


__all__ = ["TIMEFRAMES", "NATIVE", "DERIVED_FROM", "BENCHMARK_SYMBOL", "INDICES",
           "NSE_SESSION_OPEN", "resolve_instrument", "refresh_symbol", "refresh_many",
           "refresh_benchmark", "load_bars", "load_benchmark", "coverage", "last_close",
           "quote_sanity", "is_market_open", "resample", "MAX_QUOTE_DEVIATION_PCT"]
