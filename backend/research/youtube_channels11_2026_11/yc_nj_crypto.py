"""Neeraj Joshi's bitcoin strategies NJ-27 .. NJ-45 and NJ-47 (analyses/neerajjoshi.md, the "A:" lines are the exact
rules), on BTCUSD minute rows: B maps a timeframe to UTC-aligned bars (5, 15, 60, 240 minutes; bitcoin's trading day
is the UTC date). Conventions as in yc_common: completed bars only, orders from the next row, pivots only once
confirmed. NJ-33 also reads ETHUSD (the `other` market, cut to the same span)."""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import (bars_of_day, bull_engulf, bear_engulf, body, cisd_line, clock_of, ctx, flags_cross, fvg_flags,  # noqa: F401
                       fvg_gap, green, htf_sweeps, in_window, last_bar_before, last_done, latest_pivot_beyond, lw,
                       nearest_pivot_beyond, pivot_lists, red, rng, sig, swing_target, uw, weekday_of, zone_break)
from yc_engine import XExits
from yt_engine import Exits

HOUR_ROWS = 60                       # bitcoin has a row a minute: a time stop of N hourly candles is N x 60 rows


def _sorted(out):
    out.sort(key=lambda s: (s.k, s.side, s.setup))
    return out


# ── NJ-27 20-candle channel breakout with EMA 200 and ATR stops (4-hour), from his Pine strategy ──────────

def nj27(m, B, p, cache):
    b = B[240]
    c = ctx(m, B, 240, cache)
    e200, a = c.ema(200), c.atr_sma(14)
    up, dn = I.prior_highest(b.h, 20), I.prior_lowest(b.l, 20)
    out = []
    for j in range(21, len(b.c)):
        if not (np.isfinite(a[j]) and np.isfinite(up[j]) and np.isfinite(dn[j])):
            continue
        dist = float(max(2.5 * a[j], b.c[j] * 0.0001))
        if b.c[j] > up[j] and b.c[j] > e200[j]:
            out.append(sig(b, j, 1, b.c[j] - dist, "NJ27_BREAKOUT", info={"stop_dist": dist}))
        elif b.c[j] < dn[j] and b.c[j] < e200[j]:
            out.append(sig(b, j, -1, b.c[j] + dist, "NJ27_BREAKDOWN", info={"stop_dist": dist}))
    return out


def nj27_x(m, B, p, cache):
    b = B[240]
    a = ctx(m, B, 240, cache).atr_sma(14)
    return XExits(target_r=None, trail=("chand", b, a, 3.0, "high"), xbars=b,
                  xlong=b.c < I.prior_lowest(b.l, 10), xshort=b.c > I.prior_highest(b.h, 10))


# ── NJ-28 Fibonacci OTE: a 0.618-0.786 tap with an FVG (1-hour swings, 15-minute entries) ─────────────

def nj28(m, B, p, cache):
    b, bh = B[15], B[60]
    a = ctx(m, B, 15, cache).atr(14)
    f = fvg_flags(m, B, 15, cache)
    hv, hi, lv, li, _, _ = ctx(m, B, 60, cache).pivots(2)
    n = len(b.c)
    out = []
    for j in np.flatnonzero(f):
        j = int(j)
        if j < 3 or not np.isfinite(a[j]):
            continue
        q = last_done(bh, int(b.i1[j]))
        if q < 0 or hi[q] < 0 or li[q] < 0:
            continue
        H, L = float(hv[q]), float(lv[q])
        if not H > L:
            continue
        span = H - L
        exp = int(b.i1[min(j + 12, n - 1)])
        if f[j] > 0 and hi[q] > li[q]:                       # up leg (the high came after the low): longs
            if b.i0[j - 2] <= bh.i1[hi[q]]:                    # the gap forms after the swing high
                continue
            z618, z786, z50 = H - 0.618 * span, H - 0.786 * span, H - 0.5 * span
            if b.l[j - 1] <= z618 and b.h[j - 1] >= z786:
                entry = fvg_gap(b, j, 1)[1]                   # the near (upper) edge
                if entry < z50:
                    out.append(sig(b, j, 1, z786 - 0.25 * a[j], "NJ28_OTE_LONG", entry_limit=entry, expire_k=exp))
        elif f[j] < 0 and li[q] > hi[q]:                     # down leg: shorts
            if b.i0[j - 2] <= bh.i1[li[q]]:
                continue
            z618, z786, z50 = L + 0.618 * span, L + 0.786 * span, L + 0.5 * span
            if b.h[j - 1] >= z618 and b.l[j - 1] <= z786:
                entry = fvg_gap(b, j, -1)[0]                  # the near (lower) edge
                if entry > z50:
                    out.append(sig(b, j, -1, z786 + 0.25 * a[j], "NJ28_OTE_SHORT", entry_limit=entry, expire_k=exp))
    return _sorted(out)


