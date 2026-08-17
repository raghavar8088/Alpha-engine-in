"""Short-lived in-process cache for desk summaries.

WHY THIS EXISTS. The database is an Atlas M0 free-tier cluster, and it intermittently takes
seconds to answer even a trivial query — a bare find_one() was measured at 5.2s with the
box idle at 2% CPU and the scheduler not running. That is the shared tier throttling, and
no amount of indexing or aggregation on our side removes it. Both of those were worth doing
and were done; this is the part that actually makes the pages feel quick.

The desks only change state when the 180-second scheduler tick runs, so a summary recomputed
more than a few times a minute is answering a question whose answer has not moved. Serving a
cached copy for a few seconds costs nothing in accuracy and removes most of the round trips
that were producing the stalls.

FRESHNESS IS ALWAYS AVAILABLE: every cached endpoint takes `?fresh=true`, which is what the
refresh button sends. So the default is fast and the user can always demand the real thing —
rather than the page quietly showing stale numbers with no way to tell or override.

Deliberately per-process and unbounded-in-time-only: entries are tiny, keyed by endpoint,
and expire on read. A shared cache would need Redis, which is not worth a dependency for
values that live 15 seconds.
"""

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

logger = logging.getLogger("response_cache")

DEFAULT_TTL = 15.0

_entries: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}


def _lock(key: str) -> asyncio.Lock:
    lk = _locks.get(key)
    if lk is None:
        lk = _locks[key] = asyncio.Lock()
    return lk


async def cached(key: str, fn: Callable[[], Awaitable[Any]], ttl: float = DEFAULT_TTL,
                 fresh: bool = False) -> Any:
    """Return a cached value, computing it only when stale or explicitly refused.

    The lock matters: a page that fires six requests at once would otherwise start six
    identical recomputations against the very database that is already the bottleneck.
    With it, the first caller computes and the rest wait for that one result."""
    now = time.monotonic()
    if not fresh:
        hit = _entries.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    async with _lock(key):
        # Re-check inside the lock: whoever we queued behind may have just filled it.
        hit = _entries.get(key)
        if not fresh and hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        value = await fn()
        _entries[key] = (time.monotonic(), value)
        return value


def invalidate(prefix: str = "") -> int:
    """Drop cached entries so the next read recomputes — used after a desk cycle writes."""
    keys = [k for k in _entries if k.startswith(prefix)] if prefix else list(_entries)
    for k in keys:
        _entries.pop(k, None)
    return len(keys)


def stats() -> dict:
    now = time.monotonic()
    return {"entries": len(_entries),
            "keys": sorted(_entries)[:40],
            "oldest_age_s": round(max((now - t for t, _ in _entries.values()), default=0.0), 1)}
