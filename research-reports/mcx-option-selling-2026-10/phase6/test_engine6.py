"""Checks for engine6 / run_phase6 against hand calculations on the real MCX contracts.

    python test_engine6.py <work6>
"""
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), HERE):
    sys.path.insert(0, p)
import engine6 as E6  # noqa: E402
import run_phase6 as R6  # noqa: E402

work = sys.argv[1]
fut = pd.read_pickle(os.path.join(work, "fut.pkl"))
fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"{'ok  ' if cond else 'FAIL'} {name} {detail}")
    fails += 0 if cond else 1


for sym in R6.SYMS:
    mk = E6.Market(fut, sym)
    d = mk.daily
    f = fut[fut.sym == sym]
    px = {(r.expiry, r.date): r.close for r in f.itertuples()}
    days = list(d.index)
    # 1. every day's index return is the HELD contract's own close-to-close change
    bad = 0
    for i in range(1, len(days)):
        h = d.held.iloc[i - 1]
        a, b = px.get((h, days[i - 1])), px.get((h, days[i]))
        want = b / a - 1 if a and b and a > 0 and b > 0 else 0.0
        bad += abs(d.r.iloc[i] - want) > 1e-12
    check(f"{sym} index return = held contract's own change", bad == 0, f"({bad} of {len(days) - 1} days differ)")
    # 2. the roll happens exactly ROLL_DAYS trading days before the expiry
    bad, n = 0, 0
    for i in np.where(d.roll.to_numpy())[0]:
        old = d.held.iloc[i - 1]
        last = max(x for x in days if x <= old)
        n += 1
        bad += days.index(last) - i != E6.ROLL_DAYS
    check(f"{sym} rolls {E6.ROLL_DAYS} trading days before expiry", bad == 0 and n > 150, f"({n} rolls, {bad} off)")
    # 3. carry by hand on 200 random days
    rng = np.random.default_rng(3)
    bad = 0
    exps = sorted(f.expiry.unique())
    tr = {(r.expiry, r.date): r.traded for r in f.itertuples()}
    for i in rng.choice(len(days), 200, replace=False):
        dd, h = days[i], d.held.iloc[i]
        later = [e for e in exps if e > h]
        if not later or not tr.get((h, dd)) or not tr.get((later[0], dd)):
            bad += np.isfinite(d.y.iloc[i])
            continue
        want = math.log(px[(h, dd)] / px[(later[0], dd)]) * 365 / (later[0] - h).days
        bad += abs(d.y.iloc[i] - want) > 1e-12
    check(f"{sym} carry by hand", bad == 0)
    # 4. a constant long position: net = index change minus rolls (both sides + 2 orders); opening pays one side
    pos = np.ones(len(mk.D))
    w = mk.returns(pos)
    k = int(np.argmax(mk.roll_count[:-1] > 0))
    want_roll = mk.roll_unit[k] + mk.roll_count[k] * 2 * E6.ORDER
    open_cost = mk.buy_rate[0] + E6.ORDER
    ok = (abs(w.cost.iloc[0] - (open_cost + mk.roll_unit[0] + mk.roll_count[0] * 2 * E6.ORDER)) < 1e-15
          and abs(w.cost.iloc[k] - want_roll) < 1e-15 and k > 0
          and abs(w.gross.iloc[5] - (mk.I_D[6] / mk.I_D[5] - 1)) < 1e-15)
    check(f"{sym} weekly costs and returns by hand", ok)
    # 5. the roll costs land in the week that contains the roll day
    roll_days = d.index[d.roll]
    wk = [int(np.searchsorted(mk.D.values, x.to_datetime64(), side="left")) - 1 for x in roll_days]
    check(f"{sym} rolls counted once each", int(mk.roll_count.sum()) == sum(1 for x in wk if 0 <= x < len(mk.D)))
    # 6. signals use only data up to the decision close
    ft = R6.features(mk)
    w0 = 300
    D0 = mk.D[w0]
    lag = d.I.loc[:D0]
    want = lag.iloc[-1] / lag.iloc[-1 - 5 * 13] - 1
    check(f"{sym} TS13 uses data up to the decision close only", abs(ft["ts13"][w0] - want) < 1e-12)
    se = R6.raw_signal("SE", ("1x",), ft)
    m = ft["month_next"][w0]
    past = [ft["wret"][i] for i in range(1, w0 + 1) if ft["month_end"][i] == m and np.isfinite(ft["wret"][i])]
    check(f"{sym} seasonality learns from past weeks only", se[w0] == (np.sign(np.mean(past)) if len(past) >= 3 else 0))
    hi = d.I.loc[:D0].iloc[-21:-1].max()
    check(f"{sym} breakout high excludes the decision day", abs(ft["hi20"][w0] - hi) < 1e-12)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
