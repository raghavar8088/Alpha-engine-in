"""The NSE stock strategies of the four-topic intraday study (cards/<video>.txt; the 'A' rules are the exact code).
Markets: NSE5 / NSE15 (the desk's 5-minute stock pool: one row = one 5-minute bar; 15-minute bars sit on a grid that
09:15 IST fits) and, where a card also teaches the index, NIFTY. Cross-sectional rules (movers, breadth, the fixed
watchlist) read p['ctx'] built by zd_common.zd_contexts from the whole pool; each value uses data known at its time.
Books are out at 15:15 unless the card says otherwise."""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import bars_of_day, body, ctx, green, red, rng, sig
from yc_engine import XExits

import zd_common as Z
from zd_common import NSE_OPEN, T, sorted_out


def _cx(p):
    return p.get("ctx") or {}


def _top_names(cx, key, date, n):
    lst = (cx.get(key) or {}).get(date[:7])
    return set(lst[:n]) if lst else None


# ═══ SI-01 9:25 top-mover body-range breakout (no-gap stocks, NIFTY-aligned), half at 1%, EMA 9 trail ═══════════

def _movers_pick(cx, date, side, n, max_gap=0.005, max_move=0.04):
    rows = (cx.get("zd_movers925") or {}).get(date) or []
    cand = [r for r in rows if r[0] * side > 0 and abs(r[2]) < max_gap and abs(r[0]) <= max_move]
    cand.sort(key=lambda r: (-r[0] * side, r[1]))
    return {r[1] for r in cand[:n]}


def si01(m, B, p, cx_cache):
    cx = _cx(p)
    b = B[5]
    out = []
    for d in range(1, m.n_days):
        date = str(m.date[d])
        side = ((cx.get("zd_nifty") or {}).get(date) or (0, 0))[0]
        if not side or m.name not in _movers_pick(cx, date, side, 3):
            continue
        rows = [j for j in bars_of_day(b, d) if Z.ist_min(b, j) < T(9, 25)]
        if len(rows) < 2:
            continue
        hi_b = max(max(b.o[j], b.c[j]) for j in rows)
        lo_b = min(min(b.o[j], b.c[j]) for j in rows)
        for j in bars_of_day(b, d):
            im = Z.ist_min(b, j)
            if im < T(9, 25) or im >= T(10, 30):
                continue
            if side > 0 and b.c[j] > hi_b:
                out.append(sig(b, j, 1, lo_b * 0.9995, "SI01_925_LONG", info={"partial_px": float(b.c[j]) * 1.01}))
                break
            if side < 0 and b.c[j] < lo_b:
                out.append(sig(b, j, -1, hi_b * 1.0005, "SI01_925_SHORT", info={"partial_px": float(b.c[j]) * 0.99}))
                break
    return sorted_out(out)


def si01_x(m, B, p, cache):
    b = B[5]
    e9 = ctx(m, B, 5, cache).ema(9)
    return XExits(target_r=None, partial_px=True, xbars=b, xlong=b.c < e9, xshort=b.c > e9)


# ═══ SI-02 fixed watchlist: 9:15-9:30 range break on the VWAP side, pullback engulfing, stop beyond VWAP, 2R ═══════

