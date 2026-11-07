"""The runnable strategies of specs/PREREGISTRATION.md (YT-01 .. YT-27). Signals use completed bars only and
are stamped with the signal bar's last row; orders start on the next row (yt_engine)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import yt_ind as I
from yt_engine import Exits, Limits, Signal
from yt_markets import Bars, bars as make_bars, ema, rsi, sma

NIFTY_X = ("ist", 15 * 60 + 14)
FX_X = ("ny", 16 * 60 + 55)
END_X = ("end", 0)


def green(b, j): return b.c[j] > b.o[j]
def red(b, j): return b.c[j] < b.o[j]
def rng(b, j): return b.h[j] - b.l[j]
def body(b, j): return abs(b.c[j] - b.o[j])
def uw(b, j): return b.h[j] - max(b.o[j], b.c[j])
def lw(b, j): return min(b.o[j], b.c[j]) - b.l[j]


def pclose(m, d):
    return float(m.c[m.d1[d - 1] - 1]) if d > 0 else float(m.o[m.d0[d]])


def pip(m):
    return 0.0001 if m.name in ("EURUSD", "GBPUSD") else (0.1 if m.name == "XAUUSD" else 1.0)


def win_ist(b, j, lo, hi):
    return lo <= b.ist0[j] < hi


def bars_ok_fx(m, b, j):
    """24-hour markets: skip the session's first evening hour after the daily break."""
    return not (m.name in ("XAUUSD", "EURUSD", "GBPUSD") and 17 * 60 <= b.ny0[j] < 18 * 60 + 30)


def end_of_bar_row(b, j):
    return int(b.i1[j])


# ── YT-01 5 EMA alert candle ──────────────────────────────────────────────────────────

def yt01(m, B, p):
    out = []
    for tf, side in ((5, -1), (15, 1)) if not p.get("both5") else ((5, -1), (5, 1)):
        b = B[tf]
        e = ema(b.c, 5)
        for j in range(1, len(b.c) - 1):
            if b.day[j + 1] != b.day[j] or not (9 * 60 + 15 <= b.ist0[j] and b.ist0[j + 1] <= 14 * 60 + 55):
                continue
            if side < 0 and b.l[j] > e[j]:            # whole candle above the 5 EMA
                out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.h[j]), "5EMA_SELL",
                                  entry_stop=float(b.l[j]), expire_k=int(b.i1[j + 1])))
            elif side > 0 and b.h[j] < e[j]:          # whole candle below the 5 EMA
                out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.l[j]), "5EMA_BUY",
                                  entry_stop=float(b.h[j]), expire_k=int(b.i1[j + 1])))
    out.sort(key=lambda s: s.k)
    return out


# ── YT-02 market-structure pullback (4h trend, 1h trade, ATR stop) ────────────────────

def _trend_4h(b4: Bars):
    up, dn = I.fractals(b4, 2)
    tr = np.zeros(len(b4.c), int)
    sh, sl = [], []
    for j in range(len(b4.c)):
        q = j - 2
        if q >= 2:
            if up[q]: sh.append(b4.h[q])
            if dn[q]: sl.append(b4.l[q])
        if len(sh) >= 2 and len(sl) >= 2:
            tr[j] = 1 if (sh[-1] > sh[-2] and sl[-1] > sl[-2]) else -1 if (sh[-1] < sh[-2] and sl[-1] < sl[-2]) else 0
    return tr


def yt02(m, B, p):
    b, b4 = B[60], B[240]
    tr4 = _trend_4h(b4)
    a = I.atr(b, 14)
    up, dn = I.fractals(b, 2)
    out = []
    zone = None          # (side, zone_lo, zone_hi, broken_j, pullback_extreme)
    last_sh = last_sl = None
    j4 = 0
    for j in range(3, len(b.c)):
        while j4 + 1 < len(b4.c) and b4.i1[j4 + 1] < b.i0[j]:
            j4 += 1
        t4 = tr4[j4] if b4.i1[j4] < b.i0[j] else 0
        q = j - 2
        if up[q]: last_sh = (q, b.h[q], max(b.o[q], b.c[q]))
        if dn[q]: last_sl = (q, b.l[q], min(b.o[q], b.c[q]))
        if zone is None:
            if t4 > 0 and last_sh and b.c[j] > last_sh[1]:
                zone = [1, last_sh[2], last_sh[1], j, b.l[j]]
                last_sh = None
            elif t4 < 0 and last_sl and b.c[j] < last_sl[1]:
                zone = [-1, last_sl[1], last_sl[2], j, b.h[j]]
                last_sl = None
            continue
        side, zlo, zhi, bj, ext = zone
        if j - bj > 30:
            zone = None
            continue
        if side > 0:
            zone[4] = min(ext, b.l[j])
            if b.c[j] < zlo:
                zone = None
                continue
            if b.l[j] <= zhi and green(b, j) and bars_ok_fx(m, b, j) and np.isfinite(a[j]):
                out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(zone[4] - a[j]), "MS_PULLBACK"))
                zone = None
        else:
            zone[4] = max(ext, b.h[j])
            if b.c[j] > zhi:
                zone = None
                continue
            if b.h[j] >= zlo and red(b, j) and bars_ok_fx(m, b, j) and np.isfinite(a[j]):
                out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(zone[4] + a[j]), "MS_PULLBACK"))
                zone = None
    return out


# ── YT-03 50 MA double bottom / top ───────────────────────────────────────────────────

def yt03(m, B, p):
    b = B[60]
    ma = sma(b.c, 50)
    a = I.atr(b, 14)
    up, dn = I.fractals(b, 3)
    out = []
    lows, highs = [], []
    armed = None
    for j in range(4, len(b.c)):
        q = j - 3
        if dn[q]: lows.append(q)
        if up[q]: highs.append(q)
        if not np.isfinite(ma[j]) or not np.isfinite(a[j]):
            continue
        if dn[q] and len(lows) >= 2:
            q1, q2 = lows[-2], lows[-1]
            if 5 <= q2 - q1 <= 40 and abs(b.l[q1] - b.l[q2]) <= 0.25 * a[q2] and \
                    (b.l[q1] <= ma[q1] or b.l[q2] <= ma[q2]) and b.c[q2] > ma[q2] - 0.5 * a[q2]:
                armed = (1, j, min(b.l[q1], b.l[q2]))
        if up[q] and len(highs) >= 2:
            q1, q2 = highs[-2], highs[-1]
            if 5 <= q2 - q1 <= 40 and abs(b.h[q1] - b.h[q2]) <= 0.25 * a[q2] and \
                    (b.h[q1] >= ma[q1] or b.h[q2] >= ma[q2]) and b.c[q2] < ma[q2] + 0.5 * a[q2]:
                armed = (-1, j, max(b.h[q1], b.h[q2]))
        if armed is None or j - armed[1] > 10:
            continue
        side, _, ext = armed
        if side > 0 and green(b, j) and b.c[j] > ma[j] and bars_ok_fx(m, b, j):
            out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(ext - 0.1 * a[j]), "MA50_DOUBLE_BOTTOM"))
            armed = None
        elif side < 0 and red(b, j) and b.c[j] < ma[j] and bars_ok_fx(m, b, j):
            out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(ext + 0.1 * a[j]), "MA50_DOUBLE_TOP"))
            armed = None
    return out


