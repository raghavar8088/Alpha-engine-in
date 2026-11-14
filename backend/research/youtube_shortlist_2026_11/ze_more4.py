"""Fifth batch of the channel-shortlist study (14 Nov 2026): the cards of the owner's fourth list (crypto and gold
channels; cards/<video>.txt, whose 'A' rules are this code). Same conventions as ze_more3: BTCUSD and ETHUSD are Delta
Exchange perpetuals on the UTC day (real volume), XAUUSD is gold booked on Delta XAUTUSD (the 17:00 New York day; the
desk drops its weekend rows, so a week opens on Sunday 17:00 New York).

Every signal uses only the bars up to its own signal bar (daily bars here are one bar per trading day, known after the
day's last row; the still-running day is a partial bar that cannot fill); expiries are counted from the signal row,
never looked up from a later bar, so the live day sees each setup when its bar closes."""

from __future__ import annotations

import numpy as np

import yc_ind as I
import yt_ind as YI
from yc_common import ctx, sig
from yc_engine import XExits
from yt_engine import Signal

import zd_common as Z
import ze_common as E
from ze_more2 import _last_done, _swing_levels

TICK = 1e-5            # 'one tick' beyond a level: 0.001% of the price (about 1 dollar on bitcoin, 4 cents on gold)


def _fin(*xs) -> bool:
    return all(np.isfinite(x) for x in xs)


def _cached(cache, key, fn):
    if key not in cache:
        cache[key] = fn()
    return cache[key]


def _daily(m, cache):
    """One bar per trading day of the minute market (gold's day rolls at 17:00 New York, bitcoin's is the UTC date);
    a day's bar is known after its last row."""
    def calc():
        import bb_markets as BM
        d0 = np.asarray(m.d0, np.int64)
        d1 = np.asarray(m.d1, np.int64)
        n = len(d0)
        o = np.asarray(m.o, float)[d0]
        h = np.maximum.reduceat(np.asarray(m.h, float), d0)
        l = np.minimum.reduceat(np.asarray(m.l, float), d0)
        c = np.asarray(m.c, float)[d1 - 1]
        t0 = np.asarray(m.t, np.int64)[d0]
        ist0, ny0 = BM._clocks(t0)
        idx = np.arange(n, dtype=np.int64)
        return BM.Bars(1440, idx, d0, d1 - 1, t0, o, h, l, c, ist0, ny0, idx, idx + 1)
    return _cached(cache, ("ze4_daily",), calc)


def _new_swings(b, n=2):
    """(swing low, swing high) of n-bar fractals at the bar that confirms them (n bars after the pivot), NaN elsewhere:
    a trail that moves only to swings confirmed while the trade is open."""
    ph, pl = YI.fractals(b, n)
    N = len(b.c)
    lo = np.full(N, np.nan)
    hi = np.full(N, np.nan)
    for j in range(n, N):
        if pl[j - n]:
            lo[j] = float(b.l[j - n])
        if ph[j - n]:
            hi[j] = float(b.h[j - n])
    return lo, hi


# ═══ NK-02 daily gold: SMA 20 / SMA 50 aligned, RSI (7) oversold pullback, 10-day-low stop trailed to new swing lows ═

def _nk02_arr(m, cache):
    def calc():
        db = _daily(m, cache)
        c = np.asarray(db.c, float)
        lo, hi = _new_swings(db, 2)
        return db, I.sma(c, 20), I.sma(c, 50), I.rsi(c, 7), lo, hi
    return _cached(cache, ("ze4_nk02",), calc)


def nk02(m, B, p, cache):
    db, s20, s50, r7, _, _ = _nk02_arr(m, cache)
    out = []
    for j in range(50, len(db.c)):
        if not _fin(s20[j], s50[j], r7[j]):
            continue
        if s20[j] > s50[j] and r7[j] <= 30:
            out.append(sig(db, j, 1, float(np.min(db.l[j - 9:j + 1])) * 0.999, "NK02_SMA_ALIGNED_RSI7_OVERSOLD_LONG"))
        elif s20[j] < s50[j] and r7[j] >= 70:
            out.append(sig(db, j, -1, float(np.max(db.h[j - 9:j + 1])) * 1.001, "NK02_SMA_ALIGNED_RSI7_OVERBOUGHT_SHORT"))
    return out


