"""Neeraj Joshi's Indian-market strategies NJ-01 .. NJ-26 (analyses/neerajjoshi.md, the "A:" lines are the exact
rules). Each function returns signals; each *_x function returns the strategy's exits. See yc_common for the
conventions (completed bars only, orders from the next row)."""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import (bars_of_day, bear_engulf, body, bull_engulf, ctx, cross_dn, cross_up, first_bar, flags_cross,  # noqa: F401
                       green, in_window, last_bar_before, lw, prev_close, red, rng, sig, uw, weekday)
from yc_engine import XExits
from yt_engine import Exits, Signal


def _last_entry_bar(b, d, minute=15 * 60):
    """The last bar of day d starting before `minute` (orders placed after it would have no time to work)."""
    return last_bar_before(b, d, minute)


def _vwap(m, B, tf, cache):
    key = ("vwap", tf)
    if key not in cache:
        cache[key] = I.session_vwap(m, B[tf])
    return cache[key]


# ── NJ-01 9:20 VWAP + EMA 7 first-candle breakout (NSE 5-minute pool) ────────────────────

def nj01(m, B, p, cache):
    b = B[5]
    vw = _vwap(m, B, 5, cache)
    e7 = ctx(m, B, 5, cache).ema(7)
    gap = (p.get("ctx") or {}).get("nifty_gap")
    if gap is None:
        return []
    out = []
    for d in range(1, m.n_days):
        j = first_bar(b, d)
        if j >= b.b1[d] - 1 or b.ist0[j] != 9 * 60 + 15:
            continue
        g = gap.get(str(m.date[d]))
        last = _last_entry_bar(b, d, 15 * 60 + 5)
        if not g or last is None or last <= j:
            continue
        if g > 0 and green(b, j) and b.o[j] < vw[j] < b.c[j] and e7[j] < vw[j]:
            out.append(sig(b, j, 1, b.l[j], "NJ01_LONG", entry_stop=float(b.h[j]), expire_k=int(b.i1[last])))
        elif g < 0 and red(b, j) and b.o[j] > vw[j] > b.c[j] and e7[j] > vw[j]:
            out.append(sig(b, j, -1, b.h[j], "NJ01_SHORT", entry_stop=float(b.l[j]), expire_k=int(b.i1[last])))
    return out


def nj01_x(m, B, p, cache):
    return XExits(target_r=None, be_at_r=1.0, trail=("dist_r", 1.0, 0.6))


# ── NJ-02 pivot points + narrow CPR, trade from the open's side (NSE 5-minute pool, NIFTY) ─

def nj02(m, B, p, cache):
    b = B[5]
    H, L, Cc = I.day_hlc(m)
    width = np.full(m.n_days, np.nan)
    piv = [None] * m.n_days
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        pv = I.pivot_points(H[d - 1], L[d - 1], Cc[d - 1])
        piv[d] = pv
        width[d] = (pv["TC"] - pv["BC"]) / pv["P"]
    out = []
    for d in range(21, m.n_days):
        pv = piv[d]
        hist = width[d - 20:d]
        hist = hist[np.isfinite(hist)]
        if pv is None or len(hist) < 15 or not width[d] <= np.percentile(hist, 100 / 3):
            continue
        j = first_bar(b, d)
        if j >= b.b1[d] - 1 or b.ist0[j] != 9 * 60 + 15:
            continue
        op, c = b.o[j], b.c[j]
        if op > pv["P"] and pv["P"] < c < pv["R1"] and pv["BC"] < c:
            out.append(sig(b, j, 1, pv["BC"], "NJ02_LONG", target_px=float(pv["R2"]), info={"partial_px": float(pv["R1"])}))
        elif op < pv["P"] and pv["S1"] < c < pv["P"] and pv["TC"] > c:
            out.append(sig(b, j, -1, pv["TC"], "NJ02_SHORT", target_px=float(pv["S2"]), info={"partial_px": float(pv["S1"])}))
    return out


def nj02_x(m, B, p, cache):
    return XExits(target_r=None, partial_px=True)


# ── NJ-03 EMA 9 + ADX above 25 and rising (NIFTY 5-minute) ─────────────────────────────

def _adx(m, B, tf, cache):
    key = ("adx", tf)
    if key not in cache:
        cache[key] = I.adx(B[tf], 14)
    return cache[key]


def nj03(m, B, p, cache):
    b = B[5]
    e9 = ctx(m, B, 5, cache).ema(9)
    a, _, _ = _adx(m, B, 5, cache)

    def ok(j, side):
        if j < 2 or not (np.isfinite(a[j]) and np.isfinite(a[j - 1])):
            return False
        on_side = b.c[j] > e9[j] if side > 0 else b.c[j] < e9[j]
        return on_side and a[j] > 25 and a[j] > a[j - 1]

    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        for j in rows[1:]:
            if not in_window(b, j, 9 * 60 + 20, 14 * 60 + 45):
                continue
            last = min(j + 3, rows[-1])
            for side in (1, -1):
                if ok(j, side) and not ok(j - 1, side):
                    stop, trig = (b.l[j], b.h[j]) if side > 0 else (b.h[j], b.l[j])
                    out.append(sig(b, j, side, stop, "NJ03", entry_stop=float(trig), expire_k=int(b.i1[last])))
    return out


def nj03_x(m, B, p, cache):
    a, _, _ = _adx(m, B, 5, cache)
    fall = np.zeros(len(a), bool)
    fall[1:] = np.isfinite(a[1:]) & np.isfinite(a[:-1]) & (a[1:] < a[:-1])
    return Exits(target_r=None, xbars=B[5], xlong=fall, xshort=fall)


