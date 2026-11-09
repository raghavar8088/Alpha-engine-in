"""Shared pieces of the 20-channel strategies (youtube_channels20_2026_11): bars anchored to the NSE session, the
indicators these videos use that the earlier studies did not have (Fisher Transform, Squeeze Momentum, Stochastic
Momentum Index, Schaff Trend Cycle, UT Bot, linear-regression candles, DEMA, Chaikin Money Flow), and small helpers.

Conventions are the 11-channel study's (yc_common): a strategy is fn(m, B, p, cache) -> signals built from completed
bars only; a signal carries its bar's last row and orders start on the next row; a swing pivot of n bars is used only
n bars after the pivot bar. Every indicator value at bar i uses bars <= i only.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
for _p in (HERE, RESEARCH / "youtube_channels11_2026_11", RESEARCH / "youtube_top20_2026_11",
           RESEARCH / "booming_bulls_2026_11", RESEARCH / "crypto_playlist_2026_11"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402

import yc_ind as I  # noqa: E402
from yc_common import Ctx  # noqa: E402

NSE_OPEN = 9 * 60 + 15


def sorted_out(out):
    out.sort(key=lambda s: (s.k, s.side, s.setup))
    return out


# ── bars anchored to the NSE session (09:15 IST) for any timeframe ────────────────────────────────

def anchored_bars(m, tf: int, cache: dict, last_slot: int | None = None):
    """tf-minute bars of an IST-session market on a grid that starts at 09:15 IST (bb_markets.bars anchors only NIFTY and
    BANKNIFTY there; the stock pool's rows are on the UTC grid). last_slot merges every later slot into that one (e.g.
    the 15:15-15:30 quarter into the 14:15 hour). Kept in cache."""
    key = ("anch", tf, last_slot)
    if key in cache:
        return cache[key]
    import bb_markets as BM
    ist = np.asarray(m.ist, np.int64)
    slot = (ist - NSE_OPEN) // tf
    if last_slot is not None:
        slot = np.minimum(slot, last_slot)
    k = m.day.astype(np.int64) * 100_000 + (slot - slot.min() if len(slot) else slot)
    starts = np.flatnonzero(np.r_[True, k[1:] != k[:-1]]) if len(k) else np.zeros(0, np.int64)
    ends = np.r_[starts[1:], len(k)] - 1 if len(k) else np.zeros(0, np.int64)
    o, c = m.o[starts], m.c[ends]
    h = np.maximum.reduceat(m.h, starts) if len(k) else np.zeros(0)
    l = np.minimum.reduceat(m.l, starts) if len(k) else np.zeros(0)
    t0 = (m.t[starts] - (ist[starts] - (NSE_OPEN + slot[starts] * tf)) * 60).astype(np.int64)
    day = m.day[starts]
    b0 = np.searchsorted(day, np.arange(m.n_days), "left")
    b1 = np.searchsorted(day, np.arange(m.n_days), "right")
    ist0, ny0 = BM._clocks(t0)
    bars = BM.Bars(tf, day, starts.astype(np.int64), ends.astype(np.int64), t0, o, h, l, c, ist0, ny0, b0, b1)
    cache[key] = bars
    return bars


def actx(m, bars, cache: dict, name) -> Ctx:
    """A yc_common.Ctx for bars that are not in B (anchored, weekly, Heikin Ashi ...), kept under `name`."""
    key = ("actx", name)
    if key not in cache:
        cache[key] = Ctx(m, bars)
    return cache[key]


def weekly_bars(m, cache: dict):
    """Monday-Friday weeks of a daily market (one row a day) in the Bars layout; a week's bar is complete at its last
    trading day's row. day = the week's last trading day index."""
    key = ("weekly",)
    if key in cache:
        return cache[key]
    import bb_markets as BM
    d = m.date.astype("datetime64[D]").astype(np.int64)
    wk = (d + 3) // 7                      # 1970-01-05 was a Monday: weeks start on Mondays
    starts = np.flatnonzero(np.r_[True, wk[1:] != wk[:-1]]) if len(wk) else np.zeros(0, np.int64)
    ends = np.r_[starts[1:], len(wk)] - 1 if len(wk) else np.zeros(0, np.int64)
    o, c = m.o[starts], m.c[ends]
    h = np.maximum.reduceat(m.h, starts) if len(wk) else np.zeros(0)
    l = np.minimum.reduceat(m.l, starts) if len(wk) else np.zeros(0)
    t0 = np.asarray(m.t[starts], np.int64)
    day = np.asarray(m.day[ends])
    b0 = np.searchsorted(day, np.arange(m.n_days), "left")
    b1 = np.searchsorted(day, np.arange(m.n_days), "right")
    ist0, ny0 = BM._clocks(t0)
    bars = BM.Bars(7 * 1440, day, np.asarray(starts, np.int64), np.asarray(ends, np.int64), t0, o, h, l, c, ist0, ny0, b0, b1)
    cache[key] = bars
    return bars


# ── indicators ───────────────────────────────────────────────────────────────────────────────

def linreg(x: np.ndarray, n: int) -> np.ndarray:
    """Pine's linreg(x, n, 0): the least-squares line through the last n values, evaluated at the latest one."""
    x = np.asarray(x, float)
    N = len(x)
    out = np.full(N, np.nan)
    if N < n or n < 2:
        return out
    t = np.arange(n, dtype=float)
    tm = t.mean()
    den = ((t - tm) ** 2).sum()
    w = (t - tm) / den
    from numpy.lib.stride_tricks import sliding_window_view as sw
    win = sw(x, n)
    slope = win @ w
    mean = win.mean(axis=1)
    out[n - 1:] = mean + slope * (n - 1 - tm)
    return out


