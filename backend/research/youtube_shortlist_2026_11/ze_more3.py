"""Fourth batch of the channel-shortlist study (13 Nov 2026): the cards read after the third deploy (cards/<video>.txt;
the 'A' rules are this code). Same markets and conventions as ze_india / ze_global / ze_more / ze_more2: NIFTY /
BANKNIFTY one-minute index rows from 09:15 (placeholder volume), NSE5 the five-minute stock pool and NSED the daily
stock pool (real volume), NAS100 the Nasdaq 100 cash session (NQ prices, 09:30-16:00 New York), BTCUSD (the UTC day),
XAUUSD (gold; booked on Delta XAUTUSD), EURUSD / GBPUSD (the 17:00 New York day; placeholder volume, so their profiles
and VWAPs are time-weighted).

Every signal uses only the bars up to its own signal bar; expiries are counted from the signal row (never looked up
from a later bar), so the live day sees each setup when its bar closes."""

from __future__ import annotations

import numpy as np

import yc_ind as I
import yt_ind as YI
from yc_common import bars_of_day, ctx, sig
from yc_engine import XExits

import zd_common as Z
import ze_common as E
from ze_common import T, sorted_out
from ze_more2 import _last_done, _swing_levels

IXN = ("NIFTY", "BANKNIFTY")
TICK_NQ = 0.25


def _days(b, d):
    return list(bars_of_day(b, d))


def _fin(*xs) -> bool:
    return all(np.isfinite(x) for x in xs)


def _cached(cache, key, fn):
    if key not in cache:
        cache[key] = fn()
    return cache[key]


def _day_hlc(m, cache):
    return _cached(cache, ("ze3_dhlc",), lambda: I.day_hlc(m))


def _adr20(m, cache):
    """Mean daily range (high - low) of the 20 sessions before each day."""
    def calc():
        H, L, _ = _day_hlc(m, cache)
        rg = np.asarray(H - L, float)
        out = np.full(len(rg), np.nan)
        for d in range(20, len(rg)):
            out[d] = float(np.mean(rg[d - 20:d]))
        return out
    return _cached(cache, ("ze3_adr20",), calc)


def _atr5(m, cache):
    """Average true range of the 5 sessions before each day (daily bars from the session's rows)."""
    def calc():
        H, L, C = _day_hlc(m, cache)
        n = len(C)
        tr = np.full(n, np.nan)
        for d in range(1, n):
            tr[d] = max(H[d], C[d - 1]) - min(L[d], C[d - 1])
        out = np.full(n, np.nan)
        for d in range(6, n):
            out[d] = float(np.mean(tr[d - 5:d]))
        return out
    return _cached(cache, ("ze3_atr5",), calc)


def _open_clock(m, b, j) -> int:
    return int(b.ist0[j]) if m.name in IXN or m.name in ("NSE5", "NSE15") else int(b.ny0[j])


# ═══ BT-01 Scott Andrews: fade a cash-open gap smaller than 40% of the 5-day ATR to the prior close ═════════════════

def bt01(m, B, p, cache):
    b = B[1]
    a5 = _atr5(m, cache)
    first = T(9, 15) if m.name in IXN else 9 * 60 + 30
    out = []
    for d in range(6, m.n_days):
        js = _days(b, d)
        if not js or _open_clock(m, b, js[0]) != first:
            continue
        j0 = js[0]
        pc, atr = Z.prev_close(m, d), float(a5[d])
        if not (_fin(pc, atr) and atr > 0):
            continue
        gap = float(b.o[j0]) - pc
        if gap == 0 or abs(gap) >= 0.4 * atr:
            continue
        side = -1 if gap > 0 else 1
        if (side < 0 and b.l[j0] <= pc) or (side > 0 and b.h[j0] >= pc):
            continue                                   # the first minute already reached the prior close
        dist = 0.30 * atr
        c0 = float(b.c[j0])
        out.append(sig(b, j0, side, c0 - side * dist, "BT01_GAP_FADE_" + ("LONG" if side > 0 else "SHORT"),
                       target_px=pc, info={"stop_dist": dist}))
    return out


def bt01_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ QI-01 QuantInsti: daily close crossing above the upper Bollinger Band (20, 2), out below the middle band ═════════

def _bb20(B, cache):
    return _cached(cache, ("ze3_bb20",), lambda: YI.bollinger(np.asarray(B[1].c, float), 20, 2.0))