def si02(m, B, p, cache):
    cx = _cx(p)
    b = B[5]
    vw = Z.vwap_of(m, b, cache, 5)
    out = []
    for d in range(m.n_days):
        date = str(m.date[d])
        names = _top_names(cx, "zd_turnover", date, 6)
        if names is None or m.name not in names:
            continue
        w = Z.window_hl(m, d, NSE_OPEN, T(9, 30))
        if w is None:
            continue
        H, L = w[0], w[1]
        side, pulled = 0, False
        for j in bars_of_day(b, d):
            im = Z.ist_min(b, j)
            if im < T(9, 30) or im >= T(13, 30) or not np.isfinite(vw[j]):
                continue
            if not side:
                if b.c[j] > H and b.c[j] > vw[j]:
                    side = 1
                elif b.c[j] < L and b.c[j] < vw[j]:
                    side = -1
                continue
            if not pulled:
                pulled = (b.l[j] <= vw[j] * 1.002) if side > 0 else (b.h[j] >= vw[j] * 0.998)
            if not pulled or im < T(9, 35):
                continue
            if side > 0 and Z.bull_engulf(b, j) and b.c[j] > vw[j]:
                stop = min(vw[j] * 0.9995, b.c[j] * 0.997)
                out.append(sig(b, j, 1, float(stop), "SI02_ORB_VWAP_LONG"))
                break
            if side < 0 and Z.bear_engulf(b, j) and b.c[j] < vw[j]:
                stop = max(vw[j] * 1.0005, b.c[j] * 1.003)
                out.append(sig(b, j, -1, float(stop), "SI02_ORB_VWAP_SHORT"))
                break
    return sorted_out(out)


def si02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ SI-04 NIFTY's first 15-minute colour, top three movers, break of their second 15-minute candle, 2R ═════════

def si04(m, B, p, cache):
    cx = _cx(p)
    b = B[15]
    out = []
    for d in range(1, m.n_days):
        date = str(m.date[d])
        col = ((cx.get("zd_nifty") or {}).get(date) or (0, 0))[1]
        if not col:
            continue
        rows = (cx.get("zd_movers930") or {}).get(date) or []
        cand = sorted((r for r in rows if r[0] * col > 0), key=lambda r: (-r[0] * col, r[1]))[:3]
        if m.name not in {r[1] for r in cand}:
            continue
        for j in bars_of_day(b, d):
            if Z.ist_min(b, j) != T(9, 30):
                continue
            exp = int(b.i1[j]) + 15
            if col > 0:
                out.append(sig(b, j, 1, float(b.l[j]) * 0.9995, "SI04_2ND15_LONG", entry_stop=float(b.h[j]), expire_k=exp))
            else:
                out.append(sig(b, j, -1, float(b.h[j]) * 1.0005, "SI04_2ND15_SHORT", entry_stop=float(b.l[j]), expire_k=exp))
            break
    return sorted_out(out)


def si04_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ SI-06 SMMA 11/21 crossover on the side of the 15-minute SMA 21 (5-minute stocks, 3-minute NIFTY) ════════════

def _si06_bars(m, B):
    return B[3] if m.name in ("NIFTY", "BANKNIFTY") else B[5]


def _si06_lines(m, B, cache):
    b = _si06_bars(m, B)
    key = ("zd_si06", b.tf)
    if key not in cache:
        cache[key] = (I.smma(b.c, 11), I.smma(b.c, 21))
    return b, cache[key]


def si06(m, B, p, cache):
    b, (s11, s21) = _si06_lines(m, B, cache)
    bh = B[15]
    h21 = I.sma(bh.c, 21)
    n = len(b.c)
    out = []
    for x in range(1, n):
        im = Z.ist_min(b, x)
        if not (T(9, 30) <= im < T(14, 30)):
            continue
        for side in (1, -1):
            cr = Z.cross_up(s11, s21, x) if side > 0 else Z.cross_dn(s11, s21, x)
            if not cr:
                continue
            for j in range(x + 1, min(x + 5, n)):
                if b.day[j] != b.day[x] or Z.ist_min(b, j) >= T(14, 30):
                    break
                kh = Z.last_done(bh, int(b.i1[j]))
                if kh < 0 or not np.isfinite(h21[kh]):
                    break
                if side > 0 and b.c[j] > max(s11[j], s21[j], h21[kh]):
                    stop = float(b.l[max(0, j - 5):j + 1].min())
                    stop = min(max(stop, b.c[j] * (1 - 0.006)), b.c[j] * (1 - 0.0015))
                    out.append(sig(b, j, 1, stop, "SI06_SMMA_LONG"))
                    break
                if side < 0 and b.c[j] < min(s11[j], s21[j], h21[kh]):
                    stop = float(b.h[max(0, j - 5):j + 1].max())
                    stop = max(min(stop, b.c[j] * (1 + 0.006)), b.c[j] * (1 + 0.0015))
                    out.append(sig(b, j, -1, stop, "SI06_SMMA_SHORT"))
                    break
    return sorted_out(out)


