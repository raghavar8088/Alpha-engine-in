"""Phase 6 (AMENDMENT_A6.md): crude-oil and natural-gas futures on MCX's own contract prices.

The held contract is the nearest expiry, rolled at the close 3 trading days before it expires.
`I` compounds the day-to-day change of the contract actually held, so it carries the cost of
carry and never jumps at a roll. Positions are exposures (multiples of the account), decided at
each week's last close and held to the next; costs follow Angel's MCX futures card.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

MARGIN = {"CRUDEOIL": 0.311, "NATURALGAS": 0.167}          # Angel, futures, measured 2026-10-09
TICK = {"CRUDEOIL": 1.0, "NATURALGAS": 0.10}
ROLL_DAYS = 3
EXCH, CTT_SELL, STAMP_BUY, SEBI, GST = 0.000021, 0.0001, 0.00002, 0.000001, 0.18
SLIP_BP = 0.0002
BROKERAGE = 20.0
ACCOUNT = 1_000_000.0
ORDER = BROKERAGE * (1 + GST) / ACCOUNT


def build_daily(fut: pd.DataFrame, sym: str) -> pd.DataFrame:
    """One row per trading day: held expiry (from this close), the held contract's close P, the index
    I, the day's index return r, a roll flag, the carry y (front vs next, both traded) and 60-day vol."""
    f = fut[fut.sym == sym]
    days = sorted(f.date.unique())
    di = {d: i for i, d in enumerate(days)}
    px = {(r.expiry, r.date): (float(r.close), bool(r.traded)) for r in f.itertuples()}
    exps = sorted(f.expiry.unique())
    darr = np.array(days, dtype="datetime64[ns]")
    roll_idx = {}
    for e in exps:
        k = int(np.searchsorted(darr, np.datetime64(e), side="right")) - 1
        if k >= 0:
            roll_idx[e] = k - ROLL_DAYS
    held, k = [], 0
    for i in range(len(days)):
        while k < len(exps) and roll_idx.get(exps[k], -1) <= i:
            k += 1
        held.append(exps[k] if k < len(exps) else None)
    nxt = {e: (exps[j + 1] if j + 1 < len(exps) else None) for j, e in enumerate(exps)}
    rows, I = [], 1.0
    for i, d in enumerate(days):
        h_prev = held[i - 1] if i else None
        r = 0.0
        if h_prev is not None and (h_prev, d) in px and (h_prev, days[i - 1]) in px:
            p0, p1 = px[(h_prev, days[i - 1])][0], px[(h_prev, d)][0]
            if p0 > 0 and p1 > 0:
                r = p1 / p0 - 1
        I *= 1 + r
        h, y, P = held[i], np.nan, np.nan
        if h is not None and (h, d) in px:
            P, tr1 = px[(h, d)]
            e2 = nxt.get(h)
            if e2 is not None and (e2, d) in px:
                P2, tr2 = px[(e2, d)]
                if tr1 and tr2 and P > 0 and P2 > 0:
                    y = math.log(P / P2) * 365.0 / max((e2 - h).days, 1)
        rows.append({"date": d, "held": h, "P": P, "r": r, "I": I, "roll": bool(i and held[i] != held[i - 1]), "y": y})
    out = pd.DataFrame(rows).set_index("date")
    out["vol60"] = out.r.rolling(60, min_periods=40).std() * math.sqrt(252)
    return out


def cost_rate(sym, price, side):
    """Fraction of traded notional for one side: slippage + MCX + SEBI (+GST) + CTT (sell) or stamp (buy)."""
    slip = max(TICK[sym] / price, SLIP_BP) if price and np.isfinite(price) and price > 0 else SLIP_BP
    return slip + (EXCH + SEBI) * (1 + GST) + (CTT_SELL if side == "sell" else STAMP_BUY)


