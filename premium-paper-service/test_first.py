"""Offline checks of the first books in the bitcoin pass: cycle._run_first and its place in cycle.run_global.

Run:  python premium-paper-service/test_first.py

The backend's real-money desk (premium_live) names the books it copies in premium_meta 'live_priority'. Each bitcoin
pass now reads the Delta candles, runs and sizes those books, and only then does everything else (15 Nov 2026). No
network, database or market data is used: the feeds, the catalog, the ledger and the channel-book runner are replaced
by recorders, so what is checked is the order of the work and which books run where. From 15 Nov also the quick pass ("live", every
minute: the Delta candles, then the bitcoin AND gold books a real-money desk copies), the gold books' replay window
(the quick pass's few books warm up on the full pass's window), the supervisor's schedule and the status panel's feeds. From 16 Nov the quick work also runs inside a full pass, every
minute between its books, and the full pass leaves those books to it (sections 11-15).
"""
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import resource  # noqa: F401
except ImportError:             # Windows: cycle.py uses it only for its peak-memory note
    sys.modules["resource"] = types.ModuleType("resource")

import cycle  # noqa: E402

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


YC = sorted(cycle.C.YC_SOURCES)[0]
BOOKS = [(SimpleNamespace(id=i, source=YC), mk, "V0") for i, mk in
         (("TH-05", "BTCUSD"), ("TL-04", "BTCUSD"), ("TH-01", "BTCUSD"), ("ZZ-01", "BTCUSD"), ("DR-01", "XAUTUSD"))]
NAMED = ["CP-23|XAUUSD", "DR-01|XAUTUSD", "TH-01|BTCUSD", "TH-05|BTCUSD", "TL-04|BTCUSD"]   # as premium_live writes it
calls: list = []
LAST = [1_794_700_000]
FAIL_ONE: list = [None]


def run_yc_btc(db, books, errors, touched):
    ids = [a.id for a, *_ in books]
    calls.append(("run", ids))
    touched.update(i for i in ids if i != FAIL_ONE[0])
    return len(ids)


cycle.C.books_in = lambda group: list(BOOKS)
cycle.R.is_overnight = lambda acct, mk: False
cycle.F.last_minute = lambda name: LAST[0]
cycle._run_yc_btc = run_yc_btc
cycle.L.update_accounts = lambda db, ids=None: calls.append(("size", list(ids or [])))


def db_with(*docs):
    return SimpleNamespace(premium_meta=Meta({"_id": "status"}, *docs))


# 1. nothing named: nothing runs first
db, errors = db_with(), {}
check("no 'live_priority' document: nothing runs first", cycle._run_first(db, errors) == set() and not calls, calls)

# 2. the named bitcoin channel books run first and are sized at once; nothing else does
db = db_with({"_id": "live_priority", "books": NAMED})
got = cycle._run_first(db, errors)
check("the three named bitcoin books run first", got == {"TH-05", "TL-04", "TH-01"}
      and calls[:1] == [("run", ["TH-05", "TL-04", "TH-01"])], (got, calls))
check("and are sized straight away", calls[1:] == [("size", ["TH-01", "TH-05", "TL-04"])], calls)
check("an unnamed bitcoin book (ZZ-01) and a named gold book (DR-01) are left to the pass",
      all("ZZ-01" not in c[1] and "DR-01" not in c[1] for c in calls), calls)
check("the bitcoin minute it ran on is recorded", db.premium_meta.docs["sig_first"]["last"] == LAST[0])

# 3. once per new bitcoin minute
calls.clear()
check("the same minute again: nothing runs", cycle._run_first(db, errors) == set() and not calls, calls)
LAST[0] += 60
check("a new minute: they run again", cycle._run_first(db, errors) == {"TH-05", "TL-04", "TH-01"}, calls)

# 4. a book that fails is left to the pass; a failure of the step runs nothing first
calls.clear()
LAST[0] += 60
FAIL_ONE[0] = "TL-04"
got = cycle._run_first(db, errors)
check("a book that fails here is not counted as done (the pass runs it again)", got == {"TH-05", "TH-01"}
      and calls[-1:] == [("size", ["TH-01", "TH-05"])], (got, calls))
