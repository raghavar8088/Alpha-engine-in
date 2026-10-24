"""Checks for engine7 / run_phase7 on the real MCX contracts.

    python test_engine7.py <work7>
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase6"), HERE):
    sys.path.insert(0, p)
import engine7 as E7  # noqa: E402
import run_phase7 as R7  # noqa: E402

work = sys.argv[1]
U = R7.universe(work)
fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"{'ok  ' if cond else 'FAIL'} {name} {detail}")
    fails += 0 if cond else 1


# 1. each market rolls exactly ROLL[s] trading days before expiry
for s, m in U.mk.items():
    d = m.daily
    days = list(d.index)
    off = 0
    rolls = np.where(d.roll.to_numpy())[0]
    for i in rolls:
        old = d.held.iloc[i - 1]
        last = max(x for x in days if x <= old)
        off += days.index(last) - i != E7.ROLL[s]
    check(f"{s:10s} rolls {E7.ROLL[s]} days before expiry", off == 0 and len(rolls) > 50,
          f"({len(rolls)} rolls since {days[0].date()}, tick {U.ticks[s]})")
# 2. the portfolio return is the sum of the markets' own weekly returns
S = R7.signals(U, "LB", ("long",))
port = U.run(S)
manual = np.zeros(len(U.keys))
for s, m in U.mk.items():
    e = np.where(np.isfinite(U.vol[s]) & (U.vol[s] > 0), np.minimum(1 / E7.MARGIN[s], 0.10 / np.where(U.vol[s] > 0, U.vol[s], 1)), 0.0)
    w = m.returns(e[U.pos_of[s]])
    manual[U.pos_of[s][1:]] += w.net.to_numpy()
check("portfolio = sum of markets", np.allclose(port.net.to_numpy(), manual, atol=1e-15))
# 3. cross-sectional picks are the top / bottom k of the score that week
S = R7.signals(U, "XM", (26, 3))
bad = 0
for w in range(200, len(U.keys), 37):
    sc = {s: U.mom(s, 26)[w] for s in E7.UNIVERSE if np.isfinite(U.mom(s, 26)[w]) and np.isfinite(U.vol[s][w]) and U.vol[s][w] > 0}
    if len(sc) < 6:
        continue
    order = sorted(sc, key=sc.get)
    longs = {s for s in E7.UNIVERSE if S[s][w] == 1}
    shorts = {s for s in E7.UNIVERSE if S[s][w] == -1}
    bad += longs != set(order[-3:]) or shorts != set(order[:3])
check("cross-sectional momentum picks top/bottom 3", bad == 0)
# 4. momentum at week w uses only the index up to that week's decision close
s = "COPPER"
m = U.mk[s]
w = U.pos_of[s][300]
D = U.week_end[w]
lag = U.I[s][w - 26]
check("momentum is causal", np.isfinite(U.mom(s, 26)[w]) and abs(U.mom(s, 26)[w] - (U.I[s][w] / lag - 1)) < 1e-12
      and U.I[s][w] == m.daily.I.loc[:D].iloc[-1])
# 5. exposure is 10% / 60-day vol, capped at the margin limit
x = port.pos.to_numpy()
check("gross exposure within the sum of margin caps", np.nanmax(x) <= sum(1 / E7.MARGIN[s] for s in E7.UNIVERSE) + 1e-9)
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
