"""Ninth batch of the channel-shortlist study (14 Nov 2026): the cards of the owner's channel list 21-40 (cards/<video>.txt;
the 'A' rules are this code). Same conventions as ze_more4 / ze_more6: BTCUSD and ETHUSD are Delta Exchange perpetuals on
the UTC day (real volume), XAUUSD is gold booked on Delta XAUTUSD (the 17:00 New York day), EURUSD and GBPUSD are the
desk's CME euro and pound futures minutes (the 17:00 New York day, a pip is 0.0001), AAPL is Apple's 09:30-16:00 New
York session (Yahoo Finance minutes on the desk).

Every signal uses only the bars up to its own signal bar; a daily signal waits until its day is complete (the next day
has started). Two strategies replay their own earlier trades on their signal bars to decide a rule that depends on the
open trade, never looking ahead: CT-04 ('close a winning trade at the next session's open': the open trade's entry
against each daily close) and RB-01 (no new trade after a stop or a price-jump exit until the close is back at the
average). Strategies without a stop in the video get a far catastrophe stop and size on sig.info["risk_unit"]
(1% of the price = a position the size of the account)."""

from __future__ import annotations

import numpy as np

import yc_ind as I
import yt_ind as YI
import zd_common as Z
from yc_common import ctx, sig
from yc_engine import XExits
from yt_engine import Signal
from ze_more2 import _last_done
from ze_more4 import TICK, _cached, _daily, _fin
from ze_more5 import _hma

PIP = 1e-4                  # EUR/USD and GBP/USD (and the CME futures that stand for them)
ALL_IN = 0.01               # risk unit, as a fraction of the price, of a position the size of the account (1% risk)


# ── indicators ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _linreg(x, n):
    """(value, slope) of the least-squares line through the last n values at each bar (Pine's linreg(x, n, 0))."""
    x = np.asarray(x, float)
    N = len(x)
    val = np.full(N, np.nan)
    slope = np.full(N, np.nan)
    if N < n:
        return val, slope
    k = np.arange(n, dtype=float)
    km = (n - 1) / 2.0
    sxx = float(((k - km) ** 2).sum())
    sy = np.convolve(x, np.ones(n), "valid")
    sxy = np.convolve(x, k[::-1], "valid")          # sum over the window of (position in it) x value
    b = (sxy - km * sy) / sxx
    a = sy / n - b * km
    val[n - 1:] = a + b * (n - 1)
    slope[n - 1:] = b
    return val, slope


def _bodies_beyond(o, c, line, n):
    """(the last n bodies all above the line, all below), the current bar included."""
    with np.errstate(invalid="ignore"):
        above = (np.minimum(o, c) > line).astype(int)
        below = (np.maximum(o, c) < line).astype(int)
    w = np.ones(n, int)
    return np.convolve(above, w)[:len(above)] >= n, np.convolve(below, w)[:len(below)] >= n


def _done(b, j) -> bool:
    """A daily bar may signal once its day is complete: the next day has started."""
    return j + 1 < len(b.c)


# ═══ CT-04 Larry Williams outside bar: a red (green) outside candle closing beyond the previous low (high), 250-pip stop,
#     out at the next open after a daily close in profit (EUR/USD, GBP/USD daily) ═══════════════════════════════════════

def _ct04_book(m, cache):
    """Replay of the strategy on daily bars: (signals [(day, side, stop)], long exit flags, short exit flags). A trade
    enters at the next day's open (plus the half spread); each later day it is stopped if the day's range reaches the
    stop, else a close beyond the entry flags it to exit at the next open; a new signal needs no open trade."""
    def calc():
        d = _daily(m, cache)
        o, h, l, c = (np.asarray(x, float) for x in (d.o, d.h, d.l, d.c))
        half = np.asarray(m.half, float)
        n = len(c)
        xl = np.zeros(n, bool)
        xs = np.zeros(n, bool)
        sigs = []
        pos = None                                     # (side, entry, stop, first day)
        for j in range(1, n):
            if pos is not None:
                side, entry, stop, j0 = pos
                if (l[j] <= stop) if side > 0 else (h[j] >= stop):
                    pos = None                         # stopped during day j
                elif (c[j] > entry) if side > 0 else (c[j] < entry):
                    (xl if side > 0 else xs)[j] = True
                    pos = None                         # out at day j + 1's open; no new trade from day j's close
                    continue
                else:
                    continue                           # still open: no new signal
            if not _done(d, j):
                continue
            red_out = o[j] > c[j] and h[j] > h[j - 1] and l[j] < l[j - 1] and c[j] < l[j - 1]
            green_out = c[j] > o[j] and h[j] > h[j - 1] and l[j] < l[j - 1] and c[j] > h[j - 1]
            if red_out or green_out:
                side = 1 if red_out else -1
                stop = c[j] - side * 250 * PIP
                r = int(d.i0[j + 1])
                entry = o[j + 1] + side * half[r]
                sigs.append((j, side, stop))
                pos = (side, entry, stop, j + 1)
                # the entry day itself is checked on the next pass (j + 1)
        return sigs, xl, xs
    return _cached(cache, ("ze8_ct04",), calc)


