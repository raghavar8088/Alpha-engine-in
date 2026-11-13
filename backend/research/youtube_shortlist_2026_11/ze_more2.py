"""Third batch of the channel-shortlist study (13 Nov 2026): the cards read after the second deploy (cards/<video>.txt;
the 'A' rules are this code). Same markets and conventions as ze_india / ze_global / ze_more: NIFTY / BANKNIFTY
one-minute index rows from 09:15 (placeholder volume: their VWAP is time-weighted), NSE5 the five-minute stock pool
(real volume), BTCUSD (the UTC day, out at 23:55 UTC), XAUUSD (gold; booked on Delta XAUTUSD)."""

from __future__ import annotations

import numpy as np

import yc_ind as I
import yt_ind as YI
from yc_common import bars_of_day, ctx, flags_cross, sig
from yc_engine import XExits

import zd_common as Z
import ze_common as E
from ze_common import T, sorted_out
from ze_more import _cci


def _days(b, d):
    return list(bars_of_day(b, d))


def _fin(*xs) -> bool:
    return all(np.isfinite(x) for x in xs)


def _cached(cache, key, fn):
    if key not in cache:
        cache[key] = fn()
    return cache[key]


def _last_done(big, small, j):
    """Index of the last `big` bar completed by the close of `small` bar j (-1 if none)."""
    return int(np.searchsorted(big.i1, small.i1[j], "right")) - 1


def _swing_levels(b, n=2):
    """(latest confirmed swing low, latest confirmed swing high) as known at each bar's close (fractals of n bars)."""
    ph, pl = YI.fractals(b, n)
    lo = np.full(len(b.c), np.nan)
    hi = np.full(len(b.c), np.nan)
    cl = ch = np.nan
    for j in range(len(b.c)):
        p = j - n
        if p >= 0:
            if pl[p]:
                cl = float(b.l[p])
            if ph[p]:
                ch = float(b.h[p])
        lo[j], hi[j] = cl, ch
    return lo, hi


# ═══ FY-01 VWAP flow shift: price on one side of the VWAP (14), Chaikin oscillator (3, 10) crossing zero the other way ═

def _fy01_arr(m, B, cache):
    def calc():
        b = B[5]
        h, l, c = (np.asarray(x, float) for x in (b.h, b.l, b.c))
        v = ctx(m, B, 5, cache).vol().astype(float)
        tp = (h + l + c) / 3.0
        w = np.lib.stride_tricks.sliding_window_view
        vw = np.full(len(c), np.nan)
        if len(c) >= 14:
            vw[13:] = (w(tp * v, 14).sum(1)) / np.maximum(w(v, 14).sum(1), 1e-12)
        rng_ = h - l
        with np.errstate(invalid="ignore", divide="ignore"):
            mfm = np.where(rng_ > 0, ((c - l) - (h - c)) / rng_, 0.0)
        adl = np.cumsum(mfm * v)
        co = E.ema(adl, 3) - E.ema(adl, 10)
        return vw, co, ctx(m, B, 5, cache).ema(10)
    return _cached(cache, ("ze_fy01",), calc)


def fy01(m, B, p, cache):
    b = B[5]
    vw, co, e10 = _fy01_arr(m, B, cache)
    out = []
    for j in range(30, len(b.c) - 1):
        t = int(b.ist0[j])
        if not ((T(11, 25) <= t < T(12, 55)) or (T(13, 25) <= t < T(14, 40))) or b.day[j + 1] != b.day[j]:
            continue
        if not _fin(vw[j], co[j], co[j - 1], e10[j]):
            continue
        c, o = float(b.c[j]), float(b.o[j])
        if c < vw[j] and co[j] > 0 >= co[j - 1] and c > o and c > e10[j]:
            out.append(sig(b, j, 1, c - 69.0, "FY01_FLOW_SHIFT_LONG", info={"stop_dist": 69.0}))
        elif c > vw[j] and co[j] < 0 <= co[j - 1] and c < o and c < e10[j]:
            out.append(sig(b, j, -1, c + 69.0, "FY01_FLOW_SHIFT_SHORT", info={"stop_dist": 69.0}))
    return out


def fy01_x(m, B, p, cache):
    b = B[5]
    _, _, e10 = _fy01_arr(m, B, cache)
    with np.errstate(invalid="ignore"):
        return XExits(target_r=None, xbars=b, xlong=b.c < e10, xshort=b.c > e10)


