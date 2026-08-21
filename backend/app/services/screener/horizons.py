"""Multi-horizon return maths over the stored daily bars.

WHY SESSIONS, NOT CALENDAR DAYS. "This week's momentum" has to mean the last 5 TRADING
sessions, not the last 7 calendar days. NSE closes for a dozen-odd holidays a year, several
of them mid-week, and a calendar window silently shortens itself around every one — so a
Diwali week would rank differently from an ordinary week for a reason that has nothing to
do with the stocks. Every horizon here is a session count.

WEEKLY BARS ARE CALENDAR-AWARE. `nifty_scalp_strategies.resample` groups by a fixed factor
(every 5 bars), which is right for intraday timeframes and wrong for weeks: one holiday and
every subsequent "week" straddles two real ones, permanently out of phase. The resample
here buckets by ISO (year, week) so a 4-session holiday week is a 4-session weekly bar,
which is what it actually was.

DAILY BAR TIMESTAMPS. Angel returns a daily candle stamped 00:00 IST, which is stored as
18:30 UTC on the PREVIOUS date. So the trading date of a bar is always read back in IST,
never off the UTC date — reading the UTC date directly shifts every daily bar back one day
and silently misaligns every horizon by one session.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import date, datetime, timedelta, timezone

from app.core.db import bars_collection

logger = logging.getLogger("screener.horizons")


class Bar:
    """Minimal OHLCV bar.

    Defined here rather than imported from `commodity_bars` on purpose: that module pulls
    in the whole commodity desk's database surface, and the screener has no business
    depending on an MCX desk to describe an equity candle. The shape is what matters —
    the pattern detectors read `.ts/.open/.high/.low/.close/.volume` and nothing else,
    so any object with these attributes works with them.
    """

    __slots__ = ("ts", "open", "high", "low", "close", "volume")

    def __init__(self, ts: datetime, o: float, h: float, l: float, c: float, v: float):
        self.ts, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, v

    def __repr__(self) -> str:
        return f"Bar({self.ts:%Y-%m-%d} o={self.open} h={self.high} l={self.low} c={self.close})"

IST = timezone(timedelta(hours=5, minutes=30))

# Horizon -> number of trading sessions. 1w = a trading week, 1m ~ 21 sessions,
# 6m ~ 126 sessions (252 sessions in an NSE year).
HORIZONS: dict[str, int] = {"1d": 1, "1w": 5, "1m": 21, "6m": 126}
HORIZON_LABELS: dict[str, str] = {
    "1d": "Today", "1w": "This Week", "1m": "This Month", "6m": "6 Months",
}
HORIZON_ORDER = ["1d", "1w", "1m", "6m"]

# The deepest horizon needs 126 sessions plus a bar to measure from. Anything shallower
# than this simply reports None for the horizons it cannot cover — never a guess.
MIN_BARS_FOR = {"1d": 2, "1w": 6, "1m": 22, "6m": 127}

BARS_CACHE_TTL = 900.0  # 15 min; the daily bar set only changes once a day anyway

_bars_cache: dict[str, tuple[float, dict[str, list[Bar]]]] = {}


def ist_date(ts: datetime) -> date:
    """The trading date a bar belongs to, read in IST. See the module docstring."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(IST).date()


