"""Gold channels 21-40 (the owner's list of 22 Nov 2026): the strategies read from the channels' gold videos, written as
code (zg_spec.py holds every rule with its tag, quote and video time; the 'A' rules there are the choices this code
makes where the videos leave a gap).

Market: XAUUSD as the desk books it, i.e. Delta Exchange India's XAUTUSD perpetual, 1-minute candles with Delta's own
traded volume, on the gold week (Sunday 17:00 to Friday 17:00 New York; the desk drops the weekend minutes). Bars never
cross gold's trading day (it rolls at 17:00 New York); daily bars are one bar per gold day (ze_more4._daily).

Conventions are the 11-channel study's (yc_common): fn(m, B, p, cache) -> list of Signal from completed bars only; a
signal carries its bar's last row, so its order starts on the next row; a swing pivot of n bars is used only n bars
after it; a higher-timeframe bar is used only once complete (_last_done). Every function is deterministic and reads
nothing beyond its signal bar, which zg_checks.py tests by cutting the data at random minutes.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
for _p in (HERE, RESEARCH / "youtube_channels11_2026_11", RESEARCH / "youtube_top20_2026_11",
           RESEARCH / "booming_bulls_2026_11", RESEARCH / "crypto_playlist_2026_11"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402

import bb_markets as BM  # noqa: E402
import yc_ind as I  # noqa: E402
import yt_ind as YI  # noqa: E402
from yc_common import ctx, sig  # noqa: E402
from yc_engine import XExits  # noqa: E402


# the channel-shortlist study's small helpers (ze_more2 / ze_more4), copied so this study imports none of its modules
def _fin(*xs) -> bool:
    return all(np.isfinite(x) for x in xs)


def _cached(cache, key, fn):
    if key not in cache:
        cache[key] = fn()
    return cache[key]


def _last_done(big, small, j):
    """Index of the last `big` bar completed by the close of `small` bar j (-1 if none)."""
    return int(np.searchsorted(big.i1, small.i1[j], "right")) - 1


def _daily(m, cache):
    """One bar per gold trading day (the day rolls at 17:00 New York); a day's bar is known after its last row."""
    def calc():
        d0 = np.asarray(m.d0, np.int64)
        d1 = np.asarray(m.d1, np.int64)
        n = len(d0)
        o = np.asarray(m.o, float)[d0]
        h = np.maximum.reduceat(np.asarray(m.h, float), d0)
        l = np.minimum.reduceat(np.asarray(m.l, float), d0)
        c = np.asarray(m.c, float)[d1 - 1]
        t0 = np.asarray(m.t, np.int64)[d0]
        ist0, ny0 = BM._clocks(t0)
        idx = np.arange(n, dtype=np.int64)
        return BM.Bars(1440, idx, d0, d1 - 1, t0, o, h, l, c, ist0, ny0, idx, idx + 1)
    return _cached(cache, ("zg_daily",), calc)

TICK = 0.01                 # Delta XAUTUSD's price tick (US dollars)
CATASTROPHE = 0.02          # a far guard stop (2% of price) for rules whose video gives no stop
ALL_IN = 0.01               # risk unit of a position the size of the account, as a fraction of the price (1% risk)


# ── shared helpers ──────────────────────────────────────────────────────────────────────────────────────────────────

def _ny(b, j) -> int:
    """New York minute of the day at which bar j starts."""
    return int(b.ny0[j])


def _in(b, j, lo: int, hi: int) -> bool:
    """Bar j starts inside [lo, hi) New York minutes (windows that do not cross midnight)."""
    return lo <= _ny(b, j) < hi


def _ny_end(b, j) -> int:
    """New York minute at which bar j ends (its start plus its length)."""
    return (_ny(b, j) + int(b.tf)) % 1440


T = lambda h, mi: h * 60 + mi  # noqa: E731


def _day_bars(b, d):
    return range(int(b.b0[d]), int(b.b1[d]))


def _week_key(m, d) -> int:
    """Monday-based week number of gold day d (by the day's date)."""
    days = int(m.date[d].astype("datetime64[D]").astype(np.int64))
    return (days + 3) // 7


def _prior_week_hl(m, D, d):
    """(high, low) of the last complete gold week before day d's week, NaN if none."""
    wk = _week_key(m, d)
    hs, ls = [], []
    e = d - 1
    while e >= 0 and _week_key(m, e) == wk:
        e -= 1
    if e < 0:
        return np.nan, np.nan
    wk0 = _week_key(m, e)
    while e >= 0 and _week_key(m, e) == wk0:
        hs.append(D.h[e])
        ls.append(D.l[e])
        e -= 1
    return float(max(hs)), float(min(ls))


def _pivots(b, n=2):
    """Per bar: (last confirmed pivot high value, its bar, last confirmed pivot low value, its bar, previous pivot high,
    previous pivot low), each known n bars after its pivot (yc_ind.pivots_known)."""
    ph, pl = YI.fractals(b, n)
    return I.pivots_known(b, ph, pl, n)


def _profile(m, a: int, z: int, width: float):
    """Volume profile of minute rows [a, z): each minute's volume spread evenly over the price bins its range covers
    (bins of `width` dollars). Returns (poc, vah, val) with a 70% value area grown from the point of control, the side
    with the larger next bin first; NaNs when there are no rows."""
    if z <= a:
        return np.nan, np.nan, np.nan
    lo = np.asarray(m.l[a:z], float)
    hi = np.asarray(m.h[a:z], float)
    v = np.asarray(m.vol[a:z], float)
    v = np.where(np.isfinite(v) & (v > 0), v, 1.0)
    base = np.floor(lo.min() / width) * width
    i0 = np.floor((lo - base) / width + 1e-9).astype(np.int64)
    i1 = np.floor((hi - base) / width + 1e-9).astype(np.int64)
    nb = int(i1.max()) + 1
    vol = np.zeros(nb)
    span = i1 - i0 + 1
    share = v / span
    for k in range(int(span.max())):
        sel = span > k
        np.add.at(vol, i0[sel] + k, share[sel])
    poc = int(np.argmax(vol))
    total = vol.sum()
    lo_i = hi_i = poc
    acc = vol[poc]
    while acc < 0.70 * total and (lo_i > 0 or hi_i < nb - 1):
        up = vol[hi_i + 1] if hi_i < nb - 1 else -1.0
        dn = vol[lo_i - 1] if lo_i > 0 else -1.0
        if up >= dn:
            hi_i += 1
            acc += vol[hi_i]
        else:
            lo_i -= 1
            acc += vol[lo_i]
    mid = lambda i: base + (i + 0.5) * width  # noqa: E731
    return float(mid(poc)), float(base + (hi_i + 1) * width), float(base + lo_i * width)


