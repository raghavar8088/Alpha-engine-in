"""Bitcoin, gold, forex and Nasdaq strategies of the channel-shortlist study (cards/<video>.txt; the 'A' rules are this
code). Markets: BTCUSD (one-minute Delta rows, the UTC day, out at 23:55 UTC), XAUUSD (gold; the desk books it on Delta
XAUTUSD), EURUSD / GBPUSD (the desk's FX futures minutes; the day rolls at 17:00 New York), NAS100 (the Nasdaq 100 cash
session, 09:30-16:00 New York). FX and Nasdaq rows carry a placeholder volume, so their VWAP is time-weighted."""

from __future__ import annotations

import numpy as np

from yc_common import bars_of_day, body, ctx, green, last_done, red, rng, sig
from yc_engine import XExits

import zd_common as Z
import ze_common as E
from ze_common import sorted_out


def _days(b, d):
    return list(bars_of_day(b, d))


def _fin(*xs) -> bool:
    return all(np.isfinite(x) for x in xs)


# ═══ CC-01 clean double close through a level (failed flip), limit at the level, thrust-candle stop (1 hour) ══════

def cc01(m, B, p, cache):
    b = B[60]
    n = len(b.c)
    lows, highs = E.pivot_points_close(b.c, 3)
    out = []
    for kind, piv in (("R", highs), ("S", lows)):
        for i in piv:
            L = float(b.c[i])
            a = None
            for q in range(i + 4, min(i + 120, n)):
                if kind == "R" and b.c[q] > L:
                    a = q if b.c[q - 1] <= L else None
                    break
                if kind == "S" and b.c[q] < L:
                    a = q if b.c[q - 1] >= L else None
                    break
            if a is None:
                continue
            for z in range(a + 1, min(a + 49, n)):
                back = b.c[z] < L if kind == "R" else b.c[z] > L
                touched = b.l[z] <= L if kind == "R" else b.h[z] >= L
                if not back:
                    if touched:
                        break
                    continue
                rg = rng(b, z)
                strong = rg > 0 and body(b, z) >= 0.6 * rg and (red(b, z) if kind == "R" else green(b, z))
                if strong and z + 1 < n:
                    exp = int(b.i1[min(z + 6, n - 1)])
                    if kind == "R":
                        stop = float(b.h[z])
                        if stop - L < 0.001 * L:
                            stop = float(b.h[max(0, z - 3):z + 1].max())
                        out.append(sig(b, z, -1, stop, "CC01_DOUBLE_CLOSE_SHORT", entry_limit=L, expire_k=exp))
                    else:
                        stop = float(b.l[z])
                        if L - stop < 0.001 * L:
                            stop = float(b.l[max(0, z - 3):z + 1].min())
                        out.append(sig(b, z, 1, stop, "CC01_DOUBLE_CLOSE_LONG", entry_limit=L, expire_k=exp))
                break
    return sorted_out(out)


def cc01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ BN-01 EMA 20/50/100 fanned trend, retest of EMA 20/50 with engulfing or pin bar + Stoch RSI cross (15 min) ═══

def bn01(m, B, p, cache):
    b = B[15]
    cx = ctx(m, B, 15, cache)
    e20, e50, e100 = cx.ema(20), cx.ema(50), cx.ema(100)
    k, dd = Z.stoch_rsi(b.c, 14, 14, 3, 3)
    out = []
    for j in range(3, len(b.c)):
        c = float(b.c[j])
        if not _fin(e20[j], e50[j], e100[j], k[j], dd[j], k[j - 1], dd[j - 1]):
            continue
        for side in (1, -1):
            if side > 0:
                fan = e20[j] > e50[j] > e100[j] and e20[j] - e50[j] >= 0.001 * c and e50[j] - e100[j] >= 0.001 * c
                retest = any((b.l[x] <= e20[x] or b.l[x] <= e50[x]) and (E.engulf(b, x, 1) or E.pin_bar(b, x, 1))
                             for x in (j - 1, j))
                cross = any(_fin(k[y - 1], dd[y - 1]) and k[y - 1] <= dd[y - 1] and k[y] > dd[y] and k[y - 1] < 30
                            and dd[y - 1] < 30 for y in (j - 1, j))
            else:
                fan = e20[j] < e50[j] < e100[j] and e50[j] - e20[j] >= 0.001 * c and e100[j] - e50[j] >= 0.001 * c
                retest = any((b.h[x] >= e20[x] or b.h[x] >= e50[x]) and (E.engulf(b, x, -1) or E.pin_bar(b, x, -1))
                             for x in (j - 1, j))
                cross = any(_fin(k[y - 1], dd[y - 1]) and k[y - 1] >= dd[y - 1] and k[y] < dd[y] and k[y - 1] > 70
                            and dd[y - 1] > 70 for y in (j - 1, j))
            if fan and retest and cross:
                stop = float(b.l[j - 2:j + 1].min()) if side > 0 else float(b.h[j - 2:j + 1].max())
                out.append(sig(b, j, side, stop, "BN01_EMA_FAN_STOCHRSI_" + ("LONG" if side > 0 else "SHORT")))
    return sorted_out(out)


