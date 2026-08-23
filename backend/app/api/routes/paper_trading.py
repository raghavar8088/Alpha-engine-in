"""Paper Broker API — Stock Paper Trading and F&O Paper Trading.

One router, one engine, two segments. `?segment=EQUITY` is the Stock module and
`?segment=FNO` is the F&O module; everything else — funds, order book, trade book, ledger —
is shared, because they are two screens onto one broking account.

  GET  /api/paper-trading/config              order types, products, validities, cutoffs
  GET  /api/paper-trading/accounts            list / create / rename / reset
  GET  /api/paper-trading/dashboard           funds + positions + holdings + open orders
  GET  /api/paper-trading/search              scrip search for the order ticket
  GET  /api/paper-trading/quote               live price for one contract
  POST /api/paper-trading/margin              what an order would block, before placing it
  POST /api/paper-trading/orders              place
  PUT  /api/paper-trading/orders/{id}         modify a resting order
  DELETE /api/paper-trading/orders/{id}       cancel
  GET  /api/paper-trading/orders              order book
  GET  /api/paper-trading/trades              trade book
  GET  /api/paper-trading/positions           positions (segment-filtered)
  POST /api/paper-trading/positions/{id}/exit square off
  GET  /api/paper-trading/holdings            settled delivery stock
  GET  /api/paper-trading/ledger              every cash movement
  POST /api/paper-trading/tick                run one engine pass by hand

  F&O contract discovery:
  GET  /api/paper-trading/fno/underlyings
  GET  /api/paper-trading/fno/expiries
  GET  /api/paper-trading/fno/chain
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services.paper_broker import accounts, engine, market, mtf, orders, strategy
from app.services.paper_broker.core import (
    MIS_LEVERAGE,
    MIS_SQUAREOFF_EQUITY,
    MIS_SQUAREOFF_FNO,
    ORDER_TYPES,
    PRODUCTS_EQUITY,
    PRODUCTS_FNO,
    SEGMENT_EQUITY,
    SEGMENT_FNO,
    VALIDITIES,
    OrderError,
    market_is_open,
)
from app.services.response_cache import cached as _cached

router = APIRouter(prefix="/api/paper-trading", tags=["paper-trading"])


def _guard(exc: OrderError) -> HTTPException:
    return HTTPException(status_code=422, detail=exc.detail)


async def _account(account_id: str | None) -> str:
    if account_id:
        return account_id
    return (await accounts.ensure_default())["account_id"]


# ── config + accounts ───────────────────────────────────────────────────────────


@router.get("/config")
async def config(_u: dict = Depends(get_current_user)):
    return {
        "segments": [
            {"key": SEGMENT_EQUITY, "label": "Stocks", "products": list(PRODUCTS_EQUITY)},
            {"key": SEGMENT_FNO, "label": "F&O", "products": list(PRODUCTS_FNO)},
        ],
        "order_types": list(ORDER_TYPES),
        "validities": list(VALIDITIES),
        "product_help": {
            "CNC": "Delivery. Fully paid, cannot short, settles into Holdings overnight.",
            "MTF": (f"Margin Trade Funding. You fund part, the broker funds the rest and "
                    f"charges {mtf.annual_rate_pct():g}% a year on it EVERY CALENDAR DAY you "
                    f"hold, plus pledge fees in and out. Delivery charges apply. Cannot short."),
            "MIS": f"Intraday. {MIS_LEVERAGE:g}x leverage, auto squared off at the cutoff.",
            "NRML": "F&O overnight. Carries to expiry on full SPAN margin.",
        },
        "mtf": mtf.rate_card(),
        "order_type_help": {
            "MARKET": "Fills at the last traded price.",
            "LIMIT": "Rests until price reaches your limit, then fills at the better of the two.",
            "SL": "Arms when the trigger is touched, then works as a limit order.",
            "SL-M": "Arms when the trigger is touched, then fills at market.",
        },
        "squareoff": {"EQUITY": MIS_SQUAREOFF_EQUITY, "FNO": MIS_SQUAREOFF_FNO},
        "market_open": market_is_open(),
        "engine": engine.state(),
        "fills_note": (
            "Fills are at the last traded price. Angel's quote feed as consumed here carries "
            "no bid/ask depth, so there is no spread and no queue position — a resting limit "
            "at the touch always fills, where in reality it might not. Paper P&L is therefore "
            "optimistic by roughly half a spread per side."),
    }


class AccountRequest(BaseModel):
    name: str
    capital: float | None = None


@router.get("/accounts")
async def list_accounts(_u: dict = Depends(get_current_user)):
    return {"accounts": await accounts.list_accounts()}


@router.post("/accounts")
async def create_account(payload: AccountRequest, _u: dict = Depends(get_current_user)):
    try:
        return await accounts.create(payload.name, payload.capital)
    except OrderError as exc:
        raise _guard(exc)


@router.post("/accounts/{account_id}/reset")
async def reset_account(account_id: str, confirm: bool = Query(False),
                        _u: dict = Depends(get_current_user)):
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Refusing to reset without ?confirm=true — this deletes every order, "
                   "trade, position and holding on the account, and cannot be undone.")
    try:
        return await accounts.reset(account_id)
    except OrderError as exc:
        raise _guard(exc)


# ── market data ─────────────────────────────────────────────────────────────────


@router.get("/search")
async def search(q: str = Query(..., min_length=1), segment: str = Query(SEGMENT_EQUITY),
                 _u: dict = Depends(get_current_user)):
    return {"results": await market.search(q, segment)}


@router.get("/quote")
async def quote(token: str = Query(...), exchange: str = Query("NSE"),
                _u: dict = Depends(get_current_user)):
    fq = await market.full_quotes([{"angel_token": token, "exchange": exchange}])
    row = fq.get(str(token))
    if row is None:
        raise HTTPException(status_code=404, detail="Angel One returned no quote for this token")
    return row


@router.get("/fno/underlyings")
async def fno_underlyings(_u: dict = Depends(get_current_user)):
    return {"underlyings": await _cached("pt:fno:und", market.fno_underlyings, ttl=600)}


@router.get("/fno/expiries")
async def fno_expiries(symbol: str = Query(...), kind: str = Query("OPTION"),
                       _u: dict = Depends(get_current_user)):
    return {"expiries": await market.expiries(symbol, kind)}


@router.get("/fno/chain")
async def fno_chain(symbol: str = Query(...), expiry: str = Query(...),
                    fresh: bool = Query(False), _u: dict = Depends(get_current_user)):
    try:
        return await _cached(f"pt:chain:{symbol}:{expiry}",
                             lambda: market.option_chain(symbol, expiry), ttl=15, fresh=fresh)
    except OrderError as exc:
        raise _guard(exc)


# ── order ticket ────────────────────────────────────────────────────────────────


class ContractRef(BaseModel):
    """How the front end names an instrument. Equity by symbol; F&O by its coordinates."""
    segment: str = SEGMENT_EQUITY
    symbol: str
    expiry: str | None = None
    strike: float | None = None
    option_type: str | None = None
    instrument_kind: str = "EQUITY"     # EQUITY | OPTION | FUTURE


async def _resolve(ref: ContractRef) -> dict:
    if ref.segment == SEGMENT_EQUITY:
        return await market.resolve_equity(ref.symbol)
    if ref.instrument_kind == "FUTURE":
        return await market.resolve_future(ref.symbol, ref.expiry or "")
    if ref.strike is None or not ref.option_type:
        raise OrderError("An option needs an expiry, a strike and CE/PE")
    return await market.resolve_option(ref.symbol, ref.expiry or "", ref.strike, ref.option_type)


class MarginRequest(ContractRef):
    account_id: str | None = None
    transaction_type: str = "BUY"
    quantity: int = 1
    product: str = "MIS"
    price: float | None = None


@router.post("/margin")
async def margin(payload: MarginRequest, _u: dict = Depends(get_current_user)):
    try:
        account_id = await _account(payload.account_id)
        contract = await _resolve(payload)
        price = payload.price or await market.quote_one(contract)
        if not price:
            raise OrderError("No live quote — cannot estimate margin")
        est = await orders.estimate_margin(
            account_id=account_id, segment=payload.segment, contract=contract,
            transaction_type=payload.transaction_type, quantity=payload.quantity,
            price=price, product=payload.product)
        funds = await accounts.funds(account_id)
        return {**est, "price": price, "contract": contract,
                "available_margin": funds["available_margin"],
                "sufficient": est["margin"] <= funds["available_margin"]}
    except OrderError as exc:
        raise _guard(exc)


class OrderRequest(ContractRef):
    account_id: str | None = None
    transaction_type: str
    quantity: int
    order_type: str = "MARKET"
    product: str = "MIS"
    validity: str = "DAY"
    price: float | None = None
    trigger_price: float | None = None


@router.post("/orders")
async def place_order(payload: OrderRequest, _u: dict = Depends(get_current_user)):
    try:
        account_id = await _account(payload.account_id)
        contract = await _resolve(payload)
        return await orders.place(
            account_id=account_id, segment=payload.segment, contract=contract,
            transaction_type=payload.transaction_type, quantity=payload.quantity,
            order_type=payload.order_type, product=payload.product,
            validity=payload.validity, price=payload.price,
            trigger_price=payload.trigger_price)
    except OrderError as exc:
        raise _guard(exc)


class ModifyRequest(BaseModel):
    account_id: str | None = None
    quantity: int | None = None
    price: float | None = None
    trigger_price: float | None = None
    order_type: str | None = None


@router.put("/orders/{order_id}")
async def modify_order(order_id: str, payload: ModifyRequest,
                       _u: dict = Depends(get_current_user)):
    try:
        return await orders.modify(
            await _account(payload.account_id), order_id, quantity=payload.quantity,
            price=payload.price, trigger_price=payload.trigger_price,
            order_type=payload.order_type)
    except OrderError as exc:
        raise _guard(exc)


@router.delete("/orders/{order_id}")
async def cancel_order(order_id: str, account_id: str | None = Query(None),
                       _u: dict = Depends(get_current_user)):
    try:
        return await orders.cancel(await _account(account_id), order_id)
    except OrderError as exc:
        raise _guard(exc)


# ── books ───────────────────────────────────────────────────────────────────────


@router.get("/dashboard")
async def dashboard(account_id: str | None = Query(None), segment: str | None = Query(None),
                    fresh: bool = Query(False), _u: dict = Depends(get_current_user)):
    aid = await _account(account_id)
    return await _cached(f"pt:dash:{aid}:{segment}",
                         lambda: engine.dashboard(aid, segment), ttl=5, fresh=fresh)


@router.get("/orders")
async def order_book(account_id: str | None = Query(None), segment: str | None = Query(None),
                     status: str | None = Query(None), limit: int = Query(300, ge=1, le=1000),
                     _u: dict = Depends(get_current_user)):
    return await engine.order_book(await _account(account_id), segment, status, limit)


@router.get("/trades")
async def trade_book(account_id: str | None = Query(None), segment: str | None = Query(None),
                     limit: int = Query(300, ge=1, le=1000),
                     _u: dict = Depends(get_current_user)):
    return await engine.trade_book(await _account(account_id), segment, limit)


@router.get("/positions")
async def positions(account_id: str | None = Query(None), segment: str | None = Query(None),
                    fresh: bool = Query(False), _u: dict = Depends(get_current_user)):
    aid = await _account(account_id)
    return await _cached(f"pt:pos:{aid}:{segment}",
                         lambda: engine.positions(aid, segment), ttl=5, fresh=fresh)


@router.post("/positions/{position_id}/exit")
async def exit_position(position_id: str, account_id: str | None = Query(None),
                        quantity: int | None = Query(None),
                        _u: dict = Depends(get_current_user)):
    try:
        return await orders.square_off(await _account(account_id), position_id, quantity)
    except OrderError as exc:
        raise _guard(exc)


@router.get("/holdings")
async def holdings(account_id: str | None = Query(None), fresh: bool = Query(False),
                   _u: dict = Depends(get_current_user)):
    aid = await _account(account_id)
    return await _cached(f"pt:hold:{aid}", lambda: engine.holdings(aid), ttl=10, fresh=fresh)


@router.get("/ledger")
async def ledger(account_id: str | None = Query(None), limit: int = Query(200, ge=1, le=1000),
                 _u: dict = Depends(get_current_user)):
    return await engine.ledger(await _account(account_id), limit)


@router.post("/tick")
async def run_tick(_u: dict = Depends(get_current_user)):
    """Run one engine pass by hand — arms stops, fills resting orders, marks positions."""
    return await engine.tick()


@router.post("/settle")
async def settle(_u: dict = Depends(get_current_user)):
    """Move unsold CNC buys into Holdings. Normally the scheduler's job, after the close."""
    return await engine.settle_delivery()