def qi01(m, B, p, cache):
    b = B[1]
    c = np.asarray(b.c, float)
    mid, up, lo = _bb20(B, cache)
    out = []
    for j in range(21, len(c)):
        if _fin(up[j], up[j - 1], lo[j]) and c[j] > up[j] and c[j - 1] < up[j - 1] and lo[j] < c[j]:
            out.append(sig(b, j, 1, float(lo[j]), "QI01_BB_BREAKOUT_LONG"))
    return out


def qi01_x(m, B, p, cache):
    b = B[1]
    c = np.asarray(b.c, float)
    mid = _bb20(B, cache)[0]
    with np.errstate(invalid="ignore"):
        x = c < mid
    return XExits(target_r=None, xbars=b, xlong=x, xshort=np.zeros(len(x), bool))


# ═══ MS-01 Art of Trading / JB Marwood: above the 200-day SMA, close below the 10-day SMA, out above the 10-day ══════

def ms01(m, B, p, cache):
    b = B[1]
    c = np.asarray(b.c, float)
    s200, s10 = I.sma(c, 200), I.sma(c, 10)
    out = []
    for j in range(200, len(c)):
        if _fin(s200[j], s10[j]) and c[j] > s200[j] and c[j] < s10[j]:
            out.append(sig(b, j, 1, float(c[j]) * 0.90, "MS01_SMA200_10_PULLBACK_LONG", info={"stop_frac": 0.10}))
    return out


def ms01_x(m, B, p, cache):
    b = B[1]
    c = np.asarray(b.c, float)
    s10 = I.sma(c, 10)
    with np.errstate(invalid="ignore"):
        x = c > s10
    return XExits(target_r=None, xbars=b, xlong=x, xshort=np.zeros(len(x), bool))


# ═══ AV-01 Algovibes: the first UTC hour's direction held to the end of the day (bitcoin) ═════════════════════════════

def av01(m, B, p, cache):
    b = B[60]
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or E.utc_min(b, js[0]) != 0:
            continue
        j0 = js[0]
        o, c = float(b.o[j0]), float(b.c[j0])
        if c == o:
            continue
        side = 1 if c > o else -1
        out.append(sig(b, j0, side, c * (1 - side * 0.05), "AV01_FIRST_HOUR_" + ("LONG" if side > 0 else "SHORT"),
                       info={"stop_frac": 0.05}))
    return out


def av01_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ PL-01 Part Time Larry: the first five minutes' colour at 09:35, stop at the range's far end, 10R ═════════════════

def pl01(m, B, p, cache):
    b = B[1]
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ny0[js[0]]) != 9 * 60 + 30:
            continue
        rng = js[:5]
        if len(rng) < 5 or int(b.ny0[rng[4]]) != 9 * 60 + 34:
            continue
        j = rng[4]
        o0, c4 = float(b.o[js[0]]), float(b.c[j])
        hi, lo = float(np.max(b.h[rng])), float(np.min(b.l[rng]))
        if c4 > o0:
            out.append(sig(b, j, 1, lo, "PL01_ORB5_GREEN_LONG"))
        elif c4 < o0:
            out.append(sig(b, j, -1, hi, "PL01_ORB5_RED_SHORT"))
    return out


def pl01_x(m, B, p, cache):
    return XExits(target_r=10.0)


# ═══ QI-02 QuantInsti: the overnight gap's side from the open to the close when beyond 0.25 SD (NSE stock pool) ═════

def _overnight(m, cache):
    def calc():
        n = m.n_days
        r = np.full(n, np.nan)
        for d in range(1, n):
            pc, o = float(m.c[m.d1[d - 1] - 1]), float(m.o[m.d0[d]])
            if pc > 0:
                r[d] = o / pc - 1
        sd = np.full(n, np.nan)
        for d in range(41, n):
            w = r[d - 40:d]
            w = w[np.isfinite(w)]
            if len(w) >= 30:
                sd[d] = float(w.std())
        return r, sd
    return _cached(cache, ("ze3_overnight",), calc)


def qi02(m, B, p, cache):
    b = B[5]
    r, sd = _overnight(m, cache)
    out = []
    for d in range(41, m.n_days):
        js = _days(b, d)
        if not js or int(b.ist0[js[0]]) != T(9, 15) or not (_fin(r[d], sd[d]) and sd[d] > 0):
            continue
        side = 1 if r[d] > 0.25 * sd[d] else (-1 if r[d] < -0.25 * sd[d] else 0)
        if not side:
            continue
        c0 = float(b.c[js[0]])
        out.append(sig(b, js[0], side, c0 * (1 - side * 0.03), "QI02_GAP_MOMENTUM_" + ("LONG" if side > 0 else "SHORT"),
                       info={"stop_frac": 0.03}))
    return out


def qi02_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ TM-01 TradeSmart: daily open gap up after a downtrend, buy at 15:15, held to the target or the stop (index) ═════

