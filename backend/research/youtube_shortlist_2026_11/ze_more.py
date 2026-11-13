"""Second batch of the channel-shortlist study (13 Nov 2026): the cards read after the first deploy (cards/<video>.txt;
the 'A' rules are this code). Same markets and conventions as ze_india / ze_global: NIFTY / BANKNIFTY one-minute index
rows from 09:15 (placeholder volume: their VWAP is time-weighted), NSE5 / NSE15 stock pools (real volume), NSED daily
bars (long only, overnight), BTCUSD (the UTC day, out at 23:55 UTC), XAUUSD (gold; booked on Delta XAUTUSD), EURUSD /
GBPUSD (placeholder volume) and NAS100 (the 09:30-16:00 New York cash session, placeholder volume)."""

from __future__ import annotations

import numpy as np

import yc_ind as I
import yt_ind as YI
from yc_common import bars_of_day, ctx, flags_cross, sig
from yc_engine import XExits

import zd_common as Z
import ze_common as E
from ze_common import T, sorted_out


def _days(b, d):
    return list(bars_of_day(b, d))


def _fin(*xs) -> bool:
    return all(np.isfinite(x) for x in xs)


def _cached(cache, key, fn):
    if key not in cache:
        cache[key] = fn()
    return cache[key]


def _run_side(o, c, vw, n: int):
    """(all of the last n bodies above the VWAP, all below), the current bar included."""
    with np.errstate(invalid="ignore"):
        above = (np.minimum(o, c) > vw).astype(int)
        below = (np.maximum(o, c) < vw).astype(int)
    k = np.ones(n, int)
    return np.convolve(above, k)[:len(above)] >= n, np.convolve(below, k)[:len(below)] >= n


def _vwap_sd(m, b, cache, name):
    """Session VWAP and its standard deviation per bar close (volume-weighted; time-weighted on placeholder volume)."""
    def calc():
        tp = (m.h + m.l + m.c) / 3.0
        v = np.asarray(m.vol, float)
        mu = np.full(len(tp), np.nan)
        sd = np.full(len(tp), np.nan)
        for d in range(m.n_days):
            a, z = int(m.d0[d]), int(m.d1[d])
            if z <= a:
                continue
            cv = np.cumsum(v[a:z])
            cp = np.cumsum(tp[a:z] * v[a:z])
            c2 = np.cumsum(tp[a:z] ** 2 * v[a:z])
            with np.errstate(invalid="ignore", divide="ignore"):
                u = cp / cv
                mu[a:z] = u
                sd[a:z] = np.sqrt(np.maximum(c2 / cv - u * u, 0.0))
        return mu[b.i1], sd[b.i1]
    return _cached(cache, ("ze_vwsd", name), calc)


# ═══ MC-01 Supertrend (7, 3) stop and reverse on 5 minutes (Nifty, Bank Nifty) ═══════════════════════════════════════

def mc01(m, B, p, cache):
    b = B[5]
    line, dirn = ctx(m, B, 5, cache).supertrend(7, 3.0)
    out = []
    for j in range(1, len(b.c)):
        if not (T(9, 30) <= int(b.ist0[j]) < T(15, 0)) or not np.isfinite(line[j]):
            continue
        if dirn[j] != 0 and dirn[j] != dirn[j - 1]:
            s = int(np.sign(dirn[j]))
            out.append(sig(b, j, s, float(line[j]), "MC01_ST_FLIP_LONG" if s > 0 else "MC01_ST_FLIP_SHORT"))
    return out


def mc01_x(m, B, p, cache):
    b = B[5]
    _, dirn = ctx(m, B, 5, cache).supertrend(7, 3.0)
    dn = np.r_[False, (dirn[1:] < 0) & (dirn[:-1] > 0)]
    up = np.r_[False, (dirn[1:] > 0) & (dirn[:-1] < 0)]
    return XExits(target_r=None, xbars=b, xlong=dn, xshort=up)


# ═══ MC-02 zero-lag EMA (20) vs EMA (20) cross on 15 minutes, stop and reverse (Nifty, Bank Nifty) ═══════════════════

def _mc02_lines(B, cache):
    def calc():
        c = np.asarray(B[15].c, float)
        return E.zlema(c, 20), E.ema(c, 20)
    return _cached(cache, ("ze_mc02",), calc)


def mc02(m, B, p, cache):
    b = B[15]
    zl, e = _mc02_lines(B, cache)
    up, dn = flags_cross(zl, e)
    a = ctx(m, B, 15, cache).atr(14)
    out = []
    for j in range(25, len(b.c)):
        if not (up[j] or dn[j]) or not np.isfinite(a[j]) or not (T(9, 30) <= int(b.ist0[j]) < T(15, 0)):
            continue
        s = 1 if up[j] else -1
        out.append(sig(b, j, s, float(b.c[j] - s * a[j]), "MC02_ZLEMA_CROSS_LONG" if s > 0 else "MC02_ZLEMA_CROSS_SHORT",
                       info={"stop_dist": float(a[j])}))
    return out


