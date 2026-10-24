"""Cross-checks for engine4 against the audited Phase 1-3 engines, plus the week/slot logic.

    python test_engine4.py <work_dir>
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase2"), HERE):
    sys.path.insert(0, p)
import engine as E  # noqa: E402
import engine2 as E2  # noqa: E402
import engine4 as E4  # noqa: E402
import run_phase4 as R4  # noqa: E402

work = sys.argv[1]
fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"{'ok  ' if cond else 'FAIL'} {name} {detail}")
    fails += 0 if cond else 1


for inst in R4.INSTS:
    parent, mini = R4.books(work, inst)
    mult, fam, tick = E.MULT[inst], E.FAMILY[inst], E.TICK[inst]
    slots = [(d1, s) for d1, s in parent.week_slots() if s is not None]
    # 1. week/slot logic: entry = previous ISO week's last trading day, exit within this week, front expiry > entry
    bad = 0
    for d1, s in slots:
        wk = tuple(d1.isocalendar()[:2])
        prev_days = [d for d in parent.days if tuple(d.isocalendar()[:2]) < wk]
        if s.d0 != prev_days[-1] or s.c.expiry <= s.d0 or s.d1 > d1 or (s.exp_in_week and s.d1 != s.c.expiry):
            bad += 1
    check(f"{inst} slot logic", bad == 0, f"({len(slots)} weeks, {bad} bad)")
    # the front is the NEAREST expiry after entry
    nearest = all(min((c.expiry for c in parent.cycles if c.expiry > s.d0 and s.d0 in c.dates)) == s.c.expiry for _, s in slots[:60])
    check(f"{inst} front = nearest expiry", nearest)
    # 2. run_legs == engine.run_trade when the week runs to expiry (same fills, fees, margin, stops)
    exp_slots = [s for _, s in slots if s.exp_in_week][:25]
    n_cmp, worst = 0, 0.0
    for s in exp_slots:
        for d, stop in ((0.15, None), (0.25, 1.0), (0.10, 2.0)):
            kc, kp = E2.pick_delta(s.c, "CE", s.j0, d), E2.pick_delta(s.c, "PE", s.j0, d)
            if not (kc and kp):
                continue
            legs = [("CE", -1, kc), ("PE", -1, kp)]
            a = E4.run_legs(s.c, legs, s.j0, s.j1, mult, fam, tick, 0.01, stop=stop)
            b = E.run_trade(s.c, legs, s.j0, mult, fam, tick, 0.01, None, stop, 0)
            if a is None or b is None:
                check(f"{inst} run_legs/run_trade both None", a is None and b is None)
                continue
            n_cmp += 1
            worst = max(worst, abs(a["pnl"] - b["pnl"]), abs(a["fees"] - b["fees"]), abs(a["capital"] - b["capital"]))
    check(f"{inst} run_legs == run_trade at expiry", n_cmp > 10 and worst < 1e-6, f"({n_cmp} trades, max diff {worst:.2e})")
    # 3. run_dh_week P&L == engine2.run_dh_straddle when held to expiry
    n_dh, worst = 0, 0.0
    for s in exp_slots[:10]:
        a = E4.run_dh_week(s.c, s.j0, s.j1, 10, mult, fam, tick, 0.01)
        b = E2.run_dh_straddle(s.c, s.j0, 10, mult, fam, tick, 0.01)
        if a is None or b is None:
            continue
        n_dh += 1
        worst = max(worst, abs(a["pnl"] - b["pnl"]))
        hm = b["hedge_margin_peak"] + b["capital"]
        worst = max(worst, abs(a["capital"] - hm))
    check(f"{inst} run_dh_week == run_dh_straddle", n_dh >= 5 and worst < 1e-6, f"({n_dh} trades, max diff {worst:.2e})")
    # 4. a long option by hand: entry close + slip, exit max(close - slip, 0), fees both ways
    s = slots[40][1]
    k = E2.pick_delta(s.c, "CE", s.j0, 0.30)
    t = E4.run_legs(s.c, [("CE", +1, k)], s.j0, s.j1, mult, fam, tick, 0.01)
    i = E._row(s.c, "CE", k)
    cl, tr = s.c.close["CE"][i], s.c.traded["CE"][i]
    fin = cl[s.j0] + max(tick, 0.01 * cl[s.j0])
    fout = max(cl[s.j1] - max(tick, 0.01 * cl[s.j1]) * (1 if tr[s.j1] else 3), 0)
    from tradingai_shared.mcx_option_fees import mcx_option_leg
    fees = mcx_option_leg(fin, mult, sell=False)["total"] + (mcx_option_leg(fout, mult, sell=True)["total"] if fout > 0 else 0)
    hand = (fout - fin) * mult - fees
    check(f"{inst} long call by hand", t is not None and abs(t["pnl"] - hand) < 1e-6 and abs(t["capital"] - fin * mult) < 1e-6,
          f"(engine {t['pnl']:.2f} vs hand {hand:.2f})")
    # 5. a long target fires at the first close where value >= (1 + tp) x debit, never before
    hits = 0
    for _, s in slots[:150]:
        k = E2.pick_delta(s.c, "CE", s.j0, 0.30)
        if not k:
            continue
        t = E4.run_legs(s.c, [("CE", +1, k)], s.j0, s.j1, mult, fam, tick, 0.01, tp=0.5, sl=0.5)
        if t is None or t["reason"] not in ("target", "stop"):
            continue
        i = E._row(s.c, "CE", k)
        cl = s.c.close["CE"][i]
        debit = cl[s.j0] + max(tick, 0.01 * cl[s.j0])
        je = s.c.dates.index(t["exit"])
        first = next(j for j in range(s.j0 + 1, s.j1 + 1) if cl[j] >= 1.5 * debit or cl[j] <= 0.5 * debit)
        hits += 1
        if first != je:
            check(f"{inst} target/stop day", False, f"{t['entry']} exit {t['exit']} expected {s.c.dates[first]}")
    check(f"{inst} long target/stop fire on the first qualifying close", hits > 5, f"({hits} exits checked)")

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
