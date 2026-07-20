"""Margin estimator for SHORT option structures — the thing that actually gets blocked
when you sell premium, and the reason a selling desk cannot be sized the way the buying
lab is sized.

Buying an option costs premium and nothing else, so the buying lab sizes by premium and
is done. Selling blocks margin: SPAN (the exchange's scan-risk number) plus exposure
margin, and the premium you collect is *credited*, not blocked. A desk that sized short
positions by "credit collected" would think a 1-lot short strangle costs it Rs ~20k when
the exchange has actually locked up Rs ~3.7 lakh — off by ~18x, which would let the desk
oversell its paper capital by the same factor.

WHAT THIS IS AND IS NOT
-----------------------
This is a documented approximation, not an NSE SPAN replica. Real SPAN runs a 16-scenario
risk array over price and volatility shifts, applies inter-month and inter-commodity
spread charges, and changes daily. Reproducing it needs NSE's published risk parameter
files, which this app does not ingest. Instead:

  * NAKED short legs are charged `SPAN_PCT * otm_factor + EXPOSURE_PCT` of notional.
    Calibration: NIFTY near-ATM shorts run ~10% of contract value all-in on Indian
    brokers' margin calculators (SPAN ~8% + exposure 2%). Far-OTM shorts sit inside
    SPAN's scan range and get charged materially less, which `otm_factor` models as a
    linear decay to a floor — a floor, not zero, because a short option is never
    risk-free no matter how far out it is struck.

  * DEFINED-RISK structures (every short leg covered by a long of the same option type)
    are charged their true worst-case loss at expiry. This mirrors the large SPAN
    benefit NSE grants hedged positions, and it is exact rather than approximate: a
    100-point-wide bull put spread genuinely cannot lose more than 100 points x lot.

The approximation is deliberately biased toward OVER-stating margin (the naked floor,
the ATM-anchored percentages) because the failure mode that matters on a selling desk is
under-reserving capital, not over-reserving it.

`estimate_margin` returns the basis it used so callers can report it honestly instead of
presenting a modelled number as an exchange figure.
"""

from options_service.payoff import Leg as PayoffLeg
from options_service.payoff import combined_payoff

# Calibrated against Indian brokers' published margin calculators for NIFTY index
# options (near-ATM short, weekly/monthly expiry). Config, not physics — if NSE
# revises the exposure margin or a broker's SPAN feed says otherwise, edit here.
SPAN_PCT = 0.08
EXPOSURE_PCT = 0.02

# SPAN's scan range for an index is roughly a +/-3.3-sigma move; beyond it a short
# option's scan risk stops growing. 6% of spot is the practical width for NIFTY.
SCAN_RANGE_PCT = 0.06
# A far-OTM short still carries gap risk, so its SPAN component never decays past this
# fraction of the ATM charge. This is the single most conservative choice in the model.
MIN_OTM_FACTOR = 0.45

# Hedged structures still attract a small exchange charge beyond pure max-loss, and a
# zero-margin position would let the sizer open unlimited spreads. Floor at 1% of the
# short legs' notional.
DEFINED_RISK_FLOOR_PCT = 0.01


def _otm_factor(spot: float, strike: float) -> float:
    """1.0 for an ATM short, decaying linearly to MIN_OTM_FACTOR at the edge of SPAN's
    scan range and flat thereafter."""
    if spot <= 0:
        return 1.0
    distance = abs(strike - spot) / spot
    if distance >= SCAN_RANGE_PCT:
        return MIN_OTM_FACTOR
    return 1.0 - (1.0 - MIN_OTM_FACTOR) * (distance / SCAN_RANGE_PCT)


def _uncovered_shorts(legs) -> list:
    """Short legs with no long leg of the same option type to cap them. A structure with
    any uncovered short has unbounded (calls) or very large (puts) tail risk and must be
    margined as naked, however many other legs it carries."""
    out = []
    for option_type in ("CE", "PE"):
        shorts = [l for l in legs if l.option_type.upper() == option_type and _is_sell(l)]
        longs = [l for l in legs if l.option_type.upper() == option_type and not _is_sell(l)]
        # One long covers one short; surplus shorts are naked.
        out.extend(shorts[len(longs):])
    return out


def _is_sell(leg) -> bool:
    """Works for both the backtest engine's Leg (TransactionType enum) and payoff.Leg
    (plain string) — every caller in this repo uses one or the other."""
    direction = getattr(leg, "direction", None)
    value = getattr(direction, "value", direction)
    return str(value).upper() == "SELL"


def estimate_margin(
    legs, spot: float, lot_size: int, quantity_lots: int, premiums: list[float],
) -> dict:
    """Margin blocked to hold `legs` as a single structure.

    `legs` are the engine's Leg objects (option_type/strike/direction); `premiums` is the
    per-unit price of each leg in the same order, used only to compute a defined-risk
    structure's true worst case (which is net of the credit taken in).

    Returns {"margin", "basis", "max_loss", "notional"} — `basis` is "defined_risk" or
    "naked_span", and `max_loss` is None when the structure's loss is unbounded.
    """
    quantity = lot_size * quantity_lots
    notional = spot * quantity

    uncovered = _uncovered_shorts(legs)
    if not uncovered:
        # Fully hedged: every short is capped by a long of its own type. Charge the real
        # worst case at expiry, which the payoff sweep gives exactly.
        payoff_legs = [
            PayoffLeg(
                option_type=leg.option_type, strike=leg.strike,
                premium=max(price, 0.0), quantity=quantity,
                direction="SELL" if _is_sell(leg) else "BUY",
            )
            for leg, price in zip(legs, premiums)
        ]
        # Sweep every strike plus a wide margin either side; a bounded structure's worst
        # point is always at or between its strikes, so this cannot miss it.
        strikes = sorted(l.strike for l in legs)
        probes = [strikes[0] * 0.5, strikes[-1] * 1.5, *strikes]
        probes += [(a + b) / 2 for a, b in zip(strikes, strikes[1:])]
        worst = min(combined_payoff(payoff_legs, s) for s in probes)
        max_loss = -worst if worst < 0 else 0.0

        short_notional = sum(spot * quantity for l in legs if _is_sell(l))
        margin = max(max_loss, short_notional * DEFINED_RISK_FLOOR_PCT)
        return {
            "margin": round(margin, 2), "basis": "defined_risk",
            "max_loss": round(max_loss, 2), "notional": round(notional, 2),
        }

    # Naked (or partially hedged): SPAN + exposure on each uncovered short leg. Covered
    # shorts contribute nothing extra — their long already caps them.
    margin = 0.0
    for leg in uncovered:
        margin += spot * quantity * (SPAN_PCT * _otm_factor(spot, leg.strike) + EXPOSURE_PCT)
    return {
        "margin": round(margin, 2), "basis": "naked_span",
        "max_loss": None, "notional": round(notional, 2),
    }
