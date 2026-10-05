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
        # CRUDEOILM and NATGASMINI are here for the bars, not for the pattern desk's sake:
        # the Pre-Live Commodity desk trades those two and reads THIS store, and a symbol
        # absent from here has no candles for anything to evaluate. They cost 2 more symbols
        # x 5 native intervals on an already-paced poller (~15s), which is the cheap half of
        # the trade; the alternative was a second poller against an endpoint that 403s.
        "COMMODITY_UNDERLYINGS",
        "GOLD,GOLDM,SILVER,SILVERM,CRUDEOIL,NATURALGAS,COPPER,ZINC,CRUDEOILM,NATGASMINI"
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
    """MCX's own calendar: two sessions, holidays that shut only the morning, and the
    23:30 / 23:55 close that follows US daylight saving. The old test was weekday + a fixed
    09:00-23:30 window, which traded the whole of 2026-10-02 (both sessions shut) on a
    frozen quote and missed 23:30-23:55 every winter evening."""
    from tradingai_shared.mcx_calendar import is_open

    return is_open(now or _now_ist())


async def front_month_universe() -> dict[str, dict]:
    """One contract per liquid underlying — the one NEW entries go to.

    Not simply the nearest expiry: a contract inside its exit window (the delivery tender
    days for bullion and base metals, the last two sessions for energy) is skipped, so the
    desk rolls to the next month before delivery rather than trading into it. The rules
    live in `mcx_market`; positions already open are priced on their OWN contract there."""
    from app.services.mcx_market import tradable_universe

    return await tradable_universe(LIQUID_UNDERLYINGS)


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

        # KEYED BY CONTRACT. The key used to be (symbol, timeframe, ts), so every pass
        # rewrote the whole fetched window with whatever was front month that day: a bar
        # dated in September came to carry October's price, and a roll silently spliced two
        # contracts with no adjustment. With the expiry in the key each contract keeps its
        # own history, and `load_bars` joins them with a ratio adjustment at the overlap.
        for b in bars:
            ops.append(UpdateOne(
                {"symbol": symbol, "timeframe": tf, "expiry": inst.get("expiry"), "ts": b.ts},
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


def bar_end(b: Bar, minutes: int) -> datetime:
    """When a bar stops changing. Intraday: its start plus its length, but never past the
    session close (the last 4h bucket of an evening ends at 23:30, not 01:00). Daily: the
    close of that date's last session."""
    from tradingai_shared.mcx_calendar import session_close

    day_close = datetime.combine(b.ts.date(), session_close(b.ts.date()), IST)
    if minutes >= 1440:
        return day_close
    return min(b.ts + timedelta(minutes=minutes), day_close)


def drop_forming(bars: list[Bar], minutes: int, now: datetime | None = None) -> list[Bar]:
    """Remove trailing bars that have not closed yet.

    Angel returns the bar still being built, and its high, low and close move until it
    ends. A pattern evaluated on it can fire, disappear and fire again inside one bar — and
    on 1d the "signal bar" was today's half-made candle for the whole session."""
    now = now or _now_ist()
    while bars and bar_end(bars[-1], minutes) > now:
        bars = bars[:-1]
    return bars


def _continuous(docs: list[dict], prefer_expiry: str | None = None) -> tuple[list[Bar], dict]:
    """Join per-contract bars into one back-adjusted series, newest contract first.

    Walking back in time, the series stays on the newest contract for as long as it has
    bars. Where it runs out, it steps to the next-older contract, scaled by the ratio of the
    two contracts' closes at the most recent time BOTH printed — the standard ratio
    back-adjustment, so a 1.8% calendar spread is not read as a 1.8% move. When the two
    never overlap (history written before the store was keyed by contract), the join is
    left unadjusted and counted in `info["unadjusted_joins"]`."""
    by_ts: dict[datetime, dict[str, dict]] = {}
    for d in docs:
        ts = d["ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        by_ts.setdefault(ts, {})[str(d.get("expiry") or "")] = d
    ts_desc = sorted(by_ts, reverse=True)
    info = {"contracts": [], "adjusted_joins": 0, "unadjusted_joins": 0}
    if not ts_desc:
        return [], info
    newest = by_ts[ts_desc[0]]
    cur = prefer_expiry if prefer_expiry in newest else max(newest)
    info["contracts"].append(cur)
    factor = 1.0
    out: list[Bar] = []
    for ts in ts_desc:
        row = by_ts[ts]
        if cur not in row:
            older = sorted((e for e in row if e < cur), reverse=True) or sorted(row)
            nxt = older[0]
            ratio = None
            for t2 in ts_desc:                       # most recent time both printed
                both = by_ts[t2]
                if cur in both and nxt in both and both[nxt].get("close"):
                    ratio = float(both[cur]["close"]) / float(both[nxt]["close"])
                    break
            if ratio and ratio > 0:
                factor *= ratio
                info["adjusted_joins"] += 1
            else:
                info["unadjusted_joins"] += 1
            cur = nxt
            info["contracts"].append(cur)
        d = row[cur]
        out.append(Bar(ts.astimezone(IST), d["open"] * factor, d["high"] * factor, d["low"] * factor,
                       d["close"] * factor, d.get("volume") or 0))
    out.reverse()
    return out, info


_PROJ = {"_id": 0, "ts": 1, "expiry": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
JOIN_OVERLAP_BARS = 20


async def _contract_docs(symbol: str, timeframe: str, limit: int, minutes: int,
                         prefer_expiry: str | None) -> list[dict]:
    """The documents `_continuous` needs and no more: the newest contract's latest `limit`
    bars, then each older contract only for the stretch before that (plus a small overlap
    so the join has a ratio). Reading the newest N documents regardless of contract would
    fail once contracts overlap — daily bars keep ~500 days per contract, so six gold
    contracts would crowd a 250-bar window down to a few dozen distinct days."""
    raw = await commodity_bars_collection.distinct("expiry", {"symbol": symbol, "timeframe": timeframe})
    expiries = sorted((str(e) if e else "" for e in raw), reverse=True)
    if prefer_expiry and prefer_expiry in expiries:
        expiries.remove(prefer_expiry)
        expiries.insert(0, prefer_expiry)
    docs: list[dict] = []
    seen: set = set()
    boundary: datetime | None = None
    for e in expiries:
        q: dict = {"symbol": symbol, "timeframe": timeframe, "expiry": e or None}
        if boundary is not None:
            q["ts"] = {"$lte": boundary + timedelta(minutes=minutes * JOIN_OVERLAP_BARS)}
        part = [d async for d in commodity_bars_collection.find(q, _PROJ).sort("ts", -1).limit(limit + JOIN_OVERLAP_BARS)]
        if not part:
            continue
        docs.extend(part)
        for d in part:
            seen.add(d["ts"])
        oldest = min(d["ts"] for d in part)
        boundary = oldest if boundary is None else min(boundary, oldest)
        if len(seen) >= limit + 5:
            break
    return docs


async def load_bars(symbol: str, timeframe: str, limit: int = 400, closed_only: bool = False,
                    prefer_expiry: str | None = None) -> list[Bar]:
    """Bars for (symbol, timeframe) — read from the store for native intervals,
    resampled from the parent interval for 30m / 45m / 4h.

    One continuous, back-adjusted series across contracts (see `_continuous`); the newest
    bars are always the newest contract's own, unadjusted prices. `closed_only` drops the
    bar still forming — what any signal should be computed on."""
    minutes = TIMEFRAMES.get(timeframe, (None, 1440))[1]
    if timeframe in DERIVED_FROM:
        parent = DERIVED_FROM[timeframe]
        factor = TIMEFRAMES[timeframe][1] // TIMEFRAMES[parent][1]
        src = await load_bars(symbol, parent, limit * factor + factor, prefer_expiry=prefer_expiry)
        out = resample(src, minutes)
        if closed_only:
            out = drop_forming(out, minutes)
        return out[-limit:]

    docs = await _contract_docs(symbol, timeframe, limit, minutes, prefer_expiry)
    out, _info = _continuous(docs, prefer_expiry)
    if closed_only:
        out = drop_forming(out, minutes)
    return out[-limit:]


async def last_contract_price(symbol: str, expiry: str, on_or_before: datetime | None = None) -> tuple[float, datetime] | None:
    """The last close the store holds for ONE contract — what an expired position settles
    at. Angel returns nothing for an expired token (no quote, no candles; probed
    2026-10-03 on COPPER/ZINC Sep-30 and NATURALGAS Sep-25), so the store's own bars are
    the only record of where that contract last traded. Any timeframe: the latest bar wins."""
    q: dict = {"symbol": symbol, "expiry": expiry}
    if on_or_before is not None:
        q["ts"] = {"$lte": on_or_before}
    doc = await commodity_bars_collection.find_one(q, {"_id": 0, "close": 1, "ts": 1}, sort=[("ts", -1)])
    if not doc or not doc.get("close"):
        return None
    ts = doc["ts"] if doc["ts"].tzinfo else doc["ts"].replace(tzinfo=timezone.utc)
    return float(doc["close"]), ts


async def ensure_indexes() -> None:
    """The per-contract key. Best-effort: an index is a speed-up, never a precondition."""
    try:
        await commodity_bars_collection.create_index(
            [("symbol", 1), ("expiry", 1), ("ts", -1)], name="cb_symbol_expiry_ts", background=True)
        await commodity_bars_collection.create_index(
            [("symbol", 1), ("timeframe", 1), ("expiry", 1), ("ts", 1)],
            name="cb_symbol_tf_expiry_ts", background=True)
        await commodity_bars_collection.create_index(
            [("symbol", 1), ("timeframe", 1), ("ts", -1)], name="cb_symbol_tf_ts_desc", background=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("commodity_bars indexes skipped: %s", exc)


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
