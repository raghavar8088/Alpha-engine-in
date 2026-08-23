"""Multi-leg option strategy builder — payoff, Greeks and margin for a whole structure.

WHY A BUILDER RATHER THAN LEG-BY-LEG ORDERING. Real F&O positions are structures, and a
structure is not the sum of its legs in any of the ways that matter:

  * MARGIN. A naked short strangle blocks over a lakh; wrap it in wings and the same short
    strikes cost a fraction, because the exchange margins the worst-case portfolio loss and
    the wings cap it. Ordering leg by leg shows you the naked number first and never shows
    the hedge benefit at all.
  * RISK. A bull call spread's delta is not "long delta" — it is long delta that dies at the
    short strike. Only the NET Greeks describe what you are actually holding.
  * OUTCOME. Max profit, max loss and the breakevens are properties of the combination.
    There is no per-leg answer to "where does this stop making money".

So this prices the whole basket at once, off the same Black-Scholes engine the option chain
and the SPAN-lite margin model already use — so the builder, the chain and the margin
blocked at order time cannot disagree with each other.

WHAT IS MODELLED AND WHAT IS NOT
  * Payoff is at EXPIRY — intrinsic value at each spot. That is the honest curve to lead
    with: it is the one outcome that does not depend on a volatility assumption.
  * Greeks are at TODAY's spot and time-to-expiry, using each leg's own implied volatility
    solved from its live premium. A leg whose IV cannot be solved (a quote below intrinsic,
    which happens on illiquid strikes) is reported as unpriced rather than being given a
    default vol that would quietly poison the net figure.
  * No commissions in the payoff curve; the charge estimate is reported separately, because
    mixing them makes the breakevens wrong for anyone sizing differently.
"""

from __future__ import annotations

import logging
from datetime import date

from app.services.fno_margin import portfolio_margin, solve_iv
from options_service.greeks import black_scholes_greeks

logger = logging.getLogger("paper_broker.strategy")

PAYOFF_POINTS = 121          # odd, so the current spot lands exactly on a sample
PAYOFF_SPAN = 0.12           # +/- 12% of spot — wide enough to show both wings of a condor


