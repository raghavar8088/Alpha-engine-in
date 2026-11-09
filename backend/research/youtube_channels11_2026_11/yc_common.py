"""Shared pieces of the 11-channel strategies: candle tests, signal stamping, per-bars caches and sessions.

Conventions (the YouTube study's): a strategy function is fn(m, B, p, cache) -> list of yt_engine.Signal; B maps a
timeframe in minutes to that market's Bars (bars never cross a trading day; daily markets use B[1], one bar a day);
signals use completed bars only and carry the signal bar's last row, so orders start on the next row. Swing pivots
of n bars are only used n bars after the pivot bar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import yc_ind as I
from yt_engine import Limits, Signal

SWING = Limits(99, False, False)     # one position at a time, no daily cap (multi-day books)

NIFTY_X = ("ist", 15 * 60 + 14)      # NSE intraday: out at 15:15
BTC_X = ("ist", 5 * 60 + 25)         # bitcoin: 23:55 UTC, the end of the UTC day
GOLD_X = ("ny", 16 * 60 + 55)        # gold and forex: the 17:00 New York session end
NAS_X = ("ny", 15 * 60 + 55)         # Nasdaq cash session
END_X = ("end", 0)                   # positions may run to the end of the data (overnight and daily books)


def rng(b, j): return float(b.h[j] - b.l[j])
def body(b, j): return float(abs(b.c[j] - b.o[j]))
def green(b, j): return bool(b.c[j] > b.o[j])
def red(b, j): return bool(b.c[j] < b.o[j])
def uw(b, j): return float(b.h[j] - max(b.o[j], b.c[j]))
def lw(b, j): return float(min(b.o[j], b.c[j]) - b.l[j])


def bull_engulf(b, j) -> bool:
    """A green candle whose body covers the previous red candle's body."""
    return j >= 1 and green(b, j) and red(b, j - 1) and b.o[j] <= b.c[j - 1] and b.c[j] >= b.o[j - 1]


def bear_engulf(b, j) -> bool:
    return j >= 1 and red(b, j) and green(b, j - 1) and b.o[j] >= b.c[j - 1] and b.c[j] <= b.o[j - 1]


def sig(b, j, side, stop, setup, **kw) -> Signal:
    return Signal(int(b.day[j]), int(b.i1[j]), int(side), float(stop), setup, **kw)


def same_day(b, j, k) -> bool:
    return bool(b.day[j] == b.day[k])


def weekday(m, d) -> int:
    """Monday 0 ... Sunday 6 for trading day d (by its date)."""
    return int((int(m.date[d].astype(np.int64)) + 3) % 7)


def prev_close(m, d) -> float:
    return float(m.c[m.d1[d - 1] - 1]) if d > 0 else float("nan")


def day_open(m, d) -> float:
    return float(m.o[m.d0[d]])


def first_bar(b, d) -> int:
    return int(b.b0[d])


def bars_of_day(b, d):
    return range(int(b.b0[d]), int(b.b1[d]))


def bar_from(b, d, minute: int, clock: str = "ist") -> int | None:
    """The first bar of day d starting at or after `minute` on the clock ('ist' or 'ny')."""
    clk = b.ist0 if clock == "ist" else b.ny0
    for j in bars_of_day(b, d):
        if clk[j] >= minute:
            return j
    return None


def last_bar_before(b, d, minute: int, clock: str = "ist") -> int | None:
    """The last bar of day d that starts before `minute`."""
    clk = b.ist0 if clock == "ist" else b.ny0
    out = None
    for j in bars_of_day(b, d):
        if clk[j] < minute:
            out = j
    return out


def in_window(b, j, lo: int, hi: int, clock: str = "ist") -> bool:
    clk = b.ist0[j] if clock == "ist" else b.ny0[j]
    return lo <= int(clk) < hi