def nk02_x(m, B, p, cache):
    db, _, _, _, lo, hi = _nk02_arr(m, cache)
    return XExits(target_r=None, trail=("level", db, lo, hi))


# ═══ RT-02 4-hour bitcoin: close above the Bollinger Band (200, 4) over the 300-bar average, out below the (200, 0.5) ═

def _rt02_arr(m, B, cache):
    def calc():
        c = np.asarray(B[240].c, float)
        mid, up4, _ = I.bollinger(c, 200, 4.0)
        lo05 = mid - (up4 - mid) / 8.0                 # 0.5 standard deviations under the 200-bar average
        return up4, lo05, I.sma(c, 300)
    return _cached(cache, ("ze4_rt02",), calc)


def rt02(m, B, p, cache):
    b = B[240]
    up4, lo05, s300 = _rt02_arr(m, B, cache)
    c = b.c
    out = []
    for j in range(300, len(c)):
        if _fin(up4[j], lo05[j], s300[j]) and c[j] > up4[j] and c[j] > s300[j] and lo05[j] < c[j]:
            out.append(sig(b, j, 1, float(lo05[j]), "RT02_BB200_4SD_CLOSE_ABOVE_LONG"))
    return out


def rt02_x(m, B, p, cache):
    b = B[240]
    _, lo05, _ = _rt02_arr(m, B, cache)
    c = np.asarray(b.c, float)
    xl = np.isfinite(lo05) & (c < np.where(np.isfinite(lo05), lo05, -np.inf))
    return XExits(target_r=None, xbars=b, xlong=xl, xshort=np.zeros(len(c), bool))


# ═══ TT-02 daily break of the highest high above the 50 EMA, a 4-hour candle combination at the broken level, 2R ═════

def _tt02_state(m, cache):
    """Per daily bar, after its close: (trend +1 / -1 / 0, zone). The highest high of the prior 20 sessions that closed
    above the 50 EMA; a close above it starts (or renews) the uptrend and makes it the zone; mirror with the lowest low
    of the sessions that closed below the EMA. The zone lasts until the opposite break."""
    def calc():
        db = _daily(m, cache)
        h, l, c = (np.asarray(x, float) for x in (db.h, db.l, db.c))
        e50 = I.ema(c, 50)
        n = len(c)
        trend = np.zeros(n, np.int64)
        zone = np.full(n, np.nan)
        tr, zn = 0, np.nan
        for d in range(50, n):
            w = slice(d - 20, d)
            up, dn = c[w] > e50[w], c[w] < e50[w]
            hh = float(np.max(h[w][up])) if up.any() else np.nan
            ll = float(np.min(l[w][dn])) if dn.any() else np.nan
            if np.isfinite(hh) and c[d] > hh:
                tr, zn = 1, hh
            elif np.isfinite(ll) and c[d] < ll:
                tr, zn = -1, ll
            trend[d], zone[d] = tr, zn
        return db, trend, zone
    return _cached(cache, ("ze4_tt02",), calc)


