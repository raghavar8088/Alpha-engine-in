"""Print every table the report quotes, straight from the saved outputs (no recomputation).

    python make_tables.py <work_dir>
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

work = sys.argv[1]
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)

print("== VRP (implied vs realised, per monthly cycle)")
v = pd.read_csv(os.path.join(work, "vrp_cycles.csv"), parse_dates=["expiry"])
v["period"] = np.where(v.expiry >= "2024-06-01", "Jun24-Oct26", "before Jun24")
g = v.groupby(["sym", "tdte", "period"]).agg(n=("iv", "size"), iv=("iv", "mean"), rv=("rv_fwd", "mean"),
                                              iv_gt_rv=("iv_minus_rv", lambda s: (s > 0).mean()),
                                              straddle_won=("straddle_won", "mean"))
print(g.round(3).to_string())

d = pd.read_csv(os.path.join(work, "discovery_metrics.csv"))
print("\n== Discovery: how many variants clear each rule (cumulative)")
for inst, x in d.groupby("inst"):
    r1 = x[x.coverage >= 0.7]
    r2 = r1[r1.net > 0]
    r3 = r2[r2.pf >= 1.3]
    r4 = r3[r3.t >= 1.5]
    r5 = r4[r4.net_2x > 0]
    r6 = r5[r5.worst_roc >= -0.30]
    print(f"  {inst}: {len(x)} variants -> coverage {len(r1)} -> net>0 {len(r2)} -> PF>=1.3 {len(r3)} -> "
          f"t>=1.5 {len(r4)} -> 2x slip {len(r5)} -> worst>=-30% {len(r6)}")
    print(f"     share of ALL variants with net > 0: {(x.net > 0).mean():.0%}; by structure:")
    s = x[x.coverage >= 0.7].groupby("struct").agg(n=("net", "size"), profitable=("net", lambda s: (s > 0).mean()),
                                                    median_net=("net", "median"), best_net=("net", "max"))
    print(s.round(2).to_string())

if os.path.exists(os.path.join(work, "candidates.json")):
    print("\n== Candidates (frozen)")
    for c in json.load(open(os.path.join(work, "candidates.json"))):
        print(" ", c["inst"], c["key"], f"n={c['n']:.0f} net={c['net']:,.0f} pf={c['pf']:.2f} t={c['t']:.2f} p5={c['boot_p5_roc']:.2%}")
if os.path.exists(os.path.join(work, "validation.json")):
    print("\n== Validation")
    for c in json.load(open(os.path.join(work, "validation.json"))):
        print(" ", "PASS" if c["passed"] else "fail", c["inst"], c["key"], f"v_n={c['v_n']} v_net={c['v_net']} v_pf={c['v_pf']} "
              f"v_worst={c['v_worst_roc']} 2x={c['v_net_2x']} 3x={c['v_net_3x']} parent={c['x_net_parent']}")
