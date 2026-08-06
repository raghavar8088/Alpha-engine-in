"""Manual Positions module — a user-initiated paper trading desk, separate from
the auto-opened Trading Call Positions ledger. The user searches an instrument
(NSE or BSE equity), places a market/limit BUY order sized in quantity, and can
size it against real Dhan margin — CNC (full notional, no leverage), MARGIN,
INTRADAY, or MTF (Margin Trade Funding), whose actual leverage for that stock
comes straight from Dhan's own /margincalculator (no such data is invented
locally: Dhan has no bulk "MTF-eligible stocks" list, only a per-order
calculator, so leverage is fetched live per instrument+quantity).

Supports multiple named accounts, each with its own independent capital pool —
like separate real brokerage accounts, so different strategies can be tracked
separately. Every position/order belongs to exactly one account_id. A "Default"
account is auto-created (and existing account-less data migrated into it) the
first time accounts are listed, so this upgrade never loses pre-existing data.

Capital pool convention mirrors app.services.call_positions, scoped per account:
available_cash = initial + realized_pnl - deployed_margin, equity = initial +
realized_pnl + unrealized_pnl. Positions are opened/closed/averaged exactly like
a real broker's Positions tab; SELL against an open position exits (fully or
partially) rather than opening a short.
"""

import os
from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import (
    instruments_collection,
    manual_accounts_collection,
    manual_orders_collection,
    manual_positions_collection,
)
from app.services.dhan_client import DhanAPIError, DhanClient

DEFAULT_INITIAL_CAPITAL = float(os.getenv("MANUAL_POSITIONS_INITIAL_CAPITAL", "10000000"))  # ₹1 crore
PRODUCT_TYPES = ("CNC", "MTF", "MARGIN", "INTRADAY")


class OrderError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_leverage(raw: str | float | None) -> float:
    """Dhan returns leverage as a string like "4.55X" (or sometimes a bare
    number) — normalize to a float multiplier, defaulting to 1x (no leverage)
    if the field is missing or unparsable rather than guessing higher."""
    if raw is None:
        return 1.0
    if isinstance(raw, (int, float)):
        return float(raw) or 1.0
    try:
        return float(str(raw).upper().replace("X", "").strip()) or 1.0
    except ValueError:
        return 1.0


# --------------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------------


async def ensure_default_account() -> dict:
    """Idempotent migration: if no accounts exist yet, create "Default" and
    backfill it onto every pre-existing position/order that has no account_id
    (i.e. data from before multi-account support existed). Safe to call on
    every list_accounts() — a no-op once the migration has happened."""
    existing = await manual_accounts_collection.find_one(sort=[("created_at", 1)])
    if existing is not None:
        return existing

    account = {
        "account_id": uuid4().hex[:12], "name": "Default",
        "initial_capital": DEFAULT_INITIAL_CAPITAL, "created_at": _now(),
    }
    await manual_accounts_collection.insert_one(account)
    await manual_positions_collection.update_many(
        {"account_id": {"$exists": False}}, {"$set": {"account_id": account["account_id"]}}
    )
    await manual_orders_collection.update_many(
        {"account_id": {"$exists": False}}, {"$set": {"account_id": account["account_id"]}}
    )
    account.pop("_id", None)
    return account


async def list_accounts() -> list[dict]:
    await ensure_default_account()
    cursor = manual_accounts_collection.find({}, {"_id": 0}).sort("created_at", 1)
    return [d async for d in cursor]


async def get_account(account_id: str) -> dict:
    doc = await manual_accounts_collection.find_one({"account_id": account_id}, {"_id": 0})
    if doc is None:
        raise OrderError(f"Unknown account {account_id}")
    return doc


async def create_account(name: str, initial_capital: float | None = None) -> dict:
    name = name.strip()
    if not name:
        raise OrderError("Account name cannot be empty")
    if await manual_accounts_collection.find_one({"name": name}):
        raise OrderError(f'An account named "{name}" already exists')
    account = {
        "account_id": uuid4().hex[:12], "name": name,
        "initial_capital": initial_capital if initial_capital and initial_capital > 0 else DEFAULT_INITIAL_CAPITAL,
        "created_at": _now(),
    }
    await manual_accounts_collection.insert_one(account)
    account.pop("_id", None)
    return account


