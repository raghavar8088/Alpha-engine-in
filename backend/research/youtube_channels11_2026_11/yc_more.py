"""Strategies of three channels (rules: the "A:" lines of each analyses/<channel>.md):
  Pushkar Raj Thakur PR-01 .. PR-13, Stock Burner SB-01 .. SB-08, Theta Gainers TH-01 .. TH-09.
Conventions as in yc_common: completed bars only, orders from the next row, pivots only once confirmed. Functions
named *_trades build their trades themselves (two-sided or multi-leg books); the others return signals, and *_x their
exits. Strategies without a stop in the video get a far catastrophe stop and size on sig.info["risk_unit"]."""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import (bars_of_day, body, ctx, first_bar, flags_cross, green, in_window, last_bar_before, last_done,  # noqa: F401
                       lw, nearest_pivot_beyond, pivot_lists, red, rng, sig, swing_target, utc_bars, uw)
from yc_engine import XExits, ladder_trades
from yt_engine import Exits, Signal

NSE_TICK = 0.05
BTC_TICK = 0.5
GOLD_TICK = 0.01
CATASTROPHE = 0.15            # the far stop of a strategy that has none: 15% from the signal close


def _sorted(out):
    out.sort(key=lambda s: (s.k, s.side, s.setup))
    return out


