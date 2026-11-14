"""Eighth batch of the channel-shortlist study (14-15 Nov 2026): the cards of the owner's ranks 11-20 crypto channels
(The Chart Guys, Tradeciety, Moonin Papa, Tom Crown, Part Time Larry, SCryptoTrader; cards/<video>.txt, whose 'A'
rules are this code). Same conventions as ze_more4 - ze_more6: BTCUSD and ETHUSD are Delta Exchange perpetuals on the
UTC day, XAUUSD is gold booked on Delta XAUTUSD and EURUSD / GBPUSD are the desk's forex minutes (both on the 17:00
New York day); daily bars are one bar per trading day (ze_more4._daily), known after the day's last row.

Every signal uses only the bars up to its own signal bar: swing pivots of n bars are used n bars after the pivot,
higher-timeframe values are those of the last bar finished by the signal bar's close, and order expiries are counted
in bars from the signal. The order-flow strategies (SC-02 - SC-04) read bitcoin's taker buy and total taker volume per
minute (m.bv, m.vol_all; on the desk the order-flow recorder's minutes, NaN where a minute was not recorded): a
candle's delta is 2 x buys - total, unknown when any of its minutes is."""

from __future__ import annotations

import numpy as np
import pandas as pd

import yc_ind as I
import yt_ind as YI
from yc_common import ctx, sig
from yc_engine import XExits
from ze_more2 import _last_done
from ze_more4 import TICK, _cached, _daily, _fin

DAY_ROWS = 1440                      # one day of one-minute rows (max_hold counts rows)


# ── shared pieces ───────────────────────────────────────────────────────────────────────────────────────────────────

def _prior_max(x, n):
    """Max of x over the n bars before each bar (NaN until n bars exist)."""
    return pd.Series(np.asarray(x, float)).rolling(n, min_periods=n).max().shift(1).to_numpy()


def _prior_min(x, n):
    return pd.Series(np.asarray(x, float)).rolling(n, min_periods=n).min().shift(1).to_numpy()


def _bar_delta(m, b):
    """Per bar: taker buys minus taker sells (NaN when any minute of the bar is unknown); None without order flow."""
    bv, va = getattr(m, "bv", None), getattr(m, "vol_all", None)
    if bv is None or va is None or len(bv) != len(m.t) or not len(b.i0):
        return None
    buy = np.add.reduceat(np.asarray(bv, float), b.i0)
    vol = np.add.reduceat(np.asarray(va, float), b.i0)
    return 2.0 * buy - vol


def _days_since_start(b, j):
    return (float(b.t0[j]) - float(b.t0[0])) / 86400.0


def _div_scan(b, osc, n, wait, pair_ok=None, allow=None, trig_ok=None, same_day=False):
    """Divergence setups and their triggers, as known bar by bar. Bearish: the last two confirmed n-bar pivot highs
    p1 < p2 with a higher high and a lower osc (and pair_ok(p1, p2, -1)); it triggers on the first close below the
    lowest low between them (from the bar that confirms p2), within `wait` bars of p2, unless price first trades above
    the high of p2; allow(j, side) and trig_ok(j, side) filter the trigger bar. Bullish mirror on pivot lows.
    Returns [(j, side, level, p2)]."""
    ph, pl = YI.fractals(b, n)
    h, l, c = np.asarray(b.h, float), np.asarray(b.l, float), np.asarray(b.c, float)
    osc = np.asarray(osc, float)
    out = []
    his, los = [], []
    act = {1: None, -1: None}
    for j in range(len(c)):
        p = j - n
        if p >= 1:
            for side, flags, lst in ((-1, ph, his), (1, pl, los)):
                if not flags[p]:
                    continue
                lst.append(p)
                act[side] = None
                if len(lst) < 2:
                    continue
                p1, p2 = lst[-2], lst[-1]
                if same_day and b.day[p1] != b.day[p2]:
                    continue
                if not _fin(osc[p1], osc[p2]):
                    continue
                if side < 0 and h[p2] > h[p1] and osc[p2] < osc[p1] and (pair_ok is None or pair_ok(p1, p2, -1)):
                    lev = float(np.min(l[p1 + 1:p2])) if p2 > p1 + 1 else float(l[p1])
                    act[-1] = (p2, lev)
                elif side > 0 and l[p2] < l[p1] and osc[p2] > osc[p1] and (pair_ok is None or pair_ok(p1, p2, 1)):
                    lev = float(np.max(h[p1 + 1:p2])) if p2 > p1 + 1 else float(h[p1])
                    act[1] = (p2, lev)
        for side in (-1, 1):
            s = act[side]
            if s is None:
                continue
            p2, lev = s
            if j - p2 > wait or (same_day and b.day[j] != b.day[p2]):
                act[side] = None
                continue
            if (h[j] > h[p2]) if side < 0 else (l[j] < l[p2]):
                act[side] = None
                continue
            hit = (c[j] < lev) if side < 0 else (c[j] > lev)
            if hit and (allow is None or allow(j, side)) and (trig_ok is None or trig_ok(j, side)):
                out.append((j, side, lev, p2))
                act[side] = None
    return out


