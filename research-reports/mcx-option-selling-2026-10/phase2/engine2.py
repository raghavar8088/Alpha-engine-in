"""Phase 2 additions to engine.py (AMENDMENT_A2.md): delta strikes, causal IV percentile,
delta-hedged straddle. Same fill / fee / margin conventions as engine.run_trade."""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "shared"))
import b76  # noqa: E402
import engine as E  # noqa: E402
from tradingai_shared.mcx_option_fees import mcx_option_leg  # noqa: E402


# ---------------------------------------------------------------------------- delta strikes
def strike_deltas(c, cp: str, j: int):
    """(strikes, |delta|) for every strike of type cp that TRADED on day j."""
    ks, tr, cl = c.strikes[cp], c.traded[cp][:, j], c.close[cp][:, j]
    F = c.F[j]
    if not np.isfinite(F):
        return None
    sel = tr & np.isfinite(cl) & (cl > 0)
    if not sel.any():
        return None
    k, px = ks[sel], cl[sel]
    T = max((c.expiry - c.dates[j]).days, 0.5) / 365.0
    n = len(k)
    is_call = np.full(n, cp == "CE")
    iv = b76.implied_vol(px, np.full(n, F), k, np.full(n, T), is_call)
    d = b76.delta(np.full(n, F), k, np.full(n, T), np.nan_to_num(iv, nan=0.5), is_call)
    return k, np.where(np.isfinite(iv), np.abs(d), np.nan)


def pick_delta(c, cp: str, j: int, target: float):
    r = strike_deltas(c, cp, j)
    if r is None:
        return None
    k, d = r
    ok = np.isfinite(d) & (d >= 0.5 * target) & (d <= 1.5 * target)
    if cp == "CE":
        ok &= k > c.F[j]
    else:
        ok &= k < c.F[j]
    if not ok.any():
        return None
    i = int(np.argmin(np.where(ok, np.abs(d - target), np.inf)))
    return float(k[i])


def legs_delta(c, struct: str, target: float, j: int):
    out = []
    if struct in ("dcall", "dstrangle"):
        kc = pick_delta(c, "CE", j, target)
        if kc is None:
            return None
        out.append(("CE", -1, kc))
    if struct in ("dput", "dstrangle"):
        kp = pick_delta(c, "PE", j, target)
        if kp is None:
            return None
        out.append(("PE", -1, kp))
    return out


# ---------------------------------------------------------------------------- IV percentile
def front_iv_series(cycles) -> pd.Series:
    """Front-month ATM implied vol by date: on each date, the cycle with the nearest expiry."""
    rows = {}
    for c in sorted(cycles, key=lambda x: x.expiry):
        for d, v in zip(c.dates, c.iv):
            if np.isfinite(v) and d not in rows and d <= c.expiry:
                rows[d] = v
    return pd.Series(rows).sort_index()


def iv_percentile(series: pd.Series, window: int = 250, min_obs: int = 60) -> pd.Series:
    """Percentile of each day's value among the previous `window` days (strictly earlier)."""
    vals = series.values
    out = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        past = vals[max(0, i - window):i]
        if len(past) >= min_obs:
            out[i] = (past <= vals[i]).mean() * 100
    return pd.Series(out, index=series.index)


# ---------------------------------------------------------------------------- delta-hedged straddle
FUT_EXCH, FUT_CTT_SELL, FUT_STAMP_BUY, SEBI, GST, FUT_SLIP = 0.000021, 0.0001, 0.00002, 0.000001, 0.18, 0.0002


def fut_cost(lots: float, F: float, mult: int, buy: bool) -> float:
    if lots <= 0:
        return 0.0
    turnover = lots * mult * F
    brokerage, exch, sebi = 20.0, turnover * FUT_EXCH, turnover * SEBI
    tax = turnover * (FUT_STAMP_BUY if buy else FUT_CTT_SELL)
    return brokerage + exch + sebi + tax + GST * (brokerage + exch + sebi) + turnover * FUT_SLIP