def nj28_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-29 1-hour order block retest with a 5-minute CISD ──────────────────────────────────────────────

def _order_blocks(m, B, cache):
    """1-hour order blocks: (the bar that completes the move, side, block low, block high). Bullish: a red candle,
    then two green candles whose bodies add up to at least 2 x ATR 14, leaving a gap above the red candle's high."""
    key = ("nj29_blocks",)
    if key in cache:
        return cache[key]
    bh = B[60]
    a = ctx(m, B, 60, cache).atr(14)
    out = []
    for j in range(2, len(bh.c)):
        ob = j - 2
        if not np.isfinite(a[j]):
            continue
        move = body(bh, j - 1) + body(bh, j)
        if move < 2 * a[j]:
            continue
        if red(bh, ob) and green(bh, j - 1) and green(bh, j) and bh.l[j] > bh.h[ob]:
            out.append((j, 1, float(bh.l[ob]), float(bh.h[ob])))
        elif green(bh, ob) and red(bh, j - 1) and red(bh, j) and bh.h[j] < bh.l[ob]:
            out.append((j, -1, float(bh.l[ob]), float(bh.h[ob])))
    cache[key] = out
    return out


def nj29(m, B, p, cache):
    b, bh = B[5], B[60]
    ah = ctx(m, B, 60, cache).atr(14)
    n5, nh = len(b.c), len(bh.c)
    out = []
    for jk, side, lo, hi in _order_blocks(m, B, cache):
        # live from the first 5-minute candle after the block is known, for 5 days (120 hourly candles) or until an
        # hourly close beyond its far side
        end_h = min(jk + 120, nh - 1)
        for d in range(jk + 1, end_h + 1):
            if (bh.c[d] < lo) if side > 0 else (bh.c[d] > hi):
                end_h = d
                break
        end_row = int(bh.i1[end_h])
        j = int(np.searchsorted(b.i0, int(bh.i1[jk]), "right"))
        while j < n5 and b.i1[j] < end_row:
            if not (b.l[j] <= hi and b.h[j] >= lo):
                j += 1
                continue
            found = None
            for q in range(j + 1, min(j + 37, n5)):
                if b.i1[q] >= end_row:
                    break
                cl = cisd_line(b, q, side, max(1, j - 24))
                if cl is None:
                    continue
                line = cl[0]
                if (b.c[q] > line >= b.c[q - 1]) if side > 0 else (b.c[q] < line <= b.c[q - 1]):
                    found = (q, line)
                    break
            if found is not None:
                q, line = found
                qh = last_done(bh, int(b.i1[q]))
                margin = 0.1 * ah[qh] if qh >= 0 and np.isfinite(ah[qh]) else 0.0
                stop = lo - margin if side > 0 else hi + margin
                out.append(sig(b, q, side, stop, "NJ29_OB_CISD_LONG" if side > 0 else "NJ29_OB_CISD_SHORT",
                               entry_limit=float(line), expire_k=int(b.i1[min(q + 12, n5 - 1)])))
                break                                          # a block is used once it gives a setup
            j += 37                                            # no CISD in time: wait for the next touch
    return _sorted(out)


def nj29_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-30 FVG 50% limit entry, target the last swing (15-minute) ──────────────────────────────────────

def nj30(m, B, p, cache):
    b = B[15]
    a = ctx(m, B, 15, cache).atr(14)
    f = fvg_flags(m, B, 15, cache)
    ph, pl = pivot_lists(m, B, 15, cache, 2)
    n = len(b.c)
    out = []
    for j in np.flatnonzero(f):
        j = int(j)
        side = int(f[j])
        if not np.isfinite(a[j]):
            continue
        g_lo, g_hi = fvg_gap(b, j, side)
        if g_hi - g_lo < 0.2 * a[j]:
            continue
        entry = (g_lo + g_hi) / 2
        stop = g_lo - 0.1 * a[j] if side > 0 else g_hi + 0.1 * a[j]
        level = latest_pivot_beyond(b.h if side > 0 else b.l, ph if side > 0 else pl, j, 2, side, entry)
        tgt = swing_target(side, entry, stop, level, 1.5, 2.0, skip_if_close=True)
        if tgt is None:
            continue
        out.append(sig(b, j, side, stop, "NJ30_FVG50_LONG" if side > 0 else "NJ30_FVG50_SHORT", entry_limit=float(entry),
                       expire_k=int(b.i1[min(j + 24, n - 1)]), target_px=tgt))
    return _sorted(out)


