"""Gold Lab — the seven strategies that survived the 2026-10 gold strategy search, as live rules.

WHERE THEY COME FROM (backend/research/gold_lab_2026_10, GOLD_STRATEGY_LAB_2026_10.md)
---------------------------------------------------------------------------------------
157 daily strategy variants, generated in five rounds and ALL registered, were tested on GLD
(spot-gold ETF) with execution at the next New York open, 2 bp a side and returns over cash:
selection 2004-11..2014-12, validation 2015..2019, then a holdout 2020-01..2026-10 opened once.
None beat holding gold with significance after the correction for 157 trials (Tier A: 0).
These seven were profitable after costs in selection, validation AND the untouched holdout,
held up on COMEX data and with their parameter neighbours — "Tier B": profitable, NOT proven
better than holding gold. They are three ideas, not seven: a trend cluster (gl1, gl3, gl4, gl5,
return correlation 0.75-0.98), a shock-continuation pair (gl6, gl7) and macro fair-value
reversion (gl2, independent of the rest).

THESE FUNCTIONS ARE THE RESEARCH'S, PORTED (evidence betas are the holdout's)
-----------------------------------------
Inputs are DAILY CLOSES on the NYSE calendar: GLD (the signal instrument) and, for gl2, UUP
(dollar), TIP (real yields) and the S&P 500 — all closing at 16:00 New York with GLD. A target
for day t uses closes up to t only and is executed at the NEXT New York open. A test
(backend/tests/gold_desk/verify_gold_lab.py) holds every rule to the research implementation
over 2004-2026, value for value.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

DAYS = 252

LAB_STRATEGIES: list[dict] = [
    {"id": "gl1", "key": "multi_signal|scale=1.5,tom=True", "cluster": "trend",
     "name": "Multi-signal: trend + shock + month-turn",
     "how": ("Average of three signals x 1.5 (cap 1.5x): diversified trend (signs of 1/3/6/12-month "
             "returns, long/flat, sized to 15% vol), 5-day continuation after a 2-sigma day, and long "
             "over the last 2 / first 3 sessions of each month."),
     "evidence": {"sel_sharpe": 0.666, "val_sharpe": 0.665, "holdout_sharpe": 0.731, "holdout_alpha_t": 1.00,
                  "full_sharpe": 0.679, "full_alpha_t": 2.29, "delta_full_sharpe": 0.43, "beta": 0.39}},
    {"id": "gl2", "key": "macro_residual|H=10,z0=2.0", "cluster": "macro",
     "name": "Macro fair-value reversion",
     "how": ("GLD's daily return regressed (rolling 126 sessions) on the dollar (UUP), real yields (TIP) "
             "and the S&P 500; when the 20-day sum of residuals is beyond 2 sigma, fade it for 10 sessions."),
     "evidence": {"sel_sharpe": 0.531, "val_sharpe": 0.046, "holdout_sharpe": 0.557, "holdout_alpha_t": 2.01,
                  "full_sharpe": 0.456, "full_alpha_t": 2.59, "delta_full_sharpe": 0.49, "beta": -0.08}},
    {"id": "gl3", "key": "trend_plus_shock|w_shock=1.0,w_trend=1.0", "cluster": "trend",
     "name": "Trend + shock continuation",
     "how": ("6-month trend (long/flat, sized to 15% vol) plus 5-day continuation after a 2.5-sigma day, "
             "capped at 1.5x."),
     "evidence": {"sel_sharpe": 0.757, "val_sharpe": 0.608, "holdout_sharpe": 0.567, "holdout_alpha_t": 0.19,
                  "full_sharpe": 0.656, "full_alpha_t": 1.83, "delta_full_sharpe": 0.28, "beta": 0.63}},
    {"id": "gl4", "key": "trend_plus_shock|w_shock=0.5,w_trend=1.0", "cluster": "trend",
     "name": "Trend + half-weight shock continuation",
     "how": "As gl3 with the shock leg at half weight.",
     "evidence": {"sel_sharpe": 0.767, "val_sharpe": 0.544, "holdout_sharpe": 0.617, "holdout_alpha_t": 0.17,
                  "full_sharpe": 0.666, "full_alpha_t": 1.84, "delta_full_sharpe": 0.25, "beta": 0.66}},
    {"id": "gl5", "key": "tsmom|L=126,mode=long_flat,tv=0.15", "cluster": "trend",
     "name": "6-month trend, long or flat",
     "how": "Long while gold's 126-session return is positive, sized to 15% vol (cap 1.5x); flat otherwise.",
     "evidence": {"sel_sharpe": 0.679, "val_sharpe": 0.428, "holdout_sharpe": 0.690, "holdout_alpha_t": 0.26,
                  "full_sharpe": 0.630, "full_alpha_t": 1.54, "delta_full_sharpe": 0.19, "beta": 0.67}},
    {"id": "gl6", "key": "shock_stop|k=2.0", "cluster": "shock",
     "name": "Shock continuation with a stop",
     "how": ("After a 2-sigma day, hold its direction up to 10 sessions; out early if the trade's close-to-close "
             "P&L falls below -1 daily sigma."),
     "evidence": {"sel_sharpe": 0.459, "val_sharpe": 0.306, "holdout_sharpe": 0.077, "holdout_alpha_t": 0.35,
                  "full_sharpe": 0.301, "full_alpha_t": 1.64, "delta_full_sharpe": 0.31, "beta": -0.03}},
    {"id": "gl7", "key": "reversal|H=5,dir=cont,k=3.0", "cluster": "shock",
     "name": "3-sigma shock continuation",
     "how": "After a 3-sigma day, hold its direction for 5 sessions.",
     "evidence": {"sel_sharpe": 0.400, "val_sharpe": 0.013, "holdout_sharpe": 0.131, "holdout_alpha_t": 0.57,
                  "full_sharpe": 0.246, "full_alpha_t": 1.72, "delta_full_sharpe": 0.28, "beta": -0.03}},
]
LAB_IDS = tuple(s["id"] for s in LAB_STRATEGIES)

# ── the NYSE calendar the month-turn rule and the executor need ─────────────────
# Full-day closures, 2026-2028 (NYSE rules: Saturday holidays observed Friday, Sunday ones
# Monday; New Year's Day on a Saturday is not observed). Past 2028 the lab places no new
# trade until this list is extended — it fails closed rather than guessing.
NYSE_HOLIDAYS = frozenset(date.fromisoformat(d) for d in (
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
    "2027-09-06", "2027-11-25", "2027-12-24",
    "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19", "2028-07-04", "2028-09-04",
    "2028-11-23", "2028-12-25",
))
CALENDAR_THROUGH = date(2028, 12, 31)


def is_nyse_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def calendar_known(d: date) -> bool:
    return d <= CALENDAR_THROUGH


def next_nyse_day(d: date) -> date:
    n = d + timedelta(days=1)
    while not is_nyse_day(n):
        n += timedelta(days=1)
    return n


def nyse_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if is_nyse_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


# ── the rules (ported from backend/research/gold_lab_2026_10/gl_families.py) ────


def _vol(close: pd.Series, L: int) -> pd.Series:
    r = np.log(close).diff()
    return r.rolling(L, min_periods=max(10, L // 2)).std() * math.sqrt(DAYS)


def _vol_size(close: pd.Series, raw: pd.Series, target_vol: float, L: int = 63, cap: float = 1.5) -> np.ndarray:
    w = (target_vol / _vol(close, L)).clip(upper=cap)
    return (raw * w).fillna(0).to_numpy(float)


def tsmom_long_flat(close: pd.Series, L: int = 126, tv: float = 0.15) -> np.ndarray:
    sig = np.sign(np.log(close / close.shift(L))).clip(lower=0)
    return _vol_size(close, sig, tv)


def trend_ensemble_long_flat(close: pd.Series, tv: float = 0.15) -> np.ndarray:
    sig = sum(np.sign(np.log(close / close.shift(L))) for L in (21, 63, 126, 252)) / 4.0
    return _vol_size(close, sig.clip(lower=0), tv)


def shock_continuation(close: pd.Series, k: float, H: int) -> np.ndarray:
    r = np.log(close).diff().to_numpy()
    sd = (_vol(close, 63) / math.sqrt(DAYS)).shift(1).to_numpy()
    pos = np.zeros(len(r))
    left, side = 0, 0.0
    for t in range(len(r)):
        if sd[t] == sd[t] and r[t] == r[t] and abs(r[t]) > k * sd[t]:
            side = np.sign(r[t])
            left = H
        if left > 0:
            pos[t] = side
            left -= 1
    return pos


def turn_of_month(dates: pd.DatetimeIndex, future: list[date] | None = None, pre: int = 2, post: int = 3) -> np.ndarray:
    """Long over the last `pre` and first `post` sessions of each month; the target at day t is
    for the NEXT session. `future` supplies the sessions after the last date (live: from the
    NYSE calendar), so the month's position is known as the research knew it in hindsight."""
    all_days = list(dates.date) + list(future or [])
    idx = pd.DatetimeIndex(pd.to_datetime(all_days))
    month = idx.year * 12 + idx.month
    s = pd.Series(np.arange(len(idx)), index=idx)
    pos_in_month = s.groupby(month).cumcount().to_numpy()
    size = s.groupby(month).transform("size").to_numpy()
    from_end = size - 1 - pos_in_month
    hold = (from_end < pre) | (pos_in_month < post)
    tgt = np.r_[hold[1:], False].astype(float)
    return tgt[:len(dates)]