def tm01(m, B, p, cache):
    b = B[1]
    H, L, C = _day_hlc(m, cache)
    out = []
    for d in range(21, m.n_days):
        js = _days(b, d)
        if not js or int(b.ist0[js[0]]) != T(9, 15):
            continue
        at = [j for j in js if int(b.ist0[j]) == T(15, 14)]
        if not at:
            continue
        j, a = at[0], js[0]
        ph, pl = float(H[d - 1]), float(L[d - 1])
        lo_now, hi_now = float(np.min(b.l[a:j + 1])), float(np.max(b.h[a:j + 1]))
        if not lo_now > ph:
            continue                                   # not an open gap (today's low above yesterday's high)
        if not float(C[d - 1]) < float(np.mean(C[d - 20:d])):
            continue                                   # the previous trend is not down
        out.append(sig(b, j, 1, pl - 1.0, "TM01_OPEN_GAP_UP_LONG", target_px=hi_now + (ph - pl)))
    return out


def tm01_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ LT-01 LumiTraders Model 4: a two-minute close beyond 70.5% of the regular-hours gap, played for the full fill ═══

def lt01(m, B, p, cache):
    b = B[2]
    out = []
    for d in range(1, m.n_days):
        js = _days(b, d)
        if not js or int(b.ny0[js[0]]) != 9 * 60 + 30:
            continue
        pc, o0 = Z.prev_close(m, d), float(b.o[js[0]])
        if not np.isfinite(pc) or o0 == pc:
            continue
        gap = o0 - pc
        side = -1 if gap > 0 else 1                   # toward the prior close
        l705, l50 = o0 - 0.705 * gap, o0 - 0.5 * gap
        thr = 0.00035 * o0
        for j in js:
            if int(b.ny0[j]) + 2 > 12 * 60:
                break
            c = float(b.c[j])
            if (c - l705) * side >= thr:
                if (pc - c) * side > 0:
                    out.append(sig(b, j, side, l50, "LT01_GAP_705_FILL_" + ("LONG" if side > 0 else "SHORT"),
                                   target_px=pc))
                break
    return out


def lt01_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ FP-01 FessorPro: spot touches the daily pivot, R1 or S1; 60-point bracket (ATM option proxy), 1:1, one a day ═══

def fp01(m, B, p, cache):
    b = B[1]
    piv = E.day_pivots(m, cache)
    out = []
    for d in range(1, m.n_days):
        pv = piv.get(d)
        if not pv:
            continue
        levels = (float(pv["P"]), float(pv["R1"]), float(pv["S1"]))
        for j in _days(b, d):
            t = int(b.ist0[j])
            if t < T(9, 30):
                continue
            if t >= T(15, 14):
                break
            hit = [x for x in levels if b.l[j] - 5 <= x <= b.h[j] + 5]
            if not hit:
                continue
            x = min(hit, key=lambda v: abs(v - float(b.c[j])))
            exp = int(b.i1[j]) + (T(15, 14) - t)
            s = sig(b, j, 1, x, "FP01_PIVOT_TOUCH_LONG", entry_stop=x + 60.0, expire_k=exp, info={"stop_dist": 60.0})
            s.alt = sig(b, j, -1, x, "FP01_PIVOT_TOUCH_SHORT", entry_stop=x - 60.0, expire_k=exp,
                        info={"stop_dist": 60.0})
            out.append(s)
            break
    return out


def fp01_x(m, B, p, cache):
    return XExits(target_r=None, target_abs=60.0)


# ═══ CI-21 Trader Chitra: EMA 5 / 20 cross candle broken, stop at its other end, 2R or a close back through the 5 EMA ═

def _ix_window(b, j) -> bool:
    return T(9, 30) <= int(b.ist0[j]) + int(b.tf) <= T(14, 45)


def ci21(m, B, p, cache):
    b = B[5]
    cx = ctx(m, B, 5, cache)
    e5, e20 = cx.ema(5), cx.ema(20)
    out = []
    for j in range(25, len(b.c)):
        if not _ix_window(b, j) or not _fin(e5[j], e20[j], e5[j - 1], e20[j - 1]):
            continue
        if e5[j] > e20[j] and e5[j - 1] <= e20[j - 1] and b.c[j] > b.o[j]:
            out.append(sig(b, j, 1, float(b.l[j]), "CI21_EMA5_20_CROSS_LONG", entry_stop=float(b.h[j]) + 1.0,
                           expire_k=int(b.i1[j]) + 15))
        elif e5[j] < e20[j] and e5[j - 1] >= e20[j - 1] and b.c[j] < b.o[j]:
            out.append(sig(b, j, -1, float(b.h[j]), "CI21_EMA5_20_CROSS_SHORT", entry_stop=float(b.l[j]) - 1.0,
                           expire_k=int(b.i1[j]) + 15))
    return out


