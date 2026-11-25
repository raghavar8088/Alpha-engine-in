"""Offline checks of the NSE books the real-money Live Trading desk copies: cycle._run_first_nse, _stock_pass and run_live.

Run:  python premium-paper-service/test_live_nse.py

Since 25 Nov 2026 the backend's live_trading_engine copies six of these Equity intraday books into real Angel One orders
and names them in premium_meta 'live_priority_nse'. The quick pass ("live", every minute) runs and sizes those books
once per new finished 5-minute bar, through _stock_pass, the body the stocks pass runs every book with. No network,
database or market data is used: the feeds, the catalog, the runners and the ledger are recorders, so what is checked
is when the books run, which books run, and that the stocks pass still runs every book. That the quick pass computes
the same trades as the stocks pass was checked once on the box's real panel (25 Nov 2026, scratch equiv_test.py).
"""
import sys
import types
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import resource  # noqa: F401
except ImportError:             # Windows: cycle.py uses it only for its peak-memory note
    sys.modules["resource"] = types.ModuleType("resource")

import cycle  # noqa: E402
from settings import IST  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool, detail="") -> None:
    print(("PASS  " if ok else "FAIL  ") + label + ("" if ok else f"   [{detail}]"))
    if not ok:
        FAILS.append(label)


class Meta:
    """premium_meta, by _id: find_one and update_one ($set, upsert)."""

    def __init__(self, *docs):
        self.docs = {d["_id"]: dict(d) for d in docs}

    def find_one(self, q, *_a, **_k):
        return self.docs.get(q.get("_id"))

    def update_one(self, q, upd, upsert=False):
        d = self.docs.get(q["_id"])
        if d is None and upsert:
            d = self.docs[q["_id"]] = {"_id": q["_id"]}
        if d is not None:
            d.update(upd.get("$set") or {})


SIX = ["YT-23|NSE15", "SS-03|NSE5", "VWAP-U4|VWAP", "TW-01|NSE15", "DH-05|NSE5", "UP-03|NSE15"]
WED = datetime(2026, 11, 25, 11, 7, tzinfo=IST)            # a Wednesday, in the session
LAST = [1_795_574_100]
BARS = {"RELIANCE": [[LAST[0] - 300, 1, 2, 0.5, 1.5, 100], [LAST[0], 1, 2, 0.5, 1.5, 100]]}
calls: list = []


def today_bars(group):
    calls.append(("bars", group))
    return {"stocks": {k: [list(r[:-1]) + [r[-1]] for r in v] for k, v in BARS.items()} if BARS else {}}


class FakePanel:
    def __init__(self, live, now):
        calls.append(("panel", sorted(live or {})))
        self.disk_last = "2026-11-24"
        self.live_day = now.date().isoformat()
        self.days = ["2026-11-24", self.live_day]
        self.names = []


def stock_pass(db, now, panel, final, only=None, deadline=None):
    calls.append(("pass", sorted(only) if only is not None else None, final))
    return 3, {b.split("|")[0] for b in (only or SIX)}, {}


cycle.F.today_bars = today_bars
cycle.F.Panel = FakePanel
cycle.F.nse_final_day = lambda now, disk_last: "2026-11-24"
real_stock_pass = cycle._stock_pass
cycle._stock_pass = stock_pass


def db_with(*docs):
    return SimpleNamespace(premium_meta=Meta({"_id": "status"}, *docs))


def named(books=SIX):
    return {"_id": "live_priority_nse", "books": list(books), "at": 1.0, "by": "live_trading"}


# 1. nothing named: nothing runs, the backend's bars are not even read
calls.clear()
db = db_with()
errors: dict = {}
check("nothing named: no NSE book runs first", cycle._run_first_nse(db, WED, errors) == set() and calls == [], calls)

# 2. named, in the session, a new finished bar: the named books run through _stock_pass, once
calls.clear()
db = db_with(named())
done = cycle._run_first_nse(db, WED, errors)
check("named books run first through _stock_pass, only those",
      ("pass", sorted(SIX), "2026-11-24") in calls and done == {b.split("|")[0] for b in SIX}, calls)
check("…on the backend's bars of today (today_bars stocks) and a panel built from them",
      calls[0] == ("bars", "stocks") and calls[1] == ("panel", ["RELIANCE"]), calls[:2])
mark = db.premium_meta.docs.get("sig_first_nse") or {}
check("…and the last bar they ran through is remembered", mark.get("last") == LAST[0] and mark.get("trades") == 3, mark)
check("…with no error", errors == {}, errors)

# 3. the same bar again: nothing runs
calls.clear()
check("the same last bar again: nothing runs", cycle._run_first_nse(db, WED, errors) == set()
      and not any(c[0] == "pass" for c in calls), calls)

# 4. a new bar: they run again
LAST[0] += 300
BARS["RELIANCE"].append([LAST[0], 1, 2, 0.5, 1.5, 100])
calls.clear()
check("a new finished 5-minute bar: they run again", cycle._run_first_nse(db, WED, errors) != set()
      and any(c[0] == "pass" for c in calls), calls)

