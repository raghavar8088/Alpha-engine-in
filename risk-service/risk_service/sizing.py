"""Position sizing methods (roadmap Phase 4). Every function returns a share/contract
quantity, already rounded down to a lot-size multiple — callers never round themselves.
All are pure functions: no state, no I/O, trivially unit-testable."""

import math


def to_lot_multiple(raw_quantity: float, lot_size: int) -> int:
    if raw_quantity <= 0 or lot_size <= 0:
        return 0
    lots = math.floor(raw_quantity / lot_size)
    return lots * lot_size


def fixed_capital_pct_quantity(equity: float, pct: float, price: float, lot_size: int = 1) -> int:
    """Deploy `pct`% of equity notional at `price`. This is the pre-Phase-4 default
    behavior (BacktestEngine's old `_size`), kept as its own named method so existing
    validated results stay reproducible when `sizing_method="capital_pct"`."""
    if price <= 0:
        return 0
    budget = equity * pct / 100.0
    return to_lot_multiple(budget / price, lot_size)


def fixed_fractional_quantity(
    equity: float, risk_pct: float, entry_price: float, stop_price: float, lot_size: int = 1
) -> int:
    """Risk `risk_pct`% of equity on this trade, sized off the actual stop distance —
    the standard "1% risk" rule. Falls back to 0 (skip) if there's no usable stop."""
    per_share_risk = abs(entry_price - stop_price)
    if per_share_risk <= 0:
        return 0
    risk_budget = equity * risk_pct / 100.0
    return to_lot_multiple(risk_budget / per_share_risk, lot_size)


def atr_quantity(
    equity: float, risk_pct: float, entry_price: float, atr: float, atr_mult: float = 2.0, lot_size: int = 1
) -> int:
    """Same risk-budget idea as fixed-fractional, but the stop distance is `atr_mult`
    ATRs instead of an explicit signal stop — useful for strategies that don't set one."""
    if atr <= 0:
        return 0
    return fixed_fractional_quantity(equity, risk_pct, entry_price, entry_price - atr_mult * atr, lot_size)


def volatility_target_quantity(
    equity: float, target_daily_vol_pct: float, price: float, price_stdev_pct: float, lot_size: int = 1
) -> int:
    """Size so the position's expected contribution to daily P&L volatility is
    `target_daily_vol_pct`% of equity, given the instrument's own daily-return stdev
    (`price_stdev_pct`, e.g. from indicators.stdev on returns). Inversely proportional
    to volatility: calmer instruments get bigger size, wilder ones get smaller."""
    if price_stdev_pct <= 0 or price <= 0:
        return 0
    notional = equity * target_daily_vol_pct / price_stdev_pct
    return to_lot_multiple(notional / price, lot_size)


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float, cap: float = 0.25) -> float:
    """Kelly criterion f* = W - (1-W)/R where R = avg_win/avg_loss. Capped at `cap`
    (default quarter-Kelly — full Kelly is notoriously over-aggressive for real
    capital) and floored at 0 (never a negative/short-the-edge position)."""
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0
    r = avg_win / avg_loss
    f = win_rate - (1 - win_rate) / r
    return max(0.0, min(f, cap))


def kelly_quantity(
    equity: float, win_rate: float, avg_win: float, avg_loss: float, price: float,
    lot_size: int = 1, cap: float = 0.25,
) -> int:
    f = kelly_fraction(win_rate, avg_win, avg_loss, cap)
    if f <= 0 or price <= 0:
        return 0
    return to_lot_multiple(equity * f / price, lot_size)