def mc02_x(m, B, p, cache):
    zl, e = _mc02_lines(B, cache)
    up, dn = flags_cross(zl, e)
    return XExits(target_r=None, xbars=B[15], xlong=dn, xshort=up)


# ═══ DE-09 Heikin Ashi candle entirely beyond the smoothed MA (5): stop entry at its far end, out on a colour turn ════

def _de09_arr(B, cache):
    def calc():
        ho, hh, hl, hc = I.ha_ohlc(B[5])
        return ho, hh, hl, hc, I.smma(np.asarray(hc, float), 5)
    return _cached(cache, ("ze_de09",), calc)


def de09(m, B, p, cache):
    b = B[5]
    ho, hh, hl, hc, sm = _de09_arr(B, cache)
    out = []
    for j in range(10, len(b.c) - 1):
        if not np.isfinite(sm[j]) or b.day[j + 1] != b.day[j]:
            continue
        exp = int(b.i1[j + 1])
        if hh[j] < sm[j]:
            out.append(sig(b, j, 1, float(hl[j]), "DE09_HA_BELOW_MA_LONG", entry_stop=float(hh[j]), expire_k=exp))
        elif hl[j] > sm[j]:
            out.append(sig(b, j, -1, float(hh[j]), "DE09_HA_ABOVE_MA_SHORT", entry_stop=float(hl[j]), expire_k=exp))
    return out


def de09_x(m, B, p, cache):
    ho, hh, hl, hc, sm = _de09_arr(B, cache)
    return XExits(target_r=None, xbars=B[5], xlong=hc < ho, xshort=hc > ho)


# ═══ KS-01 SMA 30/40/50/60 tangled, close above the 20-day high, 20-day-low stop, 2R, 30 days (NSE daily, long) ═════

def ks01(m, B, p, cache):
    b = B[1]
    c = np.asarray(b.c, float)
    S = np.vstack([I.sma(c, n) for n in (30, 40, 50, 60)])
    with np.errstate(invalid="ignore", divide="ignore"):
        tight = (S.max(0) - S.min(0)) / c <= 0.015
    out = []
    for j in range(70, len(c) - 1):
        if tight[j - 9:j + 1].sum() < 5 or not tight[j - 4:j + 1].any():
            continue
        line = float(b.h[j - 20:j].max())
        if not (c[j] > line and c[j - 1] <= float(b.h[j - 21:j - 1].max())):
            continue
        stop = float(b.l[j - 20:j].min())
        if stop < c[j]:
            out.append(sig(b, j, 1, stop, "KS01_TANGLE_BREAKOUT_LONG"))
    return out


def ks01_x(m, B, p, cache):
    return XExits(target_r=2.0, max_hold=30)


# ═══ AO-01 CCI (20) beyond -100/+100 then a divergence, close back over (under) the EMA 9, 1R (one minute, index) ═══

def _cci(b, n=20):
    tp = (np.asarray(b.h, float) + b.l + b.c) / 3.0
    out = np.full(len(tp), np.nan)
    if len(tp) >= n:
        w = np.lib.stride_tricks.sliding_window_view(tp, n)
        ma = w.mean(1)
        md = np.abs(w - ma[:, None]).mean(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[n - 1:] = np.where(md > 0, (tp[n - 1:] - ma) / (0.015 * md), 0.0)
    return out


def ao01(m, B, p, cache):
    b = B[1]
    cci = _cached(cache, ("ze_cci20",), lambda: _cci(b, 20))
    e9 = ctx(m, B, 1, cache).ema(9)
    ph, pl = ctx(m, B, 1, cache).fractals(3)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js:
            continue
        j0, j1 = js[0], js[-1]
        for side, flags, ext in ((1, pl, b.l), (-1, ph, b.h)):
            piv = np.flatnonzero(flags[j0:j1 + 1]) + j0
            used = -1
            for a_i, p1 in enumerate(piv):
                if not np.isfinite(cci[p1]) or not ((cci[p1] < -100) if side > 0 else (cci[p1] > 100)):
                    continue
                for p2 in piv[a_i + 1:]:
                    if p2 - p1 > 30:
                        break
                    if not (((ext[p2] < ext[p1]) and (cci[p2] > cci[p1])) if side > 0
                            else ((ext[p2] > ext[p1]) and (cci[p2] < cci[p1]))):
                        continue
                    conf = int(p2) + 3
                    if conf > used:
                        for j in range(conf, min(conf + 10, j1)):
                            if not (T(9, 30) <= int(b.ist0[j]) < T(14, 45)):
                                continue
                            if (b.c[j] > e9[j]) if side > 0 else (b.c[j] < e9[j]):
                                out.append(sig(b, j, side, float(ext[p2]),
                                               "AO01_CCI_DIVERGENCE_LONG" if side > 0 else "AO01_CCI_DIVERGENCE_SHORT"))
                                used = j
                                break
                    break
    return sorted_out(out)


def ao01_x(m, B, p, cache):
    return XExits(target_r=1.0)


# ═══ AO-02 stocks: close beyond the 09:15 five-minute candle, stop at its far side, out on a close through the EMA 9 ═

def ao02(m, B, p, cache):
    b = B[5]
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ist0[js[0]]) != T(9, 15):
            continue
        H, L = float(b.h[js[0]]), float(b.l[js[0]])
        for j in js[1:]:
            if int(b.ist0[j]) >= T(13, 0):
                break
            if b.c[j] > H:
                out.append(sig(b, j, 1, L, "AO02_FIRST5_BREAK_LONG"))
                break
            if b.c[j] < L:
                out.append(sig(b, j, -1, H, "AO02_FIRST5_BREAK_SHORT"))
                break
    return out


