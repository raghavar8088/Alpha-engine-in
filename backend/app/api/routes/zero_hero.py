"""Zero Hero Trades API — expiry-day deep-OTM index option desk (paper).

  GET  /api/zero-hero/summary        capital tiles + which indices expire today
  GET  /api/zero-hero/leaderboard    all 50 strategies, ranked (PF/expectancy matter here)
  GET  /api/zero-hero/positions      open or closed positions
  GET  /api/zero-hero/trades         closed-trade blotter with the achieved multiple
  GET  /api/zero-hero/signals        signal history, including signals NOT taken and why
  GET  /api/zero-hero/daily          realised P&L per session
  POST /api/zero-hero/run            run one scan+manage cycle now
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services.zero_hero import (
    daily_pnl,
    leaderboard as zh_leaderboard,
    positions as zh_positions,
    run_cycle,
    signals as zh_signals,
    summary as zh_summary,
    trades as zh_trades,
)

router = APIRouter(prefix="/api/zero-hero", tags=["zero-hero"])


@router.get("/summary")
async def summary_endpoint(_u: dict = Depends(get_current_user)):
    return await zh_summary()


@router.get("/leaderboard")
async def leaderboard_endpoint(_u: dict = Depends(get_current_user)):
    return {"leaderboard": await zh_leaderboard()}


@router.get("/positions")
async def positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED"),
    limit: int = Query(300, ge=1, le=1000),
    _u: dict = Depends(get_current_user),
):
    return {"positions": await zh_positions(status, limit), "summary": await zh_summary()}


@router.get("/trades")
async def trades_endpoint(limit: int = Query(300, ge=1, le=1000), _u: dict = Depends(get_current_user)):
    return {"trades": await zh_trades(limit)}


@router.get("/signals")
async def signals_endpoint(
    limit: int = Query(300, ge=1, le=1000),
    taken: bool | None = Query(None, description="filter to taken / not-taken signals"),
    _u: dict = Depends(get_current_user),
):
    return {"signals": await zh_signals(limit, taken)}


@router.get("/daily")
async def daily_endpoint(limit: int = Query(60, ge=1, le=365), _u: dict = Depends(get_current_user)):
    return {"daily": await daily_pnl(limit)}


@router.post("/run")
async def run_endpoint(_u: dict = Depends(get_current_user)):
    return await run_cycle()
