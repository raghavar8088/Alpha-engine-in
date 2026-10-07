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
  POST   /api/commodity-positions/basket/estimate      what a basket costs, before placing
  POST   /api/commodity-positions/basket/execute       fill every leg, or none
  POST   /api/commodity-positions/basket/max-lots      largest equal size this book can carry
  DELETE /api/commodity-positions/accounts/{id}        delete an empty paper account
  POST   /api/commodity-positions/positions/{id}/reopen-atm   roll a leg to today's ATM strike
  POST   /api/commodity-positions/positions/reopen-atm-all    roll the book, or a selection, to ATM
  GET    /api/commodity-positions/orders               order book
  GET    /api/commodity-positions/positions            open + closed, with summary
  POST   /api/commodity-positions/positions/{id}/exit  exit fully or partially, in lots
  POST   /api/commodity-positions/remargin             restate margin from current positions
  POST   /api/commodity-positions/reset                wipe one account's book
  GET    /api/commodity-positions/spec-check           are the contract multipliers sane?
  POST   /api/commodity-positions/sync-instruments     reload the whole MCX board
  GET    /api/commodity-positions/instrument-coverage  what the master holds per underlying

There is no Dhan anywhere in this module. Dhan does not cover MCX, so quotes come from
Angel and margin is computed locally — both stated in the payloads rather than implied.
"""

import asyncio
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.db import commodity_pos_orders_collection, commodity_pos_positions_collection
from app.services.commodity_positions import (
    MAX_BASKET_LEGS,
    OrderError,
    create_account,
    delete_account,
    estimate_basket,
    execute_basket,
    max_lots,
    remargin_account,
    reopen_all_at_the_money,
    reopen_at_the_money,
    edit_account,
    performance,
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

logger = logging.getLogger("commodity_positions.api")

# MCX runs to 23:30 and Angel throttles hard, so the mark-to-market pass is throttled the
# same way the F&O desk throttles its own.
REFRESH_THROTTLE_SECONDS = 20
_last_refresh = 0.0
_mark_task: asyncio.Task | None = None

# How long a positions read waits for the mark-to-market it just started. The pass used to
# run INSIDE the request with no limit: one batched Angel quote plus a write per position,
# and - for a contract past expiry - a settlement lookup on the candle endpoint, which the
# process-wide pacer spaces 1.1 s apart. Now the read waits this long and no longer: a
# normal pass (one quote over a kept-alive connection, concurrent writes) finishes well
# inside it, so the book still comes back freshly marked; a slow one finishes in the
# background and the response says `marks_refreshing`, so the page asks again shortly.
MARK_WAIT_S = float(os.getenv("COMMODITY_MARK_WAIT_S", "0.8"))
# The first paint is worth more than the last few hundred milliseconds of mark freshness.
BOOTSTRAP_MARK_WAIT_S = float(os.getenv("COMMODITY_BOOTSTRAP_MARK_WAIT_S", "0.35"))


class CreateAccountRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    initial_capital: float | None = Field(None, gt=0)


class EditAccountRequest(BaseModel):
    """`roi_start_date` is the day the per-day averages are measured from."""
    name: str | None = Field(None, min_length=1, max_length=60)
    initial_capital: float | None = Field(None, gt=0)
    roi_start_date: str | None = None      # YYYY-MM-DD


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


class BasketLeg(BaseModel):
    instrument_kind: str = Field(..., pattern="^(OPTION|FUTURE)$")
    symbol: str
    expiry: str
    transaction_type: str = Field(..., pattern="^(BUY|SELL)$")
    lots: int = Field(..., ge=1, le=1000)
    strike: float | None = None
    option_type: str | None = Field(None, pattern="^(CE|PE)$")


class BasketRequest(BaseModel):
    account_id: str
    legs: list[BasketLeg] = Field(..., min_length=1, max_length=MAX_BASKET_LEGS)
    product_type: str = Field("MARGIN", pattern="^(INTRADAY|MARGIN)$")


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
        return await edit_account(account_id, payload.name, payload.initial_capital,
                                  payload.roi_start_date)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


@router.get("/accounts/{account_id}/performance")
async def account_performance(account_id: str,
                              start: str | None = Query(
                                  None,
                                  description="YYYY-MM-DD; defaults to the account's "
                                              "stored start date"),
                              _u: dict = Depends(get_current_user)):
    """Profit since a chosen day, and what it averages per day.

    `start` is a query parameter so the page can preview a date before committing it —
    dragging the calendar should not require saving the account first.
    """
    try:
        return await performance(account_id, start)
    except OrderError as exc:
        raise HTTPException(422, exc.detail)


@router.delete("/accounts/{account_id}")
async def delete_account_endpoint(account_id: str, _u: dict = Depends(get_current_user)):
    """Delete a paper account. Refuses while it still holds open positions."""
    try:
        return await delete_account(account_id)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


class ReopenAtmRequest(BaseModel):
    """Which legs to roll. Omit `position_ids` (or send null) to roll the whole book."""
    position_ids: list[str] | None = None


@router.post("/positions/reopen-atm-all")
async def reopen_atm_all_endpoint(account_id: str,
                                  payload: ReopenAtmRequest | None = None,
                                  _u: dict = Depends(get_current_user)):
    """Roll open option legs to their at-the-money strike — all of them, or a selection."""
    try:
        return await reopen_all_at_the_money(
            account_id, payload.position_ids if payload else None)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


@router.post("/positions/{position_id}/reopen-atm")
async def reopen_atm_endpoint(position_id: str, account_id: str,
                              _u: dict = Depends(get_current_user)):
    """Close this position and re-open the same contract at today's ATM strike."""
    try:
        return await reopen_at_the_money(account_id, position_id)
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
    from app.services.commodity_positions import invalidate_underlyings
    try:
        return await sync()
    finally:
        invalidate_underlyings()          # the board must reflect the reload at once


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