def last_row_before(m, d, minute: int, clock: str = "ist") -> int | None:
    """The last row of day d whose clock time is before `minute` ('ist', 'ny' or 'utc')."""
    a, z = int(m.d0[d]), int(m.d1[d])
    if clock == "utc":
        clk = (np.asarray(m.t[a:z], np.int64) // 60) % 1440
    else:
        clk = (m.ist if clock == "ist" else m.ny)[a:z]
    idx = np.flatnonzero(clk < minute)
    return None if not len(idx) else a + int(idx[-1])


def _two_sided(eng, d, k, ke, longs, shorts, ex, strategy):
    """Stop-entries on both sides, whichever triggers first; once that trade is stopped, the other side's order may
    still trigger (at most two trades). longs / shorts = (trigger, stop, setup)."""
    (lt, ls, lset), (st, ss, sset) = longs, shorts
    short = Signal(d, k, -1, float(ss), sset, entry_stop=float(st), expire_k=ke)
    long_ = Signal(d, k, 1, float(ls), lset, entry_stop=float(lt), expire_k=ke, alt=short)
    t1, _ = eng.trade(long_, ex, ke, strategy, "V0")
    if t1 is None:
        return []
    out = [t1]
    if t1.reason == "stop" and t1.exit_k < ke:
        if t1.side > 0:
            s2 = Signal(d, int(t1.exit_k) - 1, -1, float(ss), sset, entry_stop=float(st), expire_k=ke)
        else:
            s2 = Signal(d, int(t1.exit_k) - 1, 1, float(ls), lset, entry_stop=float(lt), expire_k=ke)
        t2, _ = eng.trade(s2, ex, ke, strategy, "V0")
        if t2 is not None and t2.entry_k >= t1.exit_k:
            out.append(t2)
    return out


# ═══ Pushkar Raj Thakur ═══════════════════════════════════════════════════════════════════

def _pr01_ind(m, B, cache):
    key = ("pr01",)
    if key not in cache:
        b = B[5]
        line, dirn = I.supertrend(b, 20, 2.0)
        ml, ms, _ = ctx(m, B, 5, cache).macd()
        mup, mdn = flags_cross(ml, ms)
        cache[key] = (line, dirn, ml, ms, mup, mdn, I.session_vwap(m, b))
    return cache[key]


def pr01(m, B, p, cache):
    """Brahmastra: Supertrend (20, 2) flip + MACD cross near VWAP (NSE 5-minute pool)."""
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    line, dirn, ml, ms, mup, mdn, vw = _pr01_ind(m, B, cache)
    n = len(b.c)
    fl_up = np.zeros(n, bool)
    fl_dn = np.zeros(n, bool)
    fl_up[1:] = (dirn[1:] == 1) & (dirn[:-1] == -1)
    fl_dn[1:] = (dirn[1:] == -1) & (dirn[:-1] == 1)
    out = []
    for j in range(5, n - 1):
        if not (in_window(b, j, 9 * 60 + 30, 14 * 60 + 30) and np.isfinite(a[j]) and np.isfinite(line[j]) and np.isfinite(vw[j])):
            continue
        w = slice(j - 4, j + 1)
        for side in (1, -1):
            fl, cr = (fl_up, mup) if side > 0 else (fl_dn, mdn)
            if not ((fl[j] and cr[w].any()) or (cr[j] and fl[w].any())):
                continue
            if dirn[j] != side or (ml[j] - ms[j]) * side <= 0:
                continue
            if (b.c[j] - vw[j]) * side > a[j]:
                continue
            stop = float(line[j])
            trig = float(b.h[j] + NSE_TICK) if side > 0 else float(b.l[j] - NSE_TICK)
            if not 0 < (trig - stop) * side <= 3 * a[j]:
                continue
            out.append(sig(b, j, side, stop, "PR01_BRAHMASTRA_LONG" if side > 0 else "PR01_BRAHMASTRA_SHORT",
                           entry_stop=trig, expire_k=int(b.i1[min(j + 2, n - 1)])))
    return out


def pr01_x(m, B, p, cache):
    b = B[5]
    line, _, _, _, mup, mdn, _ = _pr01_ind(m, B, cache)
    return XExits(target_r=None, partial_flag=(b, mdn, mup), partial_be=False, xbars=b, xlong=b.c < line, xshort=b.c > line)


def pr02(m, B, p, cache):
    """The 09:15-09:20 opening range: wait for the retest of the broken edge, 1:3 (BANKNIFTY 1-minute)."""
    b = B[1]
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        rb = [j for j in rows if 9 * 60 + 15 <= b.ist0[j] < 9 * 60 + 20]
        if len(rb) < 5:
            continue
        H, L = float(max(b.h[j] for j in rb)), float(min(b.l[j] for j in rb))
        ht = H - L
        if not ht > 0:
            continue
        state = {1: "wait", -1: "wait"}
        bo = {1: -1, -1: -1}
        for j in rows:
            if b.ist0[j] < 9 * 60 + 20:
                continue
            if b.ist0[j] >= 13 * 60:
                break
            for side in (1, -1):
                st = state[side]
                if st in ("dead", "done"):
                    continue
                beyond = b.c[j] > H if side > 0 else b.c[j] < L
                if st == "wait":
                    if beyond:
                        state[side], bo[side] = "out", j
                    continue
                if L <= b.c[j] <= H:                       # closed back inside: that side is cancelled
                    state[side] = "dead"
                    continue
                if st == "out":
                    near = (b.l[j] <= H + 0.1 * ht and b.c[j] > H) if side > 0 else (b.h[j] >= L - 0.1 * ht and b.c[j] < L)
                    if near:
                        state[side] = "retest"
                    continue
                if (green(b, j) if side > 0 else red(b, j)):
                    ref = float(b.c[j])
                    if side > 0:
                        stop = min(float(b.l[bo[1]:j + 1].min()) * (1 - 0.0005), ref * (1 - 0.001))
                    else:
                        stop = max(float(b.h[bo[-1]:j + 1].max()) * (1 + 0.0005), ref * (1 + 0.001))
                    out.append(sig(b, j, side, stop, "PR02_RETEST_LONG" if side > 0 else "PR02_RETEST_SHORT"))
                    state[side] = "done"
    return _sorted(out)


def pr02_x(m, B, p, cache):
    return Exits(target_r=3.0, max_hold=120)


def pr03(m, B, p, cache):
    """A gap against a 4-session trend, the opposite-colour first candle's break (BANKNIFTY 5-minute)."""
    b = B[5]
    _, _, C = I.day_hlc(m)
    out = []
    for d in range(5, m.n_days):
        if not m.prev_ok[d]:
            continue
        j = first_bar(b, d)
        if j >= b.b1[d] or b.ist0[j] != 9 * 60 + 15:
            continue
        last = last_row_before(m, d, 10 * 60 + 30)
        if last is None or last <= b.i1[j]:
            continue
        pc, op = float(C[d - 1]), float(m.o[m.d0[d]])
        frac = 0.0018 if rng(b, j) < 0.0025 * b.c[j] else 0.0025
        if C[d - 1] > C[d - 5] and op <= pc * (1 - 0.006) and green(b, j):
            trig = float(b.h[j])
            out.append(sig(b, j, 1, trig * (1 - frac), "PR03_GAP_DOWN_REVERSAL", entry_stop=trig, expire_k=last,
                           target_px=pc, info={"stop_frac": frac}))
        elif C[d - 1] < C[d - 5] and op >= pc * (1 + 0.006) and red(b, j):
            trig = float(b.l[j])
            out.append(sig(b, j, -1, trig * (1 + frac), "PR03_GAP_UP_REVERSAL", entry_stop=trig, expire_k=last,
                           target_px=pc, info={"stop_frac": frac}))
    return out


def pr03_x(m, B, p, cache):
    return XExits(target_r=None, trail=("dist_frac", 0.0037, 0.0012))


def pr04_trades(m, B, p, cache, eng, k_end_of_day, strategy="PR-04"):
    """The day's third 5-minute candle (09:25-09:30), both sides as stop-entries (NIFTY); out at 15:00."""
    b = B[5]
    ex = Exits(target_r=None)
    out = []
    for d in range(m.n_days):
        j = next((x for x in bars_of_day(b, d) if b.ist0[x] == 9 * 60 + 25), None)
        ke = k_end_of_day(d)
        if j is None or ke is None or b.i1[j] >= ke:
            continue
        hi, lo = float(b.h[j]), float(b.l[j])
        out += _two_sided(eng, d, int(b.i1[j]), ke, (hi * 1.0003, lo, "PR04_THIRD_CANDLE_UP"),
                          (lo * 0.9997, hi, "PR04_THIRD_CANDLE_DOWN"), ex, strategy)
    return out


def pr05(m, B, p, cache):
    """Ghanshyam Tech's window: the 09:15 one-minute candle's high (low) near a round hundred (BANKNIFTY 1-minute)."""
    b = B[1]
    out = []
    for d in range(m.n_days):
        j = first_bar(b, d)
        if j >= b.b1[d] or b.ist0[j] != 9 * 60 + 15:
            continue
        hi, lo = float(b.h[j]), float(b.l[j])
        buy = (hi % 100) <= 30
        sell = (lo % 100) >= 70 or (lo % 100) == 0
        exp = int(b.i1[min(j + 2, b.b1[d] - 1)])
        k = int(b.i1[j])
        short = Signal(d, k, -1, hi, "PR05_WINDOW_SHORT", entry_stop=lo, expire_k=exp) if sell else None
        if buy:
            out.append(Signal(d, k, 1, lo, "PR05_WINDOW_LONG", entry_stop=hi, expire_k=exp, alt=short))
        elif short is not None:
            out.append(short)
    return out


def pr05_x(m, B, p, cache):
    b = B[1]
    xl = np.zeros(len(b.c), bool)
    xs = np.zeros(len(b.c), bool)
    xl[1:] = b.c[1:] < b.l[:-1]
    xs[1:] = b.c[1:] > b.h[:-1]
    return Exits(target_r=None, xbars=b, xlong=xl, xshort=xs)


def pr06(m, B, p, cache):
    """Ghanshyam Yadav's 14:20 candle with open space (BANKNIFTY 5-minute)."""
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        j = next((x for x in rows if b.ist0[x] == 14 * 60 + 20), None)
        if j is None or not np.isfinite(a[j]):
            continue
        hour = [x for x in rows if 13 * 60 + 20 <= b.ist0[x] < 14 * 60 + 20]
        exp = last_row_before(m, d, 14 * 60 + 55)
        if len(hour) < 12 or exp is None:
            continue
        hh, hl = float(max(b.h[x] for x in hour)), float(min(b.l[x] for x in hour))
        H, L = float(b.h[j]), float(b.l[j])
        k = int(b.i1[j])
        short = Signal(d, k, -1, H, "PR06_1420_SHORT", entry_stop=L, expire_k=exp) if L <= hl + 0.25 * a[j] else None
        if H >= hh - 0.25 * a[j]:
            out.append(Signal(d, k, 1, L, "PR06_1420_LONG", entry_stop=H, expire_k=exp, alt=short))
        elif short is not None:
            out.append(short)
    return out


def pr06_x(m, B, p, cache):
    b = B[5]
    xl = np.zeros(len(b.c), bool)
    xs = np.zeros(len(b.c), bool)
    xl[1:] = b.c[1:] < b.l[:-1]
    xs[1:] = b.c[1:] > b.h[:-1]
    return Exits(target_r=None, xbars=b, xlong=xl, xshort=xs)


def pr07(m, B, p, cache):
    """Fibonacci 0.71 buy after a fall from the session high (BANKNIFTY 5-minute, buys only)."""
    b = B[5]
    out = []
    for d in range(m.n_days):
        H, L = -np.inf, np.inf
        for j in bars_of_day(b, d):
            if b.h[j] > H:                                  # a new session high resets the low anchor
                H, L = float(b.h[j]), np.inf
                continue
            if b.ist0[j] >= 14 * 60:
                break
            L = min(L, float(b.l[j]))
            span = H - L
            if span < 0.005 * b.c[j]:
                continue
            if b.c[j] > L + 0.71 * span:
                out.append(sig(b, j, 1, L + 0.38 * span, "PR07_FIB_071", target_px=float(L + 1.27 * span),
                               info={"partial_px": H}))
                break
    return out


def pr07_x(m, B, p, cache):
    return XExits(target_r=None, partial_px=True)


def pr08(m, B, p, cache):
    """Pivot points: a limit at the pivot on the side of the 09:30 close (NSE 5-minute pool)."""
    b = B[5]
    H, L, C = I.day_hlc(m)
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        pv = I.pivot_points(float(H[d - 1]), float(L[d - 1]), float(C[d - 1]))
        j = next((x for x in bars_of_day(b, d) if b.ist0[x] == 9 * 60 + 25), None)
        exp = last_row_before(m, d, 13 * 60 + 30)
        if j is None or exp is None:
            continue
        c = float(b.c[j])
        if pv["S2"] < c < pv["P"]:
            out.append(sig(b, j, -1, pv["R1"] * 1.0007, "PR08_PIVOT_SELL", entry_limit=float(pv["P"]), expire_k=exp,
                           target_px=float(pv["S2"]), info={"partial_px": float(pv["S1"])}))
        elif pv["P"] < c < pv["R2"]:
            out.append(sig(b, j, 1, pv["S1"] * 0.9993, "PR08_PIVOT_BUY", entry_limit=float(pv["P"]), expire_k=exp,
                           target_px=float(pv["R2"]), info={"partial_px": float(pv["R1"])}))
    return out


def pr08_x(m, B, p, cache):
    return XExits(target_r=None, partial_px=True)


def pr09(m, B, p, cache):
    """EMA 10 / 30 cross on 3 minutes, stop and reverse (NIFTY)."""
    b = B[3]
    c = ctx(m, B, 3, cache)
    up, dn = flags_cross(c.ema(10), c.ema(30))
    out = []
    for j in range(31, len(b.c) - 1):
        if up[j]:
            out.append(sig(b, j, 1, b.c[j] - 25.0, "PR09_CROSS_UP", info={"stop_dist": 25.0}))
        elif dn[j]:
            out.append(sig(b, j, -1, b.c[j] + 25.0, "PR09_CROSS_DOWN", info={"stop_dist": 25.0}))
    return out


def pr09_x(m, B, p, cache):
    c = ctx(m, B, 3, cache)
    up, dn = flags_cross(c.ema(10), c.ema(30))
    return XExits(target_r=None, xbars=B[3], xlong=dn, xshort=up)


def pr10(m, B, p, cache):
    """RSI divergence with a close-line trigger (NIFTY 15-minute)."""
    b = B[15]
    bull, bear = I.rsi_divergences(b, 14, 5, 5, 5, 60)
    n = len(b.c)
    out = []
    for lst, side in ((bull, 1), (bear, -1)):
        for pv, kb in lst:
            if kb >= n:
                continue
            line = float(b.c[pv])
            step, ref = 0, None
            for j in range(kb + 1, min(kb + 31, n)):
                if step == 0:
                    if (red(b, j) and b.c[j] < line) if side > 0 else (green(b, j) and b.c[j] > line):
                        step, ref = 1, float(b.l[j]) if side > 0 else float(b.h[j])
                    continue
                if step == 1 and ((b.l[j] < ref) if side > 0 else (b.h[j] > ref)):
                    step = 2
                if step == 2 and ((green(b, j) and b.c[j] > line) if side > 0 else (red(b, j) and b.c[j] < line)):
                    if in_window(b, j, 9 * 60 + 15, 14 * 60 + 30):
                        ext = float(b.l[pv:j + 1].min()) if side > 0 else float(b.h[pv:j + 1].max())
                        stop = ext * (1 - 0.0005) if side > 0 else ext * (1 + 0.0005)
                        out.append(sig(b, j, side, stop, "PR10_DIVERGENCE_LONG" if side > 0 else "PR10_DIVERGENCE_SHORT"))
                    break
    return _sorted(out)


def pr10_x(m, B, p, cache):
    return Exits(target_r=2.0)


def _gator(b):
    med = (b.h + b.l) / 2
    s13, s8, s5 = I.smma(med, 13), I.smma(med, 8), I.smma(med, 5)
    return s13, s8, s5, I.shift(s13, 8), I.shift(s8, 5), I.shift(s5, 3)


def _pr11_ind(m, B, cache):
    key = ("pr11",)
    if key not in cache:
        b = B[1]
        s13, s8, s5, jaw, teeth, lips = _gator(b)
        lips_dn = np.zeros(len(b.c), bool)
        ok = np.isfinite(lips) & np.isfinite(teeth)
        lips_dn[1:] = ok[1:] & ok[:-1] & (lips[:-1] >= teeth[:-1]) & (lips[1:] < teeth[1:])
        cache[key] = (s13, jaw, teeth, lips, lips_dn)
    return cache[key]


def pr11(m, B, p, cache):
    """52-week-high stocks bought on a pullback to the Alligator's teeth (NSE daily pool, long only)."""
    b = B[1]
    a = ctx(m, B, 1, cache).atr(14)
    s13, jaw, teeth, lips, _ = _pr11_ind(m, B, cache)
    liq = getattr(m, "liquid", np.ones(len(b.c), bool))
    n = len(b.c)
    hi52 = np.zeros(n, bool)
    for j in range(251, n):
        hi52[j] = b.c[j] >= b.c[j - 251:j + 1].max()
    out = []
    last_hi = -1
    for j in range(n):
        if hi52[j]:
            last_hi = j
        if j < 260 or last_hi < 0 or j - last_hi > 14 or not liq[j] or not np.isfinite(a[j]):
            continue
        if not (lips[j] > teeth[j] > jaw[j] and jaw[j] > jaw[j - 5]):
            continue
        if b.l[j] <= teeth[j] and b.c[j] > jaw[j]:
            jaw_next = float(s13[j - 7])                     # the jaw plotted for the entry day, known now
            out.append(sig(b, j, 1, jaw_next - a[j], "PR11_52WH_TEETH", info={"group": int(last_hi), "target_frac": 0.15}))
    return out


def pr11_x(m, B, p, cache):
    b = B[1]
    _, jaw, _, _, lips_dn = _pr11_ind(m, B, cache)
    return XExits(target_r=None, xbars=b, xlong=(b.c < jaw) | lips_dn, xshort=np.zeros(len(b.c), bool), max_hold=30)


def ladder(m, cache, eng, risk_pct, since_k, strategy, take_profit=None):
    """PR-12 / PR-13: Supertrend (10, 3) on 4-hour candles drawn from 00:00 UTC, traded by yc_engine.ladder_trades."""
    key = ("utc240",)
    if key not in cache:
        cache[key] = utc_bars(m, 240)
    b4 = cache[key]
    _, dirn = I.supertrend(b4, 10, 3.0)
    return ladder_trades(eng, b4, dirn, strategy, risk_pct, since_k, take_profit)


def pr12_trades(m, B, p, cache, eng, risk_pct, since_k=0, strategy="PR-12"):
    return ladder(m, cache, eng, risk_pct, since_k, strategy)


def pr13_trades(m, B, p, cache, eng, risk_pct, since_k=0, strategy="PR-13"):
    return ladder(m, cache, eng, risk_pct, since_k, strategy, take_profit=0.10)


# ═══ Stock Burner ═════════════════════════════════════════════════════════════════════════

def sb01(m, B, p, cache):
    """9/20 EMA: the first pullback to EMA 9 after a volume breakout (NSE 5-minute pool)."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    e9, e20, a = c.ema(9), c.ema(20), c.atr(14)
    vol, va = c.vol(), c.vol_avg(20)
    hh, ll = I.prior_highest(b.h, 12), I.prior_lowest(b.l, 12)
    n = len(b.c)
    out = []
    for x in range(13, n - 1):
        if not (np.isfinite(va[x]) and vol[x] >= 1.5 * va[x]):
            continue
        for side in (1, -1):
            trend = e9[x] > e20[x] if side > 0 else e9[x] < e20[x]
            brk = b.c[x] > hh[x] if side > 0 else b.c[x] < ll[x]
            if not (trend and brk):
                continue
            for j in range(x + 1, min(x + 11, n)):
                if b.day[j] != b.day[x]:
                    break
                if not np.isfinite(a[j]):
                    continue
                if side > 0:
                    ok = e9[j] > e20[j] and b.l[j] <= e9[j] and b.c[j] > e9[j] and b.c[j] > e20[j]
                else:
                    ok = e9[j] < e20[j] and b.h[j] >= e9[j] and b.c[j] < e9[j] and b.c[j] < e20[j]
                if ok:
                    if in_window(b, j, 9 * 60 + 30, 14 * 60 + 30):
                        stop = b.l[j] - 0.1 * a[j] if side > 0 else b.h[j] + 0.1 * a[j]
                        out.append(sig(b, j, side, stop, "SB01_FIRST_PULLBACK_LONG" if side > 0 else "SB01_FIRST_PULLBACK_SHORT"))
                    break
    return _sorted(out)


def sb01_x(m, B, p, cache):
    b = B[5]
    e20 = ctx(m, B, 5, cache).ema(20)
    return Exits(target_r=None, xbars=b, xlong=b.c < e20, xshort=b.c > e20)


def _ema_crossings(c, e, j, n):
    """How many times the closes crossed e in the last n candles up to j."""
    s = np.sign(c[j - n:j + 1] - e[j - n:j + 1])
    return int(np.sum((s[1:] != s[:-1]) & (s[1:] != 0) & (s[:-1] != 0)))


def sb02(m, B, p, cache):
    """9/20 EMA rejected pullback, 15 minutes (BTCUSD)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e9, e20, a = c.ema(9), c.ema(20), c.atr(14)
    n = len(b.c)
    out = []
    for j in range(25, n - 1):
        if not np.isfinite(a[j]) or _ema_crossings(b.c, e20, j, 12) > 2:
            continue
        exp = int(b.i1[min(j + 3, n - 1)])
        lo2 = all(b.c[k] < min(e9[k], e20[k]) for k in (j - 2, j - 1))
        hi2 = all(b.c[k] > max(e9[k], e20[k]) for k in (j - 2, j - 1))
        if e9[j] < e20[j] and lo2 and red(b, j) and b.h[j] >= e9[j] and b.c[j] < e20[j]:
            out.append(sig(b, j, -1, b.h[j - 4:j + 1].max() + 0.1 * a[j], "SB02_PULLBACK_SHORT",
                           entry_stop=float(b.l[j] - BTC_TICK), expire_k=exp))
        elif e9[j] > e20[j] and hi2 and green(b, j) and b.l[j] <= e9[j] and b.c[j] > e20[j]:
            out.append(sig(b, j, 1, b.l[j - 4:j + 1].min() - 0.1 * a[j], "SB02_PULLBACK_LONG",
                           entry_stop=float(b.h[j] + BTC_TICK), expire_k=exp))
    return out


def sb02_x(m, B, p, cache):
    return Exits(target_r=2.5)


def sb03(m, B, p, cache):
    """9 EMA rejection scalp (NIFTY 5-minute)."""
    b = B[5]
    e9 = ctx(m, B, 5, cache).ema(9)
    n = len(b.c)
    out = []
    for j in range(12, n - 1):
        if not in_window(b, j, 9 * 60 + 30, 14 * 60 + 45) or _ema_crossings(b.c, e9, j, 9) >= 3:
            continue
        r = rng(b, j)
        if not r > 0:
            continue
        if b.c[j - 1] < e9[j - 1] and b.c[j - 2] < e9[j - 2] and red(b, j) and b.h[j] >= e9[j] > b.c[j] and uw(b, j) >= 0.4 * r:
            out.append(sig(b, j, -1, b.h[j] * 1.0002, "SB03_EMA9_REJECT_SHORT"))
        elif b.c[j - 1] > e9[j - 1] and b.c[j - 2] > e9[j - 2] and green(b, j) and b.l[j] <= e9[j] < b.c[j] and lw(b, j) >= 0.4 * r:
            out.append(sig(b, j, 1, b.l[j] * 0.9998, "SB03_EMA9_REJECT_LONG"))
    return out


def sb03_x(m, B, p, cache):
    b = B[5]
    e9 = ctx(m, B, 5, cache).ema(9)
    return Exits(target_r=2.0, xbars=b, xlong=b.c < e9, xshort=b.c > e9, max_hold=15)


def sb04(m, B, p, cache):
    """200 EMA retest with a confirmation candle (BTCUSD 15-minute)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e200, a = c.ema(200), c.atr(14)
    n = len(b.c)
    above = b.c > e200
    below = b.c < e200
    out = []
    for j in range(210, n - 1):
        q = j + 1
        if not (np.isfinite(a[j]) and np.isfinite(a[q])):
            continue
        if above[j - 9:j + 1].all() and b.l[j] <= e200[j] + 0.1 * a[j] and green(b, q) and b.c[q] > b.h[j]:
            out.append(sig(b, q, 1, b.l[q - 4:q + 1].min() - 0.1 * a[q], "SB04_EMA200_RETEST_LONG"))
        elif below[j - 9:j + 1].all() and b.h[j] >= e200[j] - 0.1 * a[j] and red(b, q) and b.c[q] < b.l[j]:
            out.append(sig(b, q, -1, b.h[q - 4:q + 1].max() + 0.1 * a[q], "SB04_EMA200_RETEST_SHORT"))
    return out


def sb04_x(m, B, p, cache):
    return Exits(target_r=2.0)


def sb05(m, B, p, cache):
    """The first 5-minute candle breakout with the 5-session trend, one trade a day (NIFTY)."""
    b = B[5]
    _, _, C = I.day_hlc(m)
    out = []
    for d in range(6, m.n_days):
        if not m.prev_ok[d]:
            continue
        j0 = first_bar(b, d)
        if j0 >= b.b1[d] or b.ist0[j0] != 9 * 60 + 15:
            continue
        pc, op = float(C[d - 1]), float(m.o[m.d0[d]])
        if abs(op / pc - 1) >= 0.004:
            continue
        up, dn = C[d - 1] > C[d - 6], C[d - 1] < C[d - 6]
        for j in range(j0 + 1, int(b.b1[d])):
            if b.ist0[j] >= 12 * 60:
                break
            r = rng(b, j)
            strong = r > 0 and body(b, j) >= 0.6 * r
            if up and strong and green(b, j) and b.c[j] > b.h[j0]:
                out.append(sig(b, j, 1, b.l[j0], "SB05_FIRST_CANDLE_UP"))
                break
            if dn and strong and red(b, j) and b.c[j] < b.l[j0]:
                out.append(sig(b, j, -1, b.h[j0], "SB05_FIRST_CANDLE_DOWN"))
                break
    return out


def sb05_x(m, B, p, cache):
    return Exits(target_r=None, partial_at_r=3.0)


def sb06(m, B, p, cache):
    """A sweep of a tested 1-hour level, then a hammer or a pause-candle break (gold, 15-minute entries)."""
    b, bh = B[15], B[60]
    a = ctx(m, B, 15, cache).atr(14)
    eh = ctx(m, B, 60, cache).ema(50)
    phh, plh = pivot_lists(m, B, 60, cache, 2)
    n = len(b.c)
    out = []
    for side, piv, vals in ((1, plh, bh.l), (-1, phh, bh.h)):
        lv = sorted((int(bh.i1[q + 2]), float(vals[q]), int(q)) for q in piv)
        active, i = [], 0
        for j in range(2, n):
            start = int(b.i0[j])
            while i < len(lv) and lv[i][0] < start:
                active.append(lv[i])
                i += 1
            q = last_done(bh, int(b.i1[j]))
            if q < 1:
                continue
            keep, hit = [], None
            for known, v, pq in active:
                if pq < q - 120:                                # only levels from the last 5 days
                    continue
                if (b.l[j] < v) if side > 0 else (b.h[j] > v):
                    hit = (v, pq) if hit is None else hit       # the first level traded through is used up
                    continue
                keep.append((known, v, pq))
            active = keep
            if hit is None:
                continue
            v, pq = hit
            trend = eh[q] > eh[q - 1] if side > 0 else eh[q] < eh[q - 1]
            if not trend:
                continue
            for x in range(j, min(j + 5, n)):
                if not np.isfinite(a[x]):
                    break
                ext = float(b.l[j:x + 1].min()) if side > 0 else float(b.h[j:x + 1].max())
                stop = ext - side * 0.1 * a[x]
                wick = lw(b, x) if side > 0 else uw(b, x)
                back = b.c[x] > v if side > 0 else b.c[x] < v
                if wick >= 2 * body(b, x) and back:
                    ref = float(b.c[x])
                    lvl = nearest_pivot_beyond(bh.h if side > 0 else bh.l, phh if side > 0 else plh, q, 2, side, ref, 120)
                    out.append(sig(b, x, side, stop, "SB06_SWEEP_HAMMER_LONG" if side > 0 else "SB06_SWEEP_STAR_SHORT",
                                   target_px=swing_target(side, ref, stop, lvl, 3.0, 3.0), info={"group": (side, pq)}))
                    break
                beyond = (red(b, x) and b.c[x] < v) if side > 0 else (green(b, x) and b.c[x] > v)
                y = x + 1
                if beyond and y < n and body(b, y) <= 0.5 * body(b, x):
                    trig = float(b.h[y] + GOLD_TICK) if side > 0 else float(b.l[y] - GOLD_TICK)
                    ext = float(b.l[j:y + 1].min()) if side > 0 else float(b.h[j:y + 1].max())
                    stop = ext - side * 0.1 * a[y]
                    lvl = nearest_pivot_beyond(bh.h if side > 0 else bh.l, phh if side > 0 else plh, q, 2, side, trig, 120)
                    out.append(sig(b, y, side, stop, "SB06_SWEEP_PAUSE_LONG" if side > 0 else "SB06_SWEEP_PAUSE_SHORT",
                                   entry_stop=trig, expire_k=int(b.i1[min(y + 2, n - 1)]),
                                   target_px=swing_target(side, trig, stop, lvl, 3.0, 3.0), info={"group": (side, pq)}))
                    break
    return _sorted(out)


def sb06_x(m, B, p, cache):
    return Exits(target_r=None)


def sb07(m, B, p, cache):
    """Pre-breakout: buy under a tested resistance while the lows rise (BTCUSD 30-minute, long only)."""
    b = B[30]
    c = ctx(m, B, 30, cache)
    e50, a = c.ema(50), c.atr(14)
    ph, pl = pivot_lists(m, B, 30, cache, 2)
    n = len(b.c)
    out = []
    for j in range(60, n - 1):
        if not (np.isfinite(a[j]) and b.c[j] > e50[j]):
            continue
        k = int(np.searchsorted(ph, j - 2, "right"))
        P = [int(q) for q in ph[int(np.searchsorted(ph, j - 80, "left")):k]]
        best = None
        for q in P:
            grp = [r for r in P if abs(b.h[r] / b.h[q] - 1) <= 0.0025]
            if len(grp) < 2:
                continue
            R, first = float(max(b.h[r] for r in grp)), min(grp)
            if not R * 0.996 <= b.c[j] < R or (b.c[first:j] > R).any():
                continue
            kl = int(np.searchsorted(pl, j - 2, "right"))
            lows = [int(r) for r in pl[:kl] if r > first]
            if len(lows) < 2 or not b.l[lows[-1]] > b.l[lows[-2]]:
                continue
            best = (R, first, float(b.l[lows[-1]]))
            break
        if best is None:
            continue
        R, first, hl = best
        out.append(sig(b, j, 1, hl - 0.1 * a[j], "SB07_PRE_BREAKOUT", target_px=float(R + (R - hl)),
                       info={"be_close": R, "group": (first, round(R, 2))}))
    return out


def sb07_x(m, B, p, cache):
    return XExits(target_r=None, be_close=(B[30],), max_hold=48 * 30)


def sb08(m, B, p, cache):
    """Bollinger Band breakout on 1-hour bitcoin, 2% stop and 5% target."""
    b = B[60]
    _, up, lo = ctx(m, B, 60, cache).bollinger(20, 2.0)
    out = []
    for j in range(21, len(b.c) - 1):
        if not np.isfinite(up[j]):
            continue
        if b.c[j] > up[j]:
            out.append(sig(b, j, 1, b.c[j] * 0.98, "SB08_BB_BREAKOUT_LONG", info={"stop_frac": 0.02}))
        elif b.c[j] < lo[j]:
            out.append(sig(b, j, -1, b.c[j] * 1.02, "SB08_BB_BREAKOUT_SHORT", info={"stop_frac": 0.02}))
    return out


def sb08_x(m, B, p, cache):
    b = B[60]
    xl = np.zeros(len(b.c), bool)
    xs = np.zeros(len(b.c), bool)
    xl[1:] = b.c[1:] < b.l[:-1]
    xs[1:] = b.c[1:] > b.h[:-1]
    return XExits(target_r=2.5, xbars=b, xlong=xl, xshort=xs)


# ═══ Theta Gainers ════════════════════════════════════════════════════════════════════════

def _th01_ind(m, B, cache):
    key = ("th01",)
    if key not in cache:
        cache[key] = I.anchored_vwap(m, B[5], 30)          # bitcoin's day opens 06:00 IST = 00:30 UTC
    return cache[key]


def th01(m, B, p, cache):
    """The 18:00-23:00 IST session: an "N" above anchored VWAP and EMA 25 (BTCUSD 5-minute)."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    e25, a = c.ema(25), c.atr(14)
    vw = _th01_ind(m, B, cache)
    hv, hi, lv, li, _, _ = c.pivots(1)
    out = []
    for j in range(30, len(b.c) - 1):
        if not (18 * 60 <= b.ist0[j] < 23 * 60) or not (np.isfinite(a[j]) and np.isfinite(vw[j])):
            continue
        if hi[j] >= 0 and li[j] > hi[j] and b.c[j] > hv[j] >= b.c[j - 1] and b.c[j] > vw[j] and b.c[j] > e25[j]:
            out.append(sig(b, j, 1, lv[j] - 0.1 * a[j], "TH01_N_LONG"))
        elif li[j] >= 0 and hi[j] > li[j] and b.c[j] < lv[j] <= b.c[j - 1] and b.c[j] < vw[j] and b.c[j] < e25[j]:
            out.append(sig(b, j, -1, hv[j] + 0.1 * a[j], "TH01_N_SHORT"))
    return out


def th01_x(m, B, p, cache):
    bq = B[15]
    hv, _, lv, _, _, _ = ctx(m, B, 15, cache).pivots(1)
    with np.errstate(invalid="ignore"):
        return Exits(target_r=None, xbars=bq, xlong=bq.c < lv, xshort=bq.c > hv)


def th02(m, B, p, cache):
    """Standard pivots R1 / S1 with a fast Supertrend (7, 3) (NIFTY 5-minute)."""
    b = B[5]
    line, dirn = I.supertrend(b, 7, 3.0)
    H, L, C = I.day_hlc(m)
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        pv = I.pivot_points(float(H[d - 1]), float(L[d - 1]), float(C[d - 1]))
        for j in bars_of_day(b, d):
            if not in_window(b, j, 9 * 60 + 20, 14 * 60 + 55) or not np.isfinite(line[j]):
                continue
            if b.c[j] > pv["R1"] and dirn[j] == 1:
                out.append(sig(b, j, 1, line[j], "TH02_ABOVE_R1"))
            elif b.c[j] < pv["S1"] and dirn[j] == -1:
                out.append(sig(b, j, -1, line[j], "TH02_BELOW_S1"))
    return out


def th02_x(m, B, p, cache):
    b = B[5]
    line, _ = I.supertrend(b, 7, 3.0)
    with np.errstate(invalid="ignore"):
        return Exits(target_r=None, xbars=b, xlong=b.c < line, xshort=b.c > line)


class _BrickBars:
    """Renko bricks in the shape the engine's exit flags need: the row each brick completed on, and its close."""

    def __init__(self, i1, c):
        self.i1, self.c = np.asarray(i1, np.int64), np.asarray(c, float)


def renko_grid(c: np.ndarray, box: float):
    """Traditional Renko of a close series on a fixed price grid (multiples of the box, so the bricks do not depend on
    where the data starts once the first reversal has formed): (direction, close, row) per brick; a reversal needs two
    boxes."""
    dirs, cls, rows = [], [], []
    if not box > 0 or len(c) < 2:
        return np.zeros(0, int), np.zeros(0), np.zeros(0, np.int64)
    top = bot = round(float(c[0]) / box) * box
    trend = 0
    for k in range(1, len(c)):
        x = float(c[k])
        while True:
            if trend >= 0 and x >= top + box:
                bot, top, trend = top, top + box, 1
                dirs.append(1), cls.append(top), rows.append(k)
            elif trend <= 0 and x <= bot - box:
                top, bot, trend = bot, bot - box, -1
                dirs.append(-1), cls.append(bot), rows.append(k)
            elif trend == 1 and x <= bot - box:
                top, bot, trend = bot, bot - box, -1
                dirs.append(-1), cls.append(bot), rows.append(k)
            elif trend == -1 and x >= top + box:
                bot, top, trend = top, top + box, 1
                dirs.append(1), cls.append(top), rows.append(k)
            else:
                break
    return np.asarray(dirs, int), np.asarray(cls, float), np.asarray(rows, np.int64)


def _renko_ichi(m, box, cache):
    key = ("renko_ichi", float(box))
    if key not in cache:
        dirs, cls, rows = renko_grid(np.asarray(m.c, float), box)
        opens = cls - dirs * box
        hi, lo = np.maximum(opens, cls), np.minimum(opens, cls)
        mid = lambda n: (I.highest(hi, n) + I.lowest(lo, n)) / 2  # noqa: E731
        ten, kij = mid(9), mid(26)
        sa, sb = I.shift((ten + kij) / 2, 26), I.shift(mid(52), 26)
        cache[key] = (dirs, cls, rows, kij, sa, sb, _BrickBars(rows, cls))
    return cache[key]


def _renko_signals(m, box, cache, tag):
    dirs, cls, rows, kij, sa, sb, _ = _renko_ichi(m, box, cache)
    out = []
    n = len(cls)
    for i in range(n):
        if i + 1 < n and rows[i + 1] == rows[i]:           # several bricks in one minute: act on the last one
            continue
        if not (np.isfinite(kij[i]) and np.isfinite(sa[i]) and np.isfinite(sb[i])):
            continue
        r = int(rows[i])
        top, bot = max(sa[i], sb[i]), min(sa[i], sb[i])
        if cls[i] > kij[i] and cls[i] > top:
            out.append(Signal(int(m.day[r]), r, 1, float(cls[i] * (1 - CATASTROPHE)), f"{tag}_RENKO_LONG",
                              info={"risk_unit": 2 * box}))
        elif cls[i] < kij[i] and cls[i] < bot:
            out.append(Signal(int(m.day[r]), r, -1, float(cls[i] * (1 + CATASTROPHE)), f"{tag}_RENKO_SHORT",
                              info={"risk_unit": 2 * box}))
    return out


def _renko_exits(m, box, cache):
    _, cls, _, kij, sa, sb, bricks = _renko_ichi(m, box, cache)
    with np.errstate(invalid="ignore"):
        top = np.fmax(sa, sb)
        return Exits(target_r=None, xbars=bricks, xlong=cls < top, xshort=cls > kij)


TH03_BOX = 43.0


def th03(m, B, p, cache):
    """Renko (a 43-dollar box) + Ichimoku on the bricks (gold)."""
    return _renko_signals(m, TH03_BOX, cache, "TH03")


def th03_x(m, B, p, cache):
    return _renko_exits(m, TH03_BOX, cache)


def th04_box(m, p) -> float:
    """1% of the first close of the replay window, in whole dollars, then fixed (p["box"] when the runner fixed it)."""
    if p.get("box"):
        return float(p["box"])
    return float(max(1.0, round(float(m.c[0]) * 0.01)))


def th04(m, B, p, cache):
    """The same Renko + Ichimoku system on bitcoin."""
    return _renko_signals(m, th04_box(m, p), cache, "TH04")


def th04_x(m, B, p, cache):
    return _renko_exits(m, th04_box(m, p), cache)


def th05(m, B, p, cache):
    """EMA 50 / 200 trend, a pullback to EMA 50 with RSI 40-55 (BTCUSD 15-minute)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e50, e200, a, r = c.ema(50), c.ema(200), c.atr(14), c.rsi(14)
    out = []
    for j in range(210, len(b.c) - 1):
        if not np.isfinite(a[j]):
            continue
        up = e50[j] > e200[j] and e50[j] > e50[j - 4] and e200[j] > e200[j - 4]
        dn = e50[j] < e200[j] and e50[j] < e50[j - 4] and e200[j] < e200[j - 4]
        if up and b.l[j] <= e50[j] + 0.1 * a[j] and green(b, j) and b.c[j] > e50[j] and 40 <= r[j] <= 55:
            out.append(sig(b, j, 1, b.l[j - 9:j + 1].min() - 0.1 * a[j], "TH05_EMA50_PULLBACK_LONG"))
        elif dn and b.h[j] >= e50[j] - 0.1 * a[j] and red(b, j) and b.c[j] < e50[j] and 45 <= r[j] <= 60:
            out.append(sig(b, j, -1, b.h[j - 9:j + 1].max() + 0.1 * a[j], "TH05_EMA50_PULLBACK_SHORT"))
    return out


def th05_x(m, B, p, cache):
    r = ctx(m, B, 15, cache).rsi(14)
    return Exits(target_r=None, xbars=B[15], xlong=(r >= 70) | (r < 40), xshort=(r <= 30) | (r > 60))


def th06(m, B, p, cache):
    """The 07:15-07:30 IST range breakout, stop at mid-range, 1:2 (BTCUSD)."""
    b = B[15]
    out = []
    for d in range(m.n_days):
        j = next((x for x in bars_of_day(b, d) if b.ist0[x] == 7 * 60 + 15), None)
        exp = last_row_before(m, d, 18 * 60 + 30, "utc")    # valid until 23:59 IST = 18:29 UTC
        if j is None or exp is None or exp <= b.i1[j]:
            continue
        H, L = float(b.h[j]), float(b.l[j])
        mid = (H + L) / 2
        k = int(b.i1[j])
        short = Signal(d, k, -1, mid, "TH06_RANGE_SHORT", entry_stop=L, expire_k=exp)
        out.append(Signal(d, k, 1, mid, "TH06_RANGE_LONG", entry_stop=H, expire_k=exp, alt=short))
    return out


def th06_x(m, B, p, cache):
    return Exits(target_r=2.0)


def _th07_ind(m, B, cache):
    key = ("th07",)
    if key not in cache:
        b = B[30]
        c = ctx(m, B, 30, cache)
        _, dirn = I.supertrend(b, 13, 4.0)
        ml, ms, _ = c.macd()
        cache[key] = (dirn, ml, ms, c.ema(200))
    return cache[key]


def th07(m, B, p, cache):
    """Supertrend + EMA 200 + MACD, three-way confirmation (BTCUSD 30-minute)."""
    b = B[30]
    a = ctx(m, B, 30, cache).atr(14)
    dirn, ml, ms, e200 = _th07_ind(m, B, cache)
    out = []
    for j in range(210, len(b.c) - 1):
        if not np.isfinite(a[j]):
            continue
        unit = float(max(abs(b.c[j] - e200[j]), a[j]))
        if dirn[j] == 1 and b.c[j] > e200[j] and ml[j] > 0 and ml[j] > ms[j]:
            out.append(sig(b, j, 1, b.c[j] * (1 - CATASTROPHE), "TH07_THREE_WAY_LONG", info={"risk_unit": unit}))
        elif dirn[j] == -1 and b.c[j] < e200[j] and ml[j] < 0 and ml[j] < ms[j]:
            out.append(sig(b, j, -1, b.c[j] * (1 + CATASTROPHE), "TH07_THREE_WAY_SHORT", info={"risk_unit": unit}))
    return out


def th07_x(m, B, p, cache):
    b = B[30]
    dirn, ml, ms, e200 = _th07_ind(m, B, cache)
    return Exits(target_r=None, xbars=b, xlong=(b.c < e200) | ((dirn == -1) & (ml < ms)),
                 xshort=(b.c > e200) | ((dirn == 1) & (ml > ms)))


def th08(m, B, p, cache):
    """EMA 288 trend, a Supertrend signal, enter on the base break, trail behind swings (BTCUSD 5-minute)."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    e288, a = c.ema(288), c.atr(14)
    _, dirn = I.supertrend(b, 10, 3.0)
    hv, hi, lv, li, _, _ = c.pivots(1)
    n = len(b.c)
    out = []
    turn = 0
    for j in range(1, n - 1):
        if dirn[j] != dirn[j - 1]:
            turn = j
        if j < 300 or not np.isfinite(a[j]):
            continue
        if b.c[j] < e288[j] and dirn[j] == -1 and li[j] >= turn and b.c[j] < lv[j] <= b.c[j - 1] and np.isfinite(hv[j]):
            out.append(sig(b, j, -1, hv[j] + 0.1 * a[j], "TH08_BASE_BREAK_SHORT"))
        elif b.c[j] > e288[j] and dirn[j] == 1 and hi[j] >= turn and b.c[j] > hv[j] >= b.c[j - 1] and np.isfinite(lv[j]):
            out.append(sig(b, j, 1, lv[j] - 0.1 * a[j], "TH08_BASE_BREAK_LONG"))
    return out


def th08_x(m, B, p, cache):
    b = B[5]
    c = ctx(m, B, 5, cache)
    a = c.atr(14)
    hv, _, lv, _, _, _ = c.pivots(1)
    return XExits(target_r=None, trail=("level", b, lv - 0.1 * a, hv + 0.1 * a))


def _darvas(m, B, cache):
    """Darvas boxes on daily rows: per row, the breakout flag (a close above a completed box's top), that box's bottom,
    and the bottom of the latest completed box (for the trailing stop). A box starts at a 52-week closing high."""
    key = ("darvas",)
    if key in cache:
        return cache[key]
    b = B[1]
    n = len(b.c)
    brk = np.zeros(n, bool)
    brk_bot = np.full(n, np.nan)
    level = np.full(n, np.nan)
    state, top, top_j, bot, cnt = "seek", np.nan, -1, np.nan, 0
    cur = np.nan
    for j in range(n):
        if j >= 251 and state == "seek":
            if b.c[j] >= b.c[j - 251:j + 1].max():
                state, top, top_j, cnt = "top", float(b.h[j]), j, 0
        elif state == "top":
            if b.h[j] > top:
                top, top_j, cnt = float(b.h[j]), j, 0
            else:
                cnt += 1
                if cnt >= 3:
                    state, bot, cnt = "bot", float(b.l[top_j + 1:j + 1].min()), 0
        elif state == "bot":
            if b.h[j] > top:
                state, top, top_j, cnt = "top", float(b.h[j]), j, 0
            elif b.l[j] < bot:
                bot, cnt = float(b.l[j]), 0
            else:
                cnt += 1
                if cnt >= 3:
                    state, cur = "box", bot
        elif state == "box":
            if b.c[j] > top:
                brk[j], brk_bot[j] = True, bot
                state, top, top_j, cnt = "top", float(b.h[j]), j, 0
            elif b.c[j] < bot:
                state = "seek"
        level[j] = cur
    cache[key] = (brk, brk_bot, level)
    return cache[key]


def th09(m, B, p, cache):
    """Darvas box at 52-week highs (NSE daily pool, long only)."""
    b = B[1]
    a = ctx(m, B, 1, cache).atr(14)
    brk, brk_bot, _ = _darvas(m, B, cache)
    liq = getattr(m, "liquid", np.ones(len(b.c), bool))
    out = []
    for j in np.flatnonzero(brk):
        j = int(j)
        if liq[j] and np.isfinite(a[j]):
            out.append(sig(b, j, 1, brk_bot[j] - 0.1 * a[j], "TH09_DARVAS_BREAKOUT"))
    return out


def th09_x(m, B, p, cache):
    b = B[1]
    a = ctx(m, B, 1, cache).atr(14)
    _, _, level = _darvas(m, B, cache)
    return XExits(target_r=None, max_hold=60, trail=("level", b, level - 0.1 * a, np.full(len(b.c), np.nan)))