def run_dh_straddle(c, j0: int, lots: int, mult: int, family: str, tick: float, slip: float) -> dict | None:
    """Sell `lots` ATM straddles at the close of day j0, hedge the delta with whole futures lots at
    every close, close everything at the expiry-day close."""
    k = c.katm[j0]
    if not np.isfinite(k):
        return None
    ice, ipe = E._row(c, "CE", k), E._row(c, "PE", k)
    if ice is None or ipe is None:
        return None
    ce, pe = c.close["CE"][ice], c.close["PE"][ipe]
    trc, trp = c.traded["CE"][ice], c.traded["PE"][ipe]
    last = len(c.dates) - 1
    sl = lambda px, m=1.0: max(tick, slip * px) * m  # noqa: E731
    e_ce, e_pe = ce[j0] - sl(ce[j0]), pe[j0] - sl(pe[j0])
    if e_ce <= 0 or e_pe <= 0:
        return None
    fees = mcx_option_leg(e_ce, mult * lots, sell=True)["total"] + mcx_option_leg(e_pe, mult * lots, sell=True)["total"]
    hedge, hedge_pnl, max_hedge = 0, 0.0, 0
    for j in range(j0, last + 1):
        if j > j0 and np.isfinite(c.F[j]) and np.isfinite(c.F[j - 1]):
            hedge_pnl += hedge * (c.F[j] - c.F[j - 1]) * mult
        if j == last:
            break
        F = c.F[j]
        if not np.isfinite(F):
            continue
        T = max((c.expiry - c.dates[j]).days, 0.5) / 365.0
        ivs = b76.implied_vol(np.array([ce[j], pe[j]]), np.array([F, F]), np.array([k, k]), np.array([T, T]),
                              np.array([True, False]))
        if not np.isfinite(ivs).all():
            continue                                   # keep yesterday's hedge
        dl = b76.delta(np.array([F, F]), np.array([k, k]), np.array([T, T]), ivs, np.array([True, False]))
        target = int(round(float(dl.sum()) * lots))    # short straddle delta = -(dc + dp): buy this many futures
        if target != hedge:
            ch = target - hedge
            fees += fut_cost(abs(ch), F, mult, buy=ch > 0)
            hedge = target
            max_hedge = max(max_hedge, abs(hedge))
    Fl = c.F[last]
    if hedge != 0 and np.isfinite(Fl):
        fees += fut_cost(abs(hedge), Fl, mult, buy=hedge < 0)
    x_ce = ce[last] + sl(ce[last], 1.0 if trc[last] else 3.0)
    x_pe = pe[last] + sl(pe[last], 1.0 if trp[last] else 3.0)
    fees += mcx_option_leg(x_ce, mult * lots, sell=False)["total"] + mcx_option_leg(x_pe, mult * lots, sell=False)["total"]
    opt_pnl = ((e_ce + e_pe) - (x_ce + x_pe)) * mult * lots
    pnl = opt_pnl + hedge_pnl - fees
    margin = 2 * lots * E.SHORT_OPTION_FACTOR * E.MARGIN_RATE[family] * c.F[j0] * mult
    return {"expiry": c.expiry, "entry": c.dates[j0], "exit": c.dates[last], "reason": "time",
            "F0": c.F[j0], "straddle0": c.straddle[j0], "iv0": c.iv[j0], "rv0": c.rv20[j0],
            "legs": f"S{lots}xCE{k:g};S{lots}xPE{k:g}+hedge", "credit": (e_ce + e_pe) * mult * lots,
            "gross": opt_pnl + hedge_pnl, "fees": fees, "pnl": pnl, "capital": margin,
            "roc": pnl / margin if margin > 0 else np.nan, "stale_exit_legs": int(not trc[last]) + int(not trp[last]),
            # the futures hedge's own margin, if the broker does not net it (Angel did not net options)
            "max_hedge_lots": max_hedge, "hedge_margin_peak": max_hedge * E.MARGIN_RATE[family] * c.F[j0] * mult}
