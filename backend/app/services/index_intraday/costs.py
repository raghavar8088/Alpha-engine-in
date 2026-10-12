"""Indian Index Intraday: what a trade costs, per index, on the route a real account would use.

An index cannot be bought. The research trades the INDEX level (signals and fills) but charges
every trade what the matching cash-market ETF would cost:

  charges   Angel One's intraday rate card, computed by the app's own fee model
            (app.services.angel_fees.round_trip) at the position size: brokerage min(Rs20,
            0.25%) a side, STT 0.025% on the sell, exchange 0.00297%, SEBI, IPFT, stamp 0.003%
            on the buy, GST 18% on the services — ~4.0 bp a round trip at Rs10 lakh.
  slippage  half-spread + impact a side for a Rs10 lakh market order in the ETF: a starting
            table (below), then checked against each ETF's effective spread estimated from its
            own 1-minute prices (Roll's bid-ask-bounce estimator, research ii_spreads.py) — the larger
            of the two is used.

BANKEX has no exchange-traded ETF: it is studied as an index-point SIMULATION only, charged
BANKBEES' costs, and can never be traded in the cash market — the module says so.
"""

from __future__ import annotations

from app.services.angel_fees import round_trip

from .engine import Costs

NOTIONAL = 1_000_000.0          # Rs10 lakh a trade

# index -> (ETF symbol, ETF price on 2026-10-09 for the fee arithmetic, slippage bp a side)
# Slippage is the MEASURED effective half-spread (the larger of Roll's and Corwin-Schultz's
# estimates, 2024-2026 1-minute bars after the price-sanity rules; research ii_spreads.py), never
# less than the starting table.
# The research rounds used the starting table, which UNDER-charged the four thin ETFs — their
# indexes failed even so.
ROUTE = {
    "NIFTY": ("NIFTYBEES", 280.0, 1.0),
    "BANKNIFTY": ("BANKBEES", 560.0, 1.7),
    "SENSEX": ("SENSEXIETF", 900.0, 4.5),
    "FINNIFTY": ("FINIETF", 30.0, 5.0),
    "NIFTYNXT50": ("JUNIORBEES", 700.0, 2.0),
    "NIFTY100": ("NIF100BEES", 270.0, 21.2),
    "MIDCPNIFTY": ("MIDSELIETF", 16.0, 9.4),
    "BANKEX": (None, 560.0, 1.7),
}
# Median traded value of a traded minute (Rs lakh, 2024-2026) — what an intraday order can take
# without moving the ETF. The paper engine caps an ETF order at LIQUIDITY_SHARE of it.
MINUTE_VALUE_LAKH = {"NIFTYBEES": 20.2, "BANKBEES": 4.1, "JUNIORBEES": 2.3, "SENSEXIETF": 0.2,
                     "FINIETF": 0.2, "NIF100BEES": 0.4, "MIDSELIETF": 0.1}
LIQUIDITY_SHARE = 0.25
# The research's starting slippage table (bp a side), kept for the record the rounds were run on.
RESEARCH_SLIP = {"NIFTY": 1.0, "BANKNIFTY": 1.5, "SENSEX": 3.0, "FINNIFTY": 5.0, "NIFTYNXT50": 2.0,
                 "NIFTY100": 3.0, "MIDCPNIFTY": 6.0, "BANKEX": 1.5}


def max_etf_order(etf: str | None) -> float:
    """The largest ETF order (Rs) the engine will simulate: LIQUIDITY_SHARE of a median minute."""
    if not etf:
        return 0.0
    return MINUTE_VALUE_LAKH.get(etf, 0.0) * 1e5 * LIQUIDITY_SHARE


def fee_rt_bp(price: float = 280.0, notional: float = NOTIONAL) -> float:
    qty = max(1, int(notional // price))
    fb = round_trip(price, price, qty, "BUY", "INTRADAY")
    return fb.total / (qty * price) * 1e4


def costs_for(index: str, slip_override: float | None = None, scale: float = 1.0,
              research: bool = False) -> Costs:
    """The all-in cost model for one index's route. `research=True` reproduces the table the
    research rounds were run on."""
    etf, px, slip = ROUTE[index]
    if research:
        slip = RESEARCH_SLIP[index]
    s = slip if slip_override is None else slip_override
    return Costs(fee_rt_bp=fee_rt_bp(px) * scale, slip_bp=s * scale)


if __name__ == "__main__":
    for idx, (etf, px, slip) in ROUTE.items():
        print(f"{idx:11} via {etf or '(no ETF — simulation only)':28} charges {fee_rt_bp(px):.2f} bp a round trip "
              f"at Rs10 lakh; slippage {slip} bp a side -> {fee_rt_bp(px) + 2 * slip:.2f} bp all-in")
