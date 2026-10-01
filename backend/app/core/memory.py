"""Give freed memory back to the operating system.

THE PROBLEM THIS SOLVES
-----------------------
Measured 2026-10-02 on the production container: the worker held 756 MB resident and
another 639 MB in swap against an 800 MB limit, with 17 million major page faults and
35 million swap refaults. `/health` — no database, no work — took 60 SECONDS, eight times
in a row, at 5% CPU. Every module page was unusable. A restart took it to 4 ms, and two
days later it was back.

It is not a leak in the ordinary sense. Nothing holds those objects: the caches were
nearly empty when measured. It is the allocator never handing freed pages back.

WHY IT RATCHETS
---------------
The desks allocate in bursts. One commodity cycle builds tens of thousands of Bar objects
and the Mongo documents they came from, frees them all, and does it again two minutes
later. glibc serves those allocations from per-thread arenas, and this process runs 44
threads — Starlette's default 40-thread pool plus Mongo's and uvicorn's. The default arena
cap is 8 x CPU cores, each arena grows to fit its own peak, and a free() in the middle of
an arena returns nothing to the kernel. So RSS tracks the HIGH-WATER MARK of every arena
added together, for ever. The process measured 1.9 GB of VmData holding ~1.4 GB of live
heap, which is the gap this closes.

TWO LEVERS, BOTH CHEAP
----------------------
`MALLOC_ARENA_MAX=2` (set on the container, not here — it must be in the environment
before the first allocation) stops the arena count scaling with threads.

`malloc_trim()` below is the other half: it walks the arenas and releases free pages back
to the kernel. It is called on a timer rather than after every cycle, because trimming is
not free and the point is to undo a slow ratchet, not to police each allocation.

NOTHING HERE CHANGES BEHAVIOUR. If the C library has no `malloc_trim` — musl does not —
every call is a no-op that says so, and the app runs exactly as before.
"""

import ctypes
import ctypes.util
import logging
import os
import time

logger = logging.getLogger("memory")

# Every 10 minutes. Long enough that trimming costs nothing measurable, short enough that
# a burst of allocation is given back within one page-refresh of the desks noticing.
TRIM_INTERVAL_S = int(os.getenv("MALLOC_TRIM_INTERVAL_S", "600"))

_stats = {"trims": 0, "last_at": None, "last_rss_mb": None, "last_freed_mb": None,
          "available": None}


def _libc():
    try:
        return ctypes.CDLL("libc.so.6", use_errno=True)
    except OSError:
        name = ctypes.util.find_library("c")
        if not name:
            return None
        try:
            return ctypes.CDLL(name, use_errno=True)
        except OSError:
            return None


def rss_mb() -> float | None:
    """This process's resident size, read from /proc. None where /proc is not mounted."""
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    return None


def trim() -> dict:
    """Release free heap pages back to the kernel. Safe to call at any time."""
    lib = _libc()
    fn = getattr(lib, "malloc_trim", None) if lib else None
    if fn is None:
        _stats["available"] = False
        return dict(_stats)
    _stats["available"] = True
    before = rss_mb()
    try:
        fn.argtypes = [ctypes.c_size_t]
        fn.restype = ctypes.c_int
        fn(0)
    except Exception as exc:                            # noqa: BLE001
        logger.warning("malloc_trim failed (%s) — continuing", str(exc)[:120])
        return dict(_stats)
    after = rss_mb()
    _stats["trims"] += 1
    _stats["last_at"] = time.time()
    _stats["last_rss_mb"] = after
    if before is not None and after is not None:
        _stats["last_freed_mb"] = round(before - after, 1)
    return dict(_stats)


def stats() -> dict:
    return dict(_stats)


async def trim_loop() -> None:
    """Trim on a timer, for the life of the process."""
    import asyncio

    while True:
        await asyncio.sleep(TRIM_INTERVAL_S)
        try:
            s = trim()
            freed = s.get("last_freed_mb") or 0.0
            # Only worth a log line when it actually returned something: a quiet loop
            # should stay quiet, but a trim that frees 200 MB is the story of the day.
            if freed >= 20:
                logger.info("[memory] trimmed %.1f MB back to the OS — RSS now %.1f MB",
                            freed, s.get("last_rss_mb") or -1)
        except Exception:                               # noqa: BLE001
            logger.exception("[memory] trim failed — will retry next interval")
