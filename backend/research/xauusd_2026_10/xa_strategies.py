"""The candidate strategies: published rules, each with its source, coded as plans for xa_engine.

Every indicator at session d uses bars up to and including d (causal); the engine acts on it in
session d+1. Parameter grids are fixed here, before any result was seen, and centred on each
source's published values (`default`). Selection on the in-sample period picks within the grid.

Families whose published rules could not be verified, or that need data this study does not have,
are listed in DISCARDED with the reason.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from xa_engine import Market, Plan, Trade


# ── indicators (causal) ─────────────────────────────────────────────────────────


def _s(x) -> pd.Series:
    return pd.Series(x)


def sma(x, n):
    return _s(x).rolling(n, min_periods=n).mean().to_numpy(dtype=float, copy=True)


def ema(x, n):
    return _s(x).ewm(span=n, adjust=False, min_periods=n).mean().to_numpy(dtype=float, copy=True)


def wilder(x, n):
    return _s(x).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().to_numpy(dtype=float, copy=True)


def true_range(m: Market):
    pc = np.concatenate([[np.nan], m.d_c[:-1]])
    return np.nanmax(np.vstack([m.d_h - m.d_l, np.abs(m.d_h - pc), np.abs(m.d_l - pc)]), axis=0)


def roll_max(x, n):
    return _s(x).rolling(n, min_periods=n).max().to_numpy(dtype=float, copy=True)


def roll_min(x, n):
    return _s(x).rolling(n, min_periods=n).min().to_numpy(dtype=float, copy=True)


def rsi(x, n):
    d = np.diff(x, prepend=np.nan)
    up = wilder(np.where(d > 0, d, 0.0), n)
    dn = wilder(np.where(d < 0, -d, 0.0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = up / dn
    out = 100 - 100 / (1 + rs)
    out[(dn == 0) & (up > 0)] = 100.0
    return out


def month_end_mask(m: Market) -> np.ndarray:
    months = m.d_date.astype("datetime64[M]")
    me = np.zeros(len(months), bool)
    me[:-1] = months[1:] != months[:-1]
    me[-1] = False                      # the last session is not known to be a month end
    return me


def week_end_mask(m: Market) -> np.ndarray:
    wk = pd.to_datetime(m.d_date).to_period("W-FRI").values
    we = np.zeros(len(wk), bool)
    we[:-1] = wk[1:] != wk[:-1]
    return we


def state_plan(s: np.ndarray, **kw) -> Plan:
    """A desired position (+1 / 0 / -1) decided at each close, held until it changes."""
    s = np.nan_to_num(s, nan=0.0)
    return Plan(long_entry=s > 0, short_entry=s < 0, long_exit=s <= 0, short_exit=s >= 0, reverse=True, state=True, **kw)


def ffill_state(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Values decided on masked sessions (month or week ends), held until the next one."""
    out = pd.Series(np.where(mask, values, np.nan)).ffill().to_numpy(dtype=float, copy=True)
    return np.nan_to_num(out, nan=0.0)


def _side(sig_long, sig_short, direction):
    return sig_long, (sig_short if direction == "long_short" else np.zeros_like(sig_long, dtype=bool))


# ── trend following ─────────────────────────────────────────────────────────────


def faber_sma(m: Market, months: int, direction: str) -> Plan:
    me = month_end_mask(m)
    mc = pd.Series(m.d_c[me])
    ma = mc.rolling(months, min_periods=months).mean().values
    sig = np.where(mc.values > ma, 1.0, np.where(direction == "long_short", -1.0, 0.0))
    sig[np.isnan(ma)] = 0.0
    full = np.full(len(me), np.nan)
    full[me] = sig
    return state_plan(ffill_state(full, me))


def bbdd_ma(m: Market, short: int, long: int) -> Plan:
    me = month_end_mask(m)
    mc = pd.Series(m.d_c[me])
    s_ma = mc.rolling(short, min_periods=short).mean().values
    l_ma = mc.rolling(long, min_periods=long).mean().values
    sig = np.where(s_ma > l_ma, 1.0, 0.0)
    sig[np.isnan(l_ma)] = 0.0
    full = np.full(len(me), np.nan)
    full[me] = sig
    return state_plan(ffill_state(full, me))


def tsmom(m: Market, lookback: int, direction: str) -> Plan:
    me = month_end_mask(m)
    idx = np.flatnonzero(me)
    mc = m.d_c[idx]
    # excess over the T-bill (Moskowitz, Ooi & Pedersen use excess returns); the bill accrues on calendar days
    rate = m.rate
    cum = np.concatenate([[0.0], np.cumsum(rate.values / 365.0)])
    ri = rate.index.get_indexer(pd.to_datetime(m.d_date[idx]))
    sig = np.zeros(len(idx))
    for j in range(lookback, len(idx)):
        past = mc[j] / mc[j - lookback] - 1.0
        bill = cum[ri[j]] - cum[ri[j - lookback]]
        ex = past - bill
        sig[j] = 1.0 if ex > 0 else (-1.0 if direction == "long_short" else 0.0)
    full = np.full(len(me), np.nan)
    full[idx] = sig
    return state_plan(ffill_state(full, me))


def ma_cross(m: Market, short: int, long: int, band: float, direction: str) -> Plan:
    fast = m.d_c if short == 1 else sma(m.d_c, short)
    slow = sma(m.d_c, long)
    up = fast > slow * (1 + band)
    dn = fast < slow * (1 - band)
    s = np.full(len(fast), np.nan)
    s[up] = 1.0
    s[dn] = -1.0 if direction == "long_short" else 0.0
    if band > 0:                       # inside the band: keep what was held
        s = pd.Series(s).ffill().to_numpy(dtype=float, copy=True)
    else:
        s[~up & ~dn] = 0.0
    s[np.isnan(slow)] = 0.0
    return state_plan(np.nan_to_num(s))