# ── MTF + closed positions ──────────────────────────────────────────────────────


@router.get("/mtf/rate-card")
async def mtf_rate_card(_u: dict = Depends(get_current_user)):
    """The MTF leverage tiers, funding rate and pledge fees — and where they came from."""
    return mtf.rate_card()


@router.get("/mtf/leverage")
async def mtf_leverage(symbol: str = Query(...), _u: dict = Depends(get_current_user)):
    """Leverage for one scrip, with its source named."""
    try:
        contract = await market.resolve_equity(symbol)
    except OrderError as exc:
        raise _guard(exc)
    return await mtf.leverage_for(
        contract["symbol"], security_id=contract.get("security_id"),
        exchange_segment=contract.get("exchange_segment"))


@router.get("/closed")
async def closed_positions(account_id: str | None = Query(None),
                           segment: str | None = Query(None),
                           limit: int = Query(200, ge=1, le=1000),
                           fresh: bool = Query(False),
                           _u: dict = Depends(get_current_user)):
    """Closed trades with every charge itemised — statutory, MTF funding, pledge fees."""
    aid = await _account(account_id)
    return await _cached(f"pt:closed:{aid}:{segment}:{limit}",
                         lambda: engine.closed_positions(aid, segment, limit),
                         ttl=10, fresh=fresh)


