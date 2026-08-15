"""Commodity bar store — the data floor under the Commodity Trading module.

WHY A STORE AND NOT DIRECT CALLS
---------------------------------
Angel's candle endpoint rate-limits far harder than its quote endpoint: eight
back-to-back candle requests measured 5 x HTTP 403 in 0.6 seconds. The Commodity desk
runs 312 strategies over 8 symbols and 8 timeframes, so anything that reached for Angel
inside a strategy loop would be throttled into uselessness within one cycle. Instead a
paced poller writes bars into Mongo (`commodity_bars`) and every strategy reads from
there. The rate limit is then a property of ONE background task, not of the desk.

ONLY NATIVE INTERVALS ARE STORED
---------------------------------
Angel serves 1 / 5 / 15 / 60 minute and daily candles — there is no 30m, 45m or 4h.
Those three are derived by resampling on read (30m and 45m from 15m, 4h from 1h) rather
than stored, so a derived series can never drift out of step with the native one it came
from, and a change to the bucketing rule needs no migration.

Buckets are anchored to the MCX session open (09:00 IST), not to midnight. A 45-minute
bar anchored to midnight would cut the session at 09:00-09:15, leaving a stub bar every
day whose range is a third of the others — enough to fire range/volatility patterns
spuriously at exactly the same time each morning.
"""

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone

from app.core.db import (
    commodity_bars_collection,
    commodity_state_collection,
    instruments_collection,
)
from app.services.angel_client import AngelAPIError, angel_client

logger = logging.getLogger("commodity_bars")

IST = timezone(timedelta(hours=5, minutes=30))

# MCX runs one long session; every intraday bucket is measured from this.
SESSION_OPEN_HHMM = (9, 0)
SESSION_CLOSE_HHMM = (23, 30)

LIQUID_UNDERLYINGS = [
    u.strip().upper() for u in os.getenv(
        "COMMODITY_UNDERLYINGS", "GOLD,GOLDM,SILVER,SILVERM,CRUDEOIL,NATURALGAS,COPPER,ZINC"
    ).split(",") if u.strip()
]

# label -> (angel resolution key, minutes). None resolution = derived by resampling.
TIMEFRAMES: dict[str, tuple[str | None, int]] = {
    "1m": ("1", 1),
    "5m": ("5", 5),
    "15m": ("15", 15),
    "30m": (None, 30),     # from 15m
    "45m": (None, 45),     # from 15m
    "1h": ("60", 60),
    "4h": (None, 240),     # from 1h
    "1d": ("D", 1440),
}
NATIVE_TIMEFRAMES = {tf: res for tf, (res, _m) in TIMEFRAMES.items() if res}
DERIVED_FROM = {"30m": "15m", "45m": "15m", "4h": "1h"}

# How much history to pull per native interval, and how many bars to keep. Sized so the
# slowest pattern (a 60-bar rounding formation) always has enough bars on every timeframe.
FETCH_DAYS = {"1m": 4, "5m": 10, "15m": 30, "1h": 90, "1d": 500}
KEEP_BARS = {"1m": 3000, "5m": 1500, "15m": 1200, "1h": 900, "1d": 600}

# Pacing for the candle endpoint. Measured: 8 unpaced calls -> 5 x 403. This is the one
# knob that decides whether the poller works at all, so it is deliberately conservative.
CANDLE_MIN_INTERVAL_S = float(os.getenv("COMMODITY_CANDLE_INTERVAL_S", "3.0"))
CANDLE_MAX_RETRIES = int(os.getenv("COMMODITY_CANDLE_RETRIES", "4"))
CANDLE_BACKOFF_S = float(os.getenv("COMMODITY_CANDLE_BACKOFF_S", "6.0"))

_last_call_at = 0.0
_call_lock = asyncio.Lock()
_LAST_ERRORS: dict[str, str] = {}


class Bar:
    """Minimal OHLCV bar. Deliberately not the shared `tradingai_shared.domain.Bar`,
    which is a pydantic model carrying a Timeframe enum this module has no member for
    (30m/45m/4h do not exist there)."""

    __slots__ = ("ts", "open", "high", "low", "close", "volume")

    def __init__(self, ts: datetime, o: float, h: float, l: float, c: float, v: float):
        self.ts, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, v

    def __repr__(self) -> str:
        return f"Bar({self.ts:%Y-%m-%d %H:%M} o={self.open} h={self.high} l={self.low} c={self.close})"