def ao02_x(m, B, p, cache):
    b = B[5]
    e9 = ctx(m, B, 5, cache).ema(9)
    with np.errstate(invalid="ignore"):
        return XExits(target_r=None, xbars=b, xlong=b.c < e9, xshort=b.c > e9)


# ═══ CH-01 trend-day VWAP retest after a one-minute reclaim, 2R, two-bar trail (Nasdaq cash session) ══════════════════

def ch01(m, B, p, cache):
    b = B[1]
    vw = Z.vwap_of(m, b, cache, "1")
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ny0[js[0]]) != T(9, 30):
            continue
        j0, jz = js[0], js[-1] + 1
        for j in js:
            t = int(b.ny0[j])
            if t < T(10, 0) or j - j0 < 60 or not np.isfinite(vw[j]):
                continue
            if t >= T(15, 30):
                break
            above = int(np.sum(b.c[j - 20:j] > vw[j - 20:j]))
            below = int(np.sum(b.c[j - 20:j] < vw[j - 20:j]))
            hl = float(b.l[j - 30:j].min()) > float(b.l[j - 60:j - 30].min())
            lh = float(b.h[j - 30:j].max()) < float(b.h[j - 60:j - 30].max())
            if above >= 16 and hl and b.l[j] <= vw[j] * 1.0002:
                side = 1
            elif below >= 16 and lh and b.h[j] >= vw[j] * 0.9998:
                side = -1
            else:
                continue
            for q in range(j + 1, min(j + 6, jz)):
                if int(b.ny0[q]) >= T(15, 30):
                    break
                if (b.c[q] > b.h[j]) if side > 0 else (b.c[q] < b.l[j]):
                    out.append(sig(b, q, side, float(b.l[j]) if side > 0 else float(b.h[j]),
                                   "CH01_VWAP_RETEST_LONG" if side > 0 else "CH01_VWAP_RETEST_SHORT"))
                    break
    return sorted_out(out)


def ch01_x(m, B, p, cache):
    b = B[1]
    lo2 = np.r_[np.nan, np.nan, np.asarray(b.l, float)[:-2]]
    hi2 = np.r_[np.nan, np.nan, np.asarray(b.h, float)[:-2]]
    return XExits(target_r=2.0, trail=("level", b, lo2, hi2))


# ═══ SK-01 exhaustive four-candle leg past the previous impulse's level, limit back at the level with the 20 MA (gold) ═

def sk01(m, B, p, cache):
    b = B[5]
    sma = ctx(m, B, 5, cache).sma(20)
    rg = np.asarray(b.h, float) - b.l
    n = len(b.c)
    out = []
    for j in range(40, n - 1):
        if b.day[j + 1] != b.day[j] or not _fin(sma[j], sma[j - 12]):
            continue
        if not all(rg[q] > rg[q - 1] for q in range(j - 2, j + 1)):
            continue
        reds = all(b.c[q] < b.o[q] for q in range(j - 3, j + 1))
        greens = all(b.c[q] > b.o[q] for q in range(j - 3, j + 1))
        exp = int(b.i1[min(j + 24, n - 1)])
        if reds and sma[j] < sma[j - 12]:
            lvl = float(b.l[j - 15:j - 3].min())
            if b.c[j] < lvl and abs(sma[j] - lvl) <= 0.0015 * lvl:
                out.append(sig(b, j, -1, lvl * 1.0008, "SK01_EXHAUSTION_SELL_LIMIT", entry_limit=lvl, expire_k=exp))
        elif greens and sma[j] > sma[j - 12]:
            lvl = float(b.h[j - 15:j - 3].max())
            if b.c[j] > lvl and abs(sma[j] - lvl) <= 0.0015 * lvl:
                out.append(sig(b, j, 1, lvl * 0.9992, "SK01_EXHAUSTION_BUY_LIMIT", entry_limit=lvl, expire_k=exp))
    return out


def sk01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ QC-01 30-minute opening range breakout, far-side stop, out at 13:30 New York (Nasdaq proxy for Tesla) ════════════

def qc01(m, B, p, cache):
    b = B[1]
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ny0[js[0]]) != T(9, 30):
            continue
        rj = [j for j in js if int(b.ny0[j]) < T(10, 0)]
        if len(rj) < 25 or len(js) <= len(rj):
            continue
        H, L = float(b.h[rj].max()), float(b.l[rj].min())
        for j in js[len(rj):]:
            if int(b.ny0[j]) >= T(13, 29):
                break
            if b.c[j] > H:
                out.append(sig(b, j, 1, L, "QC01_ORB30_LONG"))
                break
            if b.c[j] < L:
                out.append(sig(b, j, -1, H, "QC01_ORB30_SHORT"))
                break
    return out


