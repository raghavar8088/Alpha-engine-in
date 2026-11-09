"""The Indian-market strategies of the 20-channel study (analyses/<channel>.md; the "Code [A]" lines are the exact rules):
NIFTY / BANKNIFTY index minutes, the NSE 5-minute stock pool (NSE5 / NSE15), the NSE daily pool (NSED) and daily NIFTY
(NIFTY_D). Conventions as in zc_common: completed bars only, orders from the next row, pivots only once confirmed.
The index has no volume (one unit a row), so its "VWAP" is the session's average typical price."""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import (bars_of_day, bear_engulf, body, bull_engulf, ctx, flags_cross, green, last_done, lw,  # noqa: F401
                       red, rng, sig, uw)
from yc_engine import XExits
from yt_engine import Exits, Signal

import zc_common as Z
from zc_common import NSE_OPEN, actx, anchored_bars, prev_day_hlc, sorted_out

T = lambda h, mi: h * 60 + mi  # noqa: E731


def _vwap(m, b, cache, name):
    key = ("vwap", name)
    if key not in cache:
        cache[key] = I.session_vwap(m, b)
    return cache[key]


def _bar_at(b, d, minute):
    """The bar of day d that starts exactly at `minute` IST (None if missing)."""
    for j in bars_of_day(b, d):
        if int(b.ist0[j]) == minute:
            return j
        if int(b.ist0[j]) > minute:
            return None
    return None


def _last_row_before(m, d, minute):
    """The last row of day d that starts before `minute` IST."""
    a, z = int(m.d0[d]), int(m.d1[d])
    ist = m.ist[a:z]
    idx = np.flatnonzero(ist < minute)
    return a + int(idx[-1]) if len(idx) else None


def _day_open(m, d):
    return float(m.o[m.d0[d]])


# ═══ Dhan ═══════════════════════════════════════════════════════════════════════════════════

def dh01(m, B, p, cache):
    """VWAP pullback with an engulfing turn after a sweep (NIFTY 5-minute, 09:15-12:00, 1-hour EMA 20 side)."""
    b, bh = B[5], B[60]
    vw = _vwap(m, b, cache, 5)
    eh = ctx(m, B, 60, cache).ema(20)
    out = []
    for d in range(m.n_days):
        crosses = 0
        rows = list(bars_of_day(b, d))
        for i, j in enumerate(rows):
            if i >= 1 and np.isfinite(vw[j]) and np.isfinite(vw[j - 1]) and (b.c[j] - vw[j]) * (b.c[j - 1] - vw[j - 1]) < 0:
                crosses += 1
            if i < 8 or int(b.ist0[j]) >= T(11, 55) or crosses >= 4 or not np.isfinite(vw[j]):
                continue
            h = last_done(bh, int(b.i1[j]))
            if h < 0 or not np.isfinite(eh[h]):
                continue
            up = bh.c[h] > eh[h]
            near = b.l[j] <= vw[j] * 1.001 and b.h[j] >= vw[j] * 0.999
            if not near:
                continue
            ref_lo, ref_hi = b.l[j - 7:j - 1].min(), b.h[j - 7:j - 1].max()
            if up and bull_engulf(b, j) and min(b.l[j], b.l[j - 1]) < ref_lo:
                out.append(sig(b, j, 1, float(min(b.l[j], b.l[j - 1])), "DH01_VWAP_SWEEP_LONG"))
            elif (not up) and bear_engulf(b, j) and max(b.h[j], b.h[j - 1]) > ref_hi:
                out.append(sig(b, j, -1, float(max(b.h[j], b.h[j - 1])), "DH01_VWAP_SWEEP_SHORT"))
    return sorted_out(out)


def dh01_x(m, B, p, cache):
    return Exits(target_r=2.0)


def movers_context(pool) -> dict:
    """{date: (top 10 gainers, top 10 losers)} of the pool by the change from the previous close to the 09:20 close."""
    by: dict = {}
    for m in pool:
        for d in range(1, m.n_days):
            if not m.prev_ok[d]:
                continue
            a, z = int(m.d0[d]), int(m.d1[d])
            idx = np.flatnonzero(m.ist[a:z] == NSE_OPEN)          # the 09:15 five-minute row closes at 09:20
            if not len(idx):
                continue
            pc = float(m.c[m.d1[d - 1] - 1])
            if pc > 0:
                by.setdefault(str(m.date[d]), []).append((float(m.c[a + int(idx[0])]) / pc - 1, m.name))
    out = {}
    for day, rows in by.items():
        ups = sorted((r for r in rows if r[0] > 0), key=lambda x: (-x[0], x[1]))[:10]
        dns = sorted((r for r in rows if r[0] < 0), key=lambda x: (x[0], x[1]))[:10]
        out[day] = ({s for _, s in ups}, {s for _, s in dns})
    return out


def dh02(m, B, p, cache):
    """9:20 top movers: VWAP pullback, inside bar, engulfing break (NSE 5-minute pool). p["ctx"]["movers"]."""
    cx = (p.get("ctx") or {}).get("movers") or {}
    b = B[5]
    vw = _vwap(m, b, cache, 5)
    out = []
    for d in range(m.n_days):
        pick = cx.get(str(m.date[d]))
        if not pick:
            continue
        side = 1 if m.name in pick[0] else (-1 if m.name in pick[1] else 0)
        if not side:
            continue
        for j in bars_of_day(b, d):
            if j - 2 < int(b.b0[d]) or not (T(9, 25) <= int(b.ist0[j]) < T(11, 55)) or not np.isfinite(vw[j - 1]):
                continue
            q = j - 1
            if not (b.h[q] <= b.h[q - 1] and b.l[q] >= b.l[q - 1]):
                continue
            lo_b, hi_b = min(b.o[q - 1], b.c[q - 1]), max(b.o[q - 1], b.c[q - 1])
            if side > 0 and b.c[q] >= vw[q] and b.l[q] <= vw[q] * 1.002 and green(b, j) and b.c[j] > b.h[q] \
                    and b.o[j] <= lo_b and b.c[j] >= hi_b:
                out.append(sig(b, j, 1, float(min(b.l[q], vw[j])), "DH02_MOVER_INSIDE_LONG"))
            elif side < 0 and b.c[q] <= vw[q] and b.h[q] >= vw[q] * 0.998 and red(b, j) and b.c[j] < b.l[q] \
                    and b.o[j] >= hi_b and b.c[j] <= lo_b:
                out.append(sig(b, j, -1, float(max(b.h[q], vw[j])), "DH02_MOVER_INSIDE_SHORT"))
    return sorted_out(out)


def dh02_x(m, B, p, cache):
    return XExits(target_r=3.0, partial_at_r=2.0)


def _is_doji(o, h, l, c):
    r = h - l
    if not r > 0:
        return False
    return abs(c - o) <= 0.35 * r and (h - max(o, c)) >= 0.15 * r and (min(o, c) - l) >= 0.15 * r


def dh03(m, B, p, cache):
    """3-minute Heikin Ashi pullback scalp with EMA 100 (NIFTY, 10:00-12:00): skip two trend candles, the doji triggers."""
    b = B[3]
    hb = I.HABars(b)
    e100 = actx(m, hb, cache, "ha3").ema(100)
    hg = hb.c > hb.o
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        for i, t in enumerate(rows):
            if i < 4 or not (T(10, 0) <= int(b.ist0[t]) < T(11, 57)) or not np.isfinite(e100[t]):
                continue
            if not _is_doji(hb.o[t], hb.h[t], hb.l[t], hb.c[t]):
                continue
            for side in (1, -1):
                if (hb.c[t] - e100[t]) * side <= 0:
                    continue
                trend = hg if side > 0 else ~hg
                # walk back: trend-colour candles (at least two, at most six bars since the second), then the pullback
                x = t - 1
                n_tr = 0
                while x >= rows[0] and trend[x] and not _is_doji(hb.o[x], hb.h[x], hb.l[x], hb.c[x]):
                    n_tr += 1
                    x -= 1
                if not (2 <= n_tr <= 7) or x < rows[0] or trend[x]:
                    continue
                if side > 0:
                    out.append(sig(b, t, 1, float(hb.l[t]), "DH03_HA_DOJI_LONG", entry_stop=float(hb.h[t]),
                                   expire_k=int(b.i1[min(t + 1, rows[-1])])))
                else:
                    out.append(sig(b, t, -1, float(hb.h[t]), "DH03_HA_DOJI_SHORT", entry_stop=float(hb.l[t]),
                                   expire_k=int(b.i1[min(t + 1, rows[-1])])))
    return sorted_out(out)


