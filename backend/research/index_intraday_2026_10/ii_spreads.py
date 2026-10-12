"""Index intraday research: each ETF's effective spread, estimated from its own 1-minute prices.

    python backend/research/index_intraday_2026_10/ii_spreads.py

No bid / ask history exists here, so the effective half-spread is ESTIMATED two ways from the
minute bars and compared with the cost table's assumption (ii_costs.ROUTE):

  Roll (1984)            spread = 2 sqrt(-cov(dp_t, dp_{t-1})) of minute close changes — the
                         bid-ask bounce makes successive changes negatively correlated.
  Corwin-Schultz (2012)  from two consecutive minutes' high / low ranges.

Both are estimated per month (2024 onward — the most recent, liquid regime) and the median is
reported, in bp a side (half the spread). Minutes with no trade (zero volume) are dropped.
Also: the median traded value per minute, to see how much of it a Rs10 lakh order is.
"""

from __future__ import annotations

import math

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (_ROOT / "shared", _ROOT / "backend"):          # the repo's own packages first
    if str(_p) in sys.path:
        sys.path.remove(str(_p))
    sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402

from app.services.index_intraday.costs import ROUTE  # noqa: E402
from app.services.index_intraday.data import load  # noqa: E402


def roll_half_spread_bp(c: np.ndarray, v: np.ndarray) -> float | None:
    x = c[v > 0]
    if len(x) < 200:
        return None
    dp = np.diff(np.log(x))
    cov = np.cov(dp[1:], dp[:-1])[0, 1]
    if cov >= 0:
        return 0.0
    return math.sqrt(-cov) * 1e4                    # half of 2*sqrt(-cov), in bp


def cs_half_spread_bp(h: np.ndarray, l: np.ndarray, v: np.ndarray) -> float | None:
    ok = (v[:-1] > 0) & (v[1:] > 0) & (l[:-1] > 0) & (l[1:] > 0)
    if ok.sum() < 200:
        return None
    b = np.log(h[:-1] / l[:-1]) ** 2 + np.log(h[1:] / l[1:]) ** 2
    g = np.log(np.maximum(h[:-1], h[1:]) / np.minimum(l[:-1], l[1:])) ** 2
    k = 3 - 2 * math.sqrt(2)
    alpha = (np.sqrt(2 * b) - np.sqrt(b)) / k - np.sqrt(g / k)
    s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    s = np.clip(s[ok], 0, None)
    return float(np.mean(s) / 2 * 1e4)


def main() -> None:
    for idx, (etf, px, slip) in ROUTE.items():
        if not etf:
            print(f"{idx:11} no ETF — simulation only")
            continue
        try:
            d = load(etf)
        except FileNotFoundError:
            print(f"{idx:11} {etf}: no data yet")
            continue
        m = d.mask("2024-01-01", "2026-12-31")
        months = d.dates[m].astype("datetime64[M]")
        rolls, css, mv = [], [], []
        for mo in np.unique(months):
            rows = np.nonzero(m)[0][months == mo]
            c, h, l, v = d.c[rows].ravel(), d.h[rows].ravel(), d.l[rows].ravel(), d.v[rows].ravel()
            r = roll_half_spread_bp(c, v)
            s = cs_half_spread_bp(h, l, v)
            if r is not None:
                rolls.append(r)
            if s is not None:
                css.append(s)
            tv = (c * v)[v > 0]
            if len(tv):
                mv.append(float(np.median(tv)))
        zero = float((d.v[m] == 0).mean())
        print(f"{idx:11} {etf:11} half-spread bp: Roll {np.median(rolls) if rolls else float('nan'):.2f}, "
              f"Corwin-Schultz {np.median(css) if css else float('nan'):.2f} | table {slip:.1f} | "
              f"median value a traded minute Rs{np.median(mv) / 1e5 if mv else float('nan'):.1f} lakh | "
              f"minutes with no trade {zero:.0%}")


if __name__ == "__main__":
    main()