def qc01_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ CV-01 15-minute opening range stop orders both sides (OCO), 10-point stop and target (Nasdaq) ═══════════════════

def cv01(m, B, p, cache):
    b = B[1]
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ny0[js[0]]) != T(9, 30):
            continue
        rj = [j for j in js if int(b.ny0[j]) < T(9, 45)]
        if len(rj) < 15 or len(js) <= len(rj):        # the range is complete once a 09:45 row exists
            continue
        exp = int(b.i1[rj[-1]]) + 75                 # the 10:59 row (one-minute rows)
        H, L = float(b.h[rj].max()), float(b.l[rj].min())
        s = sig(b, rj[-1], 1, H + 0.25 - 10.0, "CV01_ORB15_LONG", entry_stop=H + 0.25, expire_k=exp,
                info={"stop_dist": 10.0})
        s.alt = sig(b, rj[-1], -1, L - 0.25 + 10.0, "CV01_ORB15_SHORT", entry_stop=L - 0.25, expire_k=exp,
                    info={"stop_dist": 10.0})
        out.append(s)
    return out


def cv01_x(m, B, p, cache):
    return XExits(target_r=None, target_abs=10.0)


# ═══ KT-01 200 EMA band (high/close/low) dip, close back outside + a fresh MACD cross, break of that candle (1 min) ════

def kt01(m, B, p, cache):
    b = B[1]

    def calc():
        eh, el = I.ema(np.asarray(b.h, float), 200), I.ema(np.asarray(b.l, float), 200)
        line, sgl, _ = I.macd(np.asarray(b.c, float), 12, 26, 9)
        return eh, el, line, sgl
    eh, el, line, sgl = _cached(cache, ("ze_kt01",), calc)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js:
            continue
        for j in js:
            if j < 260 or not (T(9, 30) <= int(b.ist0[j]) < T(14, 45)):
                continue
            exp = int(b.i1[j]) + 3
            fresh_up = line[j] > sgl[j] and bool((line[j - 3:j] <= sgl[j - 3:j]).any())
            fresh_dn = line[j] < sgl[j] and bool((line[j - 3:j] >= sgl[j - 3:j]).any())
            if fresh_up and b.c[j] > eh[j] and bool((b.l[j - 15:j] <= eh[j - 15:j]).any()):
                out.append(sig(b, j, 1, float(b.l[j - 9:j + 1].min()), "KT01_EMA200_BAND_MACD_LONG",
                               entry_stop=float(b.h[j]) + 1.0, expire_k=exp))
            elif fresh_dn and b.c[j] < el[j] and bool((b.h[j - 15:j] >= el[j - 15:j]).any()):
                out.append(sig(b, j, -1, float(b.h[j - 9:j + 1].max()), "KT01_EMA200_BAND_MACD_SHORT",
                               entry_stop=float(b.l[j]) - 1.0, expire_k=exp))
    return out


def kt01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ KR-01 open in range and in value: fade a hold at the previous value-area edge back to the naked POC (Nasdaq) ═════

def _tpo(m, d, step=5.0):
    """(point of control, value-area high, value-area low) of session d's time-at-price profile on `step` buckets."""
    a, z = int(m.d0[d]), int(m.d1[d])
    if z - a < 100:
        return None
    lo = np.floor(m.l[a:z] / step).astype(np.int64)
    hi = np.floor(m.h[a:z] / step).astype(np.int64)
    base = int(lo.min())
    cnt = np.zeros(int(hi.max()) - base + 1)
    for x, y in zip(lo - base, hi - base):
        cnt[x:y + 1] += 1
    ties = np.flatnonzero(cnt == cnt.max())
    poc = int(ties[np.argmin(np.abs(ties - (len(cnt) - 1) / 2))])
    lo_i = hi_i = poc
    acc, tot = cnt[poc], cnt.sum()
    while acc < 0.7 * tot:
        up = cnt[hi_i + 1] if hi_i + 1 < len(cnt) else -1.0
        dn = cnt[lo_i - 1] if lo_i >= 1 else -1.0
        if up < 0 and dn < 0:
            break
        if up >= dn:
            hi_i += 1
            acc += up
        else:
            lo_i -= 1
            acc += dn
    return (base + poc + 0.5) * step, (base + hi_i + 1) * step, (base + lo_i) * step


def kr01(m, B, p, cache):
    b = B[5]
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        js = _days(b, d)
        if not js or int(b.ny0[js[0]]) != T(9, 30):
            continue
        prof = _cached(cache, ("ze_tpo", d), lambda: _tpo(m, d - 1))
        if prof is None:
            continue
        poc, vah, val = prof
        o = float(b.o[js[0]])
        if not (val <= o <= vah) or o == poc:
            continue
        side = -1 if o > poc else 1
        touched = False
        for j in js:
            if int(b.ny0[j]) >= T(13, 0):
                break
            hi, lo = float(b.h[js[0]:j + 1].max()), float(b.l[js[0]:j + 1].min())
            if side < 0:
                if lo <= poc:
                    break
                touched = touched or b.h[j] >= vah
                if touched and b.c[j] < vah:
                    out.append(sig(b, j, -1, hi * 1.0015, "KR01_VAH_HOLD_FADE_SHORT", target_px=poc))
                    break
            else:
                if hi >= poc:
                    break
                touched = touched or b.l[j] <= val
                if touched and b.c[j] > val:
                    out.append(sig(b, j, 1, lo * (1 - 0.0015), "KR01_VAL_HOLD_FADE_LONG", target_px=poc))
                    break
    return out


