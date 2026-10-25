"""Shared toolkit for the NIFTY ATM option ORB test (2026-10-25).

The premium model is the one the BANKNIFTY research built and validated
(../banknifty_2026_10/bn_common.py, bn_surface.py, bn_price.py), redone for NIFTY's weekly options:

  clock     variance clock: trading minutes + 0.2 of a session per calendar night, 325 sessions a
            year (calibrated on 5,800 real NIFTY option trades in ../prelive_2026_10)
  surface   per session and expiry, from REAL NSE closing prices (bhavcopy): the put-call-parity
            forward and a quadratic smile in ln(K/F)
  price     a contract traded on session k is priced off session k-1's real smile for that very
            expiry (each strike keeps its vol: sticky strike), times (India VIX now / VIX at k-1's
            close) ** VIX_BETA, Black-76 on the forward; nothing from session k's own option prices
            is used
  costs     Angel One's option charges at today's rates (app.services.angel_fees), one lot of today's
            65 units, plus the measured bid-ask spread and a tick of slippage on every fill
"""

from __future__ import annotations

import math
import sys
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for _p in (REPO / "options-service", REPO / "shared", REPO / "backend", HERE.parent / "niftybees_orb_2026_10"):
    if str(_p) in sys.path:
        sys.path.remove(str(_p))
    sys.path.insert(0, str(_p))

IST = timezone(timedelta(hours=5, minutes=30))
DATA = HERE / "data"
RES = HERE / "results"
STEP = 50                         # NIFTY weekly strikes
LOT = 65                          # today's NIFTY lot (it was 50, then 25, then 75 in the window)
R = 0.065                         # discount rate
CARRY = 0.052                     # forward = spot * exp(CARRY * years): ~6.5% rate less NIFTY's ~1.3% yield
W_NIGHT = 0.2
SESS_PER_YEAR = 252 + 365 * W_NIGHT
OPEN_MIN, CLOSE_MIN = 9 * 60 + 15, 15 * 60 + 30
TICK = 0.05
HALF_SPREAD = 0.0015              # of premium, a side: measured ATM same-week median 0.115%, p90 0.15%
SLIP_TICKS = 1                    # plus one tick against every market fill
VIX_BETA = 0.4                    # replaced by nopt_calibrate.py's choice (results/calibration.json)
SMILE = "strike"


# ── calendar and clock ─────────────────────────────────────────────────────────────────────────────

def dk(d: date) -> int:
    return (d - date(1970, 1, 1)).days


def kdate(k: int) -> date:
    return date(1970, 1, 1) + timedelta(days=k)


def at(k: int, hm: int) -> int:
    """Epoch of minute-of-day hm (IST, minutes after midnight) on day key k."""
    return k * 86400 - 19800 + hm * 60


def dkey(e: int) -> int:
    return (e + 19800) // 86400


def minute_of_day(e: int) -> int:
    return ((e + 19800) % 86400) // 60


_TRADING: list[int] = []
_TRADING_SET: set[int] = set()


def set_calendar() -> None:
    """NSE sessions: weekdays less exchange holidays plus weekend sessions (the list orb_data.py
    reconciled with the data), through 2026, from the shared calendar for 2026."""
    import orb_data as OD
    hol = OD._holidays()
    ks = []
    d = date(2021, 9, 1)
    while d <= date(2026, 12, 31):
        iso = d.isoformat()
        if (d.weekday() < 5 and iso not in hol) or iso in OD.SPECIAL_SESSIONS:
            if iso not in ("2024-03-02", "2024-05-18"):          # DR drills were not full sessions
                ks.append(dk(d))
        d += timedelta(days=1)
    global _TRADING, _TRADING_SET
    _TRADING, _TRADING_SET = ks, set(ks)


import os  # noqa: E402

# The clock inside a session: "u" counts each minute by its share of a day's variance
# (nopt_clock.py, NIFTY 2021-23); "flat" counts every minute alike (the first model).
CLOCK = os.environ.get("NOPT_CLOCK", "u")
_PROFILE: dict = {}


def _profile() -> dict:
    if not _PROFILE:
        import json
        p = DATA / "clock_profile.json"
        if p.exists():
            _PROFILE.update(json.load(open(p, encoding="utf-8")))
    return _PROFILE