def nj30_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-31 4-hour fractal sweep + 5-minute engulfing / NJ-44 the same sweep, entered on its close ───────

def nj31(m, B, p, cache):
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    n = len(b.c)
    out, seen = [], set()
    for j0, side, _lvl in htf_sweeps(m, B, cache, 240, 5, 2):
        for q in range(j0 + 1, min(j0 + 7, n)):
            if not np.isfinite(a[q]):
                continue
            if (bull_engulf(b, q) if side > 0 else bear_engulf(b, q)) and (q, side) not in seen:
                seen.add((q, side))
                ext = float(b.l[j0:q + 1].min()) if side > 0 else float(b.h[j0:q + 1].max())
                out.append(sig(b, q, side, ext - side * 0.1 * a[q], "NJ31_SWEEP_ENGULF_LONG" if side > 0 else "NJ31_SWEEP_ENGULF_SHORT"))
                break
    return _sorted(out)


def nj31_x(m, B, p, cache):
    return Exits(target_r=2.0)


def nj44(m, B, p, cache):
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    out = []
    for j, side, _lvl in htf_sweeps(m, B, cache, 240, 5, 2):
        if not np.isfinite(a[j]):
            continue
        ext = float(b.l[j]) if side > 0 else float(b.h[j])
        out.append(sig(b, j, side, ext - side * 0.1 * a[j], "NJ44_SWEEP_LONG" if side > 0 else "NJ44_SWEEP_SHORT"))
    return _sorted(out)


def nj44_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-32 candle range theory 2.0 (1-hour range, 5-minute FVG entry) ─────────────────────────────────

def nj32(m, B, p, cache):
    b, bh = B[5], B[60]
    ch = ctx(m, B, 60, cache)
    e50, ah = ch.ema(50), ch.atr(14)
    phl, pll = pivot_lists(m, B, 60, cache, 2)
    a5 = ctx(m, B, 5, cache).atr(14)
    f5 = fvg_flags(m, B, 5, cache)
    n5, nh = len(b.c), len(bh.c)
    out = []
    for R in range(12, nh - 1):
        S = R + 1
        if not np.isfinite(ah[R]):
            continue
        for side in (1, -1):
            if side > 0:
                trend = bh.c[R - 1] > e50[R - 1] and e50[R - 1] > e50[R - 11]
                if not (trend and red(bh, R)):
                    continue
                k = int(np.searchsorted(pll, R - 2, "right"))
                near = any(abs(bh.l[q] - bh.l[R]) <= 0.5 * ah[R] for q in pll[max(0, k - 50):k] if q >= R - 100)
                swept = bh.l[S] < bh.l[R] and bh.l[R] < bh.c[S] < bh.h[R]
            else:
                trend = bh.c[R - 1] < e50[R - 1] and e50[R - 1] < e50[R - 11]
                if not (trend and green(bh, R)):
                    continue
                k = int(np.searchsorted(phl, R - 2, "right"))
                near = any(abs(bh.h[q] - bh.h[R]) <= 0.5 * ah[R] for q in phl[max(0, k - 50):k] if q >= R - 100)
                swept = bh.h[S] > bh.h[R] and bh.l[R] < bh.c[S] < bh.h[R]
            if not (near and swept):
                continue
            s_end = int(bh.i1[S])                              # the sweep is confirmed when its hour closes
            w_end = int(bh.i1[min(S + 1, nh - 1)])             # FVGs during the sweep hour and the next one
            jj = int(np.searchsorted(b.i1, s_end, "left"))     # the 5-minute candle closing with the sweep hour
            j_lo = int(np.searchsorted(b.i0, int(bh.i0[S]), "left"))
            # the opposite side swept and closed back inside after the confirmation cancels the setup
            cancel = None
            for x in range(jj + 1, min(jj + 200, n5)):
                if (b.h[x] > bh.h[R] and b.c[x] < bh.h[R]) if side > 0 else (b.l[x] < bh.l[R] and b.c[x] > bh.l[R]):
                    cancel = x
                    break
            for j in range(max(j_lo + 2, 2), n5):
                if b.i1[j] > w_end:
                    break
                if f5[j] != side:
                    continue
                stamp = max(j, jj)
                if stamp >= n5 or (cancel is not None and cancel <= stamp) or not np.isfinite(a5[stamp]):
                    break
                entry = fvg_gap(b, j, side)[1] if side > 0 else fvg_gap(b, j, side)[0]
                ext = float(b.l[j_lo:stamp + 1].min()) if side > 0 else float(b.h[j_lo:stamp + 1].max())
                exp = int(b.i1[min(stamp + 12, n5 - 1)])
                if cancel is not None:
                    exp = min(exp, int(b.i1[cancel]))
                out.append(sig(b, stamp, side, ext - side * 0.1 * a5[stamp], "NJ32_CRT_LONG" if side > 0 else "NJ32_CRT_SHORT",
                               entry_limit=float(entry), expire_k=exp))
                break
    return _sorted(out)