def dh03_x(m, B, p, cache):
    return Exits(target_r=1.0)


def dh04(m, B, p, cache):
    """First 30 minutes range, break, pullback, confirmation (NIFTY 5-minute, gap 0.2-1.2%, 2R)."""
    b = B[5]
    ra = ctx(m, B, 5, cache).range_avg(20)
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        pc = float(m.c[m.d1[d - 1] - 1])
        gap = abs(_day_open(m, d) / pc - 1) if pc > 0 else np.nan
        if not (0.002 <= gap <= 0.012):
            continue
        rows = list(bars_of_day(b, d))
        first = [j for j in rows if int(b.ist0[j]) < T(9, 45)]
        if len(first) < 6:
            continue
        H, L = float(b.h[first].max()), float(b.l[first].min())
        broke = 0
        pull = None
        for j in rows:
            if int(b.ist0[j]) < T(9, 45):
                continue
            if int(b.ist0[j]) >= T(11, 25):
                break
            if broke == 0:
                if b.c[j] > H:
                    broke = 1
                elif b.c[j] < L:
                    broke = -1
                continue
            if broke > 0 and b.c[j] < L:
                broke, pull = -1, None
                continue
            if broke < 0 and b.c[j] > H:
                broke, pull = 1, None
                continue
            counter = red(b, j) if broke > 0 else green(b, j)
            if counter:
                pull = j
                continue
            if pull is None:
                continue
            big = rng(b, j) > 0 and body(b, j) >= 0.6 * rng(b, j)
            if not big or (np.isfinite(ra[j]) and rng(b, j) > 2.5 * ra[j]):
                continue
            if broke > 0 and green(b, j) and b.c[j] > b.h[pull]:
                out.append(sig(b, j, 1, float(b.l[j]), "DH04_FIRST30_LONG"))
                pull = None
            elif broke < 0 and red(b, j) and b.c[j] < b.l[pull]:
                out.append(sig(b, j, -1, float(b.h[j]), "DH04_FIRST30_SHORT"))
                pull = None
    return sorted_out(out)


def dh04_x(m, B, p, cache):
    return Exits(target_r=2.0)


def _orb_filters(m, B, cache, tf=5):
    c = ctx(m, B, tf, cache)
    a, _, _ = c._get(("adx", 14), lambda: I.adx(B[tf], 14))
    return c.rsi(14), a, c.vol(), c.vol_avg(20)


def dh05(m, B, p, cache):
    """9:15-9:20 opening range breakout with a 1-1.5% day change, RSI 55, rising ADX, volume; Supertrend (7, 2) trail."""
    b = B[5]
    rsi, adx, vol, va = _orb_filters(m, B, cache)
    stl, std = ctx(m, B, 5, cache).supertrend(7, 2.0)
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        j0 = _bar_at(b, d, NSE_OPEN)
        if j0 is None:
            continue
        pc = float(m.c[m.d1[d - 1] - 1])
        done = set()
        for j in range(j0 + 1, int(b.b1[d])):
            if int(b.ist0[j]) >= T(10, 25):
                break
            if not (np.isfinite(rsi[j]) and np.isfinite(adx[j]) and np.isfinite(adx[j - 1]) and np.isfinite(stl[j])):
                continue
            chg = b.c[j] / pc - 1
            okv = np.isfinite(va[j]) and vol[j] > va[j]
            rising = adx[j] > adx[j - 1]
            if 1 not in done and b.c[j] > b.h[j0] and 0.01 < chg < 0.015 and b.c[j] > b.o[j0] and rsi[j] > 55 and rising and okv:
                done.add(1)
                if std[j] > 0 and stl[j] < b.c[j]:
                    out.append(sig(b, j, 1, float(stl[j]), "DH05_ORB_LONG", info={"partial_px": float(b.c[j] * 1.007)}))
            if -1 not in done and b.c[j] < b.l[j0] and -0.015 < chg < -0.01 and b.c[j] < b.o[j0] and rsi[j] < 45 and rising and okv:
                done.add(-1)
                if std[j] < 0 and stl[j] > b.c[j]:
                    out.append(sig(b, j, -1, float(stl[j]), "DH05_ORB_SHORT", info={"partial_px": float(b.c[j] * 0.993)}))
    return sorted_out(out)


def dh05_x(m, B, p, cache):
    b = B[5]
    _, std = ctx(m, B, 5, cache).supertrend(7, 2.0)
    return XExits(target_r=None, partial_px=True, xbars=b, xlong=std < 0, xshort=std > 0)


def dh06(m, B, p, cache):
    """"9:20 BYR": a 1-4% gainer above Supertrend with RSI 55 and volume, buy the 9:20 high, +0.65%."""
    b = B[5]
    rsi, _, vol, va = _orb_filters(m, B, cache)
    _, std = ctx(m, B, 5, cache).supertrend(10, 3.0)
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        j = _bar_at(b, d, NSE_OPEN)
        if j is None or not np.isfinite(rsi[j]):
            continue
        pc = float(m.c[m.d1[d - 1] - 1])
        chg = b.c[j] / pc - 1
        if not (0.01 <= chg <= 0.04 and b.c[j] > b.o[j] and std[j] > 0 and np.isfinite(va[j]) and vol[j] > va[j] and rsi[j] > 55):
            continue
        last = _last_row_before(m, d, T(10, 30))
        if last is None or last <= int(b.i1[j]):
            continue
        out.append(sig(b, j, 1, float(b.l[j]), "DH06_BYR_LONG", entry_stop=float(b.h[j]), expire_k=int(last),
                       info={"target_frac": 0.0065}))
    return sorted_out(out)


def dh06_x(m, B, p, cache):
    return Exits(target_r=None)


