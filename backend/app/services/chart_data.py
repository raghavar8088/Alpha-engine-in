"""Live charting data — powers the TradingView-style Chart module (frontend uses
`lightweight-charts`, the free open-source library TradingView itself publishes;
the paid/gated Charting Library was not available so this adapter targets that
instead). Fetches real candles from Dhan on demand for whatever the user
searches, rather than only the locally-backfilled symbol set, since a chart
module needs to work for any instrument a user picks.

Response shape for bars is UDF-ish ({s, t, o, h, l, c, v}) so this can be
upgraded to a real TradingView UDF datafeed later with minimal changes if the
gated Charting Library ever becomes available.
"""

from datetime import datetime, timedelta, timezone

from app.core.db import instruments_collection
from app.services.dhan_client import DhanAPIError, DhanClient

IST = timezone(timedelta(hours=5, minutes=30))

# Dhan's `instrument` field for /charts/* endpoints, by our asset_class.
_INSTRUMENT_TYPE = {
    "EQUITY": "EQUITY",
    "ETF": "EQUITY",
    "INDEX": "INDEX",
    "EQUITY_FUTURE": "FUTSTK",
    "INDEX_FUTURE": "FUTIDX",
}

# TradingView-style resolution string -> Dhan intraday interval (minutes), or
# None for resolutions served from the daily-candle endpoint.
_INTRADAY_MINUTES = {"1": 1, "5": 5, "15": 15, "60": 60}
SUPPORTED_RESOLUTIONS = ["1", "5", "15", "60", "D", "W"]

INTRADAY_CHUNK_DAYS = 75  # Dhan caps a single /charts/intraday request at 90 days
INTRADAY_MAX_LOOKBACK_DAYS = 30  # intraday history isn't useful/available much past this


class ChartError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


async def search_symbols(query: str, limit: int = 20) -> list[dict]:
    """Prefix/name search across chartable instruments. A plain query() with no
    ranking buries short exact tickers (e.g. the single "NIFTY" index row) under
    thousands of same-prefixed F&O contract names ("NIFTY-Aug2026-FUT", every
    NIFTY option strike, ...) — sort candidates by symbol length so exact/short
    matches surface first, which is what "search for NIFTY" actually means."""
    q = query.strip()
    if not q:
        return []
    pipeline = [
        {"$match": {
            "asset_class": {"$in": list(_INSTRUMENT_TYPE.keys())},
            "$or": [
                {"symbol": {"$regex": f"^{q}", "$options": "i"}},
                {"name": {"$regex": q, "$options": "i"}},
            ],
        }},
        {"$addFields": {"_symlen": {"$strLenCP": "$symbol"}}},
        {"$sort": {"_symlen": 1, "symbol": 1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "symbol": 1, "name": 1, "security_id": 1, "exchange_segment": 1,
                      "asset_class": 1, "tick_size": 1}},
    ]
    return [d async for d in instruments_collection.aggregate(pipeline)]


async def _instrument(security_id: str, exchange_segment: str) -> dict:
    doc = await instruments_collection.find_one({"security_id": security_id, "exchange_segment": exchange_segment})
    if doc is None:
        raise ChartError(f"Unknown instrument {security_id}/{exchange_segment}")
    if doc["asset_class"] not in _INSTRUMENT_TYPE:
        raise ChartError(f"Charting isn't supported for asset class {doc['asset_class']}")
    return doc


async def resolve_symbol(security_id: str, exchange_segment: str) -> dict:
    inst = await _instrument(security_id, exchange_segment)
    tick = inst.get("tick_size") or 0.05
    # pricescale is decimal subdivisions per price unit (100 = 2dp) — tick_size
    # data for some rows is >= 1 (a scrip-master quirk, not a real ₹10 tick), which
    # would invert to 0 and break the chart's price axis; clamp to the standard
    # 2dp convention whenever tick isn't in the normal sub-unit range.
    pricescale = round(1 / tick) if 0 < tick < 1 else 100
    return {
        "symbol": inst["symbol"],
        "name": inst.get("name") or inst["symbol"],
        "security_id": inst["security_id"],
        "exchange_segment": inst["exchange_segment"],
        "asset_class": inst["asset_class"],
        "pricescale": pricescale,
        "timezone": "Asia/Kolkata",
        "session": "0915-1530",
        "supported_resolutions": SUPPORTED_RESOLUTIONS,
    }


def _to_ist_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(IST).strftime("%Y-%m-%d")


def _parse_candles(raw: dict) -> tuple[list[int], list[float], list[float], list[float], list[float], list[float]]:
    stamps = raw.get("timestamp") or []
    return (
        [int(t) for t in stamps],
        [float(x) for x in raw.get("open") or []],
        [float(x) for x in raw.get("high") or []],
        [float(x) for x in raw.get("low") or []],
        [float(x) for x in raw.get("close") or []],
        [float(x) for x in raw.get("volume") or [0] * len(stamps)],
    )


