"""MCX futures charges — the one schedule every commodity desk and the executor use.

Angel One's card for commodity futures (angelone.in/exchange-transaction-charges, read
2026-10-03): brokerage Rs 20 per executed order; MCX exchange transaction charge 0.0021%
of turnover (MCX's revised rate from 2024-10-01; it was 0.0026% before); CTT 0.01% on the
SELL side of non-agricultural commodities; stamp duty 0.002% on the BUY side; SEBI fee
Rs 10 a crore; GST 18% on brokerage + exchange charge + SEBI fee.

The desks each carried their own copy of this (the pattern desk with exchange 0.0026% and
a 0.03% brokerage cap Angel does not charge), which is how two pages showed different costs
for the same trade. One schedule, dated, so a past trade is costed at the rate of its day.
Rounding happens once, on the total — not per component.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class McxRates:
    effective: date
    brokerage_per_order: float = 20.0
    exchange_pct: float = 0.000021
    ctt_sell_pct: float = 0.0001
    stamp_buy_pct: float = 0.00002
    sebi_pct: float = 0.000001          # Rs 10 / crore
    gst_pct: float = 0.18


SCHEDULE: list[McxRates] = [
    McxRates(effective=date(2000, 1, 1), exchange_pct=0.000026),
    McxRates(effective=date(2024, 10, 1)),
]


def rates_on(on: date | None = None) -> McxRates:
    d = on or date.today()
    current = SCHEDULE[0]
    for r in SCHEDULE:
        if r.effective <= d:
            current = r
    return current


def leg_breakdown(price: float, qty: float, is_buy: bool, on: date | None = None, orders: int = 1) -> dict:
    """Charges for one executed side. `qty` is in PRICE units (price x qty = turnover):
    lots x the contract's value multiplier, never the broker's lot count."""
    r = rates_on(on)
    turnover = float(price) * float(qty)
    if turnover <= 0:
        return {"turnover": 0.0, "total": 0.0}
    brokerage = r.brokerage_per_order * max(int(orders), 1)
    exch = turnover * r.exchange_pct
    sebi = turnover * r.sebi_pct
    ctt = 0.0 if is_buy else turnover * r.ctt_sell_pct
    stamp = turnover * r.stamp_buy_pct if is_buy else 0.0
    gst = r.gst_pct * (brokerage + exch + sebi)
    total = brokerage + exch + sebi + ctt + stamp + gst
    return {"turnover": turnover, "brokerage": brokerage, "exchange": exch, "sebi": sebi, "ctt": ctt,
            "stamp": stamp, "gst": gst, "total": total, "rates_effective": r.effective.isoformat()}


def mcx_leg(price: float, qty: float, is_buy: bool, on: date | None = None, orders: int = 1) -> float:
    return round(leg_breakdown(price, qty, is_buy, on, orders)["total"], 2)


def mcx_round_trip(entry: float, exit_: float, qty: float, side: str, on: date | None = None) -> float:
    """Both legs of a futures round trip. `side` is the ENTRY side ("BUY" = long)."""
    long = side.upper() == "BUY"
    a = leg_breakdown(entry, qty, long, on)["total"]
    b = leg_breakdown(exit_, qty, not long, on)["total"]
    return round(a + b, 2)
