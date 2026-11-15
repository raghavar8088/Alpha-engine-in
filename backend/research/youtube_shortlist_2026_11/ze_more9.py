"""Tenth batch of the channel-shortlist study (15 Nov 2026): the owner's list E of NIFTY option-buying channels
(cards/<video>.txt; the 'A' rules are this code). Two kinds of book:

- index books (NIFTY, BANKNIFTY: the desk's one-minute index data from Angel One through the app's backend) for rules
  read from the index chart; the video's option is then a labelled proxy and the result is in index points;
- option books (NIFTY_OPT: the real recorded NIFTY option chain, see ze_opt) for rules read from the option premium. Each
  strategy picks its contract-days through a context built from the day's chain (CONTEXT), using only the snapshots up
  to each decision; its orders fill at the recorded ask and exit at the recorded bid.

Every signal uses only the bars or snapshots up to its own signal minute; order expiries count rows from the signal
row, never bars that have not happened yet."""

from __future__ import annotations

import numpy as np

import yc_ind as I
import ze_opt as O
from yc_common import ctx, sig
from yc_engine import XExits
from ze_more4 import TICK, _cached, _fin

T1500 = 15 * 60
RK01_VIX_MAX = 14.0          # Saketh's VIX filter (a module constant so a check can switch it off to test the mechanics)


def _prev_day_levels(m, cache):
    """Per trading day: the previous session's classic pivot P and R1 (NaN when there is no previous session)."""
    def calc():
        H, L, C = I.day_hlc(m)
        P = (H + L + C) / 3.0
        R1 = 2 * P - L
        pp, rr = np.r_[np.nan, P[:-1]], np.r_[np.nan, R1[:-1]]
        ok = np.asarray(m.prev_ok, bool)
        return np.where(ok, pp, np.nan), np.where(ok, rr, np.nan)
    return _cached(cache, ("ze9_pivots",), calc)


# ═══ TZ-01 SMA 22 / 33 scalp (Siddharth Bhanushali, tested by Trader Insights): both averages rising (falling), a green
#     (red) candle touching the band, a stop order beyond it, stop at its other end, 2R (NIFTY, 3 minutes) ══════════════

def tz01(m, B, p, cache):
    b = B[3]
    cx = ctx(m, B, 3, cache)
    s22, s33 = cx.sma(22), cx.sma(33)
    o, h, l, c = b.o, b.h, b.l, b.c
    out = []
    for j in range(34, len(c)):
        if not _fin(s22[j], s33[j], s22[j - 1], s33[j - 1]) or int(b.ist0[j]) >= T1500:
            continue
        top, bot = max(s22[j], s33[j]), min(s22[j], s33[j])
        if not (l[j] <= top and h[j] >= bot):
            continue
        exp = int(b.i1[j]) + 9                                   # the order lives for three more 3-minute candles
        if s22[j] > s22[j - 1] and s33[j] > s33[j - 1] and c[j] > o[j]:
            out.append(sig(b, j, 1, float(l[j]) * (1 - TICK), "TZ01_SMA22_33_LONG", entry_stop=float(h[j]) * (1 + TICK),
                           expire_k=exp))
        elif s22[j] < s22[j - 1] and s33[j] < s33[j - 1] and c[j] < o[j]:
            out.append(sig(b, j, -1, float(h[j]) * (1 + TICK), "TZ01_SMA22_33_SHORT", entry_stop=float(l[j]) * (1 - TICK),
                           expire_k=exp))
    return out


def tz01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ TZ-02 Pivot point + 20 MA (Abhishek Kar, tested by Trader Insights): above the day's pivot a green candle crossing
#     the 20 MA, or above the MA a candle crossing the pivot; enter at its close, stop under the candle or the MA, 2R
#     (NIFTY, 15 minutes) ═══════════════════════════════════════════════════════════════════════════════════════════