def _turtle_allow(m: Market, hi20, lo20, xlo, xhi, N, stop_mult):
    """Turtle System 1 filter: skip a breakout when the previous breakout - taken or not - would
    have won (daily-bar shadow of the hypothetical trades)."""
    nd = len(m.d_c)
    allow = np.ones(nd, bool)
    last_win = False
    hyp = None
    for d in range(1, nd):
        allow[d - 1] = not last_win
        if hyp is None and hi20[d - 1] == hi20[d - 1]:
            up = m.d_h[d] >= hi20[d - 1]
            dn = m.d_l[d] <= lo20[d - 1]
            if up and dn:
                up = (hi20[d - 1] - m.d_o[d]) <= (m.d_o[d] - lo20[d - 1])
                dn = not up
            if up or dn:
                side = 1 if up else -1
                px = max(m.d_o[d], hi20[d - 1]) if up else min(m.d_o[d], lo20[d - 1])
                hyp = (side, px, px - side * stop_mult * N[d - 1])
                continue
        if hyp is not None:
            side, px, st = hyp
            if side == 1:
                lvl = max(st, xlo[d - 1]) if xlo[d - 1] == xlo[d - 1] else st
                if m.d_l[d] <= lvl:
                    last_win = min(m.d_o[d], lvl) > px
                    hyp = None
            else:
                lvl = min(st, xhi[d - 1]) if xhi[d - 1] == xhi[d - 1] else st
                if m.d_h[d] >= lvl:
                    last_win = max(m.d_o[d], lvl) < px
                    hyp = None
    return allow


def turtle(m: Market, entry: int, exit: int, stop_n: float | None, direction: str, filter_s1: bool = False) -> Plan:
    N = wilder(true_range(m), 20)
    hi, lo = roll_max(m.d_h, entry), roll_min(m.d_l, entry)
    xlo, xhi = roll_min(m.d_l, exit), roll_max(m.d_h, exit)
    buy, sell = hi.copy(), lo.copy()
    if filter_s1:
        allow = _turtle_allow(m, hi, lo, xlo, xhi, N, stop_n or 2.0)
        hi55, lo55 = roll_max(m.d_h, 55), roll_min(m.d_l, 55)
        buy = np.where(allow, hi, hi55)          # skipped System 1 breakout -> the 55-day failsafe
        sell = np.where(allow, lo, lo55)
    if direction != "long_short":
        sell = np.full(len(sell), np.nan)
    return Plan(buy_stop=buy, sell_stop=sell, exit_level_long=xlo, exit_level_short=xhi,
                stop_dist=(stop_n * N) if stop_n else None, oco=True)


def clenow(m: Market, breakout: int, atr_mult: float, direction: str) -> Plan:
    f, s = ema(m.d_c, 50), ema(m.d_c, 100)
    atr = sma(true_range(m), 100)
    hi, lo = roll_max(m.d_c, breakout), roll_min(m.d_c, breakout)
    le = (m.d_c >= hi) & (f > s)
    se = (m.d_c <= lo) & (f < s)
    le, se = _side(le, se, direction)
    return Plan(long_entry=le, short_entry=se, stop_dist=atr_mult * atr, trail=("close_atr", atr_mult, atr))


def macd(m: Market, timeframe: str, zero_filter: bool, direction: str) -> Plan:
    if timeframe == "weekly":
        we = week_end_mask(m)
        wc = m.d_c[we]
        line = ema(wc, 12) - ema(wc, 26)
        sigl = pd.Series(line).ewm(span=9, adjust=False, min_periods=9).mean().values
        up = (line > sigl) & ((line > 0) if zero_filter else True)
        dn = (line < sigl) & ((line < 0) if zero_filter else True)
        st = np.where(up, 1.0, np.where(dn & (direction == "long_short"), -1.0, 0.0))
        st[np.isnan(sigl)] = 0.0
        full = np.full(len(we), np.nan)
        full[we] = st
        return state_plan(ffill_state(full, we))
    line = ema(m.d_c, 12) - ema(m.d_c, 26)
    sigl = pd.Series(line).ewm(span=9, adjust=False, min_periods=9).mean().values
    up = (line > sigl) & ((line > 0) if zero_filter else True)
    dn = (line < sigl) & ((line < 0) if zero_filter else True)
    st = np.where(up, 1.0, np.where(dn & (direction == "long_short"), -1.0, 0.0))
    st[np.isnan(sigl)] = 0.0
    return state_plan(st)


def weinstein(m: Market, weeks: int, rising: bool, direction: str) -> Plan:
    """Stage analysis on weekly closes: long above a rising N-week SMA (stage 2), out below it."""
    we = week_end_mask(m)
    wc = m.d_c[we]
    ma = sma(wc, weeks)
    prev = np.concatenate([[np.nan], ma[:-1]])
    up = (wc > ma) & ((ma > prev) if rising else True)
    dn = (wc < ma) & ((ma < prev) if rising else True)
    st = np.where(up, 1.0, np.where(dn & (direction == "long_short"), -1.0, 0.0))
    st[np.isnan(ma)] = 0.0
    full = np.full(len(we), np.nan)
    full[we] = st
    return state_plan(ffill_state(full, we))


def _ichimoku_lines(h, l, c):
    tenkan = (roll_max(h, 9) + roll_min(l, 9)) / 2
    kijun = (roll_max(h, 26) + roll_min(l, 26)) / 2
    span_a = (tenkan + kijun) / 2
    span_b = (roll_max(h, 52) + roll_min(l, 52)) / 2
    # the cloud plotted at t was computed 26 periods earlier: shifting it forward keeps it causal
    a = np.concatenate([np.full(26, np.nan), span_a[:-26]])
    b = np.concatenate([np.full(26, np.nan), span_b[:-26]])
    return tenkan, kijun, np.fmax(a, b), np.fmin(a, b)