@router.post("/mtf/accrue")
async def mtf_accrue(_u: dict = Depends(get_current_user)):
    """Run the daily MTF interest accrual by hand. Idempotent per calendar day."""
    return {"accrued": await engine.accrue_mtf_interest()}


# ── F&O strategy builder ────────────────────────────────────────────────────────


class StrategyLeg(BaseModel):
    strike: float
    option_type: str          # CE | PE
    side: str                 # BUY | SELL
    lots: int = 1


class StrategyRequest(BaseModel):
    symbol: str
    expiry: str
    legs: list[StrategyLeg]
    account_id: str | None = None


@router.get("/fno/strategy/presets")
async def strategy_presets(_u: dict = Depends(get_current_user)):
    """The standard structures, each with what it is actually for."""
    return {"presets": strategy.PRESETS}


async def _price_legs(symbol: str, expiry: str, legs: list[StrategyLeg]) -> tuple[list[dict], dict, float]:
    """Resolve each leg to a real contract and price it off ONE batched quote.

    One quote for the whole structure rather than a call per leg: a four-leg condor would
    otherwise be four round trips to Angel every time a strike is nudged, which is both slow
    and exactly the pattern that gets this backend rate-limited.
    """
    resolved = []
    for leg in legs:
        contract = await market.resolve_option(symbol, expiry, leg.strike, leg.option_type)
        resolved.append((leg, contract))

    prices = await market.quotes([c for _, c in resolved])
    priced, missing = [], []
    lot_size = resolved[0][1]["lot_size"] if resolved else 1
    for leg, contract in resolved:
        ltp = prices.get(str(contract["angel_token"]))
        if ltp is None:
            missing.append(f"{leg.strike:g}{leg.option_type}")
            continue
        priced.append({
            "strike": leg.strike,
            "option_type": leg.option_type.upper(),
            "side": leg.side.upper(),
            "lots": leg.lots,
            "quantity": leg.lots * contract["lot_size"],
            "premium": ltp,
            "contract": contract,
        })
    return priced, {"missing": missing}, lot_size