def _div_signals(b, scan, label):
    """Market entries at the next open from _div_scan triggers, the stop just beyond the second swing's extreme."""
    h, l = b.h, b.l
    out = []
    for j, side, _lev, p2 in scan:
        if side < 0:
            out.append(sig(b, j, -1, float(np.max(h[p2:j + 1])) * (1 + TICK), label + "_SHORT"))
        else:
            out.append(sig(b, j, 1, float(np.min(l[p2:j + 1])) * (1 - TICK), label + "_LONG"))
    return out


# ═══ CG-03 Back burner, 5 minutes: the first RSI (14) close under 30 after a new 30-day high ════════════════════════

def cg03(m, B, p, cache):
    b = B[5]
    cx = ctx(m, B, 5, cache)
    rsi, a14 = cx.rsi(14), cx.atr(14)
    h, l = np.asarray(b.h, float), np.asarray(b.l, float)
    hi30 = _cached(cache, ("ze7_cg03_hi30",), lambda: _prior_max(h, 30 * 288))
    out = []
    armed, low = False, np.inf
    for j in range(1, len(b.c)):
        if np.isfinite(hi30[j]) and h[j] > hi30[j] and _days_since_start(b, j) >= 30:
            armed, low = True, float(l[j])           # a new 30-day high (re)arms the setup
            continue
        if not armed:
            continue
        low = min(low, float(l[j]))
        if _fin(rsi[j], a14[j]) and rsi[j] < 30:
            out.append(sig(b, j, 1, low - float(a14[j]), "CG03_BACK_BURNER_5M_LONG"))
            armed = False                            # once per new high
    return out


def cg03_x(m, B, p, cache):
    return XExits(target_r=3.0, partial_at_r=1.0, max_hold=180)


# ═══ CG-04 Back burner, 4 hours: the first 4-hour RSI (14) under 30 after a new 90-day high, daily close over EMA 50 ═

def cg04(m, B, p, cache):
    b = B[240]
    cx = ctx(m, B, 240, cache)
    rsi, a14 = cx.rsi(14), cx.atr(14)
    db = _daily(m, cache)
    de50 = _cached(cache, ("ze7_d_ema50",), lambda: I.ema(np.asarray(db.c, float), 50))
    h, l = np.asarray(b.h, float), np.asarray(b.l, float)
    hi90 = _prior_max(h, 90 * 6)
    out = []
    armed, low = False, np.inf
    for j in range(1, len(b.c)):
        if np.isfinite(hi90[j]) and h[j] > hi90[j]:
            armed, low = True, float(l[j])
            continue
        if not armed:
            continue
        low = min(low, float(l[j]))
        if not (_fin(rsi[j], a14[j]) and rsi[j] < 30):
            continue
        k = _last_done(db, b, j)
        if k >= 60 and _fin(de50[k]) and db.c[k] > de50[k]:
            out.append(sig(b, j, 1, low - float(a14[j]), "CG04_BACK_BURNER_4H_LONG"))
        armed = False                                # the first oversold close after the high, taken or not
    return out


def cg04_x(m, B, p, cache):
    return XExits(target_r=3.0, partial_at_r=1.0)


# ═══ CG-05 Stair step: 10+ higher lows (lower highs) in a row, a stop entry at the last stair candle's far end ══════