def kr01_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ KG-01 weekly + daily CPR side, R1 + previous-day-high break, midpoint stop, R1-R2 midpoint then R2 (5 min) ══════

def _week_hlc(m, cache):
    def calc():
        wk = (m.date.astype("datetime64[D]").astype(np.int64) + 3) // 7
        out = {}
        for d in range(m.n_days):
            a, z = int(m.d0[d]), int(m.d1[d])
            if z <= a:
                continue
            w = int(wk[d])
            h, l, c = float(m.h[a:z].max()), float(m.l[a:z].min()), float(m.c[z - 1])
            out[w] = (max(out[w][0], h), min(out[w][1], l), c) if w in out else (h, l, c)
        return wk, out
    return _cached(cache, ("ze_week_hlc",), calc)


def kg01(m, B, p, cache):
    b, h1 = B[5], B[60]
    wk, wh = _week_hlc(m, cache)
    weeks = sorted(wh)
    widths = {}
    for d in range(1, m.n_days):
        pd = E.prev_day_hlc(m, d)
        if pd:
            P, BC, TC = E.cpr(*pd)
            widths[d] = (TC - BC) / P
    out = []
    for d in range(21, m.n_days):
        pd = E.prev_day_hlc(m, d)
        if not pd or d not in widths:
            continue
        prevw = [x for x in weeks if x < int(wk[d])]
        js = _days(b, d)
        if not prevw or not js or int(b.ist0[js[0]]) != T(9, 15):
            continue
        _, WBC, WTC = E.cpr(*wh[prevw[-1]])
        pv = E.floor_pivots(*pd)
        PDH, PDL = pd[0], pd[1]
        hist = [widths[x] for x in range(d - 20, d) if x in widths]
        wide = len(hist) >= 10 and widths[d] > float(np.median(hist))
        o0 = float(b.o[js[0]])
        hs = _days(h1, d)
        up_l, dn_l = max(pv["R1"], PDH), min(pv["S1"], PDL)
        for i, j in enumerate(js):
            if int(b.ist0[j]) >= T(14, 30):
                break
            done = [q for q in hs if int(h1.i1[q]) <= int(b.i1[j])]
            ref = float(h1.c[done[-1]]) if done else o0
            c = float(b.c[j])
            fresh_up = i == 0 or float(b.c[j - 1]) <= up_l
            fresh_dn = i == 0 or float(b.c[j - 1]) >= dn_l
            if c > up_l and fresh_up and ref > WTC:
                t1, t2, stop = (pv["R1"] + pv["R2"]) / 2, pv["R2"], (pv["R1"] + PDH) / 2
                if c < t1 and stop < c:
                    out.append(sig(b, j, 1, stop, "KG01_R1_PDH_BREAK_LONG", target_px=t1 if wide else t2,
                                   info={} if wide else {"partial_px": t1}))
                break
            if c < dn_l and fresh_dn and ref < WBC:
                t1, t2, stop = (pv["S1"] + pv["S2"]) / 2, pv["S2"], (pv["S1"] + PDL) / 2
                if c > t1 and stop > c:
                    out.append(sig(b, j, -1, stop, "KG01_S1_PDL_BREAK_SHORT", target_px=t1 if wide else t2,
                                   info={} if wide else {"partial_px": t1}))
                break
    return out


def kg01_x(m, B, p, cache):
    return XExits(target_r=None, partial_px=True)


# ═══ TN-02 New York 15-minute opening range double break: reclaim on the VWAP side, target the far edge (Nasdaq) ══════

def tn02(m, B, p, cache):
    b = B[5]
    vw = Z.vwap_of(m, b, cache, "5")
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if len(js) < 4 or int(b.ny0[js[0]]) != T(9, 30) or int(b.ny0[js[2]]) != T(9, 40):
            continue
        H, L = float(b.h[js[:3]].max()), float(b.l[js[:3]].min())
        broke_lo = broke_hi = False
        for j in js[3:]:
            if int(b.ny0[j]) >= T(11, 55):
                break
            if not np.isfinite(vw[j]):
                continue
            c = float(b.c[j])
            lo, hi = float(b.l[js[0]:j + 1].min()), float(b.h[js[0]:j + 1].max())
            if broke_lo and c > L and c > vw[j]:
                if c > lo and (H - c) >= 0.5 * (c - lo):
                    out.append(sig(b, j, 1, lo, "TN02_DOUBLE_BREAK_LONG", target_px=H))
                break
            if broke_hi and c < H and c < vw[j]:
                if hi > c and (c - L) >= 0.5 * (hi - c):
                    out.append(sig(b, j, -1, hi, "TN02_DOUBLE_BREAK_SHORT", target_px=L))
                break
            broke_lo = broke_lo or c < L
            broke_hi = broke_hi or c > H
    return out


