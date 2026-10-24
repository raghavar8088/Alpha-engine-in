"""Intraday strategy families: published rules coded on the New York session clock.

Session minute `sm`: 0 = 18:00 New York (the session open), 540 = 03:00 (London open), 840 = 08:00,
860 = 08:20 (COMEX day-session open), 870 = 08:30 (US data releases), 1170 = 13:30 (COMEX day close),
1379 = 16:59 (the last minute before the 17:00 roll). Every trade is flat by the end of its session.
Indicators use only earlier minutes and earlier sessions; each rule enters on a minute after the one
it decided on. Grids are fixed here, centred on each source's published values (`default`).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from xi_engine import limit_entry, run_exit, stop_entry

T = {"open": 0, "london": 540, "ny0800": 840, "comex": 860, "data": 870, "ny0900": 900, "ny1230": 1110, "ny1300": 1140,
     "comex_close": 1170, "ny1400": 1200, "ny1600": 1320, "ny1630": 1350, "end": 1380}


def sm_of(hh: int, mm: int = 0) -> int:
    return ((hh * 60 + mm) - 18 * 60) % 1440


# ── per-session helpers ─────────────────────────────────────────────────────────


def at(D: dict, d: int, t: int, slack: int = 5) -> int | None:
    """Index of the first minute of session d at or after session-minute t (within `slack` minutes)."""
    s0, s1 = D["s_start"][d], D["s_end"][d]
    i = s0 + int(np.searchsorted(D["sm"][s0:s1], t))
    if i >= s1 or D["sm"][i] - t > slack:
        return None
    return i


def last_before(D: dict, d: int, t: int) -> int | None:
    """Index of the last minute of session d before session-minute t."""
    s0, s1 = D["s_start"][d], D["s_end"][d]
    i = s0 + int(np.searchsorted(D["sm"][s0:s1], t)) - 1
    return i if i >= s0 else None


class Context:
    """Per-session values computed once from earlier sessions only."""

    def __init__(self, D: dict):
        self.D = D
        n = len(D["s_start"])
        self.n = n
        dh, dl, do, dc = D["d_h"], D["d_l"], D["d_o"], D["d_c"]
        self.prev_range = np.concatenate([[np.nan], (dh - dl)[:-1]])
        near = np.minimum(dh - do, do - dl)
        self.stretch_session = pd.Series(near).rolling(10, min_periods=10).mean().shift(1).to_numpy()
        P = (dh + dl + dc) / 3
        rng = dh - dl
        lag = lambda x: np.concatenate([[np.nan], x[:-1]])
        self.pivot = {"P": lag(P), "R1": lag(2 * P - dl), "S1": lag(2 * P - dh), "R2": lag(P + rng), "S2": lag(P - rng)}
        self._comex = None
        self._noise = {}
        self._bars = {}
        self._fix = {}

    def comex_anchor(self):
        """Open at 08:20 and the high/low from 08:20 to the session end, per session (for Crabel)."""
        if self._comex is None:
            D = self.D
            o = np.full(self.n, np.nan)
            hi = np.full(self.n, np.nan)
            lo = np.full(self.n, np.nan)
            for d in range(self.n):
                i = at(D, d, T["comex"])
                if i is None:
                    continue
                e = D["s_end"][d]
                o[d], hi[d], lo[d] = D["o"][i], D["h"][i:e].max(), D["l"][i:e].min()
            near = np.minimum(hi - o, o - lo)
            stretch = pd.Series(near).rolling(10, min_periods=8).mean().shift(1).to_numpy()
            self._comex = (o, stretch)
        return self._comex

    def noise(self, anchor: int, span: int):
        """Zarattini et al.'s noise area: the mean over the previous 14 sessions of |close(anchor + tau) / open(anchor) - 1|."""
        key = (anchor, span)
        if key not in self._noise:
            D = self.D
            M = np.full((self.n, span), np.nan)
            opens = np.full(self.n, np.nan)
            for d in range(self.n):
                i = at(D, d, anchor)
                if i is None:
                    continue
                e = D["s_end"][d]
                smv = D["sm"][i:e] - anchor
                ok = (smv >= 0) & (smv < span)
                opens[d] = D["o"][i]
                M[d, smv[ok]] = np.abs(D["c"][i:e][ok] / D["o"][i] - 1.0)
            sig = pd.DataFrame(M).rolling(14, min_periods=10).mean().shift(1).to_numpy()
            self._noise[key] = (opens, sig)
        return self._noise[key]

    def bars(self, size: int):
        """Continuous `size`-minute bars (built inside sessions) with Bollinger inputs."""
        if size not in self._bars:
            D = self.D
            key = D["sess"].astype(np.int64) * 10000 + (D["sm"] // size)
            starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
            ends = np.r_[starts[1:], len(key)] - 1
            close = D["c"][ends]
            s = pd.Series(close)
            mid = s.rolling(20, min_periods=20).mean().to_numpy()
            sd = s.rolling(20, min_periods=20).std(ddof=0).to_numpy()
            self._bars[size] = {"start": starts, "end": ends, "close": close, "mid": mid, "sd": sd,
                                "sess": D["sess"][starts]}
        return self._bars[size]

    def fix_minute(self, lon_min: int):
        """Index of the minute at London clock `lon_min` in each session (or -1)."""
        if lon_min not in self._fix:
            D = self.D
            out = np.full(self.n, -1, dtype=np.int64)
            hit = np.flatnonzero(D["lon_min"] == lon_min)
            # the first such minute in each session (a session holds one 15:00 London)
            sess = D["sess"][hit]
            first = np.r_[True, sess[1:] != sess[:-1]]
            out[sess[first]] = hit[first]
            self._fix[lon_min] = out
        return self._fix[lon_min]


def nfp_dates(first_year: int = 2009, last_year: int = 2026) -> set:
    """US Employment Situation release dates by BLS's rule: the third Friday after the reference week
    (the Sunday-Saturday week that contains the 12th of the data month); moved to Thursday when that
    Friday is 4 July. Shutdown-delayed releases (October 2013, autumn 2025) are not modelled."""
    out = set()
    for y in range(first_year, last_year + 1):
        for m in range(1, 13):
            d12 = date(y, m, 12)
            sat = d12 + timedelta(days=(5 - d12.weekday()) % 7)          # Saturday ending the reference week
            fri = sat + timedelta(days=6 + 14)                            # the third Friday after it
            if fri.month == 7 and fri.day == 4:
                fri = fri - timedelta(days=1)
            out.add(np.datetime64(fri, "D"))
    return out


# ── the strategies: each returns rows (day, side, ei, ep, xi, xp, reason) for sessions in `days` ──


def orb_first_bar(D, C, days, anchor, or_len, target, exit):
    """Zarattini & Aziz (2023): trade in the direction of the opening range; stop at its far side;
    target 10R or none; flat at the exit time."""
    t0 = T[anchor]
    t_exit = T[exit]
    rows = []
    for d in days:
        i0 = at(D, d, t0)
        ie = at(D, d, t0 + or_len)
        xl = last_before(D, d, t_exit)
        if i0 is None or ie is None or xl is None or xl <= ie:
            continue
        o_, c_ = D["o"][i0], D["c"][ie - 1]
        hi, lo = D["h"][i0:ie].max(), D["l"][i0:ie].min()
        if c_ == o_ or hi <= lo:
            continue
        side = 1 if c_ > o_ else -1
        ep = D["o"][ie]
        stop = lo if side == 1 else hi
        risk = abs(ep - stop)
        if risk <= 0:
            continue
        tgt = ep + side * 10 * risk if target == "10R" else np.nan
        xi, xp, why = run_exit(D, side, ie, ep, stop, tgt, xl, inside=False)
        rows.append((d, side, ie, ep, xi, xp, why))
    return rows


def crabel(D, C, days, anchor, k, stop):
    """Crabel (1990): buy-stop at the open + stretch, sell-stop at the open - stretch; stretch = the
    10-session average of the distance from the open to the nearer extreme. First fill is the trade;
    the other level is its stop (or no stop). Flat at 16:59."""
    rows = []
    if anchor == "open":
        opens, stretch = None, C.stretch_session
    else:
        opens, stretch = C.comex_anchor()
    for d in days:
        st = stretch[d]
        if not (st == st) or st <= 0:
            continue
        i0 = at(D, d, T[anchor])
        xl = last_before(D, d, T["end"])
        if i0 is None or xl is None:
            continue
        O = D["o"][i0]
        buy, sell = O + k * st, O - k * st
        f = stop_entry(D, i0, xl, buy, sell)
        if f is None:
            continue
        ei, side, ep, inside = f
        sl = (sell if side == 1 else buy) if stop == "opposite" else np.nan
        xi, xp, why = run_exit(D, side, ei, ep, sl, np.nan, xl, inside)
        rows.append((d, side, ei, ep, xi, xp, why))
    return rows


def williams_day(D, C, days, k, direction, stop):
    """Williams (1999), the day-trade form: buy-stop at the session open + k x the previous session's
    range (sell-stop below for shorts); out at the session close."""
    rows = []
    for d in days:
        r = C.prev_range[d]
        if not (r == r) or r <= 0:
            continue
        i0 = at(D, d, T["open"])
        xl = last_before(D, d, T["end"])
        if i0 is None or xl is None:
            continue
        O = D["o"][i0]
        f = stop_entry(D, i0, xl, O + k * r, (O - k * r) if direction == "long_short" else np.nan)
        if f is None:
            continue
        ei, side, ep, inside = f
        sl = ep - side * 0.5 * r if stop == "half_range" else np.nan
        xi, xp, why = run_exit(D, side, ei, ep, sl, np.nan, xl, inside)
        rows.append((d, side, ei, ep, xi, xp, why))
    return rows


def london_breakout(D, C, days, tp_r, range_filter, breakeven):
    """MQL5 blog (2026): range 20:00-01:00 New York; OCO stops 0.02% beyond it from 01:00; stop at the far
    side capped at 0.6%; target tp_r x risk; break-even at 1.5R; flat at 14:00 New York; one trade a day."""
    rows = []
    a, b = sm_of(20), sm_of(1)
    for d in days:
        ia, ib = at(D, d, a), at(D, d, b)
        xl = last_before(D, d, T["ny1400"])
        if ia is None or ib is None or xl is None or xl <= ib:
            continue
        hi, lo = D["h"][ia:ib].max(), D["l"][ia:ib].min()
        mid = (hi + lo) / 2
        rp = (hi - lo) / mid
        if range_filter and not (0.003 <= rp <= 0.016):
            continue
        buf = 0.0002 * mid
        f = stop_entry(D, ib, xl, hi + buf, lo - buf)
        if f is None:
            continue
        ei, side, ep, inside = f
        far = lo if side == 1 else hi
        risk = min(abs(ep - far), 0.006 * ep)
        stop = ep - side * risk
        tgt = ep + side * tp_r * risk
        be = ep + side * 1.5 * risk if breakeven else np.nan
        xi, xp, why = run_exit(D, side, ei, ep, stop, tgt, xl, inside, be)
        rows.append((d, side, ei, ep, xi, xp, why))
    return rows


WINDOWS = {"comex": (sm_of(8, 20), sm_of(13, 30)), "ny": (sm_of(8), sm_of(17) or 1380), "session": (0, 1380)}


def intraday_momentum(D, C, days, window, predictor):
    """Gao, Han, Li & Zhou (2018): the first half-hour's return predicts the last half-hour's; trade the
    last half-hour in the first half-hour's direction (optionally only when the penultimate half-hour agrees)."""
    rows = []
    a, z = WINDOWS[window]
    for d in days:
        i_a, i_a30 = at(D, d, a), at(D, d, a + 30)
        i_l = at(D, d, z - 30)
        xl = last_before(D, d, z)
        i_p = at(D, d, z - 60)
        if None in (i_a, i_a30, i_l, xl, i_p) or xl <= i_l:
            continue
        r1 = D["c"][i_a30 - 1] / D["o"][i_a] - 1.0
        if r1 == 0:
            continue
        side = 1 if r1 > 0 else -1
        if predictor == "first_and_penultimate":
            rp = D["c"][i_l - 1] / D["o"][i_p] - 1.0
            if np.sign(rp) != side:
                continue
        xi, xp, why = run_exit(D, side, i_l, D["o"][i_l], np.nan, np.nan, xl, inside=False)
        rows.append((d, side, i_l, D["o"][i_l], xi, xp, why))
    return rows


def noise_area(D, C, days, anchor, check, mult):
    """Zarattini, Aziz & Barbon (2024): bands open x (1 +/- mult x the 14-session average absolute move
    from the open at that time of day). At each check time, go long above the upper band / short below the
    lower; leave when a check finds price back inside; flat at 16:59. (No VWAP: the feed has no volume.)"""
    rows = []
    t0 = T[anchor]
    span = T["end"] - t0
    opens, sig = C.noise(t0, span)
    for d in days:
        if not (opens[d] == opens[d]) or np.isnan(sig[d]).all():
            continue
        xl = last_before(D, d, T["end"])
        if xl is None:
            continue
        pos, ei, ep = 0, None, None
        for tau in range(check, span, check):
            i = at(D, d, t0 + tau, slack=2)
            if i is None or i > xl:
                break
            s = sig[d, tau - 1] if tau - 1 < span else np.nan
            if not (s == s):
                continue
            up, dn = opens[d] * (1 + mult * s), opens[d] * (1 - mult * s)
            px_close = D["c"][i - 1]
            if pos == 1 and px_close <= up:
                rows.append((d, 1, ei, ep, i, D["o"][i], "band"))
                pos = 0
            elif pos == -1 and px_close >= dn:
                rows.append((d, -1, ei, ep, i, D["o"][i], "band"))
                pos = 0
            if pos == 0:
                if px_close > up:
                    pos, ei, ep = 1, i, D["o"][i]
                elif px_close < dn:
                    pos, ei, ep = -1, i, D["o"][i]
        if pos != 0:
            rows.append((d, pos, ei, ep, xl, D["c"][xl], "time"))
    return rows


def session_drift(D, C, days, exit):
    """Long from the session's first minute (18:00 New York) to the exit time: Asian (and London) hours only."""
    rows = []
    for d in days:
        i0 = at(D, d, T["open"], slack=30)
        ix = at(D, d, T[exit])
        if i0 is None or ix is None or ix <= i0:
            continue
        rows.append((d, 1, i0, D["o"][i0], ix, D["o"][ix], "time"))
    return rows


def london_fix(D, C, days, fix, window):
    """Caminschi & Heaney (2014): the first minutes of the London fix predict its direction. Take the
    direction of the move over the first `window` minutes of the fix and hold to 10 minutes after."""
    rows = []
    lm = 10 * 60 + 30 if fix == "am" else 15 * 60
    first = C.fix_minute(lm)
    hold = 10 if window == 2 else 15
    for d in days:
        i0 = first[d]
        if i0 < 0:
            continue
        iw, ix = i0 + window, i0 + hold
        if ix >= D["s_end"][d] or (D["t"][ix] - D["t"][i0]) != hold * 60:
            continue
        r = D["c"][iw - 1] / D["o"][i0] - 1.0
        if r == 0:
            continue
        side = 1 if r > 0 else -1
        rows.append((d, side, iw, D["o"][iw], ix - 1, D["c"][ix - 1], "time"))
    return rows


NFP = nfp_dates()


def nfp(D, C, days, mode, exit, tp):
    """US payrolls days (08:30 New York): straddle the 08:00-08:30 range with OCO stops, or follow the
    08:30-09:00 move from 09:00; stop at the far side; optional 3R target; flat at the exit time."""
    rows = []
    for d in days:
        if D["sess_date"][d] not in NFP:
            continue
        xl = last_before(D, d, T[exit])
        if xl is None:
            continue
        if mode == "straddle":
            ia, ib = at(D, d, T["ny0800"]), at(D, d, T["data"])
            if ia is None or ib is None:
                continue
            hi, lo = D["h"][ia:ib].max(), D["l"][ia:ib].min()
            buf = 0.0002 * hi
            f = stop_entry(D, ib, xl, hi + buf, lo - buf)
            if f is None:
                continue
            ei, side, ep, inside = f
            stop = lo - buf if side == 1 else hi + buf
        else:
            ia, ib = at(D, d, T["data"]), at(D, d, T["ny0900"])
            if ia is None or ib is None:
                continue
            move = D["c"][ib - 1] / D["o"][ia] - 1.0
            if move == 0:
                continue
            side = 1 if move > 0 else -1
            ei, ep, inside = ib, D["o"][ib], False
            stop = D["l"][ia:ib].min() if side == 1 else D["h"][ia:ib].max()
        risk = abs(ep - stop)
        if risk <= 0:
            continue
        tgt = ep + side * 3 * risk if tp == "3R" else np.nan
        xi, xp, why = run_exit(D, side, ei, ep, stop, tgt, xl, inside)
        rows.append((d, side, ei, ep, xi, xp, why))
    return rows


def pivots(D, C, days, mode, window):
    """Floor-trader pivots from the previous session (Person 2004). Fade: sell R1 (stop R2, target P),
    buy S1 (stop S2, target P). Breakout: buy above R1 (stop P, target R2), sell below S1 (stop P,
    target S2). One trade a session, flat at 16:59."""
    rows = []
    pv = C.pivot
    t0 = T["london"] if window == "london_ny" else T["open"]
    for d in days:
        P, R1, S1, R2, S2 = (pv[k][d] for k in ("P", "R1", "S1", "R2", "S2"))
        if not (P == P):
            continue
        i0 = at(D, d, t0, slack=30)
        xl = last_before(D, d, T["end"])
        if i0 is None or xl is None:
            continue
        # an order is only placed on a side the market has not already crossed when the window opens
        # (nobody rests a sell limit below the market or a buy stop below it)
        o0 = D["o"][i0]
        if mode == "fade":
            f = limit_entry(D, i0, xl, S1 if o0 > S1 else np.nan, R1 if o0 < R1 else np.nan)
            if f is None:
                continue
            ei, side, ep, inside = f
            stop, tgt = (S2, P) if side == 1 else (R2, P)
        else:
            f = stop_entry(D, i0, xl, R1 if o0 < R1 else np.nan, S1 if o0 > S1 else np.nan)
            if f is None:
                continue
            ei, side, ep, inside = f
            stop, tgt = (P, R2) if side == 1 else (P, S2)
        xi, xp, why = run_exit(D, side, ei, ep, stop, tgt, xl, inside)
        rows.append((d, side, ei, ep, xi, xp, why))
    return rows


def bb_intraday(D, C, days, tf, k, direction):
    """Bollinger (20, k) reversion on tf-minute bars: buy the next bar's open after a close below the lower
    band, sell it after a close above the middle band (shorts mirror it); flat at 16:59."""
    rows = []
    B = C.bars(tf)
    sess = B["sess"]
    lo_b = B["mid"] - k * B["sd"]
    hi_b = B["mid"] + k * B["sd"]
    dayset = set(int(x) for x in days)
    first_bar = np.searchsorted(sess, np.arange(sess.max() + 1), side="left")
    last_bar = np.searchsorted(sess, np.arange(sess.max() + 1), side="right") - 1
    for d in days:
        if d >= len(first_bar):
            continue
        a, z = first_bar[d], last_bar[d]
        xl = last_before(D, d, T["end"])
        if a > z or xl is None:
            continue
        pos, ei, ep = 0, None, None
        for j in range(a, z):                      # decide on bar j's close, act at bar j+1's open
            cl, m, lb, ub = B["close"][j], B["mid"][j], lo_b[j], hi_b[j]
            if not (m == m):
                continue
            nxt = B["start"][j + 1]
            if nxt > xl:
                break
            if pos == 1 and cl >= m:
                rows.append((d, 1, ei, ep, nxt, D["o"][nxt], "mid"))
                pos = 0
                continue
            if pos == -1 and cl <= m:
                rows.append((d, -1, ei, ep, nxt, D["o"][nxt], "mid"))
                pos = 0
                continue
            if pos == 0:
                if cl < lb:
                    pos, ei, ep = 1, nxt, D["o"][nxt]
                elif cl > ub and direction == "long_short":
                    pos, ei, ep = -1, nxt, D["o"][nxt]
        if pos != 0:
            rows.append((d, pos, ei, ep, xl, D["c"][xl], "time"))
    return rows


# ── registry ────────────────────────────────────────────────────────────────────


@dataclass
class Family:
    key: str
    name: str
    category: str
    source: str
    url: str
    rules: str
    stops: str
    sizing_published: str
    deviations: str
    fn: object
    grid: dict
    default: dict

    def configs(self):
        keys = list(self.grid)
        for vals in itertools.product(*[self.grid[k] for k in keys]):
            yield dict(zip(keys, vals))


FAMILIES = [
    Family("orb_first_bar", "Opening-range breakout, first bar (Zarattini & Aziz)", "breakout",
           "Zarattini, C. & Aziz, A. (2023). Can Day Trading Really Be Profitable? Evidence of Sustainable Long-term Profits from Opening Range Breakout Day Trading Strategy. SSRN 4416622.",
           "https://www.cxoadvisory.com/technical-trading/day-trading-with-an-opening-range-breakout-strategy",
           "Take the direction of the opening range (its close vs its open) at the next minute's open; stop at the range's far side; target 10R or none; flat at the exit time.",
           "Stop at the far side of the opening range; target 10R or none; time exit.",
           "1% of equity risked at the stop, leverage capped at 4x", "gold has no single open: tested at the COMEX day open (08:20 New York) and the London open (03:00)",
           orb_first_bar, {"anchor": ["comex", "london"], "or_len": [5, 15, 30], "target": ["10R", "none"], "exit": ["comex_close", "end"]},
           {"anchor": "comex", "or_len": 5, "target": "10R", "exit": "end"}),
    Family("crabel", "Crabel opening-range breakout with the stretch", "breakout",
           "Crabel, T. (1990). Day Trading with Short Term Price Patterns and Opening Range Breakout. Traders Press; Stocks & Commodities V.6:9.",
           "https://store.traders.com/-v06-c09-playing-pdf.html",
           "Buy-stop at the open + k x stretch and sell-stop at the open - k x stretch, stretch = the 10-session average distance from the open to the nearer extreme; first fill is the trade; flat at 16:59.",
           "The other order's level is the stop (or no stop); no target; time exit.",
           "not specified", "anchored at the session open (18:00) or the COMEX open (08:20)",
           crabel, {"anchor": ["open", "comex"], "k": [1.0, 1.5, 2.0], "stop": ["opposite", "none"]}, {"anchor": "comex", "k": 1.0, "stop": "opposite"}),
    Family("williams_day", "Williams volatility breakout, day-trade form", "volatility",
           "Williams, L. (1999). Long-Term Secrets to Short-Term Trading. Wiley.",
           "https://www.wiley.com/en-us/Long+Term+Secrets+to+Short+Term+Trading-p-9780471297222",
           "Buy-stop at the session open + k x the previous session's range (sell-stop below for shorts); out at the session close.",
           "No stop, or half the previous range; time exit.",
           "fixed fraction of equity", "none",
           williams_day, {"k": [0.3, 0.5, 0.7, 1.0], "direction": ["long_short", "long"], "stop": ["none", "half_range"]},
           {"k": 0.5, "direction": "long_short", "stop": "none"}),
    Family("london_breakout", "London breakout of the Asian range", "session",
           "'London Breakout on Gold: 3.7 Years of Backtests, What Works and What Does Not', MQL5 blog, 2026-10-13 (self-published).",
           "https://www.mql5.com/en/blogs/post/777540",
           "Range 20:00-01:00 New York; OCO stops 0.02% beyond it from 01:00; one trade a day; skip ranges under 0.30% or over 1.60% of price.",
           "Stop at the far side capped at 0.6% of price; target 2.5R (5R variant); break-even at 1.5R; flat at 14:00 New York.",
           "1% of equity risked per trade", "server time taken as New York + 7h; buffer 0.02% of price",
           london_breakout, {"tp_r": [2.5, 5.0], "range_filter": [True, False], "breakeven": [True, False]},
           {"tp_r": 2.5, "range_filter": True, "breakeven": True}),
    Family("intraday_momentum", "Intraday momentum, first half-hour (Gao, Han, Li & Zhou)", "trend",
           "Gao, L., Han, Y., Li, S. Z. & Zhou, G. (2018). Market intraday momentum. Journal of Financial Economics 129(2), 394-414.",
           "https://www.sciencedirect.com/science/article/abs/pii/S0304405X18301351",
           "Trade the last half-hour of the day in the direction of the first half-hour (optionally only when the penultimate half-hour agrees).",
           "No stop or target; half-hour holding.",
           "not specified (return predictability study)", "the 'day' for a 24-hour market: the COMEX day session, the New York day or the whole session",
           intraday_momentum, {"window": ["comex", "ny", "session"], "predictor": ["first", "first_and_penultimate"]},
           {"window": "comex", "predictor": "first"}),
    Family("noise_area", "Noise-area intraday momentum (Zarattini, Aziz & Barbon)", "trend",
           "Zarattini, C., Aziz, A. & Barbon, A. (2024). Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY). SSRN.",
           "https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content",
           "Bands = open x (1 +/- the 14-session average absolute move from the open at that minute); at each check time go long above / short below; leave when a check finds price back inside; flat at 16:59.",
           "The band is the trailing stop, checked at the check times; time exit.",
           "volatility-targeted, up to 4x", "no VWAP (the feed has no volume); no gap adjustment (24-hour market)",
           noise_area, {"anchor": ["comex", "london"], "check": [30, 60], "mult": [1.0, 1.5]}, {"anchor": "comex", "check": 30, "mult": 1.0}),
    Family("session_drift", "Asia/London session drift", "session",
           "Gold Strategy Lab (this repository, 2026-10-11): gold earned its return in Asian and London hours on GLD 2004-14; widely repeated lore, no peer-reviewed source found.",
           "https://github.com/raghavar8088/Alpha-engine-in/blob/main/GOLD_STRATEGY_LAB_2026_10.md",
           "Long from the session's first minute (18:00 New York) to 08:00 (or 03:00) New York.",
           "No stop; time exit.", "equal notional", "none",
           session_drift, {"exit": ["ny0800", "london"]}, {"exit": "ny0800"}),
    Family("london_fix", "London fix leakage (Caminschi & Heaney)", "session",
           "Caminschi, A. & Heaney, R. (2014). Fixing a Leaky Fixing: Short-Term Market Reactions to the London PM Gold Price Fixing. Journal of Futures Markets 34(11), 1003-1039.",
           "https://ideas.repec.org/a/wly/jfutmk/v34y2014i11p1003-1039.html",
           "Trade the direction of the first 2 (or 4) minutes after the fix starts (10:30 or 15:00 London), holding to 10 (or 15) minutes after it.",
           "No stop; time exit.", "not specified", "the LBMA auction replaced the fix in 2015 at the same times",
           london_fix, {"fix": ["pm", "am"], "window": [2, 4]}, {"fix": "pm", "window": 2}),
    Family("nfp", "US payrolls-day breakout", "volatility",
           "Practitioner rule (straddle the pre-release range / follow the first half-hour); release days by BLS's published schedule rule. No peer-reviewed gold study found.",
           "https://www.bls.gov/schedule/news_release/empsit.htm",
           "Straddle: OCO stops 0.02% beyond the 08:00-08:30 range from 08:30. Continuation: from 09:00 follow the 08:30-09:00 move.",
           "Stop at the far side of the range; target 3R or none; flat at 13:30 or 16:59.", "not specified",
           "release dates by rule; shutdown-delayed releases are not modelled",
           nfp, {"mode": ["straddle", "continuation"], "exit": ["comex_close", "end"], "tp": ["none", "3R"]},
           {"mode": "straddle", "exit": "end", "tp": "none"}),
    Family("pivots", "Floor-trader pivots (fade or breakout)", "mean reversion",
           "Person, J. L. (2004). A Complete Guide to Technical Trading Tactics. Wiley (pivot points).",
           "https://www.wiley.com/en-us/A+Complete+Guide+to+Technical+Trading+Tactics%3A+How+to+Profit+Using+Pivot+Points%2C+Candlesticks+%26+Other+Indicators-p-9780471466000",
           "Pivots from the previous session. Fade: sell R1, buy S1. Breakout: buy above R1, sell below S1. One trade a session.",
           "Fade: stop R2/S2, target P. Breakout: stop P, target R2/S2. Flat at 16:59.", "not specified", "none",
           pivots, {"mode": ["fade", "breakout"], "window": ["london_ny", "session"]}, {"mode": "fade", "window": "london_ny"}),
    Family("bb_intraday", "Bollinger reversion on intraday bars", "mean reversion",
           "Bollinger, J. (2001). Bollinger on Bollinger Bands. McGraw-Hill (band tags as reversion signals, any timeframe).",
           "https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands",
           "Buy the next bar after a close below the lower band (20, k); sell after a close above the middle band; shorts mirror it.",
           "No stop; flat at 16:59.", "not specified", "none",
           bb_intraday, {"tf": [5, 15], "k": [2.0, 2.5], "direction": ["long_short", "long"]}, {"tf": 15, "k": 2.0, "direction": "long_short"}),
]


def label(cfg: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in cfg.items())
