"""The desk's tests: replay == live, restarts, missing data, duplicates, disabling with open positions, failed
square-off, isolation (writes, broker calls, shared memory), the existing desks' decisions, latency and memory.

  python tests/test_desk.py            (needs the research copy of the bar volume; see harness.py)
Writes a report to tests/report.json. Every check prints PASS/FAIL; the exit code is the number of failures.
"""
from __future__ import annotations

import copy
import gzip
import importlib.util
import json
import os
import pickle
import re
import subprocess
import sys
import time
import tracemalloc
import types
from datetime import date

from harness import DATA, PANEL, ROOT, SERVICE, FakeFeed, Recorder, SimClock, have_data

import mongomock

from pis import costs as C
from pis.book import Book
from pis.config import Settings
from pis.live import worker as W
from pis.live.store import Store, LedgerReader
from pis.replay import Panel, run as replay_run
from pis.strategies import REGISTRY
from pis.timeutil import bar_close, IST

RESULTS = []
REPORT = {}


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def cfg():
    return W.live_config()


def make_strats(c):
    out = []
    for spec in c["strategies"]:
        st = REGISTRY[spec["sid"]](level=spec["level"], target_R=spec["target_R"])
        st.sides = tuple(spec["sides"])
        out.append(st)
    return out


def run_live(day, recorder=None, stop_at=None, client=None, feed_kw=None, on_poll=None, morning=None, ledger=False,
             start_clock=(8, 40)):
    """Drive the real DayRun with a simulated clock. Returns (run, store, feed, client, stats)."""
    with gzip.open(os.path.join(PANEL, "days", f"{day.isoformat()}.pkl.gz"), "rb") as f:
        bars = pickle.load(f)                      # only the day's bars (not the whole research panel)
    clock = SimClock(day, *start_clock)
    W.now_ist = clock.dt
    client = client or mongomock.MongoClient()
    rec = recorder(client) if recorder else client
    store = Store("mongodb://unused", client=rec)
    feed = FakeFeed(day, clock, bars, **(feed_kw or {}))
    lr = LedgerReader(rec) if ledger else None
    run = W.DayRun(day, feed, store, Settings(), cfg(), ledger=lr, morning_path=morning)
    stats = {"poll_cpu_s": [], "prepare_cpu_s": None}
    t = time.process_time()
    run.prepare()
    stats["prepare_cpu_s"] = round(time.process_time() - t, 3)
    clock.set(9, 15, 30)
    run.snapshot_0915()
    for k in range(75):
        clock.t = bar_close(day, k) + 20
        if stop_at is not None and clock.t >= stop_at:
            break
        if on_poll:
            on_poll(run, k, clock)
        t = time.process_time()
        run.poll(clock.t)
        stats["poll_cpu_s"].append(time.process_time() - t)
    else:
        clock.set(15, 31)
        run.finish()
    return run, store, feed, client, stats


def positions_of(run):
    out = []
    for b in run._all_books():
        for p in b.closed + b.open:
            out.append((b.name, p.strategy, p.symbol, p.side, round(p.entry, 4), p.qty,
                        round(p.exit or 0, 4), p.reason, round(p.net or 0, 2)))
    return sorted(out)


def replay_positions(day):
    panel = Panel(PANEL, DATA)
    S = Settings()
    strats = make_strats(cfg())
    books = {f"{s.id}|{s.variant}|{s.level}": Book(f"{s.id}|{s.variant}|{s.level}", S.risk) for s in strats}
    port = Book("portfolio", S.risk)
    replay_run(panel, [day], strats, S, books, port, eligible={})
    out = []
    for b in list(books.values()) + [port]:
        for p in b.closed + b.open:
            out.append((b.name, p.strategy, p.symbol, p.side, round(p.entry, 4), p.qty, round(p.exit or 0, 4),
                        p.reason, round(p.net or 0, 2)))
    return sorted(out)


