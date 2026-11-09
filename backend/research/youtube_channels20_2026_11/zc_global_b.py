"""Crypto and gold strategies of the 20-channel study, part B: TradingLab's Bollinger/RSI (TL-02), Devansh Rai (DR),
The Trading School's gold and bitcoin rules (TS-04, TS-05), Priyank's bitcoin SMC scalp (PV-04), TRADING RUSH (RU),
Pro Trading School (PT), Transparent Fx Academy (TF), Trading Data (TD), Faiz SMC (FZ) and Mulham Trading (MH).
Rules: analyses/<channel>.md ("Code [A]" lines). Conventions as in zc_common."""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import (bars_of_day, bear_engulf, body, bull_engulf, ctx, flags_cross, green, last_done,  # noqa: F401
                       red, rng, sig)
from yc_engine import XExits
from yt_engine import Exits

import zc_common as Z
from zc_common import sorted_out
from zc_global_a import clusters, gap_dn, gap_up, htf_above_ema, recent_extreme, swing_trend_at, utc_min


# ═══ TradingLab: TL-02 ═════════════════════════════════════════════════════════════════════

def tl02(m, B, p, cache):
    """Bollinger (30, 2) + RSI (13): a close beyond the band with RSI past 25/75 -> back to the middle band; squeezes
    skipped; stop 2 ATR (assumed)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    mid, upb, lob = c.bollinger(30, 2.0)
    rsi, a = c.rsi(13), c.atr(14)
    width = (upb - lob) / mid
    out = []
    for j in range(130, len(b.c)):
        if not (np.isfinite(width[j]) and np.isfinite(a[j]) and np.isfinite(rsi[j])):
            continue
        w = width[j - 99:j + 1]
        if np.isfinite(w).sum() < 50 or width[j] < np.nanpercentile(w, 20):
            continue
        if b.c[j] < lob[j] and rsi[j] < 25:
            out.append(sig(b, j, 1, float(b.c[j] - 2 * a[j]), "TL02_BB_RSI_LONG", target_px=float(mid[j]),
                           info={"stop_dist": float(2 * a[j])}))
        elif b.c[j] > upb[j] and rsi[j] > 75:
            out.append(sig(b, j, -1, float(b.c[j] + 2 * a[j]), "TL02_BB_RSI_SHORT", target_px=float(mid[j]),
                           info={"stop_dist": float(2 * a[j])}))
    return sorted_out(out)


def tgt_x(m, B, p, cache):
    return Exits(target_r=None)


# ═══ Devansh Rai ═══════════════════════════════════════════════════════════════════════════

def _tl_breaks(b, piv_h, piv_l, e200, j_lo, j_hi, min_risk, a):
    """Trend-line breakouts on b between bars j_lo..j_hi: for buys (close above EMA 200) the line through the last two
    confirmed, falling swing highs of the pullback; a close through it. Yields (bar, side, stop)."""
    for j in range(max(j_lo, 3), j_hi):
        if not np.isfinite(e200[j]) or not np.isfinite(a[j]):
            continue
        side = 1 if b.c[j] > e200[j] else -1
        piv = piv_h if side > 0 else piv_l
        k = int(np.searchsorted(piv, j - 2, "right"))
        if k < 2:
            continue
        q1, q2 = int(piv[k - 2]), int(piv[k - 1])
        v1, v2 = (b.h[q1], b.h[q2]) if side > 0 else (b.l[q1], b.l[q2])
        if (v2 - v1) * side >= 0 or j - q1 > 80:
            continue
        # both swings after the latest close on the other side of the EMA 200
        if np.any((b.c[q1:j] - e200[q1:j]) * side <= 0):
            continue
        slope = (v2 - v1) / (q2 - q1)
        line_j, line_p = v2 + slope * (j - q2), v2 + slope * (j - 1 - q2)
        if (b.c[j] - line_j) * side > 0 and (b.c[j - 1] - line_p) * side <= 0:
            ext = float(b.l[j]) if side > 0 else float(b.h[j])
            dist = max(abs(float(b.c[j]) - ext), min_risk * a[j])
            yield j, side, float(b.c[j]) - side * dist, dist


def dr01(m, B, p, cache):
    """EMA 200 side on 15 minutes + a counter-trend-line breakout; stop under the breakout candle; 1:2."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e200, a = c.ema(200), c.atr(14)
    ph, pl = (np.flatnonzero(x) for x in c.fractals(2))
    out = []
    for j, side, stop, dist in _tl_breaks(b, ph, pl, e200, 205, len(b.c), 0.2, a):
        out.append(sig(b, j, side, stop, "DR01_EMA200_TL_LONG" if side > 0 else "DR01_EMA200_TL_SHORT", info={"stop_dist": dist}))
    return sorted_out(out)


def dr02(m, B, p, cache):
    """Gold 1-minute: the 15-minute EMA 200 side (0.2% clear of it), a 1-minute dip through the 1-minute EMA 200 and a
    close back -> enter; stop under the last 15 bars; 1:2."""
    b, b15 = B[1], B[15]
    c = ctx(m, B, 1, cache)
    e200, a = c.ema(200), c.atr(14)
    e15 = ctx(m, B, 15, cache).ema(200)
    out = []
    for j in range(220, len(b.c)):
        if not (np.isfinite(e200[j]) and np.isfinite(a[j])):
            continue
        for side in (1, -1):
            if not ((b.c[j] - e200[j]) * side > 0 and (b.c[j - 1] - e200[j - 1]) * side <= 0):
                continue
            wrong = np.any((b.c[j - 15:j] - e200[j - 15:j]) * side < 0)
            if not wrong:
                continue
            h = last_done(b15, int(b.i1[j]))
            if h < 0 or not np.isfinite(e15[h]):
                continue
            if (b15.c[h] - e15[h]) * side <= 0 or abs(b15.c[h] / e15[h] - 1) < 0.002:
                continue
            ext = recent_extreme(b, j, 15, side)
            out.append(sig(b, j, side, float(ext - side * 0.1 * a[j]), "DR02_1M_RECLAIM_LONG" if side > 0 else "DR02_1M_RECLAIM_SHORT"))
    return sorted_out(out)