# 5. outside the session, at the weekend, before the paper start, with no bars: nothing runs
for label, now in (("before 09:20 IST", WED.replace(hour=9, minute=19)),
                   ("after 15:40 IST", WED.replace(hour=15, minute=41)),
                   ("on a Saturday", datetime(2026, 11, 28, 11, 7, tzinfo=IST))):
    calls.clear()
    LAST[0] += 300
    BARS["RELIANCE"].append([LAST[0], 1, 2, 0.5, 1.5, 100])
    check(f"{label}: nothing runs", cycle._run_first_nse(db_with(named()), now, {}) == set() and calls == [], calls)
saved_start = cycle.PAPER_START
cycle.PAPER_START = date(2026, 12, 1)
check("before the paper desk's start: nothing runs", cycle._run_first_nse(db_with(named()), WED, {}) == set())
cycle.PAPER_START = saved_start
saved = dict(BARS)
BARS.clear()
calls.clear()
check("no bars from the backend (a holiday, or the backend down): nothing runs",
      cycle._run_first_nse(db_with(named()), WED, {}) == set() and not any(c[0] == "pass" for c in calls), calls)
BARS.update(saved)

# 6. a failure is caught, reported, and leaves the marker alone
def broken(*a, **k):
    raise RuntimeError("panel unreadable")


cycle._stock_pass = broken
db = db_with(named())
errors = {}
LAST[0] += 300
BARS["RELIANCE"].append([LAST[0], 1, 2, 0.5, 1.5, 100])
check("a failure returns no books", cycle._run_first_nse(db, WED, errors) == set())
check("…is reported under 'first NSE books'", "panel unreadable" in errors.get("first NSE books", ""), errors)
check("…and the bar is not marked done, so the next pass tries again", "sig_first_nse" not in db.premium_meta.docs)
cycle._stock_pass = stock_pass

# 7. run_live: the Delta quick work first, then the NSE books with a time budget; both reported
import time as _t  # noqa: E402

order: list = []
budget: list = []
cycle._live_work = lambda db, errors, new: (order.append("delta"), {"TH-05"})[1]
saved_first = cycle._run_first_nse
cycle._run_first_nse = lambda db, now, errors, deadline=None: (order.append("nse"), budget.append(deadline),
                                                              {"YT-23", "SS-03"})[2]
t_before = _t.time()
info = cycle.run_live(db_with(named()), WED)
check("the quick pass runs the Delta work, then the NSE books", order == ["delta", "nse"], order)
check("…and reports both", info.get("first") == ["TH-05"] and info.get("first_nse") == ["SS-03", "YT-23"], info)
check("…the NSE books get a deadline NSE_BUDGET_S after the pass started (main.py kills a quick pass at 120 s)",
      budget and budget[0] is not None and t_before <= budget[0] - cycle.NSE_BUDGET_S <= _t.time()
      and cycle.NSE_BUDGET_S < 120, (budget, cycle.NSE_BUDGET_S))
cycle._run_first_nse = lambda db, now, errors, deadline=None: set()
info = cycle.run_live(db_with(), WED)
check("…with no NSE book run, the report is as before (no first_nse key)", "first_nse" not in info, info)
cycle._run_first_nse = saved_first

# 8. _stock_pass itself: `only` keeps the named books, None keeps every book (the stocks pass)
cycle._stock_pass = real_stock_pass
YT, YC = cycle.C.YT, sorted(cycle.C.YC_SOURCES)[0]
ACCTS = {"YT-23": SimpleNamespace(id="YT-23", source=YT), "NJ-14": SimpleNamespace(id="NJ-14", source=YC),
         "DH-05": SimpleNamespace(id="DH-05", source=YC), "VWAP-U4": SimpleNamespace(id="VWAP-U4", source="vwap"),
         "VWAP-A": SimpleNamespace(id="VWAP-A", source="vwap")}
cycle.C.books_in = lambda group: [(ACCTS["YT-23"], "NSE15", "V0"), (ACCTS["NJ-14"], "NSE5", "V0"),
                                  (ACCTS["DH-05"], "NSE5", "V0"), (ACCTS["VWAP-U4"], "VWAP", "U4"),
                                  (ACCTS["VWAP-A"], "VWAP", "A")]
ran: list = []
persisted: list = []
sized: list = []
cycle._from = lambda db, a, mk, overnight=False: date(2026, 11, 9)
cycle.replay_from = lambda db, acct, market, overnight: date(2026, 11, 9)
cycle._yc_stock_context = lambda pool, panel, now: ran.append(("ctx", sorted(a.id for a, *_ in pool))) or {}
cycle._fresh_only = lambda db, a, mk, docs: docs
cycle.R.run_yc = lambda sid, mk, m, cache, p=None, since_t=None: (ran.append(("yc", sid, m)), ([], {}))[1]
cycle.R.run_yt = lambda sid, v, mk, m, cache: (ran.append(("yt", sid, m)), ([], {}))[1]
cycle._yc_start = lambda a: (0, date(2026, 11, 9))
cycle.R.take_slots = lambda docs, n: docs
cycle.R.is_overnight = lambda acct, mk: False
cycle.L.persist = lambda db, acct, mk, docs, start, final, ov: persisted.append((acct, mk)) or len(docs)
cycle.L.update_accounts = lambda db, ids=None: sized.append(list(ids or []))
VW_DAYS: list = []
cycle.vwap_run.run = lambda panel, days: (VW_DAYS.append(sorted(days)), {k: [] for k in ("A", "B", "U1", "U2", "U3", "U4")})[1]