def _rows_between(m, d, lo_min: int, hi_min: int, evening: bool = False):
    """Minute rows [a, z) of gold day d whose New York clock is inside [lo_min, hi_min); evening=True takes the rows
    from lo_min to midnight plus those from midnight to hi_min (the overnight session, which starts the gold day)."""
    a, z = int(m.d0[d]), int(m.d1[d])
    ny = np.asarray(m.ny[a:z], np.int64)
    sel = ((ny >= lo_min) | (ny < hi_min)) if evening else ((ny >= lo_min) & (ny < hi_min))
    idx = np.flatnonzero(sel)
    if not len(idx):
        return None
    return a + int(idx[0]), a + int(idx[-1]) + 1


def _sweep_tail_short(b, j, level, look):
    """Highest high of bars j-look..j (the tail of a break above `level`) if one of them traded above it."""
    j0 = max(int(b.b0[b.day[j]]), j - look)
    hh = float(np.max(b.h[j0:j + 1]))
    return hh if hh > level else np.nan


def _sweep_tail_long(b, j, level, look):
    j0 = max(int(b.b0[b.day[j]]), j - look)
    ll = float(np.min(b.l[j0:j + 1]))
    return ll if ll < level else np.nan


def _tgt(side, entry_ref, stop, level, min_r, default_r):
    """A structural target `level` if it is at least min_r R beyond the reference entry, else default_r R."""
    risk = (entry_ref - stop) * side
    if not risk > 0:
        return None
    if np.isfinite(level) and (level - entry_ref) * side >= min_r * risk:
        return float(level)
    return float(entry_ref + side * default_r * risk)


# ═══ AF-03  Axia Futures: gold inside-day break, continuation to the mother day's extreme (15 minutes) ═══════════════

def af03(m, B, p, cache):
    b = B[15]
    D = _daily(m, cache)
    out = []
    for d in range(2, m.n_days):
        if not (D.h[d - 1] <= D.h[d - 2] and D.l[d - 1] >= D.l[d - 2]):
            continue
        ih, il = float(D.h[d - 1]), float(D.l[d - 1])
        mh, ml = float(D.h[d - 2]), float(D.l[d - 2])
        for j in _day_bars(b, d):
            if _ny(b, j) >= T(16, 0) and _ny(b, j) < T(17, 0):
                break
            c = float(b.c[j])
            if c > ih:
                stop = float(b.l[j]) - TICK
                tp = _tgt(1, c, stop, mh, 1.0, 2.0)
                if tp is not None:
                    out.append(sig(b, j, 1, stop, "AF03_INSIDE_DAY_BREAK_UP", target_px=tp))
                break
            if c < il:
                stop = float(b.h[j]) + TICK
                tp = _tgt(-1, c, stop, ml, 1.0, 2.0)
                if tp is not None:
                    out.append(sig(b, j, -1, stop, "AF03_INSIDE_DAY_BREAK_DOWN", target_px=tp))
                break
    return out


def af03_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ AF-04  Axia Futures: COMEX-hours break of a repeatedly tested prior-day high (low), target last week's high (low)
#     (5 minutes) ═════════════════════════════════════════════════════════════════════════════════════════════════════

AF04_TEST = 0.0003          # a 'test': a 5-minute high within 0.03% of the level without a close beyond it
AF04_GAP = 6                # tests at least six bars (30 minutes) apart count separately


def af04(m, B, p, cache):
    b = B[5]
    D = _daily(m, cache)
    out = []
    for d in range(1, m.n_days):
        pdh, pdl = float(D.h[d - 1]), float(D.l[d - 1])
        wh, wl = _prior_week_hl(m, D, d)
        tests_h, tests_l = [], []
        done = False
        for j in _day_bars(b, d):
            if done:
                break
            h, l, c = float(b.h[j]), float(b.l[j]), float(b.c[j])
            in_cash = _in(b, j, T(8, 20), T(13, 30))
            fresh_up = j > int(b.b0[d]) and b.c[j - 1] <= pdh       # the first close above it, not a drift above
            fresh_dn = j > int(b.b0[d]) and b.c[j - 1] >= pdl
            if in_cash and c > pdh and fresh_up and len(tests_h) >= 2:
                j0 = max(int(b.b0[d]), j - 6)
                stop = float(np.min(b.l[j0:j])) - TICK if j > j0 else float(b.l[j]) - TICK
                tp = _tgt(1, c, stop, wh, 1.5, 2.0)
                if tp is not None and stop < c:
                    out.append(sig(b, j, 1, stop, "AF04_TESTED_PDH_BREAK", target_px=tp))
                done = True
                continue
            if in_cash and c < pdl and fresh_dn and len(tests_l) >= 2:
                j0 = max(int(b.b0[d]), j - 6)
                stop = float(np.max(b.h[j0:j])) + TICK if j > j0 else float(b.h[j]) + TICK
                tp = _tgt(-1, c, stop, wl, 1.5, 2.0)
                if tp is not None and stop > c:
                    out.append(sig(b, j, -1, stop, "AF04_TESTED_PDL_BREAK", target_px=tp))
                done = True
                continue
            if c <= pdh and h >= pdh * (1 - AF04_TEST) and (not tests_h or j - tests_h[-1] >= AF04_GAP):
                tests_h.append(j)
            if c >= pdl and l <= pdl * (1 + AF04_TEST) and (not tests_l or j - tests_l[-1] >= AF04_GAP):
                tests_l.append(j)
    return out


def af04_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ BO-01  BikoTrading: anchored VWAP from the last 4-hour swing, retested against the trend's direction and rejected
#     (15 minutes) ════════════════════════════════════════════════════════════════════════════════════════════════════

def _vwap_sums(m, cache):
    """Running sums of typical price x volume and of volume over the minute rows (Delta volume; 1 where missing)."""
    def calc():
        tp = (np.asarray(m.h, float) + np.asarray(m.l, float) + np.asarray(m.c, float)) / 3
        v = np.asarray(m.vol, float)
        v = np.where(np.isfinite(v) & (v > 0), v, 1.0)
        return np.r_[0.0, np.cumsum(tp * v)], np.r_[0.0, np.cumsum(v)]
    return _cached(cache, ("zg_vwap_sums",), calc)


