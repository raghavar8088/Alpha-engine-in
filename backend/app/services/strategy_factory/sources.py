"""Bar sources — how the Strategy Factory reaches every market the app trades.

The 546 strategies are instrument-agnostic: they need only "give me the last N bars of
SYMBOL on TIMEFRAME". This module is the adapter layer that answers that question for
each market, so the SAME library runs on commodities, equities and indices without a
single strategy being duplicated into another module's engine.

WHY ADAPTERS RATHER THAN COPYING THE CATALOG INTO EACH DESK
------------------------------------------------------------
Every existing desk (intraday lab, commodity, NIFTY scalp, momentum, options, ...) has
its own catalog, capital model and engine. Injecting 546 more strategies into each of
them would multiply their capital, force their signal contracts to change, and put a
research library inside desks that are being used to evaluate specific ideas. Adding a
source instead leaves every one of those desks byte-identical while the factory still
covers their market.

HONEST TIMEFRAME COVERAGE
-------------------------
A source only advertises timeframes it can actually serve. The equity store holds deep
DAILY history for ~500 symbols but intraday bars for a handful, so the equity source
reports daily as available and intraday as available-per-symbol; the engine then skips
what it cannot feed rather than evaluating a truncated series and calling the silence a
result.

Session anchors differ per market and are NOT interchangeable: NSE opens 09:15, MCX
09:00. Resampling equities on a 09:00 anchor would put a 15-minute stub at the start of
every session and fire the range patterns on it every single morning.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

from app.core.db import bars_collection, instruments_collection

IST = timezone(timedelta(hours=5, minutes=30))

# label -> (parent timeframe to resample from, minutes). Native ones have parent None.
TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "45m": 45, "1h": 60, "4h": 240, "1d": 1440}
DERIVED_FROM = {"30m": "15m", "45m": "15m", "4h": "1h"}


class Bar:
    __slots__ = ("ts", "open", "high", "low", "close", "volume")

    def __init__(self, ts, o, h, l, c, v):
        self.ts, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, v


def resample(bars: list[Bar], minutes: int, session_open: tuple[int, int]) -> list[Bar]:
    """Aggregate into `minutes` buckets anchored to this market's session open.

    Anchoring to the session rather than midnight is what stops a permanent stub bar at
    the open on 45m and 4h — a bar a third the normal width, appearing at the same time
    every day, which the range and volatility templates would fire on relentlessly."""
    if not bars or minutes <= 0:
        return []
    buckets: dict[tuple, list[Bar]] = {}
    for b in bars:
        so = b.ts.replace(hour=session_open[0], minute=session_open[1], second=0, microsecond=0)
        offset = max(0, int((b.ts - so).total_seconds() // 60))
        buckets.setdefault((b.ts.date(), offset // minutes), []).append(b)

    out: list[Bar] = []
    for (day, idx) in sorted(buckets):
        g = buckets[(day, idx)]
        start = g[0].ts.replace(hour=session_open[0], minute=session_open[1], second=0,
                                microsecond=0) + timedelta(minutes=idx * minutes)
        out.append(Bar(start, g[0].open, max(x.high for x in g), min(x.low for x in g),
                       g[-1].close, sum(x.volume for x in g)))
    return out


def _to_bars(docs: list[dict]) -> list[Bar]:
    out: list[Bar] = []
    for d in docs:
        ts = d.get("ts")
        if isinstance(ts, str):
            # The shared `bars` collection historically stored some rows with a STRING ts.
            # That was migrated, but parse defensively rather than crash a whole sweep on
            # one stale row.
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        try:
            out.append(Bar(ts.astimezone(IST), float(d["open"]), float(d["high"]),
                           float(d["low"]), float(d["close"]), float(d.get("volume") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda b: b.ts)
    return out


# --------------------------------------------------------------------------------
# Equity / index — the shared `bars` collection
# --------------------------------------------------------------------------------

NSE_SESSION_OPEN = (9, 15)
INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}

EQUITY_MIN_DAILY_BARS = int(os.getenv("SF_EQUITY_MIN_BARS", "250"))
EQUITY_MAX_SYMBOLS = int(os.getenv("SF_EQUITY_MAX_SYMBOLS", "120"))


async def equity_load_bars(symbol: str, timeframe: str, limit: int) -> list[Bar]:
    """Bars for an NSE equity. Native timeframes come straight from the store; 30m/45m/4h
    are resampled from their parent on the NSE 09:15 anchor."""
    if timeframe in DERIVED_FROM:
        parent = DERIVED_FROM[timeframe]
        factor = TF_MINUTES[timeframe] // TF_MINUTES[parent]
        src = await equity_load_bars(symbol, parent, limit * factor + factor)
        return resample(src, TF_MINUTES[timeframe], NSE_SESSION_OPEN)[-limit:]

    docs = [d async for d in bars_collection.find(
        {"symbol": symbol, "timeframe": timeframe}).sort("ts", -1).limit(limit)]
    docs.reverse()
    return _to_bars(docs)


async def equity_universe() -> dict[str, dict]:
    """Equities with enough DAILY history to be worth testing.

    Capped by `SF_EQUITY_MAX_SYMBOLS` because 546 strategies x 500 symbols is 273,000
    replays — a sweep measured in days, not hours. The cap takes the deepest histories
    first, which are also the longest-listed and most liquid names."""
    pipeline = [{"$match": {"timeframe": "1d"}},
                {"$group": {"_id": "$symbol", "n": {"$sum": 1}}},
                {"$match": {"n": {"$gte": EQUITY_MIN_DAILY_BARS}}},
                {"$sort": {"n": -1}},
                {"$limit": EQUITY_MAX_SYMBOLS}]
    names = [r["_id"] async for r in bars_collection.aggregate(pipeline)
             if r["_id"] and r["_id"] not in INDICES]
    if not names:
        return {}
    out: dict[str, dict] = {}
    async for d in instruments_collection.find(
            {"asset_class": "EQUITY", "symbol": {"$in": names}}):
        out[d["symbol"]] = {"symbol": d.get("symbol"), "security_id": d.get("security_id"),
                            "exchange_segment": d.get("exchange_segment"),
                            "lot_size": 1, "asset_class": "EQUITY"}
    # A symbol with bars but no instrument row is still testable — bars are all a
    # backtest needs, and dropping it would silently shrink the universe.
    for n in names:
        out.setdefault(n, {"symbol": n, "security_id": None,
                           "exchange_segment": "NSE_EQ", "lot_size": 1,
                           "asset_class": "EQUITY"})
    return out


async def index_load_bars(symbol: str, timeframe: str, limit: int) -> list[Bar]:
    return await equity_load_bars(symbol, timeframe, limit)


async def index_universe() -> dict[str, dict]:
    """The indices themselves — NIFTY and friends, where intraday bars actually exist."""
    have = set(await bars_collection.distinct("symbol", {"timeframe": "1d"}))
    out: dict[str, dict] = {}
    for n in sorted(INDICES & have):
        out[n] = {"symbol": n, "security_id": None, "exchange_segment": "IDX_I",
                  "lot_size": 1, "asset_class": "INDEX"}
    return out


async def available_timeframes(source: str) -> dict[str, int]:
    """How many symbols each timeframe can actually serve, per source.

    Surfaced so a market with no intraday history reads as a DATA gap on the page rather
    than as a set of strategies that mysteriously never fire."""
    if source in ("equity", "index"):
        out: dict[str, int] = {}
        for tf in ("1m", "5m", "15m", "1h", "1d"):
            syms = await bars_collection.distinct("symbol", {"timeframe": tf})
            if source == "index":
                syms = [s for s in syms if s in INDICES]
            else:
                syms = [s for s in syms if s not in INDICES]
            out[tf] = len(syms)
        for d, parent in DERIVED_FROM.items():
            out[d] = out.get(parent, 0)
        return out
    if source == "commodity":
        from app.services.commodity_bars import commodity_bars_collection
        out = {}
        for tf in ("1m", "5m", "15m", "1h", "1d"):
            out[tf] = len(await commodity_bars_collection.distinct("symbol", {"timeframe": tf}))
        for d, parent in DERIVED_FROM.items():
            out[d] = out.get(parent, 0)
        return out
    return {}


__all__ = ["Bar", "resample", "equity_load_bars", "equity_universe",
           "index_load_bars", "index_universe", "available_timeframes",
           "NSE_SESSION_OPEN", "INDICES", "TF_MINUTES", "DERIVED_FROM"]
