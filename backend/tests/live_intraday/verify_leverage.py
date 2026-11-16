"""Checks of the 5x intraday-leverage rule in live_intraday_mirror.plan_book (2026-11-16).

Pure: the module's database and fee imports are stubbed, so no Mongo is needed.
Run: python backend/tests/live_intraday/verify_leverage.py [--old PATH_TO_PREVIOUS_live_intraday_mirror.py]

With --old, it also replays thousands of random books through the PREVIOUS plan_book and the new
one with no leverage arguments, and requires identical answers: five other desks share plan_book.
"""
from __future__ import annotations

import importlib.util
import random
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))


class _Fees:
    def __init__(self, total):
        self.total = total

    def as_dict(self):
        return {"total": self.total}


def _round_trip(entry_price=None, exit_price=None, qty=0, side="BUY", product="INTRADAY", **_):
    turnover = (entry_price + exit_price) * qty
    return _Fees(round(min(20.0, 0.0025 * entry_price * qty) * 2 + 0.00035 * turnover, 2))


def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _Coll:
    def __getattr__(self, name):
        raise RuntimeError("no database in this test")


class _DbModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Coll()


sys.modules["app.core.db"] = _DbModule("app.core.db")
_stub("app.services.intraday_v2_strategies", BY_ID={}, CATALOG=[])
_stub("app.services.angel_fees", round_trip=_round_trip, product_for=lambda *a, **k: "INTRADAY")


def _naive_utc(dt):
    if dt is None:
        return None
    from datetime import timezone
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


async def _reset_at(*_a, **_k):
    return None


_stub("app.services.book_reset", naive_utc=_naive_utc, reset_at=_reset_at)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NEW = _load(BACKEND / "app/services/live_intraday_mirror.py", "mirror_new")
from app.services import equity_margin as EM      # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or not detail else f"   [{detail}]"))
    if not cond:
        fails.append(name)


T0 = datetime(2026, 11, 16, 4, 0)          # 09:30 IST


def parent(pid, sym, mins_open, mins_close, entry, exit_, side="BUY", status="CLOSED", **extra):
    return {"position_id": pid, "strategy_id": "s", "symbol": sym, "side": side,
            "entry_price": entry, "exit_price": exit_ if status == "CLOSED" else None,
            "status": status, "opened_at": T0 + timedelta(minutes=mins_open),
            "closed_at": T0 + timedelta(minutes=mins_close) if status == "CLOSED" else None,
            "opened_on": "2026-11-16", **extra}


def five_x(_p):
    return 5.0


def plan(parents, *, capital=200000.0, realized=0.0, **kw):
    return NEW.plan_book(capital=capital, realized=realized, deployed=0.0, open_rows=[],
                         parents=parents, decided=set(), breaker_tripped=False, entries=True,
                         closed_rows=[], **kw)


# 1. One position: 5x the shares, margin a fifth of the value, P&L on the shares held.
ps = [parent("a", "AAA", 0, 30, 100.0, 102.0)]
p1, p5 = plan(ps), plan(ps, leverage_fn=five_x)
o1, o5 = p1["opens"][0], p5["opens"][0]
check("1x: qty = cap / price", o1["qty"] == 400, o1["qty"])                      # 2L / 5 / 100
check("5x: qty = 5 x cap / price", o5["qty"] == 2000, o5["qty"])
check("5x: value = 2,00,000 (the whole capital in one slot)", o5["notional"] == 200000.0, o5["notional"])
check("5x: margin = value / 5", o5["spend"] == 40000.0, o5["spend"])
check("1x: margin = value", o1["spend"] == o1["notional"] == 40000.0)
check("5x: gross = (exit - entry) x qty held", o5["close"]["gross"] == 4000.0, o5["close"]["gross"])
check("5x gross is the price move, not 5 x the 1x NET",
      o5["close"]["net"] != round(5 * o1["close"]["net"], 2) and o5["close"]["gross"] == 5 * o1["close"]["gross"])
check("fees are charged on the 5x quantity", o5["close"]["fb"].total > o1["close"]["fb"].total)

# 2. Five slots at 5x: exposure 5 x capital, margin = capital; the sixth is "full".
ps = [parent(f"p{i}", f"S{i}", i, 300, 100.0, 100.5) for i in range(6)]
p5 = plan(ps, leverage_fn=five_x)
check("5 opens, 1 skipped full", len(p5["opens"]) == 5 and [s["reason"] for s in p5["skips"]] == ["full"])
check("exposure = 5 x capital", round(sum(o["notional"] for o in p5["opens"]), 2) == 1000000.0)
check("margin used = capital", round(sum(o["spend"] for o in p5["opens"]), 2) == 200000.0)