# ═══ FY-02 11:00-11:15 range breakout on one-minute Nifty, first close beyond, far-side stop, out at 15:24 ════════════

def fy02(m, B, p, cache):
    b = B[1]
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        rj = [j for j in js if T(11, 0) <= int(b.ist0[j]) < T(11, 15)]
        if len(rj) < 12:
            continue
        H, L = float(b.h[rj].max()), float(b.l[rj].min())
        for j in js:
            t = int(b.ist0[j])
            if t < T(11, 15):
                continue
            if t >= T(15, 20):
                break
            if b.c[j] > H:
                out.append(sig(b, j, 1, L, "FY02_1115_RANGE_LONG"))
                break
            if b.c[j] < L:
                out.append(sig(b, j, -1, H, "FY02_1115_RANGE_SHORT"))
                break
    return out


def fy02_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ AO-03 EMA 9/21 cross, a steep 9 EMA, pullback touching it, break of a bullish candle, candle stop, 1:2 (1 min) ═══

def ao03(m, B, p, cache):
    b = B[1]
    cx = ctx(m, B, 1, cache)
    e9, e21, a = cx.ema(9), cx.ema(21), cx.atr(14)
    up, dn = flags_cross(e9, e21)
    slope = np.r_[np.full(5, np.nan), e9[5:] - e9[:-5]]
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js:
            continue
        last_up = last_dn = -10 ** 9
        steep_up = steep_dn = False
        for j in js:
            if up[j]:
                last_up, steep_up = j, False
            if dn[j]:
                last_dn, steep_dn = j, False
            if not _fin(a[j], slope[j], e9[j], e21[j]):
                continue
            steep_up = steep_up or (last_up > last_dn and slope[j] >= a[j])
            steep_dn = steep_dn or (last_dn > last_up and -slope[j] >= a[j])
            t = int(b.ist0[j])
            if not (T(9, 30) <= t < T(14, 45)):
                continue
            exp = int(b.i1[j]) + 3
            body, rg = abs(float(b.c[j] - b.o[j])), float(b.h[j] - b.l[j])
            if last_up > last_dn and j - last_up <= 30 and steep_up:
                touch = bool((b.l[j - 2:j + 1] <= e9[j - 2:j + 1]).any()) and b.c[j] > e21[j]
                bull = (b.c[j] > b.o[j] and rg > 0 and body >= 0.6 * rg and b.c[j] > e9[j]) or E.pin_bar(b, j, 1)
                if touch and bull and e9[j] >= e9[j - 3]:
                    out.append(sig(b, j, 1, float(b.l[j]), "AO03_EMA9_PULLBACK_LONG", entry_stop=float(b.h[j]) + 1.0,
                                   expire_k=exp))
            elif last_dn > last_up and j - last_dn <= 30 and steep_dn:
                touch = bool((b.h[j - 2:j + 1] >= e9[j - 2:j + 1]).any()) and b.c[j] < e21[j]
                bear = (b.c[j] < b.o[j] and rg > 0 and body >= 0.6 * rg and b.c[j] < e9[j]) or E.pin_bar(b, j, -1)
                if touch and bear and e9[j] <= e9[j - 3]:
                    out.append(sig(b, j, -1, float(b.h[j]), "AO03_EMA9_PULLBACK_SHORT", entry_stop=float(b.l[j]) - 1.0,
                                   expire_k=exp))
    return out


def ao03_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ US-01 CCI (200) above 100 with a Supertrend (10, 2) trailing stop, 150 points (Bank Nifty five minutes, long) ═════

def _us01_arr(m, B, cache):
    def calc():
        line, dirn = ctx(m, B, 5, cache).supertrend(10, 2.0)
        return _cci(B[5], 200), line, dirn
    return _cached(cache, ("ze_us01",), calc)


def us01(m, B, p, cache):
    b = B[5]
    cci, line, dirn = _us01_arr(m, B, cache)
    out = []
    for j in range(201, len(b.c) - 1):
        t = int(b.ist0[j])
        if not (T(9, 30) <= t < T(14, 30)) or b.day[j + 1] != b.day[j] or not _fin(cci[j], cci[j - 1], line[j]):
            continue
        if cci[j] > 100 and dirn[j] > 0 and (cci[j - 1] <= 100 or dirn[j - 1] < 0):
            out.append(sig(b, j, 1, float(line[j]), "US01_CCI200_SUPERTREND_LONG"))
    return out


