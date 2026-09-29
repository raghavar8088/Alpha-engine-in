"""Delta gold bar store — the data floor under the Gold Desk's dollar tab.

WHAT IT PULLS
-------------
Two perpetual futures on gold-backed TOKENS, from Delta's public market-data API:

    XAUTUSD   Tether Gold Token Perpetual   ~$700m turnover
    PAXGUSD   PAX Gold Token Perpetual      ~$135m turnover

No keys. `/v2/history/candles` and `/v2/tickers` are open endpoints, which is why this
desk can exist in an app that holds no Delta credentials and never will — it reads a
public price and trades it on paper.

THESE ARE NOT XAU/USD, AND NOT MCX GOLD
---------------------------------------
XAUT and PAXG are tokens redeemable for a troy ounce. They track spot gold closely and
they are the only gold this venue can fill, but the basis between them is real: measured
$2.49 apart on the same ounce while this was written, and the desk they came from has
seen $15. Neither is MCX gold, which carries Indian import duty and GST and is quoted in
rupees per 10 grams. The two tabs of this desk are therefore two different instruments
that happen to be the same metal — never averaged, never netted.

A SEPARATE STORE FROM `commodity_bars`, ON PURPOSE
--------------------------------------------------
Not because the schema differs — it does not — but because the SESSION does. Every
intraday bucket in the commodity store is anchored to the MCX open at 09:00 IST, and
every `prior_session_break` / `opening_range` / `pivot` template reads `bar.ts.date()` to
decide what "today's session" was. A 24/7 venue has no 09:00, so bars anchored that way
would hand those templates a session boundary in the middle of active trading and an
opening range that is just wherever the clock happened to be. Here the day is the UTC
day, the anchor is UTC midnight, and bars are carried in UTC for exactly that reason.

WHAT IS NATIVE AND WHAT IS DERIVED
----------------------------------
Delta serves 1m/5m/15m/30m/1h/4h/1d natively — more than Angel does, so only 45m has to
be resampled here (from 15m). That is one derived series against the commodity store's
three, and a derived series is the one that can drift, so fewer is better.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.core.db import gold_bars_collection, gold_state_collection

logger = logging.getLogger("gold_delta_feed")

BASE_URL = os.getenv("DELTA_API_BASE_URL", "https://api.india.delta.exchange").rstrip("/")

# The two gold token perpetuals. Silver (SLVONUSD) is listed on the same venue and
# deliberately left out: this desk was asked for gold, and a second metal would turn every
# result into a question about which metal rather than about the strategy.
SYMBOLS: list[str] = [
    s.strip().upper() for s in os.getenv("GOLD_DELTA_SYMBOLS", "XAUTUSD,PAXGUSD").split(",")
    if s.strip()
]

# label -> (Delta resolution, minutes). None = derived here by resampling.
TIMEFRAMES: dict[str, tuple[str | None, int]] = {
    "1m": ("1m", 1),
    "5m": ("5m", 5),
    "15m": ("15m", 15),
    "30m": ("30m", 30),
    "45m": (None, 45),      # Delta has no 45m — derived from 15m
    "1h": ("1h", 60),
    "4h": ("4h", 240),
    "1d": ("1d", 1440),
}
NATIVE_TIMEFRAMES = {tf: res for tf, (res, _m) in TIMEFRAMES.items() if res}
DERIVED_FROM = {"45m": "15m"}

# History per native interval, and how many bars to keep. Sized so the slowest pattern in
# the library (a 60-bar rounding formation) always has its bars on every timeframe.
FETCH_DAYS = {"1m": 4, "5m": 10, "15m": 30, "30m": 60, "1h": 90, "4h": 240, "1d": 500}
KEEP_BARS = {"1m": 3000, "5m": 1500, "15m": 1200, "30m": 1000, "1h": 900, "4h": 700, "1d": 600}

# Pacing. Delta's public endpoints are far more forgiving than Angel's candle API, but a
# poller that hammers a free endpoint is how a free endpoint stops being available, and a
# full pass is only 2 symbols x 7 intervals = 14 requests either way.
REQUEST_MIN_INTERVAL_S = float(os.getenv("GOLD_DELTA_REQUEST_INTERVAL_S", "0.4"))
REQUEST_TIMEOUT_S = float(os.getenv("GOLD_DELTA_TIMEOUT_S", "20"))
MAX_RETRIES = int(os.getenv("GOLD_DELTA_RETRIES", "3"))
BACKOFF_S = float(os.getenv("GOLD_DELTA_BACKOFF_S", "2.0"))

_last_call_at = 0.0
_call_lock = asyncio.Lock()
_LAST_ERRORS: dict[str, str] = {}


class Bar:
    """Minimal OHLCV bar, carried in UTC.

    The same shape as `commodity_bars.Bar` rather than an import of it, because the two
    stores disagree about what a day is and a shared class would invite sharing the
    resampler too. Duplicating six slots is cheaper than a bar that silently belongs to
    the wrong session."""

    __slots__ = ("ts", "open", "high", "low", "close", "volume")

    def __init__(self, ts: datetime, o: float, h: float, l: float, c: float, v: float):
        self.ts, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, v

    def __repr__(self) -> str:
        return f"Bar({self.ts:%Y-%m-%d %H:%M}Z o={self.open} h={self.high} l={self.low} c={self.close})"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_market_open(_now_utc: datetime | None = None) -> bool:
    """Always true. Perpetual futures do not close — no weekend, no holiday, no session.

    A function rather than a constant so the desk code reads the same on both venues and
    the Gold Desk's MCX leg can be the one that says no."""
    return True