def bn01_x(m, B, p, cache):
    return XExits(target_r=2.5, be_at_r=1.0)


# ═══ TC-01 4-hour breakout, dirty retest back into the pattern, 15-minute break of the retest ════════════════════

def tc01(m, B, p, cache):
    b4, b15 = B[240], B[15]
    a4 = ctx(m, B, 240, cache).atr(14)
    n4, n15 = len(b4.c), len(b15.c)
    out = []
    used_days = set()
    for q in range(13, n4):
        if not np.isfinite(a4[q]):
            continue
        S, R = float(b4.l[q - 12:q].min()), float(b4.h[q - 12:q].max())
        for side in (-1, 1):
            lvl = S if side < 0 else R
            if side < 0 and not (b4.c[q] < S <= b4.c[q - 1]):
                continue
            if side > 0 and not (b4.c[q] > R >= b4.c[q - 1]):
                continue
            r = next((x for x in range(q + 1, min(q + 7, n4))
                      if (b4.l[x] <= S - a4[q] if side < 0 else b4.h[x] >= R + a4[q])), None)
            if r is None:
                continue
            u = next((x for x in range(r + 1, min(r + 13, n4))
                      if (b4.c[x] > S if side < 0 else b4.c[x] < R)), None)
            if u is None or (side < 0 and b4.c[u] >= R) or (side > 0 and b4.c[u] <= S):
                continue
            k0, k1 = int(b4.i1[u]), int(b4.i1[min(u + 12, n4 - 1)])
            j0 = int(np.searchsorted(b15.i1, k0, "right"))
            ext = float(b4.h[u]) if side < 0 else float(b4.l[u])
            for j in range(max(j0, 8), n15):
                if b15.i1[j] > k1:
                    break
                ext = max(ext, float(b15.h[j])) if side < 0 else min(ext, float(b15.l[j]))
                brk = b15.c[j] < b15.l[j - 8:j].min() if side < 0 else b15.c[j] > b15.h[j - 8:j].max()
                if brk:
                    dkey = int(b15.day[j])
                    if dkey not in used_days:
                        used_days.add(dkey)
                        out.append(sig(b15, j, side, ext, "TC01_DIRTY_RETEST_" + ("SHORT" if side < 0 else "LONG")))
                    break
            _ = lvl
    return sorted_out(out)


def tc01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ TC-02 trend day, Asian grind back into the daily pivot, London-open 5-minute breakout to S1/R1 ══════════════

def tc02(m, B, p, cache):
    b = B[5]
    out = []
    for d in range(1, m.n_days):
        a0, z0 = int(m.d0[d - 1]), int(m.d1[d - 1])
        if z0 - a0 < 300:
            continue
        O, H, L, C = float(m.o[a0]), float(m.h[a0:z0].max()), float(m.l[a0:z0].min()), float(m.c[z0 - 1])
        rg = H - L
        if not rg > 0:
            continue
        up = (C - O) >= 0.6 * rg and C >= L + 0.75 * rg
        dn = (O - C) >= 0.6 * rg and C <= L + 0.25 * rg
        if not (up or dn):
            continue
        pv = E.floor_pivots(H, L, C)
        js = _days(b, d)
        asia = [j for j in js if int(b.ny0[j]) >= 1140 or int(b.ny0[j]) < 120]
        if len(asia) < 30:
            continue
        AH, AL = float(b.h[asia].max()), float(b.l[asia].min())
        if not AL <= pv["P"] <= AH:
            continue
        for j in js:
            t = int(b.ny0[j])
            if not 180 <= t < 360:
                continue
            c = float(b.c[j])
            if dn and c < AL:
                stop = max(pv["P"], AH) * 1.0002
                risk = stop - c
                tgt = next((pv[x] for x in ("S1", "S2") if risk > 0 and c - pv[x] >= 2 * risk), None)
                if tgt is not None:
                    out.append(sig(b, j, -1, stop, "TC02_PIVOT_LONDON_SHORT", target_px=float(tgt)))
                break
            if up and c > AH:
                stop = min(pv["P"], AL) * 0.9998
                risk = c - stop
                tgt = next((pv[x] for x in ("R1", "R2") if risk > 0 and pv[x] - c >= 2 * risk), None)
                if tgt is not None:
                    out.append(sig(b, j, 1, stop, "TC02_PIVOT_LONDON_LONG", target_px=float(tgt)))
                break
    return sorted_out(out)