def tz02(m, B, p, cache):
    b = B[15]
    ma = ctx(m, B, 15, cache).sma(20)
    P, _ = _prev_day_levels(m, cache)
    o, h, l, c = b.o, b.h, b.l, b.c
    out = []
    for j in range(20, len(c)):
        pv = P[int(b.day[j])]
        if not _fin(ma[j], pv) or int(b.ist0[j]) >= T1500:
            continue
        long1 = c[j] > pv and c[j] > o[j] and o[j] <= ma[j] < c[j]
        long2 = c[j] > ma[j] and o[j] <= pv < c[j]
        short1 = c[j] < pv and c[j] < o[j] and o[j] >= ma[j] > c[j]
        short2 = c[j] < ma[j] and o[j] >= pv > c[j]
        if long1 or long2:
            out.append(sig(b, j, 1, float(min(l[j], ma[j])) * (1 - TICK), "TZ02_PIVOT_MA20_LONG"))
        elif short1 or short2:
            out.append(sig(b, j, -1, float(max(h[j], ma[j])) * (1 + TICK), "TZ02_PIVOT_MA20_SHORT"))
    return out


def tz02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ TE-01 Ghanshyam Tech's 9:20 strategy as built on Tradetron: a gap of more than 100 points is faded through the
#     first 5-minute candle's range, 200-point target, 70 / 100-point stop by the candle's size, out on an opposite
#     candle that closes 50 points off its extreme (BANKNIFTY) ═════════════════════════════════════════════════════

def te01(m, B, p, cache):
    b = B[5]
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        j0 = int(b.b0[d])
        if j0 >= int(b.b1[d]) or int(b.ist0[j0]) != 9 * 60 + 15:
            continue
        prev_close = float(m.c[int(m.d1[d - 1]) - 1])
        gap = float(m.o[int(m.d0[d])]) - prev_close
        if abs(gap) <= 100:
            continue
        side = -1 if gap > 0 else 1                              # a gap up is sold, a gap down bought
        hi, lo = float(b.h[j0]), float(b.l[j0])
        stop_pts = 100.0 if hi - lo > 150 else 70.0
        trig = hi + 0.05 if side > 0 else lo - 0.05
        out.append(sig(b, j0, side, trig - side * stop_pts, "TE01_920_GAP_FADE_" + ("LONG" if side > 0 else "SHORT"),
                       entry_stop=trig, expire_k=int(m.d1[d]) - 1, info={"stop_dist": stop_pts}))
    return out


def te01_x(m, B, p, cache):
    b = B[5]
    o, h, l, c = (np.asarray(x, float) for x in (b.o, b.h, b.l, b.c))
    return XExits(target_r=None, target_abs=200.0, xbars=b, xlong=(c < o) & (h - c >= 50), xshort=(c > o) & (c - l >= 50))


# ═══ UX-01 Upstox AlgoVerse option-buying build: a 3-minute close above the Supertrend, the upper Bollinger Band and the
#     day's R1 with RSI above 72 and a green candle; out on a close back below the Supertrend (NIFTY, long only) ═══════

def ux01(m, B, p, cache):
    b = B[3]
    cx = ctx(m, B, 3, cache)
    st, _ = cx.supertrend(10, 3.0)
    r14 = cx.rsi(14)
    _, up, _ = cx.bollinger(20, 2.0)
    _, R1 = _prev_day_levels(m, cache)
    o, c = b.o, b.c
    out = []
    for j in range(20, len(c)):
        r1 = R1[int(b.day[j])]
        if not _fin(st[j], r14[j], up[j], r1) or int(b.ist0[j]) >= T1500:
            continue
        if c[j] > st[j] and r14[j] > 72 and c[j] > up[j] and c[j] > o[j] and c[j] > r1:
            px = float(c[j])
            out.append(sig(b, j, 1, px * 0.99, "UX01_ALGOVERSE_LONG",
                           info={"stop_frac": 0.01, "risk_unit": max(px - float(st[j]), px * 0.001)}))
    return out


def ux01_x(m, B, p, cache):
    b = B[3]
    st, _ = ctx(m, B, 3, cache).supertrend(10, 3.0)
    c = np.asarray(b.c, float)
    with np.errstate(invalid="ignore"):
        x = c < st
    return XExits(target_r=None, xbars=b, xlong=x, xshort=np.zeros(len(x), bool))


