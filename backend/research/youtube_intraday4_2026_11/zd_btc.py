"""The bitcoin strategies of the four-topic intraday study (cards/<video>.txt; the 'A' rules are the exact code).
Market BTCUSD: one-minute rows, the trading day is the UTC day, every book is out at 23:55 UTC (the desk's BTC_X)."""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import bars_of_day, body, ctx, green, red, rng, sig
from yc_engine import XExits

import zd_common as Z
from zd_common import T, sorted_out


# ═══ BI-01 four-hour opening range (00:00-04:00 UTC = 05:30-09:30 IST), 15-minute breakout, 2 ATR stop ═══════════

def bi01(m, B, p, cache):
    b = B[15]
    a14 = ctx(m, B, 15, cache).atr(14)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        first = [j for j in rows if Z.utc_min(b, j) < 240]
        if len(first) < 16:
            continue
        H, L = float(b.h[first].max()), float(b.l[first].min())
        for j in rows:
            um = Z.utc_min(b, j)
            if um < 240 or um >= T(23, 30) or not np.isfinite(a14[j]):
                continue
            bd = body(b, j)
            if not bd > 0:
                continue
            if green(b, j) and b.c[j] > H and b.c[j] - max(b.o[j], H) >= 0.4 * bd:
                out.append(sig(b, j, 1, H - 2 * float(a14[j]), "BI01_ORB4H_LONG", entry_stop=float(b.h[j]) * 1.0003))
            elif red(b, j) and b.c[j] < L and min(b.o[j], L) - b.c[j] >= 0.4 * bd:
                out.append(sig(b, j, -1, L + 2 * float(a14[j]), "BI01_ORB4H_SHORT", entry_stop=float(b.l[j]) * 0.9997))
    return sorted_out(out)


def bi01_x(m, B, p, cache):
    return XExits(target_r=2.0, partial_at_r=1.0)


# ═══ BI-02 fresh zone inside a zone: 4-hour supply/demand, the two outermost untouched 15-minute zones ════════════

def _base_zones(b, a):
    """[(base bar, known bar, low, high, side)]: side -1 supply (a green base, then two red bars closing 1.5 ATR below
    the base low), +1 demand (mirror)."""
    out = []
    for j in range(len(b.c) - 2):
        if not np.isfinite(a[j]):
            continue
        if green(b, j) and red(b, j + 1) and red(b, j + 2) and b.c[j + 2] <= b.l[j] - 1.5 * a[j]:
            out.append((j, j + 2, float(b.l[j]), float(b.h[j]), -1))
        elif red(b, j) and green(b, j + 1) and green(b, j + 2) and b.c[j + 2] >= b.h[j] + 1.5 * a[j]:
            out.append((j, j + 2, float(b.l[j]), float(b.h[j]), 1))
    return out


def _touched(b, lo, hi, j0, j1) -> bool:
    """Did any bar j0 .. j1 (inclusive) trade into [lo, hi]?"""
    for x in range(j0, j1 + 1):
        if b.l[x] <= hi and b.h[x] >= lo:
            return True
    return False


def bi02(m, B, p, cache):
    b4, b = B[240], B[15]
    a4 = ctx(m, B, 240, cache).atr(14)
    a15 = ctx(m, B, 15, cache).atr(14)
    small = _base_zones(b, a15)
    out = []
    for j4, k4, lo4, hi4, side in _base_zones(b4, a4):
        t_lo, t_hi = int(b4.i0[j4]), int(b4.i1[k4])           # rows of the 4-hour zone's build
        known15 = int(np.searchsorted(b.i1, t_hi, "right")) - 1  # the last 15-minute bar complete at that row
        inner = []
        for j, k, lo, hi, s in small:
            if s != side or b.i0[j] < t_lo or b.i1[k] > t_hi:
                continue
            ov = min(hi, hi4) - max(lo, lo4)
            if not (hi > lo and ov > 0.5 * (hi - lo)):
                continue
            if k + 1 <= known15 and _touched(b, lo, hi, k + 1, known15):
                continue                                       # tested before the 4-hour zone was complete
            inner.append((lo, hi))
        if not inner:
            continue
        inner.sort(key=lambda z: -z[1] if side < 0 else z[0])  # outermost first: highest for supply, lowest for demand
        zones = inner[:2]
        last = min(len(b.c) - 1, known15 + 10 * 96)             # a zone is watched for ten days
        live = [True] * len(zones)
        for x in range(known15 + 1, last + 1):
            if side < 0 and b.c[x] > hi4 or side > 0 and b.c[x] < lo4:
                break                                          # the 4-hour zone is broken
            for zi, (lo, hi) in enumerate(zones):
                if not live[zi]:
                    continue
                inside = b.h[x] >= lo if side < 0 else b.l[x] <= hi
                if not inside:
                    continue
                live[zi] = False                               # first touch: this zone is used now
                for y in range(x, min(x + 3, last + 1)):
                    if side < 0 and b.c[y] > hi or side > 0 and b.c[y] < lo:
                        break
                    if side < 0 and (Z.bear_engulf(b, y) or Z.evening_star(b, y) or Z.shooting_star(b, y)):
                        out.append(sig(b, y, -1, hi * 1.0005, "BI02_ZONE_SUPPLY"))
                        break
                    if side > 0 and (Z.bull_engulf(b, y) or Z.morning_star(b, y) or Z.hammer(b, y)):
                        out.append(sig(b, y, 1, lo * 0.9995, "BI02_ZONE_DEMAND"))
                        break
            if not any(live):
                break
    return sorted_out(out)


