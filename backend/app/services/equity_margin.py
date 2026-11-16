"""Intraday (MIS) margin for the Intraday Stocks paper accounts (2026-11-16).

The owner asked for the module's paper accounts to trade with the 5x leverage an Indian broker gives
on intraday equity. An account keeps its own capital; its buying power is 5 x that capital; each
position blocks MARGIN of 20% of its value, and the margin of everything open together can never be
more than the account has.

WHAT IS ELIGIBLE. Only an INTRADAY (MIS) trade in an NSE/BSE cash-equity stock - one that is
squared off in the same session. A position an account may carry overnight is a delivery (CNC)
trade and pays its full value, as it would at a broker. Anything that is not cash equity (F&O,
commodities, currency) keeps its own margin rules and is never sized here.

WHY A FLAT 5x. Under SEBI's peak-margin rules a stock's intraday margin is its VaR + ELM, and never
less than 20%, so 5x is the MOST a broker may give. Volatile or less liquid names need more margin,
and a broker gives them 1x-4x. The tournament trades the 200 most-traded NSE stocks, most of which
sit at the 20% floor. A flat 5x is the owner's choice, and it overstates the leverage on the few
names that need more.

P&L IS NOT MULTIPLIED. Leverage changes how many shares a position may hold, and nothing else. Gross
P&L is still (exit - entry) x the shares actually held, and the costs are Angel's rate card on those
shares. A loss is a loss on the account's own money: the 3% daily breaker stays a share of the
account's CAPITAL, not of its buying power, so it trips five times sooner on the same price move.
"""

from __future__ import annotations

import os

MIS_LEVERAGE = max(float(os.getenv("INTRADAY_EQUITY_LEVERAGE", "5")), 1.0)
CASH_EQUITY_SEGMENTS = frozenset({"NSE_EQ", "BSE_EQ", "NSE", "BSE"})
# The Patterns desk's styles that are squared off the same session (intraday_session's close-out
# job checks exactly these). Its "swing" style (4h and 1d) may hold for days.
INTRADAY_STYLES = frozenset({"intraday", "scalping"})


def intraday_leverage(segment: str | None = None, *, intraday: bool, limit: float | None = None) -> float:
    """The leverage one entry may use: MIS_LEVERAGE for a same-session cash-equity trade, else 1.0.

    `segment` is the instrument's exchange segment when the caller knows it; None means the caller
    only trades cash equity (the tournament, the Patterns desk). `limit` caps it (a book's own)."""
    if not intraday:
        return 1.0
    if segment is not None and str(segment).upper() not in CASH_EQUITY_SEGMENTS:
        return 1.0
    lev = MIS_LEVERAGE if limit is None else min(MIS_LEVERAGE, max(float(limit), 1.0))
    return max(lev, 1.0)


def margin_for(value: float, leverage: float) -> float:
    """Margin a position of this VALUE blocks at this leverage (value itself at 1x)."""
    lev = max(float(leverage or 1.0), 1.0)
    return round(value, 2) if lev == 1.0 else round(value / lev, 2)
