"""F&O Positions — user-initiated paper trading desk for index/stock options
and futures. See app.services.fno_positions for the capital-pool/fill/exit
logic; this router is a thin HTTP layer over it, following the same shape as
manual_positions.py.

  GET    /api/fno-positions/underlyings           index/stock underlyings with F&O
  GET    /api/fno-positions/options/expiries       expiry list for an underlying
  GET    /api/fno-positions/options/chain          live option chain (strikes/CE/PE)
  GET    /api/fno-positions/futures/expiries       futures expiry list for an underlying
  GET    /api/fno-positions/top-movers             today's top gaining CE/PE across indices
  GET    /api/fno-positions/margin                 live margin/leverage estimate
  POST   /api/fno-positions/orders                 place a BUY/SELL option or future order
  GET    /api/fno-positions/orders                 order book (pending/filled)
  GET    /api/fno-positions/positions              open+closed positions, with summary
  POST   /api/fno-positions/positions/{id}/exit    exit (fully or partially, in lots)
  POST   /api/fno-positions/reset                  wipe all positions/orders, reset capital
"""

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import fno_orders_collection, fno_positions_collection
from app.services.fno_positions import (
    OrderError,
    create_account,
    edit_account,
    estimate_basket_margin,
    estimate_margin,
    execute_basket,
    exit_position,
    future_expiries,
    list_accounts,
    option_chain,
    option_expiries,
    place_order,
    reset_account,
    summary,
    sync_positions,
    top_movers,
    underlyings,
)

router = APIRouter(prefix="/api/fno-positions", tags=["fno-positions"])

REFRESH_THROTTLE_SECONDS = 20
_last_refresh = 0.0


class PlaceFnoOrderRequest(BaseModel):
    account_id: str
    instrument_kind: str  # OPTION / FUTURE
    symbol: str
    expiry: str
    transaction_type: str  # BUY / SELL
    lots: int
    order_type: str  # MARKET / LIMIT
    product_type: str  # INTRADAY / MARGIN
    strike: float | None = None
    option_type: str | None = None  # CE / PE
    limit_price: float = 0.0


class ExitPositionRequest(BaseModel):
    account_id: str
    lots: int | None = None  # None = exit the full remaining quantity


class CreateAccountRequest(BaseModel):
    name: str
    initial_capital: float | None = None


class EditAccountRequest(BaseModel):
    name: str | None = None
    initial_capital: float | None = None


class ResetAccountRequest(BaseModel):
    account_id: str


class BasketLegRequest(BaseModel):
    instrument_kind: str = "OPTION"  # OPTION / FUTURE
    symbol: str
    expiry: str
    transaction_type: str  # BUY / SELL
    lots: int
    strike: float | None = None
    option_type: str | None = None  # CE / PE


class BasketRequest(BaseModel):
    account_id: str
    product_type: str = "MARGIN"
    legs: list[BasketLegRequest]


def _serialize(doc: dict, ts_fields: tuple[str, ...]) -> dict:
    doc.pop("_id", None)
    for key in ts_fields:
        if doc.get(key) is not None:
            doc[key] = doc[key].isoformat()
    return doc


async def _optional_dhan(user_id: str):
    """Dhan if it is connected, else None — quotes, chains and expiries all fall back to
    Angel One, and the auto-roll scheduler runs with None routinely, so its HTTP twin
    must behave identically rather than 400ing where the scheduler would have proceeded."""
    try:
        return await _get_dhan_client(user_id)
    except HTTPException:
        return None


async def _dhan(current_user: dict):
    try:
        return await _get_dhan_client(str(current_user["_id"]))
    except HTTPException:
        raise HTTPException(
            status_code=400,
            detail="Dhan account not connected — the F&O Positions module needs a live broker "
            "connection for real option chains, futures prices, and margin figures.",
        )


@router.get("/accounts")
async def accounts(_current_user: dict = Depends(get_current_user)):
    return {"accounts": [{**a, "created_at": a["created_at"].isoformat()} for a in await list_accounts()]}


@router.post("/accounts")
async def new_account(payload: CreateAccountRequest, _current_user: dict = Depends(get_current_user)):
    try:
        account = await create_account(payload.name, payload.initial_capital)
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    account["created_at"] = account["created_at"].isoformat()
    return account


@router.patch("/accounts/{account_id}")
async def update_account(account_id: str, payload: EditAccountRequest, _current_user: dict = Depends(get_current_user)):
    try:
        account = await edit_account(account_id, name=payload.name, initial_capital=payload.initial_capital)
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    if account.get("created_at") is not None and not isinstance(account["created_at"], str):
        account["created_at"] = account["created_at"].isoformat()
    return account


@router.get("/underlyings")
async def list_underlyings(_current_user: dict = Depends(get_current_user)):
    return {"underlyings": await underlyings()}


@router.get("/options/expiries")
async def options_expiries(symbol: str, current_user: dict = Depends(get_current_user)):
    # Chain + expiries now come from Angel One / the instrument master, so no Dhan needed.
    try:
        return {"symbol": symbol.upper(), "expiries": await option_expiries(None, symbol)}
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)


@router.get("/options/chain")
async def options_chain(symbol: str, expiry: str = Query(description="YYYY-MM-DD"), current_user: dict = Depends(get_current_user)):
    try:
        return await option_chain(None, symbol, expiry)
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)


@router.get("/futures/expiries")
async def futures_expiries(symbol: str, _current_user: dict = Depends(get_current_user)):
    return {"symbol": symbol.upper(), "expiries": await future_expiries(symbol)}


