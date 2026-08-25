"""Commodity Positions — user-initiated paper trading desk for MCX futures and options.

The MCX twin of `fno_positions.py`, and deliberately the same HTTP shape so the frontend
can be the same shape too. See `app.services.commodity_positions` for the contract
mathematics; this router is a thin layer over it.

  GET    /api/commodity-positions/accounts             named paper books
  POST   /api/commodity-positions/accounts             create one
  PATCH  /api/commodity-positions/accounts/{id}        rename / re-capitalise
  GET    /api/commodity-positions/underlyings          MCX underlyings + contract specs
  GET    /api/commodity-positions/futures/expiries     futures expiries for an underlying
  GET    /api/commodity-positions/futures              the live futures board
  GET    /api/commodity-positions/options/expiries     option expiries for an underlying
  GET    /api/commodity-positions/options/chain        option chain around the future
  GET    /api/commodity-positions/margin               SPAN-lite margin for one leg
  POST   /api/commodity-positions/orders               place a BUY/SELL order
  GET    /api/commodity-positions/orders               order book
  GET    /api/commodity-positions/positions            open + closed, with summary
  POST   /api/commodity-positions/positions/{id}/exit  exit fully or partially, in lots
  POST   /api/commodity-positions/reset                wipe one account's book
  GET    /api/commodity-positions/spec-check           are the contract multipliers sane?
  POST   /api/commodity-positions/sync-instruments     reload the whole MCX board
  GET    /api/commodity-positions/instrument-coverage  what the master holds per underlying

There is no Dhan anywhere in this module. Dhan does not cover MCX, so quotes come from
Angel and margin is computed locally — both stated in the payloads rather than implied.
"""

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.db import commodity_pos_orders_collection, commodity_pos_positions_collection
from app.services.commodity_positions import (
    OrderError,
    create_account,
    edit_account,
    estimate_margin,
    exit_position,
    future_expiries,
    futures_board,
    list_accounts,
    option_chain,
    option_expiries,
    place_order,
    reset_account,
    summary,
    sync_positions,
    underlyings,
)

router = APIRouter(prefix="/api/commodity-positions", tags=["commodity-positions"])

# MCX runs to 23:30 and Angel throttles hard, so the mark-to-market pass is throttled the
# same way the F&O desk throttles its own.
REFRESH_THROTTLE_SECONDS = 20
_last_refresh = 0.0


class CreateAccountRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    initial_capital: float | None = Field(None, gt=0)


class EditAccountRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    initial_capital: float | None = Field(None, gt=0)


class PlaceOrderRequest(BaseModel):
    account_id: str
    instrument_kind: str = Field(..., pattern="^(OPTION|FUTURE)$")
    symbol: str
    expiry: str
    transaction_type: str = Field(..., pattern="^(BUY|SELL)$")
    lots: int = Field(..., ge=1, le=1000)
    order_type: str = Field("MARKET", pattern="^(MARKET|LIMIT)$")
    product_type: str = Field("MARGIN", pattern="^(INTRADAY|MARGIN)$")
    strike: float | None = None
    option_type: str | None = Field(None, pattern="^(CE|PE)$")
    limit_price: float = 0.0


class ExitRequest(BaseModel):
    account_id: str
    lots: int | None = Field(None, ge=1)


def _ser(doc: dict, ts=()) -> dict:
    doc.pop("_id", None)
    for k in ts:
        v = doc.get(k)
        if v is not None and not isinstance(v, str):
            try:
                doc[k] = v.isoformat()
            except AttributeError:
                doc[k] = str(v)
    return doc


ORDER_TS = ("placed_at", "updated_at", "filled_at")
POSITION_TS = ("opened_at", "updated_at", "closed_at")


# --------------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------------


@router.get("/accounts")
async def accounts_endpoint(_u: dict = Depends(get_current_user)):
    return {"accounts": await list_accounts()}


@router.post("/accounts")
async def create_account_endpoint(payload: CreateAccountRequest,
                                  _u: dict = Depends(get_current_user)):
    try:
        return await create_account(payload.name, payload.initial_capital)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


@router.patch("/accounts/{account_id}")
async def edit_account_endpoint(account_id: str, payload: EditAccountRequest,
                                _u: dict = Depends(get_current_user)):
    try:
        return await edit_account(account_id, payload.name, payload.initial_capital)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


# --------------------------------------------------------------------------------
# Universe
# --------------------------------------------------------------------------------


@router.get("/underlyings")
async def underlyings_endpoint(_u: dict = Depends(get_current_user)):
    rows = await underlyings()
    return {"underlyings": rows, "count": len(rows), "exchange": "MCX"}


@router.get("/futures/expiries")
async def future_expiries_endpoint(symbol: str = Query(...),
                                   _u: dict = Depends(get_current_user)):
    return {"symbol": symbol.upper(), "expiries": await future_expiries(symbol)}


@router.get("/futures")
async def futures_endpoint(symbol: str | None = Query(None),
                           _u: dict = Depends(get_current_user)):
    return await futures_board(symbol)