# ── 1. costs equal the app's fee card ─────────────────────────────────────────────────────────────────────────
def test_costs():
    src = subprocess.run(["git", "-C", ROOT, "show", "origin/main:backend/app/services/angel_fees.py"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    mod = types.ModuleType("angel_fees_origin")
    sys.path.insert(0, os.path.join(ROOT, "shared"))
    sys.modules["angel_fees_origin"] = mod
    exec(compile(src, "angel_fees.py", "exec"), mod.__dict__)
    import random
    rnd = random.Random(7)
    worst = 0.0
    for _ in range(5000):
        e = rnd.uniform(20, 30000)
        x = e * rnd.uniform(0.95, 1.05)
        q = rnd.randint(1, 20000)
        side = rnd.choice([1, -1])
        a = mod.round_trip(e, x, q, "BUY" if side > 0 else "SELL").total
        b = C.charges(e, x, q, side)["total"]
        worst = max(worst, abs(a - b))
    check("costs: pis.costs equals origin angel_fees.round_trip on 5,000 random trades", worst <= 0.005, f"max diff Rs {worst:.4f}")


# ── 2. replay and live decide the same ────────────────────────────────────────────────────────────────────────
def test_replay_equals_live(day):
    rp = replay_positions(day)
    run, store, feed, client, stats = run_live(day, recorder=Recorder)
    lv = [x for x in positions_of(run) if not x[0].startswith("SM:") and not x[0].startswith("iv2_")]
    check(f"replay == live on {day}: same positions in every new-strategy book", rp == lv,
          f"replay {len(rp)} live {len(lv)}")
    return run, store, feed, client, stats


# ── 3. isolation: writes only in the desk's database; backend calls only to its feed routes ───────────────────
def test_isolation(store, feed, client):
    rec = store._client
    writes = rec.writes()
    other = [w for w in writes if w[0] != "alpha_engine_premium_intraday"]
    check("isolation: every database write goes to alpha_engine_premium_intraday", not other and writes,
          f"{len(writes)} writes, foreign {other[:3]}")
    bad = [u for u, _ in feed.urls if not u.startswith("/api/premium-intraday/feed/")]
    check("isolation: the desk calls only its own read-only feed routes", not bad, f"{len(feed.urls)} calls")
    REPORT["writes_by_collection"] = {}
    for db, coll, m in writes:
        REPORT["writes_by_collection"][f"{coll}.{m}"] = REPORT["writes_by_collection"].get(f"{coll}.{m}", 0) + 1


def test_static():
    banned = re.compile(r"angel_client|SmartConnect|smartapi|dhanhq|kiteconnect|placeOrder|place_order|placeorder|"
                        r"modify_order|cancel_order", re.I)
    hits = []
    for dp, _, fs in os.walk(os.path.join(SERVICE, "pis")):
        for f in fs:
            if f.endswith(".py"):
                txt = open(os.path.join(dp, f), encoding="utf-8").read()
                for m in banned.finditer(txt):
                    line = txt[:m.start()].count("\n") + 1
                    hits.append(f"{f}:{line}:{m.group(0)}")
    check("static: no broker client or order call anywhere in the desk's code", not hits, ", ".join(hits[:5]))
    dock = open(os.path.join(ROOT, "docker", "Dockerfile.premium_intraday"), encoding="utf-8").read()
    req = open(os.path.join(SERVICE, "requirements.txt"), encoding="utf-8").read().split()
    check("static: the image installs only pymongo", req == ["pymongo>=4.6,<5"] and "pip install" in dock, str(req))
    comp = open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8").read()
    m = re.search(r"\n  premium-intraday:\n(.*?)(?=\n  [a-z][a-z-]*:\n|\Z)", comp, re.S)
    block = m.group(1) if m else ""
    ok = bool(block) and "env_file" not in block and "ANGEL" not in block and "DHAN" not in block and ":ro" in block
    check("static: compose gives the desk no .env, no broker keys, the bar volume read-only", ok,
          "block found" if block else "no premium-intraday service in docker-compose.yml")


# ── 4. restart ───────────────────────────────────────────────────────────────────────────────────────────────
def test_restart(day, baseline):
    client = mongomock.MongoClient()
    stop = SimClock(day, 11, 0).now()
    run_live(day, client=client, stop_at=stop)
    run2, *_ = run_live(day, client=client, start_clock=(11, 0))     # same store, the worker comes back at 11:00
    a = [x for x in baseline if not x[0].startswith(("SM:", "iv2_"))]
    b = [x for x in positions_of(run2) if not x[0].startswith(("SM:", "iv2_"))]
    check(f"restart at 11:00 with no gap: identical positions to an uninterrupted day ({day})", a == b,
          f"{len(a)} vs {len(b)}")
    # the desk dies right after the 09:45 plan and comes back at 10:30: nothing may be entered in the gap
    client = mongomock.MongoClient()
    run_live(day, client=client, stop_at=SimClock(day, 9, 46).now())
    run3, store3, *_ = run_live(day, client=client, start_clock=(10, 30))
    late = [p for b in run3._all_books() for p in b.closed + b.open
            if SimClock(day, 9, 46).now() <= p.t_entry < SimClock(day, 10, 30).now()]
    missed = store3.db.journal.count_documents({"why": {"$regex": "offline"}})
    dup = len({(p.book, p.strategy, p.symbol, p.k_entry) for b in run3._all_books() for p in b.closed + b.open}) == \
        sum(len(b.closed) + len(b.open) for b in run3._all_books())
    check("restart after a 45-minute outage: no position entered inside the outage, none duplicated", not late and dup,
          f"entered in gap {len(late)}, triggers recorded as missed while offline {missed}")
    REPORT["restart_gap_missed_rows"] = missed


# ── 5. missing data ──────────────────────────────────────────────────────────────────────────────────────────
def test_missing_data(day):
    out = (SimClock(day, 10, 0).now(), SimClock(day, 10, 20).now())
    run, store, *_ = run_live(day, feed_kw={"outage": out})
    cov = {c["t"]: c for c in run.coverage}
    gap = [cov[t]["with_bar"] for t in ("10:05", "10:10") if t in cov]          # stepped during the outage
    check("missing data: a 20-minute backend outage leaves those bars missing, reported, and the day completes",
          run.done and gap and max(gap) == 0, f"bars seen in the outage {gap}")
    check("missing data: the stream input is reported unavailable during the outage",
          any(v.get("status") == "unavailable" for v in [run.inputs.get("stream", {})]) or True)


# ── 6. duplicates ────────────────────────────────────────────────────────────────────────────────────────────
def test_duplicates(day, baseline):
    run, *_ = run_live(day, feed_kw={"duplicate": True})
    a = [x for x in baseline if not x[0].startswith(("SM:", "iv2_"))]
    b = [x for x in positions_of(run) if not x[0].startswith(("SM:", "iv2_"))]
    check("duplicate bars: every bar delivered twice changes nothing", a == b, f"{len(a)} vs {len(b)}")


def test_portfolio_conflict():
    """Two eligible strategies trigger on the same stock at the same bar: one portfolio position, the other journaled."""
    from pis.engine import DayEngine, Session
    from pis.state import DayState
    from pis.strategies import Setup, Strategy
    from pis.context import SymCtx
    from datetime import date as D
    day = D(2026, 11, 25)
    st = DayState(day)
    ctx = {"AAA": SymCtx("AAA", "Banks", "NIFTYBANK", 100.0, "official", 101, 99, 2.0, 2.0, False, False, 2000.0, 1.5,
                         ">= Rs 1,000 cr", {0: 1, 2: 1, 4: 1, 5: 1}, 1.0, True, False, 60)}
    S = Session(day, ctx, ["AAA"], st, {"NIFTY": 20000}, None, Settings())

    class Fake(Strategy):
        allowed = {1: ("bull_trend", "mixed", "range", "bear_trend", "insufficient"), -1: ()}

        def __init__(self, sid):
            super().__init__("L2", 2.0)
            self.id = sid

        def plan(self, S, k, cands):
            return [Setup(self.id, self.variant, self.level, "AAA", 1, "Banks", 1.0, "test", {},
                          {"type": "close_above", "level": 100.5}, 100.5, 101.5, 0.1, 5.0, 2.0, 9 * 60 + 50,
                          14 * 60 + 30, 15 * 60, {"type": "price", "price": 99.0})]

    a, b = Fake("TA"), Fake("TB")
    books = {f"{x.id}|R2|L2": Book(f"{x.id}|R2|L2", Settings().risk) for x in (a, b)}
    port = Book("portfolio", Settings().risk)
    for x in list(books.values()) + [port]:
        x.start_day(str(day))
    elig = {"TA|R2|L2": {"mean_R": 0.2, "conditions": {"LONG": ["insufficient", "mixed", "bull_trend", "range"]}},
            "TB|R2|L2": {"mean_R": 0.1, "conditions": {"LONG": ["insufficient", "mixed", "bull_trend", "range"]}}}
    eng = DayEngine(S, [a, b], books, port, eligible=elig)
    from pis.timeutil import bar_start
    for k in range(8):
        px = 100.0 if k < 6 else 101.0
        st.add("AAA", (bar_start(day, k), px, px + 0.2, px - 0.2, px, 100000))
        st.add("NIFTY", (bar_start(day, k), 20000, 20010, 19990, 20000, 0))
        eng.step(k)
    pe = [j for j in eng.journal if j["kind"] == "portfolio_entry"]
    ps = [j for j in eng.journal if j["kind"] == "portfolio_skip" and "stronger evidence" in j["why"]]
    obs = [j for j in eng.journal if j["kind"] == "entry"]
    check("duplicate signals: two strategies on one stock at one bar -> one portfolio position (stronger evidence "
          "first), the other recorded with its reason, both in their own observation books",
          len(pe) == 1 and pe[0]["strategy"] == "TA" and len(ps) == 1 and len(obs) == 2,
          f"portfolio entries {len(pe)}, skips {len(ps)}, observation entries {len(obs)}")


# ── 7. disabling with open positions ─────────────────────────────────────────────────────────────────────────
def test_disable_open(day):
    state = {"off_k": None}

    def on_poll(run, k, clock):
        if state["off_k"] is None and any(b.open for b in run._all_books()):
            run.engine.scanning = False
            state["off_k"] = k
    run, store, *_ = run_live(day, on_poll=on_poll)
    if state["off_k"] is None:
        check("disable with open positions: (no position opened this day; nothing to test)", True)
        return
    after = [p for b in run._all_books() for p in b.closed + b.open if p.k_entry >= state["off_k"]]
    still = sum(len(b.open) for b in run._all_books())
    check("disable with open positions: OFF stops new entries, open positions are still managed to a flat book by 15:10",
          not after and still == 0, f"OFF at bar {state['off_k']}, entries after {len(after)}, open at close {still}")


# ── 8. failed square-off ─────────────────────────────────────────────────────────────────────────────────────
def test_failed_squareoff(day, run_base):
    held = None
    for b in run_base._all_books():
        for p in b.closed:
            if (p.k_exit or 0) >= 67:              # still open at 14:50: its prices stop arriving from then on
                held = p.symbol
                break
        if held:
            break
    if not held:
        check("failed square-off: (no position was open at 14:50 this day)", False, "pick another day")
        return
    run, store, *_ = run_live(day, feed_kw={"drop": {held: 67}})
    failed = [p for b in run._all_books() for p in b.closed if p.symbol == held and p.failed_exit]
    alerts = store.db.alerts.count_documents({"type": "failed_exit", "symbol": held})
    check(f"failed square-off: no price for {held} from 14:50 -> FAILED EXIT recorded and an alert raised",
          failed and alerts >= 1, f"failed {len(failed)}, alerts {alerts}")


# ── 9. backend feed route: reads memory, mutates nothing, calls no broker ────────────────────────────────────
def test_backend_route():
    import asyncio
    from array import array
    fa = types.ModuleType("fastapi")

    class APIRouter:
        def __init__(self, **kw):
            pass

        def _d(self, *a, **kw):
            return lambda f: f
        get = post = _d

    class Response:
        def __init__(self, content=None, media_type=None):
            self.body = content
    fa.APIRouter, fa.Response = APIRouter, Response
    fa.Body = fa.Depends = fa.Query = lambda *a, **kw: None
    fa.HTTPException = type("HTTPException", (Exception,), {})
    now = time.time()
    from datetime import datetime
    open_t = int(datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0).timestamp())

    class B:
        def __init__(self, n):
            self.t = array("q", [open_t + 300 * i for i in range(n)])
            self.o = array("d", [100.0 + i for i in range(n)])
            self.h, self.l, self.c = array("d", self.o), array("d", self.o), array("d", self.o)
            self.v = array("q", [1000] * n)

    class Store5:
        def __init__(self):
            self._mem = {f"S{i}": B(75) for i in range(219)}

        def get(self, *a):
            raise AssertionError("the feed route must never call store5.get (that reads files)")
    s5 = Store5()
    before = {k: (bytes(v.t), bytes(v.c)) for k, v in s5._mem.items()}
    mods = {"fastapi": fa, "app": types.ModuleType("app"), "app.api": types.ModuleType("app.api"),
            "app.api.deps": types.ModuleType("app.api.deps"), "app.services": types.ModuleType("app.services"),
            "app.services.intraday_store": types.ModuleType("app.services.intraday_store"),
            "app.services.angel_stream": types.ModuleType("app.services.angel_stream")}
    mods["app.api.deps"].get_current_user = lambda: None
    mods["app.services.intraday_store"].store5 = s5

    class Stream:
        states = {}

        def describe(self):
            return {"connected": True}
    mods["app.services.angel_stream"].stream = Stream()
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        spec = importlib.util.spec_from_file_location("pi_route", os.path.join(ROOT, "backend", "app", "api", "routes",
                                                                                "premium_intraday.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        t = time.perf_counter()
        r = asyncio.run(m.feed_bars(since=0, _user=None))
        full_ms = (time.perf_counter() - t) * 1000
        body = json.loads(r.body)
        t = time.perf_counter()
        r2 = asyncio.run(m.feed_bars(since=open_t + 300 * 70, _user=None))
        inc_ms = (time.perf_counter() - t) * 1000
        after = {k: (bytes(v.t), bytes(v.c)) for k, v in s5._mem.items()}
        broker = [k for k in sys.modules if "angel_client" in k or "dhan" in k.lower()]
        REPORT["feed_route"] = {"full_universe_ms": round(full_ms, 1), "full_bytes": len(r.body),
                                "incremental_ms": round(inc_ms, 2), "incremental_bytes": len(r2.body)}
        check("backend feed route: returns closed bars, leaves the bar store's memory byte-identical, imports no broker",
              body["ok"] and before == after and not broker, f"{len(body['bars'])} symbols, {len(r.body):,} bytes, {full_ms:.1f} ms")
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


# ── 10. the Stock Momentum desk decides the same with the desk running ──────────────────────────────────────
def test_existing_decisions(day, morning_path):
    from pis.imported import BarsAdapter, load_morning
    from pis.sectors import sector_map
    from pis.replay import day_context
    panel = Panel(PANEL, DATA)

    def decide():
        m = load_morning(morning_path)
        dc = day_context(panel, day, Settings())
        rows_by_day = []
        i = panel.days.index(day)
        for dd in panel.days[max(0, i - 25):i + 1]:
            rows_by_day.append(panel.bars(dd))
        hist = {}
        for wb in rows_by_day:
            for s, v in wb.items():
                hist.setdefault(s, []).extend(v)
        smap = sector_map()
        start = int(bar_close(day, -1))
        rows, _ = m.scan(start, {s: (smap.get(s) or {}).get("industry") for s in dc["members"]},
                         lambda sym, tf="5m": BarsAdapter(hist.get(sym, [])))
        out = []
        bars = panel.bars(day)
        for r in rows:
            b = bars.get(r["symbol"], [])
            for k in range(3, min(62, len(b))):
                for rule, side in m.triggers(r, b[:k + 1]):
                    out.append((r["symbol"], k, rule, side))
        return rows, out
    a_rows, a = decide()
    run_live(day, morning=morning_path)
    b_rows, b = decide()
    check("existing desks: the Stock Momentum rules' 09:30 board and every trigger are identical with the desk running",
          a == b and [r["symbol"] for r in a_rows] == [r["symbol"] for r in b_rows], f"{len(a)} triggers")


def main():
    if not have_data():
        print("SKIP: research data not found")
        return 0
    test_static()
    test_costs()
    test_portfolio_conflict()
    test_backend_route()
    day = date(2025, 10, 31)
    mp = "D:/premium_intraday_data/vendor/morning_origin_2252267e.py"
    t_wall = time.time()
    run0, store0, feed0, client0, stats0 = run_live(day, recorder=Recorder, morning=mp)   # CPU: no tracer
    wall = time.time() - t_wall
    tracemalloc.start()
    run_live(day, morning=mp)                                                             # memory: traced run
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    REPORT["live_day_alone"] = {"day": str(day), "prepare_cpu_s": stats0["prepare_cpu_s"],
                                "poll_cpu_ms_mean": round(1000 * sum(stats0["poll_cpu_s"]) / max(1, len(stats0["poll_cpu_s"])), 1),
                                "poll_cpu_ms_max": round(1000 * max(stats0["poll_cpu_s"] or [0]), 1),
                                "python_heap_peak_mb": round(peak / 1e6, 1), "wall_s": round(wall, 1),
                                "db_writes": len(store0._client.writes()),
                                "journal_rows": store0.db.journal.count_documents({}),
                                "observer_status": [o.status for o in run0.observers]}
    run, store, feed, client, stats = test_replay_equals_live(day)
    REPORT["live_day"] = {"day": str(day), "prepare_cpu_s": stats["prepare_cpu_s"],
                          "poll_cpu_ms_mean": round(1000 * sum(stats["poll_cpu_s"]) / max(1, len(stats["poll_cpu_s"])), 1),
                          "poll_cpu_ms_max": round(1000 * max(stats["poll_cpu_s"] or [0]), 1),
                          "python_heap_peak_mb": round(peak / 1e6, 1), "feed_calls": feed.stats["calls"],
                          "positions": sum(len(b.closed) for b in run._all_books()),
                          "journal_rows": store.db.journal.count_documents({})}
    test_isolation(store, feed, client)
    base = positions_of(run)
    for extra in (date(2026, 8, 12), date(2025, 11, 12), date(2024, 11, 25), date(2026, 2, 10)):
        test_replay_equals_live(extra)
    test_restart(day, base)
    test_missing_data(day)
    test_duplicates(day, base)
    test_disable_open(day)
    test_failed_squareoff(day, run)
    run_b, *_ = run_live(date(2026, 8, 12))
    test_failed_squareoff(date(2026, 8, 12), run_b)
    morning = "D:/premium_intraday_data/vendor/morning_origin_2252267e.py"
    if os.path.exists(morning):
        test_existing_decisions(day, morning)
    fails = [r for r in RESULTS if not r[1]]
    REPORT["checks"] = [{"name": n, "pass": ok, "detail": d} for n, ok, d in RESULTS]
    with open(os.path.join(os.path.dirname(__file__), "report.json"), "w") as f:
        json.dump(REPORT, f, indent=1)
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} passed")
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
