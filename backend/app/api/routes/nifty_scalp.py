"""NIFTY 50 Option Scalping API — 400 candle/indicator strategies (50 templates x 8
timeframes) buying near-expiry ATM NIFTY options on Rs2,00,000 each.

  GET  /api/nifty-scalp/summary      desk capital, ROI, costs, expiry in use
  GET  /api/nifty-scalp/leaderboard  every strategy ranked, filterable by timeframe
  GET  /api/nifty-scalp/timeframes   which HORIZON is working, 50 strategies aggregated
  GET  /api/nifty-scalp/positions    open/closed option positions
  GET  /api/nifty-scalp/signals      signal history, including ones not funded
  GET  /api/nifty-scalp/daily        per-day realised P&L, fees and ROI
  POST /api/nifty-scalp/run          trigger one manage+scan cycle
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services.nifty_scalp_engine import (
    daily as ns_daily,
    leaderboard as ns_leaderboard,
    positions as ns_positions,
    run_cycle,
    signals as ns_signals,
    summary as ns_summary,
    timeframe_stats,
)

router = APIRouter(prefix="/api/nifty-scalp", tags=["nifty-scalp"])


@router.get("/summary")
async def summary_endpoint(current_user: dict = Depends(get_current_user)):
    return await ns_summary()


@router.get("/leaderboard")
async def leaderboard_endpoint(
    timeframe: str | None = Query(None, description="1m|5m|10m|15m|30m|1h|4h|1d"),
    limit: int = Query(400, ge=1, le=400),
    current_user: dict = Depends(get_current_user),
):
    return {"leaderboard": await ns_leaderboard(timeframe, limit)}


@router.get("/timeframes")
async def timeframes_endpoint(current_user: dict = Depends(get_current_user)):
    return {"timeframes": await timeframe_stats()}


@router.get("/positions")
async def positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED | ALL"),
    timeframe: str | None = Query(None),
    limit: int = Query(300, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    return {"positions": await ns_positions(status, limit, timeframe),
            "summary": await ns_summary()}


@router.get("/signals")
async def signals_endpoint(
    limit: int = Query(200, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    return {"signals": await ns_signals(limit)}


@router.get("/daily")
async def daily_endpoint(
    limit: int = Query(60, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
):
    return {"daily": await ns_daily(limit)}


@router.post("/run")
async def run_endpoint(current_user: dict = Depends(get_current_user)):
    return await run_cycle()
