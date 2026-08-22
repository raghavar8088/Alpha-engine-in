"""Domain rules for the paper broker: what an order may be, and what it costs.

Everything here is pure and synchronous. It is the part of a broker that is policy rather
than plumbing, kept separate so the rules can be read — and argued with — without wading
through database calls.
"""

from __future__ import annotations

import os
from datetime import datetime, time, timedelta, timezone

from app.services.angel_fees import option_round_trip, round_trip

IST = timezone(timedelta(hours=5, minutes=30))

# ── segments ────────────────────────────────────────────────────────────────────
SEGMENT_EQUITY = "EQUITY"
SEGMENT_FNO = "FNO"
SEGMENTS = (SEGMENT_EQUITY, SEGMENT_FNO)

# ── order vocabulary, matching what a real terminal offers ──────────────────────
ORDER_TYPES = ("MARKET", "LIMIT", "SL", "SL-M")
TRANSACTION_TYPES = ("BUY", "SELL")
VALIDITIES = ("DAY", "IOC")

# CNC  delivery equity — cannot short, settles into holdings
# MTF  delivery equity on broker funding — cannot short, carries overnight, accrues DAILY
#      interest on the funded part and pledge fees in and out. See paper_broker.mtf.
# MIS  intraday, any segment — squared off at the cutoff, leveraged
# NRML overnight F&O — carries to expiry
PRODUCTS_EQUITY = ("CNC", "MTF", "MIS")
PRODUCTS_FNO = ("NRML", "MIS")

ORDER_STATUSES = ("PENDING", "TRIGGER_PENDING", "COMPLETE", "CANCELLED", "REJECTED", "EXPIRED")
OPEN_STATUSES = ("PENDING", "TRIGGER_PENDING")

# ── session clock ───────────────────────────────────────────────────────────────
MARKET_OPEN = os.getenv("PT_MARKET_OPEN", "09:15")
MARKET_CLOSE = os.getenv("PT_MARKET_CLOSE", "15:30")
# The exchange squares off intraday positions before the close; brokers do it a little
# earlier so they are not the last one out. 15:20 equity / 15:25 F&O mirrors the usual
# Indian retail convention.
MIS_SQUAREOFF_EQUITY = os.getenv("PT_MIS_SQUAREOFF_EQUITY", "15:20")
MIS_SQUAREOFF_FNO = os.getenv("PT_MIS_SQUAREOFF_FNO", "15:25")

# Intraday leverage. A real broker's MIS multiplier varies per scrip and per day; there is
# no bulk feed for it, so one conservative flat figure is used and labelled rather than a
# per-stock number being invented.
MIS_LEVERAGE = float(os.getenv("PT_MIS_LEVERAGE", "5"))

DEFAULT_CAPITAL = float(os.getenv("PT_INITIAL_CAPITAL", "1000000"))  # ₹10 lakh