def ct04(m, B, p, cache):
    d = _daily(m, cache)
    sigs, _, _ = _ct04_book(m, cache)
    return [sig(d, j, side, float(stop), "CT04_OUTSIDE_BAR_" + ("LONG" if side > 0 else "SHORT")) for j, side, stop in sigs]


def ct04_x(m, B, p, cache):
    _, xl, xs = _ct04_book(m, cache)
    return XExits(target_r=None, xbars=_daily(m, cache), xlong=xl, xshort=xs)


# ═══ CT-05 EMA 100 and VWAP trend (six and three bodies), a candle within 0.2% of the VWAP, 0.8 ATR stop, 2R ════════════

def _ct05_arr(m, B, cache):
    def calc():
        b = B[15]
        vw = Z.vwap_of(m, b, cache, "15")
        e100 = ctx(m, B, 15, cache).ema(100)
        a7 = _cached(cache, ("ze_atr7_15",), lambda: YI.atr(b, 7))
        eu, ed = _bodies_beyond(b.o, b.c, e100, 6)
        vu, vd = _bodies_beyond(b.o, b.c, vw, 3)
        return vw, a7, eu & vu, ed & vd
    return _cached(cache, ("ze8_ct05",), calc)


def ct05(m, B, p, cache):
    b = B[15]
    vw, a7, up, dn = _ct05_arr(m, B, cache)
    out = []
    for j in range(110, len(b.c) - 1):
        if not _fin(vw[j], a7[j]) or b.day[j + 1] != b.day[j]:
            continue
        tol = 0.002 * float(b.c[j])
        d = 0.8 * float(a7[j])
        if up[j] and abs(float(b.l[j]) - vw[j]) <= tol:
            out.append(sig(b, j, 1, float(b.c[j]) - d, "CT05_EMA_VWAP_BOUNCE_LONG", info={"stop_dist": d}))
        elif dn[j] and abs(float(b.h[j]) - vw[j]) <= tol:
            out.append(sig(b, j, -1, float(b.c[j]) + d, "CT05_EMA_VWAP_BOUNCE_SHORT", info={"stop_dist": d}))
    return out


def ct05_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ CT-06 Hull MA 16 / 65 cross on 4 hours, RSI (14) above 52, the last daily close above its 50-day linear
#     regression; out on the cross back (long, no stop: catastrophe 50%, one account) ════════════════════════════════════

def _ct06_arr(m, B, cache):
    def calc():
        b = B[240]
        c = np.asarray(b.c, float)
        hf, hs = _hma(c, 16), _hma(c, 65)
        d = _daily(m, cache)
        lr, _ = _linreg(d.c, 50)
        return hf, hs, ctx(m, B, 240, cache).rsi(14), d, lr
    return _cached(cache, ("ze8_ct06",), calc)


def ct06(m, B, p, cache):
    b = B[240]
    hf, hs, r14, d, lr = _ct06_arr(m, B, cache)
    out = []
    for j in range(1, len(b.c)):
        if not _fin(hf[j], hs[j], hf[j - 1], hs[j - 1], r14[j]):
            continue
        if not (hf[j] > hs[j] and hf[j - 1] <= hs[j - 1] and r14[j] > 52):
            continue
        dj = _last_done(d, b, j)
        if dj < 0 or not np.isfinite(lr[dj]) or not d.c[dj] > lr[dj]:
            continue
        px = float(b.c[j])
        out.append(sig(b, j, 1, px * 0.5, "CT06_HMA_CROSS_LONG", info={"stop_frac": 0.5, "risk_unit": px * ALL_IN}))
    return out