def si06_x(m, B, p, cache):
    b, (s11, s21) = _si06_lines(m, B, cache)
    xl, xs = Z.flags(len(b.c))
    for j in range(1, len(b.c)):
        xl[j] = Z.cross_dn(s11, s21, j)
        xs[j] = Z.cross_up(s11, s21, j)
    return XExits(target_r=None, partial_at_r=2.0, xbars=b, xlong=xl, xshort=xs)


# ═══ SI-08 previous afternoon (14:00-15:30) range around VWAP: break, pullback, engulfing, 2R ═══════════════════

def si08(m, B, p, cache):
    cx = _cx(p)
    b = B[5]
    vw = Z.vwap_of(m, b, cache, 5)
    is_index = m.name in ("NIFTY", "BANKNIFTY")
    out = []
    for d in range(1, m.n_days):
        date = str(m.date[d])
        if not is_index:
            names = _top_names(cx, "zd_turnover", date, 10)
            if names is None or m.name not in names:
                continue
        if not m.prev_ok[d]:
            continue
        w = Z.window_hl(m, d - 1, T(14, 0), T(15, 30))
        if w is None:
            continue
        H, L = w[0], w[1]
        if not (L > 0 and (H - L) / L < 0.012):
            continue
        pb = [j for j in bars_of_day(b, d - 1) if Z.ist_min(b, j) >= T(14, 0)]
        if len(pb) < 2 or not (np.isfinite(vw[pb[0]]) and np.isfinite(vw[pb[-1]])):
            continue
        if abs(vw[pb[-1]] / vw[pb[0]] - 1) >= 0.003:
            continue
        side, pulled, ext = 0, False, None
        for j in bars_of_day(b, d):
            im = Z.ist_min(b, j)
            if im < T(9, 20) or im >= T(14, 0):
                continue
            if not side:
                if b.c[j] > H:
                    side, ext = 1, float(b.l[j])
                elif b.c[j] < L:
                    side, ext = -1, float(b.h[j])
                continue
            ext = min(ext, float(b.l[j])) if side > 0 else max(ext, float(b.h[j]))
            if not pulled:
                pulled = (b.l[j] <= H * 1.0015) if side > 0 else (b.h[j] >= L * 0.9985)
            if not pulled:
                continue
            if side > 0 and Z.bull_engulf(b, j) and b.c[j] > H:
                stop = min(ext * 0.9995, b.c[j] * 0.998)
                out.append(sig(b, j, 1, float(stop), "SI08_PM_RANGE_LONG"))
                break
            if side < 0 and Z.bear_engulf(b, j) and b.c[j] < L:
                stop = max(ext * 1.0005, b.c[j] * 1.002)
                out.append(sig(b, j, -1, float(stop), "SI08_PM_RANGE_SHORT"))
                break
    return sorted_out(out)


def si08_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ SI-10 breadth side, previous-day high / low broken by two same-colour 5-minute candles, half at 2R ═════════