class OrderError(Exception):
    """A malformed request — rejected before it ever becomes an order."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> str:
    return now_ist().date().isoformat()


def _hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def is_trading_day(when: datetime | None = None) -> bool:
    return (when or now_ist()).weekday() < 5


def market_is_open(when: datetime | None = None) -> bool:
    when = when or now_ist()
    return is_trading_day(when) and _hhmm(MARKET_OPEN) <= when.time() <= _hhmm(MARKET_CLOSE)


def past_squareoff(segment: str, when: datetime | None = None) -> bool:
    when = when or now_ist()
    cutoff = MIS_SQUAREOFF_FNO if segment == SEGMENT_FNO else MIS_SQUAREOFF_EQUITY
    return is_trading_day(when) and when.time() >= _hhmm(cutoff)


# Products that survive the close. Everything else is flattened at the intraday cutoff.
OVERNIGHT_PRODUCTS = ("CNC", "MTF", "NRML")


def products_for(segment: str) -> tuple[str, ...]:
    return PRODUCTS_FNO if segment == SEGMENT_FNO else PRODUCTS_EQUITY


def validate_order(*, segment: str, transaction_type: str, order_type: str, product: str,
                   validity: str, quantity: int, price: float | None,
                   trigger_price: float | None) -> None:
    """Reject anything a broker's own front end would reject, with the same reasoning.

    These raise rather than producing a REJECTED order because they are malformed
    REQUESTS — a broker's UI never lets them be submitted. Rejections that belong in the
    order book (no margin, no quote) are raised later, by the engine, where they become
    records.
    """
    if segment not in SEGMENTS:
        raise OrderError(f"segment must be one of {SEGMENTS}")
    if transaction_type not in TRANSACTION_TYPES:
        raise OrderError("transaction_type must be BUY or SELL")
    if order_type not in ORDER_TYPES:
        raise OrderError(f"order_type must be one of {ORDER_TYPES}")
    if product not in products_for(segment):
        raise OrderError(f"product for {segment} must be one of {products_for(segment)}")
    if validity not in VALIDITIES:
        raise OrderError(f"validity must be one of {VALIDITIES}")
    if quantity < 1:
        raise OrderError("Quantity must be at least 1")

    if order_type in ("LIMIT", "SL") and not price:
        raise OrderError(f"{order_type} orders need a price")
    if order_type in ("SL", "SL-M") and not trigger_price:
        raise OrderError(f"{order_type} orders need a trigger price")
    if order_type == "MARKET" and price:
        raise OrderError("A MARKET order cannot carry a price")

    # NOTE: CNC and MTF cannot go short, but that is not checked here — it depends on what
    # the account actually holds, which this pure function cannot see. `orders.execute`
    # enforces it against the position book and the holdings.

    # A stop-loss that triggers on the wrong side of its own limit can never fill: a BUY
    # SL arms when price rises to the trigger, so its limit must sit at or above it.
    if order_type == "SL" and price and trigger_price:
        if transaction_type == "BUY" and price < trigger_price:
            raise OrderError(
                "A BUY stop-loss limit must be at or above its trigger price — below it the "
                "order arms and then can never fill")
        if transaction_type == "SELL" and price > trigger_price:
            raise OrderError(
                "A SELL stop-loss limit must be at or below its trigger price — above it the "
                "order arms and then can never fill")


def triggered(order: dict, ltp: float) -> bool:
    """Has this stop-loss order's trigger been touched?

    A BUY stop arms when price RISES to the trigger (you are stopping into a long, or out
    of a short); a SELL stop arms when price FALLS to it. Getting this backwards makes
    every stop fire instantly, which is the classic way a paper engine flatters itself.
    """
    trigger = order.get("trigger_price")
    if not trigger:
        return False
    return ltp >= trigger if order["transaction_type"] == "BUY" else ltp <= trigger


def marketable(order: dict, ltp: float) -> bool:
    """Would this order fill against the current price right now?"""
    order_type = order["order_type"]
    if order_type in ("MARKET", "SL-M"):
        return True
    price = order.get("price")
    if not price:
        return False
    return ltp <= price if order["transaction_type"] == "BUY" else ltp >= price


def fill_price_for(order: dict, ltp: float) -> float:
    """Where the order fills.

    MARKET and SL-M take the last traded price. A LIMIT that is marketable fills at the
    BETTER of its limit and the market — a buy limit at 100 with the stock at 98 fills at
    98, as it would in reality; filling at the limit would quietly hand the paper account
    money it never made.
    """
    if order["order_type"] in ("MARKET", "SL-M"):
        return ltp
    price = float(order["price"])
    return min(price, ltp) if order["transaction_type"] == "BUY" else max(price, ltp)


def fee_product(segment: str, product: str) -> str:
    """Map a broker product onto the Angel One equity fee schedule.

    MTF pays DELIVERY charges. It is funded delivery, not a leveraged intraday trade — the
    stock is actually bought and pledged, so it carries the 0.1%-both-legs STT and the DP
    charge. Billing it as intraday would understate an MTF round trip by roughly two thirds
    before the funding interest is even counted.
    """
    if segment == SEGMENT_FNO:
        return "INTRADAY"          # unused for F&O; option/future charges go their own way
    return "DELIVERY" if product in ("CNC", "MTF") else "INTRADAY"


def charges(*, segment: str, product: str, instrument_kind: str, entry: float, exit_price: float,
            quantity: int, lot_size: int = 1, side: str = "BUY") -> dict:
    """Round-trip charges for one position, on the real Angel One schedule.

    Equity and options are genuinely different schedules — an option pays a flat ₹20 per
    order and STT on premium, an equity delivery trade pays 0.1% STT on both legs plus a DP
    charge. Routing both through one formula is how a paper desk ends up under-charging the
    thing it trades most.
    """
    if segment == SEGMENT_FNO and instrument_kind == "OPTION":
        lots = max(1, quantity // max(1, lot_size))
        return option_round_trip(entry, exit_price, lots, lot_size).as_dict()
    return round_trip(entry, exit_price, quantity, side, fee_product(segment, product)).as_dict()


def margin_required(*, segment: str, product: str, price: float, quantity: int) -> float:
    """Cash a broker blocks to hold this equity position.

    F&O never uses this path — its margin comes from the SPAN-lite portfolio model, which
    has to see the whole basket to give the hedge benefit that makes a spread cheaper than
    a naked leg.
    """
    notional = price * quantity
    if segment == SEGMENT_FNO:
        return notional
    if product == "MIS":
        return notional / MIS_LEVERAGE
    # MTF never reaches here — its leverage is per-scrip and has to be looked up, which is
    # async, so orders.estimate_margin owns it. Falling through to full notional would
    # silently turn every MTF order into a CNC one.
    return notional      # CNC is fully paid