class Ctx:
    """Indicators of one Bars object, computed once and kept: ATR(14) by default, EMAs, SMAs, RSI, average bodies,
    bar volumes and confirmed swing pivots."""

    def __init__(self, m, b):
        self.m, self.b = m, b
        self._d: dict = {}

    def _get(self, key, fn):
        if key not in self._d:
            self._d[key] = fn()
        return self._d[key]

    def atr(self, n=14):
        return self._get(("atr", n), lambda: I.atr(self.b, n))

    def atr_sma(self, n=14):
        """ATR as a simple average of true range (some Pine scripts)."""
        return self._get(("atr_sma", n), lambda: I.sma(I.true_range(self.b), n))

    def ema(self, n, src="c"):
        return self._get(("ema", n, src), lambda: I.ema(getattr(self.b, src), n))

    def sma(self, n, src="c"):
        return self._get(("sma", n, src), lambda: I.sma(getattr(self.b, src), n))

    def rsi(self, n=14):
        return self._get(("rsi", n), lambda: I.rsi(self.b.c, n))

    def body_avg(self, n=20):
        """Mean body of the n bars before each bar."""
        return self._get(("body_avg", n), lambda: I.mean_prev(np.abs(self.b.c - self.b.o), n))

    def range_avg(self, n=20):
        return self._get(("range_avg", n), lambda: I.mean_prev(self.b.h - self.b.l, n))

    def vol(self):
        """Volume of each bar (the sum of its rows)."""
        return self._get(("vol",), lambda: np.add.reduceat(np.asarray(self.m.vol, float), self.b.i0) if len(self.b.i0) else np.zeros(0))

    def vol_avg(self, n=20):
        return self._get(("vol_avg", n), lambda: I.mean_prev(self.vol(), n))

    def fractals(self, n=2):
        """Pivot flags of n bars each side, known n bars after the pivot."""
        return self._get(("fr", n), lambda: I.fractals(self.b, n))

    def pivots(self, n=2):
        """Per bar, the latest confirmed pivot high / low (value, index) and the one before it."""
        ph, pl = self.fractals(n)
        return self._get(("pv", n), lambda: I.pivots_known(self.b, ph, pl, n))

    def macd(self, a=12, b=26, s=9):
        return self._get(("macd", a, b, s), lambda: I.macd(self.b.c, a, b, s))

    def supertrend(self, n=10, mult=3.0):
        return self._get(("st", n, mult), lambda: I.supertrend(self.b, n, mult))

    def bollinger(self, n=20, k=2.0):
        return self._get(("bb", n, k), lambda: I.bollinger(self.b.c, n, k))


