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
    # The screener's daily-bar cache reports SYMBOLS held ("525"); its bars are counted here
    # (197,462 on 2026-10-18: each symbol carries ~376 daily bars).
    try:
        hz = sys.modules.get("app.services.screener.horizons")
        if hz is not None:
            held = sum(len(bars) for _ts, by_sym in list(hz._bars_cache.values()) for bars in by_sym.values())
            for r in rows:
                if r["cache"] == "screener.horizons.bars":
                    r["holds"] = held
                    r["note"] = "daily bars across every symbol held"
                    break
    except Exception:                                   # noqa: BLE001
        pass

    for mod, fn, label in (
        ("app.services.intraday_pattern_engine", "cache_stats", "intraday_patterns.series"),
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


# ── who is holding it ──────────────────────────────────────────────────────────────
#
# The type histogram says WHAT fills the heap ("349,802 Bar objects") but not WHO keeps it
# alive, and four modules define a class called Bar. This walk answers the second question:
# from every global of the app's own modules — and from the local variables of every running
# task, where a loop that loads a whole universe of candles each cycle keeps them — it follows
# containers and instance attributes and charges each object to the FIRST holder that reaches
# it. Infrastructure (the event loop, the Mongo driver, FastAPI's routing) is never entered:
# its graphs are huge and never the app's leak.

_SKIP_TYPE_MODULES = ("asyncio", "motor", "pymongo", "bson", "fastapi", "starlette", "pydantic",
                      "pydantic_core", "uvicorn", "ssl", "socket", "selectors", "threading",
                      "concurrent", "logging", "httpx", "httpcore", "anyio", "websockets", "h11",
                      "multiprocessing", "typing", "inspect", "importlib", "_frozen_importlib",
                      "weakref", "abc", "enum", "functools", "contextvars", "_contextvars")
_LEAF_TYPES = (str, bytes, bytearray, int, float, bool, complex, type(None), range, memoryview)


def _never_enter(o) -> bool:
    import types
    if isinstance(o, (types.ModuleType, type, types.FunctionType, types.BuiltinFunctionType,
                      types.MethodType, types.CodeType, types.FrameType, types.GeneratorType,
                      types.CoroutineType, types.AsyncGeneratorType, property, staticmethod,
                      classmethod)):
        return True
    mod = getattr(type(o), "__module__", "") or ""
    return mod.startswith(_SKIP_TYPE_MODULES)


def _size_and_children(o) -> tuple[int, list]:
    """Shallow size of `o` (an array counts its buffer) and what it keeps alive."""
    from collections import deque

    try:
        size = sys.getsizeof(o)
    except Exception:                                   # noqa: BLE001
        size = 0
    if isinstance(o, _LEAF_TYPES):
        return size, []
    tname = type(o).__name__
    tmod = getattr(type(o), "__module__", "") or ""
    if tmod.startswith("numpy") and hasattr(o, "nbytes"):
        return size + (int(o.nbytes) if getattr(o, "base", None) is None else 0), []
    if tmod.startswith("pandas") and tname in ("DataFrame", "Series", "Index"):
        try:
            mu = o.memory_usage(index=True, deep=False)
            return size + int(mu.sum() if hasattr(mu, "sum") else mu), []
        except Exception:                               # noqa: BLE001
            return size, []
    try:
        if isinstance(o, dict):
            items = list(o.items())
            return size, [k for k, _ in items if not isinstance(k, _LEAF_TYPES)] + [v for _, v in items]
        if isinstance(o, (list, tuple, set, frozenset, deque)):
            return size, list(o)
    except RuntimeError:                                # changed while copied: skip it this time
        return size, []
    if _never_enter(o):
        return size, []
    kids: list = []
    try:
        d = object.__getattribute__(o, "__dict__")
        if isinstance(d, dict):
            size += sys.getsizeof(d)                    # the attribute table itself is memory too
            kids.extend(d.values())
    except Exception:                                   # noqa: BLE001
        pass
    for cls in type(o).__mro__:
        slots = cls.__dict__.get("__slots__", ())
        for s in (slots,) if isinstance(slots, str) else slots:
            if s in ("__dict__", "__weakref__"):
                continue
            try:
                kids.append(object.__getattribute__(o, s))
            except Exception:                           # noqa: BLE001
                pass
    return size, kids


def _roots(task_coros: list[tuple[str, object]], prefixes: tuple[str, ...]) -> list[tuple[str, object]]:
    """Module globals first (a cache is charged to the module that owns it), then class-level
    attributes of the app's classes, then the locals of every frame in each running task."""
    import types
    roots: list[tuple[str, object]] = []
    for name, mod in sorted(sys.modules.items()):
        if mod is None or not name.startswith(prefixes):
            continue
        try:
            items = list(vars(mod).items())
        except Exception:                               # noqa: BLE001
            continue
        for attr, val in items:
            if attr.startswith("__"):
                continue
            if isinstance(val, type) and getattr(val, "__module__", None) == name:
                for k, v in list(vars(val).items()):
                    if not k.startswith("__") and not callable(v) and not isinstance(
                            v, (property, staticmethod, classmethod)):
                        roots.append((f"{name}.{val.__name__}.{k}", v))
                continue
            if isinstance(val, (types.ModuleType, type, types.FunctionType, types.BuiltinFunctionType)):
                continue
            roots.append((f"{name}.{attr}", val))
    for task_name, coro in task_coros:
        c, depth = coro, 0
        while c is not None and depth < 12:
            frame = getattr(c, "cr_frame", None) or getattr(c, "gi_frame", None)
            if frame is not None:
                code = frame.f_code
                label = f"task:{task_name}:{code.co_filename.rsplit('/', 1)[-1]}:{code.co_name}"
                try:
                    for k, v in list(frame.f_locals.items()):
                        roots.append((f"{label}.{k}", v))
                except Exception:                       # noqa: BLE001
                    pass
            c = getattr(c, "cr_await", None) or getattr(c, "gi_yieldfrom", None)
            depth += 1
    return roots


def holders_report(types_wanted: list[str], task_coros: list[tuple[str, object]], top: int = 25,
                   max_nodes: int = 6_000_000, max_seconds: float = 90.0,
                   prefixes: tuple[str, ...] = ("app.", "tradingai_shared")) -> dict:
    """Charge every object reachable from the app's roots to the first root that reaches it."""
    t0 = time.monotonic()
    wanted = set(types_wanted)
    in_heap = {t: 0 for t in wanted}
    for o in gc.get_objects():
        n = type(o).__name__
        if n in in_heap:
            in_heap[n] += 1
    seen: set[int] = set()
    rows: list[dict] = []
    nodes, budget_hit = 0, False
    for label, root in _roots(task_coros, prefixes):
        if id(root) in seen or isinstance(root, _LEAF_TYPES):
            continue
        size, objs, counts = 0, 0, dict.fromkeys(wanted, 0)
        stack = [root]
        while stack:
            o = stack.pop()
            oid = id(o)
            if oid in seen:
                continue
            seen.add(oid)
            nodes += 1
            tn = type(o).__name__
            if tn in counts:
                counts[tn] += 1
            s, kids = _size_and_children(o)
            size += s
            objs += 1
            for k in kids:
                if id(k) not in seen:
                    stack.append(k)
            if nodes >= max_nodes or time.monotonic() - t0 > max_seconds:
                budget_hit = True
                break
        if objs > 1 or any(counts.values()):
            rows.append({"root": label, "mb": round(size / 1048576, 2), "objects": objs,
                         "counts": {k: v for k, v in counts.items() if v}})
        if budget_hit:
            break
    rows.sort(key=lambda r: r["mb"], reverse=True)
    reached = {t: sum(r["counts"].get(t, 0) for r in rows) for t in wanted}
    return {"took_s": round(time.monotonic() - t0, 1), "nodes": nodes, "budget_hit": budget_hit,
            "types": {t: {"in_heap": in_heap[t], "reached": reached[t]} for t in sorted(wanted)},
            "total_mb_reached": round(sum(r["mb"] for r in rows), 1), "holders": rows[:top]}


# The walk remembers every object it has visited (~60 bytes each: about 100 MB for the 1.6
# million objects of a fresh worker). Run on a worker already near its limit, that alone would
# push it into swap — so it needs this much headroom unless forced.
HOLDERS_MIN_HEADROOM_MB = float(os.getenv("DIAG_HOLDERS_MIN_HEADROOM_MB", "200"))


@router.get("/memory/holders")
async def memory_holders(types: str = Query("Bar,set,dict,list", description="type names to count"),
                         top: int = Query(25, ge=1, le=200),
                         max_seconds: float = Query(90.0, ge=1, le=600),
                         force: bool = Query(False, description="run even with little headroom"),
                         _user: dict = Depends(get_current_user)):
    """Which globals and task locals keep the heap alive. COSTLY: walks every reachable app
    object (tens of seconds, in a worker thread, ~100 MB of bookkeeping). Read-only; meant for a
    quiet hour — the scheduled census below is the cheap record of the busy ones."""
    import asyncio
    proc = _proc_memory()
    headroom = proc.get("headroom_mb")
    if not force and headroom is not None and headroom < HOLDERS_MIN_HEADROOM_MB:
        return {"refused": True, "process": proc,
                "why": f"{headroom:.0f} MB of headroom; the walk needs ~{HOLDERS_MIN_HEADROOM_MB:.0f}. Run it at a "
                       "quiet hour, read /memory/snapshots, or pass force=true."}
    task_coros = [(t.get_name(), t.get_coro()) for t in asyncio.all_tasks()]
    wanted = [t.strip() for t in types.split(",") if t.strip()]
    return await asyncio.to_thread(holders_report, wanted, task_coros, top, 6_000_000, max_seconds)


# ── the scheduled census ─────────────────────────────────────────────────────────
#
# The footprint climbs from ~225 MB at boot to the 800 MB limit within one trading day and is
# back at the floor after every deploy, so the moment worth measuring is when nobody is
# looking. Twice each trading day the process records, cheaply, what it holds: its memory, the
# type histogram, and every container of 1,000+ items held by an app module (top-level length
# only — no deep walk). A container that grows day after day is the leak.

SNAPSHOT_SLOTS_IST = tuple(t.strip() for t in os.getenv("DIAG_SNAPSHOT_SLOTS", "15:45,22:00").split(",") if t.strip())
SNAPSHOT_KEEP = 40
SNAPSHOTS_ENABLED = os.getenv("DIAG_MEMORY_SNAPSHOTS", "1").lower() not in ("0", "false", "")
_SNAPSHOT_TASKS: set = set()


def shallow_census(min_len: int = 1000, top: int = 40,
                   prefixes: tuple[str, ...] = ("app.", "tradingai_shared")) -> list[dict]:
    """Every app-module container (and attribute of a module-level object) with >= `min_len`
    items, by top-level length. Cheap: no recursion, nothing walked."""
    import types
    from collections import deque
    sized = (dict, list, set, frozenset, tuple, deque)
    rows: list[dict] = []
    for name, mod in list(sys.modules.items()):
        if mod is None or not name.startswith(prefixes):
            continue
        try:
            items = list(vars(mod).items())
        except Exception:                               # noqa: BLE001
            continue
        for attr, val in items:
            if attr.startswith("__") or isinstance(val, (types.ModuleType, type, types.FunctionType,
                                                         types.BuiltinFunctionType)):
                continue
            cands = [(f"{name}.{attr}", val)]
            if not isinstance(val, sized) and not _never_enter(val):
                try:
                    cands += [(f"{name}.{attr}.{k}", v)
                              for k, v in list(object.__getattribute__(val, "__dict__").items())]
                except Exception:                       # noqa: BLE001
                    pass
            for label, obj in cands:
                if isinstance(obj, sized):
                    try:
                        n = len(obj)
                    except Exception:                   # noqa: BLE001
                        continue
                    if n >= min_len:
                        rows.append({"holder": label, "type": type(obj).__name__, "len": n})
    rows.sort(key=lambda r: r["len"], reverse=True)
    return rows[:top]


def _type_histogram(top: int = 25) -> dict:
    hist: dict[str, int] = {}
    for o in gc.get_objects():
        n = type(o).__name__
        hist[n] = hist.get(n, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: kv[1], reverse=True)[:top])