def nj32_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-33 BTC/ETH SMT divergence (5-minute) ──────────────────────────────────────────────────────────

def nj33(m, B, p, cache, other=None):
    """`other` = (ETHUSD minutes, its bars dict), cut to the same span."""
    if other is None:
        return []
    b = B[5]
    om, oB = other
    ob = oB[5]
    a = ctx(m, B, 5, cache).atr(14)
    ph, pl = ctx(m, B, 5, cache).fractals(1)
    pos = {int(t): i for i, t in enumerate(ob.t0)}
    n = len(b.c)
    hs, ls = [], []
    out = []
    for j in range(2, n):
        q = j - 1                                              # a 3-candle pivot at q is confirmed by bar j
        for kind in ("h", "l"):
            if not (ph[q] if kind == "h" else pl[q]):
                continue
            lst = hs if kind == "h" else ls
            lst.append(q)
            if len(lst) < 2:
                continue
            q1, q2 = lst[-2], lst[-1]
            if q2 - q1 > 36 or j + 2 >= n or not np.isfinite(a[j]):
                continue
            i1, i2, ij = pos.get(int(b.t0[q1])), pos.get(int(b.t0[q2])), pos.get(int(b.t0[j]))
            if i1 is None or i2 is None or ij is None or i1 < 1:
                continue
            if kind == "h":
                o1 = ob.h[i1 - 1:i1 + 2].max()
                o2 = ob.h[i2 - 1:min(i2 + 2, ij + 1)].max()
                if (b.h[q2] > b.h[q1] and o2 < o1) or (b.h[q2] < b.h[q1] and o2 > o1):
                    out.append(sig(b, j + 2, -1, b.h[q2] + 0.1 * a[j], "NJ33_SMT_TOP"))
            else:
                o1 = ob.l[i1 - 1:i1 + 2].min()
                o2 = ob.l[i2 - 1:min(i2 + 2, ij + 1)].min()
                if (b.l[q2] < b.l[q1] and o2 > o1) or (b.l[q2] > b.l[q1] and o2 < o1):
                    out.append(sig(b, j + 2, 1, b.l[q2] - 0.1 * a[j], "NJ33_SMT_BOTTOM"))
    return _sorted(out)


def nj33_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-34 hidden breakeven liquidity re-entry (5-minute) ─────────────────────────────────────────────

def nj34(m, B, p, cache):
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    ph, pl = ctx(m, B, 5, cache).fractals(1)
    n = len(b.c)
    out = []
    for side, piv in ((-1, np.flatnonzero(ph)), (1, np.flatnonzero(pl))):
        for s in piv:
            s = int(s)
            ext0 = float(b.h[s]) if side < 0 else float(b.l[s])
            starts = red if side < 0 else green
            r = next((x for x in range(s + 1, min(s + 7, n)) if starts(b, x)), None)
            if r is None:
                continue
            L = float(b.c[r])
            leg = (ext0 - L) * -side                              # the swing-to-level distance
            if not leg > 0:
                continue
            goal = L + side * leg if side > 0 else L - leg
            e = None
            for x in range(r + 1, min(r + 13, n)):
                if (b.h[x] > ext0) if side < 0 else (b.l[x] < ext0):  # the swing gave way first
                    break
                if (b.l[x] <= goal) if side < 0 else (b.h[x] >= goal):
                    e = x
                    break
            if e is None or not np.isfinite(a[e]):
                continue
            out.append(sig(b, e, side, ext0 - side * 0.1 * a[e], "NJ34_HIDDEN_LONG" if side > 0 else "NJ34_HIDDEN_SHORT",
                           entry_limit=L, expire_k=int(b.i1[min(e + 24, n - 1)])))
    return _sorted(out)