def us01_x(m, B, p, cache):
    b = B[5]
    _, line, dirn = _us01_arr(m, B, cache)
    lv = np.where(dirn > 0, line, np.nan)
    return XExits(target_r=None, target_abs=150.0, trail=("level", b, lv, np.full(len(lv), np.nan)))


# ═══ CD-01 05:30 IST VWAP reclaim: 20 EMA vs VWAP side, engulfing or star at the VWAP, pattern stop, 2R (BTC 15 min) ═

def _star(b, j, side):
    """Morning star (side +1) / evening star (side -1) ending at bar j."""
    if j < 2:
        return False
    b2 = abs(float(b.c[j - 2] - b.o[j - 2]))
    b1 = abs(float(b.c[j - 1] - b.o[j - 1]))
    mid = (float(b.o[j - 2]) + float(b.c[j - 2])) / 2
    if not b2 > 0 or b1 > 0.3 * b2:
        return False
    if side > 0:
        return b.c[j - 2] < b.o[j - 2] and b.c[j] > b.o[j] and b.c[j] > mid
    return b.c[j - 2] > b.o[j - 2] and b.c[j] < b.o[j] and b.c[j] < mid


def cd01(m, B, p, cache):
    b = B[15]
    vw = Z.vwap_of(m, b, cache, "15")
    e20 = ctx(m, B, 15, cache).ema(20)
    out = []
    for j in range(25, len(b.c) - 1):
        if b.day[j + 1] != b.day[j] or not _fin(vw[j], e20[j]):
            continue
        for side in (1, -1):
            if (e20[j] > vw[j]) != (side > 0):
                continue
            eng, star = E.engulf(b, j, side), _star(b, j, side)
            if not (eng or star):
                continue
            k0 = j - (2 if star and not eng else 1)
            if side > 0:
                lo = float(b.l[k0:j + 1].min())
                if lo <= vw[j] * 1.0015 and b.c[j] > vw[j]:
                    out.append(sig(b, j, 1, lo * (1 - 0.0005), "CD01_VWAP_RECLAIM_LONG"))
            else:
                hi = float(b.h[k0:j + 1].max())
                if hi >= vw[j] * (1 - 0.0015) and b.c[j] < vw[j]:
                    out.append(sig(b, j, -1, hi * (1 + 0.0005), "CD01_VWAP_REJECT_SHORT"))
    return out


def cd01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ CD-02 200 EMA side and slope, pullback touching the EMA, engulfing close, 2R (gold one minute, Asia session) ═════

def cd02(m, B, p, cache):
    b = B[1]
    e = ctx(m, B, 1, cache).ema(200)
    out = []
    for j in range(220, len(b.c) - 1):
        if b.day[j + 1] != b.day[j] or not _fin(e[j], e[j - 15]) or not (0 <= E.utc_min(b, j) < 8 * 60 + 25):
            continue
        if b.c[j] < e[j] and e[j] < e[j - 15] and E.engulf(b, j, -1):
            if bool((b.h[j - 3:j] >= e[j - 3:j] * (1 - 0.0002)).any()):
                out.append(sig(b, j, -1, float(b.h[j - 3:j + 1].max()) * (1 + 0.0002), "CD02_EMA200_PULLBACK_SHORT"))
        elif b.c[j] > e[j] and e[j] > e[j - 15] and E.engulf(b, j, 1):
            if bool((b.l[j - 3:j] <= e[j - 3:j] * (1 + 0.0002)).any()):
                out.append(sig(b, j, 1, float(b.l[j - 3:j + 1].min()) * (1 - 0.0002), "CD02_EMA200_PULLBACK_LONG"))
    return out


def cd02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ DE-10 session VWAP bounce, rejection and break-and-retest on five minutes, no flat VWAP (BTC) ════════════════════

