"""Angel-One option chain — assembled locally, because Angel (unlike Dhan) has no
single option-chain endpoint. We enumerate the listed strikes from our own
`instruments` collection, batch-quote them in Angel FULL mode (LTP + OI + volume), and
fold in Black-Scholes IV/Greeks with the SAME helpers the Dhan chain used
(options_service.chain), so the output is shape-identical to `parse_chain` and every
existing consumer (F&O Positions, Options Analytics, Chart) can read it unchanged.

Coverage note: a strike only appears if its contract has been mapped to an Angel token
(`angel_token`) by the market-data instrument sync. That mapping is being completed;
until it is, a chain shows the mapped strikes (the liquid near-ATM band first) rather
than the entire listed ladder. Expiries come straight from the DB, so they never depend
on a broker being reachable.
"""

import logging
from datetime import datetime

from app.core.db import instruments_collection
from app.services.angel_client import AngelAPIError, angel_client
from options_service.chain import (
    _fill_leg,
    _years_to_expiry,
    compute_max_pain,
    compute_pcr,
)

logger = logging.getLogger("angel_option_chain")

OPTION_CLASSES = ("INDEX_OPTION", "EQUITY_OPTION")
INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}


class ChainError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


async def _underlying(symbol: str) -> dict | None:
    return await instruments_collection.find_one({
        "symbol": symbol.upper(),
        "asset_class": "INDEX" if symbol.upper() in INDEX_UNDERLYINGS else "EQUITY",
    })


async def option_expiries(symbol: str) -> list[str]:
    """Listed expiries for the underlying, from the instrument master — no broker call."""
    today = datetime.now().date().isoformat()
    rows = await instruments_collection.distinct(
        "expiry", {"underlying_symbol": symbol.upper(), "asset_class": {"$in": list(OPTION_CLASSES)}}
    )
    return sorted(e for e in rows if e and e >= today)


async def _angel_spot(under: dict) -> float | None:
    tok, ex = under.get("angel_token"), under.get("angel_exchange") or "NSE"
    if not tok:
        return None
    try:
        prices = await angel_client.ltp({ex: [str(tok)]})
    except AngelAPIError:
        return None
    val = prices.get(str(tok))
    return float(val) if val else None


def _atm_parity_spot(strikes: list[dict]) -> float | None:
    """Fallback spot when the index itself isn't priced: at the ATM strike CE-PE ≈
    spot-strike (put-call parity, ignoring rate/time), so spot ≈ strike + (ce - pe) at
    the strike where |ce - pe| is smallest."""
    best = None
    for s in strikes:
        ce, pe = s["ce"].get("last_price") or 0, s["pe"].get("last_price") or 0
        if ce <= 0 or pe <= 0:
            continue
        diff = abs(ce - pe)
        if best is None or diff < best[0]:
            best = (diff, s["strike"] + (ce - pe))
    return round(best[1], 2) if best else None


async def option_chain(symbol: str, expiry: str) -> dict:
    """Assemble the chain for one underlying+expiry from Angel FULL quotes. Same output
    shape as options_service.parse_chain, plus `symbol` and `source`."""
    under = await _underlying(symbol)
    if under is None:
        raise ChainError(f"{symbol} has no underlying instrument on file")

    contracts = [
        c async for c in instruments_collection.find(
            {"underlying_symbol": symbol.upper(), "expiry": expiry,
             "asset_class": {"$in": list(OPTION_CLASSES)}, "angel_token": {"$ne": None}},
            {"strike": 1, "option_type": 1, "angel_token": 1, "angel_exchange": 1},
        )
    ]
    if not contracts:
        raise ChainError(
            f"No Angel-mapped {symbol} option contracts for {expiry} yet — the Dhan→Angel "
            "token mapping for these strikes is still being filled in."
        )

    by_ex: dict[str, list[str]] = {}
    tokmap: dict[str, tuple[float, str]] = {}
    for c in contracts:
        tok = str(c["angel_token"])
        by_ex.setdefault(c.get("angel_exchange") or "NFO", []).append(tok)
        tokmap[tok] = (float(c["strike"]), str(c["option_type"]).upper())

    quotes: dict[str, dict] = {}
    try:
        for ex, toks in by_ex.items():
            quotes.update(await angel_client.full_quote({ex: toks}))
    except AngelAPIError as exc:
        raise ChainError(f"Angel quote failed while building the chain: {exc}")

    spot = await _angel_spot(under) or 0.0
    t_years = _years_to_expiry(expiry)

    strike_legs: dict[float, dict] = {}
    for tok, (strike, ot) in tokmap.items():
        row = quotes.get(tok)
        if not row:
            continue
        strike_legs.setdefault(strike, {})[ot.lower()] = {
            "last_price": row.get("ltp") or 0,
            "oi": row.get("oi") or 0,
            "volume": row.get("volume") or 0,
            "previous_close_price": row.get("close") or 0,
        }

    strikes: list[dict] = []
    for strike in sorted(strike_legs):
        legs = strike_legs[strike]
        strikes.append({"strike": strike, "ce": legs.get("ce") or {}, "pe": legs.get("pe") or {}})

    if not spot:
        spot = _atm_parity_spot(strikes) or 0.0
    if spot:
        for s in strikes:
            s["ce"] = _fill_leg(s["ce"], spot, s["strike"], t_years, "CE")
            s["pe"] = _fill_leg(s["pe"], spot, s["strike"], t_years, "PE")

    return {
        "symbol": symbol.upper(),
        "spot": spot,
        "expiry": expiry,
        "days_to_expiry": round(t_years * 365),
        "strikes": strikes,
        "pcr_oi": compute_pcr(strikes),
        "max_pain": compute_max_pain(strikes),
        "source": "angel",
    }