def _day_ohlc(m):
    """Per trading day: open, high, low, close of the session (from the minute rows)."""
    H, L, C = I.day_hlc(m)
    O_ = np.array([float(m.o[int(m.d0[d])]) for d in range(m.n_days)])
    return O_, H, L, C


# ═══ SJ-01 Trading with Sidhant: two daily closes the same way (each below - or above - the day before's, both candles
#     that colour) set the day's side; the 9:15-9:45 range of 5-minute candles; after a close through its edge on that
#     side, the first retest of the edge, then each candle of that colour arms a stop order at its far end for one
#     candle; stop beyond the retest candle; out when two candles of the other colour break the second one's extreme
#     (NIFTY, 5 minutes; the video buys the ATM option) ═══════════════════════════════════════════════════════════════

def sj01(m, B, p, cache):
    b = B[5]
    O_, _, _, C = _day_ohlc(m)
    o, h, l, c = b.o, b.h, b.l, b.c
    out = []
    for d in range(3, m.n_days):
        if not (m.prev_ok[d] and m.prev_ok[d - 1] and m.prev_ok[d - 2]):
            continue
        down = C[d - 1] < C[d - 2] < C[d - 3] and C[d - 1] < O_[d - 1] and C[d - 2] < O_[d - 2]
        up = C[d - 1] > C[d - 2] > C[d - 3] and C[d - 1] > O_[d - 1] and C[d - 2] > O_[d - 2]
        if not (down or up):
            continue
        side = 1 if up else -1
        j0, j1 = int(b.b0[d]), int(b.b1[d])
        rng = [j for j in range(j0, j1) if 9 * 60 + 15 <= int(b.ist0[j]) <= 9 * 60 + 40]
        if len(rng) != 6 or int(b.ist0[rng[0]]) != 9 * 60 + 15:
            continue                                             # the range needs all six candles
        hi, lo = float(max(h[j] for j in rng)), float(min(l[j] for j in rng))
        broke = retest = None
        for j in range(rng[-1] + 1, j1):
            if int(b.ist0[j]) >= T1500:
                break
            if broke is None:
                if (c[j] > hi) if side < 0 else (c[j] < lo):     # through the other edge first: no trade today
                    break
                if (c[j] < lo) if side < 0 else (c[j] > hi):
                    broke = j
                continue
            if retest is None:
                if (h[j] >= lo) if side < 0 else (l[j] <= hi):
                    retest = j
                continue
            if (c[j] < o[j]) if side < 0 else (c[j] > o[j]):     # a candle of the day's colour after the retest
                stop = float(h[retest]) * (1 + TICK) if side < 0 else float(l[retest]) * (1 - TICK)
                trig = float(l[j]) * (1 - TICK) if side < 0 else float(h[j]) * (1 + TICK)
                exp = int(b.i1[j + 1]) if j + 1 < j1 else int(b.i1[j])
                out.append(sig(b, j, side, stop, "SJ01_TWO_DAY_RANGE_RETEST_" + ("LONG" if side > 0 else "SHORT"),
                               entry_stop=trig, expire_k=exp))
    return out


def sj01_x(m, B, p, cache):
    b = B[5]
    o, h, l, c = (np.asarray(x, float) for x in (b.o, b.h, b.l, b.c))
    green, red = c > o, c < o
    two_red = red & np.r_[False, red[:-1]]
    two_green = green & np.r_[False, green[:-1]]
    long_lv = np.where(two_red, l * (1 - TICK), np.nan)          # a long's stop moves to the second red candle's low
    short_lv = np.where(two_green, h * (1 + TICK), np.nan)
    return XExits(target_r=None, trail=("level", b, long_lv, short_lv))


# ═══ GT-01 Art of Option Learning's 44FR: after NIFTY falls at least 80 points (half a percent at today's level) from
#     the day's high, a Fibonacci from that high to the low since; buy when price climbs through 0.44, stop at 0.22, half
#     out at 0.77, the rest at 1.0 (NIFTY, 5 minutes, calls only) ═══════════════════════════════════════════════════