def tn02_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ CT-01 VWAP trend (15 bodies one side) + close outside the Bollinger band (14, 2) + RSI (16) 45/55 (forex 5m) ═════

def _ct01_arr(m, B, cache):
    def calc():
        b = B[5]
        c = np.asarray(b.c, float)
        _, up, lo = YI.bollinger(c, 14, 2.0)
        return I.anchored_vwap(m, b, 0), up, lo, I.rsi(c, 16), YI.atr(b, 7)
    return _cached(cache, ("ze_ct01",), calc)


def ct01(m, B, p, cache):
    b = B[5]
    vw, up, lo, r, a = _ct01_arr(m, B, cache)
    tu, td = _run_side(b.o, b.c, vw, 15)
    out = []
    for j in range(30, len(b.c) - 1):
        if not _fin(up[j], lo[j], r[j], a[j]) or b.day[j + 1] != b.day[j]:
            continue
        if tu[j] and b.c[j] < lo[j] and r[j] < 45:
            out.append(sig(b, j, 1, float(b.c[j] - 1.2 * a[j]), "CT01_VWAP_BB_RSI_LONG", info={"stop_dist": float(1.2 * a[j])}))
        elif td[j] and b.c[j] > up[j] and r[j] > 55:
            out.append(sig(b, j, -1, float(b.c[j] + 1.2 * a[j]), "CT01_VWAP_BB_RSI_SHORT", info={"stop_dist": float(1.2 * a[j])}))
    return out


def ct01_x(m, B, p, cache):
    vw, up, lo, r, a = _ct01_arr(m, B, cache)
    rp = np.r_[np.nan, r[:-1]]
    with np.errstate(invalid="ignore"):
        xl = (r > 90) & (rp <= 90)
        xs = (r < 10) & (rp >= 10)
    return XExits(target_r=1.5, xbars=B[5], xlong=xl, xshort=xs)


# ═══ CT-02 VWAP bounce: 15 bodies on one side of the VWAP, a candle reaching within 0.2% of it, 0.8 ATR, 2.5R (BTC) ══

def ct02(m, B, p, cache):
    b = B[15]
    vw = Z.vwap_of(m, b, cache, "15")
    a = _cached(cache, ("ze_atr7_15",), lambda: YI.atr(b, 7))
    tu, td = _run_side(b.o, b.c, vw, 15)
    out = []
    for j in range(30, len(b.c) - 1):
        if not _fin(vw[j], a[j]) or b.day[j + 1] != b.day[j]:
            continue
        tol = 0.002 * float(b.c[j])
        if tu[j] and abs(float(b.l[j]) - vw[j]) <= tol:
            out.append(sig(b, j, 1, float(b.c[j] - 0.8 * a[j]), "CT02_VWAP_BOUNCE_LONG", info={"stop_dist": float(0.8 * a[j])}))
        elif td[j] and abs(float(b.h[j]) - vw[j]) <= tol:
            out.append(sig(b, j, -1, float(b.c[j] + 0.8 * a[j]), "CT02_VWAP_BOUNCE_SHORT", info={"stop_dist": float(0.8 * a[j])}))
    return out


def ct02_x(m, B, p, cache):
    return XExits(target_r=2.5)


# ═══ CH-02 15-minute New York opening range break on a one-minute close, VWAP side and slope, 1.5 x range (Nasdaq) ════

def ch02(m, B, p, cache):
    b = B[1]
    vw = Z.vwap_of(m, b, cache, "1")
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ny0[js[0]]) != T(9, 30):
            continue
        rj = [j for j in js if int(b.ny0[j]) < T(9, 45)]
        if len(rj) < 15:
            continue
        H, L = float(b.h[rj].max()), float(b.l[rj].min())
        R = H - L
        if not R > 0:
            continue
        for j in js[len(rj):]:
            if int(b.ny0[j]) >= T(12, 0):
                break
            if not _fin(vw[j], vw[j - 5]):
                continue
            c = float(b.c[j])
            if c > H and c > vw[j] and vw[j] > vw[j - 5]:
                out.append(sig(b, j, 1, L, "CH02_ORB15_VWAP_LONG", target_px=H + 1.5 * R))
                break
            if c < L and c < vw[j] and vw[j] < vw[j - 5]:
                out.append(sig(b, j, -1, H, "CH02_ORB15_VWAP_SHORT", target_px=L - 1.5 * R))
                break
    return out


def ch02_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ CT-03 close above the daily VWAP and the day's open = long (below both = short), 1.5 ATR trail (15 minutes) ══════

def _ct03_arr(m, B, cache):
    def calc():
        b = B[15]
        vw = Z.vwap_of(m, b, cache, "15")
        do = np.array([float(m.o[m.d0[int(d)]]) for d in b.day])
        c = np.asarray(b.c, float)
        with np.errstate(invalid="ignore"):
            return (c > vw) & (c > do), (c < vw) & (c < do), YI.atr(b, 14)
    return _cached(cache, ("ze_ct03",), calc)


