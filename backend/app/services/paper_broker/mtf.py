"""MTF — Margin Trade Funding. The broker lends you most of a delivery purchase.

WHAT MTF ACTUALLY IS, because the charges only make sense once the mechanics do. You buy
₹1,00,000 of stock and put up ₹25,000; the broker funds the other ₹75,000. Three things
follow, and all three cost money:

  1. INTEREST accrues DAILY on the funded amount for as long as you hold. This is the whole
     product and it is the charge people forget. At ~0.05%/day, holding a ₹75,000 funded
     position for a month costs about ₹1,100 — which can quietly exceed the profit on a 2%
     move.
  2. The shares are PLEDGED to the broker as collateral, which carries a per-scrip fee on
     the way in and again on the way out.
  3. It is still DELIVERY, so it pays the delivery brokerage and STT schedule, not intraday.

A paper desk that models MTF as "CNC with leverage" gets the position size right and the
cost completely wrong — and since the entire appeal of MTF is holding leveraged positions
for weeks, the cost it omits is the one that decides whether the trade was any good.

────────────────────────────────────────────────────────────────────────────────────────
WHERE THE LEVERAGE NUMBERS COME FROM — READ THIS BEFORE TRUSTING THEM
────────────────────────────────────────────────────────────────────────────────────────
This app has NO Kotak Neo integration: no credentials, no API client, no endpoint. Kotak's
actual per-scrip MTF leverage list therefore cannot be fetched here, and inventing numbers
while calling them Kotak's would be worse than useless — you would size real positions off
a fiction.

So leverage resolves in this order, and every quote says which one it used:

  "dhan_live"  Dhan's /margincalculator with productType=MTF returns the real per-stock
               leverage a broker would apply. It is one call per instrument and needs a live
               Dhan token, so it is OFF by default (PT_MTF_LIVE_LEVERAGE=1 to enable).
  "rate_card"  A tiered table below, keyed on index membership — the same structure brokers
               use (SEBI Group I large caps get the most leverage, thin scrips the least).
               Every figure is env-overridable so it can be set to YOUR broker's actual card.
  "default"    The most conservative tier, for anything not in the universe.

The DEFAULTS below are typical published Indian retail MTF terms, not a quote from any
specific broker on any specific day. Rates move and are negotiable. Set the env vars to
your broker's real card before reading any of this as your cost.
"""

from __future__ import annotations

import logging
import os
from datetime import date

from app.core.db import stock_universe_collection

logger = logging.getLogger("paper_broker.mtf")

# ── the rate card ───────────────────────────────────────────────────────────────
# Leverage by index tier. Expressed as a multiplier: 4.0 means you fund 25% and the broker
# funds 75%. Brokers publish these as a margin PERCENTAGE; the reciprocal is used here
# because the order ticket asks "how much do I need", not "what fraction is mine".
MTF_LEVERAGE = {
    "nifty50": float(os.getenv("PT_MTF_LEV_N50", "4.0")),      # 25% margin
    "nifty100": float(os.getenv("PT_MTF_LEV_N100", "3.33")),   # 30%
    "nifty250": float(os.getenv("PT_MTF_LEV_N250", "2.86")),   # 35%
    "nifty500": float(os.getenv("PT_MTF_LEV_N500", "2.5")),    # 40%
}
MTF_LEVERAGE_DEFAULT = float(os.getenv("PT_MTF_LEV_DEFAULT", "2.0"))   # 50% for anything else

# Daily funding rate on the funded amount. 0.049%/day ~ 17.9% a year, which is the middle of
# the published Indian retail range. Promotional rates go far lower; set yours.
MTF_DAILY_RATE = float(os.getenv("PT_MTF_DAILY_RATE", "0.00049"))

# Per-scrip pledge fees. Charged once on the way in and once on the way out, plus GST.
MTF_PLEDGE_FEE = float(os.getenv("PT_MTF_PLEDGE_FEE", "30.0"))
MTF_UNPLEDGE_FEE = float(os.getenv("PT_MTF_UNPLEDGE_FEE", "30.0"))
GST_RATE = 0.18

# Live per-scrip leverage via Dhan's margin calculator. Off by default: it is one network
# call per instrument on the order ticket and needs a valid Dhan token.
LIVE_LEVERAGE = os.getenv("PT_MTF_LIVE_LEVERAGE", "0").lower() not in ("0", "false", "")

TIER_ORDER = ["nifty50", "nifty100", "nifty250", "nifty500"]


def annual_rate_pct() -> float:
    return round(MTF_DAILY_RATE * 365 * 100, 2)


