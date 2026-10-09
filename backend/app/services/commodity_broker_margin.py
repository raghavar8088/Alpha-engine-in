"""MCX margin as the BROKER charges it, with a measured fallback when it cannot be asked.

WHY THIS EXISTS
---------------
The local SPAN-lite model was 8.2x too lenient on short MCX options, and the gap showed up
exactly where it does the most damage: the max-lots sizer. Measured on 2026-10-09 against
a Rs 66,000 account sizing a 1-lot CRUDEOILM 8750 short straddle:

    our model      Rs  7,347 per lot    ->  max_lots said 8
    Angel One      Rs 60,603 per lot    ->  the broker allows 1

Two faults compounded. The price-scan bands were calibrated for NIFTY and never
re-measured against MCX, and `portfolio_margin` credited the straddle Rs 69,181 of "hedge
benefit" that the broker does not give at all: asked for the two legs separately Angel
returns Rs 30,805 and Rs 29,694, and asked for them together it returns Rs 60,499 - the
exact sum. A short straddle is two short options to SPAN, not a hedge.

So this module asks Angel's own margin calculator, which reproduces the broker app:

    1-lot CRUDEOILM 8750 short straddle   this module Rs 60,499    the app Rs 60,603

WHAT THE BROKER'S ANSWER IS WORTH, AND WHERE IT IS NOT
------------------------------------------------------
All of the following was measured from the production box on 2026-10-09.

*   It is EXACTLY LINEAR in size. A CRUDEOILM straddle: 1 lot Rs 60,499, 3 lots
    Rs 1,81,496, 9 lots Rs 5,44,489 - 3.000x and 9.000x. SILVERMIC and GOLDM futures the
    same. That is what lets `max_lots` be one call and a division instead of a search.

*   It is ADDITIVE ACROSS LEGS, near enough. A straddle nets nothing. A vertical spread
    (short 8750 CE / long 8800 CE) returns Rs 30,242 against Rs 30,805 for the short leg
    alone - a benefit of Rs 563, 1.8%. Asking for the whole basket at once captures what
    little there is.

*   A LONG OPTION IS FREE. Rs 0, because the premium is paid up front. That is a real
    answer, which is the heart of the next problem.

*   THROTTLED, IT ANSWERS ZERO rather than 403. Unpaced bursts of ~35 calls came back 0
    for a third of them, scattered: GOLDM returned 0 at 1, 2, 3 and 5 lots and then
    Rs 1,37,545 for the same contract INTRADAY. Since 0 is also the true answer for a long
    option, a throttled reply cannot be told from a real one by shape alone - so it is
    told apart by whether the basket could possibly need no margin at all. Paced 1.5 s
    apart (see `margin_pacer`) the same questions were bit-stable over six repeats.

*   TWO FUTURES ARE WRONG AT THE SOURCE. CRUDEOILM and SILVER100 futures both return 1.3%
    of notional, stable over six paced repeats, against 7.4-31% for every other contract
    and against 35.2% for a CRUDEOILM option on the same underlying. Rs 1,105 to carry a
    Rs 87,550 crude position is not a figure to size a book on, however firmly Angel
    repeats it. Angel's own answers contradict each other there, so futures legs are
    floored against the measured rate below.

MEASURED_RATE is therefore not a guess refined into a model - it is what the broker
actually charged, contract by contract, on one day, kept so that the fallback is within a
few per cent instead of 8x out. Re-measure it with `scripts/measure_mcx_margin.py`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from app.services.angel_client import angel_client

logger = logging.getLogger("commodity_broker_margin")

__all__ = ["basket_margin", "MEASURED_RATE", "SHORT_OPTION_FACTOR", "measured_rate",
           "fallback_margin", "margin_cache_stats", "invalidate_margin_cache"]

# Broker margin as a fraction of ONE LOT'S NOTIONAL, per commodity family, for a FUTURES
# leg. Measured against Angel's calculator on 2026-10-09 at the front-month contract.
# Keyed by family (see SCAN_FAMILY in commodity_positions) so a mini inherits its parent's
# rate: a mini is the same commodity in a smaller wrapper and carries the same percentage.
MEASURED_RATE: dict[str, float] = {
    "GOLD": 0.092,          # GOLD, GOLDM, GOLDTEN, GOLDGUINEA, GOLDPETAL all 9.2%
    "SILVER": 0.127,        # SILVER 12.7%, SILVERM and SILVERMIC 12.6%
    "CRUDEOIL": 0.311,      # the parent; CRUDEOILM's own figure is the broken one
    "NATURALGAS": 0.167,    # NATURALGAS and NATGASMINI both 16.7%
    "COPPER": 0.092,
    "ZINC": 0.091,
    "ALUMINIUM": 0.093,
    "LEAD": 0.074,
    "NICKEL": 0.093,
    "CARDAMOM": 0.132,
    "COTTON": 0.093,
    "MENTHAOIL": 0.113,
    "STEELREBAR": 0.099,
    "ELECDMBL": 0.310,
}

# Above the measured futures rate for the same commodity, every short option came in
# between 1.13x and 1.19x of it: NATGAS 19.0/16.7, CRUDEOIL 35.2/31.1, COPPER 10.5/9.2,
# GOLDM 10.8/9.2, ZINC 10.7/9.1, SILVERM 14.8/12.6, GOLD 10.9/9.2, SILVER 15.2/12.7.
# Rounded UP past the top of that range, so the fallback errs expensive - the direction
# that refuses a trade rather than allowing one the account cannot carry. (It was first
# set to 1.15 from a narrower sample; re-measuring the full board put the top at 1.19,
# which is the whole reason `scripts/measure_mcx_margin.py` prints this range.)
SHORT_OPTION_FACTOR = float(os.getenv("COMMODITY_SHORT_OPTION_FACTOR", "1.20"))

# For an underlying with no measured rate: above all but crude and power. A contract nobody
# has measured should cost more to carry than one that has been, not less.
DEFAULT_RATE = float(os.getenv("COMMODITY_DEFAULT_MARGIN_RATE", "0.15"))

# A FUTURES answer below this fraction of the measured rate is not believed - it is the
# CRUDEOILM/SILVER100 defect, which sits at about a seventh of its family's rate. Options
# are not floored this way: a far out-of-the-money short legitimately carries little
# margin, and the broker's option figures reproduced the app exactly.
FUTURES_FLOOR_FRACTION = float(os.getenv("COMMODITY_FUTURES_FLOOR_FRACTION", "0.5"))

# How long a broker margin figure is reused. SPAN files are published a few times a day and
# the figure moved by Rs 0.25 across five paced repeats, so minutes are safe; the TTL is
# really about not spending the endpoint's tiny budget on one page load.
CACHE_TTL_S = float(os.getenv("COMMODITY_MARGIN_CACHE_TTL", "300"))
ENABLED = os.getenv("COMMODITY_BROKER_MARGIN", "1") not in ("0", "false", "False")

_CACHE: dict[tuple, tuple[float, float, str]] = {}      # key -> (ts, margin, source)
_STATS = {"calls": 0, "hits": 0, "misses": 0, "rejected_zero": 0,
          "rejected_floor": 0, "errors": 0, "unmapped": 0}


def measured_rate(family: str) -> float:
    return MEASURED_RATE.get((family or "").upper(), DEFAULT_RATE)


# --------------------------------------------------------------------------------
# The leg shape this module speaks
# --------------------------------------------------------------------------------
# Every function here takes legs of the form
#
#   {"symbol":   "CRUDEOILM",       the underlying
#    "family":   "CRUDEOIL",        commodity family, for the measured rate
#    "kind":     "OPTION"|"FUTURE",
#    "side":     "BUY"|"SELL",
#    "lots":     int,
#    "notional": float,             ONE lot's notional in rupees (strike x multiplier for
#                                   an option, price x multiplier for a future)
#    "token":    str|None,          Angel's instrument token
#    "order_qty": int|None,         Angel's ORDER quantity for one lot (its `lotsize`),
#                                   which on MCX is NOT the value multiplier
#    "product":  "MARGIN"|"INTRADAY"}
#
# `order_qty` and `notional` are deliberately separate. GOLD trades in lots of 1 while one
# lot is worth 100x the quoted 10-gram price; sending the value multiplier as the quantity
# asks the broker about a position 100x the size.


def _needs_margin(legs: list[dict]) -> bool:
    """Could this basket possibly cost nothing to carry?

    Only if every leg is a BOUGHT option - those are paid for in premium and margined at
    zero. Any future, either way round, and any sold option, must cost something. This is
    the test that tells a throttled zero from a true one."""
    return any(leg["kind"] != "OPTION" or leg["side"] == "SELL" for leg in legs)


def _angel_positions(legs: list[dict], lots: int) -> list[dict] | None:
    """The request body, or None if any leg has no Angel mapping.

    All-or-nothing on purpose: a basket priced from a mix of broker figures and local
    estimates is neither, and would be reported as the broker's."""
    out = []
    for leg in legs:
        if not leg.get("token") or not leg.get("order_qty"):
            return None
        out.append({
            "exchange": "MCX",
            "qty": int(leg["order_qty"]) * int(lots) * int(leg.get("lots") or 1),
            # Zero, not the premium. Angel prices the contract from its own SPAN file; the
            # figure it returned this way is the one the broker app shows.
            "price": 0,
            "productType": ("INTRADAY" if leg.get("product") == "INTRADAY"
                            else "CARRYFORWARD"),
            "token": str(leg["token"]),
            "tradeType": "SELL" if leg["side"] == "SELL" else "BUY",
            # Not optional, whatever the docs imply: without it the call is rejected
            # outright with "Order type is required".
            "orderType": "MARKET",
        })
    return out