def dr03(m, B, p, cache):
    """5 EMA "candle that does not touch" on 15 minutes, both ways: the next candle closes beyond it -> enter; 1:2."""
    b = B[15]
    e5 = ctx(m, B, 15, cache).ema(5)
    out = []
    for j in range(10, len(b.c)):
        q = j - 1
        if b.l[q] > e5[q] and b.c[j] < b.l[q]:
            out.append(sig(b, j, -1, float(b.h[q]), "DR03_5EMA_SHORT"))
        elif b.h[q] < e5[q] and b.c[j] > b.h[q]:
            out.append(sig(b, j, 1, float(b.l[q]), "DR03_5EMA_LONG"))
    return sorted_out(out)


def dr04(m, B, p, cache):
    """A 15-minute momentum candle (range >= 2%) in the 15-minute EMA 200 direction, then 1-minute trend-line breaks its
    way within 2 hours; stop at the breakout candle; 1:2 (ether)."""
    b, b15 = B[1], B[15]
    c1 = ctx(m, B, 1, cache)
    e1, a1 = c1.ema(200), c1.atr(14)
    ph, pl = (np.flatnonzero(x) for x in c1.fractals(2))
    e15 = ctx(m, B, 15, cache).ema(200)
    out = []
    for h in range(201, len(b15.c)):
        r = (b15.h[h] - b15.l[h]) / b15.c[h]
        if r < 0.02 or not np.isfinite(e15[h]):
            continue
        side = 1 if (green(b15, h) and b15.c[h] > e15[h]) else (-1 if (red(b15, h) and b15.c[h] < e15[h]) else 0)
        if not side:
            continue
        j0 = int(np.searchsorted(b.i1, int(b15.i1[h]), "right"))
        for j, s2, stop, dist in _tl_breaks(b, ph, pl, e1, j0, min(j0 + 120, len(b.c)), 0.2, a1):
            if s2 == side:
                out.append(sig(b, j, side, stop, "DR04_MOMENTUM_TL_LONG" if side > 0 else "DR04_MOMENTUM_TL_SHORT",
                               info={"stop_dist": dist, "group": f"dr04-{h}"}))
    return sorted_out(out)


# ═══ The Trading School: gold and bitcoin ══════════════════════════════════════════════════

def ts04(m, B, p, cache):
    """Gold: the previous day's wick zones (the mother candle on an inside day); a 15-minute sweep of the prior candle
    inside the zone, then a close through the sweep candle within 4 bars -> enter; stop beyond the sweep; 1:2."""
    b = B[15]
    out = []
    for d in range(2, m.n_days):
        if not m.prev_ok[d]:
            continue
        o1, h1, l1, c1 = Z_day(m, d - 1)
        o0, h0, l0, c0 = Z_day(m, d - 2)
        if h1 <= h0 and l1 >= l0 and m.prev_ok[d - 1]:
            o1, h1, l1, c1 = o0, h0, l0, c0                     # inside day: the mother candle's wicks
        sup_lo, sup_hi = max(o1, c1), h1                         # supply zone: the upper wick
        dem_lo, dem_hi = l1, min(o1, c1)                         # demand zone: the lower wick
        rows = list(bars_of_day(b, d))
        for i, j in enumerate(rows[1:-1], start=1):
            q = rows[i - 1]
            if b.h[j] > b.h[q] and b.c[j] < b.h[q] and sup_lo <= b.h[j] <= sup_hi:
                for t in rows[i + 1:i + 5]:
                    if b.h[t] > b.h[j]:
                        break
                    if b.c[t] < b.l[j]:
                        out.append(sig(b, t, -1, float(b.h[j]), "TS04_GOLD_SUPPLY_SWEEP_SHORT"))
                        break
            elif b.l[j] < b.l[q] and b.c[j] > b.l[q] and dem_lo <= b.l[j] <= dem_hi:
                for t in rows[i + 1:i + 5]:
                    if b.l[t] < b.l[j]:
                        break
                    if b.c[t] > b.h[j]:
                        out.append(sig(b, t, 1, float(b.l[j]), "TS04_GOLD_DEMAND_SWEEP_LONG"))
                        break
    return sorted_out(out)


def Z_day(m, d):
    a, z = int(m.d0[d]), int(m.d1[d])
    return float(m.o[a]), float(m.h[a:z].max()), float(m.l[a:z].min()), float(m.c[z - 1])


def ts05(m, B, p, cache):
    """Bitcoin 1-minute Fibonacci: an impulse of at least 0.4% between confirmed swings (fractal 5); a pullback into the
    0.5-0.786 band, then a close back beyond the 0.5 level -> enter; stop beyond the pullback; 1:1; 60 bars."""
    b = B[1]
    c = ctx(m, B, 1, cache)
    a = c.atr(14)
    ph, pl = c.fractals(5)
    H = np.flatnonzero(ph)
    L = np.flatnonzero(pl)
    n = len(b.c)
    out = []
    for side, A_, Bp in ((-1, H, L), (1, L, H)):
        # side -1: a fall from a swing high to a later swing low; trade the pullback short
        for q2 in Bp:
            q2 = int(q2)
            k = int(np.searchsorted(A_, q2, "left")) - 1
            if k < 0:
                continue
            q1 = int(A_[k])
            if q2 - q1 > 240:
                continue
            top, bot = (float(b.h[q1]), float(b.l[q2])) if side < 0 else (float(b.h[q2]), float(b.l[q1]))
            if (top - bot) / bot < 0.004:
                continue
            if side < 0:
                f50, f786 = bot + 0.5 * (top - bot), bot + 0.786 * (top - bot)
            else:
                f50, f786 = top - 0.5 * (top - bot), top - 0.786 * (top - bot)
            touched = False
            ext = None
            for j in range(q2 + 5, min(q2 + 65, n)):
                if b.day[j] != b.day[q2] or not np.isfinite(a[j]):
                    break
                if (side < 0 and b.h[j] > top) or (side > 0 and b.l[j] < bot) or \
                        (side < 0 and b.l[j] < bot) or (side > 0 and b.h[j] > top):
                    break
                ext = (max(ext, float(b.h[j])) if ext is not None else float(b.h[j])) if side < 0 else \
                      (min(ext, float(b.l[j])) if ext is not None else float(b.l[j]))
                if (side < 0 and b.h[j] >= f50) or (side > 0 and b.l[j] <= f50):
                    touched = True
                if touched and ((side < 0 and b.c[j] < f50) or (side > 0 and b.c[j] > f50)):
                    stop = ext + 0.1 * a[j] if side < 0 else ext - 0.1 * a[j]
                    if (side < 0 and ext > f786 + 0.25 * (top - bot)) or (side > 0 and ext < f786 - 0.25 * (top - bot)):
                        break
                    out.append(sig(b, j, side, float(stop), "TS05_FIB_SHORT" if side < 0 else "TS05_FIB_LONG"))
                    break
    return sorted_out(out)


