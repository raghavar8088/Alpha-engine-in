from datetime import datetime, timezone
from uuid import uuid4

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import (
    instruments_collection,
    option_backtests_collection,
    option_sweeps_collection,
    option_sweeps_selling_collection,
)
from app.schemas.options import (
    OptionsBacktestRequest,
    OptionsSellingSweepRequest,
    OptionsSweepRequest,
    PayoffRequest,
)
from app.services.dhan_client import DhanAPIError
from options_service.chain import parse_chain
from options_service.options_backtest import OPTION_BUYING_CATEGORIES, run_options_backtest
from options_service.options_selling_backtest import (
    DEFAULT_OVERLAP_THRESHOLD,
    OPTION_SELLING_CATEGORIES,
    entry_days,
    overlap_groups,
    qualify,
    run_options_selling_backtest,
)
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


SELLING_STYLE_TIMEFRAMES = {
    "options_sell_intraday": Timeframe.M15,
    "options_sell_expiry": Timeframe.M15,
    # Swing entries are read off 15m bars but the position is HELD across sessions to
    # the weekly expiry — the style that measurably rescued the neutral book (see
    # OPTION_SELLING_CATEGORIES for the before/after numbers).
    "options_sell_swing": Timeframe.M15,
    "options_sell_positional": Timeframe.D1,
}