# ── YT-04 ICT Silver Bullet ───────────────────────────────────────────────────────────

SB_WINDOWS = ((3 * 60, 4 * 60), (10 * 60, 11 * 60), (14 * 60, 15 * 60))


def yt04(m, B, p):
    b = B[1]
    minroom = 15 * pip(m) if m.name in ("EURUSD", "GBPUSD") else 10.0
    out = []
    for d in range(m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        hi_so_far, lo_so_far = -np.inf, np.inf
        used = set()
        for j in range(s0, s1):
            w = next((i for i, (a_, z_) in enumerate(SB_WINDOWS) if a_ <= b.ny0[j] < z_), None)
            if w is not None and w not in used and j - 2 >= s0:
                end_j = next((x for x in range(j, s1) if b.ny0[x] >= SB_WINDOWS[w][1]), s1 - 1)
                if b.l[j] > b.h[j - 2] and hi_so_far - b.h[j - 2] >= minroom:            # bullish FVG, room up
                    out.append(Signal(d, int(b.i1[j]), 1, float(b.l[j - 2]), "SILVER_BULLET",
                                      entry_limit=float(b.l[j]), expire_k=int(b.i1[end_j]), target_px=float(hi_so_far)))
                    used.add(w)
                elif b.h[j] < b.l[j - 2] and b.l[j - 2] - lo_so_far >= minroom:          # bearish FVG, room down
                    out.append(Signal(d, int(b.i1[j]), -1, float(b.h[j - 2]), "SILVER_BULLET",
                                      entry_limit=float(b.h[j]), expire_k=int(b.i1[end_j]), target_px=float(lo_so_far)))
                    used.add(w)
            hi_so_far, lo_so_far = max(hi_so_far, b.h[j]), min(lo_so_far, b.l[j])
    return out


# ── YT-05 ICT Judas swing ─────────────────────────────────────────────────────────────

def yt05(m, B, p):
    b = B[5]
    dc = m.c[m.d1 - 1]
    ma20 = sma(dc, 20)
    out = []
    for d in range(21, m.n_days):
        if not np.isfinite(ma20[d - 1]):
            continue
        bias = 1 if dc[d - 1] > ma20[d - 1] else -1
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        asia = [j for j in range(s0, s1) if b.ny0[j] >= 19 * 60]
        mid = next((j for j in range(s0, s1) if b.ny0[j] == 0), None)
        if len(asia) < 30 or mid is None:
            continue
        ah, al = max(b.h[j] for j in asia), min(b.l[j] for j in asia)
        mo = b.o[mid]
        took_hi = took_lo = False
        ext_lo, ext_hi = np.inf, -np.inf
        for j in range(mid, s1):
            if b.ny0[j] >= 5 * 60:
                break
            ext_lo, ext_hi = min(ext_lo, b.l[j]), max(ext_hi, b.h[j])
            if bias > 0:
                took_hi |= b.h[j] > ah
                if took_hi and ext_lo < min(mo, al) and b.c[j] > al:
                    out.append(Signal(d, int(b.i1[j]), 1, float(ext_lo - 10 * pip(m)), "JUDAS_BULL"))
                    break
            else:
                took_lo |= b.l[j] < al
                if took_lo and ext_hi > max(mo, ah) and b.c[j] < ah:
                    out.append(Signal(d, int(b.i1[j]), -1, float(ext_hi + 10 * pip(m)), "JUDAS_BEAR"))
                    break
    return out


# ── YT-06 ICT OTE 62% (08:30-11:00 New York) ──────────────────────────────────────────

def yt06(m, B, p):
    b = B[5]
    out = []
    for d in range(m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        idx = [j for j in range(s0, s1) if 0 <= b.ny0[j] < 8 * 60 + 30]
        start = next((j for j in range(s0, s1) if b.ny0[j] == 8 * 60 + 30), None)
        if len(idx) < 60 or start is None:
            continue
        # search forward from 08:30: the session's first evening (after 17:00 New York) also has ny0 >= 11:00
        end = next((j for j in range(start, s1) if b.ny0[j] >= 11 * 60), s1 - 1)
        hj = max(idx, key=lambda j: b.h[j])
        lj = min(idx, key=lambda j: b.l[j])
        H, L = b.h[hj], b.l[lj]
        span = H - L
        if span <= 0:
            continue
        if lj < hj:                                    # bullish leg: buy the 62% retracement
            entry = H - 0.62 * span
            tgt = H + 0.5 * span
            if tgt - entry >= 15 * pip(m):
                out.append(Signal(d, int(b.i1[start - 1]), 1, float(L - 2 * pip(m)), "OTE62",
                                  entry_limit=float(entry), expire_k=int(b.i1[end]), target_px=float(tgt)))
        elif hj < lj:
            entry = L + 0.62 * span
            tgt = L - 0.5 * span
            if entry - tgt >= 15 * pip(m):
                out.append(Signal(d, int(b.i1[start - 1]), -1, float(H + 2 * pip(m)), "OTE62",
                                  entry_limit=float(entry), expire_k=int(b.i1[end]), target_px=float(tgt)))
    return out


# ── YT-07 Connors RSI(10) pullback (daily) ────────────────────────────────────────────

def yt07(m, B, p):
    b = B[1]
    ma = sma(b.c, 200)
    r = I.rma(np.maximum(np.diff(b.c, prepend=b.c[0]), 0), 10)
    dn = I.rma(np.maximum(-np.diff(b.c, prepend=b.c[0]), 0), 10)
    with np.errstate(divide="ignore", invalid="ignore"):
        R = 100 - 100 / (1 + r / dn)
    a = I.atr(b, 14)
    out = []
    for j in range(201, len(b.c) - 1):
        if np.isfinite(ma[j]) and np.isfinite(R[j]) and b.c[j] > ma[j] and R[j] < 30 and np.isfinite(a[j]):
            stop = b.c[j] - (2 if p.get("stop") else 30) * a[j]
            out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(stop), "CONNORS_RSI10",
                              info={"risk_unit": float(2 * a[j])}))
    return out