def ichimoku(m: Market, timeframe: str, exit: str, direction: str) -> Plan:
    if timeframe == "weekly":
        we = week_end_mask(m)
        idx = np.flatnonzero(we)
        # weekly bars from sessions: the week's high and low, closing at its last session. Sessions
        # after the last completed week form their own group, which is dropped - never merged into
        # the week before (that would let a week's close see later sessions).
        wk = np.searchsorted(idx, np.arange(len(we)))
        hw = pd.Series(m.d_h).groupby(wk).max().to_numpy()[:len(idx)]
        lw = pd.Series(m.d_l).groupby(wk).min().to_numpy()[:len(idx)]
        cw = m.d_c[idx]
        t, k, top, bot = _ichimoku_lines(hw, lw, cw)
        le = (cw > top) & (t > k)
        se = (cw < bot) & (t < k)
        lx = (cw < k) if exit == "kijun" else (cw < top)
        sx = (cw > k) if exit == "kijun" else (cw > bot)
        st = np.zeros(len(idx))
        cur = 0.0
        for j in range(len(idx)):
            if cur == 1 and lx[j]:
                cur = 0.0
            elif cur == -1 and sx[j]:
                cur = 0.0
            if cur == 0:
                cur = 1.0 if le[j] else (-1.0 if (se[j] and direction == "long_short") else 0.0)
            st[j] = cur
        full = np.full(len(we), np.nan)
        full[idx] = st
        return state_plan(ffill_state(full, we))
    t, k, top, bot = _ichimoku_lines(m.d_h, m.d_l, m.d_c)
    le = (m.d_c > top) & (t > k)
    se = (m.d_c < bot) & (t < k)
    le, se = _side(le, se, direction)
    lx = (m.d_c < k) if exit == "kijun" else (m.d_c < top)
    sx = (m.d_c > k) if exit == "kijun" else (m.d_c > bot)
    return Plan(long_entry=le, short_entry=se, long_exit=lx, short_exit=sx)


def wilder_dmi(m: Market, adx_min: float, direction: str) -> Plan:
    up = np.diff(m.d_h, prepend=np.nan)
    dn = -np.diff(m.d_l, prepend=np.nan)
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = wilder(true_range(m), 14)
    pdi = 100 * wilder(pdm, 14) / tr
    mdi = 100 * wilder(mdm, 14) / tr
    with np.errstate(divide="ignore", invalid="ignore"):
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    adx = wilder(np.nan_to_num(dx), 14)
    le = (pdi > mdi) & (adx > adx_min)
    se = (mdi > pdi) & (adx > adx_min)
    le, se = _side(le, se, direction)
    return Plan(long_entry=le, short_entry=se, long_exit=pdi < mdi, short_exit=mdi < pdi)


# ── breakout and volatility ─────────────────────────────────────────────────────


def bollinger_squeeze(m: Market, tol: float, window: int, exit: str, direction: str) -> Plan:
    mid = sma(m.d_c, 20)
    sd = _s(m.d_c).rolling(20, min_periods=20).std(ddof=0).values
    up, dn = mid + 2 * sd, mid - 2 * sd
    bw = (up - dn) / mid
    sq = bw <= roll_min(bw, 125) * (1 + tol)
    recent = _s(sq.astype(float)).rolling(window, min_periods=1).max().values > 0
    le = (m.d_c > up) & recent
    se = (m.d_c < dn) & recent
    le, se = _side(le, se, direction)
    if exit == "sar":
        return Plan(long_entry=le, short_entry=se, trail=("sar", 0.02, 0.02, 0.20))
    return Plan(long_entry=le, short_entry=se, long_exit=m.d_c < mid, short_exit=m.d_c > mid)


def chandelier(m: Market, entry_n: int, k: float, direction: str) -> Plan:
    """Enter on a close at the N-session high (low); exit on LeBeau's chandelier: the highest high
    since entry less k x ATR(22) (the lowest low plus, for shorts)."""
    atr = wilder(true_range(m), 22)
    hi, lo = roll_max(m.d_c, entry_n), roll_min(m.d_c, entry_n)
    le, se = _side(m.d_c >= hi, m.d_c <= lo, direction)
    return Plan(long_entry=le, short_entry=se, stop_dist=k * atr, trail=("chandelier", k, atr))


def keltner(m: Market, n: int, k: float, direction: str) -> Plan:
    mid = ema(m.d_c, n)
    atr = wilder(true_range(m), n)
    le = m.d_c > mid + k * atr
    se = m.d_c < mid - k * atr
    le, se = _side(le, se, direction)
    return Plan(long_entry=le, short_entry=se, long_exit=m.d_c < mid, short_exit=m.d_c > mid)


def williams_vbo(m: Market, k: float, exit: str, direction: str) -> Plan:
    rng = m.d_h - m.d_l
    plan = Plan(stop_dist=rng.copy(), oco=True)
    plan.buy_from_open = k * rng                                   # level = next session's open + k x range
    plan.sell_from_open = (k * rng) if direction == "long_short" else None
    if exit == "bailout":
        plan.bailout = True
        plan.max_hold = 10
    else:
        plan.max_hold = int(exit.replace("hold", ""))
    return plan


