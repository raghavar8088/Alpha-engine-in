"""Shared toolkit for the BANKNIFTY option-buying research (2026-10-11).

Everything the replays share lives here so that every strategy is priced, charged and
timed the same way:

  bars      NIFTY BANK / NIFTY / India VIX 5-minute bars from Angel (2015-01 .. 2026-10-09),
            grouped into sessions; Muhurat and broken sessions (< 60 bars) are dropped
  clock     the variance clock the NIFTY research calibrated on 5,800 real option trades:
            trading minutes + 0.2 of a session per calendar night, 325 sessions a year
  pricing   Black-76 on the forward; implied vols from REAL option closes (NSE bhavcopy)
  costs     Angel One's rate card at TODAY's rates on every trade (the question is whether a
            strategy pays its way now), plus a half-spread on each side
  contract  what BANKNIFTY lists now: monthly expiries only, strikes 100 apart, lot 30

Paths: BN_DATA points at the downloaded data (not committed; see bn_fetch_*.py).
"""

from __future__ import annotations

import gzip
import json
import math
import os
import sys
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DATA = os.environ.get("BN_DATA", os.path.join(HERE, "data"))
for p in (os.path.join(REPO, "shared"), os.path.join(REPO, "strategy-service"), os.path.join(REPO, "options-service")):
    if p not in sys.path:
        sys.path.insert(0, p)

IST = timezone(timedelta(hours=5, minutes=30))
LOT = 30
STEP = 100
R = 0.065                      # discount rate (only discounts; the forward comes from the market)
CARRY = 0.058                  # forward = spot * exp(CARRY * T): r minus BANKNIFTY's ~0.7% yield
W_NIGHT = 0.2
SESS_PER_YEAR = 252 + 365 * W_NIGHT
OPEN_MIN, CLOSE_MIN = 9 * 60 + 15, 15 * 60 + 30
SQUARE_OFF_MIN = 15 * 60 + 15
NO_ENTRY_AFTER_MIN = 15 * 60       # no new position on a bar ending after 15:00
HALF_SPREAD = float(os.environ.get("BN_HALF_SPREAD", "0.0025"))   # of premium, per side
MIN_TICK = 0.05
# How much of India VIX's move since the previous close passes into BANKNIFTY's option vol:
# vol *= (VIX now / VIX at the previous close) ** VIX_BETA. Calibrated on EXPLORE (bn_calibrate.py).
VIX_BETA = float(os.environ.get("BN_VIX_BETA", "0.4"))
# "strike": each strike keeps the previous close's vol (x = ln K / F at the previous close);
# "moneyness": the smile moves with the forward. bn_calibrate.py chose strike + beta 0.4 on
# EXPLORE (rms 7.12% vs 8.18% for moneyness + beta 1); HOLDOUT bias -0.06% a day.
SMILE = os.environ.get("BN_SMILE", "strike")
# Contract rule, fixed before any result: buy the nearest MONTHLY with at least this many
# sessions left (today counts); inside that, the next monthly. A last-week monthly decays
# like a weekly (theta of 10-20% of premium a day), which no intraday edge here can carry.
MIN_SESSIONS_LEFT = 7
RESEARCH_START = date(2016, 1, 1)          # India VIX 5m bars start 2015-12-01
EXPLORE_END = date(2021, 12, 31)           # EXPLORE 2016-2021 | HOLDOUT 2022-01 .. 2026-10-09
DATA_END = date(2026, 10, 9)


# ── time ────────────────────────────────────────────────────────────────────────


def dkey(e: int) -> int:
    return (e + 19800) // 86400


def kdate(k: int) -> date:
    return date(1970, 1, 1) + timedelta(days=k)


def dk(d: date) -> int:
    return (d - date(1970, 1, 1)).days


def minute(e: int) -> int:
    return ((e + 19800) % 86400) // 60


def ist(e: int) -> datetime:
    return datetime.fromtimestamp(e, IST)


def at(k: int, hm: int) -> int:
    """Epoch of minute-of-day hm (IST) on day key k."""
    return k * 86400 - 19800 + hm * 60


def period(k: int) -> str:
    return "explore" if kdate(k) <= EXPLORE_END else "holdout"


# ── bars ────────────────────────────────────────────────────────────────────────


def load_rows(name: str) -> list[list[float]]:
    with gzip.open(os.path.join(DATA, f"{name}.json.gz"), "rt") as f:
        return json.load(f)


class Sessions:
    """5m bars of one instrument, by session. Only complete sessions (>= 60 bars starting
    09:15) from RESEARCH_START are kept."""

    def __init__(self, name: str, start: date = RESEARCH_START):
        rows = load_rows(f"{name}_5")
        by: dict[int, list] = {}
        for r in rows:
            by.setdefault(dkey(int(r[0])), []).append(r)
        k0 = dk(start)
        self.days = [k for k in sorted(by) if k >= k0 and len(by[k]) >= 60 and minute(int(by[k][0][0])) == OPEN_MIN]
        self.bars = {k: by[k] for k in self.days}
        self.t = [int(r[0]) for k in self.days for r in self.bars[k]]
        self.c = [r[4] for k in self.days for r in self.bars[k]]
        self.all_days = sorted(by)          # every session incl. short ones (for the clock)

    def close_before(self, e: int, max_age: int = 86400 * 5) -> float | None:
        """Close of the last 5m bar that ENDED at or before epoch e."""
        i = bisect_right(self.t, e - 300) - 1
        return self.c[i] if i >= 0 and e - self.t[i] < max_age else None

    def last_close(self, k: int) -> float | None:
        b = self.bars.get(k)
        return b[-1][4] if b else None


