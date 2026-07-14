"""Manual Positions — user-initiated paper trading desk (search a stock, buy it
with a market/limit order and a quantity, optionally via MTF leverage), across
multiple independent named accounts. See app.services.manual_positions for the
account/capital-pool/fill/exit logic; this router is a thin HTTP layer over it,
following the same shape as trading_calls.py.

  GET    /api/manual-positions/accounts            list accounts (auto-migrates legacy data into "Default")
  POST   /api/manual-positions/accounts            create a new named account
  GET    /api/manual-positions/search               instrument autocomplete (NSE+BSE)
  GET    /api/manual-positions/margin                live margin/leverage estimate before buying
  POST   /api/manual-positions/orders               place a BUY/SELL order (account_id required)
  GET    /api/manual-positions/orders               order book for one account (pending/filled)
  GET    /api/manual-positions/positions            one account's open+closed positions, with summary
  POST   /api/manual-positions/positions/{id}/exit  exit (fully or partially)
  POST   /api/manual-positions/reset                wipe one account's positions/orders, reset its capital
"""

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import manual_orders_collection, manual_positions_collection
from app.services.manual_positions import (
    OrderError,
    create_account,
    estimate_margin,
    exit_position,
    get_quote,
    list_accounts,
    place_order,
    reset_account,
    search_instruments,
    summary,
    sync_positions,
)

router = APIRouter(prefix="/api/manual-positions", tags=["manual-positions"])

REFRESH_THROTTLE_SECONDS = 20
_last_refresh = 0.0


class PlaceManualOrderRequest(BaseModel):
    account_id: str
    security_id: str
    exchange_segment: str
    transaction_type: str  # BUY / SELL
    quantity: int
    order_type: str  # MARKET / LIMIT
    product_type: str  # CNC / MTF / MARGIN / INTRADAY
    limit_price: float = 0.0


class ExitPositionRequest(BaseModel):
    account_id: str
    quantity: int | None = None  # None = exit the full remaining quantity


class CreateAccountRequest(BaseModel):
    name: str
    initial_capital: float | None = None


class ResetAccountRequest(BaseModel):
    account_id: str


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


@router.get("/accounts")
async def accounts(current_user: dict = Depends(get_current_user)):
    return {"accounts": [{**a, "created_at": a["created_at"].isoformat()} for a in await list_accounts()]}


@router.post("/accounts")
async def new_account(payload: CreateAccountRequest, current_user: dict = Depends(get_current_user)):
    try:
        account = await create_account(payload.name, payload.initial_capital)
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    account["created_at"] = account["created_at"].isoformat()
    return account


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
            dhan, account_id=payload.account_id, security_id=payload.security_id, exchange_segment=payload.exchange_segment,
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
    account_id: str = Query(...),
    status: str | None = Query(None, description="PENDING | FILLED"),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    query: dict = {"account_id": account_id}
    if status:
        query["status"] = status.upper()
    cursor = manual_orders_collection.find(query).sort("placed_at", -1).limit(limit)
    orders = [_serialize(d, ("placed_at", "updated_at", "filled_at")) async for d in cursor]
    return {"orders": orders}


@router.get("/positions")
async def list_positions(
    account_id: str = Query(...),
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

    query: dict = {"account_id": account_id}
    if status:
        query["status"] = status.upper()
    cursor = manual_positions_collection.find(query).sort("opened_at", -1).limit(limit)
    positions = [_serialize(d, ("opened_at", "updated_at", "closed_at")) async for d in cursor]
    try:
        acct_summary = await summary(account_id)
    except OrderError as exc:
        raise HTTPException(status_code=404, detail=exc.detail)
    return {"positions": positions, "summary": acct_summary}


@router.post("/positions/{position_id}/exit")
async def exit(position_id: str, payload: ExitPositionRequest, current_user: dict = Depends(get_current_user)):
    dhan = await _dhan(current_user)
    try:
        result = await exit_position(dhan, payload.account_id, position_id, payload.quantity)
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    result["position"] = _serialize(result["position"], ("opened_at", "updated_at", "closed_at"))
    return _serialize(result, ("placed_at", "updated_at", "filled_at"))


@router.post("/reset")
async def reset(payload: ResetAccountRequest, current_user: dict = Depends(get_current_user)):
    try:
        return await reset_account(payload.account_id)
    except OrderError as exc:
        raise HTTPException(status_code=404, detail=exc.detail)