def dh07(m, B, p, cache):
    """Supertrend side + Fisher Transform cross below zero, entered near zero + rising ADX (NIFTY 5-minute index proxy)."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    stl, std = c.supertrend(10, 3.0)
    fi, tr = c._get(("fisher", 9), lambda: Z.fisher(b, 9))
    adx, _, _ = c._get(("adx", 14), lambda: I.adx(b, 14))
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        armed = {1: None, -1: None}
        for j in rows:
            if j < 22 or not (np.isfinite(fi[j]) and np.isfinite(tr[j]) and np.isfinite(fi[j - 1]) and np.isfinite(tr[j - 1])):
                continue
            if fi[j - 1] <= tr[j - 1] and fi[j] > tr[j] and fi[j] < 0:
                armed[1] = j
            if fi[j - 1] >= tr[j - 1] and fi[j] < tr[j] and fi[j] > 0:
                armed[-1] = j
            if int(b.ist0[j]) >= T(15, 0):
                continue
            w = fi[j - 19:j + 1]
            if not np.all(np.isfinite(w)) or w.max() - w.min() < 1.5:
                continue
            if not (np.isfinite(adx[j]) and np.isfinite(adx[j - 2]) and adx[j] > adx[j - 1] > adx[j - 2]):
                continue
            nxt = int(b.i1[min(j + 1, rows[-1])])
            x = armed[1]
            if x is not None and j - x <= 6 and fi[j] >= -0.3 and fi[j] > tr[j] and std[j] > 0 and b.c[j] > stl[j]:
                out.append(sig(b, j, 1, float(b.l[j - 1]), "DH07_ST_FISHER_LONG", entry_stop=float(b.h[j]), expire_k=nxt))
                armed[1] = None
            x = armed[-1]
            if x is not None and j - x <= 6 and fi[j] <= 0.3 and fi[j] < tr[j] and std[j] < 0 and b.c[j] < stl[j]:
                out.append(sig(b, j, -1, float(b.h[j - 1]), "DH07_ST_FISHER_SHORT", entry_stop=float(b.l[j]), expire_k=nxt))
                armed[-1] = None
    return sorted_out(out)


def dh07_x(m, B, p, cache):
    b = B[5]
    stl, std = ctx(m, B, 5, cache).supertrend(10, 3.0)
    flat = np.zeros(len(stl), bool)
    for j in range(6, len(stl)):
        w = stl[j - 6:j + 1]
        flat[j] = bool(np.all(np.isfinite(w)) and w.max() - w.min() <= 1e-9 * max(1.0, abs(w[-1])))
    return XExits(target_r=None, xbars=b, xlong=(std < 0) | flat, xshort=(std > 0) | flat)


def dh08(m, B, p, cache):
    """1-minute box breakout scalp with OCO stop orders (NIFTY, 09:30-15:00, 2R, 15-minute time stop)."""
    b = B[1]
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        nxt_ok = -1
        for i, j in enumerate(rows):
            if i < 10 or j < nxt_ok or not (T(9, 30) <= int(b.ist0[j]) < T(15, 0)):
                continue
            w = slice(j - 9, j + 1)
            hi, lo = float(b.h[w].max()), float(b.l[w].min())
            if hi - lo > 0.0005 * b.c[j] or hi <= lo:
                continue
            rr = b.h[w] - b.l[w]
            small = np.sum((rr > 0) & (np.abs(b.c[w] - b.o[w]) <= 0.5 * rr))
            if small < 7:
                continue
            last = int(b.i1[rows[min(i + 10, len(rows) - 1)]])
            alt = Signal(int(b.day[j]), int(b.i1[j]), -1, hi, "DH08_BOX_SHORT", {}, lo, last, None)
            out.append(sig(b, j, 1, lo, "DH08_BOX_LONG", entry_stop=hi, expire_k=last, alt=alt))
            nxt_ok = j + 10
    return sorted_out(out)


def dh08_x(m, B, p, cache):
    return XExits(target_r=2.0, max_hold=15)


# ═══ AbhishekXTrades ═══════════════════════════════════════════════════════════════════════

def ax01(m, B, p, cache):
    """EMA 5/20 cross, one or two counter candles, break of the counter candle within 3 bars (first two crosses a day)."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    e5, e20, a = c.ema(5), c.ema(20), c.atr(14)
    up, dn = flags_cross(e5, e20)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        n_cross = 0
        cross_at = None
        for t in rows:
            if up[t] or dn[t]:
                n_cross += 1
                cross_at = t if n_cross <= 2 else None
            if cross_at is None or int(b.ist0[t]) >= T(14, 25) or t == rows[-1] or not np.isfinite(a[t]):
                continue
            side = 1 if e5[t] > e20[t] else -1
            if (side > 0) != bool(up[cross_at]):
                continue
            counter_c = red if side > 0 else green
            r = next((x for x in range(t, cross_at - 1, -1) if counter_c(b, x)), None)
            if r is None or t - r > 2:
                continue
            run = 0
            x = r
            while x >= rows[0] and counter_c(b, x):
                run += 1
                x -= 1
            if run >= 3:
                continue
            lvl = float(b.h[r] * 1.0002) if side > 0 else float(b.l[r] * 0.9998)
            lo10 = float(b.l[max(rows[0], t - 9):t + 1].min()) if side > 0 else float(b.h[max(rows[0], t - 9):t + 1].max())
            dist = abs(lvl - lo10)
            if dist > 1.5 * a[t]:
                dist /= 2
            stop = lvl - side * dist
            if dist <= 0:
                continue
            out.append(sig(b, t, side, float(stop), "AX01_EMA520_LONG" if side > 0 else "AX01_EMA520_SHORT",
                           entry_stop=lvl, expire_k=int(b.i1[t + 1])))
    return sorted_out(out)


def ax01_x(m, B, p, cache):
    return Exits(target_r=2.0)


def ax02(m, B, p, cache):
    """Previous-day high/low bias, a close through the counter candle's open on 15 minutes; half at 1R, rest to 15:15."""
    b = B[15]
    out = []
    for d in range(1, m.n_days):
        pv = prev_day_hlc(m, b, d)
        if pv is None:
            continue
        PH, PL, _ = pv
        rows = list(bars_of_day(b, d))
        for j in rows[1:]:
            if int(b.ist0[j]) >= T(14, 45):
                break
            for side in (1, -1):
                if (side > 0 and not b.c[j] > PH) or (side < 0 and not b.c[j] < PL):
                    continue
                counter_c = red if side > 0 else green
                r = next((x for x in (j - 1, j - 2) if x >= rows[0] and counter_c(b, x)), None)
                if r is None or any(counter_c(b, x) for x in range(r + 1, j)):
                    continue
                run, x = 0, r
                while x >= rows[0] and counter_c(b, x):
                    run += 1
                    x -= 1
                if run >= 3:
                    continue
                if any((b.c[x] - b.o[r]) * side > 0 for x in range(r + 1, j)):
                    continue                                   # only the first close through the open
                if (b.c[j] - b.o[r]) * side > 0:
                    stop = float(b.l[j] * 0.9997) if side > 0 else float(b.h[j] * 1.0003)
                    out.append(sig(b, j, side, stop, "AX02_PDHL_LONG" if side > 0 else "AX02_PDHL_SHORT"))
    return sorted_out(out)


def ax02_x(m, B, p, cache):
    return XExits(target_r=None, partial_at_r=1.0, partial_be=False)


def ax03(m, B, p, cache):
    """NIFTY 9:30-10:00 range (2nd and 3rd 15-minute candles): OCO stop orders 10:00-14:30, +25 points, stop at the far edge."""
    b = B[15]
    out = []
    for d in range(m.n_days):
        j2, j3 = _bar_at(b, d, T(9, 30)), _bar_at(b, d, T(9, 45))
        if j2 is None or j3 is None:
            continue
        R, S = float(max(b.h[j2], b.h[j3])), float(min(b.l[j2], b.l[j3]))
        last = _last_row_before(m, d, T(14, 30))
        if last is None or last <= int(b.i1[j3]) or R <= S:
            continue
        alt = Signal(int(b.day[j3]), int(b.i1[j3]), -1, R, "AX03_RANGE_SHORT", {}, S, int(last), None)
        out.append(sig(b, j3, 1, S, "AX03_RANGE_LONG", entry_stop=R, expire_k=int(last), alt=alt))
    return sorted_out(out)


def ax03_x(m, B, p, cache):
    return Exits(target_r=None, target_abs=25.0)


