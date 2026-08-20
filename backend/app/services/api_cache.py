"""Cache every read endpoint, not the eight I happened to wrap by hand.

WHY THE PAGES ARE SLOW. The database is an Atlas M0 free-tier cluster and it stalls for
seconds on arbitrary queries — a bare find_one() was measured at 5.2s with the box idle.
Nothing in our code fixes that. What we control is how often we ask.

Last pass I wrapped a handful of summary endpoints individually. That left roughly forty
list endpoints — the ones behind every table — going to Atlas on every page load and again
on every 30-second refresh. A page fires four to six of them at once and is only as fast as
its slowest, so one stall makes the whole screen feel broken. Wrapping them one at a time
also guarantees the next endpoint anyone adds is slow again.

So this caches at the door instead: any GET under /api/ is served from memory for a few
seconds. It covers endpoints that do not exist yet, which per-route decorators never could.

WHAT IS DELIBERATELY NOT CACHED: anything that reads live broker state (funds, positions,
order books) or touches auth and credentials. Those are the places where a few seconds of
staleness is not a cosmetic detail — showing a stale balance on a real-money desk is how a
person makes a decision on a number that has already changed.

?fresh=true bypasses everything, which is exactly what the Refresh button sends. Fast by
default, current on demand.
"""

import asyncio
import logging
import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger("api_cache")

TTL = float(os.getenv("API_CACHE_TTL", "20"))
MAX_ENTRIES = int(os.getenv("API_CACHE_MAX", "800"))

# Paths that must always hit the source. Matched as prefixes after /api/.
NEVER_CACHE = (
    "auth", "users", "broker", "settings",
    "live-trading/angel-account",   # the real balance behind real orders
    "fno/margin",                   # quoted margin must not be stale
    "desk-history/fno",             # cheap already, and account-scoped
)

_entries: dict[str, tuple[float, int, bytes, str]] = {}
_locks: dict[str, asyncio.Lock] = {}


def _lock(key: str) -> asyncio.Lock:
    lk = _locks.get(key)
    if lk is None:
        lk = _locks[key] = asyncio.Lock()
    return lk


def _cacheable(path: str) -> bool:
    if not path.startswith("/api/"):
        return False
    rest = path[5:]
    return not any(rest.startswith(p) for p in NEVER_CACHE)


def _evict() -> None:
    """Drop the oldest half when the table grows. Entries are small, but a process that
    runs for weeks should not accumulate every query string ever asked for."""
    if len(_entries) <= MAX_ENTRIES:
        return
    for k, _ in sorted(_entries.items(), key=lambda kv: kv[1][0])[: len(_entries) // 2]:
        _entries.pop(k, None)
        _locks.pop(k, None)


class APICacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method != "GET" or not _cacheable(request.url.path):
            return await call_next(request)
        if request.query_params.get("fresh", "").lower() in ("1", "true", "yes"):
            return await call_next(request)

        key = f"{request.url.path}?{request.url.query}"
        now = time.monotonic()
        hit = _entries.get(key)
        if hit and now - hit[0] < TTL:
            return Response(content=hit[2], status_code=hit[1], media_type=hit[3],
                            headers={"X-Cache": "HIT"})

        async with _lock(key):
            # Re-check inside the lock: a page firing six requests at once should not
            # start six identical queries against the database that is already the problem.
            hit = _entries.get(key)
            if hit and time.monotonic() - hit[0] < TTL:
                return Response(content=hit[2], status_code=hit[1], media_type=hit[3],
                                headers={"X-Cache": "HIT"})

            response = await call_next(request)
            body = b"".join([chunk async for chunk in response.body_iterator])
            # Only successful JSON is worth remembering; an error should be retried, not
            # pinned for twenty seconds.
            if response.status_code == 200:
                _entries[key] = (time.monotonic(), response.status_code, body,
                                 response.media_type or "application/json")
                _evict()
            return Response(content=body, status_code=response.status_code,
                            media_type=response.media_type,
                            headers={"X-Cache": "MISS"})


def stats() -> dict:
    now = time.monotonic()
    ages = [now - t for t, *_ in _entries.values()]
    return {"entries": len(_entries), "ttl_s": TTL,
            "oldest_age_s": round(max(ages), 1) if ages else 0.0}
