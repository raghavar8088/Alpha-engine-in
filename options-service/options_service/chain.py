"""Option-chain normalization + OI analytics. Pure functions over the ALREADY-FETCHED
Dhan option-chain response (fetching itself lives on `DhanClient.option_chain()` in the
backend, which owns the broker connection) — keeps this package unit-testable without
a live broker.

Dhan's own Greeks/IV read 0 for illiquid strikes with no recent trade; where that
happens but a last-traded price exists, we fill the gap with our own Black-Scholes
IV-from-price + Greeks, tagged `"source": "computed"` vs `"source": "broker"` so a caller
never mistakes a modeled value for an exchange-quoted one."""

from datetime import date, datetime

from options_service.greeks import black_scholes_greeks, implied_volatility

RISK_FREE_RATE = 0.065


def _years_to_expiry(expiry: str, as_of: date | None = None) -> float:
    as_of = as_of or datetime.now().date()
    expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    return max((expiry_date - as_of).days, 0) / 365.0


def _fill_leg(leg: dict, spot: float, strike: float, t_years: float, option_type: str) -> dict:
    iv = leg.get("implied_volatility") or 0
    greeks = leg.get("greeks") or {}
    has_broker_greeks = iv > 0 and any(v for v in greeks.values())
    ltp = leg.get("last_price") or 0

    if has_broker_greeks:
        return {**leg, "implied_volatility_source": "broker", "greeks_source": "broker"}
    if ltp <= 0:
        return {**leg, "implied_volatility_source": None, "greeks_source": None}

    solved_iv = implied_volatility(ltp, spot, strike, t_years, option_type, RISK_FREE_RATE)
    if solved_iv is None:
        return {**leg, "implied_volatility_source": None, "greeks_source": None}
    computed_greeks = black_scholes_greeks(spot, strike, t_years, option_type, RISK_FREE_RATE, sigma=solved_iv)
    return {
        **leg, "implied_volatility": round(solved_iv * 100, 3),
        "implied_volatility_source": "computed", "greeks": computed_greeks, "greeks_source": "computed",
    }


def parse_chain(raw: dict, expiry: str, as_of: date | None = None) -> dict:
    """Normalizes Dhan's `{"<strike_str>": {"ce": {...}, "pe": {...}}}` into a sorted
    list, filling illiquid Greeks/IV gaps as documented above."""
    data = raw.get("data", {})
    spot = data.get("last_price", 0)
    t_years = _years_to_expiry(expiry, as_of)

    strikes = []
    for strike_str, legs in (data.get("oc") or {}).items():
        strike = float(strike_str)
        ce = _fill_leg(legs.get("ce") or {}, spot, strike, t_years, "CE")
        pe = _fill_leg(legs.get("pe") or {}, spot, strike, t_years, "PE")
        strikes.append({"strike": strike, "ce": ce, "pe": pe})
    strikes.sort(key=lambda s: s["strike"])

    return {
        "spot": spot, "expiry": expiry, "days_to_expiry": round(t_years * 365),
        "strikes": strikes, "pcr_oi": compute_pcr(strikes), "max_pain": compute_max_pain(strikes),
    }


def compute_pcr(strikes: list[dict]) -> float | None:
    """Put/Call ratio by open interest — >1 reads bullish-contrarian (heavy put
    writing), <1 bearish-contrarian, by the usual (imperfect) market convention."""
    call_oi = sum(s["ce"].get("oi") or 0 for s in strikes)
    put_oi = sum(s["pe"].get("oi") or 0 for s in strikes)
    return round(put_oi / call_oi, 3) if call_oi > 0 else None


def compute_max_pain(strikes: list[dict]) -> float | None:
    """The strike at which OPTION WRITERS collectively lose the least at expiry —
    the classic (imperfect) 'max pain' pin-risk heuristic."""
    if not strikes:
        return None
    candidate_strikes = [s["strike"] for s in strikes]
    best_strike, best_loss = None, float("inf")
    for settle in candidate_strikes:
        total_loss = 0.0
        for s in strikes:
            call_oi = s["ce"].get("oi") or 0
            put_oi = s["pe"].get("oi") or 0
            total_loss += max(settle - s["strike"], 0) * call_oi  # call writers pay this if ITM
            total_loss += max(s["strike"] - settle, 0) * put_oi  # put writers pay this if ITM
        if total_loss < best_loss:
            best_strike, best_loss = settle, total_loss
    return best_strike


def classify_oi_buildup(leg: dict) -> str | None:
    """Long Build-up / Short Build-up / Long Unwinding / Short Covering, from THIS
    contract's own price and OI change (not the underlying's) — the standard
    per-contract convention."""
    ltp, prev_close = leg.get("last_price") or 0, leg.get("previous_close_price") or 0
    oi, prev_oi = leg.get("oi") or 0, leg.get("previous_oi") or 0
    if ltp <= 0 or prev_close <= 0:
        return None
    price_up, oi_up = ltp > prev_close, oi > prev_oi
    if price_up and oi_up:
        return "Long Build-up"
    if not price_up and oi_up:
        return "Short Build-up"
    if not price_up and not oi_up:
        return "Long Unwinding"
    if price_up and not oi_up:
        return "Short Covering"
    return None