def ax04(m, B, p, cache):
    """"All-touch candle" (EMA 5/9/15 + SMA 20) on 15 minutes before 10:00, 1:1, one stop-and-reverse."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    L4 = np.vstack([c.ema(5), c.ema(9), c.ema(15), c.sma(20)])
    a = c.atr(14)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        for j in rows:
            if int(b.ist0[j]) >= T(10, 0):
                break
            col = L4[:, j]
            if not (np.all(np.isfinite(col)) and np.isfinite(a[j])):
                continue
            touch = b.l[j] <= col.min() and b.h[j] >= col.max()
            strong = rng(b, j) > 0 and body(b, j) >= 0.4 * rng(b, j) and rng(b, j) >= 0.6 * a[j]
            if not (touch and strong):
                continue
            side = 1 if b.c[j] > col.max() else (-1 if b.c[j] < col.min() else 0)
            if not side:
                continue
            ref = float(b.c[j])
            ext = float(b.l[j]) if side > 0 else float(b.h[j])
            risk = abs(ref - ext)
            if risk > 50:
                risk *= 0.5
            risk = max(risk, 15.0)
            stop = ref - side * risk
            out.append(sig(b, j, side, stop, "AX04_ALLTOUCH_LONG" if side > 0 else "AX04_ALLTOUCH_SHORT",
                           info={"stop_dist": risk}))
            # the stop-and-reverse: the bar that takes the stop (before the 1R target), seen bar by bar
            k0 = int(b.i1[j]) + 1
            if k0 >= int(b.i1[rows[-1]]):
                break
            e = float(m.o[k0])
            st_px, tg_px = e - side * risk, e + side * risk
            for jj in rows[rows.index(j) + 1:]:
                lo, hi = float(b.l[jj]), float(b.h[jj])
                hit_stop = lo <= st_px if side > 0 else hi >= st_px
                hit_tgt = hi >= tg_px if side > 0 else lo <= tg_px
                if hit_stop:
                    if jj != rows[-1] and int(b.ist0[jj]) < T(15, 0):
                        r2 = max(abs(float(b.c[jj]) - (hi if side > 0 else lo)), 15.0)
                        out.append(sig(b, jj, -side, float(b.c[jj]) + side * r2,
                                       "AX04_REVERSE_SHORT" if side > 0 else "AX04_REVERSE_LONG", info={"stop_dist": r2}))
                    break
                if hit_tgt:
                    break
            break
    return sorted_out(out)


def ax04_x(m, B, p, cache):
    return Exits(target_r=1.0)


def _cpr(H, L, C):
    P = (H + L + C) / 3
    BC = (H + L) / 2
    TC = 2 * P - BC
    return P, min(BC, TC), max(BC, TC)


def ax05(m, B, p, cache):
    """CPR relationship bias (today's pivot above / below yesterday's), touch then close beyond the band; 1:2; one
    stop-and-reverse on a close beyond the other side."""
    b = B[15]
    out = []
    for d in range(2, m.n_days):
        if not (m.prev_ok[d] and m.prev_ok[d - 1]):
            continue
        y = prev_day_hlc(m, b, d)
        yy = prev_day_hlc(m, b, d - 1)
        if y is None or yy is None:
            continue
        P, lo, hi = _cpr(*y)
        P0, _, _ = _cpr(*yy)
        bias = 1 if P > P0 else (-1 if P < P0 else 0)
        if not bias:
            continue
        touched = False
        first = None
        for j in bars_of_day(b, d):
            if int(b.ist0[j]) >= T(14, 30):
                break
            touched = touched or (b.h[j] >= lo and b.l[j] <= hi)
            if not touched:
                continue
            if first is None:
                if bias > 0 and b.c[j] > hi:
                    out.append(sig(b, j, 1, float(lo * 0.9998), "AX05_CPR_LONG"))
                    first = 1
                elif bias < 0 and b.c[j] < lo:
                    out.append(sig(b, j, -1, float(hi * 1.0002), "AX05_CPR_SHORT"))
                    first = -1
            else:
                if first > 0 and b.c[j] < lo:
                    out.append(sig(b, j, -1, float(hi * 1.0002), "AX05_CPR_REVERSE_SHORT"))
                    break
                if first < 0 and b.c[j] > hi:
                    out.append(sig(b, j, 1, float(lo * 0.9998), "AX05_CPR_REVERSE_LONG"))
                    break
    return sorted_out(out)


def ax05_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ═══ Stock Investment Academy ══════════════════════════════════════════════════════════════

def _daily_ohlc(m, d):
    a, z = int(m.d0[d]), int(m.d1[d])
    return float(m.o[a]), float(m.h[a:z].max()), float(m.l[a:z].min()), float(m.c[z - 1])


def ab01(m, B, p, cache):
    """Gap day (no overlap with the day before): next day, the first 5-minute close through the gap day's far side."""
    b = B[5]
    out = []
    for d in range(2, m.n_days):
        if not (m.prev_ok[d] and m.prev_ok[d - 1]):
            continue
        _, h1, l1, _ = _daily_ohlc(m, d - 1)
        _, h0, l0, _ = _daily_ohlc(m, d - 2)
        gap = 1 if l1 > h0 else (-1 if h1 < l0 else 0)
        if not gap:
            continue
        for j in bars_of_day(b, d):
            if int(b.ist0[j]) >= T(15, 5):
                break
            if gap > 0 and b.c[j] < l1:
                out.append(sig(b, j, -1, float(b.h[j]), "AB01_GAPUP_FAIL_SHORT"))
                break
            if gap < 0 and b.c[j] > h1:
                out.append(sig(b, j, 1, float(b.l[j]), "AB01_GAPDOWN_FAIL_LONG"))
                break
    return sorted_out(out)


def ab01_x(m, B, p, cache):
    return XExits(target_r=None, partial_at_r=2.0)


def ab02(m, B, p, cache):
    """First two 15-minute candles the same colour, the second closes beyond VWAP: enter at 09:45 (stocks), 1:1."""
    b = B[15]
    vw = _vwap(m, b, cache, 15)
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        j1, j2 = _bar_at(b, d, NSE_OPEN), _bar_at(b, d, T(9, 30))
        if j1 is None or j2 is None or not np.isfinite(vw[j2]):
            continue
        pc = float(m.c[m.d1[d - 1] - 1])
        if pc <= 0 or abs(b.o[j1] / pc - 1) > 0.02:
            continue
        if green(b, j1) and green(b, j2) and b.c[j2] > vw[j2]:
            out.append(sig(b, j2, 1, float(min(vw[j2], b.l[j2])), "AB02_VWAP_TWO_GREEN_LONG"))
        elif red(b, j1) and red(b, j2) and b.c[j2] < vw[j2]:
            out.append(sig(b, j2, -1, float(max(vw[j2], b.h[j2])), "AB02_VWAP_TWO_RED_SHORT"))
    return sorted_out(out)


def ab02_x(m, B, p, cache):
    return Exits(target_r=1.0)


def ab03(m, B, p, cache):
    """EMA 9/21 cross + a healthy confirmation candle within 3 bars (stocks, 15-minute intraday)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e9, e21 = c.ema(9), c.ema(21)
    up, dn = flags_cross(e9, e21)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        for x in rows:
            if not (up[x] or dn[x]):
                continue
            side = 1 if up[x] else -1
            for j in range(x, min(x + 3, rows[-1])):
                if (e9[j] - e21[j]) * side <= 0 or int(b.ist0[j]) >= T(15, 0):
                    break
                r = rng(b, j)
                if not r > 0:
                    continue
                if side > 0:
                    ok = green(b, j) and (body(b, j) >= 0.6 * r or (lw(b, j) > uw(b, j) and b.c[j] >= b.l[j] + 0.5 * r))
                else:
                    ok = red(b, j) and (body(b, j) >= 0.6 * r or (uw(b, j) > lw(b, j) and b.c[j] <= b.h[j] - 0.5 * r))
                if ok:
                    stop = float(min(b.l[j], e9[j])) if side > 0 else float(max(b.h[j], e9[j]))
                    out.append(sig(b, j, side, stop, "AB03_EMA921_LONG" if side > 0 else "AB03_EMA921_SHORT"))
                    break
    return sorted_out(out)


def ab03_x(m, B, p, cache):
    b = B[15]
    c = ctx(m, B, 15, cache)
    up, dn = flags_cross(c.ema(9), c.ema(21))
    return XExits(target_r=3.0, xbars=b, xlong=dn, xshort=up)


def ab04(m, B, p, cache):
    """1-hour close at least 0.5% above the EMA 50 after crossing it (stocks, BTST / swing, long only)."""
    hb = anchored_bars(m, 60, cache, last_slot=5)
    e50 = actx(m, hb, cache, "a60").ema(50)
    out = []
    for j in range(60, len(hb.c)):
        if not np.isfinite(e50[j]):
            continue
        if hb.l[j] <= e50[j] and hb.c[j] >= e50[j] * 1.005:
            out.append(sig(hb, j, 1, float(min(hb.l[j], e50[j])), "AB04_EMA50_HOURLY_LONG"))
    return sorted_out(out)


def ab04_x(m, B, p, cache):
    return XExits(target_r=2.0, max_hold=375)


def ab06(m, B, p, cache, other=None):
    """EMA 9/15 cross + pin bar / full-body / healthy confirmation, NIFTY 5-minute, BANK NIFTY on the same side, 1:1."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    e9, e15 = c.ema(9), c.ema(15)
    up, dn = flags_cross(e9, e15)
    if other is None:
        return []
    om, OB = other
    ob = OB[5]
    key = ("ab06_bn",)
    if key not in cache:
        cache[key] = (I.ema(ob.c, 9), I.ema(ob.c, 15))
    o9, o15 = cache[key]
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        for x in rows:
            if not (up[x] or dn[x]):
                continue
            side = 1 if up[x] else -1
            for j in range(x, min(x + 4, rows[-1])):
                if (e9[j] - e15[j]) * side <= 0 or int(b.ist0[j]) >= T(15, 0):
                    break
                r = rng(b, j)
                if not r > 0 or (min(b.l[j], b.h[j]) - max(e9[j], e15[j]) if side > 0 else min(e9[j], e15[j]) - b.h[j]) < 0:
                    continue
                bd = body(b, j)
                if side > 0:
                    pin = lw(b, j) >= 2 * bd and b.c[j] >= b.h[j] - r / 3
                    full = green(b, j) and bd >= 0.7 * r
                    healthy = green(b, j) and bd >= 0.5 * r and uw(b, j) <= 0.25 * r and lw(b, j) <= 0.25 * r
                else:
                    pin = uw(b, j) >= 2 * bd and b.c[j] <= b.l[j] + r / 3
                    full = red(b, j) and bd >= 0.7 * r
                    healthy = red(b, j) and bd >= 0.5 * r and uw(b, j) <= 0.25 * r and lw(b, j) <= 0.25 * r
                if not (pin or full or healthy):
                    continue
                q = last_done(ob, int(om.t.searchsorted(int(m.t[b.i1[j]]), "right")) - 1)
                if q < 0 or not (np.isfinite(o9[q]) and np.isfinite(o15[q])) or (o9[q] - o15[q]) * side <= 0:
                    break
                out.append(sig(b, j, side, float(b.l[j]) if side > 0 else float(b.h[j]),
                               "AB06_EMA915_LONG" if side > 0 else "AB06_EMA915_SHORT"))
                break
    return sorted_out(out)


