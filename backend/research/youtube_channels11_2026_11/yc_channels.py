"""Strategies of six channels (rules: the "A:" lines of each analyses/<channel>.md):
  Tanisha Garg TG-01 .. TG-06, IITian Trader IT-01 / IT-02, The Trade Room TR-01, Sagar Sinha SS-01 .. SS-06,
  saya crypto SY-01, Brad Goh (The Trading Geek) BG-01 .. BG-10.
Conventions as in yc_common: completed bars only, orders from the next row, pivots only once confirmed. Functions
named *_trades build their trades themselves (multi-leg or two-step books); the others return signals, and *_x their
exits."""

from __future__ import annotations

import numpy as np

import yc_ind as I
from yc_common import (bars_of_day, bear_engulf, bias_zones, body, bull_engulf, cross_dn, cross_up, ctx, first_bar,  # noqa: F401
                       flags_cross, fvg_flags, fvg_gap, green, in_window, last_bar_before, last_done, lw,
                       nearest_pivot_beyond, pivot_lists, red, rng, sig, swing_target, uw, zone_break)
from yc_engine import XExits
from yt_engine import Exits, Signal

HOUR_ROWS = 60


def _sorted(out):
    out.sort(key=lambda s: (s.k, s.side, s.setup))
    return out


def _dedupe(out):
    seen, keep = set(), []
    for s in _sorted(out):
        key = (s.k, s.side)
        if key not in seen:
            seen.add(key)
            keep.append(s)
    return keep


# ═══ Tanisha Garg ═════════════════════════════════════════════════════════════════════════

def tg01(m, B, p, cache):
    """Failed breakout of a two-touch level (NIFTY 15-minute): short the trap back below a broken resistance."""
    b = B[15]
    a = ctx(m, B, 15, cache).atr(14)
    ph, pl = pivot_lists(m, B, 15, cache, 2)
    n = len(b.c)
    out, taken = [], set()
    for j in range(3, n):
        if not np.isfinite(a[j]):
            continue
        for lvl_side, piv, vals in ((1, ph, b.h), (-1, pl, b.l)):
            level = zone_break(vals, piv, j, 2, 0.25 * a[j], b.c[j], b.c[j - 1], lvl_side, 60)
            if level is None:
                continue
            side = -lvl_side
            for q in range(j + 1, min(j + 7, n)):
                if (b.c[q] < level) if lvl_side > 0 else (b.c[q] > level):
                    key = (int(b.day[q]), side)
                    if key not in taken and np.isfinite(a[q]):
                        ext = float(b.h[j:q + 1].max()) if side < 0 else float(b.l[j:q + 1].min())
                        out.append(sig(b, q, side, ext - side * 0.1 * a[q], "TG01_TRAP_SHORT" if side < 0 else "TG01_TRAP_LONG"))
                        taken.add(key)
                    break
    return _dedupe(out)


def tg01_x(m, B, p, cache):
    return Exits(target_r=2.0)


def tg02(m, B, p, cache):
    """RSI 21 roof (60) / floor (40) cross, the cross candle's break (NIFTY 15-minute)."""
    b = B[15]
    r = ctx(m, B, 15, cache).rsi(21)
    n = len(b.c)
    out = []
    for j in range(22, n - 1):
        if r[j - 1] >= 60 > r[j]:
            out.append(sig(b, j, -1, b.h[j], "TG02_ROOF_BREAK", entry_stop=float(b.l[j]), expire_k=int(b.i1[j + 1])))
        elif r[j - 1] <= 40 < r[j]:
            out.append(sig(b, j, 1, b.l[j], "TG02_FLOOR_BREAK", entry_stop=float(b.h[j]), expire_k=int(b.i1[j + 1])))
    return out


def tg02_x(m, B, p, cache):
    r = ctx(m, B, 15, cache).rsi(21)
    return Exits(target_r=None, xbars=B[15], xlong=r >= 50, xshort=r <= 50)