# ── the venue ────────────────────────────────────────────────────────────────────


async def _get(path: str, params: dict) -> dict:
    """One paced GET against Delta's public API."""
    global _last_call_at
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        async with _call_lock:
            wait = REQUEST_MIN_INTERVAL_S - (time.monotonic() - _last_call_at)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call_at = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
                r = await client.get(f"{BASE_URL}{path}", params=params,
                                     headers={"Accept": "application/json"})
            if r.status_code == 429:
                raise RuntimeError("rate limited (HTTP 429)")
            r.raise_for_status()
            body = r.json()
            if not body.get("success", True):
                raise RuntimeError(f"delta reported failure: {str(body)[:180]}")
            return body
        except Exception as exc:                       # noqa: BLE001 - retried, then reported
            last_err = exc
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BACKOFF_S * (attempt + 1))
    raise RuntimeError(str(last_err))


# Product specs, fetched once and cached for the process.
#
# `contract_value` and `taker_commission_rate` are per PRODUCT and they are not what a
# crypto perpetual charges: gold takes 0.01% a side against Bitcoin's 0.05%. The desk this
# module was ported from hardcoded one crypto rate and charged it on gold — 5.9x the real
# fee, on a book whose whole question is whether an edge survives its costs. So the rate
# is read from the venue rather than written down here.
_PRODUCTS: dict[str, dict] = {}


async def product(symbol: str) -> dict:
    """Contract value, tick size and the venue's own commission rates for one symbol."""
    symbol = symbol.upper()
    if symbol in _PRODUCTS:
        return _PRODUCTS[symbol]
    body = await _get(f"/v2/products/{symbol}", {})
    r = body.get("result") or {}
    spec = {
        "symbol": symbol,
        "description": r.get("description") or symbol,
        # How much metal one contract is. 0.001 oz on both gold perps.
        "contract_value": float(r.get("contract_value") or 0) or 0.001,
        "contract_unit": r.get("contract_unit_currency") or symbol.replace("USD", ""),
        "tick_size": float(r.get("tick_size") or 0.01),
        "taker_fee_rate": float(r.get("taker_commission_rate") or 0.0),
        "maker_fee_rate": float(r.get("maker_commission_rate") or 0.0),
    }
    _PRODUCTS[symbol] = spec
    return spec


async def mark_price(symbol: str) -> float | None:
    """The venue's own mark for this perpetual — what an open position is worth now."""
    try:
        body = await _get(f"/v2/tickers/{symbol.upper()}", {})
    except Exception as exc:                            # noqa: BLE001
        _LAST_ERRORS[f"{symbol}:ticker"] = str(exc)[:200]
        return None
    r = body.get("result") or {}
    for key in ("mark_price", "close", "spot_price"):
        v = r.get(key)
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


async def fetch_candles(symbol: str, resolution: str, days: float) -> list[Bar]:
    """One native series, oldest first.

    Delta returns candles NEWEST FIRST. Reversing is not cosmetic: every pattern in the
    library indexes `bars[-1]` as the most recent bar, so a series left in the venue's
    order would have each template reading history backwards and reporting a breakout for
    what was actually a collapse."""
    end = int(time.time())
    start = end - int(days * 86400)
    body = await _get("/v2/history/candles",
                      {"resolution": resolution, "symbol": symbol.upper(),
                       "start": start, "end": end})
    rows = body.get("result") or []
    out: list[Bar] = []
    for c in rows:
        try:
            ts = datetime.fromtimestamp(int(c["time"]), tz=timezone.utc)
            out.append(Bar(ts, float(c["open"]), float(c["high"]), float(c["low"]),
                           float(c["close"]), float(c.get("volume") or 0)))
        except (KeyError, TypeError, ValueError):
            continue                      # one malformed candle costs one candle
    out.sort(key=lambda b: b.ts)
    return out


# ── the store ────────────────────────────────────────────────────────────────────


