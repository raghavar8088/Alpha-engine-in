"""Indian-market strategies of the channel-shortlist study (cards/<video>.txt; the 'A' rules are this code).
Markets: NIFTY / BANKNIFTY (one-minute index rows from 09:15; bars anchored at 09:15), NSE5 / NSE15 (the 5-minute stock
pool on 5- or 15-minute bars), NSED (daily stock bars, long only, overnight). Every intraday book is out at 15:15 unless
its record sets another clock. Volume on the index rows is a placeholder (1 a minute): VWAP there is time-weighted."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

import yc_ind as I
import yt_ind as YI
from yc_common import bars_of_day, body, ctx, green, red, rng, sig
from yc_engine import XExits

import zd_common as Z
import ze_common as E
from ze_common import T, sorted_out


def _days(b, d):
    return list(bars_of_day(b, d))


# ═══ TW-01 15-minute opening range breakout on a volume expansion, VWAP side, session-low stop (NSE15) ═════════════

def tw01(m, B, p, cache):
    b = B[15]
    vol = ctx(m, B, 15, cache).vol()
    vw = Z.vwap_of(m, b, cache, "15")
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if len(js) < 2 or int(b.ist0[js[0]]) != T(9, 15):
            continue
        j0 = js[0]
        H, L = float(b.h[j0]), float(b.l[j0])
        for j in js[1:]:
            if int(b.ist0[j]) >= T(12, 45):
                break
            if j < 8 or not np.isfinite(vw[j]):
                continue
            va = float(np.mean(vol[j - 8:j]))
            if not (va > 0 and vol[j] >= 1.5 * va):
                continue
            if b.c[j] > H and b.c[j] > vw[j]:
                out.append(sig(b, j, 1, float(b.l[j0:j + 1].min()), "TW01_ORB_VOL_LONG"))
                break
            if b.c[j] < L and b.c[j] < vw[j]:
                out.append(sig(b, j, -1, float(b.h[j0:j + 1].max()), "TW01_ORB_VOL_SHORT"))
                break
    return sorted_out(out)


def tw01_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ TW-02 strong gap out of a 20-day range with RSI holding 40, range-low stop (NSED, long only) ═══════════════════

def tw02(m, B, p, cache):
    b = B[1]
    cx = ctx(m, B, 1, cache)
    a14, r14 = cx.atr(14), cx.rsi(14)
    out = []
    for j in range(61, len(b.c)):
        if not (np.isfinite(a14[j]) and np.isfinite(r14[j])):
            continue
        ph = float(b.h[j - 1])
        if not (ph < b.o[j] <= ph * 1.015):
            continue
        r = float(b.h[j] - b.l[j])
        # the volume rule is not applied: the desk's NSE daily panel carries no volume (placeholder 1)
        if not (r >= 1.2 * a14[j] and b.c[j] >= b.l[j] + 0.75 * r):
            continue
        if not b.c[j] > b.h[j - 20:j].max():
            continue
        rw = r14[j - 20:j]
        if not (np.all(np.isfinite(rw)) and rw.min() >= 38 and r14[j] > 50):
            continue
        if b.c[j] > 1.25 * b.l[j - 60:j].min():
            continue
        out.append(sig(b, j, 1, float(b.l[j - 20:j].min()), "TW02_GAP_RANGE_RSI"))
    return out


def tw02_x(m, B, p, cache):
    b = B[1]
    r14 = ctx(m, B, 1, cache).rsi(14)
    return XExits(target_r=None, xbars=b, xlong=np.nan_to_num(r14, nan=50.0) < 40, xshort=np.zeros(len(b.c), bool),
                  max_hold=20)


# ═══ DF-01 ten strongest movers on Nifty's side, Point & Figure double-top buy / double-bottom sell (NSE5) ════════

def df01(m, B, p, cache):
    b = B[5]
    cx = (p or {}).get("ctx", {})
    rk, ns = cx.get("ze_rank930", {}), cx.get("ze_nifty930", {})
    out = []
    for d in range(m.n_days):
        ds = str(m.date[d])
        side = ns.get(ds, 0)
        if side == 0 or ds not in rk:
            continue
        names = [n for _, n, _ in sorted(rk[ds], key=lambda x: -x[0] * side)[:10]]
        if m.name not in names:
            continue
        js = _days(b, d)
        if len(js) < 3:
            continue
        ref = float(b.o[js[0]])
        box = ref * 0.0015
        cols = E.pnf_columns(b.c[js[0]:js[-1] + 1], 0.0015, 3, ref)
        for i in range(1, len(cols)):
            j = js[i]
            if not T(9, 30) <= int(b.ist0[j]) + 5 <= T(14, 30):
                continue
            dirn, top, bot, fin = cols[i]
            pdir, ptop, pbot, _ = cols[i - 1]
            if side > 0 and dirn == 1 and len(fin) >= 2 and fin[-1][0] == -1 and fin[-2][0] == 1:
                prev_top = fin[-2][1]
                if top > prev_top and not (pdir == 1 and ptop > prev_top):
                    out.append(sig(b, j, 1, float(fin[-1][2] - box), "DF01_PNF_DOUBLE_TOP_BUY"))
            if side < 0 and dirn == -1 and len(fin) >= 2 and fin[-1][0] == 1 and fin[-2][0] == -1:
                prev_bot = fin[-2][2]
                if bot < prev_bot and not (pdir == -1 and pbot < prev_bot):
                    out.append(sig(b, j, -1, float(fin[-1][1] + box), "DF01_PNF_DOUBLE_BOTTOM_SELL"))
    return sorted_out(out)


def df01_x(m, B, p, cache):
    """Trail: each finished O column's low (minus a box) for longs, each X column's top (plus a box) for shorts."""
    b = B[5]
    lo = np.full(len(b.c), np.nan)
    hi = np.full(len(b.c), np.nan)
    for d in range(m.n_days):
        js = _days(b, d)
        if not js:
            continue
        ref = float(b.o[js[0]])
        box = ref * 0.0015
        cols = E.pnf_columns(b.c[js[0]:js[-1] + 1], 0.0015, 3, ref)
        for i, (_, _, _, fin) in enumerate(cols):
            os_ = [c for c in fin if c[0] == -1]
            xs = [c for c in fin if c[0] == 1]
            if os_:
                lo[js[i]] = os_[-1][2] - box
            if xs:
                hi[js[i]] = xs[-1][1] + box
    return XExits(target_r=None, trail=("level", b, lo, hi))


# ═══ DF-02 RSI(14) back through 30/70 on 5 minutes, swing stop with a points filter, VWAP then 200 EMA ═══════════

def df02(m, B, p, cache):
    b = B[5]
    cx = ctx(m, B, 5, cache)
    r = cx.rsi(14)
    e200 = cx.ema(200)
    vw = Z.vwap_of(m, b, cache, "5")
    filt = 10.0 if m.name == "NIFTY" else 50.0
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        lo_start = hi_start = None
        for j in js:
            if not np.isfinite(r[j]):
                continue
            if r[j] < 30 and (lo_start is None):
                lo_start = j
            if r[j] > 70 and (hi_start is None):
                hi_start = j
            prev_ok = j - 1 >= js[0] and np.isfinite(r[j - 1])
            t_ok = T(9, 25) <= int(b.ist0[j]) < T(14, 45)
            if prev_ok and r[j - 1] < 30 <= r[j] and lo_start is not None:
                if t_ok:
                    c = float(b.c[j])
                    stop = float(b.l[lo_start:j + 1].min()) - filt
                    info, tgt = {}, None
                    if np.isfinite(vw[j]) and vw[j] > c:
                        info["partial_px"] = float(vw[j])
                        if np.isfinite(e200[j]) and e200[j] > vw[j]:
                            tgt = float(e200[j])
                    elif np.isfinite(e200[j]) and e200[j] > c:
                        tgt = float(e200[j])
                    out.append(sig(b, j, 1, stop, "DF02_RSI30_LONG", target_px=tgt, info=info))
                lo_start = None
            elif r[j] >= 30:
                lo_start = None if r[j] > 30 else lo_start
            if prev_ok and r[j - 1] > 70 >= r[j] and hi_start is not None:
                if t_ok:
                    c = float(b.c[j])
                    stop = float(b.h[hi_start:j + 1].max()) + filt
                    info, tgt = {}, None
                    if np.isfinite(vw[j]) and vw[j] < c:
                        info["partial_px"] = float(vw[j])
                        if np.isfinite(e200[j]) and e200[j] < vw[j]:
                            tgt = float(e200[j])
                    elif np.isfinite(e200[j]) and e200[j] < c:
                        tgt = float(e200[j])
                    out.append(sig(b, j, -1, stop, "DF02_RSI70_SHORT", target_px=tgt, info=info))
                hi_start = None
            elif r[j] <= 70:
                hi_start = None if r[j] < 70 else hi_start
    return sorted_out(out)


def df02_x(m, B, p, cache):
    return XExits(target_r=2.0, partial_px=True)


# ═══ PW-01 previous close's last swing (or last-three-candle range) break, no gap entries, 1:1 (index proxy) ══════

def _pw_levels(b15, d):
    js = _days(b15, d - 1)
    if len(js) < 6:
        return None
    close = float(b15.c[js[-1]])
    tops = np.maximum(b15.o[js], b15.c[js])
    bots = np.minimum(b15.o[js], b15.c[js])
    t3, b3 = tops[-3:], bots[-3:]
    if t3.max() - b3.min() <= 0.003 * close:
        return float(t3.max()), float(b3.min())
    buy = sell = None
    for i in range(len(js) - 2, 0, -1):
        if buy is None and tops[i] > close and tops[i] > tops[i - 1] and tops[i] > tops[i + 1]:
            buy = float(tops[i])
        if sell is None and bots[i] < close and bots[i] < bots[i - 1] and bots[i] < bots[i + 1]:
            sell = float(bots[i])
        if buy is not None and sell is not None:
            break
    if buy is None or sell is None:
        return None
    return buy, sell


def pw01(m, B, p, cache):
    b, b15 = B[1], B[15]
    dist = 80.0 if m.name == "NIFTY" else 120.0
    out = []
    for d in range(1, m.n_days):
        lv = _pw_levels(b15, d)
        if lv is None:
            continue
        buy, sell = lv
        js = _days(b, d)
        for j in js[1:]:
            if int(b.ist0[j]) >= T(14, 45):
                break
            if b.c[j - 1] <= buy < b.c[j]:
                out.append(sig(b, j, 1, float(b.c[j]) - dist, "PW01_LAST_SWING_LONG", info={"stop_dist": dist}))
            elif b.c[j - 1] >= sell > b.c[j]:
                out.append(sig(b, j, -1, float(b.c[j]) + dist, "PW01_LAST_SWING_SHORT", info={"stop_dist": dist}))
    return sorted_out(out)


def pw01_x(m, B, p, cache):
    return XExits(target_r=1.0)


# ═══ VB-01 high-activity stock, first 15-minute high/low break on 5 minutes before 2 PM (NSE5) ══════════════════════

def vb01(m, B, p, cache):
    b = B[5]
    out = []
    dvol = np.array([float(np.sum(m.vol[int(m.d0[d]):int(m.d1[d])])) for d in range(m.n_days)])
    for d in range(21, m.n_days):
        base = dvol[d - 21:d - 1]
        if not (base.mean() > 0 and dvol[d - 1] >= 2.0 * base.mean()):
            continue
        js = _days(b, d)
        first = [j for j in js if int(b.ist0[j]) < T(9, 30)]
        if len(first) < 3:
            continue
        H, L = float(b.h[first].max()), float(b.l[first].min())
        for j in js:
            t0 = int(b.ist0[j])
            if t0 < T(9, 30):
                continue
            if t0 + 5 > T(14, 0):
                break
            if b.c[j] > H:
                out.append(sig(b, j, 1, float(min(b.l[j], b.l[j - 1])), "VB01_FIRST15_BREAK_LONG"))
                break
            if b.c[j] < L:
                out.append(sig(b, j, -1, float(max(b.h[j], b.h[j - 1])), "VB01_FIRST15_BREAK_SHORT"))
                break
    return sorted_out(out)


def vb01_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ VB-02 session VWAP and 15-minute Supertrend (10, 3) agreeing (NSE15) ══════════════════════════════════════════

def vb02(m, B, p, cache):
    b = B[15]
    line, dirn = ctx(m, B, 15, cache).supertrend(10, 3.0)
    vw = Z.vwap_of(m, b, cache, "15")
    bull = (b.c > vw) & (dirn > 0)
    bear = (b.c < vw) & (dirn < 0)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        for j in js[1:]:
            t0 = int(b.ist0[j])
            if t0 < T(9, 30) or not np.isfinite(vw[j]) or not np.isfinite(line[j]):
                continue
            if t0 + 15 > T(14, 0):
                break
            if bull[j] and not bull[j - 1]:
                out.append(sig(b, j, 1, float(line[j]), "VB02_VWAP_ST_LONG"))
                break
            if bear[j] and not bear[j - 1]:
                out.append(sig(b, j, -1, float(line[j]), "VB02_VWAP_ST_SHORT"))
                break
    return sorted_out(out)


def vb02_x(m, B, p, cache):
    b = B[15]
    _, dirn = ctx(m, B, 15, cache).supertrend(10, 3.0)
    vw = Z.vwap_of(m, b, cache, "15")
    with np.errstate(invalid="ignore"):
        xl = (b.c < vw) | (dirn < 0)
        xs = (b.c > vw) | (dirn > 0)
    return XExits(target_r=None, xbars=b, xlong=xl, xshort=xs)


# ═══ DH-09 BB Trend (100, 250) side + fresh MACD (48, 104, 36) cross, part at a fixed target, EMA 5/15 trail ═════

def dh09(m, B, p, cache):
    b = B[5]
    bt = cache.setdefault(("ze_bbt", 5), E.bbtrend(b.c, 100, 250, 2.0))
    ml, ms, _ = ctx(m, B, 5, cache).macd(48, 104, 36)
    part = 35.0 if m.name == "NIFTY" else 100.0
    out = []
    for d in range(m.n_days):
        for j in _days(b, d)[1:]:
            t0 = int(b.ist0[j])
            if not (T(9, 25) <= t0 < T(14, 45)) or not (np.isfinite(bt[j]) and np.isfinite(ml[j]) and np.isfinite(ms[j])):
                continue
            c = float(b.c[j])
            if bt[j] > 0 and Z.cross_up(ml, ms, j):
                out.append(sig(b, j, 1, c - 2 * part, "DH09_BBT_MACD_LONG",
                               info={"partial_px": c + part, "stop_dist": 2 * part}))
            elif bt[j] < 0 and Z.cross_dn(ml, ms, j):
                out.append(sig(b, j, -1, c + 2 * part, "DH09_BBT_MACD_SHORT",
                               info={"partial_px": c - part, "stop_dist": 2 * part}))
    return sorted_out(out)


def dh09_x(m, B, p, cache):
    b = B[5]
    cx = ctx(m, B, 5, cache)
    e5, e15 = cx.ema(5), cx.ema(15)
    with np.errstate(invalid="ignore"):
        return XExits(target_r=None, partial_px=True, xbars=b, xlong=e5 < e15, xshort=e5 > e15)


# ═══ DH-10 9:15-9:30 opening range edges + Hull MA (55) colour flips, one minute ══════════════════════════════════

def _hull_green(b, cache):
    key = ("ze_hullg", id(b))
    if key not in cache:
        h = E.hma(b.c, 55)
        g = np.zeros(len(h), bool)
        g[2:] = h[2:] > h[:-2]
        ok = np.zeros(len(h), bool)
        ok[2:] = np.isfinite(h[2:]) & np.isfinite(h[:-2])
        cache[key] = (g, ok)
    return cache[key]


def dh10(m, B, p, cache):
    b = B[1]
    g, ok = _hull_green(b, cache)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        orr = [j for j in js if int(b.ist0[j]) < T(9, 30)]
        if len(orr) < 10:
            continue
        H, L = float(b.h[orr].max()), float(b.l[orr].min())
        q = 0.25 * (H - L)
        for j in js:
            t0 = int(b.ist0[j])
            if t0 < T(9, 30) or not (ok[j] and ok[j - 1]):
                continue
            if t0 >= T(14, 45):
                break
            lo10, hi10 = float(b.l[j - 9:j + 1].min()), float(b.h[j - 9:j + 1].max())
            c = float(b.c[j])
            if g[j] and not g[j - 1] and lo10 <= L + q:
                out.append(sig(b, j, 1, c * (1 - 0.0025), "DH10_HULL_RANGE_LOW_LONG", info={"stop_frac": 0.0025}))
            elif (not g[j]) and g[j - 1] and hi10 >= H - q:
                out.append(sig(b, j, -1, c * (1 + 0.0025), "DH10_HULL_RANGE_HIGH_SHORT", info={"stop_frac": 0.0025}))
    return sorted_out(out)


def dh10_x(m, B, p, cache):
    b = B[1]
    g, ok = _hull_green(b, cache)
    turn_red = np.zeros(len(g), bool)
    turn_green = np.zeros(len(g), bool)
    turn_red[1:] = ok[1:] & ~g[1:] & g[:-1]
    turn_green[1:] = ok[1:] & g[1:] & ~g[:-1]
    return XExits(target_r=None, xbars=b, xlong=turn_red, xshort=turn_green)


# ═══ DH-11 15-minute Bollinger Band exhaustion + RSI 70/30, first opposite candle, 1% target (NSE15) ═══════════════

def dh11(m, B, p, cache):
    b = B[15]
    cx = ctx(m, B, 15, cache)
    mid, up, lo = cx.bollinger(20, 2.0)
    r = cx.rsi(14)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        done = False
        for s in js:
            if done:
                break
            if not (np.isfinite(up[s]) and np.isfinite(r[s])) or int(b.ist0[s]) < T(9, 45):
                continue
            rg = rng(b, s)
            if not (rg > 0 and body(b, s) >= 0.6 * rg):
                continue
            side = -1 if (b.c[s] > up[s] and r[s] > 70) else (1 if (b.c[s] < lo[s] and r[s] < 30) else 0)
            if side == 0:
                continue
            for t in range(s + 1, min(s + 4, js[-1] + 1)):
                t0 = int(b.ist0[t])
                if t0 < T(10, 0) or t0 > T(14, 15) or not np.isfinite(r[t - 1]):
                    continue
                col_ok = red(b, t) if side < 0 else green(b, t)
                turn = r[t] < r[t - 1] if side < 0 else r[t] > r[t - 1]
                if col_ok and turn:
                    c = float(b.c[t])
                    stop = float(b.h[t]) if side < 0 else float(b.l[t])
                    one = c * (1 + side * 0.01)
                    md = float(mid[t])
                    if not np.isfinite(md) or (md - c) * side <= 0:
                        continue
                    info, tgt = {}, md
                    if (md - one) * side > 0:
                        info["partial_px"] = one
                    out.append(sig(b, t, side, stop, "DH11_BB_RSI_REVERSAL_" + ("SHORT" if side < 0 else "LONG"),
                                   target_px=tgt, info=info))
                    done = True
                    break
    return sorted_out(out)


def dh11_x(m, B, p, cache):
    return XExits(target_r=None, partial_px=True)


# ═══ MV-02 regular RSI divergence 3-10 bars apart, confirmation candle, target the middle swing (NSED, long) ══════

def mv02(m, B, p, cache):
    b = B[1]
    r = ctx(m, B, 1, cache).rsi(14)
    lows, _ = E.pivot_points_close(b.c, 2)
    out = []
    last = -1
    for k, i2 in enumerate(lows):
        for i1 in reversed(lows[:k]):
            if i2 - i1 < 3:
                continue
            if i2 - i1 > 10:
                break
            if not (b.c[i2] < b.c[i1] and np.isfinite(r[i1]) and np.isfinite(r[i2]) and r[i2] > r[i1] and r[i1] < 40):
                continue
            for j in range(i2 + 2, min(i2 + 5, len(b.c))):
                if green(b, j) and b.c[j] > b.c[i2]:
                    tgt = float(b.h[i1:i2 + 1].max())
                    risk = float(b.c[j] - b.l[i2])
                    if risk > 0 and tgt - b.c[j] >= 3 * risk and j > last:
                        out.append(sig(b, j, 1, float(b.l[i2]), "MV02_RSI_BULL_DIVERGENCE", target_px=tgt))
                        last = j
                    break
            break
    return sorted_out(out)


def mv02_x(m, B, p, cache):
    return XExits(target_r=None, max_hold=20)


# ═══ CK-01 Connors RSI (3, 2, 100) 80/20 in the direction of RSI(14) above 60 / below 40, 5 minutes ═════════════

def ck01(m, B, p, cache):
    b = B[5]
    key = ("ze_crsi", 5)
    if key not in cache:
        cache[key] = E.connors_rsi(b.c, 3, 2, 100)
    cr = cache[key]
    r14 = ctx(m, B, 5, cache).rsi(14)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        for j in js[2:]:
            t0 = int(b.ist0[j])
            if not (T(9, 25) <= t0 < T(14, 45)):
                continue
            for side in (1, -1):
                col = green(b, j) if side > 0 else red(b, j)
                if not col:
                    continue
                hit = False
                for s in (j - 2, j - 1):
                    if s < js[0] or not (np.isfinite(cr[s]) and np.isfinite(r14[s])):
                        continue
                    if side > 0 and cr[s] < 20 and r14[s] > 60:
                        hit = not any(green(b, x) for x in range(s + 1, j))
                    if side < 0 and cr[s] > 80 and r14[s] < 40:
                        hit = not any(red(b, x) for x in range(s + 1, j))
                    if hit:
                        break
                if hit:
                    stop = float(b.l[j - 2:j + 1].min()) if side > 0 else float(b.h[j - 2:j + 1].max())
                    out.append(sig(b, j, side, stop, "CK01_CONNORS_" + ("LONG" if side > 0 else "SHORT")))
    return sorted_out(out)


def ck01_x(m, B, p, cache):
    return XExits(target_r=None, max_hold=20)


# ═══ CK-02 previous-day high/low break with a 0.5% buffer, day-extreme stop, 2R, out at 3 PM (high-beta, NSE5) ═════

def ck02(m, B, p, cache):
    b = B[5]
    out = []
    rngs = []
    for d in range(m.n_days):
        a, z = int(m.d0[d]), int(m.d1[d])
        rngs.append(float((m.h[a:z].max() - m.l[a:z].min()) / m.c[z - 1]) if z > a and m.c[z - 1] > 0 else np.nan)
    for d in range(21, m.n_days):
        mr = np.nanmean(rngs[d - 20:d])
        pd = Z.prev_day_hl(m, d)
        if not (mr >= 0.03 and pd):
            continue
        up, dn = pd[0] * 1.005, pd[1] * 0.995
        js = _days(b, d)
        for j in js:
            t0 = int(b.ist0[j])
            if t0 + 5 > T(14, 0):
                break
            nxt = [x for x in js if x > j]
            if not nxt:
                break
            exp = int(b.i1[nxt[0]])
            lo, hi = float(b.l[js[0]:j + 1].min()), float(b.h[js[0]:j + 1].max())
            if b.h[js[0]:j + 1].max() < up and lo < up:
                out.append(sig(b, j, 1, lo, "CK02_PDH_BREAK_LONG", entry_stop=up, expire_k=exp, info={"group": f"{d}"}))
            if b.l[js[0]:j + 1].min() > dn and hi > dn:
                out.append(sig(b, j, -1, hi, "CK02_PDL_BREAK_SHORT", entry_stop=dn, expire_k=exp, info={"group": f"{d}"}))
    return sorted_out(out)


def ck02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ EC-01 Supertrend (10, 3) on Heikin Ashi signals only at pivot support or on a resistance break (index) ══════

def _ha_st(b, cache):
    key = ("ze_hast", id(b))
    if key not in cache:
        ho, hh, hl, hc = I.ha_ohlc(b)
        hb = SimpleNamespace(o=ho, h=hh, l=hl, c=hc)
        line, dirn = YI.supertrend(hb, 10, 3.0)
        cache[key] = (ho, hh, hl, hc, line, dirn)
    return cache[key]


def ec01(m, B, p, cache):
    b = B[5]
    ho, hh, hl, hc, line, dirn = _ha_st(b, cache)
    piv = E.day_pivots(m, cache)
    out = []
    for d in range(1, m.n_days):
        if d not in piv:
            continue
        lv = sorted(piv[d].values())
        js = _days(b, d)
        for j in js[2:]:
            t0 = int(b.ist0[j])
            if not (T(9, 25) <= t0 < T(14, 45)) or not np.isfinite(line[j]):
                continue
            c = float(hc[j])
            if dirn[j] > 0 and dirn[j - 1] < 0:
                low3 = float(hl[j - 2:j + 1].min())
                near = any(L < c and abs(low3 - L) <= 0.001 * L for L in lv)
                brk = any(hc[x - 1] <= L < hc[x] for L in lv for x in (j - 1, j))
                if near or brk:
                    out.append(sig(b, j, 1, float(line[j]), "EC01_HA_ST_SUPPORT_LONG"))
            elif dirn[j] < 0 and dirn[j - 1] > 0:
                high3 = float(hh[j - 2:j + 1].max())
                near = any(L > c and abs(high3 - L) <= 0.001 * L for L in lv)
                brk = any(hc[x - 1] >= L > hc[x] for L in lv for x in (j - 1, j))
                if near or brk:
                    out.append(sig(b, j, -1, float(line[j]), "EC01_HA_ST_RESIST_SHORT"))
    return sorted_out(out)


def ec01_x(m, B, p, cache):
    b = B[5]
    ho, hh, hl, hc, _, _ = _ha_st(b, cache)
    eps = 1e-9
    xl = hl < np.minimum(ho, hc) - eps * np.abs(hc)
    xs = hh > np.maximum(ho, hc) + eps * np.abs(hc)
    return XExits(target_r=None, xbars=b, xlong=xl, xshort=xs)


# ═══ EC-02 9:15 candle on 2x closing volume: big candle side, second candle closes beyond it, 2R (NSE15) ════════════

def ec02(m, B, p, cache):
    b = B[15]
    vol = ctx(m, B, 15, cache).vol()
    out = []
    for d in range(1, m.n_days):
        js, pj = _days(b, d), _days(b, d - 1)
        if len(js) < 2 or not pj or int(b.ist0[js[0]]) != T(9, 15) or int(b.ist0[pj[-1]]) != T(15, 15):
            continue
        j0, j1 = js[0], js[1]
        rg = rng(b, j0)
        if not (rg > 0 and body(b, j0) >= 0.6 * rg and rg >= 0.008 * b.o[j0] and vol[pj[-1]] > 0
                and vol[j0] >= 2 * vol[pj[-1]]):
            continue
        small = rng(b, j1) < 0.0025 * b.c[j1]
        if red(b, j0) and b.c[j1] < b.l[j0]:
            stop = float(b.h[j0]) if small else float(b.h[j1])
            out.append(sig(b, j1, -1, stop, "EC02_915_BIG_RED_SHORT"))
        elif green(b, j0) and b.c[j1] > b.h[j0]:
            stop = float(b.l[j0]) if small else float(b.l[j1])
            out.append(sig(b, j1, 1, stop, "EC02_915_BIG_GREEN_LONG"))
    return sorted_out(out)


def ec02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ PC-01 trending day, pin bar at a sloping 20 MA; PC-02 previous-day high/low rejection; PC-03 wide CPR ═════════

def pc01(m, B, p, cache):
    b = B[5]
    s20 = ctx(m, B, 5, cache).sma(20)
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        for j in js:
            t0 = int(b.ist0[j])
            if not (T(9, 25) <= t0 < T(14, 45)) or j < 12 or not (np.isfinite(s20[j]) and np.isfinite(s20[j - 6])):
                continue
            hh = int(np.sum(b.h[j - 11:j + 1] > np.maximum.accumulate(b.h[j - 12:j])))
            ll = int(np.sum(b.l[j - 11:j + 1] < np.minimum.accumulate(b.l[j - 12:j])))
            up = s20[j] > s20[j - 6] and hh >= 2 and ll == 0
            dn = s20[j] < s20[j - 6] and ll >= 2 and hh == 0
            if up and b.l[j] <= s20[j] * 1.0005 and b.c[j] > s20[j] and E.pin_bar(b, j, 1):
                out.append(sig(b, j, 1, float(b.l[j]), "PC01_MA20_PIN_LONG"))
            elif dn and b.h[j] >= s20[j] * 0.9995 and b.c[j] < s20[j] and E.pin_bar(b, j, -1):
                out.append(sig(b, j, -1, float(b.h[j]), "PC01_MA20_PIN_SHORT"))
    return sorted_out(out)


def pc01_x(m, B, p, cache):
    return XExits(target_r=1.0, max_hold=15)


def pc02(m, B, p, cache):
    b = B[5]
    out = []
    for d in range(1, m.n_days):
        pd = Z.prev_day_hl(m, d)
        if not pd:
            continue
        H, L = pd[0], pd[1]
        used = set()
        for j in _days(b, d):
            t0 = int(b.ist0[j])
            if not (T(9, 20) <= t0 < T(14, 45)):
                continue
            if "H" not in used and b.h[j] >= H * (1 - 0.0005) and red(b, j) and b.c[j] < H:
                out.append(sig(b, j, -1, float(b.h[j]), "PC02_PDH_REJECT_SHORT"))
                used.add("H")
            elif "L" not in used and b.l[j] <= L * (1 + 0.0005) and green(b, j) and b.c[j] > L:
                out.append(sig(b, j, 1, float(b.l[j]), "PC02_PDL_REJECT_LONG"))
                used.add("L")
    return sorted_out(out)


def pc02_x(m, B, p, cache):
    return XExits(target_r=None, max_hold=5)


def pc03(m, B, p, cache):
    b = B[5]
    out = []
    for d in range(1, m.n_days):
        pd = Z.prev_day_hl(m, d)
        if not pd:
            continue
        P, BC, TC = E.cpr(*pd)
        if not (TC - BC) >= 0.0025 * P:
            continue
        for j in _days(b, d):
            t0 = int(b.ist0[j])
            if not (T(9, 30) <= t0 < T(14, 45)) or j < 6:
                continue
            falling = b.c[j - 6] > b.c[j - 1]
            rising = b.c[j - 6] < b.c[j - 1]
            if falling and green(b, j) and b.l[j] <= P < b.c[j] and b.c[j - 1] > P:
                out.append(sig(b, j, 1, float(b.l[j]), "PC03_WIDE_CPR_P_LONG"))
                break
            if rising and red(b, j) and b.h[j] >= P > b.c[j] and b.c[j - 1] < P:
                out.append(sig(b, j, -1, float(b.h[j]), "PC03_WIDE_CPR_P_SHORT"))
                break
    return sorted_out(out)


def pc03_x(m, B, p, cache):
    return XExits(target_r=None, max_hold=5)


# ═══ OF-01 Williams %R (10) bullish divergence with RSI below 30 on daily candles (NSED, long only) ═════════════════

def of01(m, B, p, cache):
    b = B[1]
    cx = ctx(m, B, 1, cache)
    r = cx.rsi(14)
    w = Z.williams_r(b, 10)
    a = cx.atr(14)
    lows, _ = E.pivot_points_close(b.c, 2)
    out = []
    for k, i2 in enumerate(lows):
        for i1 in reversed(lows[:k]):
            if i2 - i1 < 3:
                continue
            if i2 - i1 > 20:
                break
            if (b.c[i2] <= b.c[i1] and np.isfinite(w[i1]) and np.isfinite(w[i2]) and w[i2] > w[i1]
                    and np.isfinite(r[i2]) and r[i2] < 30 and i2 + 2 < len(b.c) and np.isfinite(a[i2])):
                out.append(sig(b, i2 + 2, 1, float(b.l[i2] - a[i2]), "OF01_WR_DIVERGENCE_RSI30"))
            break
    return sorted_out(out)


def of01_x(m, B, p, cache):
    b = B[1]
    r = ctx(m, B, 1, cache).rsi(14)
    return XExits(target_r=None, xbars=b, xlong=np.nan_to_num(r, nan=0.0) > 50, xshort=np.zeros(len(b.c), bool),
                  max_hold=15)