# ── presets ─────────────────────────────────────────────────────────────────────
# Offsets are in STRIKE STEPS from the at-the-money strike, so one definition works on
# NIFTY's 50-point ladder and a stock's 20-point one without rewriting it.
PRESETS: list[dict] = [
    {"key": "long_call", "name": "Long Call", "outlook": "bullish",
     "why": "Cheapest way to be long with a known worst case — you can only lose the premium.",
     "legs": [{"offset": 0, "type": "CE", "side": "BUY", "lots": 1}]},
    {"key": "long_put", "name": "Long Put", "outlook": "bearish",
     "why": "Long downside with a floor under the loss.",
     "legs": [{"offset": 0, "type": "PE", "side": "BUY", "lots": 1}]},
    {"key": "bull_call_spread", "name": "Bull Call Spread", "outlook": "bullish",
     "why": "Cheaper than a naked call and margin-light, at the cost of a capped upside.",
     "legs": [{"offset": 0, "type": "CE", "side": "BUY", "lots": 1},
              {"offset": 2, "type": "CE", "side": "SELL", "lots": 1}]},
    {"key": "bear_put_spread", "name": "Bear Put Spread", "outlook": "bearish",
     "why": "The mirror of the bull call spread: defined risk, defined reward, downside.",
     "legs": [{"offset": 0, "type": "PE", "side": "BUY", "lots": 1},
              {"offset": -2, "type": "PE", "side": "SELL", "lots": 1}]},
    {"key": "long_straddle", "name": "Long Straddle", "outlook": "volatile",
     "why": "Pays for a big move either way. Needs the move to beat BOTH premiums.",
     "legs": [{"offset": 0, "type": "CE", "side": "BUY", "lots": 1},
              {"offset": 0, "type": "PE", "side": "BUY", "lots": 1}]},
    {"key": "long_strangle", "name": "Long Strangle", "outlook": "volatile",
     "why": "Cheaper than a straddle, but needs a bigger move to clear the wider gap.",
     "legs": [{"offset": 2, "type": "CE", "side": "BUY", "lots": 1},
              {"offset": -2, "type": "PE", "side": "BUY", "lots": 1}]},
    {"key": "short_straddle", "name": "Short Straddle", "outlook": "range-bound",
     "why": "Collects both premiums if nothing happens. Loss is UNBOUNDED on both sides.",
     "legs": [{"offset": 0, "type": "CE", "side": "SELL", "lots": 1},
              {"offset": 0, "type": "PE", "side": "SELL", "lots": 1}]},
    {"key": "short_strangle", "name": "Short Strangle", "outlook": "range-bound",
     "why": "Wider break-evens than a short straddle, smaller credit. Still unbounded.",
     "legs": [{"offset": 2, "type": "CE", "side": "SELL", "lots": 1},
              {"offset": -2, "type": "PE", "side": "SELL", "lots": 1}]},
    {"key": "iron_condor", "name": "Iron Condor", "outlook": "range-bound",
     "why": "A short strangle with wings — the wings cap the loss and cut the margin sharply.",
     "legs": [{"offset": 2, "type": "CE", "side": "SELL", "lots": 1},
              {"offset": 4, "type": "CE", "side": "BUY", "lots": 1},
              {"offset": -2, "type": "PE", "side": "SELL", "lots": 1},
              {"offset": -4, "type": "PE", "side": "BUY", "lots": 1}]},
    {"key": "iron_butterfly", "name": "Iron Butterfly", "outlook": "range-bound",
     "why": "A short straddle with wings. Bigger credit than a condor, narrower profit zone.",
     "legs": [{"offset": 0, "type": "CE", "side": "SELL", "lots": 1},
              {"offset": 3, "type": "CE", "side": "BUY", "lots": 1},
              {"offset": 0, "type": "PE", "side": "SELL", "lots": 1},
              {"offset": -3, "type": "PE", "side": "BUY", "lots": 1}]},
    {"key": "call_butterfly", "name": "Call Butterfly", "outlook": "range-bound",
     "why": "Cheap, pinned to one strike. Pays best if the market finishes exactly there.",
     "legs": [{"offset": -2, "type": "CE", "side": "BUY", "lots": 1},
              {"offset": 0, "type": "CE", "side": "SELL", "lots": 2},
              {"offset": 2, "type": "CE", "side": "BUY", "lots": 1}]},
    {"key": "call_ratio_spread", "name": "Call Ratio Spread", "outlook": "mildly bullish",
     "why": "Often opens for a credit, but the extra short leg leaves upside risk open.",
     "legs": [{"offset": 0, "type": "CE", "side": "BUY", "lots": 1},
              {"offset": 2, "type": "CE", "side": "SELL", "lots": 2}]},
]

PRESET_BY_KEY = {p["key"]: p for p in PRESETS}


def _years_to_expiry(expiry: str | None) -> float:
    if not expiry:
        return 1 / 365
    try:
        d = date.fromisoformat(expiry)
    except (TypeError, ValueError):
        return 1 / 365
    return max((d - date.today()).days, 0) / 365.0 or 1 / 365


def _leg_payoff(spot: float, leg: dict) -> float:
    """One leg's value at expiry — pure intrinsic, no time value left."""
    strike = float(leg["strike"])
    if str(leg.get("option_type") or "").upper() == "CE":
        intrinsic = max(spot - strike, 0.0)
    else:
        intrinsic = max(strike - spot, 0.0)
    qty = int(leg["quantity"])
    premium = float(leg["premium"])
    sign = 1 if leg["side"] == "BUY" else -1
    # A long leg paid the premium and receives the intrinsic; a short leg is the reverse.
    return sign * (intrinsic - premium) * qty