async def leverage_for(symbol: str, *, security_id: str | None = None,
                       exchange_segment: str | None = None, quantity: int = 1,
                       price: float = 0.0) -> dict:
    """Leverage for one scrip, with the source named.

    Never raises and never guesses upward: every failure path falls to the most
    conservative tier, because over-stating leverage lets a paper account open a position a
    real broker would have refused.
    """
    if LIVE_LEVERAGE and security_id and exchange_segment and price > 0:
        live = await _dhan_leverage(security_id, exchange_segment, quantity, price)
        if live:
            return live

    doc = await stock_universe_collection.find_one(
        {"symbol": symbol.upper()}, {"_id": 0, "tightest_index": 1, "indices": 1})
    tier = (doc or {}).get("tightest_index")
    if tier in MTF_LEVERAGE:
        lev = MTF_LEVERAGE[tier]
        return {
            "leverage": lev,
            "margin_pct": round(100 / lev, 1),
            "source": "rate_card",
            "tier": tier,
            "note": (f"{tier} tier of the configured rate card — {round(100 / lev, 1)}% of the "
                     f"purchase is yours, the rest is funded. This is a configured table, "
                     f"NOT a live figure from your broker."),
        }
    return {
        "leverage": MTF_LEVERAGE_DEFAULT,
        "margin_pct": round(100 / MTF_LEVERAGE_DEFAULT, 1),
        "source": "default",
        "tier": None,
        "note": (f"{symbol.upper()} is not in the stored index universe, so the most "
                 f"conservative tier applies ({round(100 / MTF_LEVERAGE_DEFAULT, 1)}% margin). "
                 f"Many such scrips are not MTF-eligible at all with a real broker."),
    }


async def _dhan_leverage(security_id: str, exchange_segment: str, quantity: int,
                         price: float) -> dict | None:
    """Real per-stock MTF leverage from Dhan's margin calculator, when enabled.

    Dhan publishes no bulk MTF-eligibility list — the per-order calculator is the documented
    way to get it, one instrument at a time. Returns None on any failure so the caller falls
    back to the rate card rather than the whole ticket erroring.
    """
    try:
        from app.api.routes.broker import _get_dhan_client
        from app.api.deps import get_current_user
        from app.services.manual_positions import _parse_leverage

        user = await get_current_user()
        dhan = await _get_dhan_client(str(user["_id"]))
        body = await dhan.margin_calculator(
            security_id=security_id, exchange_segment=exchange_segment,
            transaction_type="BUY", quantity=quantity, product_type="MTF", price=price)
        lev = _parse_leverage((body.get("data") or body).get("leverage"))
        if lev and lev > 1:
            return {
                "leverage": lev,
                "margin_pct": round(100 / lev, 1),
                "source": "dhan_live",
                "tier": None,
                "note": ("Live from Dhan's margin calculator — the real leverage a broker "
                         "would apply to this scrip today."),
            }
    except Exception as exc:  # noqa: BLE001 — a leverage lookup must never break an order
        logger.info("MTF live leverage unavailable (%s) — falling back to the rate card", exc)
    return None


def funded_amount(notional: float, leverage: float) -> float:
    """The part the broker lends. Interest accrues on this, not on the whole position."""
    return round(max(0.0, notional - notional / max(leverage, 1.0)), 2)


def daily_interest(funded: float) -> float:
    return round(funded * MTF_DAILY_RATE, 2)


def interest_for_days(funded: float, days: int) -> float:
    """Simple daily interest. Brokers charge on calendar days held, weekends included —
    the money is lent over the weekend too."""
    return round(funded * MTF_DAILY_RATE * max(0, days), 2)


def days_held(opened_on: str, closed_on: str | None = None) -> int:
    """Calendar days the funding was outstanding, minimum 1.

    Minimum one because buying and selling the same day still borrows the money for a day —
    and a zero would let an intraday round trip on MTF look free, which it is not.
    """
    try:
        start = date.fromisoformat(opened_on)
        end = date.fromisoformat(closed_on) if closed_on else date.today()
    except (TypeError, ValueError):
        return 1
    return max(1, (end - start).days)


def pledge_charge() -> float:
    return round(MTF_PLEDGE_FEE * (1 + GST_RATE), 2)


def unpledge_charge() -> float:
    return round(MTF_UNPLEDGE_FEE * (1 + GST_RATE), 2)


def rate_card() -> dict:
    """The whole card, for the UI — including where the numbers came from."""
    return {
        "leverage_tiers": [
            {"tier": t, "leverage": MTF_LEVERAGE[t], "margin_pct": round(100 / MTF_LEVERAGE[t], 1)}
            for t in TIER_ORDER
        ],
        "default_leverage": MTF_LEVERAGE_DEFAULT,
        "default_margin_pct": round(100 / MTF_LEVERAGE_DEFAULT, 1),
        "daily_rate_pct": round(MTF_DAILY_RATE * 100, 4),
        "annual_rate_pct": annual_rate_pct(),
        "pledge_charge": pledge_charge(),
        "unpledge_charge": unpledge_charge(),
        "live_leverage_enabled": LIVE_LEVERAGE,
        "provenance": (
            "This app has NO Kotak Neo integration — no credentials, no API — so Kotak's "
            "actual per-scrip MTF leverage cannot be fetched here. These are TYPICAL "
            "published Indian retail MTF terms held in a configurable table, not a quote "
            "from any broker on any day. Every value is env-overridable "
            "(PT_MTF_LEV_*, PT_MTF_DAILY_RATE, PT_MTF_PLEDGE_FEE): set them to your "
            "broker's real card before treating these as your costs. Enabling "
            "PT_MTF_LIVE_LEVERAGE=1 sources real per-stock leverage from Dhan's margin "
            "calculator instead of the table."),
        "mechanics": (
            "You fund the margin percentage; the broker funds the rest and charges interest "
            "on THAT amount every calendar day you hold, weekends included. The shares are "
            "pledged as collateral, costing a fee in and out. MTF is delivery, so it pays "
            "the delivery brokerage and STT schedule too."),
    }