FAIL_ONE[0] = None


def boom(*_a, **_k):
    raise RuntimeError("disk")


cycle._run_yc_btc, keep = boom, cycle._run_yc_btc
LAST[0] += 60
errors = {}
check("the step itself fails: nothing counted as done, the error is reported",
      cycle._run_first(db, errors) == set() and "first books" in errors, errors)
cycle._run_yc_btc = keep

# 5. its place in run_global: Delta candles, then the first books, then Yahoo; the pass does not run them twice
calls.clear()
LAST[0] += 60
cycle.F.YF = ["EURUSD"]
cycle.F.update_delta_candles = lambda symbol="BTCUSD", **_k: calls.append(("delta", symbol)) or {"new": 1}
cycle.F.update_minutes = lambda name, **_k: calls.append(("yahoo", name)) or {"new": 1}
cycle.F.backfill_delta_candles = lambda *_a, **_k: {"new": 0}
cycle.F.usdinr = lambda: None
cycle.F.global_final_day = lambda name, now=None: "2026-11-14"
cycle.F.gold_market = lambda *_a, **_k: None
cycle.F.global_market = lambda *_a, **_k: None
cycle.L.signature = lambda db, group: "an older signature"
cycle.L.set_signature = lambda db, group, sig: calls.append(("signature", group))
cycle.time.sleep = lambda s: None
db = db_with({"_id": "live_priority", "books": NAMED}, {"_id": "yahoo_at", "t": 0})
info = cycle.run_global(db, datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc))
order = [c[0] if c[0] != "run" else "run " + "+".join(c[1]) for c in calls]
check("Delta candles first, then the three books and their sizing, then Yahoo, then the rest", order[:7] == [
    "delta", "delta", "delta", "run TH-05+TL-04+TH-01", "size", "yahoo", "run ZZ-01"], order)
check("the pass runs only the other bitcoin book (ZZ-01), so nothing runs twice",
      [c for c in calls if c[0] == "run"] == [("run", ["TH-05", "TL-04", "TH-01"]), ("run", ["ZZ-01"])], calls)
check("its report names the first books", info.get("first") == ["TH-01", "TH-05", "TL-04"], info)

# 6. the gold books' replay window (15 Nov): the quick pass's few books warm up on the full pass's window
from datetime import date, timedelta  # noqa: E402
GOLD_BOOKS = [(SimpleNamespace(id=i, source=src), mk, "V0") for i, src, mk in
              (("CP-23", cycle.C.CP, "XAUUSD"), ("DR-01", YC, "XAUTUSD"), ("ZZ-09", cycle.C.CP, "XAUUSD"), ("YT-14", "yt", "XAUUSD"))]
FIRSTS = {"CP-23": date(2026, 11, 10), "DR-01": date(2026, 11, 12), "ZZ-09": date(2026, 11, 1), "YT-14": date(2026, 11, 8)}
ran, sliced = [], []
cycle._from = lambda db, a, bmk, on=False: FIRSTS[a.id]
cycle.F.gold_market = lambda since: SimpleNamespace(date=["2026-11-14"])
cycle.F.slice_from = lambda full, d: sliced.append(d) or SimpleNamespace(date=["2026-11-14"])
cycle.F.yt_cost = lambda name: 0.0
cycle.YM._as_mkt = lambda m, *a, **k: m
cycle.R.run_cp = lambda acct, name, m, cache, comp: ran.append(acct) or ([], None)
cycle.R.run_yc = lambda acct, mk, m, cache, **k: ran.append(acct) or ([], None)
cycle.R.run_yt = lambda acct, v, name, m, cache: ran.append(acct) or ([], None)
cycle._companion = lambda *a: None
cycle._save_book = lambda *a: 1
gold4 = [(a, mk, v, False) for a, mk, v in GOLD_BOOKS]
named = [b for b in gold4 if b[0].id in ("CP-23", "DR-01")]
touched6: set = set()
cycle._run_market_books(db_with(), "XAUUSD", named, {}, touched6, window=gold4)
want_start = date(2026, 11, 1) - timedelta(days=cycle.GLOBAL_WARM_DAYS)
check("the quick pass replays only its named gold books (any source)", sorted(ran) == ["CP-23", "DR-01"]
      and touched6 == {"CP-23", "DR-01"}, ran)