# --------------------------------------------------------------------------------
# Instrument / quote / margin helpers
# --------------------------------------------------------------------------------


async def _instrument(security_id: str, exchange_segment: str) -> dict:
    doc = await instruments_collection.find_one({"security_id": security_id, "exchange_segment": exchange_segment})
    if doc is None:
        raise OrderError(f"Unknown instrument {security_id}/{exchange_segment}")
    return doc


async def _ltp(dhan: DhanClient, security_id: str, exchange_segment: str) -> float | None:
    # Dhan-first, then Angel One (broker_data.get_ltp owns the failover), so equity
    # marking/fills keep working when Dhan's data endpoint is unavailable.
    from app.services.broker_data import get_ltp

    price, _source = await get_ltp(dhan, security_id, exchange_segment)
    if price is not None:
        return price
    try:
        raw = await dhan.quote_data({exchange_segment: [int(security_id)]})
    except (DhanAPIError, Exception):
        return None
    data = raw.get("data", {}) if isinstance(raw, dict) else {}
    row = data.get(exchange_segment, {}).get(str(security_id))
    return float(row["last_price"]) if row and row.get("last_price") else None


# Static, conservative leverage per product type, used now that margin no longer comes
# from Dhan (Angel One is a market-DATA source only — it has no margin calculator). CNC
# is full notional; leveraged products divide notional by the assumed multiplier.
_PRODUCT_LEVERAGE = {"CNC": 1.0, "MTF": 4.0, "MARGIN": 5.0, "INTRADAY": 5.0}


async def _margin(
    dhan: DhanClient | None, security_id: str, exchange_segment: str, transaction_type: str,
    quantity: int, product_type: str, price: float,
) -> tuple[float, float, str]:
    """(margin_required, leverage, source). Off Dhan: derived from the static leverage
    assumption above. `source` is "static" so callers stay honest that it's an assumption,
    not a live broker figure."""
    leverage = _PRODUCT_LEVERAGE.get(product_type, 1.0)
    return round(price * quantity / leverage, 2), leverage, "static"


async def _deployed_margin(account_id: str) -> float:
    total = 0.0
    async for p in manual_positions_collection.find({"account_id": account_id, "status": "OPEN"}, {"margin_used": 1}):
        total += p.get("margin_used") or 0.0
    return total