def bo01(m, B, p, cache):
    b, h4 = B[15], B[240]
    cx = ctx(m, B, 15, cache)
    atr = cx.atr(14)
    hv, hi_i, lv, lo_i, phv, plv = _cached(cache, ("zg_bo01_piv",), lambda: _pivots(h4, 2))
    cpv, cv = _vwap_sums(m, cache)

    def _avwap_from(row0: int, row1: int) -> float:
        """VWAP of minute rows [row0, row1]."""
        return float((cpv[row1 + 1] - cpv[row0]) / (cv[row1 + 1] - cv[row0]))

    out = []
    used = set()
    for j in range(1, len(b.c)):
        q = _last_done(h4, b, j)
        if q < 1 or not _fin(hv[q], lv[q], phv[q], plv[q], atr[j]):
            continue
        if not _in(b, j, T(2, 0), T(16, 0)):
            continue
        down = hv[q] < phv[q] and lv[q] < plv[q]
        up = hv[q] > phv[q] and lv[q] > plv[q]
        if down:
            anchor = int(h4.i0[hi_i[q]])
            key = ("dn", anchor)
            if key in used or anchor >= int(b.i1[j]):
                continue
            vw = _avwap_from(anchor, int(b.i1[j]))
            if b.h[j] >= vw and b.c[j] < vw and b.c[j - 1] < vw:
                stop = float(b.h[j]) + 0.25 * float(atr[j])
                tp = _tgt(-1, float(b.c[j]), stop, float(lv[q]), 1.5, 2.0)
                if tp is not None:
                    out.append(sig(b, j, -1, stop, "BO01_AVWAP_RETEST_SHORT", target_px=tp))
                    used.add(key)
        elif up:
            anchor = int(h4.i0[lo_i[q]])
            key = ("up", anchor)
            if key in used or anchor >= int(b.i1[j]):
                continue
            vw = _avwap_from(anchor, int(b.i1[j]))
            if b.l[j] <= vw and b.c[j] > vw and b.c[j - 1] > vw:
                stop = float(b.l[j]) - 0.25 * float(atr[j])
                tp = _tgt(1, float(b.c[j]), stop, float(hv[q]), 1.5, 2.0)
                if tp is not None:
                    out.append(sig(b, j, 1, stop, "BO01_AVWAP_RETEST_LONG", target_px=tp))
                    used.add(key)
    return out