def ct03(m, B, p, cache):
    b = B[15]
    lg, sh, a = _ct03_arr(m, B, cache)
    nse = m.name != "BTCUSD"
    out = []
    for j in range(20, len(b.c) - 1):
        if b.day[j + 1] != b.day[j] or not np.isfinite(a[j]):
            continue
        if nse and not (T(9, 30) <= int(b.ist0[j]) < T(14, 45)):
            continue
        if lg[j]:
            out.append(sig(b, j, 1, float(b.c[j] - 1.5 * a[j]), "CT03_VWAP_DAY_OPEN_LONG", info={"stop_dist": float(1.5 * a[j])}))
        elif sh[j]:
            out.append(sig(b, j, -1, float(b.c[j] + 1.5 * a[j]), "CT03_VWAP_DAY_OPEN_SHORT", info={"stop_dist": float(1.5 * a[j])}))
    return out


def ct03_x(m, B, p, cache):
    b = B[15]
    lg, sh, a = _ct03_arr(m, B, cache)
    return XExits(target_r=None, trail=("chand", b, a, 1.5), xbars=b, xlong=sh, xshort=lg)


# ═══ QC-03 gap down beyond -3 standard deviations of the last hour's closes: buy, out at 10:00 (NSE stocks) ═══════════

def qc03(m, B, p, cache):
    b = B[5]
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        js, pj = _days(b, d), _days(b, d - 1)
        if not js or len(pj) < 12 or int(b.ist0[js[0]]) != T(9, 15):
            continue
        sd = float(np.std(np.asarray(b.c[pj[-12:]], float)))
        pc = float(b.c[pj[-1]])
        j0 = js[0]
        gap = float(b.o[j0]) - pc
        if not sd > 0 or gap / sd >= -3:
            continue
        out.append(sig(b, j0, 1, float(b.c[j0]) - abs(gap), "QC03_GAP_DOWN_FADE_LONG",
                       info={"stop_dist": abs(gap), "k_last": int(b.i1[j0]) + 8}))   # the 09:55 row (5-minute rows)
    return out


def qc03_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ AC-02 day type from the 3-minute range vs the VWAP; 1-3 SD bands + RSI 70/30 (Nasdaq 3 minutes) ═════════════════

def ac02(m, B, p, cache):
    b = B[3]
    vw, sd = _vwap_sd(m, b, cache, "3")
    r = ctx(m, B, 3, cache).rsi(14)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ny0[js[0]]) != T(9, 30):
            continue
        ORH, ORL = float(b.h[js[0]]), float(b.l[js[0]])
        for j in js[1:]:
            if int(b.ny0[j]) >= T(15, 0):
                break
            if not _fin(vw[j], sd[j], r[j]) or not sd[j] > 0:
                continue
            V, S = float(vw[j]), float(sd[j])
            h, l, c = float(b.h[j]), float(b.l[j]), float(b.c[j])
            if V > ORH:                                      # trend up: buy the pullback to the lower first band
                band = V - S
                if l <= band and r[j] <= 30 and c > band:
                    out.append(sig(b, j, 1, min(band, l) * 0.9995, "AC02_TREND_UP_BAND1_LONG", target_px=V + S,
                                   info={"partial_px": V}))
            elif V < ORL:                                    # trend down: sell the rally to the highest band touched
                k = next((k for k in (3, 2, 1) if h >= V + k * S), None)
                if k is not None and r[j] >= 70 and c < V + k * S:
                    out.append(sig(b, j, -1, max(V + k * S, h) * 1.0005, f"AC02_TREND_DOWN_BAND{k}_SHORT",
                                   target_px=V - S, info={"partial_px": V}))
            else:                                            # sideways: fade the third band back to the VWAP
                if h >= V + 3 * S and r[j] >= 70 and c < V + 3 * S:
                    out.append(sig(b, j, -1, max(V + 3 * S, h) * 1.0005, "AC02_RANGE_BAND3_SHORT", target_px=V))
                elif l <= V - 3 * S and r[j] <= 30 and c > V - 3 * S:
                    out.append(sig(b, j, 1, min(V - 3 * S, l) * 0.9995, "AC02_RANGE_BAND3_LONG", target_px=V))
    return out


def ac02_x(m, B, p, cache):
    return XExits(target_r=None, partial_px=True)


# ═══ CR-01 drop, base, rally on one-minute candles in a 30-minute uptrend: limit at the base top, 3R (Nasdaq, long) ═══

