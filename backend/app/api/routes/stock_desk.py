"""Stock-option Pre-Live desks API — the stock twins of the NIFTY buying/selling desks.

  GET  /api/stock-desk/{side}/summary       capital tiles + breaker + universe
  GET  /api/stock-desk/{side}/leaderboard   per-strategy forward scoreboard
  GET  /api/stock-desk/{side}/positions     open (or closed) paper positions
  GET  /api/stock-desk/{side}/trades        closed-trade blotter
  POST /api/stock-desk/{side}/run           run one scan+manage cycle now
  POST /api/stock-desk/refresh-contracts    reload NSE stock options from Angel

`side` is "buying" or "selling".
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.api.deps import get_current_user
from app.core.db import stock_desk_trades_collection
from app.services.stock_desk import (
    BUYING,
    SELLING,
    StockDeskError,
    leaderboard as desk_leaderboard,
    positions as desk_positions,
    run_cycle,
    strategy_ids,
    summary as desk_summary,
)
from app.services.stock_options import option_underlyings, refresh_stock_options

router = APIRouter(prefix="/api/stock-desk", tags=["stock-desk"])


def _side(side: str) -> str:
    if side not in (BUYING, SELLING):
        raise HTTPException(status_code=422, detail=f"side must be '{BUYING}' or '{SELLING}'")
    return side


@router.get("/underlyings")
async def underlyings(_u: dict = Depends(get_current_user)):
    """Every stock that currently has listed options (the pool the universe draws from)."""
    u = await option_underlyings()
    return {"count": len(u), "underlyings": u}


@router.post("/refresh-contracts")
async def refresh_contracts(_u: dict = Depends(get_current_user)):
    return await refresh_stock_options()


@router.get("/{side}/summary")
async def summary_endpoint(side: str = Path(...), _u: dict = Depends(get_current_user)):
    return await desk_summary(_side(side))


@router.get("/{side}/leaderboard")
async def leaderboard_endpoint(
    side: str = Path(...),
    limit: int = Query(300, ge=1, le=1000),
    _u: dict = Depends(get_current_user),
):
    s = _side(side)
    return {"leaderboard": await desk_leaderboard(s, limit), "strategy_count": len(strategy_ids(s))}


@router.get("/{side}/positions")
async def positions_endpoint(
    side: str = Path(...),
    status: str = Query("OPEN", description="OPEN | CLOSED"),
    limit: int = Query(300, ge=1, le=1000),
    _u: dict = Depends(get_current_user),
):
    s = _side(side)
    return {"positions": await desk_positions(s, status, limit), "summary": await desk_summary(s)}


@router.get("/{side}/trades")
async def trades_endpoint(
    side: str = Path(...),
    limit: int = Query(200, ge=1, le=1000),
    _u: dict = Depends(get_current_user),
):
    s = _side(side)
    rows = []
    async for t in stock_desk_trades_collection.find({"side": s}).sort("closed_at", -1).limit(limit):
        t.pop("_id", None)
        for k in ("opened_at", "closed_at"):
            if t.get(k):
                t[k] = t[k].isoformat()
        rows.append(t)
    return {"trades": rows}


@router.post("/{side}/run")
async def run_endpoint(side: str = Path(...), _u: dict = Depends(get_current_user)):
    try:
        return await run_cycle(_side(side))
    except StockDeskError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
