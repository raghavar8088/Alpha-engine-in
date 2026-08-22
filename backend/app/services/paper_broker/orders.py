"""The order lifecycle — the part that makes this a broker rather than a position list.

AN ORDER IS A RECORD FROM THE MOMENT IT IS ACCEPTED. It moves
PENDING / TRIGGER_PENDING -> COMPLETE | CANCELLED | REJECTED | EXPIRED and every state is
kept. That matters more than it sounds: the orders that never filled are the ones that
explain a strategy's real behaviour — the stops that armed and missed, the limits that
expired unfilled, the entries the account could not afford. A desk that only records fills
shows a strategy that always had money and always got its price.

REJECTIONS ARE RECORDED, NOT RAISED. Running out of margin produces a REJECTED order with a
reason, exactly as a broker does. Only malformed requests raise — those are the ones a
broker's own front end would refuse to submit.

POSITION SEMANTICS follow the product:
  CNC   delivery. Cannot short: a sell is only allowed against stock you hold or bought
        today. Unsold buys settle into Holdings overnight.
  MIS   intraday, either direction, force-closed at the exchange cutoff.
  NRML  F&O overnight, either direction, carries to expiry.

A SELL that exceeds a long position does NOT silently become a short. It closes what is
there and rejects the excess, because a fat-fingered quantity turning a exit into a
reversed position is the single most expensive accident in this shape of code.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from app.core.db import (
    pt_holdings_collection,
    pt_orders_collection,
    pt_positions_collection,
    pt_trades_collection,
)
from app.services.fno_margin import portfolio_margin, solve_iv
from app.services.paper_broker import accounts, market, mtf
from app.services.paper_broker.core import (
    MIS_LEVERAGE,
    OPEN_STATUSES,
    SEGMENT_EQUITY,
    SEGMENT_FNO,
    OrderError,
    charges,
    fill_price_for,
    margin_required,
    marketable,
    now_utc,
    today_ist,
    triggered,
    validate_order,
)

logger = logging.getLogger("paper_broker.orders")


def _pos_key(account_id: str, contract: dict, product: str) -> dict:
    return {
        "account_id": account_id,
        "token": contract["angel_token"],
        "product": product,
        "status": "OPEN",
    }


async def _years_to_expiry(expiry: str | None) -> float:
    from datetime import date
    if not expiry:
        return 0.02
    try:
        d = date.fromisoformat(expiry)
    except ValueError:
        return 0.02
    days = max((d - date.today()).days, 0)
    return max(days / 365.0, 1 / 365.0)


async def estimate_margin(*, account_id: str, segment: str, contract: dict,
                          transaction_type: str, quantity: int, price: float,
                          product: str) -> dict:
    """What this order would block. Shown on the ticket before it is placed.

    Equity is a flat notional-or-leverage calculation. F&O goes through the same SPAN-lite
    portfolio model the F&O Positions desk uses, evaluated on the basket this order would
    CREATE — so a short strangle's second leg costs less than its first, and a spread costs
    a fraction of a naked leg, which is the whole reason the model exists.
    """
    if segment == SEGMENT_EQUITY and product == "MTF":
        # MTF leverage is per SCRIP, not per product — a Nifty 50 name is funded far more
        # generously than a smallcap, and the difference is the whole reason the rate card
        # exists. See paper_broker.mtf for where these numbers come from and do not.
        lev = await mtf.leverage_for(
            contract["symbol"], security_id=contract.get("security_id"),
            exchange_segment=contract.get("exchange_segment"),
            quantity=quantity, price=price)
        notional = price * quantity
        own = round(notional / lev["leverage"], 2)
        funded = mtf.funded_amount(notional, lev["leverage"])
        return {
            "margin": own,
            "method": f"MTF {lev['margin_pct']:g}% ({lev['source']})",
            "basis": (f"Of {notional:,.2f}, you fund {own:,.2f} and the broker funds "
                      f"{funded:,.2f} at {mtf.MTF_DAILY_RATE * 100:.4f}%/day "
                      f"({mtf.annual_rate_pct():g}% a year) — about "
                      f"{mtf.daily_interest(funded):,.2f} every calendar day you hold, plus "
                      f"{mtf.pledge_charge():,.2f} to pledge and {mtf.unpledge_charge():,.2f} "
                      f"to unpledge. {lev['note']}"),
            "span": None, "exposure": None,
            "mtf": {
                "leverage": lev["leverage"], "margin_pct": lev["margin_pct"],
                "source": lev["source"], "tier": lev.get("tier"),
                "funded_amount": funded,
                "daily_interest": mtf.daily_interest(funded),
                "daily_rate_pct": round(mtf.MTF_DAILY_RATE * 100, 4),
                "annual_rate_pct": mtf.annual_rate_pct(),
                "pledge_charge": mtf.pledge_charge(),
                "unpledge_charge": mtf.unpledge_charge(),
            },
        }

    if segment == SEGMENT_EQUITY:
        m = margin_required(segment=segment, product=product, price=price, quantity=quantity)
        cnc = product == "CNC"
        return {
            "margin": round(m, 2),
            "method": "notional" if cnc else f"notional / {MIS_LEVERAGE:g}",
            "basis": (f"Full notional ({price:,.2f} x {quantity}) — CNC is fully paid delivery"
                      if cnc else
                      f"Notional {price * quantity:,.2f} divided by the {MIS_LEVERAGE:g}x "
                      f"intraday multiplier. One flat figure, because a real broker's MIS "
                      f"leverage varies per scrip and per day and there is no bulk feed for it."),
            "span": None, "exposure": None}

    # Long options are paid for in full and block nothing beyond the premium.
    if contract["kind"] == "OPTION" and transaction_type == "BUY":
        return {"margin": round(price * quantity, 2), "method": "premium",
                "basis": "A long option is paid for in full; its loss is capped at the premium",
                "span": None, "exposure": None}

    underlying = contract.get("underlying") or contract["symbol"]
    spot = await _underlying_spot(underlying, contract)
    if not spot:
        # No spot means no scenario scan, so fall back to notional and SAY so rather than
        # returning a confident number the model did not produce.
        notional = price * quantity
        return {"margin": round(notional, 2), "method": "notional-fallback",
                "basis": (f"Could not price {underlying} spot, so the SPAN model could not "
                          f"run — blocking full notional instead of guessing"),
                "span": None, "exposure": None}

    existing = [p async for p in pt_positions_collection.find(
        {"account_id": account_id, "segment": SEGMENT_FNO, "status": "OPEN",
         "underlying": underlying})]

    legs = [{
        "kind": p.get("kind", "OPTION"), "option_type": p.get("option_type"),
        "strike": p.get("strike"), "qty": abs(p["quantity"]), "premium": p["avg_price"],
        "side": "BUY" if p["quantity"] > 0 else "SELL", "iv": p.get("iv"),
    } for p in existing]

    t = await _years_to_expiry(contract.get("expiry"))
    iv = None
    if contract["kind"] == "OPTION" and contract.get("strike"):
        try:
            iv = solve_iv(price, spot, float(contract["strike"]), t,
                          str(contract["option_type"]).upper())
        except Exception:  # noqa: BLE001 — an un-solvable IV must not block an order ticket
            iv = None

    before = portfolio_margin(legs, spot, t)["total"] if legs else 0.0
    legs.append({
        "kind": contract["kind"], "option_type": contract.get("option_type"),
        "strike": contract.get("strike"), "qty": quantity, "premium": price,
        "side": transaction_type, "iv": iv,
    })
    after = portfolio_margin(legs, spot, t)
    # The INCREMENTAL cost of adding this leg — never below zero, because a hedge that
    # reduces portfolio margin does not hand cash back at order time.
    delta = max(0.0, after["total"] - before)
    return {
        "margin": round(delta, 2),
        "method": "span-lite portfolio",
        "basis": (f"Portfolio margin rises from {before:,.0f} to {after['total']:,.0f} when "
                  f"this leg is added. SPAN-lite scenario model, not the exchange's own number."),
        "span": round(after.get("span", 0), 2),
        "exposure": round(after.get("exposure", 0), 2),
        "iv": round(iv, 4) if iv else None,
    }


async def _underlying_spot(underlying: str, contract: dict) -> float | None:
    try:
        under = await market.resolve_equity(underlying)
    except OrderError:
        from app.core.db import instruments_collection
        doc = await instruments_collection.find_one(
            {"symbol": underlying.upper(), "angel_token": {"$ne": None}})
        if doc is None:
            return None
        under = market.to_contract(doc)
    return await market.quote_one(under)


# ── placing ─────────────────────────────────────────────────────────────────────


async def place(*, account_id: str, segment: str, contract: dict, transaction_type: str,
                quantity: int, order_type: str = "MARKET", product: str = "MIS",
                validity: str = "DAY", price: float | None = None,
                trigger_price: float | None = None) -> dict:
    """Accept an order. It fills now, rests, or is rejected — all three are records."""
    await accounts.get(account_id)
    validate_order(segment=segment, transaction_type=transaction_type, order_type=order_type,
                   product=product, validity=validity, quantity=quantity, price=price,
                   trigger_price=trigger_price)

    lot = int(contract.get("lot_size") or 1)
    if segment == SEGMENT_FNO and quantity % lot:
        raise OrderError(
            f"F&O quantity must be a whole number of lots — {contract['symbol']} trades in "
            f"lots of {lot}, so {quantity} is not valid")

    order = {
        "order_id": f"PT-{uuid4().hex[:12]}",
        "account_id": account_id,
        "segment": segment,
        "contract": contract,
        "symbol": contract["symbol"],
        "token": contract["angel_token"],
        "transaction_type": transaction_type,
        "quantity": quantity,
        "filled_quantity": 0,
        "order_type": order_type,
        "product": product,
        "validity": validity,
        "price": float(price) if price else None,
        "trigger_price": float(trigger_price) if trigger_price else None,
        "status": "PENDING",
        "status_message": None,
        "margin_blocked": 0.0,
        "placed_at": now_utc(),
        "placed_on": today_ist(),
        "updated_at": now_utc(),
        "ts": now_utc(),
    }

    ltp = await market.quote_one(contract)
    if ltp is None:
        return await _reject(order, "No live Angel One quote for this contract — the order "
                                    "cannot be priced, so it is not accepted")

    order["ltp_at_placement"] = ltp

    # A stop-loss order rests as TRIGGER_PENDING until its trigger is touched. Only then
    # does it become a live LIMIT or MARKET order.
    if order_type in ("SL", "SL-M") and not triggered(order, ltp):
        order["status"] = "TRIGGER_PENDING"
        await pt_orders_collection.insert_one(dict(order))
        order.pop("_id", None)
        return order

    if not marketable(order, ltp):
        # IOC means immediate-or-cancel: it never rests. Letting it sit as PENDING would
        # turn every IOC into a day order, which is the opposite of what the user asked for.
        if validity == "IOC":
            order["status"] = "CANCELLED"
            order["status_message"] = (
                f"IOC not executable — market is {ltp} against a {order_type.lower()} "
                f"at {price}. Cancelled rather than rested.")
            await pt_orders_collection.insert_one(dict(order))
            order.pop("_id", None)
            return order
        order["status"] = "PENDING"
        await pt_orders_collection.insert_one(dict(order))
        order.pop("_id", None)
        return order

    return await execute(order, ltp)


async def _reject(order: dict, reason: str) -> dict:
    order = {**order, "status": "REJECTED", "status_message": reason,
             "margin_blocked": 0.0, "updated_at": now_utc()}
    await pt_orders_collection.replace_one({"order_id": order["order_id"]}, dict(order),
                                           upsert=True)
    order.pop("_id", None)
    logger.info("paper broker: rejected %s %s — %s", order["symbol"], order["order_id"], reason)
    return order


async def execute(order: dict, ltp: float) -> dict:
    """Fill an order against the current price, moving position, cash and ledger together."""
    fill = fill_price_for(order, ltp)
    if fill <= 0:
        return await _reject(order, "Fill price resolved to zero — refusing to book a trade "
                                    "at a price the market never showed")

    contract = order["contract"]
    account_id, segment, product = order["account_id"], order["segment"], order["product"]
    qty = order["quantity"]
    side = order["transaction_type"]

    existing = await pt_positions_collection.find_one(_pos_key(account_id, contract, product))
    signed_existing = int(existing["quantity"]) if existing else 0

    closing_qty = 0
    if signed_existing and ((signed_existing > 0) != (side == "BUY")):
        closing_qty = min(qty, abs(signed_existing))
    opening_qty = qty - closing_qty

    # CNC cannot go short. A sell first reduces today's unsettled CNC position, then sells
    # from settled HOLDINGS, and anything left over is refused — it is never allowed to
    # reverse into a short.
    #
    # These are two DIFFERENT books and must not be conflated: the day position realises
    # against `existing.avg_price`, while holdings realise against their own settled
    # average. An earlier version added the holdings quantity into `closing_qty` and also
    # reduced holdings, which booked the same shares twice — once against a day position
    # that did not hold them and once against the holding.
    holdings_sell_qty = 0
    if segment == SEGMENT_EQUITY and product == "MTF" and side == "SELL" and opening_qty > 0:
        # MTF is funded delivery. You cannot short stock the broker just lent you the money
        # to buy — a sell only ever closes an MTF position.
        if closing_qty == 0:
            return await _reject(
                order,
                "MTF is funded delivery — a sell can only close an existing MTF position, "
                f"and you have none open in {contract['symbol']}. Use MIS to go short intraday.")
        qty = closing_qty
        opening_qty = 0
        order = {**order, "quantity": qty,
                 "status_message": "Quantity capped at the open MTF position — MTF cannot short"}

    if segment == SEGMENT_EQUITY and product == "CNC" and side == "SELL" and opening_qty > 0:
        held = await _holdings_qty(account_id, contract["angel_token"])
        holdings_sell_qty = min(opening_qty, max(0, held))
        if holdings_sell_qty < opening_qty:
            if closing_qty == 0 and holdings_sell_qty == 0:
                return await _reject(
                    order,
                    "CNC is delivery — you can only sell stock you actually hold. You hold "
                    f"{held} of {contract['symbol']}. Use MIS to go short intraday.")
            qty = closing_qty + holdings_sell_qty
            order = {**order, "quantity": qty,
                     "status_message": (
                         f"Partially filled — capped at what you actually hold "
                         f"({closing_qty} from today's position, {holdings_sell_qty} from holdings)")}
        # Never open a short leg on CNC.
        opening_qty = 0

    margin = 0.0
    if opening_qty > 0:
        est = await estimate_margin(account_id=account_id, segment=segment, contract=contract,
                                    transaction_type=side, quantity=opening_qty,
                                    price=fill, product=product)
        margin = est["margin"]
        ok, why = await accounts.can_afford(account_id, margin)
        if not ok:
            return await _reject(order, why)

    # Opening an MTF leg pledges the stock, which costs money on the way in.
    mtf_open_meta: dict | None = None
    if opening_qty > 0 and product == "MTF" and segment == SEGMENT_EQUITY:
        lev = await mtf.leverage_for(
            contract["symbol"], security_id=contract.get("security_id"),
            exchange_segment=contract.get("exchange_segment"),
            quantity=opening_qty, price=fill)
        notional = fill * opening_qty
        mtf_open_meta = {
            "leverage": lev["leverage"],
            "margin_pct": lev["margin_pct"],
            "leverage_source": lev["source"],
            "funded": mtf.funded_amount(notional, lev["leverage"]),
            "pledge_charge": mtf.pledge_charge(),
        }

    realised = 0.0
    fees_total = 0.0
    mtf_cost: dict | None = None
    statutory_breakdown: dict | None = None
    gross_for_breakdown = 0.0
    statutory = 0.0
    if closing_qty > 0 and existing:
        entry = float(existing["avg_price"])
        direction = 1 if signed_existing > 0 else -1
        gross = (fill - entry) * closing_qty * direction
        fee = charges(segment=segment, product=product, instrument_kind=contract["kind"],
                      entry=entry, exit_price=fill, quantity=closing_qty,
                      lot_size=contract.get("lot_size", 1),
                      side="BUY" if direction > 0 else "SELL")
        fees_total = float(fee["total"])
        statutory_breakdown = fee
        gross_for_breakdown = gross
        realised = round(gross - fees_total, 2)

        # MTF's real cost lands here. Interest has been running every calendar day the
        # funding was outstanding, and closing means unpledging the shares. Neither shows up
        # in the statutory charge schedule, and together they routinely exceed it — on a
        # month-held position the funding alone can dwarf every other line.
        if existing.get("product") == "MTF":
            share = closing_qty / abs(signed_existing)
            funded_closed = round(float(existing.get("mtf_funded") or 0) * share, 2)
            held = mtf.days_held(existing.get("opened_on"), today_ist())
            interest = mtf.interest_for_days(funded_closed, held)
            unpledge = mtf.unpledge_charge()
            mtf_cost = {
                "days_held": held,
                "funded_amount": funded_closed,
                "daily_rate_pct": round(mtf.MTF_DAILY_RATE * 100, 4),
                "annual_rate_pct": mtf.annual_rate_pct(),
                "interest": interest,
                "pledge_charge": round(float(existing.get("mtf_pledge_charge") or 0) * share, 2),
                "unpledge_charge": unpledge,
                "leverage": existing.get("mtf_leverage"),
                "leverage_source": existing.get("mtf_leverage_source"),
                "total": round(interest + unpledge
                               + float(existing.get("mtf_pledge_charge") or 0) * share, 2),
            }
            fees_total += mtf_cost["total"]
            realised = round(gross - fees_total, 2)
            await accounts.ledger(
                account_id, "CHARGES", -interest,
                f"MTF funding interest on {contract['symbol']} — {funded_closed:,.2f} funded "
                f"for {held} day(s)", order["order_id"])
            await accounts.ledger(account_id, "CHARGES", -unpledge,
                                  f"Unpledge charge on {contract['symbol']}", order["order_id"])

        released = float(existing.get("margin_blocked") or 0) * (closing_qty / abs(signed_existing))
        remaining = signed_existing + (closing_qty if side == "BUY" else -closing_qty)

        if remaining == 0:
            await pt_positions_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {"status": "CLOSED", "closed_at": now_utc(), "closed_on": today_ist(),
                          "exit_price": fill, "realised_pnl": round(
                              float(existing.get("realised_pnl") or 0) + realised, 2),
                          "margin_blocked": 0.0, "updated_at": now_utc()}})
        else:
            partial = {"quantity": remaining,
                       "margin_blocked": round(float(existing.get("margin_blocked") or 0) - released, 2),
                       "realised_pnl": round(float(existing.get("realised_pnl") or 0) + realised, 2),
                       "updated_at": now_utc()}
            if mtf_cost:
                # The funding on the SOLD portion has been repaid, so it must come off the
                # position. Leaving it whole would charge interest on the full original
                # borrowing again on the next partial close — the same money billed twice.
                keep = 1 - (closing_qty / abs(signed_existing))
                partial["mtf_funded"] = round(float(existing.get("mtf_funded") or 0) * keep, 2)
                partial["mtf_pledge_charge"] = round(
                    float(existing.get("mtf_pledge_charge") or 0) * keep, 2)
                partial["mtf_interest_accrued"] = round(
                    float(existing.get("mtf_interest_accrued") or 0) * keep, 2)
            await pt_positions_collection.update_one({"_id": existing["_id"]}, {"$set": partial})

        await accounts.ledger(account_id, "REALISED", gross,
                              f"Closed {closing_qty} {contract['symbol']} @ {fill}",
                              order["order_id"])
        statutory = round(fees_total - (mtf_cost["total"] if mtf_cost else 0.0), 2)
        await accounts.ledger(account_id, "CHARGES", -statutory,
                              f"Charges on {contract['symbol']}", order["order_id"])
        await accounts.ledger(account_id, "MARGIN_RELEASE", released,
                              f"Margin released on {contract['symbol']}", order["order_id"])

    # Settled stock sold out of Holdings — its own book, its own average, its own charges.
    if holdings_sell_qty > 0:
        realised += await _reduce_holdings(account_id, contract, holdings_sell_qty, fill, order)

    if opening_qty > 0:
        await _open_or_add(account_id, segment, contract, product, side, opening_qty,
                           fill, margin, order, mtf_open_meta)
        if mtf_open_meta:
            await accounts.ledger(
                account_id, "CHARGES", -mtf_open_meta["pledge_charge"],
                f"Pledge charge on {contract['symbol']} (MTF)", order["order_id"])
        await accounts.ledger(account_id, "MARGIN_BLOCK", -margin,
                              f"Margin blocked for {opening_qty} {contract['symbol']}",
                              order["order_id"])

    trade = {
        "trade_id": f"T-{uuid4().hex[:12]}",
        "order_id": order["order_id"],
        "account_id": account_id,
        "segment": segment,
        "symbol": contract["symbol"],
        "contract": contract,
        "transaction_type": side,
        "quantity": qty,
        "price": round(fill, 2),
        "product": product,
        "order_type": order["order_type"],
        "value": round(fill * qty, 2),
        "realised_pnl": realised,
        "charges": round(fees_total, 2),
        # The whole cost of the round trip, itemised. This is what the closed-position view
        # renders: a single "charges" number cannot tell you whether a losing MTF trade lost
        # on the market or on the funding.
        "charge_breakdown": {
            "gross_pnl": round(gross_for_breakdown, 2),
            "statutory": statutory_breakdown,
            "mtf": mtf_cost,
            "total_charges": round(fees_total, 2),
            "net_pnl": realised,
        } if closing_qty > 0 else None,
        "traded_at": now_utc(),
        "traded_on": today_ist(),
        "ts": now_utc(),
    }
    await pt_trades_collection.insert_one(dict(trade))
    trade.pop("_id", None)

    order = {**order, "status": "COMPLETE", "filled_quantity": qty,
             "fill_price": round(fill, 2), "filled_at": now_utc(),
             "margin_blocked": 0.0, "updated_at": now_utc()}
    await pt_orders_collection.replace_one({"order_id": order["order_id"]}, dict(order),
                                           upsert=True)
    order.pop("_id", None)
    logger.info("paper broker: filled %s %s x%s @ %.2f (%s)",
                side, contract["symbol"], qty, fill, product)
    return {**order, "trade": trade}


async def _open_or_add(account_id, segment, contract, product, side, qty, fill, margin, order,
                       mtf_meta: dict | None = None):
    """Open a new position or average into an existing one on the same side."""
    signed = qty if side == "BUY" else -qty
    existing = await pt_positions_collection.find_one(_pos_key(account_id, contract, product))
    if existing:
        old_qty = int(existing["quantity"])
        new_qty = old_qty + signed
        # Averaging is on absolute exposure — adding to a short at a better price improves
        # its average the same way adding to a long does.
        total_cost = abs(old_qty) * float(existing["avg_price"]) + abs(signed) * fill
        avg = total_cost / max(1, abs(old_qty) + abs(signed))
        update = {"quantity": new_qty, "avg_price": round(avg, 2),
                  "margin_blocked": round(float(existing.get("margin_blocked") or 0) + margin, 2),
                  "updated_at": now_utc()}
        if mtf_meta:
            # Funding and pledge fees ACCUMULATE across top-ups: each add pledges more stock
            # and borrows more money, and both have to be carried or the close-out
            # under-charges the position.
            update["mtf_funded"] = round(float(existing.get("mtf_funded") or 0) + mtf_meta["funded"], 2)
            update["mtf_pledge_charge"] = round(
                float(existing.get("mtf_pledge_charge") or 0) + mtf_meta["pledge_charge"], 2)
            update["mtf_leverage"] = mtf_meta["leverage"]
            update["mtf_leverage_source"] = mtf_meta["leverage_source"]
        await pt_positions_collection.update_one({"_id": existing["_id"]}, {"$set": update})
        return

    await pt_positions_collection.insert_one({
        "position_id": f"P-{uuid4().hex[:12]}",
        "account_id": account_id,
        "segment": segment,
        "symbol": contract["symbol"],
        "token": contract["angel_token"],
        "contract": contract,
        "kind": contract["kind"],
        "underlying": contract.get("underlying") or contract["symbol"],
        "option_type": contract.get("option_type"),
        "strike": contract.get("strike"),
        "expiry": contract.get("expiry"),
        "product": product,
        "quantity": signed,
        "avg_price": round(fill, 2),
        "ltp": round(fill, 2),
        "margin_blocked": round(margin, 2),
        "realised_pnl": 0.0,
        "unrealised_pnl": 0.0,
        "mtf_funded": (mtf_meta or {}).get("funded", 0.0),
        "mtf_leverage": (mtf_meta or {}).get("leverage"),
        "mtf_leverage_source": (mtf_meta or {}).get("leverage_source"),
        "mtf_pledge_charge": (mtf_meta or {}).get("pledge_charge", 0.0),
        "mtf_interest_accrued": 0.0,
        "mtf_last_accrued_on": None,
        "status": "OPEN",
        "opened_at": now_utc(),
        "opened_on": today_ist(),
        "updated_at": now_utc(),
        "ts": now_utc(),
    })


async def _holdings_qty(account_id: str, token: str) -> int:
    doc = await pt_holdings_collection.find_one({"account_id": account_id, "token": token})
    return int(doc["quantity"]) if doc else 0


async def _reduce_holdings(account_id, contract, qty, fill, order) -> float:
    """Sell settled stock. Returns the net realised P&L so the trade row can carry it."""
    doc = await pt_holdings_collection.find_one(
        {"account_id": account_id, "token": contract["angel_token"]})
    if not doc or qty <= 0:
        return 0.0
    entry = float(doc["avg_price"])
    gross = (fill - entry) * qty
    fee = charges(segment=SEGMENT_EQUITY, product="CNC", instrument_kind="EQUITY",
                  entry=entry, exit_price=fill, quantity=qty)
    remaining = int(doc["quantity"]) - qty
    if remaining <= 0:
        await pt_holdings_collection.delete_one({"_id": doc["_id"]})
    else:
        await pt_holdings_collection.update_one(
            {"_id": doc["_id"]}, {"$set": {"quantity": remaining, "updated_at": now_utc()}})
    await accounts.ledger(account_id, "REALISED", gross,
                          f"Sold {qty} {contract['symbol']} from holdings @ {fill}",
                          order["order_id"])
    await accounts.ledger(account_id, "CHARGES", -float(fee["total"]),
                          f"Delivery charges on {contract['symbol']}", order["order_id"])
    return round(gross - float(fee["total"]), 2)


# ── amending ────────────────────────────────────────────────────────────────────


async def modify(account_id: str, order_id: str, *, quantity: int | None = None,
                 price: float | None = None, trigger_price: float | None = None,
                 order_type: str | None = None) -> dict:
    """Change a resting order. Only the fields a broker lets you change."""
    order = await pt_orders_collection.find_one({"account_id": account_id, "order_id": order_id})
    if order is None:
        raise OrderError(f"No order {order_id!r} on this account")
    if order["status"] not in OPEN_STATUSES:
        raise OrderError(
            f"Order is {order['status']} — only a resting order can be modified. "
            f"A filled order is changed by placing another one.")

    updated = {**{k: v for k, v in order.items() if k != "_id"}}
    if quantity is not None:
        updated["quantity"] = int(quantity)
    if price is not None:
        updated["price"] = float(price)
    if trigger_price is not None:
        updated["trigger_price"] = float(trigger_price)
    if order_type is not None:
        updated["order_type"] = order_type

    validate_order(segment=updated["segment"], transaction_type=updated["transaction_type"],
                   order_type=updated["order_type"], product=updated["product"],
                   validity=updated["validity"], quantity=updated["quantity"],
                   price=updated.get("price"), trigger_price=updated.get("trigger_price"))

    # A modify re-arms the order: an SL whose trigger moved back above the market goes from
    # PENDING back to TRIGGER_PENDING, which is what a broker does and what stops a stale
    # armed flag from firing an order the user just moved out of the way.
    if updated["order_type"] in ("SL", "SL-M"):
        ltp = await market.quote_one(updated["contract"])
        updated["status"] = "PENDING" if (ltp and triggered(updated, ltp)) else "TRIGGER_PENDING"
    updated["updated_at"] = now_utc()
    updated["status_message"] = "Modified"

    await pt_orders_collection.replace_one({"order_id": order_id}, updated)
    updated.pop("_id", None)
    return updated


async def cancel(account_id: str, order_id: str) -> dict:
    order = await pt_orders_collection.find_one({"account_id": account_id, "order_id": order_id})
    if order is None:
        raise OrderError(f"No order {order_id!r} on this account")
    if order["status"] not in OPEN_STATUSES:
        raise OrderError(f"Order is already {order['status']}")
    await pt_orders_collection.update_one(
        {"order_id": order_id},
        {"$set": {"status": "CANCELLED", "status_message": "Cancelled by user",
                  "margin_blocked": 0.0, "updated_at": now_utc()}})
    return await pt_orders_collection.find_one({"order_id": order_id}, {"_id": 0})


async def square_off(account_id: str, position_id: str, quantity: int | None = None) -> dict:
    """Exit a position at market — the Positions screen's exit button."""
    pos = await pt_positions_collection.find_one(
        {"account_id": account_id, "position_id": position_id, "status": "OPEN"})
    if pos is None:
        raise OrderError("No such open position")
    held = abs(int(pos["quantity"]))
    qty = min(int(quantity), held) if quantity else held
    if qty < 1:
        raise OrderError("Nothing to square off")
    return await place(
        account_id=account_id, segment=pos["segment"], contract=pos["contract"],
        transaction_type="SELL" if pos["quantity"] > 0 else "BUY",
        quantity=qty, order_type="MARKET", product=pos["product"], validity="DAY")
