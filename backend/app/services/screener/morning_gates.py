"""Paper order admission after ranking and strategy confirmation. No broker calls."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class EntryEvidence:
    symbol: str
    side: str
    signal_time: datetime
    quote_time: datetime
    entry: float
    stop: float
    target: float
    quantity: int
    estimated_cost: float  # round trip, in rupees for the full quantity
    required_margin: float
    available_margin: float


def entry_rejections(e: EntryEvidence, now: datetime, *, trading_session: bool,
                     opening_minutes: int, complete_data: bool, eligible: bool,
                     paper_enabled: bool, approved: bool, confirmed: bool,
                     liquidity_ok: bool, limits_ok: bool, duplicate: bool,
                     quote_max_age_seconds: int = 5) -> list[str]:
    """Collect all failures for the signal ledger. Entry checks never gate exits."""
    reasons = [label for passed, label in (
        (trading_session, "exchange_closed"), (complete_data, "incomplete_data"),
        (eligible, "instrument_or_side_ineligible"), (paper_enabled, "paper_paused"),
        (approved, "strategy_unapproved"), (confirmed, "trigger_unconfirmed"),
        (liquidity_ok, "insufficient_liquidity"), (limits_ok, "account_risk_limit"),
        (not duplicate, "duplicate_signal"),
    ) if not passed]
    if any(t.utcoffset() is None for t in (now, e.signal_time, e.quote_time)):
        return reasons + ["missing_timezone"]
    local = now.astimezone(IST)
    signal = e.signal_time.astimezone(IST)
    earliest = local.replace(hour=9, minute=15, second=0, microsecond=0) + timedelta(minutes=opening_minutes)
    if opening_minutes not in (15, 30) or not earliest <= signal <= local or local.hour * 60 + local.minute >= 870:
        reasons.append("outside_entry_window")
    if not 0 <= (now - e.quote_time).total_seconds() <= quote_max_age_seconds:
        reasons.append("stale_quote")
    if not all(isfinite(x) for x in (e.entry, e.stop, e.target, e.estimated_cost,
                                     e.required_margin, e.available_margin)):
        return reasons + ["invalid_numeric_data"]
    if e.quantity <= 0 or min(e.entry, e.stop, e.target, e.required_margin) <= 0 or e.estimated_cost < 0:
        return reasons + ["invalid_order"]
    if not ((e.side == "LONG" and e.stop < e.entry < e.target)
            or (e.side == "SHORT" and e.target < e.entry < e.stop)):
        reasons.append("invalid_direction_or_levels")
    if abs(e.target - e.entry) * e.quantity <= e.estimated_cost:
        reasons.append("target_below_cost")
    if e.required_margin > e.available_margin:
        reasons.append("insufficient_margin")
    return reasons
