"""Swing Trading API — you name the buy price, the desk waits and fills it.

  GET    /api/swing/search?q=       every listed Indian equity Angel can quote
  GET    /api/swing/summary         capital, equity, and the three ROI denominators
  GET    /api/swing/watchlist       buy orders waiting for their price
  POST   /api/swing/watch           add one: {symbol, buy_price, sl_pct?, tp_pct?}
  PATCH  /api/swing/watch/{id}      change buy price / SL / TP before it fills
  DELETE /api/swing/watch/{id}      cancel a waiting order
  GET    /api/swing/positions       open or closed
  PATCH  /api/swing/positions/{id}  change SL / TP on a LIVE position
  GET    /api/swing/equity          equity curve
  GET    /api/swing/daily           per-day P&L and ROI
  POST   /api/swing/run             trigger one watch+manage cycle now
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.services import swing_trading as sw

router = APIRouter(prefix="/api/swing", tags=["swing-trading"])


class WatchIn(BaseModel):
    symbol: str
    buy_price: float = Field(gt=0)
    sl_pct: float | None = Field(default=None, gt=0, lt=100)
    tp_pct: float | None = Field(default=None, gt=0)
    # How far past your price a gap may open and still be filled. 0 = exact price only.
    drift_pct: float | None = Field(default=None, ge=0, le=25)
    note: str = ""


class WatchEdit(BaseModel):
    buy_price: float | None = Field(default=None, gt=0)
    sl_pct: float | None = Field(default=None, gt=0, lt=100)
    tp_pct: float | None = Field(default=None, gt=0)
    drift_pct: float | None = Field(default=None, ge=0, le=25)


class PositionEdit(BaseModel):
    """Percentages stay anchored to the buy price you named; absolute prices override."""
    sl_pct: float | None = Field(default=None, gt=0, lt=100)
    tp_pct: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)


@router.get("/search")
async def search_endpoint(
    q: str = Query(..., min_length=1, description="symbol or company name"),
    limit: int = Query(25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    return {"results": await sw.search(q, limit)}


@router.get("/summary")
async def summary_endpoint(current_user: dict = Depends(get_current_user)):
    return await sw.summary()


@router.get("/watchlist")
async def watchlist_endpoint(
    status: str | None = Query(None, description="WAITING | TRIGGERED | UNFILLABLE | ALL"),
    limit: int = Query(500, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    return {"watchlist": await sw.watchlist(status, limit)}


@router.post("/watch")
async def add_watch_endpoint(body: WatchIn, current_user: dict = Depends(get_current_user)):
    try:
        return await sw.add_watch(body.symbol, body.buy_price, body.sl_pct,
                                  body.tp_pct, body.note, body.drift_pct)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.patch("/watch/{watch_id}")
async def edit_watch_endpoint(
    watch_id: str, body: WatchEdit, current_user: dict = Depends(get_current_user)
):
    try:
        return await sw.edit_watch(watch_id, body.buy_price, body.sl_pct,
                                   body.tp_pct, body.drift_pct)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/watch/{watch_id}")
async def remove_watch_endpoint(watch_id: str, current_user: dict = Depends(get_current_user)):
    if not await sw.remove_watch(watch_id):
        raise HTTPException(404, "no waiting watch with that id")
    return {"removed": True}


@router.get("/positions")
async def positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED | ALL"),
    limit: int = Query(500, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    return {"positions": await sw.positions(status, limit), "summary": await sw.summary()}


@router.patch("/positions/{position_id}")
async def edit_position_endpoint(
    position_id: str, body: PositionEdit, current_user: dict = Depends(get_current_user)
):
    try:
        return await sw.edit_position(position_id, body.sl_pct, body.tp_pct,
                                      body.stop_price, body.target_price)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/equity")
async def equity_endpoint(
    limit: int = Query(500, ge=1, le=2000), current_user: dict = Depends(get_current_user)
):
    return {"equity": await sw.equity_curve(limit)}


@router.get("/daily")
async def daily_endpoint(
    limit: int = Query(90, ge=1, le=365), current_user: dict = Depends(get_current_user)
):
    return {"daily": await sw.daily(limit)}


@router.post("/run")
async def run_endpoint(current_user: dict = Depends(get_current_user)):
    return await sw.run_cycle()
