"""Sixth batch of the channel-shortlist study (14 Nov 2026): the cards of the owner's ten extra crypto channels
(cards/<video>.txt; the 'A' rules are this code). Same conventions as ze_more4: BTCUSD and ETHUSD are Delta Exchange
perpetuals on the UTC day (real volume), XAUUSD is gold booked on Delta XAUTUSD (the 17:00 New York day).

Every signal uses only the bars up to its own signal bar; recursive indicators (EMAs, the SSL state, the Chandelier
Exit) only ever move forward, so a later bar never changes an earlier value."""

from __future__ import annotations

import numpy as np

import yc_ind as I
import ze_common as E
from yc_common import ctx, sig
from yc_engine import XExits
from ze_more2 import _last_done
from ze_more4 import TICK, _cached, _fin


# ── indicators ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _ssl(b, n=10):
    """SSL Channel trend: +1 after a close above the n-bar SMA of highs, -1 after a close below the SMA of lows."""
    hi, lo = I.sma(np.asarray(b.h, float), n), I.sma(np.asarray(b.l, float), n)
    c = np.asarray(b.c, float)
    out = np.zeros(len(c), np.int64)
    s = 0
    for j in range(len(c)):
        if np.isfinite(hi[j]) and c[j] > hi[j]:
            s = 1
        elif np.isfinite(lo[j]) and c[j] < lo[j]:
            s = -1
        out[j] = s
    return out