def nr_breakout(m: Market, pattern: str, hold: int, direction: str) -> Plan:
    rng = m.d_h - m.d_l
    if pattern == "NR7":
        flag = rng <= roll_min(rng, 7)
    else:   # inside day that is also the narrowest of 4 (Crabel's ID/NR4)
        inside = np.zeros(len(rng), bool)
        inside[1:] = (m.d_h[1:] < m.d_h[:-1]) & (m.d_l[1:] > m.d_l[:-1])
        flag = inside & (rng <= roll_min(rng, 4))
    buy = np.where(flag, m.d_h, np.nan)
    sell = np.where(flag & (direction == "long_short"), m.d_l, np.nan)
    return Plan(buy_stop=buy, sell_stop=sell, stop_dist=rng.copy(), max_hold=hold, oco=True)


def shock(m: Market, k: float, hold: int, stop: str) -> Plan:
    r = np.diff(np.log(m.d_c), prepend=np.nan)
    sd = _s(r).rolling(20, min_periods=20).std().shift(1).values
    z = r / sd
    atr = wilder(true_range(m), 20)
    return Plan(long_entry=z > k, short_entry=z < -k, max_hold=hold, stop_dist=(2 * atr) if stop == "2atr" else None)


# ── mean reversion ──────────────────────────────────────────────────────────────


def connors_rsi2(m: Market, threshold: int, exit_ma: int, direction: str) -> Plan:
    r2 = rsi(m.d_c, 2)
    t200, xm = sma(m.d_c, 200), sma(m.d_c, exit_ma)
    le = (m.d_c > t200) & (r2 < threshold)
    se = (m.d_c < t200) & (r2 > 100 - threshold)
    le, se = _side(le, se, direction)
    return Plan(long_entry=le, short_entry=se, long_exit=m.d_c > xm, short_exit=m.d_c < xm)


def double_seven(m: Market, n: int, direction: str) -> Plan:
    t200 = sma(m.d_c, 200)
    lo, hi = roll_min(m.d_c, n), roll_max(m.d_c, n)
    le = (m.d_c > t200) & (m.d_c <= lo)
    se = (m.d_c < t200) & (m.d_c >= hi)
    le, se = _side(le, se, direction)
    return Plan(long_entry=le, short_entry=se, long_exit=m.d_c >= hi, short_exit=m.d_c <= lo)


def bb_reversion(m: Market, k: float, trend: str, direction: str) -> Plan:
    mid = sma(m.d_c, 20)
    sd = _s(m.d_c).rolling(20, min_periods=20).std(ddof=0).values
    t200 = sma(m.d_c, 200)
    le = m.d_c < mid - k * sd
    se = m.d_c > mid + k * sd
    if trend == "sma200":
        le, se = le & (m.d_c > t200), se & (m.d_c < t200)
    le, se = _side(le, se, direction)
    return Plan(long_entry=le, short_entry=se, long_exit=m.d_c > mid, short_exit=m.d_c < mid)


# ── seasonal ────────────────────────────────────────────────────────────────────


def _next_session_dates(m: Market) -> pd.DatetimeIndex:
    nxt = np.concatenate([m.d_date[1:], [m.d_date[-1] + np.timedelta64(1, "D")]])
    return pd.to_datetime(nxt)


def autumn(m: Market, mode: str) -> Plan:
    nx = _next_session_dates(m)
    mo = nx.month.values
    if mode == "sep_and_nov":          # Baur (2013): the two months with significant gains, flat in October
        return state_plan(np.isin(mo, [9, 11]).astype(float))
    return state_plan(np.isin(mo, [9, 10, 11]).astype(float))


def winter(m: Market, mode: str) -> Plan:
    nx = _next_session_dates(m)
    mo, dy = nx.month.values, nx.day.values
    if mode == "dec_feb":
        s = np.isin(mo, [12, 1, 2])
    else:                              # astronomical winter, 21 Dec - 20 Mar
        s = ((mo == 12) & (dy >= 21)) | np.isin(mo, [1, 2]) | ((mo == 3) & (dy <= 20))
    return state_plan(s.astype(float))


# ── session (hourly) strategies: their own small loops, same Trade records ──────


def run_london_breakout(m: Market, first: int, last: int, tp_r: float, range_filter: bool) -> list[Trade]:
    """MQL5 blog 'London Breakout on Gold' (2026-10-13), as written, with server time = New York + 7h
    (the usual MT5 'New York close' server): range 03:00-08:00 server = 20:00-01:00 New York; OCO stops
    from 01:00 New York; stop at the far side of the range capped at 0.6% of price; target tp_r x risk;
    stop to break-even at 1.5R; everything closed at 21:00 server = 14:00 New York; one trade a day;
    days skipped if the range is under 0.30% or over 1.60% of price."""
    out: list[Trade] = []
    for d in range(first, min(last, len(m.d_date) - 1) + 1):
        hs, he = m.s_start[d], m.s_end[d]
        if he - hs < 10:
            continue
        nyh = m.h_ny_hour[hs:he]
        rng_idx = [hs + j for j in range(he - hs) if nyh[j] in (20, 21, 22, 23, 0)]
        work = [hs + j for j in range(he - hs) if 1 <= nyh[j] <= 13]
        if len(rng_idx) < 4 or not work:
            continue
        hi, lo = m.h_h[rng_idx].max(), m.h_l[rng_idx].min()
        mid = (hi + lo) / 2
        rp = (hi - lo) / mid
        if range_filter and not (0.003 <= rp <= 0.016):
            continue
        buf = 0.0002 * mid
        bstop, sstop = hi + buf, lo - buf
        pos, entry_px, stop, tp, risk, eh = 0, np.nan, np.nan, np.nan, np.nan, 0
        be_armed = False
        for i in work:
            o, h, l = m.h_o[i], m.h_h[i], m.h_l[i]
            filled = False
            if pos == 0:
                hb, hsl = h >= bstop, l <= sstop
                if hb and hsl:
                    hb = (bstop - o) <= (o - sstop)
                    hsl = not hb
                if not (hb or hsl):
                    continue
                pos = 1 if hb else -1
                entry_px = max(o, bstop) if hb else min(o, sstop)
                far = lo if pos == 1 else hi
                risk = min(abs(entry_px - far), 0.006 * entry_px)
                stop = entry_px - pos * risk
                tp = entry_px + pos * tp_r * risk
                eh, filled = i, True
            if pos == 1:
                if l <= stop:
                    out.append(Trade(1, d, eh, entry_px, d, i, stop if filled else min(o, stop), "stop"))
                    pos = 2
                    break
                if not filled and h >= tp:
                    out.append(Trade(1, d, eh, entry_px, d, i, max(o, tp), "target"))
                    pos = 2
                    break
                if be_armed:
                    stop = max(stop, entry_px)
                be_armed = be_armed or h >= entry_px + 1.5 * risk
            elif pos == -1:
                if h >= stop:
                    out.append(Trade(-1, d, eh, entry_px, d, i, stop if filled else max(o, stop), "stop"))
                    pos = 2
                    break
                if not filled and l <= tp:
                    out.append(Trade(-1, d, eh, entry_px, d, i, min(o, tp), "target"))
                    pos = 2
                    break
                if be_armed:
                    stop = min(stop, entry_px)
                be_armed = be_armed or l <= entry_px - 1.5 * risk
        if pos in (1, -1):
            i = work[-1]
            out.append(Trade(pos, d, eh, entry_px, d, i, m.h_c[i], "time"))
    return out