def ct06_x(m, B, p, cache):
    hf, hs, _, _, _ = _ct06_arr(m, B, cache)
    with np.errstate(invalid="ignore"):
        x = hf < hs
    return XExits(target_r=None, xbars=B[240], xlong=x, xshort=np.zeros(len(x), bool))


# ═══ CT-08 ADX regime switch on 1 hour: trend mode (ADX > 20) and range mode (ADX < 16), Bollinger re-entry, RSI,
#     the 4-hour linear regression and the 100-bar slope; 5.5% target, 1.5% stop ════════════════════════════════════════

def _ct08_arr(m, B, cache):
    def calc():
        b = B[60]
        adx, _, _ = I.adx(b, 14)
        mid, up, lo = ctx(m, B, 60, cache).bollinger(20, 2.0)
        _, slope = _linreg(b.c, 100)
        lr4, _ = _linreg(B[240].c, 50)
        return adx, up, lo, ctx(m, B, 60, cache).rsi(14), slope, lr4
    return _cached(cache, ("ze8_ct08",), calc)


def ct08(m, B, p, cache):
    b, b4 = B[60], B[240]
    adx, up, lo, r14, slope, lr4 = _ct08_arr(m, B, cache)
    c = np.asarray(b.c, float)
    out = []
    for j in range(1, len(c)):
        if not _fin(adx[j], up[j], lo[j], up[j - 1], lo[j - 1], r14[j]):
            continue
        x_up = c[j] > lo[j] and c[j - 1] <= lo[j - 1]          # back above the lower band
        x_dn = c[j] < up[j] and c[j - 1] >= up[j - 1]          # back below the upper band
        if not (x_up or x_dn):
            continue
        side, setup = 0, ""
        if adx[j] > 20:
            k4 = _last_done(b4, b, j)
            if k4 < 0 or not _fin(lr4[k4], slope[j]):
                continue
            if x_up and c[j] > lr4[k4] and slope[j] > 0 and r14[j] > 20:
                side, setup = 1, "CT08_TREND_LONG"
            elif x_dn and c[j] < lr4[k4] and slope[j] < 0 and r14[j] < 80:
                side, setup = -1, "CT08_TREND_SHORT"
        elif adx[j] < 16:
            if x_up and r14[j] < 35:
                side, setup = 1, "CT08_RANGE_LONG"
            elif x_dn and r14[j] > 65:
                side, setup = -1, "CT08_RANGE_SHORT"
        if side:
            out.append(sig(b, j, side, float(c[j]) * (1 - side * 0.015), setup,
                           info={"stop_frac": 0.015, "target_frac": 0.055}))
    return out


def ct08_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ RB-01 Envelope: a limit 7% from the 6-period Donchian midline of the close, out at the midline, 40% stop, a 15%
#     price-jump exit, no new trade after a stop or a jump until the close is back at the average (first envelope) ═══════

ENV, JUMP, RB_STOP = 0.07, 0.15, 0.40


def _rb01_arr(m, B, cache):
    def calc():
        b = B[60]
        c = np.asarray(b.c, float)
        avg = (I.highest(c, 6) + I.lowest(c, 6)) / 2.0
        cp = np.r_[np.nan, c[:-1]]
        with np.errstate(invalid="ignore"):
            jump_dn = c < cp * (1 - JUMP)
            jump_up = c > cp * (1 + JUMP)
            back_up = c >= avg                       # a long's limit at the average is marketable from here
            back_dn = c <= avg
        return avg, jump_dn, jump_up, back_up, back_dn
    return _cached(cache, ("ze8_rb01",), calc)