def ab06_x(m, B, p, cache):
    return Exits(target_r=1.0)


# ═══ The Trading School ════════════════════════════════════════════════════════════════════

def ts01(m, B, p, cache):
    """First 1-hour candle's wick zones: 5-minute break-and-confirm or reject-and-confirm after 10:15, 1:2."""
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        first = [j for j in rows if int(b.ist0[j]) < T(10, 15)]
        if len(first) < 12:
            continue
        o1, c1 = float(b.o[first[0]]), float(b.c[first[-1]])
        h1, l1 = float(b.h[first].max()), float(b.l[first].min())
        if not (h1 > l1 and abs(c1 - o1) >= 0.5 * (h1 - l1)):
            continue
        up_lo, dn_hi = max(o1, c1), min(o1, c1)
        later = [j for j in rows if T(10, 15) <= int(b.ist0[j]) < T(14, 25)]
        for i, j in enumerate(later[:-1]):
            if not np.isfinite(a[j]):
                continue
            strong = rng(b, j) >= 0.8 * a[j] and body(b, j) >= 0.6 * rng(b, j)
            if not strong:
                continue
            k = later[i + 1]
            if green(b, j) and b.c[j] > h1 and b.c[k] > b.h[j]:
                out.append(sig(b, k, 1, float(b.l[j] * 0.9998), "TS01_BREAK_LONG"))
            elif red(b, j) and b.c[j] < l1 and b.c[k] < b.l[j]:
                out.append(sig(b, k, -1, float(b.h[j] * 1.0002), "TS01_BREAK_SHORT"))
            elif red(b, j) and b.h[j] >= up_lo and b.c[j] < up_lo and b.c[k] < b.l[j]:
                out.append(sig(b, k, -1, float(max(h1, b.h[j], b.h[k]) * 1.0002), "TS01_REJECT_SHORT"))
            elif green(b, j) and b.l[j] <= dn_hi and b.c[j] > dn_hi and b.c[k] > b.h[j]:
                out.append(sig(b, k, 1, float(min(l1, b.l[j], b.l[k]) * 0.9998), "TS01_REJECT_LONG"))
    return sorted_out(out)


def ts01_x(m, B, p, cache):
    return Exits(target_r=2.0)


def ts02(m, B, p, cache):
    """First 1-hour range: a later 1-hour candle sweeps its high (low) and closes back inside -> fade; target min(2R, far side)."""
    b = B[60]
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        if len(rows) < 2 or int(b.ist0[rows[0]]) != NSE_OPEN:
            continue
        H, L = float(b.h[rows[0]]), float(b.l[rows[0]])
        for j in rows[1:]:
            if b.h[j] > H and L < b.c[j] < H:
                st = float(b.h[j])
                tp = max(float(b.c[j]) - 2 * (st - float(b.c[j])), L)
                out.append(sig(b, j, -1, st, "TS02_SWEEP_HIGH_SHORT", target_px=tp))
            elif b.l[j] < L and L < b.c[j] < H:
                st = float(b.l[j])
                tp = min(float(b.c[j]) + 2 * (float(b.c[j]) - st), H)
                out.append(sig(b, j, 1, st, "TS02_SWEEP_LOW_LONG", target_px=tp))
    return sorted_out(out)


def ts02_x(m, B, p, cache):
    return Exits(target_r=None)


def ts03(m, B, p, cache):
    """Two-session squeeze (width <= 2%), 15-minute close beyond on 2x volume; exit on a close back inside; 3R."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    vol, va = c.vol(), c.vol_avg(20)
    out = []
    for d in range(2, m.n_days):
        if not (m.prev_ok[d] and m.prev_ok[d - 1]):
            continue
        a, z = int(m.d0[d - 2]), int(m.d1[d - 1])
        H, L = float(m.h[a:z].max()), float(m.l[a:z].min())
        if not (H > L and (H - L) / float(m.c[z - 1]) <= 0.02):
            continue
        mid = (H + L) / 2
        for j in bars_of_day(b, d):
            if int(b.ist0[j]) >= T(14, 0):
                break
            if not (np.isfinite(va[j]) and vol[j] >= 2 * va[j]):
                continue
            if b.c[j] > H:
                out.append(sig(b, j, 1, float(mid), "TS03_SQUEEZE_LONG", info={"close_stop": H}))
                break
            if b.c[j] < L:
                out.append(sig(b, j, -1, float(mid), "TS03_SQUEEZE_SHORT", info={"close_stop": L}))
                break
    return sorted_out(out)


def ts03_x(m, B, p, cache):
    return XExits(target_r=3.0, close_stop=(B[15],))


# ═══ HOLD with Priyank ═════════════════════════════════════════════════════════════════════

def pv02(m, B, p, cache):
    """EMA 21 continuation: a down-close candle still above the EMA after an up-close above it; buy its high within 3 bars."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    e21, a = c.ema(21), c.atr(14)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        for t in rows:
            if not (T(9, 30) <= int(b.ist0[t]) < T(14, 45)) or t == rows[-1] or not np.isfinite(a[t]):
                continue
            for side in (1, -1):
                trig_c = red if side > 0 else green
                tr = next((x for x in range(t, max(rows[0], t - 3), -1) if trig_c(b, x)), None)
                if tr is None or t - tr > 2:
                    continue
                if any((b.c[x] - e21[x]) * side <= 0 for x in range(tr, t + 1)):
                    continue
                if abs(b.c[tr] - e21[tr]) > 0.3 * a[tr]:
                    continue
                prior = [x for x in range(max(rows[0], tr - 5), tr) if (green(b, x) if side > 0 else red(b, x))
                         and (b.c[x] - e21[x]) * side > 0]
                if not prior or any((b.c[x] - e21[x]) * side <= 0 for x in range(prior[-1], tr)):
                    continue
                lvl = float(b.h[tr]) if side > 0 else float(b.l[tr])
                stop = float(b.l[tr] * 0.9998) if side > 0 else float(b.h[tr] * 1.0002)
                out.append(sig(b, t, side, stop, "PV02_EMA21_LONG" if side > 0 else "PV02_EMA21_SHORT",
                               entry_stop=lvl, expire_k=int(b.i1[t + 1]), info={"group": f"pv02-{side}-{int(b.i1[tr])}"}))
    return sorted_out(out)