def tg03(m, B, p, cache):
    """A candle completely outside the Bollinger Band, traded back inside (NIFTY 15-minute)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    mid, up, lo = c.bollinger(20, 2.0)
    a = c.atr(14)
    n = len(b.c)
    out = []
    for j in range(25, n - 1):
        if not (np.isfinite(up[j]) and np.isfinite(a[j])) or not rng(b, j) > 0:
            continue
        exp = int(b.i1[min(j + 3, n - 1)])
        unit = float(b.h[j] - b.l[j])
        if b.l[j] > up[j]:
            out.append(sig(b, j, -1, b.h[j] + 1.5 * a[j], "TG03_OUTSIDE_UPPER", entry_stop=float(b.l[j]), expire_k=exp,
                           target_px=float(mid[j]), info={"close_stop": float(b.h[j]), "risk_unit": unit}))
        elif b.h[j] < lo[j]:
            out.append(sig(b, j, 1, b.l[j] - 1.5 * a[j], "TG03_OUTSIDE_LOWER", entry_stop=float(b.h[j]), expire_k=exp,
                           target_px=float(mid[j]), info={"close_stop": float(b.l[j]), "risk_unit": unit}))
    return out


def tg03_x(m, B, p, cache):
    return XExits(target_r=None, close_stop=(B[15],))


def tg04(m, B, p, cache):
    """A green candle engulfing the bodies of the previous three after a fall (NSE daily pool, long only)."""
    b = B[1]
    c = ctx(m, B, 1, cache)
    e20, a = c.ema(20), c.atr(14)
    lo20 = I.lowest(b.l, 20)
    liq = getattr(m, "liquid", np.ones(len(b.c), bool))
    n = len(b.c)
    out = []
    for j in range(25, n):
        if not (liq[j] and green(b, j) and np.isfinite(a[j])):
            continue
        if not all(b.c[j] >= max(b.o[k], b.c[k]) and b.o[j] <= min(b.o[k], b.c[k]) for k in range(j - 3, j)):
            continue
        if b.c[j] < e20[j] or (np.isfinite(lo20[j]) and b.c[j] - lo20[j] <= a[j]):
            out.append(sig(b, j, 1, b.l[j] * 0.998, "TG04_ENGULF_3", entry_stop=float(b.h[j]), expire_k=int(b.i1[min(j + 3, n - 1)])))
    return out


def tg04_x(m, B, p, cache):
    return Exits(target_r=2.0, max_hold=20)


def tg05(m, B, p, cache):
    """EMA 20 cross, a held pullback candle, its break; 1:4 (BTCUSD 15-minute)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e20, a = c.ema(20), c.atr(14)
    n = len(b.c)
    out = []
    for g in range(21, n - 1):
        for side in (1, -1):
            first = green(b, g) and b.c[g] > e20[g] >= b.c[g - 1] if side > 0 else red(b, g) and b.c[g] < e20[g] <= b.c[g - 1]
            if not first:
                continue
            pull = red if side > 0 else green
            r = next((x for x in (g + 1, g + 2) if x < n and pull(b, x)), None)
            if r is None or not np.isfinite(a[r]):
                continue
            held = b.c[r] >= e20[r] if side > 0 else b.c[r] <= e20[r]
            if not held:
                continue
            line = float(min(b.l[g], b.l[r])) if side > 0 else float(max(b.h[g], b.h[r]))
            trig = float(b.h[r]) if side > 0 else float(b.l[r])
            dist = (trig - line) * side
            if not dist > 0:
                continue
            out.append(sig(b, r, side, line - side * 1.5 * a[r], "TG05_EMA20_LONG" if side > 0 else "TG05_EMA20_SHORT",
                           entry_stop=trig, expire_k=int(b.i1[min(r + 2, n - 1)]), target_px=trig + side * 4 * dist,
                           info={"close_stop": line, "risk_unit": dist}))
    return _sorted(out)


def tg05_x(m, B, p, cache):
    return XExits(target_r=None, close_stop=(B[15],))


def tg06(m, B, p, cache):
    """Gann special numbers: the session closes nearer one level, the next session goes to it (NIFTY minutes, held
    overnight). Decided on the 15:28 minute's close, filled at the 15:29 open; target the nearer level, stop the
    farther; closed at the next session's close."""
    out = []
    for d in range(m.n_days):
        a, z = int(m.d0[d]), int(m.d1[d])
        idx = np.flatnonzero(m.ist[a:z] == 15 * 60 + 28)
        if not len(idx):
            continue
        r = a + int(idx[0])
        P = float(m.c[r])
        lv = I.gann_levels(P * 0.9, P * 1.1)
        below = [x for x in lv if x <= P]
        above = [x for x in lv if x > P]
        if not below or not above:
            continue
        lower, upper = max(below), min(above)
        if m.h[a:r + 1].max() >= upper and m.l[a:r + 1].min() <= lower:
            continue
        if upper - P < P - lower:
            side, target, stop = 1, upper, lower
        elif P - lower < upper - P:
            side, target, stop = -1, lower, upper
        else:
            continue
        info = {"k_last": int(m.d1[d + 1] - 1)} if d + 1 < m.n_days else {}
        out.append(Signal(d, r, side, float(stop), "TG06_GANN_UP" if side > 0 else "TG06_GANN_DOWN", info=info,
                          target_px=float(target)))
    return out


def tg06_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ IITian Trader ════════════════════════════════════════════════════════════════════════

def it01(m, B, p, cache):
    """BANKNIFTY first 5-minute candle: body at the top (bottom) and the wick below (above)."""
    b = B[5]
    out = []
    for d in range(m.n_days):
        j = first_bar(b, d)
        if j >= b.b1[d] or b.ist0[j] != 9 * 60 + 15:
            continue
        r = rng(b, j)
        if not r > 0 or body(b, j) < 0.4 * r:
            continue
        if green(b, j) and uw(b, j) <= 0.2 * r:
            out.append(sig(b, j, 1, b.l[j], "IT01_FIRST_CANDLE_UP"))
        elif red(b, j) and lw(b, j) <= 0.2 * r:
            out.append(sig(b, j, -1, b.h[j], "IT01_FIRST_CANDLE_DOWN"))
    return out


def it01_x(m, B, p, cache):
    return Exits(target_r=None)