# 3. Margin binds after a loss: the fifth position only gets what the free margin carries.
ps = [parent(f"p{i}", f"S{i}", i, 300, 100.0, 100.5) for i in range(5)]
p5 = plan(ps, realized=-10000.0, leverage_fn=five_x)
last = p5["opens"][-1]
check("after a Rs 10,000 loss the 5th position is cut to the free margin",
      last["spend"] <= 30000.0 + 0.01 and last["notional"] <= 150000.0 + 0.01, (last["spend"], last["notional"]))
check("total margin never exceeds capital + realised",
      round(sum(o["spend"] for o in p5["opens"]), 2) <= 190000.0 + 0.01)

# 4. Ineligible copy (a swing trade held overnight) stays at 1x inside a 5x book.
def by_style(p):
    return EM.intraday_leverage(None, intraday=p.get("style") in EM.INTRADAY_STYLES)


ps = [parent("i", "III", 0, 30, 100.0, 101.0, style="intraday"),
      parent("w", "WWW", 1, 30, 100.0, 101.0, style="swing")]
pm = plan(ps, leverage_fn=by_style)
lev = {o["parent"]["position_id"]: o["leverage"] for o in pm["opens"]}
check("intraday copy 5x, swing copy 1x", lev == {"i": 5.0, "w": 1.0}, lev)
w = [o for o in pm["opens"] if o["parent"]["position_id"] == "w"][0]
check("swing copy blocks its full value", w["spend"] == w["notional"] == 40000.0, (w["spend"], w["notional"]))
check("segment outside cash equity gets 1x", EM.intraday_leverage("NSE_FNO", intraday=True) == 1.0)
check("NSE_EQ intraday gets 5x", EM.intraday_leverage("NSE_EQ", intraday=True) == 5.0)
check("a book limit of 1 gives 1x", NEW.parent_leverage({"instrument": {"exchange_segment": "NSE_EQ"}}, 1.0) == 1.0)

# 5. The daily breaker on the trades' clock: a close that loses 3% of capital stops later entries
#    that IST day, and the next day trades again.
limit = 0.03 * 200000.0
ps = [parent("L", "LOSS", 0, 20, 100.0, 96.0),                      # -4% on 2,000 shares = -8,000
      parent("A", "AAA", 30, 60, 100.0, 101.0),                     # same day, after the loss
      {**parent("N", "NXT", 60 * 24, 60 * 24 + 30, 100.0, 101.0), "opened_on": "2026-11-17"}]
pb = plan(ps, leverage_fn=five_x, loss_limit=limit)
check("entry after the day's loss is refused as breaker",
      [(s["parent"]["position_id"], s["reason"]) for s in pb["skips"]] == [("A", "breaker")], pb["skips"])
check("next day's entry is taken", {o["parent"]["position_id"] for o in pb["opens"]} == {"L", "N"})
pb_seed = plan([parent("A", "AAA", 30, 60, 100.0, 101.0)], leverage_fn=five_x, loss_limit=limit,
               day_realized={"2026-11-16": -6500.0})
check("day_realized seeds the day's loss", [s["reason"] for s in pb_seed["skips"]] == ["breaker"])
pb_none = plan(ps, leverage_fn=five_x)
check("no loss_limit: no breaker", not pb_none["skips"])
check("ist_day of 18:45 UTC is the next IST date", NEW.ist_day(datetime(2026, 11, 16, 18, 45)) == "2026-11-17")