async def take_snapshot(slot: str, coll=None) -> dict:
    """One census, stored; the oldest beyond SNAPSHOT_KEEP are dropped."""
    import asyncio
    from datetime import datetime, timezone
    if coll is None:
        from app.core.db import db
        coll = db["diagnostics_memory_snapshots"]
    census = await asyncio.to_thread(shallow_census)
    doc = {"at": datetime.now(timezone.utc), "slot": slot, "uptime_hours": round((time.time() - _STARTED) / 3600, 2),
           "process": _proc_memory(), "objects": await asyncio.to_thread(_type_histogram),
           "containers": census, "caches": _cache_sizes()}
    await coll.insert_one(doc)
    old = [d["_id"] async for d in coll.find({}, {"_id": 1}).sort("at", -1).skip(SNAPSHOT_KEEP)]
    if old:
        await coll.delete_many({"_id": {"$in": old}})
    return doc


def _due_slots(now, done: set) -> list[str]:
    """The slots whose half-hour window `now` falls in and that have not been taken today."""
    from datetime import datetime, timedelta
    hhmm = now.strftime("%H:%M")
    out = []
    for slot in SNAPSHOT_SLOTS_IST:
        late = (datetime.strptime(slot, "%H:%M") + timedelta(minutes=30)).strftime("%H:%M")
        if f"{now.date()}:{slot}" not in done and slot <= hhmm < late:
            out.append(slot)
    return out