def pv02_x(m, B, p, cache):
    return Exits(target_r=1.5)


def pv03(m, B, p, cache):
    """RSI divergence; enter on a close through the swing between the two extremes (NIFTY 5-minute), stop at the extreme, 1:1."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    rsi = c.rsi(14)
    ph, pl = c.fractals(3)
    H = np.flatnonzero(ph)
    L = np.flatnonzero(pl)
    out = []
    for side, piv, vals in ((-1, H, b.h), (1, L, b.l)):
        for t in range(1, len(piv)):
            q1, q2 = int(piv[t - 1]), int(piv[t])
            if q2 - q1 > 40 or b.day[q1] != b.day[q2] or not (np.isfinite(rsi[q1]) and np.isfinite(rsi[q2])):
                continue
            if side < 0 and not (b.h[q2] > b.h[q1] and rsi[q2] < rsi[q1]):
                continue
            if side > 0 and not (b.l[q2] < b.l[q1] and rsi[q2] > rsi[q1]):
                continue
            mid = float(b.l[q1:q2 + 1].min()) if side < 0 else float(b.h[q1:q2 + 1].max())
            for j in range(q2 + 3, min(q2 + 21, len(b.c))):
                if b.day[j] != b.day[q2] or int(b.ist0[j]) >= T(15, 0):
                    break
                if (side < 0 and b.h[j] > b.h[q2]) or (side > 0 and b.l[j] < b.l[q2]):
                    break
                if (b.c[j] - mid) * side > 0:
                    stop = float(b.h[q2] * 1.0002) if side < 0 else float(b.l[q2] * 0.9998)
                    out.append(sig(b, j, side, stop, "PV03_RSI_DIV_SHORT" if side < 0 else "PV03_RSI_DIV_LONG"))
                    break
    return sorted_out(out)


def pv03_x(m, B, p, cache):
    return Exits(target_r=1.0)


# ═══ Upsurge Club ══════════════════════════════════════════════════════════════════════════

def up01(m, B, p, cache):
    """The 9:15 open-price cross (index version): the 09:15 minute trades beyond the open and closes back -> the other way."""
    b = B[1]
    out = []
    for d in range(m.n_days):
        j = _bar_at(b, d, NSE_OPEN)
        if j is None or j + 1 >= int(b.b1[d]):
            continue
        O = float(b.o[j])
        if b.h[j] > O and b.c[j] < O:
            out.append(sig(b, j, -1, float(b.h[j]), "UP01_OPEN_CROSS_SHORT"))
        elif b.l[j] < O and b.c[j] > O:
            out.append(sig(b, j, 1, float(b.l[j]), "UP01_OPEN_CROSS_LONG"))
    return sorted_out(out)


def up01_x(m, B, p, cache):
    return Exits(target_r=None, target_abs=40.0 if m.name == "BANKNIFTY" else 20.0)


def up02(m, B, p, cache):
    """Gap trap: the first hour closes back across VWAP with a big wick; after 10:15 fade the VWAP retest on 10 minutes."""
    b = anchored_bars(m, 10, cache)
    vw = _vwap(m, b, cache, "a10")
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        rows = list(bars_of_day(b, d))
        first = [j for j in rows if int(b.ist0[j]) < T(10, 15)]
        if len(first) < 6:
            continue
        pv = prev_day_hlc(m, b, d)
        if pv is None:
            continue
        PH, PL, PC = pv
        P = (PH + PL + PC) / 3
        S1, S2, R1, R2 = 2 * P - PH, P - (PH - PL), 2 * P - PL, P + (PH - PL)
        gap = _day_open(m, d) / PC - 1
        o1, c1 = float(b.o[first[0]]), float(b.c[first[-1]])
        h1, l1 = float(b.h[first].max()), float(b.l[first].min())
        r1 = h1 - l1
        jl = first[-1]
        if not (r1 > 0 and np.isfinite(vw[jl])):
            continue
        side = 0
        if gap >= 0.01 and (h1 - max(o1, c1)) >= 0.5 * r1 and c1 < vw[jl]:
            side = -1
        elif gap <= -0.01 and (min(o1, c1) - l1) >= 0.5 * r1 and c1 > vw[jl]:
            side = 1
        if not side:
            continue
        hi_so_far, lo_so_far = h1, l1
        for j in rows:
            if int(b.ist0[j]) < T(10, 15):
                continue
            hi_so_far, lo_so_far = max(hi_so_far, float(b.h[j])), min(lo_so_far, float(b.l[j]))
            if int(b.ist0[j]) >= T(13, 20) or j == rows[-1] or not np.isfinite(vw[j]):
                continue
            if side < 0 and b.c[j] < vw[j] and S1 < vw[j]:
                out.append(sig(b, j, -1, hi_so_far, "UP02_GAPUP_TRAP_SHORT", entry_limit=float(vw[j]),
                               expire_k=int(b.i1[j + 1]), target_px=float(S2), info={"partial_px": float(S1), "group": f"up02-{d}"}))
            elif side > 0 and b.c[j] > vw[j] and R1 > vw[j]:
                out.append(sig(b, j, 1, lo_so_far, "UP02_GAPDOWN_TRAP_LONG", entry_limit=float(vw[j]),
                               expire_k=int(b.i1[j + 1]), target_px=float(R2), info={"partial_px": float(R1), "group": f"up02-{d}"}))
    return sorted_out(out)


def up02_x(m, B, p, cache):
    b = anchored_bars(m, 10, cache)
    vw = _vwap(m, b, cache, "a10")
    above = np.r_[False, (b.c[1:] > vw[1:]) & (b.c[:-1] > vw[:-1])]
    below = np.r_[False, (b.c[1:] < vw[1:]) & (b.c[:-1] < vw[:-1])]
    return XExits(target_r=None, partial_px=True, xbars=b, xlong=below, xshort=above)


def up03(m, B, p, cache):
    """15-minute ADX "curve": ADX rising up through the lower DI line, a candle in the DI trend's direction, its break."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    adx, pdi, mdi = c._get(("adx3", 14), lambda: I.adx(b, 14))
    lo_di = np.minimum(pdi, mdi)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        for j in rows[:-1]:
            if j < 30 or int(b.ist0[j]) >= T(14, 45):
                continue
            if not (np.isfinite(adx[j]) and np.isfinite(adx[j - 1]) and np.isfinite(lo_di[j - 1])):
                continue
            if not (adx[j - 1] <= lo_di[j - 1] and adx[j] > lo_di[j] and adx[j] > adx[j - 1]):
                continue
            side = 1 if pdi[j] > mdi[j] else -1
            if (side > 0 and not green(b, j)) or (side < 0 and not red(b, j)):
                continue
            last = int(b.i1[min(j + 2, rows[-1])])
            if side > 0:
                out.append(sig(b, j, 1, float(b.l[j]), "UP03_ADX_CURVE_LONG", entry_stop=float(b.h[j]), expire_k=last))
            else:
                out.append(sig(b, j, -1, float(b.h[j]), "UP03_ADX_CURVE_SHORT", entry_stop=float(b.l[j]), expire_k=last))
    return sorted_out(out)


def up03_x(m, B, p, cache):
    b = B[15]
    adx, pdi, mdi = ctx(m, B, 15, cache)._get(("adx3", 14), lambda: I.adx(b, 14))
    fall2 = np.r_[False, False, (adx[2:] < adx[1:-1]) & (adx[1:-1] < adx[:-2])]
    return XExits(target_r=None, xbars=b, xlong=fall2 | (pdi < mdi), xshort=fall2 | (pdi > mdi))