def _now_ist() -> datetime:
    return datetime.now(IST)


def is_market_open(now: datetime | None = None) -> bool:
    now = now or _now_ist()
    if now.weekday() >= 5:
        return False
    hhmm = now.strftime("%H:%M")
    return f"{SESSION_OPEN_HHMM[0]:02d}:{SESSION_OPEN_HHMM[1]:02d}" <= hhmm <= \
           f"{SESSION_CLOSE_HHMM[0]:02d}:{SESSION_CLOSE_HHMM[1]:02d}"


async def front_month_universe() -> dict[str, dict]:
    """One front-month future per liquid underlying — the tradable set.

    Nearest unexpired expiry wins. Expired contracts are excluded explicitly because the
    instrument master keeps months of history and sorting by expiry ascending otherwise
    hands back contracts that stopped trading weeks ago."""
    today = date.today().isoformat()
    out: dict[str, dict] = {}
    async for d in instruments_collection.find({
        "asset_class": "COMMODITY_FUTURE",
        "expiry": {"$gte": today},
        "underlying_symbol": {"$in": LIQUID_UNDERLYINGS},
        "angel_token": {"$ne": None},
    }):
        u = d["underlying_symbol"]
        if u not in out or (d.get("expiry") or "9999") < (out[u].get("expiry") or "9999"):
            out[u] = d
    return out


