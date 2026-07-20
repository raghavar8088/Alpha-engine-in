"""Live bar streaming for the Chart module.

Reuses the plumbing that already exists rather than adding a second live path:
market-data-service's `live_feed.py` polls every (symbol, timeframe) listed in
the `live_watchlist` collection and publishes each forming/finalized bar to the
Redis `bars_updates` channel. This hub keeps one shared subscription to that
channel — the same pattern `ws/manager.py` and `services/live_engine.py` use —
and fans matching bars out to whichever chart viewers are watching that key.

Two consequences worth knowing:

* Opening a chart registers its (symbol, timeframe) in `live_watchlist`, so
  live_feed starts polling it. That costs no *extra* Dhan calls per viewer:
  live_feed batches one quote request per exchange segment per cycle regardless
  of how many symbols are on the list, and N viewers of the same symbol share a
  single registration.
* A registration created here is tagged `chart_owned` and is only ever removed
  by this module. A watchlist entry a strategy run created is never taken over
  or deleted here — pulling that out from under a running strategy would stop
  it receiving bars.
"""

import asyncio
import contextlib
import json
from datetime import datetime, timezone

import redis.asyncio as redis

from app.core.config import settings
from app.core.db import live_watchlist_collection
from app.services import chart_cache

BARS_UPDATES_CHANNEL = "bars_updates"

# Chart resolution -> the timeframe string live_feed buckets bars into. "W" is
# absent deliberately: live_feed has no weekly bucket, and a weekly candle
# doesn't meaningfully "tick" for a trader watching intraday.
_RESOLUTION_TIMEFRAME = {"1": "1m", "5": "5m", "15": "15m", "60": "1h", "D": "1d"}
_TIMEFRAME_RESOLUTION = {v: k for k, v in _RESOLUTION_TIMEFRAME.items()}

# Only intraday bars are worth accumulating: Dhan serves daily history back for
# years, so there is nothing to recover there.
_PERSIST_TIMEFRAMES = {"1m", "5m", "15m", "1h"}

# Bounded so one stalled reader can't grow without limit; on overflow the oldest
# pending update is dropped, since a stale in-progress candle has no value once
# a newer one for the same bar exists.
_QUEUE_MAXSIZE = 32


def stream_timeframe(resolution: str) -> str | None:
    """live_feed timeframe for a chart resolution, or None if it isn't streamable."""
    return _RESOLUTION_TIMEFRAME.get(resolution)


def bar_epoch(ts_iso: str) -> int:
    """Epoch seconds for a live bar, in the same convention the `history`
    endpoint's timestamps use.

    Dhan's /charts/* responses carry epochs that, read as UTC, spell out IST
    wall-clock time — `providers/dhan_history.py` and `chart_data._to_ist_date`
    both already treat them that way. live_feed stamps its buckets with a real
    IST-aware datetime, so to land on the same grid the wall-clock is stripped
    of its offset and re-read as UTC.

    The frontend does not trust this blindly: it only merges an update that
    lands exactly on its current bar or the next one, and otherwise flags the
    stream stale rather than writing a candle at the wrong place.
    """
    ts = datetime.fromisoformat(ts_iso)
    return int(ts.replace(tzinfo=timezone.utc).timestamp())


class ChartStreamHub:
    def __init__(self) -> None:
        self._subscribers: dict[tuple[str, str], set[asyncio.Queue]] = {}
        # Published bars identify their instrument only by symbol; this remembers
        # which security_id/segment a watched key belongs to so finalized bars can
        # be filed against the same identity the history endpoint uses.
        self._instruments: dict[tuple[str, str], tuple[str, str]] = {}
        self._redis: redis.Redis | None = None
        self._listener_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def subscribe(
        self, symbol: str, timeframe: str, security_id: str, exchange_segment: str,
    ) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        key = (symbol, timeframe)
        async with self._lock:
            first_viewer = key not in self._subscribers
            self._subscribers.setdefault(key, set()).add(queue)
            self._instruments[key] = (security_id, exchange_segment)
            if first_viewer:
                await self._ensure_watched(symbol, timeframe, security_id, exchange_segment)
            if self._listener_task is None:
                self._listener_task = asyncio.create_task(self._listen())
        return queue

    async def unsubscribe(self, symbol: str, timeframe: str, queue: asyncio.Queue) -> None:
        key = (symbol, timeframe)
        async with self._lock:
            subscribers = self._subscribers.get(key)
            if subscribers is None:
                return
            subscribers.discard(queue)
            if subscribers:
                return
            self._subscribers.pop(key, None)
            self._instruments.pop(key, None)
            # Only ever removes a registration this module created.
            await live_watchlist_collection.delete_one(
                {"symbol": symbol, "timeframe": timeframe, "chart_owned": True}
            )

    async def _ensure_watched(
        self, symbol: str, timeframe: str, security_id: str, exchange_segment: str,
    ) -> None:
        existing = await live_watchlist_collection.find_one({"symbol": symbol, "timeframe": timeframe})
        if existing is not None:
            return  # already polled (by a strategy run, or a chart view that raced us)
        await live_watchlist_collection.update_one(
            {"symbol": symbol, "timeframe": timeframe},
            {"$setOnInsert": {
                "symbol": symbol, "timeframe": timeframe,
                "security_id": security_id, "exchange_segment": exchange_segment,
                "chart_owned": True,
            }},
            upsert=True,
        )

    async def _listen(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(BARS_UPDATES_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, ValueError):
                continue
            key = (payload.get("symbol"), payload.get("timeframe"))
            for queue in list(self._subscribers.get(key, set())):
                if queue.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(payload)
            if payload.get("final"):
                await self._persist(key, payload)

    async def _persist(self, key: tuple[str, str], payload: dict) -> None:
        """Bank a finalized intraday bar so this range is still available once
        Dhan's ~30-day intraday window has rolled past it."""
        timeframe = key[1]
        if timeframe not in _PERSIST_TIMEFRAMES:
            return
        instrument = self._instruments.get(key)
        if instrument is None:
            return
        security_id, exchange_segment = instrument
        bar = {
            "t": bar_epoch(payload["ts"]),
            "o": payload["open"], "h": payload["high"],
            "l": payload["low"], "c": payload["close"], "v": payload.get("volume") or 0,
        }
        try:
            await chart_cache.store_bars(
                security_id, exchange_segment, _TIMEFRAME_RESOLUTION[timeframe], [bar],
            )
        except Exception as exc:
            # Never let a storage hiccup kill the shared listener — that would
            # silently stop live updates for every open chart.
            print(f"[warn] chart bar persist failed for {key}: {exc}", flush=True)


hub = ChartStreamHub()