@router.get("/options/expiries")
async def option_expiries_endpoint(symbol: str = Query(...),
                                   _u: dict = Depends(get_current_user)):
    return {"symbol": symbol.upper(), "expiries": await option_expiries(symbol)}


@router.get("/options/chain")
async def chain_endpoint(symbol: str = Query(...), expiry: str = Query(...),
                         around: int = Query(20, ge=3, le=80),
                         _u: dict = Depends(get_current_user)):
    try:
        return await option_chain(symbol, expiry, around=around)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


@router.post("/sync-instruments")
async def sync_instruments_endpoint(_u: dict = Depends(get_current_user)):
    """Reload every MCX contract from the broker's scrip master.

    The instrument master carried 8 of MCX's 28 underlyings and `lot_size: 1` on all of
    them; this is what closes both gaps. Safe to re-run — it upserts and never deletes."""
    from app.services.commodity_instruments import sync
    return await sync()


@router.get("/instrument-coverage")
async def instrument_coverage_endpoint(_u: dict = Depends(get_current_user)):
    from app.services.commodity_instruments import coverage
    return await coverage()


@router.get("/spec-check")
async def spec_check_endpoint(_u: dict = Depends(get_current_user)):
    """Re-derive every contract value from live prices.

    An MCX lot is worth roughly ₹2 lakh to ₹4 crore; anything outside that band means a
    multiplier is off by a power of ten and every P&L on that underlying is wrong by the
    same factor. Exposed as an endpoint because it is the one number in this module that
    cannot be checked by reading the code."""
    board = await futures_board()
    return {"spec_check": board["spec_check"],
            "all_plausible": all(r["plausible"] for r in board["spec_check"]),
            "note": "Multipliers come from the published MCX contract specification, not "
                    "from the broker's lotsize field — the two disagree for GOLD, GOLDM "
                    "and ZINC."}


# --------------------------------------------------------------------------------
# Trading
# --------------------------------------------------------------------------------


@router.get("/margin")
async def margin_endpoint(
    symbol: str = Query(...), expiry: str = Query(...),
    instrument_kind: str = Query("FUTURE", pattern="^(OPTION|FUTURE)$"),
    transaction_type: str = Query("BUY", pattern="^(BUY|SELL)$"),
    lots: int = Query(1, ge=1, le=1000), price: float = Query(..., gt=0),
    strike: float | None = Query(None), option_type: str | None = Query(None),
    _u: dict = Depends(get_current_user),
):
    try:
        return await estimate_margin(
            symbol=symbol, expiry=expiry, instrument_kind=instrument_kind,
            transaction_type=transaction_type, lots=lots, price=price,
            strike=strike, option_type=option_type)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


@router.post("/orders")
async def place_order_endpoint(payload: PlaceOrderRequest,
                               _u: dict = Depends(get_current_user)):
    try:
        return await place_order(
            account_id=payload.account_id, instrument_kind=payload.instrument_kind,
            symbol=payload.symbol, expiry=payload.expiry,
            transaction_type=payload.transaction_type, lots=payload.lots,
            order_type=payload.order_type, product_type=payload.product_type,
            strike=payload.strike, option_type=payload.option_type,
            limit_price=payload.limit_price)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


@router.get("/orders")
async def orders_endpoint(account_id: str = Query(...), limit: int = Query(200, ge=1, le=500),
                          _u: dict = Depends(get_current_user)):
    rows = [_ser(d, ORDER_TS) async for d in commodity_pos_orders_collection.find(
        {"account_id": account_id}).sort("placed_at", -1).limit(limit)]
    return {"orders": rows}


@router.get("/positions")
async def positions_endpoint(account_id: str = Query(...), refresh: bool = Query(True),
                             _u: dict = Depends(get_current_user)):
    """Open + closed positions and the account summary.

    Marks to market on read, throttled — MCX runs a long session and Angel's quote limit
    is the binding constraint, so a page left open does not become a quote firehose."""
    global _last_refresh
    if refresh and (time.time() - _last_refresh) > REFRESH_THROTTLE_SECONDS:
        _last_refresh = time.time()
        try:
            await sync_positions()
        except Exception:  # noqa: BLE001 — a stale mark must never 500 the book
            pass
    try:
        data = await summary(account_id)
    except OrderError as exc:
        raise HTTPException(404, exc.detail)
    data["open_positions"] = [_ser(dict(p), POSITION_TS) for p in data["open_positions"]]
    data["closed_positions"] = [_ser(dict(p), POSITION_TS) for p in data["closed_positions"]]
    acc = data.get("account") or {}
    if acc.get("created_at") is not None and not isinstance(acc["created_at"], str):
        acc["created_at"] = acc["created_at"].isoformat()
    return data


@router.post("/positions/{position_id}/exit")
async def exit_endpoint(position_id: str, payload: ExitRequest,
                        _u: dict = Depends(get_current_user)):
    try:
        return _ser(await exit_position(payload.account_id, position_id, payload.lots),
                    ORDER_TS)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


@router.post("/reset")
async def reset_endpoint(account_id: str = Query(...), _u: dict = Depends(get_current_user)):
    try:
        return await reset_account(account_id)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)
