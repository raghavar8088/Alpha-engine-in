"""Shared pieces of the channel-shortlist study (Nov 2026): extra indicators (BB Trend, zero-lag MACD, Hull MA,
Connors RSI, floor pivots, CPR, Point & Figure), small candle helpers, and the pool contexts the stock books read.

Conventions are the 11- and 20-channel studies' (yc_common): fn(m, B, p, cache) -> list of Signal from completed bars
only; a signal carries its bar's last row, so orders start on the next row; a swing pivot of n bars is used only n bars
after it. Volume caveat: the desk's index (Nifty, Bank Nifty), Nasdaq and FX feeds carry a placeholder volume of 1 per
minute, so a VWAP there is time-weighted; bitcoin and NSE stocks carry real volume.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
for _p in (HERE, RESEARCH / "youtube_intraday4_2026_11", RESEARCH / "youtube_channels20_2026_11",
           RESEARCH / "youtube_channels11_2026_11", RESEARCH / "youtube_top20_2026_11", RESEARCH / "booming_bulls_2026_11",
           RESEARCH / "crypto_playlist_2026_11"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402

import yc_ind as I  # noqa: E402
import yt_ind as YI  # noqa: E402
from yc_common import bars_of_day, body, ctx, green, red, rng, sig  # noqa: E402,F401
from yt_engine import Signal  # noqa: E402,F401
import zd_common as Z  # noqa: E402

T = lambda h, mi: h * 60 + mi  # noqa: E731
NSE_OPEN = T(9, 15)


def sorted_out(out):
    out.sort(key=lambda s: (s.k, s.side, s.setup))
    return out


def ny_min(b, j) -> int:
    return int(b.ny0[j])


def utc_min(b, j) -> int:
    return int((int(b.t0[j]) // 60) % 1440)


def uw(b, j) -> float:
    return float(b.h[j] - max(b.o[j], b.c[j]))


def lw(b, j) -> float:
    return float(min(b.o[j], b.c[j]) - b.l[j])


def pin_bar(b, j, side: int, wick=2.0, share=0.6) -> bool:
    """A bullish (side +1) pin bar: lower wick at least `wick` x the body and at least `share` of the range."""
    r = rng(b, j)
    if not r > 0:
        return False
    w = lw(b, j) if side > 0 else uw(b, j)
    return w >= wick * body(b, j) and w >= share * r


def engulf(b, j, side: int) -> bool:
    if j < 1:
        return False
    if side > 0:
        return green(b, j) and red(b, j - 1) and b.c[j] >= b.o[j - 1] and b.o[j] <= b.c[j - 1]
    return red(b, j) and green(b, j - 1) and b.c[j] <= b.o[j - 1] and b.o[j] >= b.c[j - 1]


# ── indicators ──────────────────────────────────────────────────────────────────────────────────────────────────────

def ema(x, n):
    return I.ema(np.asarray(x, float), n)


def wma(x, n: int) -> np.ndarray:
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    w = np.arange(1, n + 1, dtype=float)
    w /= w.sum()
    out[n - 1:] = np.convolve(x, w[::-1], mode="valid")
    return out


def hma(x, n: int) -> np.ndarray:
    """Hull moving average: WMA(2 x WMA(n/2) - WMA(n), sqrt(n))."""
    x = np.asarray(x, float)
    a, b = wma(x, max(1, n // 2)), wma(x, n)
    raw = 2 * a - b
    out = np.full(len(x), np.nan)
    ok = np.flatnonzero(np.isfinite(raw))
    if len(ok):
        out[ok[0]:] = wma(raw[ok[0]:], max(1, int(round(np.sqrt(n)))))
    return out


def zlema(x, n: int) -> np.ndarray:
    """Zero-lag EMA = 2 x EMA - EMA(EMA)."""
    e1 = ema(x, n)
    e2 = ema(np.nan_to_num(e1, nan=float(np.asarray(x, float)[0])), n)
    return 2 * e1 - e2


def zl_macd(c, a=12, b=26, s=9):
    line = zlema(c, a) - zlema(c, b)
    ok = np.isfinite(line)
    signal = np.full(len(line), np.nan)
    if ok.any():
        i0 = int(np.flatnonzero(ok)[0])
        signal[i0:] = zlema(line[i0:], s)
    return line, signal


def bbtrend(c, short=20, long=50, k=2.0) -> np.ndarray:
    """John Bollinger's BBTrend: (|lower_s - lower_l| - |upper_s - upper_l|) / middle_s x 100."""
    ms, us, ls_ = YI.bollinger(np.asarray(c, float), short, k)
    _, ul, ll = YI.bollinger(np.asarray(c, float), long, k)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (np.abs(ls_ - ll) - np.abs(us - ul)) / ms * 100.0


def rsi(c, n: int) -> np.ndarray:
    return I.rsi(np.asarray(c, float), n)


def connors_rsi(c, n_rsi=3, n_streak=2, n_rank=100) -> np.ndarray:
    """Connors RSI = (RSI(close, 3) + RSI(up/down streak, 2) + percent rank of the 1-bar change over 100) / 3."""
    c = np.asarray(c, float)
    streak = np.zeros(len(c))
    for i in range(1, len(c)):
        if c[i] > c[i - 1]:
            streak[i] = streak[i - 1] + 1 if streak[i - 1] > 0 else 1
        elif c[i] < c[i - 1]:
            streak[i] = streak[i - 1] - 1 if streak[i - 1] < 0 else -1
    roc = np.r_[np.nan, c[1:] / c[:-1] - 1]
    rank = np.full(len(c), np.nan)
    for i in range(n_rank, len(c)):
        w = roc[i - n_rank:i]
        rank[i] = 100.0 * np.sum(w < roc[i]) / n_rank
    return (rsi(c, n_rsi) + rsi(streak, n_streak) + rank) / 3


