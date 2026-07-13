from datetime import datetime, timezone
from uuid import uuid4

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import instruments_collection, option_backtests_collection, option_sweeps_collection
from app.schemas.options import OptionsBacktestRequest, OptionsSweepRequest, PayoffRequest
from app.services.dhan_client import DhanAPIError
from options_service.chain import parse_chain
from options_service.options_backtest import OPTION_BUYING_CATEGORIES, run_options_backtest
from options_service.payoff import Leg, breakevens, max_profit_loss, net_greeks, payoff_diagram
from tradingai_shared.contracts import STRATEGY_REGISTRY
from tradingai_shared.domain import Timeframe

router = APIRouter(prefix="/api/options", tags=["options"])


async def _underlying_instrument(symbol: str) -> dict:
    instrument = await instruments_collection.find_one({"symbol": symbol.upper(), "asset_class": "INDEX"})
    if instrument is None:
        raise HTTPException(
            status_code=422,
            detail=f"{symbol} is not a whitelisted index underlying (NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY/SENSEX)",
        )
    return instrument


@router.get("/expiries/{symbol}")
async def expiries(symbol: str, current_user: dict = Depends(get_current_user)):
    instrument = await _underlying_instrument(symbol)
    client = await _get_dhan_client(str(current_user["_id"]))
    try:
        result = await client.option_chain_expiry_list(int(instrument["security_id"]), instrument["exchange_segment"])
    except DhanAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.remarks)
    return {"symbol": symbol.upper(), "expiries": result.get("data", [])}


@router.get("/chain/{symbol}")
async def chain(
    symbol: str, expiry: str = Query(description="YYYY-MM-DD"), current_user: dict = Depends(get_current_user)
):
    instrument = await _underlying_instrument(symbol)
    client = await _get_dhan_client(str(current_user["_id"]))
    try:
        raw = await client.option_chain(int(instrument["security_id"]), instrument["exchange_segment"], expiry)
    except DhanAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.remarks)
    if raw.get("status") != "success":
        raise HTTPException(status_code=502, detail=raw.get("remarks") or "Dhan option chain request failed")
    return parse_chain(raw, expiry)


@router.post("/payoff")
async def payoff(request: PayoffRequest, _current_user: dict = Depends(get_current_user)):
    legs = [Leg(**leg.model_dump()) for leg in request.legs]
    result = {
        "diagram": payoff_diagram(legs),
        "breakevens": breakevens(legs),
        **max_profit_loss(legs),
    }
    if request.spot is not None:
        result["net_greeks"] = net_greeks(
            legs, spot=request.spot, t_years=request.days_to_expiry / 365,
            sigma_by_strike={leg.strike: request.iv_pct / 100 for leg in legs},
        )
    return result