def ci21_x(m, B, p, cache):
    b = B[5]
    e5 = ctx(m, B, 5, cache).ema(5)
    with np.errstate(invalid="ignore"):
        return XExits(target_r=2.0, xbars=b, xlong=b.c < e5, xshort=b.c > e5)


# ═══ CI-22 Trader Chitra: 3-minute close back over (under) the 21 EMA on the right side of S3 / PDL (R3 / PDH) ═════════

def ci22(m, B, p, cache):
    b = B[3]
    e21 = ctx(m, B, 3, cache).ema(21)
    out = []
    for d in range(1, m.n_days):
        pd = E.prev_day_hlc(m, d)
        if not pd:
            continue
        H, L, C = pd
        r3, s3 = C + 1.1 * (H - L) / 4, C - 1.1 * (H - L) / 4
        for j in _days(b, d):
            if j < 3 or not _ix_window(b, j) or not _fin(e21[j]):
                continue
            c, o = float(b.c[j]), float(b.o[j])
            near = abs(c - e21[j]) <= 0.003 * c
            if c > o and c > e21[j] and near and c > s3 and c > L and any(b.c[i] <= e21[i] for i in range(j - 3, j)):
                ent = float(b.h[j]) + 1.0
                ahead = [x for x in (r3, H) if x > ent]
                out.append(sig(b, j, 1, float(b.l[j]), "CI22_EMA21_RECLAIM_LONG", entry_stop=ent,
                               expire_k=int(b.i1[j]) + 9, target_px=min(ahead) if ahead else None))
            elif c < o and c < e21[j] and near and c < r3 and c < H and any(b.c[i] >= e21[i] for i in range(j - 3, j)):
                ent = float(b.l[j]) - 1.0
                ahead = [x for x in (s3, L) if x < ent]
                out.append(sig(b, j, -1, float(b.h[j]), "CI22_EMA21_LOSS_SHORT", entry_stop=ent,
                               expire_k=int(b.i1[j]) + 9, target_px=max(ahead) if ahead else None))
    return out


def ci22_x(m, B, p, cache):
    b = B[3]
    e21 = ctx(m, B, 3, cache).ema(21)
    with np.errstate(invalid="ignore"):
        return XExits(target_r=2.0, xbars=b, xlong=(b.c < b.o) & (b.c < e21), xshort=(b.c > b.o) & (b.c > e21))


# ═══ SP-02 Stock Phoenix: Heikin Ashi flat-bottomed candle above the 20 SMA with RSI over 50, one-hour HA side ══════

def _sp02_arr(m, B, cache):
    def calc():
        ha = I.HABars(B[5])
        ha60 = I.HABars(B[60])
        return ha, I.sma(ha.c, 20), I.rsi(ha.c, 14), ha60, I.sma(ha60.c, 20)
    return _cached(cache, ("ze3_sp02",), calc)


def sp02(m, B, p, cache):
    b, b60 = B[5], B[60]
    ha, s20, r14, ha60, s60 = _sp02_arr(m, B, cache)
    out = []
    for j in range(25, len(b.c)):
        if not _ix_window(b, j) or not _fin(s20[j], r14[j], r14[j - 3]):
            continue
        k = _last_done(b60, b, j)
        if k < 0 or not np.isfinite(s60[k]):
            continue
        tol = 1e-9 * float(ha.c[j])
        up_x = any(r14[i - 1] <= 50 < r14[i] for i in range(j - 2, j + 1))
        dn_x = any(r14[i - 1] >= 50 > r14[i] for i in range(j - 2, j + 1))
        if (r14[j] > 50 and up_x and ha.c[j] > ha.o[j] and abs(ha.o[j] - ha.l[j]) <= tol and ha.l[j] > s20[j]
                and ha60.c[k] > s60[k]):
            out.append(sig(b, j, 1, float(ha.l[j]), "SP02_HA_FLAT_BOTTOM_LONG", entry_stop=float(ha.h[j]) + 1.0,
                           expire_k=int(b.i1[j]) + 15))
        elif (r14[j] < 50 and dn_x and ha.c[j] < ha.o[j] and abs(ha.o[j] - ha.h[j]) <= tol and ha.h[j] < s20[j]
                and ha60.c[k] < s60[k]):
            out.append(sig(b, j, -1, float(ha.h[j]), "SP02_HA_FLAT_TOP_SHORT", entry_stop=float(ha.l[j]) - 1.0,
                           expire_k=int(b.i1[j]) + 15))
    return out


