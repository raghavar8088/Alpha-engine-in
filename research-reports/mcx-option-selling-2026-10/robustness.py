"""Robustness and trade logs for the finalists (run after validate.py).

    python robustness.py <work_dir>
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

import engine as E
from search import DISCOVERY, K_LISTS, metrics
from validate import V_FROM, V_TO, VALIDATION, run


def summarise(trades):
    if not trades:
        return {"n": 0}
    m = metrics(trades, len(trades))
    return {k: m[k] for k in ("n", "net", "mean", "win", "pf", "mean_roc", "worst_roc", "worst_pnl", "maxdd", "avg_capital")}


def main(work: str) -> None:
    opt = pd.read_pickle(os.path.join(work, "opt.pkl"))
    fut = pd.read_pickle(os.path.join(work, "fut.pkl"))
    vals = {v["key"]: v for v in json.load(open(os.path.join(work, "validation.json")))}
    finals = json.load(open(os.path.join(work, "finalists.json")))
    out = {}
    cyc = {}
    for key in finals:
        c = dict(vals[key])
        c["entry"], c["texit"] = int(c["entry"]), int(c["texit"])
        c["k"], c["w"] = float(c["k"]), float(c["w"])
        for c_ in ("pt", "sl"):
            c[c_] = None if c[c_] in (None, "None") or (isinstance(c[c_], float) and np.isnan(c[c_])) else float(c[c_])
        inst = c["inst"]
        if ("v", inst) not in cyc:
            src, fsym = VALIDATION[inst][0]
            cyc[("v", inst)] = E.build_cycles(opt, fut, src, fsym, V_FROM, V_TO)
            s, fs, a, b = DISCOVERY[inst]
            cyc[("d", inst)] = E.build_cycles(opt, fut, s, fs, a, b)
        vcy, dcy = cyc[("v", inst)], cyc[("d", inst)]
        rep = {"rule": {k: c[k] for k in ("inst", "struct", "k", "w", "entry", "filt", "pt", "sl", "texit")}}
        dtr, vtr = run(dcy, c), run(vcy, c)
        rep["discovery"], rep["validation"] = summarise(dtr), summarise(vtr)
        rep["slippage"] = {f"{s:.0%}": summarise(run(vcy, c, s)) for s in (0.01, 0.02, 0.03)}
        rep["entry_shift"] = {str(c["entry"] + d): summarise(run(vcy, c, 0.01, entry=c["entry"] + d))
                              for d in (-2, +2) if c["entry"] + d >= 2}
        ks = K_LISTS[c["struct"]]
        i = ks.index(c["k"])
        rep["k_shift"] = {str(kk): summarise(run(vcy, c, 0.01, k=kk))
                          for kk in (ks[i - 1] if i > 0 else None, ks[i + 1] if i + 1 < len(ks) else None) if kk is not None}
        alltr = dtr + vtr
        if alltr:
            best = max(alltr, key=lambda t: t["pnl"])
            rep["without_best_month"] = summarise([t for t in alltr if t is not best])
            rep["without_best_month"]["removed"] = str(best["expiry"].date())
        years = {}
        for t in alltr:
            y = t["expiry"].year
            years.setdefault(y, []).append(t["pnl"])
        rep["by_year"] = {y: {"n": len(v), "net": float(np.sum(v)), "win": float(np.mean(np.array(v) > 0))}
                          for y, v in sorted(years.items())}
        pd.DataFrame(dtr).assign(period="discovery (parent prices)").pipe(
            lambda d: pd.concat([d, pd.DataFrame(vtr).assign(period="validation (mini prices)")])).to_csv(
            os.path.join(work, f"trades_{key.replace('|', '_').replace('=', '-')}.csv"), index=False)
        out[key] = rep
        print(f"\n=== {key}")
        for sec in ("discovery", "validation"):
            r = rep[sec]
            print(f"  {sec:<10} n={r['n']} net=Rs{r.get('net', 0):,.0f} win={r.get('win', 0):.0%} pf={r.get('pf', 0):.2f} "
                  f"mean_roc={r.get('mean_roc', 0):.2%} worst={r.get('worst_roc', 0):.1%} maxdd=Rs{r.get('maxdd', 0):,.0f}")
        print("  slippage:", {k: round(v.get("net", 0)) for k, v in rep["slippage"].items()})
        print("  entry shift:", {k: round(v.get("net", 0)) for k, v in rep["entry_shift"].items()})
        print("  k shift:", {k: round(v.get("net", 0)) for k, v in rep["k_shift"].items()})
        print("  without best month:", round(rep["without_best_month"].get("net", 0)), "removed", rep["without_best_month"].get("removed"))
        print("  by year:", {y: round(v["net"]) for y, v in rep["by_year"].items()})
    json.dump(out, open(os.path.join(work, "robustness.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1])