def r1_x(m, B, p, cache):
    return Exits(target_r=1.0)


# ═══ HOLD with Priyank: bitcoin SMC scalp ══════════════════════════════════════════════════

def pv04(m, B, p, cache):
    """No-bias SMC scalp (bitcoin): the previous day's high / low; two 1-hour candles at a level (fake-out -> reversal,
    two closes beyond -> breakout); then a 15-minute sweep of the last 12 bars and two closes over the last swing ->
    enter; half at 1.5R, the rest at 2.5R with the stop to entry."""
    b, bh = B[15], B[60]
    a = ctx(m, B, 15, cache).atr(14)
    hv, _, lv, _, _, _ = ctx(m, B, 15, cache).pivots(2)
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        a0, z0 = int(m.d0[d - 1]), int(m.d1[d - 1])
        PH, PL = float(m.h[a0:z0].max()), float(m.l[a0:z0].min())
        hrs = list(bars_of_day(bh, d))
        bias, since_row = 0, None
        for i in range(1, len(hrs)):
            x, y = hrs[i - 1], hrs[i]
            if bh.h[x] > PH and bh.c[x] > PH and bh.c[y] > PH:
                bias, since_row = 1, int(bh.i1[y])
            elif bh.l[x] < PL and bh.c[x] < PL and bh.c[y] < PL:
                bias, since_row = -1, int(bh.i1[y])
            elif bh.h[x] > PH and bh.c[y] < PH:
                bias, since_row = -1, int(bh.i1[y])
            elif bh.l[x] < PL and bh.c[y] > PL:
                bias, since_row = 1, int(bh.i1[y])
            if bias:
                break
        if not bias:
            continue
        rows = [j for j in bars_of_day(b, d) if int(b.i0[j]) > since_row]
        swept = None
        for j in rows:
            if j < 14 or not np.isfinite(a[j]):
                continue
            if swept is None:
                if bias > 0 and b.l[j] < b.l[j - 12:j].min():
                    swept = float(b.l[j])
                elif bias < 0 and b.h[j] > b.h[j - 12:j].max():
                    swept = float(b.h[j])
                continue
            swept = min(swept, float(b.l[j])) if bias > 0 else max(swept, float(b.h[j]))
            lvl = hv[j] if bias > 0 else lv[j]
            if not np.isfinite(lvl):
                continue
            if (b.c[j] - lvl) * bias > 0 and (b.c[j - 1] - lvl) * bias > 0:
                stop = swept - bias * 0.1 * a[j]
                risk = abs(float(b.c[j]) - stop)
                out.append(sig(b, j, bias, float(stop), "PV04_SMC_LONG" if bias > 0 else "PV04_SMC_SHORT",
                               info={"partial_px": float(b.c[j] + bias * 1.5 * risk)}))
                break
    return sorted_out(out)


def pv04_x(m, B, p, cache):
    return XExits(target_r=2.5, partial_px=True)


# ═══ TRADING RUSH ══════════════════════════════════════════════════════════════════════════

def ru01(m, B, p, cache):
    """MACD crossover below (above) zero in the EMA 200 trend, 10-bar swing stop, 1.5R (1-hour)."""
    b = B[60]
    c = ctx(m, B, 60, cache)
    line, sgl, _ = c.macd()
    up, dn = flags_cross(line, sgl)
    e200 = c.ema(200)
    out = []
    for j in range(205, len(b.c)):
        if up[j] and line[j] < 0 and sgl[j] < 0 and b.c[j] > e200[j]:
            out.append(sig(b, j, 1, recent_extreme(b, j, 10, 1), "RU01_MACD_LONG"))
        elif dn[j] and line[j] > 0 and sgl[j] > 0 and b.c[j] < e200[j]:
            out.append(sig(b, j, -1, recent_extreme(b, j, 10, -1), "RU01_MACD_SHORT"))
    return sorted_out(out)


def ru02(m, B, p, cache):
    """Stochastic %K below 20, then the next bullish MACD cross within 20 bars with %K still below 80; 1.5R (30-minute)."""
    b = B[30]
    c = ctx(m, B, 30, cache)
    K, _ = c._get(("stoch", 14, 3, 3), lambda: I.stochastic(b, 14, 3, 3))
    line, sgl, _ = c.macd()
    up, dn = flags_cross(line, sgl)
    out = []
    os_ = ob_ = -1000
    for j in range(40, len(b.c)):
        if np.isfinite(K[j]):
            if K[j] < 20:
                os_ = j
            if K[j] > 80:
                ob_ = j
        if up[j] and 0 < j - os_ <= 20 and K[j] < 80:
            out.append(sig(b, j, 1, recent_extreme(b, j, 10, 1), "RU02_STOCH_MACD_LONG"))
            os_ = -1000
        elif dn[j] and 0 < j - ob_ <= 20 and K[j] > 20:
            out.append(sig(b, j, -1, recent_extreme(b, j, 10, -1), "RU02_STOCH_MACD_SHORT"))
            ob_ = -1000
    return sorted_out(out)


def ru03(m, B, p, cache):
    """"Opposite RSI": RSI crosses above 70 (below 30) with ADX above 25 in the EMA 200 trend; stop beyond EMA 21; 1.5R."""
    b = B[30]
    c = ctx(m, B, 30, cache)
    rsi, e200, e21, a = c.rsi(14), c.ema(200), c.ema(21), c.atr(14)
    adx, _, _ = c._get(("adx", 14), lambda: I.adx(b, 14))
    out = []
    for j in range(205, len(b.c)):
        if not (np.isfinite(adx[j]) and np.isfinite(a[j])) or adx[j] <= 25:
            continue
        if rsi[j - 1] <= 70 < rsi[j] and b.c[j] > e200[j]:
            stop = e21[j] - 0.1 * a[j]
            if b.c[j] - stop >= 0.3 * a[j]:
                out.append(sig(b, j, 1, float(stop), "RU03_RSI_ADX_LONG"))
        elif rsi[j - 1] >= 30 > rsi[j] and b.c[j] < e200[j]:
            stop = e21[j] + 0.1 * a[j]
            if stop - b.c[j] >= 0.3 * a[j]:
                out.append(sig(b, j, -1, float(stop), "RU03_RSI_ADX_SHORT"))
    return sorted_out(out)


