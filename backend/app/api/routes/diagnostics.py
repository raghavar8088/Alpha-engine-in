"""Why is the backend slow right now — answered by the backend itself.

WHY THIS EXISTS
---------------
Measured 2026-10-02: `/health`, which touches no database and does no work, took **60
seconds**, eight times in a row, with the container at 5% CPU. Every module page was
unusable and every obvious explanation was wrong — it was not the queries, not the Atlas
tier, not the event loop.

It was memory. The worker had 756 MB resident and another 639 MB in swap against an
800 MB cgroup limit: 17 million major page faults and 35 million swap refaults, so the
process could not touch its own heap without a disk read. A restart took `/health` from
60s to 4ms. Two days later it was back.

Nothing in the app could say any of that. The only way to see it was to SSH to the box and
read `/proc/<pid>/smaps_rollup`, which means in practice nobody sees it until the app is
already dead. So the process reports its own footprint here, and the caches that can grow
report their own size, because an unbounded cache that nobody can measure is found by
running out of memory.

READ-ONLY AND CHEAP. No database, no broker, no allocation of consequence. The type
histogram walks the GC's object list, which is the one costly part, so it is opt-in via
`?objects=true` rather than paid for on every poll.
"""

import gc
import os
import sys
import time

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

_STARTED = time.time()

# Packages worth naming individually: each one costs tens of megabytes of resident memory
# the moment it is imported, and several are pulled in transitively by a single feature.
_HEAVY = ("pandas", "numpy", "scipy", "sklearn", "matplotlib", "yfinance", "torch",
          "statsmodels", "qdrant_client", "transformers", "pyarrow", "anthropic",
          "grpc", "curl_cffi", "bs4", "lxml")


