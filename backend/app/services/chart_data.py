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
from app.services import chart_cache
from app.services.broker_data import angel_bars, dhan_is_cooling_down, note_dhan_rate_limit
from app.services.dhan_client import DhanAPIError, DhanClient, DhanRateLimitError

IST = timezone(timedelta(hours=5, minutes=30))

# Dhan's `instrument` field for /charts/* endpoints, by our asset_class. Mirrors
# the mapping market-data-service/providers/dhan_history.py already uses — the
# /charts/historical and /charts/intraday request shapes are identical for
# options and commodities (same expiryCode/interval fields), so no per-class
# branching is needed on the request side. Session hours do differ; see
# `market_session`.
_INSTRUMENT_TYPE = {
    "EQUITY": "EQUITY",
    "ETF": "EQUITY",
    "INDEX": "INDEX",
    "EQUITY_FUTURE": "FUTSTK",
    "INDEX_FUTURE": "FUTIDX",
    "EQUITY_OPTION": "OPTSTK",
    "INDEX_OPTION": "OPTIDX",
    "COMMODITY_FUTURE": "FUTCOM",
    "COMMODITY_OPTION": "OPTFUT",
}

_COMMODITY_CLASSES = {"COMMODITY_FUTURE", "COMMODITY_OPTION"}
_OPTION_CLASSES = {"EQUITY_OPTION", "INDEX_OPTION", "COMMODITY_OPTION"}