def nj34_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-35 manipulation model at the New York open (IST times, 5-minute) ──────────────────────────────

def nj35(m, B, p, cache):
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        rb = [j for j in rows if 17 * 60 + 30 <= b.ist0[j] < 18 * 60 + 30]
        if len(rb) < 12:
            continue
        H, L = float(max(b.h[j] for j in rb)), float(min(b.l[j] for j in rb))
        last = rows[-1]
        for j in rows:
            if not (18 * 60 + 30 <= b.ist0[j] < 19 * 60 + 30):
                continue
            if b.h[j] > H and L <= b.c[j] < H:
                side = -1
            elif b.l[j] < L and L < b.c[j] <= H:
                side = 1
            else:
                continue
            ext = float(b.h[j]) if side < 0 else float(b.l[j])
            for q in range(j + 1, min(j + 25, last + 1)):
                ext = max(ext, float(b.h[q])) if side < 0 else min(ext, float(b.l[q]))
                cl = cisd_line(b, q, side, max(int(b.b0[d]), j - 12))
                if cl is None or not np.isfinite(a[q]):
                    continue
                line = cl[0]
                if (b.c[q] > line >= b.c[q - 1]) if side > 0 else (b.c[q] < line <= b.c[q - 1]):
                    out.append(sig(b, q, side, ext - side * 0.1 * a[q], "NJ35_NY_LONG" if side > 0 else "NJ35_NY_SHORT",
                                   entry_limit=float(line), expire_k=int(b.i1[min(q + 12, last)])))
                    break
    return _sorted(out)


def nj35_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-36 the two-hour New York range sweep ──────────────────────────────────────────────────────────

def nj36(m, B, p, cache):
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        rb = [j for j in rows if 8 * 60 <= b.ny0[j] < 10 * 60]
        if len(rb) < 24:
            continue
        H, L = float(max(b.h[j] for j in rb)), float(min(b.l[j] for j in rb))
        for j in rows:
            if not (10 * 60 <= b.ny0[j] < 14 * 60) or not np.isfinite(a[j]):
                continue
            if b.h[j] > H and L <= b.c[j] < H:
                out.append(sig(b, j, -1, b.h[j] + 0.1 * a[j], "NJ36_RANGE_HIGH_SWEEP"))
            elif b.l[j] < L and L < b.c[j] <= H:
                out.append(sig(b, j, 1, b.l[j] - 0.1 * a[j], "NJ36_RANGE_LOW_SWEEP"))
    return _sorted(out)


def nj36_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-37 the New York open fair value gap (15-minute, weekdays) ─────────────────────────────────────

def nj37(m, B, p, cache):
    b = B[15]
    a = ctx(m, B, 15, cache).atr(14)
    f = fvg_flags(m, B, 15, cache)
    wd = weekday_of(b, "America/New_York", cache, 15)
    out = []
    for j in np.flatnonzero(f):
        j = int(j)
        side = int(f[j])
        mid = j - 1
        if not (9 * 60 + 15 <= b.ny0[mid] < 10 * 60) or wd[mid] >= 5 or not np.isfinite(a[j]):
            continue
        last = last_bar_before(b, int(b.day[j]), 14 * 60 + 30, "ny")
        if last is None or last <= j:
            continue
        g_lo, g_hi = fvg_gap(b, j, side)
        entry = g_hi if side > 0 else g_lo
        ext = float(b.l[j - 2]) if side > 0 else float(b.h[j - 2])
        out.append(sig(b, j, side, ext - side * 0.1 * a[j], "NJ37_NY_FVG_LONG" if side > 0 else "NJ37_NY_FVG_SHORT",
                       entry_limit=float(entry), expire_k=int(b.i1[last])))
    return _sorted(out)


def nj37_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-38 golden-hour 15-minute range breakout, London and New York ──────────────────────────────────

def nj38(m, B, p, cache):
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    clocks = (("LONDON", clock_of(b, "Europe/London", cache, 5)), ("NEWYORK", b.ny0))
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        for name, clk in clocks:
            rb = [j for j in rows if 8 * 60 <= clk[j] < 8 * 60 + 15]
            if len(rb) < 3:
                continue
            H, L = float(max(b.h[j] for j in rb)), float(min(b.l[j] for j in rb))
            for j in rows:
                if not (8 * 60 + 15 <= clk[j] < 9 * 60 + 15):
                    continue
                if not np.isfinite(a[j]):
                    break
                if b.c[j] > H:
                    out.append(sig(b, j, 1, L - 0.1 * a[j], f"NJ38_{name}_LONG"))
                    break
                if b.c[j] < L:
                    out.append(sig(b, j, -1, H + 0.1 * a[j], f"NJ38_{name}_SHORT"))
                    break
    return _sorted(out)


