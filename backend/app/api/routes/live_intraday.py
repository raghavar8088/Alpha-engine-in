"""Live Intraday desk API — the curated ₹80,000 shortlist (8 strategies, ₹10k each)
inside the Intraday Stocks module, paper-trading on the live Angel-One feed.

  GET  /api/live-intraday/summary      capital tiles for the ₹80k desk
  GET  /api/live-intraday/leaderboard  the 8 selected strategies, ranked
  GET  /api/live-intraday/positions    open/closed paper positions
  GET  /api/live-intraday/trades       closed-trade blotter
  POST /api/live-intraday/run          manually trigger one scan+manage cycle
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import (
    live_intraday_positions_collection,
    live_intraday_state_collection,
    live_intraday_trades_collection,
)
from app.services.dhan_client import DhanClient
from app.services.live_intraday_engine import (
    STATE_ID,
    leaderboard as live_leaderboard,
    run_cycle,
    summary as live_summary,
)

router = APIRouter(prefix="/api/live-intraday", tags=["live-intraday"])


async def _optional_dhan(user_id: str) -> DhanClient | None:
    try:
        return await _get_dhan_client(user_id)
    except HTTPException:
        return None


def _serialize(doc: dict, ts_fields: tuple[str, ...]) -> dict:
    doc.pop("_id", None)
    for key in ts_fields:
        if doc.get(key) is not None:
            doc[key] = doc[key].isoformat()
    return doc


@router.get("/summary")
async def summary_endpoint(current_user: dict = Depends(get_current_user)):
    snap = await live_summary()
    state = await live_intraday_state_collection.find_one({"_id": STATE_ID}) or {}
    snap["last_run_at"] = state["last_run_at"].isoformat() if state.get("last_run_at") else None
    snap["broker_connected"] = state.get("broker_connected", False)
    snap["angel_configured"] = state.get("angel_configured", False)
    return snap


@router.get("/leaderboard")
async def leaderboard_endpoint(current_user: dict = Depends(get_current_user)):
    return {"leaderboard": await live_leaderboard()}


@router.get("/positions")
async def list_positions(
    strategy_id: str | None = Query(None),
    status: str | None = Query(None, description="OPEN | CLOSED"),
    limit: int = Query(300, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    query: dict = {}
    if strategy_id:
        query["strategy_id"] = strategy_id
    if status:
        query["status"] = status.upper()
    cursor = live_intraday_positions_collection.find(query).sort("opened_at", -1).limit(limit)
    positions = [_serialize(d, ("opened_at", "updated_at", "closed_at")) async for d in cursor]
    return {"positions": positions, "summary": await live_summary()}


@router.get("/trades")
async def list_trades(limit: int = Query(200, ge=1, le=1000), current_user: dict = Depends(get_current_user)):
    cursor = live_intraday_trades_collection.find({}).sort("closed_at", -1).limit(limit)
    trades = [_serialize(d, ("opened_at", "closed_at")) async for d in cursor]
    return {"trades": trades}


@router.post("/run")
async def run_now(current_user: dict = Depends(get_current_user)):
    dhan = await _optional_dhan(str(current_user["_id"]))
    result = await run_cycle(dhan)
    result["broker_connected"] = dhan is not None
    return result