def gt01(m, B, p, cache):
    b = B[5]
    h, l, c = b.h, b.l, b.c
    out = []
    for d in range(m.n_days):
        j0, j1 = int(b.b0[d]), int(b.b1[d])
        hi, lo = -np.inf, np.inf
        for j in range(j0, j1):
            if h[j] > hi:
                hi, lo = float(h[j]), np.inf                     # a new day's high: the fall is measured afresh
            else:
                lo = min(lo, float(l[j]))
            if int(b.ist0[j]) >= T1500:
                break
            if not np.isfinite(lo):
                continue
            fall = hi - lo
            if fall < max(80.0, 0.005 * hi):
                continue
            e44 = lo + 0.44 * fall
            if c[j] >= e44:
                continue                                         # the order waits below the level
            exp = int(b.i1[j + 1]) if j + 1 < j1 else int(b.i1[j])
            out.append(sig(b, j, 1, lo + 0.22 * fall, "GT01_44FR_LONG", entry_stop=e44, expire_k=exp, target_px=hi,
                           info={"partial_px": lo + 0.77 * fall}))
    return out


def gt01_x(m, B, p, cache):
    return XExits(target_r=None, partial_px=True, partial_be=False)


# ═══ AX-07 AbhishekXTrades' zero-to-hero framework: the previous day's high and low set the side (above the high buy
#     only, below the low sell only, between them no trade); one or two candles against the side, then a close beyond
#     the last one's open enters (a third such candle cancels); stop at the pullback's extreme, half out at 1R, the rest
#     at 2R or the stop (NIFTY, 15 minutes) ════════════════════════════════════════════════════════════════════════

def ax07(m, B, p, cache):
    b = B[15]
    _, H, L, _ = _day_ohlc(m)
    o, h, l, c = b.o, b.h, b.l, b.c
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        pdh, pdl = float(H[d - 1]), float(L[d - 1])
        j0, j1 = int(b.b0[d]), int(b.b1[d])
        run = {1: 0, -1: 0}                                       # consecutive candles against a buy (red) / a sell (green)
        ref = {1: None, -1: None}                                 # (last pullback candle's open, the pullback's extreme)
        for j in range(j0, j1):
            if int(b.ist0[j]) >= T1500:
                break
            for side in (1, -1):
                against = (c[j] < o[j]) if side > 0 else (c[j] > o[j])
                if against:
                    run[side] += 1
                    ext = float(l[j]) if side > 0 else float(h[j])
                    if ref[side] is None or run[side] == 1:
                        ref[side] = (float(o[j]), ext)
                    else:
                        ref[side] = (float(o[j]), min(ref[side][1], ext) if side > 0 else max(ref[side][1], ext))
                    continue
                n, rf = run[side], ref[side]
                run[side], ref[side] = 0, None
                if not (1 <= n <= 2) or rf is None:
                    continue
                trigger = (c[j] > rf[0] and c[j] > pdh) if side > 0 else (c[j] < rf[0] and c[j] < pdl)
                if trigger:
                    stop = rf[1] * (1 - TICK) if side > 0 else rf[1] * (1 + TICK)
                    out.append(sig(b, j, side, stop, "AX07_PDHL_PULLBACK_" + ("LONG" if side > 0 else "SHORT")))
    return out


def ax07_x(m, B, p, cache):
    return XExits(target_r=2.0, partial_at_r=1.0, partial_be=False)


# ═══ the option books: each strategy's contracts per day (CONTEXT) ═════════════════════════════════════════════════

def _first_cross_above(day, key, level: float, i_from: int, i_to: int):
    """First snapshot index in [i_from, i_to) where the mid is above `level` for two minutes in a row after being at or
    below it (the break and the 'sustain'); the index of the second minute, or None."""
    below_seen = False
    prev_above = False
    for i in range(max(i_from, 1), i_to):
        mid = O.mid_of(day, key, i)
        if not np.isfinite(mid):
            continue
        if mid <= level:
            below_seen, prev_above = True, False
            continue
        if below_seen and prev_above:
            return i
        prev_above = below_seen
    return None