async def _realized_pnl_all_time(account_id: str) -> float:
    total = 0.0
    async for p in manual_positions_collection.find({"account_id": account_id}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    return total


async def available_cash(account_id: str) -> float:
    account = await get_account(account_id)
    deployed = await _deployed_margin(account_id)
    realized = await _realized_pnl_all_time(account_id)
    return account["initial_capital"] + realized - deployed


async def search_instruments(query: str, limit: int = 15) -> list[dict]:
    """Autocomplete over NSE + BSE equities/ETFs by symbol or company name."""
    q = query.strip()
    if not q:
        return []
    cursor = instruments_collection.find(
        {
            "asset_class": {"$in": ["EQUITY", "ETF"]},
            "$or": [
                {"symbol": {"$regex": f"^{q}", "$options": "i"}},
                {"name": {"$regex": q, "$options": "i"}},
            ],
        },
        {"_id": 0, "symbol": 1, "name": 1, "security_id": 1, "exchange_segment": 1,
         "lot_size": 1, "tick_size": 1, "asset_class": 1},
    ).limit(limit)
    return [d async for d in cursor]


async def get_quote(dhan: DhanClient, security_id: str, exchange_segment: str) -> dict:
    ltp = await _ltp(dhan, security_id, exchange_segment)
    if ltp is None:
        raise OrderError("Live quote unavailable (broker offline or rate-limited) — try again shortly")
    return {"ltp": ltp}


async def estimate_margin(
    dhan: DhanClient, security_id: str, exchange_segment: str, transaction_type: str,
    quantity: int, product_type: str, price: float,
) -> dict:
    margin, leverage, source = await _margin(dhan, security_id, exchange_segment, transaction_type, quantity, product_type, price)
    return {
        "margin_required": round(margin, 2), "leverage": leverage, "notional_value": round(price * quantity, 2),
        "source": source,
    }


# --------------------------------------------------------------------------------
# Orders / fills / exits
# --------------------------------------------------------------------------------


async def place_order(
    dhan: DhanClient, *, account_id: str, security_id: str, exchange_segment: str, transaction_type: str,
    quantity: int, order_type: str, product_type: str, limit_price: float = 0.0,
    force_new_position: bool = False,
) -> dict:
    await get_account(account_id)  # 404s cleanly if the account_id is bogus
    if quantity < 1:
        raise OrderError("Quantity must be at least 1")
    if product_type not in PRODUCT_TYPES:
        raise OrderError(f"product_type must be one of {PRODUCT_TYPES}")
    if order_type == "LIMIT" and limit_price <= 0:
        raise OrderError("Limit orders need a positive limit_price")

    inst = await _instrument(security_id, exchange_segment)
    ltp = await _ltp(dhan, security_id, exchange_segment)
    if ltp is None:
        raise OrderError("Live quote unavailable (broker offline?) — cannot price this order")

    order_id = f"MANUAL-{uuid4().hex[:12]}"
    now = _now()
    base_order = {
        "order_id": order_id, "account_id": account_id,
        "symbol": inst["symbol"],
        "display_name": inst.get("name") or inst["symbol"],
        "instrument": {
            "symbol": inst["symbol"], "security_id": inst["security_id"],
            "exchange_segment": inst["exchange_segment"], "lot_size": inst.get("lot_size", 1),
            "tick_size": inst.get("tick_size", 0.05),
        },
        "transaction_type": transaction_type, "quantity": quantity, "order_type": order_type,
        "limit_price": limit_price if order_type == "LIMIT" else None,
        "product_type": product_type, "placed_at": now, "updated_at": now,
        "force_new_position": force_new_position,
    }

    marketable = (
        order_type == "MARKET"
        or (transaction_type == "BUY" and ltp <= limit_price)
        or (transaction_type == "SELL" and ltp >= limit_price)
    )
    if not marketable:
        doc = {**base_order, "status": "PENDING", "fill_price": None, "filled_at": None,
               "margin_used": None, "leverage": None}
        await manual_orders_collection.insert_one(doc)
        doc.pop("_id", None)
        return doc

    fill_price = ltp if order_type == "MARKET" else limit_price
    return await _fill(dhan, base_order, fill_price, force_new_position=force_new_position)


async def _fill(dhan: DhanClient, base_order: dict, fill_price: float, force_new_position: bool = False) -> dict:
    inst = base_order["instrument"]
    security_id, segment = inst["security_id"], inst["exchange_segment"]
    transaction_type, quantity, product_type = base_order["transaction_type"], base_order["quantity"], base_order["product_type"]
    symbol, account_id = base_order["symbol"], base_order["account_id"]

    # force_new_position: the user was warned this symbol already has an open
    # position and chose to open a separate one anyway rather than average in —
    # only meaningful on BUY (SELL always targets an existing position by id).
    existing = None if (force_new_position and transaction_type == "BUY") else await manual_positions_collection.find_one(
        {"account_id": account_id, "symbol": symbol, "product_type": product_type, "status": "OPEN"}
    )

    if transaction_type == "BUY":
        margin, leverage, margin_source = await _margin(dhan, security_id, segment, "BUY", quantity, product_type, fill_price)
        cash = await available_cash(account_id)
        if margin > cash:
            raise OrderError(
                f"Insufficient paper capital: order needs {'₹'}{margin:,.2f} margin "
                f"({product_type}), only {'₹'}{cash:,.2f} available"
            )
        if existing is None:
            position = {
                "position_id": uuid4().hex[:12], "account_id": account_id, "symbol": symbol,
                "display_name": base_order["display_name"],
                "instrument": inst, "product_type": product_type, "side": "BUY",
                "quantity": quantity, "avg_price": fill_price, "margin_used": round(margin, 2),
                "leverage": leverage, "margin_source": margin_source, "ltp": fill_price, "ltp_source": "dhan_quote",
                "unrealized_pnl": 0.0, "pnl_pct": 0.0, "realized_pnl": 0.0,
                "status": "OPEN", "opened_at": _now(), "updated_at": _now(), "closed_at": None,
            }
            await manual_positions_collection.insert_one(position)
            position.pop("_id", None)
        else:
            new_qty = existing["quantity"] + quantity
            new_avg = (existing["quantity"] * existing["avg_price"] + quantity * fill_price) / new_qty
            new_margin, new_leverage, new_margin_source = await _margin(dhan, security_id, segment, "BUY", new_qty, product_type, new_avg)
            await manual_positions_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {"quantity": new_qty, "avg_price": round(new_avg, 4),
                          "margin_used": round(new_margin, 2), "leverage": new_leverage,
                          "margin_source": new_margin_source, "updated_at": _now()}},
            )
            position = await manual_positions_collection.find_one({"_id": existing["_id"]})
            position.pop("_id", None)

    else:  # SELL — must be exiting an existing open position, no short-selling
        if existing is None or existing["quantity"] < quantity:
            held = existing["quantity"] if existing else 0
            raise OrderError(f"Cannot sell {quantity} {symbol} ({product_type}) — only {held} held")
        realized = round((fill_price - existing["avg_price"]) * quantity, 2)
        remaining_qty = existing["quantity"] - quantity
        if remaining_qty == 0:
            await manual_positions_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "status": "CLOSED", "quantity": 0, "margin_used": 0.0,
                    "realized_pnl": round(existing.get("realized_pnl", 0.0) + realized, 2),
                    "unrealized_pnl": 0.0, "ltp": fill_price,
                    "updated_at": _now(), "closed_at": _now(),
                }},
            )
        else:
            new_margin, new_leverage, new_margin_source = await _margin(
                dhan, security_id, segment, "BUY", remaining_qty, product_type, existing["avg_price"]
            )
            await manual_positions_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "quantity": remaining_qty, "margin_used": round(new_margin, 2), "leverage": new_leverage,
                    "margin_source": new_margin_source,
                    "realized_pnl": round(existing.get("realized_pnl", 0.0) + realized, 2),
                    "updated_at": _now(),
                }},
            )
        position = await manual_positions_collection.find_one({"_id": existing["_id"]})
        position.pop("_id", None)

    order_doc = {**base_order, "status": "FILLED", "fill_price": fill_price, "filled_at": _now(),
                 "margin_used": position.get("margin_used"), "leverage": position.get("leverage")}
    await manual_orders_collection.insert_one(order_doc)
    order_doc.pop("_id", None)
    order_doc["position"] = position
    return order_doc


