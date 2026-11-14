"""Seventh batch of the channel-shortlist study (14 Nov 2026): the cards of the owner's channels 61-70 (cards/<video>.txt;
the 'A' rules are this code). Same conventions as ze_more4 / ze_more5: BTCUSD and ETHUSD are Delta Exchange perpetuals on
the UTC day (real volume), XAUUSD is gold booked on Delta XAUTUSD (the 17:00 New York day).

Every signal uses only the bars up to its own signal bar. SA-02's ten-candle wait after a trade closes is decided by
replaying its own earlier trades on the rows up to the signal (its stop and target are fixed at entry), never by
looking ahead."""

from __future__ import annotations

import numpy as np

import yc_ind as I
import zd_common as Z
from yc_common import ctx, sig
from yc_engine import XExits
from ze_more2 import _last_done, _swing_levels
from ze_more4 import TICK, _cached, _fin


# ── indicators ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _kama(c, n=14, fast=2, slow=30):
    """Kaufman adaptive moving average (Jesse / TA-Lib defaults)."""
    c = np.asarray(c, float)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    fs, ss = 2.0 / (fast + 1), 2.0 / (slow + 1)
    vol = np.abs(np.diff(c, prepend=c[0]))
    k = c[n - 1]
    out[n - 1] = k
    for i in range(n, len(c)):
        v = vol[i - n + 1:i + 1].sum()
        er = abs(c[i] - c[i - n]) / v if v > 0 else 0.0
        sc = (er * (fs - ss) + ss) ** 2
        k = k + sc * (c[i] - k)
        out[i] = k
    return out


def _cmo(c, n=14):
    """Chande momentum oscillator, -100..100."""
    d = np.diff(np.asarray(c, float), prepend=np.nan)
    up, dn = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    cs = lambda x: np.cumsum(np.r_[0.0, np.nan_to_num(x)])  # noqa: E731
    su, sd = cs(up), cs(dn)
    out = np.full(len(d), np.nan)
    a, z = su[n + 1:] - su[1:-n], sd[n + 1:] - sd[1:-n]
    with np.errstate(invalid="ignore", divide="ignore"):
        out[n:] = np.where(a + z > 0, 100 * (a - z) / (a + z), 0.0)
    return out


