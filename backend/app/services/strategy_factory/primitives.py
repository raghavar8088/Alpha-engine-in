"""Shared primitives for the Strategy Factory: regime classification, level building,
position sizing and transaction costs.

RISK/REWARD IS PER STRATEGY, NOT A HOUSE RULE
----------------------------------------------
There is deliberately no universal minimum R:R here. A 1-minute pin-bar fade and a daily
head-and-shoulders are different trades with different realistic reward profiles, and
forcing both to one multiple would either reject every scalp or invent unreachable
targets for them. Each recipe declares `target_r`, or supplies a measured move projected
from the pattern itself, and the engine records the REALISED R on every close so the
leaderboard ranks on average R rather than on an assumption.

What IS enforced is that levels must be sane: a stop on the correct side of entry, not
tighter than a volatility floor (an ATR fraction — otherwise ordinary noise stops you out
and the advertised R:R is fiction) and not absurdly wide, with the target on the correct
side. Degenerate geometry is rejected rather than traded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone

from strategy_service.indicators import adx, atr as atr_series, ema, sma, stdev

IST = timezone(timedelta(hours=5, minutes=30))

# A stop closer than this many ATRs is noise, not a level.
MIN_STOP_ATR = float(os.getenv("SF_MIN_STOP_ATR", "0.35"))
# ...and one wider than this is not a stop, it is a hope.
MAX_STOP_ATR = float(os.getenv("SF_MAX_STOP_ATR", "6.0"))

DEFAULT_CAPITAL = float(os.getenv("SF_PER_STRATEGY_CAPITAL", "1000000"))   # Rs 10,00,000
DEFAULT_RISK_PCT = float(os.getenv("SF_RISK_PCT", "0.01"))                 # 1% per trade
DEFAULT_MAX_NOTIONAL_PCT = float(os.getenv("SF_MAX_NOTIONAL_PCT", "1.0"))  # no leverage

REGIMES = (
    "strong_bull", "weak_bull", "strong_bear", "weak_bear", "sideways",
    "high_volatility", "low_volatility", "breakout", "mean_reversion",
)


@dataclass
class RegimeState:
    """Regimes are TAGS, not one label.

    A market can be in a strong bull trend AND high volatility AND a breakout expansion
    simultaneously. Collapsing that to a single enum would force a strategy that
    legitimately wants "trending, any volatility" to pick one and miss the other.
    `primary` exists only for display."""

    primary: str
    tags: set[str] = field(default_factory=set)
    adx: float | None = None
    atr_pct: float | None = None
    trend_slope: float | None = None
    bb_width_pct: float | None = None

    def allows(self, wanted: set[str] | None) -> bool:
        """Trades when ANY declared regime is currently present. Empty means agnostic."""
        return not wanted or bool(self.tags & set(wanted))


def classify_regime(bars, fast: int = 20, slow: int = 50, adx_period: int = 14) -> RegimeState:
    """Tag the market state from price alone, so this works identically on an MCX future
    and an equity without needing an external index."""
    if len(bars) < max(slow, adx_period) + 5:
        return RegimeState(primary="unknown")

    closes = [b.close for b in bars]
    f, s = ema(closes, fast), ema(closes, slow)
    a_series = atr_series(bars, adx_period)
    adx_series, _p, _m = adx(bars, adx_period)
    atr_now = a_series[-1] if a_series else 0.0
    adx_now = adx_series[-1] if adx_series else 0.0
    price = closes[-1]
    atr_pct = (atr_now / price * 100) if price else 0.0

    slope = 0.0
    if len(f) >= 10 and f[-10]:
        slope = (f[-1] - f[-10]) / abs(f[-10]) * 100

    mid, sd = sma(closes, 20), stdev(closes, 20)
    bb_width_pct = None
    widths: list[float] = []
    if mid and sd:
        n = min(len(mid), len(sd))
        widths = [(4 * sd[-n + i]) / mid[-n + i] * 100 for i in range(n) if mid[-n + i]]
        if widths:
            bb_width_pct = widths[-1]

    tags: set[str] = set()
    up = bool(f and s and f[-1] > s[-1])
    down = bool(f and s and f[-1] < s[-1])
    trending = adx_now >= 25
    choppy = adx_now < 20

    if up and trending:
        tags.add("strong_bull")
    elif up:
        tags.add("weak_bull")
    if down and trending:
        tags.add("strong_bear")
    elif down:
        tags.add("weak_bear")
    if choppy:
        tags.add("sideways")
        tags.add("mean_reversion")

    # Volatility measured against this instrument's OWN recent ATR, so a quiet metal and
    # a violent energy contract are each judged on their own scale.
    if len(a_series) >= 40 and price:
        hist = sorted(a_series[-60:])
        if atr_now >= hist[int(len(hist) * 0.75)]:
            tags.add("high_volatility")
        elif atr_now <= hist[int(len(hist) * 0.25)]:
            tags.add("low_volatility")

    if len(widths) >= 30 and bb_width_pct is not None:
        recent_min = min(widths[-30:-1])
        if recent_min > 0 and bb_width_pct >= recent_min * 1.3:
            tags.add("breakout")

    primary = (
        "strong_bull" if "strong_bull" in tags else
        "strong_bear" if "strong_bear" in tags else
        "weak_bull" if "weak_bull" in tags else
        "weak_bear" if "weak_bear" in tags else
        "sideways" if "sideways" in tags else "unknown"
    )
    return RegimeState(primary=primary, tags=tags, adx=round(adx_now, 2),
                       atr_pct=round(atr_pct, 3), trend_slope=round(slope, 3),
                       bb_width_pct=round(bb_width_pct, 3) if bb_width_pct is not None else None)


@dataclass
class Levels:
    entry: float
    stop: float
    target: float
    risk: float
    reward: float
    r_multiple: float
    stop_basis: str      # structural | atr_floor | atr_cap
    target_basis: str    # measured_move | r_multiple


def build_levels(side: str, entry: float, atr: float, target_r: float,
                 structural_stop: float | None = None,
                 measured_target: float | None = None) -> Levels | None:
    """Turn a raw signal into tradable levels, or None if the geometry is degenerate.

    Structure decides WHERE the stop goes (pattern invalidation, swing point); volatility
    decides whether that distance is believable, clamping it into
    [MIN_STOP_ATR, MAX_STOP_ATR] ATRs. The target is the pattern's own measured move when
    it has one, else `target_r` times the resulting risk."""
    if entry <= 0 or atr <= 0 or target_r <= 0:
        return None
    long = side == "BUY"

    floor_dist, cap_dist = MIN_STOP_ATR * atr, MAX_STOP_ATR * atr
    basis = "structural"
    if structural_stop is None:
        dist, basis = floor_dist, "atr_floor"
    else:
        dist = (entry - structural_stop) if long else (structural_stop - entry)
        if dist <= 0:
            return None                      # stop on the wrong side of entry
        if dist < floor_dist:
            dist, basis = floor_dist, "atr_floor"
        elif dist > cap_dist:
            dist, basis = cap_dist, "atr_cap"

    stop = entry - dist if long else entry + dist
    if stop <= 0:
        return None

    if measured_target is not None:
        reward = (measured_target - entry) if long else (entry - measured_target)
        target, tbasis = measured_target, "measured_move"
        if reward <= 0:                      # projection points the wrong way
            reward = target_r * dist
            target = entry + reward if long else entry - reward
            tbasis = "r_multiple"
    else:
        reward = target_r * dist
        target = entry + reward if long else entry - reward
        tbasis = "r_multiple"

    if target <= 0:
        return None
    if long and not (stop < entry < target):
        return None
    if not long and not (target < entry < stop):
        return None

    return Levels(entry=entry, stop=stop, target=target, risk=dist, reward=reward,
                  r_multiple=round(reward / dist, 3), stop_basis=basis, target_basis=tbasis)


def position_size(capital: float, available_cash: float, levels: Levels,
                  risk_pct: float = DEFAULT_RISK_PCT,
                  max_notional_pct: float = DEFAULT_MAX_NOTIONAL_PCT,
                  lot_size: int = 1) -> int:
    """Whole lots sized so a stop-out costs `risk_pct` of the account.

    Risk-based first (quantity = risk budget / stop distance), then capped by the cash the
    strategy actually holds. Both caps matter: risk sizing alone can demand more notional
    than the account has when the stop is tight, and notional sizing alone silently varies
    the risk per trade with volatility."""
    if levels.risk <= 0 or levels.entry <= 0 or lot_size < 1:
        return 0
    by_risk = (capital * risk_pct) / levels.risk
    by_cash = min(available_cash, capital * max_notional_pct) / levels.entry
    units = int(min(by_risk, by_cash))
    return (units // lot_size) * lot_size


GST = 0.18
SEBI_PCT = 0.000001


def equity_intraday_charges(price: float, qty: float, is_buy: bool) -> float:
    """NSE cash intraday (MIS): no STT on the buy, 0.025% on the sell."""
    t = price * qty
    if t <= 0:
        return 0.0
    brokerage = min(20.0, t * 0.0003)
    stt = 0.0 if is_buy else t * 0.00025
    exch = t * 0.0000297
    stamp = t * 0.00003 if is_buy else 0.0
    return brokerage + stt + exch + t * SEBI_PCT + stamp + GST * (brokerage + exch + t * SEBI_PCT)


def equity_delivery_charges(price: float, qty: float, is_buy: bool) -> float:
    """NSE cash delivery: STT 0.1% BOTH sides — roughly 4x the intraday drag."""
    t = price * qty
    if t <= 0:
        return 0.0
    stt = t * 0.001
    exch = t * 0.0000297
    stamp = t * 0.00015 if is_buy else 0.0
    return stt + exch + t * SEBI_PCT + stamp + GST * (exch + t * SEBI_PCT)


def commodity_charges(price: float, qty: float, is_buy: bool) -> float:
    """MCX non-agri futures: CTT (0.01%, sell side) rather than STT."""
    t = price * qty
    if t <= 0:
        return 0.0
    brokerage = min(20.0, t * 0.0003)
    ctt = 0.0 if is_buy else t * 0.0001
    exch = t * 0.000026
    stamp = t * 0.00002 if is_buy else 0.0
    return brokerage + ctt + exch + t * SEBI_PCT + stamp + GST * (brokerage + exch + t * SEBI_PCT)


COST_MODELS = {
    "equity_intraday": equity_intraday_charges,
    "equity_delivery": equity_delivery_charges,
    "commodity": commodity_charges,
}


def round_trip_cost(model: str, entry: float, exit_px: float, qty: float, is_long: bool) -> float:
    fn = COST_MODELS.get(model, commodity_charges)
    return fn(entry, qty, is_long) + fn(exit_px, qty, not is_long)


def slippage_price(price: float, bps: float, adverse_for_buy: bool) -> float:
    """Fills are always worse than the signal: buys pay up, sells receive less."""
    delta = price * bps / 10000.0
    return price + delta if adverse_for_buy else price - delta