def ru04(m, B, p, cache):
    """Williams fractal breakout in the 200 MA trend: a close above the latest up-fractal candle's high, stop at the latest
    down-fractal low; 1.5R (30-minute)."""
    b = B[30]
    c = ctx(m, B, 30, cache)
    e200 = c.ema(200)
    hv, hi, lv, li, _, _ = c.pivots(2)
    out = []
    for j in range(205, len(b.c)):
        if not (np.isfinite(hv[j]) and np.isfinite(lv[j])):
            continue
        if b.c[j] > e200[j] and b.c[j] > hv[j] and b.c[j - 1] <= hv[j] and b.c[hi[j]] > e200[hi[j]] and lv[j] < b.c[j]:
            out.append(sig(b, j, 1, float(lv[j]), "RU04_FRACTAL_LONG"))
        elif b.c[j] < e200[j] and b.c[j] < lv[j] and b.c[j - 1] >= lv[j] and b.c[li[j]] < e200[li[j]] and hv[j] > b.c[j]:
            out.append(sig(b, j, -1, float(hv[j]), "RU04_FRACTAL_SHORT"))
    return sorted_out(out)


# ═══ Pro Trading School ════════════════════════════════════════════════════════════════════

def pt01(m, B, p, cache):
    """Gold stop hunt: a 5-minute bar runs through a level of two or more swing points and closes back, with the 1-hour
    swing trend; stop beyond the wick; 2R."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    a = c.atr(14)
    ph, pl = (np.flatnonzero(x) for x in c.fractals(3))
    out = []
    for j in range(160, len(b.c)):
        if not np.isfinite(a[j]):
            continue
        for side, piv, vals in ((1, pl, b.l), (-1, ph, b.h)):
            k, aa = int(np.searchsorted(piv, j - 3, "right")), int(np.searchsorted(piv, j - 150, "left"))
            pv = vals[piv[aa:k]]
            hit = ((pv > b.l[j]) & (pv < b.c[j])).any() if side > 0 else ((pv < b.h[j]) & (pv > b.c[j])).any()
            if not hit:
                continue
            levels = clusters(vals, piv, j, 3, 0.25 * a[j], 150)
            lv = [lo for lo, _ in levels] if side > 0 else [hi_ for _, hi_ in levels]
            if not any((side > 0 and b.l[j] < x < b.c[j]) or (side < 0 and b.h[j] > x > b.c[j]) for x in lv):
                continue
            if swing_trend_at(m, B, cache, 60, int(b.i1[j]), 2) != side:
                continue
            stop = float(b.l[j] - 0.1 * a[j]) if side > 0 else float(b.h[j] + 0.1 * a[j])
            out.append(sig(b, j, side, stop, "PT01_STOP_HUNT_LONG" if side > 0 else "PT01_STOP_HUNT_SHORT"))
            break
    return sorted_out(out)


def pt02(m, B, p, cache):
    """Gold RSI divergence on candle bodies + an engulfing within 6 bars of the second pivot, with the 1-hour trend; 2R."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    rsi, a = c.rsi(14), c.atr(14)
    key = ("pt02_piv",)
    if key not in cache:
        bt, bb = np.maximum(b.o, b.c), np.minimum(b.o, b.c)
        n = 3
        N = len(bt)
        hp, lp = np.zeros(N, bool), np.zeros(N, bool)
        for i in range(n, N - n):
            hp[i] = bt[i] > bt[i - n:i].max() and bt[i] >= bt[i + 1:i + n + 1].max()
            lp[i] = bb[i] < bb[i - n:i].min() and bb[i] <= bb[i + 1:i + n + 1].min()
        cache[key] = (bt, bb, np.flatnonzero(hp), np.flatnonzero(lp))
    bt, bb, H, L = cache[key]
    out = []
    for side, piv, vals in ((1, L, bb), (-1, H, bt)):
        for t in range(1, len(piv)):
            q1, q2 = int(piv[t - 1]), int(piv[t])
            if q2 - q1 > 40 or not (np.isfinite(rsi[q1]) and np.isfinite(rsi[q2])):
                continue
            if side > 0 and not (vals[q2] < vals[q1] and rsi[q2] > rsi[q1]):
                continue
            if side < 0 and not (vals[q2] > vals[q1] and rsi[q2] < rsi[q1]):
                continue
            for j in range(q2 + 3, min(q2 + 7, len(b.c))):
                eng = bull_engulf(b, j) if side > 0 else bear_engulf(b, j)
                if eng and np.isfinite(a[j]) and swing_trend_at(m, B, cache, 60, int(b.i1[j]), 2) == side:
                    stop = float(b.l[j] - 0.1 * a[j]) if side > 0 else float(b.h[j] + 0.1 * a[j])
                    out.append(sig(b, j, side, stop, "PT02_RSI_DIV_LONG" if side > 0 else "PT02_RSI_DIV_SHORT"))
                    break
    return sorted_out(out)


def pt03(m, B, p, cache):
    """"Sweep and flip": the Asian range (00:00-07:00 UTC) swept by a London 15-minute candle (07:00-11:00 UTC) that
    closes back inside, with the 1-hour swing trend; stop beyond the sweep; target the other side (at least 1.5R)."""
    b = B[15]
    a = ctx(m, B, 15, cache).atr(14)
    um = utc_min(b, cache, 15)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        asia = [j for j in rows if um[j] < 7 * 60]
        if len(asia) < 20:
            continue
        AH, AL = float(b.h[asia].max()), float(b.l[asia].min())
        for j in rows:
            if not (7 * 60 <= um[j] < 11 * 60) or not np.isfinite(a[j]):
                continue
            side = 0
            if b.h[j] > AH and AL < b.c[j] < AH:
                side = -1
            elif b.l[j] < AL and AL < b.c[j] < AH:
                side = 1
            if not side or swing_trend_at(m, B, cache, 60, int(b.i1[j]), 2) != side:
                continue
            stop = float(b.h[j] + 0.1 * a[j]) if side < 0 else float(b.l[j] - 0.1 * a[j])
            risk = abs(float(b.c[j]) - stop)
            far = AL if side < 0 else AH
            tgt = far if (far - float(b.c[j])) * side >= 1.5 * risk else float(b.c[j]) + side * 1.5 * risk
            out.append(sig(b, j, side, stop, "PT03_ASIA_SWEEP_FLIP_LONG" if side > 0 else "PT03_ASIA_SWEEP_FLIP_SHORT",
                           target_px=float(tgt)))
            break
    return sorted_out(out)