def _breakevens(points: list[dict]) -> list[float]:
    """Where the payoff curve crosses zero, found by linear interpolation between samples.

    Interpolated rather than snapped to the nearest sample: with a 121-point grid the
    nearest sample can be tens of points away from the real crossing, and a breakeven that
    is visibly wrong on the chart destroys trust in everything beside it.
    """
    out: list[float] = []
    for a, b in zip(points, points[1:]):
        if a["pnl"] == 0:
            out.append(a["spot"])
        elif (a["pnl"] < 0) != (b["pnl"] < 0):
            span = b["pnl"] - a["pnl"]
            if span:
                out.append(round(a["spot"] + (0 - a["pnl"]) / span * (b["spot"] - a["spot"]), 2))
    return sorted(set(out))


def analyse(legs: list[dict], spot: float, expiry: str | None,
            lot_size: int = 1) -> dict:
    """Payoff, Greeks, margin and outcome bounds for a whole structure.

    `legs` each carry: strike, option_type (CE/PE), side (BUY/SELL), quantity (units, not
    lots), premium. Everything else is derived.
    """
    if not legs:
        return {"ok": False, "error": "Add at least one leg"}
    if not spot or spot <= 0:
        return {"ok": False, "error": "No underlying price — cannot build a payoff"}

    t = _years_to_expiry(expiry)

    # ── payoff at expiry ────────────────────────────────────────────────────
    lo, hi = spot * (1 - PAYOFF_SPAN), spot * (1 + PAYOFF_SPAN)
    step = (hi - lo) / (PAYOFF_POINTS - 1)
    points = []
    for i in range(PAYOFF_POINTS):
        s = lo + i * step
        points.append({"spot": round(s, 2),
                       "pnl": round(sum(_leg_payoff(s, leg) for leg in legs), 2)})

    pnls = [p["pnl"] for p in points]
    max_profit, max_loss = max(pnls), min(pnls)

    # THE SCAN WINDOW IS FINITE, so an open-ended leg looks capped at the edge of it.
    # Reporting a short straddle's "max loss" as whatever it happens to be at -12% would be
    # the single most dangerous number this module could print. So the ENDS are read by
    # slope, and the two directions are reported separately because they are not the same
    # risk:
    #
    #   upside   genuinely unbounded — spot has no ceiling, so a naked short call's loss
    #            and a long call's profit have no limit at all.
    #   downside bounded, but only at spot = 0. A short put's worst case is real and
    #            enormous rather than infinite, and it sits far outside a +/-12% scan.
    #
    # Collapsing both into one "unlimited" flag would either overstate the put side or
    # understate the call side.
    up_slope = pnls[-1] - pnls[-2]
    down_slope = pnls[0] - pnls[1]      # negative = still losing as spot falls

    unlimited_profit = up_slope > 0.01
    unlimited_loss = up_slope < -0.01           # naked short call: no ceiling on the loss
    downside_open = down_slope < -0.01          # loss still growing at the bottom of the scan

    # ── net Greeks at today's spot ──────────────────────────────────────────
    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    per_leg = []
    unpriced = 0
    for leg in legs:
        strike, otype = float(leg["strike"]), str(leg["option_type"]).upper()
        premium, qty = float(leg["premium"]), int(leg["quantity"])
        sign = 1 if leg["side"] == "BUY" else -1
        iv = None
        try:
            iv = solve_iv(premium, spot, strike, t, otype)
        except Exception:  # noqa: BLE001 — one unsolvable leg must not kill the analysis
            iv = None
        if not iv or iv <= 0:
            # No implied vol means no honest Greeks for this leg. Substituting a default
            # would produce a net delta that looks authoritative and is not.
            unpriced += 1
            per_leg.append({**_leg_label(leg), "iv": None, "greeks": None,
                            "note": "IV unsolvable from this premium — leg excluded from net Greeks"})
            continue
        g = black_scholes_greeks(spot, strike, t, otype, sigma=iv)
        scaled = {k: round(v * qty * sign, 4) for k, v in g.items()}
        for k in net:
            net[k] += scaled[k]
        per_leg.append({**_leg_label(leg), "iv": round(iv * 100, 2), "greeks": scaled})

    net = {k: round(v, 4) for k, v in net.items()}

    # ── margin, off the same SPAN-lite model the order path uses ────────────
    margin_legs = [{
        "kind": "OPTION", "option_type": str(l["option_type"]).upper(),
        "strike": float(l["strike"]), "qty": int(l["quantity"]),
        "side": l["side"], "premium": float(l["premium"]),
    } for l in legs]
    margin = portfolio_margin(margin_legs, spot, t)

    # ── net debit / credit ──────────────────────────────────────────────────
    net_premium = sum((1 if l["side"] == "BUY" else -1) * float(l["premium"]) * int(l["quantity"])
                      for l in legs)

    return {
        "ok": True,
        "spot": round(spot, 2),
        "expiry": expiry,
        "days_to_expiry": max(0, round(t * 365)),
        "lot_size": lot_size,
        "points": points,
        "breakevens": _breakevens(points),
        "max_profit": None if unlimited_profit else round(max_profit, 2),
        # None means genuinely unbounded. A downside-open structure still reports the worst
        # case IN THE SCAN, flagged, because "we scanned to -12% and it was still falling"
        # is useful and "unknown" is not.
        "max_loss": None if unlimited_loss else round(max_loss, 2),
        "unlimited_profit": unlimited_profit,
        "unlimited_loss": unlimited_loss,
        "downside_open": downside_open,
        "scan_range": {"low": round(lo, 2), "high": round(hi, 2), "pct": PAYOFF_SPAN * 100},
        "net_premium": round(net_premium, 2),
        "is_debit": net_premium > 0,
        "greeks": net,
        "per_leg": per_leg,
        "unpriced_legs": unpriced,
        "margin": {
            "total": round(margin.get("total", 0), 2),
            "span": round(margin.get("span", 0), 2),
            "exposure": round(margin.get("exposure", 0), 2),
        },
        "risk_note": _risk_note(unlimited_loss, downside_open, net, net_premium, lo),
    }