def it02_signals(m, B, p, cache):
    """IT-02 entries (BTCUSD 15-minute): EMA 9 crossing EMA 11 back in EMA 45's direction; the room is ATR 14."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e9, e11, e45, a = c.ema(9), c.ema(11), c.ema(45), c.atr(14)
    up, dn = flags_cross(e9, e11)
    out = []
    for j in range(50, len(b.c)):
        if not np.isfinite(a[j]):
            continue
        if up[j] and b.c[j] > e45[j] and e45[j] > e45[j - 4]:
            out.append(sig(b, j, 1, b.c[j] - 1.8 * a[j], "IT02_ROOM_LONG", info={"room": float(a[j])}))
        elif dn[j] and b.c[j] < e45[j] and e45[j] < e45[j - 4]:
            out.append(sig(b, j, -1, b.c[j] + 1.8 * a[j], "IT02_ROOM_SHORT", info={"room": float(a[j])}))
    return out


def it02_trades(m, B, p, cache, eng, strategy="IT-02", since_k: int = 0):
    from yc_engine import room_trades
    S = [s for s in it02_signals(m, B, p, cache) if s.k + 1 >= since_k]
    return room_trades(eng, S, strategy, 48 * 15, len(m.t) - 1)


# ═══ The Trade Room ═══════════════════════════════════════════════════════════════════════

def tr01(m, B, p, cache):
    """EMA 9/15 scalp on three entry candles (BANKNIFTY 5-minute)."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    e9, e15, ba = c.ema(9), c.ema(15), c.body_avg(20)
    n = len(b.c)
    out = []
    for j in range(20, n - 1):
        if not np.isfinite(ba[j]):
            continue
        r, bd = rng(b, j), body(b, j)
        if not r > 0:
            continue
        exp = int(b.i1[min(j + 2, n - 1)])
        if e9[j] > e15[j] and e9[j] > e9[j - 3] and e15[j] > e15[j - 3] and b.l[j] <= e9[j] and b.c[j] > e15[j]:
            pin = lw(b, j) >= 2 * bd
            big = green(b, j) and bd >= 0.6 * r and bd >= ba[j]
            cross = b.o[j] < e9[j] < b.c[j]
            if pin or big or cross:
                out.append(sig(b, j, 1, b.l[j], "TR01_LONG", entry_stop=float(b.h[j]), expire_k=exp))
        elif e9[j] < e15[j] and e9[j] < e9[j - 3] and e15[j] < e15[j - 3] and b.h[j] >= e9[j] and b.c[j] < e15[j]:
            pin = uw(b, j) >= 2 * bd
            big = red(b, j) and bd >= 0.6 * r and bd >= ba[j]
            cross = b.o[j] > e9[j] > b.c[j]
            if pin or big or cross:
                out.append(sig(b, j, -1, b.h[j], "TR01_SHORT", entry_stop=float(b.l[j]), expire_k=exp))
    return out


def tr01_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ═══ Sagar Sinha ══════════════════════════════════════════════════════════════════════════

def _ss01_alerts(m, B, cache):
    key = ("ss01",)
    if key not in cache:
        b = B[1]
        hb = I.HABars(b)
        mid, up, lo = I.bollinger(hb.c, 20, 2.0)
        n = len(b.c)
        sell = np.zeros(n, bool)
        buy = np.zeros(n, bool)
        ok = np.isfinite(up)
        sell[1:] = ok[1:] & ok[:-1] & (hb.h[:-1] >= up[:-1]) & (hb.h[1:] < up[1:])
        buy[1:] = ok[1:] & ok[:-1] & (hb.l[:-1] <= lo[:-1]) & (hb.l[1:] > lo[1:])
        cache[key] = (mid, up, lo, sell, buy)
    return cache[key]


def ss01(m, B, p, cache):
    """Bollinger Band + Heikin Ashi alert candle (NIFTY daily), guest Kushal Varshney."""
    b = B[1]
    mid, up, lo, sell, buy = _ss01_alerts(m, B, cache)
    n = len(b.c)
    out = []
    for a in np.flatnonzero(sell | buy):
        a = int(a)
        side = -1 if sell[a] else 1
        last = min(a + 25, n - 1)
        # an alert is invalid once the other side breaks first: the order is cancelled on that day
        for x in range(a + 1, last + 1):
            if (b.h[x] > b.h[a]) if side < 0 else (b.l[x] < b.l[a]):
                last = x - 1
                break
        if last <= a:
            continue
        if side < 0:
            out.append(sig(b, a, -1, b.h[a], "SS01_UPPER_ALERT", entry_stop=float(b.l[a]), expire_k=int(b.i1[last]),
                           target_px=float(lo[a])))
        else:
            out.append(sig(b, a, 1, b.l[a], "SS01_LOWER_ALERT", entry_stop=float(b.h[a]), expire_k=int(b.i1[last]),
                           target_px=float(up[a])))
    return out


def ss01_x(m, B, p, cache):
    _, _, _, sell, buy = _ss01_alerts(m, B, cache)
    return Exits(target_r=None, xbars=B[1], xlong=sell, xshort=buy, max_hold=25)


