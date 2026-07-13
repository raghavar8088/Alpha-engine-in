"""Black-Scholes European option pricing + Greeks + implied-volatility solver.
Pure-python (erf-based normal CDF/PDF, no numpy/scipy) to match the rest of this
codebase's dependency-light style. Used both to cross-check/fill gaps in Dhan's own
quoted Greeks and to price the synthetic option series `options_backtest.py` needs
(no continuous historical option-chain series exists to backtest against directly)."""

import math

MIN_T_YEARS = 1 / 365 / 24  # floor at ~1 hour to avoid division by zero at/after expiry


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _d1_d2(spot: float, strike: float, t_years: float, rate: float, dividend: float, sigma: float) -> tuple[float, float]:
    t = max(t_years, MIN_T_YEARS)
    sigma = max(sigma, 1e-6)
    d1 = (math.log(spot / strike) + (rate - dividend + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    return d1, d2


def black_scholes_price(
    spot: float, strike: float, t_years: float, option_type: str,
    rate: float = 0.065, dividend: float = 0.0, sigma: float = 0.15,
) -> float:
    """`rate` defaults to a representative Indian risk-free rate (91-day T-bill
    ballpark); `sigma` is annualized volatility (e.g. 0.15 = 15%)."""
    t = max(t_years, MIN_T_YEARS)
    d1, d2 = _d1_d2(spot, strike, t, rate, dividend, sigma)
    disc_r = math.exp(-rate * t)
    disc_q = math.exp(-dividend * t)
    if option_type.upper() == "CE":
        return spot * disc_q * _norm_cdf(d1) - strike * disc_r * _norm_cdf(d2)
    return strike * disc_r * _norm_cdf(-d2) - spot * disc_q * _norm_cdf(-d1)


def black_scholes_greeks(
    spot: float, strike: float, t_years: float, option_type: str,
    rate: float = 0.065, dividend: float = 0.0, sigma: float = 0.15,
) -> dict:
    """Returns delta, gamma, theta (PER DAY, not per year), vega (per 1 vol POINT,
    i.e. per 1% = 0.01 change in sigma), rho (per 1% change in rate)."""
    t = max(t_years, MIN_T_YEARS)
    is_call = option_type.upper() == "CE"
    d1, d2 = _d1_d2(spot, strike, t, rate, dividend, sigma)
    disc_r = math.exp(-rate * t)
    disc_q = math.exp(-dividend * t)
    pdf_d1 = _norm_pdf(d1)

    gamma = disc_q * pdf_d1 / (spot * sigma * math.sqrt(t))
    vega = spot * disc_q * pdf_d1 * math.sqrt(t) / 100  # per 1 vol point

    if is_call:
        delta = disc_q * _norm_cdf(d1)
        theta_year = (
            -spot * disc_q * pdf_d1 * sigma / (2 * math.sqrt(t))
            - rate * strike * disc_r * _norm_cdf(d2)
            + dividend * spot * disc_q * _norm_cdf(d1)
        )
        rho = strike * t * disc_r * _norm_cdf(d2) / 100
    else:
        delta = -disc_q * _norm_cdf(-d1)
        theta_year = (
            -spot * disc_q * pdf_d1 * sigma / (2 * math.sqrt(t))
            + rate * strike * disc_r * _norm_cdf(-d2)
            - dividend * spot * disc_q * _norm_cdf(-d1)
        )
        rho = -strike * t * disc_r * _norm_cdf(-d2) / 100

    return {
        "delta": round(delta, 5),
        "gamma": round(gamma, 6),
        "theta": round(theta_year / 365, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
    }


def implied_volatility(
    market_price: float, spot: float, strike: float, t_years: float, option_type: str,
    rate: float = 0.065, dividend: float = 0.0,
    initial_guess: float = 0.3, max_iter: int = 50, tol: float = 1e-6,
) -> float | None:
    """Newton-Raphson with a bisection fallback (vega collapses near-zero for
    deep ITM/OTM, where Newton-Raphson can diverge). Returns None if no volatility
    in [0.001, 5.0] reproduces the price (e.g. the quote is below intrinsic value)."""
    t = max(t_years, MIN_T_YEARS)
    sigma = initial_guess
    for _ in range(max_iter):
        price = black_scholes_price(spot, strike, t, option_type, rate, dividend, sigma)
        vega_per_unit = black_scholes_greeks(spot, strike, t, option_type, rate, dividend, sigma)["vega"] * 100
        diff = price - market_price
        if abs(diff) < tol:
            return round(sigma, 6)
        if vega_per_unit < 1e-8:
            break
        sigma -= diff / vega_per_unit
        if sigma <= 0 or sigma > 5:
            break

    lo, hi = 0.001, 5.0
    price_lo = black_scholes_price(spot, strike, t, option_type, rate, dividend, lo) - market_price
    price_hi = black_scholes_price(spot, strike, t, option_type, rate, dividend, hi) - market_price
    if price_lo * price_hi > 0:
        return None  # market price outside what any volatility in range can produce
    for _ in range(100):
        mid = (lo + hi) / 2
        price_mid = black_scholes_price(spot, strike, t, option_type, rate, dividend, mid) - market_price
        if abs(price_mid) < tol:
            return round(mid, 6)
        if price_lo * price_mid < 0:
            hi = mid
        else:
            lo, price_lo = mid, price_mid
    return round((lo + hi) / 2, 6)