def bi02_x(m, B, p, cache):
    return XExits(target_r=2.0, partial_at_r=1.0)


# ═══ BI-04 Bollinger W/M: first swing outside the band, fakeout of it, neckline break (5 minutes) ════════════════

def bi04(m, B, p, cache):
    b = B[5]
    mid, upb, lob = ctx(m, B, 5, cache).bollinger(20, 2.0)
    n = len(b.c)
    out = []
    for side in (1, -1):
        band, opp = (lob, upb) if side > 0 else (upb, lob)
        j = 6
        while j < n - 3:
            beyond = (b.l[j] < band[j]) if side > 0 else (b.h[j] > band[j])
            inside_before = all(np.isfinite(band[i]) and ((b.l[i] >= band[i]) if side > 0 else (b.h[i] <= band[i]))
                                for i in range(j - 5, j))
            if not (np.isfinite(band[j]) and beyond and inside_before):
                j += 1
                continue
            j0 = j
            got = None
            # the swing: a 2-bar fractal beyond the band within 20 bars of the first exit (known 2 bars later)
            q = None
            for x in range(j0, min(j0 + 20, n - 2)):
                if x < 2:
                    continue
                lo_ok = b.l[x] < min(b.l[x - 1], b.l[x - 2], b.l[x + 1], b.l[x + 2]) and b.l[x] < band[x]
                hi_ok = b.h[x] > max(b.h[x - 1], b.h[x - 2], b.h[x + 1], b.h[x + 2]) and b.h[x] > band[x]
                if (side > 0 and lo_ok) or (side < 0 and hi_ok):
                    q = x
                    break
            if q is None:
                j = j0 + 1
                continue
            level = float(b.l[q]) if side > 0 else float(b.h[q])
            f = None
            for x in range(q + 3, min(q + 33, n)):             # known at q + 2; the fakeout comes after
                if (side > 0 and b.h[x] >= opp[x]) or (side < 0 and b.l[x] <= opp[x]):
                    break                                      # the opposite band was tested: setup over
                wick = (b.l[x] < level < b.c[x]) if side > 0 else (b.h[x] > level > b.c[x])
                quick = (b.c[x - 1] < level < b.c[x]) if side > 0 else (b.c[x - 1] > level > b.c[x])
                if wick or quick:
                    f = x
                    break
            if f is None:
                j = q + 3
                continue
            neck = float(b.h[q:f + 1].max()) if side > 0 else float(b.l[q:f + 1].min())
            ext = float(b.l[f]) if side > 0 else float(b.h[f])
            stop = min(ext, float(lob[f])) * 0.9998 if side > 0 else max(ext, float(upb[f])) * 1.0002
            for e in range(f + 1, min(f + 21, n)):
                if (side > 0 and (b.h[e] >= opp[e] or b.l[e] < ext)) or (side < 0 and (b.l[e] <= opp[e] or b.h[e] > ext)):
                    break
                if (side > 0 and b.c[e] > neck) or (side < 0 and b.c[e] < neck):
                    risk = (b.c[e] - stop) * side
                    if risk > 0 and (b.c[e] - neck) * side <= 0.5 * risk:
                        w0 = max(0, j0 - 30)
                        far = float(b.h[w0:j0].max()) if side > 0 else float(b.l[w0:j0].min())
                        tgt = max(far, b.c[e] + 1.5 * risk) if side > 0 else min(far, b.c[e] - 1.5 * risk)
                        got = sig(b, e, side, stop, "BI04_BB_W_LONG" if side > 0 else "BI04_BB_M_SHORT",
                                  target_px=float(tgt))
                    break
            if got is not None:
                out.append(got)
            j = f + 1
    return sorted_out(out)