def _chop(b, n=14):
    """Choppiness index: 100 log10(sum of n true ranges / n-bar range) / log10(n)."""
    tr = I.true_range(b)
    cs = np.cumsum(np.r_[0.0, tr])
    s = np.full(len(tr), np.nan)
    s[n - 1:] = cs[n:] - cs[:-n]
    rng = I.highest(np.asarray(b.h, float), n) - I.lowest(np.asarray(b.l, float), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(rng > 0, 100 * np.log10(s / rng) / np.log10(n), np.nan)


def _harsi(b, n=14, smooth=7):
    """Heikin Ashi RSI oscillator (JayRogers): HA candles of the zero-centred RSI; (open, high, low, close)."""
    import bb_markets as BM
    zc = BM.rsi(np.asarray(b.c, float), n) - 50
    zh = BM.rsi(np.asarray(b.h, float), n) - 50
    zl = BM.rsi(np.asarray(b.l, float), n) - 50
    N = len(zc)
    op_rsi = np.r_[zc[0], zc[:-1]]
    hi_rsi, lo_rsi = np.maximum(zh, zl), np.minimum(zh, zl)
    cl = (op_rsi + hi_rsi + lo_rsi + zc) / 4
    op = np.full(N, np.nan)
    for i in range(N):
        if i < smooth or not np.isfinite(op[i - 1]):
            op[i] = (op_rsi[i] + zc[i]) / 2
        else:
            op[i] = (op[i - 1] * smooth + cl[i - 1]) / (smooth + 1)
    hi = np.maximum(hi_rsi, np.maximum(op, cl))
    lo = np.minimum(lo_rsi, np.minimum(op, cl))
    return op, hi, lo, cl


def _alligator_close(b):
    """Jesse's Alligator of the close: SMMA 13 / 8 / 5 shifted 8 / 5 / 3."""
    c = np.asarray(b.c, float)
    return I.shift(I.smma(c, 13), 8), I.shift(I.smma(c, 8), 5), I.shift(I.smma(c, 5), 3)


def _gator_trend(b, jaw, teeth, lips):
    c = np.asarray(b.c, float)
    ok = np.isfinite(jaw) & np.isfinite(teeth) & np.isfinite(lips)
    jw, tt, lp = (np.where(ok, x, 0.0) for x in (jaw, teeth, lips))
    up = ok & (lp > tt) & (tt > jw) & (c > lp)
    dn = ok & (lp < tt) & (tt < jw) & (c < lp)
    return np.where(up, 1, np.where(dn, -1, 0))


# ═══ TQ-01 Heikin Ashi RSI oscillator back to zero, then the first candle with the EMA 200 trend, swing stop, 2R ══════

def tq01(m, B, p, cache):
    b = B[1]
    e200 = ctx(m, B, 1, cache).ema(200)
    op, hi, lo, cl = _cached(cache, ("ze6_harsi1",), lambda: _harsi(b, 14, 7))
    h, l, c = b.h, b.l, b.c
    out = []
    arm_l = arm_s = False
    for j in range(220, len(c)):
        if not _fin(e200[j], op[j], cl[j], hi[j], lo[j]):
            continue
        if c[j] > e200[j]:
            arm_s = False
            if arm_l and cl[j] > op[j]:
                out.append(sig(b, j, 1, float(np.min(l[j - 9:j + 1])) * (1 - TICK), "TQ01_HARSI_PULLBACK_LONG"))
                arm_l = False
            elif lo[j] <= 0:
                arm_l = True
        else:
            arm_l = False
            if arm_s and cl[j] < op[j]:
                out.append(sig(b, j, -1, float(np.max(h[j - 9:j + 1])) * (1 + TICK), "TQ01_HARSI_PULLBACK_SHORT"))
                arm_s = False
            elif hi[j] >= 0:
                arm_s = True
    return out


def tq01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ TQ-02 EMA 50 / 200 cross, the first touch of the EMA 50, a candle back beyond it, 2 ATR stop, 1.5R ══════════════

def tq02(m, B, p, cache):
    b = B[1]
    cx = ctx(m, B, 1, cache)
    e50, e200, a14 = cx.ema(50), cx.ema(200), cx.atr(14)
    o, h, l, c = b.o, b.h, b.l, b.c
    out = []
    st = None                                          # (side, touched, closes beyond the 200 against the side)
    for j in range(220, len(c)):
        if not _fin(e50[j], e200[j], e50[j - 1], e200[j - 1], a14[j]):
            continue
        if e50[j] > e200[j] and e50[j - 1] <= e200[j - 1]:
            st = [1, False, 0]
        elif e50[j] < e200[j] and e50[j - 1] >= e200[j - 1]:
            st = [-1, False, 0]
        elif st is None:
            continue
        side = st[0]
        if (c[j] < e200[j]) if side > 0 else (c[j] > e200[j]):
            st[2] += 1
            if st[2] > 3:
                st = None
                continue
        if not st[1] and ((l[j] <= e50[j]) if side > 0 else (h[j] >= e50[j])):
            st[1] = True
        if st[1] and ((c[j] > o[j] and c[j] > e50[j]) if side > 0 else (c[j] < o[j] and c[j] < e50[j])):
            d = 2.0 * float(a14[j])
            out.append(sig(b, j, side, float(c[j]) - side * d,
                           "TQ02_EMA50_FIRST_TOUCH_LONG" if side > 0 else "TQ02_EMA50_FIRST_TOUCH_SHORT", info={"stop_dist": d}))
            st = None
    return out


def tq02_x(m, B, p, cache):
    return XExits(target_r=1.5)


# ═══ TQ-03 Supertrend (7, 5) with a MACD (8, 21, 3) cross on the far side of zero, 2.5 ATR trailing stop, 4R ═════════

def tq03(m, B, p, cache):
    b = B[5]
    cx = ctx(m, B, 5, cache)
    _, dirn = cx.supertrend(7, 5.0)
    a14 = cx.atr(14)
    c5 = np.asarray(b.c, float)
    macd = I.ema(c5, 8) - I.ema(c5, 21)
    sgl = I.ema(macd, 3)
    out = []
    used = 0                                           # one entry per Supertrend direction
    for j in range(40, len(c5)):
        if dirn[j] != dirn[j - 1]:
            used = 0
        if used or not _fin(a14[j], macd[j], sgl[j], macd[j - 1], sgl[j - 1]):
            continue
        d = 2.5 * float(a14[j])
        if dirn[j] > 0 and macd[j] > sgl[j] and macd[j - 1] <= sgl[j - 1] and macd[j] < 0:
            out.append(sig(b, j, 1, float(c5[j]) - d, "TQ03_SUPERTREND_MACD_LONG", info={"stop_dist": d}))
            used = 1
        elif dirn[j] < 0 and macd[j] < sgl[j] and macd[j - 1] >= sgl[j - 1] and macd[j] > 0:
            out.append(sig(b, j, -1, float(c5[j]) + d, "TQ03_SUPERTREND_MACD_SHORT", info={"stop_dist": d}))
            used = 1
    return out


def tq03_x(m, B, p, cache):
    b = B[5]
    return XExits(target_r=4.0, trail=("chand", b, ctx(m, B, 5, cache).atr(14), 2.5, "high"))


# ═══ JO-01 Ichimoku edge to edge: a close inside the cloud from one side targets the other edge ═════════════════════

def _jo01_cloud(m, B, cache):
    def calc():
        b = B[60]
        h, l, c = (np.asarray(x, float) for x in (b.h, b.l, b.c))
        prm = (18, 52, 104, 26) if m.name == "XAUUSD" else (20, 60, 120, 30)    # his legacy / crypto settings
        _, _, sa, sb = I.ichimoku(h, l, c, *prm)
        return np.fmax(sa, sb), np.fmin(sa, sb)
    return _cached(cache, ("ze6_jo01",), calc)


def jo01(m, B, p, cache):
    b = B[60]
    top, bot = _jo01_cloud(m, B, cache)
    c = b.c
    out = []
    for j in range(1, len(c)):
        if not _fin(top[j], bot[j], top[j - 1], bot[j - 1]) or not top[j] > bot[j]:
            continue
        inside = bot[j] <= c[j] <= top[j]
        if inside and c[j - 1] < bot[j - 1]:
            out.append(sig(b, j, 1, float(bot[j]) * (1 - 0.003), "JO01_EDGE_TO_EDGE_LONG", target_px=float(top[j])))
        elif inside and c[j - 1] > top[j - 1]:
            out.append(sig(b, j, -1, float(top[j]) * (1 + 0.003), "JO01_EDGE_TO_EDGE_SHORT", target_px=float(bot[j])))
    return out


def jo01_x(m, B, p, cache):
    b = B[60]
    top, bot = _jo01_cloud(m, B, cache)
    c = np.asarray(b.c, float)
    out_dn = np.isfinite(bot) & (c < np.where(np.isfinite(bot), bot, -np.inf))      # a close back out the entry edge
    out_up = np.isfinite(top) & (c > np.where(np.isfinite(top), top, np.inf))
    return XExits(target_r=None, xbars=b, xlong=out_dn, xshort=out_up)


# ═══ SA-01 ADX above 50 with the DI trend and Williams %R at an extreme, stop at the SMA 50, target the 30-bar extreme ═

def _sa01_arr(m, B, cache):
    def calc():
        b = B[15]
        adx, pdi, mdi = I.adx(b, 14)
        wr = Z.williams_r(b, 14)
        sma = I.sma(np.asarray(b.c, float), 50)
        ok = np.isfinite(adx) & np.isfinite(pdi) & np.isfinite(mdi) & np.isfinite(wr)
        long_ok = ok & (np.where(ok, pdi, 0) > np.where(ok, mdi, 0)) & (np.where(ok, adx, 0) > 50) & (np.where(ok, wr, 0) < -80)
        short_ok = ok & (np.where(ok, mdi, 0) > np.where(ok, pdi, 0)) & (np.where(ok, adx, 0) > 50) & (np.where(ok, wr, -100) > -20)
        return long_ok, short_ok, sma
    return _cached(cache, ("ze6_sa01",), calc)


def sa01(m, B, p, cache):
    b = B[15]
    lk, sk, sma = _sa01_arr(m, B, cache)
    h, l = b.h, b.l
    out = []
    for j in range(60, len(b.c)):
        if not np.isfinite(sma[j]):
            continue
        if lk[j]:
            out.append(sig(b, j, 1, float(sma[j]), "SA01_ADX_WILLR_LONG", target_px=float(np.max(h[j - 29:j + 1]))))
        elif sk[j]:
            out.append(sig(b, j, -1, float(sma[j]), "SA01_ADX_WILLR_SHORT", target_px=float(np.min(l[j - 29:j + 1]))))
    return out


def sa01_x(m, B, p, cache):
    b = B[15]
    lk, sk, _ = _sa01_arr(m, B, cache)
    return XExits(target_r=None, xbars=b, xlong=sk, xshort=lk)


# ═══ SA-02 KAMA trend on 15 minutes and 4 hours, ADX > 50, choppiness < 50, narrow bands, 2.5 ATR both ways, 10-bar wait ═

def _sa02_cands(m, B, cache):
    def calc():
        b, b4 = B[15], B[240]
        c = np.asarray(b.c, float)
        k15 = _kama(c, 14, 2, 30)
        k4 = _kama(np.asarray(b4.c, float), 14, 2, 30)
        adx, _, _ = I.adx(b, 14)
        chop = _chop(b, 14)
        mid, up, lo = I.bollinger(c, 20, 2.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            bbw = (up - lo) / mid * 100
        a14 = ctx(m, B, 15, cache).atr(14)
        out = []
        for j in range(60, len(c)):
            k = _last_done(b4, b, j)
            if k < 0 or not _fin(k15[j], k4[k], adx[j], chop[j], bbw[j], a14[j]):
                continue
            if not (adx[j] > 50 and chop[j] < 50 and bbw[j] < 7):
                continue
            if c[j] > k15[j] and c[j] > k4[k]:
                out.append((j, 1, 2.5 * float(a14[j])))
            elif c[j] < k15[j] and c[j] < k4[k]:
                out.append((j, -1, 2.5 * float(a14[j])))
        return out
    return _cached(cache, ("ze6_sa02",), calc)


def sa02(m, B, p, cache):
    """One trade at a time, the next only 10 bars after the last one closed: the earlier trades are replayed on the rows
    (stop and target 2.5 ATR from the next row's open; a row touching both counts as the stop)."""
    b = B[15]
    mh, ml, mo = np.asarray(m.h, float), np.asarray(m.l, float), np.asarray(m.o, float)
    last = len(m.t) - 1
    free_from = -1                                     # the first bar a new signal may use
    out = []
    for j, side, d in _sa02_cands(m, B, cache):
        if j < free_from:
            continue
        k0 = int(b.i1[j]) + 1
        if k0 > last:
            break
        out.append(sig(b, j, side, float(b.c[j]) - side * d,
                       "SA02_KAMA_TREND_LONG" if side > 0 else "SA02_KAMA_TREND_SHORT", info={"stop_dist": d}))
        entry = mo[k0]
        stop, tgt = entry - side * d, entry + side * d
        hit = None
        for r in range(k0, last + 1):
            if (ml[r] <= stop) if side > 0 else (mh[r] >= stop):
                hit = r
                break
            if (mh[r] >= tgt) if side > 0 else (ml[r] <= tgt):
                hit = r
                break
        if hit is None:                                # still open at the end of the data
            break
        free_from = int(np.searchsorted(b.i1, hit, "left")) + 10
    return out


def sa02_x(m, B, p, cache):
    return XExits(target_r=1.0)


# ═══ SA-03 Alligator trend on 30 minutes and 4 hours, ADX > 30, 4-hour EMA 100, CMO beyond 20, Stoch RSI pullback, 2 ATR ═

def sa03(m, B, p, cache):
    b, b4 = B[30], B[240]
    c = np.asarray(b.c, float)
    tr30 = _cached(cache, ("ze6_sa03_t30",), lambda: _gator_trend(b, *_alligator_close(b)))
    tr4 = _cached(cache, ("ze6_sa03_t4",), lambda: _gator_trend(b4, *_alligator_close(b4)))
    e100 = I.ema(np.asarray(b4.c, float), 100)
    adx, _, _ = I.adx(b, 14)
    cmo = _cmo(c, 14)
    K, _ = Z.stoch_rsi(c, 14, 14, 3, 3)
    a14 = ctx(m, B, 30, cache).atr(14)
    out = []
    for j in range(60, len(c)):
        k = _last_done(b4, b, j)
        if k < 100 or not _fin(adx[j], cmo[j], K[j], a14[j], e100[k]) or adx[j] <= 30:
            continue
        d = 2.0 * float(a14[j])
        if tr30[j] == 1 and tr4[k] == 1 and c[j] > e100[k] and cmo[j] > 20 and K[j] < 20:
            out.append(sig(b, j, 1, float(c[j]) - d, "SA03_ALLIGATOR_PULLBACK_LONG", info={"stop_dist": d}))
        elif tr30[j] == -1 and tr4[k] == -1 and c[j] < e100[k] and cmo[j] < -20 and K[j] > 80:
            out.append(sig(b, j, -1, float(c[j]) + d, "SA03_ALLIGATOR_PULLBACK_SHORT", info={"stop_dist": d}))
    return out


def sa03_x(m, B, p, cache):
    return XExits(target_r=1.0)


# ═══ BV-01 Williams Alligator side + a close beyond the last fractal, fractal trailing stop, out under the teeth ══════

def _bv01_arr(m, B, cache):
    def calc():
        b = B[240]
        jaw, teeth, lips = I.alligator(b)
        flo, fhi = _swing_levels(b, 2)
        return jaw, teeth, lips, flo, fhi
    return _cached(cache, ("ze6_bv01",), calc)


def bv01(m, B, p, cache):
    b = B[240]
    jaw, teeth, lips, flo, fhi = _bv01_arr(m, B, cache)
    c = b.c
    out = []
    for j in range(30, len(c)):
        if not _fin(jaw[j], teeth[j], lips[j], flo[j], fhi[j]):
            continue
        if lips[j] > teeth[j] > jaw[j] and c[j] > fhi[j] >= c[j - 1] and flo[j] < c[j]:
            out.append(sig(b, j, 1, float(flo[j]) * (1 - TICK), "BV01_GATOR_FRACTAL_BREAK_LONG"))
        elif lips[j] < teeth[j] < jaw[j] and c[j] < flo[j] <= c[j - 1] and fhi[j] > c[j]:
            out.append(sig(b, j, -1, float(fhi[j]) * (1 + TICK), "BV01_GATOR_FRACTAL_BREAK_SHORT"))
    return out


def bv01_x(m, B, p, cache):
    b = B[240]
    jaw, teeth, lips, flo, fhi = _bv01_arr(m, B, cache)
    c = np.asarray(b.c, float)
    ok = np.isfinite(teeth) & np.isfinite(lips)
    tt, lp = np.where(ok, teeth, 0.0), np.where(ok, lips, 0.0)
    xl = ok & ((c < tt) | (lp < tt))
    xs = ok & ((c > tt) | (lp > tt))
    return XExits(target_r=None, xbars=b, xlong=xl, xshort=xs, trail=("level", b, flo * (1 - TICK), fhi * (1 + TICK)))