def yt07_exit(m, B):
    b = B[1]
    r = I.rma(np.maximum(np.diff(b.c, prepend=b.c[0]), 0), 10)
    dn = I.rma(np.maximum(-np.diff(b.c, prepend=b.c[0]), 0), 10)
    with np.errstate(divide="ignore", invalid="ignore"):
        R = 100 - 100 / (1 + r / dn)
    xl = R > 40
    return b, xl, np.zeros(len(xl), bool)


# ── YT-08 inside candle (15m) ─────────────────────────────────────────────────────────

def yt08(m, B, p):
    b = B[15]
    R = b.h - b.l
    cs = np.cumsum(np.r_[0.0, R])
    mother_break = p.get("entry") == "mother"
    out = []
    for j in range(21, len(b.c) - 1):
        if b.day[j] != b.day[j - 1] or not (9 * 60 + 30 <= b.ist0[j] <= 14 * 60 + 30):
            continue
        mo = j - 1
        mean20 = (cs[mo] - cs[mo - 20]) / 20
        if not (R[mo] >= mean20 and b.h[j] <= b.h[mo] and b.l[j] >= b.l[mo]):
            continue
        last = min(j + 4, int(b.b1[b.day[j]]) - 1)
        span = R[mo]
        lo_t, hi_t = (b.l[mo], b.h[mo]) if mother_break else (b.l[j], b.h[j])
        short = Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.h[j]), "INSIDE_CANDLE", entry_stop=float(lo_t),
                       expire_k=int(b.i1[last]), target_px=None if p.get("t2r") else float(lo_t - span))
        long = Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.l[j]), "INSIDE_CANDLE", entry_stop=float(hi_t),
                      expire_k=int(b.i1[last]), target_px=None if p.get("t2r") else float(hi_t + span))
        long.alt = short
        out.append(long)
    return out


# ── YT-09 traffic light (1m pair breakout) ────────────────────────────────────────────

def yt09(m, B, p):
    tf = p.get("tf", 1)
    b = B[tf]
    out = []
    for d in range(1, m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        start = s0 + (1 if tf == 1 else 0)
        px = pclose(m, d)
        for j in range(start + 1, s1):
            if b.ist0[j] > 14 * 60 + 45:
                break
            if (green(b, j - 1) and red(b, j)) or (red(b, j - 1) and green(b, j)):
                H, L = max(b.h[j - 1], b.h[j]), min(b.l[j - 1], b.l[j])
                if H - L > 0.002 * px:
                    continue
                last = next((x for x in range(j, s1) if b.ist0[x] >= 15 * 60), s1 - 1)
                lg = Signal(d, int(b.i1[j]), 1, float(L), "TRAFFIC_LIGHT", entry_stop=float(H), expire_k=int(b.i1[last]))
                lg.alt = Signal(d, int(b.i1[j]), -1, float(H), "TRAFFIC_LIGHT", entry_stop=float(L), expire_k=int(b.i1[last]))
                out.append(lg)
                break
    return out


# ── YT-10 gap day + shooting star / hammer first candle ───────────────────────────────

def yt10(m, B, p):
    tf = p.get("tf", 15)
    b = B[tf]
    out = []
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        px = pclose(m, d)
        gap = b.o[s0] / px - 1
        j = s0
        r = rng(b, j)
        if r <= 0:
            continue
        last = next((x for x in range(j, s1) if b.ist0[x] >= 11 * 60), s1 - 1)
        if gap >= 0.005 and uw(b, j) >= 2 * body(b, j) and lw(b, j) <= 0.25 * r:
            out.append(Signal(d, int(b.i1[j]), -1, float(b.h[j]), "GAP_SHOOTING_STAR", entry_stop=float(b.l[j]),
                              expire_k=int(b.i1[last])))
        elif gap <= -0.005 and lw(b, j) >= 2 * body(b, j) and uw(b, j) <= 0.25 * r:
            out.append(Signal(d, int(b.i1[j]), 1, float(b.l[j]), "GAP_HAMMER", entry_stop=float(b.h[j]),
                              expire_k=int(b.i1[last])))
    return out


# ── YT-11 momentum loss into a 4h swing level ─────────────────────────────────────────

def yt11(m, B, p):
    b, b4 = B[60], B[240]
    a = I.atr(b, 14)
    up4, dn4 = I.fractals(b4, 2)
    out = []
    j4 = 0
    levels_hi, levels_lo = [], []
    for j in range(4, len(b.c)):
        while j4 + 1 < len(b4.c) and b4.i1[j4 + 1] < b.i0[j]:
            j4 += 1
            q = j4 - 2
            if q >= 2:
                if up4[q]: levels_hi = (levels_hi + [b4.h[q]])[-6:]
                if dn4[q]: levels_lo = (levels_lo + [b4.l[q]])[-6:]
        if not np.isfinite(a[j]) or not bars_ok_fx(m, b, j):
            continue
        shrinking = rng(b, j - 3) > rng(b, j - 2) > rng(b, j - 1)
        if not shrinking or rng(b, j) <= 0:
            continue
        for L in levels_lo:
            if b.c[j - 3] > b.c[j - 1] > L and b.l[j] <= L + 0.1 * a[j] and b.c[j] > L and lw(b, j) >= 0.5 * rng(b, j):
                out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.l[j] - 0.1 * a[j]), "MOMENTUM_LOSS"))
                break
        else:
            for H in levels_hi:
                if b.c[j - 3] < b.c[j - 1] < H and b.h[j] >= H - 0.1 * a[j] and b.c[j] < H and uw(b, j) >= 0.5 * rng(b, j):
                    out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.h[j] + 0.1 * a[j]), "MOMENTUM_LOSS"))
                    break
    return out


# ── YT-12a 44 SMA bullish candle (daily stocks) ───────────────────────────────────────

def yt12a(m, B, p):
    b = B[1]
    ma = sma(b.c, 44)
    out = []
    liq = getattr(m, "liquid", np.ones(len(b.c), bool))
    for j in range(50, len(b.c) - 1):
        if not liq[j] or not np.isfinite(ma[j]) or ma[j] <= ma[j - 5]:
            continue
        if green(b, j) and b.l[j] <= ma[j] * 1.01 and b.c[j] > ma[j]:
            out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.l[j]), "SMA44", entry_stop=float(b.h[j]),
                              expire_k=int(b.i1[j + 1])))
    return out


