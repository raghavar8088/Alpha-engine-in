"""The NIFTY / Bank Nifty index strategies of the four-topic intraday study (cards/<video>.txt; the 'A' rules are the
exact code). The option-buying videos are traded on the index as a labelled proxy: the desk has no intraday option
premiums, so premium rules are mapped to index moves with the delta stated on each card. Index minutes: 375 rows a day
from 09:15 IST; bars are anchored at 09:15 (bb_markets anchors NIFTY and BANKNIFTY); books are out at 15:15."""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import bars_of_day, body, ctx, green, red, rng, sig
from yc_engine import XExits
from yt_engine import Signal

import zd_common as Z
from zd_common import NSE_OPEN, T, sorted_out


def _row(m, d, minute):
    """Row of day d starting at `minute` IST on the 375-row index grid (None if the data has no such row yet)."""
    r = int(m.d0[d]) + (minute - NSE_OPEN)
    return r if r < int(m.d1[d]) else None


def _row_at(m, d, minute):
    """The same row by the calendar alone (an order's expiry or a time exit may lie beyond the data so far)."""
    return int(m.d0[d]) + (minute - NSE_OPEN)


# ═══ OB-01 9:30 premium-180 breakout as a delta-0.6 NIFTY proxy: first 15-point move from the 9:25 close ═══════

def ob01(m, B, p, cache):
    out = []
    for d in range(m.n_days):
        k = _row(m, d, T(9, 24))
        if k is None:
            continue
        c = float(m.c[k])
        up, dn = c * 1.0006, c * 0.9994
        info = {"stop_frac": 0.0013, "target_frac": 0.0027, "k_last": _row_at(m, d, T(10, 0))}
        short = Signal(d, k, -1, dn * 1.0013, "OB01_PREM180_SHORT", dict(info), entry_stop=dn, expire_k=k + 20)
        out.append(Signal(d, k, 1, up * 0.9987, "OB01_PREM180_LONG", dict(info), entry_stop=up, expire_k=k + 20,
                          alt=short))
    return sorted_out(out)


def ob01_x(m, B, p, cache):
    return XExits(target_r=None, be_at_r=0.5)


# ═══ OB-03 Williams %R (280) overbought on 60, 20 and a fresh 5-minute signal; 0.12% stop and target ════════════

def ob03(m, B, p, cache):
    b, b20, b60 = B[5], B[20], B[60]
    w5 = Z.williams_r(b, 280)
    w20 = Z.williams_r(b20, 280)
    w60 = Z.williams_r(b60, 280)
    out = []
    for j in range(12, len(b.c)):
        im = Z.ist_min(b, j)
        if not (T(9, 30) <= im < T(14, 30)) or not (np.isfinite(w5[j]) and np.isfinite(w5[j - 1])):
            continue
        k20, k60 = Z.last_done(b20, int(b.i1[j])), Z.last_done(b60, int(b.i1[j]))
        if k20 < 0 or k60 < 0 or not (np.isfinite(w20[k20]) and np.isfinite(w60[k60])):
            continue
        prev = w5[j - 12:j]
        if w60[k60] > -20 and w20[k20] > -20 and w5[j - 1] <= -20 < w5[j] and np.nanmin(prev) <= -50:
            out.append(sig(b, j, 1, b.c[j] * 0.9988, "OB03_WR280_CALL", info={"stop_frac": 0.0012, "target_frac": 0.0012}))
        elif w60[k60] < -80 and w20[k20] < -80 and w5[j - 1] >= -80 > w5[j] and np.nanmax(prev) >= -50:
            out.append(sig(b, j, -1, b.c[j] * 1.0012, "OB03_WR280_PUT", info={"stop_frac": 0.0012, "target_frac": 0.0012}))
    return sorted_out(out)


def ob03_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ OB-04 the 14:55 five-minute candle breakout with a 5-point buffer, out at 15:15 ═════════════════════════════

