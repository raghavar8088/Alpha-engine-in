"""Momentum Trading API — intraday cash-equity momentum (long 2% up / short 2% down).

  GET  /api/momentum-trading/summary     capital tiles, checkpoints, rule set
  GET  /api/momentum-trading/preview     who would be taken right now (read-only)
  GET  /api/momentum-trading/positions   open or closed positions
  GET  /api/momentum-trading/trades      closed-trade blotter
  GET  /api/momentum-trading/daily       realised P&L per session
  POST /api/momentum-trading/run         run a cycle now (?checkpoint=09:20 to force one)
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services.momentum_trading import (
    daily_pnl,
    positions as mt_positions,
    preview as mt_preview,
    run_cycle,
    summary as mt_summary,
    trades as mt_trades,
)

router = APIRouter(prefix="/api/momentum-trading", tags=["momentum-trading"])


@router.get("/summary")
async def summary_endpoint(_u: dict = Depends(get_current_user)):
    return await mt_summary()


@router.get("/preview")
async def preview_endpoint(_u: dict = Depends(get_current_user)):
    return await mt_preview()


@router.get("/positions")
async def positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED"),
    limit: int = Query(300, ge=1, le=1000),
    _u: dict = Depends(get_current_user),
):
    return {"positions": await mt_positions(status, limit), "summary": await mt_summary()}


@router.get("/trades")
async def trades_endpoint(limit: int = Query(300, ge=1, le=1000), _u: dict = Depends(get_current_user)):
    return {"trades": await mt_trades(limit)}


@router.get("/daily")
async def daily_endpoint(limit: int = Query(60, ge=1, le=365), _u: dict = Depends(get_current_user)):
    return {"daily": await daily_pnl(limit)}


@router.post("/run")
async def run_endpoint(
    checkpoint: str | None = Query(None, description="force a checkpoint, e.g. 09:20"),
    _u: dict = Depends(get_current_user),
):
    return await run_cycle(force_checkpoint=checkpoint)
