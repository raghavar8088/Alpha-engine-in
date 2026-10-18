"""Verify the memory diagnostics — the holders walk, the census, the snapshot schedule — offline.

Run:  python backend/tests/diagnostics/verify_memory_tools.py

Why these exist (2026-10-18): the worker sat at its 800 MB limit with 349,802 Bar objects alive
and the type histogram could not say who held them — four modules define a class called Bar.
`holders_report` charges every reachable object to the first app global or task local that
reaches it; `shallow_census` records, twice a trading day, which app containers are large, so
one that grows day after day stands out without anyone watching at the peak.
"""

import asyncio
import os
import sys
import time
import types
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200"   # never the real cluster
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "shared"))
sys.path.insert(0, str(ROOT))

# The router module only needs FastAPI's decorators; the test runs where FastAPI may not be installed.
try:
    import fastapi  # noqa: F401
except ImportError:
    fake = types.ModuleType("fastapi")

    class _Router:
        def __init__(self, *a, **k):
            self.on_startup = []

        def get(self, *a, **k):
            return lambda f: f

        def add_event_handler(self, kind, fn):
            self.on_startup.append(fn)
    fake.APIRouter = _Router
    fake.Depends = lambda *a, **k: None
    fake.Query = lambda default=None, **k: default
    sys.modules["fastapi"] = fake
    deps = types.ModuleType("app.api.deps")
    deps.get_current_user = lambda: None
    sys.modules["app.api.deps"] = deps

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("diagnostics_under_test", ROOT / "app" / "api" / "routes" / "diagnostics.py")
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)

FAILURES: list[str] = []


def check(label: str, ok: bool, detail="") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -- ' + str(detail)) if detail not in ('', None) else ''}")
    if not ok:
        FAILURES.append(label)


@dataclass
class Bar:
    ts: int
    o: float
    h: float
    l: float
    c: float


class SlotBar:
    __slots__ = ("ts", "c")

    def __init__(self, ts, c):
        self.ts, self.c = ts, c


class Engine:
    def __init__(self):
        self.series = {"Y": [Bar(i, 1, 1, 1, 1) for i in range(3000)]}
        self.seen = set(range(1200))


m1 = types.ModuleType("app.services.fake_cache")
m1._cache = {("X", "1d"): (time.time(), [Bar(i, 1.0, 2.0, 0.5, 1.5) for i in range(5000)])}
m1.small = {"a": 1}
sys.modules[m1.__name__] = m1
m2 = types.ModuleType("app.services.fake_engine")
m2.engine = Engine()
sys.modules[m2.__name__] = m2
m3 = types.ModuleType("app.services.fake_slots")
m3.bars = [SlotBar(i, float(i)) for i in range(2000)]
sys.modules[m3.__name__] = m3
PREFIX = ("app.services.fake",)

print("\nHOLDERS — every reachable object charged to the first global or task local that holds it")
print("-" * 90)


async def desk_loop():
    bars = [Bar(i, 1, 1, 1, 1) for i in range(1500)]    # a loop keeping a whole load in a local
    await asyncio.sleep(3600)
    return bars


async def walk():
    t = asyncio.create_task(desk_loop(), name="desk_loop")
    await asyncio.sleep(0.01)
    coros = [(x.get_name(), x.get_coro()) for x in asyncio.all_tasks()]
    rep = D.holders_report(["Bar", "SlotBar", "set"], coros, top=10, prefixes=PREFIX)
    t.cancel()
    return rep

rep = asyncio.run(walk())
by = {r["root"]: r for r in rep["holders"]}
check("a module cache: 5,000 Bars charged to app.services.fake_cache._cache",
      by.get("app.services.fake_cache._cache", {}).get("counts", {}).get("Bar") == 5000, by.get("app.services.fake_cache._cache"))
check("an engine object's attributes: 3,000 Bars and its set, charged to the engine",
      by.get("app.services.fake_engine.engine", {}).get("counts") == {"Bar": 3000, "set": 1},
      by.get("app.services.fake_engine.engine"))
