"""The tick: what happens to orders and positions while nobody is looking.

A broker is mostly a background process. Between the moment you place an order and the
moment it matters, five things have to happen on their own — and every one of them is a
place where a paper desk quietly diverges from reality if it is skipped:

  1. MARK. Open positions re-price against the live quote, so P&L is current.
  2. ARM. A stop-loss whose trigger is touched moves TRIGGER_PENDING -> live.
  3. FILL. A resting order whose price is reached executes.
  4. EXPIRE. DAY orders die at the close. Leaving them resting is how a paper account
     fills a trade three days after the idea stopped being true.
  5. SQUARE OFF. MIS positions are closed at the exchange cutoff whether or not the user
     is watching — that is what intraday means, and a desk that carries them overnight is
     reporting the results of a product it did not trade.

Then once a day, after the close, unsold CNC buys SETTLE into Holdings, which is what makes
delivery different from a position.

ORDER OF OPERATIONS MATTERS. Marking runs before filling, so a position opened this tick is
not immediately re-marked at a price from before it existed. Square-off runs last, so an
order that filled at 15:19 is still closed by the 15:20 cutoff rather than surviving a tick.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from app.core.db import (
    pt_holdings_collection,
    pt_ledger_collection,
    pt_orders_collection,
    pt_positions_collection,
    pt_trades_collection,
)
from app.services.paper_broker import accounts, market, orders
from app.services.paper_broker.core import (
    MARKET_CLOSE,
    OPEN_STATUSES,
    SEGMENT_EQUITY,
    SEGMENT_FNO,
    OrderError,
    marketable,
    now_ist,
    now_utc,
    past_squareoff,
    today_ist,
    triggered,
)

logger = logging.getLogger("paper_broker.engine")

ENABLED = os.getenv("PT_ENABLED", "1").lower() not in ("0", "false", "")
TICK_SECONDS = int(os.getenv("PT_TICK_SECONDS", "20"))

_state: dict = {"last_tick": None, "ticks": 0, "fills": 0, "errors": 0, "last_settled": None}


async def tick() -> dict:
    """One pass. Safe to call by hand; the scheduler calls it on a timer."""
    result = {"marked": 0, "armed": 0, "filled": 0, "expired": 0, "squared_off": 0}

    open_positions = [p async for p in pt_positions_collection.find({"status": "OPEN"})]
    resting = [o async for o in pt_orders_collection.find({"status": {"$in": list(OPEN_STATUSES)}})]

    # ONE batched quote for everything this tick needs. A per-order or per-position quote
    # loop against Angel is what gets this backend rate-limited.
    contracts = [p["contract"] for p in open_positions] + [o["contract"] for o in resting]
    if not contracts:
        return result
    prices = await market.quotes(contracts)

    # 1. mark
    for pos in open_positions:
        ltp = prices.get(str(pos["token"]))
        if ltp is None:
            continue
        qty = int(pos["quantity"])
        unrealised = round((ltp - float(pos["avg_price"])) * qty, 2)
        await pt_positions_collection.update_one(
            {"_id": pos["_id"]},
            {"$set": {"ltp": round(ltp, 2), "unrealised_pnl": unrealised,
                      "updated_at": now_utc()}})
        result["marked"] += 1

    # 2 + 3. arm, then fill
    for order in resting:
        ltp = prices.get(str(order["token"]))
        if ltp is None:
            continue
        doc = {k: v for k, v in order.items() if k != "_id"}

        if doc["status"] == "TRIGGER_PENDING":
            if not triggered(doc, ltp):
                continue
            doc["status"] = "PENDING"
            doc["status_message"] = f"Trigger {doc['trigger_price']} hit at {ltp}"
            await pt_orders_collection.update_one(
                {"order_id": doc["order_id"]},
                {"$set": {"status": "PENDING", "status_message": doc["status_message"],
                          "triggered_at": now_utc(), "updated_at": now_utc()}})
            result["armed"] += 1

        if marketable(doc, ltp):
            try:
                await orders.execute(doc, ltp)
                result["filled"] += 1
                _state["fills"] += 1
            except OrderError as exc:
                # The account may have run out of margin since the order was placed. That
                # is a rejection with a reason, not a crash and not a silent skip.
                await orders._reject(doc, exc.detail)

    # 4. expire DAY orders once the session is over
    if now_ist().strftime("%H:%M") >= MARKET_CLOSE:
        expired = await pt_orders_collection.update_many(
            {"status": {"$in": list(OPEN_STATUSES)}, "validity": "DAY",
             "placed_on": {"$lte": today_ist()}},
            {"$set": {"status": "EXPIRED", "margin_blocked": 0.0,
                      "status_message": "DAY order expired at the close",
                      "updated_at": now_utc()}})
        result["expired"] = expired.modified_count

    # 5. force intraday flat at the cutoff
    result["squared_off"] = await _squareoff_mis(prices)

    _state["last_tick"] = now_utc()
    _state["ticks"] += 1
    return result


async def _squareoff_mis(prices: dict[str, float]) -> int:
    """Close MIS positions at the exchange cutoff. Not optional, by definition."""
    closed = 0
    for segment in (SEGMENT_EQUITY, SEGMENT_FNO):
        if not past_squareoff(segment):
            continue
        async for pos in pt_positions_collection.find(
                {"status": "OPEN", "product": "MIS", "segment": segment}):
            ltp = prices.get(str(pos["token"])) or await market.quote_one(pos["contract"])
            if ltp is None:
                continue
            try:
                doc = {
                    "order_id": f"AUTO-{pos['position_id']}",
                    "account_id": pos["account_id"], "segment": segment,
                    "contract": pos["contract"], "symbol": pos["symbol"],
                    "token": pos["token"],
                    "transaction_type": "SELL" if pos["quantity"] > 0 else "BUY",
                    "quantity": abs(int(pos["quantity"])), "filled_quantity": 0,
                    "order_type": "MARKET", "product": "MIS", "validity": "DAY",
                    "price": None, "trigger_price": None, "status": "PENDING",
                    "status_message": "Auto square-off at the intraday cutoff",
                    "margin_blocked": 0.0, "placed_at": now_utc(),
                    "placed_on": today_ist(), "updated_at": now_utc(), "ts": now_utc(),
                }
                await orders.execute(doc, ltp)
                closed += 1
            except OrderError:
                logger.exception("paper broker: auto square-off failed for %s", pos["symbol"])
    return closed


async def settle_delivery() -> dict:
    """Move unsold CNC buys into Holdings — the T+1 step that makes delivery delivery.

    Runs once after the close. Until it happens a CNC buy shows in Positions, exactly as it
    does in a real terminal on the day of purchase.
    """
    day = today_ist()
    if _state.get("last_settled") == day:
        return {"settled": 0, "reason": "already settled today"}

    settled = 0
    async for pos in pt_positions_collection.find(
            {"status": "OPEN", "product": "CNC", "segment": SEGMENT_EQUITY}):
        qty = int(pos["quantity"])
        if qty <= 0:
            continue
        existing = await pt_holdings_collection.find_one(
            {"account_id": pos["account_id"], "token": pos["token"]})
        if existing:
            old = int(existing["quantity"])
            avg = (old * float(existing["avg_price"]) + qty * float(pos["avg_price"])) / (old + qty)
            await pt_holdings_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {"quantity": old + qty, "avg_price": round(avg, 2),
                          "updated_at": now_utc()}})
        else:
            await pt_holdings_collection.insert_one({
                "account_id": pos["account_id"], "symbol": pos["symbol"],
                "token": pos["token"], "contract": pos["contract"],
                "quantity": qty, "avg_price": float(pos["avg_price"]),
                "settled_on": day, "updated_at": now_utc(), "ts": now_utc(),
            })
        # The margin blocked against the day position is released; the stock is now paid for
        # and sits in holdings instead.
        await accounts.ledger(pos["account_id"], "MARGIN_RELEASE",
                              float(pos.get("margin_blocked") or 0),
                              f"{pos['symbol']} settled to holdings")
        await pt_positions_collection.update_one(
            {"_id": pos["_id"]},
            {"$set": {"status": "SETTLED", "margin_blocked": 0.0,
                      "settled_on": day, "updated_at": now_utc()}})
        settled += 1

    _state["last_settled"] = day
    logger.info("paper broker: settled %s CNC positions into holdings", settled)
    return {"settled": settled, "date": day}


# ── reports ─────────────────────────────────────────────────────────────────────


async def positions(account_id: str, segment: str | None = None) -> dict:
    q: dict = {"account_id": account_id, "status": "OPEN"}
    if segment:
        q["segment"] = segment
    rows = [p async for p in pt_positions_collection.find(q, {"_id": 0})]

    if rows:
        prices = await market.quotes([r["contract"] for r in rows])
        for r in rows:
            ltp = prices.get(str(r["token"]))
            if ltp is not None:
                r["ltp"] = round(ltp, 2)
                r["unrealised_pnl"] = round((ltp - float(r["avg_price"])) * int(r["quantity"]), 2)
            r["pnl_pct"] = (round(r["unrealised_pnl"] / (abs(int(r["quantity"])) * float(r["avg_price"])) * 100, 2)
                            if r.get("unrealised_pnl") is not None and r["avg_price"] else None)
            r["side"] = "LONG" if int(r["quantity"]) > 0 else "SHORT"
            r["value"] = round(abs(int(r["quantity"])) * (r.get("ltp") or r["avg_price"]), 2)
            for k in ("opened_at", "updated_at", "ts"):
                if hasattr(r.get(k), "isoformat"):
                    r[k] = r[k].isoformat()

    rows.sort(key=lambda r: -(r.get("unrealised_pnl") or 0))
    total_unrealised = round(sum(r.get("unrealised_pnl") or 0 for r in rows), 2)
    return {
        "count": len(rows),
        "rows": rows,
        "unrealised_pnl": total_unrealised,
        "day_realised": await _day_realised(account_id, segment),
    }


async def _day_realised(account_id: str, segment: str | None = None) -> float:
    q: dict = {"account_id": account_id, "traded_on": today_ist()}
    if segment:
        q["segment"] = segment
    total = 0.0
    async for t in pt_trades_collection.find(q, {"realised_pnl": 1}):
        total += float(t.get("realised_pnl") or 0)
    return round(total, 2)


async def holdings(account_id: str) -> dict:
    rows = [h async for h in pt_holdings_collection.find({"account_id": account_id}, {"_id": 0})]
    if rows:
        prices = await market.quotes([r["contract"] for r in rows])
        for r in rows:
            ltp = prices.get(str(r["token"]))
            r["ltp"] = round(ltp, 2) if ltp else None
            invested = int(r["quantity"]) * float(r["avg_price"])
            r["invested"] = round(invested, 2)
            r["current_value"] = round(int(r["quantity"]) * ltp, 2) if ltp else None
            r["pnl"] = round(r["current_value"] - invested, 2) if ltp else None
            r["pnl_pct"] = round(r["pnl"] / invested * 100, 2) if ltp and invested else None
            for k in ("updated_at", "ts"):
                if hasattr(r.get(k), "isoformat"):
                    r[k] = r[k].isoformat()
    rows.sort(key=lambda r: -(r.get("pnl") or 0))
    return {
        "count": len(rows),
        "rows": rows,
        "invested": round(sum(r.get("invested") or 0 for r in rows), 2),
        "current_value": round(sum(r.get("current_value") or 0 for r in rows), 2),
        "pnl": round(sum(r.get("pnl") or 0 for r in rows), 2),
    }


async def order_book(account_id: str, segment: str | None = None,
                     status: str | None = None, limit: int = 300) -> dict:
    q: dict = {"account_id": account_id}
    if segment:
        q["segment"] = segment
    if status == "OPEN":
        q["status"] = {"$in": list(OPEN_STATUSES)}
    elif status:
        q["status"] = status
    rows = [o async for o in pt_orders_collection.find(q, {"_id": 0})
            .sort("placed_at", -1).limit(limit)]
    for r in rows:
        for k in ("placed_at", "updated_at", "filled_at", "triggered_at", "ts"):
            if hasattr(r.get(k), "isoformat"):
                r[k] = r[k].isoformat()
    return {"count": len(rows), "rows": rows,
            "open": sum(1 for r in rows if r["status"] in OPEN_STATUSES)}


async def trade_book(account_id: str, segment: str | None = None, limit: int = 300) -> dict:
    q: dict = {"account_id": account_id}
    if segment:
        q["segment"] = segment
    rows = [t async for t in pt_trades_collection.find(q, {"_id": 0})
            .sort("traded_at", -1).limit(limit)]
    for r in rows:
        for k in ("traded_at", "ts"):
            if hasattr(r.get(k), "isoformat"):
                r[k] = r[k].isoformat()
    return {"count": len(rows), "rows": rows,
            "realised_pnl": round(sum(float(r.get("realised_pnl") or 0) for r in rows), 2),
            "charges": round(sum(float(r.get("charges") or 0) for r in rows), 2)}


async def ledger(account_id: str, limit: int = 200) -> dict:
    rows = [e async for e in pt_ledger_collection.find({"account_id": account_id}, {"_id": 0})
            .sort("ts", -1).limit(limit)]
    for r in rows:
        if hasattr(r.get("ts"), "isoformat"):
            r["ts"] = r["ts"].isoformat()
    return {"count": len(rows), "rows": rows}


async def dashboard(account_id: str, segment: str | None = None) -> dict:
    """Everything the terminal header needs in one call."""
    pos = await positions(account_id, segment)
    hold = await holdings(account_id) if segment != SEGMENT_FNO else {"pnl": 0, "count": 0,
                                                                     "invested": 0,
                                                                     "current_value": 0}
    f = await accounts.funds(account_id, unrealised=pos["unrealised_pnl"] + (hold.get("pnl") or 0))
    ob = await order_book(account_id, segment, status="OPEN", limit=50)
    return {
        "funds": f,
        "positions": {"count": pos["count"], "unrealised_pnl": pos["unrealised_pnl"],
                      "day_realised": pos["day_realised"]},
        "holdings": {"count": hold["count"], "pnl": hold.get("pnl"),
                     "invested": hold.get("invested"), "value": hold.get("current_value")},
        "open_orders": ob["open"],
        "market_open": None,
        "engine": state(),
    }


def state() -> dict:
    last = _state.get("last_tick")
    return {
        "enabled": ENABLED,
        "tick_seconds": TICK_SECONDS,
        "ticks": _state["ticks"],
        "fills": _state["fills"],
        "errors": _state["errors"],
        "last_tick": last.isoformat() if isinstance(last, datetime) else None,
        "last_settled": _state.get("last_settled"),
    }