def nj38_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-39 long-wick rejection at a 1-hour support or resistance ──────────────────────────────────────

def nj39(m, B, p, cache):
    b = B[60]
    a = ctx(m, B, 60, cache).atr(14)
    ph, pl = pivot_lists(m, B, 60, cache, 2)
    out = []
    for j in range(5, len(b.c)):
        r, bd = rng(b, j), body(b, j)
        if not (r > 0 and np.isfinite(a[j])):
            continue
        if lw(b, j) >= 2 * bd and lw(b, j) >= 0.5 * r:
            k = int(np.searchsorted(pl, j - 2, "right"))
            sup = [q for q in pl[max(0, k - 60):k] if q >= j - 100 and b.l[j] < b.l[q] < b.c[j]]
            if sup:
                stop = b.l[j] - 0.1 * a[j]
                lvl = nearest_pivot_beyond(b.h, ph, j, 2, 1, float(b.c[j]), 100)
                out.append(sig(b, j, 1, stop, "NJ39_WICK_SUPPORT", target_px=swing_target(1, float(b.c[j]), stop, lvl, 1.5, 2.0)))
                continue
        if uw(b, j) >= 2 * bd and uw(b, j) >= 0.5 * r:
            k = int(np.searchsorted(ph, j - 2, "right"))
            res = [q for q in ph[max(0, k - 60):k] if q >= j - 100 and b.c[j] < b.h[q] < b.h[j]]
            if res:
                stop = b.h[j] + 0.1 * a[j]
                lvl = nearest_pivot_beyond(b.l, pl, j, 2, -1, float(b.c[j]), 100)
                out.append(sig(b, j, -1, stop, "NJ39_WICK_RESISTANCE", target_px=swing_target(-1, float(b.c[j]), stop, lvl, 1.5, 2.0)))
    return out


def nj39_x(m, B, p, cache):
    return Exits(target_r=None, max_hold=48 * HOUR_ROWS)


# ── NJ-40 Ichimoku triple confirmation (1-hour) ──────────────────────────────────────────────────────

def _ichi(m, B, cache):
    key = ("nj40",)
    if key not in cache:
        b = B[60]
        ten, kij, ca, cb = I.ichimoku(b.h, b.l, b.c)
        raw_a = (ten + kij) / 2
        raw_b = (I.highest(b.h, 52) + I.lowest(b.l, 52)) / 2
        up, dn = flags_cross(ten, kij)
        cache[key] = (ten, kij, ca, cb, raw_a, raw_b, up, dn)
    return cache[key]


def nj40(m, B, p, cache):
    b = B[60]
    a = ctx(m, B, 60, cache).atr(14)
    ten, kij, ca, cb, raw_a, raw_b, up, dn = _ichi(m, B, cache)
    n = len(b.c)
    out = []
    for side, crosses in ((1, np.flatnonzero(up)), (-1, np.flatnonzero(dn))):
        for x in crosses:
            x = int(x)
            for j in range(x, min(x + 3, n)):
                if not (np.isfinite(ca[j]) and np.isfinite(cb[j]) and np.isfinite(a[j])):
                    continue
                still = ten[j] > kij[j] if side > 0 else ten[j] < kij[j]
                if not still:
                    break
                if side > 0 and b.c[j] > max(ca[j], cb[j]) and raw_a[j] > raw_b[j]:
                    out.append(sig(b, j, 1, min(b.l[x], b.c[j] - 0.5 * a[j]), "NJ40_ICHIMOKU_LONG"))
                    break
                if side < 0 and b.c[j] < min(ca[j], cb[j]) and raw_a[j] < raw_b[j]:
                    out.append(sig(b, j, -1, max(b.h[x], b.c[j] + 0.5 * a[j]), "NJ40_ICHIMOKU_SHORT"))
                    break
    return _sorted(out)


def nj40_x(m, B, p, cache):
    *_, up, dn = _ichi(m, B, cache)
    return Exits(target_r=None, xbars=B[60], xlong=dn, xshort=up)


# ── NJ-41 Richard Dennis zone breakout (4-hour) ──────────────────────────────────────────────────────