def _rb01_book(m, B, cache):
    """Replay on 1-hour bars of the bars whose close sends the two band limits (flat and allowed). Each bar's prices are
    taken as the engine trades them (the ask for buying, the bid for selling, row by row): a long fills when the next
    bar's ask reaches the lower band (a short when its bid reaches the upper band; a bar reaching both is taken as long);
    then, bar by bar, the stop (40% from the fill) first, then the target (the average, moved to each close's average
    while that is in the trade's favour), then at the close a 15% jump or a close back at the average flags an exit at
    the next open. After a stop or a jump exit, no orders while the close is on the losing side of the average."""
    def calc():
        b = B[60]
        c = np.asarray(b.c, float)
        hf = np.asarray(m.half, float)
        i0 = np.asarray(b.i0, np.int64)
        lo_bid = np.minimum.reduceat(np.asarray(m.l, float) - hf, i0)
        lo_ask = np.minimum.reduceat(np.asarray(m.l, float) + hf, i0)
        hi_bid = np.maximum.reduceat(np.asarray(m.h, float) - hf, i0)
        hi_ask = np.maximum.reduceat(np.asarray(m.h, float) + hf, i0)
        o_ask = np.asarray(m.o, float)[i0] + hf[i0]
        o_bid = np.asarray(m.o, float)[i0] - hf[i0]
        avg, jdn, jup, bu, bd = _rb01_arr(m, B, cache)
        n = len(c)
        allowed = []
        pos = None                                   # (side, entry, stop, target)
        gate = 0                                     # +1: after a long stop / jump; -1: after a short one
        pending = False                              # an exit flagged at the last close fills at this bar's open
        for j in range(n):
            if pos is not None:
                side, entry, stop, tgt = pos
                if pending:
                    pos, pending = None, False
                elif (lo_bid[j] <= stop) if side > 0 else (hi_ask[j] >= stop):
                    pos, gate = None, side
                elif (hi_bid[j] >= tgt) if side > 0 else (lo_ask[j] <= tgt):
                    pos = None
                else:
                    if jdn[j] if side > 0 else jup[j]:
                        pending, gate = True, side
                    elif bu[j] if side > 0 else bd[j]:
                        pending = True
                    elif np.isfinite(avg[j]) and (avg[j] - entry) * side > 0:
                        pos = (side, entry, stop, float(avg[j]))
                    if pending:
                        continue                     # still in the trade at this close
            if pos is not None:
                continue
            if gate and np.isfinite(avg[j]) and ((c[j] >= avg[j]) if gate > 0 else (c[j] <= avg[j])):
                gate = 0
            if gate or not np.isfinite(avg[j]) or j + 1 >= n:
                continue
            allowed.append(j)
            lo_b, hi_b = avg[j] * (1 - ENV), avg[j] * (1 + ENV)
            if lo_ask[j + 1] <= lo_b:
                e = min(lo_b, o_ask[j + 1])
                pos = (1, e, e * (1 - RB_STOP), float(avg[j]))
            elif hi_bid[j + 1] >= hi_b:
                e = max(hi_b, o_bid[j + 1])
                pos = (-1, e, e * (1 + RB_STOP), float(avg[j]))
        return allowed
    return _cached(cache, ("ze8_rb01_book",), calc)


def rb01(m, B, p, cache):
    b = B[60]
    avg = _rb01_arr(m, B, cache)[0]
    out = []
    for j in _rb01_book(m, B, cache):
        exp = int(b.i1[j + 1])
        lo_b, hi_b = float(avg[j] * (1 - ENV)), float(avg[j] * (1 + ENV))
        out.append(sig(b, j, 1, lo_b * (1 - RB_STOP), "RB01_ENVELOPE_LONG", entry_limit=lo_b, expire_k=exp,
                       target_px=float(avg[j]), info={"stop_frac": RB_STOP, "risk_unit": lo_b * 3 * ALL_IN}))
        out.append(sig(b, j, -1, hi_b * (1 + RB_STOP), "RB01_ENVELOPE_SHORT", entry_limit=hi_b, expire_k=exp,
                       target_px=float(avg[j]), info={"stop_frac": RB_STOP, "risk_unit": hi_b * 3 * ALL_IN}))
    return out


def rb01_x(m, B, p, cache):
    b = B[60]
    avg, jdn, jup, bu, bd = _rb01_arr(m, B, cache)
    return XExits(target_r=None, tgt_level=(b, avg, avg), xbars=b, xlong=jdn | bu, xshort=jup | bd)


# ═══ QN-01 SMA 25 / SMA 100 on 5 minutes, always in the market: a cross reverses the position (Apple) ════════════════════