def cr01(m, B, p, cache):
    b, b30 = B[1], B[30]
    a = ctx(m, B, 1, cache).atr(14)
    e50 = ctx(m, B, 30, cache).ema(50)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ny0[js[0]]) != T(9, 30):
            continue
        jz = js[-1]
        s = js[0] + 11
        while s <= jz - 4:
            if not np.isfinite(a[s - 1]) or not (b.c[s - 1] <= b.c[s - 11] - 1.5 * a[s - 1]):
                s += 1
                continue
            best = None
            for L in range(4, 13):
                e = s + L - 1
                if e > jz:
                    break
                if best is not None:                     # a close that would be the rally ends the base
                    ph_, pl_ = float(b.h[s:e].max()), float(b.l[s:e].min())
                    if b.c[e] >= ph_ + 2 * (ph_ - pl_):
                        break
                if float(b.h[s:e + 1].max() - b.l[s:e + 1].min()) >= 1.5 * a[s - 1]:
                    break
                best = L
            if best is None:
                s += 1
                continue
            e = s + best - 1
            bh, bl = float(b.h[s:e + 1].max()), float(b.l[s:e + 1].min())
            rally = next((q for q in range(e + 1, min(e + 11, jz + 1)) if b.c[q] >= bh + 2 * (bh - bl)), None)
            if rally is None:
                s += 1
                continue
            if T(9, 45) <= int(b.ny0[rally]) < T(15, 0):
                k30 = int(np.searchsorted(b30.i1, b.i1[rally], "right")) - 1
                if k30 >= 1 and _fin(e50[k30], e50[k30 - 1]) and b30.c[k30] > e50[k30] > e50[k30 - 1]:
                    out.append(sig(b, rally, 1, bl * (1 - 0.0002), "CR01_DROP_BASE_RALLY_LONG", entry_limit=bh,
                                   expire_k=int(b.i1[rally]) + 60))
            s = rally + 1
    return out


def cr01_x(m, B, p, cache):
    return XExits(target_r=3.0)


# ═══ CR-02 VWAP bounce / rejection after an hour clear of the VWAP, stop entry past the touch candle, 2R (NSE) ════════

def cr02(m, B, p, cache):
    b = B[5]
    vw = Z.vwap_of(m, b, cache, "5")
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if not js or int(b.ist0[js[0]]) != T(9, 15):
            continue
        for i, j in enumerate(js):
            t = int(b.ist0[j])
            if t < T(10, 15) or i < 12 or not np.isfinite(vw[j]):
                continue
            if t >= T(14, 30):
                break
            prev = js[i - 12:i]
            exp = int(b.i1[j]) + 3
            if all(b.l[q] > vw[q] for q in prev) and b.l[j] <= vw[j] < b.c[j]:
                out.append(sig(b, j, 1, float(b.l[j]) - 0.05, "CR02_VWAP_BOUNCE_LONG", entry_stop=float(b.h[j]) + 0.05,
                               expire_k=exp))
            elif all(b.h[q] < vw[q] for q in prev) and b.h[j] >= vw[j] > b.c[j]:
                out.append(sig(b, j, -1, float(b.h[j]) + 0.05, "CR02_VWAP_REJECT_SHORT", entry_stop=float(b.l[j]) - 0.05,
                               expire_k=exp))
    return out


def cr02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ KG-02 trend reversal CPR: open on the wrong side of a descending (ascending) CPR, fade or break (5 min) ══════════

def kg02(m, B, p, cache):
    b = B[5]
    out = []
    for d in range(2, m.n_days):
        pd, pd2 = E.prev_day_hlc(m, d), E.prev_day_hlc(m, d - 1)
        js = _days(b, d)
        if not pd or not pd2 or len(js) < 4 or int(b.ist0[js[0]]) != T(9, 15):
            continue
        _, BC, TC = E.cpr(*pd)
        _, BC2, TC2 = E.cpr(*pd2)
        pv = E.floor_pivots(*pd)
        o0 = float(b.o[js[0]])
        if TC < BC2 and o0 > TC:
            side = -1
        elif BC > TC2 and o0 < BC:
            side = 1
        else:
            continue
        H15, L15 = float(b.h[js[:3]].max()), float(b.l[js[:3]].min())
        far = ((o0 - TC) if side < 0 else (BC - o0)) / o0 >= 0.0025
        up_brk, dn_brk = max(pv["R1"], pd[0]), min(pv["S1"], pd[1])
        for j in js:
            t = int(b.ist0[j])
            if t >= T(13, 0):
                break
            hi, lo = float(b.h[js[0]:j + 1].max()), float(b.l[js[0]:j + 1].min())
            c = float(b.c[j])
            if side < 0:
                if hi >= up_brk:                              # it rallied through R1 / the previous day high instead
                    break
                if t < T(9, 30):
                    continue
                if far and c < L15:
                    out.append(sig(b, j, -1, hi * 1.0005, "KG02_REVERSAL_FADE_TO_CPR_SHORT", target_px=TC))
                    break
                if not far and c < BC:
                    tgt = max(pv["S1"], pd[1])
                    if tgt < c:
                        out.append(sig(b, j, -1, TC * 1.0005, "KG02_CPR_BREAK_SHORT", target_px=tgt))
                    break
            else:
                if lo <= dn_brk:
                    break
                if t < T(9, 30):
                    continue
                if far and c > H15:
                    out.append(sig(b, j, 1, lo * 0.9995, "KG02_REVERSAL_FADE_TO_CPR_LONG", target_px=BC))
                    break
                if not far and c > TC:
                    tgt = min(pv["R1"], pd[0])
                    if tgt > c:
                        out.append(sig(b, j, 1, BC * 0.9995, "KG02_CPR_BREAK_LONG", target_px=tgt))
                    break
    return out


def kg02_x(m, B, p, cache):
    return XExits(target_r=None)