def sp02_x(m, B, p, cache):
    b = B[5]
    ha, s20 = _sp02_arr(m, B, cache)[:2]
    with np.errstate(invalid="ignore"):
        return XExits(target_r=None, xbars=b, xlong=ha.c < s20, xshort=ha.c > s20)


# ═══ FS-01 RSI (14) beyond 70/30 within 3 bars, then a close back through the 9 EMA, swing stop, 1.5R ═══════════════

def _fs_tf(m) -> int:
    return 5 if m.name == "BTCUSD" else 30


def fs01(m, B, p, cache):
    tf = _fs_tf(m)
    b = B[tf]
    cx = ctx(m, B, tf, cache)
    e9, r14 = cx.ema(9), cx.rsi(14)
    h, l, c = b.h, b.l, b.c
    out = []
    for j in range(20, len(c)):
        if not _fin(e9[j], e9[j - 1], r14[j], r14[j - 2]) or b.day[j] != b.day[j - 1]:
            continue
        hot = max(r14[j - 2:j + 1]) >= 70
        cold = min(r14[j - 2:j + 1]) <= 30
        if hot and c[j] < e9[j] and c[j - 1] >= e9[j - 1]:
            out.append(sig(b, j, -1, float(np.max(h[j - 4:j + 1])) * 1.0002, "FS01_RSI70_EMA9_SHORT"))
        elif cold and c[j] > e9[j] and c[j - 1] <= e9[j - 1]:
            out.append(sig(b, j, 1, float(np.min(l[j - 4:j + 1])) * 0.9998, "FS01_RSI30_EMA9_LONG"))
    return out


def fs01_x(m, B, p, cache):
    return XExits(target_r=1.5)


# ═══ TT-01 three tests of a support above the 50 EMA, green close above the EMA, 1.6R (forex, 15 minutes) ════════════

def tt01(m, B, p, cache):
    b = B[15]
    e50 = ctx(m, B, 15, cache).ema(50)
    ph, pl = YI.fractals(b, 2)
    h, l, c, o = b.h, b.l, b.c, b.o
    out = []
    lows, highs = [], []
    arm_l = arm_h = None
    for j in range(55, len(c)):
        q = j - 2
        if pl[q] and np.isfinite(e50[q]):
            lows.append((float(l[q]), bool(l[q] > e50[q])))
            last = lows[-3:]
            if len(last) == 3 and all(a for _, a in last):
                v = [x for x, _ in last]
                if max(v) - min(v) <= 0.0005 * min(v):
                    arm_l = (j + 3, min(v))
        if ph[q] and np.isfinite(e50[q]):
            highs.append((float(h[q]), bool(h[q] < e50[q])))
            last = highs[-3:]
            if len(last) == 3 and all(a for _, a in last):
                v = [x for x, _ in last]
                if max(v) - min(v) <= 0.0005 * min(v):
                    arm_h = (j + 3, max(v))
        if arm_l and j > arm_l[0]:
            arm_l = None
        if arm_h and j > arm_h[0]:
            arm_h = None
        t = int(b.ny0[j])
        quiet = 16 * 60 <= t < 18 * 60
        if not np.isfinite(e50[j]) or quiet:
            continue
        if arm_l and c[j] > o[j] and c[j] > e50[j]:
            out.append(sig(b, j, 1, arm_l[1] * 0.9998, "TT01_TRIPLE_TEST_LONG"))
            arm_l = None
        elif arm_h and c[j] < o[j] and c[j] < e50[j]:
            out.append(sig(b, j, -1, arm_h[1] * 1.0002, "TT01_TRIPLE_TEST_SHORT"))
            arm_h = None
    return out


def tt01_x(m, B, p, cache):
    return XExits(target_r=1.6)


# ═══ ET-01 John Kurisko: quad rotation + 9-3 divergence 'super signal' (Nasdaq 100, one minute) ══════════════════════

def _quad(m, B, cache):
    return _cached(cache, ("ze3_quad",), lambda: [I.stochastic(B[1], n, s, 3)[0]
                                                    for n, s in ((9, 3), (14, 3), (40, 4), (60, 10))])