def pt04(m, B, p, cache):
    """Inside-bar breakout on 4 hours in the direction of the 4-hour swing structure; stop at the inside bar's other end; 2R."""
    b = B[240]
    hv, _, lv, _, phv, plv = ctx(m, B, 240, cache).pivots(2)
    out = []
    for j in range(10, len(b.c) - 1):
        if not (b.h[j] <= b.h[j - 1] and b.l[j] >= b.l[j - 1]) or b.h[j] <= b.l[j]:
            continue
        t = Z.swings_up(hv, lv, phv, plv, j)
        if not t:
            continue
        last = int(b.i1[min(j + 2, len(b.c) - 1)])
        if t > 0:
            out.append(sig(b, j, 1, float(b.l[j]), "PT04_INSIDE_BAR_LONG", entry_stop=float(b.h[j]), expire_k=last))
        else:
            out.append(sig(b, j, -1, float(b.h[j]), "PT04_INSIDE_BAR_SHORT", entry_stop=float(b.l[j]), expire_k=last))
    return sorted_out(out)


# ═══ Transparent Fx Academy ════════════════════════════════════════════════════════════════

FIBS = (0.382, 0.5, 0.618, 0.786, 1.0)


def tf01(m, B, p, cache):
    """Fibonacci confluence continuation: after a break of the last swing, a limit at the Fibonacci level nearest the
    flipped level (on the pullback side), stop past the next level, target the -0.272 extension; 24 bars."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    hv, hi, lv, li, _, _ = c.pivots(3)
    n = len(b.c)
    out = []
    j = 10
    while j < n - 1:
        side = 0
        if np.isfinite(hv[j]) and b.c[j] > hv[j] and b.c[j - 1] <= hv[j]:
            side = 1
        elif np.isfinite(lv[j]) and b.c[j] < lv[j] and b.c[j - 1] >= lv[j]:
            side = -1
        if not side:
            j += 1
            continue
        S = float(hv[j]) if side > 0 else float(lv[j])               # the flipped level
        base = float(lv[j]) if side > 0 else float(hv[j])            # the swing the impulse started from
        if not np.isfinite(base):
            j += 1
            continue
        ext = float(b.h[j]) if side > 0 else float(b.l[j])
        for t in range(j, min(j + 24, n - 1)):
            ext = max(ext, float(b.h[t])) if side > 0 else min(ext, float(b.l[t]))
            leg = abs(ext - base)
            if not leg > 0:
                continue
            lv_px = [ext - side * f * leg for f in FIBS]
            near = [i for i in range(3) if (lv_px[i] - S) * side >= 0]
            if not near:
                continue
            i = max(near)                       # the deepest of 0.382/0.5/0.618 still on the near side of the level
            entry = lv_px[i]
            stop = lv_px[i + 1] - side * 0.6 * abs(lv_px[i + 2] - lv_px[i + 1]) if i + 2 < len(FIBS) else lv_px[i + 1]
            tgt = ext + side * 0.272 * leg
            if (b.c[t] - entry) * side <= 0:
                break                          # price already through the entry level: the setup is gone
            out.append(sig(b, t, side, float(stop), "TF01_FIB_CONFLUENCE_LONG" if side > 0 else "TF01_FIB_CONFLUENCE_SHORT",
                           entry_limit=float(entry), expire_k=int(b.i1[t + 1]), target_px=float(tgt),
                           info={"group": f"tf01-{j}"}))
        j += 1
    return sorted_out(out)


# ═══ Trading Data ══════════════════════════════════════════════════════════════════════════

def td01(m, B, p, cache):
    """9/20 EMA cross at a twice-touched level (or a flipped swing), with the swing trend and premium/discount; stop
    beyond the zone; 1.5R."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    e9, e20, a = c.ema(9), c.ema(20), c.atr(14)
    up, dn = flags_cross(e9, e20)
    ph, pl = (np.flatnonzero(x) for x in c.fractals(3))
    hv, _, lv, _, phv, plv = c.pivots(3)
    out = []
    for j in range(210, len(b.c)):
        side = 1 if up[j] else (-1 if dn[j] else 0)
        if not side or not np.isfinite(a[j]):
            continue
        if Z.swings_up(hv, lv, phv, plv, j) != side:
            continue
        if not (np.isfinite(hv[j]) and np.isfinite(lv[j])):
            continue
        half = lv[j] + 0.5 * (hv[j] - lv[j])
        if (side > 0 and b.c[j] >= half) or (side < 0 and b.c[j] <= half):
            continue
        piv, vals = (pl, b.l) if side > 0 else (ph, b.h)
        zones = [(lo, hi_) for lo, hi_ in clusters(vals, piv, j, 3, 0.3 * a[j], 200)]
        # flipped swings: a confirmed swing high since broken by a close (support for longs), and the mirror
        opp, ov = (ph, b.h) if side > 0 else (pl, b.l)
        k = int(np.searchsorted(opp, j - 3, "right"))
        for q in opp[max(0, k - 6):k]:
            q = int(q)
            lvl = float(ov[q])
            if q < j - 200:
                continue
            after = b.c[q + 4:j + 1] if q + 4 <= j else np.zeros(0)
            if len(after) and ((side > 0 and after.max() > lvl) or (side < 0 and after.min() < lvl)):
                zones.append((lvl, lvl))
        hit = None
        for lo, hi_ in zones:
            edge = hi_ if side > 0 else lo
            w = slice(max(0, j - 5), j + 1)
            touched = (b.l[w] <= edge + 0.15 * a[j]).any() if side > 0 else (b.h[w] >= edge - 0.15 * a[j]).any()
            held = (b.c[w] >= lo).all() if side > 0 else (b.c[w] <= hi_).all()
            if touched and held and (b.c[j] - edge) * side > 0:
                hit = (lo, hi_) if hit is None else hit
        if hit is None:
            continue
        stop = hit[0] - 0.1 * a[j] if side > 0 else hit[1] + 0.1 * a[j]
        out.append(sig(b, j, side, float(stop), "TD01_EMA920_LEVEL_LONG" if side > 0 else "TD01_EMA920_LEVEL_SHORT"))
    return sorted_out(out)