# 6. Compounding (A Grade) at 5x: cap = 5 x realised equity / slots.
ps = [parent("c1", "C1", 0, 10, 100.0, 110.0), parent("c2", "C2", 20, 40, 100.0, 100.0)]
pc = plan(ps, capital=1000000.0, leverage_fn=five_x, compound=True)
eq_after = 1000000.0 + pc["opens"][0]["close"]["net"]
check("compound 5x: second entry is 5 x equity / 5",
      pc["opens"][1]["qty"] == int(eq_after // 100.0), (pc["opens"][1]["qty"], eq_after))

# 7. Invariants on random 5x books: never more than the slots, one stock once, margin <= money.
rng = random.Random(7)
bad = 0
for trial in range(400):
    n = rng.randint(5, 40)
    ps = []
    for i in range(n):
        o = rng.randint(0, 300)
        c = o + rng.randint(1, 120)
        e = round(rng.uniform(20, 4000), 2)
        ps.append(parent(f"t{trial}_{i}", f"S{rng.randint(0, 12)}", o, c, e,
                         round(e * rng.uniform(0.95, 1.05), 2), side=rng.choice(["BUY", "SELL"]),
                         status="CLOSED" if rng.random() < 0.9 else "OPEN"))
    ps.sort(key=lambda p: (p["opened_at"], p["position_id"]))
    cap = rng.choice([10000.0, 80000.0, 200000.0, 1000000.0])
    pr = plan(ps, capital=cap, leverage_fn=five_x, compound=rng.random() < 0.3)
    ev = []
    for o in pr["opens"]:
        ev.append((o["parent"]["opened_at"], 1, o))
        if o["close"] is not None:
            ev.append((o["parent"]["closed_at"], 0, o))
    ev.sort(key=lambda e: (e[0], e[1]))
    money, margin, held = cap, 0.0, {}
    for _t, kind, o in ev:
        sym = o["parent"]["symbol"]
        if kind == 1:
            margin += o["spend"]
            held[sym] = held.get(sym, 0) + 1
            if (margin > money + 0.05 or len([s for s, k in held.items() if k]) > 5
                    or held[sym] > 1 or o["notional"] > 5 * max(money, cap) / 5 + 0.05
                    or abs(o["spend"] - o["notional"] / 5) > 0.011):
                bad += 1
        else:
            margin -= o["spend"]
            money += o["close"]["net"]
            held[sym] -= 1
check("400 random 5x books: slots, one stock once, margin <= money, margin = value / 5", bad == 0, bad)

# 8. Differential: no leverage arguments = the previous plan_book, exactly.
if "--old" in sys.argv:
    OLD = _load(Path(sys.argv[sys.argv.index("--old") + 1]), "mirror_old")
    diffs = 0
    for trial in range(3000):
        n = rng.randint(1, 30)
        ps = []
        for i in range(n):
            o = rng.randint(0, 400)
            c = o + rng.randint(0, 200)
            e = round(rng.uniform(5, 6000), 2)
            ps.append(parent(f"d{trial}_{i}", f"S{rng.randint(0, 9)}", o, c, e,
                             round(e * rng.uniform(0.9, 1.1), 2), side=rng.choice(["BUY", "SELL"]),
                             status="CLOSED" if rng.random() < 0.85 else "OPEN"))
        ps.sort(key=lambda p: (p["opened_at"], p["position_id"]))
        cap = rng.choice([10000.0, 30000.0, 80000.0, 200000.0, 1000000.0])
        realized = round(rng.uniform(-0.1, 0.1) * cap, 2)
        # Some books already hold rows and have closes to rewind - the live pass shape.
        open_rows, closed_rows, decided = [], [], set()
        k = rng.randint(0, min(3, n))
        for q in ps[:k]:
            decided.add(q["position_id"])
            if rng.random() < 0.5 and q["status"] == "OPEN":
                open_rows.append({"_id": q["position_id"], "symbol": q["symbol"], "side": q["side"],
                                  "entry_price": q["entry_price"], "qty": 3, "capital_deployed": 3 * q["entry_price"],
                                  "source": "tournament", "parent_position_id": q["position_id"]})
            elif q["status"] == "CLOSED":
                closed_rows.append({"symbol": q["symbol"], "capital_deployed": 2 * q["entry_price"],
                                    "realized_pnl": 5.0, "opened_at": q["opened_at"], "closed_at": q["closed_at"]})
        deployed = sum(r["capital_deployed"] for r in open_rows)
        kw = dict(capital=cap, realized=realized, deployed=deployed, open_rows=open_rows, parents=ps,
                  decided=decided, breaker_tripped=rng.random() < 0.05, entries=True,
                  closed_rows=closed_rows, compound=rng.random() < 0.3,
                  max_open=rng.choice([None, 3, 5, 10]))
        a, b = OLD.plan_book(**kw), NEW.plan_book(**kw)

        def shape(r):
            return ([(o["parent"]["position_id"], o["qty"], o["spend"],
                      None if o["close"] is None else (o["close"]["gross"], o["close"]["net"]))
                     for o in r["opens"]],
                    [(c["row"]["_id"], c["gross"], c["net"]) for c in r["closes"]],
                    [(s["parent"]["position_id"], s["reason"]) for s in r["skips"]])
        if shape(a) != shape(b):
            diffs += 1
    check("3000 random books: new plan_book without leverage == previous plan_book", diffs == 0, diffs)

print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED: {fails}'}")
sys.exit(1 if fails else 0)
