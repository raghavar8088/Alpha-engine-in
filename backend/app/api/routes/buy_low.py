"""Buy Low Options API — buy a cheap OTM call on F&O stocks that crashed today.

  GET  /api/buy-low/summary     capital tiles + the rule set in force
  GET  /api/buy-low/fallers     live board of today's biggest F&O fallers
  GET  /api/buy-low/positions   open or closed positions
  GET  /api/buy-low/trades      closed-trade blotter
  GET  /api/buy-low/signals     every faller evaluated, taken or skipped (with the reason)
  GET  /api/buy-low/daily       realised P&L per session
  POST /api/buy-low/run         run one cycle now (?force=true to bypass the 3 PM window)
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services.buy_low_options import (
    daily_pnl,
    fallers as bl_fallers,
    positions as bl_positions,
    run_cycle,
    signals as bl_signals,
    summary as bl_summary,
    trades as bl_trades,
)

router = APIRouter(prefix="/api/buy-low", tags=["buy-low"])


@router.get("/summary")
async def summary_endpoint(_u: dict = Depends(get_current_user)):
    return await bl_summary()


@router.get("/fallers")
async def fallers_endpoint(limit: int = Query(40, ge=1, le=250), _u: dict = Depends(get_current_user)):
    return {"fallers": await bl_fallers(limit)}


@router.get("/positions")
async def positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED"),
    limit: int = Query(500, ge=1, le=1000),
    _u: dict = Depends(get_current_user),
):
    return {"positions": await bl_positions(status, limit), "summary": await bl_summary()}


@router.get("/trades")
async def trades_endpoint(limit: int = Query(500, ge=1, le=1000), _u: dict = Depends(get_current_user)):
    return {"trades": await bl_trades(limit)}


@router.get("/signals")
async def signals_endpoint(limit: int = Query(500, ge=1, le=1000), _u: dict = Depends(get_current_user)):
    return {"signals": await bl_signals(limit)}


@router.get("/daily")
async def daily_endpoint(limit: int = Query(60, ge=1, le=365), _u: dict = Depends(get_current_user)):
    return {"daily": await daily_pnl(limit)}


@router.post("/run")
async def run_endpoint(
    force: bool = Query(False, description="bypass the 3 PM entry window"),
    _u: dict = Depends(get_current_user),
):
    return await run_cycle(force_scan=force)
