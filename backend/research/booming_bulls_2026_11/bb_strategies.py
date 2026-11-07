"""The 17 runnable strategies of specs/PREREGISTRATION.md section 4 (BB-15 is blocked on data).

Each signal function reads COMPLETED bars only: a bar is used after its last minute, and every signal is
stamped with that bar's last minute row (Signal.k), so the engine fills at the next minute. Swings and pivots
are used only once confirmed (a fractal of n bars each side is known n bars later). bb_checks.py verifies
this with a truncation test (signals do not change when later data is cut off).

STRATEGIES maps an id to its markets, variants (signal parameters + exits), limits and forced exit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from bb_engine import Exits, Limits, Signal
from bb_markets import Bars, Minutes, bars as make_bars, ema, rsi, sma

IST_1500, IST_1514 = 15 * 60, 15 * 60 + 14


# ── shared helpers ────────────────────────────────────────────────────────────────────

def green(b: Bars, j) -> bool:
    return b.c[j] > b.o[j]


def red(b: Bars, j) -> bool:
    return b.c[j] < b.o[j]


def upper_wick(b: Bars, j) -> float:
    return b.h[j] - max(b.o[j], b.c[j])


def lower_wick(b: Bars, j) -> float:
    return min(b.o[j], b.c[j]) - b.l[j]


def rng(b: Bars, j) -> float:
    return b.h[j] - b.l[j]


def body(b: Bars, j) -> float:
    return abs(b.c[j] - b.o[j])


def prev_close(m: Minutes, d: int) -> float:
    return float(m.c[m.d1[d - 1] - 1])


def prev_hl(b: Bars, d: int, mode: str = "wick") -> tuple[float, float]:
    a0, a1 = b.b0[d - 1], b.b1[d - 1]
    if mode == "body":
        return float(np.maximum(b.o[a0:a1], b.c[a0:a1]).max()), float(np.minimum(b.o[a0:a1], b.c[a0:a1]).min())
    return float(b.h[a0:a1].max()), float(b.l[a0:a1].min())


def pivots(b: Bars, n: int):
    """Fractal pivots: arrays ph[j]/pl[j] = True if bar j is a swing high/low with n bars each side.
    Known only at bar j + n. Ties count for the earlier bar only (strict on the left)."""
    N = len(b.h)
    ph = np.zeros(N, bool)
    pl = np.zeros(N, bool)
    for j in range(n, N - n):
        hj, lj = b.h[j], b.l[j]
        if hj > b.h[j - n:j].max() and hj >= b.h[j + 1:j + n + 1].max():
            ph[j] = True
        if lj < b.l[j - n:j].min() and lj <= b.l[j + 1:j + n + 1].min():
            pl[j] = True
    return ph, pl


def episodes(b: Bars, js: int, je: int, level: float, above: bool, pc0: float, max_wait: int | None = 6,
             mode: str = "wick", start_ok=None, confirm=None, retry: int = 0):
    """Sweeps/traps of one level within bars js..je-1. above=True: the level is a high (excursion above it,
    trade short on the close back below). pc0 = the close before bar js (or the day's open).
    mode 'wick': an excursion starts on a bar whose high crosses the level while the previous close was
    inside; 'close': on a bar that closes beyond it. The excursion completes on the first bar (the start bar
    itself in wick mode) that closes back inside, if within max_wait bars of the start; confirm(j) must hold
    on that bar, or on one of the next `retry` bars that also close inside. Yields (j_signal, extreme, j_start)
    and also failed completions as (j, extreme, j_start, False) via the 4th field."""
    sgn = 1 if above else -1
    inside_prev = (pc0 - level) * sgn <= 0
    j_start, extreme = None, None
    j = js
    while j < je:
        hi_or_lo = b.h[j] if above else b.l[j]
        closes_beyond = (b.c[j] - level) * sgn > 0
        if j_start is None:
            crosses = (hi_or_lo - level) * sgn > 0 if mode == "wick" else closes_beyond
            if inside_prev and crosses and (start_ok is None or start_ok(j)):
                j_start, extreme = j, hi_or_lo
                if mode == "close":
                    inside_prev = False
                    j += 1
                    continue
            else:
                inside_prev = not closes_beyond
                j += 1
                continue
        # an excursion is open (j_start set); j may equal j_start in wick mode
        extreme = max(extreme, hi_or_lo) if above else min(extreme, hi_or_lo)
        if not closes_beyond:
            if max_wait is not None and j - j_start > max_wait:
                j_start = None
                inside_prev = True
                j += 1
                continue
            ok = confirm is None or confirm(j)
            k = j
            tries = 0
            while not ok and tries < retry and k + 1 < je:
                k += 1
                tries += 1
                extreme = max(extreme, b.h[k]) if above else min(extreme, b.l[k])
                if (b.c[k] - level) * sgn > 0:           # closed beyond again: abandon
                    break
                ok = confirm(k)
            yield (k, extreme, j_start, ok)
            j_start = None
            inside_prev = (b.c[k] - level) * sgn <= 0
            j = k + 1
            continue
        if max_wait is not None and j - j_start >= max_wait:
            j_start = None                               # stayed beyond: a breakout, not a sweep
            inside_prev = False
        j += 1


def in_window(b: Bars, j, clock: str, lo: int, hi: int) -> bool:
    v = b.ist0[j] if clock == "ist" else b.ny0[j]
    return lo <= v < hi


# ── BB-01 Nifty previous-day high/low ─────────────────────────────────────────────────

def sig_bb01(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[5]
    out: list[Signal] = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d] or b.b1[d - 1] - b.b0[d - 1] < 10:
            continue
        PDH, PDL = prev_hl(b, d, prm.get("levels", "body"))
        p = prev_close(m, d)
        BIG, GAPMIN, WIDE, MINSTOP, TOUCH = 0.0032 * p, 0.0012 * p, 0.0020 * p, 0.0004 * p, 0.0003 * p
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        o0 = b.o[s0]
        line_lo, line_hi = min(b.o[s0], b.c[s0]), max(b.o[s0], b.c[s0])
        gap = o0 - p

        def q_long(j):
            r = rng(b, j)
            return green(b, j) and r > 0 and upper_wick(b, j) <= 0.15 * r

        def q_short(j):
            r = rng(b, j)
            return red(b, j) and r > 0 and lower_wick(b, j) <= 0.15 * r

        def make(j, side, base, setup):
            cj = b.c[j]
            stop = base - side * 0.15 * abs(cj - base)
            if abs(cj - stop) > WIDE:
                ext = b.l[j] if side > 0 else b.h[j]
                stop = ext - side * 0.15 * abs(cj - ext)
            if abs(cj - stop) < MINSTOP or (cj - stop) * side <= 0:
                stop = cj - side * MINSTOP
            return Signal(d, int(b.i1[j]), side, float(stop), setup, {"PDH": PDH, "PDL": PDL})

        sides = {}
        for sgn, L in ((1, PDH), (-1, PDL)):    # sgn=+1: the high (long breakout / short trap)
            sides[sgn] = {"L": L, "armed": (o0 - L) * sgn <= 0, "live": False, "brk": None, "ext": None,
                          "any": False, "first": None}
        sig = None
        pc = o0
        sess_hi, sess_lo = -np.inf, np.inf
        for j in range(s0, s1):
            if b.ist0[j] > 14 * 60 + 55:
                break
            cj, hj, lj = b.c[j], b.h[j], b.l[j]
            sess_hi, sess_lo = max(sess_hi, hj), min(sess_lo, lj)
            # gap fill (before 11:00: the signal bar must close by 11:00)
            if j > s0 and b.ist0[j] <= 10 * 60 + 55 and abs(gap) >= GAPMIN:
                if gap > 0 and cj < line_lo <= pc and (cj - p) >= GAPMIN and q_short(j):
                    sig = make(j, -1, sess_hi, "G")
                elif gap < 0 and cj > line_hi >= pc and (p - cj) >= GAPMIN and q_long(j):
                    sig = make(j, 1, sess_lo, "G")
            if sig is None:
                for sgn in (1, -1):
                    S = sides[sgn]
                    L = S["L"]
                    beyond = (cj - L) * sgn > 0
                    was_inside = (pc - L) * sgn <= 0
                    if not S["armed"]:
                        if not beyond:
                            S["armed"] = True
                        continue
                    q_with = q_long if sgn > 0 else q_short     # quality for a trade WITH the break
                    q_against = q_short if sgn > 0 else q_long
                    ext_j = hj if sgn > 0 else lj
                    # retest of a broken level
                    near = (lj <= L + TOUCH) if sgn > 0 else (hj >= L - TOUCH)
                    if S["any"] and j > S["first"] and near and beyond and q_with(j):
                        sig = make(j, sgn, lj if sgn > 0 else hj, "R")
                        break
                    if not S["live"]:
                        if was_inside and beyond:
                            S.update(live=True, brk=j, ext=ext_j, any=True, first=S["first"] if S["first"] is not None else j)
                            if body(b, j) >= BIG and q_with(j):
                                sig = make(j, sgn, (hj + lj) / 2, "B_big")
                                break
                        continue
                    S["ext"] = max(S["ext"], hj) if sgn > 0 else min(S["ext"], lj)
                    if not beyond:
                        S["live"] = False
                        if q_against(j):
                            sig = make(j, -sgn, S["ext"], "T")
                            break
                    elif q_with(j):
                        brk = S["brk"]
                        base = min(b.l[brk], lj) if sgn > 0 else max(b.h[brk], hj)
                        sig = make(j, sgn, base, "B")
                        break
            pc = cj
            if sig is not None:
                break
        if sig is not None:
            out.append(sig)
    return out


# ── BB-02 15-minute ORB ───────────────────────────────────────────────────────────────

def sig_bb02(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[5]
    out = []
    for d in range(1, m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        if s1 - s0 < 10:
            continue
        p = prev_close(m, d) if m.prev_ok[d] else b.o[s0]
        orh, orl = b.h[s0:s0 + 3].max(), b.l[s0:s0 + 3].min()
        for j in range(s0 + 3, s1):
            if b.ist0[j] > 14 * 60 + 55:
                break
            r = rng(b, j)
            if r <= 0 or body(b, j) < 0.30 * r:
                continue
            cj = b.c[j]
            side = 1 if cj > orh else -1 if cj < orl else 0
            if not side:
                continue
            ext = b.l[j] if side > 0 else b.h[j]
            stop = ext - side * 0.0002 * p
            if abs(cj - stop) > 0.0018 * p:
                edge = (orh if side > 0 else orl) - side * 0.0002 * p
                if (cj - edge) * side > 0 and abs(cj - edge) < abs(cj - stop):
                    stop = edge
            if abs(cj - stop) < 0.0004 * p:
                stop = cj - side * 0.0004 * p
            out.append(Signal(d, int(b.i1[j]), side, float(stop), "ORB", {"orh": orh, "orl": orl}))
    return out


# ── BB-03 Nifty + BankNifty synchronised break ────────────────────────────────────────

def sig_bb03(m: Minutes, B: dict, prm: dict, other: Minutes, Bo: dict) -> list[Signal]:
    b, bo = B[5], Bo[5]
    odays = {str(other.date[d]): d for d in range(other.n_days)}
    out = []
    use_cd = prm.get("current_day", True)
    for d in range(1, m.n_days):
        e = odays.get(str(m.date[d]))
        if e is None or e == 0 or not (m.prev_ok[d] and other.prev_ok[e]):
            continue
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        t0, t1 = int(bo.b0[e]), int(bo.b1[e])
        if s1 - s0 != t1 - t0 or s1 - s0 < 10:
            continue
        p = prev_close(m, d)
        lv = [prev_hl(b, d), prev_hl(bo, e)]
        for off in range(3, s1 - s0):
            j, k = s0 + off, t0 + off
            if b.ist0[j] < 9 * 60 + 30 or b.ist0[j] > 14 * 60 + 25:
                continue
            fired = 0
            for side in (1, -1):
                ok_all = True
                for (bb, jj, base0, (ph, pl)) in ((b, j, s0, lv[0]), (bo, k, t0, lv[1])):
                    c, pc = bb.c[jj], bb.c[jj - 1]
                    col = green(bb, jj) if side > 0 else red(bb, jj)
                    lvl_prev = ph if side > 0 else pl
                    brk = (c > lvl_prev >= pc) if side > 0 else (c < lvl_prev <= pc)
                    if use_cd and not brk:
                        cd = bb.h[base0:jj].max() if side > 0 else bb.l[base0:jj].min()
                        brk = c > cd if side > 0 else c < cd
                    if not (col and brk):
                        ok_all = False
                        break
                if ok_all:
                    fired = side
                    break
            if fired:
                ext = b.h[j] if fired < 0 else b.l[j]
                out.append(Signal(d, int(b.i1[j]), fired, float(ext - fired * 0.0002 * p), "SYNC"))
                break
    return out


# ── BB-04 zone trap with RSI divergence (15m) ─────────────────────────────────────────

def sig_bb04(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[15]
    R = rsi(b.c, 14)
    ph, pl = pivots(b, 2)
    need_div = prm.get("rsi", True)
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        a0, a1 = int(b.b0[d - 1]), int(b.b1[d - 1])
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        if a1 - a0 < 10 or s1 - s0 < 10:
            continue
        p = prev_close(m, d)
        hi_top, hi_bot = b.h[a0:a1].max(), b.c[a0:a1].max()
        lo_bot, lo_top = b.l[a0:a1].min(), b.c[a0:a1].min()
        firsts = []
        for sgn, top, bot in ((1, hi_top, hi_bot), (-1, lo_bot, lo_top)):
            pc = b.o[s0]
            j = s0
            found = None
            while j < s1 and found is None:
                if b.ist0[j] > 14 * 60 + 45:
                    break
                broke = (b.c[j] > top >= pc) if sgn > 0 else (b.c[j] < top <= pc)
                if not broke:
                    pc = b.c[j]
                    j += 1
                    continue
                ext, xi = (b.h[j], j) if sgn > 0 else (b.l[j], j)
                jend = j
                for k in range(j + 1, min(j + 7, s1)):
                    if b.ist0[k] > 14 * 60 + 45:
                        break
                    jend = k
                    if (b.h[k] > ext) if sgn > 0 else (b.l[k] < ext):
                        ext, xi = (b.h[k], k) if sgn > 0 else (b.l[k], k)
                    back = (b.c[k] < bot and red(b, k)) if sgn > 0 else (b.c[k] > bot and green(b, k))
                    if not back:
                        continue
                    ok = True
                    if need_div:
                        ok = False
                        piv = ph if sgn > 0 else pl
                        for q in range(xi - 1, max(xi - 31, 0), -1):
                            if piv[q] and q + 2 <= k:
                                ok = (b.h[xi] > b.h[q] and R[xi] < R[q]) if sgn > 0 else (b.l[xi] < b.l[q] and R[xi] > R[q])
                                break
                    if ok:
                        found = Signal(d, int(b.i1[k]), -sgn, float(ext + sgn * 0.0002 * p), "TRAP_RSI" if need_div else "TRAP")
                    break
                pc = b.c[jend]
                j = jend + 1
            if found is not None:
                firsts.append(found)
        if firsts:
            out.append(min(firsts, key=lambda s_: s_.k))
    return sorted(out, key=lambda s: s.k)


# ── BB-05 SMC structure break into an order block (BankNifty 5m) ──────────────────────

def sig_bb05(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[5]
    ph, pl = pivots(b, 2)
    out = []
    for d in range(1, m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        if s1 - s0 < 20:
            continue
        p = prev_close(m, d) if m.prev_ok[d] else b.o[s0]
        sh = sl = None            # last confirmed swing high/low: (price, index)
        trend = 0
        pend = {1: None, -1: None}   # direction -> (ob_low, ob_high, created_j)
        for j in range(s0, s1):
            q = j - 2
            if q >= s0 + 2:
                if ph[q]:
                    sh = (b.h[q], q)
                if pl[q]:
                    sl = (b.l[q], q)
            c = b.c[j]
            # pending order-block entries (blocks made on earlier bars)
            for side in (1, -1):
                P = pend[side]
                if P is None:
                    continue
                lo_, hi_, made = P
                if j - made > 24 or (side > 0 and c < lo_) or (side < 0 and c > hi_):
                    pend[side] = None
                    continue
                touch = b.l[j] <= hi_ if side > 0 else b.h[j] >= lo_
                if touch and (green(b, j) if side > 0 else red(b, j)) and 9 * 60 + 30 <= b.ist0[j] <= 14 * 60 + 55:
                    stop = (lo_ - 0.0002 * p) if side > 0 else (hi_ + 0.0002 * p)
                    if (c - stop) * side > 0:
                        out.append(Signal(d, int(b.i1[j]), side, float(stop), "OB"))
                    pend[side] = None
            # structure breaks
            if sh is not None and c > sh[0]:
                lo_i = sh[1] + int(np.argmin(b.l[sh[1]:j + 1]))
                ob = next((i for i in range(lo_i, max(lo_i - 6, s0 - 1), -1) if red(b, i)), None)
                if ob is not None:
                    pend[1] = (b.l[ob], b.h[ob], j)
                trend, sh = 1, None
            elif sl is not None and c < sl[0]:
                hi_i = sl[1] + int(np.argmax(b.h[sl[1]:j + 1]))
                ob = next((i for i in range(hi_i, max(hi_i - 6, s0 - 1), -1) if green(b, i)), None)
                if ob is not None:
                    pend[-1] = (b.l[ob], b.h[ob], j)
                trend, sl = -1, None
    return out


# ── BB-06 gap + first candle through the 15m 200 MA ───────────────────────────────────

def sig_bb06(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[15]
    ma = sma(b.c, 200)
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        s0, e_prev = int(b.b0[d]), int(b.b1[d - 1]) - 1
        if not (np.isfinite(ma[s0]) and np.isfinite(ma[e_prev])):
            continue
        p = prev_close(m, d)
        gap = b.o[s0] - p
        if gap >= 0.0012 * p and b.c[s0] > ma[s0] and b.c[e_prev] < ma[e_prev] and green(b, s0):
            out.append(Signal(d, int(b.i1[s0]), 1, float(b.l[s0] - 0.0002 * p), "GAP_MA"))
        elif gap <= -0.0012 * p and b.c[s0] < ma[s0] and b.c[e_prev] > ma[e_prev] and red(b, s0):
            out.append(Signal(d, int(b.i1[s0]), -1, float(b.h[s0] + 0.0002 * p), "GAP_MA"))
    return out


# ── sweep families on 24-hour markets (BB-07, BB-08, BB-10) ───────────────────────────

def _day_atr(m: Minutes, n=14) -> np.ndarray:
    hi = np.maximum.reduceat(m.h, m.d0)
    lo = np.minimum.reduceat(m.l, m.d0)
    r = hi - lo
    out = np.full(len(r), np.nan)
    for d in range(n, len(r)):
        out[d] = r[d - n:d].mean()
    return out


def _window(m: Minutes, b: Bars, j: int, win) -> bool:
    clock, lo, hi = win
    if clock == "ny_gold":     # BB-13 on gold: 08:30 New York to 22:00 IST, never the session's first evening
        return 8 * 60 + 30 <= b.ny0[j] < 17 * 60 and 12 * 60 <= b.ist0[j] < 22 * 60
    if not in_window(b, j, clock, lo, hi):
        return False
    if m.name in ("XAUUSD", "EURUSD", "GBPUSD") and clock == "ist" and b.ny0[j] >= 17 * 60:
        return False      # never the session's first evening
    return True


def _sweep_family(m: Minutes, B: dict, prm: dict, levels_fn, buffer_pct: float, setup: str,
                  min_stop_pct: float = 0.0, colour: bool = False, retry: int = 0, max_wait=6,
                  mode="wick", start_win=None) -> list[Signal]:
    """For each day, levels_fn(d) -> list of (level, above, j_first, j_last) bar spans to scan."""
    b = B[prm.get("tf", 5)]
    win = prm["window"]
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        p = prev_close(m, d)
        spans = levels_fn(d)
        for (level, above, js, je, pc0) in spans:
            side = -1 if above else 1

            def confirm(j, side=side):
                return (red(b, j) if side < 0 else green(b, j)) if colour else True
            sw = start_win or win
            for (k, ext, j0, ok) in episodes(b, js, je, level, above, pc0, max_wait, mode,
                                             start_ok=lambda j: _window(m, b, j, sw), confirm=confirm, retry=retry):
                if not ok or not _window(m, b, k, win):
                    continue
                stop = ext - side * buffer_pct * p
                c = b.c[k]
                if min_stop_pct and abs(c - stop) < min_stop_pct * p:
                    stop = c - side * min_stop_pct * p
                if (c - stop) * side <= 0:
                    continue
                out.append(Signal(d, int(b.i1[k]), side, float(stop), setup, {"level": level}))
    out.sort(key=lambda s: s.k)
    return out


def _pdhl_spans(m: Minutes, b: Bars, d: int, mode="wick"):
    s0, s1 = int(b.b0[d]), int(b.b1[d])
    if b.b1[d - 1] - b.b0[d - 1] < 5:
        return []
    H, L = prev_hl(b, d, mode)
    pc0 = b.o[s0]
    return [(H, True, s0, s1, pc0), (L, False, s0, s1, pc0)]


def sig_bb07(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[5]
    out = _sweep_family(m, B, prm, lambda d: _pdhl_spans(m, b, d), 0.0007, "PDHL_SWEEP")
    if prm.get("current_day"):
        atr = _day_atr(m)
        win = prm["window"]
        for d in range(15, m.n_days):
            if not np.isfinite(atr[d]):
                continue
            p = prev_close(m, d)
            s0, s1 = int(b.b0[d]), int(b.b1[d])
            # current-day high/low sweeps: candle j trades beyond the day's extreme so far and closes back
            for j in range(s0 + 1, s1):
                if not _window(m, b, j, win):
                    continue
                hi, lo = b.h[s0:j].max(), b.l[s0:j].min()
                if hi - lo < 0.75 * atr[d]:
                    continue
                if b.h[j] > hi and b.c[j] < hi:
                    out.append(Signal(d, int(b.i1[j]), -1, float(b.h[j] + 0.0007 * p), "CDH_SWEEP"))
                    break
                if b.l[j] < lo and b.c[j] > lo:
                    out.append(Signal(d, int(b.i1[j]), 1, float(b.l[j] - 0.0007 * p), "CDL_SWEEP"))
                    break
        out.sort(key=lambda s: s.k)
    return out


def sig_bb08(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[5]
    return _sweep_family(m, B, prm, lambda d: _pdhl_spans(m, b, d), 0.0002, "PDHL_TRAP", colour=True, retry=1)


def sig_bb10(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[5]
    mode = prm.get("range", "body")

    def spans(d):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        idx = [j for j in range(s0, s1) if 11 * 60 + 30 <= b.ist0[j] < 12 * 60 + 30 and b.ny0[j] < 17 * 60]
        if len(idx) < 8:
            return []
        if mode == "body":
            H = max(max(b.o[j], b.c[j]) for j in idx)
            L = min(min(b.o[j], b.c[j]) for j in idx)
        else:
            H, L = max(b.h[j] for j in idx), min(b.l[j] for j in idx)
        js = idx[-1] + 1
        pc0 = b.c[idx[-1]]
        return [(H, True, js, s1, pc0), (L, False, js, s1, pc0)]
    return _sweep_family(m, B, prm, spans, 0.0003, "RANGE_SWEEP")


# ── BB-09 value-area trap ─────────────────────────────────────────────────────────────

def value_area(m: Minutes, a: int, z: int, pct: float, rows: int = 24):
    lo, hi = m.l[a:z].min(), m.h[a:z].max()
    if not hi > lo:
        return None
    step = (hi - lo) / rows
    r0 = np.clip(((m.l[a:z] - lo) / step).astype(int), 0, rows - 1)
    r1 = np.clip(((m.h[a:z] - lo) / step).astype(int), 0, rows - 1)
    w = m.vol[a:z].astype(float) / (r1 - r0 + 1)
    diff = np.zeros(rows + 1)
    np.add.at(diff, r0, w)
    np.add.at(diff, r1 + 1, -w)
    prof = np.cumsum(diff)[:rows]
    total = prof.sum()
    poc = int(np.argmax(prof))
    lo_r = hi_r = poc
    acc = prof[poc]
    while acc < pct * total:
        up = prof[hi_r + 1] if hi_r + 1 < rows else -1.0
        dn = prof[lo_r - 1] if lo_r - 1 >= 0 else -1.0
        if up < 0 and dn < 0:
            break
        if up >= dn:
            hi_r += 1
            acc += up
        else:
            lo_r -= 1
            acc += dn
    return lo + lo_r * step, lo + (hi_r + 1) * step


def sig_bb09(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[5]
    pct = prm.get("va", 0.70)

    def spans(d):
        a = int(m.d0[d - 1])
        seg = np.flatnonzero((m.ist[m.d0[d]:m.d1[d]] >= 16 * 60) & (m.ny[m.d0[d]:m.d1[d]] < 17 * 60))
        if not len(seg):
            return []
        z = int(m.d0[d] + seg[0])
        va = value_area(m, a, z, pct)
        if va is None:
            return []
        VAL, VAH = va
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        js = s0 + int(np.searchsorted(b.i0[s0:s1], z))
        if js >= s1:
            return []
        pc0 = b.o[js]
        return [(VAH, True, js, s1, pc0), (VAL, False, js, s1, pc0)]
    return _sweep_family(m, B, prm, spans, 0.0005, "VA_TRAP", min_stop_pct=0.0018)


# ── BB-11 forex 10:00 IST range trap (15m) ────────────────────────────────────────────

def sig_bb11(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[15]
    void_rule = prm.get("void", True)
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        p = prev_close(m, d)
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        pre = [j for j in range(s0, s1) if b.ist0[j] < 10 * 60 and (b.ny0[j] >= 17 * 60 or b.ist0[j] >= 4 * 60)]
        if len(pre) < 8:
            continue
        tops = [max(b.o[j], b.c[j]) for j in pre]
        bots = [min(b.o[j], b.c[j]) for j in pre]
        H, L = max(tops), min(bots)
        last = pre[-1]
        jr = last
        if tops[-1] == H and green(b, last):        # still rising at 10:00: wait for the turn
            k = last + 1
            while k < s1 and not red(b, k):
                H = max(H, max(b.o[k], b.c[k]))
                k += 1
            if k < s1:
                H = max(H, max(b.o[k], b.c[k]))
            jr = max(jr, k)
        if bots[-1] == L and red(b, last):
            k = last + 1
            while k < s1 and not green(b, k):
                L = min(L, min(b.o[k], b.c[k]))
                k += 1
            if k < s1:
                L = min(L, min(b.o[k], b.c[k]))
            jr = max(jr, k)
        height = H - L
        if not height > 0 or jr + 1 >= s1:
            continue
        cands = []
        for level, above in ((H, True), (L, False)):
            side = -1 if above else 1

            def good(j, side=side):
                r = rng(b, j)
                adverse = lower_wick(b, j) if side < 0 else upper_wick(b, j)
                col = red(b, j) if side < 0 else green(b, j)
                return r > 0 and col and adverse <= 0.30 * r
            for (k, ext, j0, ok) in episodes(b, jr + 1, s1, level, above, b.c[jr], None, "close",
                                             start_ok=lambda j: b.ny0[j] < 17 * 60 or b.ist0[j] < 4 * 60,
                                             confirm=good, retry=2):
                cands.append((k, side, ext, ok))
        cands.sort()
        if void_rule and any(10 * 60 <= b.ist0[k] < 11 * 60 + 45 for (k, _, _, _) in cands):
            continue
        for (k, side, ext, ok) in cands:
            if not ok or not (11 * 60 + 45 <= b.ist0[k] <= 21 * 60) or b.ny0[k] >= 17 * 60:
                continue
            c = b.c[k]
            stop = ext - side * 0.0002 * p
            if abs(stop - c) > 0.6 * height:
                stop = c - side * 0.55 * height
            if (c - stop) * side > 0:
                out.append(Signal(d, int(b.i1[k]), side, float(stop), "RANGE10_TRAP"))
                break
    return out


# ── BB-12 400 EMA trap (15m) ──────────────────────────────────────────────────────────

def sig_bb12(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[15]
    E = ema(b.c, 400)
    stop_mode = prm.get("stop", "trap")
    out = []
    for d in range(1, m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        p = prev_close(m, d) if m.prev_ok[d] else b.o[s0]
        if s0 < 400:
            continue
        sidebar = next((j for j in range(s0, s1) if b.ist0[j] == 12 * 60 and b.ny0[j] < 17 * 60), None)
        if sidebar is None:
            continue
        side = 1 if b.c[sidebar] > E[sidebar] else -1
        touch = None
        for j in range(sidebar, s1):
            if not (12 * 60 <= b.ist0[j] < 22 * 60) or b.ny0[j] >= 17 * 60:
                break
            through = b.l[j] < E[j] if side > 0 else b.h[j] > E[j]
            if through:
                touch = j
            if touch is None or j - touch > 6:
                continue

            def ok_dir(i):
                return (green(b, i) and b.c[i] > E[i]) if side > 0 else (red(b, i) and b.c[i] < E[i])

            def strong(i):
                r = rng(b, i)
                return r > 0 and body(b, i) >= 0.5 * r

            def clean(i):
                r = rng(b, i)
                return r > 0 and (upper_wick(b, i) if side > 0 else lower_wick(b, i)) <= 0.10 * r
            fire = False
            if ok_dir(j) and j >= 10 and rng(b, j) > max(rng(b, i) for i in range(j - 10, j)):
                fire = True
            elif j - 1 >= touch and ok_dir(j) and ok_dir(j - 1) and strong(j) and strong(j - 1) \
                    and (clean(j) or clean(j - 1)) and (b.c[j] - b.c[j - 1]) * side > 0:
                fire = True
            if fire:
                if stop_mode == "trap":
                    ext = b.l[touch:j + 1].min() if side > 0 else b.h[touch:j + 1].max()
                else:
                    ext = E[j]
                stop = ext - side * 0.0002 * p
                if (b.c[j] - stop) * side > 0:
                    out.append(Signal(d, int(b.i1[j]), side, float(stop), "EMA400_TRAP"))
                break
    return out


# ── BB-13 "prop-firm" inside-body breakout (5m) ───────────────────────────────────────

def sig_bb13(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[5]
    win = prm["window"]
    two = prm.get("stop", "one") == "two"
    out = []
    for d in range(1, m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        p = prev_close(m, d) if m.prev_ok[d] else b.o[s0]
        done = False
        for j1 in range(s0, s1 - 2):
            if done:
                break
            for side in (1, -1):
                mother_ok = red(b, j1) if side > 0 else green(b, j1)
                if not mother_ok:
                    continue
                j2 = j1 + 1
                t1, b1_ = max(b.o[j1], b.c[j1]), min(b.o[j1], b.c[j1])
                if not (max(b.o[j2], b.c[j2]) <= t1 and min(b.o[j2], b.c[j2]) >= b1_):
                    continue
                for jx in (j1 + 2, j1 + 3):
                    if jx >= s1:
                        break
                    c = b.c[jx]
                    brk = c > b.h[j1] if side > 0 else c < b.l[j1]
                    opp = c < b.l[j1] if side > 0 else c > b.h[j1]
                    if opp:
                        break
                    if not brk:
                        continue
                    r = rng(b, jx)
                    col = green(b, jx) if side > 0 else red(b, jx)
                    if col and r > 0 and body(b, jx) >= 0.70 * r and _window(m, b, jx, win):
                        if two:
                            ext = min(b.l[jx], b.l[jx - 1]) if side > 0 else max(b.h[jx], b.h[jx - 1])
                        else:
                            ext = b.l[jx] if side > 0 else b.h[jx]
                        stop = ext - side * 0.0002 * p
                        if (c - stop) * side > 0:
                            out.append(Signal(d, int(b.i1[jx]), side, float(stop), "INSIDE_BODY"))
                            done = True
                    break
                if done:
                    break
    out.sort(key=lambda s: s.k)
    return out


# ── BB-14 inside candle with the poke filter ──────────────────────────────────────────

def sig_bb14(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[prm.get("tf", 5)]
    range_stop = prm.get("stop", "candle") == "range"
    R = b.h - b.l
    cs = np.cumsum(np.r_[0.0, R])
    out = []
    for d in range(1, m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        p = prev_close(m, d) if m.prev_ok[d] else b.o[s0]
        poke = 0.00025 * p
        j = max(s0, 20)
        while j < s1 - 3:
            mean20 = (cs[j] - cs[j - 20]) / 20
            r = R[j]
            mo_ok = (r > 0 and body(b, j) >= 0.6 * r and r >= mean20 and upper_wick(b, j) > 0 and lower_wick(b, j) > 0)
            if not mo_ok:
                j += 1
                continue
            H, L = b.h[j], b.l[j]
            ins = all(L <= b.o[i] <= H and L <= b.c[i] <= H for i in (j + 1, j + 2))
            if not ins:
                j += 1
                continue
            cancel_long = cancel_short = False
            fired = False
            for i in range(j + 1, min(j + 9, s1)):
                c = b.c[i]
                if i >= j + 3 and (c > H or c < L):
                    side = 1 if c > H else -1
                    in_win = b.ny0[i] >= 9 * 60 + 30 and b.ist0[i] >= 12 * 60
                    if in_win and not (cancel_long if side > 0 else cancel_short):
                        ext = (L if side > 0 else H) if range_stop else (b.l[i] if side > 0 else b.h[i])
                        stop = ext - side * 0.00005 * p
                        if (c - stop) * side > 0:
                            out.append(Signal(d, int(b.i1[i]), side, float(stop), "INSIDE_CANDLE"))
                    fired = True
                    j = i
                    break
                if c > H or c < L:          # closed outside before the 2 inside candles were done
                    fired = True
                    j = i
                    break
                if b.l[i] < L - poke:
                    cancel_long = True
                if b.h[i] > H + poke:
                    cancel_short = True
            j += 1
    return out


# ── BB-16 retracement-zone sweep (1h legs, 5m entries) ────────────────────────────────

def sig_bb16(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    h1, b = B[60], B[5]
    zlo, zhi = prm.get("zone", (0.50, 0.618))
    ph, pl = pivots(h1, 3)
    tr = np.maximum(h1.h[1:], h1.c[:-1]) - np.minimum(h1.l[1:], h1.c[:-1])
    tr = np.r_[h1.h[0] - h1.l[0], tr]
    atr = np.full(len(tr), np.nan)
    cs = np.cumsum(np.r_[0.0, tr])
    atr[14:] = (cs[14:-1] - cs[:-15]) / 14 if len(tr) > 15 else np.nan
    # legs, in order of the minute they become known (the close of the confirming hour)
    legs = []
    last_pl = last_ph = None
    for j in range(3, len(h1.h)):
        q = j - 3
        if pl[q]:
            last_pl = q
        if ph[q]:
            last_ph = q
        if ph[q] and last_pl is not None and last_pl < q and np.isfinite(atr[q]):
            H, L = h1.h[q], h1.l[last_pl]
            if H - L >= 3 * atr[q]:
                legs.append((int(h1.i1[j]), 1, H, L))
        if pl[q] and last_ph is not None and last_ph < q and np.isfinite(atr[q]):
            H, L = h1.h[last_ph], h1.l[q]
            if H - L >= 3 * atr[q]:
                legs.append((int(h1.i1[j]), -1, H, L))
    p5h, p5l = pivots(b, 2)
    out = []
    leg_i = 0
    cur = None
    used_day = set()
    nb = len(b.c)
    known_k = np.array([x[0] for x in legs], dtype=np.int64) if legs else np.zeros(0, np.int64)
    last5h = last5l = None
    for j in range(2, nb):
        q = j - 2
        if p5h[q] and b.day[q] == b.day[j]:
            last5h = (b.h[q], q)
        if p5l[q] and b.day[q] == b.day[j]:
            last5l = (b.l[q], q)
        while leg_i < len(legs) and known_k[leg_i] < b.i0[j]:
            cur = legs[leg_i] + (False,)
            leg_i += 1
        if cur is None or cur[4]:
            continue
        _, side, H, L, _used = cur
        span = H - L
        if side > 0:
            top, bot = H - zlo * span, H - zhi * span
            if b.c[j] < bot:
                cur = None
                continue
            in_zone = b.l[j] <= top
            sw = last5l
            trig = in_zone and sw is not None and sw[1] < j and b.l[j] < sw[0] < b.c[j]
        else:
            bot, top = L + zlo * span, L + zhi * span
            if b.c[j] > top:
                cur = None
                continue
            in_zone = b.h[j] >= bot
            sw = last5h
            trig = in_zone and sw is not None and sw[1] < j and b.h[j] > sw[0] > b.c[j]
        d = int(b.day[j])
        if trig and d not in used_day and d > 0 and _window(m, b, j, ("ist", 600, 1320)):
            p = prev_close(m, d)
            ext = b.l[j] if side > 0 else b.h[j]
            stop = ext - side * 0.0005 * p
            out.append(Signal(d, int(b.i1[j]), side, float(stop), "FIB_SWEEP"))
            used_day.add(d)
            cur = cur[:4] + (True,)
    return out


# ── BB-17 order-block 50% trap (15m blocks, 5m entries) ───────────────────────────────

def sig_bb17(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b15, b = B[15], B[5]
    ob_stop = prm.get("stop", "trap") == "block"
    bodies = np.abs(b15.c - b15.o)
    cs = np.cumsum(np.r_[0.0, bodies])
    blocks = []      # (known_after_row, side, lo, hi, expire_row)
    for j in range(22, len(b15.c)):
        mean20 = (cs[j - 1] - cs[j - 21]) / 20
        if bodies[j - 1] < 1.5 * mean20:
            continue
        if b15.l[j] > b15.h[j - 2] and b15.c[j - 1] > b15.o[j - 1]:
            side = 1
        elif b15.h[j] < b15.l[j - 2] and b15.c[j - 1] < b15.o[j - 1]:
            side = -1
        else:
            continue
        exp_j = min(j + 48, len(b15.c) - 1)
        blocks.append((int(b15.i1[j]), side, b15.l[j - 2], b15.h[j - 2], int(b15.i1[exp_j]), j))
    out = []
    active = {1: None, -1: None}
    bi = 0
    trap = {1: None, -1: None}
    nb = len(b.c)
    j15 = 0
    for j in range(nb):
        while bi < len(blocks) and blocks[bi][0] < b.i0[j]:
            blk = blocks[bi]
            active[blk[1]] = list(blk) + [False]
            trap[blk[1]] = None
            bi += 1
        # 15m closes through the block invalidate it
        while j15 < len(b15.c) and b15.i1[j15] < b.i0[j]:
            for side in (1, -1):
                A = active[side]
                if A is not None and j15 > A[5]:
                    if (side > 0 and b15.c[j15] < A[2]) or (side < 0 and b15.c[j15] > A[3]):
                        active[side] = None
            j15 += 1
        for side in (1, -1):
            A = active[side]
            if A is None or A[6]:
                continue
            if b.i1[j] > A[4]:
                active[side] = None
                continue
            mid = (A[2] + A[3]) / 2
            T = trap[side]
            through = b.l[j] < mid if side > 0 else b.h[j] > mid
            if T is None:
                if through:
                    T = trap[side] = [j, b.l[j] if side > 0 else b.h[j]]
                else:
                    continue
            else:
                T[1] = min(T[1], b.l[j]) if side > 0 else max(T[1], b.h[j])
            if j - T[0] > 6:
                trap[side] = None
                continue
            back = b.c[j] > mid if side > 0 else b.c[j] < mid
            d = int(b.day[j])
            if back and d > 0 and _window(m, b, j, ("ist", 600, 1320)):
                p = prev_close(m, d)
                ext = (A[2] if side > 0 else A[3]) if ob_stop else T[1]
                stop = ext - side * 0.0003 * p
                if (b.c[j] - stop) * side > 0:
                    out.append(Signal(d, int(b.i1[j]), side, float(stop), "OB50_TRAP"))
                A[6] = True
                trap[side] = None
            elif back:
                trap[side] = None
    return out


# ── BB-18 15m 200 EMA breakout-retest ─────────────────────────────────────────────────

def sig_bb18(m: Minutes, B: dict, prm: dict) -> list[Signal]:
    b = B[15]
    E = ema(b.c, 200)
    out = []
    for d in range(1, m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        if s0 < 201:
            continue
        p = prev_close(m, d) if m.prev_ok[d] else b.o[s0]
        brk = None
        for j in range(s0, s1):
            if b.ny0[j] >= 17 * 60 and b.ist0[j] < 12 * 60:
                continue
            if b.c[j] > E[j] and b.c[j - 1] <= E[j - 1]:
                brk = (j, 1)
                continue
            if b.c[j] < E[j] and b.c[j - 1] >= E[j - 1]:
                brk = (j, -1)
                continue
            if brk is None or j - brk[0] > 8 or not (16 * 60 <= b.ist0[j] < 20 * 60):
                continue
            side = brk[1]
            tol = 0.0002 * p
            if side > 0 and b.l[j] <= E[j] + tol and b.c[j] > E[j] and green(b, j):
                out.append(Signal(d, int(b.i1[j]), 1, float(b.l[j] - tol), "EMA200_RETEST"))
                break
            if side < 0 and b.h[j] >= E[j] - tol and b.c[j] < E[j] and red(b, j):
                out.append(Signal(d, int(b.i1[j]), -1, float(b.h[j] + tol), "EMA200_RETEST"))
                break
    return out


# ── registry ──────────────────────────────────────────────────────────────────────────

@dataclass
class Variant:
    tag: str                 # V0 / S1 / R1 ...
    sig: dict = field(default_factory=dict)
    exits: dict = field(default_factory=dict)     # Exits fields; "trail_tf" picks the bars for the 9 EMA


@dataclass
class Strategy:
    sid: str
    name: str
    videos: tuple
    fn: object
    markets: tuple
    tfs: tuple
    variants: tuple
    limits: Limits
    exit_clock: dict          # market -> (clock, minute) forced exit
    base_sig: dict = field(default_factory=dict)
    market_sig: dict = field(default_factory=dict)   # market -> extra signal params
    first_upload: str = ""


NIFTY_EXIT = ("ist", IST_1514)
FX_EXIT = ("ny", 16 * 60 + 55)
GOLD_DAY = ("ist", 10 * 60, 22 * 60)


def _ex(**kw):
    return kw


STRATEGIES = {
    "BB-01": Strategy("BB-01", "Previous-day high/low: breakout, trap, gap fill, retest", ("gNoByC3ZEOo",), sig_bb01,
                      ("NIFTY",), (5,),
                      (Variant("V0"), Variant("S1", exits=_ex(target_r=1.5)), Variant("S2", exits=_ex(be_at_frac=0.5)),
                       Variant("R1", sig={"levels": "wick"})),
                      Limits(1), {"NIFTY": NIFTY_EXIT}, {"levels": "body"}, first_upload="2025-10-04"),
    "BB-02": Strategy("BB-02", "15-minute opening-range breakout, 5-minute close", ("yKtI-VEMwC0", "4iPEKSo_vwY"), sig_bb02,
                      ("NIFTY",), (5,),
                      (Variant("V0"), Variant("S1", exits=_ex(target_r=1.5)), Variant("S2", exits=_ex(target_r=1.0)),
                       Variant("S3", exits=_ex(target_r=None, trail_from_r=2.0, trail_tf=5)),
                       Variant("S4", exits=_ex(be_at_frac=0.5))),
                      Limits(2, stop_after_target=True, second_only_after_stop=True), {"NIFTY": NIFTY_EXIT},
                      first_upload="2026-05-26"),
    "BB-03": Strategy("BB-03", "Nifty + BankNifty synchronised level break", ("0MasZZQiL5s",), sig_bb03,
                      ("NIFTY",), (5,), (Variant("V0"), Variant("R1", sig={"current_day": False})),
                      Limits(1), {"NIFTY": NIFTY_EXIT}, first_upload="2023-01-01"),
    "BB-04": Strategy("BB-04", "Zone trap with RSI divergence (15m)", ("SxQwiHBfHUs", "v5AUeTSUiiM"), sig_bb04,
                      ("NIFTY",), (15,), (Variant("V0"), Variant("R1", sig={"rsi": False})),
                      Limits(1), {"NIFTY": NIFTY_EXIT}, first_upload="2021-01-01"),
    "BB-05": Strategy("BB-05", "SMC structure break into an order block", ("hXtpVnpjuXg",), sig_bb05,
                      ("BANKNIFTY",), (5,), (Variant("V0", exits=_ex(partial_at_r=1.0)), Variant("S1")),
                      Limits(3, stop_after_target=False, second_only_after_stop=False), {"BANKNIFTY": NIFTY_EXIT},
                      first_upload="2023-08-21"),
    "BB-06": Strategy("BB-06", "Gap day + first candle through the 15m 200 MA", ("zm9emzopBi0",), sig_bb06,
                      ("NIFTY",), (15,), (Variant("V0"), Variant("S1", exits=_ex(target_r=None, trail_from_r=1.0, trail_tf=15))),
                      Limits(1), {"NIFTY": NIFTY_EXIT}, first_upload="2023-01-01"),
    "BB-07": Strategy("BB-07", "Liquidity sweep of previous-day high/low (masterclass)", ("IOBoaM71MUA",), sig_bb07,
                      ("XAUUSD", "NAS100"), (5,), (Variant("V0"), Variant("S1", sig={"current_day": True})),
                      Limits(1), {"XAUUSD": FX_EXIT, "NAS100": ("ny", 15 * 60 + 55)}, {"window": GOLD_DAY},
                      {"NAS100": {"window": ("ny", 10 * 60, 15 * 60 + 30)}}, first_upload="2026-10-01"),
    "BB-08": Strategy("BB-08", "Previous-day high/low 'manipulation' trap after 10:00 IST",
                      ("HxBwAconvqA", "7LLm0HSarPc", "TIQeTWWc1-8"), sig_bb08, ("XAUUSD", "EURUSD", "GBPUSD"), (5,),
                      (Variant("V0", exits=_ex(target_r=1.5)), Variant("S1", exits=_ex(target_r=1.5, be_at_frac=0.5)),
                       Variant("S2", exits=_ex(target_r=None, trail_from_r=1.5, trail_tf=5)),
                       Variant("S3", exits=_ex(target_r=2.0))),
                      Limits(1), {"XAUUSD": FX_EXIT, "EURUSD": FX_EXIT, "GBPUSD": FX_EXIT}, {"window": GOLD_DAY},
                      first_upload="2024-01-01"),
    "BB-09": Strategy("BB-09", "Value-area (volume profile) trap", ("zYGUL82NsS4", "rFrFhpwJJOc", "eT4kr2HDXoE"), sig_bb09,
                      ("XAUUSD",), (5,),
                      (Variant("V0"), Variant("S1", exits=_ex(target_r=1.5)),
                       Variant("S2", exits=_ex(target_r=3.0, lock_at_r=2.0, lock_to_r=1.0)),
                       Variant("R1", sig={"va": 0.60}), Variant("R2", sig={"va": 0.80})),
                      Limits(2, stop_after_target=True, second_only_after_stop=True), {"XAUUSD": FX_EXIT},
                      {"window": ("ist", 16 * 60, 22 * 60)}, first_upload="2026-06-02"),
    "BB-10": Strategy("BB-10", "Gold 11:30-12:30 IST range sweep", ("1hZMOSd34vQ",), sig_bb10, ("XAUUSD",), (5,),
                      (Variant("V0"), Variant("R1", sig={"range": "wick"})),
                      Limits(1), {"XAUUSD": FX_EXIT}, {"window": ("ist", 14 * 60 + 30, 22 * 60)}, first_upload="2025-01-01"),
    "BB-11": Strategy("BB-11", "Forex 10:00 IST range trap", ("uUa61jN45vM",), sig_bb11, ("EURUSD", "GBPUSD", "XAUUSD"), (15,),
                      (Variant("V0"), Variant("S1", exits=_ex(be_at_r=1.5)), Variant("R1", sig={"void": False})),
                      Limits(1), {"EURUSD": FX_EXIT, "GBPUSD": FX_EXIT, "XAUUSD": FX_EXIT}, first_upload="2025-12-01"),
    "BB-12": Strategy("BB-12", "400 EMA trap (15m)", ("DI3ydbq9b6M",), sig_bb12, ("XAUUSD",), (15,),
                      (Variant("V0", exits=_ex(target_r=1.5)), Variant("S1", exits=_ex(target_r=2.0)),
                       Variant("R1", sig={"stop": "ema"}, exits=_ex(target_r=1.5))),
                      Limits(1), {"XAUUSD": FX_EXIT}, first_upload="2025-01-01"),
    "BB-13": Strategy("BB-13", "'Prop-firm' inside-body breakout", ("Lb4yel3nCws", "NwCyONUCsC0"), sig_bb13,
                      ("NAS100", "XAUUSD"), (5,),
                      (Variant("V0", exits=_ex(target_r=1.0)), Variant("S1", exits=_ex(target_r=1.5)),
                       Variant("S2", exits=_ex(target_r=2.0)), Variant("R1", sig={"stop": "two"}, exits=_ex(target_r=1.0))),
                      Limits(1), {"NAS100": ("ny", 15 * 60 + 55), "XAUUSD": FX_EXIT}, {},
                      {"NAS100": {"window": ("ny", 10 * 60, 15 * 60)}, "XAUUSD": {"window": ("ny_gold", 0, 0)}},
                      first_upload="2025-12-01"),
    "BB-14": Strategy("BB-14", "Inside candle with the poke filter", ("kakFchv-ylo",), sig_bb14, ("NAS100",), (5, 15),
                      (Variant("V0", exits=_ex(target_r=1.5)), Variant("S1", sig={"tf": 15}, exits=_ex(target_r=1.5)),
                       Variant("S2", exits=_ex(target_r=2.0)), Variant("R1", sig={"stop": "range"}, exits=_ex(target_r=1.5))),
                      Limits(2, stop_after_target=False, second_only_after_stop=False, max_stops_per_day=2),
                      {"NAS100": ("ny", 15 * 60 + 59)}, {"tf": 5}, first_upload="2025-01-01"),
    "BB-16": Strategy("BB-16", "Retracement-zone (Fibonacci 50-61.8%) sweep", ("rFrFhpwJJOc", "3gj7MbZ0vHs"), sig_bb16,
                      ("XAUUSD",), (5, 60),
                      (Variant("V0", exits=_ex(target_r=2.5)), Variant("S1", sig={"zone": (0.705, 0.79)}, exits=_ex(target_r=2.5)),
                       Variant("S2", exits=_ex(target_r=2.0))),
                      Limits(1), {"XAUUSD": FX_EXIT}, first_upload="2026-07-01"),
    "BB-17": Strategy("BB-17", "Order-block 50% trap", ("RTbVZfriRrw",), sig_bb17, ("XAUUSD", "EURUSD"), (5, 15),
                      (Variant("V0"), Variant("S1", sig={"stop": "block"})),
                      Limits(2, stop_after_target=False, second_only_after_stop=False), {"XAUUSD": FX_EXIT, "EURUSD": FX_EXIT},
                      first_upload="2026-05-01"),
    "BB-18": Strategy("BB-18", "15m 200 EMA breakout-retest", ("Hj56fabq2c8",), sig_bb18, ("EURUSD", "GBPUSD"), (15,),
                      (Variant("V0"), Variant("S1", exits=_ex(target_r=3.0))),
                      Limits(1), {"EURUSD": FX_EXIT, "GBPUSD": FX_EXIT}, first_upload="2023-01-01"),
}


def signals(st: Strategy, m: Minutes, B: dict, vsig: dict, other=None) -> list[Signal]:
    prm = {**st.base_sig, **st.market_sig.get(m.name, {}), **vsig}
    if st.sid == "BB-03":
        return st.fn(m, B, prm, *other)
    return st.fn(m, B, prm)


def build_bars(m: Minutes, tfs) -> dict:
    return {tf: make_bars(m, tf) for tf in tfs}


def exits_for(v: Variant, B: dict) -> Exits:
    kw = dict(v.exits)
    tf = kw.pop("trail_tf", None)
    ex = Exits(**kw)
    if ex.trail_from_r is not None:
        ex.trail_bars = B[tf]
        ex.trail_ema = ema(B[tf].c, 9)
    return ex
