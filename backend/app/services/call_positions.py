"""Trading Call Positions — an automatic paper-trading ledger over the Trading
Calls module. The instant a call is generated it is booked as a paper position
sized off a shared capital pool (default ₹1 crore); SL/TP are taken directly
from the call's own target/stoploss rather than recomputed, and the position
closes at the same price/moment its parent call rolls to a terminal status
(TARGET_HIT / STOPLOSS / EXPIRED / manual CLOSED). Paper only — no live orders.
"""

import os
from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import trading_call_positions_collection, trading_calls_collection

INITIAL_CAPITAL = float(os.getenv("CALL_POSITIONS_INITIAL_CAPITAL", "10000000"))  # ₹1 crore
CAPITAL_PER_TRADE_PCT = float(os.getenv("CALL_POSITIONS_CAPITAL_PER_TRADE_PCT", "0.02"))
MAX_LOTS_PER_TRADE = int(os.getenv("CALL_POSITIONS_MAX_LOTS", "20"))

TERMINAL_STATUSES = {"TARGET_HIT", "STOPLOSS", "EXPIRED", "CLOSED"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _deployed_capital() -> float:
    total = 0.0
    async for p in trading_call_positions_collection.find({"status": "OPEN"}, {"capital_deployed": 1}):
        total += p.get("capital_deployed", 0.0)
    return total


async def _realized_pnl_all_time() -> float:
    total = 0.0
    async for p in trading_call_positions_collection.find({"status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    return total


async def available_cash() -> float:
    deployed = await _deployed_capital()
    realized = await _realized_pnl_all_time()
    return INITIAL_CAPITAL + realized - deployed


def _size(entry_price: float, lot_size: int, budget: float, cash: float) -> tuple[int, int]:
    """(lots, units); units = lots * lot_size. Equities (lot_size 1) size in shares
    directly with no lot cap; F&O/futures/commodity lots are capped at MAX_LOTS_PER_TRADE."""
    lot_size = lot_size or 1
    unit_cost = entry_price * lot_size
    if unit_cost <= 0:
        return 0, 0
    cap = min(budget, cash)
    lots = int(cap // unit_cost)
    if lot_size > 1:
        lots = min(lots, MAX_LOTS_PER_TRADE)
    if lots < 1:
        return 0, 0
    return lots, lots * lot_size


async def open_position_for_call(call: dict) -> dict | None:
    """Books a paper position the instant a call is created. Returns None if a
    position for this call already exists, or if there isn't enough capital left
    in the pool to size even one share/lot."""
    existing = await trading_call_positions_collection.find_one({"call_id": call["call_id"]})
    if existing is not None:
        return None

    cash = await available_cash()
    budget = INITIAL_CAPITAL * CAPITAL_PER_TRADE_PCT
    inst = call.get("instrument") or {}
    lot_size = inst.get("lot_size") or 1
    entry = call["entry_price"]
    lots, units = _size(entry, lot_size, budget, cash)
    if units < 1:
        return None

    doc = {
        "position_id": uuid4().hex[:12],
        "call_id": call["call_id"],
        "segment": call["segment"],
        "horizon": call["horizon"],
        "side": call["side"],
        "symbol": call["symbol"],
        "display_name": call["display_name"],
        "instrument": call.get("instrument"),
        "entry_price": entry,
        "lot_size": lot_size,
        "lots": lots,
        "qty": units,
        "capital_deployed": round(entry * units, 2),
        "target": call["target"],
        "stoploss": call["stoploss"],
        "ltp": call["ltp"],
        "ltp_source": call["ltp_source"],
        "unrealized_pnl": 0.0,
        "pnl_pct": call.get("pnl_pct"),
        "realized_pnl": None,
        "exit_price": None,
        "status": "OPEN",
        "opened_at": _now(),
        "updated_at": _now(),
        "closed_at": None,
    }
    await trading_call_positions_collection.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def open_positions_for_calls(calls: list[dict]) -> int:
    opened = 0
    for call in calls:
        if await open_position_for_call(call) is not None:
            opened += 1
    return opened


async def sync_positions() -> int:
    """Mirror each open position's LTP/PnL off its parent call, and close it the
    moment the parent call rolls to a terminal status — same price, same event,
    so exits never drift out of sync with the call they were opened from."""
    cursor = trading_call_positions_collection.find({"status": "OPEN"})
    open_positions = [p async for p in cursor]
    if not open_positions:
        return 0

    call_ids = [p["call_id"] for p in open_positions]
    calls = {c["call_id"]: c async for c in trading_calls_collection.find({"call_id": {"$in": call_ids}})}

    updated = 0
    for pos in open_positions:
        call = calls.get(pos["call_id"])
        if call is None:
            continue
        sign = 1 if pos["side"] == "BUY" else -1
        ltp = call["ltp"]
        changes = {
            "ltp": ltp,
            "ltp_source": call["ltp_source"],
            "unrealized_pnl": round(sign * (ltp - pos["entry_price"]) * pos["qty"], 2),
            "pnl_pct": call.get("pnl_pct"),
            "target": call["target"],
            "stoploss": call["stoploss"],
            "updated_at": _now(),
        }
        if call["status"] in TERMINAL_STATUSES:
            changes["status"] = call["status"]
            changes["exit_price"] = ltp
            changes["realized_pnl"] = round(sign * (ltp - pos["entry_price"]) * pos["qty"], 2)
            changes["unrealized_pnl"] = 0.0
            changes["closed_at"] = call.get("closed_at") or _now()
        await trading_call_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
        updated += 1
    return updated


async def summary() -> dict:
    deployed = await _deployed_capital()
    realized = await _realized_pnl_all_time()
    unrealized = 0.0
    async for p in trading_call_positions_collection.find({"status": "OPEN"}, {"unrealized_pnl": 1}):
        unrealized += p.get("unrealized_pnl") or 0.0
    equity = INITIAL_CAPITAL + realized + unrealized
    open_count = await trading_call_positions_collection.count_documents({"status": "OPEN"})
    closed_count = await trading_call_positions_collection.count_documents({"status": {"$ne": "OPEN"}})
    return {
        "initial_capital": INITIAL_CAPITAL,
        "available_cash": round(INITIAL_CAPITAL + realized - deployed, 2),
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "equity": round(equity, 2),
        "open_positions": open_count,
        "closed_positions": closed_count,
    }