def run_session_drift(m: Market, first: int, last: int, exit_hour: int) -> list[Trade]:
    """Long from each session's first hour (~18:00 New York) to the open of the `exit_hour` New York
    bar - holding the Asian (and London) hours only, flat through New York."""
    out: list[Trade] = []
    for d in range(first, min(last, len(m.d_date) - 1) + 1):
        hs, he = m.s_start[d], m.s_end[d]
        nyh = m.h_ny_hour[hs:he]
        if he - hs < 10 or nyh[0] not in (17, 18, 19):
            continue
        k = next((j for j in range(he - hs) if nyh[j] == exit_hour), None)
        if k is None or k == 0:
            continue
        out.append(Trade(1, d, hs, m.h_o[hs], d, hs + k, m.h_o[hs + k], "time"))
    return out


# ── the registry ────────────────────────────────────────────────────────────────


@dataclass
class Family:
    key: str
    name: str
    category: str
    timeframe: str
    source: str
    url: str
    rules: str
    sizing_published: str
    deviations: str
    builder: object
    grid: dict
    default: dict
    hourly: bool = False
    stops: str = ""                         # stop-loss / take-profit logic, filled from STOPS below

    def configs(self):
        keys = list(self.grid)
        for vals in itertools.product(*[self.grid[k] for k in keys]):
            cfg = dict(zip(keys, vals))
            if self.key == "turtle" and cfg.get("filter_s1") and tuple(cfg["entry_exit"]) != (20, 10):
                continue
            if self.key == "turtle" and cfg.get("filter_s1") and cfg["stop_n"] is None:
                continue
            yield cfg


