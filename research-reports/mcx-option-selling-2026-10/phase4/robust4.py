"""Phase 4 follow-up (after the one-time tests; nothing here selects or re-tunes): robustness of the one
tradeable pass (natural-gas weekly calm-IV strangle), its overlap with N-B, and the "what would 2% a
week take" table for every candidate.

    python robust4.py <work_dir>
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, ".."), os.path.join(HERE, "..", "phase2"), HERE):
    sys.path.insert(0, p)
import engine4 as E4  # noqa: E402
import run_phase4 as R4  # noqa: E402

NG = "NATGASMINI"
PASS = ("WS1", (0.1, None, "ivp<=50", "trade"))


def by_year(rows):
    out = {}
    for r in rows:
        if r["trade"] is not None:
            out.setdefault(r["week"].year, []).append(r["trade"]["pnl"])
    return {y: round(sum(v)) for y, v in sorted(out.items())}


def short(s):
    return {k: (round(s[k], 4) if isinstance(s.get(k), float) else s.get(k)) for k in (
        "traded", "net", "pf", "mean_ret", "pos_weeks", "ge2_weeks", "worst_ret", "maxdd")}


def main(work):
    out = {}
    fam, v = PASS
    parent, mini = R4.books(work, NG)
    rows = R4.run_variant(fam, v, mini, NG, *R4.T2, 0.01)
    s = E4.wstats(rows)
    best = max((r for r in rows if r["trade"]), key=lambda r: r["trade"]["pnl"])
    rep = {"test": short(s), "by_year": by_year(rows),
           "without_best_week": round(s["net"] - best["trade"]["pnl"]),
           "neighbours": {str(n): short(E4.wstats(R4.run_variant(fam, n, mini, NG, *R4.T2, 0.01))) for n in (
               (0.15, None, "ivp<=50", "trade"), (0.1, 1.0, "ivp<=50", "trade"), (0.1, 2.0, "ivp<=50", "trade"),
               (0.1, None, "ivp<=50", "skip"), (0.1, None, "none", "trade"))},
           "slippage_3x": short(E4.wstats(R4.run_variant(fam, v, mini, NG, *R4.T2, 0.03)))}
    ref = json.load(open(os.path.join(work, "p4_reference.json")))
    core = pd.Series(ref["core_by_week"])
    mine = pd.Series({str(r["week"].date()): (r["trade"]["pnl"] if r["trade"] else 0.0) for r in rows})
    rep["weekly_corr_with_core"] = round(float(pd.concat([core, mine], axis=1).fillna(0).corr().iloc[0, 1]), 2)
    out["NG_WS1_robustness"] = rep
    res = json.load(open(os.path.join(work, "p4_results.json")))
    table = []
    for r in res:
        t = r.get("T2_2024_26_mini", {})
        t1 = r.get("T1_2018_19", {})
        table.append({"inst": r["inst"], "family": r["family"], "variant": r["variant"],
                      "T1_net": t1.get("net"), "T2_net": t.get("net"), "T2_mean_pct_week": round(100 * t.get("mean_ret", 0), 2),
                      "T2_profitable_weeks": t.get("pos_weeks"), "T2_weeks_ge_2pct": t.get("ge2_weeks"),
                      "T2_worst_week_pct": round(100 * t.get("worst_ret", 0), 1),
                      "f_star_x_account": t.get("f_star"), "worst_week_at_f_star_pct": round(100 * t["worst_week_at_f_star"], 1)
                      if isinstance(t.get("worst_week_at_f_star"), float) and np.isfinite(t["worst_week_at_f_star"]) else None,
                      "tradeable": r["PASSED"]["tradeable"], "near_target": r["PASSED"]["near_target"],
                      "literal": r["PASSED"]["literal_every_week_2pct"], "walkforward_total": r["walkforward_total"]})
    out["candidates"] = table
    for k, val in rep.items():
        print(f"{k}: {val}")
    print()
    for row in table:
        print(row)
    json.dump(out, open(os.path.join(work, "p4_robust.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1])
