"""Multi-leg option payoff calculator: P&L-at-expiry diagram, breakeven(s), max
profit/loss (bounded or unbounded), and net Greeks for a combined position (a single
leg is just a 1-leg case) — powers the payoff builder for strategies like Iron Condor,
Bull Put Spread, or ad-hoc multi-leg construction."""

from pydantic import BaseModel, Field

from options_service.greeks import black_scholes_greeks


class Leg(BaseModel):
    option_type: str = Field(description="CE or PE")
    strike: float
    premium: float = Field(description="premium paid (buy) or received (sell), per unit")
    quantity: int = Field(gt=0, description="lots x lot_size, i.e. total units")
    direction: str = Field(description="BUY or SELL")


def leg_payoff_at_expiry(leg: Leg, spot_at_expiry: float) -> float:
    intrinsic = max(spot_at_expiry - leg.strike, 0) if leg.option_type.upper() == "CE" else max(leg.strike - spot_at_expiry, 0)
    per_unit_pnl = (intrinsic - leg.premium) if leg.direction.upper() == "BUY" else (leg.premium - intrinsic)
    return per_unit_pnl * leg.quantity


def combined_payoff(legs: list[Leg], spot_at_expiry: float) -> float:
    return sum(leg_payoff_at_expiry(leg, spot_at_expiry) for leg in legs)


def payoff_diagram(legs: list[Leg], spot_range_pct: float = 0.15, points: int = 100) -> list[dict]:
    """Spot swept +/- `spot_range_pct` around the current underlying-implied center
    (the average strike, as a reasonable anchor with no live spot passed in)."""
    if not legs:
        return []
    center = sum(leg.strike for leg in legs) / len(legs)
    lo, hi = center * (1 - spot_range_pct), center * (1 + spot_range_pct)
    step = (hi - lo) / (points - 1)
    return [
        {"spot": round(lo + i * step, 2), "pnl": round(combined_payoff(legs, lo + i * step), 2)}
        for i in range(points)
    ]


def breakevens(legs: list[Leg], spot_range_pct: float = 0.3, resolution: int = 2000) -> list[float]:
    """Root-finds sign changes in the payoff curve over a wide sweep — works for any
    number of legs (unlike a closed-form breakeven, which only exists for simple
    spreads)."""
    if not legs:
        return []
    center = sum(leg.strike for leg in legs) / len(legs)
    lo, hi = center * (1 - spot_range_pct), center * (1 + spot_range_pct)
    step = (hi - lo) / resolution
    points = [(lo + i * step, combined_payoff(legs, lo + i * step)) for i in range(resolution + 1)]
    roots = []
    for (s1, p1), (s2, p2) in zip(points, points[1:]):
        if p1 == 0:
            roots.append(round(s1, 2))
        elif p1 * p2 < 0:
            roots.append(round(s1 + (s2 - s1) * (-p1) / (p2 - p1), 2))
    return roots


def max_profit_loss(legs: list[Leg], spot_range_pct: float = 0.5) -> dict:
    """Bounded strategies get an exact number; unbounded ones (naked long/short a
    single leg whose payoff keeps climbing) are reported as `None` with `unbounded`
    flagged, never a truncated number pretending to be the true max."""
    if not legs:
        return {"max_profit": None, "max_loss": None, "profit_unbounded": False, "loss_unbounded": False}
    diagram = payoff_diagram(legs, spot_range_pct, points=500)
    pnls = [p["pnl"] for p in diagram]
    max_p, min_p = max(pnls), min(pnls)

    net_calls = sum((1 if leg.direction.upper() == "BUY" else -1) * leg.quantity for leg in legs if leg.option_type.upper() == "CE")
    profit_unbounded = net_calls > 0  # net long calls -> profit climbs without bound as spot -> infinity
    naked_short_put = any(
        leg.option_type.upper() == "PE" and leg.direction.upper() == "SELL" for leg in legs
    ) and not any(leg.option_type.upper() == "PE" and leg.direction.upper() == "BUY" for leg in legs)
    naked_short_call = any(
        leg.option_type.upper() == "CE" and leg.direction.upper() == "SELL" for leg in legs
    ) and not any(leg.option_type.upper() == "CE" and leg.direction.upper() == "BUY" for leg in legs)
    loss_unbounded = naked_short_put or naked_short_call

    return {
        "max_profit": None if profit_unbounded else round(max_p, 2),
        "max_loss": None if loss_unbounded else round(min_p, 2),
        "profit_unbounded": profit_unbounded,
        "loss_unbounded": bool(loss_unbounded),
    }


def net_greeks(
    legs: list[Leg], spot: float, t_years: float, rate: float = 0.065, sigma_by_strike: dict[float, float] | None = None,
) -> dict:
    """Aggregate delta/gamma/theta/vega/rho across all legs at CURRENT spot (not
    expiry) — needs a volatility per leg; falls back to a flat 15% if none given."""
    sigma_by_strike = sigma_by_strike or {}
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    for leg in legs:
        sigma = sigma_by_strike.get(leg.strike, 0.15)
        g = black_scholes_greeks(spot, leg.strike, t_years, leg.option_type, rate, sigma=sigma)
        sign = 1 if leg.direction.upper() == "BUY" else -1
        for key in totals:
            totals[key] += sign * g[key] * leg.quantity
    return {k: round(v, 4) for k, v in totals.items()}
