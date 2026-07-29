"""Read-only API for the option-SELLING pre-live paper desk.

A separate router from `prelive.py` rather than a `?desk=selling` parameter on it. The
two desks share a shape but nothing else: selling carries margin, credit, multi-leg
structures and a circuit breaker that buying has no concept of, and their capital pools
are deliberately isolated. A shared endpoint would have to either return the union of
both schemas (making every field optional and every consumer guess) or silently omit the
selling-specific numbers that are the whole point of the desk. Separate routes keep each
response honest about which desk it describes.

Everything here reads `prelive_selling_*`. The daemon owns all writes.
"""

import os

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.db import db

router = APIRouter(prefix="/api/prelive-selling", tags=["prelive-selling"])

trades_collection = db["prelive_selling_trades"]
positions_collection = db["prelive_selling_positions"]
equity_collection = db["prelive_selling_equity"]
daily_pnl_collection = db["prelive_selling_daily_pnl"]
scores_collection = db["prelive_selling_strategy_scores"]
state_collection = db["prelive_selling_state"]


def _clean(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


@router.get("/status")
async def status(_current_user: dict = Depends(get_current_user)):
    """Engine heartbeat, capital, margin deployed, and open structures.

    `open_structures` carries the live mark of each position. For a selling desk that is
    not a nicety: a structure's risk is in what it would COST to buy back right now, and
    a page that showed only entry credit would look calm while the book was on fire.
    """
    state = _clean(await state_collection.find_one({"_id": "selling"})) or {
        "running": False, "heartbeat": None, "universe_size": 0,
        "open_structures": 0, "breaker_tripped": False,
    }
    positions = []
    async for doc in positions_collection.find({}).sort("entry_ts", 1):
        positions.append(_clean(doc))

    realized = 0.0
    async for doc in trades_collection.aggregate(
        [{"$group": {"_id": None, "s": {"$sum": "$pnl"}}}]
    ):
        realized = float(doc.get("s") or 0.0)

    unrealized = sum(p.get("unrealized") or 0.0 for p in positions)
    margin = sum(p.get("margin") or 0.0 for p in positions)
    credit_open = sum((p.get("credit") or 0.0) * (p.get("qty") or 0) for p in positions)

    sessions = await daily_pnl_collection.count_documents({})
    return {
        "desk": "selling",
        **state,
        "realized_all_time": round(realized, 2),
        "unrealized": round(unrealized, 2),
        "margin_deployed": round(margin, 2),
        "credit_at_risk": round(credit_open, 2),
        "sessions_traded": sessions,
        "open_structures_detail": positions,
    }


@router.get("/leaderboard")
async def leaderboard(_current_user: dict = Depends(get_current_user)):
    """Per-strategy running record on this desk.

    Profit factor is computed here rather than stored so it always reflects the current
    gross win/loss totals. Win rate is returned but is NOT what this desk is judged on —
    the same reason the qualification gate ignores it.
    """
    per_cap = float(os.getenv("PRELIVE_SELLING_PER_STRATEGY_CAPITAL", "1000000"))
    rows = []
    async for doc in scores_collection.find({}).sort("net_pnl", -1):
        doc = _clean(doc)
        wins, losses = doc.get("wins", 0), doc.get("losses", 0)
        trades = wins + losses
        gross_win, gross_loss = doc.get("gross_win", 0.0), doc.get("gross_loss", 0.0)
        doc["trades"] = trades
        doc["win_rate"] = round(wins / trades, 4) if trades else None
        doc["profit_factor"] = round(gross_win / gross_loss, 3) if gross_loss > 0 else None
        doc["allocated_capital"] = round(per_cap + (doc.get("net_pnl") or 0.0), 2)
        rows.append(doc)
    return rows


@router.get("/trades")
async def trades(
    limit: int = Query(100, ge=1, le=500),
    _current_user: dict = Depends(get_current_user),
):
    """Closed multi-leg paper trades, newest first. Legs are returned in full so the
    blotter can show what was actually sold, not just a strategy name."""
    out = []
    async for doc in trades_collection.find({}).sort("exit_ts", -1).limit(limit):
        out.append(_clean(doc))
    return out


@router.get("/equity")
async def equity(
    limit: int = Query(500, ge=1, le=5000),
    _current_user: dict = Depends(get_current_user),
):
    out = []
    async for doc in equity_collection.find({}).sort("ts", -1).limit(limit):
        out.append(_clean(doc))
    out.reverse()  # chronological for charting
    return out


@router.get("/daily")
async def daily(
    limit: int = Query(90, ge=1, le=365),
    _current_user: dict = Depends(get_current_user),
):
    """One doc per session, newest first. `open_carried` is the count of structures held
    overnight — on a swing desk that is normal, not a leak, and the page says so."""
    out = []
    async for doc in daily_pnl_collection.find({}).sort("session", -1).limit(limit):
        out.append(_clean(doc))
    return out
