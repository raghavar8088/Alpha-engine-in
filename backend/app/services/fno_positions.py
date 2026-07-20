"""F&O Positions module — a user-initiated paper trading desk for Index/Stock
OPTIONS and FUTURES, separate from the equity-only Manual Positions desk (see
app.services.manual_positions, whose capital-pool/fill/exit shape this mirrors).

The user picks an underlying (index or F&O-enabled stock), an expiry, and for
options a strike+CE/PE — resolved to a real Dhan security_id from the
`instruments` collection (asset_class INDEX_OPTION/EQUITY_OPTION/INDEX_FUTURE/
EQUITY_FUTURE) — then buys/sells in lots at the live premium/futures price.
Margin comes from Dhan's own /margincalculator, same as Manual Positions; no
leverage or premium is invented locally.

NOTE: stock OPTIONS (OPTSTK) are excluded from the instrument universe by
market-data-service/universe.py (deferred there to keep the FNO row count
down) — only stock FUTURES are loaded today, so the option chain picker only
lists index underlyings until that's re-enabled and universe.py is re-run.
"""

import os
from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import fno_orders_collection, fno_positions_collection, instruments_collection
from app.services.dhan_client import DhanAPIError, DhanClient
from options_service.chain import parse_chain

INITIAL_CAPITAL = float(os.getenv("FNO_POSITIONS_INITIAL_CAPITAL", "10000000"))  # ₹1 crore
PRODUCT_TYPES = ("INTRADAY", "MARGIN")
OPTION_CLASSES = ("INDEX_OPTION", "EQUITY_OPTION")
FUTURE_CLASSES = ("INDEX_FUTURE", "EQUITY_FUTURE")
INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}
# Only used when Dhan's margin calculator is unreachable. SPAN+exposure on a short
# scales with the UNDERLYING notional, not with the premium, so the stand-in is a
# flat percentage of notional. Set above real SPAN (~10-12% on index options) so an
# outage errs toward under-trading. See _fallback_margin.
SHORT_MARGIN_NOTIONAL_PCT = 0.15


class OrderError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_leverage(raw: str | float | None) -> float:
    if raw is None:
        return 1.0
    if isinstance(raw, (int, float)):
        return float(raw) or 1.0
    try:
        return float(str(raw).upper().replace("X", "").strip()) or 1.0
    except ValueError:
        return 1.0


async def _underlying_instrument(symbol: str) -> dict:
    doc = await instruments_collection.find_one({
        "symbol": symbol.upper(),
        "asset_class": "INDEX" if symbol.upper() in INDEX_UNDERLYINGS else "EQUITY",
    })
    if doc is None:
        raise OrderError(f"{symbol} has no F&O underlying instrument on file")
    return doc


async def underlyings() -> list[dict]:
    """Index underlyings (whitelisted) plus equities that have at least one
    stock-futures contract loaded — the current tradable F&O universe."""
    index_docs = await instruments_collection.find(
        {"asset_class": "INDEX"}, {"_id": 0, "symbol": 1, "name": 1}
    ).to_list(None)
    stock_symbols = await instruments_collection.distinct("underlying_symbol", {"asset_class": "EQUITY_FUTURE"})
    stock_docs = await instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": stock_symbols}}, {"_id": 0, "symbol": 1, "name": 1}
    ).to_list(None) if stock_symbols else []
    return [{**d, "kind": "INDEX"} for d in index_docs] + [{**d, "kind": "EQUITY"} for d in stock_docs]


async def option_expiries(dhan: DhanClient, symbol: str) -> list[str]:
    inst = await _underlying_instrument(symbol)
    try:
        result = await dhan.option_chain_expiry_list(int(inst["security_id"]), inst["exchange_segment"])
    except DhanAPIError as exc:
        raise OrderError(exc.remarks)
    return result.get("data", [])


async def option_chain(dhan: DhanClient, symbol: str, expiry: str) -> dict:
    inst = await _underlying_instrument(symbol)
    try:
        raw = await dhan.option_chain(int(inst["security_id"]), inst["exchange_segment"], expiry)
    except DhanAPIError as exc:
        raise OrderError(exc.remarks)
    if raw.get("status") != "success":
        raise OrderError(raw.get("remarks") or "Dhan option chain request failed")
    parsed = parse_chain(raw, expiry)
    parsed["symbol"] = symbol.upper()
    return parsed