@router.post("/basket/estimate")
async def basket_estimate_endpoint(payload: BasketRequest,
                                   _u: dict = Depends(get_current_user)):
    """What the basket costs and whether the account can carry it — no order placed.

    The page calls this on every change, so the capital figure on screen is always the
    one the execute gate will use."""
    try:
        return await estimate_basket(payload.account_id,
                                     [leg.model_dump() for leg in payload.legs])
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


@router.post("/basket/max-lots")
async def max_lots_endpoint(payload: BasketRequest, _u: dict = Depends(get_current_user)):
    """The largest equal lot count this account can carry across the given legs."""
    try:
        return await max_lots(payload.account_id,
                              [leg.model_dump() for leg in payload.legs])
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


@router.post("/basket/execute")
async def basket_execute_endpoint(payload: BasketRequest,
                                  _u: dict = Depends(get_current_user)):
    """Fill every leg or none. Refuses outright if the basket exceeds available cash."""
    try:
        res = await execute_basket(payload.account_id,
                                   [leg.model_dump() for leg in payload.legs],
                                   payload.product_type)
        res["orders"] = [_ser(o, ORDER_TS) for o in res["orders"]]
        return res
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


@router.get("/orders")
async def orders_endpoint(account_id: str = Query(...), limit: int = Query(200, ge=1, le=500),
                          _u: dict = Depends(get_current_user)):
    rows = [_ser(d, ORDER_TS) async for d in commodity_pos_orders_collection.find(
        {"account_id": account_id}).sort("placed_at", -1).limit(limit)]
    return {"orders": rows}


async def _run_marks() -> None:
    try:
        await sync_positions()
    except Exception:  # noqa: BLE001 — a stale mark must never 500 the book
        logger.warning("commodity mark-to-market pass failed", exc_info=True)


def _start_marks() -> asyncio.Task | None:
    """The pass already running, or a new one if one is due; None when the last is recent.

    Single-flight: two tabs (or the bootstrap and the first poll) arriving together share
    one pass instead of quoting the same tokens twice."""
    global _last_refresh, _mark_task
    if _mark_task is not None and not _mark_task.done():
        return _mark_task
    if (time.time() - _last_refresh) <= REFRESH_THROTTLE_SECONDS:
        return None
    _last_refresh = time.time()
    _mark_task = asyncio.create_task(_run_marks())
    return _mark_task


async def _book(account_id: str, refresh: bool, wait_s: float) -> dict:
    refreshing = False
    task = _start_marks() if refresh else None
    if task is not None:
        try:
            # shield: running out of patience must not cancel the pass itself.
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_s)
        except asyncio.TimeoutError:
            refreshing = True
    try:
        data = await summary(account_id)
    except OrderError as exc:
        raise HTTPException(404, exc.detail)
    data["open_positions"] = [_ser(dict(p), POSITION_TS) for p in data["open_positions"]]
    data["closed_positions"] = [_ser(dict(p), POSITION_TS) for p in data["closed_positions"]]
    acc = data.get("account") or {}
    if acc.get("created_at") is not None and not isinstance(acc["created_at"], str):
        acc["created_at"] = acc["created_at"].isoformat()
    data["marks_refreshing"] = refreshing
    return data


@router.get("/positions")
async def positions_endpoint(account_id: str = Query(...), refresh: bool = Query(True),
                             _u: dict = Depends(get_current_user)):
    """Open + closed positions and the account summary.

    Marks to market on read, throttled — MCX runs a long session and Angel's quote limit
    is the binding constraint, so a page left open does not become a quote firehose. The
    read waits up to MARK_WAIT_S for the pass; past that it answers with the marks it has
    and sets `marks_refreshing`."""
    return await _book(account_id, refresh, MARK_WAIT_S)