class Mkt:
    def __init__(self, name):
        self.name = name
        self.date = ["2026-11-25"]


class Pnl:
    days = ["2026-11-06", "2026-11-09", "2026-11-25"]
    names = ["INFY", "TCS"]
    live_day = None

    def market(self, i):
        return Mkt(self.names[i])

    def rank_on(self, j, i):
        return 1.0


n, touched, errs = cycle._stock_pass(None, WED, Pnl(), "2026-11-24", only={"YT-23|NSE15", "DH-05|NSE5", "VWAP-U4|VWAP"})
ids = {r[1] for r in ran if r[0] in ("yc", "yt")}
check("only the named pool books run, on every stock", ids == {"YT-23", "DH-05"} and len([r for r in ran if r[0] in ("yc", "yt")]) == 4,
      ran)
check("…their context is built from them alone", ("ctx", ["DH-05", "YT-23"]) in ran, ran)
check("…the named VWAP book is saved, the other VWAP books are not",
      ("VWAP-U4", "VWAP") in persisted and ("VWAP-A", "VWAP") not in persisted, persisted)
check("…every named book is saved and sized, nothing else",
      set(persisted) == {("YT-23", "NSE15"), ("DH-05", "NSE5"), ("VWAP-U4", "VWAP")}
      and sized == [["DH-05", "VWAP-U4", "YT-23"]], (persisted, sized))
check("…the VWAP study runs over the named book's days only", VW_DAYS[-1] == ["2026-11-09", "2026-11-25"], VW_DAYS)

ran.clear()
persisted.clear()
sized.clear()
n, touched, errs = cycle._stock_pass(None, WED, Pnl(), "2026-11-24")
check("only=None (the stocks pass): every pool book runs",
      {r[1] for r in ran if r[0] in ("yc", "yt")} == {"YT-23", "NJ-14", "DH-05"}, ran)
check("…and every VWAP book is saved", {("VWAP-U4", "VWAP"), ("VWAP-A", "VWAP")} <= set(persisted), persisted)

ran.clear()
persisted.clear()
sized.clear()
n, touched, errs = cycle._stock_pass(None, WED, Pnl(), "2026-11-24", only={"NOPE|NSE5"})
check("a name that is no book: nothing runs, nothing is saved or sized", ran == [] and persisted == [] and sized == [],
      (ran, persisted, sized))

# 9. the time budget: out of time before the stock books are saved -> nothing at all is saved
ran.clear()
persisted.clear()
sized.clear()
try:
    cycle._stock_pass(None, WED, Pnl(), "2026-11-24", only={"YT-23|NSE15", "VWAP-U4|VWAP"}, deadline=_t.time() - 1)
    check("past the deadline the stock books stop", False, "no TimeoutError")
except TimeoutError:
    check("past the deadline the stock books stop with TimeoutError", True)
check("…before anything is saved or sized", persisted == [] and sized == [], (persisted, sized))

# the deadline passes after the stock books (here: only a VWAP book is named, so the loop never checks it)
ran.clear()
persisted.clear()
sized.clear()
VW_DAYS.clear()
n, touched, errs = cycle._stock_pass(None, WED, Pnl(), "2026-11-24", only={"VWAP-U4|VWAP"}, deadline=_t.time() - 1)
check("out of time before the VWAP study: it is left for the next pass, and the reason is kept",
      VW_DAYS == [] and persisted == [] and "VWAP" in errs, (VW_DAYS, persisted, errs))
n, touched, errs = cycle._stock_pass(None, WED, Pnl(), "2026-11-24", only={"VWAP-U4|VWAP"}, deadline=_t.time() + 60)
check("…with time left it runs as before", ("VWAP-U4", "VWAP") in persisted and "VWAP" not in errs, (persisted, errs))

# 10. a TimeoutError in the quick pass is caught like any failure: the Delta work already ran, the bar is retried
cycle._stock_pass = lambda *a, **k: (_ for _ in ()).throw(TimeoutError("out of time before any stock book was saved"))
cycle._run_first_nse = saved_first
db = db_with(named())
errors = {}
LAST[0] += 300
BARS["RELIANCE"].append([LAST[0], 1, 2, 0.5, 1.5, 100])
check("out of time in the quick pass: no books, no exception", cycle._run_first_nse(db, WED, errors, deadline=0.0) == set())
check("…the reason is reported and the bar is not marked done",
      "out of time" in errors.get("first NSE books", "") and "sig_first_nse" not in db.premium_meta.docs, errors)
cycle._stock_pass = real_stock_pass

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("all checks passed")