async def future_expiries(symbol: str) -> list[str]:
    today = _now().date().isoformat()
    rows = await instruments_collection.distinct(
        "expiry", {"underlying_symbol": symbol.upper(), "asset_class": {"$in": list(FUTURE_CLASSES)}}
    )
    return sorted(e for e in rows if e and e >= today)


async def _resolve_option(symbol: str, expiry: str, strike: float, option_type: str) -> dict:
    doc = await instruments_collection.find_one({
        "underlying_symbol": symbol.upper(), "expiry": expiry, "strike": strike,
        "option_type": option_type.upper(), "asset_class": {"$in": list(OPTION_CLASSES)},
    })
    if doc is None:
        raise OrderError(f"No option contract for {symbol} {expiry} {strike:g}{option_type.upper()} on file")
    return doc


async def _resolve_future(symbol: str, expiry: str) -> dict:
    doc = await instruments_collection.find_one({
        "underlying_symbol": symbol.upper(), "expiry": expiry, "asset_class": {"$in": list(FUTURE_CLASSES)},
    })
    if doc is None:
        raise OrderError(f"No futures contract for {symbol} expiring {expiry}")
    return doc


async def _ltp(dhan: DhanClient, security_id: str, exchange_segment: str) -> float | None:
    try:
        raw = await dhan.quote_data({exchange_segment: [int(security_id)]})
    except (DhanAPIError, Exception):
        return None
    data = raw.get("data", {}) if isinstance(raw, dict) else {}
    row = data.get(exchange_segment, {}).get(str(security_id))
    return float(row["last_price"]) if row and row.get("last_price") else None


def _fallback_margin(transaction_type: str, quantity: int, price: float, strike: float | None) -> float:
    """Stand-in margin for when Dhan's calculator can't be reached.

    Premium x quantity is correct for a BUY — that is exactly what you pay. It is
    badly wrong for a SELL: the broker blocks SPAN+exposure, which tracks the
    underlying notional, so a ₹0.25 far-OTM strike would reserve a few hundred
    rupees against a position whose real margin is over a lakh per lot. Use the
    strike as the underlying proxy for options; a future's own price is already the
    notional, so it needs no proxy.
    """
    if transaction_type != "SELL":
        return price * quantity
    return (strike or price) * quantity * SHORT_MARGIN_NOTIONAL_PCT


async def _margin(
    dhan: DhanClient, security_id: str, exchange_segment: str, transaction_type: str,
    quantity: int, product_type: str, price: float, strike: float | None = None,
) -> tuple[float, float, str]:
    try:
        r = await dhan.margin_calculator(
            security_id=security_id, exchange_segment=exchange_segment, transaction_type=transaction_type,
            quantity=quantity, product_type=product_type, price=price,
        )
        margin = float(r.get("totalMargin") or 0) or _fallback_margin(transaction_type, quantity, price, strike)
        return margin, _parse_leverage(r.get("leverage")), "dhan_calculator"
    except (DhanAPIError, Exception):
        return _fallback_margin(transaction_type, quantity, price, strike), 1.0, "fallback"


async def _deployed_margin() -> float:
    total = 0.0
    async for p in fno_positions_collection.find({"status": "OPEN"}, {"margin_used": 1}):
        total += p.get("margin_used") or 0.0
    return total