def market_session(asset_class: str) -> str:
    """Trading window for an asset class. MCX runs a long evening session, so
    assuming the equity 09:15-15:30 for a commodity would mislabel most of its
    trading day as closed."""
    return "0900-2330" if asset_class in _COMMODITY_CLASSES else "0915-1530"

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
    matches surface first, which is what "search for NIFTY" actually means. That
    ranking matters more now that options are chartable: a single underlying can
    contribute thousands of strike rows, and without it the underlying itself
    would never appear in the first 20 results.

    `expiry`/`strike`/`option_type`/`underlying_symbol` are projected so the UI
    can label a contract properly — "NIFTY 24500 CE 28-Aug" rather than an
    opaque contract symbol.

    Expired derivatives are excluded. The instrument master keeps every historical
    contract, and there are far more dead strikes than live ones, so without this
    a "NIFTY-Jul" search returned 20 already-expired options — each of which
    charts as no_data — and not a single tradeable one. A contract is kept if it
    has no expiry (equities/indices/ETFs) or its expiry is today or later."""
    q = query.strip()
    if not q:
        return []
    today = datetime.now(IST).strftime("%Y-%m-%d")
    pipeline = [
        {"$match": {
            "asset_class": {"$in": list(_INSTRUMENT_TYPE.keys())},
            # No expiry field at all (cash/index/ETF) OR not yet expired.
            "$or": [
                {"expiry": {"$exists": False}},
                {"expiry": None},
                {"expiry": {"$gte": today}},
            ],
            "$and": [{"$or": [
                {"symbol": {"$regex": f"^{q}", "$options": "i"}},
                {"name": {"$regex": q, "$options": "i"}},
                {"underlying_symbol": {"$regex": f"^{q}", "$options": "i"}},
            ]}],
        }},
        {"$addFields": {"_symlen": {"$strLenCP": "$symbol"}}},
        # Nearest expiry first within a given symbol length, so the contracts a
        # trader actually looks at aren't buried behind far-dated ones.
        {"$sort": {"_symlen": 1, "expiry": 1, "strike": 1, "symbol": 1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "symbol": 1, "name": 1, "security_id": 1, "exchange_segment": 1,
                      "asset_class": 1, "tick_size": 1, "expiry": 1, "strike": 1,
                      "option_type": 1, "underlying_symbol": 1, "lot_size": 1}},
    ]
    return [d async for d in instruments_collection.aggregate(pipeline)]


async def _instrument(security_id: str, exchange_segment: str) -> dict:
    doc = await instruments_collection.find_one({"security_id": security_id, "exchange_segment": exchange_segment})
    if doc is None:
        raise ChartError(f"Unknown instrument {security_id}/{exchange_segment}")
    if doc["asset_class"] not in _INSTRUMENT_TYPE:
        raise ChartError(f"Charting isn't supported for asset class {doc['asset_class']}")
    return doc


async def instrument_for_stream(security_id: str, exchange_segment: str) -> dict:
    """Instrument doc for the live-stream route. live_feed keys its watchlist and
    its published bars by `symbol`, not security_id, so the stream endpoint has
    to resolve one to the other before it can subscribe."""
    return await _instrument(security_id, exchange_segment)


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
        "session": market_session(inst["asset_class"]),
        "supported_resolutions": SUPPORTED_RESOLUTIONS,
        # Contract details, present only for derivatives — the chart header and
        # the search list use them to label a strike rather than show a raw
        # contract symbol.
        "expiry": inst.get("expiry"),
        "strike": inst.get("strike"),
        "option_type": inst.get("option_type"),
        "underlying_symbol": inst.get("underlying_symbol"),
        "lot_size": inst.get("lot_size"),
        "is_option": inst["asset_class"] in _OPTION_CLASSES,
        "is_commodity": inst["asset_class"] in _COMMODITY_CLASSES,
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
    """Cached entry point for candle history.

    A repeat request for the same (instrument, resolution, range) inside the TTL
    is served from Redis without touching Dhan — see `services.chart_cache` for
    how the TTL is chosen so an in-progress candle is never served stale.
    """
    if resolution not in SUPPORTED_RESOLUTIONS:
        raise ChartError(f"resolution must be one of {SUPPORTED_RESOLUTIONS}")
    inst = await _instrument(security_id, exchange_segment)

    key = chart_cache.cache_key(security_id, exchange_segment, resolution, from_ts, to_ts)
    cached = await chart_cache.get_cached(key)
    if cached is not None:
        return cached

    payload = await _fetch_bars(dhan, inst, resolution, from_ts, to_ts)
    # Session-aware: an MCX contract is still trading at 21:00 IST, so its
    # in-progress candle must not be cached as if the day were over.
    ttl = chart_cache.ttl_for(to_ts, session=market_session(inst["asset_class"]))
    await chart_cache.set_cached(key, payload, ttl)
    return payload


async def _fetch_bars(
    dhan: DhanClient, inst: dict, resolution: str, from_ts: int, to_ts: int,
) -> dict:
    security_id = inst["security_id"]
    exchange_segment = inst["exchange_segment"]
    instrument_type = _INSTRUMENT_TYPE[inst["asset_class"]]

    t: list[int] = []
    o: list[float] = []
    h: list[float] = []
    low: list[float] = []
    c: list[float] = []
    v: list[float] = []
    dhan_failure: str | None = None

    try:
        if await dhan_is_cooling_down():
            # Skip straight to the Angel fallback below rather than spending another
            # request while Dhan is throttling the account.
            raise DhanRateLimitError("Dhan rate limit — cooling down")
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
            # Dhan only serves a recent intraday window — asking further back just
            # returns empty, so cap what we request of it. Anything older that we
            # have is topped up from the durable store below.
            dhan_from_dt = max(from_dt, to_dt - timedelta(days=INTRADAY_MAX_LOOKBACK_DAYS))
            chunk_start = dhan_from_dt
            while chunk_start < to_dt:
                chunk_end = min(chunk_start + timedelta(days=INTRADAY_CHUNK_DAYS), to_dt)
                raw = await dhan.historical_intraday(
                    security_id, exchange_segment, instrument_type, minutes,
                    chunk_start.strftime("%Y-%m-%d %H:%M:%S"), chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                )
                ct, co, ch, cl, cc, cv = _parse_candles(raw)
                t.extend(ct); o.extend(co); h.extend(ch); low.extend(cl); c.extend(cc); v.extend(cv)
                chunk_start = chunk_end
    except DhanRateLimitError as exc:
        await note_dhan_rate_limit()
        dhan_failure = exc.remarks
    except DhanAPIError as exc:
        # Don't give up yet — Angel One below is an independent source that
        # survives the Dhan token being rotated out from under us.
        dhan_failure = exc.remarks

    series = {"t": t, "o": o, "h": h, "l": low, "c": c, "v": v}

    # Intraday requests that reach past Dhan's serving window get whatever the
    # live stream has accumulated for those dates spliced in front. Dates before
    # this feature started recording simply have nothing, and say so.
    if resolution in _INTRADAY_MINUTES and from_ts < int((datetime.now(timezone.utc) - timedelta(days=INTRADAY_MAX_LOOKBACK_DAYS)).timestamp()):
        stored = await chart_cache.load_stored_bars(security_id, exchange_segment, resolution, from_ts, to_ts)
        if stored["t"]:
            series = chart_cache.merge_series(stored, series)

    if not series["t"]:
        # Nothing from Dhan — it either errored or served an empty window. Try Angel
        # One, which authenticates independently. Angel has no weekly interval, so
        # weekly is aggregated from its daily bars exactly as Dhan's is above.
        fallback = await angel_bars(
            security_id, exchange_segment, "D" if resolution == "W" else resolution, from_ts, to_ts
        )
        if fallback:
            if resolution == "W":
                (fallback["t"], fallback["o"], fallback["h"],
                 fallback["l"], fallback["c"], fallback["v"]) = _aggregate_weekly(
                    fallback["t"], fallback["o"], fallback["h"],
                    fallback["l"], fallback["c"], fallback["v"],
                )
            return fallback
        if dhan_failure:
            raise ChartError(f"Dhan history request failed: {dhan_failure}")
        return {"s": "no_data"}
    return {"s": "ok", **series}


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


# --- Phase 6: structural analysis -----------------------------------------
#
# `find_trend_points` above is kept exactly as it was — the `trendline` endpoint
# and the existing frontend toggle still depend on it. Everything below is
# additive: multi-touch zones, a fitted channel, and swing structure.

_SWING_WINDOW = 2  # bars either side that a fractal pivot must beat


def _swing_indices(values: list[float], start: int, end: int, want_high: bool) -> list[int]:
    """Fractal pivots: a bar whose high (or low) is not bettered by the
    `_SWING_WINDOW` bars on either side."""
    out = []
    for i in range(start + _SWING_WINDOW, end - _SWING_WINDOW):
        window = range(i - _SWING_WINDOW, i + _SWING_WINDOW + 1)
        if want_high and all(values[i] >= values[j] for j in window):
            out.append(i)
        elif not want_high and all(values[i] <= values[j] for j in window):
            out.append(i)
    return out


def _cluster_zones(
    prices: list[float], times: list[int], tolerance: float, min_touches: int = 2,
) -> list[dict]:
    """Group nearby pivots into support/resistance *zones*.

    A level that price has turned at three times is a materially stronger
    reference than a single swing point, which is the main thing the old
    two-point line could not express. Zones are returned strongest-first.
    """
    if not prices:
        return []
    order = sorted(range(len(prices)), key=lambda i: prices[i])
    clusters: list[list[int]] = []
    for idx in order:
        if clusters and abs(prices[idx] - prices[clusters[-1][-1]]) <= tolerance:
            clusters[-1].append(idx)
        else:
            clusters.append([idx])

    zones = []
    for cluster in clusters:
        if len(cluster) < min_touches:
            continue
        members = [prices[i] for i in cluster]
        zones.append({
            "price": round(sum(members) / len(members), 4),
            "low": round(min(members), 4),
            "high": round(max(members), 4),
            "touches": len(cluster),
            "last_touch_time": max(times[i] for i in cluster),
        })
    zones.sort(key=lambda z: (-z["touches"], -z["last_touch_time"]))
    return zones


def _fit_line(indices: list[int], values: list[float], times: list[int]) -> dict | None:
    """Least-squares line through pivot points, returned as the two (time, price)
    endpoints the chart draws. Least squares rather than first-and-last so one
    outlier pivot can't tilt the whole channel."""
    if len(indices) < 2:
        return None
    n = len(indices)
    mean_x = sum(indices) / n
    mean_y = sum(values[i] for i in indices) / n
    denominator = sum((i - mean_x) ** 2 for i in indices)
    if denominator == 0:
        return None
    slope = sum((i - mean_x) * (values[i] - mean_y) for i in indices) / denominator
    intercept = mean_y - slope * mean_x
    first, last = indices[0], indices[-1]
    return {
        "p1": {"time": times[first], "price": round(slope * first + intercept, 4)},
        "p2": {"time": times[last], "price": round(slope * last + intercept, 4)},
        "slope_per_bar": round(slope, 6),
    }


