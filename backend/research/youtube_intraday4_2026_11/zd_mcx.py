"""The MCX commodity strategies of the four-topic intraday study (cards/<video>.txt; the 'A' rules are the exact code).
Markets MCXCRUDE / MCXNG / MCXSILVER: one-minute rows of the MCX session (09:00-23:30 IST), one day per IST date; the
books are out at 23:25 IST unless the card holds positions across sessions. 20-minute and 1-hour bars are anchored at
the 09:00 open (zd_common.session_bars); 3-, 5-, 15- and 30-minute bars are on the plain grid, which 09:00 IST fits."""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import bars_of_day, body, ctx, green, red, rng, sig, weekday
from yc_engine import XExits

import zd_common as Z
from zd_common import MCX_OPEN, T, sorted_out


def _swing(b, j, n, side):
    """Lowest low (side +1) / highest high (side -1) of bars j-n+1 .. j."""
    a = max(0, j - n + 1)
    return float(b.l[a:j + 1].min()) if side > 0 else float(b.h[a:j + 1].max())


# ═══ CI-01 crude: 1-hour MACD side, fresh 15-minute MACD crosses, exit on the opposite cross ═══════════════════

def ci01(m, B, p, cache):
    b = B[15]
    bh = Z.session_bars(m, 60, cache, MCX_OPEN)
    ml, ms, _ = ctx(m, B, 15, cache).macd(12, 26, 9)
    hl, hs, _ = Z.vctx(m, bh, cache, "h60").macd(12, 26, 9)
    out = []
    for j in range(1, len(b.c)):
        if Z.ist_min(b, j) >= T(23, 0):
            continue
        kh = Z.last_done(bh, int(b.i1[j]))
        if kh < 0 or not (np.isfinite(hl[kh]) and np.isfinite(hs[kh])):
            continue
        side_h = 1 if hl[kh] > hs[kh] else (-1 if hl[kh] < hs[kh] else 0)
        if side_h > 0 and Z.cross_up(ml, ms, j):
            out.append(sig(b, j, 1, _swing(b, j, 6, 1) * 0.999, "CI01_MACD_LONG", info={"target_frac": 0.009}))
        elif side_h < 0 and Z.cross_dn(ml, ms, j):
            out.append(sig(b, j, -1, _swing(b, j, 6, -1) * 1.001, "CI01_MACD_SHORT", info={"target_frac": 0.009}))
    return sorted_out(out)


def ci01_x(m, B, p, cache):
    b = B[15]
    ml, ms, _ = ctx(m, B, 15, cache).macd(12, 26, 9)
    xl, xs = Z.flags(len(b.c))
    for j in range(1, len(b.c)):
        xl[j] = Z.cross_dn(ml, ms, j)
        xs[j] = Z.cross_up(ml, ms, j)
    return XExits(target_r=None, xbars=b, xlong=xl, xshort=xs)


# ═══ CI-02 crude: 66 moving-average slope + Stochastic (14, 2) 75 / 35 re-cross, 1:2 ═══════════════════════════

def ci02(m, B, p, cache):
    b = B[15]
    s66 = ctx(m, B, 15, cache).sma(66)
    K, _ = I.stochastic(b, 14, 2, 3)
    out = []
    for j in range(5, len(b.c)):
        im = Z.ist_min(b, j)
        if not (T(9, 15) <= im < T(23, 0)) or not (np.isfinite(s66[j]) and np.isfinite(s66[j - 5])):
            continue
        slope = s66[j] - s66[j - 5]
        exp = int(b.i1[j]) + 45
        if slope < -0.0005 * b.c[j] and K[j - 1] >= 75 > K[j]:
            out.append(sig(b, j, -1, max(b.h[j], b.h[j - 1]) * 1.0002, "CI02_STOCH75_SHORT",
                           entry_stop=float(b.l[j]), expire_k=exp))
        elif slope > 0.0005 * b.c[j] and K[j - 1] <= 35 < K[j]:
            out.append(sig(b, j, 1, min(b.l[j], b.l[j - 1]) * 0.9998, "CI02_STOCH35_LONG",
                           entry_stop=float(b.h[j]), expire_k=exp))
    return sorted_out(out)


def ci02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ CI-03 crude: the 17:30-18:00 IST candle, its 50% level, 3-minute break after 18:00, 1:2 ═══════════════════