def _cache_key(legs: list[dict], lots: int) -> tuple:
    return (lots, tuple(sorted(
        (str(leg.get("token")), leg["side"], str(leg.get("product") or "MARGIN"),
         int(leg.get("lots") or 1)) for leg in legs)))


# --------------------------------------------------------------------------------
# The calibrated local fallback
# --------------------------------------------------------------------------------


def fallback_margin(legs: list[dict], lots: int = 1) -> float:
    """What the measured rates say this basket costs. No network, no scenario walk.

    Additive across legs and linear in size, which is what the broker was measured to be -
    so this is the same SHAPE as the real thing, differing only in that its rate is one
    day's measurement rather than today's SPAN file. It deliberately gives no netting
    benefit, because the broker gives 0% on a straddle and 1.8% on a vertical."""
    total = 0.0
    for leg in legs:
        n = int(lots) * int(leg.get("lots") or 1)
        if leg["kind"] == "OPTION" and leg["side"] == "BUY":
            continue                      # paid for in premium; margined at zero
        rate = measured_rate(leg.get("family") or leg.get("symbol") or "")
        if leg["kind"] == "OPTION":
            rate *= SHORT_OPTION_FACTOR
        total += rate * float(leg.get("notional") or 0.0) * n
    return round(total, 2)


# --------------------------------------------------------------------------------
# The broker's answer
# --------------------------------------------------------------------------------


