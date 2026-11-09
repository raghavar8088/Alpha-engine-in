"""Crypto and gold strategies of the 20-channel study, part A: Delta Exchange (DE), Trade with Pat (TP), AbhishekXTrades'
bitcoin rule (AX-06), Data Trader (DT), TradingLab (TL) and Jesse Rogers (JR). Markets: BTCUSD (UTC days, minute
rows) and XAUUSD (the 17:00 New York gold day). Rules: analyses/<channel>.md ("Code [A]" lines). Conventions as in
zc_common: completed bars only, orders from the next row, pivots only once confirmed."""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import (bars_of_day, bear_engulf, body, bull_engulf, ctx, flags_cross, green, last_done,  # noqa: F401
                       red, rng, sig, weekday_of)
from yc_engine import XExits
from yt_engine import Exits, Signal  # noqa: F401

import zc_common as Z
from zc_common import sorted_out

NY_OPEN = 9 * 60 + 30


# ── shared pieces ──────────────────────────────────────────────────────────────────────────

def utc_min(b, cache, tf):
    key = ("utcmin", tf)
    if key not in cache:
        cache[key] = ((np.asarray(b.t0, np.int64) // 60) % 1440).astype(np.int32)
    return cache[key]


def htf_above_ema(m, B, cache, tf, n, row):
    """+1 / -1: the last completed tf-minute close above / below its EMA n at minute row `row` (0 if unknown)."""
    bh = B[tf]
    e = ctx(m, B, tf, cache).ema(n)
    h = last_done(bh, row)
    if h < 0 or not np.isfinite(e[h]):
        return 0
    return 1 if bh.c[h] > e[h] else (-1 if bh.c[h] < e[h] else 0)


def swing_trend_at(m, B, cache, tf, row, n=2):
    """+1 / -1 / 0: the last two confirmed tf-minute swing highs and lows both rising / falling, as of minute row `row`."""
    bh = B[tf]
    hv, _, lv, _, phv, plv = ctx(m, B, tf, cache).pivots(n)
    h = last_done(bh, row)
    return 0 if h < 0 else Z.swings_up(hv, lv, phv, plv, h)


def gap_up(b, j):
    return j >= 2 and b.l[j] > b.h[j - 2]


def gap_dn(b, j):
    return j >= 2 and b.h[j] < b.l[j - 2]


def ny_range(b, d, start, minutes):
    """(high, low, last bar) of the bars of day d starting in [start, start + minutes) New York time."""
    idx = [j for j in bars_of_day(b, d) if start <= int(b.ny0[j]) < start + minutes]
    if not idx:
        return None
    return float(b.h[idx].max()), float(b.l[idx].min()), idx[-1], idx[0]


def clusters(vals, piv, j, n, tol, lookback):
    """Levels made of at least two confirmed pivots (bar indices piv, values vals) within tol of each other, known by
    bar j (pivot q <= j - n) and within `lookback` bars: a list of (mean level, outer level for a low cluster's min /
    a high cluster's max is the caller's choice: here (lo, hi) of the group)."""
    k = int(np.searchsorted(piv, j - n, "right"))
    a = int(np.searchsorted(piv, j - lookback, "left"))
    P = [float(vals[int(q)]) for q in piv[a:k]]
    out = []
    used = set()
    for i, v in enumerate(P):
        if i in used:
            continue
        grp = [x for x, w in enumerate(P) if abs(w - v) <= tol]
        if len(grp) >= 2:
            used.update(grp)
            ws = [P[x] for x in grp]
            out.append((min(ws), max(ws)))
    return out


def recent_extreme(b, j, n, side):
    """The lowest low (side +1) / highest high (side -1) of the last n bars up to j."""
    a = max(0, j - n + 1)
    return float(b.l[a:j + 1].min()) if side > 0 else float(b.h[a:j + 1].max())


# ═══ Delta Exchange ════════════════════════════════════════════════════════════════════════

def de01(m, B, p, cache):
    """EMA 9/30 cross with a strong candle near the cross that breaks the last 10-bar extreme (BTC 3-minute)."""
    b = B[3]
    c = ctx(m, B, 3, cache)
    e9, e30, a = c.ema(9), c.ema(30), c.atr(14)
    up, dn = flags_cross(e9, e30)
    out = []
    for j in range(12, len(b.c)):
        if not np.isfinite(a[j]) or not (b.day[j] == b.day[j - 1]):
            continue
        r = rng(b, j)
        if not r > 0 or body(b, j) < 0.5 * r or abs(b.c[j] - e30[j]) > 0.6 * a[j]:
            continue
        if (up[j] or up[j - 1]) and green(b, j) and b.c[j] > b.h[j - 10:j].max():
            stop = min(float(b.c[j - 1]), float(b.c[j] - 0.25 * a[j]))
            out.append(sig(b, j, 1, stop, "DE01_EMA930_LONG"))
        elif (dn[j] or dn[j - 1]) and red(b, j) and b.c[j] < b.l[j - 10:j].min():
            stop = max(float(b.c[j - 1]), float(b.c[j] + 0.25 * a[j]))
            out.append(sig(b, j, -1, stop, "DE01_EMA930_SHORT"))
    return sorted_out(out)


def de01_x(m, B, p, cache):
    b = B[3]
    e9 = ctx(m, B, 3, cache).ema(9)
    return XExits(target_r=None, partial_at_r=2.0, xbars=b, xlong=b.c < e9, xshort=b.c > e9, x_from_r=2.0)


def de02(m, B, p, cache):
    """EMA 20/50/100 stack + a confirmed Williams fractal + a close through the last up (down) fractal, with the 4-hour
    EMA 50 side (BTC 1-minute)."""
    b = B[1]
    c = ctx(m, B, 1, cache)
    e20, e50, e100, a = c.ema(20), c.ema(50), c.ema(100), c.atr(14)
    ph, pl = c.fractals(2)
    hv, hi, lv, li, _, _ = c.pivots(2)
    out = []
    last_long = last_short = -10
    for j in range(110, len(b.c)):
        if not np.isfinite(a[j]):
            continue
        spread = abs(e20[j] - e100[j]) >= 0.001 * b.c[j]
        if not spread:
            continue
        if e20[j] > e50[j] > e100[j] and b.c[j] > e20[j] and li[j] >= j - 2 - 5 and np.isfinite(hv[j]) \
                and b.c[j] > hv[j] and b.c[j - 1] <= hv[j] and j - last_long > 3:
            if htf_above_ema(m, B, cache, 240, 50, int(b.i1[j])) > 0:
                stop = min(float(e20[j] - 0.1 * a[j]), float(b.c[j] - 0.25 * a[j]))
                out.append(sig(b, j, 1, stop, "DE02_STACK_FRACTAL_LONG"))
                last_long = j
        elif e20[j] < e50[j] < e100[j] and b.c[j] < e20[j] and hi[j] >= j - 2 - 5 and np.isfinite(lv[j]) \
                and b.c[j] < lv[j] and b.c[j - 1] >= lv[j] and j - last_short > 3:
            if htf_above_ema(m, B, cache, 240, 50, int(b.i1[j])) < 0:
                stop = max(float(e20[j] + 0.1 * a[j]), float(b.c[j] + 0.25 * a[j]))
                out.append(sig(b, j, -1, stop, "DE02_STACK_FRACTAL_SHORT"))
                last_short = j
    return sorted_out(out)


def de02_x(m, B, p, cache):
    return Exits(target_r=2.0)


def de03(m, B, p, cache):
    """"Neela Peela": EMA 57 / 111 first retest on 5 minutes with 1/3/5-minute agreement, 06:00-09:30 IST Mon-Fri;
    exit when a 1-minute bar closes back across both 1-minute lines."""
    b = B[5]
    c5 = ctx(m, B, 5, cache)
    f5, s5, a = c5.ema(57), c5.ema(111), c5.atr(14)
    c3, c1 = ctx(m, B, 3, cache), ctx(m, B, 1, cache)
    f3, s3, f1, s1 = c3.ema(57), c3.ema(111), c1.ema(57), c1.ema(111)
    b3, b1 = B[3], B[1]
    wd = weekday_of(b, "Asia/Kolkata", cache, 5)
    out = []
    state = 0            # +1 after a break above both, -1 below both
    since = -1
    touched = False
    lower_seen = -10_000
    upper_seen = -10_000
    for j in range(120, len(b.c)):
        if not (np.isfinite(f5[j]) and np.isfinite(s5[j]) and np.isfinite(a[j])):
            continue
        lo_l, hi_l = min(f5[j], s5[j]), max(f5[j], s5[j])
        if b.c[j] < lo_l:
            lower_seen = j
        if b.c[j] > hi_l:
            upper_seen = j
        if b.c[j] < lo_l and state != -1 and j - upper_seen <= 48:
            state, since, touched = -1, j, False
            continue
        if b.c[j] > hi_l and state != 1 and j - lower_seen <= 48:
            state, since, touched = 1, j, False
            continue
        if state == 0 or touched or j - since > 288:
            continue
        side = state
        near = lo_l if side < 0 else hi_l
        if (side < 0 and b.h[j] >= near) or (side > 0 and b.l[j] <= near):
            touched = True
            if (side < 0 and b.c[j] > hi_l) or (side > 0 and b.c[j] < lo_l):
                state = 0
                continue
            ist = int(b.ist0[j])
            if not (6 * 60 <= ist < 9 * 60 + 30) or wd[j] >= 5 or rng(b, j) > 0.6 * a[j]:
                continue
            row = int(b.i1[j])
            h3, h1 = last_done(b3, row), last_done(b1, row)
            if h3 < 0 or h1 < 0:
                continue
            agree = all((b_.c[h] > max(f_[h], s_[h])) if side > 0 else (b_.c[h] < min(f_[h], s_[h]))
                        for b_, f_, s_, h in ((b3, f3, s3, h3), (b1, f1, s1, h1)))
            if not agree:
                continue
            far = hi_l if side < 0 else lo_l
            stop = float(far + 0.1 * a[j]) if side < 0 else float(far - 0.1 * a[j])
            lvl = float(b.l[j]) if side < 0 else float(b.h[j])
            out.append(sig(b, j, side, stop, "DE03_NEELA_PEELA_SHORT" if side < 0 else "DE03_NEELA_PEELA_LONG",
                           entry_stop=lvl, expire_k=int(b.i1[min(j + 2, len(b.c) - 1)])))
    return sorted_out(out)


def de03_x(m, B, p, cache):
    b1 = B[1]
    c1 = ctx(m, B, 1, cache)
    f1, s1 = c1.ema(57), c1.ema(111)
    return XExits(target_r=None, xbars=b1, xlong=b1.c < np.minimum(f1, s1), xshort=b1.c > np.maximum(f1, s1))


def de04_trades(m, B, p, cache, eng, k_end_of_day, sid):
    """Gold 4-hour Supertrend (10, 4), long only: 100% on the flip, a one-time 30% add on a close above the previous 40
    closes, everything out on the opposite flip (no stop: R unit = 1% of the entry, so 1% risk sizing = full notional)."""
    b = B[240]
    stl, std = ctx(m, B, 240, cache).supertrend(10, 4.0)
    hc40 = I.prior_highest(b.c, 40)
    ex = XExits(target_r=None, xbars=b, xlong=std < 0, xshort=np.zeros(len(std), bool))
    trades = []
    j = 1
    n = len(b.c)
    while j < n:
        if not (std[j] > 0 and std[j - 1] < 0 and np.isfinite(stl[j])):
            j += 1
            continue
        px = float(b.c[j])
        s = sig(b, j, 1, px * 0.5, "DE04_ST_FLIP_LONG", info={"stop_frac": 0.5, "risk_unit": px * 0.01})
        ke = k_end_of_day(s.day)
        if ke is None or s.k >= ke:
            j += 1
            continue
        t, _ = eng.trade(s, ex, ke, sid, "V0")
        if t is None:
            j += 1
            continue
        trades.append(t)
        end_bar = int(np.searchsorted(b.i1, t.exit_k, "left"))
        for u in range(j + 1, min(end_bar, n)):
            if np.isfinite(hc40[u]) and b.c[u] > hc40[u] and int(b.i1[u]) < t.exit_k - 1:
                pu = float(b.c[u])
                s2 = sig(b, u, 1, pu * 0.5, "DE04_ADD_30PCT", info={"stop_frac": 0.5, "risk_unit": pu * 0.01 / 0.3})
                t2, _ = eng.trade(s2, ex, ke, sid, "ADD")
                if t2 is not None:
                    trades.append(t2)
                break
        j = max(j + 1, end_bar)
    return trades


def de07(m, B, p, cache):
    """The 7:30 PM IST bitcoin trade: the 13:30-14:00 UTC 30-minute candle in the 4-hour EMA 50 trend, 1:1, Mon-Fri."""
    b = B[30]
    um = utc_min(b, cache, 30)
    wd = weekday_of(b, "UTC", cache, 30)
    out = []
    for j in range(len(b.c)):
        if int(um[j]) != 13 * 60 + 30 or wd[j] >= 5:
            continue
        side = htf_above_ema(m, B, cache, 240, 50, int(b.i1[j]))
        if not side:
            continue
        px = float(b.c[j])
        ext = float(b.l[j]) if side > 0 else float(b.h[j])
        dist = max(abs(px - ext), 0.0015 * px)
        out.append(sig(b, j, side, px - side * dist, "DE07_730PM_LONG" if side > 0 else "DE07_730PM_SHORT",
                       info={"stop_dist": dist}))
    return sorted_out(out)


def de07_x(m, B, p, cache):
    return Exits(target_r=1.0)


# ═══ AbhishekXTrades: bitcoin 20-20 EMA ════════════════════════════════════════════════════

def ax06(m, B, p, cache):
    """Bitcoin 20-20 EMA: EMA 20 on 15 minutes and on 1 hour; a touch of the hourly line, then a close back beyond the
    15-minute line with the close beyond both; the hourly EMA must have moved 0.4% the trade's way over 6 hours."""
    b, bh = B[15], B[60]
    c = ctx(m, B, 15, cache)
    e15, a = c.ema(20), c.atr(14)
    eh = ctx(m, B, 60, cache).ema(20)
    out = []
    touch = {1: None, -1: None}
    for j in range(30, len(b.c)):
        h = last_done(bh, int(b.i1[j]))
        if h < 6 or not (np.isfinite(eh[h]) and np.isfinite(eh[h - 6]) and np.isfinite(a[j])):
            continue
        e60 = float(eh[h])
        for side in (1, -1):
            beyond_both = (b.c[j] - max(e15[j], e60)) * side > 0 if side > 0 else (min(e15[j], e60) - b.c[j]) > 0
            if (side > 0 and b.l[j] <= e60) or (side < 0 and b.h[j] >= e60):
                if touch[side] is None:
                    touch[side] = j
            t = touch[side]
            if t is None:
                continue
            if j - t > 16:
                touch[side] = None
                continue
            moved = (eh[h] / eh[h - 6] - 1) * side >= 0.004
            back = (b.c[j] - e15[j]) * side > 0 and (b.c[j - 1] - e15[j - 1]) * side <= 0 or j == t
            if beyond_both and back and moved:
                ext = recent_extreme(b, j, j - t + 1, side)
                stop = ext - side * 0.1 * a[j]
                out.append(sig(b, j, side, float(stop), "AX06_2020EMA_LONG" if side > 0 else "AX06_2020EMA_SHORT"))
                touch[side] = None
    return sorted_out(out)


def ax06_x(m, B, p, cache):
    return XExits(target_r=2.0, lock_at_r=1.0, lock_to_r=0.1)


# ═══ Trade with Pat ════════════════════════════════════════════════════════════════════════

def _tp01(m, B, p, cache, tf):
    b = B[tf]
    c = ctx(m, B, tf, cache)
    a, e200 = c.atr(14), c.ema(200)
    ph, pl = (np.flatnonzero(x) for x in c.fractals(3))
    out = []
    n = len(b.c)
    for j in range(205, n - 1):
        if not (np.isfinite(a[j]) and gap_up(b, j) and b.c[j] > e200[j]):
            continue
        if rng(b, j - 1) < 1.5 * a[j]:
            continue
        sup = [lo for lo, hi_ in clusters(b.l, pl, j, 3, 0.25 * a[j], 150) if 0 <= b.l[j - 2] - lo <= 1.0 * a[j]]
        if not sup:
            continue
        s_lo = min(sup)
        top = float(b.l[j])
        stop = float(min(b.l[j - 2], s_lo) - 0.1 * a[j])
        range_top = max((hi_ for lo, hi_ in clusters(b.h, ph, j, 3, 0.25 * a[j], 150)), default=np.nan)
        hi_so_far = float(b.h[j])
        for t in range(j + 1, min(j + 48, n - 1)):
            if b.l[t] <= top:
                break                                    # tapped: only the orders placed before count
            hi_so_far = max(hi_so_far, float(b.h[t]))
            fib50 = s_lo + 0.5 * (hi_so_far - s_lo)
            if not top < fib50:
                continue
            tgt = max(float(range_top) if np.isfinite(range_top) else -np.inf, top + 2 * (top - stop))
            out.append(sig(b, t, 1, stop, "TP01_RANGE_FVG_LONG", entry_limit=top, expire_k=int(b.i1[t + 1]),
                           target_px=float(tgt), info={"partial_px": hi_so_far, "group": f"tp01-{j}"}))
    return sorted_out(out)


def tp01(m, B, p, cache):
    """Gold range trading: support + impulsive FVG + discount below 50% + EMA 200, 5-minute book."""
    return _tp01(m, B, p, cache, 5)


def tp01h(m, B, p, cache):
    """The same on 1-hour candles (holds overnight)."""
    return _tp01(m, B, p, cache, 60)


def tp01_x(m, B, p, cache):
    return XExits(target_r=None, partial_px=True)


def tp02(m, B, p, cache):
    """Gold 5-minute: a sweep of a tested level, then a big candle through the minor trend line, EMA 200 side."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    a, e200 = c.atr(14), c.ema(200)
    ph3, pl3 = (np.flatnonzero(x) for x in c.fractals(3))
    ph2, pl2 = (np.flatnonzero(x) for x in c.fractals(2))
    out = []
    n = len(b.c)
    for j in range(205, n):
        if not np.isfinite(a[j]):
            continue
        for side in (1, -1):
            if (b.c[j] - e200[j]) * side <= 0:
                continue
            piv, vals = (pl3, b.l) if side > 0 else (ph3, b.h)
            kk, aa = int(np.searchsorted(piv, j - 3, "right")), int(np.searchsorted(piv, j - 150, "left"))
            pv = vals[piv[aa:kk]]
            if not (((pv > b.l[j]) & (pv < b.c[j])).any() if side > 0 else ((pv < b.h[j]) & (pv > b.c[j])).any()):
                continue
            levels = clusters(vals, piv, j, 3, 0.25 * a[j], 150)
            lv = [lo for lo, _ in levels] if side > 0 else [hi_ for _, hi_ in levels]
            swept = [x for x in lv if (side > 0 and b.l[j] < x < b.c[j]) or (side < 0 and b.h[j] > x > b.c[j])]
            if not swept:
                continue
            ext = float(b.l[j]) if side > 0 else float(b.h[j])
            # the minor trend line of the push into the sweep: the last two confirmed swing highs (for a long) falling
            tp_piv = ph2 if side > 0 else pl2
            k = int(np.searchsorted(tp_piv, j - 2, "right"))
            if k < 2:
                continue
            q1, q2 = int(tp_piv[k - 2]), int(tp_piv[k - 1])
            v1, v2 = (b.h[q1], b.h[q2]) if side > 0 else (b.l[q1], b.l[q2])
            if q2 <= q1 or j - q1 > 60 or (v2 - v1) * side >= 0:
                continue
            slope = (v2 - v1) / (q2 - q1)
            opp = [hi_ for _, hi_ in clusters(b.h, ph3, j, 3, 0.25 * a[j], 150)] if side > 0 else \
                  [lo for lo, _ in clusters(b.l, pl3, j, 3, 0.25 * a[j], 150)]
            for t in range(j + 1, min(j + 13, n)):
                if b.day[t] != b.day[j]:
                    break
                if (side > 0 and b.l[t] < ext) or (side < 0 and b.h[t] > ext):
                    break
                line = v2 + slope * (t - q2)
                if (b.c[t] - line) * side > 0 and rng(b, t) >= 1.2 * a[t]:
                    stop = ext - side * 0.1 * a[j]
                    risk = abs(float(b.c[t]) - stop)
                    cands = [x for x in opp if (x - b.c[t]) * side >= 2 * risk]
                    tgt = min(cands, key=lambda x: abs(x - b.c[t])) if cands else float(b.c[t]) + side * 2 * risk
                    out.append(sig(b, t, side, float(stop), "TP02_SWEEP_TL_LONG" if side > 0 else "TP02_SWEEP_TL_SHORT",
                                   target_px=float(tgt)))
                    break
            break
    return sorted_out(out)


def tp02_x(m, B, p, cache):
    return Exits(target_r=None)


def _tp_orb_engine(m, B, p, cache, amd: bool, setup):
    """The New York 9:30-9:45 displacement ORB (5-minute): a close beyond the range, then the first engulfing candle
    whose low (high) returns to the break's FVG or the range edge within 90 minutes; stop beyond the FVG / candle; 2R.
    amd=True keeps only the side opposite a London push out of a tight Asian range (TP-03)."""
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    um = utc_min(b, cache, 5)
    out = []
    widths = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        if not rows:
            continue
        allowed = (1, -1)
        if amd:
            asia = [j for j in rows if um[j] < 6 * 60]
            lon = [j for j in rows if 7 * 60 <= um[j] < 12 * 60]
            if len(asia) < 30 or len(lon) < 30:
                continue
            AH, AL = float(b.h[asia].max()), float(b.l[asia].min())
            W = AH - AL
            med = float(np.median(widths[-20:])) if len(widths) >= 10 else np.nan
            widths.append(W)
            if not (W > 0 and np.isfinite(med) and W < med):
                continue
            lh, ll = float(b.h[lon].max()), float(b.l[lon].min())
            last_c = float(b.c[lon[-1]])
            if lh >= AH + 0.3 * W and last_c > AH:
                allowed = (-1,)
            elif ll <= AL - 0.3 * W and last_c < AL:
                allowed = (1,)
            else:
                continue
        rg = ny_range(b, d, NY_OPEN, 15)
        if rg is None:
            continue
        H, L, last, _ = rg
        done = False
        for x in rows:
            if done or x <= last or int(b.ny0[x]) >= 12 * 60:
                continue
            side = 1 if b.c[x] > H else (-1 if b.c[x] < L else 0)
            if not side:
                continue
            if side not in allowed:
                done = True
                continue
            fvg = None
            for g in range(max(x - 1, rows[0] + 2), min(x + 3, rows[-1] + 1)):
                if side > 0 and gap_up(b, g):
                    fvg = (float(b.h[g - 2]), float(b.l[g]))
                elif side < 0 and gap_dn(b, g):
                    fvg = (float(b.h[g]), float(b.l[g - 2]))
            edge = H if side > 0 else L
            for t in range(x + 1, min(x + 19, rows[-1])):
                if int(b.ny0[t]) >= 16 * 60 - 5:
                    break
                touch_lvl = max(edge, fvg[1]) if (side > 0 and fvg) else (min(edge, fvg[0]) if fvg else edge)
                eng = bull_engulf(b, t) if side > 0 else bear_engulf(b, t)
                reach = b.l[t] <= touch_lvl if side > 0 else b.h[t] >= touch_lvl
                if eng and reach and np.isfinite(a[t]):
                    far = (min(fvg[0], float(b.l[t])) if fvg else float(b.l[t])) if side > 0 else \
                          (max(fvg[1], float(b.h[t])) if fvg else float(b.h[t]))
                    stop = far - side * 0.1 * a[t]
                    out.append(sig(b, t, side, float(stop), f"{setup}_LONG" if side > 0 else f"{setup}_SHORT"))
                    break
            done = True
    return sorted_out(out)


def tp03(m, B, p, cache):
    """Asian range -> London push -> New York reversal on the 9:30-9:45 displacement ORB with an engulfing entry."""
    return _tp_orb_engine(m, B, p, cache, True, "TP03_AMD_ORB")


def tp05(m, B, p, cache):
    """The same displacement ORB without the session (AMD) filter."""
    return _tp_orb_engine(m, B, p, cache, False, "TP05_DISPLACEMENT_ORB")


def tp03_x(m, B, p, cache):
    return Exits(target_r=2.0)


def tp04(m, B, p, cache):
    """New York 15-minute ORB: the first 5-minute close out of it; a limit at the range edge / midline / far side by the
    impulse's strength over three bars; stop beyond the far edge; target the impulse extreme (at least 1.5R)."""
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    out = []
    widths = []
    for d in range(m.n_days):
        rg = ny_range(b, d, NY_OPEN, 15)
        if rg is None:
            continue
        H, L, last, _ = rg
        W = H - L
        med = float(np.median(widths[-20:])) if len(widths) >= 10 else np.nan
        widths.append(W)
        if not (W > 0 and np.isfinite(med) and W <= 1.5 * med):
            continue
        rows = list(bars_of_day(b, d))
        for x in rows:
            if x <= last:
                continue
            if int(b.ny0[x]) >= 12 * 60:
                break
            side = 1 if b.c[x] > H else (-1 if b.c[x] < L else 0)
            if not side:
                continue
            y = x + 2
            if y > rows[-1] or int(b.ny0[y]) >= 12 * 60 or not np.isfinite(a[y]):
                break
            ext = float(b.h[x:y + 1].max()) if side > 0 else float(b.l[x:y + 1].min())
            strength = ((ext - H) if side > 0 else (L - ext)) / W
            if side > 0:
                lvl = H if strength >= 1.0 else ((H + L) / 2 if strength >= 0.5 else L + 0.1 * W)
                stop = L - 0.1 * a[y]
            else:
                lvl = L if strength >= 1.0 else ((H + L) / 2 if strength >= 0.5 else H - 0.1 * W)
                stop = H + 0.1 * a[y]
            risk = abs(lvl - stop)
            tgt = ext if (ext - lvl) * side >= 1.5 * risk else lvl + side * 1.5 * risk
            end = max((j for j in rows if int(b.ny0[j]) < 12 * 60), default=None)
            if end is None or end <= y:
                break
            out.append(sig(b, y, side, float(stop), "TP04_ORB_LEVEL_LONG" if side > 0 else "TP04_ORB_LEVEL_SHORT",
                           entry_limit=float(lvl), expire_k=int(b.i1[end]), target_px=float(tgt)))
            break
    return sorted_out(out)


def tp04_x(m, B, p, cache):
    return Exits(target_r=None)


# ═══ Data Trader ═══════════════════════════════════════════════════════════════════════════

def _macd_trend(m, B, p, cache, tf, n_trend, rr_tag):
    b = B[tf]
    c = ctx(m, B, tf, cache)
    line, sgl, _ = c.macd()
    up, dn = flags_cross(line, sgl)
    e = c.ema(n_trend)
    out = []
    for j in range(n_trend + 5, len(b.c)):
        if up[j] and b.c[j] > e[j]:
            out.append(sig(b, j, 1, recent_extreme(b, j, 10, 1), f"{rr_tag}_LONG"))
        elif dn[j] and b.c[j] < e[j]:
            out.append(sig(b, j, -1, recent_extreme(b, j, 10, -1), f"{rr_tag}_SHORT"))
    return sorted_out(out)


def dt01(m, B, p, cache):
    """MACD signal-line cross in the EMA 100 trend, 10-bar swing stop, 1.5R (1-hour)."""
    return _macd_trend(m, B, p, cache, 60, 100, "DT01_MACD_EMA100")


def r15_x(m, B, p, cache):
    return Exits(target_r=1.5)


def dt02(m, B, p, cache):
    """MACD cross + Parabolic SAR side + EMA 200, stop at the SAR dot (capped at 0.7%), 1:1 (30-minute)."""
    b = B[30]
    c = ctx(m, B, 30, cache)
    line, sgl, _ = c.macd()
    up, dn = flags_cross(line, sgl)
    e200 = c.ema(200)
    sar, tr = c._get(("psar",), lambda: I.psar(b))
    out = []
    for x in range(205, len(b.c)):
        side = 1 if up[x] else (-1 if dn[x] else 0)
        if not side:
            continue
        for j in range(x, min(x + 6, len(b.c))):
            if (line[j] - sgl[j]) * side <= 0:
                break
            if (b.c[j] - e200[j]) * side <= 0:
                continue
            if tr[j] == side and np.isfinite(sar[j]):
                cap = 0.007 * b.c[j]
                dist = min(abs(float(b.c[j]) - float(sar[j])), cap)
                out.append(sig(b, j, side, float(b.c[j] - side * dist), "DT02_MACD_SAR_LONG" if side > 0 else "DT02_MACD_SAR_SHORT",
                               info={"stop_dist": dist}))
                break
    return sorted_out(out)


def r1_x(m, B, p, cache):
    return Exits(target_r=1.0)


def dt03(m, B, p, cache):
    """Stochastic (14, 3, 3) both lines oversold, then RSI above 50 and a MACD cross up before overbought; 1.5R; the stop
    is capped (0.5% bitcoin, 0.3% gold)."""
    b = B[30]
    c = ctx(m, B, 30, cache)
    K, D = c._get(("stoch", 14, 3, 3), lambda: I.stochastic(b, 14, 3, 3))
    rsi = c.rsi(14)
    line, sgl, _ = c.macd()
    up, dn = flags_cross(line, sgl)
    cap = 0.005 if m.name == "BTCUSD" else 0.003
    out = []
    last_os = last_ob = -1000
    for j in range(40, len(b.c)):
        if np.isfinite(K[j]) and np.isfinite(D[j]):
            if K[j] < 20 and D[j] < 20:
                last_os = j
            if K[j] > 80 and D[j] > 80:
                last_ob = j
        if up[j] and j - last_os <= 12 and rsi[j] > 50 and K[j] < 80 and D[j] < 80:
            dist = min(float(b.c[j]) - recent_extreme(b, j, 10, 1), cap * b.c[j])
            if dist > 0:
                out.append(sig(b, j, 1, float(b.c[j] - dist), "DT03_STOCH_RSI_MACD_LONG", info={"stop_dist": dist}))
        elif dn[j] and j - last_ob <= 12 and rsi[j] < 50 and K[j] > 20 and D[j] > 20:
            dist = min(recent_extreme(b, j, 10, -1) - float(b.c[j]), cap * b.c[j])
            if dist > 0:
                out.append(sig(b, j, -1, float(b.c[j] + dist), "DT03_STOCH_RSI_MACD_SHORT", info={"stop_dist": dist}))
    return sorted_out(out)


def dt04(m, B, p, cache):
    """Bitcoin daily Ichimoku lead lines (displacement 1): a green close above the cloud with Lead 1 over Lead 2; out on a
    red close below Lead 1. Long only, no stop (R unit = 1% of the entry, so 1% risk sizing = full notional)."""
    b = B[1440]
    l1, l2 = _ichi_leads(b)
    out = []
    for j in range(60, len(b.c)):
        if not (np.isfinite(l1[j]) and np.isfinite(l2[j])):
            continue
        if green(b, j) and b.c[j] > max(l1[j], l2[j]) and l1[j] > l2[j] and not (b.c[j - 1] > max(l1[j - 1], l2[j - 1]) and l1[j - 1] > l2[j - 1] and green(b, j - 1)):
            px = float(b.c[j])
            out.append(sig(b, j, 1, px * 0.5, "DT04_ICHIMOKU_DAILY_LONG", info={"stop_frac": 0.5, "risk_unit": px * 0.01}))
    return sorted_out(out)


def _ichi_leads(b):
    tenkan = (I.highest(b.h, 9) + I.lowest(b.l, 9)) / 2
    kijun = (I.highest(b.h, 26) + I.lowest(b.l, 26)) / 2
    return (tenkan + kijun) / 2, (I.highest(b.h, 52) + I.lowest(b.l, 52)) / 2


def dt04_x(m, B, p, cache):
    b = B[1440]
    l1, _ = _ichi_leads(b)
    return XExits(target_r=None, xbars=b, xlong=(b.c < b.o) & (b.c < l1), xshort=np.zeros(len(b.c), bool))


def dt05(m, B, p, cache):
    """15-minute Chaikin Money Flow (20) side + MACD signal-line cross, 10-bar swing stop, 1.5R (bitcoin)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    cm = c._get(("cmf", 20), lambda: Z.cmf(b, c.vol(), 20))
    line, sgl, _ = c.macd()
    up, dn = flags_cross(line, sgl)
    out = []
    for j in range(30, len(b.c)):
        if not np.isfinite(cm[j]):
            continue
        if up[j] and cm[j] > 0:
            out.append(sig(b, j, 1, recent_extreme(b, j, 10, 1), "DT05_CMF_MACD_LONG"))
        elif dn[j] and cm[j] < 0:
            out.append(sig(b, j, -1, recent_extreme(b, j, 10, -1), "DT05_CMF_MACD_SHORT"))
    return sorted_out(out)


def dt06(m, B, p, cache):
    """First New York 4-hour candle (00:00-04:00 NY): a 5-minute close outside, then a close back inside -> fade; stop at
    the breakout extreme; 2R; setups until 16:00 NY."""
    b = B[5]
    out = []
    for d in range(m.n_days):
        rg = ny_range(b, d, 0, 240)
        if rg is None:
            continue
        H, L, last, first = rg
        if int(b.ny0[first]) != 0 or not H > L:
            continue
        W = H - L
        state, ext = 0, None
        for j in bars_of_day(b, d):
            if j <= last:
                continue
            if int(b.ny0[j]) >= 16 * 60:
                break
            if state == 0:
                if b.c[j] > H:
                    state, ext = 1, float(b.h[j])
                elif b.c[j] < L:
                    state, ext = -1, float(b.l[j])
                continue
            ext = max(ext, float(b.h[j])) if state > 0 else min(ext, float(b.l[j]))
            if state > 0 and b.c[j] < H:
                if ext - H <= W and b.c[j] > L:
                    out.append(sig(b, j, -1, ext, "DT06_NY4H_FADE_SHORT"))
                state, ext = 0, None
            elif state < 0 and b.c[j] > L:
                if L - ext <= W and b.c[j] < H:
                    out.append(sig(b, j, 1, ext, "DT06_NY4H_FADE_LONG"))
                state, ext = 0, None
    return sorted_out(out)


def r2_x(m, B, p, cache):
    return Exits(target_r=2.0)


def dt07(m, B, p, cache):
    """"SLC": 4-hour swing structure, a fresh 5-minute zone (the last opposite candle before a 2-ATR run), a stochastic
    hook back out of 80/20 inside the zone; 2R."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    a = c.atr(14)
    K, _ = c._get(("stoch", 14, 3, 3), lambda: I.stochastic(b, 14, 3, 3))
    n = len(b.c)
    zones = []                 # [side, lo, hi, made_at, alive]
    out = []
    for j in range(20, n):
        if not np.isfinite(a[j]):
            continue
        # new zones: a run of 3 candles that moved >= 2 ATR, the last opposite candle before it
        if j >= 4:
            mv = b.c[j] - b.o[j - 2]
            if mv >= 2 * a[j] and all(green(b, x) for x in (j - 2, j - 1, j)) and red(b, j - 3):
                zones.append([1, float(b.l[j - 3]), float(b.h[j - 3]), j, True])
            elif -mv >= 2 * a[j] and all(red(b, x) for x in (j - 2, j - 1, j)) and green(b, j - 3):
                zones.append([-1, float(b.l[j - 3]), float(b.h[j - 3]), j, True])
        zones = [z for z in zones if j - z[3] <= 288 and z[4]]
        for z in zones:
            side, lo, hi, made, _ = z
            if j <= made:
                continue
            inside = b.l[j] <= hi and b.h[j] >= lo
            if not inside:
                continue
            z[4] = False                                  # touched: no longer fresh after this bar
            hook = (K[j - 1] <= 20 < K[j]) if side > 0 else (K[j - 1] >= 80 > K[j])
            st = swing_trend_at(m, B, cache, 240, int(b.i1[j]))
            if hook and st == side:
                stop = lo - 0.1 * a[j] if side > 0 else hi + 0.1 * a[j]
                out.append(sig(b, j, side, float(stop), "DT07_SLC_LONG" if side > 0 else "DT07_SLC_SHORT"))
    return sorted_out(out)


def dt08(m, B, p, cache):
    """"Manipulation": a 15-minute swing level (moved away from by 1.5 ATR) swept on 5 minutes, then a close through
    the FVG made by the move into the sweep (an inverse FVG); stop beyond the gap; 2R."""
    b, b15 = B[5], B[15]
    a = ctx(m, B, 5, cache).atr(14)
    c15 = ctx(m, B, 15, cache)
    a15 = c15.atr(14)
    ph, pl = c15.fractals(3)
    n, n15 = len(b.c), len(b15.c)
    out = []
    for side, flags, vals in ((-1, ph, b15.h), (1, pl, b15.l)):
        for q in np.flatnonzero(flags):
            q = int(q)
            lvl = float(vals[q])
            # the level counts once price has moved 1.5 ATR(15m) away (seen on closed 15-minute bars after confirmation)
            act = None
            for u in range(q + 3, min(q + 3 + 288, n15)):
                if b15.t0[u] > b15.t0[q] + 3 * 86400:
                    break
                away = (lvl - b15.l[q + 1:u + 1].min()) if side < 0 else (b15.h[q + 1:u + 1].max() - lvl)
                if (side < 0 and b15.h[u] > lvl) or (side > 0 and b15.l[u] < lvl):
                    break                                   # traded through before it became a level
                if np.isfinite(a15[u]) and away >= 1.5 * a15[u]:
                    act = u
                    break
            if act is None:
                continue
            j0 = int(np.searchsorted(b.i0, int(b15.i1[act]) + 1, "left"))
            t_end = int(b15.t0[q]) + 3 * 86400
            j1 = int(np.searchsorted(b.t0, t_end, "right"))
            if j0 >= min(j1, n):
                continue
            seg = b.h[j0:min(j1, n)] > lvl if side < 0 else b.l[j0:min(j1, n)] < lvl
            if not seg.any():
                continue
            j = j0 + int(np.argmax(seg))
            if not np.isfinite(a[j]):
                continue
            gap = None
            for g in range(max(2, j - 11), j + 1):
                if side < 0 and gap_up(b, g):
                    gap = (float(b.h[g - 2]), float(b.l[g]))
                elif side > 0 and gap_dn(b, g):
                    gap = (float(b.h[g]), float(b.l[g - 2]))
            if gap is None:
                continue
            for u in range(j + 1, min(j + 13, n)):
                if side < 0 and b.c[u] < gap[0]:
                    out.append(sig(b, u, -1, float(gap[1] + 0.1 * a[u]), "DT08_IFVG_SHORT"))
                    break
                if side > 0 and b.c[u] > gap[1]:
                    out.append(sig(b, u, 1, float(gap[0] - 0.1 * a[u]), "DT08_IFVG_LONG"))
                    break
    return sorted_out(out)


# ═══ TradingLab ════════════════════════════════════════════════════════════════════════════

def tl01(m, B, p, cache):
    """MACD cross on the far side of zero in the EMA 200 trend, stop beyond the EMA 200 (skipped beyond 3 ATR), 1.5R."""
    b = B[60]
    c = ctx(m, B, 60, cache)
    line, sgl, _ = c.macd()
    up, dn = flags_cross(line, sgl)
    e200, a = c.ema(200), c.atr(14)
    out = []
    for j in range(205, len(b.c)):
        if not np.isfinite(a[j]):
            continue
        if up[j] and line[j] < 0 and sgl[j] < 0 and b.c[j] > e200[j] and b.c[j] - e200[j] <= 3 * a[j]:
            out.append(sig(b, j, 1, float(e200[j] - 0.1 * a[j]), "TL01_MACD_EMA200_LONG"))
        elif dn[j] and line[j] > 0 and sgl[j] > 0 and b.c[j] < e200[j] and e200[j] - b.c[j] <= 3 * a[j]:
            out.append(sig(b, j, -1, float(e200[j] + 0.1 * a[j]), "TL01_MACD_EMA200_SHORT"))
    return sorted_out(out)


def tl03(m, B, p, cache):
    """DEMA 200 side + Supertrend (12, 3) signal; stop at the Supertrend line; out on the opposite signal."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    dm = c._get(("dema", 200), lambda: Z.dema(b.c, 200))
    stl, std = c.supertrend(12, 3.0)
    out = []
    for j in range(410, len(b.c)):
        if not (np.isfinite(dm[j]) and np.isfinite(stl[j])):
            continue
        flip_up = std[j] > 0 and std[j - 1] < 0
        flip_dn = std[j] < 0 and std[j - 1] > 0
        x_up = b.c[j] > dm[j] and b.c[j - 1] <= dm[j - 1]
        x_dn = b.c[j] < dm[j] and b.c[j - 1] >= dm[j - 1]
        if (flip_up and b.c[j] > dm[j]) or (x_up and std[j] > 0):
            out.append(sig(b, j, 1, float(stl[j]), "TL03_DEMA_ST_LONG"))
        elif (flip_dn and b.c[j] < dm[j]) or (x_dn and std[j] < 0):
            out.append(sig(b, j, -1, float(stl[j]), "TL03_DEMA_ST_SHORT"))
    return sorted_out(out)


def tl03_x(m, B, p, cache):
    b = B[15]
    _, std = ctx(m, B, 15, cache).supertrend(12, 3.0)
    return XExits(target_r=None, xbars=b, xlong=std < 0, xshort=std > 0)


def tl04(m, B, p, cache):
    """EMA 200 trend + RSI above (below) 50 + a closed engulfing candle; stop two candle-lengths away; 2R."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e200, rsi = c.ema(200), c.rsi(14)
    out = []
    for j in range(205, len(b.c)):
        if bull_engulf(b, j) and b.c[j] > e200[j] and rsi[j] > 50:
            d = 2 * rng(b, j)
            out.append(sig(b, j, 1, float(b.c[j] - d), "TL04_ENGULF_LONG", info={"stop_dist": d}))
        elif bear_engulf(b, j) and b.c[j] < e200[j] and rsi[j] < 50:
            d = 2 * rng(b, j)
            out.append(sig(b, j, -1, float(b.c[j] + d), "TL04_ENGULF_SHORT", info={"stop_dist": d}))
    return sorted_out(out)


# ═══ Jesse Rogers ══════════════════════════════════════════════════════════════════════════

def jr01(m, B, p, cache):
    """"First Candle Rule": the 9:30-9:45 range; the first 5-minute FVG through it (one of its candles closing outside);
    a limit at the gap's near edge until 12:00 NY; stop at candle 1 of the gap; 2R."""
    b = B[5]
    out = []
    for d in range(m.n_days):
        rg = ny_range(b, d, NY_OPEN, 15)
        if rg is None:
            continue
        H, L, last, _ = rg
        rows = [j for j in bars_of_day(b, d) if j > last + 1 and int(b.ny0[j]) < 12 * 60]
        end = rows[-1] if rows else None
        for j in rows:
            if j >= end:
                break
            if gap_up(b, j) and b.l[j] > H and max(b.c[j - 2:j + 1]) > H:
                out.append(sig(b, j, 1, float(b.l[j - 2]), "JR01_FIRST_CANDLE_LONG", entry_limit=float(b.l[j]),
                               expire_k=int(b.i1[end])))
                break
            if gap_dn(b, j) and b.h[j] < L and min(b.c[j - 2:j + 1]) < L:
                out.append(sig(b, j, -1, float(b.h[j - 2]), "JR01_FIRST_CANDLE_SHORT", entry_limit=float(b.h[j]),
                               expire_k=int(b.i1[end])))
                break
    return sorted_out(out)


def _value_area(m, a, z):
    """Value area (70%) and point of control of rows a..z-1, each row's volume at its typical price."""
    tp = (m.h[a:z] + m.l[a:z] + m.c[a:z]) / 3
    v = np.asarray(m.vol[a:z], float)
    if not len(tp) or v.sum() <= 0:
        return None
    order = np.argsort(tp)
    tp, v = tp[order], v[order]
    poc = int(np.argmax(v))
    lo = hi = poc
    acc = v[poc]
    tot = v.sum()
    while acc < 0.7 * tot and (lo > 0 or hi < len(v) - 1):
        left = v[lo - 1] if lo > 0 else -1
        right = v[hi + 1] if hi < len(v) - 1 else -1
        if right >= left:
            hi += 1
            acc += v[hi]
        else:
            lo -= 1
            acc += v[lo]
    return float(tp[lo]), float(tp[hi]), float(tp[poc])


def jr02(m, B, p, cache):
    """"First Candle Value": the 9:30-9:45 value area (1-minute volumes); a 5-minute close back inside after trading
    outside it -> fade to the range's far side (at least 1R); break-even at 1R (bitcoin)."""
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    out = []
    for d in range(m.n_days):
        rg = ny_range(b, d, NY_OPEN, 15)
        if rg is None:
            continue
        H, L, last, first = rg
        va = _value_area(m, int(b.i0[first]), int(b.i1[last]) + 1)
        if va is None:
            continue
        VAL, VAH, _ = va
        ext = {1: None, -1: None}
        for j in bars_of_day(b, d):
            if j <= last or not np.isfinite(a[j]):
                continue
            if int(b.ny0[j]) >= 15 * 60:
                break
            if b.h[j] > VAH:
                ext[-1] = max(ext[-1] or -np.inf, float(b.h[j]))
            if b.l[j] < VAL:
                ext[1] = min(ext[1] or np.inf, float(b.l[j]))
            if ext[-1] is not None and VAL < b.c[j] < VAH and (b.c[j - 1] >= VAH or b.h[j] > VAH):
                stop = ext[-1] + 0.1 * a[j]
                risk = stop - float(b.c[j])
                tgt = L if float(b.c[j]) - L >= risk else float(b.c[j]) - risk
                out.append(sig(b, j, -1, float(stop), "JR02_VALUE_FAIL_SHORT", target_px=float(tgt)))
                break
            if ext[1] is not None and VAL < b.c[j] < VAH and (b.c[j - 1] <= VAL or b.l[j] < VAL):
                stop = ext[1] - 0.1 * a[j]
                risk = float(b.c[j]) - stop
                tgt = H if H - float(b.c[j]) >= risk else float(b.c[j]) + risk
                out.append(sig(b, j, 1, float(stop), "JR02_VALUE_FAIL_LONG", target_px=float(tgt)))
                break
    return sorted_out(out)


def jr02_x(m, B, p, cache):
    return XExits(target_r=None, be_at_r=1.0)


def jr03(m, B, p, cache):
    """The 9:30-9:35 range on 1 minute: a close-beyond break that leaves a FVG outside the range -> enter at the third
    gap candle's close; or, without a gap, a gap formed away from the range after a return; stop at the break candle; 2R."""
    b = B[1]
    out = []
    for d in range(m.n_days):
        rg = ny_range(b, d, NY_OPEN, 5)
        if rg is None:
            continue
        H, L, last, _ = rg
        rows = [j for j in bars_of_day(b, d) if j > last and int(b.ny0[j]) < 11 * 60]
        brk = {}
        done = set()
        returned = {1: False, -1: False}
        for j in rows:
            for side in (1, -1):
                if side in done:
                    continue
                if side not in brk:
                    if (side > 0 and b.c[j] > H) or (side < 0 and b.c[j] < L):
                        brk[side] = j
                    continue
                x = brk[side]
                if (side > 0 and b.l[j] <= H) or (side < 0 and b.h[j] >= L):
                    returned[side] = True
                g_ok = gap_up(b, j) and b.h[j - 2] >= H if side > 0 else gap_dn(b, j) and b.l[j - 2] <= L
                if not g_ok:
                    continue
                if x >= j - 2 or returned[side]:
                    stop = float(b.l[x]) if side > 0 else float(b.h[x])
                    if (b.c[j] - stop) * side > 0:
                        out.append(sig(b, j, side, stop, "JR03_FVG_BREAK_LONG" if side > 0 else "JR03_FVG_BREAK_SHORT"))
                        done.add(side)
    # first valid setup of the day
    first = {}
    for s in sorted_out(out):
        first.setdefault(s.day, s)
    return sorted_out(list(first.values()))


def jr04(m, B, p, cache):
    """The 9:30-9:35 range: a body closing fully outside, then a retest candle that dips back in and closes outside ->
    enter; stop beyond the range midpoint; 2R; first setup of the day."""
    b = B[5]
    out = []
    for d in range(m.n_days):
        rg = ny_range(b, d, NY_OPEN, 5)
        if rg is None:
            continue
        H, L, last, _ = rg
        mid = (H + L) / 2
        side = 0
        for j in bars_of_day(b, d):
            if j <= last:
                continue
            if int(b.ny0[j]) >= 12 * 60:
                break
            if side == 0:
                if min(b.o[j], b.c[j]) > H:
                    side = 1
                elif max(b.o[j], b.c[j]) < L:
                    side = -1
                continue
            if side > 0 and b.l[j] <= H and b.c[j] > H:
                out.append(sig(b, j, 1, float(mid - 0.0001 * mid), "JR04_RETEST_LONG"))
                break
            if side < 0 and b.h[j] >= L and b.c[j] < L:
                out.append(sig(b, j, -1, float(mid + 0.0001 * mid), "JR04_RETEST_SHORT"))
                break
    return sorted_out(out)


def jr05(m, B, p, cache):
    """The 9:30-9:35 range on 1 minute: a FVG through the level, a pullback into it within 30 bars, a candle engulfing
    the retest candle's body -> enter; stop one tick beyond the retest candle; 3R."""
    b = B[1]
    out = []
    for d in range(m.n_days):
        rg = ny_range(b, d, NY_OPEN, 5)
        if rg is None:
            continue
        H, L, last, _ = rg
        rows = [j for j in bars_of_day(b, d) if j > last + 1 and int(b.ny0[j]) < 12 * 60]
        found = False
        for j in rows:
            if found:
                break
            for side in (1, -1):
                if side > 0 and not (gap_up(b, j) and b.h[j - 2] <= H < b.l[j] and max(b.c[j - 2:j + 1]) > H):
                    continue
                if side < 0 and not (gap_dn(b, j) and b.h[j] < L <= b.l[j - 2] and min(b.c[j - 2:j + 1]) < L):
                    continue
                top, bot = (float(b.l[j]), float(b.h[j - 2])) if side > 0 else (float(b.l[j - 2]), float(b.h[j]))
                r = None
                for t in range(j + 1, min(j + 31, rows[-1])):
                    if r is None:
                        if (side > 0 and b.l[t] <= top) or (side < 0 and b.h[t] >= bot):
                            r = t
                        continue
                    lo_b, hi_b = min(b.o[r], b.c[r]), max(b.o[r], b.c[r])
                    eng = (b.c[t] > hi_b and b.o[t] <= lo_b and green(b, t)) if side > 0 else \
                          (b.c[t] < lo_b and b.o[t] >= hi_b and red(b, t))
                    if eng:
                        tick = 1e-4 * b.c[t]
                        stop = float(b.l[r] - tick) if side > 0 else float(b.h[r] + tick)
                        if (b.c[t] - stop) * side > 0:
                            out.append(sig(b, t, side, stop, "JR05_FVG_ENGULF_LONG" if side > 0 else "JR05_FVG_ENGULF_SHORT"))
                            found = True
                        break
                    if (side > 0 and b.l[t] < b.l[r]) or (side < 0 and b.h[t] > b.h[r]):
                        r = t                              # a deeper retest candle replaces it
                if found:
                    break
    return sorted_out(out)


def r3_x(m, B, p, cache):
    return Exits(target_r=3.0)
