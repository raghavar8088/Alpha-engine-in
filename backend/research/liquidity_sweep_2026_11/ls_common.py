"""Shared plumbing for the liquidity-sweep study: clean imports, NIFTY minute data, candles, fills, fees.

Run every script with `python -I` from anywhere. Isolated mode keeps the local venv's stale
`tradingai_shared` / `strategy_service` (TradingAI/) out; the repo's own packages go first on
sys.path below, and any cached copies are evicted before the first import.
"""

from __future__ import annotations

import gzip
import hashlib
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # d:/INDIAN MARKET
HERE = Path(__file__).resolve().parent
for _p in (ROOT / "backend", ROOT / "options-service", ROOT / "strategy-service", ROOT / "shared"):
    sys.path.insert(0, str(_p))
for _m in [m for m in sys.modules if m.split(".")[0] in ("tradingai_shared", "strategy_service", "options_service", "app")]:
    del sys.modules[_m]

import numpy as np  # noqa: E402

import strategy_service.strategies.options_buying  # noqa: E402,F401  (registers the library)
from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext  # noqa: E402,F401  (re-exported)
from tradingai_shared.domain import Bar, SignalAction, Timeframe  # noqa: E402,F401  (re-exported)

assert Path(sys.modules["strategy_service"].__file__).resolve().is_relative_to(ROOT / "strategy-service"), \
    "loaded a stale strategy_service — run with python -I"

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
OPEN_MIN = 9 * 60 + 15
SESSION_MIN = 375
STRATEGY_ID = "bb_liquidity_sweep"

STORE_1M = ROOT / "backend" / "research" / "index_intraday_2026_10" / "data" / "1m" / "NIFTY"   # 30-day windows to 9 Oct 2026
BOX_1M = ROOT / "backend" / "research" / "niftybees_orb_2026_10" / "data" / "box_1m" / "NIFTY"  # server daily files from 12 Oct 2026
EXTRA_1M = HERE / "data" / "box_1m" / "NIFTY"                                                   # anything fetched for this study

PERIODS = {
    "P": (date(2025, 9, 24), date(2026, 10, 19)),   # the span the PDF's 42 examples come from (primary)
    "F": (date(2026, 10, 20), date(2026, 12, 31)),  # after the PDF
    "H": (date(2016, 1, 1), date(2025, 9, 23)),     # every earlier session on disk
}
RUNS = {
    "A": {"minutes": 5, "params": {}},
    "B": {"minutes": 5, "params": {"ema_filter": 200}},
    "C": {"minutes": 3, "params": {"bar_minutes": 3}},
}

LOT = 65                  # NIFTY lot (costs are per lot; R and points do not depend on it)
SLIP_PTS = 1.0            # index points of slippage on every fill


def prereg_hash() -> str:
    """SHA-256 of the rule card with LF line ends (as committed), so a CRLF checkout hashes the same."""
    return hashlib.sha256((HERE / "PREREGISTRATION.md").read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ── minute data ────────────────────────────────────────────────────────────────────────

def _read_dir(folder: Path) -> list[np.ndarray]:
    parts = []
    for f in sorted(folder.glob("*.csv.gz")) if folder.exists() else []:
        rows = []
        with gzip.open(f, "rt") as fh:
            next(fh, None)
            for line in fh:
                bits = line.strip().split(",")
                if len(bits) < 5:
                    continue
                try:
                    vals = [float(x) if x else 0.0 for x in bits[:6]] + [0.0] * (6 - len(bits[:6]))
                except ValueError:
                    continue
                rows.append(vals)
        if rows:
            parts.append(np.asarray(rows, dtype=float))
    return parts


def load_minutes():
    """All NIFTY sessions on disk as the index-intraday module's own cleaned `Days`
    (dates x 375 minutes, 09:15..15:29; bad prints dropped, mornings-missing / short days
    dropped, gaps flat-filled) — built by that module's `_build`, so the cleaning is the app's."""
    from app.services.index_intraday import data as ii_data

    parts = _read_dir(STORE_1M) + _read_dir(BOX_1M) + _read_dir(EXTRA_1M)
    rows = np.concatenate(parts)
    return ii_data._build("NIFTY", rows)


class Market:
    """Minute matrices plus candle builders and a date index."""

    def __init__(self, days):
        self.days = days
        self.dates = [date.fromisoformat(str(d)) for d in days.dates]
        self.index = {d: i for i, d in enumerate(self.dates)}
        self.o, self.h, self.l, self.c = days.o, days.h, days.l, days.c

    def minute_ts(self, i: int, m: int) -> datetime:
        d = self.dates[i]
        return datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST) + timedelta(minutes=m)

    def candles(self, i: int, minutes: int) -> list[Bar]:
        out = []
        for start in range(0, SESSION_MIN, minutes):
            stop = min(start + minutes, SESSION_MIN)
            out.append(Bar(
                symbol="NIFTY", timeframe=Timeframe.M5 if minutes != 1 else Timeframe.M1,
                ts=self.minute_ts(i, start).astimezone(UTC),
                open=float(self.o[i, start]), high=float(self.h[i, start:stop].max()),
                low=float(self.l[i, start:stop].min()), close=float(self.c[i, stop - 1])))
        return out