def fisher(b, n: int = 9):
    """TradingView's Fisher Transform (length n) on hl2: (fisher, trigger = the previous fisher)."""
    hl2 = (b.h + b.l) / 2
    hi, lo = I.highest(hl2, n), I.lowest(hl2, n)
    N = len(hl2)
    val = np.zeros(N)
    fish = np.full(N, np.nan)
    pv = pf = 0.0
    for i in range(N):
        if not (np.isfinite(hi[i]) and np.isfinite(lo[i])):
            continue
        rngv = hi[i] - lo[i]
        v = 0.66 * (((hl2[i] - lo[i]) / rngv - 0.5) if rngv > 0 else 0.0) + 0.67 * pv
        v = 0.999 if v > 0.99 else (-0.999 if v < -0.99 else v)
        f = 0.5 * np.log((1 + v) / (1 - v)) + 0.5 * pf
        val[i], fish[i] = v, f
        pv, pf = v, f
    trig = np.r_[np.nan, fish[:-1]]
    return fish, trig


def squeeze_momentum(b, n_kc: int = 20) -> np.ndarray:
    """LazyBear's Squeeze Momentum value: linreg(close - avg(avg(highest(high), lowest(low)), sma(close)), n_kc)."""
    hh, ll = I.highest(b.h, n_kc), I.lowest(b.l, n_kc)
    mid = ((hh + ll) / 2 + I.sma(b.c, n_kc)) / 2
    return linreg(b.c - mid, n_kc)


def smi(b, k: int = 10, d: int = 3, e: int = 3):
    """TradingView's Stochastic Momentum Index: (smi, its EMA signal)."""
    hh, ll = I.highest(b.h, k), I.lowest(b.l, k)
    rel = b.c - (hh + ll) / 2
    span = hh - ll
    first = int(np.argmax(np.isfinite(hh))) if np.isfinite(hh).any() else len(hh)
    out = np.full(len(b.c), np.nan)
    sg = np.full(len(b.c), np.nan)
    if first >= len(hh):
        return out, sg
    ee = lambda x: I.ema(I.ema(x, d), d)  # noqa: E731
    num, den = ee(rel[first:]), ee(span[first:])
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(den != 0, 200 * num / den, 0.0)
    out[first:] = s
    sg[first:] = I.ema(s, e)
    return out, sg


def stc(c: np.ndarray, cycle: int = 10, fast: int = 23, slow: int = 50, factor: float = 0.5) -> np.ndarray:
    """Schaff Trend Cycle (the "STC Indicator - A Better MACD" script): two stochastic passes of MACD, each smoothed."""
    c = np.asarray(c, float)
    mac = I.ema(c, fast) - I.ema(c, slow)
    N = len(c)
    out = np.full(N, np.nan)
    f1 = f2 = pf = pff = np.nan
    pfs = np.full(N, np.nan)
    for i in range(N):
        a = max(0, i - cycle + 1)
        lo, hi = mac[a:i + 1].min(), mac[a:i + 1].max()
        f1 = ((mac[i] - lo) / (hi - lo) * 100) if hi > lo else (f1 if np.isfinite(f1) else 0.0)
        pf = f1 if not np.isfinite(pf) else pf + factor * (f1 - pf)
        pfs[i] = pf
        lo2, hi2 = pfs[a:i + 1].min(), pfs[a:i + 1].max()
        f2 = ((pf - lo2) / (hi2 - lo2) * 100) if hi2 > lo2 else (f2 if np.isfinite(f2) else 0.0)
        pff = f2 if not np.isfinite(pff) else pff + factor * (f2 - pff)
        if i >= slow:
            out[i] = pff
    return out


