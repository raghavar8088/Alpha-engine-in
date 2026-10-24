"""The three trader-style setups of PREREGISTRATION.md, coded on the New York session clock.

Session minute sm: 0 = 18:00 New York, 120 = 20:00, 540 = 03:00, 840 = 08:00, 860 = 08:20, 870 = 08:30,
890 = 08:50, 1080 = 12:00, 1380 = 17:00. Fills use the intraday study's engine (xi_engine): stop entries
at their level (or a worse open), the worse outcome inside a minute, a stop before a target.
Each row: (day, side, entry index, entry price, exit index, exit price, reason, risk = stop distance).
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

SM = {"2000": 120, "0300": 540, "0800": 840, "0820": 860, "0830": 870, "0850": 890, "1200": 1080, "1700": 1380}


class Context:
    def __init__(self, D: dict):
        self.D = D
        c = pd.Series(D["d_c"])
        lag = lambda s: s.shift(1).to_numpy()
        self.close_prev = lag(c)
        self.sma = {n: lag(c.rolling(n, min_periods=n).mean()) for n in (20, 50, 200)}
        pc = c.shift(1)
        tr = pd.concat([pd.Series(D["d_h"]) - pd.Series(D["d_l"]), (pd.Series(D["d_h"]) - pc).abs(), (pd.Series(D["d_l"]) - pc).abs()], axis=1).max(axis=1)
        self.atr = lag(tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean())
        self._b5 = None

    def trend(self, d: int, kind: str) -> int:
        fast, slow = (20, 50) if kind == "20/50" else (50, 200)
        c, f, s = self.close_prev[d], self.sma[fast][d], self.sma[slow][d]
        if not (c == c and f == f and s == s):
            return 0
        if c > s and f > s:
            return 1
        if c < s and f < s:
            return -1
        return 0

    def bars5(self):
        """Five-minute bars inside sessions, with a continuous EMA20 of their closes."""
        if self._b5 is None:
            D = self.D
            key = D["sess"].astype(np.int64) * 1000 + (D["sm"] // 5)
            st = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
            en = np.r_[st[1:], len(key)] - 1
            close = D["c"][en]
            low = np.minimum.reduceat(D["l"], st)
            high = np.maximum.reduceat(D["h"], st)
            ema = pd.Series(close).ewm(span=20, adjust=False, min_periods=20).mean().to_numpy()
            sess = D["sess"][st]
            self._b5 = {"start": st, "end": en, "close": close, "low": low, "high": high, "ema": ema, "sess": sess,
                        "sm0": (D["sm"][st] // 5) * 5,
                        "first": np.searchsorted(sess, np.arange(sess.max() + 1), side="left"),
                        "last": np.searchsorted(sess, np.arange(sess.max() + 1), side="right")}
        return self._b5


def london(D, C, days, k, trend, exit):
    rows = []
    t_exit = SM["1200"] if exit == "1159" else SM["1700"]
    for d in days:
        tr = C.trend(d, trend)
        atr = C.atr[d]
        if tr == 0 or not (atr == atr):
            continue
        ia, ib = at(D, d, SM["2000"]), at(D, d, SM["0300"])
        we, xl = last_before(D, d, SM["0800"]), last_before(D, d, t_exit)
        if None in (ia, ib, we, xl) or we <= ib:
            continue
        hi, lo = D["h"][ia:ib].max(), D["l"][ia:ib].min()
        if not (0.1 * atr <= hi - lo <= 0.8 * atr):
            continue
        buf = 0.0002 * hi
        f = stop_entry(D, ib, we, hi + buf if tr == 1 else np.nan, lo - buf if tr == -1 else np.nan)
        if f is None:
            continue
        ei, side, ep, inside = f
        risk = min(abs(ep - (lo if side == 1 else hi)), 0.5 * atr)
        if risk <= 0:
            continue
        xi, xp, why = run_exit(D, side, ei, ep, ep - side * risk, ep + side * k * risk, xl, inside)
        rows.append((d, side, ei, ep, xi, xp, why, risk))
    return rows


def ny_pullback(D, C, days, k, trend, breakeven):
    rows = []
    B = C.bars5()
    for d in days:
        tr = C.trend(d, trend)
        atr = C.atr[d]
        if tr == 0 or not (atr == atr) or d >= len(B["first"]):
            continue
        xl = last_before(D, d, SM["1700"])
        if xl is None:
            continue
        a, z = B["first"][d], B["last"][d]
        pulled = False
        for j in range(a, z - 1):
            s0 = B["sm0"][j]
            if s0 < SM["0830"]:
                continue
            if s0 >= SM["1200"]:
                break
            cl, e = B["close"][j], B["ema"][j]
            if not (e == e):
                continue
            if (tr == 1 and cl < e) or (tr == -1 and cl > e):
                pulled = True
                continue
            if pulled and ((tr == 1 and cl > e) or (tr == -1 and cl < e)):
                ei = B["start"][j + 1]
                if ei > xl:
                    break
                ep = D["o"][ei]
                lo6 = B["low"][max(a, j - 5):j + 1].min()
                hi6 = B["high"][max(a, j - 5):j + 1].max()
                stop = lo6 - 0.0002 * lo6 if tr == 1 else hi6 + 0.0002 * hi6
                risk = (ep - stop) * tr
                if not (0.1 * atr <= risk <= 0.5 * atr):
                    pulled = False
                    continue
                be = ep + tr * risk if breakeven == "1R" else np.nan
                xi, xp, why = run_exit(D, tr, ei, ep, stop, ep + tr * k * risk, xl, False, be)
                rows.append((d, tr, ei, ep, xi, xp, why, risk))
                break
    return rows


def ny_orb(D, C, days, k, trend, breakeven):
    rows = []
    for d in days:
        tr = C.trend(d, trend)
        atr = C.atr[d]
        if tr == 0 or not (atr == atr):
            continue
        i0, i1 = at(D, d, SM["0820"]), at(D, d, SM["0850"])
        we, xl = last_before(D, d, SM["1200"]), last_before(D, d, SM["1700"])
        if None in (i0, i1, we, xl) or we <= i1:
            continue
        hi, lo = D["h"][i0:i1].max(), D["l"][i0:i1].min()
        buf = 0.0002 * hi
        f = stop_entry(D, i1, we, hi + buf if tr == 1 else np.nan, lo - buf if tr == -1 else np.nan)
        if f is None:
            continue
        ei, side, ep, inside = f
        far = lo if side == 1 else hi
        risk = abs(ep - far)
        if not (0.1 * atr <= risk <= 0.5 * atr):
            continue
        be = ep + side * risk if breakeven == "1R" else np.nan
        xi, xp, why = run_exit(D, side, ei, ep, far, ep + side * k * risk, xl, inside, be)
        rows.append((d, side, ei, ep, xi, xp, why, risk))
    return rows


@dataclass
class Setup:
    key: str
    name: str
    rules: str
    fn: object
    grid: dict
    default: dict

    def configs(self):
        ks = list(self.grid)
        for vals in itertools.product(*[self.grid[x] for x in ks]):
            yield dict(zip(ks, vals))


SETUPS = [
    Setup("london", "London-open breakout with the trend",
          "Asian range 20:00-02:59 NY; 03:00-07:59 a stop order 0.02% beyond the range in the trend's direction; range 0.1-0.8 x ATR14; "
          "stop at the far side (max 0.5 x ATR14); target k x R; exit 11:59 or 16:59.",
          london, {"k": [2, 3], "trend": ["20/50", "50/200"], "exit": ["1159", "1659"]}, {"k": 2, "trend": "20/50", "exit": "1659"}),
    Setup("ny_pullback", "New York pullback with the trend",
          "08:30-11:59 NY, 5-minute bars: after a close on the wrong side of the EMA20, the first close back on the trend's side enters at the "
          "next bar's open; stop beyond the last six bars' extreme (0.1-0.5 x ATR14); target k x R; optional break-even at 1R; exit 16:59.",
          ny_pullback, {"k": [2, 3], "trend": ["20/50", "50/200"], "breakeven": ["off", "1R"]}, {"k": 2, "trend": "20/50", "breakeven": "off"}),
    Setup("ny_orb", "New York opening-range breakout with the trend",
          "30-minute range from 08:20 NY; 08:50-11:59 a stop order 0.02% beyond it in the trend's direction; stop at the far side "
          "(0.1-0.5 x ATR14); target k x R; optional break-even at 1R; exit 16:59.",
          ny_orb, {"k": [2, 3], "trend": ["20/50", "50/200"], "breakeven": ["off", "1R"]}, {"k": 2, "trend": "20/50", "breakeven": "off"}),
]


def label(cfg: dict) -> str:
    return ", ".join(f"{a}={b}" for a, b in cfg.items())