def ss02(m, B, p, cache):
    """EMA 5/13 cross at the previous UTC day's high or low, swing-to-swing (BTCUSD 15-minute)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e5, e13, a = c.ema(5), c.ema(13), c.atr(14)
    up, dn = flags_cross(e5, e13)
    H, L, _ = I.day_hlc(m)
    ph, pl = pivot_lists(m, B, 15, cache, 1)
    hv, _, lv, _, _, _ = c.pivots(1)
    n = len(b.c)
    out = []
    for side, crosses in ((1, np.flatnonzero(up)), (-1, np.flatnonzero(dn))):
        for x in crosses:
            x = int(x)
            j = x + 1
            d = int(b.day[x])
            if j >= n or d < 1 or not np.isfinite(a[x]) or not np.isfinite(a[j]):
                continue
            near = b.l[x] <= L[d - 1] + 0.5 * a[x] if side > 0 else b.h[x] >= H[d - 1] - 0.5 * a[x]
            if not near:
                continue
            swing = lv[j] if side > 0 else hv[j]
            if not np.isfinite(swing):
                continue
            stop = float(swing - side * 0.1 * a[j])
            ref = float(b.c[j])
            dist = (ref - stop) * side
            if not 0 < dist <= 3 * a[j]:
                continue
            lvl = nearest_pivot_beyond(b.h if side > 0 else b.l, ph if side > 0 else pl, j, 1, side, ref)
            out.append(sig(b, j, side, stop, "SS02_EDGE_CROSS_LONG" if side > 0 else "SS02_EDGE_CROSS_SHORT",
                           target_px=swing_target(side, ref, stop, lvl, 1.0, 2.0)))
    return _sorted(out)


def ss02_x(m, B, p, cache):
    return Exits(target_r=None)


def ss03_context(pool) -> dict:
    """{date: (side, set of symbols)}: the pool's breadth at 09:25 (price above vs below the previous close) sets the
    day's side; the three weakest stocks by 09:25 change are traded on a short day, the three strongest on a long day."""
    by_date: dict = {}
    for m in pool:
        for d in range(1, m.n_days):
            if not m.prev_ok[d]:
                continue
            a, z = int(m.d0[d]), int(m.d1[d])
            ist = m.ist[a:z]
            idx = np.flatnonzero((ist >= 9 * 60 + 20) & (ist < 9 * 60 + 25))   # the 09:20 row closes at 09:25
            if not len(idx):
                continue
            px = float(m.c[a + int(idx[-1])])
            pc = float(m.c[m.d1[d - 1] - 1])
            if pc > 0:
                by_date.setdefault(str(m.date[d]), []).append((px / pc - 1, m.name))
    out = {}
    for day, rows in by_date.items():
        upn = sum(1 for r, _ in rows if r > 0)
        dnn = sum(1 for r, _ in rows if r < 0)
        if upn == dnn:
            continue
        side = 1 if upn > dnn else -1
        pick = sorted(rows, key=lambda x: (-x[0], x[1]) if side > 0 else (x[0], x[1]))[:3]
        out[day] = (side, {s for _, s in pick})
    return out


def ss03(m, B, p, cache):
    """The lowest-volume opposite candle (NSE 5-minute pool), guest Kushal Varshney. p["ctx"]["ss03"] = ss03_context."""
    cx = (p.get("ctx") or {}).get("ss03") or {}
    b = B[5]
    vol = ctx(m, B, 5, cache).vol()
    out = []
    for d in range(m.n_days):
        pick = cx.get(str(m.date[d]))
        if not pick or m.name not in pick[1]:
            continue
        side = pick[0]
        rows = list(bars_of_day(b, d))
        last = last_bar_before(b, d, 14 * 60 + 30)
        if not rows or last is None:
            continue
        lowest = np.inf
        cands = []
        for i, j in enumerate(rows):
            opp = green(b, j) if side < 0 else red(b, j)
            if i >= 3 and j <= last and opp and vol[j] < lowest:
                cands.append(j)
            lowest = min(lowest, float(vol[j]))
        for i, j in enumerate(cands):
            until = cands[i + 1] if i + 1 < len(cands) else last
            if side < 0:
                out.append(sig(b, j, -1, b.h[j], "SS03_EMPTY_TRAIN_SHORT", entry_stop=float(b.l[j]), expire_k=int(b.i1[until])))
            else:
                out.append(sig(b, j, 1, b.l[j], "SS03_EMPTY_TRAIN_LONG", entry_stop=float(b.h[j]), expire_k=int(b.i1[until])))
    return out


def ss03_x(m, B, p, cache):
    b = B[5]
    return Exits(target_r=None, partial_at_r=2.0, trail_from_r=2.0, trail_bars=b, trail_ema=ctx(m, B, 5, cache).ema(10))


def ss04_trades(m, B, p, cache, eng, k_end_of_day, strategy="SS-04"):
    """The 09:45-09:50 candle (BANKNIFTY): stop-entries on both sides, whichever triggers first; after a stop the
    other side may still trigger; stop at the candle's other end; out at 15:15; at most two trades a day."""
    b = B[5]
    ex = Exits(target_r=None)
    out = []
    for d in range(m.n_days):
        j = next((x for x in bars_of_day(b, d) if b.ist0[x] == 9 * 60 + 45), None)
        ke = k_end_of_day(d)
        if j is None or ke is None or b.i1[j] >= ke:
            continue
        H, L = float(b.h[j]), float(b.l[j])
        k = int(b.i1[j])
        short = Signal(d, k, -1, H, "SS04_SHORT", entry_stop=L, expire_k=ke)
        long_ = Signal(d, k, 1, L, "SS04_LONG", entry_stop=H, expire_k=ke, alt=short)
        t1, _ = eng.trade(long_, ex, ke, strategy, "V0")
        if t1 is None:
            continue
        out.append(t1)
        if t1.reason == "stop" and t1.exit_k < ke:
            other = Signal(d, int(t1.exit_k) - 1, -t1.side, H if t1.side > 0 else L, "SS04_SHORT" if t1.side > 0 else "SS04_LONG",
                           entry_stop=L if t1.side > 0 else H, expire_k=ke)
            t2, _ = eng.trade(other, ex, ke, strategy, "V0")
            if t2 is not None and t2.entry_k >= t1.exit_k:
                out.append(t2)
    return out