def cg05(m, B, p, cache):
    b = B[5]
    a14 = ctx(m, B, 5, cache).atr(14)
    db = _daily(m, cache)
    de12 = _cached(cache, ("ze7_d_ema12",), lambda: I.ema(np.asarray(db.c, float), 12))
    h, l = np.asarray(b.h, float), np.asarray(b.l, float)
    n = len(b.c)
    out = []
    up = dn = 0                                       # consecutive higher lows / lower highs ending at the bar
    for j in range(1, n):
        if b.day[j] != b.day[j - 1]:
            up = dn = 0
            continue
        up = up + 1 if l[j] > l[j - 1] else 0
        dn = dn + 1 if h[j] < h[j - 1] else 0
        if (up < 10 and dn < 10) or not _fin(a14[j]):
            continue
        k = _last_done(db, b, j)
        if k < 24 or not _fin(de12[k]):
            continue
        exp = int(b.i1[min(j + 1, n - 1)])           # live for the next candle only
        if up >= 10 and db.c[k] < de12[k]:
            stop = float(np.max(h[j - up:j + 1])) * (1 + 0.0005)
            if stop - l[j] <= 2 * a14[j]:
                out.append(sig(b, j, -1, stop, "CG05_STAIR_STEP_SHORT", entry_stop=float(l[j]), expire_k=exp))
        if dn >= 10 and db.c[k] > de12[k]:
            stop = float(np.min(l[j - dn:j + 1])) * (1 - 0.0005)
            if h[j] - stop <= 2 * a14[j]:
                out.append(sig(b, j, 1, stop, "CG05_STAIR_STEP_LONG", entry_stop=float(h[j]), expire_k=exp))
    return out


def cg05_x(m, B, p, cache):
    return XExits(target_r=3.0, partial_at_r=1.0, partial_be=False)


# ═══ TC-05 Daily Bollinger (20, 2.5) spike and snap-back, next day's 15-minute engulfing candle with the EMA 50 ═════

def _tc05_spikes(m, cache):
    def calc():
        db = _daily(m, cache)
        c = np.asarray(db.c, float)
        _, up, lo = I.bollinger(c, 20, 2.5)
        ok = np.isfinite(up) & np.isfinite(lo)
        lng = ok & (np.asarray(db.l, float) < np.where(ok, lo, -np.inf)) & (c > np.where(ok, lo, np.inf))
        sht = ok & (np.asarray(db.h, float) > np.where(ok, up, np.inf)) & (c < np.where(ok, up, -np.inf))
        return lng, sht
    return _cached(cache, ("ze7_tc05",), calc)


def tc05(m, B, p, cache):
    b = B[15]
    e50 = ctx(m, B, 15, cache).ema(50)
    lng, sht = _tc05_spikes(m, cache)
    o, h, l, c = (np.asarray(x, float) for x in (b.o, b.h, b.l, b.c))
    out = []
    for j in range(60, len(c)):
        d = int(b.day[j]) - 1                         # the spike day: the trading day before this bar's day
        if d < 0 or not (lng[d] or sht[d]) or not _fin(e50[j]):
            continue
        wide_up = h[j] > max(h[j - 1], h[j - 2])
        wide_dn = l[j] < min(l[j - 1], l[j - 2])
        if not (wide_up and wide_dn):
            continue
        if lng[d] and c[j] > o[j] and c[j] > e50[j]:
            out.append(sig(b, j, 1, float(l[j]) * (1 - TICK), "TC05_BB_SPIKE_ENGULF_LONG"))
        elif sht[d] and c[j] < o[j] and c[j] < e50[j]:
            out.append(sig(b, j, -1, float(h[j]) * (1 + TICK), "TC05_BB_SPIKE_ENGULF_SHORT"))
    return out


def tc05_x(m, B, p, cache):
    b = B[15]
    return XExits(target_r=None, trail_from_r=0.0, trail_bars=b, trail_ema=ctx(m, B, 15, cache).ema(50))


# ═══ TC-08 Daily fakeout: a new 20-day high (low), then a close back under the prior day's low (over its high), 2R ═══

def tc08(m, B, p, cache):
    db = _daily(m, cache)
    o, h, l, c = (np.asarray(x, float) for x in (db.o, db.h, db.l, db.c))
    a14 = _cached(cache, ("ze7_d_atr14",), lambda: YI.atr(db, 14))
    out = []
    for k in range(22, len(c)):
        if not _fin(a14[k]):
            continue
        prior_hi = float(np.max(h[k - 21:k - 1]))
        prior_lo = float(np.min(l[k - 21:k - 1]))
        top = max(h[k - 1], h[k])
        bot = min(l[k - 1], l[k])
        if top > prior_hi and c[k] < o[k] and c[k] < l[k - 1]:
            out.append(sig(db, k, -1, float(top + 0.25 * a14[k]), "TC08_DAILY_FAKEOUT_SHORT"))
        elif bot < prior_lo and c[k] > o[k] and c[k] > h[k - 1]:
            out.append(sig(db, k, 1, float(bot - 0.25 * a14[k]), "TC08_DAILY_FAKEOUT_LONG"))
    return out