async def _realized_pnl_all_time() -> float:
    total = 0.0
    async for p in fno_positions_collection.find({}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    return total


async def available_cash() -> float:
    deployed = await _deployed_margin()
    realized = await _realized_pnl_all_time()
    return INITIAL_CAPITAL + realized - deployed


async def top_movers(dhan: DhanClient, limit: int = 10) -> dict:
    """Scans the nearest expiry's chain for every whitelisted index and ranks
    CE/PE legs by intraday % change off the previous close — the closest honest
    proxy for "today's top performing options" without a dedicated Dhan
    FNO-gainers endpoint."""
    calls, puts = [], []
    for symbol in INDEX_UNDERLYINGS:
        try:
            exps = await option_expiries(dhan, symbol)
            if not exps:
                continue
            chain = await option_chain(dhan, symbol, exps[0])
        except OrderError:
            continue
        for row in chain["strikes"]:
            for side, bucket in (("ce", calls), ("pe", puts)):
                leg = row[side]
                ltp, prev = leg.get("last_price") or 0, leg.get("previous_close_price") or 0
                if ltp <= 0 or prev <= 0:
                    continue
                bucket.append({
                    "symbol": symbol, "expiry": exps[0], "strike": row["strike"],
                    "option_type": side.upper(), "ltp": ltp,
                    "change_pct": round((ltp / prev - 1) * 100, 2),
                    "volume": leg.get("volume") or 0, "oi": leg.get("oi") or 0,
                })
    calls.sort(key=lambda r: r["change_pct"], reverse=True)
    puts.sort(key=lambda r: r["change_pct"], reverse=True)
    return {"top_calls": calls[:limit], "top_puts": puts[:limit]}


async def estimate_margin(
    dhan: DhanClient, security_id: str, exchange_segment: str, transaction_type: str,
    quantity: int, product_type: str, price: float,
) -> dict:
    # The strike only matters if we end up on the fallback path, but it has to be
    # resolved here — this entry point is handed a bare security_id, not a contract.
    contract = await instruments_collection.find_one(
        {"security_id": security_id, "exchange_segment": exchange_segment}, {"strike": 1}
    )
    margin, leverage, source = await _margin(
        dhan, security_id, exchange_segment, transaction_type, quantity, product_type, price,
        strike=(contract or {}).get("strike"),
    )
    return {"margin_required": round(margin, 2), "leverage": leverage, "notional_value": round(price * quantity, 2), "source": source}


async def place_order(
    dhan: DhanClient, *, instrument_kind: str, symbol: str, expiry: str, transaction_type: str,
    lots: int, order_type: str, product_type: str, strike: float | None = None,
    option_type: str | None = None, limit_price: float = 0.0,
) -> dict:
    if lots < 1:
        raise OrderError("Lots must be at least 1")
    if product_type not in PRODUCT_TYPES:
        raise OrderError(f"product_type must be one of {PRODUCT_TYPES}")
    if order_type == "LIMIT" and limit_price <= 0:
        raise OrderError("Limit orders need a positive limit_price")

    if instrument_kind == "OPTION":
        if strike is None or option_type not in ("CE", "PE"):
            raise OrderError("Options need a strike and option_type (CE/PE)")
        inst = await _resolve_option(symbol, expiry, strike, option_type)
    elif instrument_kind == "FUTURE":
        inst = await _resolve_future(symbol, expiry)
    else:
        raise OrderError("instrument_kind must be OPTION or FUTURE")

    quantity = lots * inst.get("lot_size", 1)
    ltp = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
    if ltp is None:
        raise OrderError("Live quote unavailable (broker offline?) — cannot price this order")

    order_id = f"FNO-{uuid4().hex[:12]}"
    now = _now()
    contract_label = (
        f"{symbol} {expiry} {strike:g}{option_type}" if instrument_kind == "OPTION" else f"{symbol} {expiry} FUT"
    )
    base_order = {
        "order_id": order_id,
        "symbol": inst["symbol"],
        "display_name": contract_label,
        "instrument_kind": instrument_kind,
        "instrument": {
            "symbol": inst["symbol"], "security_id": inst["security_id"],
            "exchange_segment": inst["exchange_segment"], "lot_size": inst.get("lot_size", 1),
            "tick_size": inst.get("tick_size", 0.05), "underlying_symbol": inst.get("underlying_symbol"),
            "expiry": inst.get("expiry"), "strike": inst.get("strike"), "option_type": inst.get("option_type"),
        },
        "transaction_type": transaction_type, "lots": lots, "quantity": quantity, "order_type": order_type,
        "limit_price": limit_price if order_type == "LIMIT" else None,
        "product_type": product_type, "placed_at": now, "updated_at": now,
    }

    marketable = (
        order_type == "MARKET"
        or (transaction_type == "BUY" and ltp <= limit_price)
        or (transaction_type == "SELL" and ltp >= limit_price)
    )
    if not marketable:
        doc = {**base_order, "status": "PENDING", "fill_price": None, "filled_at": None,
               "margin_used": None, "leverage": None}
        await fno_orders_collection.insert_one(doc)
        doc.pop("_id", None)
        return doc

    fill_price = ltp if order_type == "MARKET" else limit_price
    return await _fill(dhan, base_order, fill_price)


async def _fill(dhan: DhanClient, base_order: dict, fill_price: float) -> dict:
    inst = base_order["instrument"]
    security_id, segment = inst["security_id"], inst["exchange_segment"]
    transaction_type, quantity, product_type = base_order["transaction_type"], base_order["quantity"], base_order["product_type"]
    contract_key = {"symbol": base_order["symbol"], "instrument.expiry": inst.get("expiry"),
                     "instrument.strike": inst.get("strike"), "instrument.option_type": inst.get("option_type")}

    existing = await fno_positions_collection.find_one({**contract_key, "product_type": product_type, "status": "OPEN"})
    lot_size = inst.get("lot_size", 1) or 1

    # Positions net per contract+product, the way a real broker book does: an order
    # on the same side as the open position adds to it, the opposite side reduces or
    # closes it, and with nothing open either side may open one — BUY goes long,
    # SELL opens a short (option writing). Legacy docs predate `side`, so any
    # position without it is a long.
    existing_side = existing.get("side", "BUY") if existing else None
    opening = existing is None or existing_side == transaction_type

    if opening:
        side = transaction_type
        margin, leverage, margin_source = await _margin(
            dhan, security_id, segment, side, quantity, product_type, fill_price, strike=inst.get("strike")
        )
        cash = await available_cash()
        if margin > cash:
            raise OrderError(f"Insufficient paper capital: order needs ₹{margin:,.2f} margin ({product_type}), only ₹{cash:,.2f} available")
        if existing is None:
            position = {
                "position_id": uuid4().hex[:12], "symbol": base_order["symbol"], "display_name": base_order["display_name"],
                "instrument_kind": base_order["instrument_kind"], "instrument": inst, "product_type": product_type, "side": side,
                "lots": base_order["lots"], "quantity": quantity, "avg_price": fill_price, "margin_used": round(margin, 2),
                "leverage": leverage, "margin_source": margin_source, "ltp": fill_price, "ltp_source": "dhan_quote",
                "unrealized_pnl": 0.0, "pnl_pct": 0.0, "realized_pnl": 0.0,
                "status": "OPEN", "opened_at": _now(), "updated_at": _now(), "closed_at": None,
            }
            await fno_positions_collection.insert_one(position)
            position.pop("_id", None)
        else:
            new_qty = existing["quantity"] + quantity
            new_avg = (existing["quantity"] * existing["avg_price"] + quantity * fill_price) / new_qty
            new_margin, new_leverage, new_margin_source = await _margin(
                dhan, security_id, segment, side, new_qty, product_type, new_avg, strike=inst.get("strike")
            )
            await fno_positions_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {"quantity": new_qty, "lots": new_qty // lot_size, "avg_price": round(new_avg, 4),
                          "margin_used": round(new_margin, 2), "leverage": new_leverage,
                          "margin_source": new_margin_source, "updated_at": _now()}},
            )
            position = await fno_positions_collection.find_one({"_id": existing["_id"]})
            position.pop("_id", None)

    else:  # opposite side — reduce or close the open position
        if existing["quantity"] < quantity:
            verb = "sell" if transaction_type == "SELL" else "buy back"
            raise OrderError(f"Cannot {verb} {quantity} {base_order['display_name']} — only {existing['quantity']} open")
        # A long earns (exit - entry); a short earns (entry - exit).
        direction = 1 if existing_side == "BUY" else -1
        realized = round((fill_price - existing["avg_price"]) * quantity * direction, 2)
        remaining_qty = existing["quantity"] - quantity
        if remaining_qty == 0:
            await fno_positions_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "status": "CLOSED", "quantity": 0, "lots": 0, "margin_used": 0.0,
                    "realized_pnl": round(existing.get("realized_pnl", 0.0) + realized, 2),
                    "unrealized_pnl": 0.0, "ltp": fill_price, "updated_at": _now(), "closed_at": _now(),
                }},
            )
        else:
            new_margin, new_leverage, new_margin_source = await _margin(
                dhan, security_id, segment, existing_side, remaining_qty, product_type, existing["avg_price"],
                strike=inst.get("strike"),
            )
            await fno_positions_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "quantity": remaining_qty, "lots": remaining_qty // lot_size, "margin_used": round(new_margin, 2),
                    "leverage": new_leverage, "margin_source": new_margin_source,
                    "realized_pnl": round(existing.get("realized_pnl", 0.0) + realized, 2), "updated_at": _now(),
                }},
            )
        position = await fno_positions_collection.find_one({"_id": existing["_id"]})
        position.pop("_id", None)

    order_doc = {**base_order, "status": "FILLED", "fill_price": fill_price, "filled_at": _now(),
                 "margin_used": position.get("margin_used"), "leverage": position.get("leverage")}
    await fno_orders_collection.insert_one(order_doc)
    order_doc.pop("_id", None)
    order_doc["position"] = position
    return order_doc