def de10(m, B, p, cache):
    b = B[5]
    vw = Z.vwap_of(m, b, cache, "5")
    n = len(b.c)
    with np.errstate(invalid="ignore"):
        above = np.asarray(b.c > vw, int)
        below = np.asarray(b.c < vw, int)
    out = []
    armed = {}                                       # side -> (break bar, day)
    for j in range(60, n - 1):
        if b.day[j + 1] != b.day[j] or not _fin(vw[j], vw[j - 12]):
            continue
        if abs(vw[j] - vw[j - 12]) < 0.001 * vw[j]:
            continue
        c, o, h, l = float(b.c[j]), float(b.o[j]), float(b.h[j]), float(b.l[j])
        rg = h - l
        # a break: the first close on the other side after at least 6 closes on one side (not after > 48 of them)
        if above[j] and below[j - 6:j].all() and below[j - 48:j].sum() < 48:
            armed[1] = (j, int(b.day[j]))
        if below[j] and above[j - 6:j].all() and above[j - 48:j].sum() < 48:
            armed[-1] = (j, int(b.day[j]))
        for side in (1, -1):
            x = armed.get(side)
            if x is None or x[1] != int(b.day[j]) or not (x[0] < j <= x[0] + 12):
                continue
            seg = above[x[0]:j] if side > 0 else below[x[0]:j]
            if not seg.all():
                armed.pop(side, None)
                continue
            if side > 0 and l <= vw[j] < c:
                out.append(sig(b, j, 1, min(vw[j], l) * (1 - 0.0005), "DE10_BREAK_RETEST_LONG"))
                armed.pop(side, None)
            elif side < 0 and h >= vw[j] > c:
                out.append(sig(b, j, -1, max(vw[j], h) * (1 + 0.0005), "DE10_BREAK_RETEST_SHORT"))
                armed.pop(side, None)
        if rg > 0 and below[j - 6:j].all() and h >= vw[j] > c and (h - max(o, c)) >= 0.5 * rg:
            out.append(sig(b, j, -1, h * (1 + 0.0005), "DE10_REJECT_SHORT"))
        elif rg > 0 and above[j - 6:j].all() and l <= vw[j] < c and (min(o, c) - l) >= 0.5 * rg:
            out.append(sig(b, j, 1, l * (1 - 0.0005), "DE10_BOUNCE_LONG"))
    return out


def de10_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ KT-02 VWAP pullback on the lowest volume after a run away from it, break of that candle (NSE stocks) ═════════════

def kt02(m, B, p, cache):
    b = B[5]
    vw = Z.vwap_of(m, b, cache, "5")
    cx = ctx(m, B, 5, cache)
    vol, a = cx.vol(), cx.atr(14)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ist0[js[0]]) != T(9, 15):
            continue
        last_lo = last_hi = js[0] - 1                 # last bar touching the VWAP from above / below
        for i, j in enumerate(js):
            if not _fin(vw[j], a[j]):
                continue
            t = int(b.ist0[j])
            ok_t = (T(9, 30) <= t < T(11, 30)) or (T(13, 45) <= t < T(14, 45))
            if ok_t and i >= 6:
                exp = int(b.i1[j]) + 3
                lowest_vol = vol[j] <= vol[js[i - 5]:j + 1].min()
                run_hi = float(b.h[last_lo + 1:j].max()) if j - last_lo > 1 else -np.inf
                run_lo = float(b.l[last_hi + 1:j].min()) if j - last_hi > 1 else np.inf
                if lowest_vol and run_hi >= vw[j] + 1.5 * a[j] and b.l[j] <= vw[j] * 1.002 and b.c[j] > vw[j]:
                    out.append(sig(b, j, 1, float(vw[j]) * (1 - 0.001), "KT02_VWAP_PULLBACK_LONG",
                                   entry_stop=float(b.h[j]) + 0.05, expire_k=exp))
                elif lowest_vol and run_lo <= vw[j] - 1.5 * a[j] and b.h[j] >= vw[j] * 0.998 and b.c[j] < vw[j]:
                    out.append(sig(b, j, -1, float(vw[j]) * (1 + 0.001), "KT02_VWAP_PULLBACK_SHORT",
                                   entry_stop=float(b.l[j]) - 0.05, expire_k=exp))
            if b.l[j] <= vw[j]:
                last_lo = j
            if b.h[j] >= vw[j]:
                last_hi = j
    return out


def kt02_x(m, B, p, cache):
    b = B[5]
    lo, hi = _cached(cache, ("ze_swing2_5",), lambda: _swing_levels(b, 2))
    return XExits(target_r=None, partial_at_r=1.0, trail=("level", b, lo, hi))


# ═══ KS-02 EMA 10 / EMA 13 cross on 15 minutes, stop and reverse (index) ══════════════════════════════════════════════

