"""DISCOVERY search (PROTOCOL.md): every variant on the discovery period, then the fixed rules.

    python search.py <work_dir>

Writes <work_dir>/discovery_metrics.csv (every variant), discovery_roc.pkl (per-trade returns) and
candidates.json (the frozen candidate list). Validation data is not loaded here at all.
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

DISCOVERY = {
    # instrument traded: (price-source option symbol, its futures symbol, expiry from, to)
    "CRUDEOILM": ("CRUDEOIL", "CRUDEOIL", "2020-01-01", "2024-05-31"),
    "NATGASMINI": ("NATURALGAS", "NATURALGAS", "2022-03-01", "2024-04-30"),
}
K_LISTS = {s: sorted({k for st, k, w in E.structure_grid() if st == s}) for s in E.STRUCT_LEGS}


def variant_key(v: dict) -> str:
    return "|".join(f"{k}={v[k]}" for k in ("inst", "struct", "k", "w", "entry", "filt", "pt", "sl", "texit"))


def metrics(trades: list[dict], n_avail: int) -> dict:
    if not trades:
        return {"n": 0, "coverage": 0.0}
    p = np.array([t["pnl"] for t in trades])
    r = np.array([t["roc"] for t in trades])
    wins, losses = p[p > 0].sum(), -p[p < 0].sum()
    sd = p.std(ddof=1) if len(p) > 1 else np.nan
    eq = np.cumsum(p)
    dd = float((np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq])).max())
    return {"n": len(p), "coverage": len(p) / max(n_avail, 1), "net": p.sum(), "mean": p.mean(),
            "median": float(np.median(p)), "win": (p > 0).mean(), "pf": wins / losses if losses > 0 else np.inf,
            "t": p.mean() / (sd / np.sqrt(len(p))) if sd and sd > 0 else np.nan,
            "mean_roc": r.mean(), "sd_roc": r.std(ddof=1) if len(r) > 1 else np.nan, "worst_roc": r.min(),
            "worst_pnl": p.min(), "maxdd": dd, "avg_capital": float(np.mean([t["capital"] for t in trades])),
            "stops": sum(t["reason"] == "stop" for t in trades), "stale": sum(t["stale_exit_legs"] for t in trades)}


def run_instrument(args):
    inst, cycles_path, slip = args
    cycles = pd.read_pickle(cycles_path)
    mult, family, tick = E.MULT[inst], E.FAMILY[inst], E.TICK[inst]
    rows, all_trades = [], {}
    for (struct, k, w), n_entry, filt in itertools.product(E.structure_grid(), E.ENTRIES, E.FILTERS):
        n_avail = sum(1 for c in cycles if E.entry_index(c, n_entry) is not None)
        prepared = []
        for c in cycles:
            j0 = E.entry_index(c, n_entry)
            if j0 is None:
                continue
            if filt == "ivrv" and not (np.isfinite(c.iv[j0]) and np.isfinite(c.rv20[j0]) and c.iv[j0] > c.rv20[j0]):
                continue
            legs = E.legs_for(c, struct, k, w, j0)
            if legs is not None:
                prepared.append((c, legs, j0))
        for pt, sl, texit in itertools.product(E.PTS, E.SLS, E.TEXITS):
            v = {"inst": inst, "struct": struct, "k": k, "w": w, "entry": n_entry, "filt": filt,
                 "pt": pt, "sl": sl, "texit": texit}
            trades = []
            for c, legs, j0 in prepared:
                t = E.run_trade(c, legs, j0, mult, family, tick, slip, pt, sl, texit)
                if t is not None:
                    trades.append(t)
            m = metrics(trades, n_avail)
            rows.append({**v, **m, "key": variant_key(v)})
            if slip == 0.01:      # per-trade return on capital, for the bootstrap; full logs are rebuilt later
                all_trades[variant_key(v)] = np.array([t["roc"] for t in trades], dtype=np.float64)
    return inst, slip, rows, all_trades


def bootstrap_p5(r: np.ndarray, draws: int = 5000, seed: int = 7) -> float:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(r), size=(draws, len(r)))
    return float(np.percentile(r[idx].mean(axis=1), 5))


def neighbours(row: pd.Series, by_key: dict) -> list:
    out = []
    ks = K_LISTS[row.struct]
    i = ks.index(row.k)
    for kk in (ks[i - 1] if i > 0 else None, ks[i + 1] if i + 1 < len(ks) else None):
        if kk is not None:
            out.append({**row.to_dict(), "k": kk})
    ei = E.ENTRIES.index(row.entry)
    for ee in (E.ENTRIES[ei - 1] if ei > 0 else None, E.ENTRIES[ei + 1] if ei + 1 < len(E.ENTRIES) else None):
        if ee is not None:
            out.append({**row.to_dict(), "entry": ee})
    out.append({**row.to_dict(), "filt": "none" if row.filt == "ivrv" else "ivrv"})
    res = []
    for v in out:
        key = variant_key({**v, "pt": None if pd.isna(v["pt"]) else v["pt"], "sl": None if pd.isna(v["sl"]) else v["sl"]})
        if key in by_key:
            res.append(by_key[key])
    return res


def main(work: str) -> None:
    opt = pd.read_pickle(os.path.join(work, "opt.pkl"))
    fut = pd.read_pickle(os.path.join(work, "fut.pkl"))
    paths = {}
    for inst, (src, fsym, a, b) in DISCOVERY.items():
        t0 = time.time()
        cyc = E.build_cycles(opt, fut, src, fsym, a, b)
        p = os.path.join(work, f"cycles_discovery_{inst}.pkl")
        pd.to_pickle(cyc, p)
        paths[inst] = p
        print(f"{inst}: {len(cyc)} discovery cycles from {src} ({cyc[0].expiry.date()} .. {cyc[-1].expiry.date()}) "
              f"in {time.time() - t0:.0f}s", flush=True)
    jobs = [(inst, paths[inst], s) for inst in DISCOVERY for s in (0.01, 0.02)]
    rows, trades = [], {}
    with ProcessPoolExecutor(max_workers=4) as ex:
        for inst, slip, r, tr in ex.map(run_instrument, jobs):
            for x in r:
                x["slip"] = slip
            rows += r
            trades.update(tr)
            print(f"  ran {inst} at slippage {slip:.0%}: {len(r)} variants", flush=True)
    df = pd.DataFrame(rows)
    base = df[df.slip == 0.01].copy()
    two = df[df.slip == 0.02].set_index("key")["net"]
    base["net_2x"] = base["key"].map(two)
    base.to_csv(os.path.join(work, "discovery_metrics.csv"), index=False)
    pd.to_pickle(trades, os.path.join(work, "discovery_roc.pkl"))

    # ---- the fixed selection rules
    elig = base[(base.coverage >= 0.70) & (base.net > 0) & (base.pf >= 1.3) & (base.t >= 1.5)
                & (base.net_2x > 0) & (base.worst_roc >= -0.30)].copy()
    by_key = {r.key: r for r in base.itertuples()}
    keep = []
    for _, row in elig.iterrows():
        nb = neighbours(row, by_key)
        ok = sum(1 for x in nb if x.pf >= 1.1) / len(nb) if nb else 0.0
        if ok >= 2 / 3:
            keep.append((row.key, ok))
    plateau = elig[elig.key.isin([k for k, _ in keep])].copy()
    plateau["plateau_share"] = plateau.key.map(dict(keep))
    plateau["boot_p5_roc"] = [bootstrap_p5(trades[k]) for k in plateau.key]
    plateau = plateau.sort_values("boot_p5_roc", ascending=False)
    plateau.to_csv(os.path.join(work, "discovery_eligible.csv"), index=False)
    cands = []
    for inst in DISCOVERY:
        seen = set()
        for _, r in plateau[plateau.inst == inst].iterrows():
            if (r.struct, r.entry) in seen:
                continue
            seen.add((r.struct, r.entry))
            cands.append({k: (None if isinstance(r[k], float) and np.isnan(r[k]) else r[k])
                          for k in ("inst", "struct", "k", "w", "entry", "filt", "pt", "sl", "texit", "key",
                                    "n", "net", "pf", "t", "mean_roc", "worst_roc", "boot_p5_roc", "plateau_share")})
            if sum(1 for c in cands if c["inst"] == inst) == 6:
                break
    json.dump(cands, open(os.path.join(work, "candidates.json"), "w"), indent=1, default=float)
    print(f"\nvariants: {len(base)} | eligible: {len(elig)} | on a plateau: {len(plateau)} | candidates: {len(cands)}")
    for c in cands:
        print(f"  {c['inst']:<10} {c['struct']:<10} k={c['k']} w={c['w']} entry={c['entry']} filt={c['filt']} "
              f"pt={c['pt']} sl={c['sl']} texit={c['texit']} | n={c['n']} net=Rs{c['net']:,.0f} pf={c['pf']:.2f} "
              f"t={c['t']:.2f} mean_roc={c['mean_roc']:.2%} worst={c['worst_roc']:.1%} p5={c['boot_p5_roc']:.2%}")


if __name__ == "__main__":
    main(sys.argv[1])
