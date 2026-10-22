"""Phase 2 (AMENDMENT_A2.md + A2_1): discovery selection -> frozen candidates -> one holdout test,
plus a per-family walk-forward.

    python run_phase2.py <work_dir> discover     # writes p2_candidates.json (then freeze it)
    python run_phase2.py <work_dir> holdout      # runs ONCE on the frozen candidates
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

import engine2 as E2
import engine as E
from search import bootstrap_p5, metrics

FAMILIES = {
    "C-A": ("CRUDEOILM", [("dcall", d, e, None, sl) for d in (0.05, 0.10, 0.15, 0.20) for e in (12, 10, 7, 5) for sl in (None, 2.0)]),
    "C-B": ("CRUDEOILM", [("dput", d, e, None, sl) for d in (0.05, 0.10, 0.15, 0.20) for e in (7, 5, 3) for sl in (None, 2.0)]),
    "C-C": ("CRUDEOILM", [("dstrangle", d, e, None, sl) for d in (0.10, 0.15, 0.20) for e in (10, 7, 5) for sl in (None, 1.0, 2.0)]),
    "C-D": ("CRUDEOILM", [("dstrangle", d, e, ("ge", th), sl) for th in (50, 67) for d in (0.15, 0.20, 0.25) for e in (15, 10) for sl in (None, 2.0)]),
    "C-E": ("CRUDEOILM", [("dh", None, e, None, None) for e in (20, 10)]),
    "N-A": ("NATGASMINI", [("dstrangle", d, e, None, sl) for d in (0.03, 0.05, 0.08) for e in (20, 15, 10) for sl in (None, 1.0, 2.0)]),
    "N-B": ("NATGASMINI", [("dstrangle", d, e, ("le", 50), sl) for d in (0.10, 0.15, 0.20) for e in (15, 10) for sl in (None, 1.0, 2.0)]),
}
assert sum(len(v) for _, v in FAMILIES.values()) == 154
DISC = {"CRUDEOILM": ("2020-01-01", "2024-05-31"), "NATGASMINI": ("2022-03-01", "2024-04-30")}
HOLD = ("2024-06-01", "2026-10-31")
WF_YEARS = {"CRUDEOILM": [2022, 2023, 2024, 2025, 2026], "NATGASMINI": [2024, 2025, 2026]}
DH_LOTS = 10


def vkey(fam, v):
    s, d, e, f, sl = v
    return f"{fam}|{s}|d={d}|e={e}|f={f[0] + str(f[1]) if f else 'none'}|sl={sl}"


def run_variant(cycles, inst, v, ivpct, slip):
    """(trades, n_eligible_cycles) - the coverage denominator per A2.1."""
    s, d, e, f, sl = v
    mult, fam, tick = E.MULT[inst], E.FAMILY[inst], E.TICK[inst]
    trades, n_den = [], 0
    for c in cycles:
        j0 = E.entry_index(c, e)
        if j0 is None:
            continue
        if f is not None:
            p = ivpct.get(c.dates[j0], np.nan)
            if not np.isfinite(p) or not ((p >= f[1]) if f[0] == "ge" else (p <= f[1])):
                continue
        n_den += 1
        if s == "dh":
            t = E2.run_dh_straddle(c, j0, DH_LOTS, mult, fam, tick, slip)
        else:
            legs = E2.legs_delta(c, s, d, j0)
            t = E.run_trade(c, legs, j0, mult, fam, tick, slip, None, sl, 0) if legs else None
        if t is not None:
            trades.append(t)
    return trades, n_den


def eligible(m, m2):
    return (m.get("n", 0) >= 3 and m["coverage"] >= 0.70 and m["net"] > 0 and m["pf"] >= 1.3 and m["t"] >= 1.5
            and m2.get("net", -1) > 0 and m["worst_roc"] >= -0.30)


def load(work):
    cyc = {}
    for inst in ("CRUDEOILM", "NATGASMINI"):
        full = pd.read_pickle(os.path.join(work, f"cycles_a1_{inst}_full.pkl"))          # parent prices 2020/22-2026
        cyc[(inst, "full")] = full
        cyc[(inst, "mini")] = pd.read_pickle(os.path.join(work, f"cycles_a1_{inst}_mini.pkl"))
        cyc[(inst, "ivpct")] = E2.iv_percentile(E2.front_iv_series(full)).to_dict()
    return cyc


def select_family(cycles, inst, variants, fam, ivpct):
    best, rows = None, []
    for v in variants:
        tr, den = run_variant(cycles, inst, v, ivpct, 0.01)
        tr2, _ = run_variant(cycles, inst, v, ivpct, 0.02)
        m, m2 = metrics(tr, den), metrics(tr2, den)
        ok = eligible(m, m2)
        p5 = bootstrap_p5(np.array([t["roc"] for t in tr])) if ok else np.nan
        rows.append({"family": fam, "key": vkey(fam, v), **{k: m.get(k) for k in ("n", "coverage", "net", "pf", "t", "worst_roc", "mean_roc")},
                     "net_2x": m2.get("net"), "eligible": ok, "p5": p5})
        if ok and (best is None or p5 > best[0]):
            best = (p5, v)
    return best, rows


def discover(work):
    cyc = load(work)
    cands, allrows = [], []
    for fam, (inst, variants) in FAMILIES.items():
        a, b = DISC[inst]
        cycles = [c for c in cyc[(inst, "full")] if pd.Timestamp(a) <= c.expiry <= pd.Timestamp(b)]
        best, rows = select_family(cycles, inst, variants, fam, cyc[(inst, "ivpct")])
        allrows += rows
        n_el = sum(r["eligible"] for r in rows)
        if best:
            r = next(x for x in rows if x["key"] == vkey(fam, best[1]))
            cands.append({"family": fam, "inst": inst, "variant": list(best[1]), "key": r["key"], "disc": r})
            print(f"{fam} ({inst}, {len(cycles)} discovery cycles): {n_el}/{len(rows)} eligible -> best {r['key']} | "
                  f"n={r['n']} net=Rs{r['net']:,.0f} pf={r['pf']:.2f} t={r['t']:.2f} worst={r['worst_roc']:.1%} p5={r['p5']:.2%}")
        else:
            best_any = max(rows, key=lambda x: x["net"] if x["net"] is not None else -1e9)
            print(f"{fam} ({inst}, {len(cycles)} discovery cycles): 0/{len(rows)} eligible -> NO CANDIDATE "
                  f"(best net Rs{best_any['net'] or 0:,.0f}, pf {best_any['pf'] or 0:.2f}, t {best_any['t'] or 0:.2f})")
    pd.DataFrame(allrows).to_csv(os.path.join(work, "p2_discovery.csv"), index=False)
    json.dump(cands, open(os.path.join(work, "p2_candidates.json"), "w"), indent=1, default=float)
    print(f"\n{len(cands)} candidates written")


def stats(tr):
    if not tr:
        return {"n": 0, "net": 0.0}
    p = np.array([t["pnl"] for t in tr])
    r = np.array([t["roc"] for t in tr])
    eq = np.concatenate([[0], np.cumsum(p)])
    return {"n": len(p), "net": round(float(p.sum())), "win": round(float((p > 0).mean()), 3),
            "pf": round(float(p[p > 0].sum() / -p[p < 0].sum()), 2) if (p < 0).any() else float("inf"),
            "worst": round(float(p.min())), "worst_roc": round(float(r.min()), 3),
            "maxdd": round(float((np.maximum.accumulate(eq) - eq).max())), "mean_roc": round(float(r.mean()), 4),
            "avg_capital": round(float(np.mean([t["capital"] for t in tr])))}


def holdout(work):
    cyc = load(work)
    cands = json.load(open(os.path.join(work, "p2_candidates.json")))
    out = []
    for cd in cands:
        inst, v = cd["inst"], tuple(cd["variant"][:3]) + (tuple(cd["variant"][3]) if cd["variant"][3] else None, cd["variant"][4])
        mini = cyc[(inst, "mini")]
        parent = [c for c in cyc[(inst, "full")] if c.expiry >= pd.Timestamp(HOLD[0])]
        res = {}
        for s in (0.01, 0.02, 0.03):
            tr, den = run_variant(mini, inst, v, cyc[(inst, "ivpct")], s)
            res[s] = (stats(tr), tr)
        px, _ = run_variant(parent, inst, v, cyc[(inst, "ivpct")], 0.01)
        h, h2 = res[0.01][0], res[0.02][0]
        passed = h["n"] > 0 and h["net"] > 0 and h["pf"] >= 1.15 and h2["net"] > 0 and h["worst_roc"] >= -0.45
        # walk-forward for this family (parent prices, full history)
        fam_inst, fam_vars = FAMILIES[cd["family"]]
        full = cyc[(inst, "full")]
        years = np.array([c.expiry.year for c in full])
        wf = []
        for Y in WF_YEARS[inst]:
            train = [c for c, y in zip(full, years) if y < Y]
            if len(train) < 20:
                continue
            best, _ = select_family(train, inst, fam_vars, cd["family"], cyc[(inst, "ivpct")])
            if best is None:
                wf.append({"year": Y, "pick": None, "net": 0.0, "n": 0})
                continue
            test = [c for c, y in zip(full, years) if y == Y]
            tr, _ = run_variant(test, inst, best[1], cyc[(inst, "ivpct")], 0.01)
            wf.append({"year": Y, "pick": vkey(cd["family"], best[1]), "net": float(sum(t["pnl"] for t in tr)), "n": len(tr),
                       "pnls": [t["pnl"] for t in tr]})
        wf_p = np.array([p for y in wf for p in y.get("pnls", [])])
        wf_stats = {"n": len(wf_p), "net": round(float(wf_p.sum())) if len(wf_p) else 0,
                    "pf": round(float(wf_p[wf_p > 0].sum() / -wf_p[wf_p < 0].sum()), 2) if (wf_p < 0).any() else (float("inf") if len(wf_p) else 0)}
        row = {"family": cd["family"], "key": cd["key"], "disc": cd["disc"], "holdout_1x": h, "holdout_2x_net": h2["net"],
               "holdout_3x_net": res[0.03][0]["net"], "parent_crosscheck": stats(px), "passed": bool(passed),
               "walkforward": [{k: y[k] for k in ("year", "pick", "net", "n")} for y in wf], "walkforward_total": wf_stats}
        out.append(row)
        pd.DataFrame(res[0.01][1]).to_csv(os.path.join(work, f"p2_holdout_trades_{cd['family']}.csv"), index=False)
        print(f"\n{cd['family']} {cd['key']}  -> {'PASS' if passed else 'fail'}")
        print(f"   holdout (mini prices): {h}")
        print(f"   slippage 2%/3%: Rs{h2['net']:,} / Rs{res[0.03][0]['net']:,} | parent cross-check: {stats(px)}")
        print(f"   walk-forward: {[(y['year'], round(y['net'])) for y in wf]} -> total {wf_stats}")
    json.dump(out, open(os.path.join(work, "p2_holdout.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    {"discover": discover, "holdout": holdout}[sys.argv[2]](sys.argv[1])
