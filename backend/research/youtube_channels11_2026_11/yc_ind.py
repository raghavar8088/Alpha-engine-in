"""Indicators for the 11-channel strategies, beyond the YouTube study's yt_ind. Every value at bar i uses bars <= i
only, except where a name says it is shifted (the Alligator and Ichimoku are plotted shifted forward, which only ever
moves a value later, never earlier). Pivots of n bars are known n bars after the pivot bar: callers must wait."""

from __future__ import annotations

import numpy as np

import yt_ind as I
from yt_markets import ema, rsi, sma  # noqa: F401  (re-exported)

rma = I.rma
atr = I.atr
true_range = I.true_range
supertrend = I.supertrend
bollinger = I.bollinger
heikin_ashi = I.heikin_ashi
session_vwap = I.session_vwap
fractals = I.fractals          # Williams fractals: flag at the pivot bar, known n bars later


def shift(x: np.ndarray, n: int) -> np.ndarray:
    """x moved n bars later (value at i is x[i - n]); the first n values are NaN."""
    out = np.full(len(x), np.nan)
    if n < len(x):
        out[n:] = x[:len(x) - n]
    return out


def highest(x: np.ndarray, n: int) -> np.ndarray:
    """Max of x over the n bars ending at i (inclusive)."""
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = x[i - n + 1:i + 1].max()
    return out


