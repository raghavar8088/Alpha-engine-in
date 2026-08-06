"""Stocks Range API — the Nifty 50/100/250/500 watch-table with a per-stock manual
buy range (Angel-One data, no Dhan).

  GET  /api/stocks-range/indices    the selectable index lists
  GET  /api/stocks-range/universe   the table for one index (LTP, 1d/1w change, trends, buy zone)
  GET  /api/stocks-range/search     stock search (symbol/name) for the Add Range dialog
  GET  /api/stocks-range/range      this user's buy price for a stock (for the overwrite dialog)
  POST /api/stocks-range/range      set/overwrite a stock's buy price
  POST /api/stocks-range/refresh    re-seed the constituent lists on demand
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services.stocks_range import (
    INDEX_LABELS,
    RangeError,
    get_range,
    list_universe,
    refresh_stock_universe,
    search_stocks,
    set_range,
)

router = APIRouter(prefix="/api/stocks-range", tags=["stocks-range"])


class SetRangeRequest(BaseModel):
    symbol: str
    buy_price: float


@router.get("/indices")
async def indices(_current_user: dict = Depends(get_current_user)):
    return {"indices": [{"key": k, "label": v} for k, v in INDEX_LABELS.items()]}


@router.get("/universe")
async def universe(index: str = Query("nifty50"), current_user: dict = Depends(get_current_user)):
    try:
        return await list_universe(str(current_user["_id"]), index)
    except RangeError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)


@router.get("/search")
async def search(q: str = Query(..., min_length=1), _current_user: dict = Depends(get_current_user)):
    return {"results": await search_stocks(q)}


@router.get("/range")
async def range_get(symbol: str = Query(...), current_user: dict = Depends(get_current_user)):
    return await get_range(str(current_user["_id"]), symbol)


@router.post("/range")
async def range_set(payload: SetRangeRequest, current_user: dict = Depends(get_current_user)):
    try:
        return await set_range(str(current_user["_id"]), payload.symbol, payload.buy_price)
    except RangeError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)


@router.post("/refresh")
async def refresh(_current_user: dict = Depends(get_current_user)):
    return await refresh_stock_universe()
