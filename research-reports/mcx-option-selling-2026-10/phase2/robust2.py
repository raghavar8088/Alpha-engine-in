"""Phase 2 robustness for the 4 holdout passers + last 30 days + Rs10 lakh sizing.

    python robust2.py <work_dir>
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

import engine as E
from run_phase2 import HOLD, load, run_variant, stats

PASSERS = {
    "C-B": ("CRUDEOILM", ("dput", 0.15, 5, None, None)),
    "C-C": ("CRUDEOILM", ("dstrangle", 0.15, 5, None, None)),
    "C-E": ("CRUDEOILM", ("dh", None, 10, None, None)),
    "N-B": ("NATGASMINI", ("dstrangle", 0.10, 10, ("le", 50), None)),
}
CAP = 1_000_000


def capital(t):
    return t["capital"] + t.get("hedge_margin_peak", 0.0)


def main(work):
    cyc = load(work)
    out = {}
    for name, (inst, v) in PASSERS.items():
        full, mini, ivp = cyc[(inst, "full")], cyc[(inst, "mini")], cyc[(inst, "ivpct")]
        tf, _ = run_variant(full, inst, v, ivp, 0.01)
        tm, _ = run_variant(mini, inst, v, ivp, 0.01)
        s, d, e, f, sl = v
        rep = {"full_history": stats(tf), "holdout_mini": stats(tm)}
        rep["entry_shift"] = {str(e + k): stats(run_variant(full, inst, (s, d, e + k, f, sl), ivp, 0.01)[0])["net"] for k in (-2, 2)}
        if s == "dh":
            import run_phase2 as R
            shifts = {}
            for lots in (5, 20):
                R.DH_LOTS = lots
                shifts[f"{lots} lots"] = stats(run_variant(full, inst, v, ivp, 0.01)[0])["net"] * 10 / lots
            R.DH_LOTS = 10
            rep["hedge_granularity_per10lots"] = shifts
            caps = [capital(t) for t in tm]
            rep["capital_incl_hedge_margin"] = {"avg": round(float(np.mean(caps))), "max": round(float(np.max(caps))),
                                                "avg_peak_hedge_lots": round(float(np.mean([t["max_hedge_lots"] for t in tm])), 1)}
        else:
            alt = {"dput": (0.10, 0.20), "dstrangle": (0.10, 0.20) if d == 0.15 else (0.08, 0.15)}[s]
            rep["delta_shift"] = {str(dd): stats(run_variant(full, inst, (s, dd, e, f, sl), ivp, 0.01)[0])["net"] for dd in alt}
        if f is not None:
            rep["filter_shift"] = {f"{f[0]}{th}": stats(run_variant(full, inst, (s, d, e, (f[0], th), sl), ivp, 0.01)[0])["net"] for th in (40, 60)}
        if tf:
            best = max(tf, key=lambda t: t["pnl"])
            rep["full_without_best"] = stats([t for t in tf if t is not best])["net"]
        yrs = {}
        for t in tf:
            yrs.setdefault(t["expiry"].year, []).append(t["pnl"])
        rep["by_year_full"] = {y: round(sum(p)) for y, p in sorted(yrs.items())}
        # last 30 days on the mini's own prices, and Rs10 lakh sizing
        last = [t for t in tm if t["exit"] >= pd.Timestamp("2026-09-22")]
        worst = min(tm, key=lambda t: t["pnl"]) if tm else None
        unit = "10-lot unit" if s == "dh" else "lot"
        rows = []
        for t in last:
            cap1 = capital(t)
            for label, frac in (("half kept as buffer", 0.5), ("all as margin", 1.0)):
                n = int(CAP * frac // cap1)
                rows.append({"label": label, "units": n, "pnl": round(t["pnl"] * n), "pct": round(t["pnl"] * n / CAP * 100, 2),
                             "worst_month_same_size": round(worst["pnl"] * n) if worst else None})
            rep["last30"] = {"trade": f"{t['legs']} entered {t['entry'].date()} exit {t['exit'].date()} ({t['reason']})",
                             f"pnl_per_{unit}": round(t["pnl"]), f"capital_per_{unit}": round(cap1), "sizing_10_lakh": rows,
                             "worst_month": str(worst["expiry"].date()) if worst else None}
        if not last:
            rep["last30"] = "no trade in the last 30 days (filter or no entry)"
        out[name] = rep
        pd.DataFrame(tf).to_csv(os.path.join(work, f"p2_full_trades_{name}.csv"), index=False)
        print(f"\n=== {name} {inst} {v}")
        for k, val in rep.items():
            print(f"  {k}: {val}")
    # correlation with the Phase 1 crude strategies (same expiries, parent prices)
    per = {}
    for n in ("CO-1", "CO-2", "CO-3"):
        t = pd.read_csv(os.path.join(work, f"final_trades_{n}.csv"), parse_dates=["expiry"])
        per[n] = t.set_index("expiry").pnl
    for n in ("C-B", "C-C", "C-E"):
        t = pd.read_csv(os.path.join(work, f"p2_full_trades_{n}.csv"), parse_dates=["expiry"])
        per[n] = t.set_index("expiry").pnl
    print("\nper-cycle P&L correlation (crude):")
    print(pd.DataFrame(per).corr().round(2).to_string())
    json.dump(out, open(os.path.join(work, "p2_robust.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1])