def _tdfi(c, lookback=13, mma_len=13, smma_len=13, n=3):
    """Trend Direction Force Index (TradingView TDFI defaults): signal in [-1, 1]; above 0.05 green, below -0.05 red."""
    price = np.asarray(c, float) * 1000.0
    mma = I.ema(price, mma_len)
    smma = I.ema(mma, smma_len)
    imp_m = np.r_[0.0, np.diff(mma)]
    imp_s = np.r_[0.0, np.diff(smma)]
    tdf = np.abs(mma - smma) * ((imp_m + imp_s) / 2.0) ** n
    top = I.highest(np.abs(tdf), lookback * n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(top > 0, tdf / top, 0.0)


def _hma(x, n):
    """Hull MA as Pine plots it: WMA(2 WMA(n/2) - WMA(n), floor(sqrt(n)))."""
    x = np.asarray(x, float)
    raw = 2 * E.wma(x, n // 2) - E.wma(x, n)
    out = np.full(len(x), np.nan)
    ok = np.flatnonzero(np.isfinite(raw))
    if len(ok):
        out[ok[0]:] = E.wma(raw[ok[0]:], int(np.floor(np.sqrt(n))))
    return out


def _t3(x, n=300, a=0.7):
    """Tillson T3 (six cascaded EMAs)."""
    e1 = I.ema(np.asarray(x, float), n)
    e2 = I.ema(e1, n)
    e3 = I.ema(e2, n)
    e4 = I.ema(e3, n)
    e5 = I.ema(e4, n)
    e6 = I.ema(e5, n)
    c1, c2 = -a ** 3, 3 * a ** 2 + 3 * a ** 3
    c3, c4 = -6 * a ** 2 - 3 * a - 3 * a ** 3, 1 + 3 * a + a ** 3 + 3 * a ** 2
    return c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3


def _cmf(b, vol, n=20):
    rng = np.asarray(b.h - b.l, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        mfm = np.where(rng > 0, ((b.c - b.l) - (b.h - b.c)) / rng, 0.0)
    cs = lambda x: np.cumsum(np.r_[0.0, x])  # noqa: E731
    a, v = cs(mfm * vol), cs(np.asarray(vol, float))
    out = np.full(len(vol), np.nan)
    den = v[n:] - v[:-n]
    with np.errstate(invalid="ignore", divide="ignore"):
        out[n - 1:] = np.where(den > 0, (a[n:] - a[:-n]) / den, 0.0)
    return out


def _chandelier_flips(b, n=22, mult=2.0):
    """Chandelier Exit (everget, highs/lows): (turned short, turned long) flags per bar."""
    h, l, c = (np.asarray(x, float) for x in (b.h, b.l, b.c))
    atr = mult * I.atr(b, n)
    hh, ll = I.highest(h, n), I.lowest(l, n)
    N = len(c)
    dn = np.zeros(N, bool)
    up = np.zeros(N, bool)
    ls_prev = ss_prev = np.nan
    d = 1
    for j in range(N):
        if not (np.isfinite(atr[j]) and np.isfinite(hh[j]) and np.isfinite(ll[j])):
            continue
        ls, ss = hh[j] - atr[j], ll[j] + atr[j]
        if np.isfinite(ls_prev) and c[j - 1] > ls_prev:
            ls = max(ls, ls_prev)
        if np.isfinite(ss_prev) and c[j - 1] < ss_prev:
            ss = min(ss, ss_prev)
        nd = d
        if np.isfinite(ss_prev) and c[j] > ss_prev:
            nd = 1
        elif np.isfinite(ls_prev) and c[j] < ls_prev:
            nd = -1
        dn[j], up[j] = (nd == -1 and d == 1), (nd == 1 and d == -1)
        d, ls_prev, ss_prev = nd, ls, ss
    return dn, up


# ═══ DD-01 over-extended RSI: RSI (14) crossing above 70 with the SSL trend and the TDFI, 1% stop, half at 1%, rest 2% ═

def _dd01_arr(m, B, cache):
    def calc():
        b = B[15]
        r = ctx(m, B, 15, cache).rsi(14)
        return r, I.sma(r, 14), _ssl(b, 10), _tdfi(b.c)
    return _cached(cache, ("ze5_dd01",), calc)


def dd01(m, B, p, cache):
    b = B[15]
    r, ra, ssl, td = _dd01_arr(m, B, cache)
    out = []
    for j in range(40, len(b.c)):
        if not _fin(r[j], r[j - 1], ra[j], td[j]):
            continue
        c = float(b.c[j])
        if ssl[j] == 1 and r[j] > 70 >= r[j - 1] and r[j] > ra[j] and td[j] > 0.05:
            out.append(sig(b, j, 1, c * 0.99, "DD01_RSI_OVEREXTENDED_LONG", info={"stop_frac": 0.01}))
        elif ssl[j] == -1 and r[j] < 30 <= r[j - 1] and r[j] < ra[j] and td[j] < -0.05:
            out.append(sig(b, j, -1, c * 1.01, "DD01_RSI_OVEREXTENDED_SHORT", info={"stop_frac": 0.01}))
    return out


def dd01_x(m, B, p, cache):
    return XExits(target_r=2.0, partial_at_r=1.0, partial_be=False)


# ═══ DD-02 EMA 50/200 trend, a larger-than-average 1-minute MACD histogram pullback, 0.7% / 0.7%, VWAP side ═════════

def _dd02_arr(m, B, cache):
    def calc():
        b1 = B[1]
        c1 = np.asarray(b1.c, float)
        macd = I.ema(c1, 12) - I.ema(c1, 26)
        hist = macd - I.ema(macd, 9)
        avg = I.mean_prev(np.abs(hist), 100)
        # session VWAP of the UTC day at each 1-minute bar's close (typical price x volume of the rows)
        tp = (np.asarray(m.h, float) + np.asarray(m.l, float) + np.asarray(m.c, float)) / 3.0
        vol = np.asarray(m.vol, float)
        cpv, cv = np.cumsum(tp * vol), np.cumsum(vol)
        k = np.asarray(b1.i1, np.int64)
        d0 = np.asarray(m.d0, np.int64)[np.asarray(b1.day, np.int64)]
        base_pv = np.where(d0 > 0, cpv[np.maximum(d0 - 1, 0)], 0.0)
        base_v = np.where(d0 > 0, cv[np.maximum(d0 - 1, 0)], 0.0)
        den = cv[k] - base_v
        with np.errstate(invalid="ignore", divide="ignore"):
            vwap = np.where(den > 0, (cpv[k] - base_pv) / den, np.nan)
        cx5 = ctx(m, B, 5, cache)
        return hist, avg, vwap, cx5.ema(50), cx5.ema(200)
    return _cached(cache, ("ze5_dd02",), calc)


def dd02(m, B, p, cache):
    b1, b5 = B[1], B[5]
    hist, avg, vwap, e50, e200 = _dd02_arr(m, B, cache)
    c = b1.c
    out = []
    cross_id, n_long, n_short, last_side = -1, 0, 0, 0
    for j in range(130, len(c)):
        k5 = _last_done(b5, b1, j)
        if k5 < 200 or not _fin(e50[k5], e200[k5], hist[j], hist[j - 1], avg[j], avg[j - 1], vwap[j]):
            continue
        side = 1 if e50[k5] > e200[k5] else -1
        if side != last_side:                          # a new EMA crossover: the five-signal count restarts
            cross_id, n_long, n_short, last_side = k5, 0, 0, side
        if side > 0 and n_long < 5 and hist[j] < -avg[j] and hist[j - 1] >= -avg[j - 1] and c[j] > vwap[j]:
            out.append(sig(b1, j, 1, float(c[j]) * 0.993, "DD02_EMA_TREND_MACD1M_PULLBACK_LONG",
                           info={"stop_frac": 0.007, "target_frac": 0.007}))
            n_long += 1
        elif side < 0 and n_short < 5 and hist[j] > avg[j] and hist[j - 1] <= avg[j - 1] and c[j] < vwap[j]:
            out.append(sig(b1, j, -1, float(c[j]) * 1.007, "DD02_EMA_TREND_MACD1M_PULLBACK_SHORT",
                           info={"stop_frac": 0.007, "target_frac": 0.007}))
            n_short += 1
    return out


def dd02_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ DD-03 Hull MA baseline cross with AO and CMF above zero, T3 (300) and TDFI filters, 3 ATR stop, 1.3R ═══════════

def _dd03_arr(m, B, cache):
    def calc():
        b = B[5]
        c = np.asarray(b.c, float)
        med = (np.asarray(b.h, float) + np.asarray(b.l, float)) / 2.0
        hma = _hma(c, 24)
        ao = I.sma(med, 5) - I.sma(med, 34)
        cmf = _cmf(b, ctx(m, B, 5, cache).vol(), 20)
        return hma, ao, cmf, _t3(c, 300, 0.7), _tdfi(c), ctx(m, B, 5, cache).atr(14)
    return _cached(cache, ("ze5_dd03",), calc)


def dd03(m, B, p, cache):
    b = B[5]
    hma, ao, cmf, t3, td, a14 = _dd03_arr(m, B, cache)
    c = b.c
    out = []
    for j in range(320, len(c)):
        if not _fin(hma[j], hma[j - 1], ao[j], cmf[j], t3[j], td[j], a14[j]):
            continue
        if c[j] > hma[j] and c[j - 1] <= hma[j - 1] and ao[j] > 0 and cmf[j] > 0 and c[j] > t3[j] and td[j] > 0.05:
            out.append(sig(b, j, 1, float(c[j] - 3 * a14[j]), "DD03_HMA_AO_CMF_LONG"))
        elif c[j] < hma[j] and c[j - 1] >= hma[j - 1] and ao[j] < 0 and cmf[j] < 0 and c[j] < t3[j] and td[j] < -0.05:
            out.append(sig(b, j, -1, float(c[j] + 3 * a14[j]), "DD03_HMA_AO_CMF_SHORT"))
    return out


def dd03_x(m, B, p, cache):
    b = B[5]
    hma = _dd03_arr(m, B, cache)[0]
    fin = np.isfinite(hma)
    h0, h1, h2 = hma, np.r_[np.nan, hma[:-1]], np.r_[np.nan, np.nan, hma[:-2]]
    ok = fin & np.isfinite(h1) & np.isfinite(h2)
    turn_dn = ok & (np.where(ok, h0, 0) < np.where(ok, h1, 0)) & (np.where(ok, h1, 0) >= np.where(ok, h2, 0))
    turn_up = ok & (np.where(ok, h0, 0) > np.where(ok, h1, 0)) & (np.where(ok, h1, 0) <= np.where(ok, h2, 0))
    return XExits(target_r=1.3, xbars=b, xlong=turn_dn, xshort=turn_up)


# ═══ DD-04 Bollinger 1-2-3: above the upper band, below the lower band, rejected at the middle, break of the 1-3 line ═

def dd04(m, B, p, cache):
    b = B[15]
    mid, up, lo = ctx(m, B, 15, cache).bollinger(20, 2.0)
    h, l, c = b.h, b.l, b.c
    out = []
    L = {"st": 0}                                      # long setup: 1 above the upper band, 2 lower band broken, 4 rejected
    S = {"st": 0}
    for j in range(21, len(c)):
        if not _fin(mid[j], up[j], lo[j]):
            continue
        # ── long: point 1 above the upper band, point 2 under the lower band, point 3 a rejection at the middle band
        st = L["st"]
        if st == 4:
            if l[j] < L["p2"]:
                L = {"st": 0}
            else:
                line = L["p3"] + (L["p3"] - L["p1"]) / (L["t3"] - L["t1"]) * (j - L["t3"])
                if c[j] > line:
                    out.append(sig(b, j, 1, L["p2"] * (1 - TICK), "DD04_BB123_TRENDLINE_BREAK_LONG"))
                    L = {"st": 0}
                elif j >= L["t3"] + 40:
                    L = {"st": 0}
        elif st == 3:
            L["p2"] = min(L["p2"], float(l[j]))
            if c[j] > mid[j]:
                L = {"st": 0}
            elif h[j] >= mid[j] * 0.999:
                L.update(st=4, p3=float(h[j]), t3=j)
        elif st == 2:
            if h[j] > up[j]:
                L = {"st": 1, "p1": float(h[j]), "t1": j}
            elif l[j] < lo[j]:
                L.update(st=3, p2=float(l[j]))
        elif st == 1:
            if h[j] > L["p1"] and c[j] >= mid[j]:
                L.update(p1=float(h[j]), t1=j)
            if c[j] < mid[j]:
                L["st"] = 2
                if l[j] < lo[j]:                       # the same bar may already break the lower band
                    L.update(st=3, p2=float(l[j]))
        if L["st"] == 0 and h[j] > up[j]:
            L = {"st": 1, "p1": float(h[j]), "t1": j}
        # ── short: the mirror
        st = S["st"]
        if st == 4:
            if h[j] > S["p2"]:
                S = {"st": 0}
            else:
                line = S["p3"] + (S["p3"] - S["p1"]) / (S["t3"] - S["t1"]) * (j - S["t3"])
                if c[j] < line:
                    out.append(sig(b, j, -1, S["p2"] * (1 + TICK), "DD04_BB123_TRENDLINE_BREAK_SHORT"))
                    S = {"st": 0}
                elif j >= S["t3"] + 40:
                    S = {"st": 0}
        elif st == 3:
            S["p2"] = max(S["p2"], float(h[j]))
            if c[j] < mid[j]:
                S = {"st": 0}
            elif l[j] <= mid[j] * 1.001:
                S.update(st=4, p3=float(l[j]), t3=j)
        elif st == 2:
            if l[j] < lo[j]:
                S = {"st": 1, "p1": float(l[j]), "t1": j}
            elif h[j] > up[j]:
                S.update(st=3, p2=float(h[j]))
        elif st == 1:
            if l[j] < S["p1"] and c[j] <= mid[j]:
                S.update(p1=float(l[j]), t1=j)
            if c[j] > mid[j]:
                S["st"] = 2
                if h[j] > up[j]:
                    S.update(st=3, p2=float(h[j]))
        if S["st"] == 0 and l[j] < lo[j]:
            S = {"st": 1, "p1": float(l[j]), "t1": j}
    return out


def dd04_x(m, B, p, cache):
    return XExits(target_r=1.5)


# ═══ TL-06 range breakout confirmed by a momentum candle, stop past the level, half at 1.5R, rest on the Chandelier ═══

def _tl06_ranges(m, B, cache):
    """Per 15-minute bar: (valid range, range high, range low) of the 30 bars before it."""
    def calc():
        b = B[15]
        h, l = np.asarray(b.h, float), np.asarray(b.l, float)
        a14 = ctx(m, B, 15, cache).atr(14)
        N = len(h)
        ok = np.zeros(N, bool)
        rh = np.full(N, np.nan)
        rl = np.full(N, np.nan)
        for j in range(31, N):
            hh, ll = h[j - 30:j], l[j - 30:j]
            top, bot = float(hh.max()), float(ll.min())
            rh[j], rl[j] = top, bot
            ht = top - bot
            if not (ht > 0 and np.isfinite(a14[j - 1]) and ht <= 4 * a14[j - 1]):
                continue
            th = np.flatnonzero(hh >= top - 0.1 * ht)
            tl = np.flatnonzero(ll <= bot + 0.1 * ht)
            ok[j] = len(th) >= 2 and th[-1] - th[0] >= 3 and len(tl) >= 2 and tl[-1] - tl[0] >= 3
        return ok, rh, rl
    return _cached(cache, ("ze5_tl06",), calc)


def tl06(m, B, p, cache):
    b = B[15]
    ok, rh, rl = _tl06_ranges(m, B, cache)
    bav = ctx(m, B, 15, cache).body_avg(20)
    o, c = b.o, b.c
    out = []
    for j in range(34, len(c)):
        body = float(c[j] - o[j])
        # one big candle mostly beyond the level
        if ok[j] and np.isfinite(bav[j]) and abs(body) >= 1.5 * bav[j]:
            if body > 0 and c[j] > rh[j] and c[j] - max(o[j], rh[j]) >= 0.5 * body:
                out.append(sig(b, j, 1, rh[j] * (1 - TICK), "TL06_MOMENTUM_BREAKOUT_LONG"))
                continue
            if body < 0 and c[j] < rl[j] and min(o[j], rl[j]) - c[j] >= 0.5 * -body:
                out.append(sig(b, j, -1, rl[j] * (1 + TICK), "TL06_MOMENTUM_BREAKOUT_SHORT"))
                continue
        # three candles: the first close beyond the level, then two more the same colour, all beyond it
        k = j - 2
        if ok[k] and c[k - 1] <= rh[k] < c[k] and all(c[i] > o[i] and c[i] > rh[k] for i in (k, k + 1, j)):
            out.append(sig(b, j, 1, rh[k] * (1 - TICK), "TL06_THREE_CANDLE_BREAKOUT_LONG"))
        elif ok[k] and c[k - 1] >= rl[k] > c[k] and all(c[i] < o[i] and c[i] < rl[k] for i in (k, k + 1, j)):
            out.append(sig(b, j, -1, rl[k] * (1 + TICK), "TL06_THREE_CANDLE_BREAKOUT_SHORT"))
    return out


def tl06_x(m, B, p, cache):
    b = B[15]
    dn, up = _cached(cache, ("ze5_tl06_ce",), lambda: _chandelier_flips(b, 22, 2.0))
    return XExits(target_r=None, partial_at_r=1.5, partial_be=False, lock_at_r=1.5, lock_to_r=1.5,
                  xbars=b, xlong=dn, xshort=up, x_from_r=1.5)