# ── YT-12b 44 SMA + big green opening candle (15m stocks) ─────────────────────────────

def yt12b(m, B, p):
    b = B[15]
    dc = m.c[m.d1 - 1]
    ma = sma(dc, 44)
    R = b.h - b.l
    cs = np.cumsum(np.r_[0.0, R])
    out = []
    for d in range(45, m.n_days):
        if not (np.isfinite(ma[d - 1]) and ma[d - 1] > ma[d - 6] and abs(dc[d - 1] / ma[d - 1] - 1) <= 0.02):
            continue
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        if s0 < 600:
            continue
        mean_r = (cs[s0] - cs[s0 - 500]) / 500        # about 20 sessions of 15-minute bars
        for j in (s0, s0 + 1):
            if j >= s1:
                break
            if green(b, j) and R[j] >= 1.5 * mean_r and body(b, j) >= 0.5 * R[j]:
                last = next((x for x in range(j, s1) if b.ist0[x] >= 11 * 60), s1 - 1)
                out.append(Signal(d, int(b.i1[j]), 1, float(b.l[j]), "SMA44_BIG_GREEN", entry_stop=float(b.h[j]),
                                  expire_k=int(b.i1[last])))
                break
    return out


# ── YT-13 daily bear/bull trap ────────────────────────────────────────────────────────

def yt13(m, B, p):
    b = B[1]
    R = b.h - b.l
    cs = np.cumsum(np.r_[0.0, R])
    liq = getattr(m, "liquid", np.ones(len(b.c), bool))
    longs_only = p.get("longs_only", False)
    out = []
    for j in range(22, len(b.c) - 1):
        if not liq[j]:
            continue
        mean20 = (cs[j] - cs[j - 20]) / 20
        prev = j - 1
        lo20 = b.c[prev - 20:prev].min()
        hi20 = b.c[prev - 20:prev].max()
        big = R[j] >= 1.5 * mean20
        if b.c[prev] < lo20 and big and green(b, j):
            out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.l[j]), "BEAR_TRAP", entry_stop=float(b.h[j]),
                              expire_k=int(b.i1[j + 1])))
        elif not longs_only and b.c[prev] > hi20 and big and red(b, j):
            out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.h[j]), "BULL_TRAP", entry_stop=float(b.l[j]),
                              expire_k=int(b.i1[j + 1])))
    return out


# ── YT-14 MA fan + engulfing / three-line strike + RSI 50 ─────────────────────────────

def yt14(m, B, p):
    b = B[5]
    m21, m50, m200 = I.rma(b.c, 21), I.rma(b.c, 50), I.rma(b.c, 200)
    R = rsi(b.c, 14)
    out = []
    for j in range(205, len(b.c)):
        if b.day[j] != b.day[j - 3] or not bars_ok_fx(m, b, j):
            continue
        up = m21[j] > m50[j] > m200[j] and m21[j] > m21[j - 5] and m50[j] > m50[j - 5] and m200[j] > m200[j - 5] and b.c[j] > m200[j]
        dn = m21[j] < m50[j] < m200[j] and m21[j] < m21[j - 5] and m50[j] < m50[j - 5] and m200[j] < m200[j - 5] and b.c[j] < m200[j]
        L = rng(b, j)
        if L <= 0:
            continue
        if up and R[j] > 50 and R[j] > R[j - 1]:
            eng = green(b, j) and red(b, j - 1) and b.o[j] <= b.c[j - 1] and b.c[j] >= b.o[j - 1]
            tls = green(b, j) and red(b, j - 1) and red(b, j - 2) and red(b, j - 3) and b.c[j] > b.o[j - 3]
            if eng or tls:
                out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.c[j] - 2 * L), "TLS" if tls else "ENGULF"))
        elif dn and R[j] < 50 and R[j] < R[j - 1]:
            eng = red(b, j) and green(b, j - 1) and b.o[j] >= b.c[j - 1] and b.c[j] <= b.o[j - 1]
            tls = red(b, j) and green(b, j - 1) and green(b, j - 2) and green(b, j - 3) and b.c[j] < b.o[j - 3]
            if eng or tls:
                out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.c[j] + 2 * L), "TLS" if tls else "ENGULF"))
    return out


# ── YT-15 MA alignment + Williams fractal, 10 pips ────────────────────────────────────

def yt15(m, B, p):
    b = B[5]
    m21, m50, m200 = I.rma(b.c, 21), I.rma(b.c, 50), I.rma(b.c, 200)
    R = rsi(b.c, 14)
    up, dn = I.fractals(b, 2)
    out = []
    for j in range(205, len(b.c)):
        q = j - 2
        if b.day[j] != b.day[q] or not bars_ok_fx(m, b, j):
            continue
        aligned_up = m21[j] > m50[j] > m200[j] and b.c[j] > m21[j] and m200[j] > m200[j - 5]
        aligned_dn = m21[j] < m50[j] < m200[j] and b.c[j] < m21[j] and m200[j] < m200[j - 5]
        if dn[q] and aligned_up and R[j] > 50:
            out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.l[q] - 0.2 * pip(m)), "FRACTAL"))
        elif up[q] and aligned_dn and R[j] < 50:
            out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.h[q] + 0.2 * pip(m)), "FRACTAL"))
    return out


# ── YT-16 MA pullback + engulfing / pin bar, 1:2 ──────────────────────────────────────

def yt16(m, B, p):
    tf = p.get("tf", 60)
    b = B[tf]
    m50, m150 = sma(b.c, 50), sma(b.c, 150)
    a = I.atr(b, 14)
    out = []
    for j in range(156, len(b.c)):
        if not (np.isfinite(m150[j]) and np.isfinite(a[j])) or not bars_ok_fx(m, b, j):
            continue
        L = rng(b, j)
        if L <= 0:
            continue
        if m50[j] > m150[j] and m50[j] > m50[j - 5] and b.l[j] <= m50[j] < b.c[j]:
            eng = green(b, j) and red(b, j - 1) and b.o[j] <= b.c[j - 1] and b.c[j] >= b.o[j - 1]
            pin = lw(b, j) >= 2 * body(b, j) and uw(b, j) <= max(body(b, j), 0.1 * L)
            if eng or pin:
                out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.l[j] - 0.1 * a[j]), "MA_PULLBACK"))
        elif m50[j] < m150[j] and m50[j] < m50[j - 5] and b.h[j] >= m50[j] > b.c[j]:
            eng = red(b, j) and green(b, j - 1) and b.o[j] >= b.c[j - 1] and b.c[j] <= b.o[j - 1]
            pin = uw(b, j) >= 2 * body(b, j) and lw(b, j) <= max(body(b, j), 0.1 * L)
            if eng or pin:
                out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.h[j] + 0.1 * a[j]), "MA_PULLBACK"))
    return out


