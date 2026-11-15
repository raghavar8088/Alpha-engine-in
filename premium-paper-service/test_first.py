"""Offline checks of the first books in the bitcoin pass: cycle._run_first and its place in cycle.run_global.

Run:  python premium-paper-service/test_first.py

The backend's real-money desk (premium_live) names the books it copies in premium_meta 'live_priority'. Each bitcoin
pass now reads the Delta candles, runs and sizes those books, and only then does everything else (15 Nov 2026). No
network, database or market data is used: the feeds, the catalog, the ledger and the channel-book runner are replaced
by recorders, so what is checked is the order of the work and which books run where.
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

print("\nALL PASS" if not FAILS else f"\n{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
