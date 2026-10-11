"""Gold strategy lab: the backtest engine and its statistics.

EXECUTION (no look-ahead, no trading at the close you computed from)
--------------------------------------------------------------------
A rule outputs `target[t]`: the position it wants, decided with data up to the CLOSE of day t.
It is executed at the OPEN of day t+1. So on day t:

    return[t] = (1 + target[t-2] * gap[t])    (open_t / close_{t-1} - 1: the position held overnight)
              * (1 + target[t-1] * intraday[t]) - 1      (close_t / open_t - 1: the position just executed)
              - cost * |target[t-1] - target[t-2]|      (paid at the open of day t)
              - target[t-1] * rf[t]           (excess over cash: what a futures position earns)

Positions are fractions of capital (1 = fully long one unit of notional). Costs are per side
in bp of notional (default 2.0 — above the measured MCX GOLDM 1.7 and Delta XAUT 1.3).
Returns are EXCESS returns: gold held through futures or a perpetual earns gold minus the cash
rate, so the benchmark is the same: always long 1.0, entered once, charged the same way.

STATISTICS
----------
Sharpe annualised from daily returns; alpha and beta against the benchmark from WEEKLY returns
(positions overlap days; weekly sums keep the t honest); the Deflated Sharpe Ratio (Bailey &
Lopez de Prado 2014) and PBO by CSCV (Bailey, Borwein, Lopez de Prado & Zhu 2017).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd

from gl_data import load, rf_daily

ND = NormalDist()
DAYS = 252


@dataclass
class Market:
    name: str
    dates: pd.DatetimeIndex
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    rf: np.ndarray

    @property
    def gap(self) -> np.ndarray:
        g = np.zeros(len(self.close))
        g[1:] = self.open[1:] / self.close[:-1] - 1
        return g

    @property
    def intraday(self) -> np.ndarray:
        return self.close / self.open - 1

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame({"open": self.open, "high": self.high, "low": self.low, "close": self.close},
                            index=self.dates)


def market(name: str = "GLD", on: pd.DatetimeIndex | None = None) -> Market:
    """One instrument's bars — on its own calendar, or reindexed onto another's (`on`): a session
    the instrument did not trade becomes a flat bar at its last close, so it adds no return."""
    df = load(name)
    if on is not None:
        c = df["close"].reindex(on.union(df.index)).ffill().reindex(on)
        traded = pd.Series(on.isin(df.index), index=on)
        o = df["open"].reindex(on).where(traded, c)
        h = df["high"].reindex(on).where(traded, c)
        lo = df["low"].reindex(on).where(traded, c)
        df = pd.DataFrame({"open": o, "high": h, "low": lo, "close": c}, index=on)
        first = df["close"].first_valid_index()
        df = df.fillna(df["close"].loc[first] if first is not None else 1.0)
    rf = rf_daily(df.index).to_numpy()
    return Market(name, df.index, df["open"].to_numpy(float), df["high"].to_numpy(float),
                  df["low"].to_numpy(float), df["close"].to_numpy(float), rf)


def simulate(target: np.ndarray, m: Market, cost_bp: float = 2.0, excess: bool = True) -> np.ndarray:
    """Daily net returns of a target-position series (see the module docstring)."""
    tgt = np.nan_to_num(np.asarray(target, float), nan=0.0)
    held_gap = np.r_[0.0, 0.0, tgt[:-2]]          # target[t-2]
    held_day = np.r_[0.0, tgt[:-1]]               # target[t-1]
    trade = np.abs(held_day - held_gap)
    # exact: the overnight leg moves equity by held_gap * gap, then the book is reset to held_day
    r = (1 + held_gap * m.gap) * (1 + held_day * m.intraday) - 1 - trade * cost_bp / 1e4
    if excess:
        r = r - held_day * m.rf
    return r


def simulate_legs(targets: dict, legs: dict, cost_bp: float = 2.0) -> np.ndarray:
    """A multi-instrument rule: each leg simulated on its own bars, as a fraction of the same
    capital, and summed. Cash-rate charges cancel on a dollar-neutral pair, as they should."""
    out = None
    for name, tgt in targets.items():
        r = simulate(tgt, legs[name], cost_bp)
        out = r if out is None else out + r
    return out


def benchmark(m: Market, cost_bp: float = 2.0) -> np.ndarray:
    tgt = np.ones(len(m.close))
    return simulate(tgt, m, cost_bp)


# ── statistics ───────────────────────────────────────────────────────────────────


def max_drawdown(r: np.ndarray) -> float:
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float((1 - eq / peak).max()) if len(eq) else 0.0


def ols_alpha(y: np.ndarray, x: np.ndarray, lags: int = 2) -> tuple[float, float, float]:
    """(alpha, beta, Newey-West t of alpha) for y = a + b x."""
    n = len(y)
    if n < 10:
        return float("nan"), float("nan"), float("nan")
    X = np.column_stack([np.ones(n), x])
    xtx_inv = np.linalg.inv(X.T @ X)
    b = xtx_inv @ X.T @ y
    e = y - X @ b
    s = (X * e[:, None])
    S = s.T @ s
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        g = s[L:].T @ s[:-L]
        S += w * (g + g.T)
    cov = xtx_inv @ S @ xtx_inv
    se = math.sqrt(max(cov[0, 0], 1e-30))
    return float(b[0]), float(b[1]), float(b[0] / se)


def weekly(r: pd.Series) -> pd.Series:
    return r.groupby(r.index.to_period("W")).sum()


def metrics(r: np.ndarray, bench: np.ndarray, target: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    n = len(r)
    if n < 60:
        return {"days": n}
    sd = r.std(ddof=1)
    rs = pd.Series(r, index=dates)
    bs = pd.Series(bench, index=dates)
    rw, bw = weekly(rs), weekly(bs)
    a, b, ta = ols_alpha(rw.to_numpy(), bw.to_numpy())
    tgt = np.nan_to_num(np.asarray(target, float))
    change = np.abs(np.diff(np.r_[0.0, tgt]))
    entries = int(((np.r_[0.0, tgt[:-1]] == 0) & (tgt != 0)).sum() + ((np.sign(np.r_[0.0, tgt[:-1]]) * np.sign(tgt)) < 0).sum())
    years = n / DAYS
    half = n // 2
    s1 = r[:half].mean() / r[:half].std(ddof=1) * math.sqrt(DAYS) if r[:half].std(ddof=1) > 0 else 0.0
    s2 = r[half:].mean() / r[half:].std(ddof=1) * math.sqrt(DAYS) if r[half:].std(ddof=1) > 0 else 0.0
    sk = float(pd.Series(r).skew())
    ku = float(pd.Series(r).kurt()) + 3.0
    return {
        "days": n, "years": round(years, 2),
        "ann_ret": float(r.mean() * DAYS), "ann_vol": float(sd * math.sqrt(DAYS)),
        "sharpe": float(r.mean() / sd * math.sqrt(DAYS)) if sd > 0 else 0.0,
        "cagr": float(np.prod(1 + r) ** (1 / years) - 1) if years > 0 else 0.0,
        "maxdd": max_drawdown(r),
        "alpha_ann": a * 52 if a == a else float("nan"), "beta": b, "alpha_t": ta,
        "exposure": float(np.abs(tgt).mean()), "long_share": float((tgt > 0).mean()),
        "turnover_yr": float(change.sum() / years), "entries": entries,
        "sharpe_h1": float(s1), "sharpe_h2": float(s2),
        "skew": sk, "kurt": ku, "sr_daily": float(r.mean() / sd) if sd > 0 else 0.0,
    }


def deflated_sr(sr: float, n: int, skew: float, kurt: float, sr_var: float, trials: int) -> float:
    """Bailey & Lopez de Prado (2014): P(true SR > 0) given `trials` attempts. SR per period."""
    if n < 3 or not np.isfinite(sr) or trials < 2:
        return float("nan")
    g = 0.5772156649
    sr0 = math.sqrt(max(sr_var, 1e-12)) * ((1 - g) * ND.inv_cdf(1 - 1 / trials) + g * ND.inv_cdf(1 - 1 / (trials * math.e)))
    den = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr * sr, 1e-12))
    return float(ND.cdf((sr - sr0) * math.sqrt(n - 1) / den))


def pbo_cscv(mat: np.ndarray, S: int = 16) -> tuple[float, int]:
    """Probability of backtest overfitting (CSCV). mat: periods x strategies."""
    T, N = mat.shape
    if N < 3 or T < S * 2:
        return float("nan"), 0
    blocks = np.array_split(np.arange(T), S)

    def sharpe(mm):
        sd = mm.std(axis=0, ddof=1)
        return np.where(sd > 0, mm.mean(axis=0) / np.where(sd > 0, sd, 1), -np.inf)

    lam = []
    for comb in itertools.combinations(range(S), S // 2):
        is_idx = np.concatenate([blocks[k] for k in comb])
        oos_idx = np.concatenate([blocks[k] for k in range(S) if k not in comb])
        best = int(np.argmax(sharpe(mat[is_idx])))
        oos = sharpe(mat[oos_idx])
        rank = (oos < oos[best]).sum() + 0.5 * ((oos == oos[best]).sum() - 1)
        w = (rank + 1) / (N + 1)
        lam.append(math.log(w / (1 - w)))
    lam = np.asarray(lam)
    return float((lam <= 0).mean()), len(lam)