def td02(m, B, p, cache):
    """9/15 EMA cross with the SMI (7, 2, 2) still rising and not above +60 (mirror for shorts); enter on the close beyond
    both EMAs; stop at the candle before; out on the opposite cross. Gold 5-minute, bitcoin 15-minute."""
    tf = 5 if m.name == "XAUUSD" else 15
    b = B[tf]
    c = ctx(m, B, tf, cache)
    e9, e15 = c.ema(9), c.ema(15)
    up, dn = flags_cross(e9, e15)
    s, sg = c._get(("smi", 7, 2, 2), lambda: Z.smi(b, 7, 2, 2))
    out = []
    for x in range(25, len(b.c)):
        side = 1 if up[x] else (-1 if dn[x] else 0)
        if not side:
            continue
        others = int(up[x - 20:x].sum() + dn[x - 20:x].sum())
        if others > 1:
            continue
        if not (np.isfinite(s[x]) and np.isfinite(s[x - 1]) and np.isfinite(sg[x])):
            continue
        rising = (s[x] > sg[x] and s[x] > s[x - 1]) if side > 0 else (s[x] < sg[x] and s[x] < s[x - 1])
        if not rising or (side > 0 and s[x] > 60) or (side < 0 and s[x] < -60):
            continue
        for j in range(x, min(x + 3, len(b.c))):
            if (e9[j] - e15[j]) * side <= 0:
                break
            if (side > 0 and b.c[j] > max(e9[j], e15[j])) or (side < 0 and b.c[j] < min(e9[j], e15[j])):
                stop = float(b.l[j - 1]) if side > 0 else float(b.h[j - 1])
                if (b.c[j] - stop) * side > 0:
                    out.append(sig(b, j, side, stop, "TD02_EMA915_SMI_LONG" if side > 0 else "TD02_EMA915_SMI_SHORT"))
                break
    return sorted_out(out)


def td02_x(m, B, p, cache):
    tf = 5 if m.name == "XAUUSD" else 15
    b = B[tf]
    c = ctx(m, B, tf, cache)
    up, dn = flags_cross(c.ema(9), c.ema(15))
    return XExits(target_r=None, xbars=b, xlong=dn, xshort=up)


def _ut_pair(m, B, cache, tf):
    b = B[tf]
    c = ctx(m, B, tf, cache)
    ts_b, buy, _ = c._get(("ut", 2.0, 300), lambda: Z.ut_bot(b, 2.0, 300))
    ts_s, _, sell = c._get(("ut", 2.0, 1), lambda: Z.ut_bot(b, 2.0, 1))
    return buy, sell


def td03(m, B, p, cache):
    """UT Bot (key 2 / ATR 300 for buys, key 2 / ATR 1 for sells) + STC (80, 27, 50) beyond 25/75 and turning; stop at
    the 10-bar extreme; 2R (15-minute)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    buy, sell = _ut_pair(m, B, cache, 15)
    st = c._get(("stc", 80, 27, 50), lambda: Z.stc(b.c, 80, 27, 50))
    out = []
    for j in range(320, len(b.c)):
        if not (np.isfinite(st[j]) and np.isfinite(st[j - 1])):
            continue
        if buy[j] and st[j] < 25 and st[j] > st[j - 1]:
            out.append(sig(b, j, 1, recent_extreme(b, j, 10, 1), "TD03_UT_STC_LONG"))
        elif sell[j] and st[j] > 75 and st[j] < st[j - 1]:
            out.append(sig(b, j, -1, recent_extreme(b, j, 10, -1), "TD03_UT_STC_SHORT"))
    return sorted_out(out)


def td04(m, B, p, cache):
    """UT Bot + linear-regression candles (8, 6): a regression candle of the trade's colour closing beyond its signal line
    with a UT Bot signal in the last 3 bars; out when an opposite candle closes back; 3-ATR protective stop (1-hour)."""
    b = B[60]
    c = ctx(m, B, 60, cache)
    buy, sell = _ut_pair(m, B, cache, 60)
    lo_, lc, sg = c._get(("lrc", 8, 6), lambda: Z.lr_candles(b, 8, 6))
    a = c.atr(14)
    out = []
    for j in range(320, len(b.c)):
        if not (np.isfinite(lc[j]) and np.isfinite(sg[j]) and np.isfinite(a[j])):
            continue
        if lc[j] > lo_[j] and lc[j] > sg[j] and buy[j - 2:j + 1].any():
            out.append(sig(b, j, 1, float(b.c[j] - 3 * a[j]), "TD04_UT_LRC_LONG", info={"stop_dist": float(3 * a[j]), "group": f"td04-{int(np.flatnonzero(buy[j - 2:j + 1])[-1]) + j - 2}"}))
        elif lc[j] < lo_[j] and lc[j] < sg[j] and sell[j - 2:j + 1].any():
            out.append(sig(b, j, -1, float(b.c[j] + 3 * a[j]), "TD04_UT_LRC_SHORT", info={"stop_dist": float(3 * a[j]), "group": f"td04s-{int(np.flatnonzero(sell[j - 2:j + 1])[-1]) + j - 2}"}))
    return sorted_out(out)


def td04_x(m, B, p, cache):
    b = B[60]
    lo_, lc, sg = ctx(m, B, 60, cache)._get(("lrc", 8, 6), lambda: Z.lr_candles(b, 8, 6))
    return XExits(target_r=None, xbars=b, xlong=(lc < lo_) & (lc < sg), xshort=(lc > lo_) & (lc > sg))


def td05(m, B, p, cache):
    """ADX/DI + EMA 200 retest: a sloping EMA 200, a held retest in the last 8 bars, a fresh widening DI cross, a close
    above the previous 5 highs -> enter; stop 0.25 ATR beyond the EMA 200; 2R (15-minute)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e200, a = c.ema(200), c.atr(14)
    _, pdi, mdi = c._get(("adx", 14), lambda: I.adx(b, 14))
    up, dn = flags_cross(pdi, mdi)
    out = []
    for j in range(230, len(b.c)):
        if not (np.isfinite(e200[j]) and np.isfinite(e200[j - 20]) and np.isfinite(a[j])):
            continue
        slope = e200[j] - e200[j - 20]
        for side, xs in ((1, up), (-1, dn)):
            if slope * side < 0.2 * a[j]:
                continue
            crosses = np.flatnonzero(xs[j - 4:j + 1])
            if not len(crosses):
                continue
            x = j - 4 + int(crosses[-1])
            gap_now, gap_x = (pdi[j] - mdi[j]) * side, (pdi[x] - mdi[x]) * side
            if not gap_now > gap_x:
                continue
            w = slice(j - 8, j)
            if side > 0:
                touched = (b.l[w] <= e200[w] + 0.1 * a[j]).any()
                held = (b.c[w] >= e200[w] - 0.1 * a[j]).all()
                brk = b.c[j] > b.h[j - 5:j].max()
            else:
                touched = (b.h[w] >= e200[w] - 0.1 * a[j]).any()
                held = (b.c[w] <= e200[w] + 0.1 * a[j]).all()
                brk = b.c[j] < b.l[j - 5:j].min()
            if touched and held and brk:
                stop = e200[j] - side * 0.25 * a[j]
                if (b.c[j] - stop) * side > 0:
                    out.append(sig(b, j, side, float(stop), "TD05_ADX_EMA200_LONG" if side > 0 else "TD05_ADX_EMA200_SHORT"))
    return sorted_out(out)