@router.post("/fno/strategy/analyse")
async def strategy_analyse(payload: StrategyRequest, _u: dict = Depends(get_current_user)):
    """Payoff, net Greeks, margin and outcome bounds for a whole structure."""
    if not payload.legs:
        raise HTTPException(status_code=422, detail="Add at least one leg")
    try:
        priced, meta, lot_size = await _price_legs(payload.symbol, payload.expiry, payload.legs)
    except OrderError as exc:
        raise _guard(exc)
    if not priced:
        raise HTTPException(
            status_code=422,
            detail=f"None of these strikes could be priced right now ({', '.join(meta['missing'])}) "
                   f"— Angel returned no quote, so there is nothing honest to plot.")

    chain = await _cached(f"pt:chain:{payload.symbol}:{payload.expiry}",
                          lambda: market.option_chain(payload.symbol, payload.expiry), ttl=15)
    spot = chain.get("atm_strike")
    result = strategy.analyse(priced, float(spot or 0), payload.expiry, lot_size)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Could not analyse"))

    account_id = await _account(payload.account_id)
    funds = await accounts.funds(account_id)
    return {
        **result,
        "symbol": payload.symbol,
        "legs": [{k: v for k, v in p.items() if k != "contract"} for p in priced],
        "unpriced_strikes": meta["missing"],
        "available_margin": funds["available_margin"],
        "affordable": result["margin"]["total"] <= funds["available_margin"],
    }