def tc08_x(m, B, p, cache):
    return XExits(target_r=2.0, max_hold=5 * DAY_ROWS)


# ═══ TC-10 15-minute pullback against the 4-hour EMA 50 with an RSI (14) divergence, a strong close through, 2R ═════

def tc10(m, B, p, cache):
    b, b4 = B[15], B[240]
    cx = ctx(m, B, 15, cache)
    rsi, a15 = cx.rsi(14), cx.atr(14)
    e4 = ctx(m, B, 240, cache).ema(50)
    o, c = np.asarray(b.o, float), np.asarray(b.c, float)
    h, l = np.asarray(b.h, float), np.asarray(b.l, float)

    def ema4(j):
        k = _last_done(b4, b, j)
        return float(e4[k]) if k >= 100 and _fin(e4[k]) else np.nan

    def pair_ok(p1, p2, side):
        e, a = ema4(p2), a15[p2]
        if not _fin(e, a):
            return False
        return (0 <= e - h[p2] <= a) if side < 0 else (0 <= l[p2] - e <= a)

    def allow(j, side):
        e = ema4(j)
        return _fin(e) and ((c[j] < e) if side < 0 else (c[j] > e))

    def strong(j, side):
        return _fin(a15[j]) and side * (c[j] - o[j]) >= 0.5 * a15[j]

    scan = _cached(cache, ("ze7_tc10",), lambda: _div_scan(b, rsi, 3, 20, pair_ok, allow, strong))
    return _div_signals(b, scan, "TC10_RSI_DIV_PULLBACK")


def tc10_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ TC-11 RSI (14) divergence at a lower low (higher high), a close beyond the high (low) between the swings, 2R ═══

def tc11(m, B, p, cache):
    b = B[60]
    rsi = ctx(m, B, 60, cache).rsi(14)
    scan = _cached(cache, ("ze7_tc11",), lambda: _div_scan(b, rsi, 3, 30))
    return _div_signals(b, scan, "TC11_RSI_DIV_REVERSAL")


def tc11_x(m, B, p, cache):
    return XExits(target_r=2.0, max_hold=3 * DAY_ROWS)


# ═══ TC-13 Central pivot rejection with the pivot trend: a pin at the daily pivot, a strong candle away, S1/S2 ══════

def tc13(m, B, p, cache):
    b = B[15]
    a15 = ctx(m, B, 15, cache).atr(14)
    H, L, C = _cached(cache, ("ze7_day_hlc",), lambda: I.day_hlc(m))
    o, h, l, c = (np.asarray(x, float) for x in (b.o, b.h, b.l, b.c))
    out = []
    for j in range(2, len(c)):
        d = int(b.day[j])
        if d < 2 or b.day[j - 1] != d or not _fin(a15[j]):
            continue
        P = (H[d - 1] + L[d - 1] + C[d - 1]) / 3
        P0 = (H[d - 2] + L[d - 2] + C[d - 2]) / 3
        rng = H[d - 1] - L[d - 1]
        t = j - 1
        if P < P0 and o[t] < P <= h[t] and c[t] < P and c[j] < o[j] and o[j] - c[j] >= a15[j] and c[j] < l[t]:
            stop = float(max(h[t], h[j])) * (1 + TICK)
            s1, s2 = 2 * P - H[d - 1], P - rng
            tgt = s1 if c[j] > s1 else s2
            if c[j] - tgt >= stop - c[j]:
                out.append(sig(b, j, -1, stop, "TC13_PIVOT_REJECT_SHORT", target_px=float(tgt)))
        elif P > P0 and o[t] > P >= l[t] and c[t] > P and c[j] > o[j] and c[j] - o[j] >= a15[j] and c[j] > h[t]:
            stop = float(min(l[t], l[j])) * (1 - TICK)
            r1, r2 = 2 * P - L[d - 1], P + rng
            tgt = r1 if c[j] < r1 else r2
            if tgt - c[j] >= c[j] - stop:
                out.append(sig(b, j, 1, stop, "TC13_PIVOT_REJECT_LONG", target_px=float(tgt)))
    return out


