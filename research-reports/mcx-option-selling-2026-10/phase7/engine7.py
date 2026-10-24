"""Phase 7 (AMENDMENT_A7.md): weekly cross-commodity futures portfolios on MCX's own contract prices.

Each market is engine6's held-contract index (energy rolled 3 trading days before expiry, bullion
and base metals 6, ahead of the delivery period). Every week each market gets a signal; its
exposure is signal x 10% / its 60-day vol (equal risk); the portfolio's return is the sum of the
markets' weekly net returns (their own costs and rolls included), as a fraction of the account.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "phase6"))
import engine6 as E6  # noqa: E402

UNIVERSE = ("GOLD", "SILVER", "COPPER", "NICKEL", "ALUMINIUM", "ZINC", "LEAD", "CRUDEOIL", "NATURALGAS")
MARGIN = {"GOLD": 0.092, "SILVER": 0.127, "COPPER": 0.092, "NICKEL": 0.093, "ALUMINIUM": 0.093, "ZINC": 0.091,
          "LEAD": 0.074, "CRUDEOIL": 0.311, "NATURALGAS": 0.167}      # Angel futures, measured 2026-10-09
ROLL = {s: (3 if s in ("CRUDEOIL", "NATURALGAS") else 6) for s in UNIVERSE}
RISK = 0.10


def infer_tick(fut, sym):
    px = np.unique(np.round(fut.loc[(fut.sym == sym) & fut.traded, "close"].to_numpy(), 4))
    st = np.diff(px)
    st = st[st > 1e-9]
    return float(np.round(st.min(), 4)) if len(st) else 0.05


class Universe:
    """All nine markets on one weekly grid (ISO weeks)."""

    def __init__(self, fut):
        self.mk, self.ticks = {}, {}
        for s in UNIVERSE:
            self.ticks[s] = E6.TICK.get(s) or infer_tick(fut, s)
            E6.TICK[s] = self.ticks[s]
            keep = E6.ROLL_DAYS
            E6.ROLL_DAYS = ROLL[s]
            try:
                self.mk[s] = E6.Market(fut, s)
            finally:
                E6.ROLL_DAYS = keep
        keys = sorted({tuple(d.isocalendar()[:2]) for m in self.mk.values() for d in m.D})
        self.keys = keys
        self.kidx = {k: i for i, k in enumerate(keys)}
        n = len(keys)
        # per market: weekly arrays aligned to the common grid (nan where the market has no week)
        self.I = {}
        self.y = {}
        self.vol = {}
        self.pos_of = {}
        ends = {}
        for s, m in self.mk.items():
            idx = np.array([self.kidx[tuple(d.isocalendar()[:2])] for d in m.D])
            self.pos_of[s] = idx
            for arr_name, src in (("I", m.I_D), ("y", m.y_D), ("vol", m.vol_D)):
                a = np.full(n, np.nan)
                a[idx] = src
                getattr(self, arr_name)[s] = a
            for i, d in zip(idx, m.D):
                ends[i] = max(ends.get(i, d), d)
        self.week_end = pd.DatetimeIndex([ends[i] for i in range(n)])

    def mom(self, s, L):
        I = self.I[s]
        out = np.full(len(I), np.nan)
        out[L:] = I[L:] / I[:-L] - 1
        return out

    def carry4(self, s):
        return pd.Series(self.y[s]).rolling(4, min_periods=2).mean().to_numpy()

    def run(self, signals: dict, cost_mult: float = 1.0) -> pd.DataFrame:
        """signals[s][k] on the common grid -> weekly portfolio returns indexed by the week the return accrues."""
        n = len(self.keys)
        net = np.zeros(n)
        gross_exp = np.zeros(n)
        margin = np.zeros(n)
        cost = np.zeros(n)
        for s, m in self.mk.items():
            sig = np.nan_to_num(signals.get(s, np.zeros(n)))
            vol = self.vol[s]
            cap = 1.0 / MARGIN[s]
            e = np.where(np.isfinite(vol) & (vol > 0), np.minimum(cap, RISK / np.where(vol > 0, vol, 1.0)), 0.0) * sig
            pos_m = e[self.pos_of[s]]                          # the market's own weeks
            w = m.returns(pos_m, cost_mult)                    # rows: the market's weeks 1..end
            acc = self.pos_of[s][1:]                           # grid index of the week each return accrues in
            net[acc] += w.net.to_numpy()
            cost[acc] += w.cost.to_numpy()
            gross_exp[acc] += np.abs(w.pos.to_numpy())
            margin[acc] += np.abs(w.pos.to_numpy()) * MARGIN[s]
        return pd.DataFrame({"net": net, "pos": gross_exp, "margin": margin, "cost": cost}, index=self.week_end)


def kelly(sharpe):
    """Best possible log-growth a year at full Kelly, and the weekly rate it compounds to."""
    g = sharpe * sharpe / 2 if np.isfinite(sharpe) and sharpe > 0 else 0.0
    return g, math.exp(g / 52) - 1


def pstats(w: pd.DataFrame, a=None, b=None) -> dict:
    x = w if a is None else w.loc[(w.index >= pd.Timestamp(a)) & (w.index <= pd.Timestamp(b))]
    s = E6.wstats(x)
    if s.get("weeks", 0):
        s["avg_margin"] = float(x.margin.mean())
        s["max_margin"] = float(x.margin.max())
        s["kelly_growth_per_year"], s["kelly_ceiling_per_week"] = kelly(s.get("sharpe", np.nan))
        if "L_star" in s:
            s["margin_needed_avg"] = s["L_star"] * s["avg_margin"]
            s["margin_needed_max"] = s["L_star"] * s["max_margin"]
    return s