# ═══ Faiz SMC ══════════════════════════════════════════════════════════════════════════════

def fz01(m, B, p, cache):
    """Gold 8 PM / 9 PM New York ("Midas"): the latest 15-minute swing high and low before the hour; one taken after it;
    a 1-minute structure shift with a fair value gap in the shift leg -> enter; stop beyond the sweep; break-even at 1R;
    2R; entries before 22:00 NY."""
    b, b15 = B[1], B[15]
    hv15, _, lv15, _, _, _ = ctx(m, B, 15, cache).pivots(2)
    a15 = ctx(m, B, 15, cache).atr(14)
    hv1, _, lv1, _, _, _ = ctx(m, B, 1, cache).pivots(2)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        for hour in (20 * 60, 21 * 60):
            start = next((j for j in rows if int(b.ny0[j]) == hour), None)
            if start is None:
                continue
            h15 = last_done(b15, int(b.i0[start]) - 1)
            if h15 < 0 or not (np.isfinite(hv15[h15]) and np.isfinite(lv15[h15]) and np.isfinite(a15[h15])):
                continue
            SH, SL = float(hv15[h15]), float(lv15[h15])
            side, ext, ext_j = 0, None, None
            for j in rows:
                if j < start:
                    continue
                if int(b.ny0[j]) >= 22 * 60 or int(b.ny0[j]) < hour:
                    break
                if side == 0:
                    if b.h[j] > SH:
                        side, ext, ext_j = -1, float(b.h[j]), j
                    elif b.l[j] < SL:
                        side, ext, ext_j = 1, float(b.l[j]), j
                    continue
                if (side < 0 and b.h[j] > ext) or (side > 0 and b.l[j] < ext):
                    ext, ext_j = (float(b.h[j]), j) if side < 0 else (float(b.l[j]), j)
                    continue
                lvl = lv1[j] if side < 0 else hv1[j]
                if not np.isfinite(lvl):
                    continue
                if (side < 0 and b.c[j] < lvl and b.c[j - 1] >= lvl) or (side > 0 and b.c[j] > lvl and b.c[j - 1] <= lvl):
                    has_gap = any((gap_dn(b, g) if side < 0 else gap_up(b, g)) for g in range(ext_j + 2, j + 1))
                    if has_gap:
                        stop = ext + 0.1 * a15[h15] if side < 0 else ext - 0.1 * a15[h15]
                        out.append(sig(b, j, side, float(stop), "FZ01_MIDAS_SHORT" if side < 0 else "FZ01_MIDAS_LONG"))
                    break
    return sorted_out(out)


def fz01_x(m, B, p, cache):
    return XExits(target_r=2.0, be_at_r=1.0)


def fz02(m, B, p, cache):
    """Gold London first FVG inversion (15-minute): the first gap made in 03:00-07:00 NY, a body close through it; a
    limit on the retest of its near edge until 07:00 NY; stop beyond the bodies; break-even at 1R; 2R."""
    b = B[15]
    a = ctx(m, B, 15, cache).atr(14)
    out = []
    for d in range(m.n_days):
        rows = [j for j in bars_of_day(b, d) if 3 * 60 <= int(b.ny0[j]) < 7 * 60]
        if len(rows) < 5:
            continue
        gap = None
        for j in rows:
            if j - 2 < rows[0]:
                continue
            if gap is None:
                if gap_up(b, j):
                    gap = (1, float(b.h[j - 2]), float(b.l[j]), j)
                elif gap_dn(b, j):
                    gap = (-1, float(b.h[j]), float(b.l[j - 2]), j)
                continue
            g_side, lo, hi_, gj = gap
            if j <= gj or not np.isfinite(a[j]):
                continue
            last = rows[-1]
            if j >= last:
                break
            bodies = slice(max(rows[0], j - 3), j + 1)
            if g_side > 0 and b.c[j] < lo:                       # a bullish gap inverted -> short on the retest of its bottom
                stop = float(np.maximum(b.o[bodies], b.c[bodies]).max() + 0.05 * a[j])
                if stop > lo:
                    out.append(sig(b, j, -1, stop, "FZ02_LONDON_IFVG_SHORT", entry_limit=lo, expire_k=int(b.i1[last])))
                break
            if g_side < 0 and b.c[j] > hi_:
                stop = float(np.minimum(b.o[bodies], b.c[bodies]).min() - 0.05 * a[j])
                if stop < hi_:
                    out.append(sig(b, j, 1, stop, "FZ02_LONDON_IFVG_LONG", entry_limit=hi_, expire_k=int(b.i1[last])))
                break
    return sorted_out(out)


# ═══ Mulham Trading ════════════════════════════════════════════════════════════════════════

def mh01(m, B, p, cache):
    """Gold 8 PM New York hourly candle: the 9 PM candle sweeps a side and closes back inside (reversal) or closes beyond
    (continuation); enter at the 22:00 open; 2R."""
    b = B[60]
    a = ctx(m, B, 60, cache).atr(14)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        j20 = next((j for j in rows if int(b.ny0[j]) == 20 * 60), None)
        if j20 is None or j20 + 1 > rows[-1] or int(b.ny0[j20 + 1]) != 21 * 60 or not np.isfinite(a[j20 + 1]):
            continue
        j = j20 + 1
        H, L = float(b.h[j20]), float(b.l[j20])
        if b.c[j] > H:
            out.append(sig(b, j, 1, float(b.l[j]), "MH01_8PM_CONTINUATION_LONG"))
        elif b.c[j] < L:
            out.append(sig(b, j, -1, float(b.h[j]), "MH01_8PM_CONTINUATION_SHORT"))
        elif b.h[j] > H and b.c[j] < H:
            out.append(sig(b, j, -1, float(b.h[j] + 0.1 * a[j]), "MH01_8PM_REVERSAL_SHORT"))
        elif b.l[j] < L and b.c[j] > L:
            out.append(sig(b, j, 1, float(b.l[j] - 0.1 * a[j]), "MH01_8PM_REVERSAL_LONG"))
    return sorted_out(out)


