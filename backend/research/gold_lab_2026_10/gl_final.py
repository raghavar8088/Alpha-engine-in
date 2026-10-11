"""Gold strategy lab, final stage: luck correction, robustness, tiers — then the holdout, ONCE.

    python backend/research/gold_lab_2026_10/gl_final.py stage3     # no holdout data touched
    python backend/research/gold_lab_2026_10/gl_final.py holdout    # opens 2020-2026 once

STAGE 3 (selection + validation only, 2004-11 .. 2019-12)
    * Deflated Sharpe Ratio of every registered variant against ALL registered trials (the
      variance of their Sharpe ratios and their number), and PBO by CSCV across all of them.
    * Robustness: the median of the variant's parameter neighbours (same family, one parameter
      one grid step away) must keep >= 50% of its Sharpe; the same rule on COMEX GC=F over
      2000-08 .. 2019-12 must have alpha > 0.
    * Tier A (proven)  = selection bar (alpha t >= 2 ...) + validation bar + DSR >= 0.95
                         + robustness.
      Tier B (profitable, NOT proven better than holding gold) = selection Sharpe >= 0.30 with
                         both halves > 0; validation Sharpe > 0 and alpha >= 0; alpha t over
                         2004-2019 >= 1.5; robustness. (Both tiers fixed after round 2, before
                         any holdout number existed — see the README.)
HOLDOUT (2020-01 .. 2026-10), once, for the Tier A + B candidates only
    Tier A keeps a strategy with alpha > 0 and Sharpe > 0; Tier B with Sharpe > 0 and alpha >= 0.
    Also reported: the same strategies under the Delta and MCX cost models, at 2x costs,
    and their return correlations (how many INDEPENDENT effects the set holds).
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import gl_families as GF
from gl_engine import (DAYS, benchmark, deflated_sr, market, metrics, pbo_cscv, simulate,
                       simulate_legs)
from gl_round import SEL, VAL, passes, period_mask

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
HOLD = ("2020-01-01", "2026-12-31")
MARKER = DATA / "holdout_opened.json"


def all_returns() -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    mats, keys, dates = [], [], None
    for f in sorted(DATA.glob("returns_r*_GLD.npz")):
        z = np.load(f, allow_pickle=True)
        mats.append(z["mat"])
        keys += list(z["keys"])
        dates = pd.to_datetime(z["dates"])
    mat = np.column_stack(mats)
    df = pd.DataFrame(mat, columns=keys, index=dates)
    return df.loc[:, ~df.columns.duplicated()], dates


def run_rule(fam: str, p: dict, instrument: str, cost_bp: float = 2.0, funding: float | None = None):
    """(daily returns, target, market) of one rule on one instrument's calendar. `funding` (a
    year) replaces the cash rate as the carry on the signed position (the Delta model)."""
    m = market(instrument)
    ctx = GF.Ctx(m)
    out = GF.FAMILIES[fam](p, ctx)
    if funding is not None:
        m.rf = np.full(len(m.close), funding / DAYS)
    if isinstance(out, dict):
        legs = {}
        for name in out:
            lg = m if name == instrument else ctx.leg(name)
            if funding is not None:
                lg.rf = np.full(len(lg.close), funding / DAYS)
            legs[name] = lg
        r = simulate_legs(out, legs, cost_bp)
        tgt = np.asarray(out.get(instrument, next(iter(out.values()))), float)
    else:
        tgt = out
        r = simulate(tgt, m, cost_bp)
    return r, tgt, m


def neighbours(row: pd.Series, reg: pd.DataFrame) -> list[str]:
    """Same family, exactly one parameter different, and that one adjacent in its grid."""
    p = json.loads(row["params"])
    fam = reg[reg["family"] == row["family"]]
    out = []
    grids: dict[str, list] = {}
    for _, r in fam.iterrows():
        for k, v in json.loads(r["params"]).items():
            grids.setdefault(k, [])
            if v not in grids[k]:
                grids[k].append(v)
    for k in grids:
        try:
            grids[k] = sorted(grids[k])
        except TypeError:
            pass
    for _, r in fam.iterrows():
        q = json.loads(r["params"])
        if set(q) != set(p):
            continue
        diff = [k for k in p if q[k] != p[k]]
        if len(diff) != 1:
            continue
        k = diff[0]
        g = grids[k]
        try:
            if abs(g.index(q[k]) - g.index(p[k])) == 1:
                out.append(r["key"])
        except ValueError:
            continue
    return out


def stage3() -> pd.DataFrame:
    reg = pd.read_csv(DATA / "registry.csv")
    reg = reg[reg["instrument"] == "GLD"].drop_duplicates("key").reset_index(drop=True)
    rets, dates = all_returns()
    rets = rets[reg["key"]]
    n_trials = len(reg)
    # Sharpe per day over selection + validation, for every trial
    sr = rets.mean() / rets.std(ddof=1)
    sr_var = float(sr.var(ddof=1))
    pbo, ncomb = pbo_cscv(rets.fillna(0).to_numpy(), S=16)
    print(f"trials: {n_trials} | variance of daily Sharpe across trials {sr_var:.3e} "
          f"(annualised sd {math.sqrt(sr_var * DAYS):.2f}) | PBO across all trials {pbo:.2f} ({ncomb} splits)")
    g = 0.5772156649
    from statistics import NormalDist
    nd = NormalDist()
    sr0 = math.sqrt(sr_var) * ((1 - g) * nd.inv_cdf(1 - 1 / n_trials) + g * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    print(f"the best Sharpe expected from {n_trials} trials of pure luck: {sr0 * math.sqrt(DAYS):.2f} a year")

    reg = passes(reg)
    dsr, nb_med, gc_alpha, gc_sharpe = [], [], [], []
    sv_sharpe = sr * math.sqrt(DAYS)
    for _, row in reg.iterrows():
        x = rets[row["key"]].to_numpy()
        x = x[np.isfinite(x)]
        sk = float(pd.Series(x).skew())
        ku = float(pd.Series(x).kurt()) + 3
        dsr.append(deflated_sr(float(x.mean() / x.std(ddof=1)), len(x), sk, ku, sr_var, n_trials))
        nbs = neighbours(row, reg)
        nb_med.append(float(np.median([sv_sharpe[k] for k in nbs])) if nbs else float("nan"))
    reg["sv_sharpe_daily"] = sv_sharpe[reg["key"]].to_numpy()
    reg["dsr"] = dsr
    reg["nb_median_sharpe"] = nb_med
    # COMEX GC=F robustness (2000-08 .. 2019-12), only where it matters
    cand = reg[(reg["sel_sharpe"] >= 0.30) & (reg["val_sharpe"] > 0)].index
    for i in reg.index:
        if i not in cand:
            gc_alpha.append(float("nan"))
            gc_sharpe.append(float("nan"))
            continue
        row = reg.loc[i]
        r, tgt, m = run_rule(row["family"], json.loads(row["params"]), "GC")
        b = benchmark(m)
        msk = (m.dates <= pd.Timestamp(VAL[1]))
        mt = metrics(r[msk], b[msk], tgt[msk], m.dates[msk])
        gc_alpha.append(mt["alpha_ann"])
        gc_sharpe.append(mt["sharpe"])
    reg["gc_alpha_ann"] = gc_alpha
    reg["gc_sharpe"] = gc_sharpe
    robust = (reg["nb_median_sharpe"].isna() | (reg["nb_median_sharpe"] >= 0.5 * reg["sv_sharpe"])) & (reg["gc_alpha_ann"] > 0)
    tier_a = reg["stage2"] & (reg["dsr"] >= 0.95) & robust
    tier_b = ((reg["sel_sharpe"] >= 0.30) & (reg["sel_sharpe_h1"] > 0) & (reg["sel_sharpe_h2"] > 0)
              & (reg["val_sharpe"] > 0) & (reg["val_alpha_ann"] >= 0) & (reg["sv_alpha_t"] >= 1.5) & robust & ~tier_a)
    reg["tier"] = np.where(tier_a, "A", np.where(tier_b, "B", ""))
    reg["robust"] = robust
    reg.to_csv(DATA / "stage3.csv", index=False)
    cols = ["key", "sel_sharpe", "sel_alpha_t", "val_sharpe", "val_alpha_t", "sv_sharpe", "sv_alpha_t", "sv_beta",
            "dsr", "nb_median_sharpe", "gc_sharpe", "gc_alpha_ann", "stage2", "robust", "tier"]
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 55)
    show = reg[(reg["val_sharpe"] > 0) & (reg["sel_sharpe"] >= 0.3)].sort_values("sv_alpha_t", ascending=False)
    print(show[cols].round(3).to_string(index=False))
    print(f"\nTier A candidates: {int(tier_a.sum())} | Tier B candidates: {int(tier_b.sum())}")
    return reg


def holdout(force: bool = False) -> None:
    if MARKER.exists() and not force:
        print(f"The holdout was already opened ({json.loads(MARKER.read_text())['opened_at']}); it is not re-run.")
        return
    reg = pd.read_csv(DATA / "stage3.csv")
    final = reg[reg["tier"].isin(["A", "B"])].copy()
    MARKER.write_text(json.dumps({"opened_at": datetime.now(timezone.utc).isoformat(),
                                  "candidates": final["key"].tolist()}, indent=1))
    rows, series = [], {}
    for _, row in final.iterrows():
        p = json.loads(row["params"])
        out = {"key": row["key"], "tier_pre": row["tier"]}
        for tag, kw in (("base", {}), ("x2cost", {"cost_bp": 4.0}), ("delta", {"cost_bp": 1.3, "funding": 0.1095}),
                        ("mcx", {"cost_bp": 1.7})):
            r, tgt, m = run_rule(row["family"], p, "GLD", **kw)
            b = benchmark(m, kw.get("cost_bp", 2.0)) if "funding" not in kw else None
            if b is None:                         # the Delta benchmark pays the same funding
                mb = market("GLD")
                mb.rf = np.full(len(mb.close), 0.1095 / DAYS)
                b = benchmark(mb, 1.3)
            msk = period_mask(m.dates, HOLD)
            mt = metrics(r[msk], b[msk], tgt[msk], m.dates[msk])
            for k in ("sharpe", "ann_ret", "alpha_ann", "alpha_t", "beta", "maxdd", "entries", "cagr"):
                out[f"{tag}_{k}"] = mt.get(k)
            if tag == "base":
                series[row["key"]] = pd.Series(r[msk], index=m.dates[msk])
                full = (m.dates >= pd.Timestamp(SEL[0]))
                ft = metrics(r[full], b[full], tgt[full], m.dates[full])
                out["full_sharpe"], out["full_alpha_t"], out["full_cagr"], out["full_maxdd"] = (
                    ft["sharpe"], ft["alpha_t"], ft["cagr"], ft["maxdd"])
        keep_a = out["tier_pre"] == "A" and out["base_alpha_ann"] > 0 and out["base_sharpe"] > 0
        keep_b = out["tier_pre"] == "B" and out["base_sharpe"] > 0 and out["base_alpha_ann"] >= 0
        out["final"] = "A" if keep_a else ("B" if keep_b else "dropped")
        rows.append(out)
    res = pd.DataFrame(rows)
    res.to_csv(DATA / "holdout.csv", index=False)
    mb = market("GLD")
    bb = benchmark(mb)
    msk = period_mask(mb.dates, HOLD)
    bm = metrics(bb[msk], bb[msk], np.ones(msk.sum()), mb.dates[msk])
    print(f"holdout 2020-01 .. 2026-10 — holding gold (excess): Sharpe {bm['sharpe']:.2f}, CAGR {bm['cagr']:.1%}, max DD {bm['maxdd']:.1%}")
    pd.set_option("display.width", 250)
    cols = ["key", "tier_pre", "base_sharpe", "base_alpha_ann", "base_alpha_t", "base_beta", "base_maxdd", "base_entries",
            "x2cost_sharpe", "delta_sharpe", "delta_alpha_ann", "mcx_sharpe", "full_sharpe", "full_alpha_t", "final"]
    print(res[cols].round(3).to_string(index=False))
    kept = res[res["final"] != "dropped"]["key"].tolist()
    if len(kept) > 1:
        c = pd.concat({k: series[k] for k in kept}, axis=1).corr()
        c.to_csv(DATA / "holdout_corr.csv")
        print("\nreturn correlations (holdout) among the kept strategies:")
        print(c.round(2).to_string())
    print(f"\nkept: Tier A {int((res['final'] == 'A').sum())} | Tier B {int((res['final'] == 'B').sum())} | dropped {int((res['final'] == 'dropped').sum())}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stage3"
    if cmd == "stage3":
        stage3()
    elif cmd == "holdout":
        holdout(force="--force" in sys.argv)