@router.post("/fno/strategy/execute")
async def strategy_execute(payload: StrategyRequest, _u: dict = Depends(get_current_user)):
    """Place every leg as a market order.

    LONG LEGS FIRST, deliberately. In a defined-risk structure the long wings are what cap
    the loss and therefore what earns the margin benefit — placing a naked short first can
    trip the margin check on a basket the account can comfortably afford once complete.
    """
    account_id = await _account(payload.account_id)
    try:
        priced, meta, _ = await _price_legs(payload.symbol, payload.expiry, payload.legs)
    except OrderError as exc:
        raise _guard(exc)
    if meta["missing"]:
        raise HTTPException(
            status_code=422,
            detail=f"Refusing to place a partial structure — {', '.join(meta['missing'])} "
                   f"could not be priced. A half-built spread is a naked position.")

    ordered = sorted(priced, key=lambda p: 0 if p["side"] == "BUY" else 1)
    placed, failed = [], []
    for p in ordered:
        try:
            res = await orders.place(
                account_id=account_id, segment=SEGMENT_FNO, contract=p["contract"],
                transaction_type=p["side"], quantity=p["quantity"],
                order_type="MARKET", product="NRML", validity="DAY")
            (placed if res["status"] == "COMPLETE" else failed).append({
                "leg": f"{p['side']} {p['lots']}x{p['strike']:g}{p['option_type']}",
                "status": res["status"], "message": res.get("status_message"),
                "fill": res.get("fill_price"),
            })
        except OrderError as exc:
            failed.append({"leg": f"{p['side']} {p['lots']}x{p['strike']:g}{p['option_type']}",
                           "status": "ERROR", "message": exc.detail})

    return {
        "placed": placed, "failed": failed,
        "complete": len(failed) == 0,
        "warning": (None if not failed else
                    "Some legs did not fill. What is open is NOT the structure you designed — "
                    "check Positions and either complete it or close what filled."),
    }