async def get_bars(
    dhan: DhanClient, security_id: str, exchange_segment: str, resolution: str, from_ts: int, to_ts: int,
) -> dict:
    if resolution not in SUPPORTED_RESOLUTIONS:
        raise ChartError(f"resolution must be one of {SUPPORTED_RESOLUTIONS}")
    inst = await _instrument(security_id, exchange_segment)
    instrument_type = _INSTRUMENT_TYPE[inst["asset_class"]]

    t: list[int] = []
    o: list[float] = []
    h: list[float] = []
    low: list[float] = []
    c: list[float] = []
    v: list[float] = []

    try:
        if resolution in ("D", "W"):
            raw = await dhan.historical_daily(
                security_id, exchange_segment, instrument_type,
                _to_ist_date(from_ts), _to_ist_date(to_ts),
            )
            t, o, h, low, c, v = _parse_candles(raw)
            if resolution == "W":
                t, o, h, low, c, v = _aggregate_weekly(t, o, h, low, c, v)
        else:
            minutes = _INTRADAY_MINUTES[resolution]
            from_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc)
            to_dt = datetime.fromtimestamp(to_ts, tz=timezone.utc)
            # Intraday history is only meaningfully available/useful for a recent
            # window — cap the lookback rather than issuing chunked requests back
            # to the instrument's inception, which Dhan will just return empty for.
            from_dt = max(from_dt, to_dt - timedelta(days=INTRADAY_MAX_LOOKBACK_DAYS))
            chunk_start = from_dt
            while chunk_start < to_dt:
                chunk_end = min(chunk_start + timedelta(days=INTRADAY_CHUNK_DAYS), to_dt)
                raw = await dhan.historical_intraday(
                    security_id, exchange_segment, instrument_type, minutes,
                    chunk_start.strftime("%Y-%m-%d %H:%M:%S"), chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                )
                ct, co, ch, cl, cc, cv = _parse_candles(raw)
                t.extend(ct); o.extend(co); h.extend(ch); low.extend(cl); c.extend(cc); v.extend(cv)
                chunk_start = chunk_end
    except DhanAPIError as exc:
        raise ChartError(f"Dhan history request failed: {exc.remarks}")

    if not t:
        return {"s": "no_data"}
    return {"s": "ok", "t": t, "o": o, "h": h, "l": low, "c": c, "v": v}


def _aggregate_weekly(
    t: list[int], o: list[float], h: list[float], low: list[float], c: list[float], v: list[float],
) -> tuple[list[int], list[float], list[float], list[float], list[float], list[float]]:
    """Dhan has no weekly candle endpoint — build them from daily closes, bucketed
    by ISO week (Monday), matching the same convention used for local backfills."""
    buckets: dict[int, dict] = {}
    for i in range(len(t)):
        day = datetime.fromtimestamp(t[i], tz=timezone.utc).astimezone(IST)
        week_start = day - timedelta(days=day.weekday())
        key = int(week_start.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        b = buckets.setdefault(key, {"o": o[i], "h": h[i], "l": low[i], "c": c[i], "v": 0.0})
        b["h"] = max(b["h"], h[i])
        b["l"] = min(b["l"], low[i])
        b["c"] = c[i]
        b["v"] += v[i]
    keys = sorted(buckets)
    return (
        keys,
        [buckets[k]["o"] for k in keys], [buckets[k]["h"] for k in keys],
        [buckets[k]["l"] for k in keys], [buckets[k]["c"] for k in keys], [buckets[k]["v"] for k in keys],
    )


def find_trend_points(h: list[float], low: list[float], t: list[int], lookback: int = 60) -> dict | None:
    """Simple, honest swing-high/swing-low trend line: over the last `lookback`
    candles, connect the earliest and latest local extremes on whichever side has
    the clearer directional move. Not a substitute for real pattern recognition —
    just enough to draw one reasonable trend line automatically, matching what
    createMultipointShape would need two (time, price) points for."""
    n = len(t)
    if n < 10:
        return None
    window = min(lookback, n)
    start = n - window

    def swing_lows() -> list[int]:
        return [i for i in range(start + 2, n - 2) if low[i] <= low[i - 1] and low[i] <= low[i - 2]
                and low[i] <= low[i + 1] and low[i] <= low[i + 2]]

    def swing_highs() -> list[int]:
        return [i for i in range(start + 2, n - 2) if h[i] >= h[i - 1] and h[i] >= h[i - 2]
                and h[i] >= h[i + 1] and h[i] >= h[i + 2]]

    lows_idx, highs_idx = swing_lows(), swing_highs()
    net_move = low[n - 1] - low[start]
    if net_move >= 0 and len(lows_idx) >= 2:
        i1, i2 = lows_idx[0], lows_idx[-1]
        return {"kind": "support", "p1": {"time": t[i1], "price": low[i1]}, "p2": {"time": t[i2], "price": low[i2]}}
    if net_move < 0 and len(highs_idx) >= 2:
        i1, i2 = highs_idx[0], highs_idx[-1]
        return {"kind": "resistance", "p1": {"time": t[i1], "price": h[i1]}, "p2": {"time": t[i2], "price": h[i2]}}
    return None