# ── YT-17 breakout, pullback, continuation (5m) ───────────────────────────────────────

def yt17(m, B, p):
    b = B[5]
    out = []
    for d in range(m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        if s1 - s0 < 7:                               # the 6-bar range must be complete (no day-length look-ahead)
            continue
        H, L = b.h[s0:s0 + 6].max(), b.l[s0:s0 + 6].min()
        state = 0
        for j in range(s0 + 6, s1):
            if b.ist0[j] > 14 * 60 + 30:
                break
            if state == 0:
                state = 1 if b.c[j] > H else -1 if b.c[j] < L else 0
                continue
            if state > 0 and red(b, j):
                last = min(j + 3, s1 - 1)
                out.append(Signal(d, int(b.i1[j]), 1, float(b.l[j]), "BREAKOUT_PULLBACK", entry_stop=float(b.h[j]),
                                  expire_k=int(b.i1[last])))
                break
            if state < 0 and green(b, j):
                last = min(j + 3, s1 - 1)
                out.append(Signal(d, int(b.i1[j]), -1, float(b.h[j]), "BREAKOUT_PULLBACK", entry_stop=float(b.l[j]),
                                  expire_k=int(b.i1[last])))
                break
    return out


# ── YT-18 Heikin-Ashi colour change + RSI 50 ──────────────────────────────────────────

def yt18(m, B, p):
    tf = p.get("tf", 15)
    b = B[tf]
    ho, hc = I.heikin_ashi(b)
    g = hc > ho
    R = rsi(b.c, 14)
    a = I.atr(b, 14)
    out = []
    for j in range(20, len(b.c)):
        if not bars_ok_fx(m, b, j) or not np.isfinite(a[j]):
            continue
        if g[j] and not g[j - 1] and R[j] > 50:
            out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.l[j] - 0.1 * a[j]), "HA_RSI"))
        elif not g[j] and g[j - 1] and R[j] < 50:
            out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.h[j] + 0.1 * a[j]), "HA_RSI"))
    return out


def yt18_exit(m, B, tf):
    b = B[tf]
    ho, hc = I.heikin_ashi(b)
    g = hc > ho
    return b, ~g, g          # exit longs on a red HA bar, shorts on a green one


# ── YT-19 Supertrend(10,3) direction at 09:20 (futures proxy) ─────────────────────────

def yt19(m, B, p):
    b = B[5]
    line, dirn = I.supertrend(b, 10, 3.0)
    out = []
    for d in range(m.n_days):
        j = int(b.b0[d])
        if j >= int(b.b1[d]) or not np.isfinite(line[j]):
            continue
        side = int(dirn[j])
        out.append(Signal(d, int(b.i1[j]), side, float(line[j]), "SUPERTREND_0920"))
    return out


def yt19_exit(m, B):
    b = B[5]
    _, dirn = I.supertrend(b, 10, 3.0)
    return b, dirn < 0, dirn > 0


# ── YT-20 3-EMA 1-minute scalp ────────────────────────────────────────────────────────

def yt20(m, B, p):
    b = B[1]
    e50, e100, e150 = ema(b.c, 50), ema(b.c, 100), ema(b.c, 150)
    out = []
    dip = None
    for j in range(160, len(b.c)):
        if not (7 * 60 <= ((b.t0[j] // 60) % 1440) < 17 * 60):
            dip = None
            continue
        up = e50[j] > e100[j] > e150[j] and e50[j] > e50[j - 10] and e150[j] > e150[j - 10]
        dn = e50[j] < e100[j] < e150[j] and e50[j] < e50[j - 10] and e150[j] < e150[j - 10]
        if dip is None:
            if up and b.c[j] < e50[j] and b.c[j] > e100[j]:
                dip = [1, j, b.l[j]]
            elif dn and b.c[j] > e50[j] and b.c[j] < e100[j]:
                dip = [-1, j, b.h[j]]
            continue
        side, j0, ext = dip
        if (side > 0 and (not up or b.c[j] < e100[j])) or (side < 0 and (not dn or b.c[j] > e100[j])) or j - j0 > 30:
            dip = None
            continue
        if side > 0:
            dip[2] = min(ext, b.l[j])
            if b.c[j] > e50[j]:
                out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(dip[2] - 0.2 * pip(m)), "3EMA"))
                dip = None
        else:
            dip[2] = max(ext, b.h[j])
            if b.c[j] < e50[j]:
                out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(dip[2] + 0.2 * pip(m)), "3EMA"))
                dip = None
    return out


# ── YT-21 Bollinger 2.5 SD range fade ─────────────────────────────────────────────────

def yt21(m, B, p):
    b = B[15]
    mid, up, lo = I.bollinger(b.c, 20, 2.5)
    a = I.atr(b, 14)
    out = []
    for j in range(31, len(b.c)):
        if not (np.isfinite(mid[j]) and np.isfinite(mid[j - 10]) and np.isfinite(a[j])) or not bars_ok_fx(m, b, j):
            continue
        w, w0 = up[j] - lo[j], up[j - 10] - lo[j - 10]
        parallel = w0 > 0 and abs(w - w0) <= 0.05 * w0 and abs(mid[j] - mid[j - 10]) <= 0.25 * w
        if not parallel:
            continue
        if b.l[j] <= lo[j] < b.c[j]:
            out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.c[j] - a[j]), "BB_FADE"))
        elif b.h[j] >= up[j] > b.c[j]:
            out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.c[j] + a[j]), "BB_FADE"))
    return out


def yt21_exit(m, B):
    b = B[15]
    mid, _, _ = I.bollinger(b.c, 20, 2.5)
    return b, b.c >= mid, b.c <= mid


# ── YT-22 Heikin-Ashi pair + Stochastic RSI 20/80 ─────────────────────────────────────