def _leg_label(leg: dict) -> dict:
    return {
        "strike": float(leg["strike"]),
        "option_type": str(leg["option_type"]).upper(),
        "side": leg["side"],
        "quantity": int(leg["quantity"]),
        "premium": float(leg["premium"]),
        "label": f"{leg['side']} {leg['quantity']} x {float(leg['strike']):g}"
                 f"{str(leg['option_type']).upper()}",
    }


def _risk_note(unlimited_loss: bool, downside_open: bool, greeks: dict,
               net_premium: float, scan_low: float) -> str:
    """One sentence on what this structure actually exposes you to."""
    if unlimited_loss:
        return ("UNBOUNDED LOSS ON THE UPSIDE. There is a naked short call here and spot has "
                "no ceiling, so there is no worst case — only one you have not scanned to. "
                "Size this on what you can afford to lose, never on the margin blocked.")
    if downside_open:
        return (f"OPEN DOWNSIDE. The loss is still growing at {scan_low:,.0f} and only stops "
                f"at zero, so the true worst case is far outside this chart. Bounded in "
                f"theory, ruinous in practice — size it accordingly.")
    parts = []
    parts.append("Credit received" if net_premium < 0 else "Debit paid")
    theta = greeks.get("theta", 0)
    if theta > 0:
        parts.append(f"time works FOR you at about {theta:,.0f}/day")
    elif theta < 0:
        parts.append(f"time works AGAINST you at about {abs(theta):,.0f}/day")
    delta = greeks.get("delta", 0)
    if abs(delta) > 0.5:
        parts.append(f"net {'long' if delta > 0 else 'short'} {abs(delta):.1f} delta")
    else:
        parts.append("close to delta-neutral")
    return ". ".join(parts) + ". Loss is capped."


def build_from_preset(preset_key: str, atm_strike: float, strike_step: float,
                      lots: int = 1, lot_size: int = 1) -> list[dict]:
    """Turn a preset into concrete strikes around the current ATM."""
    preset = PRESET_BY_KEY.get(preset_key)
    if not preset:
        raise KeyError(preset_key)
    out = []
    for leg in preset["legs"]:
        out.append({
            "strike": atm_strike + leg["offset"] * strike_step,
            "option_type": leg["type"],
            "side": leg["side"],
            "lots": leg["lots"] * lots,
            "quantity": leg["lots"] * lots * lot_size,
        })
    return out