def ks02(m, B, p, cache):
    b = B[15]
    cx = ctx(m, B, 15, cache)
    up, dn = flags_cross(cx.ema(10), cx.ema(13))
    a = cx.atr(14)
    out = []
    for j in range(20, len(b.c)):
        if not (up[j] or dn[j]) or not np.isfinite(a[j]) or not (T(9, 30) <= int(b.ist0[j]) < T(15, 0)):
            continue
        s = 1 if up[j] else -1
        out.append(sig(b, j, s, float(b.c[j] - s * a[j]), "KS02_EMA10_13_LONG" if s > 0 else "KS02_EMA10_13_SHORT",
                       info={"stop_dist": float(a[j])}))
    return out


def ks02_x(m, B, p, cache):
    cx = ctx(m, B, 15, cache)
    up, dn = flags_cross(cx.ema(10), cx.ema(13))
    return XExits(target_r=None, xbars=B[15], xlong=dn, xshort=up)


# ═══ VV-01 Heikin Ashi doji, then an open = high (low) candle, break of its low (high), 0.25% stop, HA trail ═══════════

def _vv01_arr(B, cache):
    return _cached(cache, ("ze_vv01",), lambda: I.ha_ohlc(B[15]))


def vv01(m, B, p, cache):
    b = B[15]
    ho, hh, hl, hc = _vv01_arr(B, cache)
    out = []
    for j in range(2, len(b.c) - 1):
        t = int(b.ist0[j])
        if not (T(9, 15) <= t < T(14, 45)) or b.day[j + 1] != b.day[j] or b.day[j - 1] != b.day[j]:
            continue
        r1 = float(hh[j - 1] - hl[j - 1])
        doji = r1 > 0 and abs(float(hc[j - 1] - ho[j - 1])) <= 0.1 * r1
        if not doji:
            continue
        exp = int(b.i1[j + 1])
        if ho[j] >= hh[j] - 1e-9 and hc[j] < ho[j]:
            out.append(sig(b, j, -1, float(hl[j]) * 1.0025, "VV01_HA_DOJI_OPEN_HIGH_SHORT",
                           entry_stop=float(hl[j]) - 1.0, expire_k=exp, info={"stop_frac": 0.0025}))
        elif ho[j] <= hl[j] + 1e-9 and hc[j] > ho[j]:
            out.append(sig(b, j, 1, float(hh[j]) * 0.9975, "VV01_HA_DOJI_OPEN_LOW_LONG",
                           entry_stop=float(hh[j]) + 1.0, expire_k=exp, info={"stop_frac": 0.0025}))
    return out


def vv01_x(m, B, p, cache):
    b = B[15]
    ho, hh, hl, hc = _vv01_arr(B, cache)
    return XExits(target_r=None, trail=("level", b, np.asarray(hl, float), np.asarray(hh, float)), xbars=b,
                  xlong=hc < ho, xshort=hc > ho)


# ═══ VV-02 09:15 five-minute candle on the VWAP side, VWAP crosses with a follow-up candle, Supertrend agreement, 1:1 ═

def _vv02_dist(m):
    return 150.0 if m.name == "BANKNIFTY" else 60.0


def vv02(m, B, p, cache):
    b = B[5]
    vw = Z.vwap_of(m, b, cache, "5")
    _, dirn = ctx(m, B, 5, cache).supertrend(10, 3.0)
    dist = _vv02_dist(m)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ist0[js[0]]) != T(9, 15):
            continue
        j0 = js[0]
        exp = int(b.i1[j0]) + 55                      # the 10:14 row (one-minute index rows)
        if np.isfinite(vw[j0]):
            if b.c[j0] > vw[j0] and dirn[j0] > 0:
                out.append(sig(b, j0, 1, float(b.h[j0]) - dist, "VV02_FIRST_CANDLE_LONG", entry_stop=float(b.h[j0]),
                               expire_k=exp, info={"stop_dist": dist}))
            elif b.c[j0] < vw[j0] and dirn[j0] < 0:
                out.append(sig(b, j0, -1, float(b.l[j0]) + dist, "VV02_FIRST_CANDLE_SHORT", entry_stop=float(b.l[j0]),
                               expire_k=exp, info={"stop_dist": dist}))
        for i in range(2, len(js)):
            tr, j = js[i - 1], js[i]                  # the trigger candle, then the follow-up candle
            t = int(b.ist0[j])
            if not (T(9, 30) <= t < T(14, 30)) or not _fin(vw[tr], vw[js[i - 2]]):
                continue
            if b.c[js[i - 2]] <= vw[js[i - 2]] and b.c[tr] > vw[tr] and dirn[j] > 0 and b.c[j] > b.h[tr]:
                out.append(sig(b, j, 1, float(b.c[j]) - dist, "VV02_VWAP_CROSS_LONG", info={"stop_dist": dist}))
            elif b.c[js[i - 2]] >= vw[js[i - 2]] and b.c[tr] < vw[tr] and dirn[j] < 0 and b.c[j] < b.l[tr]:
                out.append(sig(b, j, -1, float(b.c[j]) + dist, "VV02_VWAP_CROSS_SHORT", info={"stop_dist": dist}))
    return sorted_out(out)