def _describe_structure(highs: list[float], lows: list[float]) -> dict:
    """Higher-highs/higher-lows style read on the last two swings of each side.

    Each side is classified as rising, falling or *flat* rather than by a bare
    `>`: an equal high is not a lower high, and collapsing the two would report
    a descending triangle (lower highs against a flat floor) as a plain
    downtrend, which is a different setup with a different break direction.
    "Flat" is a relative tolerance so it behaves the same on a ₹20 premium and a
    50,000-point index.
    """
    if len(highs) < 2 or len(lows) < 2:
        return {"label": "not enough swings to call structure", "bias": "unclear"}

    def direction(previous: float, latest: float) -> int:
        scale = max(abs(previous), abs(latest), 1e-9)
        if abs(latest - previous) / scale < 0.001:
            return 0
        return 1 if latest > previous else -1

    high_dir = direction(highs[-2], highs[-1])
    low_dir = direction(lows[-2], lows[-1])

    if high_dir > 0 and low_dir > 0:
        return {"label": "higher highs and higher lows", "bias": "uptrend"}
    if high_dir < 0 and low_dir < 0:
        return {"label": "lower highs and lower lows", "bias": "downtrend"}
    if high_dir == 0 and low_dir == 0:
        return {"label": "flat highs and flat lows", "bias": "sideways"}
    if high_dir > 0 and low_dir < 0:
        return {"label": "higher highs and lower lows — a broadening range", "bias": "expansion"}
    if high_dir < 0 and low_dir > 0:
        return {"label": "lower highs and higher lows — a contracting range", "bias": "compression"}
    if low_dir > 0:  # high_dir == 0
        return {"label": "higher lows into a flat ceiling", "bias": "compression"}
    if low_dir < 0:  # high_dir == 0
        return {"label": "lower lows under a flat ceiling", "bias": "downtrend"}
    if high_dir > 0:  # low_dir == 0
        return {"label": "higher highs over a flat floor", "bias": "compression"}
    return {"label": "lower highs over a flat floor", "bias": "compression"}