def macro_residual(gld: pd.Series, uup: pd.Series, tip: pd.Series, spx: pd.Series,
                   z0: float = 2.0, H: int = 10, W: int = 126) -> np.ndarray:
    g = np.log(gld).diff()
    X = pd.concat({"UUP": np.log(uup / uup.shift(1)), "TIP": np.log(tip / tip.shift(1)),
                   "SPX": np.log(spx / spx.shift(1))}, axis=1)
    df = pd.concat([g.rename("g"), X], axis=1)
    arr = df.to_numpy()
    resid = np.full(len(df), np.nan)
    for t in range(W, len(df)):
        win = arr[t - W + 1:t + 1]
        ok = ~np.isnan(win).any(axis=1)
        if ok.sum() < W * 0.8:
            continue
        y, xm = win[ok, 0], np.column_stack([np.ones(ok.sum()), win[ok, 1:]])
        beta = np.linalg.lstsq(xm, y, rcond=None)[0]
        if not np.isnan(arr[t]).any():
            resid[t] = arr[t, 0] - np.r_[1.0, arr[t, 1:]] @ beta
    rs = pd.Series(resid, index=df.index)
    cum = rs.rolling(20, min_periods=15).sum()
    z = (cum / (rs.rolling(126, min_periods=60).std() * math.sqrt(20))).to_numpy()
    side = np.nan_to_num(np.where(z > z0, -1.0, np.where(z < -z0, 1.0, 0.0)))
    pos = np.zeros(len(side))
    left, cur = 0, 0.0
    for t in range(len(side)):
        if side[t] != 0:
            cur, left = side[t], H
        if left > 0:
            pos[t] = cur
            left -= 1
    return pos


