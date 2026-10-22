"""AMENDMENT_A1.md: walk-forward evaluation of the selection procedure, plus its current picks.

    python walkforward.py <work_dir>

Every variant's result in every monthly cycle is computed once (a trade depends only on its own
cycle). Each test year's selection then uses only cycles that expired before that year.
"""
from __future__ import annotations

import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

import engine as E
from search import bootstrap_p5

FULL = {"CRUDEOILM": ("CRUDEOIL", "CRUDEOIL", "2020-01-01", "2026-10-31"),
        "NATGASMINI": ("NATURALGAS", "NATURALGAS", "2022-03-01", "2026-10-31")}
MINI = {"CRUDEOILM": ("CRUDEOILM", "CRUDEOILM", "2024-06-01", "2026-10-31"),
        "NATGASMINI": ("NATGASMINI", "NATGASMINI", "2024-06-01", "2026-10-31")}
TEST_YEARS = {"CRUDEOILM": [2022, 2023, 2024, 2025, 2026], "NATGASMINI": [2024, 2025, 2026]}
FILTERS = ("none", "ivrv", "ivrv110")
GRID = E.grid_a1()
K_LISTS = {s: sorted({k for st, k, w in GRID if st == s}) for s, _, _ in GRID}


def variants():
    return [(st, k, w, e, f, pt, sl, tx) for (st, k, w), e, f in itertools.product(GRID, E.ENTRIES, FILTERS)
            for pt, sl, tx in itertools.product(E.PTS, E.SLS, E.TEXITS)]


def chunk_run(args):
    """Per-cycle pnl / roc / capital for a slice of variants: arrays [len(slice), n_cycles]."""
    cycles_path, inst, lo, hi, slip = args
    cycles = pd.read_pickle(cycles_path)
    V = variants()[lo:hi]
    mult, family, tick = E.MULT[inst], E.FAMILY[inst], E.TICK[inst]
    nC = len(cycles)
    P = np.full((len(V), nC), np.nan)
    R = np.full((len(V), nC), np.nan)
    legs_cache = {}
    for vi, (st, k, w, e, f, pt, sl, tx) in enumerate(V):
        for ci, c in enumerate(cycles):
            j0 = E.entry_index(c, e)
            if j0 is None or not E.passes_filter(c, j0, f):
                continue
            key = (ci, st, k, w, e)
            if key not in legs_cache:
                legs_cache[key] = E.legs_for(c, st, k, w, j0)
            legs = legs_cache[key]
            if legs is None:
                continue
            t = E.run_trade(c, legs, j0, mult, family, tick, slip, pt, sl, tx)
            if t is not None:
                P[vi, ci], R[vi, ci] = t["pnl"], t["roc"]
    return lo, hi, slip, P, R


