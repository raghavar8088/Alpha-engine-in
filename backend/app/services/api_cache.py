"""Cache every read endpoint, not the eight that happened to get wrapped by hand.

WHY THE PAGES ARE SLOW. The database is an Atlas M0 free-tier cluster and it stalls for
seconds on arbitrary queries — a bare find_one() was measured at 5.2s with the box idle.
Nothing in our code fixes that. What we control is how often we ask.

Wrapping endpoints one at a time left roughly forty list endpoints — the ones behind every
table — going to Atlas on every page load and again on every 30-second refresh. A page
fires four to six of them at once and is only as fast as its slowest, so one stall makes
the whole screen feel broken. It also guarantees the next endpoint anyone adds is slow
again. So this caches at the door: any GET under /api/ is served from memory for a few
seconds, including endpoints that do not exist yet.

STREAMING RESPONSES MUST NOT BE BUFFERED
-----------------------------------------
Caching at the door means this middleware sees EVERY response, including ones that never
end. `/api/chart/stream` is Server-Sent Events: its generator only finishes when the
client disconnects. Reading it into a bytes buffer to cache it meant the request emitted
no headers at all and hung until the client gave up — measured, the Chart module's live
stream was completely dead. Streaming paths are excluded before the lock, and any
response that declares a streaming content type is passed through unbuffered as a safety
net for endpoints added later.

MUTATIONS INVALIDATE THEIR OWN MODULE
--------------------------------------
A twenty-second TTL after a write means clicking Exit and watching the position sit there
is the expected behaviour, which reads as a broken button. Any non-GET under /api/<mod>/
drops the cached GETs for that same module, so an action is reflected immediately without
giving up caching everywhere else.

WHAT IS DELIBERATELY NOT CACHED: anything reading live broker state (funds, positions,
order books) or touching auth and credentials. A few seconds of staleness is not cosmetic
there — a stale balance on a real-money desk is how someone acts on a number that has
already changed.

?fresh=true bypasses everything, which is what the Refresh button sends.
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
    "fno/margin",                   # a quoted margin must not be stale
    "desk-history/fno",             # cheap already, and account-scoped
    # Server-sent events. Buffering an endless generator emits no headers and hangs the
    # request forever; this must never reach the buffering path or the per-key lock.
    "chart/stream",
)

# Content types that must be streamed straight through, whatever the path.
STREAMING_TYPES = ("text/event-stream", "application/octet-stream", "multipart/")

_entries: dict[str, tuple[float, int, bytes, str]] = {}
_locks: dict[str, asyncio.Lock] = {}
_hits = _misses = _invalidations = 0


def _lock(key: str) -> asyncio.Lock:
    lk = _locks.get(key)
    if lk is None:
        lk = _locks[key] = asyncio.Lock()
    return lk


def _module_of(path: str) -> str:
    """/api/momentum/positions -> 'momentum'. The unit a write invalidates."""
    rest = path[5:] if path.startswith("/api/") else path
    return rest.split("/", 1)[0]


def _cacheable(path: str) -> bool:
    if not path.startswith("/api/"):
        return False
    rest = path[5:]
    return not any(rest.startswith(p) for p in NEVER_CACHE)


def _is_streaming(response) -> bool:
    ctype = (response.headers.get("content-type") or "").lower()
    return any(t in ctype for t in STREAMING_TYPES)


def invalidate_module(module: str) -> int:
    """Drop cached GETs for one module after it has been written to."""
    global _invalidations
    prefix = f"/api/{module}/"
    exact = f"/api/{module}?"
    dead = [k for k in _entries if k.startswith(prefix) or k.startswith(exact)]
    for k in dead:
        _entries.pop(k, None)
    _invalidations += len(dead)
    return len(dead)


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
        global _hits, _misses
        path = request.url.path

        # A write invalidates its own module's cached reads, so the next poll after an
        # action shows the result of that action rather than a 20-second-old table.
        if request.method != "GET":
            response = await call_next(request)
            if path.startswith("/api/") and response.status_code < 400:
                invalidate_module(_module_of(path))
            return response

        if not _cacheable(path):
            return await call_next(request)
        if request.query_params.get("fresh", "").lower() in ("1", "true", "yes"):
            return await call_next(request)

        key = f"{path}?{request.url.query}"
        now = time.monotonic()
        hit = _entries.get(key)
        if hit and now - hit[0] < TTL:
            _hits += 1
            return Response(content=hit[2], status_code=hit[1], media_type=hit[3],
                            headers={"X-Cache": "HIT"})

        async with _lock(key):
            # Re-check inside the lock: a page firing six requests at once should not
            # start six identical queries against the database that is already the problem.
            hit = _entries.get(key)
            if hit and time.monotonic() - hit[0] < TTL:
                _hits += 1
                return Response(content=hit[2], status_code=hit[1], media_type=hit[3],
                                headers={"X-Cache": "HIT"})

            response = await call_next(request)
            # Safety net for any streaming endpoint added later that is not in
            # NEVER_CACHE: hand it back untouched rather than trying to buffer it.
            if _is_streaming(response):
                return response

            body = b"".join([chunk async for chunk in response.body_iterator])
            # Only successful JSON is worth remembering; an error should be retried, not
            # pinned for twenty seconds.
            if response.status_code == 200:
                _entries[key] = (time.monotonic(), response.status_code, body,
                                 response.media_type or "application/json")
                _evict()
            _misses += 1
            return Response(content=body, status_code=response.status_code,
                            media_type=response.media_type,
                            headers={"X-Cache": "MISS"})


def stats() -> dict:
    now = time.monotonic()
    ages = [now - t for t, *_ in _entries.values()]
    total = _hits + _misses
    return {"entries": len(_entries), "ttl_s": TTL,
            "hits": _hits, "misses": _misses,
            "hit_rate": round(_hits / total, 3) if total else 0.0,
            "invalidations": _invalidations,
            "oldest_age_s": round(max(ages), 1) if ages else 0.0}