def floor_pivots(H, L, C) -> dict:
    """TradingView 'Traditional' pivots: P, R1-R5, S1-S5."""
    P = (H + L + C) / 3
    return {"P": P, "R1": 2 * P - L, "S1": 2 * P - H, "R2": P + (H - L), "S2": P - (H - L),
            "R3": H + 2 * (P - L), "S3": L - 2 * (H - P), "R4": P * 3 + (H - 3 * L), "S4": P * 3 - (3 * H - L),
            "R5": P * 4 + (H - 4 * L), "S5": P * 4 - (4 * H - L)}


def cpr(H, L, C):
    P = (H + L + C) / 3
    BC = (H + L) / 2
    TC = 2 * P - BC
    return P, min(BC, TC), max(BC, TC)


def prev_day_hlc(m, d):
    """(high, low, close) of the previous trading day, or None."""
    return Z.prev_day_hl(m, d)


def day_pivots(m, cache) -> dict:
    """{day: floor pivots of the previous day}."""
    key = ("ze_piv",)
    if key not in cache:
        out = {}
        for d in range(1, m.n_days):
            pd = prev_day_hlc(m, d)
            if pd:
                out[d] = floor_pivots(*pd)
        cache[key] = out
    return cache[key]


def pivot_points_close(c, n: int):
    """Indices of closes lower (lows) / higher (highs) than the n closes on each side; known n bars later."""
    c = np.asarray(c, float)
    lo, hi = [], []
    for i in range(n, len(c) - n):
        w = c[i - n:i + n + 1]
        if not np.all(np.isfinite(w)):
            continue
        if c[i] == w.min() and np.sum(w == c[i]) == 1:
            lo.append(i)
        if c[i] == w.max() and np.sum(w == c[i]) == 1:
            hi.append(i)
    return lo, hi


def pnf_columns(prices, box_pct: float, rev: int = 3, ref: float | None = None):
    """Point & Figure from a price sequence (close-only), box = box_pct of `ref` (the first price by default),
    `rev`-box reversal. Returns per price index: (column direction +1 X / -1 O, current column extreme, list of
    finished columns as (dir, top, bottom))."""
    p = np.asarray(prices, float)
    if not len(p):
        return []
    box = (ref or float(p[0])) * box_pct
    out, cols = [], []
    d, top, bot = 0, float(p[0]), float(p[0])
    for x in p:
        if d >= 0 and x >= top + box:
            top += box * int((x - top) // box)
            d = 1 if d == 0 else d
        elif d <= 0 and x <= bot - box:
            bot -= box * int((bot - x) // box)
            d = -1 if d == 0 else d
        elif d == 1 and x <= top - rev * box:
            cols.append((1, top, bot))
            d, bot = -1, top - box * int((top - x) // box)
            top = top - box
        elif d == -1 and x >= bot + rev * box:
            cols.append((-1, top, bot))
            d, top = 1, bot + box * int((x - bot) // box)
            bot = bot + box
        out.append((d, top, bot, list(cols)))
    return out


# ── pool contexts (the stock books' cross-section; each value uses only data known at its time) ─────────────────

def rank930(pool) -> dict:
    """{date: [(score, name, change)]}: change from the previous close at 09:30 divided by the stock's mean daily range
    (high-low over close) of the previous 20 sessions, for DF-01's momentum universe."""
    by: dict = {}
    for m in pool:
        rngs = []
        for d in range(m.n_days):
            a, z = int(m.d0[d]), int(m.d1[d])
            if z > a and m.c[z - 1] > 0:
                rngs.append(float((m.h[a:z].max() - m.l[a:z].min()) / m.c[z - 1]))
            else:
                rngs.append(np.nan)
            if d < 21:
                continue
            pc = Z.prev_close(m, d)
            c930 = Z._close_at(m, d, T(9, 30))
            mr = np.nanmean(rngs[d - 20:d])
            if pc > 0 and np.isfinite(c930) and mr > 0:
                ch = c930 / pc - 1
                by.setdefault(str(m.date[d]), []).append((ch / mr, m.name, ch))
    return by


def nifty_side930(nifty) -> dict:
    """{date: +1 / -1 / 0}: NIFTY's close at 09:30 against the previous close."""
    out = {}
    if nifty is None:
        return out
    for d in range(1, nifty.n_days):
        pc = Z.prev_close(nifty, d)
        c = Z._close_at(nifty, d, T(9, 30))
        if pc > 0 and np.isfinite(c):
            out[str(nifty.date[d])] = 1 if c > pc else (-1 if c < pc else 0)
    return out


def ze_contexts(needs: set, pool=None, nifty=None) -> dict:
    cx = {}
    if not isinstance(pool, list):
        return cx
    if "ze_rank930" in needs:
        cx["ze_rank930"] = rank930(pool)
    if "ze_nifty930" in needs:
        cx["ze_nifty930"] = nifty_side930(nifty)
    return cx