def mh02(m, B, p, cache):
    """15-minute fake-out of an untouched 15-minute swing (the sweep candle coloured the sweep's way), then in the next
    15 minutes a 1-minute close beyond the sweep candle's close -> enter; stop beyond the sweep candle; target the
    nearest untouched 15-minute swing (skip under 1R)."""
    b, b1 = B[15], B[1]
    a = ctx(m, B, 15, cache).atr(14)
    ph, pl = (np.flatnonzero(x) for x in ctx(m, B, 15, cache).fractals(2))
    n = len(b.c)
    out = []
    for j in range(30, n - 1):
        if not np.isfinite(a[j]) or b.day[j + 1] != b.day[j]:
            continue
        for side, piv, vals in ((-1, ph, b.h), (1, pl, b.l)):
            k = int(np.searchsorted(piv, j - 2, "right"))
            P = piv[max(0, k - 20):k]
            V = vals[P]
            hit = ((V < b.h[j]) & (V > b.c[j])) if side < 0 else ((V > b.l[j]) & (V < b.c[j]))
            if not hit.any():
                continue
            cand = []
            for q, v in zip(P[hit], V[hit]):
                seg = vals[int(q) + 1:j]
                if (seg.max() <= v) if side < 0 else (seg.min() >= v):
                    cand.append(float(v))
            if not cand:
                continue
            if (side < 0 and not green(b, j)) or (side > 0 and not red(b, j)):
                continue
            stop = float(b.h[j] + 0.05 * a[j]) if side < 0 else float(b.l[j] - 0.05 * a[j])
            # targets: untouched swings on the other side
            opp, ov = (pl, b.l) if side < 0 else (ph, b.h)
            k2 = int(np.searchsorted(opp, j - 2, "right"))
            tg = []
            for q in opp[max(0, k2 - 20):k2]:
                q = int(q)
                v = float(ov[q])
                seg = ov[q + 1:j + 1]
                if (side < 0 and seg.min() >= v and v < b.c[j]) or (side > 0 and seg.max() <= v and v > b.c[j]):
                    tg.append(v)
            if not tg:
                continue
            tgt = max(tg) if side < 0 else min(tg)
            ref = float(b.c[j])
            r0, r1 = int(b.i1[j]) + 1, int(b.i1[j + 1])
            for r in range(r0, r1 + 1):
                if r >= len(b1.c) or b1.day[r] != b.day[j]:
                    break
                if (side < 0 and b1.h[r] > stop) or (side > 0 and b1.l[r] < stop):
                    break
                if (side < 0 and b1.c[r] < ref) or (side > 0 and b1.c[r] > ref):
                    if abs(tgt - b1.c[r]) >= abs(b1.c[r] - stop):
                        out.append(sig(b1, r, side, stop, "MH02_FAKEOUT_FLIP_SHORT" if side < 0 else "MH02_FAKEOUT_FLIP_LONG",
                                       target_px=float(tgt)))
                    break
            break
    return sorted_out(out)


def mh03(m, B, p, cache):
    """Asian liquidity sweep into a PD array: the 20:00-00:00 NY range; an unfilled 1-hour gap just beyond its extreme; a
    London 15-minute sweep into it that closes back inside (with the 4-hour swing structure); the first 1-minute gap the
    other way within 30 minutes -> a limit at its middle; stop beyond the sweep; target the other side (at least 1.5R)."""
    b, b15, bh, b1 = B[15], B[15], B[60], B[1]
    a15 = ctx(m, B, 15, cache).atr(14)
    ah = ctx(m, B, 60, cache).atr(14)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        asia = [j for j in rows if int(b.ny0[j]) >= 20 * 60]
        if len(asia) < 12:
            continue
        AH, AL = float(b.h[asia].max()), float(b.l[asia].min())
        lon = [j for j in rows if 2 * 60 <= int(b.ny0[j]) < 5 * 60]
        if not lon:
            continue
        r_asia_end = int(b.i1[asia[-1]])
        h = last_done(bh, r_asia_end)
        if h < 3 or not np.isfinite(ah[h]):
            continue
        # unfilled 1-hour gaps beyond the Asian extremes (made within the last 3 days, untouched since)
        pd_short = pd_long = None
        for g in range(max(2, h - 72), h + 1):
            if gap_dn(bh, g):
                lo, hi_ = float(bh.h[g]), float(bh.l[g - 2])
                if AH <= lo <= AH + 0.5 * ah[h] and (bh.h[g + 1:h + 1].max() if g < h else -np.inf) < lo:
                    pd_short = (lo, hi_)
            if gap_up(bh, g):
                lo, hi_ = float(bh.h[g - 2]), float(bh.l[g])
                if AL - 0.5 * ah[h] <= hi_ <= AL and (bh.l[g + 1:h + 1].min() if g < h else np.inf) > hi_:
                    pd_long = (lo, hi_)
        for j in lon:
            side = 0
            if pd_short and b15.h[j] >= pd_short[0] and b15.c[j] < AH:
                side = -1
            elif pd_long and b15.l[j] <= pd_long[1] and b15.c[j] > AL:
                side = 1
            if not side or swing_trend_at(m, B, cache, 240, int(b15.i1[j]), 2) != side:
                continue
            ext = float(b15.h[j]) if side < 0 else float(b15.l[j])
            stop = ext + 0.1 * a15[j] if side < 0 else ext - 0.1 * a15[j]
            r0 = int(b15.i1[j]) + 1
            for r in range(r0 + 2, min(r0 + 30, len(b1.c))):
                if b1.day[r] != b15.day[j]:
                    break
                if (side < 0 and b1.h[r] > ext) or (side > 0 and b1.l[r] < ext):
                    break
                if (side < 0 and gap_dn(b1, r)) or (side > 0 and gap_up(b1, r)):
                    lo, hi_ = (float(b1.h[r]), float(b1.l[r - 2])) if side < 0 else (float(b1.h[r - 2]), float(b1.l[r]))
                    mid = (lo + hi_) / 2
                    far = AL if side < 0 else AH
                    risk = abs(mid - stop)
                    tgt = far if (far - mid) * side >= 1.5 * risk else mid + side * 1.5 * risk
                    out.append(sig(b1, r, side, float(stop), "MH03_ASIA_PD_SHORT" if side < 0 else "MH03_ASIA_PD_LONG",
                                   entry_limit=float(mid), expire_k=int(min(r0 + 30, len(b1.c) - 1)), target_px=float(tgt)))
                    break
            break
    return sorted_out(out)