def session_range(mk: Market, first: date, last: date) -> list[int]:
    return [i for i, d in enumerate(mk.dates) if first <= d <= last]


# ── fills ──────────────────────────────────────────────────────────────────────────────

SQUARE_OFF = 15 * 60 + 15 - OPEN_MIN      # minute index 360 = 15:15; exit at the 15:14 close


def walk(mk: Market, i: int, m0: int, side: int, stop: float, target: float, last_minute: int = SQUARE_OFF,
         carry_days: int = 0):
    """Walk 1-minute candles from minute m0 of session i. Returns (exit_price, reason, day_index,
    minute, both_in_one_minute). Stop first when one minute touches both; a minute opening
    beyond the stop fills at its open. Exit at the close of the minute before `last_minute`
    if neither is touched (carry_days > 0 walks into later sessions, for the PDF's overnight trade)."""
    day, m = i, m0
    remaining = carry_days
    while True:
        end = last_minute
        while m < end:
            o, h, lo = mk.o[day, m], mk.h[day, m], mk.l[day, m]
            if side < 0:
                s_hit, t_hit = h >= stop, lo <= target
                if s_hit:
                    return (max(o, stop), "stop", day, m, bool(t_hit))
                if t_hit:
                    return (target, "target", day, m, False)   # a resting limit: no price improvement
            else:
                s_hit, t_hit = lo <= stop, h >= target
                if s_hit:
                    return (min(o, stop), "stop", day, m, bool(t_hit))
                if t_hit:
                    return (target, "target", day, m, False)
            m += 1
        if remaining <= 0 or day + 1 >= len(mk.dates):
            return (float(mk.c[day, end - 1]), "15:15", day, end - 1, False)
        remaining -= 1
        day, m = day + 1, 0


# ── fees: Angel One futures, the formula of backend/app/services/angel_fees.futures_round_trip ──

FUT_BROKERAGE = 20.0
FUT_STAMP_BUY = 0.00002
SEBI_TURNOVER = 0.000001
NSE_IPFT = 0.000001
GST_RATE = 0.18
FUT_STT_SELL_SCHEDULE = [(date(2026, 4, 1), 0.0005), (date(2024, 10, 1), 0.0002), (date(1900, 1, 1), 0.000125)]
FUT_EXCHANGE_SCHEDULE = [(date(2024, 10, 1), 0.0000173), (date(1900, 1, 1), 0.00002)]


def _rate(schedule, on: date) -> float:
    for start, rate in schedule:
        if on >= start:
            return rate
    return schedule[-1][1]


def futures_fees(entry: float, exit_: float, qty: int, side: int, on: date) -> float:
    """Rupees for opening and closing `qty` NIFTY futures. side +1 = long (buy first)."""
    buy = (entry if side > 0 else exit_) * qty
    sell = (exit_ if side > 0 else entry) * qty
    turnover = buy + sell
    brokerage = FUT_BROKERAGE * 2
    stt = sell * _rate(FUT_STT_SELL_SCHEDULE, on)
    exch = turnover * _rate(FUT_EXCHANGE_SCHEDULE, on)
    sebi = turnover * SEBI_TURNOVER
    ipft = turnover * NSE_IPFT
    stamp = buy * FUT_STAMP_BUY
    gst = GST_RATE * (brokerage + exch + sebi + ipft)
    return round(brokerage + stt + exch + sebi + ipft + stamp + gst, 2)