async def load_daily_bars(symbols: list[str], lookback: int = 400,
                          fresh: bool = False) -> dict[str, list[Bar]]:
    """Daily bars per symbol, oldest first, capped at `lookback` sessions each.

    One query for the whole universe rather than 500 queries — on an Atlas M0 the
    per-query latency dominates completely, and a per-symbol loop here was what made the
    first draft of this take minutes instead of seconds.
    """
    # Key on the CONTENT of the symbol list, not its length. Two different universes of
    # the same size would otherwise share a cache entry and serve each other's bars.
    key = f"{hashlib.sha1(','.join(sorted(symbols)).encode()).hexdigest()}:{lookback}"
    now = time.monotonic()
    if not fresh:
        hit = _bars_cache.get(key)
        if hit and now - hit[0] < BARS_CACHE_TTL:
            return hit[1]

    out: dict[str, list[Bar]] = {}
    cursor = bars_collection.find(
        {"timeframe": "1d", "symbol": {"$in": symbols}},
        {"_id": 0, "symbol": 1, "ts": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
    ).sort("ts", 1)
    async for b in cursor:
        try:
            out.setdefault(b["symbol"], []).append(Bar(
                b["ts"], float(b["open"]), float(b["high"]),
                float(b["low"]), float(b["close"]), float(b.get("volume") or 0.0),
            ))
        except (TypeError, ValueError, KeyError):
            # One malformed bar must cost one bar, never the symbol and never the scan.
            continue

    # Trim to the lookback and drop any duplicate trading date (a re-backfill can leave
    # two rows for one session if the stored ts ever drifted).
    for sym, bars in out.items():
        seen: dict[date, Bar] = {}
        for bar in bars:
            seen[ist_date(bar.ts)] = bar
        merged = [seen[d] for d in sorted(seen)]
        out[sym] = merged[-lookback:]

    _bars_cache[key] = (now, out)
    return out


def to_weekly(bars: list[Bar]) -> list[Bar]:
    """Resample daily bars into ISO-week buckets. Open = first, high = max, low = min,
    close = last, volume = sum. Stamped with the week's LAST session."""
    if not bars:
        return []
    buckets: dict[tuple[int, int], list[Bar]] = {}
    for b in bars:
        d = ist_date(b.ts)
        iso = d.isocalendar()
        buckets.setdefault((iso[0], iso[1]), []).append(b)

    weekly: list[Bar] = []
    for key in sorted(buckets):
        group = buckets[key]
        weekly.append(Bar(
            group[-1].ts,
            group[0].open,
            max(x.high for x in group),
            min(x.low for x in group),
            group[-1].close,
            sum(x.volume for x in group),
        ))
    return weekly


def pct_return(closes: list[float], sessions: int) -> float | None:
    """% change over `sessions` trading sessions, or None if the history is too short."""
    if len(closes) < sessions + 1:
        return None
    then = closes[-1 - sessions]
    if then <= 0:
        return None
    return (closes[-1] / then - 1) * 100


def all_horizon_returns(closes: list[float]) -> dict[str, float | None]:
    return {h: pct_return(closes, n) for h, n in HORIZONS.items()}


def consistency(closes: list[float], sessions: int) -> float | None:
    """Share of the window's sessions that closed up.

    This is what separates a stock that ground out +30% over six months from one that
    gapped +30% in a day and went sideways. Both show the same return; only one of them
    is a trend, and a board that ranks them identically is misleading by construction.
    """
    if len(closes) < sessions + 1:
        return None
    window = closes[-1 - sessions:]
    ups = sum(1 for a, b in zip(window, window[1:]) if b > a)
    return ups / (len(window) - 1) * 100


def up_streak(closes: list[float]) -> int:
    """Consecutive sessions closed higher, counting back from the last bar."""
    n = 0
    for a, b in zip(reversed(closes[:-1]), reversed(closes[1:])):
        if b > a:
            n += 1
        else:
            break
    return n


def relative_strength(stock_ret: float | None, bench_ret: float | None) -> float | None:
    """Simple return spread in percentage points. Deliberately not a ratio: a ratio
    explodes when the benchmark return is near zero, which for a 1-day horizon is most
    days."""
    if stock_ret is None or bench_ret is None:
        return None
    return stock_ret - bench_ret


def percentile_rank(value: float | None, population: list[float]) -> float | None:
    """Where `value` sits in `population`, 0-100. Ties resolve to the midpoint."""
    if value is None or not population:
        return None
    below = sum(1 for v in population if v < value)
    equal = sum(1 for v in population if v == value)
    return (below + equal / 2) / len(population) * 100


def donchian_break(bars: list[Bar], window: int) -> date | None:
    """The trading date the last close broke above its own `window`-session high, or None.

    The high is measured over the bars BEFORE the breakout bar — including the breakout
    bar's own high in its own resistance level means nothing ever breaks out.
    """
    if len(bars) < window + 1:
        return None
    prior_high = max(b.high for b in bars[-1 - window:-1])
    if bars[-1].close > prior_high:
        return ist_date(bars[-1].ts)
    return None


def sma(vals: list[float], n: int) -> float | None:
    return sum(vals[-n:]) / n if len(vals) >= n else None


def ema_last(vals: list[float], n: int) -> float | None:
    """EMA at the final bar, seeded with the first n-value SMA."""
    if len(vals) < n:
        return None
    k = 2 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def days_above_ema(closes: list[float], n: int = 9, window: int = 21) -> float | None:
    """Share of the last `window` sessions that closed above the n-period EMA.

    Deliberately a SHARE and not an unbroken streak. Measured across the live Nifty 500,
    the median stock's unbroken 9-EMA streak is 2 sessions and only a handful ever reach
    21 — the 9 EMA is fast enough that even a textbook uptrend clips it every week or two.
    Gating on an unbroken month empties the screen permanently; Bullish Stocks learned this
    the hard way on its first deploy.
    """
    if len(closes) < n + window:
        return None
    k = 2 / (n + 1)
    e = sum(closes[:n]) / n
    series: list[float] = []
    for v in closes[n:]:
        e = v * k + e * (1 - k)
        series.append(e)
    pairs = list(zip(closes[n:], series))[-window:]
    if not pairs:
        return None
    return sum(1 for c, ev in pairs if c > ev) / len(pairs) * 100


def volume_ratio(bars: list[Bar], window: int = 20) -> float | None:
    """Last session's volume against its own trailing average. The average EXCLUDES the
    last bar, so a huge day does not dilute the very baseline it is being judged against."""
    if len(bars) < window + 1:
        return None
    prior = [b.volume for b in bars[-1 - window:-1] if b.volume > 0]
    if not prior:
        return None
    avg = sum(prior) / len(prior)
    return bars[-1].volume / avg if avg > 0 else None


def turnover(bars: list[Bar], sessions: int = 1) -> float | None:
    """Rupee turnover over the last `sessions` bars (close x volume)."""
    if not bars:
        return None
    window = bars[-sessions:]
    return sum(b.close * b.volume for b in window)


def high_low_context(bars: list[Bar], window: int = 252) -> dict[str, float | None]:
    """Distance from the rolling high and low of `window` sessions, as percentages."""
    if len(bars) < 2:
        return {"high": None, "low": None, "pct_from_high": None, "pct_from_low": None}
    win = bars[-window:]
    hi = max(b.high for b in win)
    lo = min(b.low for b in win)
    last = bars[-1].close
    return {
        "high": hi,
        "low": lo,
        "pct_from_high": (last / hi - 1) * 100 if hi > 0 else None,
        "pct_from_low": (last / lo - 1) * 100 if lo > 0 else None,
    }


def atr(bars: list[Bar], n: int = 14) -> float | None:
    """Wilder's ATR at the final bar. The volatility unit every stop here is sized in —
    a fixed percentage stop is either too tight on a volatile name or too loose on a
    quiet one, and the same number cannot be both."""
    if len(bars) < n + 1:
        return None
    trs: list[float] = []
    for prev, cur in zip(bars, bars[1:]):
        trs.append(max(cur.high - cur.low,
                       abs(cur.high - prev.close),
                       abs(cur.low - prev.close)))
    if len(trs) < n:
        return None
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def last_swing_low(bars: list[Bar], left: int = 3, right: int = 3) -> float | None:
    """The most recent CONFIRMED swing low — a bar whose low is the lowest within `left`
    bars before and `right` after it.

    The right-hand lookahead is what makes it confirmed, and it means the last `right`
    bars can never qualify. That is correct: a low is only a swing low once price has
    turned away from it, and treating the newest bar as one is how a stop gets placed
    under a level that is still falling.
    """
    n = len(bars)
    for i in range(n - right - 1, left - 1, -1):
        low = bars[i].low
        if all(bars[j].low >= low for j in range(i - left, i)) and \
           all(bars[j].low >= low for j in range(i + 1, i + right + 1)):
            return low
    return None


def donchian_high(bars: list[Bar], window: int) -> float | None:
    """Highest high over the `window` sessions BEFORE the last bar."""
    if len(bars) < window + 1:
        return None
    return max(b.high for b in bars[-1 - window:-1])


def donchian_low(bars: list[Bar], window: int) -> float | None:
    if len(bars) < window + 1:
        return None
    return min(b.low for b in bars[-1 - window:-1])


def coverage(bars_by_symbol: dict[str, list[Bar]], horizon: str) -> dict:
    """How much of the universe can actually answer this horizon. Surfaced in the UI so a
    thin backfill reads as 'not enough history' rather than 'nothing is trending'."""
    need = MIN_BARS_FOR.get(horizon, 2)
    total = len(bars_by_symbol)
    have = sum(1 for b in bars_by_symbol.values() if len(b) >= need)
    return {
        "symbols": total,
        "with_history": have,
        "pct": round(have / total * 100, 1) if total else 0.0,
        "sessions_needed": need,
    }