def tt02(m, B, p, cache):
    b = B[240]
    db, trend, zone = _tt02_state(m, cache)
    a14 = ctx(m, B, 240, cache).atr(14)
    h, l = b.h, b.l
    out = []
    watch = None                                       # (side, zone, last bar the pattern candle may be on)
    for j in range(1, len(b.c)):
        d = _last_done(db, b, j)
        if d < 50 or trend[d] == 0 or not np.isfinite(zone[d]):
            watch = None
            continue
        side, z = int(trend[d]), float(zone[d])
        if watch is not None and (watch[0] != side or watch[1] != z):
            watch = None
        if watch is not None and j - 1 <= watch[2] and np.isfinite(a14[j]):
            pat = E.pin_bar(b, j - 1, side) or E.engulf(b, j - 1, side)
            conf = (b.c[j] > b.o[j]) if side > 0 else (b.c[j] < b.o[j])
            if pat and conf:
                if side > 0:
                    stop = float(min(l[j - 1], l[j])) - 0.5 * float(a14[j])
                    out.append(sig(b, j, 1, stop, "TT02_ZONE_COMBO_LONG"))
                else:
                    stop = float(max(h[j - 1], h[j])) + 0.5 * float(a14[j])
                    out.append(sig(b, j, -1, stop, "TT02_ZONE_COMBO_SHORT"))
                watch = None
                continue
        if h[j] >= z * 0.997 and l[j] <= z * 1.003:     # this bar comes within 0.3% of the zone: a six-bar watch
            watch = (side, z, j + 5)
        elif watch is not None and j - 1 >= watch[2]:
            watch = None
    return out


def tt02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ TC-04 five-minute trend continuation: a close outside the opposite Bollinger Band (20, 1), back within 3 bars ════

def tc04(m, B, p, cache):
    b = B[5]
    cx = ctx(m, B, 5, cache)
    e100 = cx.ema(100)
    mid, up1, lo1 = cx.bollinger(20, 1.0)
    h, l, c = b.h, b.l, b.c
    ok = np.isfinite(mid)
    above = ok & (c > np.where(ok, mid, np.inf))
    below = ok & (c < np.where(ok, mid, -np.inf))
    out = []
    corr = None                                        # (side, first correction bar, the 12-bar extreme before it)
    for j in range(113, len(c)):
        if not _fin(e100[j], mid[j], up1[j], lo1[j]):
            corr = None
            continue
        if corr is not None:
            side, c0, lvl = corr
            if j - c0 > 3:
                corr = None
            elif (c[j] >= lo1[j]) if side > 0 else (c[j] <= up1[j]):     # back inside the band
                corr = None
                if (c[j] > e100[j]) if side > 0 else (c[j] < e100[j]):
                    ext = float(np.min(l[c0:j + 1])) if side > 0 else float(np.max(h[c0:j + 1]))
                    trig = lvl * (1 + side * TICK)
                    if (trig - c[j]) * side > 0:
                        out.append(sig(b, j, side, ext * (1 - side * TICK),
                                       "TC04_BB1_CORRECTION_BREAK_LONG" if side > 0 else "TC04_BB1_CORRECTION_BREAK_SHORT",
                                       entry_stop=float(trig), expire_k=int(b.i1[j]) + 24 * 5))
                continue
            else:
                continue
        if c[j] < lo1[j] and c[j] > e100[j] and int(above[j - 12:j].sum()) >= 6:
            corr = (1, j, float(np.max(h[j - 12:j])))
        elif c[j] > up1[j] and c[j] < e100[j] and int(below[j - 12:j].sum()) >= 6:
            corr = (-1, j, float(np.min(l[j - 12:j])))
    return out


def tc04_x(m, B, p, cache):
    return XExits(target_r=3.0)


# ═══ BX-01 first green Heikin Ashi candle with MFI (14) oversold; out on the first red one after MFI reaches 80 ═══════

def _bx01_arr(m, B, cache):
    def calc():
        b = B[15]
        ho, hc = YI.heikin_ashi(b)
        grn, red = hc > ho, hc < ho
        mf = Z.mfi(b, ctx(m, B, 15, cache).vol(), 14)
        xl = np.zeros(len(hc), bool)
        armed = False                                  # MFI has reached 80 since the last red candle
        for j in range(len(hc)):
            if np.isfinite(mf[j]) and mf[j] >= 80:
                armed = True
            if red[j]:
                xl[j] = armed
                armed = False
        return grn, red, mf, xl
    return _cached(cache, ("ze4_bx01",), calc)