@router.get("/bootstrap")
async def bootstrap_endpoint(account_id: str | None = Query(None),
                             symbol: str | None = Query(None),
                             expiry: str | None = Query(None),
                             around: int = Query(20, ge=3, le=80),
                             with_chain: bool = Query(False),
                             _u: dict = Depends(get_current_user)):
    """Everything the page needs to first paint, in ONE request.

    The page used to load in a waterfall - accounts and underlyings, THEN the chosen
    commodity's expiries, THEN its chain, THEN two sizing calls - five dependent round trips
    before the ticket was usable, each one crossing the network on its own. Here the
    independent parts run concurrently on the server and the dependent ones follow each
    other in-process, where a hop costs microseconds rather than a network round trip.

    Every part has exactly the shape its own endpoint returns, so the page seeds the same
    state it would have fetched. A part that fails comes back empty with its reason instead
    of failing the whole response; the page then fetches that part the old way.

    The option chain (and the ATM sizing that hangs off it) is opt-in with `with_chain`: the
    page opens on its Positions tab, and holding the first paint for an Angel round trip on
    a chain nobody is looking at yet would be the wrong trade. The page fetches the chain in
    the background right after, so the tab is ready by the time it is clicked."""
    accounts, unders = await asyncio.gather(list_accounts(), underlyings())

    acc = next((a["account_id"] for a in accounts if a["account_id"] == account_id),
               accounts[0]["account_id"] if accounts else None)
    wanted = (symbol or "").upper()
    sym = (wanted if any(u["symbol"] == wanted for u in unders)
           else next((u["symbol"] for u in unders if u.get("has_options")),
                     unders[0]["symbol"] if unders else None))

    opt_exps, fut_exps = (await asyncio.gather(option_expiries(sym), future_expiries(sym))
                          if sym else ([], []))
    exp = expiry if expiry in opt_exps else (opt_exps[0] if opt_exps else None)

    async def chain_part() -> tuple[dict | None, str | None]:
        if not (with_chain and sym and exp):
            return None, None
        try:
            return await option_chain(sym, exp, around=around), None
        except OrderError as exc:
            return None, exc.detail

    async def book_part() -> tuple[dict | None, str | None]:
        if not acc:
            return None, None
        try:
            return await _book(acc, True, BOOTSTRAP_MARK_WAIT_S), None
        except HTTPException as exc:
            return None, str(exc.detail)

    (chain, chain_error), (book, book_error) = await asyncio.gather(chain_part(), book_part())

    # The ATM pair, sized both ways - picked by the SAME rule the page uses (the first strike
    # nearest the reference future), so the page can show it without asking again. The
    # chain has just quoted these contracts, so sizing reuses those prices.
    sizing = None
    if chain and acc and chain.get("strikes"):
        atm = min(chain["strikes"], key=lambda r: abs(r["strike"] - chain["spot"]))["strike"]

        def pair(side: str) -> list[dict]:
            return [{"instrument_kind": "OPTION", "symbol": chain["symbol"],
                     "expiry": chain["expiry"], "strike": atm, "option_type": ot,
                     "transaction_type": side, "lots": 1} for ot in ("CE", "PE")]

        async def size(side: str) -> dict | None:
            try:
                return await max_lots(acc, pair(side))
            except OrderError:
                return None

        sell, buy = await asyncio.gather(size("SELL"), size("BUY"))
        sizing = {"account_id": acc, "symbol": chain["symbol"], "expiry": chain["expiry"],
                  "strike": atm, "sell": sell, "buy": buy}

    return {
        "accounts": accounts,
        "account_id": acc,
        "underlyings": unders,
        "symbol": sym,
        "option_expiries": opt_exps,
        "future_expiries": fut_exps,
        "expiry": exp,
        "chain": chain,
        "chain_error": chain_error,
        "positions": book,
        "positions_error": book_error,
        "sizing": sizing,
    }


@router.post("/positions/{position_id}/exit")
async def exit_endpoint(position_id: str, payload: ExitRequest,
                        _u: dict = Depends(get_current_user)):
    try:
        return _ser(await exit_position(payload.account_id, position_id, payload.lots),
                    ORDER_TS)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)


@router.post("/remargin")
async def remargin_endpoint(account_id: str | None = Query(None),
                            _u: dict = Depends(get_current_user)):
    """Restate margin on every open group from current positions and current prices.

    Repairs books written before margin was recomputed when a position was added to: the
    margin was set at the first fill and never again, so a position could grow without its
    margin growing. Safe to re-run."""
    return await remargin_account(account_id)


@router.post("/reset")
async def reset_endpoint(account_id: str = Query(...), _u: dict = Depends(get_current_user)):
    try:
        return await reset_account(account_id)
    except OrderError as exc:
        raise HTTPException(400, exc.detail)