@router.post("/selling/backtest-all")
async def options_selling_backtest_all(
    request: OptionsSellingSweepRequest, _current_user: dict = Depends(get_current_user)
):
    """Run every registered option-SELLING strategy and gate each on the selling rule
    (profit factor + tail size + drawdown + sample size — never win rate).

    Every result carries the reasons it failed the gate, so the leaderboard can show why
    a 90%-win-rate strategy was rejected instead of just marking it red.
    """
    from backtesting_service.service import load_bars

    sweep_id = uuid4().hex[:12]
    bars_cache: dict[Timeframe, list] = {}

    def bars_for(timeframe: Timeframe):
        if timeframe not in bars_cache:
            bars_cache[timeframe] = load_bars(request.symbol, timeframe, request.years)
        return bars_cache[timeframe]

    gate = {
        "min_profit_factor": request.min_profit_factor,
        "min_trades": request.min_trades,
        "max_worst_trade_pct_capital": request.max_worst_trade_pct_capital,
        "max_drawdown_pct": request.max_drawdown_pct,
        "naked_min_profit_factor": request.naked_min_profit_factor,
        "naked_max_worst_trade_pct_capital": request.naked_max_worst_trade_pct_capital,
    }

    selling = sorted(
        (sid, cls) for sid, cls in STRATEGY_REGISTRY.items()
        if cls.metadata.category in OPTION_SELLING_CATEGORIES
    )
    results = []
    days_by_strategy: dict[str, set] = {}  # entry days, for the overlap pass below
    for sid, cls in selling:
        timeframe = SELLING_STYLE_TIMEFRAMES[cls.metadata.category]
        entry = {
            "strategy_id": sid,
            "name": cls.metadata.name,
            "style": cls.metadata.category.removeprefix("options_sell_"),
            "timeframe": timeframe.value,
            "suitable_market": cls.metadata.suitable_market,
        }
        bars = await to_thread.run_sync(bars_for, timeframe)
        if not bars:
            entry["error"] = f"no local bars for {request.symbol} {timeframe.value} — backfill it first"
            results.append(entry)
            continue

        # Weekly expiries exist only for NIFTY in this app's instrument data, so only
        # NIFTY's intraday/expiry styles get priced off the real Tuesday cycle; the
        # positional style's 30-day assumption already matches real monthlies.
        # Weekly-expiry styles price each entry off NIFTY's REAL Tuesday cycle, not a
        # flat DTE guess. Swing belongs in this set: a "7-day hold" is not a listed
        # contract on any day but Wednesday, and pricing it as one overstates the time
        # value collected on late-week entries. Verified that the swing book's edge
        # survives the switch (10 of 11 robust strategies stay above the gate) — the
        # realistic cycle roughly doubles turnover because holds are shorter.
        expiry_wd = (
            1 if request.symbol == "NIFTY"
            and cls.metadata.category in (
                "options_sell_intraday", "options_sell_expiry", "options_sell_swing",
            )
            else None
        )
        # Full history, plus a chronological hold-back run. The split is what separates
        # "this works" from "this got lucky once" when ~180 candidates are tested against
        # one price history — at a PF gate, some WILL clear it on noise alone. Split is
        # strictly by time; shuffling bars would leak the future into the past and make
        # almost everything look robust.
        cut = int(len(bars) * request.train_fraction)
        try:
            def _go(window, sid=sid, timeframe=timeframe, expiry_wd=expiry_wd, trades=False):
                return run_options_selling_backtest(
                    sid, request.symbol, timeframe, window,
                    initial_capital=request.initial_capital, lot_size=request.lot_size,
                    quantity_lots=request.quantity_lots, expiry_weekday=expiry_wd,
                    include_trades=trades,
                    # The sweep stores metrics and structure only — never charts. Building
                    # them anyway cost one dict + isoformat per bar per run, which on a
                    # 178-strategy sweep over 32k 15m bars is ~11M objects created and
                    # discarded unread, and was the dominant cost of running a sweep.
                    with_charts=False,
                )

            result = await to_thread.run_sync(lambda: _go(bars, trades=True))
            test = await to_thread.run_sync(lambda: _go(bars[cut:]))
        except Exception as exc:  # one bad strategy must not sink the sweep
            entry["error"] = str(exc)
            results.append(entry)
            continue

        verdict = qualify(result["metrics"], gate)
        test_verdict = qualify(test["metrics"], gate)
        thin_test = test["metrics"]["total_trades"] < request.min_test_trades
        days_by_strategy[sid] = entry_days(result.get("trades"))
        entry.update({
            "data_from": bars[0].ts.isoformat(),
            "data_to": bars[-1].ts.isoformat(),
            "metrics": result["metrics"],
            "structure": result["structure"],
            "qualified": verdict["qualified"],
            "naked": verdict["naked"],
            "gate_failures": verdict["reasons"],
            # Out-of-sample verdict on the held-back tail.
            "test_qualified": test_verdict["qualified"] and not thin_test,
            "test_metrics": {
                "profit_factor": test["metrics"]["profit_factor"],
                "total_trades": test["metrics"]["total_trades"],
                "net_profit": test["metrics"]["net_profit"],
                "win_rate": test["metrics"]["win_rate"],
                "max_drawdown_pct": test["metrics"]["max_drawdown_pct"],
            },
            "test_failures": (
                [f"only {test['metrics']['total_trades']} held-back trades "
                 f"(need {request.min_test_trades})"] if thin_test else test_verdict["reasons"]
            ),
        })
        results.append(entry)

    # --- de-duplicate the survivors ------------------------------------------------
    # A strategy that passes both the gate and the split can still be another survivor
    # wearing a different name. Keep the higher out-of-sample profit factor of each
    # overlapping pair and record what each dropped one duplicates, so the leaderboard
    # can show WHY rather than silently omitting it.
    def _test_pf(e):
        return (e.get("test_metrics") or {}).get("profit_factor") or 0

    survivors = [e for e in results if e.get("qualified") and e.get("test_qualified")]
    survivors.sort(key=_test_pf, reverse=True)
    kept, dropped = overlap_groups(
        days_by_strategy, [e["strategy_id"] for e in survivors], request.overlap_threshold
    )
    kept_set = set(kept)
    for e in results:
        sid = e["strategy_id"]
        if sid in dropped:
            e["independent"] = False
            e["duplicate_of"] = dropped[sid]["duplicate_of"]
            e["overlap"] = dropped[sid]["overlap"]
        else:
            e["independent"] = sid in kept_set
    # The basket the daemon trades: passed the gate, survived out of sample, and is not
    # a duplicate of something already in it.
    for e in results:
        e["in_basket"] = bool(e.get("qualified") and e.get("test_qualified") and e.get("independent"))

    def sort_key(e):
        m = e.get("metrics") or {}
        return (e.get("in_basket", False), e.get("qualified", False),
                _test_pf(e), m.get("profit_factor") or -1)

    results.sort(key=sort_key, reverse=True)
    doc = {
        "sweep_id": sweep_id,
        "created_at": datetime.now(timezone.utc),
        "symbol": request.symbol,
        "years": request.years,
        "desk": "selling",
        "gate": gate,
        "train_fraction": request.train_fraction,
        "min_test_trades": request.min_test_trades,
        "overlap_threshold": request.overlap_threshold,
        "pricing_model": "black_scholes_realized_vol_proxy",
        "margin_model": "span_exposure_approximation",
        # The funnel, so the count can never be quoted without its context.
        "strategy_count": len(results),
        "qualified_count": sum(1 for e in results if e.get("qualified")),
        "robust_count": sum(1 for e in results if e.get("qualified") and e.get("test_qualified")),
        "basket_count": sum(1 for e in results if e.get("in_basket")),
        "results": results,
    }
    await option_sweeps_selling_collection.insert_one(doc)
    doc.pop("_id", None)
    doc["created_at"] = doc["created_at"].isoformat()
    return doc


@router.get("/selling/qualified")
async def qualified_selling_strategies(_current_user: dict = Depends(get_current_user)):
    """The latest SELLING sweep's leaderboard (all strategies, with gate verdicts)."""
    doc = await option_sweeps_selling_collection.find_one({}, sort=[("created_at", -1)])
    if doc is None:
        return {"sweep_id": None, "results": [], "qualified_count": 0, "strategy_count": 0}
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