FAMILIES: list[Family] = [
    Family("faber_sma", "Faber 10-month SMA timing", "trend", "monthly (decided at month-end close)",
           "Faber, M. (2007). A Quantitative Approach to Tactical Asset Allocation. Journal of Wealth Management 9(4).",
           "https://papers.ssrn.com/abstract=962461",
           "Long when the month-end close is above its N-month simple moving average; otherwise cash (or short). Checked once a month.",
           "100% of the sleeve in the asset or in cash", "short side added as a variant (Faber is long/cash)",
           faber_sma, {"months": [6, 8, 10, 12], "direction": ["long", "long_short"]}, {"months": 10, "direction": "long"}),
    Family("bbdd_ma", "Gold monthly moving-average rules (Bartsch, Baur, Dichtl & Drobetz)", "trend", "monthly",
           "Bartsch, Baur, Dichtl & Drobetz (2018). Investing in the Gold Market: Market Timing or Buy-and-Hold? SSRN 3202658.",
           "https://quantpedia.com/an-extensive-test-of-market-timing-strategies-in-the-gold-market/",
           "Hold gold when the short moving average of month-end prices is above the long one, else cash. The study's ten pairs.",
           "100% gold or 100% cash", "none (as published)",
           bbdd_ma, {"pair": [(1, 9), (1, 12), (2, 9), (2, 12), (3, 9), (3, 12), (1, 10), (1, 24), (1, 36), (1, 48)]},
           {"pair": (1, 10)}),
    Family("tsmom", "Time-series momentum (Moskowitz, Ooi & Pedersen; Bartsch et al.)", "trend", "monthly",
           "Moskowitz, Ooi & Pedersen (2012). Time series momentum. Journal of Financial Economics 104(2), 228-250; gold lookbacks from Bartsch et al. (2018).",
           "https://papers.ssrn.com/abstract=2089463",
           "At each month end, the sign of the past k-month return over the T-bill decides the next month: long if positive; short (MOP) or cash (Bartsch et al.) if negative.",
           "MOP scale each position to 40% annual volatility; Bartsch et al. 100% gold or cash", "volatility scaling not applied (1x notional for every strategy)",
           tsmom, {"lookback": [1, 3, 6, 9, 12, 24, 36, 48], "direction": ["long", "long_short"]}, {"lookback": 12, "direction": "long_short"}),
    Family("ma_cross", "Moving-average crossover (Brock, Lakonishok & LeBaron; golden cross)", "trend", "daily",
           "Brock, Lakonishok & LeBaron (1992). Simple Technical Trading Rules and the Stochastic Properties of Stock Returns. Journal of Finance 47(5).",
           "https://doi.org/10.1111/j.1540-6261.1992.tb04681.x",
           "Long when the short moving average (1 = the close) is above the long one by more than the band, short (or cash) when below; inside the band the position is kept.",
           "not specified (signal study)", "inside-band days keep the previous position instead of being excluded",
           ma_cross, {"pair": [(1, 50), (1, 150), (5, 150), (1, 200), (2, 200), (50, 200)], "band": [0.0, 0.01], "direction": ["long", "long_short"]},
           {"pair": (50, 200), "band": 0.0, "direction": "long"}),
    Family("turtle", "Turtle breakout (System 1 / System 2)", "trend", "daily, intraday stop orders",
           "Faith, C. (2003). The Original Turtle Trading Rules; Faith (2007) Way of the Turtle. Gold was a Turtle market.",
           "https://www.tradingview.com/script/jbyeMkat/",
           "Buy-stop at the N-day high, sell-stop at the N-day low; exit on the M-day opposite breakout or a 2N stop (N = 20-day Wilder ATR). System 1 = 20/10 with the skip-after-a-winner filter and a 55-day failsafe; System 2 = 55/20.",
           "1 unit = 1% of equity per N; up to 4 units added every N/2", "no pyramiding (one unit, 1x notional)",
           turtle, {"entry_exit": [(20, 10), (55, 20), (100, 50)], "stop_n": [2.0, None], "direction": ["long_short", "long"], "filter_s1": [False, True]},
           {"entry_exit": (55, 20), "stop_n": 2.0, "direction": "long_short", "filter_s1": False}),
    Family("clenow", "Clenow core trend model", "trend", "daily",
           "Clenow, A. (2013). Following the Trend: Diversified Managed Futures Trading. Wiley.",
           "https://www.followingthetrend.com/",
           "Trend filter 50-day EMA vs 100-day EMA; enter on a close at the N-day high (low) in the filter's direction; exit on a trailing stop k x ATR(100) from the best close.",
           "risk parity: 0.2% of equity per daily ATR", "1x notional; rules as described in secondary summaries of the book",
           clenow, {"breakout": [50, 100], "atr_mult": [2.0, 3.0, 4.0], "direction": ["long_short", "long"]},
           {"breakout": 50, "atr_mult": 3.0, "direction": "long_short"}),
    Family("macd", "MACD(12,26,9) trend", "trend", "daily / weekly",
           "Appel, G. (2005). Technical Analysis: Power Tools for Active Investors. FT Press.",
           "https://www.investopedia.com/terms/m/macd.asp",
           "Long while the MACD line is above its signal line (optionally only above zero); short (or cash) while below.",
           "not specified", "none",
           macd, {"timeframe": ["daily", "weekly"], "zero_filter": [False, True], "direction": ["long", "long_short"]},
           {"timeframe": "daily", "zero_filter": False, "direction": "long"}),
    Family("weinstein", "Weinstein stage analysis (30-week MA)", "trend", "weekly",
           "Weinstein, S. (1988). Secrets for Profiting in Bull and Bear Markets. McGraw-Hill.",
           "https://chartschool.stockcharts.com/table-of-contents/market-analysis/stan-weinstein-s-stage-analysis",
           "Buy when the weekly close is above the 30-week SMA and the SMA is rising (stage 2); exit when the weekly close falls below it.",
           "not specified (position trading)", "shorts in stage 4 added as a variant",
           weinstein, {"weeks": [30, 40], "rising": [True, False], "direction": ["long", "long_short"]},
           {"weeks": 30, "rising": True, "direction": "long"}),
    Family("ichimoku", "Ichimoku cloud trend", "trend", "daily / weekly",
           "Hosoda, G. (1969) Ichimoku Kinko Hyo; Patel, M. (2010). Trading with Ichimoku Clouds. Wiley.",
           "https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/ichimoku-cloud",
           "Long when the close is above the cloud and Tenkan (9) is above Kijun (26); exit on a close below Kijun (or below the cloud). Shorts mirror it.",
           "not specified", "none",
           ichimoku, {"timeframe": ["daily", "weekly"], "exit": ["kijun", "cloud"], "direction": ["long", "long_short"]},
           {"timeframe": "daily", "exit": "kijun", "direction": "long"}),
    Family("wilder_dmi", "Wilder DMI / ADX trend", "trend", "daily",
           "Wilder, J. W. (1978). New Concepts in Technical Trading Systems. Trend Research.",
           "https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-directional-index-adx",
           "Long when +DI(14) is above -DI(14) and ADX(14) is above a threshold; exit when +DI crosses below -DI. Shorts mirror it.",
           "not specified", "none",
           wilder_dmi, {"adx_min": [20, 25], "direction": ["long", "long_short"]}, {"adx_min": 25, "direction": "long_short"}),
    Family("chandelier", "Breakout with LeBeau chandelier exit", "volatility", "daily",
           "LeBeau, C. & Lucas, D. (1992). Technical Traders Guide to Computer Analysis of the Futures Markets (chandelier exit).",
           "https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/chandelier-exit",
           "Enter on a close at the N-session high (low); exit when price trades through the highest high since entry less k x ATR(22).",
           "not specified", "the entry (an N-day closing breakout) is generic; LeBeau published the exit",
           chandelier, {"entry_n": [20, 50, 100], "k": [2.5, 3.0, 4.0], "direction": ["long_short", "long"]},
           {"entry_n": 50, "k": 3.0, "direction": "long_short"}),
    Family("bollinger_squeeze", "Bollinger Band squeeze breakout", "volatility", "daily",
           "Bollinger, J. (2001). Bollinger on Bollinger Bands. McGraw-Hill ('Method I: the Squeeze'); StockCharts ChartSchool.",
           "https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/bollinger-band-squeeze",
           "BandWidth (20, 2) at (or within tol of) its 6-month (125-session) low marks a squeeze; within W sessions a close outside a band enters in that direction; exit by Parabolic SAR (0.02/0.2) or a close back through the middle band.",
           "not specified", "none",
           bollinger_squeeze, {"tol": [0.0, 0.1], "window": [5, 20], "exit": ["sar", "mid"], "direction": ["long_short", "long"]},
           {"tol": 0.0, "window": 20, "exit": "sar", "direction": "long_short"}),
    Family("keltner", "Keltner / ATR channel breakout", "volatility", "daily",
           "Keltner, C. (1960). How to Make Money in Commodities; ATR form per Raschke & Connors (1996) Street Smarts.",
           "https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels",
           "Enter when the close leaves the channel EMA(n) +/- k x ATR(n); exit when it closes back across the EMA.",
           "not specified", "none",
           keltner, {"n": [20, 50], "k": [1.5, 2.0, 2.5], "direction": ["long_short", "long"]}, {"n": 20, "k": 2.0, "direction": "long_short"}),
    Family("williams_vbo", "Larry Williams volatility breakout", "volatility", "daily, intraday stop orders",
           "Williams, L. (1999). Long-Term Secrets to Short-Term Trading. Wiley.",
           "https://www.wiley.com/en-us/Long+Term+Secrets+to+Short+Term+Trading-p-9780471297222",
           "Buy-stop at the session open + k x the previous session's range (sell-stop below for shorts); stop one range away; exit on the first profitable open ('bailout') or after a fixed number of sessions.",
           "fixed fraction of equity", "none",
           williams_vbo, {"k": [0.5, 0.75, 1.0], "exit": ["bailout", "hold5", "hold10"], "direction": ["long", "long_short"]},
           {"k": 0.75, "exit": "bailout", "direction": "long_short"}),
    Family("nr_breakout", "Crabel NR7 / ID-NR4 breakout", "volatility", "daily, intraday stop orders",
           "Crabel, T. (1990). Day Trading with Short Term Price Patterns and Opening Range Breakout. Traders Press.",
           "https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/narrow-range-day-nr7",
           "After the narrowest range of 7 sessions (or an inside day that is the narrowest of 4), buy-stop at its high and sell-stop at its low for the next session; stop at the other side; exit after H sessions.",
           "not specified", "multi-session holds added (Crabel's are intraday)",
           nr_breakout, {"pattern": ["NR7", "IDNR4"], "hold": [1, 5, 20], "direction": ["long_short", "long"]},
           {"pattern": "NR7", "hold": 1, "direction": "long_short"}),
    Family("shock", "Volatility-shock continuation", "volatility", "daily",
           "Gold Strategy Lab (this repository, 2026-10-11): shock continuation tested on GLD daily; documented internally, not peer-reviewed.",
           "GOLD_STRATEGY_LAB_2026_10.md",
           "After a session whose return exceeds k x the prior 20-session volatility, take its direction at the next open and hold H sessions (optional 2 x ATR stop).",
           "equal notional", "XAUUSD with next-open entry (the lab used GLD next New York open)",
           shock, {"k": [2.0, 2.5, 3.0], "hold": [5, 10, 20], "stop": ["none", "2atr"]}, {"k": 2.5, "hold": 10, "stop": "none"}),
    Family("connors_rsi2", "Connors RSI(2) pullback", "mean reversion", "daily",
           "Connors, L. & Alvarez, C. (2008). Short Term Trading Strategies That Work. TradingMarkets.",
           "https://www.luxalgo.com/library/concept/rsi-2/",
           "Long when the close is above its 200-day SMA and RSI(2) is below t; exit on a close above the 5- (or 10-) day SMA; shorts mirror it.",
           "fixed fraction of equity", "entry at the next open instead of the signal close",
           connors_rsi2, {"threshold": [5, 10], "exit_ma": [5, 10], "direction": ["long", "long_short"]},
           {"threshold": 10, "exit_ma": 5, "direction": "long"}),
    Family("double_seven", "Connors Double 7s", "mean reversion", "daily",
           "Connors, L. & Alvarez, C. (2009). Short Term Trading Strategies That Work, 'Double 7s'.",
           "https://www.quantifiedstrategies.com/double-7s-strategy/",
           "Above the 200-day SMA, buy a close at the n-day low; sell at a close at the n-day high; shorts mirror it.",
           "fixed fraction of equity", "entry at the next open",
           double_seven, {"n": [5, 7, 10], "direction": ["long", "long_short"]}, {"n": 7, "direction": "long"}),
    Family("bb_reversion", "Bollinger Band reversion", "mean reversion", "daily",
           "Bollinger, J. (2001). Bollinger on Bollinger Bands (band tags as reversion signals).",
           "https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands",
           "Buy a close below the lower band (20, k), sell it on a close above the middle band (optional 200-day trend filter); shorts mirror it.",
           "not specified", "none",
           bb_reversion, {"k": [2.0, 2.5], "trend": ["none", "sma200"], "direction": ["long", "long_short"]},
           {"k": 2.0, "trend": "none", "direction": "long"}),
    Family("london_breakout", "London breakout of the Asian range", "session", "hourly",
           "'London Breakout on Gold: 3.7 Years of Backtests, What Works and What Does Not', MQL5 blog, 2026-10-13 (self-published).",
           "https://www.mql5.com/en/blogs/post/777540",
           "Range 03:00-08:00 server; OCO stops beyond it at 08:00; stop at the far side capped at 0.6%; target 2.5R; break-even at 1.5R; flat at 21:00 server; one trade a day; skip ranges <0.30% or >1.60%.",
           "1% of equity risked per trade", "server time taken as New York + 7h; 'small buffer' = 0.02% of price",
           None, {"tp_r": [2.5, 5.0], "range_filter": [True, False]}, {"tp_r": 2.5, "range_filter": True}, hourly=True),
    Family("session_drift", "Overnight (Asia/London) session drift", "session", "hourly",
           "Gold Strategy Lab (this repository): gold earned its return in Asian and London hours on GLD 2004-14; widely repeated as trading lore, no peer-reviewed source found.",
           "GOLD_STRATEGY_LAB_2026_10.md",
           "Long from the session's first hour (~18:00 New York) to 08:00 New York (or 03:00), flat through New York hours.",
           "equal notional", "none",
           None, {"exit_hour": [8, 3]}, {"exit_hour": 8}, hourly=True),
    Family("autumn", "Autumn effect (Baur 2013)", "seasonal", "monthly calendar",
           "Baur, D. G. (2013). The autumn effect of gold. Research in International Business and Finance 27(1), 1-11.",
           "https://ideas.repec.org/a/eee/riibaf/v27y2013i1p1-11.html",
           "Hold gold in September and November (the two significant months; flat in October), or continuously September-November.",
           "100% gold or cash", "none",
           autumn, {"mode": ["sep_and_nov", "sep_to_nov"]}, {"mode": "sep_and_nov"}),
    Family("winter", "Winter effect (Potrykus & Augustynowicz 2024)", "seasonal", "monthly calendar",
           "Potrykus, M. & Augustynowicz, J. (2024). The 'autumn effect' in the gold market - does it contradict the Adaptive Market Hypothesis? International Journal of Management and Economics 60(3).",
           "https://doi.org/10.2478/ijme-2024-0011",
           "Hold gold through winter: meteorological (December-February) or astronomical (21 December - 20 March).",
           "100% gold or cash", "months taken from the paper's season definitions",
           winter, {"mode": ["dec_feb", "dec21_mar20"]}, {"mode": "dec_feb"}),
]

