"""SPAN-lite portfolio margin engine for the F&O Positions paper desk.

Why this exists: Dhan's /margincalculator prices ONE leg at a time, so it cannot
express the hedge benefit that makes an iron condor cost a fraction of a naked
strangle. Real brokers margin the whole basket at once — the exchange's SPAN
algorithm walks a set of underlying-price scenarios and takes the worst-case
portfolio loss, so a long option that caps a short's loss shrinks the whole
number. We reproduce that here, on the same Black-Scholes pricer the option chain
already uses (options_service.greeks), so the two are consistent.

Method (a defensible SPAN approximation, not the exchange's exact 16-scenario
array):
  1. Scan the underlying across +/- PRICE_SCAN_PCT (SPAN's "price scan range";
     ~6% for index is the calibration that lands a naked NIFTY strangle near the
     ~Rs2 lakh a real broker blocks).
  2. Re-price every leg with Black-Scholes at each scenario (same days-to-expiry
     and per-leg IV — so time value at the scan edge is captured, not just
     intrinsic).
  3. SPAN = the worst (largest) portfolio loss across those scenarios, floored at
     0. A long-only basket is bounded by the premium paid; a naked short is large;
     a hedged short is capped by its wings — the benefit falls out for free.
  4. Exposure margin = EXPOSURE_PCT of the NET-short notional per option type (and
     net futures), so a fully-hedged structure (equal long/short counts per type)
     carries little-to-no exposure either.
  total = SPAN + exposure. All figures are per the quantities passed (already in
  units = lots x lot_size), long-or-short via each leg's `side`.

Everything here is pure/synchronous and does no I/O — callers supply spot, time to
expiry and each leg's premium/IV. Tunables are env-overridable so the calibration
can move without a code change.
"""

import os

from options_service.greeks import black_scholes_price, implied_volatility

PRICE_SCAN_PCT = float(os.getenv("FNO_MARGIN_PRICE_SCAN_PCT", "0.06"))
EXPOSURE_PCT = float(os.getenv("FNO_MARGIN_EXPOSURE_PCT", "0.03"))
SCAN_STEPS = int(os.getenv("FNO_MARGIN_SCAN_STEPS", "40"))
# Relative IV shift added as an extra worst-case scenario (SPAN also scans vol).
# Default 0 keeps the naked-strangle calibration on ~Rs2 lakh; raise it for a more
# conservative (higher) short margin.
VOL_SHIFT = float(os.getenv("FNO_MARGIN_VOL_SHIFT", "0"))
RISK_FREE = float(os.getenv("FNO_MARGIN_RISK_FREE", "0.065"))
DEFAULT_IV = float(os.getenv("FNO_MARGIN_DEFAULT_IV", "0.15"))
MIN_T_YEARS = 0.5 / 365.0  # never let time-to-expiry hit zero in the pricer


def solve_iv(premium: float, spot: float, strike: float, t_years: float, option_type: str) -> float:
    """Implied vol from a leg's premium, falling back to DEFAULT_IV when the
    solver can't reproduce the price (deep ITM/OTM, stale/za quote)."""
    if not (premium and premium > 0 and spot and spot > 0 and strike and strike > 0):
        return DEFAULT_IV
    try:
        iv = implied_volatility(premium, spot, strike, max(t_years, MIN_T_YEARS), option_type, RISK_FREE)
    except Exception:
        iv = None
    if iv is None or iv <= 0.001 or iv > 5.0:
        return DEFAULT_IV
    return float(iv)


def _leg_value(scenario_spot: float, leg: dict, t_years: float, at_expiry: bool = False) -> float:
    """Mark of one leg at a scanned underlying price. A future tracks the
    underlying 1:1. An option is re-priced with Black-Scholes at the same t, or —
    for the expiry scenario — taken at pure intrinsic (t=0 payoff), which is what
    makes an out-of-the-money long lose its entire premium."""
    if leg.get("kind") == "FUTURE" or not leg.get("option_type"):
        return scenario_spot
    strike = float(leg["strike"])
    if at_expiry:
        return max(scenario_spot - strike, 0.0) if str(leg["option_type"]).upper() == "CE" else max(strike - scenario_spot, 0.0)
    iv = leg.get("iv") or DEFAULT_IV
    return black_scholes_price(
        scenario_spot, strike, max(t_years, MIN_T_YEARS),
        str(leg["option_type"]).upper(), RISK_FREE, 0.0, iv,
    )


