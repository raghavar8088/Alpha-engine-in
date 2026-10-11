"""How many strategies would the page call READY ("Worth real money?") by luck alone?

    python backend/research/gold_2026_10/gd_luck.py   (after gd_analyse.py)

The desk labels each (strategy, symbol) with `commodity_engine._verdict`: READY at >= 30
trades, net > 0, profit factor > 1.2, expectancy > 0, win rate >= 30%, drawdown <= 20% of the
WHOLE book, t >= 1.5. Under the null of no edge, a strategy's trade returns are as likely to
be positive as negative, so flipping each trade's sign at random keeps every strategy's size
and tails and removes any edge. Applying the gate to those zero-edge records, 200 times,
counts the READY labels the page would show by chance — the false-discovery base rate the
"Worth real money?" column stands on. Also reported: how many READY the page WOULD show if
the desk had run this history with its own (5 bp) costs, and with measured costs.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
AN = HERE / "data" / "analysis"
RNG = np.random.default_rng(20261010)
BOOK = {"delta": (10_000.0, 10_000.0 / 6), "mcx": (3_000_000.0, 1_500_000.0)}   # base, notional a position


def gate(pnl: np.ndarray, base: float) -> bool:
    n = len(pnl)
    if n < 30:
        return False
    net = pnl.sum()
    if net <= 0:
        return False
    w, l = pnl[pnl > 0], pnl[pnl < 0]
    gl = -l.sum()
    pf = w.sum() / gl if gl > 0 else float("inf")
    if pf <= 1.2 or (len(w) / n) < 0.30:
        return False
    eq = base + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.r_[base, eq])[1:]
    if ((peak - eq) / peak).max() * 100 > 20:
        return False
    sd = pnl.std(ddof=1)
    t = pnl.mean() / (sd / math.sqrt(n)) if sd > 0 else float("inf")
    return t >= 1.5


def load(ds: str) -> pd.DataFrame | None:
    for ext, fn in ((".parquet", pd.read_parquet), (".pkl", pd.read_pickle)):
        p = AN / f"{ds}_trades{ext}"
        if p.exists():
            return fn(p)
    return None


def main() -> None:
    for ds, venue in (("B_PAXG", "delta"), ("A_XAUT", "delta"), ("A_PAXG", "delta"), ("C_GC", "mcx"), ("D_GOLDM", "mcx")):
        t = load(ds)
        if t is None:
            print(f"{ds}: no trades file")
            continue
        base, notional = BOOK[venue]
        groups = [g for _, g in t.groupby(["tf", "template"])]
        eligible = sum(1 for g in groups if len(g) >= 30)
        real_desk = sum(gate(g.net_desk.to_numpy() / 1e4 * notional, base) for g in groups)
        real_act = sum(gate(g.net_actual.to_numpy() / 1e4 * notional, base) for g in groups)
        counts = []
        for _ in range(200):
            c = 0
            for g in groups:
                x = g.net_actual.to_numpy() / 1e4 * notional
                if len(x) < 30:
                    continue
                c += gate(np.abs(x) * RNG.choice([-1.0, 1.0], size=len(x)), base)
            counts.append(c)
        counts = np.asarray(counts)
        print(f"{ds:8} ({venue}): {len(groups)} strategies, {eligible} with >= 30 trades | READY on this history: "
              f"{real_desk} with the desk's own 5 bp costs, {real_act} with measured costs | READY by pure luck "
              f"(zero-edge sign flips): mean {counts.mean():.1f}, 90th pct {np.percentile(counts, 90):.0f}, "
              f"max {counts.max()} ({counts.mean() / max(eligible, 1):.1%} of eligible)")


if __name__ == "__main__":
    main()