def bo01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ BO-02  BikoTrading: false breakout of a daily key level (the previous day's high / low or the last daily swing),
#     back inside: entry at the level, stop 2 pips beyond the tail, 4R (15 minutes) ════════════════════════════════════

BO02_NEAR = 0.50            # 'maximum 5 pips from the key level': a market entry within $0.50 of it, else a limit there
BO02_PIP2 = 0.20            # 'two pips above the tail' on gold
BO02_LOOK = 3               # the break may come up to three bars (45 minutes) before the close back inside


def bo02(m, B, p, cache):
    b = B[15]
    D = _daily(m, cache)
    dh_v, _, dl_v, _, _, _ = _cached(cache, ("zg_bo02_dpiv",), lambda: _pivots(D, 2))
    out = []
    for d in range(1, m.n_days):
        highs = {float(D.h[d - 1])}
        lows = {float(D.l[d - 1])}
        if np.isfinite(dh_v[d - 1]):
            highs.add(float(dh_v[d - 1]))
        if np.isfinite(dl_v[d - 1]):
            lows.add(float(dl_v[d - 1]))
        taken = set()
        first = {}                                      # level -> the first bar of the day that traded beyond it
        for j in _day_bars(b, d):
            if _ny(b, j) >= T(16, 0) and _ny(b, j) < T(17, 0):
                break
            c = float(b.c[j])
            for lv in highs:
                if b.h[j] > lv:
                    first.setdefault(("s", lv), j)
            for lv in lows:
                if b.l[j] < lv:
                    first.setdefault(("b", lv), j)
            for lv in sorted(highs):
                if ("s", lv) in taken or c >= lv or j - first.get(("s", lv), -99) > BO02_LOOK:
                    continue
                tail = _sweep_tail_short(b, j, lv, BO02_LOOK)
                if not np.isfinite(tail):
                    continue
                stop = tail + BO02_PIP2
                lim = None if lv - c <= BO02_NEAR else lv
                ref = c if lim is None else lim
                if not stop > ref:
                    continue
                out.append(sig(b, j, -1, stop, "BO02_FALSE_BREAK_HIGH", entry_limit=lim,
                               expire_k=int(b.i1[min(j + 4, int(b.b1[d]) - 1)]) if lim is not None else None))
                taken.add(("s", lv))
            for lv in sorted(lows, reverse=True):
                if ("b", lv) in taken or c <= lv or j - first.get(("b", lv), -99) > BO02_LOOK:
                    continue
                tail = _sweep_tail_long(b, j, lv, BO02_LOOK)
                if not np.isfinite(tail):
                    continue
                stop = tail - BO02_PIP2
                lim = None if c - lv <= BO02_NEAR else lv
                ref = c if lim is None else lim
                if not stop < ref:
                    continue
                out.append(sig(b, j, 1, stop, "BO02_FALSE_BREAK_LOW", entry_limit=lim,
                               expire_k=int(b.i1[min(j + 4, int(b.b1[d]) - 1)]) if lim is not None else None))
                taken.add(("b", lv))
    return out


def bo02_x(m, B, p, cache):
    return XExits(target_r=4.0)


# ═══ TO-01  Trading Orbit: daily 9-period MA side, a 1-hour Bollinger Band touch at the previous swing, a $15 stop
#     beyond the level, 1:5 (1 hour) ═══════════════════════════════════════════════════════════════════════════════════

TO01_STOP = 15.0            # '10 20 point' beyond the resistance: the middle of his range, in dollars
TO01_NEAR = 0.5             # the previous swing counts as 'around' the band within half an ATR(14)


def to01(m, B, p, cache):
    b = B[60]
    D = _daily(m, cache)
    sma9 = _cached(cache, ("zg_to01_sma9",), lambda: I.sma(np.asarray(D.c, float), 9))
    cx = ctx(m, B, 60, cache)
    mid, up, lo = cx.bollinger(20, 2.0)
    atr = cx.atr(14)
    hv, _, lv, _, _, _ = _cached(cache, ("zg_to01_piv",), lambda: _pivots(b, 2))
    out = []
    for j in range(20, len(b.c)):
        d = int(b.day[j])
        if d < 1 or not _fin(sma9[d - 1], up[j], lo[j], atr[j]):
            continue
        side = 1 if D.c[d - 1] > sma9[d - 1] else -1 if D.c[d - 1] < sma9[d - 1] else 0
        if j + 1 >= int(b.b1[d]):
            continue                                   # the limit lives in the next bar of the same day only
        nxt = int(b.i1[j + 1])
        if side < 0 and np.isfinite(hv[j]) and abs(hv[j] - up[j]) <= TO01_NEAR * atr[j] and b.c[j] < up[j]:
            lim = float(up[j])
            stop = max(float(hv[j]), lim) + TO01_STOP
            out.append(sig(b, j, -1, stop, "TO01_UPPER_BAND_AT_SWING", entry_limit=lim, expire_k=nxt))
        elif side > 0 and np.isfinite(lv[j]) and abs(lv[j] - lo[j]) <= TO01_NEAR * atr[j] and b.c[j] > lo[j]:
            lim = float(lo[j])
            stop = min(float(lv[j]), lim) - TO01_STOP
            out.append(sig(b, j, 1, stop, "TO01_LOWER_BAND_AT_SWING", entry_limit=lim, expire_k=nxt))
    return out


def to01_x(m, B, p, cache):
    return XExits(target_r=5.0)


# ═══ PF-01  PropFirmTrader (Claudia): a 30-minute engulfing candle's body as the zone, a 5-minute pull back into it,
#     then two highs broken (lows for sells); stop beyond the pull back, target the previous high (5 minutes) ══════════

PF01_LIFE = 16              # the zone is watched for 16 thirty-minute bars (8 hours) after the engulfing candle
PF01_PREV = 12              # 'the previous high': the highest of the 12 thirty-minute bars before the engulfing one


def pf01(m, B, p, cache):
    b30, b = B[30], B[5]
    out = []
    j5 = 0
    n5 = len(b.c)
    for e in range(1, len(b30.c)):
        if b30.day[e] != b30.day[e - 1]:
            continue
        bull = b30.c[e] > b30.o[e] and b30.c[e - 1] < b30.o[e - 1] and b30.c[e] >= b30.o[e - 1] and b30.o[e] <= b30.c[e - 1]
        bear = b30.c[e] < b30.o[e] and b30.c[e - 1] > b30.o[e - 1] and b30.c[e] <= b30.o[e - 1] and b30.o[e] >= b30.c[e - 1]
        if not (bull or bear):
            continue
        side = 1 if bull else -1
        z_open, z_close = float(b30.o[e]), float(b30.c[e])
        e0 = max(0, e - PF01_PREV)
        prev_ext = float(np.max(b30.h[e0:e])) if side > 0 else float(np.min(b30.l[e0:e]))
        end_row = int(b30.i1[min(e + PF01_LIFE, len(b30.c) - 1)])
        while j5 < n5 and b.i1[j5] <= b30.i1[e]:
            j5 += 1
        tapped, breaks, ext = False, 0, np.nan
        last_break_hi = np.nan
        for j in range(j5, n5):
            if b.i1[j] > end_row or b.day[j] != b30.day[e]:
                break
            if side > 0:
                if b.c[j] < z_open:
                    break                                   # below the candle's open: no trade
                if not tapped:
                    if b.l[j] <= z_close:
                        tapped, ext = True, float(b.l[j])
                    continue
                ext = min(ext, float(b.l[j]))
                if j >= 3 and b.c[j] > np.max(b.h[j - 3:j]) and not (np.isfinite(last_break_hi) and b.h[j] <= last_break_hi):
                    breaks += 1
                    last_break_hi = float(b.h[j])
                if breaks >= 2:
                    stop = ext - TICK
                    tp = _tgt(1, float(b.c[j]), stop, prev_ext, 1.0, 2.0)
                    if tp is not None:
                        out.append(sig(b, j, 1, stop, "PF01_ENGULF_ZONE_LONG", target_px=tp))
                    break
            else:
                if b.c[j] > z_open:
                    break
                if not tapped:
                    if b.h[j] >= z_close:
                        tapped, ext = True, float(b.h[j])
                    continue
                ext = max(ext, float(b.h[j]))
                if j >= 3 and b.c[j] < np.min(b.l[j - 3:j]) and not (np.isfinite(last_break_hi) and b.l[j] >= last_break_hi):
                    breaks += 1
                    last_break_hi = float(b.l[j])
                if breaks >= 2:
                    stop = ext + TICK
                    tp = _tgt(-1, float(b.c[j]), stop, prev_ext, 1.0, 2.0)
                    if tp is not None:
                        out.append(sig(b, j, -1, stop, "PF01_ENGULF_ZONE_SHORT", target_px=tp))
                    break
    out.sort(key=lambda s: (s.k, s.side))
    return out


def pf01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ MA-02  The Moving Average: daily Heikin Ashi direction, a 1-hour Heikin Ashi candle with no wick against it and a
#     larger body beyond the previous day's extreme; held until an opposite-colour candle closes (1 hour, swing) ════════

def _ha_arrays(b, cache, key):
    return _cached(cache, key, lambda: I.ha_ohlc(b))


def ma02(m, B, p, cache):
    b = B[60]
    D = _daily(m, cache)
    dho, _, _, dhc = _ha_arrays(D, cache, ("zg_ma02_dha",))
    ho, hh, hl, hc = _ha_arrays(b, cache, ("zg_ma02_ha",))
    body = np.abs(hc - ho)
    avg = I.mean_prev(body, 10)
    out = []
    for j in range(11, len(b.c)):
        d = int(b.day[j])
        if d < 1 or not _fin(avg[j]):
            continue
        dside = 1 if dhc[d - 1] > dho[d - 1] else -1 if dhc[d - 1] < dho[d - 1] else 0
        green, red = hc[j] > ho[j], hc[j] < ho[j]
        nowick_dn = hl[j] >= ho[j] - 1e-9 * abs(ho[j])
        nowick_up = hh[j] <= ho[j] + 1e-9 * abs(ho[j])
        big = body[j] > avg[j]
        c = float(b.c[j])
        if dside > 0 and green and nowick_dn and big and c > D.h[d - 1]:
            out.append(sig(b, j, 1, c * (1 - CATASTROPHE), "MA02_HA_NOWICK_LONG",
                           info={"stop_frac": CATASTROPHE, "risk_unit": c * ALL_IN}))
        elif dside < 0 and red and nowick_up and big and c < D.l[d - 1]:
            out.append(sig(b, j, -1, c * (1 + CATASTROPHE), "MA02_HA_NOWICK_SHORT",
                           info={"stop_frac": CATASTROPHE, "risk_unit": c * ALL_IN}))
    return out


def ma02_x(m, B, p, cache):
    b = B[60]
    ho, _, _, hc = _ha_arrays(b, cache, ("zg_ma02_ha",))
    return XExits(target_r=None, xbars=b, xlong=hc < ho, xshort=hc > ho)


# ═══ MA-03  The Moving Average: XAUUSD 5-minute scalp - smoothed MAs 21/50/200 fanned out, RSI(14) on the trend's side,
#     a three-line strike (three candles against the trend, then an engulfing candle with it); stop twice the engulfing
#     candle, out on an RSI divergence or after six candles (5 minutes) ═════════════════════════════════════════════════

MA03_FAN = 0.0005           # 'fanned out at a nice slope': the SMMA 50 moved at least 0.05% over the last 12 bars


def _ma03_arr(m, B, cache):
    def calc():
        b = B[5]
        c = np.asarray(b.c, float)
        return (YI.rma(c, 21), YI.rma(c, 50), YI.rma(c, 200), I.rsi(c, 14))
    return _cached(cache, ("zg_ma03",), calc)


def ma03(m, B, p, cache):
    b = B[5]
    s21, s50, s200, r = _ma03_arr(m, B, cache)
    o, c, h, l = (np.asarray(x, float) for x in (b.o, b.c, b.h, b.l))
    out = []
    for j in range(215, len(c)):
        if not _fin(s21[j], s50[j], s200[j], s50[j - 12], r[j]):
            continue
        slope = (s50[j] - s50[j - 12]) / s50[j - 12]
        if b.day[j - 3] != b.day[j]:
            continue
        up = c[j] > s200[j] and s21[j] > s50[j] > s200[j] and slope >= MA03_FAN and r[j] > 50
        dn = c[j] < s200[j] and s21[j] < s50[j] < s200[j] and slope <= -MA03_FAN and r[j] < 50
        rng = h[j] - l[j]
        if not rng > 0:
            continue
        if up and all(c[k] < o[k] for k in (j - 3, j - 2, j - 1)) and c[j] > o[j]:
            move = o[j - 3] - c[j - 1]
            if move > 0 and c[j] >= c[j - 1] + 0.5 * move and c[j] > o[j - 1]:
                out.append(sig(b, j, 1, float(c[j] - 2 * rng), "MA03_THREE_LINE_STRIKE_LONG", info={"stop_dist": 2 * rng}))
        elif dn and all(c[k] > o[k] for k in (j - 3, j - 2, j - 1)) and c[j] < o[j]:
            move = c[j - 1] - o[j - 3]
            if move > 0 and c[j] <= c[j - 1] - 0.5 * move and c[j] < o[j - 1]:
                out.append(sig(b, j, -1, float(c[j] + 2 * rng), "MA03_THREE_LINE_STRIKE_SHORT", info={"stop_dist": 2 * rng}))
    return out


def _div_flags(b, cache, key, look=10):
    """Per 5-minute bar: (bearish divergence: a close above the highest close of the previous `look` bars with a lower
    RSI(14) than at that high; bullish: the mirror). Known at the bar's close."""
    def calc():
        c = np.asarray(b.c, float)
        r = I.rsi(c, 14)
        N = len(c)
        bear = np.zeros(N, bool)
        bull = np.zeros(N, bool)
        for j in range(look + 1, N):
            w = c[j - look:j]
            if not np.isfinite(r[j]):
                continue
            ih = int(np.argmax(w)) + j - look
            il = int(np.argmin(w)) + j - look
            if c[j] > c[ih] and np.isfinite(r[ih]) and r[j] < r[ih]:
                bear[j] = True
            if c[j] < c[il] and np.isfinite(r[il]) and r[j] > r[il]:
                bull[j] = True
        return bear, bull
    return _cached(cache, key, calc)


def ma03_x(m, B, p, cache):
    b = B[5]
    bear, bull = _div_flags(b, cache, ("zg_ma03_div",))
    return XExits(target_r=None, xbars=b, xlong=bear, xshort=bull, max_hold=30)


# ═══ MA-04  The Moving Average: RSI(14) leaves 70 / 30 and comes back inside: sell (buy) the first close back inside,
#     stop beyond the swing it made, 2R (15 minutes) ════════════════════════════════════════════════════════════════════

def ma04(m, B, p, cache):
    b = B[15]
    r = ctx(m, B, 15, cache).rsi(14)
    out = []
    ext_h = ext_l = np.nan
    out_hi = out_lo = False
    for j in range(15, len(b.c)):
        if not np.isfinite(r[j]):
            continue
        if r[j] > 70:
            ext_h = max(ext_h, float(b.h[j])) if out_hi else float(b.h[j])
            out_hi = True
            continue
        if r[j] < 30:
            ext_l = min(ext_l, float(b.l[j])) if out_lo else float(b.l[j])
            out_lo = True
            continue
        if out_hi:
            stop = max(ext_h, float(b.h[j])) + TICK
            out.append(sig(b, j, -1, stop, "MA04_RSI_BACK_BELOW_70"))
            out_hi = False
        if out_lo:
            stop = min(ext_l, float(b.l[j])) - TICK
            out.append(sig(b, j, 1, stop, "MA04_RSI_BACK_ABOVE_30"))
            out_lo = False
    return out


def ma04_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ TU-01  TTrades: after 8:30 New York an hour sweeps the previous day's high (low) and closes back inside; a 5-minute
#     fair value gap in the premium (discount) of the move that followed; stop on the intermediate high, 2R (5 minutes) ═

def tu01(m, B, p, cache):
    b, h1 = B[5], B[60]
    D = _daily(m, cache)
    out = []
    for d in range(1, m.n_days):
        pdh, pdl = float(D.h[d - 1]), float(D.l[d - 1])
        side, sweep_k = 0, None
        for q in _day_bars(h1, d):
            if not (T(8, 0) <= _ny(h1, q) <= T(10, 0)):
                continue
            if h1.h[q] > pdh and pdl < h1.c[q] < pdh:
                side, sweep_k = -1, q
                break
            if h1.l[q] < pdl and pdl < h1.c[q] < pdh:
                side, sweep_k = 1, q
                break
        if not side:
            continue
        ext = float(h1.h[sweep_k]) if side < 0 else float(h1.l[sweep_k])
        js = [j for j in _day_bars(b, d) if b.i1[j] > h1.i1[sweep_k] and _ny(b, j) < T(12, 0)]
        swing = np.nan                                  # the low (high) made after the sweep hour, so far
        top = np.nan                                    # the highest high (lowest low) since that swing: the intermediate high
        for j in js:
            if j < 2 or b.day[j - 2] != d:
                continue
            if side < 0:
                if not np.isfinite(swing) or b.l[j] < swing:
                    swing, top = float(b.l[j]), float(b.h[j])
                    continue
                top = max(top, float(b.h[j]))
                fifty = swing + 0.5 * (ext - swing)
                if b.l[j - 2] > b.h[j] and b.l[j - 2] >= fifty:
                    lim = float(b.h[j])
                    stop = top + TICK
                    if stop > lim:
                        out.append(sig(b, j, -1, stop, "TU01_PDH_SWEEP_FVG_SHORT", entry_limit=lim,
                                       expire_k=int(b.i1[min(j + 6, int(b.b1[d]) - 1)])))
                    break
            else:
                if not np.isfinite(swing) or b.h[j] > swing:
                    swing, top = float(b.h[j]), float(b.l[j])
                    continue
                top = min(top, float(b.l[j]))
                fifty = swing - 0.5 * (swing - ext)
                if b.h[j - 2] < b.l[j] and b.h[j - 2] <= fifty:
                    lim = float(b.l[j])
                    stop = top - TICK
                    if stop < lim:
                        out.append(sig(b, j, 1, stop, "TU01_PDL_SWEEP_FVG_LONG", entry_limit=lim,
                                       expire_k=int(b.i1[min(j + 6, int(b.b1[d]) - 1)])))
                    break
    return out


def tu01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ TU-02  TTrades fractal model: an hour sweeps the previous hour's high (low) and closes back inside its range
#     (candle 2 closure); in the next two hours a 5-minute close through the run of up-close (down-close) candles that
#     made the high (change in the state of delivery); stop on the high, 2R; London and New York morning (5 minutes) ══

def _cisd_open(o, c, h, k_hi: int, side: int) -> float:
    """The open of the first candle of the run of up-close (side -1) / down-close (side +1) candles ending at k_hi."""
    k = k_hi
    if side < 0:
        while k - 1 >= 0 and c[k - 1] > o[k - 1]:
            k -= 1
    else:
        while k - 1 >= 0 and c[k - 1] < o[k - 1]:
            k -= 1
    return float(o[k])


def tu02(m, B, p, cache):
    b, h1 = B[5], B[60]
    o, c, h, l = (np.asarray(x, float) for x in (b.o, b.c, b.h, b.l))
    out = []
    j5 = 0
    n5 = len(c)
    for q in range(1, len(h1.c)):
        if h1.day[q] != h1.day[q - 1]:
            continue
        bear = h1.h[q] > h1.h[q - 1] and h1.l[q - 1] < h1.c[q] < h1.h[q - 1]
        bull = h1.l[q] < h1.l[q - 1] and h1.l[q - 1] < h1.c[q] < h1.h[q - 1]
        if not (bear or bull) or (bear and bull):
            continue
        side = -1 if bear else 1
        last = min(q + 2, len(h1.c) - 1)
        if h1.day[last] != h1.day[q]:
            last = q + 1 if q + 1 < len(h1.c) and h1.day[q + 1] == h1.day[q] else q
        if last == q:
            continue
        while j5 < n5 and b.i1[j5] <= h1.i1[q]:
            j5 += 1
        ext, k_ext = np.nan, -1
        for j in range(j5, n5):
            if b.i1[j] > h1.i1[last]:
                break
            if side < 0:
                if not np.isfinite(ext) or h[j] > ext:
                    ext, k_ext = float(h[j]), j
                    continue
                lvl = _cisd_open(o, c, h, k_ext, -1)
                if c[j] < lvl and (_in(b, j, T(2, 0), T(5, 0)) or _in(b, j, T(8, 0), T(11, 30))):
                    out.append(sig(b, j, -1, ext + TICK, "TU02_C2_CISD_SHORT"))
                    break
            else:
                if not np.isfinite(ext) or l[j] < ext:
                    ext, k_ext = float(l[j]), j
                    continue
                lvl = _cisd_open(o, c, h, k_ext, 1)
                if c[j] > lvl and (_in(b, j, T(2, 0), T(5, 0)) or _in(b, j, T(8, 0), T(11, 30))):
                    out.append(sig(b, j, 1, ext - TICK, "TU02_C2_CISD_LONG"))
                    break
    out.sort(key=lambda s: (s.k, s.side))
    seen, uniq = set(), []                              # two hourly setups can point at the same 5-minute candle
    for s in out:
        if (s.k, s.side) not in seen:
            seen.add((s.k, s.side))
            uniq.append(s)
    return uniq


def tu02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ CA-01  Cammy Capital: New York open - the overnight volume profile (18:00-09:30) against the session's developing
#     profile at 10:00; when value has moved away, fade back to the overnight point of control, target the developing
#     value area's far edge (5 minutes) ════════════════════════════════════════════════════════════════════════════════

CA_BIN = 0.50               # volume-profile bins of 50 cents
CA01_STOP = 0.5             # stop beyond the level by half the developing value area (at least $1.50): 'behind the node'


def _ca01_levels(m, d, cache):
    key = ("zg_ca01_lv", d)
    if key in cache:
        return cache[key]
    on = _rows_between(m, d, T(18, 0), T(9, 30), evening=True)
    dv = _rows_between(m, d, T(9, 30), T(10, 0))
    res = None
    if on is not None and dv is not None and (dv[1] - dv[0]) >= 25:
        res = (_profile(m, on[0], on[1], CA_BIN), _profile(m, dv[0], dv[1], CA_BIN), dv[1] - 1)
    cache[key] = res
    return res


def ca01(m, B, p, cache):
    b = B[5]
    out = []
    for d in range(m.n_days):
        lv = _ca01_levels(m, d, cache)
        if lv is None:
            continue
        (on_poc, on_vah, on_val), (d_poc, d_vah, d_val), last_row = lv
        if not _fin(on_poc, d_poc, d_vah, d_val):
            continue
        js = [j for j in _day_bars(b, d) if int(b.i1[j]) == last_row]
        if not js:
            continue
        j = js[0]
        if _ny_end(b, j) != T(10, 0):
            continue
        width = max(d_vah - d_val, CA_BIN)
        buf = max(CA01_STOP * width, 1.50)
        exp = [k for k in _day_bars(b, d) if _ny(b, k) < T(11, 30)]
        expire = int(b.i1[exp[-1]]) if exp else int(b.i1[j])
        if d_poc < on_poc and on_poc >= d_poc + 0.75 * (d_vah - d_poc) and on_poc > b.c[j]:
            stop = on_poc + buf
            tp = d_val
            if (on_poc - tp) >= (stop - on_poc):
                out.append(sig(b, j, -1, stop, "CA01_ON_POC_PREMIUM_SHORT", entry_limit=on_poc, expire_k=expire,
                               target_px=tp))
        elif d_poc > on_poc and on_poc <= d_poc - 0.75 * (d_poc - d_val) and on_poc < b.c[j]:
            stop = on_poc - buf
            tp = d_vah
            if (tp - on_poc) >= (on_poc - stop):
                out.append(sig(b, j, 1, stop, "CA01_ON_POC_DISCOUNT_LONG", entry_limit=on_poc, expire_k=expire,
                               target_px=tp))
    return out


def ca01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ CA-02  Cammy Capital: yesterday's premium is today's discount - the developing session value area low reaches the
#     previous regular session's value area high (or the high reaches its low); a limit there, stop near yesterday's
#     point of control, target the session value area's far edge (5 minutes) ═══════════════════════════════════════════

def _rth_profile(m, d, cache):
    key = ("zg_ca02_rth", d)
    if key not in cache:
        rows = _rows_between(m, d, T(9, 30), T(16, 0))
        cache[key] = _profile(m, rows[0], rows[1], CA_BIN) if rows and rows[1] - rows[0] >= 60 else (np.nan,) * 3
    return cache[key]


class _Prof:
    """A volume profile grown minute by minute on absolute bins of `width` dollars (the bins _profile uses), so a
    session's developing profile costs one pass over its minutes."""

    def __init__(self, width: float):
        self.w = width
        self.vol: dict[int, float] = {}

    def add(self, lo: float, hi: float, v: float) -> None:
        i0 = int(np.floor(lo / self.w + 1e-9))
        i1 = int(np.floor(hi / self.w + 1e-9))
        share = v / (i1 - i0 + 1)
        for i in range(i0, i1 + 1):
            self.vol[i] = self.vol.get(i, 0.0) + share

    def levels(self):
        if not self.vol:
            return np.nan, np.nan, np.nan
        k0, k1 = min(self.vol), max(self.vol)
        vol = np.array([self.vol.get(k, 0.0) for k in range(k0, k1 + 1)])
        poc = int(np.argmax(vol))
        total, acc = vol.sum(), vol[poc]
        lo_i = hi_i = poc
        nb = len(vol)
        while acc < 0.70 * total and (lo_i > 0 or hi_i < nb - 1):
            up = vol[hi_i + 1] if hi_i < nb - 1 else -1.0
            dn = vol[lo_i - 1] if lo_i > 0 else -1.0
            if up >= dn:
                hi_i += 1
                acc += vol[hi_i]
            else:
                lo_i -= 1
                acc += vol[lo_i]
        return (float((k0 + poc + 0.5) * self.w), float((k0 + hi_i + 1) * self.w), float((k0 + lo_i) * self.w))


def ca02(m, B, p, cache):
    b = B[5]
    out = []
    vols = np.asarray(m.vol, float)
    for d in range(1, m.n_days):
        p_poc, p_vah, p_val = _rth_profile(m, d - 1, cache)
        if not _fin(p_poc, p_vah, p_val) or p_vah <= p_val:
            continue
        ovn = _rows_between(m, d, T(18, 0), T(9, 30), evening=True)
        rth = _rows_between(m, d, T(9, 30), T(16, 0))
        got = False
        prof, s0, fed = None, None, None
        for j in _day_bars(b, d):
            if got:
                break
            t = _ny(b, j)
            if T(16, 0) <= t < T(17, 0):
                break
            # the current session: the overnight one from 18:00, the regular one from 09:30
            sess = rth if T(9, 30) <= t < T(16, 0) else ovn
            if sess is None or int(b.i1[j]) < sess[0]:
                continue
            if s0 != sess[0]:
                prof, s0, fed = _Prof(CA_BIN), sess[0], sess[0]
            z = int(b.i1[j]) + 1
            for r in range(fed, z):
                vv = vols[r]
                prof.add(float(m.l[r]), float(m.h[r]), vv if np.isfinite(vv) and vv > 0 else 1.0)
            fed = z
            if z - s0 < 30:
                continue
            c_poc, c_vah, c_val = prof.levels()
            if not _fin(c_poc, c_vah, c_val):
                continue
            open_px = float(m.o[s0])
            tol = 0.25 * (p_vah - p_val)
            if open_px >= p_poc and abs(c_val - p_vah) <= tol and b.c[j] > p_vah:
                stop = p_poc - TICK
                tp = c_vah
                if tp - p_vah >= p_vah - stop > 0:
                    out.append(sig(b, j, 1, stop, "CA02_PDVAH_IS_DISCOUNT_LONG", entry_limit=p_vah,
                                   expire_k=int(b.i1[min(j + 6, int(b.b1[d]) - 1)]), target_px=tp))
                    got = True
            elif open_px <= p_poc and abs(c_vah - p_val) <= tol and b.c[j] < p_val:
                stop = p_poc + TICK
                tp = c_val
                if p_val - tp >= stop - p_val > 0:
                    out.append(sig(b, j, -1, stop, "CA02_PDVAL_IS_PREMIUM_SHORT", entry_limit=p_val,
                                   expire_k=int(b.i1[min(j + 6, int(b.b1[d]) - 1)]), target_px=tp))
                    got = True
    return out


def ca02_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ HF-01  HANNAH FOREX: sweep, break, retest - in the 1-hour trend, a 5-minute sweep of the last swing low (high), a
#     close through the swing high (low), a limit at half of that leg; stop beyond the sweep, target the last 1-hour high
#     (low); London and New York kill zones (5 minutes) ═════════════════════════════════════════════════════════════════

HF01_WAIT = 12              # the break must come within 12 bars (an hour) of the sweep, the retest within 12 more


def hf01(m, B, p, cache):
    b, h1 = B[5], B[60]
    hv1, _, lv1, _, phv1, plv1 = _cached(cache, ("zg_hf01_p1",), lambda: _pivots(h1, 2))
    hv, _, lv, _, _, _ = _cached(cache, ("zg_hf01_p5",), lambda: _pivots(b, 2))
    out = []
    N = len(b.c)
    j = 3
    while j < N:
        q = _last_done(h1, b, j)
        kz = _in(b, j, T(2, 0), T(5, 0)) or _in(b, j, T(7, 0), T(10, 0))
        if q < 1 or not kz or not _fin(hv1[q], lv1[q], phv1[q], plv1[q], hv[j - 1], lv[j - 1]):
            j += 1
            continue
        bull = hv1[q] > phv1[q] and lv1[q] > plv1[q]
        bear = hv1[q] < phv1[q] and lv1[q] < plv1[q]
        nxt = j + 1                                     # where the scan resumes: after the break bar once a break is found
        if bull and b.l[j] < lv[j - 1]:
            sweep = float(b.l[j])
            internal = float(hv[j - 1])
            d = int(b.day[j])
            for k in range(j + 1, min(j + 1 + HF01_WAIT, N)):
                if b.day[k] != d:
                    break
                sweep = min(sweep, float(b.l[k]))
                if b.c[k] > internal:
                    top = float(np.max(b.h[j:k + 1]))
                    lim = sweep + 0.5 * (top - sweep)
                    stop = sweep - TICK
                    tp = _tgt(1, lim, stop, float(hv1[q]), 1.5, 2.0)
                    if tp is not None and lim < b.c[k]:
                        out.append(sig(b, k, 1, stop, "HF01_SBR_LONG", entry_limit=lim,
                                       expire_k=int(b.i1[min(k + HF01_WAIT, int(b.b1[d]) - 1)]), target_px=tp))
                    nxt = k + 1
                    break
        elif bear and b.h[j] > hv[j - 1]:
            sweep = float(b.h[j])
            internal = float(lv[j - 1])
            d = int(b.day[j])
            for k in range(j + 1, min(j + 1 + HF01_WAIT, N)):
                if b.day[k] != d:
                    break
                sweep = max(sweep, float(b.h[k]))
                if b.c[k] < internal:
                    bot = float(np.min(b.l[j:k + 1]))
                    lim = sweep - 0.5 * (sweep - bot)
                    stop = sweep + TICK
                    tp = _tgt(-1, lim, stop, float(lv1[q]), 1.5, 2.0)
                    if tp is not None and lim > b.c[k]:
                        out.append(sig(b, k, -1, stop, "HF01_SBR_SHORT", entry_limit=lim,
                                       expire_k=int(b.i1[min(k + HF01_WAIT, int(b.b1[d]) - 1)]), target_px=tp))
                    nxt = k + 1
                    break
        j = nxt
    out.sort(key=lambda s: (s.k, s.side))
    return out


def hf01_x(m, B, p, cache):
    return XExits(target_r=2.0)


# ═══ RU-10  Trading Rush: Donchian Channel (20) with the 200-period moving average - buy when the upper band makes a
#     new high after the lower band made a new low (mirror for sells), stop just beyond the other band, 1.5R
#     (30 minutes) ═════════════════════════════════════════════════════════════════════════════════════════════════════

RU10_FAR = 3.0              # 'if the entry and stop-loss are far away from each other, skip': beyond 3 ATR(14)


def ru10(m, B, p, cache):
    b = B[30]
    cx = ctx(m, B, 30, cache)
    e200 = cx.ema(200)
    atr = cx.atr(14)
    h, l, c = (np.asarray(x, float) for x in (b.h, b.l, b.c))
    upper = I.highest(h, 20)
    lower = I.lowest(l, 20)
    out = []
    last = 0                                            # +1: the upper band last made a new high, -1: the lower band a new low
    for j in range(21, len(c)):
        if not _fin(upper[j], lower[j], upper[j - 1], lower[j - 1]):
            continue
        rose, fell = upper[j] > upper[j - 1], lower[j] < lower[j - 1]
        if rose and last == -1 and _fin(e200[j], atr[j]) and c[j] > e200[j]:
            stop = float(lower[j]) - TICK
            if 0 < c[j] - stop <= RU10_FAR * atr[j]:
                out.append(sig(b, j, 1, stop, "RU10_DONCHIAN_LONG"))
        if fell and last == 1 and _fin(e200[j], atr[j]) and c[j] < e200[j]:
            stop = float(upper[j]) + TICK
            if 0 < stop - c[j] <= RU10_FAR * atr[j]:
                out.append(sig(b, j, -1, stop, "RU10_DONCHIAN_SHORT"))
        if rose and not fell:
            last = 1
        elif fell and not rose:
            last = -1
    return out


def ru10_x(m, B, p, cache):
    return XExits(target_r=1.5)


# ═══ TQ-05  Trade Pro: triple Supertrend (12/3, 11/2, 10/1) with the Stochastic RSI (3, 3, 14, 14) and the 200 EMA -
#     a Stochastic RSI cross out of 20 (80) with two Supertrends on the trade's side, stop at the second Supertrend
#     line, 1.5R (1 hour) ══════════════════════════════════════════════════════════════════════════════════════════════

def _tq05_arr(m, B, cache):
    def calc():
        b = B[60]
        c = np.asarray(b.c, float)
        k, dd = YI.stoch_rsi(c, 14, 14, 3, 3)
        sts = [YI.supertrend(b, n, f) for n, f in ((12, 3.0), (11, 2.0), (10, 1.0))]
        return I.ema(c, 200), k, dd, sts
    return _cached(cache, ("zg_tq05",), calc)


def tq05(m, B, p, cache):
    b = B[60]
    e200, k, dd, sts = _tq05_arr(m, B, cache)
    c = np.asarray(b.c, float)
    out = []
    armed = 0                                           # +1 after a cross up out of 20, -1 after a cross down out of 80
    for j in range(1, len(c)):
        if not _fin(k[j], dd[j], k[j - 1], dd[j - 1]):
            continue
        if k[j - 1] <= dd[j - 1] and k[j] > dd[j] and min(k[j - 1], dd[j - 1]) < 20:
            armed = 1
        elif k[j - 1] >= dd[j - 1] and k[j] < dd[j] and max(k[j - 1], dd[j - 1]) > 80:
            armed = -1
        if armed > 0 and k[j] >= 50:
            armed = 0
        if armed < 0 and k[j] <= 50:
            armed = 0
        if not armed or not np.isfinite(e200[j]):
            continue
        lines = [(float(ln[j]), int(dr[j])) for ln, dr in sts if np.isfinite(ln[j])]
        if armed > 0 and c[j] > e200[j]:
            below = sorted((v for v, dr in lines if dr == 1 and v < c[j]), reverse=True)
            if len(below) >= 2:
                out.append(sig(b, j, 1, below[1] - TICK, "TQ05_TRIPLE_ST_LONG"))
                armed = 0
        elif armed < 0 and c[j] < e200[j]:
            above = sorted(v for v, dr in lines if dr == -1 and v > c[j])
            if len(above) >= 2:
                out.append(sig(b, j, -1, above[1] + TICK, "TQ05_TRIPLE_ST_SHORT"))
                armed = 0
    return out


def tq05_x(m, B, p, cache):
    return XExits(target_r=1.5)