def lowest(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = x[i - n + 1:i + 1].min()
    return out


def prior_highest(x: np.ndarray, n: int) -> np.ndarray:
    """Max of x over the n bars before i (excluding i)."""
    return shift(highest(x, n), 1)


def prior_lowest(x: np.ndarray, n: int) -> np.ndarray:
    return shift(lowest(x, n), 1)


def mean_prev(x: np.ndarray, n: int) -> np.ndarray:
    """Mean of x over the n bars before i (excluding i)."""
    cs = np.cumsum(np.r_[0.0, x])
    out = np.full(len(x), np.nan)
    if len(x) > n:
        out[n:] = (cs[n:-1] - cs[:-n - 1]) / n
    return out


def macd(c: np.ndarray, fast=12, slow=26, sig=9):
    line = ema(c, fast) - ema(c, slow)
    signal = ema(line, sig)
    return line, signal, line - signal


def adx(b, n: int = 14):
    """Wilder's ADX with +DI and -DI (TradingView's DMI)."""
    up = b.h - np.r_[b.h[0], b.h[:-1]]
    dn = np.r_[b.l[0], b.l[:-1]] - b.l
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = rma(true_range(b), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100 * rma(pdm, n) / tr
        mdi = 100 * rma(mdm, n) / tr
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    dx = np.where(np.isfinite(dx), dx, 0.0)
    first = int(np.argmax(np.isfinite(tr))) if np.isfinite(tr).any() else len(tr)
    a = np.full(len(dx), np.nan)
    if first < len(dx):
        a[first:] = rma(dx[first:], n)
    return a, pdi, mdi


def stochastic(b, k: int = 14, smooth_k: int = 1, d: int = 3):
    lo, hi = lowest(b.l, k), highest(b.h, k)
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = np.where(hi > lo, 100 * (b.c - lo) / (hi - lo), 50.0)
    raw = np.where(np.isfinite(raw), raw, 50.0)
    K = raw if smooth_k <= 1 else sma(raw, smooth_k)
    D = sma(np.where(np.isfinite(K), K, 50.0), d)
    return K, D


def psar(b, step: float = 0.02, cap: float = 0.2):
    """Parabolic SAR (Wilder): value per bar and trend (+1 long / -1 short), computed bar by bar."""
    n = len(b.c)
    sar = np.full(n, np.nan)
    trend = np.zeros(n, int)
    if n < 2:
        return sar, trend
    up = b.c[1] >= b.c[0]
    ep = b.h[1] if up else b.l[1]
    s = b.l[0] if up else b.h[0]
    af = step
    for i in range(1, n):
        s = s + af * (ep - s)
        if up:
            s = min(s, b.l[i - 1], b.l[i - 2] if i >= 2 else b.l[i - 1])
            if b.l[i] < s:
                up, s, ep, af = False, ep, b.l[i], step
            elif b.h[i] > ep:
                ep, af = b.h[i], min(af + step, cap)
        else:
            s = max(s, b.h[i - 1], b.h[i - 2] if i >= 2 else b.h[i - 1])
            if b.h[i] > s:
                up, s, ep, af = True, ep, b.h[i], step
            elif b.l[i] < ep:
                ep, af = b.l[i], min(af + step, cap)
        sar[i] = s
        trend[i] = 1 if up else -1
    return sar, trend


def ichimoku(h: np.ndarray, l: np.ndarray, c: np.ndarray, conv=9, base=26, span_b=52, disp=26):
    """(tenkan, kijun, cloud_a, cloud_b) as plotted: the cloud at bar i is the spans computed disp bars earlier."""
    mid = lambda n: (highest(h, n) + lowest(l, n)) / 2  # noqa: E731
    tenkan, kijun = mid(conv), mid(base)
    a = (tenkan + kijun) / 2
    bb = mid(span_b)
    return tenkan, kijun, shift(a, disp), shift(bb, disp)


def pvt(c: np.ndarray, v: np.ndarray) -> np.ndarray:
    pc = np.r_[c[0], c[:-1]]
    with np.errstate(invalid="ignore", divide="ignore"):
        step = np.where(pc > 0, (c - pc) / pc * v, 0.0)
    return np.cumsum(step)


def smma(x: np.ndarray, n: int) -> np.ndarray:
    return rma(x, n)


def alligator(b):
    """Williams Alligator on the median price, as plotted: jaw SMMA 13 shifted 8, teeth SMMA 8 shifted 5,
    lips SMMA 5 shifted 3."""
    med = (b.h + b.l) / 2
    return shift(smma(med, 13), 8), shift(smma(med, 8), 5), shift(smma(med, 5), 3)


def pivot_points(H: float, L: float, C: float) -> dict:
    """Classic floor pivots and the central pivot range from the previous session."""
    P = (H + L + C) / 3
    BC = (H + L) / 2
    TC = 2 * P - BC
    return {"P": P, "R1": 2 * P - L, "S1": 2 * P - H, "R2": P + (H - L), "S2": P - (H - L),
            "R3": H + 2 * (P - L), "S3": L - 2 * (H - P), "BC": min(BC, TC), "TC": max(BC, TC)}


def day_hlc(m):
    """Per trading day of a minute market: (high, low, close)."""
    h = np.maximum.reduceat(m.h, m.d0)
    l = np.minimum.reduceat(m.l, m.d0)
    c = m.c[m.d1 - 1]
    return h, l, c


def pivots_known(b, ph: np.ndarray, pl: np.ndarray, n: int):
    """Per bar j: the most recent pivot high / low value and index confirmed by bar j (a pivot of n is known n bars
    after it). Returns (hi_val, hi_idx, lo_val, lo_idx, prev_hi_val, prev_lo_val)."""
    N = len(b.h)
    hv = np.full(N, np.nan)
    hi = np.full(N, -1, np.int64)
    lv = np.full(N, np.nan)
    li = np.full(N, -1, np.int64)
    phv = np.full(N, np.nan)
    plv = np.full(N, np.nan)
    last_h = last_l = None
    prev_h = prev_l = np.nan
    for j in range(N):
        q = j - n
        if q >= 0:
            if ph[q]:
                prev_h = last_h[0] if last_h else np.nan
                last_h = (b.h[q], q)
            if pl[q]:
                prev_l = last_l[0] if last_l else np.nan
                last_l = (b.l[q], q)
        if last_h:
            hv[j], hi[j] = last_h
        if last_l:
            lv[j], li[j] = last_l
        phv[j], plv[j] = prev_h, prev_l
    return hv, hi, lv, li, phv, plv


def pivot_flags(x_hi: np.ndarray, x_lo: np.ndarray, left: int, right: int):
    """TradingView pivothigh/pivotlow(left, right): flag at the pivot bar (known `right` bars later)."""
    N = len(x_hi)
    ph = np.zeros(N, bool)
    pl = np.zeros(N, bool)
    for i in range(left, N - right):
        if x_hi[i] > x_hi[i - left:i].max() and x_hi[i] >= x_hi[i + 1:i + right + 1].max():
            ph[i] = True
        if x_lo[i] < x_lo[i - left:i].min() and x_lo[i] <= x_lo[i + 1:i + right + 1].min():
            pl[i] = True
    return ph, pl


def rsi_divergences(b, n_rsi=14, left=5, right=5, rmin=5, rmax=60):
    """TradingView's 'RSI Divergence Indicator' regular divergences. Returns lists of (pivot bar, known bar) for
    bullish (price lower low, RSI higher low) and bearish (price higher high, RSI lower high)."""
    r = rsi(b.c, n_rsi)
    _, rpl = pivot_flags(r, r, left, right)
    rph, _ = pivot_flags(r, r, left, right)
    bull, bear = [], []
    last_l = last_h = None
    for i in range(len(r)):
        if rpl[i]:
            if last_l is not None and rmin <= i - last_l <= rmax and r[i] > r[last_l] and b.l[i] < b.l[last_l]:
                bull.append((i, i + right))
            last_l = i
        if rph[i]:
            if last_h is not None and rmin <= i - last_h <= rmax and r[i] < r[last_h] and b.h[i] > b.h[last_h]:
                bear.append((i, i + right))
            last_h = i
    return bull, bear


def anchored_vwap(m, b, anchor_utc_min: int) -> np.ndarray:
    """VWAP per bar close, reset at a fixed UTC minute of the day (bitcoin's 06:00 IST open = 00:30 UTC)."""
    tp = (m.h + m.l + m.c) / 3
    v = np.asarray(m.vol, float)
    shifted = (m.t - anchor_utc_min * 60) // 86400
    key = shifted.astype(np.int64)
    pv = tp * v
    out = np.full(len(b.c), np.nan)
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    cpv = np.empty(len(pv))
    cv = np.empty(len(v))
    for a, z in zip(starts, np.r_[starts[1:], len(key)]):
        cpv[a:z] = np.cumsum(pv[a:z])
        cv[a:z] = np.cumsum(v[a:z])
    r = b.i1
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(cv[r] > 0, cpv[r] / cv[r], np.nan)
    return out


def renko(m, box: float, start_row: int = 0):
    """Traditional Renko from minute closes. Returns per brick: (direction +1/-1, open, close, high, low, row at which
    it completed). The first brick needs a full box from the first close; a reversal needs two boxes."""
    if box <= 0:
        return np.zeros(0, int), *(np.zeros(0),) * 4, np.zeros(0, np.int64)
    c = m.c
    base = float(c[start_row])
    top, bot = base, base
    dirs, opens, closes, rows = [], [], [], []
    trend = 0
    for k in range(start_row + 1, len(c)):
        x = float(c[k])
        while True:
            if trend >= 0 and x >= top + box:
                o, top = top, top + box
                bot = o
                dirs.append(1)
                opens.append(o)
                closes.append(top)
                rows.append(k)
                trend = 1
            elif trend <= 0 and x <= bot - box:
                o, bot = bot, bot - box
                top = o
                dirs.append(-1)
                opens.append(o)
                closes.append(bot)
                rows.append(k)
                trend = -1
            elif trend == 1 and x <= bot - box:
                o, bot = bot, bot - box
                top = o
                dirs.append(-1)
                opens.append(o)
                closes.append(bot)
                rows.append(k)
                trend = -1
            elif trend == -1 and x >= top + box:
                o, top = top, top + box
                bot = o
                dirs.append(1)
                opens.append(o)
                closes.append(top)
                rows.append(k)
                trend = 1
            else:
                break
    d = np.asarray(dirs, int)
    o = np.asarray(opens, float)
    cl = np.asarray(closes, float)
    return d, o, cl, np.maximum(o, cl), np.minimum(o, cl), np.asarray(rows, np.int64)


def gann_levels(lo: float, hi: float) -> list[float]:
    """Gann 'special numbers' between lo and hi: n squared for odd n, n squared + 1 for even n."""
    out = []
    n = max(1, int(np.floor(np.sqrt(max(lo, 1.0)))) - 1)
    while True:
        v = n * n if n % 2 else n * n + 1
        if v > hi:
            break
        if v >= lo:
            out.append(float(v))
        n += 1
    return out


def ha_ohlc(b):
    """Full Heikin Ashi candles: (open, high, low, close)."""
    ho, hc = heikin_ashi(b)
    hh = np.maximum.reduce([b.h, ho, hc])
    hl = np.minimum.reduce([b.l, ho, hc])
    return ho, hh, hl, hc


class HABars:
    """Heikin Ashi candles in the Bars layout (same rows and days), so indicators can run on them."""

    def __init__(self, b):
        self.tf, self.day, self.i0, self.i1, self.t0 = b.tf, b.day, b.i0, b.i1, b.t0
        self.ist0, self.ny0, self.b0, self.b1 = b.ist0, b.ny0, b.b0, b.b1
        self.o, self.h, self.l, self.c = ha_ohlc(b)
