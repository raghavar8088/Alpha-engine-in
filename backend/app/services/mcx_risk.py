"""Real-money economics for MCX futures (C3): whole lots, margin, worst-day stress, and
what a trade would have made with real fills.

ONE SOURCE FOR CONTRACT SIZES. The value multiplier (rupees of P&L per rupee of quote per
lot) comes from `commodity_positions.CONTRACT_SPEC` — the instrument master's `lot_size`
is the broker's ORDER unit and is wrong as a multiplier (it says GOLD 1 and GOLDM 100;
the truth is 100 and 10). Margin is the same SPAN-lite calibration that desk uses.

THE REAL-MONEY P&L of a paper trade: one lot of the trade's own contract, bought at the
ask and sold at the bid the market showed at the paper fill (`entry_touch`/`exit_touch`),
charged Angel's card. The paper fill is LTP +- 5 bp; the touch is what a market order
would actually have paid. Trades from before the quotes were recorded have no real P&L.

WORST-DAY STRESS. A volatility budget sizes for an ordinary day; the account has to
survive the worst one. Single-day moves seen 2004-2026 in rupee terms (international
futures x USD/INR): silver -31% (30 Jan 2026), crude -25%, natural gas ~-30%, gold -11%,
copper / zinc ~-12%. A book is refused when its open lots would lose more than
`MAX_STRESS_PCT` of capital on every leg's worst day at once.
"""

from __future__ import annotations

import os
from datetime import date

from tradingai_shared.mcx_fees import mcx_round_trip

from app.services.commodity_positions import EXPOSURE_PCT, SCAN_FAMILY, _scan_pct, multiplier

WORST_DAY_MOVE: dict[str, float] = {
    "GOLD": 0.11, "SILVER": 0.31, "CRUDEOIL": 0.25, "NATURALGAS": 0.30,
    "COPPER": 0.12, "ZINC": 0.12, "ALUMINIUM": 0.10, "LEAD": 0.10, "NICKEL": 0.20,
}
MAX_STRESS_PCT = float(os.getenv("MCX_MAX_STRESS_PCT", "0.25"))

# The smallest liquid contract per commodity (open interest checked 2026-10-03: GOLDPETAL
# 198k, GOLDTEN 30k, SILVERMIC 134k, CRUDEOILM 36k, NATGASMINI 66k, ZINCMINI 3.7k).
# COPPER has no mini on MCX: one lot is ~Rs 35 lakh of copper.
SMALLEST: dict[str, list[str]] = {
    "GOLD": ["GOLDPETAL", "GOLDTEN", "GOLDM", "GOLD"],
    "SILVER": ["SILVERMIC", "SILVERM", "SILVER"],
    "CRUDEOIL": ["CRUDEOILM", "CRUDEOIL"],
    "NATURALGAS": ["NATGASMINI", "NATURALGAS"],
    "COPPER": ["COPPER"],
    "ZINC": ["ZINCMINI", "ZINC"],
}


def family(symbol: str) -> str:
    s = (symbol or "").upper()
    return SCAN_FAMILY.get(s, s)


def lot_value(symbol: str, price: float) -> float:
    return float(price) * multiplier(symbol)


def margin_per_lot(symbol: str, price: float) -> float:
    return (_scan_pct(symbol) + EXPOSURE_PCT) * lot_value(symbol, price)


def worst_day_loss(symbol: str, price: float, lots: int) -> float:
    return abs(lots) * lot_value(symbol, price) * WORST_DAY_MOVE.get(family(symbol), 0.20)


def whole_lots(symbol: str, price: float, target_notional: float) -> int:
    """Round a rupee exposure to whole lots (half rounds up). 0 when one lot is more
    than twice the target — taking it would more than double the intended risk."""
    lv = lot_value(symbol, price)
    if lv <= 0 or target_notional <= 0:
        return 0
    return int(target_notional / lv + 0.5)


def stress_check(legs: list[dict], capital: float) -> dict:
    """legs: [{symbol, price, lots}] -> worst-day loss of the whole book vs capital."""
    loss = sum(worst_day_loss(l["symbol"], l["price"], l["lots"]) for l in legs)
    margin = sum(abs(l["lots"]) * margin_per_lot(l["symbol"], l["price"]) for l in legs)
    return {"worst_day_loss": round(loss, 2), "worst_day_pct": round(loss / capital, 4) if capital else None,
            "margin": round(margin, 2), "margin_pct": round(margin / capital, 4) if capital else None,
            "limit_pct": MAX_STRESS_PCT, "ok": (loss <= MAX_STRESS_PCT * capital) and margin <= capital}


def real_trade(symbol: str, side: str, entry_touch: float | None, exit_touch: float | None,
               on: date | None = None, lots: int = 1) -> dict | None:
    """One lot (or `lots`) of the trade's own contract at the touch, Angel's charges."""
    if not entry_touch or not exit_touch:
        return None
    mult = multiplier(symbol)
    qty = mult * lots
    sign = 1 if side == "BUY" else -1
    gross = (exit_touch - entry_touch) * qty * sign
    fees = mcx_round_trip(entry_touch, exit_touch, qty, side, on)
    net = gross - fees
    notional = entry_touch * qty
    return {"lots": lots, "multiplier": mult, "entry": entry_touch, "exit": exit_touch,
            "gross": round(gross, 2), "fees": round(fees, 2), "pnl": round(net, 2),
            "net_bp": round(net / notional * 1e4, 3) if notional else None,
            "lot_value": round(notional / lots, 2) if lots else None}