@router.post("/backtest")
async def options_backtest(request: OptionsBacktestRequest, _current_user: dict = Depends(get_current_user)):
    from backtesting_service.service import load_bars

    try:
        timeframe = Timeframe(request.timeframe)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid timeframe {request.timeframe!r}")

    bars = await to_thread.run_sync(load_bars, request.symbol, timeframe, request.years)
    if not bars:
        raise HTTPException(
            status_code=422, detail=f"no bars for {request.symbol} {request.timeframe} — backfill it first"
        )

    try:
        result = await to_thread.run_sync(
            run_options_backtest, request.strategy_id, request.symbol, timeframe, bars,
            request.initial_capital, request.lot_size, request.quantity_lots,
            request.dte_days, request.otm_pct, request.strike_step, request.iv_lookback, request.params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    doc = {
        "strategy_id": request.strategy_id, "symbol": request.symbol, "timeframe": request.timeframe,
        "years": request.years, "created_at": datetime.now(timezone.utc), **result,
    }
    insert_result = await option_backtests_collection.insert_one(doc)
    doc["id"] = str(insert_result.inserted_id)
    doc.pop("_id", None)
    return doc


STYLE_TIMEFRAMES = {
    "options_scalp": Timeframe.M5,
    "options_intraday": Timeframe.M15,
    "options_swing": Timeframe.D1,
    "options_breakout": Timeframe.M15,
}
# If a style's native timeframe has no local bars yet (e.g. 5m before its backfill),
# fall back to the next-coarser intraday timeframe rather than skipping the strategy —
# the result is labeled with the timeframe actually used.
TIMEFRAME_FALLBACKS = {
    Timeframe.M5: [Timeframe.M5, Timeframe.M15],
    Timeframe.M15: [Timeframe.M15],
    Timeframe.D1: [Timeframe.D1],
}


@router.post("/backtest-all")
async def options_backtest_all(request: OptionsSweepRequest, _current_user: dict = Depends(get_current_user)):
    """Run every registered option-buying strategy (the 50-strategy library) over the
    requested window and gate each on the qualification rule (win rate + minimum
    trades). Stores one sweep document and returns the full leaderboard."""
    from backtesting_service.service import load_bars

    sweep_id = uuid4().hex[:12]
    bars_cache: dict[Timeframe, list] = {}

    def bars_for(timeframe: Timeframe):
        if timeframe not in bars_cache:
            bars_cache[timeframe] = load_bars(request.symbol, timeframe, request.years)
        return bars_cache[timeframe]

    buying = sorted(
        (sid, cls) for sid, cls in STRATEGY_REGISTRY.items()
        if cls.metadata.category in OPTION_BUYING_CATEGORIES
    )
    results = []
    for sid, cls in buying:
        native_tf = STYLE_TIMEFRAMES[cls.metadata.category]
        bars, used_tf = [], native_tf
        for tf in TIMEFRAME_FALLBACKS[native_tf]:
            bars = await to_thread.run_sync(bars_for, tf)
            if bars:
                used_tf = tf
                break
        entry = {
            "strategy_id": sid,
            "name": cls.metadata.name,
            "style": cls.metadata.category.removeprefix("options_"),
            "timeframe": used_tf.value,
            "timeframe_native": native_tf.value,
        }
        if not bars:
            entry.update({"error": f"no local bars for {request.symbol} {native_tf.value} — backfill it first"})
            results.append(entry)
            continue
        adx_gate = request.adx_regime if cls.metadata.suitable_market == "trending" else None
        # Real weekly options only exist for NIFTY (verified against the instruments
        # collection: BANKNIFTY/FINNIFTY/MIDCPNIFTY/SENSEX list monthlies only in this
        # data) — scalp/intraday assume a near-expiry weekly, so price them off NIFTY's
        # actual Tuesday cycle rather than a flat DTE guess. Swing's 30-day assumption
        # already matches the other indices' real monthly contracts.
        expiry_wd = (
            1 if request.symbol == "NIFTY"
            and cls.metadata.category in ("options_scalp", "options_intraday", "options_breakout")
            else None
        )
        try:
            result = await to_thread.run_sync(
                lambda sid=sid, used_tf=used_tf, bars=bars, adx_gate=adx_gate, expiry_wd=expiry_wd: run_options_backtest(
                    sid, request.symbol, used_tf, bars,
                    initial_capital=request.initial_capital, lot_size=request.lot_size,
                    quantity_lots=request.quantity_lots, adx_regime=adx_gate, expiry_weekday=expiry_wd,
                )
            )
        except Exception as exc:  # one bad strategy must not sink the sweep
            entry.update({"error": str(exc)})
            results.append(entry)
            continue
        metrics = result["metrics"]
        win_rate = metrics.get("win_rate")
        total_trades = metrics.get("total_trades", 0)
        expectancy = metrics.get("expectancy")
        entry.update(
            {
                "data_from": bars[0].ts.isoformat(),
                "data_to": bars[-1].ts.isoformat(),
                "metrics": metrics,
                "structure": result["structure"],
                "qualified": (
                    win_rate is not None
                    and win_rate >= request.min_win_rate
                    and total_trades >= request.min_trades
                    and (expectancy or 0) >= request.min_expectancy
                ),
            }
        )
        results.append(entry)

    def sort_key(e):
        m = e.get("metrics") or {}
        return (e.get("qualified", False), m.get("win_rate") or -1, m.get("net_profit") or 0)

    results.sort(key=sort_key, reverse=True)
    doc = {
        "sweep_id": sweep_id,
        "created_at": datetime.now(timezone.utc),
        "symbol": request.symbol,
        "years": request.years,
        "min_win_rate": request.min_win_rate,
        "min_trades": request.min_trades,
        "min_expectancy": request.min_expectancy,
        "adx_regime": request.adx_regime,
        "pricing_model": "black_scholes_realized_vol_proxy",
        "qualified_count": sum(1 for e in results if e.get("qualified")),
        "strategy_count": len(results),
        "results": results,
    }
    await option_sweeps_collection.insert_one(doc)
    doc.pop("_id", None)
    doc["created_at"] = doc["created_at"].isoformat()
    return doc


@router.get("/qualified")
async def qualified_strategies(_current_user: dict = Depends(get_current_user)):
    """The latest sweep's leaderboard (all strategies, qualification flags included)."""
    doc = await option_sweeps_collection.find_one({}, sort=[("created_at", -1)])
    if doc is None:
        return {"sweep_id": None, "results": [], "qualified_count": 0, "strategy_count": 0}
    doc.pop("_id", None)
    doc["created_at"] = doc["created_at"].isoformat()
    return doc


@router.get("")
async def list_option_backtests(limit: int = Query(20, ge=1, le=100), _current_user: dict = Depends(get_current_user)):
    cursor = option_backtests_collection.find({}, {"charts": 0}).sort("created_at", -1).limit(limit)
    docs = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        doc["created_at"] = doc["created_at"].isoformat()
        docs.append(doc)
    return docs