async def basket_margin(legs: list[dict], lots: int = 1) -> tuple[float, str, str]:
    """(margin, source, note) for this basket at `lots` lots per leg.

    `source` is one of "angel", "measured" or "measured:<why the broker's was not used>",
    and is meant to be shown: a number whose provenance is not on the screen gets trusted
    exactly as much as one that is, which is how the 8x-light figure survived.

    Never raises. Margin is in the path of every order gate on this desk, and a broker
    outage must not be the reason a book cannot be sized."""
    if not legs:
        return 0.0, "measured", "nothing to margin"
    lots = max(int(lots), 1)
    local = fallback_margin(legs, lots)

    if not ENABLED:
        return local, "measured", "broker margin disabled by configuration"
    if not _needs_margin(legs):
        # Every leg is a bought option. Zero is the true answer and needs no round trip.
        return 0.0, "angel", "bought options are paid for in premium, not margined"

    key = _cache_key(legs, lots)
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        _STATS["hits"] += 1
        return hit[1], hit[2], "Angel One margin calculator (cached)"
    _STATS["misses"] += 1

    positions = _angel_positions(legs, lots)
    if positions is None:
        _STATS["unmapped"] += 1
        return local, "measured:unmapped", (
            "at least one leg has no Angel token, so the broker could not be asked about "
            "the basket as a whole")

    try:
        _STATS["calls"] += 1
        got = await angel_client.margin_batch(positions)
    except asyncio.CancelledError:
        raise                       # a cancelled request is not a broker failure
    except Exception as exc:
        # DELIBERATELY EVERYTHING. This function sits in the path of every order gate on
        # the desk and promises not to raise, and a correct fallback is always in hand, so
        # there is no exception here worth turning into a book that cannot be sized. It
        # was first written to catch AngelAPIError/TimeoutError/OSError, which is the list
        # of failures someone thought of — a stubbed RuntimeError walked straight through
        # it and out through the gate.
        _STATS["errors"] += 1
        logger.warning("[commodity_broker_margin] Angel margin call failed (%s: %s) - "
                       "using the measured rate instead", type(exc).__name__, exc)
        return local, "measured:broker-unavailable", f"Angel margin call failed: {exc}"

    reason = _implausible(got, legs, local)
    if reason:
        return local, f"measured:{reason[0]}", reason[1]

    _CACHE[key] = (time.monotonic(), round(got, 2), "angel")
    if len(_CACHE) > 512:                 # bounded; a desk sizes a handful of shapes
        for k, _v in sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:128]:
            _CACHE.pop(k, None)
    return round(got, 2), "angel", "Angel One margin calculator"


