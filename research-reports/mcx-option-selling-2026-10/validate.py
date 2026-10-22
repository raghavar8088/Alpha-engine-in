"""VALIDATION (PROTOCOL.md): run ONCE on the frozen candidates, on the minis' own prices.

    python validate.py <work_dir>
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import pandas as pd

import b76
import engine as E
from search import metrics

VALIDATION = {
    "CRUDEOILM": [("CRUDEOILM", "CRUDEOILM"), ("CRUDEOIL", "CRUDEOIL")],     # primary, cross-check
    "NATGASMINI": [("NATGASMINI", "NATGASMINI"), ("NATURALGAS", "NATURALGAS")],
}
V_FROM, V_TO = "2024-06-01", "2026-10-31"
N_TRIALS = 9180


def ninv(p: float) -> float:
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if float(b76.ncdf(mid)) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def deflated_sharpe(r: np.ndarray, sr_var: float, n_trials: int = N_TRIALS) -> float:
    """Bailey & Lopez de Prado (2014). Per-trade Sharpe, benchmark = expected max of n_trials."""
    if len(r) < 3 or r.std(ddof=1) == 0:
        return float("nan")
    sr = r.mean() / r.std(ddof=1)
    g = 0.5772156649
    sr0 = math.sqrt(sr_var) * ((1 - g) * ninv(1 - 1 / n_trials) + g * ninv(1 - 1 / (n_trials * math.e)))
    skew = float(((r - r.mean()) ** 3).mean() / r.std() ** 3)
    kurt = float(((r - r.mean()) ** 4).mean() / r.std() ** 4)
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr * sr, 1e-12))
    return float(b76.ncdf((sr - sr0) * math.sqrt(len(r) - 1) / denom))


def run(cycles, c, slip=0.01, entry=None, k=None):
    return E.run_variant(cycles, c["struct"], c["k"] if k is None else k, c["w"],
                         c["entry"] if entry is None else entry, c["filt"], c["pt"], c["sl"], c["texit"],
                         E.MULT[c["inst"]], E.FAMILY[c["inst"]], E.TICK[c["inst"]], slip)


def main(work: str) -> None:
    opt = pd.read_pickle(os.path.join(work, "opt.pkl"))
    fut = pd.read_pickle(os.path.join(work, "fut.pkl"))
    cands = json.load(open(os.path.join(work, "candidates.json")))
    for c in cands:                      # JSON turned integers into floats; the engine indexes days
        c["entry"], c["texit"] = int(c["entry"]), int(c["texit"])
        c["k"], c["w"] = float(c["k"]), float(c["w"])
    disc = pd.read_csv(os.path.join(work, "discovery_metrics.csv"))
    roc = pd.read_pickle(os.path.join(work, "discovery_roc.pkl"))
    cyc = {}
    for inst, srcs in VALIDATION.items():
        for src, fsym in srcs:
            cyc[(inst, src)] = E.build_cycles(opt, fut, src, fsym, V_FROM, V_TO)
            print(f"validation cycles {inst} on {src}: {len(cyc[(inst, src)])}", flush=True)
    results = []
    for c in cands:
        prim, cross = VALIDATION[c["inst"]][0][0], VALIDATION[c["inst"]][1][0]
        cy = cyc[(c["inst"], prim)]
        n_avail = sum(1 for x in cy if E.entry_index(x, c["entry"]) is not None)
        tr1 = run(cy, c, 0.01)
        m1 = metrics(tr1, n_avail)
        m2 = metrics(run(cy, c, 0.02), n_avail)
        m3 = metrics(run(cy, c, 0.03), n_avail)
        mx = metrics(run(cyc[(c["inst"], cross)], c, 0.01), n_avail)
        disc_worst = c["worst_roc"]
        passed = (m1.get("n", 0) > 0 and m1["net"] > 0 and m1["pf"] >= 1.15
                  and m1["worst_roc"] >= 1.5 * disc_worst and m2.get("net", -1) > 0)
        results.append({**c, "v_n": m1.get("n", 0), "v_net": m1.get("net"), "v_pf": m1.get("pf"),
                        "v_mean_roc": m1.get("mean_roc"), "v_sd_roc": m1.get("sd_roc"),
                        "v_worst_roc": m1.get("worst_roc"), "v_maxdd": m1.get("maxdd"),
                        "v_net_2x": m2.get("net"), "v_net_3x": m3.get("net"),
                        "x_net_parent": mx.get("net"), "x_pf_parent": mx.get("pf"),
                        "passed": bool(passed), "_trades": tr1})
        print(f"{c['inst']:<10} {c['struct']:<10} k={c['k']} w={c['w']} e={c['entry']} {c['filt']} pt={c['pt']} sl={c['sl']} "
              f"tx={c['texit']} -> n={m1.get('n', 0)} net=Rs{m1.get('net', 0):,.0f} pf={m1.get('pf', 0):.2f} "
              f"worst={m1.get('worst_roc', 0):.1%} 2x=Rs{m2.get('net', 0):,.0f} parent=Rs{mx.get('net', 0):,.0f} "
              f"{'PASS' if passed else 'fail'}", flush=True)
    passers = [r for r in results if r["passed"]]
    for r in passers:
        r["v_score"] = r["v_mean_roc"] / r["v_sd_roc"] if r["v_sd_roc"] else float("nan")
    passers.sort(key=lambda r: r["v_score"], reverse=True)
    final, per = [], {}
    for r in passers:
        if per.get(r["inst"], 0) >= 3:
            continue
        final.append(r)
        per[r["inst"]] = per.get(r["inst"], 0) + 1
        if len(final) == 5:
            break
    # Deflated Sharpe: variance of per-trade Sharpe across every discovery trial of that instrument
    for r in final:
        inst_keys = disc[(disc.inst == r["inst"]) & (disc.n >= 5)].key
        srs = [roc[k].mean() / roc[k].std(ddof=1) for k in inst_keys if k in roc and len(roc[k]) > 2 and roc[k].std(ddof=1) > 0]
        rr = np.array([t["roc"] for t in r["_trades"]])
        r["dsr_validation"] = deflated_sharpe(rr, float(np.var(srs)))
        r["dsr_discovery"] = deflated_sharpe(roc[r["key"]], float(np.var(srs)))
    out = []
    for r in results:
        out.append({k: v for k, v in r.items() if k != "_trades"})
    json.dump(out, open(os.path.join(work, "validation.json"), "w"), indent=1, default=str)
    pd.to_pickle({r["key"]: r["_trades"] for r in results}, os.path.join(work, "validation_trades.pkl"))
    json.dump([r["key"] for r in final], open(os.path.join(work, "finalists.json"), "w"), indent=1)
    print(f"\n{len(passers)} of {len(results)} candidates passed validation; finalists: {len(final)}")
    for r in final:
        print(f"  {r['inst']} {r['key']} | val net Rs{r['v_net']:,.0f} pf {r['v_pf']:.2f} score {r['v_score']:.2f} "
              f"DSR(val) {r['dsr_validation']:.2f} DSR(disc) {r['dsr_discovery']:.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