# ── NJ-04 EMA 10 failed pullback, Anant Ladha (NIFTY 5-minute) ─────────────────────────

def nj04(m, B, p, cache):
    b = B[5]
    e10 = ctx(m, B, 5, cache).ema(10)
    out = []
    for d in range(m.n_days):
        if weekday(m, d) == 1:                       # no Tuesdays
            continue
        rows = list(bars_of_day(b, d))
        for j in rows[1:-1]:
            morning = in_window(b, j, 9 * 60 + 15, 10 * 60)
            afternoon = in_window(b, j, 13 * 60 + 45, 14 * 60 + 15)
            if not (morning or afternoon):
                continue
            tr = 3.0 if morning else 2.0
            if green(b, j) and b.h[j] < e10[j] and b.c[j - 1] < e10[j - 1]:
                risk = b.h[j] - b.l[j]
                if risk > 0:
                    out.append(sig(b, j, -1, b.h[j], "NJ04_SHORT", entry_stop=float(b.l[j]), expire_k=int(b.i1[j + 1]),
                                   target_px=float(b.l[j] - tr * risk)))
            elif red(b, j) and b.l[j] > e10[j] and b.c[j - 1] > e10[j - 1]:
                risk = b.h[j] - b.l[j]
                if risk > 0:
                    out.append(sig(b, j, 1, b.l[j], "NJ04_LONG", entry_stop=float(b.h[j]), expire_k=int(b.i1[j + 1]),
                                   target_px=float(b.h[j] + tr * risk)))
    return out


def nj04_x(m, B, p, cache):
    b = B[5]
    e10 = ctx(m, B, 5, cache).ema(10)
    return Exits(target_r=None, xbars=b, xlong=b.c < e10, xshort=b.c > e10)


# ── NJ-05 EMA 50/100 + Stochastic 14/1/3 scalp (BANKNIFTY 1-minute) ────────────────────

def _stoch(m, B, tf, cache):
    key = ("stoch", tf)
    if key not in cache:
        cache[key] = I.stochastic(B[tf], 14, 1, 3)
    return cache[key]


def nj05(m, B, p, cache):
    b = B[1]
    c = ctx(m, B, 1, cache)
    e50, e100 = c.ema(50), c.ema(100)
    K, D = _stoch(m, B, 1, cache)
    out = []
    for j in range(150, len(b.c) - 1):
        if not in_window(b, j, 9 * 60 + 20, 15 * 60) or b.day[j] != b.day[j - 1]:
            continue
        if e50[j] > e100[j] and cross_up(K, D, j) and D[j] <= 25:
            out.append(sig(b, j, 1, b.l[j], "NJ05_LONG"))
        elif e50[j] < e100[j] and cross_dn(K, D, j) and D[j] >= 75:
            out.append(sig(b, j, -1, b.h[j], "NJ05_SHORT"))
    return out


def nj05_x(m, B, p, cache):
    K, _ = _stoch(m, B, 1, cache)
    return Exits(target_r=None, xbars=B[1], xlong=K >= 80, xshort=K <= 20)


# ── NJ-06 Bollinger squeeze breakout (NSE 15-minute pool) ──────────────────────────────