async def exit_position(dhan: DhanClient, position_id: str, lots: int | None = None) -> dict:
    position = await fno_positions_collection.find_one({"position_id": position_id, "status": "OPEN"})
    if position is None:
        raise OrderError("Position not found or already closed")
    lot_size = position["instrument"].get("lot_size", 1) or 1
    qty = (lots * lot_size) if lots else position["quantity"]
    if qty > position["quantity"]:
        raise OrderError(f"Cannot exit {qty} — position only holds {position['quantity']}")

    inst = position["instrument"]
    base_order = {
        "order_id": f"FNO-{uuid4().hex[:12]}", "symbol": position["symbol"], "display_name": position["display_name"],
        "instrument_kind": position["instrument_kind"], "instrument": inst,
        # Exiting means trading the opposite side: sell to close a long, buy back a short.
        "transaction_type": "BUY" if position.get("side", "BUY") == "SELL" else "SELL",
        "lots": qty // lot_size, "quantity": qty, "order_type": "MARKET",
        "limit_price": None, "product_type": position["product_type"], "placed_at": _now(), "updated_at": _now(),
    }
    ltp = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
    if ltp is None:
        raise OrderError("Live quote unavailable (broker offline?) — cannot exit right now")
    return await _fill(dhan, base_order, ltp)


