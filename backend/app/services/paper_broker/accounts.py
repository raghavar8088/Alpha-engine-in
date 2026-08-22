"""Accounts, funds and the ledger.

ONE ACCOUNT TRADES BOTH SEGMENTS. Stock Paper Trading and F&O Paper Trading are two views
of one broking account, not two wallets — which is how a real account works: an F&O short
blocks margin out of the same pool the equity buy would have used, and seeing that
competition is most of the point of paper-trading them together. Every position and order
carries a `segment` so each screen can filter, but the cash is shared.

THE CASH IDENTITY, and it is enforced rather than displayed:

    available = opening + realised_pnl - charges_paid - blocked_margin
    equity    = opening + realised_pnl - charges_paid + unrealised_pnl

`blocked_margin` is the sum of margin stored on each open position and each resting order,
not a live recomputation. A real broker blocks margin at the moment of the trade and does
not re-block it tick by tick; recomputing would also mean an F&O portfolio's margin moved
under the user between placing an order and seeing it, which is exactly the sort of
unexplainable balance change a ledger exists to prevent.

EVERY MOVEMENT WRITES A LEDGER ROW. A balance you cannot explain is a balance you cannot
trust, and paper accounts drift silently in ways real ones cannot because nobody reconciles
them against a bank.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from app.core.db import (
    pt_accounts_collection,
    pt_ledger_collection,
    pt_orders_collection,
    pt_positions_collection,
)
from app.services.paper_broker.core import (
    DEFAULT_CAPITAL,
    OPEN_STATUSES,
    OrderError,
    now_utc,
    today_ist,
)

logger = logging.getLogger("paper_broker.accounts")

DEFAULT_ACCOUNT_NAME = "Paper Trading Account"


async def ensure_default() -> dict:
    existing = await pt_accounts_collection.find_one({}, {"_id": 0})
    if existing:
        return existing
    return await create(DEFAULT_ACCOUNT_NAME, DEFAULT_CAPITAL)


async def create(name: str, capital: float | None = None) -> dict:
    name = (name or "").strip() or DEFAULT_ACCOUNT_NAME
    if await pt_accounts_collection.find_one({"name": name}):
        raise OrderError(f"An account named {name!r} already exists")
    doc = {
        "account_id": f"PT-{uuid4().hex[:10]}",
        "name": name,
        "opening_balance": float(capital or DEFAULT_CAPITAL),
        "created_at": now_utc(),
        "ts": now_utc(),
    }
    await pt_accounts_collection.insert_one(doc)
    await ledger(doc["account_id"], "OPENING", doc["opening_balance"],
                 f"Account opened with {doc['opening_balance']:,.0f}")
    doc.pop("_id", None)
    logger.info("paper broker: created account %s (%s)", name, doc["account_id"])
    return doc


async def list_accounts() -> list[dict]:
    rows = [a async for a in pt_accounts_collection.find({}, {"_id": 0})]
    if not rows:
        return [await ensure_default()]
    return rows


async def get(account_id: str) -> dict:
    acc = await pt_accounts_collection.find_one({"account_id": account_id}, {"_id": 0})
    if acc is None:
        raise OrderError(f"No paper account {account_id!r}")
    return acc


async def rename(account_id: str, name: str) -> dict:
    await get(account_id)
    await pt_accounts_collection.update_one(
        {"account_id": account_id}, {"$set": {"name": name.strip(), "ts": now_utc()}})
    return await get(account_id)


async def ledger(account_id: str, kind: str, amount: float, note: str,
                 ref: str | None = None) -> None:
    """One row per cash movement. `amount` is signed: credits positive, debits negative."""
    await pt_ledger_collection.insert_one({
        "entry_id": f"L-{uuid4().hex[:12]}",
        "account_id": account_id,
        "kind": kind,                 # OPENING | CHARGES | REALISED | MARGIN_BLOCK | MARGIN_RELEASE
        "amount": round(float(amount), 2),
        "note": note,
        "ref": ref,
        "date": today_ist(),
        "ts": now_utc(),
    })


async def blocked_margin(account_id: str) -> float:
    """Margin held against open positions and orders still waiting to fill."""
    total = 0.0
    async for p in pt_positions_collection.find(
            {"account_id": account_id, "status": "OPEN"}, {"margin_blocked": 1}):
        total += float(p.get("margin_blocked") or 0)
    async for o in pt_orders_collection.find(
            {"account_id": account_id, "status": {"$in": list(OPEN_STATUSES)}},
            {"margin_blocked": 1}):
        total += float(o.get("margin_blocked") or 0)
    return round(total, 2)


async def realised_and_charges(account_id: str) -> tuple[float, float]:
    """(realised P&L, charges paid) across the whole life of the account."""
    realised = charges = 0.0
    async for e in pt_ledger_collection.find(
            {"account_id": account_id, "kind": {"$in": ["REALISED", "CHARGES"]}},
            {"kind": 1, "amount": 1}):
        if e["kind"] == "REALISED":
            realised += float(e["amount"])
        else:
            charges += abs(float(e["amount"]))
    return round(realised, 2), round(charges, 2)


async def funds(account_id: str, unrealised: float = 0.0) -> dict:
    """The Funds screen: what a broker shows you before it lets you place an order."""
    acc = await get(account_id)
    realised, charges = await realised_and_charges(account_id)
    blocked = await blocked_margin(account_id)
    opening = float(acc["opening_balance"])

    available = opening + realised - charges - blocked
    equity = opening + realised - charges + unrealised
    return {
        "account_id": account_id,
        "name": acc["name"],
        "opening_balance": round(opening, 2),
        "realised_pnl": realised,
        "charges_paid": charges,
        "blocked_margin": blocked,
        "available_margin": round(available, 2),
        "unrealised_pnl": round(unrealised, 2),
        "equity": round(equity, 2),
        "net_pnl": round(realised - charges + unrealised, 2),
        "roi_pct": round((realised - charges + unrealised) / opening * 100, 2) if opening else 0.0,
    }


async def can_afford(account_id: str, margin: float) -> tuple[bool, str]:
    """Would this order clear the margin check? Returns (ok, why-not).

    Returned rather than raised: a broker records an unaffordable order as REJECTED in the
    order book with a reason. Losing the attempt entirely would hide the most useful thing
    the paper account can teach — how often the strategy runs out of money.
    """
    f = await funds(account_id)
    if margin <= f["available_margin"]:
        return True, ""
    return False, (
        f"Insufficient margin: needs {margin:,.2f} but only {f['available_margin']:,.2f} "
        f"is available ({f['blocked_margin']:,.2f} already blocked)")


async def reset(account_id: str) -> dict:
    """Wipe the account back to its opening balance.

    Deliberately destructive and deliberately explicit: this is how you start a fresh
    experiment, and the alternative — carrying trades from a strategy you have since
    changed — silently pollutes every statistic the account produces.
    """
    await get(account_id)
    o = await pt_orders_collection.delete_many({"account_id": account_id})
    p = await pt_positions_collection.delete_many({"account_id": account_id})
    from app.core.db import pt_holdings_collection, pt_trades_collection
    t = await pt_trades_collection.delete_many({"account_id": account_id})
    h = await pt_holdings_collection.delete_many({"account_id": account_id})
    await pt_ledger_collection.delete_many({"account_id": account_id})

    acc = await get(account_id)
    await ledger(account_id, "OPENING", acc["opening_balance"],
                 f"Account reset to {acc['opening_balance']:,.0f}")
    return {"orders_cleared": o.deleted_count, "positions_cleared": p.deleted_count,
            "trades_cleared": t.deleted_count, "holdings_cleared": h.deleted_count}