def _exposure(legs: list[dict], spot: float, exposure_pct: float | None = None) -> float:
    """EXPOSURE_PCT on the NET-short notional per option type + net futures, so a
    balanced hedge (equal long/short counts of a type) carries no exposure on it."""
    pct = EXPOSURE_PCT if exposure_pct is None else exposure_pct
    short_ce = long_ce = short_pe = long_pe = 0.0
    net_fut = 0.0
    for leg in legs:
        qty = float(leg.get("qty") or 0)
        is_short = str(leg.get("side", "BUY")).upper() == "SELL"
        if leg.get("kind") == "FUTURE" or not leg.get("option_type"):
            net_fut += (-qty if is_short else qty)
            continue
        ot = str(leg["option_type"]).upper()
        if ot == "CE":
            short_ce += qty if is_short else 0.0
            long_ce += 0.0 if is_short else qty
        else:
            short_pe += qty if is_short else 0.0
            long_pe += 0.0 if is_short else qty
    net_short_ce = max(0.0, short_ce - long_ce)
    net_short_pe = max(0.0, short_pe - long_pe)
    units = net_short_ce + net_short_pe + abs(net_fut)
    return pct * spot * units


def portfolio_margin(legs: list[dict], spot: float, t_years: float,
                     price_scan_pct: float | None = None,
                     exposure_pct: float | None = None) -> dict:
    """Portfolio margin (span + exposure) for a set of legs on ONE underlying.

    legs: [{kind:"OPTION"|"FUTURE", option_type:"CE"|"PE"|None, strike, qty (units,
            positive), side:"BUY"|"SELL", premium, iv}]. Empty -> zero.

    `price_scan_pct`/`exposure_pct` override the module defaults for ONE call. The
    defaults are calibrated on NIFTY (~6%), which is wrong for other markets: the MCX
    desk scans natural gas at 13% and gold at 5%, because one shared number would
    either over-margin the metals or under-margin the energies. Omitting them keeps
    the F&O desk byte-identical.
    """
    scan = PRICE_SCAN_PCT if price_scan_pct is None else price_scan_pct
    if not legs or not spot or spot <= 0:
        return {"span": 0.0, "exposure": 0.0, "total": 0.0, "worst_spot": spot}

    iv_shifts = (1.0,) if VOL_SHIFT <= 0 else (1.0, 1.0 + VOL_SHIFT)
    # Scan TWO time points: today (current t — captures a short's mark-to-market loss
    # on a price move, which still carries time value) AND expiry (t~0, intrinsic —
    # captures a LONG option decaying to zero, i.e. its premium at risk). Taking the
    # worst across both is what makes a long straddle cost its premium and a debit
    # spread its net debit, with no separate premium term to double-count.
    # (t_years, at_expiry?) — today's mark AND the expiry payoff.
    time_points = ((t_years, False), (0.0, True))
    worst_loss = 0.0
    worst_spot = spot
    for i in range(SCAN_STEPS + 1):
        frac = 2.0 * i / SCAN_STEPS - 1.0  # -1 .. +1
        s2 = spot * (1.0 + scan * frac)
        for tp, at_expiry in time_points:
            for shift in iv_shifts:
                pnl = 0.0
                for leg in legs:
                    sgn = 1.0 if str(leg.get("side", "BUY")).upper() == "BUY" else -1.0
                    shifted = dict(leg)
                    if shift != 1.0 and not at_expiry and leg.get("option_type"):
                        shifted["iv"] = (leg.get("iv") or DEFAULT_IV) * shift
                    value = _leg_value(s2, shifted, tp, at_expiry)
                    pnl += sgn * (value - float(leg["premium"])) * float(leg.get("qty") or 0)
                loss = -pnl
                if loss > worst_loss:
                    worst_loss, worst_spot = loss, s2

    span = max(0.0, worst_loss)
    exposure = _exposure(legs, spot, exposure_pct)
    return {
        "span": round(span, 2),
        "exposure": round(exposure, 2),
        "total": round(span + exposure, 2),
        "worst_spot": round(worst_spot, 2),
    }