def bi04_x(m, B, p, cache):
    return XExits(target_r=None, partial_at_r=1.0)


# ═══ BI-06 two-candle turn through EMA 6 (1 hour), 3R; one stop ends the UTC day ═════════════════════════════════

def bi06(m, B, p, cache):
    b = B[60]
    e6 = ctx(m, B, 60, cache).ema(6)
    out = []
    for j in range(1, len(b.c)):
        if not np.isfinite(e6[j]) or b.day[j] != b.day[j - 1]:
            continue
        exp = int(b.i1[j]) + 180
        if green(b, j - 1) and red(b, j) and b.h[j] <= b.h[j - 1]:
            lvl = min(float(b.l[j]), float(e6[j]))
            out.append(sig(b, j, -1, max(b.h[j - 1], b.h[j]) * 1.0002, "BI06_TURN_SHORT", entry_stop=lvl, expire_k=exp))
        elif red(b, j - 1) and green(b, j) and b.l[j] >= b.l[j - 1]:
            lvl = max(float(b.h[j]), float(e6[j]))
            out.append(sig(b, j, 1, min(b.l[j - 1], b.l[j]) * 0.9998, "BI06_TURN_LONG", entry_stop=lvl, expire_k=exp))
    return sorted_out(out)


def bi06_x(m, B, p, cache):
    return XExits(target_r=3.0)


# ═══ BI-07 three-candle zone retest with a rejection candle (5 minutes), 3R ══════════════════════════════════════

def bi07(m, B, p, cache):
    b = B[5]
    e50 = ctx(m, B, 5, cache).ema(50)
    n = len(b.c)
    out = []
    for j in range(2, n - 1):
        if not np.isfinite(e50[j]):
            continue
        for side in (1, -1):
            col = green if side > 0 else red
            if not (col(b, j) and col(b, j - 1) and col(b, j - 2)):
                continue
            if (b.c[j] - e50[j]) * side <= 0:
                continue
            lo, hi = float(b.l[j - 2:j + 1].min()), float(b.h[j - 2:j + 1].max())
            midz = (lo + hi) / 2
            for i in range(j + 1, min(j + 49, n)):
                if (side > 0 and b.c[i] < lo) or (side < 0 and b.c[i] > hi):
                    break
                if side > 0 and b.l[i] <= hi and green(b, i) and b.c[i] > midz:
                    out.append(sig(b, i, 1, lo * 0.9998, "BI07_ZONE3_LONG"))
                    break
                if side < 0 and b.h[i] >= lo and red(b, i) and b.c[i] < midz:
                    out.append(sig(b, i, -1, hi * 1.0002, "BI07_ZONE3_SHORT"))
                    break
    return sorted_out(out)


def bi07_x(m, B, p, cache):
    return XExits(target_r=3.0)


# ═══ BI-08 5-minute multi-touch level, 1-minute structure breakout ═══════════════════════════════════════════════