def ut_bot(b, key: float, n: int):
    """QuantNomad's UT Bot Alerts: (trailing stop, buy flags, sell flags) with ATR(n) (Wilder) x key."""
    a = I.atr(b, n)
    src = np.asarray(b.c, float)
    N = len(src)
    ts = np.full(N, np.nan)
    buy = np.zeros(N, bool)
    sell = np.zeros(N, bool)
    prev = 0.0
    for i in range(N):
        if not np.isfinite(a[i]):
            continue
        loss = key * a[i]
        p1 = src[i - 1] if i else src[i]
        if src[i] > prev and p1 > prev:
            cur = max(prev, src[i] - loss)
        elif src[i] < prev and p1 < prev:
            cur = min(prev, src[i] + loss)
        elif src[i] > prev:
            cur = src[i] - loss
        else:
            cur = src[i] + loss
        if i and np.isfinite(ts[i - 1]):
            buy[i] = src[i] > cur and p1 <= ts[i - 1]
            sell[i] = src[i] < cur and p1 >= ts[i - 1]
        ts[i] = cur
        prev = cur
    return ts, buy, sell


def lr_candles(b, n: int = 11, smooth: int = 7):
    """Linear-regression candles: (open, close, signal line = SMA of the regression close)."""
    lo_, lc = linreg(b.o, n), linreg(b.c, n)
    sg = np.full(len(lc), np.nan)
    ok = np.isfinite(lc)
    if ok.any():
        f = int(np.argmax(ok))
        sg[f:] = I.sma(lc[f:], smooth)
    return lo_, lc, sg


def supertrend_bands(b, n: int = 10, mult: float = 3.0):
    """Supertrend's ratcheted final bands (lower, upper) with ATR n x mult, both kept every bar (TradingView logic)."""
    a = I.atr(b, n)
    hl2 = (b.h + b.l) / 2
    up, dn = hl2 - mult * a, hl2 + mult * a
    N = len(hl2)
    fu, fd = np.full(N, np.nan), np.full(N, np.nan)
    for i in range(N):
        if not np.isfinite(a[i]):
            continue
        if i and np.isfinite(fu[i - 1]):
            fu[i] = max(up[i], fu[i - 1]) if b.c[i - 1] > fu[i - 1] else up[i]
            fd[i] = min(dn[i], fd[i - 1]) if b.c[i - 1] < fd[i - 1] else dn[i]
        else:
            fu[i], fd[i] = up[i], dn[i]
    return fu, fd


def dema(c: np.ndarray, n: int) -> np.ndarray:
    e = I.ema(np.asarray(c, float), n)
    return 2 * e - I.ema(e, n)


def cmf(b, vol: np.ndarray, n: int = 20) -> np.ndarray:
    rng_ = b.h - b.l
    with np.errstate(invalid="ignore", divide="ignore"):
        mfm = np.where(rng_ > 0, ((b.c - b.l) - (b.h - b.c)) / rng_, 0.0)
    mfv = mfm * vol
    cs = lambda x: np.cumsum(np.r_[0.0, x])  # noqa: E731
    a, v = cs(mfv), cs(vol)
    out = np.full(len(vol), np.nan)
    den = v[n:] - v[:-n]
    with np.errstate(invalid="ignore", divide="ignore"):
        out[n - 1:] = np.where(den > 0, (a[n:] - a[:-n]) / den, 0.0)
    return out


def ha_bars(b):
    """Heikin Ashi candles of b in the Bars layout."""
    return I.HABars(b)


# ── small helpers ────────────────────────────────────────────────────────────────────────────

def prev_day_hlc(m, b, d):
    """The previous trading day's (high, low, close) from the market's rows (None if day d has no previous day)."""
    if d < 1 or not m.prev_ok[d]:
        return None
    a, z = int(m.d0[d - 1]), int(m.d1[d - 1])
    if z <= a:
        return None
    return float(m.h[a:z].max()), float(m.l[a:z].min()), float(m.c[z - 1])


def day_rows(m, d):
    return int(m.d0[d]), int(m.d1[d])


def day_change_at(m, d, row):
    """Close of `row` over the previous day's close, less one (nan if unknown)."""
    if d < 1 or not m.prev_ok[d]:
        return np.nan
    pc = float(m.c[m.d1[d - 1] - 1])
    return float(m.c[row]) / pc - 1 if pc > 0 else np.nan


def swings_up(hv, lv, phv, plv, j) -> int:
    """+1 when the last two confirmed swing highs and lows both rise, -1 when both fall, else 0."""
    if not all(np.isfinite(x) for x in (hv[j], lv[j], phv[j], plv[j])):
        return 0
    if hv[j] > phv[j] and lv[j] > plv[j]:
        return 1
    if hv[j] < phv[j] and lv[j] < plv[j]:
        return -1
    return 0