check("on the full pass's window: GLOBAL_WARM_DAYS before the earliest start of ALL the gold books", sliced == [want_start], sliced)
ran.clear()
sliced.clear()
cycle._run_market_books(db_with(), "XAUUSD", gold4, {}, set())
check("the full pass replays all four, on the same window", sorted(ran) == ["CP-23", "DR-01", "YT-14", "ZZ-09"]
      and sliced == [want_start], (ran, sliced))

# 7. the named gold books in the quick pass
mb_calls: list = []


def fake_market_books(db, name, mine, errors, touched, window=None):
    mb_calls.append((name, sorted(b[0].id for b in mine), sorted(b[0].id for b in (window or []))))
    touched.update(b[0].id for b in mine)
    return len(mine)


cycle.C.books_in = lambda group: list(GOLD_BOOKS) + [b for b in BOOKS if b[0].id != "DR-01"]   # DR-01 once
cycle._run_market_books = fake_market_books
calls.clear()
LAST[0] += 60
db = db_with({"_id": "live_priority", "books": ["CP-23|XAUUSD", "DR-01|XAUTUSD", "TH-05|BTCUSD"]})
got = cycle._run_first_gold(db, {})
check("the named gold books run first, on the gold market's whole window, and are sized at once",
      got == {"CP-23", "DR-01"} and mb_calls[-1] == ("XAUUSD", ["CP-23", "DR-01"], ["CP-23", "DR-01", "YT-14", "ZZ-09"])
      and calls[-1:] == [("size", ["CP-23", "DR-01"])], (got, mb_calls, calls))
check("once per new gold minute", cycle._run_first_gold(db, {}) == set() and len(mb_calls) == 1)

# 8. the quick pass, in order
calls.clear()
mb_calls.clear()
LAST[0] += 60
db = db_with({"_id": "live_priority", "books": NAMED + ["CP-23|XAUUSD"]})
info = cycle.run_live(db, datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc))
order = [c[0] if c[0] != "run" else "run " + "+".join(c[1]) for c in calls]
check("the quick pass: the Delta candles, the bitcoin books and their sizing, the gold books and theirs; nothing else",
      order == ["delta", "delta", "delta", "run TH-05+TL-04+TH-01", "size", "size"]
      and mb_calls == [("XAUUSD", ["CP-23", "DR-01"], ["CP-23", "DR-01", "YT-14", "ZZ-09"])], (order, mb_calls))
check("its report names every book it ran first", info.get("first") == ["CP-23", "DR-01", "TH-01", "TH-05", "TL-04"], info)

# 9. the supervisor's schedule
import main as SUP  # noqa: E402
check("the quick pass every minute and first in line; every book every 8 minutes",
      SUP.interval_s("live") == 60 and SUP.interval_s("global") == 480 and SUP.ORDER[0] == "live"
      and set(SUP.ORDER) == set(SUP.TIMEOUT_S), (SUP.ORDER, SUP.TIMEOUT_S))

# 10. the status panel's feeds after a quick pass
import segments as SEG  # noqa: E402
SEG._last_bar = lambda store: (1_794_700_000, 1.0)
out = SEG.feeds_now("live", {"errors": {"feed XAUUSD": "x"}})
check("a quick pass reports the three Delta feeds (so no book looks stale between full passes)",
      sorted(out) == ["BTCUSD", "ETHUSD", "XAUUSD"] and out["XAUUSD"]["fetch_error"] == "x", out)
check("a full pass still reports every feed", len(SEG.feeds_now("global", {})) == 8)