def analyze_structure(
    h: list[float], low: list[float], c: list[float], t: list[int], lookback: int = 120,
) -> dict:
    """Support/resistance zones, a fitted trend channel and swing structure over
    the recent window.

    Zone tolerance is a fraction of the window's own price range rather than a
    fixed rupee amount, so the same code works on a ₹20 option premium and a
    50,000-point index.
    """
    n = len(t)
    if n < 20:
        return {"available": False, "reason": "Not enough candles for structural analysis."}

    window = min(lookback, n)
    start = n - window
    high_idx = _swing_indices(h, start, n, want_high=True)
    low_idx = _swing_indices(low, start, n, want_high=False)

    price_range = max(h[start:]) - min(low[start:])
    tolerance = max(price_range * 0.01, 1e-9)

    resistance = _cluster_zones([h[i] for i in high_idx], [t[i] for i in high_idx], tolerance)
    support = _cluster_zones([low[i] for i in low_idx], [t[i] for i in low_idx], tolerance)

    upper = _fit_line(high_idx, h, t)
    lower = _fit_line(low_idx, low, t)
    channel = {"upper": upper, "lower": lower} if upper and lower else None

    structure = _describe_structure([h[i] for i in high_idx], [low[i] for i in low_idx])

    return {
        "available": True,
        "bars_analyzed": window,
        "last_close": c[-1] if c else None,
        "structure": structure,
        "support_zones": support[:4],
        "resistance_zones": resistance[:4],
        "channel": channel,
        "swing_highs": [{"time": t[i], "price": h[i]} for i in high_idx[-6:]],
        "swing_lows": [{"time": t[i], "price": low[i]} for i in low_idx[-6:]],
    }