def vv02_x(m, B, p, cache):
    return XExits(target_r=None, target_abs=_vv02_dist(m))


# ═══ BJ-01 5 EMA vs 200 EMA side, the cross and each close back over the 5 EMA of lows (highs) with RSI 40-50 ═════════

def _bj01_arr(m, B, cache):
    def calc():
        b = B[15]
        c, h, l = (np.asarray(x, float) for x in (b.c, b.h, b.l))
        e5, e200, e5l, e5h = I.ema(c, 5), I.ema(c, 200), I.ema(l, 5), I.ema(h, 5)
        r = I.rsi(c, 14)
        n = len(c)
        lv_l = np.full(n, np.nan)
        lv_s = np.full(n, np.nan)
        sig_l, sig_s = [], []                         # (bar, stop)
        cur_l = cur_s = np.nan
        start_l = start_s = None
        for j in range(1, n):
            if c[j] < e5l[j]:
                start_l = j if start_l is None else start_l
            elif start_l is not None:                 # the pullback under the 5 EMA of lows ended at bar j
                seg = slice(start_l, j)
                if np.isfinite(r[seg]).all() and 40 <= float(r[seg].min()) <= 50 and e5[j] > e200[j]:
                    sig_l.append((j, float(l[start_l:j + 1].min())))
                cur_l, start_l = float(l[start_l:j + 1].min()), None
            if c[j] > e5h[j]:
                start_s = j if start_s is None else start_s
            elif start_s is not None:
                seg = slice(start_s, j)
                if np.isfinite(r[seg]).all() and 50 <= float(r[seg].max()) <= 60 and e5[j] < e200[j]:
                    sig_s.append((j, float(h[start_s:j + 1].max())))
                cur_s, start_s = float(h[start_s:j + 1].max()), None
            lv_l[j], lv_s[j] = cur_l, cur_s
        up, dn = flags_cross(e5, e200)
        return e200, up, dn, sig_l, sig_s, lv_l, lv_s
    return _cached(cache, ("ze_bj01",), calc)


def bj01(m, B, p, cache):
    b = B[15]
    e200, up, dn, sig_l, sig_s, _, _ = _bj01_arr(m, B, cache)
    n = len(b.c)

    def ok(j):
        return 205 <= j < n - 1 and T(9, 30) <= int(b.ist0[j]) < T(14, 45) and b.day[j + 1] == b.day[j]
    out = []
    for j in np.flatnonzero(up):
        if ok(j):
            out.append(sig(b, j, 1, float(e200[j]) * (1 - 0.002), "BJ01_EMA5_200_CROSS_LONG"))
    for j in np.flatnonzero(dn):
        if ok(j):
            out.append(sig(b, j, -1, float(e200[j]) * (1 + 0.002), "BJ01_EMA5_200_CROSS_SHORT"))
    for j, stop in sig_l:
        if ok(j):
            out.append(sig(b, j, 1, stop, "BJ01_EMA5_LOW_PULLBACK_LONG"))
    for j, stop in sig_s:
        if ok(j):
            out.append(sig(b, j, -1, stop, "BJ01_EMA5_HIGH_PULLBACK_SHORT"))
    return sorted_out(out)


def bj01_x(m, B, p, cache):
    _, _, _, _, _, lv_l, lv_s = _bj01_arr(m, B, cache)
    return XExits(target_r=None, trail=("level", B[15], lv_l, lv_s))


# ═══ BJ-02 one-hour middle-band side, 15-minute band pullback, five-minute strong close over the middle band (NSE) ════