def tc02_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ UK-01 first one-minute candle bracket at the cash open, out at the close of minute five (Nasdaq) ════════════

def uk01(m, B, p, cache):
    b = B[1]
    out = []
    for d in range(m.n_days):
        js = _days(b, d)
        if len(js) < 10 or int(b.ny0[js[0]]) != 9 * 60 + 30:
            continue
        j0 = js[0]
        exp = next((int(b.i1[j]) for j in js if int(b.ny0[j]) == 9 * 60 + 34), None)
        if exp is None:
            continue
        hi, lo = float(b.h[j0]), float(b.l[j0])
        s_long = sig(b, j0, 1, lo, "UK01_FIRST_MINUTE_LONG", entry_stop=hi + 0.25, expire_k=exp)
        s_long.alt = sig(b, j0, -1, hi, "UK01_FIRST_MINUTE_SHORT", entry_stop=lo - 0.25, expire_k=exp)
        out.append(s_long)
    return out


def uk01_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ UK-02 biggest VWAP excursion in 3 sessions, first VWAP test outside the first/last hour, 1/3 stop, 3:1 ════════

def _session_ok(m, b, j) -> bool:
    if m.name == "NAS100":
        return 10 * 60 + 30 <= int(b.ny0[j]) < 15 * 60
    u = E.utc_min(b, j)
    return 60 <= u < 23 * 60


def uk02(m, B, p, cache):
    b = B[15]
    vw = Z.vwap_of(m, b, cache, "15")
    full = {}
    for d in range(m.n_days):
        e = [abs(float(b.c[j] - vw[j])) for j in _days(b, d) if np.isfinite(vw[j])]
        full[d] = max(e) if e else np.nan
    out = []
    for d in range(3, m.n_days):
        prev = [full[d - i] for i in (1, 2, 3)]
        if not all(np.isfinite(x) for x in prev):
            continue
        thr = max(prev)
        js = _days(b, d)
        armed = 0
        for idx, j in enumerate(js):
            if not np.isfinite(vw[j]):
                continue
            dev = float(b.c[j] - vw[j])
            if not armed and abs(dev) > thr:
                armed = 1 if dev > 0 else -1
            if not armed or idx + 1 >= len(js) or not _session_ok(m, b, j):
                continue
            L = float(vw[j])
            if (b.c[j] - L) * armed <= 0:
                break
            ext = float(b.h[js[0]:j + 1].max()) if armed > 0 else float(b.l[js[0]:j + 1].min())
            stop = L - armed * abs(ext - L) / 3
            out.append(sig(b, j, armed, stop, "UK02_VWAP_PULLBACK_" + ("LONG" if armed > 0 else "SHORT"),
                           entry_limit=L, expire_k=int(b.i1[js[idx + 1]]), target_px=ext, info={"group": f"{d}"}))
    return sorted_out(out)


def uk02_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ AF-01 early drive away from VWAP on a gap day, buy the first VWAP test, exit at a new high (Nasdaq) ═════════════