def et01(m, B, p, cache):
    b = B[1]
    k9, k14, k40, k60 = _quad(m, B, cache)
    h, l = b.h, b.l
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ny0[js[0]]) != 9 * 60 + 30:
            continue
        for side in (1, -1):
            st = None
            for j in js:
                if not _fin(k9[j], k14[j], k40[j], k60[j]):
                    continue
                kk = k9[j] if side > 0 else 100 - k9[j]
                ext = float(l[j]) if side > 0 else float(h[j])
                quad = all(((x[j] < 20) if side > 0 else (x[j] > 80)) for x in (k9, k14, k40, k60))
                if st is None:
                    if quad:
                        st = {"q": j, "s": 1, "p1": ext, "m1": kk, "pl": None, "m3": None, "dip": False}
                    continue
                if j - st["q"] > 60:
                    st = None
                    if quad:
                        st = {"q": j, "s": 1, "p1": ext, "m1": kk, "pl": None, "m3": None, "dip": False}
                    continue
                worse = (ext <= st["p1"]) if side > 0 else (ext >= st["p1"])
                if st["s"] == 1:
                    st["p1"] = min(st["p1"], ext) if side > 0 else max(st["p1"], ext)
                    st["m1"] = min(st["m1"], kk)
                    if kk >= st["m1"] + 5:
                        st["s"] = 2
                    continue
                if st["s"] == 2:
                    if worse:
                        st["s"], st["pl"], st["m3"] = 3, ext, kk
                        st["dip"] = kk <= 20
                    continue
                st["pl"] = min(st["pl"], ext) if side > 0 else max(st["pl"], ext)
                kp = k9[j - 1] if side > 0 else 100 - k9[j - 1]
                if kk <= 20:
                    st["dip"] = True
                    st["m3"] = min(st["m3"], kk)
                    continue
                if kp <= 20 < kk:
                    t = int(b.ny0[j])
                    if st["dip"] and st["m3"] > st["m1"] and 9 * 60 + 35 <= t < 15 * 60 + 30:
                        stop = st["pl"] - side * 2 * TICK_NQ
                        out.append(sig(b, j, side, stop, "ET01_QUAD_SUPER_" + ("LONG" if side > 0 else "SHORT")))
                    st = None
    return sorted_out(out)


def et01_x(m, B, p, cache):
    b = B[1]
    k9, _, _, k60 = _quad(m, B, cache)
    kp = np.r_[np.nan, k9[:-1]]
    with np.errstate(invalid="ignore"):
        xl = (kp >= 80) & (k9 < 80) & (k60 < 30)
        xs = (kp <= 20) & (k9 > 20) & (k60 > 70)
    return XExits(target_r=2.0, xbars=b, xlong=xl, xshort=xs)


# ═══ ET-02 John Kurisko: 20-20 flag (60-10 embedded above 80, 9-3 back to 20 on the 20 EMA) and the bear flag ═════════

def et02(m, B, p, cache):
    b = B[1]
    k9, _, _, k60 = _quad(m, B, cache)
    cx = ctx(m, B, 1, cache)
    e20, e200 = cx.ema(20), cx.ema(200)
    h, l, c = b.h, b.l, b.c
    out = []
    for j in range(210, len(c)):
        t = int(b.ny0[j])
        if not (9 * 60 + 35 <= t < 15 * 60 + 30) or b.day[j] != b.day[j - 10]:
            continue
        if not _fin(k9[j], k9[j - 1], k60[j], e20[j], e200[j]):
            continue
        if k60[j] > 80 and k9[j - 1] > 20 >= k9[j] and c[j] > e20[j]:
            out.append(sig(b, j, 1, float(np.min(l[j - 9:j + 1])) - TICK_NQ, "ET02_2020_BULL_FLAG_LONG"))
        elif k60[j] < 20 and k9[j - 1] < 80 <= k9[j] and c[j] < e200[j]:
            out.append(sig(b, j, -1, float(np.max(h[j - 9:j + 1])) + TICK_NQ, "ET02_BEAR_FLAG_SHORT"))
    return out


def et02_x(m, B, p, cache):
    return XExits(target_r=1.0)


# ═══ MB-01 MACD (3, 9, 5): consolidation at zero, expansion, re-cross on the trend side (Nasdaq 100, one minute) ══════

def _mb01_arr(m, B, cache):
    def calc():
        b = B[1]
        line, sgl, _ = I.macd(np.asarray(b.c, float), 3, 9, 5)
        return line, sgl, ctx(m, B, 1, cache).atr(14)
    return _cached(cache, ("ze3_mb01",), calc)