def nj06(m, B, p, cache):
    b = B[15]
    mid, up, lo = ctx(m, B, 15, cache).bollinger(20, 2.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        w = (up - lo) / mid
    sq = np.zeros(len(w), bool)
    for j in range(119, len(w)):
        win = w[j - 99:j + 1]
        win = win[np.isfinite(win)]
        if len(win) >= 80 and np.isfinite(w[j]):
            sq[j] = w[j] <= np.percentile(win, 20)
    out = []
    for j in range(125, len(b.c) - 1):
        if b.day[j] != b.day[j - 1] or not in_window(b, j, 9 * 60 + 30, 14 * 60 + 45) or not sq[j - 5:j].any():
            continue
        if b.c[j] > up[j] and b.c[j - 1] <= up[j - 1]:
            out.append(sig(b, j, 1, b.l[j], "NJ06_LONG"))
        elif b.c[j] < lo[j] and b.c[j - 1] >= lo[j - 1]:
            out.append(sig(b, j, -1, b.h[j], "NJ06_SHORT"))
    return out


def nj06_x(m, B, p, cache):
    b = B[15]
    _, up, lo = ctx(m, B, 15, cache).bollinger(20, 2.0)
    return Exits(target_r=None, xbars=b, xlong=b.c < up, xshort=b.c > lo)


# ── NJ-07 Bollinger band turn + MACD cross + volume (NSE 5-minute pool) ────────────────

def nj07(m, B, p, cache):
    b = B[5]
    c = ctx(m, B, 5, cache)
    _, up, lo = c.bollinger(20, 2.0)
    line, sg, _ = c.macd()
    vol, va = c.vol(), c.vol_avg(20)
    out = []
    for j in range(40, len(b.c) - 1):
        if b.day[j] != b.day[j - 4] or not in_window(b, j, 9 * 60 + 30, 14 * 60 + 45):
            continue
        if not (np.isfinite(va[j]) and vol[j] > va[j]):
            continue
        w = range(j - 4, j + 1)
        if cross_up(line, sg, j) and any(b.l[k] <= lo[k] for k in w):
            out.append(sig(b, j, 1, min(b.l[k] for k in w), "NJ07_LONG"))
        elif cross_dn(line, sg, j) and any(b.h[k] >= up[k] for k in w):
            out.append(sig(b, j, -1, max(b.h[k] for k in w), "NJ07_SHORT"))
    return out


def nj07_x(m, B, p, cache):
    line, sg, _ = ctx(m, B, 5, cache).macd()
    up, dn = flags_cross(line, sg)
    return Exits(target_r=None, xbars=B[5], xlong=dn, xshort=up)


# ── NJ-08 RSI 50 + EMA 14 cross (NIFTY 5-minute) ───────────────────────────────────────

def nj08(m, B, p, cache):
    b = B[5]
    c = ctx(m, B, 5, cache)
    e14, r = c.ema(14), c.rsi(14)
    out = []
    for j in range(20, len(b.c) - 1):
        if b.day[j] != b.day[j - 1] or not in_window(b, j, 9 * 60 + 20, 14 * 60 + 45):
            continue
        if b.c[j - 1] <= e14[j - 1] and b.c[j] > e14[j] and r[j] > 50:
            out.append(sig(b, j, 1, b.l[j], "NJ08_LONG"))
        elif b.c[j - 1] >= e14[j - 1] and b.c[j] < e14[j] and r[j] < 50:
            out.append(sig(b, j, -1, b.h[j], "NJ08_SHORT"))
    return out


def nj08_x(m, B, p, cache):
    r = ctx(m, B, 5, cache).rsi(14)
    back_below_70 = np.zeros(len(r), bool)
    back_above_30 = np.zeros(len(r), bool)
    back_below_70[1:] = (r[:-1] >= 70) & (r[1:] < 70)
    back_above_30[1:] = (r[:-1] <= 30) & (r[1:] > 30)
    return Exits(target_r=None, xbars=B[5], xlong=back_below_70, xshort=back_above_30)


# ── NJ-09 MACD signal-line cross (NIFTY 5-minute) ──────────────────────────────────────

def nj09(m, B, p, cache):
    b = B[5]
    line, sg, _ = ctx(m, B, 5, cache).macd()
    out = []
    for j in range(40, len(b.c) - 1):
        if b.day[j] != b.day[j - 4] or not in_window(b, j, 9 * 60 + 35, 14 * 60 + 45):
            continue
        if cross_up(line, sg, j):
            out.append(sig(b, j, 1, b.l[j - 4:j + 1].min(), "NJ09_LONG"))
        elif cross_dn(line, sg, j):
            out.append(sig(b, j, -1, b.h[j - 4:j + 1].max(), "NJ09_SHORT"))
    return out


def nj09_x(m, B, p, cache):
    line, sg, _ = ctx(m, B, 5, cache).macd()
    up, dn = flags_cross(line, sg)
    return Exits(target_r=None, xbars=B[5], xlong=dn, xshort=up)


# ── NJ-10 Heikin Ashi doji turn (NIFTY 15-minute) ──────────────────────────────────────

def _ha(m, B, tf, cache):
    key = ("ha", tf)
    if key not in cache:
        cache[key] = I.ha_ohlc(B[tf])
    return cache[key]


def nj10(m, B, p, cache):
    b = B[15]
    ho, hh, hl, hc = _ha(m, B, 15, cache)
    eps = 1e-9 * np.maximum(np.abs(hc), 1.0)
    bod = np.abs(hc - ho)
    rg = hh - hl
    upw = hh - np.maximum(ho, hc)
    loww = np.minimum(ho, hc) - hl
    doji = (rg > 0) & (bod <= rg / 3) & (upw > eps) & (loww > eps)
    g, r = hc > ho, hc < ho
    strong_g = g & (loww <= eps)
    strong_r = r & (upw <= eps)
    out = []
    for j in range(4, len(b.c) - 3):
        k = j + 2
        if not (b.day[j - 3] == b.day[k]) or not in_window(b, k, 9 * 60 + 30, 14 * 60 + 45):
            continue
        if doji[j] and g[j] and r[j - 3:j].all() and strong_g[j + 1] and strong_g[j + 2]:
            out.append(sig(b, k, 1, hl[j], "NJ10_LONG"))
        elif doji[j] and r[j] and g[j - 3:j].all() and strong_r[j + 1] and strong_r[j + 2]:
            out.append(sig(b, k, -1, hh[j], "NJ10_SHORT"))
    return out


def nj10_x(m, B, p, cache):
    ho, _, _, hc = _ha(m, B, 15, cache)
    return Exits(target_r=None, xbars=B[15], xlong=hc < ho, xshort=hc > ho)


# ── NJ-11 Renko 1-back / 2-back continuation (NIFTY, bricks from 1-minute closes) ──────

class _BrickBars:
    """Renko bricks in the shape the engine's exit flags need: the row each brick completed on, and its close."""

    def __init__(self, i1, c):
        self.i1, self.c = np.asarray(i1, np.int64), np.asarray(c, float)


def _renko_day(closes: np.ndarray, box: float):
    """Traditional Renko of one day's closes: (direction, close, local row) per brick."""
    if not box > 0 or len(closes) < 2:
        return [], [], []
    top = bot = float(closes[0])
    trend = 0
    dirs, cls, rows = [], [], []
    for k in range(1, len(closes)):
        x = float(closes[k])
        while True:
            if trend >= 0 and x >= top + box:
                bot, top, trend = top, top + box, 1
                dirs.append(1), cls.append(top), rows.append(k)
            elif trend <= 0 and x <= bot - box:
                top, bot, trend = bot, bot - box, -1
                dirs.append(-1), cls.append(bot), rows.append(k)
            elif trend == 1 and x <= bot - box:
                top, bot, trend = bot, bot - box, -1
                dirs.append(-1), cls.append(bot), rows.append(k)
            elif trend == -1 and x >= top + box:
                bot, top, trend = top, top + box, 1
                dirs.append(1), cls.append(top), rows.append(k)
            else:
                break
    return dirs, cls, rows


def _renko_all(m, B, cache):
    key = ("renko_nj11",)
    if key in cache:
        return cache[key]
    b5 = B[5]
    a5 = ctx(m, B, 5, cache).atr(14)
    per_day = {}
    all_rows, all_cls, all_dirs = [], [], []
    for d in range(1, m.n_days):
        prev_last = int(b5.b1[d - 1]) - 1
        if prev_last < 0 or not np.isfinite(a5[prev_last]):
            continue
        box = float(a5[prev_last])
        a, z = int(m.d0[d]), int(m.d1[d])
        dirs, cls, rows = _renko_day(m.c[a:z], box)
        rows = [a + r for r in rows]
        per_day[d] = (box, dirs, cls, rows)
        all_rows += rows
        all_cls += cls
        all_dirs += dirs
    dirs = np.asarray(all_dirs, int)
    out = (per_day, _BrickBars(all_rows, all_cls), dirs)
    cache[key] = out
    return out


def nj11(m, B, p, cache):
    per_day, _, _ = _renko_all(m, B, cache)
    out = []
    for d, (box, dirs, cls, rows) in per_day.items():
        n = len(dirs)
        runs = []                                     # runs of bricks of one direction: [direction, brick indices]
        for k in range(n):
            if runs and runs[-1][0] == dirs[k]:
                runs[-1][1].append(k)
            else:
                runs.append([dirs[k], [k]])
        for ri in range(2, len(runs)):
            trend_run, pull_run, cur_run = runs[ri - 2], runs[ri - 1], runs[ri]
            side = trend_run[0]
            if cur_run[0] != side or len(trend_run[1]) < 3 or not 1 <= len(pull_run[1]) <= 2:
                continue
            top = max(cls[k] for k in trend_run[1]) if side > 0 else min(cls[k] for k in trend_run[1])
            for k in cur_run[1]:
                if (cls[k] > top) if side > 0 else (cls[k] < top):
                    row = rows[k]
                    t = int(m.ist[row])
                    if 9 * 60 + 20 <= t < 15 * 60:
                        ext = min(cls[q] for q in pull_run[1]) if side > 0 else max(cls[q] for q in pull_run[1])
                        stop = ext - side * 0.1 * box
                        out.append(Signal(int(m.day[row]), int(row), side, float(stop), "NJ11_RENKO"))
                    break
    out.sort(key=lambda s: s.k)
    return out


def nj11_x(m, B, p, cache):
    _, bricks, dirs = _renko_all(m, B, cache)
    return Exits(target_r=2.0, xbars=bricks, xlong=dirs < 0, xshort=dirs > 0)


# ── NJ-12 PVT cross of its EMA 20 (NSE 5-minute pool) ──────────────────────────────────

def _pvt(m, B, cache):
    key = ("pvt",)
    if key not in cache:
        c = ctx(m, B, 5, cache)
        pv = I.pvt(B[5].c, c.vol())
        cache[key] = (pv, I.ema(pv, 20))
    return cache[key]


def nj12(m, B, p, cache):
    b = B[5]
    pv, pe = _pvt(m, B, cache)
    a = ctx(m, B, 5, cache).atr(14)
    out = []
    for j in range(30, len(b.c) - 1):
        if b.day[j] != b.day[j - 1] or not in_window(b, j, 9 * 60 + 25, 14 * 60 + 45) or not np.isfinite(a[j]):
            continue
        if cross_up(pv, pe, j):
            out.append(sig(b, j, 1, b.c[j] - 1.5 * a[j], "NJ12_LONG"))
        elif cross_dn(pv, pe, j):
            out.append(sig(b, j, -1, b.c[j] + 1.5 * a[j], "NJ12_SHORT"))
    return out


def nj12_x(m, B, p, cache):
    pv, pe = _pvt(m, B, cache)
    up, dn = flags_cross(pv, pe)
    return Exits(target_r=None, xbars=B[5], xlong=dn, xshort=up)


# ── NJ-13 hammer after a fall, with volume (NSE 15-minute pool, long only) ─────────────

def nj13(m, B, p, cache):
    b = B[15]
    c = ctx(m, B, 15, cache)
    vol, va = c.vol(), c.vol_avg(20)
    out = []
    for j in range(25, len(b.c) - 1):
        if not in_window(b, j, 9 * 60 + 15, 14 * 60 + 45) or not np.isfinite(va[j]):
            continue
        r = rng(b, j)
        bd = body(b, j)
        if r <= 0 or bd < 0.05 * r or lw(b, j) < 2 * bd or uw(b, j) > 0.25 * r:
            continue
        if b.l[j] <= b.l[j - 9:j + 1].min() and vol[j] > va[j]:
            out.append(sig(b, j, 1, b.l[j], "NJ13_HAMMER"))
    return out


def nj13_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-14 Supertrend 21/1 + RSI and its SMA on the far side of 50 (NSE 5-minute pool) ──

def _nj14_ind(m, B, cache):
    key = ("nj14",)
    if key not in cache:
        c = ctx(m, B, 5, cache)
        _, dirn = c.supertrend(21, 1.0)
        r = c.rsi(14)
        rs = I.sma(r, 14)
        cache[key] = (dirn, r, rs)
    return cache[key]


def nj14(m, B, p, cache):
    b = B[5]
    dirn, r, rs = _nj14_ind(m, B, cache)
    out = []
    for j in range(40, len(b.c) - 1):
        if b.day[j] != b.day[j - 1] or not in_window(b, j, 9 * 60 + 25, 14 * 60 + 45) or not np.isfinite(rs[j]):
            continue
        if dirn[j] == 1 and dirn[j - 1] == -1 and r[j] < 50 and rs[j] < 50:
            out.append(sig(b, j, 1, b.c[j] * 0.98, "NJ14_LONG"))
        elif dirn[j] == -1 and dirn[j - 1] == 1 and r[j] > 50 and rs[j] > 50:
            out.append(sig(b, j, -1, b.c[j] * 1.02, "NJ14_SHORT"))
    return out


def nj14_x(m, B, p, cache):
    dirn, r, rs = _nj14_ind(m, B, cache)
    xl = (dirn == -1) | ((r > 50) & (rs > 50))
    xs = (dirn == 1) | ((r < 50) & (rs < 50))
    return Exits(target_r=None, xbars=B[5], xlong=xl, xshort=xs)


# ── NJ-15 three-touch level breakout with volume (NSE 5-minute pool) ───────────────────

def nj15(m, B, p, cache):
    b = B[5]
    c = ctx(m, B, 5, cache)
    a, vol, va = c.atr(14), c.vol(), c.vol_avg(20)
    ph, pl = c.fractals(2)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        done = False
        for j in rows:
            if done or not in_window(b, j, 9 * 60 + 45, 14 * 60 + 45):
                continue
            if not (np.isfinite(a[j]) and np.isfinite(va[j]) and vol[j] > va[j]):
                continue
            tol = 0.25 * a[j]
            highs = [q for q in rows if q <= j - 2 and ph[q]]
            lows = [q for q in rows if q <= j - 2 and pl[q]]
            for side, piv, vals in ((1, highs, b.h), (-1, lows, b.l)):
                if len(piv) < 3:
                    continue
                v = sorted(piv, key=lambda q: vals[q])
                best = None
                for s0 in range(len(v)):
                    grp = [q for q in v if 0 <= (vals[q] - vals[v[s0]]) <= tol]
                    if len(grp) >= 3 and min(grp) <= j - 6:
                        lvl = max(vals[q] for q in grp) if side > 0 else min(vals[q] for q in grp)
                        best = lvl if best is None else (max(best, lvl) if side > 0 else min(best, lvl))
                if best is None:
                    continue
                if side > 0 and b.c[j] > best and b.c[j - 1] <= best:
                    out.append(sig(b, j, 1, b.l[j], "NJ15_BREAKOUT"))
                    done = True
                    break
                if side < 0 and b.c[j] < best and b.c[j - 1] >= best:
                    out.append(sig(b, j, -1, b.h[j], "NJ15_BREAKDOWN"))
                    done = True
                    break
    return out


def nj15_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-16 double bottom / double top neckline break (BANKNIFTY 5-minute) ───────────────

def nj16(m, B, p, cache):
    b = B[5]
    c = ctx(m, B, 5, cache)
    a = c.atr(14)
    ph, pl = c.fractals(2)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        used = set()
        for j in rows:
            if not in_window(b, j, 9 * 60 + 45, 14 * 60 + 45) or not np.isfinite(a[j]):
                continue
            tol = 0.25 * a[j]
            for side in (1, -1):
                piv = pl if side > 0 else ph
                vals = b.l if side > 0 else b.h
                cand = [q for q in rows if q <= j - 2 and piv[q]]
                if len(cand) < 2:
                    continue
                q2 = cand[-1]
                if q2 in used or j - q2 > 20:
                    continue
                for q1 in reversed(cand[:-1]):
                    if q2 - q1 < 5 or abs(vals[q1] - vals[q2]) > tol:
                        continue
                    prior = vals[max(q1 - 20, 0):q1]
                    if len(prior) < 10:
                        continue
                    if side > 0 and not vals[q1] <= prior.min():
                        continue
                    if side < 0 and not vals[q1] >= prior.max():
                        continue
                    if side > 0:
                        neck = b.h[q1:q2 + 1].max()
                        if b.c[j] > neck and b.c[j - 1] <= neck:
                            height = neck - min(vals[q1], vals[q2])
                            out.append(sig(b, j, 1, b.l[j], "NJ16_W", target_px=float(neck + height)))
                            used.add(q2)
                    else:
                        neck = b.l[q1:q2 + 1].min()
                        if b.c[j] < neck and b.c[j - 1] >= neck:
                            height = max(vals[q1], vals[q2]) - neck
                            out.append(sig(b, j, -1, b.h[j], "NJ16_M", target_px=float(neck - height)))
                            used.add(q2)
                    break
    return out


def nj16_x(m, B, p, cache):
    return Exits(target_r=None)


# ── NJ-17 "Day Sniper": gap, limit at the first 15-minute close (NSE 15-minute pool) ───

def nj17(m, B, p, cache):
    b = B[15]
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        j = first_bar(b, d)
        if j + 1 >= b.b1[d] or b.ist0[j] != 9 * 60 + 15:
            continue
        pc = prev_close(m, d)
        if b.l[j] > pc:
            out.append(sig(b, j, 1, b.l[j] * (1 - 0.0005), "NJ17_GAPUP", entry_limit=float(b.c[j]), expire_k=int(b.i1[j + 1])))
        elif b.h[j] < pc:
            out.append(sig(b, j, -1, b.h[j] * (1 + 0.0005), "NJ17_GAPDOWN", entry_limit=float(b.c[j]), expire_k=int(b.i1[j + 1])))
    return out


def nj17_x(m, B, p, cache):
    return Exits(target_r=None)


# ── NJ-18 gap of 0.3% + first 15-minute range breakout (NSE 15-minute pool) ────────────

def nj18(m, B, p, cache):
    b = B[15]
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        j = first_bar(b, d)
        last = last_bar_before(b, d, 14 * 60 + 30)
        if last is None or last <= j or b.ist0[j] != 9 * 60 + 15:
            continue
        g = b.o[j] / prev_close(m, d) - 1
        if g >= 0.003:
            out.append(sig(b, j, 1, b.l[j], "NJ18_GAPUP", entry_stop=float(b.h[j]), expire_k=int(b.i1[last])))
        elif g <= -0.003:
            out.append(sig(b, j, -1, b.h[j], "NJ18_GAPDOWN", entry_stop=float(b.l[j]), expire_k=int(b.i1[last])))
    return out


def nj18_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-19 EMA 50/200 cross with volume, daily (NSE daily pool, long only) ──────────────

def _value(m):
    v = getattr(m, "value", None)
    return None if v is None else np.asarray(v, float)


def nj19(m, B, p, cache):
    b = B[1]
    c = ctx(m, B, 1, cache)
    e50, e200, a = c.ema(50), c.ema(200), c.atr(14)
    val = _value(m)
    liq = getattr(m, "liquid", np.ones(len(b.c), bool))
    if val is None:
        return []
    va = I.mean_prev(val, 20)
    out = []
    for j in range(210, len(b.c)):
        if liq[j] and cross_up(e50, e200, j) and np.isfinite(va[j]) and val[j] > va[j] and np.isfinite(a[j]):
            out.append(sig(b, j, 1, b.c[j] - 2 * a[j], "NJ19_GOLDEN"))
    return out


def nj19_x(m, B, p, cache):
    c = ctx(m, B, 1, cache)
    _, dn = flags_cross(c.ema(50), c.ema(200))
    return Exits(target_r=None, xbars=B[1], xlong=dn, xshort=np.zeros(len(dn), bool))


# ── NJ-20 200-DMA cross candidates from the top 100 by turnover (NSE 5-minute pool) ────

def nj20_context(daily_markets, since: str | None = None, symbols: set | None = None) -> dict:
    """The candidates' inputs from NSE daily rows, keyed by session date: ctx["daily"][symbol][date] = (close, SMA 10,
    30, 60, 90, 120, 200, daily ATR 14) at that session's close; ctx["top100"][date] = the 100 symbols with the
    highest traded value that session (ranked over every daily market). A 5-minute session reads the entries of the
    session before it. `since` (ISO date) and `symbols` keep only the sessions and stocks a book will read (the averages
    still use the whole history)."""
    daily, by_date = {}, {}
    for m in daily_markets:
        c = np.asarray(m.c, float)
        val = _value(m)
        if val is None or len(c) < 2:
            continue
        j0 = 0 if since is None else int(np.searchsorted(m.date, np.datetime64(since)))
        if j0 >= len(c):
            continue
        keep = symbols is None or m.name in symbols
        if keep:
            s = [I.sma(c, n) for n in (10, 30, 60, 90, 120, 200)]
            pc = np.r_[c[0], c[:-1]]
            a = I.rma(np.maximum(m.h, pc) - np.minimum(m.l, pc), 14)
        rows = {}
        for j in range(j0, len(c)):
            key = str(m.date[j])
            if keep:
                rows[key] = (float(c[j]), *(float(x[j]) for x in s), float(a[j]))
            by_date.setdefault(key, []).append((float(val[j]), m.name))
        if keep:
            daily[m.name] = rows
    top = {d: {sym for _, sym in sorted(v, reverse=True)[:100]} for d, v in by_date.items()}
    return {"daily": daily, "top100": top}


def nj20(m, B, p, cache):
    """p["ctx"] = nj20_context(...) of the NSE daily pool."""
    cx = p.get("ctx") or {}
    daily = (cx.get("daily") or {}).get(m.name)
    top = cx.get("top100") or {}
    if not daily:
        return []
    b = B[5]
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        key = str(m.date[d - 1])                  # the previous session's daily close fixes today's candidates
        row = daily.get(key)
        if row is None or m.name not in top.get(key, ()):
            continue
        pc, s10, s30, s60, s90, s120, s200, datr = row
        if not all(np.isfinite(x) for x in row):
            continue
        j = first_bar(b, d)
        last = last_bar_before(b, d, 14 * 60 + 30)
        if last is None or b.ist0[j] != 9 * 60 + 15:
            continue
        sig_bar = j - 1                           # orders start with the session: stamp on the previous day's last bar
        if sig_bar < 0 or b.day[sig_bar] == d:
            continue
        shorter = (s10, s30, s60, s90, s120)
        if all(pc > s for s in shorter) and pc < s200:
            out.append(Signal(d, int(b.i1[sig_bar]), 1, float(s200 - 0.5 * datr), "NJ20_200DMA_UP",
                              entry_stop=float(s200), expire_k=int(b.i1[last])))
        elif all(pc < s for s in shorter) and pc > s200:
            out.append(Signal(d, int(b.i1[sig_bar]), -1, float(s200 + 0.5 * datr), "NJ20_200DMA_DOWN",
                              entry_stop=float(s200), expire_k=int(b.i1[last])))
    return out


def nj20_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-21 EMA 5/20 cross scalp, 10-minute time stop (NIFTY 1-minute) ───────────────────

def nj21(m, B, p, cache):
    b = B[1]
    c = ctx(m, B, 1, cache)
    e5, e20 = c.ema(5), c.ema(20)
    out = []
    for j in range(30, len(b.c) - 1):
        if b.day[j] != b.day[j - 4] or not in_window(b, j, 9 * 60 + 20, 15 * 60):
            continue
        if cross_up(e5, e20, j):
            out.append(sig(b, j, 1, b.l[j - 4:j + 1].min(), "NJ21_LONG"))
        elif cross_dn(e5, e20, j):
            out.append(sig(b, j, -1, b.h[j - 4:j + 1].max(), "NJ21_SHORT"))
    return out


def nj21_x(m, B, p, cache):
    return Exits(target_r=1.0, max_hold=10)


# ── NJ-22 MACD + Stochastic 50 + Parabolic SAR (BANKNIFTY 5-minute) ────────────────────

def _nj22_ind(m, B, cache):
    key = ("nj22",)
    if key not in cache:
        b = B[5]
        line, sg, _ = ctx(m, B, 5, cache).macd()
        K, D = _stoch(m, B, 5, cache)
        sar, tr = I.psar(b)
        up, dn = flags_cross(line, sg)
        cache[key] = (line, sg, K, D, sar, tr, up, dn)
    return cache[key]


def nj22(m, B, p, cache):
    b = B[5]
    line, sg, K, D, sar, tr, up, dn = _nj22_ind(m, B, cache)

    def long_ok(j):
        return line[j] > sg[j] and K[j] > 50 and D[j] > 50 and tr[j] == 1 and sar[j] < b.l[j]

    def short_ok(j):
        return line[j] < sg[j] and K[j] < 50 and D[j] < 50 and tr[j] == -1 and sar[j] > b.h[j]

    out = []
    for j in range(40, len(b.c) - 1):
        if b.day[j] != b.day[j - 3] or not in_window(b, j, 9 * 60 + 25, 14 * 60 + 45):
            continue
        if long_ok(j) and not long_ok(j - 1) and up[j - 2:j + 1].any():
            out.append(sig(b, j, 1, sar[j], "NJ22_LONG"))
        elif short_ok(j) and not short_ok(j - 1) and dn[j - 2:j + 1].any():
            out.append(sig(b, j, -1, sar[j], "NJ22_SHORT"))
    return out


def nj22_x(m, B, p, cache):
    b = B[5]
    line, sg, K, D, sar, tr, _, _ = _nj22_ind(m, B, cache)
    fail_long = ~((line > sg) & (K > 50) & (D > 50) & (tr == 1))
    fail_short = ~((line < sg) & (K < 50) & (D < 50) & (tr == -1))
    return Exits(target_r=None, xbars=b, xlong=fail_long, xshort=fail_short)


# ── NJ-23 harami with a confirmation candle (NIFTY 5-minute) ───────────────────────────

def nj23(m, B, p, cache):
    b = B[5]
    c = ctx(m, B, 5, cache)
    e20, ba = c.ema(20), c.body_avg(20)
    out = []
    for j in range(25, len(b.c) - 2):
        if not np.isfinite(ba[j]):
            continue
        big = body(b, j) >= 1.2 * ba[j]
        if not big:
            continue
        k = j + 1
        if b.day[k] != b.day[j]:
            continue
        top_j, bot_j = max(b.o[j], b.c[j]), min(b.o[j], b.c[j])
        inside = max(b.o[k], b.c[k]) <= top_j and min(b.o[k], b.c[k]) >= bot_j
        if not inside:
            continue
        for q in range(k + 1, min(k + 4, len(b.c))):
            if b.day[q] != b.day[j] or not in_window(b, q, 9 * 60 + 25, 14 * 60 + 45):
                break
            if red(b, j) and b.c[j] < e20[j] and green(b, k) and green(b, q) and b.c[q] > b.h[j]:
                out.append(sig(b, q, 1, b.l[j], "NJ23_BULL_HARAMI"))
                break
            if green(b, j) and b.c[j] > e20[j] and red(b, k) and red(b, q) and b.c[q] < b.l[j]:
                out.append(sig(b, q, -1, b.h[j], "NJ23_BEAR_HARAMI"))
                break
    return out


def nj23_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-24 ascending triangle breakout, daily (NSE daily pool, long only) ───────────────

def nj24(m, B, p, cache):
    b = B[1]
    c = ctx(m, B, 1, cache)
    ph, pl = c.fractals(1)
    s50 = c.sma(50)
    liq = getattr(m, "liquid", np.ones(len(b.c), bool))
    n = len(b.c)
    out = []
    used = set()
    highs = [q for q in range(n) if ph[q]]
    lows = [q for q in range(n) if pl[q]]
    for j in range(60, n):
        if not liq[j]:
            continue
        known_h = [q for q in highs if q <= j - 1 and j - q <= 75]
        known_l = [q for q in lows if q <= j - 1 and j - q <= 75]
        if len(known_h) < 2 or len(known_l) < 2:
            continue
        r2 = known_h[-1]
        if r2 in used or j - r2 > 15:
            continue
        for r1 in reversed(known_h[:-1]):
            if not (10 <= r2 - r1 <= 60) or abs(b.h[r1] / b.h[r2] - 1) > 0.015:
                continue
            s1c = [q for q in known_l if r1 < q < r2]
            s2c = [q for q in known_l if r2 < q <= j - 1]
            if not s1c or not s2c:
                continue
            s1 = min(s1c, key=lambda q: b.l[q])
            s2 = s2c[-1]
            if not b.l[s2] >= b.l[s1] * 1.01 or not (np.isfinite(s50[r1]) and b.c[r1] > s50[r1]):
                continue
            res = max(b.h[r1], b.h[r2])
            if b.c[j] > res and b.c[j - 1] <= res:
                out.append(sig(b, j, 1, b.l[j], "NJ24_ASC_TRIANGLE", info={"height": float(res - b.l[s1])},
                               target_px=float(b.c[j] + (res - b.l[s1]))))
                used.add(r2)
            break
    return out


def nj24_x(m, B, p, cache):
    return Exits(target_r=None, max_hold=30)


# ── NJ-25 BTST momentum basket (NSE daily pool): bought at the close, sold at the next open ─────────

def nj25_trades(markets, strategy: str = "NJ-25", engines: dict | None = None) -> dict:
    """{symbol: [Trade]} for the whole pool. Each session the basket is the 5 liquid stocks with the highest 20-day
    return among those whose close was above SMA 50, all measured at the previous session's close; each is bought at
    this session's close and sold at the next session's open (a basket bought on the last session in the data is
    still open, marked at that close). The unit is 3 x the previous session's daily ATR 14 (sizing only)."""
    from yc_engine import _leg, _market_at, xengine
    by_date: dict = {}
    info = {}
    for m in markets:
        c = np.asarray(m.c, float)
        if len(c) < 60:
            continue
        ret = np.full(len(c), np.nan)
        ret[20:] = c[20:] / c[:-20] - 1
        s50 = I.sma(c, 50)
        pc = np.r_[c[0], c[:-1]]
        a = I.rma(np.maximum(m.h, pc) - np.minimum(m.l, pc), 14)
        liq = getattr(m, "liquid", np.ones(len(c), bool))
        info[m.name] = (m, a)
        for j in range(1, len(c)):
            if liq[j] and np.isfinite(s50[j - 1]) and c[j - 1] > s50[j - 1] and np.isfinite(ret[j - 1]) and np.isfinite(a[j - 1]):
                by_date.setdefault(str(m.date[j]), []).append((float(ret[j - 1]), m.name, j))
    out: dict = {}
    engines = engines if engines is not None else {}
    for day, cands in sorted(by_date.items()):
        for _, sym, j in sorted(cands, key=lambda x: (-x[0], x[1]))[:5]:
            m, a = info[sym]
            eng = engines.setdefault(sym, xengine(m))
            last = len(m.c) - 1
            px_in = _market_at(eng, j, 1, float(m.c[j]))
            if j < last:
                k_out, px_out, why = j + 1, _market_at(eng, j + 1, -1, float(m.o[j + 1])), "next_open"
            else:
                k_out, px_out, why = j, float(m.c[j]), "time"
            t = _leg(eng, strategy, "NJ25_BTST", j, 1, j, px_in, k_out, px_out, why, 3.0 * float(a[j - 1]), True, why != "time")
            out.setdefault(sym, []).append(t)
    return out


# ── NJ-46 EMA 10/20 cross with a Marubozu candle, Anant Ladha (NSE daily pool, long only) ───────────

def nj46(m, B, p, cache):
    b = B[1]
    c = ctx(m, B, 1, cache)
    e10, e20, a = c.ema(10), c.ema(20), c.atr(14)
    up, _ = flags_cross(e10, e20)
    liq = getattr(m, "liquid", np.ones(len(b.c), bool))
    n = len(b.c)
    out = []
    for j in range(25, n):
        if not (liq[j] and np.isfinite(a[j])):
            continue
        r = rng(b, j)
        if not (green(b, j) and r > 0 and body(b, j) >= 0.7 * r and r >= a[j]):
            continue
        if not (up[j - 2:j + 1].any() and e10[j] > e20[j]):
            continue
        out.append(sig(b, j, 1, b.l[j], "NJ46_MARUBOZU", entry_stop=float(b.h[j]), expire_k=int(b.i1[min(j + 3, n - 1)])))
    return out


def nj46_x(m, B, p, cache):
    _, dn = flags_cross(ctx(m, B, 1, cache).ema(10), ctx(m, B, 1, cache).ema(20))
    return Exits(target_r=3.0, xbars=B[1], xlong=dn, xshort=np.zeros(len(dn), bool), max_hold=40)


# ── NJ-26 EMA 50 cross on Heikin Ashi with volume and RSI 50 (NSE daily pool, long only) ──

def _nj26_ind(m, B, cache):
    key = ("nj26",)
    if key not in cache:
        b = B[1]
        hb = I.HABars(b)
        e50 = I.ema(hb.c, 50)
        e20 = I.ema(hb.c, 20)
        r = I.rsi(hb.c, 14)
        cache[key] = (hb, e50, e20, r)
    return cache[key]


def nj26(m, B, p, cache):
    b = B[1]
    hb, e50, e20, r = _nj26_ind(m, B, cache)
    val = _value(m)
    liq = getattr(m, "liquid", np.ones(len(b.c), bool))
    if val is None:
        return []
    va = I.mean_prev(val, 20)
    out = []
    for j in range(60, len(b.c) - 1):
        if not liq[j] or not np.isfinite(va[j]):
            continue
        if hb.c[j] > hb.o[j] and hb.c[j] > e50[j] and hb.c[j - 1] <= e50[j - 1] and val[j] > va[j] and r[j] > 50:
            last = min(j + 3, len(b.c) - 1)
            out.append(sig(b, j, 1, b.l[j], "NJ26_HA_EMA50", entry_stop=float(hb.c[j]), expire_k=int(b.i1[last])))
    return out


def nj26_x(m, B, p, cache):
    hb, _, e20, r = _nj26_ind(m, B, cache)
    xl = (hb.c < e20) | (r < 50)
    return Exits(target_r=None, xbars=B[1], xlong=xl, xshort=np.zeros(len(xl), bool))