def ci03(m, B, p, cache):
    b = B[3]
    s20 = ctx(m, B, 3, cache).sma(20)
    out = []
    for d in range(m.n_days):
        w = Z.window_hl(m, d, T(17, 30), T(18, 0))
        if w is None or w[3] - w[2] < 20:
            continue
        H, L = w[0], w[1]
        mid = (H + L) / 2
        for j in bars_of_day(b, d):
            im = Z.ist_min(b, j)
            if im < T(18, 0) or im >= T(23, 0) or j < 1 or b.day[j - 1] != b.day[j] or not np.isfinite(s20[j]):
                continue
            if b.c[j - 1] <= H < b.c[j] and b.c[j] > mid and b.c[j] > s20[j]:
                out.append(sig(b, j, 1, min(b.l[j - 1], b.l[j]) * 0.9998, "CI03_530_LONG"))
            elif b.c[j - 1] >= L > b.c[j] and b.c[j] < mid and b.c[j] < s20[j]:
                out.append(sig(b, j, -1, max(b.h[j - 1], b.h[j]) * 1.0002, "CI03_530_SHORT"))
    return sorted_out(out)


def ci03_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ CI-04 crude: Donchian 200 extreme on 20 minutes, 5-minute EMA 9 reversal, half at 0.7%, EMA 9/100 exit ════

def ci04(m, B, p, cache):
    b20 = Z.session_bars(m, 20, cache, MCX_OPEN)
    up, dn = Z.donchian_offset(b20, 200, 3)
    ev_up = [int(b20.i1[i]) for i in range(len(b20.c)) if np.isfinite(up[i]) and b20.c[i] > up[i]]
    ev_dn = [int(b20.i1[i]) for i in range(len(b20.c)) if np.isfinite(dn[i]) and b20.c[i] < dn[i]]
    ev_up, ev_dn = np.array(ev_up, np.int64), np.array(ev_dn, np.int64)
    b = B[5]
    c5 = ctx(m, B, 5, cache)
    e9, e30, e100 = c5.ema(9), c5.ema(30), c5.ema(100)
    out = []

    def recent(ev, row):
        k = int(np.searchsorted(ev, row, "right")) - 1
        return k >= 0 and row - int(ev[k]) <= 360

    for j in range(1, len(b.c)):
        im = Z.ist_min(b, j)
        if not (T(9, 15) <= im < T(23, 0)) or not np.isfinite(e100[j]):
            continue
        row = int(b.i1[j])
        if recent(ev_up, row) and Z.cross_dn(e9, e30, j) and e9[j] < e100[j]:
            out.append(sig(b, j, -1, _swing(b, j, 12, -1) * 1.001, "CI04_DONCH_SHORT",
                           info={"partial_px": float(b.c[j]) * (1 - 0.007)}))
        elif recent(ev_dn, row) and Z.cross_up(e9, e30, j) and e9[j] > e100[j]:
            out.append(sig(b, j, 1, _swing(b, j, 12, 1) * 0.999, "CI04_DONCH_LONG",
                           info={"partial_px": float(b.c[j]) * (1 + 0.007)}))
    return sorted_out(out)


def ci04_x(m, B, p, cache):
    b = B[5]
    c5 = ctx(m, B, 5, cache)
    e9, e100 = c5.ema(9), c5.ema(100)
    xl, xs = Z.flags(len(b.c))
    for j in range(1, len(b.c)):
        xl[j] = Z.cross_dn(e9, e100, j)
        xs[j] = Z.cross_up(e9, e100, j)
    return XExits(target_r=None, partial_px=True, xbars=b, xlong=xl, xshort=xs)


# ═══ CI-05 crude: 15-minute two-candle rejection after 12:00 IST, 1.5R ════════════════════════════════════════

def ci05(m, B, p, cache):
    b = B[15]
    out = []
    for j in range(9, len(b.c)):
        im = Z.ist_min(b, j)
        if not (T(12, 0) <= im < T(23, 0)) or b.day[j - 1] != b.day[j]:
            continue
        exp = int(b.i1[j]) + 45
        if green(b, j - 1) and b.h[j - 1] >= b.h[j - 8:j].max() and red(b, j) and b.h[j] > b.h[j - 1]:
            out.append(sig(b, j, -1, float(b.h[j]) * 1.0004, "CI05_REJECT_SHORT", entry_stop=float(b.l[j]), expire_k=exp))
        elif red(b, j - 1) and b.l[j - 1] <= b.l[j - 8:j].min() and green(b, j) and b.l[j] < b.l[j - 1]:
            out.append(sig(b, j, 1, float(b.l[j]) * 0.9996, "CI05_REJECT_LONG", entry_stop=float(b.h[j]), expire_k=exp))
    return sorted_out(out)