def si10(m, B, p, cache):
    cx = _cx(p)
    b = B[5]
    out = []
    for d in range(1, m.n_days):
        date = str(m.date[d])
        rows = (cx.get("zd_movers925") or {}).get(date) or []
        ups, dns = sum(1 for r in rows if r[0] > 0), sum(1 for r in rows if r[0] < 0)
        side = 1 if ups > dns else (-1 if dns > ups else 0)
        pd_ = Z.prev_day_hl(m, d)
        if not side or pd_ is None:
            continue
        pdh, pdl = pd_[0], pd_[1]
        js = list(bars_of_day(b, d))
        for i, j in enumerate(js[:-1]):
            im = Z.ist_min(b, j)
            if im < T(9, 20) or im >= T(13, 30):
                continue
            q = js[i + 1]
            if side < 0 and red(b, j) and b.c[j] < pdl and red(b, q):
                if rng(b, j) > 0.03 * b.c[j]:
                    break
                stop = float(b.h[q]) * 1.0002
                if (stop - b.l[q]) / b.l[q] <= 0.01:
                    out.append(sig(b, q, -1, stop, "SI10_PDL_SHORT", entry_stop=float(b.l[q]), expire_k=int(b.i1[q]) + 2))
                break
            if side > 0 and green(b, j) and b.c[j] > pdh and green(b, q):
                if rng(b, j) > 0.03 * b.c[j]:
                    break
                stop = float(b.l[q]) * 0.9998
                if (b.h[q] - stop) / b.h[q] <= 0.01:
                    out.append(sig(b, q, 1, stop, "SI10_PDH_LONG", entry_stop=float(b.h[q]), expire_k=int(b.i1[q]) + 2))
                break
    return sorted_out(out)


def si10_x(m, B, p, cache):
    return XExits(target_r=None, partial_at_r=2.0)


# ═══ SI-11 9:30 open-equals-low gainer (open-equals-high loser): first 15-minute candle breakout, 1R, out 14:00 ═══

def si11(m, B, p, cache):
    cx = _cx(p)
    out = []
    for d in range(1, m.n_days):
        date = str(m.date[d])
        top = ((cx.get("zd_ol930") or {}).get(date) or [])[:2]
        pick = {r[1]: r[2] for r in top}
        side = pick.get(m.name)
        if not side:
            continue
        w = Z.window_hl(m, d, NSE_OPEN, T(9, 30))
        if w is None:
            continue
        H, L, _, k = w
        op = float(m.o[m.d0[d]])
        if side > 0:
            out.append(sig_row(m, d, k, 1, op * 0.9998, "SI11_OPEN_LOW_LONG", entry_stop=H * 1.0002, expire_k=k + 12))
        else:
            out.append(sig_row(m, d, k, -1, op * 1.0002, "SI11_OPEN_HIGH_SHORT", entry_stop=L * 0.9998, expire_k=k + 12))
    return sorted_out(out)


def sig_row(m, d, k, side, stop, setup, **kw):
    from yt_engine import Signal
    return Signal(int(d), int(k), int(side), float(stop), setup, **kw)


def si11_x(m, B, p, cache):
    return XExits(target_r=1.0)


# ═══ SI-12 the day's top mover: 9:20 five-minute candle on the VWAP side, break of it, 1.5R then 2R ══════════════

def si12(m, B, p, cache):
    cx = _cx(p)
    b = B[5]
    vw = Z.vwap_of(m, b, cache, 5)
    out = []
    for d in range(1, m.n_days):
        date = str(m.date[d])
        side = ((cx.get("zd_nifty") or {}).get(date) or (0, 0))[0]
        if not side:
            continue
        rows = (cx.get("zd_movers925") or {}).get(date) or []
        cand = sorted((r for r in rows if r[0] * side > 0), key=lambda r: (-r[0] * side, r[1]))
        if not cand or cand[0][1] != m.name:
            continue
        for j in bars_of_day(b, d):
            if Z.ist_min(b, j) != T(9, 20) or not np.isfinite(vw[j]):
                continue
            exp = int(b.i1[j]) + 13
            if side < 0 and red(b, j) and b.c[j] < vw[j]:
                L = float(b.l[j])
                out.append(sig(b, j, -1, min(float(b.h[j]), L * 1.006), "SI12_920_SHORT", entry_stop=L, expire_k=exp))
            elif side > 0 and green(b, j) and b.c[j] > vw[j]:
                H = float(b.h[j])
                out.append(sig(b, j, 1, max(float(b.l[j]), H * 0.994), "SI12_920_LONG", entry_stop=H, expire_k=exp))
            break
    return sorted_out(out)


def si12_x(m, B, p, cache):
    return XExits(target_r=2.0, partial_at_r=1.5)