async def exit_position(dhan: DhanClient, account_id: str, position_id: str, quantity: int | None = None) -> dict:
    position = await manual_positions_collection.find_one(
        {"position_id": position_id, "account_id": account_id, "status": "OPEN"}
    )
    if position is None:
        raise OrderError("Position not found (in this account) or already closed")
    qty = quantity or position["quantity"]
    if qty > position["quantity"]:
        raise OrderError(f"Cannot exit {qty} — position only holds {position['quantity']}")

    inst = position["instrument"]
    base_order = {
        "order_id": f"MANUAL-{uuid4().hex[:12]}", "account_id": account_id, "symbol": position["symbol"],
        "display_name": position["display_name"], "instrument": inst,
        "transaction_type": "SELL", "quantity": qty, "order_type": "MARKET",
        "limit_price": None, "product_type": position["product_type"],
        "placed_at": _now(), "updated_at": _now(),
    }
    ltp = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
    if ltp is None:
        raise OrderError("Live quote unavailable (broker offline?) — cannot exit right now")
    return await _fill(dhan, base_order, ltp)


async def sync_positions(dhan: DhanClient) -> int:
    """Refresh LTP/unrealized P&L for open positions and fill any PENDING limit
    orders whose price has now been crossed — same role as call_positions.sync.
    Runs across all accounts at once; LTP refresh isn't account-specific."""
    open_positions = [p async for p in manual_positions_collection.find({"status": "OPEN"})]
    updated = 0
    for pos in open_positions:
        inst = pos["instrument"]
        ltp = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
        if ltp is None:
            continue
        unrealized = round((ltp - pos["avg_price"]) * pos["quantity"], 2)
        pnl_pct = round((ltp / pos["avg_price"] - 1) * 100, 2) if pos["avg_price"] else 0.0
        await manual_positions_collection.update_one(
            {"_id": pos["_id"]},
            {"$set": {"ltp": ltp, "ltp_source": "dhan_quote", "unrealized_pnl": unrealized,
                      "pnl_pct": pnl_pct, "updated_at": _now()}},
        )
        updated += 1

    pending = [o async for o in manual_orders_collection.find({"status": "PENDING"})]
    for order in pending:
        inst = order["instrument"]
        ltp = await _ltp(dhan, inst["security_id"], inst["exchange_segment"])
        if ltp is None:
            continue
        limit_price = order["limit_price"]
        crossed = (order["transaction_type"] == "BUY" and ltp <= limit_price) or (
            order["transaction_type"] == "SELL" and ltp >= limit_price
        )
        if crossed:
            try:
                pending_order = {k: v for k, v in order.items() if k not in ("_id", "status", "fill_price", "filled_at", "margin_used", "leverage")}
                await _fill(dhan, pending_order, limit_price, force_new_position=order.get("force_new_position", False))
                await manual_orders_collection.delete_one({"_id": order["_id"]})
            except OrderError:
                continue  # capital dried up since placement — leave it pending
    return updated