# ── the variance clock ──────────────────────────────────────────────────────────

_TRADING: list[int] = []
_TRADING_SET: set[int] = set()


def set_trading_days(keys: list[int]) -> None:
    """Sessions known from the data, extended past DATA_END with NSE's published calendar."""
    from tradingai_shared import nse_calendar
    global _TRADING, _TRADING_SET
    ks = set(keys)
    d = DATA_END + timedelta(days=1)
    while d <= date(2027, 12, 31):
        if d.weekday() < 5 and nse_calendar.is_listed_trading_day(d):
            ks.add(dk(d))
        d += timedelta(days=1)
    _TRADING = sorted(ks)
    _TRADING_SET = set(_TRADING)


def sessions_left(e: int, expiry_k: int) -> float:
    """Variance-clock sessions from epoch e to 15:30 on the expiry day."""
    k, m = dkey(e), minute(e)
    if k > expiry_k:
        return 0.0
    frac = max(0, CLOSE_MIN - max(m, OPEN_MIN)) / (CLOSE_MIN - OPEN_MIN) if k in _TRADING_SET else 0.0
    full = bisect_right(_TRADING, expiry_k) - bisect_right(_TRADING, k)
    return frac + full + W_NIGHT * (expiry_k - k)


def trading_sessions_left(k: int, expiry_k: int) -> int:
    """Whole NSE sessions from day k to the expiry day, both counted."""
    return bisect_right(_TRADING, expiry_k) - bisect_left(_TRADING, k)


def T_years(e: int, expiry_k: int) -> float:
    return max(sessions_left(e, expiry_k), 1e-4) / SESS_PER_YEAR


def T_cal(e: int, expiry_k: int) -> float:
    return max(at(expiry_k, CLOSE_MIN) - e, 60) / (365 * 86400)


# ── Black-76 ────────────────────────────────────────────────────────────────────


def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / 1.4142135623730951))


def b76(F: float, K: float, T: float, sig: float, call: bool, disc: float = 1.0) -> float:
    if T <= 0 or sig <= 0:
        return disc * max(0.0, (F - K) if call else (K - F))
    v = sig * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    if call:
        return disc * (F * ncdf(d1) - K * ncdf(d2))
    return disc * (K * ncdf(-d2) - F * ncdf(-d1))


def implied_vol(price: float, F: float, K: float, T: float, call: bool, disc: float = 1.0) -> float | None:
    intrinsic = disc * max(0.0, (F - K) if call else (K - F))
    if price <= intrinsic + 0.01 or T <= 0:
        return None
    lo, hi = 0.005, 3.0
    if b76(F, K, T, hi, call, disc) < price:
        return None
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if b76(F, K, T, mid, call, disc) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


# ── costs ───────────────────────────────────────────────────────────────────────
# Angel One, rates in force on 2026-10-11 (tradingai_shared.option_fees for the dated
# schedule): Rs20 an order, STT 0.15% of premium sold, exchange 0.0355299%, SEBI Rs10/crore,
# stamp 0.003% of premium bought, GST 18% on brokerage + exchange + SEBI.


def fees(p_in: float, p_out: float, qty: int = LOT, legs: int = 1) -> float:
    t_in, t_out = p_in * qty, max(p_out, 0.0) * qty
    brok = 20.0 * 2 * legs
    exch = (t_in + t_out) * 0.000355299
    sebi = (t_in + t_out) * 0.000001
    return brok + exch + sebi + 0.18 * (brok + exch + sebi) + t_out * 0.0015 + t_in * 0.00003


def half_spread(p: float) -> float:
    return max(MIN_TICK, p * HALF_SPREAD)


def net_pnl(p_in: float, p_out: float, qty: int = LOT) -> float:
    """Bought at mid + half spread, sold at mid - half spread, charged Angel's rate card."""
    buy, sell = p_in + half_spread(p_in), max(0.0, p_out - half_spread(p_out))
    return (sell - buy) * qty - fees(buy, sell, qty)


# ── stats ───────────────────────────────────────────────────────────────────────


def tstat(xs: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m / math.sqrt(v / n) if v > 0 else None


def day_clustered(rows: list[tuple[int, float]]) -> tuple[float | None, int]:
    """t of the mean daily P&L (trades on one day summed): correlated same-day trades are
    one observation, not several."""
    by: dict[int, float] = {}
    for k, x in rows:
        by[k] = by.get(k, 0.0) + x
    xs = list(by.values())
    return tstat(xs), len(xs)


def dsr(sr: float, n_obs: int, sr_var: float, n_trials: int, skew: float = 0.0, kurt: float = 3.0) -> float | None:
    """Deflated Sharpe ratio (Bailey & Lopez de Prado), per-observation Sharpe."""
    from statistics import NormalDist
    if n_obs < 30 or n_trials < 2 or sr_var <= 0:
        return None
    nd, eul = NormalDist(), 0.5772156649
    sr0 = math.sqrt(sr_var) * ((1 - eul) * nd.inv_cdf(1 - 1 / n_trials) + eul * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    den = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    return nd.cdf((sr - sr0) * math.sqrt(n_obs - 1) / den)