def _daily_ha_colour(m, cache):
    """Per trading day: +1 if the PREVIOUS day's daily Heikin Ashi candle was green, -1 red, 0 unknown."""
    key = ("dha",)
    if key in cache:
        return cache[key]
    n = m.n_days
    O = np.array([m.o[m.d0[d]] for d in range(n)], float)
    C = np.array([m.c[m.d1[d] - 1] for d in range(n)], float)
    Hh = np.array([m.h[m.d0[d]:m.d1[d]].max() for d in range(n)], float)
    Ll = np.array([m.l[m.d0[d]:m.d1[d]].min() for d in range(n)], float)
    hc = (O + Hh + Ll + C) / 4
    ho = np.empty(n)
    if n:
        ho[0] = (O[0] + C[0]) / 2
    for d in range(1, n):
        ho[d] = (ho[d - 1] + hc[d - 1]) / 2
    col = np.zeros(n, np.int8)
    col[1:] = np.where(hc[:-1] > ho[:-1], 1, -1)
    cache[key] = col
    return col


def up04(m, B, p, cache):
    """NIFTY 5-minute Heikin Ashi: yesterday's daily HA colour, the EMA 200 high/low band, Squeeze Momentum turning
    light, Supertrend (5, 1) on side; buy the HA candle's high; stop the Supertrend - 10 points."""
    b = B[5]
    hb = I.HABars(b)
    hc = actx(m, hb, cache, "ha5")
    eh, el = hc.ema(200, "h"), hc.ema(200, "l")
    stl, std = hc.supertrend(5, 1.0)
    sq = hc._get(("sqz", 20), lambda: Z.squeeze_momentum(hb, 20))
    col = _daily_ha_colour(m, cache)
    out = []
    for d in range(1, m.n_days):
        side = int(col[d])
        if not side:
            continue
        rows = list(bars_of_day(b, d))
        for j in rows[:-1]:
            if j < 3 or int(b.ist0[j]) >= T(14, 50) or not all(np.isfinite(x) for x in (eh[j], el[j], stl[j], sq[j], sq[j - 1], sq[j - 2])):
                continue
            last = int(b.i1[min(j + 2, rows[-1])])
            if side > 0 and hb.c[j] > eh[j] and std[j] > 0 and sq[j] > 0 and sq[j] > sq[j - 1] and not (sq[j - 1] > 0 and sq[j - 1] > sq[j - 2]):
                out.append(sig(b, j, 1, float(stl[j] - 10), "UP04_HA_SQUEEZE_LONG", entry_stop=float(hb.h[j]), expire_k=last))
            elif side < 0 and hb.c[j] < el[j] and std[j] < 0 and sq[j] < 0 and sq[j] < sq[j - 1] and not (sq[j - 1] < 0 and sq[j - 1] < sq[j - 2]):
                out.append(sig(b, j, -1, float(stl[j] + 10), "UP04_HA_SQUEEZE_SHORT", entry_stop=float(hb.l[j]), expire_k=last))
    return sorted_out(out)


def up04_x(m, B, p, cache):
    b = B[5]
    hc = actx(m, I.HABars(b), cache, "ha5")
    _, std = hc.supertrend(5, 1.0)
    return XExits(target_r=2.0, xbars=b, xlong=std < 0, xshort=std > 0)


def up05(m, B, p, cache):
    """Stretch beyond 0.9% from the 20 average, then EMA 20 / 50 cross the other way; 22-point stop; half at +30 points,
    the rest exits on the opposite cross (NIFTY 2-minute)."""
    b = B[2]
    c = ctx(m, B, 2, cache)
    e20, e50 = c.ema(20), c.ema(50)
    up, dn = flags_cross(e20, e50)
    gap = (b.c - e20) / e20
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        last_lo = last_hi = None
        for j in rows[:-1]:
            if np.isfinite(gap[j]):
                if gap[j] <= -0.009:
                    last_lo = j
                if gap[j] >= 0.009:
                    last_hi = j
            if int(b.ist0[j]) >= T(15, 0):
                continue
            nxt = int(b.i1[min(j + 2, rows[-1])])
            if up[j] and last_lo is not None and j - last_lo <= 60:
                lvl = float(b.h[j])
                out.append(sig(b, j, 1, lvl - 22.0, "UP05_STRETCH_LONG", entry_stop=lvl, expire_k=nxt,
                               info={"stop_dist": 22.0, "partial_px": lvl + 30.0}))
                last_lo = None
            elif dn[j] and last_hi is not None and j - last_hi <= 60:
                lvl = float(b.l[j])
                out.append(sig(b, j, -1, lvl + 22.0, "UP05_STRETCH_SHORT", entry_stop=lvl, expire_k=nxt,
                               info={"stop_dist": 22.0, "partial_px": lvl - 30.0}))
                last_hi = None
    return sorted_out(out)


def up05_x(m, B, p, cache):
    b = B[2]
    c = ctx(m, B, 2, cache)
    up, dn = flags_cross(c.ema(20), c.ema(50))
    return XExits(target_r=None, partial_px=True, xbars=b, xlong=dn, xshort=up)


def up06(m, B, p, cache):
    """Reversal scalp: a 3-minute candle at least half outside the Supertrend (10, 3) final band (the ratcheted band of the
    bar before) with the stochastic oscillator beyond 80/20; a stop order at its low (high), trailed for 5 bars (a stated
    approximation of a private indicator)."""
    b = B[3]
    c = ctx(m, B, 3, cache)
    a10 = c.atr(10)
    K, D = c._get(("stoch", 14, 3, 3), lambda: I.stochastic(b, 14, 3, 3))
    osc = (K + D) / 2
    dnb, upb = c._get(("stbands", 10, 3.0), lambda: Z.supertrend_bands(b, 10, 3.0))
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        for j in rows[:-1]:
            if not (T(9, 45) <= int(b.ist0[j]) < T(15, 0)) or not (np.isfinite(a10[j]) and np.isfinite(osc[j])):
                continue
            # the band as of the bar before (the ratcheted band moves with the bar itself)
            r = rng(b, j)
            if not r > 0 or j < 1 or not np.isfinite(upb[j - 1]):
                continue
            side = 0
            if b.h[j] - max(b.l[j], upb[j - 1]) >= 0.5 * r and osc[j] > 80:
                side = -1
            elif min(b.h[j], dnb[j - 1]) - b.l[j] >= 0.5 * r and osc[j] < 20:
                side = 1
            if not side:
                continue
            stop = float(b.h[j] * 1.0001) if side < 0 else float(b.l[j] * 0.9999)
            g = f"up06-{int(b.i1[j])}"
            for t in range(j, min(j + 5, rows[-1])):
                lvl = float(b.l[t] * 0.9999) if side < 0 else float(b.h[t] * 1.0001)
                if (lvl - stop) * side <= 0:
                    break
                out.append(sig(b, t, side, stop, "UP06_BAND_REVERSAL_SHORT" if side < 0 else "UP06_BAND_REVERSAL_LONG",
                               entry_stop=lvl, expire_k=int(b.i1[t + 1]), info={"group": g}))
    return sorted_out(out)


def up06_x(m, B, p, cache):
    return XExits(target_r=2.0, partial_at_r=1.0)


# ═══ Vijay Thakkar (MastersInOne) ══════════════════════════════════════════════════════════

def vt01(m, B, p, cache):
    """The 33 EMA band on 9 minutes: a body close beyond the band + RSI beyond 55/45 + VWAP side."""
    b = B[9]
    c = ctx(m, B, 9, cache)
    eh, el, rsi = c.ema(33, "h"), c.ema(33, "l"), c.rsi(14)
    vw = _vwap(m, b, cache, 9)
    out = []
    for d in range(1, m.n_days):
        rows = list(bars_of_day(b, d))
        pc = float(m.c[m.d1[d - 1] - 1]) if m.prev_ok[d] else np.nan
        skip = 3 if (np.isfinite(pc) and abs(_day_open(m, d) / pc - 1) > 0.005) else 0
        for i, j in enumerate(rows[:-1]):
            if i < skip or int(b.ist0[j]) >= T(14, 45) or not all(np.isfinite(x) for x in (eh[j], el[j], rsi[j], vw[j])):
                continue
            if b.c[j] > eh[j] and b.o[j] <= eh[j] and rsi[j] > 55 and b.c[j] > vw[j]:
                out.append(sig(b, j, 1, float(b.l[j]), "VT01_EMA33_BAND_LONG"))
            elif b.c[j] < el[j] and b.o[j] >= el[j] and rsi[j] < 45 and b.c[j] < vw[j]:
                out.append(sig(b, j, -1, float(b.h[j]), "VT01_EMA33_BAND_SHORT"))
    return sorted_out(out)


