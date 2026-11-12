"""Shared pieces of the four-topic intraday study (Nov 2026): clocks, session-anchored bars, extra indicators, the pool
contexts the stock books read, and the MCX stand-in market the look-ahead checks run the commodity books on.

Conventions are the 11- and 20-channel studies' (yc_common): fn(m, B, p, cache) -> list of Signal from completed bars
only; a signal carries its bar's last row, so orders start on the next row; swing pivots of n bars are used n bars later.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
for _p in (HERE, RESEARCH / "youtube_channels20_2026_11", RESEARCH / "youtube_channels11_2026_11",
           RESEARCH / "youtube_top20_2026_11", RESEARCH / "booming_bulls_2026_11", RESEARCH / "crypto_playlist_2026_11"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402

import yc_ind as I  # noqa: E402
from yc_common import bars_of_day, body, ctx, green, red, rng, sig  # noqa: E402,F401
from yt_engine import Signal  # noqa: E402,F401

T = lambda h, mi: h * 60 + mi  # noqa: E731
NSE_OPEN = T(9, 15)
MCX_OPEN = T(9, 0)
MCX_X = ("ist", T(23, 25))         # MCX evening close: out at 23:25 IST
MCX_MARKETS = ("MCXCRUDE", "MCXNG", "MCXSILVER")


def sorted_out(out):
    out.sort(key=lambda s: (s.k, s.side, s.setup))
    return out


def utc_min(b, j) -> int:
    return int((int(b.t0[j]) // 60) % 1440)


def ist_min(b, j) -> int:
    return int(b.ist0[j])


def rows_window(m, d, lo: int, hi: int):
    """(first row, last row + 1) of day d whose IST minute is in [lo, hi); (None, None) when empty."""
    a, z = int(m.d0[d]), int(m.d1[d])
    ist = np.asarray(m.ist[a:z])
    idx = np.flatnonzero((ist >= lo) & (ist < hi))
    if not len(idx):
        return None, None
    return a + int(idx[0]), a + int(idx[-1]) + 1


def window_hl(m, d, lo: int, hi: int):
    """(high, low, first row, last row) of day d's rows in [lo, hi) IST; None if no rows."""
    a, z = rows_window(m, d, lo, hi)
    if a is None:
        return None
    return float(m.h[a:z].max()), float(m.l[a:z].min()), a, z - 1


def row_at_or_after(m, d, minute: int):
    a, z = int(m.d0[d]), int(m.d1[d])
    ist = np.asarray(m.ist[a:z])
    idx = np.flatnonzero(ist >= minute)
    return a + int(idx[0]) if len(idx) else None


def last_row_before(m, d, minute: int):
    a, z = int(m.d0[d]), int(m.d1[d])
    ist = np.asarray(m.ist[a:z])
    idx = np.flatnonzero(ist < minute)
    return a + int(idx[-1]) if len(idx) else None


def session_bars(m, tf: int, cache: dict, open_min: int):
    """tf-minute bars on a grid starting at open_min IST each day (the MCX 09:00 open, the NSE 09:15 open), so a
    20-minute or 1-hour bar starts where the exchange's does; bars never cross a trading day. Kept in cache."""
    key = ("zd_sess", tf, open_min)
    if key in cache:
        return cache[key]
    import bb_markets as BM
    ist = np.asarray(m.ist, np.int64)
    slot = (ist - open_min) // tf
    k = m.day.astype(np.int64) * 100_000 + (slot - (slot.min() if len(slot) else 0))
    starts = np.flatnonzero(np.r_[True, k[1:] != k[:-1]]) if len(k) else np.zeros(0, np.int64)
    ends = np.r_[starts[1:], len(k)] - 1 if len(k) else np.zeros(0, np.int64)
    o, c = m.o[starts], m.c[ends]
    h = np.maximum.reduceat(m.h, starts) if len(k) else np.zeros(0)
    l = np.minimum.reduceat(m.l, starts) if len(k) else np.zeros(0)
    t0 = (m.t[starts] - (ist[starts] - (open_min + slot[starts] * tf)) * 60).astype(np.int64)
    day = m.day[starts]
    b0 = np.searchsorted(day, np.arange(m.n_days), "left")
    b1 = np.searchsorted(day, np.arange(m.n_days), "right")
    ist0, ny0 = BM._clocks(t0)
    bars = BM.Bars(tf, day, starts.astype(np.int64), ends.astype(np.int64), t0, o, h, l, c, ist0, ny0, b0, b1)
    cache[key] = bars
    return bars