def ci05_x(m, B, p, cache):
    return XExits(target_r=1.5)


# ═══ CI-06 crude: RSI 60 / 40 cross on the SMA 89 side, trailed stop-entry, 18:00-22:00 IST, no Wednesdays ═══════

def ci06(m, B, p, cache):
    b = B[15]
    c15 = ctx(m, B, 15, cache)
    s89, r = c15.sma(89), c15.rsi(14)
    n = len(b.c)
    out = []
    for j in range(1, n):
        im = Z.ist_min(b, j)
        if not (T(18, 0) <= im < T(22, 0)) or weekday(m, int(b.day[j])) == 2:
            continue
        if not (np.isfinite(s89[j]) and np.isfinite(r[j]) and np.isfinite(r[j - 1])):
            continue
        for side in (1, -1):
            trig = (r[j - 1] <= 60 < r[j] and b.c[j] > s89[j]) if side > 0 else (r[j - 1] >= 40 > r[j] and b.c[j] < s89[j])
            if not trig:
                continue
            stop = float(b.l[j]) * 0.9998 if side > 0 else float(b.h[j]) * 1.0002
            lvl = float(b.h[j]) if side > 0 else float(b.l[j])
            grp = f"CI06-{int(b.i1[j])}-{side}"
            setup = "CI06_RSI60_LONG" if side > 0 else "CI06_RSI40_SHORT"
            out.append(sig(b, j, side, stop, setup, entry_stop=lvl, expire_k=int(b.i1[j]) + 15, info={"group": grp}))
            for i in range(j + 1, min(j + 9, n)):
                if b.day[i] != b.day[j] or Z.ist_min(b, i) >= T(22, 0):
                    break
                ok = (b.c[i] > s89[i] and r[i] > 50) if side > 0 else (b.c[i] < s89[i] and r[i] < 50)
                if not ok:
                    break
                lvl = min(lvl, float(b.h[i])) if side > 0 else max(lvl, float(b.l[i]))
                out.append(sig(b, i, side, stop, setup, entry_stop=lvl, expire_k=int(b.i1[i]) + 15, info={"group": grp}))
    return sorted_out(out)


def ci06_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ CI-07 natural gas: MFI(140) near 40 / 60 + Supertrend side + EMA 9/26 cross (1 hour), 0.8% ══════════════════

def ci07(m, B, p, cache):
    bh = Z.session_bars(m, 60, cache, MCX_OPEN)
    cx = Z.vctx(m, bh, cache, "h60")
    mf = Z.mfi(bh, cx.vol(), 140)
    line, dirn = I.supertrend(bh, 10, 3.0)
    e9, e26 = cx.ema(9), cx.ema(26)
    out = []
    for j in range(10, len(bh.c)):
        if not (np.isfinite(line[j]) and np.isfinite(e26[j])) or Z.ist_min(bh, j) >= T(23, 0):
            continue
        win = mf[j - 9:j + 1]
        if not np.isfinite(win).any():
            continue
        for side in (1, -1):
            zone = np.nanmin(win) <= 42 if side > 0 else np.nanmax(win) >= 58
            now = dirn[j] == side and (e9[j] - e26[j]) * side > 0
            before = dirn[j - 1] == side and (e9[j - 1] - e26[j - 1]) * side > 0
            crossed = any((Z.cross_up(e9, e26, x) if side > 0 else Z.cross_dn(e9, e26, x)) for x in range(j - 2, j + 1))
            if zone and now and not before and crossed:
                out.append(sig(bh, j, side, float(line[j]), "CI07_MFI_ST_LONG" if side > 0 else "CI07_MFI_ST_SHORT",
                               info={"target_frac": 0.008}))
    return sorted_out(out)


def ci07_x(m, B, p, cache):
    bh = Z.session_bars(m, 60, cache, MCX_OPEN)
    cx = Z.vctx(m, bh, cache, "h60")
    line, dirn = I.supertrend(bh, 10, 3.0)
    e9, e26 = cx.ema(9), cx.ema(26)
    xl = (dirn < 0) | (e9 < e26)
    xs = (dirn > 0) | (e9 > e26)
    return XExits(target_r=None, xbars=bh, xlong=xl, xshort=xs, max_hold=3 * 870)


