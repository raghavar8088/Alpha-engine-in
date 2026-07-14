"""Manual Positions — user-initiated paper trading desk (search a stock, buy it
with a market/limit order and a quantity, optionally via MTF leverage). See
app.services.manual_positions for the capital-pool/fill/exit logic; this router
is a thin HTTP layer over it, following the same shape as trading_calls.py.

  GET    /api/manual-positions/search             instrument autocomplete (NSE+BSE)
  GET    /api/manual-positions/margin              live margin/leverage estimate before buying
  POST   /api/manual-positions/orders              place a BUY/SELL order
  GET    /api/manual-positions/orders              order book (pending/filled)
  GET    /api/manual-positions/positions           open+closed positions, with summary
  POST   /api/manual-positions/positions/{id}/exit exit (fully or partially)
"""

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import manual_orders_collection, manual_positions_collection
from app.services.manual_positions import (
    OrderError,
    estimate_margin,
    exit_position,
    get_quote,
    place_order,
    search_instruments,
    summary,
    sync_positions,
)

router = APIRouter(prefix="/api/manual-positions", tags=["manual-positions"])

REFRESH_THROTTLE_SECONDS = 20
_last_refresh = 0.0


class PlaceManualOrderRequest(BaseModel):
    security_id: str
    exchange_segment: str
    transaction_type: str  # BUY / SELL
    quantity: int
    order_type: str  # MARKET / LIMIT
    product_type: str  # CNC / MTF / MARGIN / INTRADAY
    limit_price: float = 0.0


class ExitPositionRequest(BaseModel):
    quantity: int | None = None  # None = exit the full remaining quantity


def _serialize(doc: dict, ts_fields: tuple[str, ...]) -> dict:
    doc.pop("_id", None)
    for key in ts_fields:
        if doc.get(key) is not None:
            doc[key] = doc[key].isoformat()
    return doc


async def _dhan(current_user: dict):
    try:
        return await _get_dhan_client(str(current_user["_id"]))
    except HTTPException:
        raise HTTPException(
            status_code=400,
            detail="Dhan account not connected — the Positions module needs a live broker "
            "connection for real prices and real margin/leverage figures.",
        )


@router.get("/search")
async def search(q: str = Query(..., min_length=1), current_user: dict = Depends(get_current_user)):
    return {"results": await search_instruments(q)}


@router.get("/quote")
async def quote(security_id: str, exchange_segment: str, current_user: dict = Depends(get_current_user)):
    dhan = await _dhan(current_user)
    try:
        return await get_quote(dhan, security_id, exchange_segment)
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)


@router.get("/margin")
async def margin_estimate(
    security_id: str, exchange_segment: str, transaction_type: str, quantity: int,
    product_type: str, price: float, current_user: dict = Depends(get_current_user),
):
    dhan = await _dhan(current_user)
    return await estimate_margin(dhan, security_id, exchange_segment, transaction_type, quantity, product_type, price)


@router.post("/orders")
async def create_order(payload: PlaceManualOrderRequest, current_user: dict = Depends(get_current_user)):
    dhan = await _dhan(current_user)
    try:
        result = await place_order(
            dhan, security_id=payload.security_id, exchange_segment=payload.exchange_segment,
            transaction_type=payload.transaction_type.upper(), quantity=payload.quantity,
            order_type=payload.order_type.upper(), product_type=payload.product_type.upper(),
            limit_price=payload.limit_price,
        )
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    if "position" in result:
        result["position"] = _serialize(result["position"], ("opened_at", "updated_at", "closed_at"))
    return _serialize(result, ("placed_at", "updated_at", "filled_at"))


@router.get("/orders")
async def list_orders(
    status: str | None = Query(None, description="PENDING | FILLED"),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    query: dict = {}
    if status:
        query["status"] = status.upper()
    cursor = manual_orders_collection.find(query).sort("placed_at", -1).limit(limit)
    orders = [_serialize(d, ("placed_at", "updated_at", "filled_at")) async for d in cursor]
    return {"orders": orders}


@router.get("/positions")
async def list_positions(
    status: str | None = Query(None, description="OPEN | CLOSED"),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    global _last_refresh
    if time.monotonic() - _last_refresh > REFRESH_THROTTLE_SECONDS:
        _last_refresh = time.monotonic()
        try:
            dhan = await _dhan(current_user)
            await sync_positions(dhan)
        except HTTPException:
            pass  # no broker connected yet — serve whatever's stored, honestly stale

    query: dict = {}
    if status:
        query["status"] = status.upper()
    cursor = manual_positions_collection.find(query).sort("opened_at", -1).limit(limit)
    positions = [_serialize(d, ("opened_at", "updated_at", "closed_at")) async for d in cursor]
    return {"positions": positions, "summary": await summary()}


@router.post("/positions/{position_id}/exit")
async def exit(position_id: str, payload: ExitPositionRequest, current_user: dict = Depends(get_current_user)):
    dhan = await _dhan(current_user)
    try:
        result = await exit_position(dhan, position_id, payload.quantity)
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    result["position"] = _serialize(result["position"], ("opened_at", "updated_at", "closed_at"))
    return _serialize(result, ("placed_at", "updated_at", "filled_at"))