async def refresh_symbol(symbol: str) -> dict[str, int]:
    """Refresh every NATIVE interval for one symbol. -1 means that interval failed."""
    from pymongo import UpdateOne

    result: dict[str, int] = {}
    for tf, res in NATIVE_TIMEFRAMES.items():
        try:
            bars = await fetch_candles(symbol, res, FETCH_DAYS.get(tf, 30))
            _LAST_ERRORS.pop(f"{symbol}:{tf}", None)
        except Exception as exc:                        # noqa: BLE001
            _LAST_ERRORS[f"{symbol}:{tf}"] = str(exc)[:200]
            result[tf] = -1
            continue
        keep = KEEP_BARS.get(tf, 600)
        bars = bars[-keep:]
        ops = [
            UpdateOne(
                {"symbol": symbol, "timeframe": tf, "ts": b.ts},
                {"$set": {"open": b.open, "high": b.high, "low": b.low,
                          "close": b.close, "volume": b.volume,
                          "venue": "DELTA", "updated_at": _now()}},
                upsert=True,
            )
            for b in bars
        ]
        if ops:
            await gold_bars_collection.bulk_write(ops, ordered=False)
        result[tf] = len(bars)
    return result


async def refresh_all() -> dict:
    """One full pass: 2 symbols x 7 native intervals, ~6s at the default pacing."""
    started = time.monotonic()
    detail = {sym: await refresh_symbol(sym) for sym in SYMBOLS}
    failed = sum(1 for tfs in detail.values() for v in tfs.values() if v < 0)
    outcome = {
        "symbols": len(SYMBOLS), "seconds": round(time.monotonic() - started, 1),
        "failed_fetches": failed, "detail": detail, "errors": dict(_LAST_ERRORS),
        "finished_at": _now(), "pacing_seconds": REQUEST_MIN_INTERVAL_S,
    }
    # Written to state for the same reason the commodity store does it: this module's
    # logger does not reach uvicorn's handlers in the deployed image, so a throttled or
    # failing refresh would otherwise show up only as "no signals today".
    await gold_state_collection.update_one({"_id": "delta_bars"}, {"$set": outcome}, upsert=True)
    return outcome


def resample(bars: list[Bar], minutes: int) -> list[Bar]:
    """Aggregate into `minutes` buckets anchored to UTC MIDNIGHT.

    Midnight, not a session open, because this venue has no session. 1440 divides evenly
    by 45, so every bucket is a full 45 minutes and there is no stub bar anywhere in the
    day — which is precisely what anchoring to an arbitrary hour would create, and what a
    range or volatility template would then fire on at the same time every day."""
    if not bars or minutes <= 0:
        return []
    buckets: dict[tuple, list[Bar]] = {}
    for b in bars:
        day_start = b.ts.replace(hour=0, minute=0, second=0, microsecond=0)
        offset = int((b.ts - day_start).total_seconds() // 60)
        buckets.setdefault((b.ts.date(), offset // minutes), []).append(b)

    out: list[Bar] = []
    for (day, idx) in sorted(buckets):
        group = buckets[(day, idx)]
        start = group[0].ts.replace(hour=0, minute=0, second=0, microsecond=0) + \
            timedelta(minutes=idx * minutes)
        out.append(Bar(start, group[0].open,
                       max(g.high for g in group), min(g.low for g in group),
                       group[-1].close, sum(g.volume for g in group)))
    return out


async def load_bars(symbol: str, timeframe: str, limit: int = 400) -> list[Bar]:
    """Bars for (symbol, timeframe), oldest first, in UTC."""
    if timeframe in DERIVED_FROM:
        parent = DERIVED_FROM[timeframe]
        factor = max(TIMEFRAMES[timeframe][1] // TIMEFRAMES[parent][1], 1)
        src = await load_bars(symbol, parent, limit * factor + factor)
        return resample(src, TIMEFRAMES[timeframe][1])[-limit:]

    docs = [d async for d in gold_bars_collection.find(
        {"symbol": symbol, "timeframe": timeframe}).sort("ts", -1).limit(limit)]
    docs.reverse()
    out: list[Bar] = []
    for d in docs:
        ts = d["ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        out.append(Bar(ts.astimezone(timezone.utc), d["open"], d["high"], d["low"],
                       d["close"], d.get("volume") or 0))
    return out


async def coverage() -> dict:
    """Bar counts per (symbol, timeframe) — the diagnostic that makes a starved store
    visible instead of letting it read as a quiet market."""
    rows: dict[str, dict[str, int]] = {}
    latest: dict[str, str | None] = {}
    async for r in gold_bars_collection.aggregate(
            [{"$group": {"_id": {"s": "$symbol", "t": "$timeframe"},
                         "n": {"$sum": 1}, "last": {"$max": "$ts"}}}]):
        s, t = r["_id"]["s"], r["_id"]["t"]
        rows.setdefault(s, {})[t] = r["n"]
        ts = r.get("last")
        if ts is not None:
            iso = (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).isoformat()
            if s not in latest or (latest[s] or "") < iso:
                latest[s] = iso
    last = await gold_state_collection.find_one({"_id": "delta_bars"}) or {}
    last.pop("_id", None)
    if isinstance(last.get("finished_at"), datetime):
        last["finished_at"] = last["finished_at"].isoformat()
    return {
        "venue": "DELTA", "symbols": SYMBOLS,
        "timeframes": list(TIMEFRAMES), "native": list(NATIVE_TIMEFRAMES),
        "derived": DERIVED_FROM, "bars": rows, "last_bar_at": latest, "last_refresh": last,
    }
