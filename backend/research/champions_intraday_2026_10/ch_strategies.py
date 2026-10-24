"""The champion traders' intraday rules of PREREGISTRATION.md, coded on each market's regular session.

Session minute sm: 0 = the regular session's open (gold 08:20 New York, S&P 500 and Nasdaq 100 09:30 New York,
DAX 09:00 Frankfurt, WTI crude 09:00 New York). No new entry in the session's last 60 minutes; every trade
is flat at the session's last minute. Daily values come from completed sessions only, and each rule
enters on a minute after the one it decided on. Fills, stops and targets: ../xauusd_intraday_2026_10/
xi_engine.py (worst case inside a minute; a stop touched in the entry minute counts against the trade).
Each row: (session, side, entry index, entry price, exit index, exit price, reason).
"""

from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "xauusd_intraday_2026_10"))

import numpy as np
import pandas as pd

from xi_engine import run_exit, stop_entry  # noqa: E402
from xi_strategies import at, last_before  # noqa: E402

DEADLINE = 60          # minutes before the close after which no entry fills
BUFFER = 0.0001        # 0.01% of price beyond a range's high/low for a breakout order


class Context:
    """Per-session values from earlier sessions only, for one market."""

    def __init__(self, D: dict, length: int, skip: np.ndarray):
        self.D, self.L, self.skip = D, length, skip
        dh, dl, do, dc = D["d_h"], D["d_l"], D["d_o"], D["d_c"]
        rng = dh - dl
        lag = lambda x: np.concatenate([[np.nan], np.asarray(x, dtype=float)[:-1]])
        self.h1, self.l1, self.r1 = lag(dh), lag(dl), lag(rng)
        pc = np.concatenate([[np.nan], dc[:-1]])
        tr = np.fmax(rng, np.fmax(np.abs(dh - pc), np.abs(dl - pc)))
        self.atr = lag(pd.Series(tr).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().to_numpy())
        self.stretch = pd.Series(np.minimum(dh - do, do - dl)).rolling(10, min_periods=10).mean().shift(1).to_numpy()
        self.avg10 = pd.Series(rng).rolling(10, min_periods=10).mean().shift(1).to_numpy()
        r = pd.Series(rng)
        nr4 = r < r.shift(1).rolling(3, min_periods=3).min()
        nr7 = r < r.shift(1).rolling(6, min_periods=6).min()
        inside = (pd.Series(dh) < pd.Series(dh).shift(1)) & (pd.Series(dl) > pd.Series(dl).shift(1))
        prev = lambda s: s.shift(1, fill_value=False).to_numpy(dtype=bool)
        self.pattern = {"NR4": prev(nr4), "NR7": prev(nr7), "ID_NR4": prev(nr4 & inside)}
        self._bars = {}

    def window(self, d: int):
        """(first minute, last minute an entry may fill, last minute of the session) or None."""
        D = self.D
        i0 = at(D, d, 0)
        dl = last_before(D, d, self.L - DEADLINE)
        xl = last_before(D, d, self.L)
        if i0 is None or dl is None or xl is None or dl < i0:
            return None
        return i0, dl, xl

    def bars(self, tf: int):
        """tf-minute bars anchored at each session's open: start/end minute index, high, low, close, end sm."""
        if tf not in self._bars:
            D = self.D
            key = D["sess"].astype(np.int64) * 10000 + (D["sm"] // tf)
            st = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
            en = np.r_[st[1:], len(key)] - 1
            sess = D["sess"][st]
            n = len(D["s_start"])
            self._bars[tf] = {"start": st, "end": en, "high": np.maximum.reduceat(D["h"], st), "low": np.minimum.reduceat(D["l"], st),
                              "close": D["c"][en], "end_sm": (D["sm"][st] // tf + 1) * tf,
                              "first": np.searchsorted(sess, np.arange(n), side="left"), "last": np.searchsorted(sess, np.arange(n), side="right")}
        return self._bars[tf]


# ── Toby Crabel ─────────────────────────────────────────────────────────────────


def crabel_orb(D, C, days, k, stop, pattern="ALL"):
    """Crabel (1990): buy-stop at the open + k x stretch, sell-stop at the open - k x stretch (stretch = the
    10-session average distance from the open to the nearer extreme); the first fill is the trade; the
    other level is its stop (or none); out at the close. With a pattern, only on sessions after an NR4,
    an NR7 or an inside day that is also an NR4 (ID/NR4)."""
    rows = []
    for d in days:
        if C.skip[d] or (pattern != "ALL" and not C.pattern[pattern][d]):
            continue
        st = C.stretch[d]
        w = C.window(d)
        if w is None or not (st == st) or st <= 0:
            continue
        i0, dl, xl = w
        O = D["o"][i0]
        buy, sell = O + k * st, O - k * st
        f = stop_entry(D, i0, dl, buy, sell)
        if f is None:
            continue
        ei, side, ep, inside = f
        sl = (sell if side == 1 else buy) if stop == "opposite" else np.nan
        xi, xp, why = run_exit(D, side, ei, ep, sl, np.nan, xl, inside)
        rows.append((d, side, ei, ep, xi, xp, why))
    return rows


def crabel_nr(D, C, days, pattern, k, stop):
    return crabel_orb(D, C, days, k, stop, pattern)


# ── Larry Williams ──────────────────────────────────────────────────────────────


def williams_vbo(D, C, days, k, direction, stop):
    """Williams (1999), day-trade form: buy-stop at the open + k x the previous session's range (sell-stop
    below for shorts); stop half that range from the entry (or none); out at the close."""
    rows = []
    for d in days:
        r = C.r1[d]
        w = C.window(d)
        if C.skip[d] or w is None or not (r == r) or r <= 0:
            continue
        i0, dl, xl = w
        O = D["o"][i0]
        f = stop_entry(D, i0, dl, O + k * r, (O - k * r) if direction == "both" else np.nan)
        if f is None:
            continue
        ei, side, ep, inside = f
        sl = ep - side * 0.5 * r if stop == "half_range" else np.nan
        xi, xp, why = run_exit(D, side, ei, ep, sl, np.nan, xl, inside)
        rows.append((d, side, ei, ep, xi, xp, why))
    return rows


def williams_oops(D, C, days, direction, gap, stop):
    """Williams' Oops!, intraday form: when the session opens below the previous session's low (by more
    than gap x ATR14), a buy-stop at that low; opens above the previous high -> a sell-stop at that high.
    Stop at the session's extreme before the entry (or none); out at the close."""
    rows = []
    for d in days:
        h1, l1, atr = C.h1[d], C.l1[d], C.atr[d]
        w = C.window(d)
        if C.skip[d] or w is None or not (h1 == h1 and l1 == l1 and atr == atr):
            continue
        i0, dl, xl = w
        O = D["o"][i0]
        g = gap * atr
        buy = l1 if O < l1 - g else np.nan
        sell = h1 if (direction == "both" and O > h1 + g) else np.nan
        if not (buy == buy or sell == sell):
            continue
        f = stop_entry(D, i0, dl, buy, sell)
        if f is None:
            continue
        ei, side, ep, inside = f
        if stop == "extreme":
            if side == 1:
                sl = min(O, D["l"][i0:ei].min()) if ei > i0 else O
            else:
                sl = max(O, D["h"][i0:ei].max()) if ei > i0 else O
            if (ep - sl) * side <= 0:
                continue
        else:
            sl = np.nan
        xi, xp, why = run_exit(D, side, ei, ep, sl, np.nan, xl, inside)
        rows.append((d, side, ei, ep, xi, xp, why))
    return rows


# ── Andrea Unger ────────────────────────────────────────────────────────────────


def unger_range(D, C, days, hours, stop, filt):
    """Unger's early intraday system (DAX, S&P): breakout of the high/low of the session's first 2-3 hours
    with OCO stops (0.01% beyond); no target; stop at the range's other side or 0.5 x ATR14; out at the
    close. Anti-chop filter 'compression': only after a session narrower than its 10-session average."""
    rows = []
    for d in days:
        w = C.window(d)
        atr = C.atr[d]
        if C.skip[d] or w is None or not (atr == atr):
            continue
        if filt == "compression" and not (C.r1[d] < C.avg10[d]):
            continue
        i0, dl, xl = w
        ie = at(D, d, 60 * hours)
        if ie is None or ie > dl:
            continue
        hi, lo = D["h"][i0:ie].max(), D["l"][i0:ie].min()
        f = stop_entry(D, ie, dl, hi * (1 + BUFFER), lo * (1 - BUFFER))
        if f is None:
            continue
        ei, side, ep, inside = f
        sl = (lo if side == 1 else hi) if stop == "opposite" else ep - side * 0.5 * atr
        if (ep - sl) * side <= 0:
            continue
        xi, xp, why = run_exit(D, side, ei, ep, sl, np.nan, xl, inside)
        rows.append((d, side, ei, ep, xi, xp, why))
    return rows


def unger_reversal(D, C, days, tf, stop, target):
    """Unger's DAX reversal (false breakout), intraday form: on tf-minute bars, once price has traded above
    the previous session's high, the first bar to close back below it sells at the next bar's open (the
    mirror at the previous low buys). One trade a session; stop at the extreme reached so far or 0.25 x
    ATR14; target 2R or none; out at the close."""
    rows = []
    B = C.bars(tf)
    for d in days:
        h1, l1, atr = C.h1[d], C.l1[d], C.atr[d]
        w = C.window(d)
        if C.skip[d] or w is None or not (h1 == h1 and l1 == l1 and atr == atr):
            continue
        i0, dl, xl = w
        a, z = B["first"][d], B["last"][d]
        above = below = False
        hi = -np.inf
        lo = np.inf
        for j in range(a, z - 1):
            if B["end_sm"][j] > C.L - DEADLINE:
                break
            hi, lo = max(hi, B["high"][j]), min(lo, B["low"][j])
            above, below = above or B["high"][j] > h1, below or B["low"][j] < l1
            short = above and B["close"][j] < h1
            long_ = below and B["close"][j] > l1
            if not (short or long_):
                continue
            if short and long_:
                break
            side = 1 if long_ else -1
            ei = B["start"][j + 1]
            if ei > dl:
                break
            ep = D["o"][ei]
            sl = (lo if side == 1 else hi) if stop == "extreme" else ep - side * 0.25 * atr
            risk = (ep - sl) * side
            if risk <= 0:
                break
            tgt = ep + side * 2 * risk if target == "2R" else np.nan
            xi, xp, why = run_exit(D, side, ei, ep, sl, tgt, xl, False)
            rows.append((d, side, ei, ep, xi, xp, why))
            break
    return rows


def unger_bias(D, C, days, start, hold, side):
    """Unger's time-of-day bias: enter at a fixed minute of the session, hold a fixed time, one side."""
    rows = []
    for d in days:
        if C.skip[d]:
            continue
        ie = at(D, d, start)
        xl = last_before(D, d, min(start + hold, C.L))
        if ie is None or xl is None or xl <= ie:
            continue
        rows.append((d, side, ie, D["o"][ie], xl, D["c"][xl], "time"))
    return rows


# ── registry ────────────────────────────────────────────────────────────────────


@dataclass
class Family:
    key: str
    trader: str
    name: str
    source: str
    rules: str
    fn: object
    grid: dict

    def configs(self, length: int):
        g = dict(self.grid)
        if self.key == "unger_bias":     # every hour from the open that leaves the holding time before the close
            out = []
            for hold in (60, 120):
                for start in range(0, length - hold + 1, 60):
                    for side in (1, -1):
                        out.append({"start": start, "hold": hold, "side": side})
            return out
        ks = list(g)
        return [dict(zip(ks, v)) for v in itertools.product(*[g[k] for k in ks])]


FAMILIES = [
    Family("crabel_orb", "Toby Crabel", "Opening-range breakout with the stretch, every day",
           "Crabel, T. (1990). Day Trading with Short Term Price Patterns and Opening Range Breakout. Traders Press.",
           "Buy-stop at open + k x stretch, sell-stop at open - k x stretch; first fill trades; stop at the other level or none; out at the close.",
           crabel_orb, {"k": [0.5, 1.0, 1.5], "stop": ["opposite", "none"]}),
    Family("crabel_nr", "Toby Crabel", "Opening-range breakout after a narrow-range day (NR4, NR7, ID/NR4)",
           "Crabel (1990), chapters on NR4, NR7 and inside-day/NR4 patterns followed by an opening-range breakout.",
           "The same breakout, only on sessions after the pattern.",
           crabel_nr, {"pattern": ["NR4", "NR7", "ID_NR4"], "k": [0.5, 1.0, 1.5], "stop": ["opposite", "none"]}),
    Family("williams_vbo", "Larry Williams", "Volatility breakout, day-trade form",
           "Williams, L. (1999). Long-Term Secrets to Short-Term Trading. Wiley.",
           "Buy-stop at open + k x previous range (sell-stop below for shorts); stop half the range or none; out at the close.",
           williams_vbo, {"k": [0.3, 0.5, 0.7], "direction": ["both", "long"], "stop": ["none", "half_range"]}),
    Family("williams_oops", "Larry Williams", "Oops! (failed opening gap), intraday form",
           "Williams (1999); Stocks & Commodities 'The Oops pattern'. Original exit: the close or the first profitable open.",
           "Open below the previous low -> buy-stop at that low (above the previous high -> sell-stop at it); stop at the extreme before entry or none; out at the close.",
           williams_oops, {"direction": ["both", "long"], "gap": [0.0, 0.1], "stop": ["extreme", "none"]}),
    Family("unger_range", "Andrea Unger", "Breakout of the first 2-3 hours' range",
           "Unger's early intraday DAX/S&P system (Better System Trader ep. 16): first 2-3 hours' high/low, chop filter, stop, no target, out at the end of the day.",
           "OCO stops beyond the first hours' range; stop at the other side or 0.5 x ATR14; optional compression filter; out at the close.",
           unger_range, {"hours": [2, 3], "stop": ["opposite", "atr"], "filt": ["none", "compression"]}),
    Family("unger_reversal", "Andrea Unger", "False breakout of the previous day's high/low",
           "Unger Academy, 'Trading Systems on Dax: Two Reversal Strategies' (15-minute false breakouts of the previous day's extremes).",
           "After trading beyond the previous high (low), the first bar closing back inside reverses at the next bar's open; stop at the extreme or 0.25 x ATR14; target 2R or none; out at the close.",
           unger_reversal, {"tf": [15, 30], "stop": ["extreme", "atr"], "target": ["none", "2R"]}),
    Family("unger_bias", "Andrea Unger", "Time-of-day bias",
           "Unger's bias systems (Better System Trader ep. 16; Unger Academy intraday-bias examples).",
           "Enter at the open or a whole hour after it, hold 60 or 120 minutes, long or short.",
           unger_bias, {}),
]


def label(cfg: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in cfg.items())