async def _paced_candles(exchange: str, token: str, resolution: str, days: int) -> list[list]:
    """One candle request, globally paced and retried on throttling."""
    global _last_call_at
    to_dt = _now_ist()
    from_dt = to_dt - timedelta(days=days)
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
                from_dt.strftime("%Y-%m-%d %H:%M"), to_dt.strftime("%Y-%m-%d %H:%M"),
            )
        except AngelAPIError as exc:
            last_err = exc
            # 403 here means throttled, not forbidden — Angel returns a non-JSON 403 body
            # when the candle quota is exceeded. Back off and try again.
            await asyncio.sleep(CANDLE_BACKOFF_S * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            break
    raise last_err or RuntimeError("candle fetch failed")


def _parse(rows: list[list]) -> list[Bar]:
    out: list[Bar] = []
    for r in rows or []:
        try:
            ts = datetime.fromisoformat(r[0])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            out.append(Bar(ts.astimezone(IST), float(r[1]), float(r[2]), float(r[3]),
                           float(r[4]), float(r[5] or 0)))
        except (TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda b: b.ts)
    return out


async def refresh_symbol(symbol: str, inst: dict) -> dict:
    """Pull every NATIVE interval for one contract and upsert into the store."""
    exchange = inst.get("angel_exchange") or "MCX"
    token = str(inst["angel_token"])
    result: dict[str, int] = {}
    for tf, resolution in NATIVE_TIMEFRAMES.items():
        try:
            rows = await _paced_candles(exchange, token, resolution, FETCH_DAYS[tf])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[commodity_bars] %s %s fetch failed: %s", symbol, tf, exc)
            result[tf] = -1
            _LAST_ERRORS[f"{symbol}/{tf}"] = str(exc)[:160]
            continue
        _LAST_ERRORS.pop(f"{symbol}/{tf}", None)
        bars = _parse(rows)[-KEEP_BARS[tf]:]
        if not bars:
            result[tf] = 0
            continue
        ops = []
        from pymongo import UpdateOne

        for b in bars:
            ops.append(UpdateOne(
                {"symbol": symbol, "timeframe": tf, "ts": b.ts},
                {"$set": {"symbol": symbol, "timeframe": tf, "ts": b.ts,
                          "open": b.open, "high": b.high, "low": b.low,
                          "close": b.close, "volume": b.volume,
                          "security_id": str(inst.get("security_id")),
                          "expiry": inst.get("expiry"), "updated_at": datetime.now(timezone.utc)}},
                upsert=True,
            ))
        if ops:
            await commodity_bars_collection.bulk_write(ops, ordered=False)
        result[tf] = len(bars)
    return result


async def refresh_all() -> dict:
    """Refresh every symbol's native intervals. Paced end to end — a full pass is
    8 symbols x 5 intervals = 40 requests, ~60s at the default interval."""
    universe = await front_month_universe()
    if not universe:
        return {"symbols": 0, "note": "No unexpired MCX front-month futures with an Angel token on file."}
    started = time.monotonic()
    detail = {}
    for symbol, inst in universe.items():
        detail[symbol] = await refresh_symbol(symbol, inst)
    failed = sum(1 for tfs in detail.values() for v in tfs.values() if v < 0)
    outcome = {
        "symbols": len(universe), "seconds": round(time.monotonic() - started, 1),
        "failed_fetches": failed, "detail": detail,
        "errors": dict(_LAST_ERRORS),
        "finished_at": datetime.now(timezone.utc),
        "pacing_seconds": CANDLE_MIN_INTERVAL_S,
    }
    # Written to state because the module logger does not reach uvicorn's handlers in this
    # image: a throttled refresh was leaving four symbols empty with nothing anywhere to
    # say so. The API is now the place that tells you.
    await commodity_state_collection.update_one(
        {"_id": "commodity_bars"}, {"$set": outcome}, upsert=True)
    return outcome


def _session_open(ts: datetime) -> datetime:
    return ts.replace(hour=SESSION_OPEN_HHMM[0], minute=SESSION_OPEN_HHMM[1],
                      second=0, microsecond=0)


def resample(bars: list[Bar], minutes: int) -> list[Bar]:
    """Aggregate into `minutes` buckets anchored to the 09:00 session open.

    A bar belongs to bucket floor(minutes_since_session_open / minutes) of its own
    trading date. Anchoring to the session (not midnight) is what stops a permanent
    stub bar at the open on 45m and 4h."""
    if not bars or minutes <= 0:
        return []
    buckets: dict[tuple, list[Bar]] = {}
    for b in bars:
        so = _session_open(b.ts)
        offset = int((b.ts - so).total_seconds() // 60)
        if offset < 0:  # pre-open print — keep it in the first bucket rather than dropping data
            offset = 0
        key = (b.ts.date(), offset // minutes)
        buckets.setdefault(key, []).append(b)

    out: list[Bar] = []
    for (day, idx) in sorted(buckets):
        group = buckets[(day, idx)]
        start = _session_open(group[0].ts) + timedelta(minutes=idx * minutes)
        out.append(Bar(
            start, group[0].open,
            max(g.high for g in group), min(g.low for g in group),
            group[-1].close, sum(g.volume for g in group),
        ))
    return out


async def load_bars(symbol: str, timeframe: str, limit: int = 400) -> list[Bar]:
    """Bars for (symbol, timeframe) — read from the store for native intervals,
    resampled from the parent interval for 30m / 45m / 4h."""
    if timeframe in DERIVED_FROM:
        parent = DERIVED_FROM[timeframe]
        factor = TIMEFRAMES[timeframe][1] // TIMEFRAMES[parent][1]
        src = await load_bars(symbol, parent, limit * factor + factor)
        return resample(src, TIMEFRAMES[timeframe][1])[-limit:]

    docs = [
        d async for d in commodity_bars_collection.find(
            {"symbol": symbol, "timeframe": timeframe}
        ).sort("ts", -1).limit(limit)
    ]
    docs.reverse()
    out = []
    for d in docs:
        ts = d["ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        out.append(Bar(ts.astimezone(IST), d["open"], d["high"], d["low"], d["close"], d.get("volume") or 0))
    return out


async def coverage() -> dict:
    """Bar counts per (symbol, timeframe) — the diagnostic that makes a starved store
    visible instead of showing up as "no signals today"."""
    rows: dict[str, dict[str, int]] = {}
    pipeline = [{"$group": {"_id": {"s": "$symbol", "t": "$timeframe"}, "n": {"$sum": 1},
                            "last": {"$max": "$ts"}}}]
    latest: dict[str, str | None] = {}
    async for r in commodity_bars_collection.aggregate(pipeline):
        s, t = r["_id"]["s"], r["_id"]["t"]
        rows.setdefault(s, {})[t] = r["n"]
        ts = r.get("last")
        if ts is not None:
            iso = (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(IST).isoformat()
            if s not in latest or (latest[s] or "") < iso:
                latest[s] = iso
    last = await commodity_state_collection.find_one({"_id": "commodity_bars"}) or {}
    last.pop("_id", None)
    if last.get("finished_at") is not None:
        last["finished_at"] = last["finished_at"].isoformat()
    return {
        "last_refresh": last,
        "symbols": sorted(rows),
        "native_timeframes": sorted(NATIVE_TIMEFRAMES),
        "derived_timeframes": sorted(DERIVED_FROM),
        "bars": rows,
        "latest_bar_ist": latest,
    }