async def sync_positions(dhan: DhanClient) -> int:
    open_positions = [p async for p in fno_positions_collection.find({"status": "OPEN"})]
    updated = 0
    for pos in open_positions:
        inst = pos["instrument"]
        ltp = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
        if ltp is None:
            continue
        direction = 1 if pos.get("side", "BUY") == "BUY" else -1
        unrealized = round((ltp - pos["avg_price"]) * pos["quantity"] * direction, 2)
        pnl_pct = round((ltp / pos["avg_price"] - 1) * 100 * direction, 2) if pos["avg_price"] else 0.0
        await fno_positions_collection.update_one(
            {"_id": pos["_id"]},
            {"$set": {"ltp": ltp, "ltp_source": "dhan_quote", "unrealized_pnl": unrealized, "pnl_pct": pnl_pct, "updated_at": _now()}},
        )
        updated += 1

    pending = [o async for o in fno_orders_collection.find({"status": "PENDING"})]
    for order in pending:
        inst = order["instrument"]
        ltp = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
        if ltp is None:
            continue
        limit_price = order["limit_price"]
        crossed = (order["transaction_type"] == "BUY" and ltp <= limit_price) or (order["transaction_type"] == "SELL" and ltp >= limit_price)
        if crossed:
            try:
                await _fill(dhan, {k: v for k, v in order.items() if k not in ("_id", "status", "fill_price", "filled_at", "margin_used", "leverage")}, limit_price)
                await fno_orders_collection.delete_one({"_id": order["_id"]})
            except OrderError:
                continue
    return updated


async def reset_all() -> dict:
    positions_deleted = (await fno_positions_collection.delete_many({})).deleted_count
    orders_deleted = (await fno_orders_collection.delete_many({})).deleted_count
    return {"positions_deleted": positions_deleted, "orders_deleted": orders_deleted, "initial_capital": INITIAL_CAPITAL}


async def summary() -> dict:
    deployed = await _deployed_margin()
    realized = await _realized_pnl_all_time()
    unrealized = 0.0
    async for p in fno_positions_collection.find({"status": "OPEN"}, {"unrealized_pnl": 1}):
        unrealized += p.get("unrealized_pnl") or 0.0
    equity = INITIAL_CAPITAL + realized + unrealized
    open_count = await fno_positions_collection.count_documents({"status": "OPEN"})
    closed_count = await fno_positions_collection.count_documents({"status": "CLOSED"})
    wins = await fno_positions_collection.count_documents({"status": "CLOSED", "realized_pnl": {"$gt": 0}})
    win_rate = round(wins / closed_count * 100, 1) if closed_count else None
    return {
        "initial_capital": INITIAL_CAPITAL,
        "available_cash": round(INITIAL_CAPITAL + realized - deployed, 2),
        "deployed_margin": round(deployed, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_pnl": round(realized + unrealized, 2),
        "equity": round(equity, 2),
        "roi_pct": round((equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        "open_positions": open_count,
        "closed_positions": closed_count,
        "win_rate": win_rate,
    }