def af01(m, B, p, cache):
    b = B[5]
    vw = Z.vwap_of(m, b, cache, "5")
    out = []
    for d in range(1, m.n_days):
        pc = Z.prev_close(m, d)
        js = _days(b, d)
        if not (pc > 0 and len(js) > 8) or int(b.ny0[js[0]]) != 9 * 60 + 30:
            continue
        gap = float(b.o[js[0]]) / pc - 1
        if abs(gap) < 0.003:
            continue
        side = 1 if gap > 0 else -1
        early = [j for j in js if int(b.ny0[j]) < 10 * 60 - 5]
        if not any(np.isfinite(vw[j]) and (b.c[j] - vw[j]) * side >= 0.004 * b.c[j] for j in early):
            continue
        for idx, j in enumerate(js):
            t = int(b.ny0[j])
            if t < 10 * 60 - 5 or not np.isfinite(vw[j]):
                continue
            if t >= 15 * 60 + 30 or idx + 1 >= len(js):
                break
            L = float(vw[j])
            if (b.c[j] - L) * side <= 0:
                break
            ext = float(b.h[js[0]:j + 1].max()) if side > 0 else float(b.l[js[0]:j + 1].min())
            out.append(sig(b, j, side, L * (1 - side * 0.0025), "AF01_GAP_DAY_VWAP_" + ("LONG" if side > 0 else "SHORT"),
                           entry_limit=L, expire_k=int(b.i1[js[idx + 1]]), target_px=ext, info={"group": f"{d}"}))
    return sorted_out(out)


def af01_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ MA-01 one-minute impulse that breaks structure, limit at the 0.618, stop past the origin, target the end (FX) ═══

def ma01(m, B, p, cache):
    b = B[1]
    h, l, c = b.h, b.l, b.c
    n, N = len(c), 5
    ph = np.zeros(n, bool)
    pl = np.zeros(n, bool)
    for i in range(N, n - N):
        w = h[i - N:i + N + 1]
        if h[i] == w.max() and int(np.sum(w == h[i])) == 1:
            ph[i] = True
        w = l[i - N:i + N + 1]
        if l[i] == w.min() and int(np.sum(w == l[i])) == 1:
            pl[i] = True
    out = []
    sh = sl = None
    pend_up = pend_dn = None
    for j in range(N + 1, n):
        if b.day[j] != b.day[j - 1]:
            sh = sl = pend_up = pend_dn = None
        i = j - N
        t = int(b.ny0[j])
        win = 180 <= t < 900
        if ph[i] and b.day[i] == b.day[j]:
            if pend_up is not None and i >= pend_up[0] and win:
                H, origin = float(h[i]), pend_up[1]
                if H > origin:
                    lvl = H - 0.618 * (H - origin)
                    out.append(sig(b, j, 1, origin * (1 - 0.0002), "MA01_FIB618_LONG", entry_limit=lvl,
                                   expire_k=int(b.i1[min(j + 30, n - 1)]), target_px=H))
                pend_up = None
            sh = float(h[i])
        if pl[i] and b.day[i] == b.day[j]:
            if pend_dn is not None and i >= pend_dn[0] and win:
                Lo, origin = float(l[i]), pend_dn[1]
                if Lo < origin:
                    lvl = Lo + 0.618 * (origin - Lo)
                    out.append(sig(b, j, -1, origin * (1 + 0.0002), "MA01_FIB618_SHORT", entry_limit=lvl,
                                   expire_k=int(b.i1[min(j + 30, n - 1)]), target_px=Lo))
                pend_dn = None
            sl = float(l[i])
        if sh is not None and sl is not None:
            if pend_up is None and c[j] > sh >= c[j - 1]:
                pend_up = (j, sl)
            if pend_dn is None and c[j] < sl <= c[j - 1]:
                pend_dn = (j, sh)
    return sorted_out(out)


def ma01_x(m, B, p, cache):
    return XExits(target_r=None)


# ═══ RU-05 RSI through 70 (30) with Supertrend agreeing; RU-06 zero-lag MACD in the EMA 200 trend (30 minutes) ═══

def ru05(m, B, p, cache):
    b = B[30]
    cx = ctx(m, B, 30, cache)
    r = cx.rsi(14)
    line, dirn = cx.supertrend(10, 3.0)
    out = []
    for j in range(1, len(b.c)):
        if not _fin(r[j], r[j - 1], line[j]):
            continue
        if r[j - 1] <= 70 < r[j] and dirn[j] > 0 and line[j] < b.c[j]:
            out.append(sig(b, j, 1, float(line[j]), "RU05_RSI70_ST_LONG"))
        elif r[j - 1] >= 30 > r[j] and dirn[j] < 0 and line[j] > b.c[j]:
            out.append(sig(b, j, -1, float(line[j]), "RU05_RSI30_ST_SHORT"))
    return out