def window(P, R, A, mask):
    valid = ~np.isnan(P) & mask[None, :]
    n = valid.sum(1)
    navail = (A & mask[None, :]).sum(1)
    Pz = np.where(valid, P, 0.0)
    net = Pz.sum(1)
    wins = np.where(valid & (P > 0), P, 0.0).sum(1)
    losses = -np.where(valid & (P < 0), P, 0.0).sum(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        pf = np.where(losses > 0, wins / losses, np.inf)
        mean = net / np.maximum(n, 1)
        var = np.where(valid, (P - mean[:, None]) ** 2, 0.0).sum(1) / np.maximum(n - 1, 1)
        t = mean / (np.sqrt(var) / np.sqrt(np.maximum(n, 1)))
    worst = np.where(valid, R, np.inf).min(1)
    return {"n": n, "coverage": n / np.maximum(navail, 1), "net": net, "pf": pf, "t": t, "worst_roc": worst}


def select(V, P1, R1, P2, A, mask, index, top=3):
    m1, m2 = window(P1, R1, A, mask), window(P2, R1, A, mask)
    elig = ((m1["coverage"] >= 0.70) & (m1["net"] > 0) & (m1["pf"] >= 1.3) & (m1["t"] >= 1.5)
            & (m2["net"] > 0) & (m1["worst_roc"] >= -0.30) & (m1["n"] >= 2))
    ranked = []
    for vi in np.where(elig)[0]:
        st, k, w, e, f, pt, sl, tx = V[vi]
        nb = []
        ks = K_LISTS[st]
        i = ks.index(k)
        for kk in (ks[i - 1] if i > 0 else None, ks[i + 1] if i + 1 < len(ks) else None):
            if kk is not None:
                nb.append((st, kk, w, e, f, pt, sl, tx))
        ei = E.ENTRIES.index(e)
        for ee in (E.ENTRIES[ei - 1] if ei > 0 else None, E.ENTRIES[ei + 1] if ei + 1 < len(E.ENTRIES) else None):
            if ee is not None:
                nb.append((st, k, w, ee, f, pt, sl, tx))
        nb += [(st, k, w, e, ff, pt, sl, tx) for ff in FILTERS if ff != f]
        idx = [index[x] for x in nb if x in index]
        share = np.mean([m1["pf"][j] >= 1.1 for j in idx]) if idx else 0.0
        if share >= 2 / 3:
            r = R1[vi][~np.isnan(R1[vi]) & mask]
            ranked.append((bootstrap_p5(r), vi))
    ranked.sort(reverse=True)
    picks, seen = [], set()
    for p5, vi in ranked:
        st, e = V[vi][0], V[vi][3]
        if (st, e) in seen:
            continue
        seen.add((st, e))
        picks.append((vi, p5))
        if len(picks) == top:
            break
    return picks, int(elig.sum()), len(ranked)


def stats(pnls, rocs):
    p = np.array(pnls, dtype=float)
    if not len(p):
        return {"n": 0}
    eq = np.concatenate([[0.0], np.cumsum(p)])
    return {"n": len(p), "net": float(p.sum()), "win": float((p > 0).mean()),
            "pf": float(p[p > 0].sum() / -p[p < 0].sum()) if (p < 0).any() else float("inf"),
            "worst_pnl": float(p.min()), "worst_roc": float(np.min(rocs)),
            "maxdd": float((np.maximum.accumulate(eq) - eq).max())}


def main(work: str) -> None:
    opt = pd.read_pickle(os.path.join(work, "opt.pkl"))
    fut = pd.read_pickle(os.path.join(work, "fut.pkl"))
    V = variants()
    index = {v: i for i, v in enumerate(V)}
    print(f"{len(V)} variants per instrument", flush=True)
    report = {}
    for inst in FULL:
        res = {}
        for tag, spec in (("full", FULL[inst]), ("mini", MINI[inst])):
            src, fsym, a, b = spec
            cyc = E.build_cycles(opt, fut, src, fsym, a, b)
            path = os.path.join(work, f"cycles_a1_{inst}_{tag}.pkl")
            pd.to_pickle(cyc, path)
            t0 = time.time()
            nC = len(cyc)
            P = {s: np.full((len(V), nC), np.nan) for s in (0.01, 0.02)}
            R = {s: np.full((len(V), nC), np.nan) for s in (0.01, 0.02)}
            step = 600
            jobs = [(path, inst, lo, min(lo + step, len(V)), s) for s in (0.01, 0.02) for lo in range(0, len(V), step)]
            with ProcessPoolExecutor(max_workers=12) as ex:
                for lo, hi, s, p, r in ex.map(chunk_run, jobs):
                    P[s][lo:hi], R[s][lo:hi] = p, r
            A = np.array([[E.entry_index(c, v[3]) is not None for c in cyc] for v in V])
            res[tag] = (cyc, P, R, A)
            print(f"  {inst} {tag}: {nC} cycles ({cyc[0].expiry.date()}..{cyc[-1].expiry.date()}) in {time.time() - t0:.0f}s", flush=True)
        cyc, P, R, A = res["full"]
        years = np.array([c.expiry.year for c in cyc])
        oos, oos2, log = [], [], []
        for Y in TEST_YEARS[inst]:
            train = years < Y
            if train.sum() < 20:
                continue
            picks, n_elig, n_plat = select(V, P[0.01], R[0.01], P[0.02], A, train, index)
            test = years == Y
            for vi, p5 in picks:
                for ci in np.where(test & ~np.isnan(P[0.01][vi]))[0]:
                    oos.append((Y, vi, P[0.01][vi, ci], R[0.01][vi, ci], str(cyc[ci].expiry.date())))
                for ci in np.where(test & ~np.isnan(P[0.02][vi]))[0]:
                    oos2.append(P[0.02][vi, ci])
            yr = [o for o in oos if o[0] == Y]
            log.append({"year": Y, "train_cycles": int(train.sum()), "eligible": n_elig, "plateau": n_plat,
                        "picks": [dict(zip(("struct", "k", "w", "entry", "filt", "pt", "sl", "texit"), V[vi]), p5=p5) for vi, p5 in picks],
                        "test_trades": len(yr), "test_net": float(sum(o[2] for o in yr))})
            print(f"  {inst} test {Y}: trained on {int(train.sum())} cycles, eligible {n_elig}, plateau {n_plat}; "
                  f"picks {[V[vi][:5] for vi, _ in picks]} -> {len(yr)} trades, net Rs{sum(o[2] for o in yr):,.0f}", flush=True)
        st1 = stats([o[2] for o in oos], [o[3] for o in oos])
        st2 = stats(oos2, [0])
        gate = st1.get("n", 0) > 0 and st1["net"] > 0 and st1["pf"] >= 1.15 and st2.get("net", -1) > 0
        allmask = np.ones(len(cyc), dtype=bool)
        final, n_elig, n_plat = select(V, P[0.01], R[0.01], P[0.02], A, allmask, index)
        cycm, Pm, Rm, Am = res["mini"]
        fin = []
        for vi, p5 in final:
            full_st = stats(P[0.01][vi][~np.isnan(P[0.01][vi])], R[0.01][vi][~np.isnan(R[0.01][vi])])
            mini_st = stats(Pm[0.01][vi][~np.isnan(Pm[0.01][vi])], Rm[0.01][vi][~np.isnan(Rm[0.01][vi])])
            by_year = {}
            for ci in np.where(~np.isnan(P[0.01][vi]))[0]:
                by_year.setdefault(int(years[ci]), []).append(float(P[0.01][vi, ci]))
            fin.append({"rule": dict(zip(("struct", "k", "w", "entry", "filt", "pt", "sl", "texit"), V[vi])), "p5": p5,
                        "full_history": full_st, "mini_prices_2024_26": mini_st,
                        "by_year": {y: round(sum(v)) for y, v in sorted(by_year.items())},
                        "net_2x_full": float(np.nansum(P[0.02][vi]))})
        report[inst] = {"walkforward": log, "oos": st1, "oos_2x": st2, "gate_passed": bool(gate),
                        "final_eligible": n_elig, "final_plateau": n_plat, "final_picks": fin}
        print(f"\n{inst}: stitched OUT-OF-SAMPLE {st1} | at 2% slippage net Rs{st2.get('net', 0):,.0f} -> gate {'PASSED' if gate else 'FAILED'}")
        for f in fin:
            print(f"   current pick {f['rule']} | full {f['full_history']} | mini 2024-26 {f['mini_prices_2024_26']} | by year {f['by_year']}")
        np.savez_compressed(os.path.join(work, f"a1_{inst}.npz"), P1=P[0.01], R1=R[0.01], P2=P[0.02], A=A,
                            Pm1=Pm[0.01], Rm1=Rm[0.01])
    json.dump(report, open(os.path.join(work, "walkforward.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1])
