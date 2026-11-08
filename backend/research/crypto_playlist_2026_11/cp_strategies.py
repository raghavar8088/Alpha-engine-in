"""The strategies of Booming Bulls' "Crypto Trading" playlist (PLHqOiFE9RQj8), as exact rules. specs/RULES.md is
the readable form; this file is the exact form. Run by the YouTube study's engine (../youtube_top20_2026_11/yt_engine.py):
signals use completed bars only and are stamped with the signal bar's last minute row; orders start on the next row.

Defaults from the playlist's risk videos (qPBdLsiEa3s, Z0T-OWvruGo, lYr7pBtCORs), used by every strategy unless its
own video says otherwise: target 2R; stop moved to breakeven once price has covered half the way to the target;
at most 2 trades a day, one at a time, none after a stop-loss that day.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "youtube_top20_2026_11"))
sys.path.insert(0, str(HERE.parent / "booming_bulls_2026_11"))

import yt_ind as I  # noqa: E402
from yt_engine import Exits, Limits, Signal  # noqa: E402
from yt_markets import bars as make_bars  # noqa: E402

LIMITS = Limits(2, stop_after_target=False, second_only_after_stop=False, max_stops_per_day=1)
EXITS = {"target_r": 2.0, "be_at_frac": 0.5}
GOLD_X = ("ny", 16 * 60 + 55)       # gold: the 17:00 New York session end
BTC_X = ("ist", 5 * 60 + 25)        # bitcoin: 23:55 UTC, the end of the UTC day
FX_X = ("ny", 16 * 60 + 55)


# ── shared pieces ─────────────────────────────────────────────────────────────────────

def rng(b, j):
    return b.h[j] - b.l[j]


def body(b, j):
    return abs(b.c[j] - b.o[j])


def green(b, j):
    return b.c[j] > b.o[j]


def red(b, j):
    return b.c[j] < b.o[j]


def upper_wick(b, j):
    return b.h[j] - max(b.o[j], b.c[j])


def lower_wick(b, j):
    return min(b.o[j], b.c[j]) - b.l[j]


def pin_bull(b, j):
    """LPR / pin bar: the lower wick is at least half the candle and the close is in the upper half."""
    r = rng(b, j)
    return r > 0 and lower_wick(b, j) >= 0.5 * r and b.c[j] >= b.l[j] + 0.5 * r


def pin_bear(b, j):
    r = rng(b, j)
    return r > 0 and upper_wick(b, j) >= 0.5 * r and b.c[j] <= b.h[j] - 0.5 * r


class Ctx:
    """Per-bars helpers computed once: ATR(14), mean range of the previous 20 bars, fractal pivots of 2."""

    def __init__(self, b):
        self.b = b
        self.atr = I.atr(b, 14)
        r = b.h - b.l
        cs = np.cumsum(np.r_[0.0, r])
        self.mr20 = np.full(len(r), np.nan)
        self.mr20[20:] = (cs[20:-1] - cs[:-21]) / 20 if len(r) > 21 else np.nan
        self.ph, self.pl = I.fractals(b, 2)

    def power(self, j, up: bool):
        """Power candle: body at least 70% of the range and range at least the mean of the previous 20 bars."""
        b = self.b
        r = rng(b, j)
        ok = r > 0 and body(b, j) >= 0.7 * r and np.isfinite(self.mr20[j]) and r >= self.mr20[j]
        return ok and (green(b, j) if up else red(b, j))


def ctx(B, tf, cache):
    key = ("ctx", tf)
    if key not in cache:
        cache[key] = Ctx(B[tf])
    return cache[key]


def last_done(bh, row):
    """Index of the last higher-timeframe bar complete at minute row `row` (-1 if none)."""
    return int(np.searchsorted(bh.i1, row, "right")) - 1


def structure(ch: Ctx):
    """Per bar of a timeframe, from pivots confirmed by then (a pivot of 2 is known 2 bars later):
    trend +1 (higher high and higher low), -1 (lower high and lower low), 0; last swing high / low values."""
    b = ch.b
    n = len(b.h)
    trend = np.zeros(n, np.int8)
    sh = np.full(n, np.nan)
    sl = np.full(n, np.nan)
    highs, lows = [], []
    for j in range(n):
        q = j - 2
        if q >= 0:
            if ch.ph[q]:
                highs.append(b.h[q])
            if ch.pl[q]:
                lows.append(b.l[q])
        if highs:
            sh[j] = highs[-1]
        if lows:
            sl[j] = lows[-1]
        if len(highs) >= 2 and len(lows) >= 2:
            if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
                trend[j] = 1
            elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
                trend[j] = -1
    return trend, sh, sl


def struct_cached(B, tf, cache):
    key = ("struct", tf)
    if key not in cache:
        cache[key] = structure(ctx(B, tf, cache))
    return cache[key]


def same_day(b, j, k):
    return b.day[j] == b.day[k]


def sig(b, j, side, stop, setup, **kw):
    return Signal(int(b.day[j]), int(b.i1[j]), side, float(stop), setup, **kw)


def buffer(b, j, frac=0.0005):
    return frac * b.c[j]


# ── CP-01 trend pullback, "the 5th point" (qPBdLsiEa3s, mb0AeY9YyPg) ─────────────────

def cp01(m, B, p, cache):
    b = B[p["tf"]]
    bh = B[p["htf"]]
    trend, sh, sl = struct_cached(B, p["htf"], cache)
    out = []
    for j in range(1, len(b.c)):
        if not same_day(b, j, j - 1):
            continue
        J = last_done(bh, b.i1[j])
        if J < 0 or not (np.isfinite(sh[J]) and np.isfinite(sl[J])):
            continue
        mid = (sh[J] + sl[J]) / 2
        if trend[J] > 0 and pin_bull(b, j) and b.l[j] < b.l[j - 1] and sl[J] < b.l[j] <= mid:
            out.append(sig(b, j, 1, b.l[j] - buffer(b, j), "TREND_PULLBACK"))
        elif trend[J] < 0 and pin_bear(b, j) and b.h[j] > b.h[j - 1] and mid <= b.h[j] < sh[J]:
            out.append(sig(b, j, -1, b.h[j] + buffer(b, j), "TREND_PULLBACK"))
    return out


# ── CP-02 power-candle breakout of the last swing, in the trend ──────────────────────

def cp02(m, B, p, cache):
    b = B[p["tf"]]
    bh = B[p["htf"]]
    c = ctx(B, p["tf"], cache)
    trend, sh, sl = struct_cached(B, p["htf"], cache)
    out = []
    for j in range(1, len(b.c)):
        if not same_day(b, j, j - 1):
            continue
        J = last_done(bh, b.i1[j])
        if J < 0:
            continue
        if trend[J] > 0 and np.isfinite(sh[J]) and b.c[j - 1] <= sh[J] < b.c[j] and c.power(j, True):
            out.append(sig(b, j, 1, b.l[j] - buffer(b, j), "POWER_BREAKOUT"))
        elif trend[J] < 0 and np.isfinite(sl[J]) and b.c[j - 1] >= sl[J] > b.c[j] and c.power(j, False):
            out.append(sig(b, j, -1, b.h[j] + buffer(b, j), "POWER_BREAKOUT"))
    return out


# ── CP-03 range ping-pong, and the range breakout ─────────────────────────────────────

def cp03(m, B, p, cache):
    b = B[p["tf"]]
    bh = B[p["htf"]]
    c = ctx(B, p["tf"], cache)
    chh = ctx(B, p["htf"], cache)
    N = 20
    nh = len(bh.c)
    box = [None] * nh
    for J in range(N - 1, nh):
        H, L = bh.h[J - N + 1:J + 1].max(), bh.l[J - N + 1:J + 1].min()
        w = H - L
        if not np.isfinite(chh.atr[J]) or w <= 0 or w > 4 * chh.atr[J]:
            continue
        top = (bh.h[J - N + 1:J + 1] >= H - 0.1 * w).sum()
        bot = (bh.l[J - N + 1:J + 1] <= L + 0.1 * w).sum()
        if top >= 3 and bot >= 3:
            box[J] = (H, L, w)
    out = []
    for j in range(1, len(b.c)):
        if not same_day(b, j, j - 1):
            continue
        J = last_done(bh, b.i1[j])
        if J < 0 or box[J] is None:
            continue
        H, L, w = box[J]
        if b.c[j - 1] <= H < b.c[j] and c.power(j, True):
            out.append(sig(b, j, 1, b.l[j] - buffer(b, j), "RANGE_BREAKOUT"))
        elif b.c[j - 1] >= L > b.c[j] and c.power(j, False):
            out.append(sig(b, j, -1, b.h[j] + buffer(b, j), "RANGE_BREAKOUT"))
        elif pin_bear(b, j) and b.h[j] >= H - 0.1 * w and b.c[j] < H:
            stop = max(b.h[j], H) + buffer(b, j)
            tgt = L + 0.1 * w
            if (b.c[j] - tgt) >= 2 * (stop - b.c[j]):
                out.append(sig(b, j, -1, stop, "RANGE_FADE", target_px=float(tgt)))
        elif pin_bull(b, j) and b.l[j] <= L + 0.1 * w and b.c[j] > L:
            stop = min(b.l[j], L) - buffer(b, j)
            tgt = H - 0.1 * w
            if (tgt - b.c[j]) >= 2 * (b.c[j] - stop):
                out.append(sig(b, j, 1, stop, "RANGE_FADE", target_px=float(tgt)))
    return out


# ── CP-04 trend-line rejection (qPBdLsiEa3s) ──────────────────────────────────────────

def cp04(m, B, p, cache):
    b = B[p["tf"]]
    bh = B[p["htf"]]
    chh = ctx(B, p["htf"], cache)
    nh = len(bh.c)
    # per higher-timeframe bar: the last two confirmed swing highs and lows (index, value)
    hs, ls = [], []
    lines = [None] * nh
    for J in range(nh):
        q = J - 2
        if q >= 0:
            if chh.ph[q]:
                hs.append((q, bh.h[q]))
            if chh.pl[q]:
                ls.append((q, bh.l[q]))
        down = hs[-2:] if len(hs) >= 2 and hs[-1][1] < hs[-2][1] else None
        up = ls[-2:] if len(ls) >= 2 and ls[-1][1] > ls[-2][1] else None
        lines[J] = (down, up)
    t_h = bh.t0.astype(float)

    def value(pair, t):
        (q1, v1), (q2, v2) = pair
        return v1 + (v2 - v1) * (t - t_h[q1]) / (t_h[q2] - t_h[q1])

    out = []
    for j in range(1, len(b.c)):
        if not same_day(b, j, j - 1):
            continue
        J = last_done(bh, b.i1[j])
        if J < 0:
            continue
        down, up = lines[J]
        t = float(b.t0[j])
        if down is not None and t > t_h[down[1][0]]:
            v = value(down, t)
            vp = value(down, float(b.t0[j - 1]))
            if b.c[j - 1] < vp and b.h[j] >= v - buffer(b, j, 0.001) and b.c[j] < v and red(b, j) and bh.c[J] < value(down, t_h[J]):
                out.append(sig(b, j, -1, b.h[j] + buffer(b, j, 0.001), "TRENDLINE_REJECT"))
                continue
        if up is not None and t > t_h[up[1][0]]:
            v = value(up, t)
            vp = value(up, float(b.t0[j - 1]))
            if b.c[j - 1] > vp and b.l[j] <= v + buffer(b, j, 0.001) and b.c[j] > v and green(b, j) and bh.c[J] > value(up, t_h[J]):
                out.append(sig(b, j, 1, b.l[j] - buffer(b, j, 0.001), "TRENDLINE_REJECT"))
    return out


# ── CP-05 turning-point zones (mb0AeY9YyPg, his core method) ─────────────────────────

def cp05(m, B, p, cache):
    b = B[p["tf"]]
    bh = B[p["htf"]]
    c = ctx(B, p["tf"], cache)
    trend, _, _ = struct_cached(B, p["htf"], cache)
    n = len(b.c)
    zones = []          # [side, lo, hi, active_from_j, used]
    hist_h, hist_l = [], []
    out = []
    for j in range(n):
        q = j - 2
        if q >= 0:
            if c.ph[q]:
                z = (max(b.o[q], b.c[q]), b.h[q], q)
                ov = [x for x in hist_h if x[2] >= q - 300 and not (x[1] < z[0] or z[1] < x[0])]
                if len(ov) >= 2:
                    grp = ov[-2:] + [z]
                    zones.append([-1, min(x[0] for x in grp), max(x[1] for x in grp), j, False])
                hist_h.append(z)
            if c.pl[q]:
                z = (b.l[q], min(b.o[q], b.c[q]), q)
                ov = [x for x in hist_l if x[2] >= q - 300 and not (x[1] < z[0] or z[1] < x[0])]
                if len(ov) >= 2:
                    grp = ov[-2:] + [z]
                    zones.append([1, min(x[0] for x in grp), max(x[1] for x in grp), j, False])
                hist_l.append(z)
        if j == 0 or not np.isfinite(c.atr[j]):
            continue
        J = last_done(bh, b.i1[j])
        bias = trend[J] if J >= 0 else 0
        for Z in zones:
            side, lo, hi, j0, used = Z
            if used or j <= j0:
                continue
            if side < 0:
                if b.c[j] > hi:
                    Z[4] = True
                    continue
                if b.h[j] >= lo and pin_bear(b, j) and b.c[j] < lo and bias <= 0:
                    out.append(sig(b, j, -1, hi + 0.25 * c.atr[j], "TP_ZONE"))
                    Z[4] = True
            else:
                if b.c[j] < lo:
                    Z[4] = True
                    continue
                if b.l[j] <= hi and pin_bull(b, j) and b.c[j] > hi and bias >= 0:
                    out.append(sig(b, j, 1, lo - 0.25 * c.atr[j], "TP_ZONE"))
                    Z[4] = True
        zones = [Z for Z in zones if not Z[4] and j - Z[3] < 600]
    return out


# ── CP-06 triple top / triple bottom ──────────────────────────────────────────────────

def cp06(m, B, p, cache):
    b = B[p["tf"]]
    c = ctx(B, p["tf"], cache)
    hs, ls = [], []
    out = []
    for j in range(2, len(b.c)):
        q = j - 2
        a = c.atr[j]
        if not np.isfinite(a):
            continue
        if c.ph[q]:
            hs.append(q)
            if len(hs) >= 3:
                q1, q2, q3 = hs[-3:]
                vals = b.h[[q1, q2, q3]]
                if q2 - q1 >= 3 and q3 - q2 >= 3 and q3 - q1 <= 150 and vals.max() - vals.min() <= 0.25 * a:
                    if b.c[j] >= vals.max() - 1.5 * a:
                        out.append(sig(b, j, -1, vals.max() + 0.1 * a, "TRIPLE_TOP"))
        if c.pl[q]:
            ls.append(q)
            if len(ls) >= 3:
                q1, q2, q3 = ls[-3:]
                vals = b.l[[q1, q2, q3]]
                if q2 - q1 >= 3 and q3 - q2 >= 3 and q3 - q1 <= 150 and vals.max() - vals.min() <= 0.25 * a:
                    if b.c[j] <= vals.min() + 1.5 * a:
                        out.append(sig(b, j, 1, vals.min() - 0.1 * a, "TRIPLE_BOTTOM"))
    return out


# ── CP-07 head and shoulders / inverted ───────────────────────────────────────────────

def cp07(m, B, p, cache):
    b = B[p["tf"]]
    c = ctx(B, p["tf"], cache)
    hs, ls = [], []
    pend = []       # [side, neckline, stop, expire_j]
    out = []
    for j in range(2, len(b.c)):
        q = j - 2
        a = c.atr[j]
        if not np.isfinite(a):
            continue
        if c.ph[q]:
            hs.append(q)
            if len(hs) >= 3:
                q1, q2, q3 = hs[-3:]
                h1, h2, h3 = b.h[q1], b.h[q2], b.h[q3]
                if h2 - max(h1, h3) >= 0.5 * a and abs(h1 - h3) <= 0.5 * a and q3 - q1 <= 200:
                    neck = min(b.l[q1:q2 + 1].min(), b.l[q2:q3 + 1].min())
                    pend.append([-1, neck, h3 + 0.1 * a, j + 24])
        if c.pl[q]:
            ls.append(q)
            if len(ls) >= 3:
                q1, q2, q3 = ls[-3:]
                l1, l2, l3 = b.l[q1], b.l[q2], b.l[q3]
                if min(l1, l3) - l2 >= 0.5 * a and abs(l1 - l3) <= 0.5 * a and q3 - q1 <= 200:
                    neck = max(b.h[q1:q2 + 1].max(), b.h[q2:q3 + 1].max())
                    pend.append([1, neck, l3 - 0.1 * a, j + 24])
        keep = []
        for P in pend:
            side, neck, stop, exp = P
            if j > exp:
                continue
            if (side < 0 and b.c[j] < neck) or (side > 0 and b.c[j] > neck):
                if (b.c[j] - stop) * side > 0:
                    out.append(sig(b, j, side, stop, "HEAD_SHOULDERS"))
                continue
            keep.append(P)
        pend = keep
    return out


# ── CP-08 flag and pole ───────────────────────────────────────────────────────────────

def cp08(m, B, p, cache):
    b = B[p["tf"]]
    c = ctx(B, p["tf"], cache)
    out = []
    st = None       # [side, pole_size, pole_end, flag_hi, flag_lo, pole_extreme]
    for j in range(7, len(b.c)):
        a = c.atr[j]
        if not np.isfinite(a):
            continue
        if st is not None:
            side, size, pe, fh, fl, ext = st
            if j - pe > 15 or not same_day(b, j, pe):
                st = None
            else:
                if j - pe >= 5 and ((side > 0 and b.c[j] > fh) or (side < 0 and b.c[j] < fl)):
                    stop = (fl - 0.1 * a) if side > 0 else (fh + 0.1 * a)
                    out.append(sig(b, j, side, stop, "FLAG_POLE"))
                    st = None
                    continue
                fh, fl = max(fh, b.h[j]), min(fl, b.l[j])
                retr = (ext - fl) if side > 0 else (fh - ext)
                if fh - fl > 0.5 * size or retr > 0.5 * size:
                    st = None
                else:
                    st = [side, size, pe, fh, fl, ext]
                    continue
        move = b.c[j] - b.c[j - 6]
        if same_day(b, j, j - 6) and abs(move) >= 2.5 * a:
            side = 1 if move > 0 else -1
            st = [side, abs(move), j, -np.inf, np.inf, b.h[j] if side > 0 else b.l[j]]
    return out


# ── CP-09 trap of a swing level (a strong break that fails) ───────────────────────────

def cp09(m, B, p, cache):
    b = B[p["tf"]]
    bh = B[p["htf"]]
    c = ctx(B, p["tf"], cache)
    _, sh, sl = struct_cached(B, p["htf"], cache)
    out = []
    pend = []       # [side_of_trade, level, j_break, extreme]
    for j in range(1, len(b.c)):
        J = last_done(bh, b.i1[j])
        a = c.atr[j]
        if J < 0 or not np.isfinite(a):
            continue
        keep = []
        for P in pend:
            side, lvl, jb, ext = P
            if j - jb > 3 or not same_day(b, j, jb):
                continue
            ext = max(ext, b.h[j]) if side < 0 else min(ext, b.l[j])
            if side < 0 and b.c[j] < lvl and red(b, j):
                out.append(sig(b, j, -1, ext + 0.1 * a, "TRAP"))
                continue
            if side > 0 and b.c[j] > lvl and green(b, j):
                out.append(sig(b, j, 1, ext - 0.1 * a, "TRAP"))
                continue
            keep.append([side, lvl, jb, ext])
        pend = keep
        if not same_day(b, j, j - 1):
            continue
        if np.isfinite(sh[J]) and b.c[j - 1] <= sh[J] < b.c[j] and body(b, j) >= 0.6 * rng(b, j):
            pend.append([-1, sh[J], j, b.h[j]])
        if np.isfinite(sl[J]) and b.c[j - 1] >= sl[J] > b.c[j] and body(b, j) >= 0.6 * rng(b, j):
            pend.append([1, sl[J], j, b.l[j]])
    return out


# ── CP-10 retest of a broken swing level ──────────────────────────────────────────────

def cp10(m, B, p, cache):
    b = B[p["tf"]]
    bh = B[p["htf"]]
    c = ctx(B, p["tf"], cache)
    _, sh, sl = struct_cached(B, p["htf"], cache)
    out = []
    pend = []       # [side, level, j_break]
    for j in range(1, len(b.c)):
        J = last_done(bh, b.i1[j])
        a = c.atr[j]
        if J < 0 or not np.isfinite(a):
            continue
        keep = []
        for P in pend:
            side, lvl, jb = P
            if j - jb > 24 or not same_day(b, j, jb):
                continue
            if side > 0:
                if b.c[j] < lvl - 0.25 * a:
                    continue
                if b.l[j] <= lvl + 0.1 * a and b.c[j] > lvl and green(b, j):
                    out.append(sig(b, j, 1, min(b.l[j], lvl) - 0.1 * a, "RETEST"))
                    continue
            else:
                if b.c[j] > lvl + 0.25 * a:
                    continue
                if b.h[j] >= lvl - 0.1 * a and b.c[j] < lvl and red(b, j):
                    out.append(sig(b, j, -1, max(b.h[j], lvl) + 0.1 * a, "RETEST"))
                    continue
            keep.append(P)
        pend = keep
        if not same_day(b, j, j - 1):
            continue
        if np.isfinite(sh[J]) and b.c[j - 1] <= sh[J] < b.c[j] and c.power(j, True):
            pend.append([1, sh[J], j])
        if np.isfinite(sl[J]) and b.c[j - 1] >= sl[J] > b.c[j] and c.power(j, False):
            pend.append([-1, sl[J], j])
    return out


# ── CP-12 current-day high/low sweep after a full day's range (IOBoaM71MUA) ──────────

def _day_range_atr(m, n=14):
    hi = np.maximum.reduceat(m.h, m.d0)
    lo = np.minimum.reduceat(m.l, m.d0)
    r = hi - lo
    out = np.full(len(r), np.nan)
    for d in range(n, len(r)):
        out[d] = r[d - n:d].mean()
    return out


def cp12(m, B, p, cache):
    b = B[p["tf"]]
    atr_d = _day_range_atr(m)
    out = []
    for d in range(15, m.n_days):
        if not np.isfinite(atr_d[d]):
            continue
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        for j in range(s0 + 1, s1):
            hi, lo = b.h[s0:j].max(), b.l[s0:j].min()
            if hi - lo < 0.75 * atr_d[d]:
                continue
            if b.h[j] > hi and b.c[j] < hi:
                out.append(sig(b, j, -1, b.h[j] + buffer(b, j, 0.0007), "CURRENT_DAY_SWEEP"))
                break
            if b.l[j] < lo and b.c[j] > lo:
                out.append(sig(b, j, 1, b.l[j] - buffer(b, j, 0.0007), "CURRENT_DAY_SWEEP"))
                break
    return out


# ── fair value gaps and order blocks ──────────────────────────────────────────────────

def fvgs(b, j):
    """The gap made by bars j-2, j-1, j (known at bar j's close): (+1, lo, hi) bullish, (-1, lo, hi) bearish, or None."""
    if j < 2 or not (same_day(b, j, j - 2)):
        return None
    if b.l[j] > b.h[j - 2]:
        return (1, b.h[j - 2], b.l[j])
    if b.h[j] < b.l[j - 2]:
        return (-1, b.h[j], b.l[j - 2])
    return None


def dealing_range(B, htf, row, cache):
    """The latest confirmed higher-timeframe swing high and low at minute row `row`: (high, low) or None."""
    bh = B[htf]
    _, sh, sl = struct_cached(B, htf, cache)
    J = last_done(bh, row)
    if J < 0 or not (np.isfinite(sh[J]) and np.isfinite(sl[J])) or sh[J] <= sl[J]:
        return None
    return sh[J], sl[J]


# ── CP-13 15-minute order block at a swing extreme, entered on a 5-minute FVG ─────────

def cp13(m, B, p, cache):
    b = B[p["tf"]]
    b15 = B[p["htf"]]
    c = ctx(B, p["tf"], cache)
    blocks = []     # [known_row, side, lo, hi, expire_row, touched, done]
    for j in range(22, len(b15.c)):
        g = fvgs(b15, j)
        if g is None:
            continue
        side = g[0]
        lo, hi = b15.l[j - 2], b15.h[j - 2]
        if side > 0 and lo > b15.l[j - 22:j - 2].min():
            continue
        if side < 0 and hi < b15.h[j - 22:j - 2].max():
            continue
        blocks.append([int(b15.i1[j]), side, lo, hi, int(b15.i1[min(j + 48, len(b15.c) - 1)]), False, False])
    out = []
    bi = 0
    active = []
    for j in range(2, len(b.c)):
        while bi < len(blocks) and blocks[bi][0] < b.i0[j]:
            active.append(blocks[bi])
            bi += 1
        a = c.atr[j]
        if not np.isfinite(a):
            continue
        keep = []
        for Bk in active:
            known, side, lo, hi, exp, touched, done = Bk
            if b.i1[j] > exp:
                continue
            if (side > 0 and b.c[j] < lo) or (side < 0 and b.c[j] > hi):
                continue                                    # closed through the block: gone
            if not touched and ((side > 0 and b.l[j] <= hi) or (side < 0 and b.h[j] >= lo)):
                Bk[5] = touched = True
            if touched:
                g = fvgs(b, j)
                if g is not None and g[0] == side:
                    _, glo, ghi = g
                    if side > 0:
                        out.append(sig(b, j, 1, glo - 0.1 * a, "HTF_OB_FVG", entry_limit=float(ghi),
                                       expire_k=int(b.i1[min(j + 12, len(b.c) - 1)])))
                    else:
                        out.append(sig(b, j, -1, ghi + 0.1 * a, "HTF_OB_FVG", entry_limit=float(glo),
                                       expire_k=int(b.i1[min(j + 12, len(b.c) - 1)])))
                    continue                                # one trade per block
            keep.append(Bk)
        active = keep
    return out


# ── CP-14 / CP-15 order flow: delta = taker buy - taker sell (bitcoin) ────────────────

def _deltas(m, b):
    buy = np.add.reduceat(m.bv, b.i0)
    vol = np.add.reduceat(m.vol_all, b.i0)
    return 2 * buy - vol


def cp14(m, B, p, cache):
    """Absorption: a candle whose delta and result disagree at the 6-hour extreme, then the break of it with
    delta agreeing (ieZ--wMeSxE)."""
    b = B[p["tf"]]
    dl = _deltas(m, b)
    out = []
    for j in range(25, len(b.c)):
        t = j - 1
        if not same_day(b, j, t):
            continue
        r = rng(b, t)
        if r <= 0:
            continue
        top = b.h[t] >= b.h[t - 23:t + 1].max()
        bot = b.l[t] <= b.l[t - 23:t + 1].min()
        if top and dl[t] > 0 and (red(b, t) or upper_wick(b, t) >= 0.5 * r) and b.c[j] < b.l[t] and red(b, j) and dl[j] < 0:
            out.append(sig(b, j, -1, b.h[t] + buffer(b, j), "ABSORPTION"))
        elif bot and dl[t] < 0 and (green(b, t) or lower_wick(b, t) >= 0.5 * r) and b.c[j] > b.h[t] and green(b, j) and dl[j] > 0:
            out.append(sig(b, j, 1, b.l[t] - buffer(b, j), "ABSORPTION"))
    return out


def cp15(m, B, p, cache):
    """Morning / evening star at the 6-hour extreme, taken only when the star's delta shows the trapped side."""
    b = B[p["tf"]]
    dl = _deltas(m, b)
    out = []
    for j in range(25, len(b.c)):
        a, s = j - 2, j - 1
        if not same_day(b, j, a):
            continue
        ra = rng(b, a)
        if ra <= 0 or body(b, a) < 0.6 * ra or body(b, s) > 0.3 * body(b, a):
            continue
        mid = (b.o[a] + b.c[a]) / 2
        if red(b, a) and green(b, j) and b.c[j] > mid and b.l[s] <= b.l[s - 23:s + 1].min() and dl[s] < 0:
            out.append(sig(b, j, 1, b.l[s] - buffer(b, j), "MORNING_STAR"))
        elif green(b, a) and red(b, j) and b.c[j] < mid and b.h[s] >= b.h[s - 23:s + 1].max() and dl[s] > 0:
            out.append(sig(b, j, -1, b.h[s] + buffer(b, j), "EVENING_STAR"))
    return out


# ── CP-16 ICT: previous-day / previous-week high-low sweep (37uPX6Li-xE) ─────────────

def cp16(m, B, p, cache):
    b = B[p["tf"]]
    dates = m.date.astype("datetime64[D]")
    week = ((dates.astype(np.int64) + 3) // 7)        # Monday-based week number of each trading day
    hi_d = np.maximum.reduceat(m.h, m.d0)
    lo_d = np.minimum.reduceat(m.l, m.d0)
    out = []
    for d in range(6, m.n_days):
        if not m.prev_ok[d]:
            continue
        levels = [(hi_d[d - 1], True, "PDH"), (lo_d[d - 1], False, "PDL")]
        prev_w = np.flatnonzero(week[:d] == week[d] - 1)
        if len(prev_w):
            levels += [(hi_d[prev_w].max(), True, "PWH"), (lo_d[prev_w].min(), False, "PWL")]
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        done = set()
        for j in range(s0, s1):
            for lvl, above, name in levels:
                if name in done:
                    continue
                if above and b.h[j] > lvl and b.c[j] < lvl:
                    out.append(sig(b, j, -1, b.h[j] + buffer(b, j), name + "_SWEEP"))
                    done.add(name)
                elif not above and b.l[j] < lvl and b.c[j] > lvl:
                    out.append(sig(b, j, 1, b.l[j] - buffer(b, j), name + "_SWEEP"))
                    done.add(name)
    out.sort(key=lambda s: s.k)
    return out


# ── CP-17 fair value gap, the third touch (with premium / discount) ───────────────────

def cp17(m, B, p, cache):
    """A fair value gap in the discount (buys) or premium (sells) half of the 15-minute dealing range. Touches are
    episodes of consecutive bars trading into it. The first two are not traded; the third must run past both earlier
    touches and close back on the gap's side -> trade (37uPX6Li-xE: "trust it after it has held twice")."""
    b = B[p["tf"]]
    c = ctx(B, p["tf"], cache)
    gaps = []       # dict(side, lo, hi, jm, eps=[extremes], inside, cur)
    out = []
    for j in range(2, len(b.c)):
        a = c.atr[j]
        keep = []
        for G in gaps:
            side, lo, hi = G["side"], G["lo"], G["hi"]
            if j - G["jm"] > 288 or (side > 0 and b.c[j] < lo) or (side < 0 and b.c[j] > hi):
                continue
            touching = (b.l[j] <= hi) if side > 0 else (b.h[j] >= lo)
            if touching:
                ext = b.l[j] if side > 0 else b.h[j]
                G["cur"] = ext if not G["inside"] else (min(G["cur"], ext) if side > 0 else max(G["cur"], ext))
                G["inside"] = True
                if len(G["eps"]) == 2 and np.isfinite(a):
                    swept = G["cur"] < min(G["eps"]) if side > 0 else G["cur"] > max(G["eps"])
                    back = b.c[j] > lo if side > 0 else b.c[j] < hi
                    if swept and back:
                        out.append(sig(b, j, side, G["cur"] - side * 0.1 * a, "FVG_THIRD_TOUCH"))
                        continue
            elif G["inside"]:
                G["eps"].append(G["cur"])
                G["inside"] = False
                if len(G["eps"]) >= 3:
                    continue
            keep.append(G)
        gaps = keep
        g = fvgs(b, j)
        if g is None:
            continue
        rngd = dealing_range(B, p["htf"], int(b.i1[j]), cache)
        if rngd is None:
            continue
        mid_range = (rngd[0] + rngd[1]) / 2
        gm = (g[1] + g[2]) / 2
        if (g[0] > 0 and gm < mid_range) or (g[0] < 0 and gm > mid_range):
            gaps.append({"side": g[0], "lo": g[1], "hi": g[2], "jm": j, "eps": [], "inside": False, "cur": None})
    return out


# ── CP-18 order block (candle one of a fair value gap), limit at its 50% ─────────────

def cp18(m, B, p, cache):
    b = B[p["tf"]]
    c = ctx(B, p["tf"], cache)
    out = []
    for j in range(2, len(b.c)):
        g = fvgs(b, j)
        a = c.atr[j]
        if g is None or not np.isfinite(a):
            continue
        side = g[0]
        lo, hi = b.l[j - 2], b.h[j - 2]
        rngd = dealing_range(B, p["htf"], int(b.i1[j]), cache)
        if rngd is None:
            continue
        mid_range = (rngd[0] + rngd[1]) / 2
        mean = (lo + hi) / 2
        if (side > 0 and mean >= mid_range) or (side < 0 and mean <= mid_range):
            continue
        exp = int(b.i1[min(j + 288, len(b.c) - 1)])
        if side > 0:
            out.append(sig(b, j, 1, lo - 0.1 * a, "ORDER_BLOCK", entry_limit=float(mean), expire_k=exp))
        else:
            out.append(sig(b, j, -1, hi + 0.1 * a, "ORDER_BLOCK", entry_limit=float(mean), expire_k=exp))
    return out


# ── CP-20 inverse FVG / CP-21 breaker block ───────────────────────────────────────────

def _flip_zone(m, B, p, cache, use_block: bool, setup: str):
    """A zone (the gap itself, or the order-block candle) that price closes through; trade its retest from the other side."""
    b = B[p["tf"]]
    c = ctx(B, p["tf"], cache)
    zones = []      # [orig_side, lo, hi, j_made, broken_at]
    out = []
    for j in range(2, len(b.c)):
        a = c.atr[j]
        keep = []
        for Z in zones:
            side, lo, hi, jm, broken = Z
            if j - jm > 288:
                continue
            if broken is None:
                if (side > 0 and b.c[j] < lo) or (side < 0 and b.c[j] > hi):
                    Z[4] = j
                keep.append(Z)
                continue
            if j - broken > 48:
                continue
            if side > 0 and j > broken and b.h[j] >= lo and b.c[j] < lo and red(b, j) and np.isfinite(a):
                out.append(sig(b, j, -1, hi + 0.1 * a, setup))
                continue
            if side < 0 and j > broken and b.l[j] <= hi and b.c[j] > hi and green(b, j) and np.isfinite(a):
                out.append(sig(b, j, 1, lo - 0.1 * a, setup))
                continue
            if (side > 0 and b.c[j] > hi) or (side < 0 and b.c[j] < lo):
                continue                                     # reclaimed: the flip failed
            keep.append(Z)
        zones = keep
        g = fvgs(b, j)
        if g is not None:
            if use_block:
                zones.append([g[0], b.l[j - 2], b.h[j - 2], j, None])
            else:
                zones.append([g[0], g[1], g[2], j, None])
    return out


def cp20(m, B, p, cache):
    return _flip_zone(m, B, p, cache, False, "INVERSE_FVG")


def cp21(m, B, p, cache):
    return _flip_zone(m, B, p, cache, True, "BREAKER_BLOCK")


# ── sweeps of the last confirmed higher-timeframe swing (used by CP-22, CP-27, CP-28) ──

def _htf_sweeps(B, p, cache):
    """5-minute bars that wick beyond the last confirmed higher-timeframe swing and close back inside: (j, side_of_trade, extreme)."""
    b = B[p["tf"]]
    bh = B[p["htf"]]
    _, sh, sl = struct_cached(B, p["htf"], cache)
    out = []
    last_used = {1: None, -1: None}
    for j in range(len(b.c)):
        J = last_done(bh, b.i1[j])
        if J < 0:
            continue
        if np.isfinite(sh[J]) and b.h[j] > sh[J] and b.c[j] < sh[J] and last_used[-1] != sh[J]:
            out.append((j, -1, b.h[j]))
            last_used[-1] = sh[J]
        elif np.isfinite(sl[J]) and b.l[j] < sl[J] and b.c[j] > sl[J] and last_used[1] != sl[J]:
            out.append((j, 1, b.l[j]))
            last_used[1] = sl[J]
    return out


# ── CP-22 change in state of delivery after a sweep ───────────────────────────────────

def cp22(m, B, p, cache):
    b = B[p["tf"]]
    c = ctx(B, p["tf"], cache)
    out = []
    for (s, side, ext) in _htf_sweeps(B, p, cache):
        a = c.atr[s]
        if not np.isfinite(a) or s < 12:
            continue
        lo_i = s - 12
        if side < 0:      # a rally into a high: the first red candle after the rally's low
            start = lo_i + int(np.argmin(b.l[lo_i:s + 1]))
            reds = [k for k in range(start, s + 1) if red(b, k)]
            level = min(b.o[reds[0]], b.c[reds[0]]) if reds else b.o[start]
        else:
            start = lo_i + int(np.argmax(b.h[lo_i:s + 1]))
            greens = [k for k in range(start, s + 1) if green(b, k)]
            level = max(b.o[greens[0]], b.c[greens[0]]) if greens else b.o[start]
        for j in range(s + 1, min(s + 13, len(b.c))):
            if not same_day(b, j, s):
                break
            if (side < 0 and b.h[j] > ext) or (side > 0 and b.l[j] < ext):
                break
            if (side < 0 and b.c[j] < level) or (side > 0 and b.c[j] > level):
                out.append(sig(b, j, side, ext - side * 0.1 * a, "CISD"))
                break
    out.sort(key=lambda x: x.k)
    return out


# ── CP-23 inducement ──────────────────────────────────────────────────────────────────

def cp23(m, B, p, cache):
    b = B[p["tf"]]
    c = ctx(B, p["tf"], cache)
    out = []
    last_h = last_l = None
    pend = None     # [side, inducement_level, j_bos, swept_extreme]
    for j in range(2, len(b.c)):
        q = j - 2
        if c.ph[q]:
            last_h = (b.h[q], q)
        if c.pl[q]:
            last_l = (b.l[q], q)
        a = c.atr[j]
        if not np.isfinite(a):
            continue
        if pend is not None:
            side, lvl, jb, ext = pend
            if j - jb > 48:
                pend = None
            elif side > 0:
                if b.c[j] < lvl - a:
                    pend = None
                elif ext is None:
                    if b.l[j] < lvl:
                        pend[3] = b.l[j]
                        if b.c[j] > lvl and green(b, j):
                            out.append(sig(b, j, 1, b.l[j] - 0.1 * a, "INDUCEMENT"))
                            pend = None
                else:
                    pend[3] = min(ext, b.l[j])
                    if b.c[j] > lvl and green(b, j):
                        out.append(sig(b, j, 1, pend[3] - 0.1 * a, "INDUCEMENT"))
                        pend = None
            else:
                if b.c[j] > lvl + a:
                    pend = None
                elif ext is None:
                    if b.h[j] > lvl:
                        pend[3] = b.h[j]
                        if b.c[j] < lvl and red(b, j):
                            out.append(sig(b, j, -1, b.h[j] + 0.1 * a, "INDUCEMENT"))
                            pend = None
                else:
                    pend[3] = max(ext, b.h[j])
                    if b.c[j] < lvl and red(b, j):
                        out.append(sig(b, j, -1, pend[3] + 0.1 * a, "INDUCEMENT"))
                        pend = None
            if pend is not None:
                continue
        if last_h is not None and last_l is not None and b.c[j - 1] <= last_h[0] < b.c[j] and last_l[1] < j:
            pend = [1, last_l[0], j, None]
        elif last_h is not None and last_l is not None and b.c[j - 1] >= last_l[0] > b.c[j] and last_h[1] < j:
            pend = [-1, last_h[0], j, None]
    return out


# ── CP-24 SMT divergence between two correlated markets ───────────────────────────────

def cp24(m, B, p, cache, other=None):
    """`other` = (Minutes, bars dict) of the companion market (silver for gold, GBP/USD for EUR/USD)."""
    if other is None:
        return []
    b = B[p["tf"]]
    c = ctx(B, p["tf"], cache)
    om, oB = other
    ob = oB[p["tf"]]
    pos = {int(t): i for i, t in enumerate(ob.t0)}
    hs, ls = [], []
    out = []
    for j in range(2, len(b.c)):
        q = j - 2
        a = c.atr[j]
        if not np.isfinite(a):
            continue
        for kind in ("h", "l"):
            if (kind == "h" and not c.ph[q]) or (kind == "l" and not c.pl[q]):
                continue
            lst = hs if kind == "h" else ls
            lst.append(q)
            if len(lst) < 2:
                continue
            q1, q2 = lst[-2], lst[-1]
            if q2 - q1 > 150:
                continue
            i1, i2 = pos.get(int(b.t0[q1])), pos.get(int(b.t0[q2]))
            ij = pos.get(int(b.t0[j]))
            if i1 is None or i2 is None or ij is None or i1 < 2 or i2 < 2:
                continue
            if kind == "h":
                o1, o2 = ob.h[max(0, i1 - 2):i1 + 3].max(), ob.h[max(0, i2 - 2):min(i2 + 3, ij + 1)].max()
                if b.h[q2] > b.h[q1] and o2 < o1:
                    out.append(sig(b, j, -1, b.h[q2] + 0.1 * a, "SMT_TOP"))
            else:
                o1, o2 = ob.l[max(0, i1 - 2):i1 + 3].min(), ob.l[max(0, i2 - 2):min(i2 + 3, ij + 1)].min()
                if b.l[q2] < b.l[q1] and o2 > o1:
                    out.append(sig(b, j, 1, b.l[q2] - 0.1 * a, "SMT_BOTTOM"))
    return out


# ── CP-25 optimal trade entry, 0.705-0.79 of the last 15-minute impulse ───────────────

def cp25(m, B, p, cache):
    b = B[p["tf"]]
    bh = B[p["htf"]]
    chh = ctx(B, p["htf"], cache)
    out = []
    last_h = last_l = None
    for J in range(2, len(bh.c)):
        q = J - 2
        if chh.ph[q]:
            if last_l is not None and last_l[1] < q:
                H, L = bh.h[q], last_l[0]
                a = chh.atr[J]
                if np.isfinite(a) and H - L >= 3 * a:
                    entry = H - 0.705 * (H - L)
                    exp = int(bh.i1[min(J + 32, len(bh.c) - 1)])
                    jj = int(np.searchsorted(b.i1, bh.i1[J], "right")) - 1
                    if jj >= 0:
                        out.append(sig(b, jj, 1, L - 0.1 * a, "OTE", entry_limit=float(entry), expire_k=exp))
            last_h = (bh.h[q], q)
        if chh.pl[q]:
            if last_h is not None and last_h[1] < q:
                H, L = last_h[0], bh.l[q]
                a = chh.atr[J]
                if np.isfinite(a) and H - L >= 3 * a:
                    entry = L + 0.705 * (H - L)
                    exp = int(bh.i1[min(J + 32, len(bh.c) - 1)])
                    jj = int(np.searchsorted(b.i1, bh.i1[J], "right")) - 1
                    if jj >= 0:
                        out.append(sig(b, jj, -1, H + 0.1 * a, "OTE", entry_limit=float(entry), expire_k=exp))
            last_l = (bh.l[q], q)
    out.sort(key=lambda s: s.k)
    return out


# ── CP-26 turtle soup ─────────────────────────────────────────────────────────────────

def cp26(m, B, p, cache):
    b = B[p["tf"]]
    c = ctx(B, p["tf"], cache)
    out = []
    for j in range(21, len(b.c)):
        a = c.atr[j]
        if not np.isfinite(a) or not same_day(b, j, j - 20):
            continue
        H, L = b.h[j - 20:j].max(), b.l[j - 20:j].min()
        if b.h[j] > H and b.c[j] < H:
            out.append(sig(b, j, -1, b.h[j] + 0.1 * a, "TURTLE_SOUP"))
        elif b.l[j] < L and b.c[j] > L:
            out.append(sig(b, j, 1, b.l[j] - 0.1 * a, "TURTLE_SOUP"))
    return out


# ── CP-27 unicorn model / CP-28 silver bullet ─────────────────────────────────────────

def _unicorn(m, B, p, cache, window=None, setup="UNICORN"):
    b = B[p["tf"]]
    c = ctx(B, p["tf"], cache)
    out = []
    last_h = [None] * len(b.c)
    last_l = [None] * len(b.c)
    h = l = None
    for j in range(len(b.c)):
        q = j - 2
        if q >= 0 and c.ph[q]:
            h = b.h[q]
        if q >= 0 and c.pl[q]:
            l = b.l[q]
        last_h[j], last_l[j] = h, l
    for (s, side, ext) in _htf_sweeps(B, p, cache):
        a = c.atr[s]
        if not np.isfinite(a):
            continue
        for d in range(s + 1, min(s + 13, len(b.c) - 1)):
            if not same_day(b, d, s):
                break
            if (side < 0 and b.h[d] > ext) or (side > 0 and b.l[d] < ext):
                break
            mr = c.mr20[d]
            disp = np.isfinite(mr) and rng(b, d) >= 1.5 * mr
            if side < 0:
                mss = last_l[d] is not None and b.c[d] < last_l[d] and red(b, d)
            else:
                mss = last_h[d] is not None and b.c[d] > last_h[d] and green(b, d)
            if not (disp and mss):
                continue
            # the fair value gap of the displacement, known at bar d or d+1
            for k in (d, d + 1):
                g = fvgs(b, k)
                if g is None or g[0] != side:
                    continue
                if window is not None:
                    lo_w, hi_w = window
                    if not (lo_w <= b.ist0[k] < hi_w):
                        continue
                    end = next((x for x in range(k, len(b.c)) if b.ist0[x] >= hi_w or not same_day(b, x, k)), len(b.c) - 1)
                    exp = int(b.i1[max(k, end - 1)])
                else:
                    exp = int(b.i1[min(k + 24, len(b.c) - 1)])
                _, glo, ghi = g
                if side < 0:
                    out.append(sig(b, k, -1, ext + 0.1 * a, setup, entry_limit=float(glo), expire_k=exp))
                else:
                    out.append(sig(b, k, 1, ext - 0.1 * a, setup, entry_limit=float(ghi), expire_k=exp))
                break
            break
    out.sort(key=lambda x: x.k)
    return out


def cp27(m, B, p, cache):
    return _unicorn(m, B, p, cache)


def cp28(m, B, p, cache):
    return _unicorn(m, B, p, cache, window=(19 * 60 + 30, 20 * 60 + 30), setup="SILVER_BULLET")


# ── registry ──────────────────────────────────────────────────────────────────────────

@dataclass
class Strategy:
    sid: str
    name: str
    video: str
    fn: object
    markets: tuple
    params: dict                      # market -> {"tf": execution bars, "htf": analysis bars}
    exit_clock: dict
    exits: dict = field(default_factory=lambda: dict(EXITS))
    limits: Limits = field(default_factory=lambda: LIMITS)
    companion: dict = field(default_factory=dict)   # market -> companion market (SMT)


G = {"tf": 5, "htf": 15}
BT = {"tf": 15, "htf": 60}
VID = {"crypto": "qPBdLsiEa3s", "charts": "mb0AeY9YyPg", "liq": "IOBoaM71MUA", "flow": "ieZ--wMeSxE", "ict": "37uPX6Li-xE"}


def _s(sid, name, video, fn, markets, **kw):
    params = {mk: dict(BT if mk == "BTCUSD" else G) for mk in markets}
    clocks = {mk: (BTC_X if mk == "BTCUSD" else GOLD_X) for mk in markets}
    return Strategy(sid, name, video, fn, tuple(markets), params, clocks, **kw)


STRATEGIES = {s.sid: s for s in [
    _s("CP-01", "Trend pullback at the 5th point", VID["crypto"] + "," + VID["charts"], cp01, ("BTCUSD", "XAUUSD")),
    _s("CP-02", "Power-candle breakout of the last swing", VID["crypto"] + "," + VID["charts"], cp02, ("BTCUSD", "XAUUSD")),
    _s("CP-03", "Range ping-pong and range breakout", VID["crypto"] + "," + VID["charts"], cp03, ("BTCUSD", "XAUUSD")),
    _s("CP-04", "Trend-line rejection", VID["crypto"], cp04, ("BTCUSD",)),
    _s("CP-05", "Turning-point zones (3 touches)", VID["charts"], cp05, ("XAUUSD",)),
    _s("CP-06", "Triple top / triple bottom", VID["charts"], cp06, ("XAUUSD",)),
    _s("CP-07", "Head and shoulders / inverted", VID["charts"], cp07, ("XAUUSD",)),
    _s("CP-08", "Flag and pole", VID["charts"], cp08, ("XAUUSD",)),
    _s("CP-09", "Trap of a swing level", VID["charts"], cp09, ("XAUUSD",)),
    _s("CP-10", "Retest of a broken level", VID["charts"], cp10, ("XAUUSD",)),
    _s("CP-12", "Current-day high/low sweep", VID["liq"], cp12, ("XAUUSD",)),
    _s("CP-13", "15m order block entered on a 5m FVG", VID["liq"], cp13, ("XAUUSD",)),
    _s("CP-14", "Order-flow absorption", VID["flow"], cp14, ("BTCUSD",)),
    _s("CP-15", "Delta-filtered morning / evening star", VID["flow"], cp15, ("BTCUSD",)),
    _s("CP-16", "ICT previous-day / week high-low sweep", VID["ict"], cp16, ("XAUUSD",)),
    _s("CP-17", "Fair value gap, third touch", VID["ict"], cp17, ("XAUUSD",)),
    _s("CP-18", "Order block at its 50%", VID["ict"], cp18, ("XAUUSD",)),
    _s("CP-20", "Inverse fair value gap", VID["ict"], cp20, ("XAUUSD",)),
    _s("CP-21", "Breaker block", VID["ict"], cp21, ("XAUUSD",)),
    _s("CP-22", "CISD after a liquidity sweep", VID["ict"], cp22, ("XAUUSD",)),
    _s("CP-23", "Inducement", VID["ict"], cp23, ("XAUUSD",)),
    _s("CP-24", "SMT divergence", VID["ict"], cp24, ("XAUUSD", "EURUSD"), companion={"XAUUSD": "XAGUSD", "EURUSD": "GBPUSD"}),
    _s("CP-25", "Optimal trade entry (0.705-0.79)", VID["ict"], cp25, ("XAUUSD",)),
    _s("CP-26", "Turtle soup", VID["ict"], cp26, ("XAUUSD",)),
    _s("CP-27", "Unicorn model", VID["ict"], cp27, ("XAUUSD",)),
    _s("CP-28", "Silver bullet (19:30-20:30 IST)", VID["ict"], cp28, ("XAUUSD",)),
]}
STRATEGIES["CP-24"].exit_clock["EURUSD"] = FX_X


def tfs_of(st: Strategy, market: str) -> tuple:
    p = st.params[market]
    return tuple(sorted({p["tf"], p["htf"]}))


def build_bars(m, tfs) -> dict:
    return {tf: make_bars(m, tf) for tf in tfs}


def signals(st: Strategy, market: str, m, B: dict, cache: dict, other=None) -> list:
    p = st.params[market]
    if st.sid == "CP-24":
        return st.fn(m, B, p, cache, other)
    return st.fn(m, B, p, cache)


def exits_for(st: Strategy) -> Exits:
    return Exits(**st.exits)
