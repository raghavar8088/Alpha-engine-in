"""Offline checks of app.services.selling_each_books' planner: no database, no broker.

    python backend/tests/selling_each_books/verify_selling_each.py

The module's I/O imports are stubbed (the database, the date helper, Angel's fee card - a stand-in card here: flat
Rs 40 a leg plus a premium-proportional part, so fees are visible and scale with lots), the file is loaded, and
plan_strategy() is driven with parents built by the module's own normalizers from desk- and factory-shaped records."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "app" / "services" / "selling_each_books.py"
IST = timezone(timedelta(hours=5, minutes=30))


def _stub(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    m.__path__ = []  # type: ignore[attr-defined]
    sys.modules[name] = m
    return m


class _NoIO:
    def __getattr__(self, k):
        raise AssertionError(f"the planner must not touch the database ({k})")


class _DB(dict):
    def __getitem__(self, k):
        return _NoIO()


class _FB:
    def __init__(self, total: float):
        self.total = total


def _card(entry, exit_, lots, lot_size, on=None):
    qty = lots * lot_size
    if qty <= 0 or entry <= 0 or exit_ < 0:
        return _FB(0.0)
    return _FB(40.0 + 0.001 * (entry + exit_) * qty)


for pkg in ("app", "app.core", "app.services"):
    _stub(pkg)
_stub("app.core.db", db=_DB())
_stub("app.services.book_reset",
      naive_utc=lambda dt: dt.astimezone(timezone.utc).replace(tzinfo=None) if dt is not None and dt.tzinfo else dt)
_stub("app.services.angel_fees", option_round_trip=_card)
try:
    import pymongo.errors  # noqa: F401
except ImportError:
    _stub("pymongo")
    _stub("pymongo.errors", DuplicateKeyError=type("DuplicateKeyError", (Exception,), {}))

_spec = importlib.util.spec_from_file_location("selling_each_books", SRC)
se = importlib.util.module_from_spec(_spec)
sys.modules["selling_each_books"] = se
_spec.loader.exec_module(se)  # type: ignore[union-attr]

FAILS: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


NOW = datetime(2026, 11, 13, 10, 0)          # naive UTC
FAC, DESK = se.ACCOUNTS["sf10"], se.ACCOUNTS["desk10"]
FPICK, DPICK = FAC.picks[0], DESK.picks[0]


def fac_doc(pid, opened, status="OPEN", credit=90.0, short=(25400, 120.0), wing=(25200, 30.0), lots=1, lot_size=65,
            exits=None, marks=None, closed=None, expiry="2026-11-17", sid="SF0330"):
    width = abs(short[0] - wing[0])
    return {"position_id": pid, "desk": "index-selling", "strategy_id": sid, "timeframe": "30m", "status": status,
            "legs": [{"strike": short[0], "option_type": "PE", "expiry": expiry, "side": "SELL", "entry": short[1]},
                     {"strike": wing[0], "option_type": "PE", "expiry": expiry, "side": "BUY", "entry": wing[1]}],
            "lots": lots, "lot_size": lot_size, "credit": credit,
            "capital_deployed": max((width - credit) * lot_size, 1.0) * lots,
            "opened_at": opened, "closed_at": closed, "exit_legs": exits, "mark_legs": marks,
            "exit_reason": "target" if exits else None, "under_entry": 25410.0}


def desk_doc(key, entry_ts, closed=False, credit=30.0, margin=24000.0, lots=1, qty=75, exit_cost=None,
             exit_ts=None, mark=None, expiry="2026-11-17", sid="sell_pos_low_rv_fly"):
    d = {"key": key, "strategy_id": sid, "timeframe": "1d", "entry_ts": entry_ts, "credit": credit, "margin": margin,
         "lots": lots, "qty": qty, "expiry": expiry, "structure": "SELL 25150PE / BUY 24750PE",
         "legs": [{"strike": 25150, "option_type": "PE", "sold": True, "entry_premium": 60.0},
                  {"strike": 24750, "option_type": "PE", "sold": False, "entry_premium": 30.0}],
         "entry_spot": 25300.0}
    if closed:
        d.update({"exit_cost": exit_cost, "exit_ts": exit_ts, "exit_reason": "target", "exit_spot": 25350.0})
    else:
        d["mark"] = mark
    return d


def inserts(ops):
    return [b for k, b in ops if k == "insert"]


def updates(ops):
    return [b for k, b in ops if k == "update"]


print("normalizers")
p = se.desk_parent(desk_doc("k1", "2026-11-13T09:20:00.5+05:30"), closed=False)
check(p.opened_at == datetime(2026, 11, 13, 3, 50, 0, 500000), "desk entry_ts (+05:30 ISO) -> naive UTC")
check(p.lot_size == 75 and p.margin_per_lot == 24000.0 and p.ref == "k1|2026-11-13T09:20:00.5+05:30",
      "desk lot size, margin per lot, ref = key|entry_ts")
f = se.factory_parent(fac_doc("f1", NOW, status="CLOSED", exits=[60.0, 10.0], closed=NOW + timedelta(hours=1)))
check(f.state == "CLOSED" and f.exit_cost == 50.0 and f.margin_per_lot == (200 - 90) * 65,
      "factory close: exit cost = short buy-back - wing sale (60 - 10); margin per lot = max loss")
check(se.factory_parent(fac_doc("f2", NOW, status="CLOSED", exits=None)).state == "VOID",
      "factory close with no exit prices -> VOID")
check(se.desk_parent(desk_doc("k2", "2026-11-13T09:20:00+05:30", closed=True, exit_cost=None), True).state == "VOID",
      "desk trade with no exit cost -> VOID")

print("sizing: a fifth of the strategy's equity, at most 10 lots")
check(se.size(7150.0, 1_000_000, 0) == (10, 200000.0), "factory spread (Rs 7,150/lot): 27 fit in Rs 2 lakh -> capped at 10")
check(se.size(24000.0, 1_000_000, 0)[0] == 8, "desk spread (Rs 24,000/lot): 8 lots in Rs 2 lakh")
check(se.size(250000.0, 1_000_000, 0)[0] == 0, "a lot above Rs 2 lakh does not fit")
check(se.size(24000.0, 1_000_000, 950_000)[0] == 2, "never more than the free cash (Rs 50k free -> 2 lots)")
check(se.size(24000.0, -5000.0, 0)[0] == 0, "a strategy that has lost its money stops")

print("factory copy: opens at 10 lots, closes at the parent's exit")
t0 = NOW + timedelta(minutes=5)
copies: list = []
ops = se.plan_strategy(FAC, FPICK, [se.factory_parent(fac_doc("f10", t0))], copies, True, NOW)
ins = inserts(ops)
check(len(ins) == 1 and ins[0]["status"] == "OPEN" and ins[0]["lots"] == 10 and ins[0]["qty"] == 650,
      "a new parent entry -> one OPEN copy, 10 lots x 65")
check(ins[0]["capital_deployed"] == 71500.0 and ins[0]["equity_at_entry"] == 1_000_000.0,
      "margin in use = 10 x Rs 7,150; sized on Rs 10 lakh")
ops = se.plan_strategy(FAC, FPICK, [se.factory_parent(fac_doc("f10", t0, marks=[70.0, 15.0]))], copies, True, NOW)
check(len(updates(ops)) == 1 and copies[0]["unrealized_pnl"] == round((90 - 55) * 650, 2),
      "marked at the parent's leg marks: (credit 90 - buy-back 55) x 650")
ops = se.plan_strategy(FAC, FPICK, [se.factory_parent(fac_doc("f10", t0, marks=[70.0, 15.0]))], copies, True, NOW)
check(ops == [], "an unchanged mark writes nothing")
t1 = t0 + timedelta(hours=2)
ops = se.plan_strategy(FAC, FPICK, [se.factory_parent(fac_doc("f10", t0, status="CLOSED", exits=[60.0, 10.0],
                                                               closed=t1))], copies, True, NOW)
c = copies[0]
fees = round(_card(60.0, 120.0, 10, 65).total + _card(30.0, 10.0, 10, 65).total, 2)
check(c["status"] == "CLOSED" and c["gross_pnl"] == 26000.0 and c["closed_at"] == t1,
      "closed at the parent's exit and time: (90 - 50) x 650 = Rs 26,000 gross")
check(c["fees"] == fees and c["realized_pnl"] == round(26000.0 - fees, 2),
      f"charges per leg on the copy's 10 lots, at each leg's real entry and exit (Rs {fees})")

print("desk copy: 8 lots of a Rs 24,000 spread; profit stays in, losses shrink the next position")
d0 = "2026-11-13T09:20:00+05:30"
dcopies: list = []
ops = se.plan_strategy(DESK, DPICK, [se.desk_parent(desk_doc("k1", d0, closed=True, exit_cost=400.0,
                                                              exit_ts="2026-11-13T12:00:00+05:30"), True)],
                       dcopies, True, NOW)
first = dcopies[0]
check(first["lots"] == 8 and first["qty"] == 600 and first["status"] == "CLOSED",
      "opened and closed between two looks: copied at 8 lots and closed in the same pass")
check(first["gross_pnl"] == round((30 - 400) * 600, 2), "a max-loss trade: (30 - 400) x 600 = -Rs 2,22,000")
d1 = "2026-11-13T13:00:00+05:30"
ops = se.plan_strategy(DESK, DPICK, [se.desk_parent(desk_doc("k1", d0, closed=True, exit_cost=400.0,
                                                              exit_ts="2026-11-13T12:00:00+05:30"), True),
                                     se.desk_parent(desk_doc("k1", d1), False)], dcopies, True, NOW)
nxt = inserts(ops)
eq = 1_000_000 + first["realized_pnl"]
check(len(nxt) == 1 and nxt[0]["lots"] == int(eq * 0.2 // 24000) == 6 and nxt[0]["equity_at_entry"] == round(eq, 2),
      f"the next position is sized on the strategy's own equity (Rs {eq:,.0f}): 6 lots")
other = se.plan_strategy(DESK, DESK.picks[1], [se.desk_parent(desk_doc("k9", d1, sid=DESK.picks[1].strategy_id),
                                                             False)], [], True, NOW)
check(inserts(other)[0]["lots"] == 8, "another strategy's account is untouched by that loss: still 8 lots")

print("rules")
exp = se.plan_strategy(DESK, DPICK, [se.desk_parent(desk_doc("k3", "2026-11-17T09:30:00+05:30"), False)], [],
                       True, NOW)
check(inserts(exp)[0]["status"] == "SKIPPED" and inserts(exp)[0]["skip_reason"] == "expiry_day",
      "desk: an entry on its own expiry day is skipped and recorded")
fexp = se.plan_strategy(FAC, FPICK, [se.factory_parent(fac_doc("f30", datetime(2026, 11, 17, 4, 0)))], [], True, NOW)
check(inserts(fexp)[0]["status"] == "OPEN", "factory: same-day expiries are taken (the tab squares them off)")
held_copies: list = []
se.plan_strategy(DESK, DPICK, [se.desk_parent(desk_doc("kA", d0), False)], held_copies, True, NOW)
twin = se.plan_strategy(DESK, DPICK, [se.desk_parent(desk_doc("kA", d0), False),
                                      se.desk_parent(desk_doc("kB", "2026-11-13T09:25:00+05:30"), False)],
                        held_copies, True, NOW)
check([b["skip_reason"] for b in inserts(twin)] == ["held"], "a second structure while one is held: skipped (held)")
off_copies: list = []
se.plan_strategy(FAC, FPICK, [se.factory_parent(fac_doc("f40", t0))], off_copies, True, NOW)
off = se.plan_strategy(FAC, FPICK, [se.factory_parent(fac_doc("f40", t0, status="CLOSED", exits=[50.0, 5.0],
                                                               closed=t1)),
                                    se.factory_parent(fac_doc("f41", t1 + timedelta(minutes=30)))],
                       off_copies, False, NOW)
check(off_copies[0]["status"] == "CLOSED" and inserts(off)[0]["skip_reason"] == "off",
      "switched off: the open copy still closes, the new entry is recorded as off (never copied late)")
big = se.plan_strategy(DESK, DPICK, [se.desk_parent(desk_doc("kM", d0, margin=250000.0), False)], [], True, NOW)
check(inserts(big)[0]["skip_reason"] == "margin", "one lot needing more than a fifth of the equity: skipped (margin)")
bad = se.plan_strategy(DESK, DPICK, [se.desk_parent(desk_doc("kD", d0, lots=0, qty=0), False)], [], True, NOW)
check(inserts(bad)[0]["skip_reason"] == "data", "a parent with no size: skipped (data)")

print("a desk parent that vanished without a trade row")
v_copies: list = []
se.plan_strategy(DESK, DPICK, [se.desk_parent(desk_doc("kV", d0), False)], v_copies, True, NOW)
gone = se.plan_strategy(DESK, DPICK, [], v_copies, True, NOW)
check(gone == [] and v_copies[0]["status"] == "OPEN", "parent missing for a cycle: the copy waits (a close may be in flight)")
newer = se.plan_strategy(DESK, DPICK, [se.desk_parent(desk_doc("kW", d1), False)], v_copies, True, NOW)
check(v_copies[0]["status"] == "VOID" and v_copies[0]["realized_pnl"] == 0.0 and inserts(newer)[0]["status"] == "OPEN"
      and inserts(newer)[0]["lots"] == 8,
      "the strategy's next entry voids it (no P&L, margin back) and is copied at full size")

print("idempotent")
again = se.plan_strategy(DESK, DPICK, [se.desk_parent(desk_doc("kW", d1), False)], v_copies, True, NOW)
check(again == [], "re-planning the same parents writes nothing")

print("read model")
rows = se._strategy_rows(DESK, dcopies + inserts(other))
r0 = next(r for r in rows if r["strategy_id"] == DPICK.strategy_id)
r1 = next(r for r in rows if r["strategy_id"] == DESK.picks[1].strategy_id)
check(r0["trades"] == 1 and r0["open_positions"] == 1 and r0["position_limit"] < r1["position_limit"] == 200000.0,
      "per strategy: its own trades, open count and position limit (the loser's is smaller)")

print(f"\n{len(FAILS)} FAILED" if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