def nj41(m, B, p, cache):
    b = B[240]
    a20 = ctx(m, B, 240, cache).atr(20)
    ph, pl = pivot_lists(m, B, 240, cache, 2)
    out = []
    for j in range(3, len(b.c)):
        if not np.isfinite(a20[j]):
            continue
        tol = 0.5 * a20[j]
        dist = float(2 * a20[j])
        if zone_break(b.h, ph, j, 2, tol, b.c[j], b.c[j - 1], 1, 120) is not None:
            out.append(sig(b, j, 1, b.c[j] - dist, "NJ41_ZONE_BREAKOUT", info={"stop_dist": dist}))
        elif zone_break(b.l, pl, j, 2, tol, b.c[j], b.c[j - 1], -1, 120) is not None:
            out.append(sig(b, j, -1, b.c[j] + dist, "NJ41_ZONE_BREAKDOWN", info={"stop_dist": dist}))
    return out


def nj41_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ── NJ-42 EMA 200 + double-tested level + MACD cross (15-minute) ─────────────────────────────────────

def nj42(m, B, p, cache):
    b = B[15]
    c = ctx(m, B, 15, cache)
    a, e200 = c.atr(14), c.ema(200)
    line, sg, _ = c.macd()
    up, dn = flags_cross(line, sg)
    ph, pl = pivot_lists(m, B, 15, cache, 2)
    hv, _, lv, _, _, _ = c.pivots(2)
    out = []
    for side, crosses in ((1, np.flatnonzero(up)), (-1, np.flatnonzero(dn))):
        piv, vals = (pl, b.l) if side > 0 else (ph, b.h)
        for j in crosses:
            j = int(j)
            if not (np.isfinite(a[j]) and j >= 210):
                continue
            if side > 0 and not (line[j] < 0 and b.c[j] > e200[j]):
                continue
            if side < 0 and not (line[j] > 0 and b.c[j] < e200[j]):
                continue
            k = int(np.searchsorted(piv, j - 2, "right"))
            P = [int(q) for q in piv[int(np.searchsorted(piv, j - 100, "left")):k]]
            tol = 0.5 * a[j]
            here = b.l[j] if side > 0 else b.h[j]
            best = None
            for q in P:
                grp = [r for r in P if abs(vals[r] - vals[q]) <= tol]
                if len(grp) < 2:
                    continue
                level = float(np.mean([vals[r] for r in grp]))
                if abs(here - level) <= a[j] and (best is None or abs(here - level) < abs(here - best[0])):
                    best = (level, min(vals[r] for r in grp) if side > 0 else max(vals[r] for r in grp))
            if best is None:
                continue
            swing = lv[j] if side > 0 else hv[j]
            edge = best[1] if not np.isfinite(swing) else (min(best[1], swing) if side > 0 else max(best[1], swing))
            out.append(sig(b, j, side, edge - side * 0.1 * a[j], "NJ42_LEVEL_MACD_LONG" if side > 0 else "NJ42_LEVEL_MACD_SHORT"))
    return _sorted(out)


def nj42_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-43 Williams Alligator pullback to the teeth (1-hour) ──────────────────────────────────────────

def _gator(m, B, cache):
    key = ("nj43",)
    if key not in cache:
        b = B[60]
        med = (b.h + b.l) / 2
        s13, s8, s5 = I.smma(med, 13), I.smma(med, 8), I.smma(med, 5)
        cache[key] = (s13, s8, s5, I.shift(s13, 8), I.shift(s8, 5), I.shift(s5, 3))
    return cache[key]


def nj43(m, B, p, cache):
    b = B[60]
    a = ctx(m, B, 60, cache).atr(14)
    s13, s8, _, jaw, teeth, lips = _gator(m, B, cache)
    ph, pl = pivot_lists(m, B, 60, cache, 2)
    n = len(b.c)
    out = []
    for j in range(30, n):
        if not (np.isfinite(a[j]) and np.isfinite(jaw[j]) and np.isfinite(lips[j])):
            continue
        t_next, j_next = float(s8[j - 4]), float(s13[j - 7])   # the lines' values for the next candle (plotted ahead)
        exp = int(b.i1[min(j + 1, n - 1)])
        if lips[j] > teeth[j] > jaw[j] and lips[j] - jaw[j] >= a[j] and b.c[j] > t_next:
            stop = j_next - 0.1 * a[j]
            lvl = latest_pivot_beyond(b.h, ph, j, 2, 1, t_next)
            out.append(sig(b, j, 1, stop, "NJ43_TEETH_LONG", entry_limit=t_next, expire_k=exp,
                           target_px=swing_target(1, t_next, stop, lvl, 1.5, 2.0)))
        elif lips[j] < teeth[j] < jaw[j] and jaw[j] - lips[j] >= a[j] and b.c[j] < t_next:
            stop = j_next + 0.1 * a[j]
            lvl = latest_pivot_beyond(b.l, pl, j, 2, -1, t_next)
            out.append(sig(b, j, -1, stop, "NJ43_TEETH_SHORT", entry_limit=t_next, expire_k=exp,
                           target_px=swing_target(-1, t_next, stop, lvl, 1.5, 2.0)))
    return out