@router.get("/top-movers")
async def top_movers_route(limit: int = Query(10, ge=1, le=25), current_user: dict = Depends(get_current_user)):
    dhan = await _dhan(current_user)
    return await top_movers(dhan, limit)


@router.get("/margin")
async def margin_estimate(
    security_id: str, exchange_segment: str, transaction_type: str, quantity: int,
    product_type: str, price: float, current_user: dict = Depends(get_current_user),
):
    dhan = await _dhan(current_user)
    return await estimate_margin(dhan, security_id, exchange_segment, transaction_type, quantity, product_type, price)


@router.post("/orders")
async def create_order(payload: PlaceFnoOrderRequest, current_user: dict = Depends(get_current_user)):
    dhan = await _dhan(current_user)
    try:
        result = await place_order(
            dhan, account_id=payload.account_id, instrument_kind=payload.instrument_kind.upper(), symbol=payload.symbol,
            expiry=payload.expiry, transaction_type=payload.transaction_type.upper(), lots=payload.lots,
            order_type=payload.order_type.upper(), product_type=payload.product_type.upper(), strike=payload.strike,
            option_type=payload.option_type.upper() if payload.option_type else None, limit_price=payload.limit_price,
        )
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    if "position" in result:
        result["position"] = _serialize(result["position"], ("opened_at", "updated_at", "closed_at"))
    return _serialize(result, ("placed_at", "updated_at", "filled_at"))


def _basket_legs(payload: "BasketRequest") -> list[dict]:
    return [
        {"instrument_kind": leg.instrument_kind.upper(), "symbol": leg.symbol, "expiry": leg.expiry,
         "transaction_type": leg.transaction_type.upper(), "lots": leg.lots, "strike": leg.strike,
         "option_type": leg.option_type.upper() if leg.option_type else None}
        for leg in payload.legs
    ]


@router.post("/basket/margin")
async def basket_margin(payload: BasketRequest, current_user: dict = Depends(get_current_user)):
    """Preview the COMBINED hedge-aware margin (and net premium) for a multi-leg basket
    before placing it — the number a Groww-style order pad shows."""
    dhan = await _dhan(current_user)
    try:
        return await estimate_basket_margin(dhan, payload.account_id, _basket_legs(payload), payload.product_type.upper())
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)


@router.post("/basket/execute")
async def basket_execute(payload: BasketRequest, current_user: dict = Depends(get_current_user)):
    """Place every leg of the basket at once, gated on the combined netted margin
    (all-or-nothing: if any leg can't be priced, none are placed)."""
    dhan = await _dhan(current_user)
    try:
        result = await execute_basket(dhan, payload.account_id, _basket_legs(payload), payload.product_type.upper())
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    result["positions"] = [_serialize(p, ("opened_at", "updated_at", "closed_at")) for p in result["positions"]]
    return result


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
    cursor = fno_orders_collection.find(query).sort("placed_at", -1).limit(limit)
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
    cursor = fno_positions_collection.find(query).sort("opened_at", -1).limit(limit)
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
        result = await exit_position(dhan, payload.account_id, position_id, payload.lots)
    except OrderError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    result["position"] = _serialize(result["position"], ("opened_at", "updated_at", "closed_at"))
    return _serialize(result, ("placed_at", "updated_at", "filled_at"))


@router.post("/reset")
async def reset(payload: ResetAccountRequest, _current_user: dict = Depends(get_current_user)):
    try:
        return await reset_account(payload.account_id)
    except OrderError as exc:
        raise HTTPException(status_code=404, detail=exc.detail)


# --------------------------------------------------------------------------------
# Auto-roll — the daily 3 PM ATM short-straddle roll on one named paper account.
# See app.services.fno_auto_roll. Read-only status/preview plus a manual trigger, so
# the roll can be rehearsed and verified without waiting for the scheduler slot.
# --------------------------------------------------------------------------------


@router.get("/auto-roll/status")
async def auto_roll_status(_current_user: dict = Depends(get_current_user)):
    from app.services.fno_auto_roll import status as roll_status

    return await roll_status()


@router.get("/auto-roll/preview")
async def auto_roll_preview(current_user: dict = Depends(get_current_user)):
    """Exactly what the next roll would close and open, without touching anything."""
    from app.services.fno_auto_roll import preview

    dhan = await _optional_dhan(str(current_user["_id"]))
    return await preview(dhan)


@router.post("/auto-roll/run")
async def auto_roll_run(current_user: dict = Depends(get_current_user)):
    """Run the roll NOW. Same code path the 15:00 scheduler uses, so a manual run is a
    real rehearsal rather than a separate implementation that could drift from it."""
    from app.services.fno_auto_roll import run_roll

    dhan = await _optional_dhan(str(current_user["_id"]))
    result = await run_roll(dhan, trigger="manual")
    return _serialize(result, ("started_at", "finished_at"))


# --- Stock-universe ATM straddle roll (sibling of the NIFTY auto-roll above) ---------
@router.get("/stock-roll/status")
async def stock_roll_status(_current_user: dict = Depends(get_current_user)):
    from app.services.fno_stock_roll import status as sr_status

    return await sr_status()


@router.get("/stock-roll/preview")
async def stock_roll_preview(_current_user: dict = Depends(get_current_user)):
    from app.services.fno_stock_roll import preview

    return await preview()


@router.post("/stock-roll/run")
async def stock_roll_run(
    force: bool = Query(False, description="bypass the trading-day / window / once-a-day guards"),
    _current_user: dict = Depends(get_current_user),
):
    from app.services.fno_stock_roll import roll

    return await roll(force=force, trigger="manual")
