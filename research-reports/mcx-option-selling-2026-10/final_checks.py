"""Robustness for the final list (strict finalists + walk-forward picks + one labelled NG idea).

    python final_checks.py <work_dir>
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

import engine as E
from walkforward import FULL, MINI, K_LISTS

RULES = [
    ("CO-1", "strict-validated", dict(inst="CRUDEOILM", struct="shortput", k=0.5, w=0.0, entry=15, filt="ivrv", pt=None, sl=2.0, texit=0)),
    ("CO-2", "walk-forward pick", dict(inst="CRUDEOILM", struct="trend20", k=1.0, w=0.0, entry=15, filt="ivrv110", pt=None, sl=1.0, texit=1)),
    ("CO-3", "walk-forward pick", dict(inst="CRUDEOILM", struct="trend20", k=0.5, w=0.0, entry=10, filt="ivrv110", pt=None, sl=2.0, texit=0)),
    ("CO-4", "walk-forward pick", dict(inst="CRUDEOILM", struct="trend10", k=0.5, w=0.0, entry=10, filt="ivrv110", pt=None, sl=None, texit=0)),
    ("CO-5", "strict-validated (marginal)", dict(inst="CRUDEOILM", struct="strangle", k=0.5, w=0.0, entry=7, filt="none", pt=None, sl=1.0, texit=0)),
    ("NG-X", "UNVALIDATED (in-sample only)", dict(inst="NATGASMINI", struct="shortcall", k=1.5, w=0.0, entry=7, filt="none", pt=None, sl=1.0, texit=0)),
]


def run(cycles, r, slip=0.01, entry=None, k=None):
    return E.run_variant(cycles, r["struct"], r["k"] if k is None else k, r["w"], r["entry"] if entry is None else entry,
                         r["filt"], r["pt"], r["sl"], r["texit"], E.MULT[r["inst"]], E.FAMILY[r["inst"]],
                         E.TICK[r["inst"]], slip)


def st(tr):
    if not tr:
        return {"n": 0, "net": 0.0}
    p = np.array([t["pnl"] for t in tr])
    roc = np.array([t["roc"] for t in tr])
    eq = np.concatenate([[0], np.cumsum(p)])
    return {"n": len(p), "net": round(float(p.sum())), "win": round(float((p > 0).mean()), 3),
            "pf": round(float(p[p > 0].sum() / -p[p < 0].sum()), 2) if (p < 0).any() else float("inf"),
            "avg": round(float(p.mean())), "worst": round(float(p.min())), "worst_roc": round(float(roc.min()), 3),
            "maxdd": round(float((np.maximum.accumulate(eq) - eq).max())),
            "avg_capital": round(float(np.mean([t["capital"] for t in tr]))),
            "avg_credit": round(float(np.mean([t["credit"] for t in tr]))),
            "avg_fees": round(float(np.mean([t["fees"] for t in tr]))),
            "mean_roc": round(float(roc.mean()), 4)}


def main(work):
    opt = pd.read_pickle(os.path.join(work, "opt.pkl"))
    fut = pd.read_pickle(os.path.join(work, "fut.pkl"))
    cyc = {}
    for inst in ("CRUDEOILM", "NATGASMINI"):
        cyc[(inst, "full")] = pd.read_pickle(os.path.join(work, f"cycles_a1_{inst}_full.pkl"))
        cyc[(inst, "mini")] = pd.read_pickle(os.path.join(work, f"cycles_a1_{inst}_mini.pkl"))
    out, monthly = {}, {}
    for name, label, r in RULES:
        full, mini = cyc[(r["inst"], "full")], cyc[(r["inst"], "mini")]
        tr_full = run(full, r)
        res = {"label": label, "rule": r, "full_history": st(tr_full), "mini_2024_26": st(run(mini, r))}
        res["slippage_full"] = {f"{s:.0%}": st(run(full, r, s))["net"] for s in (0.01, 0.02, 0.03)}
        res["slippage_mini"] = {f"{s:.0%}": st(run(mini, r, s))["net"] for s in (0.01, 0.02, 0.03)}
        res["entry_shift_full"] = {str(r["entry"] + d): st(run(full, r, entry=r["entry"] + d))["net"]
                                   for d in (-2, 2) if r["entry"] + d >= 2}
        ks = K_LISTS[r["struct"]]
        i = ks.index(r["k"])
        res["k_shift_full"] = {str(kk): st(run(full, r, k=kk))["net"]
                               for kk in (ks[i - 1] if i > 0 else None, ks[i + 1] if i + 1 < len(ks) else None) if kk is not None}
        if tr_full:
            best = max(tr_full, key=lambda t: t["pnl"])
            res["full_without_best"] = st([t for t in tr_full if t is not best])["net"]
        by_year = {}
        for t in tr_full:
            by_year.setdefault(t["expiry"].year, []).append(t["pnl"])
        res["by_year_full"] = {y: round(sum(v)) for y, v in sorted(by_year.items())}
        res["reasons"] = pd.Series([t["reason"] for t in tr_full]).value_counts().to_dict()
        res["stale_exit_legs"] = int(sum(t["stale_exit_legs"] for t in tr_full))
        monthly[name] = pd.Series({t["expiry"]: t["pnl"] for t in tr_full})
        out[name] = res
        pd.DataFrame(tr_full).to_csv(os.path.join(work, f"final_trades_{name}.csv"), index=False)
        print(f"\n{name} [{label}] {r}")
        for kk in ("full_history", "mini_2024_26"):
            print(f"  {kk}: {res[kk]}")
        print(f"  slippage full {res['slippage_full']} | mini {res['slippage_mini']}")
        print(f"  entry shift {res['entry_shift_full']} | k shift {res['k_shift_full']} | without best trade {res.get('full_without_best')}")
        print(f"  by year {res['by_year_full']} | exits {res['reasons']} | stale exit legs {res['stale_exit_legs']}")
    crude = pd.DataFrame({k: v for k, v in monthly.items() if k.startswith("CO")})
    print("\nmonthly P&L correlation between the crude strategies (same expiry):")
    print(crude.corr().round(2).to_string())
    json.dump(out, open(os.path.join(work, "final_checks.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1])