def utc_bars(m, tf: int):
    """tf-minute bars on the UTC grid that may span two trading days (gold's day rolls at 17:00 New York): for rules
    whose candles are drawn from 00:00 UTC whatever the session. Same layout as bb_markets.Bars; a bar's day is its
    first row's day."""
    import bb_markets as BM
    slot = (np.asarray(m.t, np.int64) // 60) // tf
    starts = np.flatnonzero(np.r_[True, slot[1:] != slot[:-1]])
    ends = np.r_[starts[1:], len(slot)] - 1
    o, c = m.o[starts], m.c[ends]
    h = np.maximum.reduceat(m.h, starts)
    l = np.minimum.reduceat(m.l, starts)
    t0 = (slot[starts] * tf * 60).astype(np.int64)
    day = m.day[starts]
    b0 = np.searchsorted(day, np.arange(m.n_days), "left")
    b1 = np.searchsorted(day, np.arange(m.n_days), "right")
    ist0, ny0 = BM._clocks(t0)
    return BM.Bars(tf, day, starts.astype(np.int64), ends.astype(np.int64), t0, o, h, l, c, ist0, ny0, b0, b1)


def ctx(m, B, tf, cache) -> Ctx:
    key = ("ctx", tf)
    if key not in cache:
        cache[key] = Ctx(m, B[tf])
    return cache[key]


def last_done(bh, row) -> int:
    """Index of the last higher-timeframe bar complete at minute row `row` (-1 if none)."""
    return int(np.searchsorted(bh.i1, row, "right")) - 1


def cross_up(x, y, j) -> bool:
    return j >= 1 and np.isfinite(x[j - 1]) and np.isfinite(y[j - 1]) and x[j - 1] <= y[j - 1] and x[j] > y[j]


def cross_dn(x, y, j) -> bool:
    return j >= 1 and np.isfinite(x[j - 1]) and np.isfinite(y[j - 1]) and x[j - 1] >= y[j - 1] and x[j] < y[j]


def flags_cross(x, y):
    """(cross up, cross down) flags per bar."""
    up = np.zeros(len(x), bool)
    dn = np.zeros(len(x), bool)
    ok = np.isfinite(x) & np.isfinite(y)
    up[1:] = ok[1:] & ok[:-1] & (x[:-1] <= y[:-1]) & (x[1:] > y[1:])
    dn[1:] = ok[1:] & ok[:-1] & (x[:-1] >= y[:-1]) & (x[1:] < y[1:])
    return up, dn


def nz(x, default=np.nan):
    return float(x) if np.isfinite(x) else default


def pick_target(side, entry_ref, stop, candidates, min_r, default_r):
    """The nearest candidate level beyond entry_ref at least min_r x risk away, else default_r x risk (None = skip
    when default_r is None)."""
    risk = abs(entry_ref - stop)
    if not risk > 0:
        return None
    good = [c for c in candidates if np.isfinite(c) and (c - entry_ref) * side >= min_r * risk]
    if good:
        return float(min(good, key=lambda c: abs(c - entry_ref)))
    return None if default_r is None else float(entry_ref + side * default_r * risk)


def swing_target(side, ref, stop, level, min_r, default_r, skip_if_close=False):
    """`level` as the target when it lies at least min_r x risk beyond ref; a nearer level gives default_r x risk (or
    None, meaning skip the trade, with skip_if_close); no level beyond ref gives default_r x risk."""
    risk = abs(ref - stop)
    if not risk > 0:
        return None
    if level is None or not np.isfinite(level) or (level - ref) * side <= 0:
        return float(ref + side * default_r * risk)
    if (level - ref) * side >= min_r * risk:
        return float(level)
    return None if skip_if_close else float(ref + side * default_r * risk)


# ── swings, gaps and order-flow shapes shared by several channels ────────────────────────

def pivot_lists(m, B, tf, cache, n=2):
    """(pivot-high bars, pivot-low bars) of n-bar fractals on B[tf], in bar order; a pivot q is known at bar q + n."""
    key = ("plist", tf, n)
    if key not in cache:
        ph, pl = ctx(m, B, tf, cache).fractals(n)
        cache[key] = (np.flatnonzero(ph), np.flatnonzero(pl))
    return cache[key]


def latest_pivot_beyond(vals, piv, j, n, side, ref, lookback=200):
    """The most recent pivot of `piv` (bar indices; values vals[q]) known by bar j whose value lies beyond ref in
    direction side (above for side +1), within `lookback` bars; None if there is none."""
    k = int(np.searchsorted(piv, j - n, "right"))
    for t in range(k - 1, -1, -1):
        q = int(piv[t])
        if q < j - lookback:
            break
        if (vals[q] - ref) * side > 0:
            return float(vals[q])
    return None


def nearest_pivot_beyond(vals, piv, j, n, side, ref, lookback=200):
    """The pivot known by bar j (within lookback bars) nearest to ref among those beyond it in direction side."""
    k = int(np.searchsorted(piv, j - n, "right"))
    lo = int(np.searchsorted(piv, j - lookback, "left"))
    best = None
    for t in range(lo, k):
        v = vals[int(piv[t])]
        if (v - ref) * side > 0 and (best is None or abs(v - ref) < abs(best - ref)):
            best = float(v)
    return best


def fvg_flags(m, B, tf, cache, mult=1.5):
    """Per bar j (the third candle): +1 when candles j-2..j leave a bullish fair value gap (b.h[j-2] .. b.l[j]) and the
    middle candle is green with a body at least mult x the mean body of the 20 candles before it; -1 for the bearish
    mirror (gap b.h[j] .. b.l[j-2]); 0 otherwise."""
    key = ("fvg", tf, mult)
    if key not in cache:
        b = B[tf]
        n = len(b.c)
        f = np.zeros(n, np.int8)
        if n >= 3:
            ba = ctx(m, B, tf, cache).body_avg(20)
            bod = np.abs(b.c - b.o)
            mba = ba[1:-1]
            big = np.isfinite(mba) & (bod[1:-1] >= mult * np.where(np.isfinite(mba), mba, np.inf))
            bull = big & (b.c[1:-1] > b.o[1:-1]) & (b.l[2:] > b.h[:-2])
            bear = big & (b.c[1:-1] < b.o[1:-1]) & (b.h[2:] < b.l[:-2])
            tail = f[2:]
            tail[bull] = 1
            tail[bear] = -1
        cache[key] = f
    return cache[key]


def fvg_gap(b, j, side):
    """(low edge, high edge) of the gap completed at bar j."""
    return (float(b.h[j - 2]), float(b.l[j])) if side > 0 else (float(b.h[j]), float(b.l[j - 2]))


def cisd_line(b, q, side, start):
    """The change-in-state-of-delivery line for a setup in direction `side`, from bars start .. q-1: the close of the
    last opposite candle before the latest two consecutive candles moving against `side` (for a long: the close of the
    last green candle before the latest pair of red candles). Returns (line, that candle's index) or None."""
    against = red if side > 0 else green
    opposite = green if side > 0 else red
    for r in range(q - 1, start, -1):
        if against(b, r) and against(b, r - 1):
            for g in range(r - 2, start - 1, -1):
                if opposite(b, g):
                    return float(b.c[g]), g
            return None
    return None


def clock_of(b, tz: str, cache, tf) -> np.ndarray:
    """Minutes since local midnight at each bar's start, in time zone tz (e.g. 'Europe/London'; DST-aware)."""
    key = ("clock", tz, tf)
    if key not in cache:
        ts = pd.to_datetime(np.asarray(b.t0, np.int64), unit="s", utc=True).tz_convert(tz)
        cache[key] = (ts.hour.to_numpy() * 60 + ts.minute.to_numpy()).astype(np.int16)
    return cache[key]


def weekday_of(b, tz: str, cache, tf) -> np.ndarray:
    """Local weekday (Monday 0 ... Sunday 6) at each bar's start, in time zone tz."""
    key = ("wday", tz, tf)
    if key not in cache:
        ts = pd.to_datetime(np.asarray(b.t0, np.int64), unit="s", utc=True).tz_convert(tz)
        cache[key] = ts.weekday.to_numpy().astype(np.int8)
    return cache[key]


def zone_break(vals, piv, j, n, tol, close_now, close_prev, side, lookback):
    """The outermost touch of a zone that the close at bar j has just crossed: a zone is at least two pivots (bar
    indices `piv`, values vals[q], confirmed by bar j: q <= j - n, pivot bar within the last `lookback` bars) within
    `tol` of each other; side +1 = a close from at or below to above the zone's highest touch (side -1 mirrored).
    None when no zone was crossed."""
    k = int(np.searchsorted(piv, j - n, "right"))
    P = [int(q) for q in piv[int(np.searchsorted(piv, j - lookback, "left")):k]]
    best = None
    for q in P:
        grp = [r for r in P if abs(vals[r] - vals[q]) <= tol]
        if len(grp) < 2:
            continue
        outer = max(vals[r] for r in grp) if side > 0 else min(vals[r] for r in grp)
        crossed = (close_prev <= outer < close_now) if side > 0 else (close_prev >= outer > close_now)
        if crossed:
            best = outer if best is None else (max(best, outer) if side > 0 else min(best, outer))
    return best


def bias_zones(m, B, tf, cache, n=2):
    """Smart-money bias on B[tf]: per bar, as of its close, (bias, zone low, zone high, zone id). A close above the
    latest confirmed n-bar fractal high (the first close above that pivot) makes the bias bullish and its point of
    interest the last red candle before the breaking candle (within 24 bars); a close below the latest fractal low makes
    it bearish with the last green candle before it. The zone id is the breaking bar's index (-1: no zone yet)."""
    key = ("bias", tf, n)
    if key in cache:
        return cache[key]
    b = B[tf]
    hv, hi, lv, li, _, _ = ctx(m, B, tf, cache).pivots(n)
    N = len(b.c)
    bias = np.zeros(N, np.int8)
    zlo = np.full(N, np.nan)
    zhi = np.full(N, np.nan)
    zid = np.full(N, -1, np.int64)
    cur = (0, np.nan, np.nan, -1)
    used_h = used_l = -1
    for x in range(1, N):
        if hi[x] >= 0 and hi[x] != used_h and b.c[x] > hv[x]:
            used_h = int(hi[x])
            base = next((q for q in range(x - 1, max(x - 25, -1), -1) if b.c[q] < b.o[q]), None)
            cur = (1, float(b.l[base]), float(b.h[base]), x) if base is not None else (1, np.nan, np.nan, x)
        elif li[x] >= 0 and li[x] != used_l and b.c[x] < lv[x]:
            used_l = int(li[x])
            base = next((q for q in range(x - 1, max(x - 25, -1), -1) if b.c[q] > b.o[q]), None)
            cur = (-1, float(b.l[base]), float(b.h[base]), x) if base is not None else (-1, np.nan, np.nan, x)
        bias[x], zlo[x], zhi[x], zid[x] = cur
    cache[key] = (bias, zlo, zhi, zid)
    return cache[key]


def htf_sweeps(m, B, cache, tf_lvl=240, tf=5, n=2, max_age_days=30):
    """Wick sweeps of confirmed fractal levels of B[tf_lvl], seen on B[tf] candles: a list of (bar j, side, level).
    side +1: the candle trades below a fractal low and closes back above it; -1: above a fractal high and back below.
    A level counts from the first candle that starts after it is confirmed, for max_age_days after its pivot; the first
    candle that trades through it uses it up (a sweep when it closes back, a break when it does not)."""
    key = ("sweeps", tf_lvl, tf, n, max_age_days)
    if key in cache:
        return cache[key]
    b, bh = B[tf], B[tf_lvl]
    ph, pl = ctx(m, B, tf_lvl, cache).fractals(n)
    lv_h = sorted((int(bh.i1[q + n]), float(bh.h[q]), int(bh.t0[q])) for q in np.flatnonzero(ph))
    lv_l = sorted((int(bh.i1[q + n]), float(bh.l[q]), int(bh.t0[q])) for q in np.flatnonzero(pl))
    act_h: list = []
    act_l: list = []
    ih = il = 0
    out = []
    for j in range(len(b.c)):
        start = int(b.i0[j])
        while ih < len(lv_h) and lv_h[ih][0] < start:
            act_h.append(lv_h[ih][1:])
            ih += 1
        while il < len(lv_l) and lv_l[il][0] < start:
            act_l.append(lv_l[il][1:])
            il += 1
        oldest = int(b.t0[j]) - max_age_days * 86400
        swept, keep = None, []
        for v, t0 in act_h:
            if t0 < oldest:
                continue
            if b.h[j] > v:
                if b.c[j] < v:
                    swept = v if swept is None else max(swept, v)
                continue
            keep.append((v, t0))
        act_h = keep
        if swept is not None:
            out.append((j, -1, swept))
        swept, keep = None, []
        for v, t0 in act_l:
            if t0 < oldest:
                continue
            if b.l[j] < v:
                if b.c[j] > v:
                    swept = v if swept is None else min(swept, v)
                continue
            keep.append((v, t0))
        act_l = keep
        if swept is not None:
            out.append((j, 1, swept))
    cache[key] = out
    return out