def vctx(m, bars, cache: dict, name):
    """yc_common.Ctx for bars outside B (session-anchored, Heikin Ashi), kept under `name`."""
    from yc_common import Ctx
    key = ("zd_ctx", name)
    if key not in cache:
        cache[key] = Ctx(m, bars)
    return cache[key]


def last_done(bh, row) -> int:
    """Index of the last bar of bh complete at row `row` (-1 if none)."""
    return int(np.searchsorted(bh.i1, row, "right")) - 1


def rows_per_bar(b) -> int:
    return int(b.tf)


# ── indicators ────────────────────────────────────────────────────────────────────────────────────

def williams_r(b, n: int) -> np.ndarray:
    hh, ll = I.highest(b.h, n), I.lowest(b.l, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.where(hh > ll, -100.0 * (hh - b.c) / (hh - ll), np.nan)
    return w


def mfi(b, vol: np.ndarray, n: int) -> np.ndarray:
    """Money Flow Index over n bars from typical price and bar volume."""
    tp = (b.h + b.l + b.c) / 3
    mf = tp * vol
    up = np.where(np.r_[False, tp[1:] > tp[:-1]], mf, 0.0)
    dn = np.where(np.r_[False, tp[1:] < tp[:-1]], mf, 0.0)
    su = np.convolve(up, np.ones(n), "full")[:len(up)]
    sd = np.convolve(dn, np.ones(n), "full")[:len(dn)]
    out = np.full(len(tp), np.nan)
    ok = np.arange(len(tp)) >= n
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(sd > 0, su / sd, np.inf)
        val = 100 - 100 / (1 + r)
    out[ok] = val[ok]
    return out


def stoch_rsi(c: np.ndarray, n_rsi: int, n_st: int, k: int, d: int):
    """TradingView Stochastic RSI: %K = SMA(k) of the stochastic of RSI(n_rsi) over n_st; %D = SMA(d) of %K."""
    import yt_markets as YM
    r = YM.rsi(c, n_rsi)
    lo, hi = I.lowest(r, n_st), I.highest(r, n_st)
    with np.errstate(invalid="ignore", divide="ignore"):
        st = np.where(hi > lo, 100 * (r - lo) / (hi - lo), np.nan)
    K = sma_nan(st, k)
    D = sma_nan(K, d)
    return K, D


def sma_nan(x: np.ndarray, n: int) -> np.ndarray:
    """Simple average of the last n values; nan until n finite values in a row exist."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    ok = np.isfinite(x)
    xs = np.where(ok, x, 0.0)
    cs = np.cumsum(np.r_[0.0, xs])
    cnt = np.cumsum(np.r_[0, ok.astype(int)])
    s = cs[n:] - cs[:-n]
    c = cnt[n:] - cnt[:-n]
    out[n - 1:] = np.where(c == n, s / n, np.nan)
    return out


def donchian_offset(b, n: int, offset: int):
    """Donchian upper / lower of n bars, shifted forward by `offset` bars (TradingView 'offset'): the band at bar j is
    the extreme of bars j-offset-n+1 .. j-offset, so price can close outside it."""
    hi = I.highest(b.h, n)
    lo = I.lowest(b.l, n)
    up = np.full(len(hi), np.nan)
    dn = np.full(len(lo), np.nan)
    if offset < len(hi):
        up[offset:] = hi[:len(hi) - offset]
        dn[offset:] = lo[:len(lo) - offset]
    return up, dn


def cross_up(x, y, j) -> bool:
    return j >= 1 and np.isfinite(x[j - 1]) and np.isfinite(y[j - 1]) and np.isfinite(x[j]) and np.isfinite(y[j]) \
        and x[j - 1] <= y[j - 1] and x[j] > y[j]


def cross_dn(x, y, j) -> bool:
    return j >= 1 and np.isfinite(x[j - 1]) and np.isfinite(y[j - 1]) and np.isfinite(x[j]) and np.isfinite(y[j]) \
        and x[j - 1] >= y[j - 1] and x[j] < y[j]


def flags(n: int):
    return np.zeros(n, bool), np.zeros(n, bool)


def bear_engulf(b, j) -> bool:
    return j >= 1 and red(b, j) and green(b, j - 1) and b.o[j] >= b.c[j - 1] and b.c[j] <= b.o[j - 1]


def bull_engulf(b, j) -> bool:
    return j >= 1 and green(b, j) and red(b, j - 1) and b.o[j] <= b.c[j - 1] and b.c[j] >= b.o[j - 1]


def morning_star(b, j) -> bool:
    if j < 2:
        return False
    r1 = rng(b, j - 1)
    return red(b, j - 2) and r1 > 0 and body(b, j - 1) <= 0.3 * r1 and green(b, j) \
        and b.c[j] > (b.o[j - 2] + b.c[j - 2]) / 2


def evening_star(b, j) -> bool:
    if j < 2:
        return False
    r1 = rng(b, j - 1)
    return green(b, j - 2) and r1 > 0 and body(b, j - 1) <= 0.3 * r1 and red(b, j) \
        and b.c[j] < (b.o[j - 2] + b.c[j - 2]) / 2


def shooting_star(b, j) -> bool:
    r = rng(b, j)
    if not r > 0:
        return False
    up = b.h[j] - max(b.o[j], b.c[j])
    return up >= 2 * max(body(b, j), 1e-12) and b.c[j] <= b.l[j] + r / 3


def hammer(b, j) -> bool:
    r = rng(b, j)
    if not r > 0:
        return False
    lw = min(b.o[j], b.c[j]) - b.l[j]
    return lw >= 2 * max(body(b, j), 1e-12) and b.c[j] >= b.h[j] - r / 3


def vwap_of(m, b, cache, name):
    key = ("zd_vwap", name)
    if key not in cache:
        cache[key] = I.session_vwap(m, b)
    return cache[key]


def prev_day_hl(m, d):
    if d < 1 or not m.prev_ok[d]:
        return None
    a, z = int(m.d0[d - 1]), int(m.d1[d - 1])
    if z <= a:
        return None
    return float(m.h[a:z].max()), float(m.l[a:z].min()), float(m.c[z - 1])


def prev_close(m, d):
    if d < 1 or not m.prev_ok[d]:
        return float("nan")
    return float(m.c[m.d1[d - 1] - 1])


# ── pool contexts (the stock books' cross-section; each value uses only data known at its time) ─────────────────

def _close_at(m, d, minute):
    """Close of day d's last row starting before `minute` IST (nan if none)."""
    r = last_row_before(m, d, minute)
    return float(m.c[r]) if r is not None else float("nan")


def movers_at(pool, minute: int) -> dict:
    """{date: [(change from the previous close at `minute`, name, gap at the open, open, prev close)]} of the pool."""
    by: dict = {}
    for m in pool:
        for d in range(1, m.n_days):
            pc = prev_close(m, d)
            if not pc > 0:
                continue
            c = _close_at(m, d, minute)
            if not np.isfinite(c):
                continue
            op = float(m.o[m.d0[d]])
            by.setdefault(str(m.date[d]), []).append((c / pc - 1, m.name, op / pc - 1, op, pc))
    return by


def turnover_rank(pool) -> dict:
    """{'YYYY-MM': [names by the previous calendar month's traded value, largest first]} - known on the month's
    first day."""
    month_val: dict = {}
    for m in pool:
        tv = np.asarray(m.c, float) * np.asarray(m.vol, float)
        for d in range(m.n_days):
            a, z = int(m.d0[d]), int(m.d1[d])
            mo = str(m.date[d])[:7]
            month_val.setdefault(mo, {}).setdefault(m.name, 0.0)
            month_val[mo][m.name] += float(np.nansum(tv[a:z]))
    months = sorted(month_val)
    out = {}
    for i, mo in enumerate(months):
        if i == 0:
            continue
        prev = month_val[months[i - 1]]
        out[mo] = [n for n, _ in sorted(prev.items(), key=lambda kv: (-kv[1], kv[0]))]
    return out


def nifty_day_info(nifty) -> dict:
    """{date: (sign of NIFTY's change from the previous close at 9:25, colour of the first 15-minute candle)}."""
    out = {}
    if nifty is None:
        return out
    for d in range(1, nifty.n_days):
        pc = prev_close(nifty, d)
        a = int(nifty.d0[d])
        c925 = _close_at(nifty, d, T(9, 25))
        c930 = _close_at(nifty, d, T(9, 30))
        if not (pc > 0 and np.isfinite(c925) and np.isfinite(c930)):
            continue
        ch = 1 if c925 > pc else (-1 if c925 < pc else 0)
        col = 1 if c930 > float(nifty.o[a]) else (-1 if c930 < float(nifty.o[a]) else 0)
        out[str(nifty.date[d])] = (ch, col)
    return out


def open_extreme_930(pool) -> dict:
    """{date: [(|change|, name, side)]}: at 9:30, gainers whose 9:15-9:30 low is their open (within 0.02%) as side +1
    and losers whose 9:15-9:30 high is their open as side -1, largest move first."""
    by: dict = {}
    for m in pool:
        for d in range(1, m.n_days):
            pc = prev_close(m, d)
            w = window_hl(m, d, NSE_OPEN, T(9, 30))
            if not pc > 0 or w is None:
                continue
            op = float(m.o[m.d0[d]])
            c = float(m.c[w[3]])
            ch = c / pc - 1
            if ch > 0 and w[1] >= op * (1 - 0.0002):
                by.setdefault(str(m.date[d]), []).append((abs(ch), m.name, 1))
            elif ch < 0 and w[0] <= op * (1 + 0.0002):
                by.setdefault(str(m.date[d]), []).append((abs(ch), m.name, -1))
    return {k: sorted(v, key=lambda x: (-x[0], x[1])) for k, v in by.items()}


def zd_contexts(needs: set, pool=None, nifty=None) -> dict:
    """The p['ctx'] entries of this study's pool books (computed once per pool)."""
    cx = {}
    if not isinstance(pool, list):
        return cx
    if "zd_ol930" in needs:
        cx["zd_ol930"] = open_extreme_930(pool)
    if {"zd_movers925", "zd_movers930"} & needs:
        cx["zd_movers925"] = movers_at(pool, T(9, 25))
        cx["zd_movers930"] = movers_at(pool, T(9, 30))
    if "zd_turnover" in needs:
        cx["zd_turnover"] = turnover_rank(pool)
    if "zd_nifty" in needs:
        cx["zd_nifty"] = nifty_day_info(nifty)
    return cx


# ── the MCX stand-in for the checks: gold minutes cut to MCX hours (09:00-23:30 IST), one day per IST date ─────────

def mcx_proxy(name: str, source: str = "BTCUSD"):
    """A market with MCX's session shape for the look-ahead and fill checks only: research minutes of `source`
    (bitcoin by default: volatile enough to exercise every rule path) kept between 09:00 and 23:30 IST and grouped by
    IST date, under an MCX market name. It is NOT crude, natural gas or silver data and no result is read from it."""
    import bb_markets as BM
    import yc_markets as MK
    import yt_markets as YM
    g = MK.full(source)
    BM.COSTS.setdefault(name, BM.COSTS["XAUUSD"])
    ist = np.asarray(g.ist, np.int64)
    keep = (ist >= MCX_OPEN) & (ist < T(23, 30))
    t = np.asarray(g.t, np.int64)[keep]
    key = ((t + 19800) // 86400).astype(np.int64)
    half = np.asarray(getattr(g, "half", np.zeros(len(g.t))), float)
    vol = np.asarray(getattr(g, "vol", np.ones(len(g.t))), float)
    mm = BM._finish(name, t, g.o[keep], g.h[keep], g.l[keep], g.c[keep], half[keep], vol[keep], key, False)
    return YM._as_mkt(mm, name, "XAUUSD", YM.COSTS["XAUUSD"], False)