async def _snapshot_loop() -> None:
    import asyncio
    import logging
    from datetime import datetime, timedelta, timezone
    ist = timezone(timedelta(hours=5, minutes=30))
    done: set[str] = set()
    while True:
        try:
            from app.services import market_calendar
            now = datetime.now(ist)
            if market_calendar.is_trading_day(now):
                for slot in _due_slots(now, done):
                    done.add(f"{now.date()}:{slot}")
                    await take_snapshot(slot)
        except Exception:                               # noqa: BLE001 - a census must never take anything down
            logging.getLogger("diagnostics").warning("memory snapshot failed", exc_info=True)
        await asyncio.sleep(60)


async def _start_snapshots() -> None:
    """Started by this router's own startup handler (FastAPI runs a router's handlers when the
    app includes it), so main.py needs no edit. Never raises."""
    import asyncio
    try:
        if SNAPSHOTS_ENABLED:
            _SNAPSHOT_TASKS.add(asyncio.create_task(_snapshot_loop()))
    except Exception:                                   # noqa: BLE001
        pass


router.add_event_handler("startup", _start_snapshots)


@router.get("/memory/snapshots")
async def memory_snapshots(limit: int = Query(10, ge=1, le=SNAPSHOT_KEEP),
                           _user: dict = Depends(get_current_user)):
    """The stored censuses, newest first: process memory, type histogram, large containers."""
    from app.core.db import db
    rows = []
    async for d in db["diagnostics_memory_snapshots"].find({}).sort("at", -1).limit(limit):
        d["_id"] = str(d["_id"])
        rows.append(d)
    return {"slots_ist": list(SNAPSHOT_SLOTS_IST), "enabled": SNAPSHOTS_ENABLED, "snapshots": rows}


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