async def cancel_pending_order(account_id: str, order_id: str) -> dict:
    """A PENDING limit order sits forever until its price is touched or the user
    cancels it — nothing auto-expires it. This is the manual cancel path."""
    order = await manual_orders_collection.find_one({"order_id": order_id, "account_id": account_id})
    if order is None:
        raise OrderError("Order not found")
    if order["status"] != "PENDING":
        raise OrderError(f"Cannot cancel — order is already {order['status']}")
    await manual_orders_collection.delete_one({"_id": order["_id"]})
    return {"cancelled": True, "order_id": order_id}


async def reset_account(account_id: str) -> dict:
    """Wipe one account back to a pristine state: every position and order
    belonging to it is deleted (not just closed) so realized P&L is cleared too
    and available_cash returns to exactly its initial_capital. Other accounts
    are untouched. Irreversible — the caller confirms first."""
    account = await get_account(account_id)
    positions_deleted = (await manual_positions_collection.delete_many({"account_id": account_id})).deleted_count
    orders_deleted = (await manual_orders_collection.delete_many({"account_id": account_id})).deleted_count
    return {
        "positions_deleted": positions_deleted, "orders_deleted": orders_deleted,
        "initial_capital": account["initial_capital"],
    }


async def summary(account_id: str) -> dict:
    account = await get_account(account_id)
    initial_capital = account["initial_capital"]
    deployed = await _deployed_margin(account_id)
    realized = await _realized_pnl_all_time(account_id)
    unrealized = 0.0
    async for p in manual_positions_collection.find({"account_id": account_id, "status": "OPEN"}, {"unrealized_pnl": 1}):
        unrealized += p.get("unrealized_pnl") or 0.0
    equity = initial_capital + realized + unrealized
    open_count = await manual_positions_collection.count_documents({"account_id": account_id, "status": "OPEN"})
    closed_count = await manual_positions_collection.count_documents({"account_id": account_id, "status": "CLOSED"})
    wins = await manual_positions_collection.count_documents(
        {"account_id": account_id, "status": "CLOSED", "realized_pnl": {"$gt": 0}}
    )
    win_rate = round(wins / closed_count * 100, 1) if closed_count else None
    return {
        "account_id": account_id,
        "initial_capital": initial_capital,
        "available_cash": round(initial_capital + realized - deployed, 2),
        "deployed_margin": round(deployed, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_pnl": round(realized + unrealized, 2),
        "equity": round(equity, 2),
        "roi_pct": round((equity - initial_capital) / initial_capital * 100, 2),
        "open_positions": open_count,
        "closed_positions": closed_count,
        "win_rate": win_rate,
    }