def bi08(m, B, p, cache):
    b5, b1 = B[5], B[1]
    n5 = len(b5.c)
    # 5-minute 2-bar fractal lows / highs, known two bars after the pivot bar
    lows, highs = [], []
    for q in range(2, n5 - 2):
        if b5.l[q] < min(b5.l[q - 1], b5.l[q - 2], b5.l[q + 1], b5.l[q + 2]):
            lows.append((q + 2, q, float(b5.l[q])))
        if b5.h[q] > max(b5.h[q - 1], b5.h[q - 2], b5.h[q + 1], b5.h[q + 2]):
            highs.append((q + 2, q, float(b5.h[q])))

    q_lo = np.array([q for _, q, _ in lows], np.int64)
    q_hi = np.array([q for _, q, _ in highs], np.int64)

    def levels_at(j5, side):
        """Active 5-minute levels at 5-minute bar j5: a fractal within the last 72 bars touched (within 0.05%) by at
        least two other bars of those 72, with the last close on the right side of it."""
        src, qs = (lows, q_lo) if side > 0 else (highs, q_hi)
        out_l = []
        a = max(0, j5 - 71)
        i0 = int(np.searchsorted(qs, a, "left"))
        i1 = int(np.searchsorted(qs, j5 - 2, "right"))      # known = q + 2 <= j5
        for known, q, lv in src[i0:i1]:
            seg = b5.l[a:j5 + 1] if side > 0 else b5.h[a:j5 + 1]
            touches = int(np.sum(np.abs(seg - lv) <= 0.0005 * lv)) - 1
            if touches >= 2 and (b5.c[j5] - lv) * side > 0:
                out_l.append(lv)
        return out_l

    n1 = len(b1.c)
    ph = pl = None          # latest confirmed 1-minute fractal high / low (value)
    pl_prev = ph_prev = None
    out = []
    cache_lv = {}
    for j in range(4, n1):
        q = j - 2           # the pivot bar confirmed at j
        if b1.l[q] < min(b1.l[q - 1], b1.l[q - 2], b1.l[q + 1], b1.l[q + 2]):
            pl_prev, pl = pl, float(b1.l[q])
        if b1.h[q] > max(b1.h[q - 1], b1.h[q - 2], b1.h[q + 1], b1.h[q + 2]):
            ph_prev, ph = ph, float(b1.h[q])
        if b1.day[j] != b1.day[j - 1]:
            continue
        j5 = Z.last_done(b5, int(b1.i1[j]))
        if j5 < 0:
            continue
        for side in (1, -1):
            if side > 0:
                if ph is None or pl is None or pl_prev is None or not (pl > pl_prev):
                    continue
                if not (b1.c[j] > ph >= b1.c[j - 1]):
                    continue
            else:
                if pl is None or ph is None or ph_prev is None or not (ph < ph_prev):
                    continue
                if not (b1.c[j] < pl <= b1.c[j - 1]):
                    continue
            key = (j5, side)
            if key not in cache_lv:
                cache_lv[key] = levels_at(j5, side)
            lv = cache_lv[key]
            near = [x for x in lv if 0 <= (b1.c[j] - x) * side <= 0.005 * x]
            if not near:
                continue
            stop = pl * 0.9998 if side > 0 else ph * 1.0002
            out.append(sig(b1, j, side, stop, "BI08_LEVEL_BREAK_LONG" if side > 0 else "BI08_LEVEL_BREAK_SHORT"))
    return sorted_out(out)


def bi08_x(m, B, p, cache):
    return XExits(target_r=3.0)


# ═══ BI-09 SMA 100 side + 15-minute Heikin Ashi trend + MACD cross, 2R (5 minutes) ══════════════════════════════

def bi09(m, B, p, cache):
    b, bh = B[5], B[15]
    c5 = ctx(m, B, 5, cache)
    s100 = c5.sma(100)
    ml, ms, _ = c5.macd(12, 26, 9)
    ho, hc = I.heikin_ashi(bh)
    out = []
    for j in range(1, len(b.c)):
        if not (np.isfinite(s100[j]) and np.isfinite(ml[j]) and np.isfinite(ms[j])) or b.day[j] != b.day[j - 1]:
            continue
        kh = Z.last_done(bh, int(b.i1[j]))
        if kh < 0:
            continue
        ha_up = hc[kh] > ho[kh]
        for side in (1, -1):
            cross = Z.cross_up(ml, ms, j) if side > 0 else Z.cross_dn(ml, ms, j)
            if not cross or (b.c[j] - s100[j]) * side <= 0 or ha_up != (side > 0):
                continue
            if side > 0:
                stop = min(b.l[j], b.l[j - 1])
                stop = min(stop, b.c[j] * (1 - 0.0015))
            else:
                stop = max(b.h[j], b.h[j - 1])
                stop = max(stop, b.c[j] * (1 + 0.0015))
            out.append(sig(b, j, side, float(stop), "BI09_SMA_HA_MACD_LONG" if side > 0 else "BI09_SMA_HA_MACD_SHORT"))
    return sorted_out(out)


def bi09_x(m, B, p, cache):
    return XExits(target_r=2.0)