def ob04(m, B, p, cache):
    out = []
    for d in range(m.n_days):
        a, k = _row(m, d, T(14, 55)), _row(m, d, T(14, 59))
        if a is None or k is None:
            continue
        H, L = float(m.h[a:k + 1].max()), float(m.l[a:k + 1].min())
        if not L > 0 or (H - L) / L > 0.0022:
            continue
        up, dn = H * 1.0002, L * 0.9998
        short = Signal(d, k, -1, H * 1.00008, "OB04_1455_SHORT", {}, entry_stop=dn, expire_k=k + 10)
        out.append(Signal(d, k, 1, L * 0.99992, "OB04_1455_LONG", {}, entry_stop=up, expire_k=k + 10, alt=short))
    return sorted_out(out)


def ob04_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ OB-06 ADX turning up + breakout + big candle (15 minutes), 0.2% stop / 0.5% target, ADX-fall exit ═══════════

def _adx(m, B, cache, tf=15):
    c = ctx(m, B, tf, cache)
    return c._get(("adx", 14), lambda: I.adx(B[tf], 14))


def ob06(m, B, p, cache):
    b = B[15]
    a, _, _ = _adx(m, B, cache)
    bavg = ctx(m, B, 15, cache).body_avg(20)
    out = []
    for j in range(8, len(b.c)):
        im = Z.ist_min(b, j)
        if not (T(9, 30) <= im < T(14, 45)) or not np.isfinite(a[j - 4:j + 1]).all() or not np.isfinite(bavg[j]):
            continue
        turn = a[j] > a[j - 1] and a[j - 1] < a[j - 2] < a[j - 3] < a[j - 4]
        if not turn or body(b, j) < 1.5 * bavg[j]:
            continue
        if green(b, j) and b.c[j] > b.h[j - 8:j].max():
            out.append(sig(b, j, 1, b.c[j] * 0.998, "OB06_ADX_CALL", info={"stop_frac": 0.002, "target_frac": 0.005}))
        elif red(b, j) and b.c[j] < b.l[j - 8:j].min():
            out.append(sig(b, j, -1, b.c[j] * 1.002, "OB06_ADX_PUT", info={"stop_frac": 0.002, "target_frac": 0.005}))
    return sorted_out(out)


def ob06_x(m, B, p, cache):
    b = B[15]
    a, _, _ = _adx(m, B, cache)
    fall = np.zeros(len(a), bool)
    fall[2:] = (a[2:] < a[1:-1]) & (a[1:-1] < a[:-2])
    return XExits(target_r=None, xbars=b, xlong=fall, xshort=fall)


# ═══ OB-08 Supertrend (10, 1) + (10, 3) bullish with a fresh flip and a strong candle (5 minutes) ═══════════════

def ob08(m, B, p, cache):
    b = B[5]
    c5 = ctx(m, B, 5, cache)
    _, d1 = c5.supertrend(10, 1.0)
    _, d3 = c5.supertrend(10, 3.0)
    out = []
    for j in range(1, len(b.c)):
        im = Z.ist_min(b, j)
        if not (T(9, 20) <= im < T(15, 0)) or b.day[j - 1] != b.day[j]:
            continue
        r = rng(b, j)
        if not r > 0 or body(b, j) < 0.6 * r:
            continue
        for side in (1, -1):
            col = green(b, j) if side > 0 else red(b, j)
            if col and d1[j] == side and d3[j] == side and (d1[j - 1] == -side or d3[j - 1] == -side):
                out.append(sig(b, j, side, b.c[j] * (1 - side * 0.0004), "OB08_ST2_CALL" if side > 0 else "OB08_ST2_PUT",
                               info={"stop_frac": 0.0004, "target_frac": 0.0008}))
    return sorted_out(out)


def ob08_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ OB-09 2-minute EMA 10/20 trend pullback after a stop hunt, morning / evening star or engulfing ══════════════

