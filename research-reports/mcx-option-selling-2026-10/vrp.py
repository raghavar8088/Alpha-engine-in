"""Is there a premium to sell? ATM implied vol at entry vs the vol that then happened.

    python vrp.py <work_dir>

For each monthly cycle, at 20 and 10 trading days to expiry: the ATM straddle's implied vol
(Black-76, traded legs only) against the realised vol of the underlying future from that day
to expiry (close-to-close, annualised over 252 sessions). Purely descriptive.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd

import engine as E

work = sys.argv[1]
opt = pd.read_pickle(os.path.join(work, "opt.pkl"))
fut = pd.read_pickle(os.path.join(work, "fut.pkl"))
rows = []
for sym, fsym, a, b in (("CRUDEOIL", "CRUDEOIL", "2019-01-01", "2026-10-31"),
                        ("NATURALGAS", "NATURALGAS", "2022-03-01", "2026-10-31"),
                        ("CRUDEOILM", "CRUDEOILM", "2024-06-01", "2026-10-31"),
                        ("NATGASMINI", "NATGASMINI", "2024-06-01", "2026-10-31")):
    for c in E.build_cycles(opt, fut, sym, fsym, a, b):
        for n in (20, 10):
            j = E.entry_index(c, n)
            if j is None or not np.isfinite(c.iv[j]):
                continue
            path = c.F[j:]
            path = path[np.isfinite(path)]
            if len(path) < 4:
                continue
            lr = np.diff(np.log(path))
            rv = float(np.sqrt(np.mean(lr ** 2)) * math.sqrt(252))
            # the straddle's breakeven vs the move that happened
            move = abs(path[-1] - path[0])
            rows.append({"sym": sym, "expiry": c.expiry, "tdte": n, "iv": c.iv[j], "rv_fwd": rv,
                         "straddle": c.straddle[j], "move": move, "F": path[0]})
df = pd.DataFrame(rows)
df["year"] = df.expiry.dt.year
df["iv_minus_rv"] = df.iv - df.rv_fwd
df["straddle_won"] = df.straddle > df.move
df.to_csv(os.path.join(work, "vrp_cycles.csv"), index=False)
for (sym, n), g in df.groupby(["sym", "tdte"]):
    print(f"{sym:<11} T-{n:<2} cycles {len(g):>3} | ATM IV {g.iv.mean():.1%} vs realised {g.rv_fwd.mean():.1%} "
          f"| IV > RV in {(g.iv > g.rv_fwd).mean():.0%} of cycles | straddle > |move| in {g.straddle_won.mean():.0%} "
          f"| mean (straddle - |move|)/F {((g.straddle - g.move) / g.F).mean():+.2%}")
print()
for (sym, y), g in df[df.tdte == 20].groupby(["sym", "year"]):
    print(f"  {sym:<11} {y}: n {len(g):>2}  IV {g.iv.mean():.0%}  RV {g.rv_fwd.mean():.0%}  "
          f"IV>RV {(g.iv > g.rv_fwd).mean():.0%}  straddle>move {g.straddle_won.mean():.0%}")