def ss05(m, B, p, cache):
    """BTST: the Heikin Ashi close against the real close at 15:15 (NIFTY minutes), guest Kushal Varshney."""
    H, L, C = I.day_hlc(m)
    pc = np.r_[C[0], C[:-1]]
    datr = I.rma(np.maximum(H, pc) - np.minimum(L, pc), 14)
    out = []
    for d in range(15, m.n_days):
        a, z = int(m.d0[d]), int(m.d1[d])
        idx = np.flatnonzero(m.ist[a:z] == 15 * 60 + 15)
        if not len(idx) or not np.isfinite(datr[d - 1]):
            continue
        r = a + int(idx[0])
        P = float(m.c[r])
        hac = (float(m.o[a]) + float(m.h[a:r + 1].max()) + float(m.l[a:r + 1].min()) + P) / 4
        if abs(hac - P) < 10:
            continue
        side = -1 if hac > P else 1
        info = {}
        if d + 1 < m.n_days:
            a2, z2 = int(m.d0[d + 1]), int(m.d1[d + 1])
            nxt = np.flatnonzero(m.ist[a2:z2] <= 9 * 60 + 19)
            if len(nxt):
                info["k_last"] = a2 + int(nxt[-1])
        out.append(Signal(d, r, side, float(P - side * datr[d - 1]), "SS05_HA_GAP_UP" if side > 0 else "SS05_HA_GAP_DOWN", info=info))
    return out


def ss05_x(m, B, p, cache):
    return XExits(target_r=None)


def ss06(m, B, p, cache):
    """EMA 30/50/100 stacked, a limit at EMA 30 on the first pullback (BTCUSD 15-minute), guest Priyank."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e30, e50, e100, a = c.ema(30), c.ema(50), c.ema(100), c.atr(14)
    hv, _, lv, _, _, _ = c.pivots(1)
    s30, s50, s100 = I.shift(e30, 4), I.shift(e50, 4), I.shift(e100, 4)
    with np.errstate(invalid="ignore"):
        st_up = (e30 > e50) & (e50 > e100) & (e30 > s30) & (e50 > s50) & (e100 > s100) & (e30 - e100 >= a)
        st_dn = (e30 < e50) & (e50 < e100) & (e30 < s30) & (e50 < s50) & (e100 < s100) & (e100 - e30 >= a)
    n = len(b.c)
    out = []
    for side, st in ((1, st_up), (-1, st_dn)):
        for s in np.flatnonzero(st[1:] & ~st[:-1]) + 1:
            s = int(s)
            for j in range(s, min(s + 12, n)):
                if not st[j]:
                    break
                swing = lv[j] if side > 0 else hv[j]
                above = b.c[j] > e30[j] if side > 0 else b.c[j] < e30[j]
                if not (above and np.isfinite(swing) and np.isfinite(a[j])):
                    continue
                stop = float(swing - side * 0.1 * a[j])
                if (e30[j] - stop) * side <= 0:
                    continue
                out.append(sig(b, j, side, stop, "SS06_STACK_LONG" if side > 0 else "SS06_STACK_SHORT", entry_limit=float(e30[j]),
                               expire_k=int(b.i1[min(j + 1, n - 1)]), info={"group": (side, s)}))
    return _sorted(out)


def ss06_x(m, B, p, cache):
    return Exits(target_r=2.0)


# ═══ saya crypto ══════════════════════════════════════════════════════════════════════════

def sy01(m, B, p, cache):
    """A 1-hour trend's break, entered on 15 minutes (BTCUSD)."""
    b, bh = B[15], B[60]
    hv, hi, lv, li, phv, plv = ctx(m, B, 60, cache).pivots(2)
    a = ctx(m, B, 15, cache).atr(14)
    hv15, _, lv15, _, _, _ = ctx(m, B, 15, cache).pivots(1)
    used = set()
    out = []
    for j in range(2, len(b.c)):
        q = last_done(bh, int(b.i1[j]))
        if q < 0 or not np.isfinite(a[j]):
            continue
        up = hv[q] > phv[q] and lv[q] > plv[q]
        dn = hv[q] < phv[q] and lv[q] < plv[q]
        if up and b.c[j] < lv[q] <= b.c[j - 1] and ("S", int(li[q])) not in used and np.isfinite(hv15[j]):
            used.add(("S", int(li[q])))
            out.append(sig(b, j, -1, hv15[j] + 0.1 * a[j], "SY01_TREND_BREAK_SHORT"))
        elif dn and b.c[j] > hv[q] >= b.c[j - 1] and ("L", int(hi[q])) not in used and np.isfinite(lv15[j]):
            used.add(("L", int(hi[q])))
            out.append(sig(b, j, 1, lv15[j] - 0.1 * a[j], "SY01_TREND_BREAK_LONG"))
    return out


def sy01_x(m, B, p, cache):
    return Exits(target_r=2.0, be_at_r=1.0)


# ═══ Brad Goh (The Trading Geek) ══════════════════════════════════════════════════════════