def yt22(m, B, p):
    b = B[15]
    ho, hc = I.heikin_ashi(b)
    g = hc > ho
    K, _ = I.stoch_rsi(b.c)
    out = []
    for j in range(40, len(b.c)):
        if b.day[j] != b.day[j - 1] or not (9 * 60 + 30 <= b.ist0[j] <= 14 * 60 + 45):
            continue
        if g[j] and g[j - 1] and K[j] < 20:
            out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(min(b.l[j], b.l[j - 1])), "HA_STOCHRSI"))
        elif not g[j] and not g[j - 1] and K[j] > 80:
            out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(max(b.h[j], b.h[j - 1])), "HA_STOCHRSI"))
    return out


def yt22_exit(m, B):
    b = B[15]
    K, _ = I.stoch_rsi(b.c)
    Kp = np.r_[K[0], K[:-1]]
    return b, (Kp >= 80) & (K < 80), (Kp <= 20) & (K > 20)


# ── YT-23 Vortex crossover outside congestion ─────────────────────────────────────────

def yt23(m, B, p):
    b = B[15]
    vp, vm = I.vortex(b, 14)
    out = []
    for j in range(20, len(b.c)):
        if b.day[j] != b.day[j - 1] or not (9 * 60 + 30 <= b.ist0[j] <= 14 * 60 + 45) or not np.isfinite(vp[j - 1]):
            continue
        if vp[j] > vm[j] and vp[j - 1] <= vm[j - 1] and (vp[j] > 1.10 or vm[j] < 0.90):
            out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.l[j]), "VORTEX"))
        elif vm[j] > vp[j] and vm[j - 1] <= vp[j - 1] and (vm[j] > 1.10 or vp[j] < 0.90):
            out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.h[j]), "VORTEX"))
    return out


def yt23_exit(m, B):
    b = B[15]
    vp, vm = I.vortex(b, 14)
    return b, np.nan_to_num(vm) > np.nan_to_num(vp), np.nan_to_num(vp) > np.nan_to_num(vm)


# ── YT-24 5-8-13 EMA ribbon ───────────────────────────────────────────────────────────

def yt24(m, B, p):
    b = B[15]
    e5, e8, e13 = ema(b.c, 5), ema(b.c, 8), ema(b.c, 13)
    out = []
    for j in range(20, len(b.c)):
        if b.day[j] != b.day[j - 1] or not (9 * 60 + 30 <= b.ist0[j] <= 14 * 60 + 45):
            continue
        upn, upp = e5[j] > e8[j] > e13[j], e5[j - 1] > e8[j - 1] > e13[j - 1]
        dnn, dnp = e5[j] < e8[j] < e13[j], e5[j - 1] < e8[j - 1] < e13[j - 1]
        if upn and not upp and b.c[j] > max(e5[j], e8[j], e13[j]):
            out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.l[j]), "EMA_5_8_13"))
        elif dnn and not dnp and b.c[j] < min(e5[j], e8[j], e13[j]):
            out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.h[j]), "EMA_5_8_13"))
    return out


def yt24_exit(m, B):
    b = B[15]
    e8 = ema(b.c, 8)
    return b, b.c < e8, b.c > e8


# ── YT-25 RSI 70/30 reversal ──────────────────────────────────────────────────────────

def yt25(m, B, p):
    b = B[15]
    R = rsi(b.c, 14)
    out = []
    for j in range(20, len(b.c)):
        if b.day[j] != b.day[j - 1] or not (9 * 60 + 30 <= b.ist0[j] <= 14 * 60 + 45):
            continue
        if R[j - 1] >= 70 > R[j]:
            out.append(Signal(int(b.day[j]), int(b.i1[j]), -1, float(b.h[j - 4:j + 1].max()), "RSI_70_30"))
        elif R[j - 1] <= 30 < R[j]:
            out.append(Signal(int(b.day[j]), int(b.i1[j]), 1, float(b.l[j - 4:j + 1].min()), "RSI_70_30"))
    return out


# ── YT-26 5-minute ORB on gappers above/below VWAP (NSE stocks proxy) ─────────────────

def yt26(m, B, p):
    b = B[5]
    vw = I.session_vwap(m, b)
    v1 = np.array([float(m.vol[m.d0[d]:min(m.d0[d] + 1, m.d1[d])].sum()) for d in range(m.n_days)])
    out = []
    for d in range(21, m.n_days):
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        if s1 - s0 < 2 or not m.prev_ok[d]:
            continue
        gap = b.o[s0] / pclose(m, d) - 1
        if abs(gap) < 0.02 or v1[d] < 3 * v1[d - 20:d].mean():
            continue
        H, L = b.h[s0], b.l[s0]
        last = next((x for x in range(s0, s1) if b.ist0[x] >= 10 * 60 + 30), s1 - 1)
        for j in range(s0 + 1, last):
            if gap > 0 and b.c[j] > vw[j] and b.c[j] < H:
                out.append(Signal(d, int(b.i1[j]), 1, float(max(L, vw[j] * 0.9995)), "ORB5_VWAP", entry_stop=float(H),
                                  expire_k=int(b.i1[last])))
                break
            if gap < 0 and b.c[j] < vw[j] and b.c[j] > L:
                out.append(Signal(d, int(b.i1[j]), -1, float(min(H, vw[j] * 1.0005)), "ORB5_VWAP", entry_stop=float(L),
                                  expire_k=int(b.i1[last])))
                break
    return out


# ── YT-27 Camarilla R3/S3 fade and R4/S4 breakout ─────────────────────────────────────

def yt27(m, B, p):
    b = B[5]
    out = []
    win = (("ist", 9 * 60 + 20, 14 * 60 + 30) if m.name in ("NIFTY", "BANKNIFTY") else ("ny", 9 * 60 + 35, 15 * 60))
    for d in range(1, m.n_days):
        if not m.prev_ok[d]:
            continue
        a0, a1 = int(m.d0[d - 1]), int(m.d1[d - 1])
        H, L, C = m.h[a0:a1].max(), m.l[a0:a1].min(), m.c[a1 - 1]
        rr = H - L
        R3, R4, S3, S4, P = C + rr * 1.1 / 4, C + rr * 1.1 / 2, C - rr * 1.1 / 4, C - rr * 1.1 / 2, (H + L + C) / 3
        s0, s1 = int(b.b0[d]), int(b.b1[d])
        if not (S3 < b.o[s0] < R3):
            continue
        for j in range(s0, s1):
            clk = b.ist0[j] if win[0] == "ist" else b.ny0[j]
            if not (win[1] <= clk < win[2]):
                continue
            if b.h[j] > R3 and b.c[j] < R3 and b.c[j] > P:
                out.append(Signal(d, int(b.i1[j]), -1, float(R4), "CAM_FADE_R3", target_px=float(P)))
                break
            if b.l[j] < S3 and b.c[j] > S3 and b.c[j] < P:
                out.append(Signal(d, int(b.i1[j]), 1, float(S4), "CAM_FADE_S3", target_px=float(P)))
                break
            if b.c[j] > R4:
                out.append(Signal(d, int(b.i1[j]), 1, float(R3), "CAM_BREAK_R4"))
                break
            if b.c[j] < S4:
                out.append(Signal(d, int(b.i1[j]), -1, float(S3), "CAM_BREAK_S4"))
                break
    return out