def bx01(m, B, p, cache):
    b = B[15]
    grn, red, mf, _ = _bx01_arr(m, B, cache)
    out = []
    for j in range(16, len(b.c)):
        if not (grn[j] and red[j - 1] and red[j - 2]):
            continue
        if (np.isfinite(mf[j]) and mf[j] <= 20) or (np.isfinite(mf[j - 1]) and mf[j - 1] <= 20):
            out.append(sig(b, j, 1, float(b.c[j]) * 0.98, "BX01_HA_FIRST_GREEN_MFI_OVERSOLD_LONG", info={"stop_frac": 0.02}))
    return out


def bx01_x(m, B, p, cache):
    b = B[15]
    _, _, _, xl = _bx01_arr(m, B, cache)
    return XExits(target_r=None, xbars=b, xlong=xl, xshort=np.zeros(len(xl), bool))


# ═══ BX-02 TradingView Pivot Reversal (4 left, 2 right) on 1-hour bars: stop orders at the latest pivots, stop and reverse

def _pivots_lr(b, left=4, right=2):
    """ta.pivothigh / ta.pivotlow(left, right): flags at the pivot bar, known `right` bars later."""
    h, l = np.asarray(b.h, float), np.asarray(b.l, float)
    n = len(h)
    ph = np.zeros(n, bool)
    pl = np.zeros(n, bool)
    for q in range(left, n - right):
        if h[q] > h[q - left:q].max() and h[q] >= h[q + 1:q + right + 1].max():
            ph[q] = True
        if l[q] < l[q - left:q].min() and l[q] <= l[q + 1:q + right + 1].min():
            pl[q] = True
    return ph, pl


def _bx02_arr(m, B, cache):
    """Per 1-hour bar, after its close: the buy level (latest confirmed pivot high + a tick) and the sell level (latest
    confirmed pivot low - a tick)."""
    def calc():
        b = B[60]
        ph, pl = _pivots_lr(b, 4, 2)
        n = len(b.c)
        buy = np.full(n, np.nan)
        sell = np.full(n, np.nan)
        ch = cl = np.nan
        for j in range(n):
            q = j - 2
            if q >= 0:
                if ph[q]:
                    ch = float(b.h[q]) * (1 + TICK)
                if pl[q]:
                    cl = float(b.l[q]) * (1 - TICK)
            buy[j], sell[j] = ch, cl
        return buy, sell
    return _cached(cache, ("ze4_bx02",), calc)


def bx02(m, B, p, cache):
    """From flat: both stop orders rest through the next hour (an OCO, re-placed at every close; each side only while
    its level is beyond the close). In a position, the opposite level is the stop (bx02_x trails it to each new pivot),
    and the minute that crosses it also stamps the reversal: a market order in the new direction two rows later (the
    engine needs the old position closed before the new order is placed)."""
    b = B[60]
    buy, sell = _bx02_arr(m, B, cache)
    c = b.c
    mh, ml = np.asarray(m.h, float), np.asarray(m.l, float)
    last = len(m.t) - 1
    out = []
    for j in range(len(c)):
        bl, sl = buy[j], sell[j]
        long_ok = np.isfinite(bl) and np.isfinite(sl) and c[j] < bl and sl < bl
        short_ok = np.isfinite(bl) and np.isfinite(sl) and c[j] > sl and sl < bl
        exp = int(b.i1[j]) + 60
        lo = sig(b, j, 1, float(sl), "BX02_PIVOT_HIGH_BREAK_LONG", entry_stop=float(bl), expire_k=exp) if long_ok else None
        sh = sig(b, j, -1, float(bl), "BX02_PIVOT_LOW_BREAK_SHORT", entry_stop=float(sl), expire_k=exp) if short_ok else None
        if lo is not None and sh is not None:
            lo.alt = sh
            out.append(lo)
        elif lo is not None or sh is not None:
            out.append(lo or sh)
        if j + 1 >= len(c):
            continue
        # the next bar's rows: the first that crosses each resting level stamps a reversal order
        a, z = int(b.i0[j + 1]), int(b.i1[j + 1])
        for side, lvl, ok in ((1, bl, long_ok), (-1, sl, short_ok)):
            if not ok:
                continue
            seg = mh[a:z + 1] >= lvl if side > 0 else ml[a:z + 1] <= lvl
            hit = np.flatnonzero(seg)
            if not len(hit):
                continue
            k = a + int(hit[0]) + 1                   # the row after the cross: the old position is closed by then
            if k >= last:
                continue
            done = int(np.searchsorted(b.i1, k, "right")) - 1     # the last hourly bar complete at row k
            stop = sell[done] if side > 0 else buy[done]
            if not np.isfinite(stop):
                continue
            out.append(Signal(int(m.day[k]), k, side, float(stop),
                              "BX02_REVERSE_TO_LONG" if side > 0 else "BX02_REVERSE_TO_SHORT"))
    return out