def bg01(m, B, p, cache):
    """Gold: 1-hour bias and point of interest, a 15-minute sweep inside it, one candle of confirmation."""
    b, bh = B[15], B[60]
    bias, zlo, zhi, zid = bias_zones(m, B, 60, cache, 2)
    a = ctx(m, B, 15, cache).atr(14)
    hv1, _, lv1, _, _, _ = ctx(m, B, 15, cache).pivots(1)
    ph, pl = pivot_lists(m, B, 15, cache, 1)
    n = len(b.c)
    out = []
    for j in range(3, n):
        q = last_done(bh, int(b.i1[j]))
        if q < 0 or bias[q] == 0 or not np.isfinite(zlo[q]):
            continue
        side = int(bias[q])
        if not (b.l[j] <= zhi[q] and b.h[j] >= zlo[q]):
            continue
        lvl = lv1[j] if side > 0 else hv1[j]
        if not np.isfinite(lvl):
            continue
        swept = (b.l[j] < lvl < b.c[j]) if side > 0 else (b.h[j] > lvl > b.c[j])
        if not swept:
            continue
        conf = green if side > 0 else red
        for g in range(j + 1, min(j + 4, n)):
            if conf(b, g) and np.isfinite(a[g]):
                ext = float(b.l[j:g + 1].min()) if side > 0 else float(b.h[j:g + 1].max())
                stop = ext - side * 0.1 * a[g]
                ref = float(b.c[g])
                tl = nearest_pivot_beyond(b.h if side > 0 else b.l, ph if side > 0 else pl, g, 1, side, ref)
                out.append(sig(b, g, side, stop, "BG01_POI_SWEEP_LONG" if side > 0 else "BG01_POI_SWEEP_SHORT",
                               target_px=swing_target(side, ref, stop, tl, 1.5, 2.0), info={"group": int(zid[q])}))
                break
    return _dedupe(out)


def bg01_x(m, B, p, cache):
    return Exits(target_r=None)


def bg02(m, B, p, cache):
    """The liquidation candle after a sweep of a recent 3-candle fractal (gold 5-minute)."""
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    ph, pl = pivot_lists(m, B, 5, cache, 1)
    n = len(b.c)
    out = []
    for j in range(3, n):
        r, bd = rng(b, j), body(b, j)
        if not (r > 0 and np.isfinite(a[j])):
            continue
        exp = int(b.i1[min(j + 2, n - 1)])
        if lw(b, j) >= 2 * bd and lw(b, j) >= 0.6 * r:
            k = int(np.searchsorted(pl, j - 1, "right"))
            if any(q >= j - 24 and b.l[j] < b.l[q] < b.c[j] for q in pl[max(0, k - 24):k]):
                out.append(sig(b, j, 1, b.l[j] - 0.1 * a[j], "BG02_LIQUIDATION_LONG", entry_stop=float(b.h[j]), expire_k=exp))
                continue
        if uw(b, j) >= 2 * bd and uw(b, j) >= 0.6 * r:
            k = int(np.searchsorted(ph, j - 1, "right"))
            if any(q >= j - 24 and b.c[j] < b.h[q] < b.h[j] for q in ph[max(0, k - 24):k]):
                out.append(sig(b, j, -1, b.h[j] + 0.1 * a[j], "BG02_LIQUIDATION_SHORT", entry_stop=float(b.l[j]), expire_k=exp))
    return out


def bg02_x(m, B, p, cache):
    return Exits(target_r=2.0)


def bg03(m, B, p, cache):
    """Gold: 15-minute bias and zone, a 1-minute sweep inside it, a limit at the sweeping candle's body."""
    b1, bq = B[1], B[15]
    bias, zlo, zhi, _ = bias_zones(m, B, 15, cache, 2)
    a1 = ctx(m, B, 1, cache).atr(14)
    hv, _, lv, _, _, _ = ctx(m, B, 1, cache).pivots(1)
    n = len(b1.c)
    out = []
    for j in range(3, n):
        q = last_done(bq, int(b1.i1[j]))
        if q < 0 or bias[q] == 0 or not np.isfinite(zlo[q]) or not np.isfinite(a1[j]):
            continue
        side = int(bias[q])
        if not (b1.l[j] <= zhi[q] and b1.h[j] >= zlo[q]):
            continue
        exp = int(b1.i1[min(j + 30, n - 1)])
        if side > 0 and np.isfinite(lv[j]) and b1.l[j] < lv[j] < b1.c[j]:
            out.append(sig(b1, j, 1, b1.l[j] - 0.1 * a1[j], "BG03_SWEEP_ZONE_LONG",
                           entry_limit=float(max(b1.o[j], b1.c[j])), expire_k=exp))
        elif side < 0 and np.isfinite(hv[j]) and b1.h[j] > hv[j] > b1.c[j]:
            out.append(sig(b1, j, -1, b1.h[j] + 0.1 * a1[j], "BG03_SWEEP_ZONE_SHORT",
                           entry_limit=float(min(b1.o[j], b1.c[j])), expire_k=exp))
    return out


def bg03_x(m, B, p, cache):
    return Exits(target_r=2.0)