STOPS = {
    "faber_sma": "No stop or target; leaves when a month-end close is below the SMA.",
    "bbdd_ma": "No stop or target; leaves on the monthly signal.",
    "tsmom": "No stop or target; the position is re-decided at every month end.",
    "ma_cross": "No stop or target; leaves on the opposite crossover (inside the band the position is kept).",
    "turtle": "Initial stop 2N from the entry (variants without it); exits on the M-day opposite breakout; no target.",
    "clenow": "Initial and trailing stop k x ATR(100) below the best close since entry; no target.",
    "macd": "No stop or target; leaves when MACD crosses its signal line.",
    "weinstein": "No stop or target; leaves on a weekly close below the moving average.",
    "ichimoku": "No stop or target; leaves on a close below Kijun (or the cloud).",
    "wilder_dmi": "No stop or target; leaves when +DI crosses below -DI.",
    "chandelier": "Initial stop k x ATR(22) from the entry, then trailing from the highest high since entry; no target.",
    "bollinger_squeeze": "Parabolic SAR trailing stop (step 0.02, max 0.20), or a close back through the middle band; no target.",
    "keltner": "No fixed stop; leaves on a close back across the EMA.",
    "williams_vbo": "Stop one previous-session range from the entry; leaves at the first profitable open (at most 10 sessions) or after 5 / 10 sessions.",
    "nr_breakout": "Stop at the other side of the narrow bar; leaves after H sessions.",
    "shock": "Optional 2 x ATR(20) stop; leaves after H sessions.",
    "connors_rsi2": "No stop (as published); leaves on a close above the short SMA.",
    "double_seven": "No stop (as published); leaves at the n-day closing high.",
    "bb_reversion": "No stop; leaves at the middle band.",
    "london_breakout": "Stop at the far side of the range, capped at 0.6% of price; target 2.5R (5R variant); stop to break-even at 1.5R; flat at 14:00 New York.",
    "session_drift": "No stop; time exit at 08:00 (or 03:00) New York.",
    "autumn": "No stop; calendar exit.",
    "winter": "No stop; calendar exit.",
}
for _f in FAMILIES:
    _f.stops = STOPS[_f.key]