def _qn01_flags(m, B, cache):
    def calc():
        cx = ctx(m, B, 5, cache)
        f, s = cx.sma(25), cx.sma(100)
        fp, sp = np.r_[np.nan, f[:-1]], np.r_[np.nan, s[:-1]]
        with np.errstate(invalid="ignore"):
            return (f > s) & (fp <= sp), (f < s) & (fp >= sp)
    return _cached(cache, ("ze8_qn01",), calc)


def qn01(m, B, p, cache):
    b = B[5]
    up, dn = _qn01_flags(m, B, cache)
    out = []
    for j in range(100, len(b.c)):
        if up[j] or dn[j]:
            side = 1 if up[j] else -1
            px = float(b.c[j])
            out.append(sig(b, j, side, px * (1 - side * 0.15), "QN01_SMA25_100_" + ("LONG" if side > 0 else "SHORT"),
                           info={"stop_frac": 0.15, "risk_unit": px * ALL_IN}))
    return out


def qn01_x(m, B, p, cache):
    up, dn = _qn01_flags(m, B, cache)
    return XExits(target_r=None, xbars=B[5], xlong=dn, xshort=up)


# ═══ MS-03 Previous day's high / low: OCO stop orders 3 pips beyond, 5-pip stop, 10-pip target (EUR/USD, GBP/USD) ═══════

def ms03(m, B, p, cache):
    d = _daily(m, cache)
    out = []
    for j in range(len(d.c) - 1):
        hi, lo = float(d.h[j]), float(d.l[j])
        if not (hi > lo):
            continue
        exp = int(d.i1[j + 1])
        buy, sell = hi + 3 * PIP, lo - 3 * PIP          # his stop and target are fixed from the order prices
        s = sig(d, j, 1, buy - 5 * PIP, "MS03_PDH_BREAKOUT_LONG", entry_stop=buy, expire_k=exp, target_px=buy + 10 * PIP)
        s.alt = Signal(s.day, s.k, -1, sell + 5 * PIP, "MS03_PDL_BREAKOUT_SHORT", {}, sell, exp, sell - 10 * PIP)
        out.append(s)
    return out


def ms03_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ RU-07 RSI under 30 (over 70), then the first candle closing well beyond the Bollinger middle band, stop beyond the
#     outer band, 1.5R (bitcoin, gold; 30 minutes) ═════════════════════════════════════════════════════════════════════

ARM_BARS = 20


def ru07(m, B, p, cache):
    b = B[30]
    cx = ctx(m, B, 30, cache)
    mid, up, lo = cx.bollinger(20, 2.0)
    r14 = cx.rsi(14)
    o, c = np.asarray(b.o, float), np.asarray(b.c, float)
    out = []
    arm_l = arm_s = -1                             # bar of the last arming reading (-1: not armed)
    for j in range(20, len(c)):
        if not _fin(mid[j], up[j], lo[j], r14[j]):
            continue
        if r14[j] < 30:
            arm_l, arm_s = j, -1
            continue
        if r14[j] > 70:
            arm_s, arm_l = j, -1
            continue
        top, bot = max(o[j], c[j]), min(o[j], c[j])
        body = top - bot
        if arm_l >= 0 and j - arm_l <= ARM_BARS and c[j] > mid[j] and (top - max(bot, mid[j])) >= 0.5 * body:
            out.append(sig(b, j, 1, float(lo[j]) * (1 - TICK), "RU07_BB_RSI_LONG"))
            arm_l = -1
        elif arm_s >= 0 and j - arm_s <= ARM_BARS and c[j] < mid[j] and (min(top, mid[j]) - bot) >= 0.5 * body:
            out.append(sig(b, j, -1, float(up[j]) * (1 + TICK), "RU07_BB_RSI_SHORT"))
            arm_s = -1
        if arm_l >= 0 and j - arm_l > ARM_BARS:
            arm_l = -1
        if arm_s >= 0 and j - arm_s > ARM_BARS:
            arm_s = -1
    return out


def ru07_x(m, B, p, cache):
    return XExits(target_r=1.5)