def vt01_x(m, B, p, cache):
    return XExits(target_r=3.0, partial_at_r=1.0, partial_be=False)


def _week_done_rows(m, wb):
    """Per weekly bar: the daily row at which the week is known to be complete (its Friday, else the next week's first
    day), or -1 when that is not in the data yet."""
    N = len(wb.c)
    out = np.full(N, -1, np.int64)
    wd = (m.date.astype("datetime64[D]").astype(np.int64) + 3) % 7
    for w in range(N):
        last = int(wb.i1[w])
        if wd[last] == 4:
            out[w] = last
        elif w + 1 < N:
            out[w] = int(wb.i0[w + 1])
    return out


def _vt02_state(m, cache):
    key = ("vt02",)
    if key in cache:
        return cache[key]
    wb = Z.weekly_bars(m, cache)
    stl, std = I.supertrend(wb, 10, 3.0)
    done = _week_done_rows(m, wb)
    n = len(m.c)
    lvl = np.full(n, np.nan)
    exit_flag = np.zeros(n, bool)
    for w in range(len(wb.c)):
        r = int(done[w])
        if r < 0 or not np.isfinite(stl[w]):
            continue
        lvl[r:] = stl[w] if std[w] > 0 else np.nan
        if std[w] < 0:
            exit_flag[r] = True
    cache[key] = (wb, stl, std, done, lvl, exit_flag)
    return cache[key]


def vt02(m, B, p, cache):
    """Weekly Supertrend (10, 3) on stocks: a strong flip candle, then a weekly close above its high within 8 weeks."""
    wb, stl, std, done, _, _ = _vt02_state(m, cache)
    b = B[1]
    out = []
    for w in range(1, len(wb.c)):
        if not (std[w] > 0 and std[w - 1] < 0 and np.isfinite(stl[w])):
            continue
        r = wb.h[w] - wb.l[w]
        if not (r > 0 and abs(wb.c[w] - wb.o[w]) >= 0.6 * r and wb.c[w] >= wb.h[w] - 0.25 * r):
            continue
        for u in range(w + 1, min(w + 9, len(wb.c))):
            if std[u] < 0:
                break
            if wb.c[u] > wb.h[w] and done[u] >= 0:
                k = int(done[u])
                j = int(np.searchsorted(b.i1, k, "left"))
                out.append(sig(b, j, 1, float(stl[u]), "VT02_WEEKLY_ST_KING_LONG"))
                break
    return sorted_out(out)


def vt02_x(m, B, p, cache):
    b = B[1]
    _, _, _, _, lvl, flag = _vt02_state(m, cache)
    lv = lvl[b.i1]
    fl = flag[b.i1]
    return XExits(target_r=None, trail=("level", b, lv, np.full(len(lv), np.nan)), xbars=b, xlong=fl, xshort=np.zeros(len(fl), bool))


def vt03(m, B, p, cache):
    """Sunil Gurjar's swing: above EMA 20/50/200, a close above the 50-day high; stop under a big breakout candle or the
    10-day low (skip beyond 10%); exit on the 9 EMA two-candle rule."""
    b = B[1]
    c = ctx(m, B, 1, cache)
    e20, e50, e200 = c.ema(20), c.ema(50), c.ema(200)
    res = I.prior_highest(b.h, 50)
    lo10 = I.lowest(b.l, 10)
    out = []
    for j in range(200, len(b.c)):
        if not all(np.isfinite(x) for x in (e200[j], res[j], lo10[j])):
            continue
        if not (b.c[j] > res[j] and b.c[j] > e20[j] and b.c[j] > e50[j] and b.c[j] > e200[j]):
            continue
        if b.c[j - 1] > res[j - 1]:
            continue                                            # the first close above
        stop = float(b.l[j]) if rng(b, j) >= 0.04 * b.c[j] else float(lo10[j])
        if (b.c[j] - stop) / b.c[j] > 0.10 or stop >= b.c[j]:
            continue
        out.append(sig(b, j, 1, stop, "VT03_SWING_BREAKOUT_LONG"))
    return sorted_out(out)


def vt03_x(m, B, p, cache):
    b = B[1]
    e9 = ctx(m, B, 1, cache).ema(9)
    rd = b.c < b.o
    fl = np.zeros(len(b.c), bool)
    fl[1:] = rd[1:] & rd[:-1] & (b.c[:-1] < e9[:-1]) & (b.c[1:] < b.l[:-1])
    return XExits(target_r=None, xbars=b, xlong=fl, xshort=np.zeros(len(fl), bool))


# ═══ TradBuilder ═══════════════════════════════════════════════════════════════════════════

def tb01(m, B, p, cache):
    """Two consecutive candles of different colours on 15 minutes; one of the next two closes below the pair's low -> short."""
    b = B[15]
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        hit = None
        for i in range(len(rows) - 2):
            p0, p1 = rows[i], rows[i + 1]
            if not ((green(b, p0) and red(b, p1)) or (red(b, p0) and green(b, p1))):
                continue
            lo, hi = float(min(b.l[p0], b.l[p1])), float(max(b.h[p0], b.h[p1]))
            for j in rows[i + 2:i + 4]:
                if b.c[j] < lo and int(b.ist0[j]) < T(15, 0):
                    if hit is None or j < hit[0]:
                        hit = (j, hi)
                    break
        if hit is not None:
            out.append(sig(b, hit[0], -1, hit[1], "TB01_PAIR_BREAK_SHORT"))
    return sorted_out(out)


def tb01_x(m, B, p, cache):
    return Exits(target_r=3.0)


def tb02(m, B, p, cache):
    """Range of the 09:20 and 09:25 candles: a 5-minute close beyond -> trade, stop at the far edge, reverse once, hold
    to the close."""
    b = B[5]
    out = []
    for d in range(m.n_days):
        j2, j3 = _bar_at(b, d, T(9, 20)), _bar_at(b, d, T(9, 25))
        if j2 is None or j3 is None:
            continue
        H, L = float(max(b.h[j2], b.h[j3])), float(min(b.l[j2], b.l[j3]))
        seen = set()
        for j in range(j3 + 1, int(b.b1[d])):
            if int(b.ist0[j]) >= T(15, 5):
                break
            if 1 not in seen and b.c[j] > H:
                seen.add(1)
                out.append(sig(b, j, 1, L, "TB02_RANGE_LONG"))
            elif -1 not in seen and b.c[j] < L:
                seen.add(-1)
                out.append(sig(b, j, -1, H, "TB02_RANGE_SHORT"))
    return sorted_out(out)


def tb02_x(m, B, p, cache):
    return Exits(target_r=None)


def tb04(m, B, p, cache):
    """NIFTY daily EMA 9 / 20 cross, long only, out on the opposite cross (R unit = 3% of the entry, for reporting)."""
    b = B[1]
    c = ctx(m, B, 1, cache)
    up, _ = flags_cross(c.ema(9), c.ema(20))
    out = []
    for j in np.flatnonzero(up):
        j = int(j)
        if j < 25:
            continue
        out.append(sig(b, j, 1, float(b.c[j] * 0.70), "TB04_DAILY_EMA920_LONG",
                       info={"stop_frac": 0.30, "risk_unit": float(b.c[j] * 0.03)}))
    return sorted_out(out)


def tb04_x(m, B, p, cache):
    b = B[1]
    c = ctx(m, B, 1, cache)
    _, dn = flags_cross(c.ema(9), c.ema(20))
    return XExits(target_r=None, xbars=b, xlong=dn, xshort=np.zeros(len(dn), bool))