def ru05_x(m, B, p, cache):
    return XExits(target_r=1.5)


def ru06(m, B, p, cache):
    b = B[30]
    key = ("ze_zlmacd", 30)
    if key not in cache:
        cache[key] = E.zl_macd(b.c, 12, 26, 9)
    ml, sl = cache[key]
    e200 = ctx(m, B, 30, cache).ema(200)
    out = []
    for j in range(11, len(b.c)):
        if not _fin(ml[j], sl[j], ml[j - 1], sl[j - 1], e200[j]):
            continue
        if ml[j - 1] <= sl[j - 1] and ml[j] > sl[j] and ml[j] < 0 and sl[j] < 0 and b.l[j] > e200[j]:
            out.append(sig(b, j, 1, float(b.l[j - 10:j].min()), "RU06_ZLMACD_LONG"))
        elif ml[j - 1] >= sl[j - 1] and ml[j] < sl[j] and ml[j] > 0 and sl[j] > 0 and b.h[j] < e200[j]:
            out.append(sig(b, j, -1, float(b.h[j - 10:j].max()), "RU06_ZLMACD_SHORT"))
    return out


def ru06_x(m, B, p, cache):
    return XExits(target_r=1.5)


# ═══ NK-01 close outside the Bollinger Band (20, 2), stop at the middle line, 2R (1 hour) ═════════════════════════════

def nk01(m, B, p, cache):
    b = B[60]
    mid, up, lo = ctx(m, B, 60, cache).bollinger(20, 2.0)
    out = []
    for j in range(1, len(b.c)):
        if not _fin(mid[j], up[j], lo[j]):
            continue
        if b.c[j] > up[j] and b.c[j - 1] <= up[j - 1]:
            out.append(sig(b, j, 1, float(mid[j]), "NK01_BB_BREAKOUT_LONG"))
        elif b.c[j] < lo[j] and b.c[j - 1] >= lo[j - 1]:
            out.append(sig(b, j, -1, float(mid[j]), "NK01_BB_BREAKOUT_SHORT"))
    return out


def nk01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ KA-01 break of the previous hour/day high or low after a staircase approach, two closes, swing stop, 1R ══════

def ka01(m, B, p, cache):
    b, bh = B[15], B[60]
    cx = ctx(m, B, 15, cache)
    s30 = cx.sma(30)
    vol = cx.vol()
    out = []
    for d in range(1, m.n_days):
        pd = Z.prev_day_hl(m, d)
        if not pd:
            continue
        js = _days(b, d)
        for j in js:
            if j < 31 or b.day[j - 2] != d:
                continue
            kh = last_done(bh, int(b.i1[j - 1]))
            if kh < 0 or not np.isfinite(s30[j]):
                continue
            above = np.sign(b.c[j - 29:j + 1] - s30[j - 29:j + 1])
            if not np.all(np.isfinite(above)) or int(np.sum(above[1:] != above[:-1])) > 1:
                continue
            if not np.mean(vol[j - 4:j + 1]) > np.mean(vol[j - 19:j + 1]):
                continue
            for side, levels in ((1, (float(bh.h[kh]), pd[0])), (-1, (float(bh.l[kh]), pd[1]))):
                hit = False
                for Lv in levels:
                    if side > 0 and b.c[j - 2] <= Lv < b.c[j - 1] and b.c[j] > Lv:
                        hit = int(np.sum(b.l[j - 6:j - 1] > b.l[j - 7:j - 2])) >= 4
                    elif side < 0 and b.c[j - 2] >= Lv > b.c[j - 1] and b.c[j] < Lv:
                        hit = int(np.sum(b.h[j - 6:j - 1] < b.h[j - 7:j - 2])) >= 4
                    if hit:
                        break
                if hit:
                    stop = float(b.l[j - 5:j + 1].min()) if side > 0 else float(b.h[j - 5:j + 1].max())
                    out.append(sig(b, j, side, stop, "KA01_LEVEL_BREAK_" + ("LONG" if side > 0 else "SHORT")))
    return sorted_out(out)


def ka01_x(m, B, p, cache):
    return XExits(target_r=1.0)
