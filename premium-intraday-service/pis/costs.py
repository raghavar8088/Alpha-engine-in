"""Costs of one intraday equity round trip: Angel One's charges plus modelled slippage.

CHARGES are the app's own schedule, backend/app/services/angel_fees.round_trip(product="INTRADAY"), reproduced here
so the container needs no backend code; tests/test_costs.py proves the two agree to the paisa on random trades.
  brokerage min(Rs 20, 0.25% of the order) per order; STT 0.025% of the sell leg; NSE transaction 0.00297% both legs;
  SEBI Rs 10/crore and NSE IPFT Rs 10/crore both legs; stamp duty 0.003% of the buy leg; GST 18% on brokerage +
  transaction + SEBI + IPFT.

SLIPPAGE is per side, by the stock's 20-session median daily traded value (pis.config.Costs.bands): measured from
Angel's live order book at 3,355 tournament entries. A stop, a time exit and the square-off are market orders and
pay it; a target is a limit order and pays none, but fills only when the price trades THROUGH it by one tick.
"""
from __future__ import annotations

GST_RATE = 0.18
BROKERAGE_CAP = 20.0
BROKERAGE_PCT = 0.0025
STT_SELL = 0.00025
STAMP_BUY = 0.00003
EXCHANGE_TXN = 0.0000297
SEBI = 0.000001
IPFT = 0.000001


def charges(entry: float, exit_: float, qty: int, side: int) -> dict:
    """side +1 = the position opened with a BUY (a long), -1 = opened with a SELL (a short)."""
    if qty <= 0 or entry <= 0 or exit_ <= 0:
        return {"brokerage": 0.0, "stt": 0.0, "exchange_txn": 0.0, "sebi": 0.0, "ipft": 0.0, "stamp_duty": 0.0,
                "gst": 0.0, "total": 0.0}
    buy = (entry if side > 0 else exit_) * qty
    sell = (exit_ if side > 0 else entry) * qty
    turnover = buy + sell
    brokerage = min(BROKERAGE_CAP, buy * BROKERAGE_PCT) + min(BROKERAGE_CAP, sell * BROKERAGE_PCT)
    stt = sell * STT_SELL
    exch = turnover * EXCHANGE_TXN
    sebi = turnover * SEBI
    ipft = turnover * IPFT
    stamp = buy * STAMP_BUY
    gst = GST_RATE * (brokerage + exch + sebi + ipft)
    total = round(brokerage + stt + exch + sebi + ipft + stamp + gst, 2)
    return {"brokerage": brokerage, "stt": stt, "exchange_txn": exch, "sebi": sebi, "ipft": ipft,
            "stamp_duty": stamp, "gst": gst, "total": total}


def slippage_bp(turnover_cr: float | None, bands, stress: float = 1.0) -> float:
    tv = float(turnover_cr or 0.0)
    for floor, bp in bands:
        if tv >= floor:
            return bp * stress
    return bands[-1][1] * stress


def band_name(turnover_cr: float | None) -> str:
    tv = float(turnover_cr or 0.0)
    if tv >= 1000:
        return ">= Rs 1,000 cr"
    if tv >= 300:
        return "Rs 300-1,000 cr"
    if tv >= 150:
        return "Rs 150-300 cr"
    return "< Rs 150 cr"


def est_cost_per_share(price: float, qty_hint: int, side: int, slip_bp: float) -> float:
    """Planned round-trip cost per share for sizing: charges at a flat exit plus slippage on both legs."""
    qty = max(1, int(qty_hint))
    c = charges(price, price, qty, side)["total"] / qty
    return c + 2.0 * price * slip_bp / 1e4