def tc13_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ MN-05 Ichimoku cloud breakout with the lagging span above the cloud (4 hours, long only), 3%, out back inside ══

def _mn05_cloud(m, B, cache):
    def calc():
        b = B[240]
        h, l, c = (np.asarray(x, float) for x in (b.h, b.l, b.c))
        _, _, sa, sb = I.ichimoku(h, l, c, 9, 26, 52, 26)
        return np.fmax(sa, sb), np.fmin(sa, sb)
    return _cached(cache, ("ze7_mn05",), calc)


def mn05(m, B, p, cache):
    b = B[240]
    top, bot = _mn05_cloud(m, B, cache)
    c = np.asarray(b.c, float)
    out = []
    for j in range(27, len(c)):
        if not _fin(top[j], bot[j], top[j - 1], top[j - 26]):
            continue
        if c[j] > top[j] and not c[j - 1] > top[j - 1] and c[j] > c[j - 26] and c[j] > top[j - 26]:
            out.append(sig(b, j, 1, float(bot[j]) * (1 - TICK), "MN05_ICHIMOKU_BREAKOUT_LONG", info={"target_frac": 0.03}))
    return out


def mn05_x(m, B, p, cache):
    b = B[240]
    top, _ = _mn05_cloud(m, B, cache)
    c = np.asarray(b.c, float)
    back_in = np.isfinite(top) & (c < np.where(np.isfinite(top), top, -np.inf))
    return XExits(target_r=None, xbars=b, xlong=back_in, xshort=np.zeros(len(c), bool), max_hold=10 * DAY_ROWS)


# ═══ TK-06 Bollinger squeeze with an OBV divergence at the band, a close beyond the other band as the bands widen ═══