def _spot_bars(day, minutes: int):
    """Bars of NIFTY spot from the recorded snapshots (open, high, low, close of each `minutes` bucket from 09:15),
    and for each bar the index of its last snapshot."""
    mins = ((day.t + 19800) // 60) % 1440
    slot = (mins - (9 * 60 + 15)) // minutes
    o, h, l, c, last = [], [], [], [], []
    for s in np.unique(slot):
        idx = np.flatnonzero(slot == s)
        sp = day.spot[idx]
        ok = np.isfinite(sp)
        if not ok.any():
            continue
        sp = sp[ok]
        o.append(sp[0]); h.append(sp.max()); l.append(sp.min()); c.append(sp[-1]); last.append(int(idx[ok][-1]))
    return np.array(o), np.array(h), np.array(l), np.array(c), np.array(last, np.int64)


def _adx_arrays(h, l, c, n=14):
    class _B:                                                    # the shape yc_ind.adx expects
        pass
    bb = _B()
    bb.h, bb.l, bb.c = h, l, c
    bb.o = np.r_[c[:1], c[:-1]]
    return I.adx(bb, n)


def _dh12_pick(day):
    """Dhan's 3 PM momentum: on 2-minute NIFTY spot bars, the first MACD (12, 26, 9) histogram flip from 14:45 with ADX
    (14) above 25 and rising; the entry is the first later snapshot beyond the flip candle's extreme within three bars;
    the contract is 150 points in the money (rounded to 100) of the current expiry. Returns (key, entry index) or None."""
    o, h, l, c, last = _spot_bars(day, 2)
    if len(c) < 60:
        return None
    line = I.ema(c, 12) - I.ema(c, 26)
    hist = line - I.ema(line, 9)
    adx, _, _ = _adx_arrays(h, l, c, 14)
    mins = ((day.t[last] + 19800) // 60) % 1440
    for j in range(36, len(c)):
        if mins[j] < 14 * 60 + 45 or mins[j] > 15 * 60 + 16:
            continue
        if not (np.isfinite(adx[j]) and np.isfinite(adx[j - 1]) and adx[j] > 25 and adx[j] > adx[j - 1]):
            continue
        if hist[j] > 0 >= hist[j - 1]:
            side = 1
        elif hist[j] < 0 <= hist[j - 1]:
            side = -1
        else:
            continue
        lvl = h[j] if side > 0 else l[j]
        stop_at = int(last[min(j + 3, len(c) - 1)]) if j + 3 < len(c) else len(day.t) - 1
        for i in range(int(last[j]) + 1, min(stop_at, len(day.t) - 1) + 1):
            s = day.spot[i]
            if not np.isfinite(s):
                continue
            if (s > lvl) if side > 0 else (s < lvl):
                strike = round((s - 150) / 100) * 100 if side > 0 else round((s + 150) / 100) * 100
                key = (day.exp[0], float(strike), "C" if side > 0 else "P") if day.exp else None
                if key in day.q and np.isfinite(O.mid_of(day, key, i)):
                    return key, i
                return None
        return None
    return None


def _pivot_r1(prev, key) -> float:
    """Classic R1 of the contract's previous-session premium (its high, low and close of mids); NaN if not recorded."""
    hlc = O.prev_hlc(prev, key)
    if hlc is None:
        return float("nan")
    H, L, C = hlc
    return 2 * (H + L + C) / 3.0 - L


def CONTEXT(days):
    """(context, picks) of the option books over the given chain days: context = {sid: {date: {contract key: info}}},
    picks = {date: {contract key, ...}} (the contract-days the pool needs)."""
    ctx_: dict = {"IM-02": {}, "AA-01": {}, "DH-12": {}, "RK-01": {}, "QM-01": {}, "QM-02": {}}
    picks: dict = {}

    def add(sid, day, key, info):
        ctx_[sid].setdefault(day.date, {})[key] = info
        picks.setdefault(day.date, set()).add(key)

    for di, day in enumerate(days):
        dte = O.days_to_expiry(day)
        i916 = O.at_minute(day, 9 * 60 + 16)
        if i916 >= 0 and O.ist_ok(day, i916, 9 * 60 + 16):
            for cp in "CP":                                       # Zerodha: the premium closest to Rs 200 at 9:16
                k = O.closest_premium(day, i916, 200.0, cp)
                if k is not None:
                    add("IM-02", day, k, {"cp": cp})
            s = float(day.spot[i916])                             # QuantMan: the spot-based ATM call, locked at 9:16
            if day.exp and np.isfinite(s):
                k = (day.exp[0], float(round(s / 50.0) * 50), "C")
                if k in day.q:
                    r1 = _pivot_r1(O.previous_session(days, di), k)
                    add("QM-01", day, k, {"r1": r1})
                    if dte > 2 or dte == 0:                       # its multi-indicator basket skips 1-2 days to expiry
                        add("QM-02", day, k, {"r1": r1})
        i920 = O.at_minute(day, 9 * 60 + 20)                     # Saketh: Rs 50 premiums at 9:20 on expiry day and the
        if i920 >= 0 and O.ist_ok(day, i920, 9 * 60 + 20) and dte in (0, 1):    # day before, India VIX under 14
            vix = float(day.vix[i920])
            if np.isfinite(vix) and vix < RK01_VIX_MAX:
                for cp in "CP":
                    k = O.closest_premium(day, i920, 50.0, cp)
                    p0 = O.mid_of(day, k, i920) if k is not None else float("nan")
                    if k is not None and np.isfinite(p0):
                        add("RK-01", day, k, {"cp": cp, "p0": p0, "t": int(day.t[i920])})
        i925 = O.at_minute(day, 9 * 60 + 25)
        if i925 >= 0 and O.ist_ok(day, i925, 9 * 60 + 25):    # A&A: ITM premiums near Rs 180 at 9:25, first to break it
            cands = [O.closest_premium(day, i925, 180.0, cp, itm=True, below=True) for cp in "CP"]
            i945 = O.at_minute(day, 9 * 60 + 45)
            i_to = i945 if i945 >= 0 else len(day.t)
            best = None
            for k in cands:
                if k is None:
                    continue
                i = _first_cross_above(day, k, 180.0, i925 + 1, i_to)
                if i is not None and (best is None or i < best[1]):
                    best = (k, i)
            if best is not None:
                add("AA-01", day, best[0], {"t": int(day.t[best[1]])})
        got = _dh12_pick(day)
        if got is not None:
            add("DH-12", day, got[0], {"t": int(day.t[got[1]])})
    return ctx_, picks


def _info(p, sid, m):
    return (((p or {}).get("ctx") or {}).get(sid) or {}).get(getattr(m, "chain_date", None), {}).get(getattr(m, "contract", None))


def _row_at(m, t) -> int:
    j = int(np.searchsorted(m.t, int(t), "left"))
    return j if j < len(m.t) and int(m.t[j]) == int(t) else -1


def _first_row_from(m, hhmm: int) -> int:
    """The picked day's first row at or after hh:mm IST (its last row if none)."""
    d = m.n_days - 1
    a, z = int(m.d0[d]), int(m.d1[d])
    j = a + int(np.searchsorted(np.asarray(m.ist[a:z]), hhmm, "left"))
    return min(j, z - 1)


def _last_day_rows(m):
    """Mask of the picked day's rows (a contract market also carries the previous session's quotes)."""
    return np.asarray(m.day) == m.n_days - 1


# ═══ IM-02 Zerodha (In The Money): ORB on the option premium - the call and the put closest to Rs 200 at 9:16, their
#     9:16-11:15 range, a 3-minute close above it buys, 20% stop on the entry premium (real NIFTY premiums) ════════════

def im02(m, B, p, cache):
    info = _info(p, "IM-02", m)
    if info is None:
        return []
    ist = np.asarray(m.ist)
    last = m.n_days - 1
    win = _last_day_rows(m) & (ist >= 9 * 60 + 16) & (ist <= 11 * 60 + 15)
    if win.sum() < 60:
        return []
    hi = float(np.max(m.h[win]))
    b = B[3]
    for j in range(len(b.c)):
        if int(b.day[j]) != last or int(b.ist0[j]) < 11 * 60 + 15 or int(b.ist0[j]) >= T1500:
            continue
        if b.c[j] > hi:
            px = float(b.c[j])
            return [sig(b, j, 1, px * 0.8, "IM02_PREMIUM_ORB_" + info["cp"] + "E", info={"stop_frac": 0.20})]
    return []


def im02_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ AA-01 A&A Trading: the 9:30 premium breakout - the in-the-money call and put nearest Rs 180 at 9:25, buy the first
#     to break Rs 180 and hold above it, 20-point stop, 40-point target, out at 9:45 (real NIFTY premiums) ═══════════

def aa01(m, B, p, cache):
    info = _info(p, "AA-01", m)
    if info is None:
        return []
    j = _row_at(m, info["t"])
    if j < 0:
        return []
    b = B[1]
    k_last = _first_row_from(m, 9 * 60 + 45)
    if k_last <= j:
        return []
    return [sig(b, j, 1, float(b.c[j]) - 20.0, "AA01_930_PREMIUM_BREAKOUT", info={"stop_dist": 20.0, "k_last": int(k_last)})]


def aa01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ DH-12 Dhan: Nifty option buying after 3 PM - a 2-minute MACD histogram flip from 14:45 with ADX above 25 and
#     rising, the flip candle's extreme broken, a 150-point in-the-money option, 15 premium points (real premiums) ═════

def dh12(m, B, p, cache):
    info = _info(p, "DH-12", m)
    if info is None:
        return []
    j = _row_at(m, info["t"])
    if j < 0:
        return []
    b = B[1]
    k_last = _first_row_from(m, 15 * 60 + 25)
    if k_last <= j:
        return []
    px = float(b.c[j])
    return [sig(b, j, 1, px * 0.75, "DH12_3PM_MOMENTUM", info={"stop_frac": 0.25, "k_last": int(k_last)})]


def dh12_x(m, B, p, cache):
    return XExits(target_r=None, target_abs=15.0)


# ═══ RK-01 Saketh Ramakrishna's automated system (built on Fin Target, tested on Stockmock): at 9:20 the call and the
#     put nearest Rs 50; each is bought when it gains 10 points (wait and trade), 20-point stop trailed 1:1, 40-point
#     target, out at 3:29; only on expiry day and the day before, with India VIX under 14 (real NIFTY premiums) ═══════

def rk01(m, B, p, cache):
    info = _info(p, "RK-01", m)
    if info is None:
        return []
    j = _row_at(m, info["t"])
    if j < 0:
        return []
    b = B[1]
    trig = float(info["p0"]) + 10.0
    last = int(m.d1[m.n_days - 1]) - 1
    return [sig(b, j, 1, trig - 20.0, "RK01_RS50_WAIT_TRADE_" + info["cp"] + "E", entry_stop=trig, expire_k=last,
                info={"stop_dist": 20.0})]


def rk01_x(m, B, p, cache):
    return XExits(target_r=2.0, trail=("dist_r", 0.0, 1.0))


def _cci(b, n: int):
    """Commodity Channel Index of the typical price (TradingView's ta.cci on hlc3)."""
    tp = (np.asarray(b.h, float) + np.asarray(b.l, float) + np.asarray(b.c, float)) / 3.0
    out = np.full(len(tp), np.nan)
    for j in range(n - 1, len(tp)):
        w = tp[j - n + 1:j + 1]
        md = np.mean(np.abs(w - w.mean()))
        if md > 0:
            out[j] = (tp[j] - w.mean()) / (0.015 * md)
    return out


# ═══ QM-02 QuantMan's multi-indicator option basket: the ATM call locked at 9:16, on its 3-minute premium chart a close
#     above the Supertrend (10, 2), the upper Bollinger Band (15, 2), the 9:16-9:30 premium high and the premium's R1,
#     with RSI (14) above 70 and CCI (8) above 100; out on a close below the Supertrend; two trades a day; not 1-2 days
#     before expiry (real NIFTY premiums) ════════════════════════════════════════════════════════════════════════════

def qm02(m, B, p, cache):
    info = _info(p, "QM-02", m)
    if info is None or not np.isfinite(info.get("r1", np.nan)):
        return []
    r1 = float(info["r1"])
    last = m.n_days - 1
    ist = np.asarray(m.ist)
    win = _last_day_rows(m) & (ist >= 9 * 60 + 16) & (ist < 9 * 60 + 30)
    if win.sum() < 8:
        return []
    rng_hi = float(np.max(m.h[win]))
    b = B[3]
    cx = ctx(m, B, 3, cache)
    st, _ = cx.supertrend(10, 2.0)
    r14 = cx.rsi(14)
    _, up, _ = cx.bollinger(15, 2.0)
    cci = _cached(cache, ("ze9_cci8_3",), lambda: _cci(b, 8))
    c = b.c
    out = []
    for j in range(len(c)):
        if int(b.day[j]) != last or int(b.ist0[j]) < 9 * 60 + 30 or int(b.ist0[j]) >= T1500:
            continue
        if not _fin(st[j], r14[j], up[j], cci[j]):
            continue
        if c[j] > st[j] and cci[j] > 100 and c[j] > up[j] and c[j] > rng_hi and c[j] > r1 and r14[j] > 70:
            out.append(sig(b, j, 1, float(c[j]) * 0.5, "QM02_MULTI_INDICATOR_CE",
                           info={"risk_unit": max(float(c[j]) - float(st[j]), 0.05)}))
    return out


def qm02_x(m, B, p, cache):
    b = B[3]
    st, _ = ctx(m, B, 3, cache).supertrend(10, 2.0)
    c = np.asarray(b.c, float)
    with np.errstate(invalid="ignore"):
        x = c < st
    return XExits(target_r=None, xbars=b, xlong=x, xshort=np.zeros(len(x), bool))


# ═══ QM-01 QuantMan's option basket: the ATM call locked at 9:16, on its 5-minute premium chart a close above the
#     Parabolic SAR, the Supertrend (10, 2) and the premium's R1; out on a close below the Supertrend; one trade a day
#     (the video's put adjustment after the exit is left out: its conditions are not clear) (real NIFTY premiums) ════

def qm01(m, B, p, cache):
    info = _info(p, "QM-01", m)
    if info is None or not np.isfinite(info.get("r1", np.nan)):
        return []
    r1 = float(info["r1"])
    last = m.n_days - 1
    b = B[5]
    st, _ = ctx(m, B, 5, cache).supertrend(10, 2.0)
    ps, _ = _cached(cache, ("ze9_psar_5",), lambda: I.psar(b))
    c = b.c
    out = []
    for j in range(len(c)):
        if int(b.day[j]) != last or int(b.ist0[j]) >= T1500:
            continue
        if int(b.ist0[j]) + 5 <= 9 * 60 + 16:                    # the basket opens at 9:16 (a candle closing after it)
            continue
        if not _fin(st[j], ps[j]):
            continue
        if c[j] > ps[j] and c[j] > st[j] and c[j] > r1:
            out.append(sig(b, j, 1, float(c[j]) * 0.5, "QM01_PSAR_SUPERTREND_R1_CE",
                           info={"risk_unit": max(float(c[j]) - float(st[j]), 0.05)}))
    return out


def qm01_x(m, B, p, cache):
    b = B[5]
    st, _ = ctx(m, B, 5, cache).supertrend(10, 2.0)
    c = np.asarray(b.c, float)
    with np.errstate(invalid="ignore"):
        x = c < st
    return XExits(target_r=None, xbars=b, xlong=x, xshort=np.zeros(len(x), bool))