class Market:
    """Daily series plus everything a weekly decision needs, precomputed once."""

    def __init__(self, fut, sym):
        self.sym = sym
        self.daily = d = build_daily(fut, sym)
        iso = d.index.isocalendar()
        D = d.index.to_series().groupby([iso.year.to_numpy(), iso.week.to_numpy()]).max().sort_values()
        self.D = pd.DatetimeIndex(D.values)
        self.I_D = d.I.loc[self.D].to_numpy()
        self.P_D = d.P.loc[self.D].to_numpy()
        self.y_D = d.y.loc[self.D].to_numpy()
        self.vol_D = d.vol60.loc[self.D].to_numpy()
        n = len(self.D)
        self.roll_unit = np.zeros(n)          # cost fraction per unit exposure for rolls in the week AFTER D[w]
        self.roll_count = np.zeros(n, dtype=int)
        rolls = d[d.roll]
        pos = np.searchsorted(self.D.values, rolls.index.values, side="left")   # roll day in (D[w-1], D[w]] -> w
        for p, P in zip(pos, rolls.P.to_numpy()):
            w = p - 1                          # it falls in the week that starts at D[p-1]
            if 0 <= w < n:
                self.roll_unit[w] += cost_rate(sym, P, "buy") + cost_rate(sym, P, "sell")
                self.roll_count[w] += 1
        self.buy_rate = np.array([cost_rate(sym, P, "buy") for P in self.P_D])
        self.sell_rate = np.array([cost_rate(sym, P, "sell") for P in self.P_D])

    def returns(self, pos: np.ndarray, cost_mult: float = 1.0) -> pd.DataFrame:
        """Weekly net returns on the account for exposures pos[w] decided at D[w], held to D[w+1]."""
        pos = np.nan_to_num(np.asarray(pos, dtype=float))
        p, prev = pos[:-1], np.concatenate([[0.0], pos[:-2]])
        gross = p * (self.I_D[1:] / self.I_D[:-1] - 1)
        dp = p - prev
        trade = np.where(dp > 0, dp * self.buy_rate[:-1], -dp * self.sell_rate[:-1]) + (dp != 0) * ORDER
        roll = np.abs(p) * self.roll_unit[:-1] + (p != 0) * self.roll_count[:-1] * 2 * ORDER
        cost = (trade + roll) * cost_mult
        return pd.DataFrame({"pos": p, "gross": gross, "cost": cost, "net": gross - cost}, index=self.D[1:])


def wstats(w: pd.DataFrame, a=None, b=None) -> dict:
    x = w if a is None else w.loc[(w.index >= pd.Timestamp(a)) & (w.index <= pd.Timestamp(b))]
    r = x.net.to_numpy()
    n = len(r)
    if n == 0:
        return {"weeks": 0, "net_pct": 0.0, "mean": 0.0}
    sd = r.std(ddof=1) if n > 1 else np.nan
    cum = np.concatenate([[0.0], np.cumsum(r)])
    mean = float(r.mean())
    out = {"weeks": n, "weeks_in_market": int((x.pos != 0).sum()), "net_pct": float(r.sum() * 100), "mean": mean,
           "sharpe": float(mean / sd * math.sqrt(52)) if sd and sd > 0 else np.nan,
           "t": float(mean / (sd / math.sqrt(n))) if sd and sd > 0 else np.nan,
           "pf": float(r[r > 0].sum() / -r[r < 0].sum()) if (r < 0).any() else float("inf"),
           "pos_weeks": float((r > 0).mean()), "ge2_weeks": float((r >= 0.02).mean()),
           "worst_week": float(r.min()), "best_week": float(r.max()),
           "maxdd": float((np.maximum.accumulate(cum) - cum).max()),
           "avg_gross_exposure": float(np.abs(x.pos).mean()), "max_gross_exposure": float(np.abs(x.pos).max()),
           "cost_pct": float(x.cost.sum() * 100)}
    if mean > 0:
        L = 0.02 / mean
        out.update({"L_star": L, "exposure_needed_avg": L * out["avg_gross_exposure"],
                    "exposure_needed_max": L * out["max_gross_exposure"], "maxdd_at_L": L * out["maxdd"],
                    "worst_week_at_L": L * out["worst_week"], "ge2_weeks_at_L": float((r >= mean).mean())})
    return out