def bg04(m, B, p, cache):
    """The Asia range swept at the London open (GBPUSD 5-minute)."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    a, ba = c.atr(14), c.body_avg(20)
    H, L, _ = I.day_hlc(m)
    adr = I.mean_prev(H - L, 20)
    out = []
    for d in range(21, m.n_days):
        rows = list(bars_of_day(b, d))
        asia = [j for j in rows if b.ny0[j] >= 19 * 60 or b.ny0[j] < 3 * 60]
        if len(asia) < 77 or not np.isfinite(adr[d]):        # at least 80% of the 96 five-minute candles
            continue
        AH, AL = float(max(b.h[j] for j in asia)), float(min(b.l[j] for j in asia))
        if not 0.25 * adr[d] <= AH - AL <= 0.9 * adr[d]:
            continue
        for j in rows:
            if not 3 * 60 <= b.ny0[j] < 6 * 60:
                continue
            if b.h[j] > AH and AL <= b.c[j] < AH:
                side = -1
            elif b.l[j] < AL and AL < b.c[j] <= AH:
                side = 1
            else:
                continue
            for q in range(j + 1, min(j + 4, len(b.c))):
                if b.day[q] != d or not np.isfinite(ba[q]):
                    break
                if body(b, q) >= 1.5 * ba[q] and (green(b, q) if side > 0 else red(b, q)):
                    ext = float(b.l[j:q + 1].min()) if side > 0 else float(b.h[j:q + 1].max())
                    out.append(sig(b, q, side, ext - side * 0.1 * a[q], "BG04_ASIA_SWEEP_LONG" if side > 0 else "BG04_ASIA_SWEEP_SHORT"))
                    break
    return _dedupe(out)


def bg04_x(m, B, p, cache):
    return Exits(target_r=2.0)


def bg05(m, B, p, cache):
    """Gold supply/demand zone, first retest, a close back across EMA 8 that engulfs (15-minute entries)."""
    b, bh = B[15], B[60]
    ah = ctx(m, B, 60, cache).atr(14)
    c = ctx(m, B, 15, cache)
    a, e8 = c.atr(14), c.ema(8)
    nh, n = len(bh.c), len(b.c)
    out = []
    for q in range(1, nh - 3):
        if not np.isfinite(ah[q + 3]):
            continue
        g3 = all(green(bh, x) for x in (q + 1, q + 2, q + 3)) and bh.c[q + 3] - bh.o[q + 1] >= 2 * ah[q + 3]
        r3 = all(red(bh, x) for x in (q + 1, q + 2, q + 3)) and bh.o[q + 1] - bh.c[q + 3] >= 2 * ah[q + 3]
        if not (g3 or r3):
            continue
        side = 1 if g3 else -1
        zlo, zhi = float(bh.l[q]), float(bh.h[q])
        known = int(bh.i1[q + 3])
        t_end = int(bh.t0[q]) + 10 * 86400
        j = int(np.searchsorted(b.i0, known, "right"))
        touch = None
        while j < n and b.t0[j] < t_end:
            if (b.l[j] <= zhi) if side > 0 else (b.h[j] >= zlo):
                touch = j
                break
            j += 1
        if touch is None:
            continue
        for g in range(touch, min(touch + 8, n)):
            if not np.isfinite(a[g]) or b.t0[g] >= t_end:
                break
            crossed = (b.c[g] > e8[g] and b.c[g - 1] <= e8[g - 1]) if side > 0 else (b.c[g] < e8[g] and b.c[g - 1] >= e8[g - 1])
            if crossed and (bull_engulf(b, g) if side > 0 else bear_engulf(b, g)):
                stop = zlo - 0.1 * a[g] if side > 0 else zhi + 0.1 * a[g]
                out.append(sig(b, g, side, stop, "BG05_DEMAND_RETEST" if side > 0 else "BG05_SUPPLY_RETEST"))
                break
    return _dedupe(out)


def bg05_x(m, B, p, cache):
    return Exits(target_r=2.0)


def bg06(m, B, p, cache):
    """EMA 8/14 cross with an engulfing candle (NAS100 5-minute, New York cash session)."""
    b = B[5]
    c = ctx(m, B, 5, cache)
    up, dn = flags_cross(c.ema(8), c.ema(14))
    n = len(b.c)
    out = []
    for side, crosses in ((1, np.flatnonzero(up)), (-1, np.flatnonzero(dn))):
        for x in crosses:
            for g in (int(x), int(x) + 1):
                if g >= n or b.day[g] != b.day[x] or not in_window(b, g, 9 * 60 + 30, 16 * 60, "ny"):
                    continue
                if bull_engulf(b, g) if side > 0 else bear_engulf(b, g):
                    out.append(sig(b, g, side, b.l[g] if side > 0 else b.h[g], "BG06_CROSS_ENGULF_LONG" if side > 0 else "BG06_CROSS_ENGULF_SHORT"))
                    break
    return _dedupe(out)


def bg06_x(m, B, p, cache):
    return Exits(target_r=2.0)


def bg07(m, B, p, cache):
    """Silver bullet, his version (NAS100 5-minute, 10:00-11:00 New York)."""
    b = B[5]
    a = ctx(m, B, 5, cache).atr(14)
    f = fvg_flags(m, B, 5, cache)
    ph, pl = ctx(m, B, 5, cache).fractals(1)
    out = []
    for d in range(m.n_days):
        rows = list(bars_of_day(b, d))
        sess = [j for j in rows if 9 * 60 + 30 <= b.ny0[j] < 16 * 60]
        last = last_bar_before(b, d, 11 * 60 + 30, "ny")
        if not sess or last is None:
            continue
        s0 = sess[0]
        used = set()
        for s in rows:
            if not 10 * 60 <= b.ny0[s] < 11 * 60:
                continue
            highs = [q for q in range(s0, s - 1) if ph[q]]
            lows = [q for q in range(s0, s - 1) if pl[q]]
            sides = []
            if any(b.h[s] > b.h[q] for q in highs):
                sides.append(-1)
            if any(b.l[s] < b.l[q] for q in lows):
                sides.append(1)
            for side in sides:
                for j in range(s + 1, len(b.c)):
                    if b.day[j] != d or b.ny0[j] >= 11 * 60:
                        break
                    if f[j] != side or j in used or not np.isfinite(a[j]):
                        continue
                    g_lo, g_hi = fvg_gap(b, j, side)
                    entry = g_hi if side > 0 else g_lo
                    ext = float(b.l[s:j + 1].min()) if side > 0 else float(b.h[s:j + 1].max())
                    stop = ext - side * 0.1 * a[j]
                    opp = [b.h[q] for q in range(s0, j - 1) if ph[q] and b.h[q] > entry] if side > 0 else \
                          [b.l[q] for q in range(s0, j - 1) if pl[q] and b.l[q] < entry]
                    lvl = (min(opp) if side > 0 else max(opp)) if opp else None
                    out.append(sig(b, j, side, stop, "BG07_SILVER_BULLET_LONG" if side > 0 else "BG07_SILVER_BULLET_SHORT",
                                   entry_limit=float(entry), expire_k=int(b.i1[last]),
                                   target_px=swing_target(side, entry, stop, lvl, 2.0, 2.0)))
                    used.add(j)
                    break
    return _dedupe(out)


def bg07_x(m, B, p, cache):
    return Exits(target_r=None)


def bg08(m, B, p, cache):
    """Candle range theory on 15 minutes, the sweep on 5 minutes (gold)."""
    b5, bq = B[5], B[15]
    aq = ctx(m, B, 15, cache).atr(14)
    a5 = ctx(m, B, 5, cache).atr(14)
    nq, n5 = len(bq.c), len(b5.c)
    out = []
    for R in range(15, nq):
        if not (np.isfinite(aq[R]) and rng(bq, R) >= 1.2 * aq[R]):
            continue
        H, L = float(bq.h[R]), float(bq.l[R])
        end_row = int(bq.i1[min(R + 4, nq - 1)])
        j = int(np.searchsorted(b5.i0, int(bq.i1[R]), "right"))
        while j < n5 and b5.i1[j] <= end_row:
            if not np.isfinite(a5[j]):
                j += 1
                continue
            if b5.l[j] < L and L < b5.c[j] < H:
                stop = float(b5.l[j] - 0.1 * a5[j])
                if H - b5.c[j] >= 1.5 * (b5.c[j] - stop):
                    out.append(sig(b5, j, 1, stop, "BG08_CRT_LONG", target_px=H))
                break
            if b5.h[j] > H and L < b5.c[j] < H:
                stop = float(b5.h[j] + 0.1 * a5[j])
                if b5.c[j] - L >= 1.5 * (stop - b5.c[j]):
                    out.append(sig(b5, j, -1, stop, "BG08_CRT_SHORT", target_px=L))
                break
            j += 1
    return _dedupe(out)


def bg08_x(m, B, p, cache):
    return Exits(target_r=None)


def bg09(m, B, p, cache):
    """Break and retest with a confirmation candle, 1:3 (EURUSD 15-minute)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    e50, a = c.ema(50), c.atr(14)
    hv, hi, lv, li, _, _ = c.pivots(2)
    n = len(b.c)
    out = []
    used_h = used_l = -1
    for x in range(60, n):
        for side in (1, -1):
            piv, lvl = (hi[x], hv[x]) if side > 0 else (li[x], lv[x])
            if piv < 0 or piv == (used_h if side > 0 else used_l):
                continue
            if not ((b.c[x] > lvl) if side > 0 else (b.c[x] < lvl)):
                continue
            if side > 0:
                used_h = int(piv)
            else:
                used_l = int(piv)
            for q in range(x + 1, min(x + 21, n)):
                if not np.isfinite(a[q]):
                    continue
                near = (abs(min(b.l[q - 1], b.l[q]) - lvl) <= 0.25 * a[q]) if side > 0 else (abs(max(b.h[q - 1], b.h[q]) - lvl) <= 0.25 * a[q])
                trend = (e50[q] > e50[q - 1] and b.c[q] > e50[q]) if side > 0 else (e50[q] < e50[q - 1] and b.c[q] < e50[q])
                if side > 0:
                    conf = (bull_engulf(b, q) or lw(b, q) >= 2 * body(b, q)) and b.c[q] > lvl
                else:
                    conf = (bear_engulf(b, q) or uw(b, q) >= 2 * body(b, q)) and b.c[q] < lvl
                if near and trend and conf:
                    out.append(sig(b, q, side, lvl - side * 0.25 * a[q], "BG09_RETEST_LONG" if side > 0 else "BG09_RETEST_SHORT"))
                    break
    return _dedupe(out)