def mb01(m, B, p, cache):
    b = B[1]
    line, sgl, a = _mb01_arr(m, B, cache)
    h, l = b.h, b.l
    out = []
    for j in range(30, len(b.c)):
        t = int(b.ny0[j])
        if not (9 * 60 + 45 <= t < 15 * 60 + 30) or b.day[j] != b.day[j - 16]:
            continue
        if not _fin(line[j], line[j - 1], sgl[j], sgl[j - 1], a[j]):
            continue
        up = line[j] > sgl[j] and line[j - 1] <= sgl[j - 1] and line[j] > 0
        dn = line[j] < sgl[j] and line[j - 1] >= sgl[j - 1] and line[j] < 0
        if not (up or dn):
            continue
        quiet = [i for i in range(j - 15, j - 3) if _fin(line[i], a[i]) and abs(line[i]) <= 0.1 * a[i]]
        if len(quiet) < 3:
            continue
        seg = range(quiet[-1] + 1, j)
        if not len(seg):
            continue
        if up:
            pk = max(seg, key=lambda i: line[i])
            if line[pk] >= 0.3 * a[pk]:
                out.append(sig(b, j, 1, float(np.min(l[pk:j + 1])) - TICK_NQ, "MB01_MACD_RECROSS_LONG"))
        else:
            pk = min(seg, key=lambda i: line[i])
            if line[pk] <= -0.3 * a[pk]:
                out.append(sig(b, j, -1, float(np.max(h[pk:j + 1])) + TICK_NQ, "MB01_MACD_RECROSS_SHORT"))
    return out


def mb01_x(m, B, p, cache):
    b = B[1]
    line, sgl, _ = _mb01_arr(m, B, cache)
    lp, sp = np.r_[np.nan, line[:-1]], np.r_[np.nan, sgl[:-1]]
    with np.errstate(invalid="ignore"):
        xl = (line < sgl) & (lp >= sp)
        xs = (line > sgl) & (lp <= sp)
    return XExits(target_r=None, xbars=b, xlong=xl, xshort=xs)


# ═══ TD-11 Trader Dale: first pullback to the previous session's point of control, 1:1 at 15% of the daily range ═══

def _poc(m, d, step, weighted):
    a, z = int(m.d0[d]), int(m.d1[d])
    if z - a < 100 or not step > 0:
        return None
    lo = np.floor(m.l[a:z] / step).astype(np.int64)
    hi = np.floor(m.h[a:z] / step).astype(np.int64)
    base = int(lo.min())
    cnt = np.zeros(int(hi.max()) - base + 1)
    w = np.asarray(m.vol[a:z], float) if weighted else np.ones(z - a)
    for x, y, v in zip(lo - base, hi - base, w):
        cnt[x:y + 1] += v / (y - x + 1) if weighted else 1.0
    if not cnt.max() > 0:
        return None
    ties = np.flatnonzero(cnt == cnt.max())
    k = int(ties[np.argmin(np.abs(ties - (len(cnt) - 1) / 2))])
    return (base + k + 0.5) * step


def td11(m, B, p, cache):
    b = B[1]
    adr = _adr20(m, cache)
    weighted = m.name == "BTCUSD"
    out = []
    for d in range(21, m.n_days):
        if not np.isfinite(adr[d]):
            continue
        last = float(m.c[m.d1[d - 1] - 1])
        poc = _poc(m, d - 1, 0.0001 * last, weighted)
        if poc is None:
            continue
        dist = 0.15 * float(adr[d])
        for j in _days(b, d):
            c = float(b.c[j])
            if abs(c - poc) >= 0.5 * dist:
                side = 1 if c > poc else -1
                out.append(sig(b, j, side, poc - side * dist, "TD11_POC_FIRST_TEST_" + ("LONG" if side > 0 else "SHORT"),
                               entry_limit=poc, expire_k=int(m.d1[d]) - 1, info={"stop_dist": dist}))
                break
    return out


def td11_x(m, B, p, cache):
    return XExits(target_r=1.0)


# ═══ TD-12 Trader Dale: week-anchored VWAP, the first pullback to it after price moved away, 1:1 at 15% ═════════════

def _week_vwap(m, B, cache):
    def calc():
        b = B[30]
        wk_day = (m.date.astype("datetime64[D]").astype(np.int64) + 3) // 7
        wk = wk_day[m.day]
        tp = (m.h + m.l + m.c) / 3.0
        v = np.asarray(m.vol, float)
        if not np.any(v > 0):
            v = np.ones(len(tp))
        out = np.full(len(tp), np.nan)
        starts = np.flatnonzero(np.r_[True, wk[1:] != wk[:-1]])
        for a, z in zip(starts, np.r_[starts[1:], len(wk)]):
            cv = np.cumsum(v[a:z])
            cp = np.cumsum(tp[a:z] * v[a:z])
            with np.errstate(invalid="ignore", divide="ignore"):
                out[a:z] = np.where(cv > 0, cp / cv, np.nan)
        return out[b.i1]
    return _cached(cache, ("ze3_wvwap",), calc)