def shock_stop(close: pd.Series, k: float = 2.0) -> np.ndarray:
    r = np.log(close).diff().fillna(0).to_numpy()
    sd = (_vol(close, 63) / math.sqrt(DAYS)).shift(1).to_numpy()
    pos = np.zeros(len(r))
    side, left, pnl = 0.0, 0, 0.0
    for t in range(len(r)):
        if side != 0:
            pnl += side * r[t]
            if pnl < -sd[t]:
                side, left = 0.0, 0
        if sd[t] == sd[t] and abs(r[t]) > k * sd[t]:
            side, left, pnl = np.sign(r[t]), 10, 0.0
        if left > 0 and side != 0:
            pos[t] = side
            left -= 1
        else:
            side = 0.0
    return pos


def targets(closes: pd.DataFrame, future: list[date] | None = None) -> pd.DataFrame:
    """Every lab strategy's target position (fraction of its sleeve) for each date in `closes`
    (columns gld, uup, tip, spx on the NYSE calendar). Row t is the position to hold from the
    open of the session AFTER t."""
    gld = closes["gld"]
    tom = turn_of_month(closes.index, future)
    trend126 = tsmom_long_flat(gld)
    out = {
        "gl1": np.clip((trend_ensemble_long_flat(gld) + shock_continuation(gld, 2.0, 5) + tom) / 3.0 * 1.5, -1.5, 1.5),
        "gl2": macro_residual(gld, closes["uup"], closes["tip"], closes["spx"]),
        "gl3": np.clip(trend126 + shock_continuation(gld, 2.5, 5) * 1.0, -1.5, 1.5),
        "gl4": np.clip(trend126 + shock_continuation(gld, 2.5, 5) * 0.5, -1.5, 1.5),
        "gl5": trend126,
        "gl6": shock_stop(gld, 2.0),
        "gl7": shock_continuation(gld, 3.0, 5),
    }
    return pd.DataFrame(out, index=closes.index)