# 11. the quick work inside a full pass (16 Nov): _tick runs it again once LIVE_EVERY_S has passed since it last
#     started; never inside itself, never outside a full pass, and a failure never stops the pass
calls.clear()
mb_calls.clear()
clock = [2_000_000_000.0]
real_time = cycle.time.time
cycle.time.time = lambda: clock[0]
db = db_with({"_id": "live_priority", "books": NAMED + ["CP-23|XAUUSD"]})
errs, news = {}, {}
cycle._LIVE.update(on=True, busy=False, t=clock[0], errors=errs, new=news, done=set())
cycle._tick(db)
check("inside a full pass, before LIVE_EVERY_S has passed: no quick work", not calls and not mb_calls, (calls, mb_calls))
clock[0] += cycle.LIVE_EVERY_S
LAST[0] += 60
cycle._tick(db)
check("after LIVE_EVERY_S: the quick work again, the Delta candles, then the bitcoin and the gold books",
      [c[0] for c in calls] == ["delta", "delta", "delta", "run", "size", "size"]
      and mb_calls == [("XAUUSD", ["CP-23", "DR-01"], ["CP-23", "DR-01", "YT-14", "ZZ-09"])], (calls, mb_calls))
check("the books it ran count in the pass's report, its candles in the pass's 'new'",
      cycle._LIVE["done"] == {"CP-23", "DR-01", "TH-01", "TH-05", "TL-04"} and news == {"BTCUSD": 1, "XAUUSD": 1, "ETHUSD": 1},
      (cycle._LIVE["done"], news))
n = len(calls)
clock[0] += cycle.LIVE_EVERY_S - 1
cycle._tick(db)
check("not again until LIVE_EVERY_S after it last started", len(calls) == n, calls[n:])
clock[0] += 1
cycle._LIVE["busy"] = True
cycle._tick(db)
check("never inside itself (the loops of its own books tick too)", len(calls) == n, calls[n:])
cycle._LIVE.update(busy=False, on=False)
cycle._tick(db)
check("never outside a full pass", len(calls) == n, calls[n:])
cycle._LIVE["on"] = True
cycle._live_work, keep_lw = boom, cycle._live_work
try:
    cycle._tick(db)
    raised = False
except Exception:  # noqa: BLE001
    raised = True
cycle._live_work = keep_lw
check("a quick work that raises does not stop the full pass; the error is reported", not raised and "quick work" in errs, errs)
cycle._LIVE["on"] = False
cycle.time.time = real_time

# 12. a full pass does the quick work first and leaves those books to it; their market still sets the window
calls.clear()
mb_calls.clear()
LAST[0] += 60
db = db_with({"_id": "live_priority", "books": NAMED + ["CP-23|XAUUSD"]}, {"_id": "yahoo_at", "t": 0})
info = cycle.run_global(db, datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc))
gold = [c for c in mb_calls if c[0] == "XAUUSD"]
check("a full pass starts with the quick work: the Delta candles, the bitcoin books, the gold books",
      [c[0] for c in calls][:6] == ["delta", "delta", "delta", "run", "size", "size"]
      and gold[:1] == [("XAUUSD", ["CP-23", "DR-01"], ["CP-23", "DR-01", "YT-14", "ZZ-09"])], (calls, mb_calls))
check("its gold market then runs only the other gold books, on the whole market's window",
      gold[1:] == [("XAUUSD", ["YT-14", "ZZ-09"], ["CP-23", "DR-01", "YT-14", "ZZ-09"])], gold)
check("and of the bitcoin channel books only the unnamed one (ZZ-01)",
      [c for c in calls if c[0] == "run"] == [("run", ["TH-05", "TL-04", "TH-01"]), ("run", ["ZZ-01"])], calls)
check("its report names every book the quick work ran", info.get("first") == ["CP-23", "DR-01", "TH-01", "TH-05", "TL-04"], info)
check("and when it ends, no more ticks", cycle._LIVE["on"] is False)

# 13. after a failure in the pass the full pass runs them where it always did
calls.clear()
mb_calls.clear()
LAST[0] += 60
FAIL_ONE[0] = "TL-04"