def nj43_x(m, B, p, cache):
    return Exits(target_r=None, max_hold=48 * HOUR_ROWS)


# ── NJ-45 two-candle turn level breakout (15-minute) ─────────────────────────────────────────────────

def nj45(m, B, p, cache):
    b = B[15]
    a = ctx(m, B, 15, cache).atr(14)
    n = len(b.c)
    out = []
    for j in range(10, n):
        if not np.isfinite(a[j]):
            continue
        if b.h[j - 9:j - 1].max() - b.l[j - 9:j - 1].min() > 3 * a[j]:
            continue
        if abs(b.o[j] - b.c[j - 1]) > 0.05 * a[j]:
            continue
        if red(b, j - 1) and green(b, j):                     # a U-turn low: short its break
            side, level = -1, min(b.c[j - 1], b.o[j])
        elif green(b, j - 1) and red(b, j):                   # a turn at the top: buy its break
            side, level = 1, max(b.c[j - 1], b.o[j])
        else:
            continue
        for q in range(j + 1, min(j + 4, n)):
            if (b.c[q] > level) if side > 0 else (b.c[q] < level):
                if in_window(b, q, 8 * 60, 24 * 60) and np.isfinite(a[q]):
                    stop = b.l[q] - 0.1 * a[q] if side > 0 else b.h[q] + 0.1 * a[q]
                    out.append(sig(b, q, side, stop, "NJ45_TURN_BREAK_LONG" if side > 0 else "NJ45_TURN_BREAK_SHORT"))
                break
    return _sorted(out)


def nj45_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ── NJ-47 smoothed Heikin Ashi retest (1-hour) ───────────────────────────────────────────────────────

def _sha(m, B, cache):
    key = ("nj47",)
    if key not in cache:
        b = B[60]
        eo, eh, el, ec = I.ema(b.o, 10), I.ema(b.h, 10), I.ema(b.l, 10), I.ema(b.c, 10)
        hc = (eo + eh + el + ec) / 4
        ho = np.empty(len(hc))
        if len(hc):
            ho[0] = (eo[0] + ec[0]) / 2
            for i in range(1, len(hc)):
                ho[i] = (ho[i - 1] + hc[i - 1]) / 2
        so, sc = I.ema(ho, 10), I.ema(hc, 10)
        cache[key] = (so, sc)
    return cache[key]


def nj47(m, B, p, cache):
    b = B[60]
    c = ctx(m, B, 60, cache)
    a, ba = c.atr(14), c.body_avg(20)
    so, sc = _sha(m, B, cache)
    top, bot = np.maximum(so, sc), np.minimum(so, sc)
    n = len(b.c)
    out = []
    pend_l = pend_s = None
    for j in range(25, n):
        upt = bool((sc[j - 2:j + 1] > so[j - 2:j + 1]).all())
        dnt = bool((sc[j - 2:j + 1] < so[j - 2:j + 1]).all())
        if not upt:
            pend_l = None
        if not dnt:
            pend_s = None
        ok = np.isfinite(a[j]) and np.isfinite(ba[j])
        if ok and pend_l is not None and green(b, j) and body(b, j) >= ba[j] and b.c[j] > top[j]:
            out.append(sig(b, j, 1, b.l[j - 4:j + 1].min() - 0.1 * a[j], "NJ47_SHA_LONG"))
            pend_l = None
        elif upt and b.l[j] <= top[j]:
            pend_l = j
        if ok and pend_s is not None and red(b, j) and body(b, j) >= ba[j] and b.c[j] < bot[j]:
            out.append(sig(b, j, -1, b.h[j - 4:j + 1].max() + 0.1 * a[j], "NJ47_SHA_SHORT"))
            pend_s = None
        elif dnt and b.h[j] >= bot[j]:
            pend_s = j
    return out


def nj47_x(m, B, p, cache):
    return Exits(target_r=3.0)
