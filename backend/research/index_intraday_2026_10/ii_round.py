"""Index intraday research: run a round of variants on SELECTION and VALIDATION only.

    python backend/research/index_intraday_2026_10/ii_round.py ROUND INDEX [INDEX ...]

Periods (fixed before round 1 ran; the holdout is never simulated here):
    selection   2016-01-01 .. 2021-12-31
    validation  2022-01-01 .. 2023-12-31
    holdout     2024-01-01 .. 2026-10-09   ii_final.py, ONCE

The bar (fixed before round 1 ran), per (variant, index):
    selection   >= 150 trades; mean net >= +1.0 bp a trade; daily-return Sharpe >= 0.5;
                profit factor >= 1.10; positive in at least 4 of the 6 selection years;
                still positive at 1.5x costs
    validation  mean net > 0; Sharpe > 0; profit factor > 1.0
Every variant x index is written to data/registry.csv (the trial count behind the deflated
Sharpe) and its daily net returns over selection + validation to data/returns_r<N>_<INDEX>.npz.
"""

from __future__ import annotations

import json
import time

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (_ROOT / "shared", _ROOT / "backend"):          # the repo's own packages first
    if str(_p) in sys.path:
        sys.path.remove(str(_p))
    sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.services.index_intraday import families as F  # noqa: E402
from app.services.index_intraday.costs import costs_for as _costs_for  # noqa: E402


def costs_for(index):
    """The research rounds ran on the starting slippage table (costs.RESEARCH_SLIP)."""
    return _costs_for(index, research=True)
from app.services.index_intraday.data import load, minute_of  # noqa: E402
from app.services.index_intraday.engine import ENTRY_CUTOFF, Costs, simulate_day, summarize  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
REGISTRY = DATA / "registry.csv"
SEL = ("2016-01-01", "2021-12-31")
VAL = ("2022-01-01", "2023-12-31")
LAST_STUDIED = "2023-12-31"
CUTOFF = {"imom": minute_of("14:45")}


def run_variant(ctx: F.Ctx, fam: str, p: dict, exit_name: str, costs: Costs, upto: int) -> list:
    day_specs, day_exit, max_trades = F.FAMILIES[fam](ctx, p)
    xcfg = F.EXITS[exit_name]
    d = ctx.d
    cut = CUTOFF.get(fam, ENTRY_CUTOFF)
    trades = []
    for i in range(upto):
        trades += simulate_day(d.o[i], d.h[i], d.l[i], d.c[i], day_specs(i), xcfg, ctx.day_atr[i], costs,
                               day_exit(i) if day_exit else None, max_trades, i, cut)
    return trades


def period_stats(trades: list, d, span: tuple[str, str], extra: float = 0.0) -> dict:
    mask = d.mask(*span)
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return {"trades": 0}
    lo, hi = idx[0], idx[-1]
    sub = [t for t in trades if lo <= t.day <= hi]
    shifted =[type(t)(t.day - lo, t.side, t.entry_min, t.entry_px, t.exit_min, t.exit_px, t.reason, t.gross_bp, t.net_bp)
               for t in sub]
    return summarize(shifted, len(idx), d.dates[lo:hi + 1], extra)


def passes(row: dict) -> tuple[bool, bool]:
    s1 = (row.get("sel_trades", 0) >= 150 and row.get("sel_mean_net_bp", -1) >= 1.0 and row.get("sel_sharpe", -1) >= 0.5
          and row.get("sel_profit_factor", 0) >= 1.10 and row.get("sel_years_positive", 0) >= 4
          and row.get("sel15_mean_net_bp", -1) > 0)
    s2 = s1 and row.get("val_mean_net_bp", -1) > 0 and row.get("val_sharpe", -1) > 0 and row.get("val_profit_factor", 0) > 1.0
    return s1, s2


def main() -> None:
    rnd = int(sys.argv[1])
    indexes = sys.argv[2:] or ["NIFTY", "BANKNIFTY"]
    variants = getattr(F, f"ROUND{rnd}")
    vix = load("INDIAVIX")
    rows = []
    for index in indexes:
        d = load(index)
        ctx = F.Ctx(d, vix)
        costs = costs_for(index)
        upto = int(np.searchsorted(d.dates, np.datetime64(LAST_STUDIED), side="right"))
        sv = d.mask(SEL[0], VAL[1])
        sv_idx = np.nonzero(sv)[0]
        rets = {}
        t0 = time.time()
        for fam, p, xn in variants:
            key = F.variant_key(fam, p, xn)
            trades = run_variant(ctx, fam, p, xn, costs, upto)
            row = {"key": key, "family": fam, "params": json.dumps(p, sort_keys=True), "exit": xn,
                   "index": index, "round": rnd}
            extra15 = 0.5 * (costs.fee_rt_bp + 2 * costs.slip_bp)
            for tag, span, extra in (("sel", SEL, 0.0), ("val", VAL, 0.0), ("sv", (SEL[0], VAL[1]), 0.0),
                                     ("sel15", SEL, extra15)):
                st = period_stats(trades, d, span, extra)
                for k, v in st.items():
                    if k != "reasons":
                        row[f"{tag}_{k}"] = v
            s1, s2 = passes(row)
            row["stage1"], row["stage2"] = s1, s2
            rows.append(row)
            daily = np.zeros(len(sv_idx))
            lo = sv_idx[0]
            for t in trades:
                if sv_idx[0] <= t.day <= sv_idx[-1]:
                    daily[t.day - lo] += t.net_bp
            rets[key] = daily
        np.savez_compressed(DATA / f"returns_r{rnd}_{index}.npz", keys=np.array(list(rets)),
                            mat=np.column_stack(list(rets.values())), dates=d.dates[sv_idx].astype("int64"))
        print(f"{index}: {len(variants)} variants in {time.time() - t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    if REGISTRY.exists():
        old = pd.read_csv(REGISTRY)
        df_new = df[~(df["key"] + "@" + df["index"]).isin(old["key"] + "@" + old["index"])]
        allr = pd.concat([old, df_new], ignore_index=True)
    else:
        allr = df
    allr.to_csv(REGISTRY, index=False)
    cols = ["key", "index", "sel_trades", "sel_mean_net_bp", "sel_mean_gross_bp", "sel_sharpe", "sel_profit_factor",
            "sel_years_positive", "sel15_mean_net_bp", "val_mean_net_bp", "val_sharpe", "stage1", "stage2"]
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 600)
    pd.set_option("display.max_colwidth", 70)
    print(df.sort_values("sel_sharpe", ascending=False)[cols].round(2).to_string(index=False))
    print(f"\nround {rnd}: {len(df)} variant-index runs | stage 1 {int(df.stage1.sum())} | stage 2 {int(df.stage2.sum())} "
          f"| registry now {len(allr)} trials")


if __name__ == "__main__":
    main()