DISCARDED = [
    ("Algomatic Trading 'Strategy #17: Trend-following Gold Breakout'", "rules and parameters are behind a paywall; only results are published",
     "https://algomatictrading.substack.com/p/strategy-17-trend-following-gold"),
    ("Commercial gold EAs (AurumBreak Pro, London Gold Breakout, GoldPower XAUUSD, ...)", "closed-source; vendor backtests only",
     "https://www.mql5.com/en/market/product/176885"),
    ("Smart-money / ICT, Elliott wave, Fibonacci discretionary methods", "no fixed, codable entry and exit rules", ""),
    ("Urquhart et al. (2015) 5-minute moving-average rules on spot gold", "gross of costs, 5-minute data; per-trade moves are far below 2% by construction",
     "https://www.cxoadvisory.com/technical-trading/high-frequency-technical-trading-of-gold-and-silver/"),
    ("Fundamental timing (real yields, inflation, dollar) from Bartsch et al. and the Gold Lab", "needs macro series beyond price; outside the brief's five categories", ""),
]


def build_plan(f: Family, m: Market, cfg: dict) -> Plan:
    c = dict(cfg)
    if f.key == "bbdd_ma":
        s, l = c.pop("pair")
        return bbdd_ma(m, s, l)
    if f.key == "ma_cross":
        s, l = c.pop("pair")
        return ma_cross(m, s, l, c["band"], c["direction"])
    if f.key == "turtle":
        e, x = c.pop("entry_exit")
        return turtle(m, e, x, c["stop_n"], c["direction"], c["filter_s1"])
    return f.builder(m, **c)


def label(cfg: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in cfg.items())