# ═══ CI-08 crude: 6.5% stretch from the 200 average + slow Stochastic RSI turn (15 minutes), 1.5% ═══════════════

def ci08(m, B, p, cache):
    b = B[15]
    c15 = ctx(m, B, 15, cache)
    s200 = c15.sma(200)
    with np.errstate(invalid="ignore", divide="ignore"):
        dma = (b.c / s200 - 1) * 100
    K, D = Z.stoch_rsi(b.c, 140, 140, 30, 30)
    out = []
    for j in range(21, len(b.c)):
        if Z.ist_min(b, j) >= T(23, 0):
            continue
        win = dma[j - 20:j + 1]
        if not np.isfinite(win).any():
            continue
        if Z.cross_dn(K, D, j) and np.nanmax(win) >= 6.5:
            out.append(sig(b, j, -1, float(b.c[j]) * 1.02, "CI08_STRETCH_SHORT",
                           info={"stop_frac": 0.02, "target_frac": 0.015}))
        elif Z.cross_up(K, D, j) and np.nanmin(win) <= -6.5:
            out.append(sig(b, j, 1, float(b.c[j]) * 0.98, "CI08_STRETCH_LONG",
                           info={"stop_frac": 0.02, "target_frac": 0.015}))
    return sorted_out(out)


def ci08_x(m, B, p, cache):
    b = B[15]
    c15 = ctx(m, B, 15, cache)
    e5, e15 = c15.ema(5), c15.ema(15)
    K, D = Z.stoch_rsi(b.c, 140, 140, 30, 30)
    xl, xs = Z.flags(len(b.c))
    for j in range(1, len(b.c)):
        xl[j] = Z.cross_dn(e5, e15, j) or Z.cross_dn(K, D, j)
        xs[j] = Z.cross_up(e5, e15, j) or Z.cross_up(K, D, j)
    return XExits(target_r=None, xbars=b, xlong=xl, xshort=xs)


# ═══ CI-10 silver micro: the 18:30 IST 30-minute candle, 0.04% buffer, stop and reverse once, 1:2 ═══════════════

def ci10(m, B, p, cache):
    b = B[5]
    out = []
    for d in range(m.n_days):
        w = Z.window_hl(m, d, T(18, 30), T(19, 0))
        if w is None or w[3] - w[2] < 20:
            continue
        H, L = w[0], w[1]
        buf = 0.0004 * (H + L) / 2
        up_lvl, dn_lvl = H + buf, L - buf
        for j in bars_of_day(b, d):
            im = Z.ist_min(b, j)
            if im < T(18, 55) or im >= T(23, 0):
                continue
            exp = int(b.i1[j]) + 5
            out.append(sig(b, j, 1, dn_lvl, "CI10_SILVER_LONG", entry_stop=up_lvl, expire_k=exp, info={"group": f"{d}L"}))
            out.append(sig(b, j, -1, up_lvl, "CI10_SILVER_SHORT", entry_stop=dn_lvl, expire_k=exp, info={"group": f"{d}S"}))
    return sorted_out(out)


def ci10_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ CI-12 crude: the first 'bald' green candle (no lower wick) after a red / doji series, 15-minute scalp ══════════

def ci12(m, B, p, cache):
    b = B[15]
    s20 = ctx(m, B, 15, cache).sma(20)
    out = []
    for j in range(8, len(b.c)):
        im = Z.ist_min(b, j)
        if not (T(9, 15) <= im < T(23, 0)) or not (np.isfinite(s20[j]) and np.isfinite(s20[j - 4])):
            continue
        if not green(b, j) or b.o[j] - b.l[j] > 0.0002 * b.c[j]:
            continue
        r = (b.h[j] - b.l[j]) / b.c[j]
        if not (0.003 <= r <= 0.0055):
            continue
        if not (s20[j] > s20[j - 4] and b.l[j] > b.l[j - 8]):
            continue
        prev = range(j - 3, j)
        reds = all(red(b, x) for x in prev)
        dojis = all(rng(b, x) > 0 and body(b, x) <= 0.3 * rng(b, x) for x in prev)
        if not (reds or dojis):
            continue
        out.append(sig(b, j, 1, float(b.l[j]) * 0.999, "CI12_BALD_LONG", info={"target_frac": 0.0045}))
    return sorted_out(out)


def ci12_x(m, B, p, cache):
    return XExits(target_r=None, max_hold=45)
