"""Checks for engine5 (A5): opens line up with the bhavcopy, an open exit matches a hand calculation,
the shock rule fires exactly where the definition says, and F2 never holds two positions at once.

    python test_engine5.py <work4> <work5>
"""
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase2"), os.path.join(HERE, "..", "phase4"), HERE):
    sys.path.insert(0, p)
import engine as E  # noqa: E402
import engine4 as E4  # noqa: E402
import engine5 as E5  # noqa: E402
import run_phase5 as R5  # noqa: E402
from tradingai_shared.mcx_option_fees import mcx_option_leg  # noqa: E402

work4, work5 = sys.argv[1], sys.argv[2]
HAVE_METALS = os.path.exists(os.path.join(work5, "p5_specs.json"))
if HAVE_METALS:
    R5.load_specs(work5)
fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"{'ok  ' if cond else 'FAIL'} {name} {detail}")
    fails += 0 if cond else 1


if HAVE_METALS:
    check("engine tables hold the new markets", all(m in E.MULT and m in E.TICK and E.FAMILY[m] in E.MARGIN_RATE
                                                     for m in R5.METALS + R5.CROSS))
CASES = [("CRUDEOILM_parent", "CRUDEOILM", "CRUDEOIL", work4)]
if HAVE_METALS:
    CASES += [("GOLD", "GOLD", "GOLD", work5), ("COPPER", "COPPER", "COPPER", work5)]
for key, inst, sym, work in CASES:
    bk = R5.book(work5, key, inst)
    opt = pd.read_pickle(os.path.join(work, "opt.pkl"))
    o = opt[(opt.sym == sym) & opt.traded]
    # 1. opens line up with the source rows
    rng = np.random.default_rng(1)
    bad = 0
    for r in o.sample(300, random_state=1).itertuples():
        cyc = [c for c in bk.cycles if c.expiry == r.expiry]
        if not cyc or r.date not in cyc[0].dates:
            continue
        c = cyc[0]
        i = E._row(c, r.cp, r.strike)
        if i is None:
            continue
        if not np.isclose(c.open[r.cp][i, c.dates.index(r.date)], r.open):
            bad += 1
    check(f"{key} opens match the bhavcopy", bad == 0, f"({bad} mismatches)")
    # 2. an open exit by hand
    slots = [s for _, s in E5.weekend_slots(bk, "2017-01-01", "2026-10-31") if s is not None and s.j1 == s.j0 + 1]
    done = 0
    mult, fam, tick = E.MULT[inst], E.FAMILY[inst], E.TICK[inst]
    for s in slots[10:60]:
        legs = E5.short_legs(bk, s.c, s.j0, "strangle25")
        if not legs:
            continue
        t = E5.run_short_open_exit(s.c, legs, s.j0, s.j1, mult, fam, tick, 0.01)
        if t is None:
            continue
        hand, fees, cap = 0.0, 0.0, 0.0
        for cp, side, k in legs:
            i = E._row(s.c, cp, k)
            fin = s.c.close[cp][i, s.j0] - max(tick, 0.01 * s.c.close[cp][i, s.j0])
            op = s.c.open[cp][i, s.j1]
            if s.c.traded[cp][i, s.j1] and op > 0:
                fout = op + max(tick, 0.01 * op)
            else:
                px = s.c.close[cp][i, s.j1]
                fout = px + 3 * max(tick, 0.01 * px)
            hand += (fin - fout) * mult
            fees += mcx_option_leg(fin, mult, sell=True)["total"] + mcx_option_leg(fout, mult, sell=False)["total"]
            cap += 1.2 * E.MARGIN_RATE[fam] * s.c.F[s.j0] * mult
        if abs(t["pnl"] - (hand - fees)) > 1e-6 or abs(t["capital"] - cap) > 1e-6:
            check(f"{key} open exit by hand", False, f"{t['entry']} engine {t['pnl']:.2f} hand {hand - fees:.2f}")
        done += 1
    check(f"{key} open exits match a hand calculation", done >= 10, f"({done} trades)")
    # 3. the shock rule fires exactly on the definition, and F2 holds one position at a time
    tr, den = E5.f2_trades(bk, inst, (2.0, "same", "strangle25", 5), "2017-01-01", "2026-10-31", 0.01)
    ok = 0
    for t in tr:
        c = [c for c in bk.cycles if c.expiry == t["expiry"]][0]
        j = c.dates.index(t["entry"])
        r = abs(math.log(c.F[j] / c.F[j - 1]))
        ok += r >= 2.0 * c.rv20[j - 1] / math.sqrt(252)
    check(f"{key} every F2 entry is a shock day", ok == len(tr) and len(tr) > 5, f"({ok}/{len(tr)} trades, {den} shocks taken)")
    overlap = sum(b["entry"] <= a["exit"] for a, b in zip(tr[:-1], tr[1:]))
    check(f"{key} F2 never overlaps positions", overlap == 0, f"({overlap} overlaps)")
    # 4. close exits are engine4.run_legs over one day, bit for bit
    s = slots[30]
    legs = E5.short_legs(bk, s.c, s.j0, "straddle")
    a = E5.f1_trades(bk, inst, ("straddle", "none", "close"), str(s.d0.date()), str(s.d0.date()), 0.01)[0]
    b = E4.run_legs(s.c, legs, s.j0, s.j1, mult, fam, tick, 0.01) if legs else None
    check(f"{key} close exit == run_legs", (not a and b is None) or (a and b and abs(a[0]["pnl"] - b["pnl"]) < 1e-9))

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