def day_left(e: int, expiry_day: bool) -> float:
    """Share of today's session still to come at epoch e (0 after 15:30, 1 before 09:15)."""
    m_full = (e + 19800) % 86400 / 60.0 - OPEN_MIN             # minutes since 09:15, fractional
    if m_full <= 0:
        return 1.0
    if m_full >= CLOSE_MIN - OPEN_MIN:
        return 0.0
    prof = _profile()
    if CLOCK == "flat" or not prof:
        return (CLOSE_MIN - OPEN_MIN - m_full) / (CLOSE_MIN - OPEN_MIN)
    rem = prof["expiry" if expiry_day else "other"]
    m = int(m_full)
    return rem[m + 1] + (rem[m] - rem[m + 1]) * (1 - (m_full - m))


def sessions_left(e: int, expiry_k: int) -> float:
    """Variance-clock sessions from epoch e to 15:30 on the expiry day."""
    k = dkey(e)
    if k > expiry_k:
        return 0.0
    frac = day_left(e, k == expiry_k) if k in _TRADING_SET else 0.0
    full = bisect_right(_TRADING, expiry_k) - bisect_right(_TRADING, k)
    return frac + full + W_NIGHT * (expiry_k - k)


def trading_sessions_between(k0: int, k1: int) -> int:
    """Sessions from day k0 to day k1, both counted."""
    return bisect_right(_TRADING, k1) - bisect_left(_TRADING, k0)


def T_years(e: int, expiry_k: int) -> float:
    return max(sessions_left(e, expiry_k), 1e-4) / SESS_PER_YEAR


def T_cal(e: int, expiry_k: int) -> float:
    return max(at(expiry_k, CLOSE_MIN) - e, 60) / (365 * 86400)


# ── Black-76 ───────────────────────────────────────────────────────────────────────────────────────

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
    lo, hi = 0.005, 4.0
    if b76(F, K, T, hi, call, disc) < price:
        return None
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if b76(F, K, T, mid, call, disc) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def fit_smile(pts: list[tuple[float, float]]):
    """Least squares iv = a + b x + c x^2 on (x, iv) points (bn_surface.fit_smile)."""
    import statistics
    n = len(pts)
    if n < 4:
        return (statistics.mean(v for _, v in pts), 0.0, 0.0) if pts else None
    s = [sum(x ** p for x, _ in pts) for p in range(5)]
    t = [sum(v * x ** p for x, v in pts) for p in range(3)]
    m = [[s[0], s[1], s[2]], [s[1], s[2], s[3]], [s[2], s[3], s[4]]]

    def det3(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    det = det3(m)
    if abs(det) < 1e-18:
        return statistics.mean(v for _, v in pts), 0.0, 0.0
    out = []
    for col in range(3):
        mm = [row[:] for row in m]
        for i in range(3):
            mm[i][col] = t[i]
        out.append(det3(mm) / det)
    return tuple(out)


# ── costs ──────────────────────────────────────────────────────────────────────────────────────────

def buy_fill(mid: float) -> float:
    p = mid * (1 + HALF_SPREAD) + SLIP_TICKS * TICK
    return math.ceil(p / TICK - 1e-9) * TICK


def sell_fill(mid: float) -> float:
    p = mid * (1 - HALF_SPREAD) - SLIP_TICKS * TICK
    return max(TICK, math.floor(p / TICK + 1e-9) * TICK)


def charges(p_in: float, p_out: float, qty_lot: int = LOT, side: str = "BUY") -> float:
    """Angel One's option round trip at today's rates (the app's fee model). `side` is the
    opening order: a seller pays STT on the premium it sells to open."""
    from app.services.angel_fees import option_round_trip
    return option_round_trip(p_in, p_out, 1, qty_lot, on=date(2026, 10, 23), side=side).total


EXPIRY_DAY_EXTRA_ELM = 0.02       # SEBI (from 2024-11-20): +2% of notional on short options on their expiry day


def short_margin(S: float, K: float, call: bool, premium: float, iv: float, t_years: float, expiry_day: bool,
                 qty: int = LOT) -> float:
    """Margin a broker blocks for one naked short option: the app's SPAN-lite engine
    (app.services.fno_margin, +-6% scan + 3% exposure, calibrated on NIFTY), plus the expiry-day ELM."""
    from app.services.fno_margin import portfolio_margin
    leg = {"kind": "OPTION", "option_type": "CE" if call else "PE", "strike": K, "qty": qty, "side": "SELL",
           "premium": premium, "iv": iv}
    m = portfolio_margin([leg], S, t_years)["total"]
    return m + (EXPIRY_DAY_EXTRA_ELM * S * qty if expiry_day else 0.0)


def ist(e: int) -> datetime:
    return datetime.fromtimestamp(e, IST)