def bx02_x(m, B, p, cache):
    b = B[60]
    buy, sell = _bx02_arr(m, B, cache)
    return XExits(target_r=None, trail=("level", b, sell, buy))


# ═══ CB-01 1-hour swing trend, a 5-minute structure shift after a retrace to a new swing, half off at 1R, rest at 2R ═══

def cb01(m, B, p, cache):
    b, bh = B[5], B[60]
    hv, _, lv, _, phv, plv = ctx(m, B, 60, cache).pivots(2)
    lo5, hi5 = _swing_levels(b, 2)
    ph, pl = YI.fractals(b, 2)
    h, l, c = b.h, b.l, b.c
    out = []
    arm_s = arm_l = None                               # the retrace's extreme (a new confirmed 5-minute swing)
    for j in range(2, len(c)):
        k1 = _last_done(bh, b, j)
        tr = 0
        if k1 >= 0 and _fin(hv[k1], phv[k1], lv[k1], plv[k1]):
            if hv[k1] < phv[k1] and lv[k1] < plv[k1]:
                tr = -1
            elif hv[k1] > phv[k1] and lv[k1] > plv[k1]:
                tr = 1
        if tr != -1:
            arm_s = None
        if tr != 1:
            arm_l = None
        q = j - 2
        if tr == -1 and ph[q]:
            arm_s = float(h[q])
        if tr == 1 and pl[q]:
            arm_l = float(l[q])
        if arm_s is not None and h[j] > arm_s:          # traded through the retrace high: no shift from it
            arm_s = None
        if arm_l is not None and l[j] < arm_l:
            arm_l = None
        if arm_s is not None and np.isfinite(lo5[j]) and c[j] < lo5[j]:
            out.append(sig(b, j, -1, arm_s * 1.0005, "CB01_H1_DOWNTREND_M5_SHIFT_SHORT"))
            arm_s = None
        elif arm_l is not None and np.isfinite(hi5[j]) and c[j] > hi5[j]:
            out.append(sig(b, j, 1, arm_l * 0.9995, "CB01_H1_UPTREND_M5_SHIFT_LONG"))
            arm_l = None
    return out


def cb01_x(m, B, p, cache):
    return XExits(target_r=2.0, partial_at_r=1.0)


# ═══ VS-02 4-hour gold: SMA 9 over the EMA 20, confirmed by the next close, 2 ATR stop, trailed at EMA 20 - 1 ATR ════

def vs02(m, B, p, cache):
    b = B[240]
    cx = ctx(m, B, 240, cache)
    s9, e20, a14 = cx.sma(9), cx.ema(20), cx.atr(14)
    out = []
    for j in range(22, len(b.c)):
        i = j - 1
        if not _fin(s9[i - 1], e20[i - 1], s9[i], e20[i], s9[j], e20[j], a14[j]):
            continue
        if s9[i] > e20[i] and s9[i - 1] <= e20[i - 1] and s9[j] > e20[j]:
            dist = 2.0 * float(a14[j])
            out.append(sig(b, j, 1, float(b.c[j]) - dist, "VS02_SMA9_EMA20_CROSS_CONFIRMED_LONG", info={"stop_dist": dist}))
    return out