def _proc_memory() -> dict:
    """Resident and swapped memory for THIS process, straight from /proc.

    `VmSwap` is the number that matters and the one no ordinary metric shows: a process
    can look fine at 700 MB resident while another 600 MB of its heap lives on disk, and
    every touch of that half is a page fault."""
    out: dict[str, float | None] = {}
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                k, _, v = line.partition(":")
                if k in ("VmRSS", "VmSwap", "VmHWM", "VmData"):
                    out[k] = round(int(v.split()[0]) / 1024, 1)      # kB -> MB
    except OSError:
        pass
    # The cgroup limit, so "is this a lot" has an answer rather than needing one.
    for path in ("/sys/fs/cgroup/memory.max",
                 "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read().strip()
            if raw and raw != "max":
                out["limit_mb"] = round(int(raw) / 1048576, 1)
            break
        except (OSError, ValueError):
            continue
    rss, limit = out.get("VmRSS"), out.get("limit_mb")
    if rss and limit:
        out["used_pct"] = round(rss / limit * 100, 1)
        # Resident plus swapped: the real footprint, and the one that has to fit.
        out["footprint_mb"] = round(rss + (out.get("VmSwap") or 0), 1)
        out["headroom_mb"] = round(limit - rss, 1)
    try:
        with open("/proc/self/stat", encoding="utf-8") as fh:
            fields = fh.read().split()
        out["major_faults"] = int(fields[11])      # majflt: each one is a disk read
    except (OSError, IndexError, ValueError):
        pass
    return out


def _cache_sizes() -> list[dict]:
    """Every in-process cache that can grow, with its own bound reported beside it.

    A cache whose cap is None is unbounded: not necessarily wrong, but it is the first
    place to look when the footprint climbs for days."""
    rows: list[dict] = []

    def add(name: str, n: int | None, cap=None, note: str = "", approx_mb=None) -> None:
        rows.append({"cache": name, "entries": n, "max_entries": cap,
                     "approx_mb": approx_mb, "note": note})

    try:
        from app.services import api_cache as ac
        body_bytes = sum(len(v[2]) for v in ac._entries.values())
        add("api_cache.responses", len(ac._entries), ac.MAX_ENTRIES,
            f"hits={ac._hits} misses={ac._misses} ttl={ac.TTL}s",
            round(body_bytes / 1048576, 2))
        # Counted separately because it is the half that leaks: `invalidate_module` drops
        # entries without dropping their locks, so this can outgrow the table it guards.
        add("api_cache.locks", len(ac._locks), ac.MAX_ENTRIES,
            "one asyncio.Lock per URL ever requested")
    except Exception:                                   # noqa: BLE001
        pass

    for mod, attr, label, cap, note in (
        ("app.services.response_cache", "_entries", "response_cache.entries", None, ""),
        ("app.services.response_cache", "_locks", "response_cache.locks", None, ""),
        ("app.services.intraday_pattern_engine", "_cache", "intraday_patterns.series",
         None, "candles per (symbol, timeframe)"),
        ("app.services.screener.horizons", "_bars_cache", "screener.horizons.bars", 2, ""),
        ("app.services.screener.patterns", "_cache", "screener.patterns", None, ""),
        ("app.services.screener.patterns", "_scan_locks", "screener.patterns.locks", None, ""),
        ("app.services.screener.chartink", "_cache", "screener.chartink", None, ""),
        ("app.services.screener.momentum", "_snapshot", "screener.momentum", None, ""),
        ("app.services.bullish_stocks", "_cache", "bullish_stocks", None, ""),
        ("app.services.swing_signals.engine", "_cache", "swing_signals", None, ""),
        ("app.services.instrument_search.enrich", "_snapshot", "instrument_search.snapshot",
         None, "one row per instrument"),
        ("app.services.instrument_search.enrich", "_highs", "instrument_search.highs", None, ""),
        ("app.services.live_paper_buying", "_ctx", "live_paper.contexts", None, ""),
        ("app.services.stock_desk", "_ctx", "stock_desk.contexts", None, ""),
        ("app.services.stock_desk", "_libraries", "stock_desk.libraries", None, ""),
        ("app.services.gold_delta_feed", "_PRODUCTS", "gold_desk.products", None, ""),
    ):
        try:
            obj = getattr(sys.modules.get(mod) or __import__(mod, fromlist=["x"]), attr, None)
            if obj is not None:
                add(label, len(obj), cap, note)
        except Exception:                               # noqa: BLE001
            continue

    # THE CONTENT, NOT THE ENTRY COUNT.
    #
    # This is the lesson of the bug that produced this file. The intraday pattern cache
    # showed 164 entries — a number that looks harmless beside a cap of 800 somewhere
    # else — while holding 343,642 Bar objects, because one entry is a whole timeframe's
    # lookback. A cache of bars is sized by its bars. Any module exposing a `*_stats()`
    # that counts them gets to say so here.
    for mod, fn, label in (
        ("app.services.intraday_pattern_engine", "cache_stats", "intraday_patterns.series"),
        ("app.services.screener.horizons", "bars_cache_stats", "screener.horizons.bars"),
    ):
        try:
            m = sys.modules.get(mod) or __import__(mod, fromlist=["x"])
            st = getattr(m, fn)()
            held = st.get("bars_held") or st.get("symbols_held")
            if held is None:
                continue
            for r in rows:
                if r["cache"] == label:
                    r["holds"] = held
                    r["max_entries"] = st.get("max_entries", r["max_entries"])
                    break
        except Exception:                               # noqa: BLE001
            continue

    rows.sort(key=lambda r: (r["approx_mb"] or 0, r.get("holds") or 0,
                             r["entries"] or 0), reverse=True)
    return rows


def _loaded_heavy() -> dict:
    """Which expensive packages this process actually imported.

    Import cost is resident memory that never comes back, and it is paid at startup for
    every feature whose module imports at the top rather than inside the function that
    needs it. Naming them is how a 470 MB baseline becomes a list of decisions."""
    loaded = {name: True for name in _HEAVY if name in sys.modules}
    return {"loaded": sorted(loaded), "total_modules": len(sys.modules)}


@router.get("/memory")
async def memory(objects: bool = Query(False, description="also walk the GC object list"),
                 _user: dict = Depends(get_current_user)):
    out = {
        "uptime_seconds": round(time.time() - _STARTED, 1),
        "uptime_hours": round((time.time() - _STARTED) / 3600, 2),
        "pid": os.getpid(),
        "process": _proc_memory(),
        "heavy_imports": _loaded_heavy(),
        "gc": {"counts": gc.get_count(), "collected_total": sum(
            s.get("collected", 0) for s in gc.get_stats())},
        "caches": _cache_sizes(),
    }
    if objects:
        # Opt-in: on a large heap this walk is seconds and allocates a list of every
        # tracked object. Useful exactly once, when the footprint is already wrong.
        hist: dict[str, int] = {}
        for o in gc.get_objects():
            name = type(o).__name__
            hist[name] = hist.get(name, 0) + 1
        out["objects"] = dict(sorted(hist.items(), key=lambda kv: kv[1], reverse=True)[:25])
    return out