def bj02(m, B, p, cache):
    b, b15, b60 = B[5], B[15], B[60]
    mid5 = YI.bollinger(np.asarray(b.c, float), 20, 2.0)[0]
    mid15, up15, lo15 = YI.bollinger(np.asarray(b15.c, float), 20, 2.0)
    mid60 = YI.bollinger(np.asarray(b60.c, float), 20, 2.0)[0]
    cx = ctx(m, B, 5, cache)
    vol, a = cx.vol().astype(float), cx.atr(14)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ist0[js[0]]) != T(9, 15):
            continue
        for j in js:
            t = int(b.ist0[j])
            if not (T(9, 30) <= t < T(14, 30)) or j < 25:
                continue
            k60, k15 = _last_done(b60, b, j), _last_done(b15, b, j)
            if k60 < 0 or k15 < 4 or not _fin(mid5[j], mid60[k60], mid15[k15], a[j]):
                continue
            rg = float(b.h[j] - b.l[j])
            if not rg > 0 or vol[j] < 1.5 * float(vol[j - 20:j].mean()):
                continue
            w = slice(k15 - 3, k15 + 1)
            if b60.c[k60] > mid60[k60] and b.c[j] > mid5[j] and b.c[j] > b.o[j] and (b.c[j] - b.l[j]) >= 0.9 * rg:
                near = bool(((b15.l[w] <= mid15[w] * 1.002) | (b15.l[w] <= lo15[w] * 1.002)).any())
                if near and not bool((b15.c[w] < lo15[w]).any()):
                    out.append(sig(b, j, 1, float(b.c[j] - 1.5 * a[j]), "BJ02_BB_MTF_LONG",
                                   info={"stop_dist": float(1.5 * a[j])}))
            elif b60.c[k60] < mid60[k60] and b.c[j] < mid5[j] and b.c[j] < b.o[j] and (b.h[j] - b.c[j]) >= 0.9 * rg:
                near = bool(((b15.h[w] >= mid15[w] * 0.998) | (b15.h[w] >= up15[w] * 0.998)).any())
                if near and not bool((b15.c[w] > up15[w]).any()):
                    out.append(sig(b, j, -1, float(b.c[j] + 1.5 * a[j]), "BJ02_BB_MTF_SHORT",
                                   info={"stop_dist": float(1.5 * a[j])}))
    return out


def bj02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ US-02 pivot levels of each 15-minute candle: below its pivot sell at R1 (stop R2, target S1), mirror for buys ════

def us02(m, B, p, cache):
    b = B[15]
    out = []
    for j in range(1, len(b.c) - 1):
        t = int(b.ist0[j])
        if not (T(9, 15) <= t < T(14, 30)) or b.day[j + 1] != b.day[j]:
            continue
        pv = E.floor_pivots(float(b.h[j]), float(b.l[j]), float(b.c[j]))
        exp = int(b.i1[j + 1])
        if b.c[j] < pv["P"] and pv["R2"] > pv["R1"] > pv["S1"]:
            out.append(sig(b, j, -1, pv["R2"], "US02_CANDLE_PIVOT_R1_SHORT", entry_limit=pv["R1"], expire_k=exp,
                           target_px=pv["S1"]))
        elif b.c[j] > pv["P"] and pv["S2"] < pv["S1"] < pv["R1"]:
            out.append(sig(b, j, 1, pv["S2"], "US02_CANDLE_PIVOT_S1_LONG", entry_limit=pv["S1"], expire_k=exp,
                           target_px=pv["R1"]))
    return out


def us02_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ RT-01 above the 200-day MA, close below the lower Bollinger Band (20, 2.5), buy limit 3% lower (NSE daily, long) ══

def rt01(m, B, p, cache):
    b = B[1]
    c = np.asarray(b.c, float)
    s200 = I.sma(c, 200)
    lo = YI.bollinger(c, 20, 2.5)[2]
    out = []
    for j in range(200, len(c)):
        if _fin(s200[j], lo[j]) and c[j] > s200[j] and c[j] < lo[j]:
            px = 0.97 * float(c[j])
            out.append(sig(b, j, 1, px * 0.85, "RT01_BB_PULLBACK_LONG", entry_limit=px, expire_k=int(b.i1[j]) + 1))
    return out


def rt01_x(m, B, p, cache):
    b = B[1]
    r2 = I.rsi(np.asarray(b.c, float), 2)
    rp = np.r_[np.nan, r2[:-1]]
    with np.errstate(invalid="ignore"):
        x = (r2 > 50) & (rp <= 50)
    return XExits(target_r=None, xbars=b, xlong=x, xshort=np.zeros(len(x), bool), max_hold=10)
