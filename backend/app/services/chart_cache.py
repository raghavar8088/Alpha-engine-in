"""Caching and durable candle storage for the Chart module.

Two separate jobs, both aimed at the same problem — before this, every chart
open and every timeframe click went straight to Dhan, and Dhan's rate limits
have already caused incidents elsewhere in this app.

**Hot cache (Redis).** Keyed by (security_id, segment, resolution, range). How
long a response may be reused depends entirely on whether it can still change:

* A range that ends before today's session started is finished history. Those
  candles are immutable, so they are cached for days.
* A range that includes today is cached for seconds while the market is open —
  long enough to absorb a reload or a double-click, short enough that the
  in-progress candle is never visibly stale — and for minutes once the session
  has closed and the last candle has stopped moving.

**Durable store (Mongo).** Dhan only serves ~30 days of intraday history and
offers no way to backfill further, so the only way to ever have more is to keep
what we see. Finalized bars arriving on the Phase 2 live stream are appended to
`chart_bars`, and intraday requests reaching past Dhan's window are topped up
from there. This accumulates going forward only: dates before the feature
shipped genuinely have no data and are reported as such rather than invented.
"""

import json
from datetime import datetime, timedelta, timezone

import redis.asyncio as redis
from pymongo import ASCENDING, UpdateOne

from app.core.config import settings
from app.core.db import chart_bars_collection

IST = timezone(timedelta(hours=5, minutes=30))

# Finished history never changes — the only reason not to keep it forever is to
# stop Redis growing without bound from one-off symbol lookups.
_COMPLETED_TTL_SECONDS = 7 * 86400
# Today's range while the session is live: one in-progress candle is in flight.
_LIVE_TTL_SECONDS = 15
# Today's range after the close: the last candle is fixed, but the day may still
# be re-fetched with settlement/volume corrections, so don't keep it for days.
_CLOSED_TTL_SECONDS = 900

_KEY_PREFIX = "chart:bars"

_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


DEFAULT_SESSION = "0915-1530"


def _parse_session(session: str) -> tuple[int, int]:
    """"HHMM-HHMM" -> (open minute, close minute) from IST midnight."""
    open_part, close_part = session.split("-")
    return (
        int(open_part[:2]) * 60 + int(open_part[2:]),
        int(close_part[:2]) * 60 + int(close_part[2:]),
    )


def _session_start_ist(now: datetime | None = None, session: str = DEFAULT_SESSION) -> datetime:
    now_ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    open_minute, _ = _parse_session(session)
    return now_ist.replace(hour=open_minute // 60, minute=open_minute % 60, second=0, microsecond=0)


def market_is_open(now: datetime | None = None, session: str = DEFAULT_SESSION) -> bool:
    """`session` comes from `chart_data.market_session` — MCX runs to ~23:30 IST,
    so a single hardcoded equity window would treat most of a commodity's
    trading day as closed and cache its live candle far too long."""
    now_ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    if now_ist.weekday() >= 5:
        return False
    open_minute, close_minute = _parse_session(session)
    minutes = now_ist.hour * 60 + now_ist.minute
    return open_minute <= minutes <= close_minute


def cache_key(security_id: str, exchange_segment: str, resolution: str, from_ts: int, to_ts: int) -> str:
    return f"{_KEY_PREFIX}:{exchange_segment}:{security_id}:{resolution}:{from_ts}:{to_ts}"


def ttl_for(to_ts: int, now: datetime | None = None, session: str = DEFAULT_SESSION) -> int:
    """How long a response covering data up to `to_ts` may be served from cache."""
    now = now or datetime.now(timezone.utc)
    session_start = _session_start_ist(now, session).astimezone(timezone.utc)
    if datetime.fromtimestamp(to_ts, tz=timezone.utc) < session_start:
        return _COMPLETED_TTL_SECONDS
    return _LIVE_TTL_SECONDS if market_is_open(now, session) else _CLOSED_TTL_SECONDS


async def get_cached(key: str) -> dict | None:
    try:
        raw = await _redis().get(key)
    except Exception:
        return None  # a cold/broken cache must never break charting
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


async def set_cached(key: str, payload: dict, ttl_seconds: int) -> None:
    try:
        await _redis().set(key, json.dumps(payload), ex=ttl_seconds)
    except Exception:
        pass  # caching is an optimisation, never a hard dependency


async def ensure_indexes() -> None:
    await chart_bars_collection.create_index(
        [("security_id", ASCENDING), ("exchange_segment", ASCENDING),
         ("resolution", ASCENDING), ("t", ASCENDING)],
        unique=True,
        name="chart_bars_instrument_time",
    )


async def store_bars(
    security_id: str, exchange_segment: str, resolution: str, bars: list[dict],
) -> int:
    """Append finalized bars to the durable store. Idempotent — re-seeing a bar
    overwrites it rather than duplicating, so replays are harmless."""
    if not bars:
        return 0
    operations = [
        UpdateOne(
            {"security_id": security_id, "exchange_segment": exchange_segment,
             "resolution": resolution, "t": bar["t"]},
            {"$set": {
                "security_id": security_id, "exchange_segment": exchange_segment,
                "resolution": resolution, "t": bar["t"],
                "o": bar["o"], "h": bar["h"], "l": bar["l"], "c": bar["c"], "v": bar.get("v", 0),
            }},
            upsert=True,
        )
        for bar in bars
    ]
    result = await chart_bars_collection.bulk_write(operations, ordered=False)
    return (result.upserted_count or 0) + (result.modified_count or 0)


async def load_stored_bars(
    security_id: str, exchange_segment: str, resolution: str, from_ts: int, to_ts: int,
) -> dict[str, list]:
    """Accumulated bars for a range, in the same parallel-array shape as `get_bars`."""
    cursor = chart_bars_collection.find(
        {"security_id": security_id, "exchange_segment": exchange_segment,
         "resolution": resolution, "t": {"$gte": from_ts, "$lte": to_ts}},
        {"_id": 0, "t": 1, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
    ).sort("t", ASCENDING)

    t: list[int] = []
    o: list[float] = []
    h: list[float] = []
    low: list[float] = []
    c: list[float] = []
    v: list[float] = []
    async for doc in cursor:
        t.append(int(doc["t"]))
        o.append(float(doc["o"]))
        h.append(float(doc["h"]))
        low.append(float(doc["l"]))
        c.append(float(doc["c"]))
        v.append(float(doc.get("v") or 0))
    return {"t": t, "o": o, "h": h, "l": low, "c": c, "v": v}


def merge_series(older: dict[str, list], newer: dict[str, list]) -> dict[str, list]:
    """Splice accumulated history in front of a live Dhan response.

    Where both cover the same timestamp, Dhan wins: it is the authority, and a
    bar we recorded from the live feed may have been finalized mid-revision.
    """
    by_time: dict[int, tuple[float, float, float, float, float]] = {}
    for series in (older, newer):
        for i, ts in enumerate(series["t"]):
            by_time[ts] = (series["o"][i], series["h"][i], series["l"][i], series["c"][i], series["v"][i])
    ordered = sorted(by_time)
    return {
        "t": ordered,
        "o": [by_time[ts][0] for ts in ordered],
        "h": [by_time[ts][1] for ts in ordered],
        "l": [by_time[ts][2] for ts in ordered],
        "c": [by_time[ts][3] for ts in ordered],
        "v": [by_time[ts][4] for ts in ordered],
    }