# ═══ AN-01 EMA 12 crossing above the EMA 50 within two daily bars, the close above the EMA 12, out on the cross back
#     (long, no stop: catastrophe 50%, one account; bitcoin daily) ══════════════════════════════════════════════════════

def _an01_arr(m, cache):
    def calc():
        d = _daily(m, cache)
        c = np.asarray(d.c, float)
        return d, I.ema(c, 12), I.ema(c, 50)
    return _cached(cache, ("ze8_an01",), calc)


def an01(m, B, p, cache):
    d, e12, e50 = _an01_arr(m, cache)
    c = np.asarray(d.c, float)
    out = []
    last_cross = -10
    used = -1
    for j in range(51, len(c)):
        if not _fin(e12[j], e50[j], e12[j - 1], e50[j - 1]):
            continue
        if e12[j] > e50[j] and e12[j - 1] <= e50[j - 1]:
            last_cross = j
        if not _done(d, j) or used == last_cross or j - last_cross > 1:
            continue
        if e12[j] > e50[j] and c[j] > e12[j]:
            out.append(sig(d, j, 1, float(c[j]) * 0.5, "AN01_EMA12_50_LONG",
                           info={"stop_frac": 0.5, "risk_unit": float(c[j]) * ALL_IN}))
            used = last_cross
    return out


def an01_x(m, B, p, cache):
    d, e12, e50 = _an01_arr(m, cache)
    with np.errstate(invalid="ignore"):
        x = e12 < e50
    return XExits(target_r=None, xbars=d, xlong=x, xshort=np.zeros(len(x), bool))


# ═══ WT-02 A close beyond the Keltner Channel (EMA 20 +- 2 ATR 10) with the DI of that side above 25 and above the
#     other, stop at the opposite band, 2R (bitcoin, 1 hour) ════════════════════════════════════════════════════════════

def wt02(m, B, p, cache):
    b = B[60]
    cx = ctx(m, B, 60, cache)
    e20, a10 = cx.ema(20), cx.atr(10)
    _, pdi, mdi = _cached(cache, ("ze8_dmi60",), lambda: I.adx(b, 14))
    c = np.asarray(b.c, float)
    out = []
    for j in range(30, len(c)):
        if not _fin(e20[j], a10[j], pdi[j], mdi[j]):
            continue
        up, lo = e20[j] + 2 * a10[j], e20[j] - 2 * a10[j]
        if c[j] > up and pdi[j] > 25 and pdi[j] > mdi[j]:
            out.append(sig(b, j, 1, float(lo), "WT02_KELTNER_DMI_LONG"))
        elif c[j] < lo and mdi[j] > 25 and mdi[j] > pdi[j]:
            out.append(sig(b, j, -1, float(up), "WT02_KELTNER_DMI_SHORT"))
    return out


def wt02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ CU-01 MA 9 crossing above the MA 50 under a falling MA 50 / 100 / 200 stack, out when the MA 9 crosses above the
#     MA 200 or at +8% (long, no stop: catastrophe 50%, one account; bitcoin, 1 hour) ══════════════════════════════════

def _cu01_arr(m, B, cache):
    def calc():
        cx = ctx(m, B, 60, cache)
        s9, s50, s100, s200 = cx.sma(9), cx.sma(50), cx.sma(100), cx.sma(200)
        s9p, s50p, s200p = (np.r_[np.nan, x[:-1]] for x in (s9, s50, s200))
        with np.errstate(invalid="ignore"):
            entry = (s9 > s50) & (s9p <= s50p) & (s50 < s100) & (s100 < s200)
            out = (s9 > s200) & (s9p <= s200p)
        return entry, out
    return _cached(cache, ("ze8_cu01",), calc)


def cu01(m, B, p, cache):
    b = B[60]
    entry, _ = _cu01_arr(m, B, cache)
    out = []
    for j in range(200, len(b.c)):
        if entry[j]:
            px = float(b.c[j])
            out.append(sig(b, j, 1, px * 0.5, "CU01_MA_SCALPER_LONG",
                           info={"stop_frac": 0.5, "target_frac": 0.08, "risk_unit": px * ALL_IN}))
    return out


def cu01_x(m, B, p, cache):
    _, x = _cu01_arr(m, B, cache)
    return XExits(target_r=None, xbars=B[60], xlong=x, xshort=np.zeros(len(x), bool))
