"""Live Trading desk API — the REAL-MONEY twin of the Live Intraday shortlist.

  GET  /api/live-trading/summary              capital tiles + armed / kill-switch state
  GET  /api/live-trading/leaderboard          the 8 strategies, ranked, each with its enabled flag
  GET  /api/live-trading/positions            open/closed REAL positions
  GET  /api/live-trading/trades               closed-trade blotter (with broker order ids)
  POST /api/live-trading/arm                  {armed: bool}  — the green/red LIVE toggle
  POST /api/live-trading/kill-switch          {active: bool} — halt all new orders instantly
  POST /api/live-trading/strategy-enabled     {strategy_id, enabled} — per-strategy toggle
  POST /api/live-trading/panic-close-all      square off everything, disarm, kill-switch on
  POST /api/live-trading/run                  manually trigger one scan+manage cycle
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import (
    live_trading_positions_collection,
    live_trading_trades_collection,
)
from app.services.dhan_client import DhanClient
from app.services.live_trading_engine import (
    LiveTradingError,
    angel_account,
    get_state,
    leaderboard as live_leaderboard,
    open_positions,
    panic_close_all,
    run_cycle,
    set_armed,
    set_kill_switch,
    set_strategy_enabled,
    summary as live_summary,
)

router = APIRouter(prefix="/api/live-trading", tags=["live-trading"])


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


class ArmRequest(BaseModel):
    armed: bool


class KillSwitchRequest(BaseModel):
    active: bool


class StrategyEnabledRequest(BaseModel):
    strategy_id: str
    enabled: bool


@router.get("/summary")
async def summary_endpoint(current_user: dict = Depends(get_current_user)):
    return await live_summary()


@router.get("/angel-account")
async def angel_account_endpoint(
    force: bool = Query(False, description="bypass the short funds cache"),
    current_user: dict = Depends(get_current_user),
):
    """The REAL Angel One account — funds and the broker's own open positions."""
    return await angel_account(force=force)


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
    cursor = live_trading_positions_collection.find(query).sort("opened_at", -1).limit(limit)
    positions = [_serialize(d, ("opened_at", "updated_at", "closed_at")) async for d in cursor]
    return {"positions": positions, "open": await open_positions(), "summary": await live_summary()}


@router.get("/trades")
async def list_trades(limit: int = Query(200, ge=1, le=1000), current_user: dict = Depends(get_current_user)):
    cursor = live_trading_trades_collection.find({}).sort("closed_at", -1).limit(limit)
    trades = [_serialize(d, ("opened_at", "closed_at")) async for d in cursor]
    return {"trades": trades}


@router.post("/arm")
async def arm(req: ArmRequest, current_user: dict = Depends(get_current_user)):
    # Arming does NOT place orders here — it only flips the gate. Orders are placed by the
    # scan cycle (scheduled tick / manual /run) while armed. Ships disarmed.
    state = await set_armed(req.armed, reason=None if req.armed else "manual disarm")
    return {"state": state, "summary": await live_summary()}


@router.post("/kill-switch")
async def kill_switch(req: KillSwitchRequest, current_user: dict = Depends(get_current_user)):
    state = await set_kill_switch(req.active)
    return {"state": state, "summary": await live_summary()}


@router.post("/strategy-enabled")
async def strategy_enabled(req: StrategyEnabledRequest, current_user: dict = Depends(get_current_user)):
    try:
        result = await set_strategy_enabled(req.strategy_id, req.enabled)
    except LiveTradingError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    return {"result": result, "leaderboard": await live_leaderboard()}


@router.post("/panic-close-all")
async def panic(current_user: dict = Depends(get_current_user)):
    dhan = await _optional_dhan(str(current_user["_id"]))
    result = await panic_close_all(dhan)
    return {"result": result, "state": await get_state(), "summary": await live_summary()}


@router.post("/run")
async def run_now(current_user: dict = Depends(get_current_user)):
    dhan = await _optional_dhan(str(current_user["_id"]))
    result = await run_cycle(dhan)
    result["broker_connected"] = dhan is not None
    return result
