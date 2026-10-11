"""Gold strategy lab: run one round of variants through SELECTION and VALIDATION only.

    python backend/research/gold_lab_2026_10/gl_round.py ROUND [instrument]

Periods (fixed before round 1 ran; the holdout is never computed here):
    selection   2004-11-18 .. 2014-12-31   candidates are chosen on this alone
    validation  2015-01-01 .. 2019-12-31   a candidate must hold up here
    holdout     2020-01-01 .. 2026-10-09   gl_final.py, ONCE, for the final set

The bar (fixed before round 1 ran):
    selection   alpha t vs holding gold >= 2.0 (weekly, Newey-West); Sharpe >= 0.30 net of costs;
                Sharpe > 0 in both halves; >= 10 entries unless the rule is always in the market
    validation  alpha > 0 and Sharpe > 0
Every variant is written to data/registry.csv (the trial count behind the deflated Sharpe) and
its daily returns over selection + validation to data/returns_<round>.npz.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import gl_families as GF
from gl_engine import benchmark, market, metrics, simulate, simulate_legs

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
REGISTRY = DATA / "registry.csv"

SEL = ("2004-11-18", "2014-12-31")
VAL = ("2015-01-01", "2019-12-31")
ALWAYS_IN = {"vol_managed"}


def period_mask(dates: pd.DatetimeIndex, span: tuple[str, str]) -> np.ndarray:
    return (dates >= pd.Timestamp(span[0])) & (dates <= pd.Timestamp(span[1]))


def evaluate(variants: list[tuple[str, dict]], instrument: str = "GLD", fns: dict | None = None) -> pd.DataFrame:
    fns = fns or GF.FAMILIES
    m = market(instrument)
    ctx = GF.Ctx(m)
    bench = benchmark(m)
    sel, val = period_mask(m.dates, SEL), period_mask(m.dates, VAL)
    rows, rets = [], {}
    for fam, p in variants:
        out = fns[fam](p, ctx)
        if isinstance(out, dict):                    # a multi-leg rule (e.g. gold vs silver)
            legs = {name: (m if name == instrument else ctx.leg(name)) for name in out}
            r = simulate_legs(out, legs)
            tgt = np.asarray(out.get(instrument, next(iter(out.values()))), float)
        else:
            tgt = out
            r = simulate(tgt, m)
        row = {"key": GF.variant_key(fam, p), "family": fam, "params": json.dumps(p, sort_keys=True),
               "instrument": instrument}
        for tag, mask in (("sel", sel), ("val", val), ("sv", sel | val)):
            mt = metrics(r[mask], bench[mask], tgt[mask], m.dates[mask])
            for k, v in mt.items():
                row[f"{tag}_{k}"] = v
        rows.append(row)
        rets[row["key"]] = r[sel | val]
    df = pd.DataFrame(rows)
    df.attrs["dates"] = m.dates[sel | val]
    df.attrs["rets"] = rets
    return df


def passes(df: pd.DataFrame) -> pd.DataFrame:
    always = df["family"].isin(ALWAYS_IN)
    s1 = ((df["sel_alpha_t"] >= 2.0) & (df["sel_sharpe"] >= 0.30) & (df["sel_sharpe_h1"] > 0)
          & (df["sel_sharpe_h2"] > 0) & ((df["sel_entries"] >= 10) | always))
    s2 = s1 & (df["val_alpha_ann"] > 0) & (df["val_sharpe"] > 0)
    out = df.assign(stage1=s1, stage2=s2)
    return out


def register(df: pd.DataFrame, rnd: int) -> int:
    keep = [c for c in df.columns if not c.startswith("_")]
    new = df[keep].assign(round=rnd)
    if REGISTRY.exists():
        old = pd.read_csv(REGISTRY)
        new = new[~new["key"].isin(old["key"]) | ~new["instrument"].isin(old["instrument"])]
        allr = pd.concat([old, new], ignore_index=True)
    else:
        allr = new
    allr.to_csv(REGISTRY, index=False)
    return len(allr)


def show(df: pd.DataFrame, bench_row: dict) -> None:
    cols = ["key", "sel_sharpe", "sel_alpha_ann", "sel_alpha_t", "sel_beta", "sel_maxdd", "sel_entries",
            "sel_sharpe_h1", "sel_sharpe_h2", "val_sharpe", "val_alpha_ann", "val_alpha_t", "stage1", "stage2"]
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    pd.set_option("display.max_colwidth", 60)
    print(f"benchmark (always long, excess): selection Sharpe {bench_row['sel']:.2f}, validation {bench_row['val']:.2f}")
    print(df.sort_values("sel_alpha_t", ascending=False)[cols].round(3).to_string(index=False))


def main() -> None:
    rnd = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    instrument = sys.argv[2] if len(sys.argv) > 2 else "GLD"
    variants = getattr(GF, f"ROUND{rnd}")
    df = passes(evaluate(variants, instrument))
    m = market(instrument)
    b = benchmark(m)
    br = {}
    for tag, span in (("sel", SEL), ("val", VAL)):
        msk = period_mask(m.dates, span)
        br[tag] = metrics(b[msk], b[msk], np.ones(msk.sum()), m.dates[msk])["sharpe"]
    show(df, br)
    total = register(df, rnd)
    np.savez_compressed(DATA / f"returns_r{rnd}_{instrument}.npz",
                        keys=np.array(list(df.attrs["rets"])), mat=np.column_stack(list(df.attrs["rets"].values())),
                        dates=df.attrs["dates"].astype("int64"))
    print(f"\nround {rnd}: {len(df)} variants | stage 1 {int(df.stage1.sum())} | stage 2 {int(df.stage2.sum())} "
          f"| registry now {total} trials")


if __name__ == "__main__":
    main()
