"""Do the daily patterns beat simply holding gold? The Commodity Lab's criterion 4, gold only.

    python backend/research/gold_2026_10/gd_benchmark.py   (after gd_analyse.py E_GCD)

The Commodity Lab tested the desk's daily templates only as five-commodity baskets. Here each
of the 45 daily templates is run on gold alone (COMEX GC=F, 2000-2026, gd_replay E_GCD), turned
into a DAILY return series (marked to each day's close while in a trade, flat otherwise, the
measured MCX round trip charged on the exit day) and held against ALWAYS-LONG gold:

  held-out Sharpe   2013-07 onward, the strategy vs holding gold over the same days
  alpha             full period, r_strategy = a + b * r_gold, a annualised with its t

The Lab's rule: a candidate must beat always-long on BOTH — higher held-out Sharpe and alpha
t >= 2. A long-only pattern in a 15x bull market earns from being long; this asks whether it
earned anything for choosing WHEN.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BARS = HERE / "data" / "replay" / "bars"
AN = HERE / "data" / "analysis"
COST_BP = 3.31
SPLIT = pd.Timestamp("2013-07-01", tz="UTC")


def load_trades() -> pd.DataFrame:
    for ext, fn in ((".parquet", pd.read_parquet), (".pkl", pd.read_pickle)):
        p = AN / f"E_GCD_trades{ext}"
        if p.exists():
            return fn(p)
    raise SystemExit("run gd_analyse.py E_GCD first")


def daily_series(tr: pd.DataFrame, ts: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Daily returns of one strategy (one position at a time), marked at each close."""
    r = np.zeros(len(c))
    for x in tr.itertuples(index=False):
        k0 = int(np.searchsorted(ts, x.entry_ts, side="left"))
        ke = int(np.searchsorted(ts, x.exit_ts - 1, side="right")) - 1     # the bar the exit fell in
        ke = max(ke, k0)
        side = float(x.side)
        if ke == k0:
            r[k0] += side * (x.exit / x.entry - 1)
        else:
            r[k0] += side * (c[k0] / x.entry - 1)
            if ke - 1 > k0:
                r[k0 + 1:ke] += side * (c[k0 + 1:ke] / c[k0:ke - 1] - 1)
            r[ke] += side * (x.exit / c[ke - 1] - 1)
        r[ke] -= COST_BP / 1e4
    return r


def sharpe(x: np.ndarray) -> float:
    return float(x.mean() / x.std() * math.sqrt(252)) if x.std() > 0 else float("nan")


def main() -> None:
    z = np.load(BARS / "E_GCD__1d.npz")
    ts, c = z["ts"], z["c"]
    dates = pd.to_datetime(ts, unit="s", utc=True)
    rb = np.r_[0.0, c[1:] / c[:-1] - 1]
    held = dates >= SPLIT
    tr = load_trades()
    rows = []
    X = np.c_[np.ones(len(rb)), rb]
    for tmpl, g in tr.groupby("template"):
        if len(g) < 20:
            continue
        rs = daily_series(g, ts, c)
        beta, *_ = np.linalg.lstsq(X, rs, rcond=None)
        resid = rs - X @ beta
        s2 = resid.var(ddof=2)
        cov = s2 * np.linalg.inv(X.T @ X)
        a_t = beta[0] / math.sqrt(cov[0, 0])
        rows.append({"template": tmpl, "trades": len(g), "long_share": (g.side > 0).mean(),
                     "in_market": (rs != 0).mean(), "sr_heldout": sharpe(rs[held]), "sr_gold_heldout": sharpe(rb[held]),
                     "sr_full": sharpe(rs), "alpha_ann_pct": beta[0] * 252 * 100, "beta": beta[1], "alpha_t": a_t,
                     "passes": bool(sharpe(rs[held]) > sharpe(rb[held]) and a_t >= 2)})
    df = pd.DataFrame(rows).sort_values("alpha_t", ascending=False)
    print(f"always-long gold: full Sharpe {sharpe(rb):.2f}, held-out (2013-07..) Sharpe {sharpe(rb[held]):.2f}")
    print(f"{len(df)} daily templates with >= 20 trades; beat always-long on both tests: {int(df.passes.sum())}")
    print(df.head(12).round(3).to_string(index=False))
    df.to_csv(AN / "E_GCD_vs_always_long.csv", index=False)


if __name__ == "__main__":
    main()
