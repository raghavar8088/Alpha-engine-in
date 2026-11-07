"""Indicators for the YouTube top-20 strategies. Every value at bar i uses bars <= i only."""

from __future__ import annotations

import numpy as np

from yt_markets import Bars, ema, rsi, sma  # noqa: F401  (re-exported)


def rma(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder's smoothed moving average (TradingView 'SMMA' / RMA)."""
    out = np.empty(len(x))
    a = 1.0 / n
    s = float(np.nanmean(x[:n])) if len(x) >= n else float(x[0])
    for i, v in enumerate(x):
        if i < n:
            out[i] = np.nan if i < n - 1 else s
            continue
        s = s + a * (v - s)
        out[i] = s
    return out


def true_range(b: Bars) -> np.ndarray:
    pc = np.r_[b.c[0], b.c[:-1]]
    return np.maximum(b.h, pc) - np.minimum(b.l, pc)


def atr(b: Bars, n: int = 14) -> np.ndarray:
    return rma(true_range(b), n)


def stoch_rsi(c: np.ndarray, n_rsi=14, n_st=14, k=3, d=3):
    r = rsi(c, n_rsi)
    lo = np.full(len(r), np.nan)
    hi = np.full(len(r), np.nan)
    for i in range(n_st - 1, len(r)):
        w = r[i - n_st + 1:i + 1]
        lo[i], hi[i] = w.min(), w.max()
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = np.where(hi > lo, 100 * (r - lo) / (hi - lo), 50.0)
    K = sma(np.nan_to_num(raw, nan=50.0), k)
    D = sma(np.nan_to_num(K, nan=50.0), d)
    return K, D


def heikin_ashi(b: Bars):
    hc = (b.o + b.h + b.l + b.c) / 4
    ho = np.empty(len(hc))
    ho[0] = (b.o[0] + b.c[0]) / 2
    for i in range(1, len(hc)):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2
    return ho, hc        # green when hc > ho


def supertrend(b: Bars, n=10, mult=3.0):
    """TradingView Supertrend(ATR n, factor mult): returns (line, direction +1 up / -1 down)."""
    a = atr(b, n)
    hl2 = (b.h + b.l) / 2
    up = hl2 - mult * a
    dn = hl2 + mult * a
    fu, fd = up.copy(), dn.copy()
    dirn = np.ones(len(hl2), int)
    line = np.full(len(hl2), np.nan)
    for i in range(1, len(hl2)):
        if np.isnan(a[i]):
            continue
        fu[i] = max(up[i], fu[i - 1]) if b.c[i - 1] > fu[i - 1] and not np.isnan(fu[i - 1]) else up[i]
        fd[i] = min(dn[i], fd[i - 1]) if b.c[i - 1] < fd[i - 1] and not np.isnan(fd[i - 1]) else dn[i]
        if dirn[i - 1] == 1:
            dirn[i] = -1 if b.c[i] < fu[i] else 1
        else:
            dirn[i] = 1 if b.c[i] > fd[i] else -1
        line[i] = fu[i] if dirn[i] == 1 else fd[i]
    return line, dirn


def vortex(b: Bars, n=14):
    pl = np.r_[b.l[0], b.l[:-1]]
    ph = np.r_[b.h[0], b.h[:-1]]
    vmp = np.abs(b.h - pl)
    vmm = np.abs(b.l - ph)
    tr = true_range(b)
    cs = lambda x: np.cumsum(np.r_[0.0, x])
    a, bb, t = cs(vmp), cs(vmm), cs(tr)
    vp = np.full(len(tr), np.nan)
    vm = np.full(len(tr), np.nan)
    s = t[n:] - t[:-n]
    vp[n - 1:] = (a[n:] - a[:-n]) / np.where(s > 0, s, np.nan)
    vm[n - 1:] = (bb[n:] - bb[:-n]) / np.where(s > 0, s, np.nan)
    return vp, vm


def bollinger(c, n=20, k=2.0):
    mid = sma(c, n)
    sd = np.full(len(c), np.nan)
    for i in range(n - 1, len(c)):
        sd[i] = c[i - n + 1:i + 1].std()
    return mid, mid + k * sd, mid - k * sd


def fractals(b: Bars, n=2):
    """Williams fractals: up[i]/down[i] True if bar i is the extreme of i-n..i+n (known at bar i+n)."""
    N = len(b.h)
    up = np.zeros(N, bool)
    dn = np.zeros(N, bool)
    for i in range(n, N - n):
        if b.h[i] > b.h[i - n:i].max() and b.h[i] >= b.h[i + 1:i + n + 1].max():
            up[i] = True
        if b.l[i] < b.l[i - n:i].min() and b.l[i] <= b.l[i + 1:i + n + 1].min():
            dn[i] = True
    return up, dn


def session_vwap(m, b: Bars) -> np.ndarray:
    """VWAP per bar close from the rows' typical price and volume, reset each trading day."""
    tp = (m.h + m.l + m.c) / 3
    pv = tp * m.vol
    out = np.full(len(b.c), np.nan)
    for d in range(m.n_days):
        a, z = int(m.d0[d]), int(m.d1[d])
        cpv = np.cumsum(pv[a:z])
        cv = np.cumsum(m.vol[a:z])
        bs, be = int(b.b0[d]), int(b.b1[d])
        for j in range(bs, be):
            r = int(b.i1[j]) - a
            if cv[r] > 0:
                out[j] = cpv[r] / cv[r]
    return out