def bg09_x(m, B, p, cache):
    return Exits(target_r=3.0)


def bg10(m, B, p, cache):
    """Consolidation breakout on a momentum candle (EURUSD 15-minute)."""
    b = B[15]
    c = ctx(m, B, 15, cache)
    a, ba = c.atr(14), c.body_avg(20)
    n = len(b.c)
    out = []
    for j in range(21, n):
        if not (np.isfinite(a[j - 1]) and np.isfinite(ba[j])):
            continue
        hi16, lo16 = float(b.h[j - 16:j].max()), float(b.l[j - 16:j].min())
        if hi16 - lo16 > 2 * a[j - 1] or body(b, j) < 1.8 * ba[j]:
            continue
        if green(b, j) and b.c[j] > hi16:
            out.append(sig(b, j, 1, b.l[j], "BG10_BREAKOUT_LONG"))
        elif red(b, j) and b.c[j] < lo16:
            out.append(sig(b, j, -1, b.h[j], "BG10_BREAKOUT_SHORT"))
    return out


def bg10_x(m, B, p, cache):
    c = ctx(m, B, 15, cache)
    up, dn = flags_cross(c.ema(8), c.ema(14))
    return XExits(target_r=None, partial_at_r=3.0, xbars=B[15], xlong=dn, xshort=up, x_from_r=3.0)