def tk06(m, B, p, cache):
    b = B[60]
    cx = ctx(m, B, 60, cache)
    o, h, l, c = (np.asarray(x, float) for x in (b.o, b.h, b.l, b.c))
    mid, up, lo = cx.bollinger(20, 2.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        bbw = (up - lo) / mid
    vol = cx.vol()
    obv = np.cumsum(np.sign(np.diff(c, prepend=c[0])) * vol)
    out = []
    for j in range(121, len(c)):
        if not _fin(bbw[j], bbw[j - 1], mid[j], up[j], lo[j]):
            continue
        w = bbw[j - 120:j]
        if not np.isfinite(w).all() or np.min(bbw[j - 10:j]) > np.min(w) or not bbw[j] > bbw[j - 1]:
            continue
        a1 = j - 30 + int(np.argmin(l[j - 30:j - 10]))
        b2 = j - 10 + int(np.argmin(l[j - 10:j]))
        if c[j] > o[j] and c[j] > up[j] and l[b2] < l[a1] and _fin(lo[b2]) and l[b2] <= lo[b2] and obv[b2] > obv[a1]:
            out.append(sig(b, j, 1, float(mid[j]), "TK06_SQUEEZE_OBV_LONG"))
            continue
        a1 = j - 30 + int(np.argmax(h[j - 30:j - 10]))
        b2 = j - 10 + int(np.argmax(h[j - 10:j]))
        if c[j] < o[j] and c[j] < lo[j] and h[b2] > h[a1] and _fin(up[b2]) and h[b2] >= up[b2] and obv[b2] < obv[a1]:
            out.append(sig(b, j, -1, float(mid[j]), "TK06_SQUEEZE_OBV_SHORT"))
    return out


def tk06_x(m, B, p, cache):
    return XExits(target_r=2.0, max_hold=5 * DAY_ROWS)


# ═══ TK-07 Stochastic (14, 3, 3) divergence in the EMA 50/200 trend, %K back out of the zone, a limit at the retest ═

def tk07(m, B, p, cache):
    b = B[15]
    cx = ctx(m, B, 15, cache)
    e50, e200 = cx.ema(50), cx.ema(200)
    K, _ = _cached(cache, ("ze7_stoch15",), lambda: I.stochastic(b, 14, 3, 3))
    h, l = np.asarray(b.h, float), np.asarray(b.l, float)
    n = len(b.c)

    def pair_ok(p1, p2, side):
        return (K[p2] >= 80) if side < 0 else (K[p2] <= 20)

    def allow(j, side):
        return j >= 200 and _fin(e50[j], e200[j]) and ((e50[j] < e200[j]) if side < 0 else (e50[j] > e200[j]))

    def back_out(j, side):
        return _fin(K[j]) and ((K[j] < 80) if side < 0 else (K[j] > 20))

    scan = _cached(cache, ("ze7_tk07",), lambda: _div_scan(b, K, 3, 20, pair_ok, allow, back_out))
    out = []
    for j, side, lev, p2 in scan:
        exp = int(b.i1[min(j + 12, n - 1)])
        if side < 0:
            out.append(sig(b, j, -1, float(np.max(h[p2:j + 1])) * (1 + TICK), "TK07_STOCH_DIV_RETEST_SHORT",
                           entry_limit=float(lev), expire_k=exp))
        else:
            out.append(sig(b, j, 1, float(np.min(l[p2:j + 1])) * (1 - TICK), "TK07_STOCH_DIV_RETEST_LONG",
                           entry_limit=float(lev), expire_k=exp))
    return out


def tk07_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ TK-08 Daily Stochastic RSI %K/%D cross with the daily EMA 50 side, out on the opposite cross ══════════════════

def _tk08_arr(m, cache):
    def calc():
        db = _daily(m, cache)
        c = np.asarray(db.c, float)
        K, D = YI.stoch_rsi(c, 14, 14, 3, 3)
        ok = np.r_[False, np.isfinite(K[1:]) & np.isfinite(D[1:]) & np.isfinite(K[:-1]) & np.isfinite(D[:-1])]
        Kp, Dp = np.r_[np.nan, K[:-1]], np.r_[np.nan, D[:-1]]
        x_up = ok & (K > D) & (Kp <= Dp)
        x_dn = ok & (K < D) & (Kp >= Dp)
        return db, x_up, x_dn, I.ema(c, 50), YI.atr(db, 14)
    return _cached(cache, ("ze7_tk08",), calc)


def tk08(m, B, p, cache):
    db, x_up, x_dn, e50, a14 = _tk08_arr(m, cache)
    c = np.asarray(db.c, float)
    out = []
    for k in range(60, len(c)):
        if not _fin(e50[k], a14[k]):
            continue
        d = 2.0 * float(a14[k])
        if x_up[k] and c[k] > e50[k]:
            out.append(sig(db, k, 1, float(c[k]) - d, "TK08_STOCHRSI_EMA50_LONG", info={"stop_dist": d}))
        elif x_dn[k] and c[k] < e50[k]:
            out.append(sig(db, k, -1, float(c[k]) + d, "TK08_STOCHRSI_EMA50_SHORT", info={"stop_dist": d}))
    return out


def tk08_x(m, B, p, cache):
    db, x_up, x_dn, _, _ = _tk08_arr(m, cache)
    return XExits(target_r=None, xbars=db, xlong=x_dn, xshort=x_up)


# ═══ PL-03 Supertrend (ATR 7, factor 3) bot, long only: buy the close that flips it up, sell the close that flips down ═

def _pl03_arr(m, cache):
    def calc():
        db = _daily(m, cache)
        line, dirn = YI.supertrend(db, 7, 3.0)
        prev = np.r_[0, dirn[:-1]]
        return db, line, (dirn == 1) & (prev == -1), (dirn == -1) & (prev == 1), YI.atr(db, 7)
    return _cached(cache, ("ze7_pl03",), calc)


def pl03(m, B, p, cache):
    db, line, flip_up, _, a7 = _pl03_arr(m, cache)
    out = []
    for k in range(14, len(db.c)):
        if flip_up[k] and _fin(line[k], a7[k]):
            out.append(sig(db, k, 1, float(line[k] - a7[k]), "PL03_SUPERTREND_FLIP_LONG"))
    return out


def pl03_x(m, B, p, cache):
    db, _, _, flip_dn, _ = _pl03_arr(m, cache)
    return XExits(target_r=None, xbars=db, xlong=flip_dn, xshort=np.zeros(len(db.c), bool))


# ═══ PL-06 Backtrader dip test: buy after two lower daily closes in a row, sell five days later ═════════════════════

def pl06(m, B, p, cache):
    db = _daily(m, cache)
    c = np.asarray(db.c, float)
    a14 = _cached(cache, ("ze7_d_atr14",), lambda: YI.atr(db, 14))
    out = []
    for k in range(15, len(c)):
        if c[k] < c[k - 1] < c[k - 2] and _fin(a14[k]):
            d = 3.0 * float(a14[k])
            out.append(sig(db, k, 1, float(c[k]) - d, "PL06_TWO_DOWN_CLOSES_LONG", info={"stop_dist": d}))
    return out


def pl06_x(m, B, p, cache):
    return XExits(target_r=None, max_hold=5 * DAY_ROWS)


# ═══ SC-02 Cumulative delta divergence (session CVD), entered on the close through the low (high) between swings ═══

def sc02(m, B, p, cache):
    b = B[15]
    dl = _bar_delta(m, b)
    if dl is None:
        return []

    def calc():
        cvd = np.full(len(dl), np.nan)
        run, ok = 0.0, True
        for j in range(len(dl)):
            if j == 0 or b.day[j] != b.day[j - 1]:
                run, ok = 0.0, True
            if not np.isfinite(dl[j]):
                ok = False
            run += dl[j] if ok else 0.0
            cvd[j] = run if ok else np.nan
        return _div_scan(b, cvd, 3, 12, same_day=True)

    return _div_signals(b, _cached(cache, ("ze7_sc02",), calc), "SC02_CVD_DIVERGENCE")


def sc02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ SC-03 Absorption at the previous day's low (high): a sweep candle with delta against its colour, then a close ═══

def sc03(m, B, p, cache):
    b = B[5]
    dl = _bar_delta(m, b)
    if dl is None:
        return []
    H, L, _ = _cached(cache, ("ze7_day_hlc",), lambda: I.day_hlc(m))
    o, h, l, c = (np.asarray(x, float) for x in (b.o, b.h, b.l, b.c))
    n = len(c)
    out = []
    for t in range(1, n - 1):
        d = int(b.day[t])
        if d < 1 or not np.isfinite(dl[t]):
            continue
        side = 0
        if c[t] < o[t] and l[t] < L[d - 1] and dl[t] > 0:
            side = 1
        elif c[t] > o[t] and h[t] > H[d - 1] and dl[t] < 0:
            side = -1
        if not side:
            continue
        for j in range(t + 1, min(t + 4, n)):
            if b.day[j] != d:
                break
            if side > 0 and c[j] > h[t]:
                out.append(sig(b, j, 1, float(np.min(l[t:j + 1])) * (1 - TICK), "SC03_ABSORPTION_PDL_LONG"))
                break
            if side < 0 and c[j] < l[t]:
                out.append(sig(b, j, -1, float(np.max(h[t:j + 1])) * (1 + TICK), "SC03_ABSORPTION_PDH_SHORT"))
                break
    return out


def sc03_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ SC-04 Exhaustion: a new 4-hour extreme on fading volume, a volume spike with delta against the candle ════════

def sc04(m, B, p, cache):
    b = B[5]
    dl = _bar_delta(m, b)
    if dl is None:
        return []
    vol = ctx(m, B, 5, cache).vol()
    o, h, l, c = (np.asarray(x, float) for x in (b.o, b.h, b.l, b.c))
    hi48, lo48 = _prior_max(h, 48), _prior_min(l, 48)
    n = len(c)
    out = []
    for t in range(48, n - 1):
        if not (np.isfinite(dl[t]) and _fin(hi48[t], lo48[t])):
            continue
        v12 = vol[t - 12:t]
        if not (np.mean(v12[6:]) < np.mean(v12[:6]) and vol[t] >= 2 * np.mean(v12)):
            continue
        side = 0
        if c[t] > hi48[t] and c[t] > o[t] and dl[t] < 0:
            side = -1
        elif c[t] < lo48[t] and c[t] < o[t] and dl[t] > 0:
            side = 1
        if not side:
            continue
        d = b.day[t]
        for j in range(t + 1, min(t + 4, n)):
            if b.day[j] != d:
                break
            if side < 0 and c[j] < l[t]:
                out.append(sig(b, j, -1, float(np.max(h[t:j + 1])) * (1 + TICK), "SC04_EXHAUSTION_SHORT"))
                break
            if side > 0 and c[j] > h[t]:
                out.append(sig(b, j, 1, float(np.min(l[t:j + 1])) * (1 - TICK), "SC04_EXHAUSTION_LONG"))
                break
    return out


def sc04_x(m, B, p, cache):
    return XExits(target_r=2.0)
