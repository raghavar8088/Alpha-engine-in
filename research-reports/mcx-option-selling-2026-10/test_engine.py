"""Hand-checked cases for engine.run_trade (synthetic 4-day cycle)."""
import numpy as np
import pandas as pd

import engine as E
from tradingai_shared.mcx_option_fees import mcx_option_leg


def cycle(ce_path, pe_path, traded=True):
    dates = list(pd.date_range("2026-01-05", periods=4, freq="B"))
    c = E.Cycle(sym="X", expiry=dates[-1], dates=dates, tdte=np.array([3, 2, 1, 0]),
                F=np.full(4, 100.0), straddle=np.full(4, 8.0), katm=np.full(4, 100.0),
                iv=np.full(4, 0.4), rv20=np.full(4, 0.3))
    ks = np.array([90.0, 100.0, 110.0])
    for cp, path in (("CE", ce_path), ("PE", pe_path)):
        cl = np.zeros((3, 4))
        idx = 2 if cp == "CE" else 0
        cl[idx] = path
        cl[1] = 4.0
        c.strikes[cp], c.close[cp] = ks, cl
        c.high[cp] = cl.copy()
        c.traded[cp] = np.full((3, 4), traded)
    c.step = 10.0
    return c


legs = [("CE", -1, 110.0), ("PE", -1, 90.0)]
# 1. profit target 50%: credit (2.0-0.05)*2 = 3.90; day1 cost 2.0 -> pnl 1.90 < 1.95; day2 cost 1.0 -> exit
t = E.run_trade(cycle([2.0, 1.0, 0.5, 0.1], [2.0, 1.0, 0.5, 0.1]), legs, 0, 10, "CRUDEOIL", 0.05, 0.01,
                pt=0.5, sl=None, texit=0)
fees = 2 * mcx_option_leg(1.95, 10, sell=True)["total"] + 2 * mcx_option_leg(0.55, 10, sell=False)["total"]
assert t["reason"] == "target" and t["exit"] == cycle([0] * 4, [0] * 4).dates[2], t
assert abs(t["credit"] - 39.0) < 1e-9 and abs(t["gross"] - (3.90 - 1.10) * 10) < 1e-9, t
assert abs(t["fees"] - fees) < 1e-9 and abs(t["pnl"] - (28.0 - fees)) < 1e-9, (t["fees"], fees)
assert abs(t["capital"] - 2 * 1.2 * 0.311 * 100 * 10) < 1e-9
# 2. stop at 1x credit: day1 cost 8.0 -> loss 4.10 >= 3.90 -> stop on day1, bought back at 4.0+0.05... each 4.04
t = E.run_trade(cycle([2.0, 4.0, 1.0, 0.1], [2.0, 4.0, 1.0, 0.1]), legs, 0, 10, "CRUDEOIL", 0.05, 0.01,
                pt=None, sl=1.0, texit=0)
assert t["reason"] == "stop" and abs(t["gross"] - (3.90 - 2 * 4.05) * 10) < 1e-9, t
# 3. no management: held to the expiry-day close (texit 0) ; with texit=1 the day before
t0 = E.run_trade(cycle([2.0, 3.0, 1.0, 0.1], [2.0, 3.0, 1.0, 0.1]), legs, 0, 10, "CRUDEOIL", 0.05, 0.01, None, None, 0)
t1 = E.run_trade(cycle([2.0, 3.0, 1.0, 0.1], [2.0, 3.0, 1.0, 0.1]), legs, 0, 10, "CRUDEOIL", 0.05, 0.01, None, None, 1)
assert t0["reason"] == "time" and abs(t0["gross"] - (3.90 - 2 * 0.15) * 10) < 1e-9, t0
assert abs(t1["gross"] - (3.90 - 2 * 1.05) * 10) < 1e-9, t1
# 4. a leg that did not trade on the exit day pays 3x slippage
t = E.run_trade(cycle([2.0, 3.0, 1.0, 0.1], [2.0, 3.0, 1.0, 0.1], traded=True), legs, 0, 10, "CRUDEOIL", 0.05, 0.01, None, None, 0)
c = cycle([2.0, 3.0, 1.0, 0.1], [2.0, 3.0, 1.0, 0.1])
c.traded["CE"][2, 3] = False
t = E.run_trade(c, legs, 0, 10, "CRUDEOIL", 0.05, 0.01, None, None, 0)
assert t["stale_exit_legs"] == 1 and abs(t["gross"] - (3.90 - (0.1 + 0.15) - 0.15) * 10) < 1e-9, t
# 5. a long wing: condor credit nets the wing; capital adds its premium
c = cycle([2.0, 1.0, 0.5, 0.1], [2.0, 1.0, 0.5, 0.1])
legs4 = [("CE", -1, 110.0), ("PE", -1, 90.0), ("CE", 1, 100.0), ("PE", 1, 100.0)]   # odd but checks signs
t = E.run_trade(c, legs4, 0, 10, "CRUDEOIL", 0.05, 0.01, None, None, 0)
assert t is None  # wings costlier than the shorts: no credit -> no trade
print("engine tests passed")