# ── registry ──────────────────────────────────────────────────────────────────────────

@dataclass
class Variant:
    tag: str
    sig: dict = field(default_factory=dict)
    exits: dict = field(default_factory=dict)


@dataclass
class Strategy:
    sid: str
    name: str
    channel: str
    videos: tuple
    fn: object
    markets: tuple
    tfs: tuple
    variants: tuple
    limits: Limits
    exit_clock: dict
    exit_fn: object = None          # (m, B, [tf]) -> (bars, exit_long_flags, exit_short_flags)
    first_upload: str = ""
    kind: str = "minute"            # minute / daily / stock15 / stockdaily


IDX = ("NIFTY", "BANKNIFTY")
FX2 = ("EURUSD", "GBPUSD")
FX3 = ("EURUSD", "GBPUSD", "XAUUSD")
NX = {k: NIFTY_X for k in IDX}
FXX = {k: FX_X for k in FX3}
L1 = Limits(1)
LN = Limits(3, stop_after_target=False, second_only_after_stop=False)


def V(tag, **kw):
    sig = kw.pop("sig", {})
    return Variant(tag, sig, kw)


STRATEGIES = {
    "YT-01": Strategy("YT-01", "5 EMA alert candle", "Power of Stocks; Pushkar Raj Thakur", ("fBTMspiqjS4", "uu3zGIXaG8g"), yt01,
                      IDX, (5, 15), (V("V0", target_r=3.0), V("S1", target_r=None, trail_from_r=3.0, trail_tf=5, trail_n=5),
                                     V("R1", target_r=3.0, sig={"both5": True})),
                      LN, NX, first_upload="2022-06-01"),
    "YT-02": Strategy("YT-02", "Market-structure pullback, ATR stop", "The Trading Channel", ("2h5ryPi6ZYo",), yt02, FX2, (60, 240),
                      (V("V0"), V("R1", target_r=1.5)), L1, {k: END_X for k in FX2}, first_upload="2021-06-01", kind="overnight"),
    "YT-03": Strategy("YT-03", "50 MA double bottom / top", "The Trading Channel", ("hTDVTH8umR8",), yt03, FX2, (60,),
                      (V("V0"), V("R1", target_r=1.5)), L1, {k: END_X for k in FX2}, first_upload="2022-01-01", kind="overnight"),
    "YT-04": Strategy("YT-04", "ICT Silver Bullet", "The Inner Circle Trader", ("tRq1hyGGtl4",), yt04, ("EURUSD", "NAS100"), (1,),
                      (V("V0", target_r=None),), Limits(3, False, False), {"EURUSD": FX_X, "NAS100": ("ny", 15 * 60 + 55)},
                      first_upload="2023-06-01"),
    "YT-05": Strategy("YT-05", "ICT Judas Swing", "The Inner Circle Trader", ("xJMbva8SjzE",), yt05, FX2, (5,),
                      (V("V0"), V("R1", target_r=3.0)), L1, {k: ("ny", 12 * 60) for k in FX2}, first_upload="2018-01-01"),
    "YT-06": Strategy("YT-06", "ICT OTE 62% retracement", "The Inner Circle Trader", ("E9F_aT9f038",), yt06, ("EURUSD",), (5,),
                      (V("V0", target_r=None),), L1, {"EURUSD": ("ny", 12 * 60)}, first_upload="2020-05-01"),
    "YT-07": Strategy("YT-07", "Connors RSI(10) pullback, S&P 500", "Rayner Teo", ("W8ENIXvcGlQ",), yt07,
                      ("SPX500_D", "NAS100_D", "NIFTY_D"), (1,),
                      (V("V0", target_r=None, max_hold=10), V("R1", target_r=None, max_hold=10, sig={"stop": True})),
                      Limits(1, False, False), {k: END_X for k in ("SPX500_D", "NAS100_D", "NIFTY_D")},
                      exit_fn=lambda m, B: yt07_exit(m, B), first_upload="2021-01-01", kind="daily"),
    "YT-08": Strategy("YT-08", "Inside candle (15m)", "Power of Stocks", ("42J_foitsdI",), yt08, IDX + ("NSE15",), (15,),
                      (V("V0", target_r=None), V("S1", sig={"t2r": True}), V("R1", target_r=None, sig={"entry": "mother"})),
                      Limits(2, True, True), {**NX, "NSE15": NIFTY_X}, first_upload="2021-12-01", kind="minute"),
    "YT-09": Strategy("YT-09", "Traffic light candle pair", "Power of Stocks", ("djC2hSdNo74",), yt09, IDX, (1, 5),
                      (V("V0"), V("S1", sig={"tf": 5})), L1, NX, first_upload="2022-03-01"),
    "YT-10": Strategy("YT-10", "Gap + shooting star / hammer first candle", "Ghanshyam Tech", ("3v9nvXaW0QQ",), yt10, IDX, (5, 15),
                      (V("V0"), V("S1", sig={"tf": 5})), L1, NX, first_upload="2022-01-01"),
    "YT-11": Strategy("YT-11", "Momentum loss into a swing level", "Wysetrade", ("asDBegQaupM",), yt11, FX3, (60, 240),
                      (V("V0"), V("R1", target_r=1.5)), L1, {k: END_X for k in FX3}, first_upload="2021-01-01", kind="overnight"),
    "YT-12a": Strategy("YT-12a", "44 SMA bullish candle (daily)", "Siddharth Bhanushali", ("0igedWz9xD0",), yt12a, ("NSED",), (1,),
                       (V("V0", max_hold=20), V("R1", target_r=3.0, max_hold=30)), Limits(1, False, False), {"NSED": END_X},
                       first_upload="2021-06-01", kind="stockdaily"),
    "YT-12b": Strategy("YT-12b", "44 SMA + big green opening candle (15m)", "Siddharth Bhanushali", ("0igedWz9xD0",), yt12b, ("NSE15",),
                       (15,), (V("V0"),), L1, {"NSE15": NIFTY_X}, first_upload="2021-06-01", kind="minute"),
    "YT-13": Strategy("YT-13", "Daily bear / bull trap", "Siddharth Bhanushali", ("EIA095N86Vk",), yt13, ("NSED", "NIFTY_D"), (1,),
                      (V("V0", max_hold=20),), Limits(1, False, False), {"NSED": END_X, "NIFTY_D": END_X},
                      first_upload="2021-01-01", kind="stockdaily"),
    "YT-14": Strategy("YT-14", "MA fan + engulfing / three-line strike, RSI 50", "The Moving Average", ("wbfXaqjIrJ0", "oDOCBTYgCQM"),
                      yt14, FX3, (5,), (V("V0"), V("R1", target_r=1.5)), LN, FXX, first_upload="2022-06-01"),
    "YT-15": Strategy("YT-15", "MA alignment + Williams fractal, 10 pips", "The Moving Average", ("MK47z07tGNM",), yt15, FX2, (5,),
                      (V("V0", target_r=None, target_abs=0.0010), V("S1", target_r=None, target_abs=0.0010, be_at_abs=0.0010)),
                      Limits(5, False, False), {k: FX_X for k in FX2}, first_upload="2022-01-01"),
    "YT-16": Strategy("YT-16", "MA pullback + engulfing / pin bar, 1:2", "Adam Khoo", ("lHhtVfeoCdQ", "MVI7Jm_abrg"), yt16,
                      FX2 + ("SPX500_D", "NAS100_D"), (60, 1), (V("V0"),), L1,
                      {**{k: END_X for k in FX2}, "SPX500_D": END_X, "NAS100_D": END_X}, first_upload="2016-01-01", kind="overnight"),
    "YT-17": Strategy("YT-17", "Breakout, pullback, continuation", "Wealth Secret", ("oEc3_vjg6PE", "QqQLqWMjcsc"), yt17, IDX, (5,),
                      (V("V0"), V("R1", target_r=1.5)), L1, NX, first_upload="2023-09-01"),
    "YT-18": Strategy("YT-18", "Heikin-Ashi colour change + RSI 50", "The Secret Mindset", ("Ci1hKIHL9VY",), yt18, FX3, (15, 60),
                      (V("V0", target_r=None), V("S1", target_r=None, sig={"tf": 60})), LN, FXX,
                      exit_fn=lambda m, B, tf=15: yt18_exit(m, B, tf), first_upload="2021-06-01"),
    "YT-19": Strategy("YT-19", "Supertrend(10,3) at 09:20 (futures proxy)", "Elearnmarkets / Vishal Mehta", ("bj6hVKjweZ8",), yt19,
                      IDX, (5,), (V("V0", target_r=None),), L1, NX, exit_fn=lambda m, B: yt19_exit(m, B), first_upload="2021-08-01"),
    "YT-20": Strategy("YT-20", "3-EMA 1-minute scalp", "The Secret Mindset", ("7XhVy9z5SbM",), yt20, FX2, (1,),
                      (V("V0", be_at_abs=0.0005), V("S1", target_r=1.5)), Limits(5, False, False), {k: FX_X for k in FX2},
                      first_upload="2021-03-01"),
    "YT-21": Strategy("YT-21", "Bollinger 2.5 SD range fade", "The Secret Mindset", ("2G9fHBEsauE",), yt21, FX2, (15,),
                      (V("V0", target_r=None),), LN, {k: FX_X for k in FX2}, exit_fn=lambda m, B: yt21_exit(m, B),
                      first_upload="2021-06-01"),
    "YT-22": Strategy("YT-22", "Heikin-Ashi pair + Stochastic RSI 20/80", "Nitin Bhatia", ("aLwpyla5Hrk",), yt22, IDX + ("NSE15",), (15,),
                      (V("V0", target_r=None),), Limits(2, False, False), {**NX, "NSE15": NIFTY_X},
                      exit_fn=lambda m, B: yt22_exit(m, B), first_upload="2020-06-01"),
    "YT-23": Strategy("YT-23", "Vortex crossover outside congestion", "Nitin Bhatia", ("cFqdpiHokDw",), yt23, ("NIFTY", "NSE15"), (15,),
                      (V("V0", target_r=None),), Limits(2, False, False), {"NIFTY": NIFTY_X, "NSE15": NIFTY_X},
                      exit_fn=lambda m, B: yt23_exit(m, B), first_upload="2020-09-01"),
    "YT-24": Strategy("YT-24", "5-8-13 EMA ribbon", "Nitin Bhatia", ("J9FA7Ouc9i0",), yt24, IDX + ("NSE15",), (15,),
                      (V("V0", target_r=None),), Limits(2, False, False), {**NX, "NSE15": NIFTY_X},
                      exit_fn=lambda m, B: yt24_exit(m, B), first_upload="2020-06-01"),
    "YT-25": Strategy("YT-25", "RSI 70/30 reversal", "Super Trader Lakshya", ("N3VDbcqilys",), yt25, ("NSE15",), (15,),
                      (V("V0"),), Limits(2, False, False), {"NSE15": NIFTY_X}, first_upload="2021-01-01"),
    "YT-26": Strategy("YT-26", "5-minute ORB on gappers with VWAP (proxy)", "Bear Bull Traders", ("oqzgq4StNS8",), yt26, ("NSE5",), (5,),
                      (V("V0"),), L1, {"NSE5": NIFTY_X}, first_upload="2023-01-01"),
    "YT-27": Strategy("YT-27", "Camarilla R3/S3 fade, R4/S4 breakout", "Bear Bull Traders", ("AuArOT-tK9M",), yt27,
                      IDX + ("NAS100",), (5,), (V("V0"),), L1, {**NX, "NAS100": ("ny", 15 * 60 + 55)}, first_upload="2022-01-01"),
}


def build_bars(m, tfs):
    return {tf: make_bars(m, tf) for tf in tfs}


def exits_for(st: Strategy, v: Variant, m, B) -> Exits:
    kw = dict(v.exits)
    tf = kw.pop("trail_tf", None)
    n = kw.pop("trail_n", 9)
    ex = Exits(**kw)
    if ex.trail_from_r is not None:
        ex.trail_bars = B[tf]
        ex.trail_ema = ema(B[tf].c, n)
    if st.exit_fn is not None:
        if st.sid == "YT-18":
            xb, xl, xs = st.exit_fn(m, B, v.sig.get("tf", 15))
        else:
            xb, xl, xs = st.exit_fn(m, B)
        ex.xbars, ex.xlong, ex.xshort = xb, xl, xs
    return ex