def vs02_x(m, B, p, cache):
    b = B[240]
    cx = ctx(m, B, 240, cache)
    lv = cx.ema(20) - cx.atr(14)
    return XExits(target_r=None, trail=("level", b, lv, np.full(len(lv), np.nan)))


# ═══ VS-03 gold weekend gap: a 1-hour break of the 6-bar box toward the gap, target the previous week's close ═════════

def _vs03_weeks(m, cache):
    """Per trading day: the previous week's last close and the week's first open when the day opens a week (rows more
    than 40 hours apart), else NaN."""
    def calc():
        t = np.asarray(m.t, np.int64)
        d0 = np.asarray(m.d0, np.int64)
        pc = np.full(len(d0), np.nan)
        op = np.full(len(d0), np.nan)
        for d in range(1, len(d0)):
            r0 = int(d0[d])
            if t[r0] - t[r0 - 1] > 40 * 3600:
                pc[d], op[d] = float(m.c[r0 - 1]), float(m.o[r0])
        return pc, op
    return _cached(cache, ("ze4_vs03",), calc)


def vs03(m, B, p, cache):
    b = B[60]
    pc, op = _vs03_weeks(m, cache)
    h, l, c = b.h, b.l, b.c
    out = []
    for d in range(1, m.n_days):
        P, O = pc[d], op[d]
        if not _fin(P, O) or abs(O / P - 1) < 0.0015:
            continue
        side = 1 if O < P else -1                      # a gap down is bought toward its fill
        j0 = int(b.b0[d])
        j1 = int(b.b1[min(d + 2, m.n_days - 1)])       # the week's first 3 trading days
        for j in range(j0, j1):
            if (h[j] >= P) if side > 0 else (l[j] <= P):    # filled before any breakout: nothing this week
                break
            if j - 6 < j0:
                continue
            if side > 0 and c[j] > np.max(h[j - 6:j]):
                out.append(sig(b, j, 1, float(np.min(l[j - 6:j])) * 0.9995, "VS03_GAP_DOWN_BOX_BREAK_LONG",
                               target_px=float(P) * 0.9998))
                break
            if side < 0 and c[j] < np.min(l[j - 6:j]):
                out.append(sig(b, j, -1, float(np.max(h[j - 6:j])) * 1.0005, "VS03_GAP_UP_BOX_BREAK_SHORT",
                               target_px=float(P) * 1.0002))
                break
    return out


def vs03_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ FL-02 Williams Alligator: the candle clear of all three lines and engulfing, with the 1-hour EMA 50 side, 1R ═════

def _alli(m, B, cache):
    return _cached(cache, ("ze4_alli5",), lambda: I.alligator(B[5]))


def fl02(m, B, p, cache):
    b, bh = B[5], B[60]
    jaw, teeth, lips = _alli(m, B, cache)
    e50 = ctx(m, B, 60, cache).ema(50)
    out = []
    for j in range(30, len(b.c)):
        if not _fin(jaw[j], teeth[j], lips[j]):
            continue
        k1 = _last_done(bh, b, j)
        if k1 < 50:
            continue
        top = max(jaw[j], teeth[j], lips[j])
        bot = min(jaw[j], teeth[j], lips[j])
        if b.l[j] > top and E.engulf(b, j, 1) and bh.c[k1] > e50[k1]:
            out.append(sig(b, j, 1, float(bot) * (1 - 0.0002), "FL02_ALLIGATOR_ENGULF_LONG"))
        elif b.h[j] < bot and E.engulf(b, j, -1) and bh.c[k1] < e50[k1]:
            out.append(sig(b, j, -1, float(top) * (1 + 0.0002), "FL02_ALLIGATOR_ENGULF_SHORT"))
    return out


def fl02_x(m, B, p, cache):
    return XExits(target_r=1.0)