loc = [r for r in rep["holders"] if r["root"].endswith(":desk_loop.bars")]
check("a running task's local: 1,500 Bars charged to task:desk_loop", bool(loc) and loc[0]["counts"].get("Bar") == 1500,
      loc)
check("every Bar in the heap is reached (none hidden)", rep["types"]["Bar"]["reached"] == rep["types"]["Bar"]["in_heap"],
      rep["types"]["Bar"])
slots_mb = by["app.services.fake_slots.bars"]["mb"] / 2000
dict_mb = by["app.services.fake_cache._cache"]["mb"] / 5000
check("a dict-based Bar costs more than a __slots__ one (its attribute table is counted)", dict_mb > slots_mb * 1.5,
      (round(dict_mb * 1e6), round(slots_mb * 1e6)))

print("\nCENSUS — large app containers by top-level length, nothing walked")
print("-" * 90)
rows = D.shallow_census(min_len=1000, prefixes=PREFIX)
holders = {r["holder"]: r["len"] for r in rows}
check("finds the module-level list (2,000) and the engine's set (1,200)",
      holders.get("app.services.fake_slots.bars") == 2000 and holders.get("app.services.fake_engine.engine.seen") == 1200,
      holders)
check("a 1-entry cache is a container of 1, not of the 5,000 Bars inside it — and is below the bar",
      "app.services.fake_cache._cache" not in holders and "app.services.fake_cache.small" not in holders, holders)

print("\nSNAPSHOTS — twice a trading day, kept to the last 40")
print("-" * 90)
IST = timezone(timedelta(hours=5, minutes=30))
day = datetime(2026, 10, 19, tzinfo=IST)
D.SNAPSHOT_SLOTS_IST = ("15:45", "22:00")
check("15:44 is too early; 15:45 and 16:14 are inside the window; 16:15 is past it",
      D._due_slots(day.replace(hour=15, minute=44), set()) == [] and
      D._due_slots(day.replace(hour=15, minute=45), set()) == ["15:45"] and
      D._due_slots(day.replace(hour=16, minute=14), set()) == ["15:45"] and
      D._due_slots(day.replace(hour=16, minute=15), set()) == [])
check("a slot already taken today is not taken again",
      D._due_slots(day.replace(hour=15, minute=50), {"2026-10-19:15:45"}) == [])


class FakeColl:
    def __init__(self):
        self.docs = []

    async def insert_one(self, d):
        d["_id"] = len(self.docs) + 1
        self.docs.append(d)

    def find(self, q, proj=None):
        coll = self

        class _C:
            def __init__(self):
                self.rows = list(coll.docs)

            def sort(self, key, direction):
                self.rows.sort(key=lambda d: d[key], reverse=direction < 0)
                return self

            def skip(self, n):
                self.rows = self.rows[n:]
                return self

            def __aiter__(self):
                async def gen():
                    for r in self.rows:
                        yield r
                return gen()
        return _C()

    async def delete_many(self, q):
        drop = set(q["_id"]["$in"])
        self.docs = [d for d in self.docs if d["_id"] not in drop]


coll = FakeColl()


async def many():
    for _k in range(45):
        await D.take_snapshot("15:45", coll=coll)
        await asyncio.sleep(0.02)                  # distinct timestamps even on a coarse clock
    return coll.docs

docs = asyncio.run(many())
check("a snapshot holds the process memory, the type histogram and the large containers",
      all(k in docs[-1] for k in ("process", "objects", "containers", "caches", "slot")), sorted(docs[-1].keys()))
check("45 snapshots taken, the newest 40 kept", len(docs) == 40 and docs[0]["_id"] == 6, (len(docs), docs[0]["_id"]))

print("\nGUARD — the deep walk refuses on a worker without headroom")
print("-" * 90)
D._proc_memory = lambda: {"VmRSS": 720.0, "limit_mb": 800.0, "headroom_mb": 80.0}
out = asyncio.run(D.memory_holders(types="Bar", top=5, max_seconds=5, force=False, _user=None))
check("80 MB of headroom: refused, with the reason", out.get("refused") is True and "headroom" in out.get("why", ""), out)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("all checks passed")
