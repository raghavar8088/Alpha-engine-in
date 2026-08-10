"""Live Paper Buying API — the 5 Pre-Live leaderboard winners on a Rs50,000 book.

  GET  /api/live-paper/summary       capital tiles + market state
  GET  /api/live-paper/leaderboard   the 5 strategies, ranked
  GET  /api/live-paper/positions     open or closed positions
  GET  /api/live-paper/trades        closed-trade blotter
  GET  /api/live-paper/daily         realised P&L per session
  POST /api/live-paper/run           run one cycle now (?force=true outside market hours)
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services.live_paper_buying import (
    daily_pnl,
    leaderboard as lp_leaderboard,
    positions as lp_positions,
    run_cycle,
    summary as lp_summary,
    trades as lp_trades,
)

router = APIRouter(prefix="/api/live-paper", tags=["live-paper"])


@router.get("/summary")
async def summary_endpoint(_u: dict = Depends(get_current_user)):
    return await lp_summary()


@router.get("/leaderboard")
async def leaderboard_endpoint(_u: dict = Depends(get_current_user)):
    return {"leaderboard": await lp_leaderboard()}


@router.get("/positions")
async def positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED"),
    limit: int = Query(300, ge=1, le=1000),
    _u: dict = Depends(get_current_user),
):
    return {"positions": await lp_positions(status, limit), "summary": await lp_summary()}


@router.get("/trades")
async def trades_endpoint(limit: int = Query(300, ge=1, le=1000), _u: dict = Depends(get_current_user)):
    return {"trades": await lp_trades(limit)}


@router.get("/daily")
async def daily_endpoint(limit: int = Query(60, ge=1, le=365), _u: dict = Depends(get_current_user)):
    return {"daily": await daily_pnl(limit)}


@router.post("/run")
async def run_endpoint(
    force: bool = Query(False, description="run outside market hours"),
    _u: dict = Depends(get_current_user),
):
    return await run_cycle(force=force)