def ob09(m, B, p, cache):
    b = B[2]
    c2 = ctx(m, B, 2, cache)
    e10, e20, ra = c2.ema(10), c2.ema(20), c2.range_avg(20)
    n = len(b.c)
    out = []
    for side in (1, -1):
        j = 1
        while j < n:
            im = Z.ist_min(b, j)
            ok_trend = np.isfinite(e20[j]) and np.isfinite(ra[j]) and (e10[j] - e20[j]) * side > 0 and \
                (b.c[j] - e10[j]) * side > 0
            col = green(b, j) if side > 0 else red(b, j)
            if not (T(9, 15) <= im < T(11, 30) and ok_trend and col and rng(b, j) >= 2 * ra[j]):
                j += 1
                continue
            q = j
            half = (b.h[q] + b.l[q]) / 2
            x = None
            for i in range(q + 1, min(q + 16, n)):
                if b.day[i] != b.day[q]:
                    break
                deep = b.l[i] <= half if side > 0 else b.h[i] >= half
                touch = b.l[i] <= e20[i] if side > 0 else b.h[i] >= e20[i]
                if deep and touch:
                    x = i
                    break
            if x is None:
                j = q + 1
                continue
            got = None
            for i in range(x, min(x + 11, n)):
                if b.day[i] != b.day[q] or Z.ist_min(b, i) >= T(11, 30):
                    break
                pat = (Z.morning_star(b, i) or Z.bull_engulf(b, i)) if side > 0 else (Z.evening_star(b, i) or Z.bear_engulf(b, i))
                if not pat or (e10[i] - e20[i]) * side <= 0 or (b.c[i] - e20[i]) * side <= 0:
                    continue
                stop = float(b.l[i - 2:i + 1].min()) * 0.9998 if side > 0 else float(b.h[i - 2:i + 1].max()) * 1.0002
                if (b.c[i] - stop) * side <= 0.0007 * b.c[i]:
                    got = sig(b, i, side, stop, "OB09_PULLBACK_CALL" if side > 0 else "OB09_PULLBACK_PUT")
                break
            if got is not None:
                out.append(got)
            j = x + 1
    return sorted_out(out)


def ob09_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ OB-10 VWAP side + EMA 5/13 cross + RSI 50, break of the signal candle, EMA 5 trail (5 minutes) ═════════════

def ob10(m, B, p, cache):
    b = B[5]
    c5 = ctx(m, B, 5, cache)
    vw = Z.vwap_of(m, b, cache, 5)
    e5, e13, r = c5.ema(5), c5.ema(13), c5.rsi(14)
    out = []
    for j in range(6, len(b.c)):
        im = Z.ist_min(b, j)
        if not (T(9, 20) <= im < T(14, 45)) or not (np.isfinite(vw[j]) and np.isfinite(e13[j]) and np.isfinite(r[j])):
            continue
        exp = int(b.i1[j]) + 10
        if green(b, j) and b.c[j] > vw[j] and e5[j] > e13[j] and r[j] > 50 and \
                any(Z.cross_up(e5, e13, i) for i in range(j - 5, j + 1)):
            out.append(sig(b, j, 1, float(b.l[j]) * 0.9998, "OB10_VWAP_EMA_CALL", entry_stop=float(b.h[j]), expire_k=exp))
        elif red(b, j) and b.c[j] < vw[j] and e5[j] < e13[j] and r[j] < 50 and \
                any(Z.cross_dn(e5, e13, i) for i in range(j - 5, j + 1)):
            out.append(sig(b, j, -1, float(b.h[j]) * 1.0002, "OB10_VWAP_EMA_PUT", entry_stop=float(b.l[j]), expire_k=exp))
    return sorted_out(out)


def ob10_x(m, B, p, cache):
    b = B[5]
    e5 = ctx(m, B, 5, cache).ema(5)
    return XExits(target_r=None, partial_at_r=1.0, xbars=b, xlong=b.c < e5, xshort=b.c > e5)


# ═══ SI-13 first-hour (9:15-10:15) range breakout, touch entry, opposite-side stop, out at 15:15 ═════════════════

def si13(m, B, p, cache):
    out = []
    for d in range(m.n_days):
        a, k = _row(m, d, NSE_OPEN), _row(m, d, T(10, 14))
        if a is None or k is None:
            continue
        last = _row_at(m, d, T(14, 59))
        H, L = float(m.h[a:k + 1].max()), float(m.l[a:k + 1].min())
        if not H > L:
            continue
        short = Signal(d, k, -1, H, "SI13_ORB60_SHORT", {}, entry_stop=L, expire_k=last)
        out.append(Signal(d, k, 1, L, "SI13_ORB60_LONG", {}, entry_stop=H, expire_k=last, alt=short))
    return sorted_out(out)


def si13_x(m, B, p, cache):
    return XExits(target_r=None)