def _implausible(got: float, legs: list[dict], local: float) -> tuple[str, str] | None:
    """Is the broker's number one we are willing to size a book on?

    Two refusals, both aimed only at the dangerous direction - a margin too SMALL. A figure
    that comes back too large is merely conservative and is passed straight through."""
    if got <= 0.0:
        # It cannot be zero: something here is a future or a sold option. This is the
        # throttle answering 200 OK with an empty body.
        _STATS["rejected_zero"] += 1
        logger.warning("[commodity_broker_margin] Angel returned zero margin for a basket "
                       "that must need some (%d legs) - treating it as throttled",
                       len(legs))
        return ("throttled",
                "Angel returned zero margin for a basket containing a future or a sold "
                "option, which cannot be free - its throttled replies look exactly like "
                "this, so the measured rate was used instead")
    if all(leg["kind"] != "OPTION" for leg in legs) and got < local * FUTURES_FLOOR_FRACTION:
        # CRUDEOILM and SILVER100 futures, measured 2026-10-09: 1.3% of notional, against
        # 7.4-31% everywhere else and 35.2% for an option on the same underlying. Stable
        # across six paced repeats, so it is Angel's own data and not the wire.
        _STATS["rejected_floor"] += 1
        logger.warning("[commodity_broker_margin] Angel quoted Rs %.0f for a futures "
                       "basket the measured rate puts at Rs %.0f - below the floor, using "
                       "the measured rate", got, local)
        return ("below-floor",
                f"Angel quoted ₹{got:,.0f} where the rate measured on this "
                f"contract's own family implies ₹{local:,.0f}. Two MCX futures "
                f"(CRUDEOILM, SILVER100) return about a seventh of their family's rate "
                f"and contradict Angel's own option figures on the same underlying, so "
                f"the measured rate was used instead.")
    return None


def margin_cache_stats() -> dict:
    return {**_STATS, "cached_shapes": len(_CACHE), "ttl_s": CACHE_TTL_S,
            "enabled": ENABLED}


def invalidate_margin_cache() -> None:
    _CACHE.clear()