def td12(m, B, p, cache):
    b = B[30]
    vw = _week_vwap(m, B, cache)
    adr = _adr20(m, cache)
    c = np.asarray(b.c, float)
    with np.errstate(invalid="ignore"):
        sd = np.sign(c - vw)
    out = []
    for j in range(37, len(c)):
        d = int(b.day[j])
        if not _fin(vw[j], adr[d]):
            continue
        run = sd[j - 11:j + 1]
        side = 1 if np.all(run > 0) else (-1 if np.all(run < 0) else 0)
        if not side or sd[j - 12] == side:
            continue                                   # not the bar that completes the 12-close run
        prior = sd[j - 35:j - 11]
        flips = int(np.sum((prior[1:] != prior[:-1]) & (prior[1:] != 0) & (prior[:-1] != 0)))
        if flips >= 3:
            continue
        dist = 0.15 * float(adr[d])
        lvl = float(vw[j])
        out.append(sig(b, j, side, lvl - side * dist, "TD12_WEEK_VWAP_PULLBACK_" + ("LONG" if side > 0 else "SHORT"),
                       entry_limit=lvl, expire_k=int(b.i1[j]) + 12 * 30, info={"stop_dist": dist}))
    return out


def td12_x(m, B, p, cache):
    return XExits(target_r=1.0)


# ═══ DX-01 Doyle Exchange: limit at 70% of a structure-breaking impulse, stop at 100%, half at 38.2%, rest at 10% ═════

def dx01(m, B, p, cache):
    b = B[5]
    h, l, c = b.h, b.l, b.c
    lo_sw, hi_sw = _swing_levels(b, 2)
    n = len(c)
    out = []
    for side in (1, -1):
        j = 21
        while j < n:
            lvl = hi_sw[j] if side > 0 else lo_sw[j]
            if not (np.isfinite(lvl) and (c[j] - lvl) * side > 0 and (c[j - 1] - lvl) * side <= 0):
                j += 1
                continue
            origin = float(np.min(l[j - 20:j + 1])) if side > 0 else float(np.max(h[j - 20:j + 1]))
            ext = float(h[j]) if side > 0 else float(l[j])
            k = j + 1
            while k < n and k <= j + 30 and ((h[k] > ext) if side > 0 else (l[k] < ext)):
                ext = float(h[k]) if side > 0 else float(l[k])
                k += 1
            if k >= n:
                break
            if k > j + 30 or b.day[k] != b.day[j]:
                j = k
                continue
            span = (ext - origin) * side
            if span > 0:
                entry = ext - side * 0.70 * span
                half = ext - side * 0.382 * span
                tgt = ext - side * 0.10 * span
                out.append(sig(b, k, side, origin, "DX01_FIB70_" + ("LONG" if side > 0 else "SHORT"), entry_limit=entry,
                               expire_k=int(b.i1[k]) + 24 * 5, target_px=tgt, info={"partial_px": half}))
            j = k + 1
    return sorted_out(out)


def dx01_x(m, B, p, cache):
    return XExits(target_r=None, partial_px=True)


# ═══ BR-01 Al Brooks: two consecutive strong trend bars, stop entry a tick beyond the second, scalp half a bar ═══════

def br01(m, B, p, cache):
    b = B[2]
    ravg = ctx(m, B, 2, cache).range_avg(20)
    o, h, l, c = b.o, b.h, b.l, b.c
    rg = h - l

    def strong(i, side):
        r = float(rg[i])
        if not (r > 0 and np.isfinite(ravg[i]) and r >= ravg[i]):
            return False
        body = (c[i] - o[i]) * side
        tail = (h[i] - c[i]) if side > 0 else (c[i] - l[i])
        return body >= 0.5 * r and tail <= 0.25 * r

    out = []
    for j in range(25, len(c)):
        t = int(b.ny0[j])
        if not (9 * 60 + 34 <= t <= 15 * 60 + 28) or b.day[j] != b.day[j - 1]:
            continue
        a10 = float(np.mean(rg[j - 9:j + 1]))
        for side in (1, -1):
            if strong(j - 1, side) and strong(j, side):
                ent = float(h[j]) + TICK_NQ if side > 0 else float(l[j]) - TICK_NQ
                stop = float(l[j]) - TICK_NQ if side > 0 else float(h[j]) + TICK_NQ
                out.append(sig(b, j, side, stop, "BR01_ALWAYS_IN_" + ("LONG" if side > 0 else "SHORT"), entry_stop=ent,
                               expire_k=int(b.i1[j]) + 2, target_px=ent + side * 0.5 * a10))
    return sorted_out(out)


def br01_x(m, B, p, cache):
    return XExits(target_r=None)