def run_yc_btc_err(db, books, errors, touched):          # as the real one: a book that fails leaves its error
    n = run_yc_btc(db, books, errors, touched)
    if FAIL_ONE[0] in [a.id for a, *_ in books]:
        errors[f"{FAIL_ONE[0]}|BTCUSD"] = "boom"
    return n


cycle._run_yc_btc = run_yc_btc_err
cycle.run_global(db, datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc))
check("a named bitcoin book that failed in the quick work runs again in the pass",
      [c for c in calls if c[0] == "run"][-1:] == [("run", ["TL-04", "ZZ-01"])], calls)
FAIL_ONE[0] = None
calls.clear()
LAST[0] += 60
fails = [1]


def flaky_btc(db, books, errors, touched):
    if fails[0]:
        fails[0] -= 1
        raise RuntimeError("disk")
    return run_yc_btc(db, books, errors, touched)


cycle._run_yc_btc = flaky_btc
info = cycle.run_global(db, datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc))
check("the quick work's bitcoin step fails: the pass runs every bitcoin channel book itself",
      [c for c in calls if c[0] == "run"] == [("run", ["TH-05", "TL-04", "TH-01", "ZZ-01"])] and "first books" in info["errors"],
      (calls, info))
cycle._run_yc_btc = run_yc_btc
calls.clear()
mb_calls.clear()
LAST[0] += 60
gfails = [1]


def flaky_gold(db, name, mine, errors, touched, window=None):
    if gfails[0]:
        gfails[0] -= 1
        raise RuntimeError("disk")
    return fake_market_books(db, name, mine, errors, touched, window)


cycle._run_market_books = flaky_gold
info = cycle.run_global(db, datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc))
cycle._run_market_books = fake_market_books
check("the quick work's gold step fails: the pass runs all four gold books itself",
      [c for c in mb_calls if c[0] == "XAUUSD"] == [("XAUUSD", ["CP-23", "DR-01", "YT-14", "ZZ-09"], ["CP-23", "DR-01", "YT-14", "ZZ-09"])]
      and "first gold books" in info["errors"], (mb_calls, info))

# 14. a full pass's own loops tick after every book: each market's books, the bitcoin and the ether channel books
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("cycle_fresh", Path(cycle.__file__))
fresh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fresh)
ticks: list = []
fresh._tick = lambda db: ticks.append(1)
fresh._from = cycle._from
fresh._save_book = lambda *a: 1
fresh._companion = lambda *a: None
fresh._yc_from = lambda *a, **k: date(2026, 11, 9)
fresh._run_market_books(db_with(), "XAUUSD", gold4, {}, set(), window=gold4)
check("each market's loop ticks after every book", len(ticks) == 4, len(ticks))
cycle.F.btc_market = lambda since: SimpleNamespace(t=[1, 2, 3], c=[100.0, 101.0, 102.0], date=["2026-11-15"])
cycle.F.btc_final_day = lambda: "2026-11-14"
cycle.F.eth_market = cycle.F.btc_market
cycle.R.YCS = SimpleNamespace(STRATEGIES={b[0].id: SimpleNamespace(needs=()) for b in BOOKS})
cycle.R.run_yc = lambda acct, *a, **k: ([], None)
btc4 = [(a, mk, v, False) for a, mk, v in BOOKS if mk == "BTCUSD"]
ticks.clear()
fresh._run_yc_btc(db_with(), btc4, {}, set())
check("the bitcoin channel books' loop ticks after every book", len(ticks) == 4, len(ticks))
ticks.clear()
fresh._run_yc_eth(db_with(), btc4[:2], {}, set())
check("and the ether books' loop", len(ticks) == 2, len(ticks))

# 15. the supervisor gives a full pass room for the quick work it now does
check("a full pass is stopped only after 25 minutes; it still starts at most every 8",
      SUP.TIMEOUT_S["global"] == 1500 and SUP.interval_s("global") == 480 and SUP.interval_s("live") == 60, SUP.TIMEOUT_S)

print("\nALL PASS" if not FAILS else f"\n{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
