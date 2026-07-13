"""Backtest API: POST runs a simulation via backtesting_service.run_backtest in a worker
thread (pymongo + a CPU-bound loop must not block the event loop); GETs read the stored
`backtests` collection with motor like every other route."""

from functools import partial

from anyio import to_thread
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.core.db import db
from app.schemas.backtest import BacktestRequest, BacktestSummary
from backtesting_service.service import run_backtest
from tradingai_shared.domain import Timeframe

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

backtests_collection = db["backtests"]


@router.post("")
async def create_backtest(request: BacktestRequest, _current_user: dict = Depends(get_current_user)):
    try:
        timeframe = Timeframe(request.timeframe)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid timeframe {request.timeframe!r}")

    job = partial(
        run_backtest,
        strategy_id=request.strategy_id,
        symbol=request.symbol,
        timeframe=timeframe,
        years=request.years,
        initial_capital=request.initial_capital,
        params=request.params,
        config_overrides={
            "slippage_bps": request.slippage_bps,
            "position_size_pct": request.position_size_pct,
        },
        param_grid=request.param_grid,
        with_walk_forward=request.walk_forward,
        with_monte_carlo=request.monte_carlo,
    )
    try:
        doc = await to_thread.run_sync(job)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    doc["id"] = doc.pop("_id")
    return doc


@router.get("", response_model=list[BacktestSummary])
async def list_backtests(limit: int = Query(20, ge=1, le=100), _current_user: dict = Depends(get_current_user)):
    cursor = (
        backtests_collection.find({}, {"charts": 0, "walk_forward": 0, "monte_carlo": 0, "optimization": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    return [
        BacktestSummary(
            id=str(doc["_id"]),
            strategy_id=doc["strategy_id"],
            symbol=doc["symbol"],
            timeframe=doc["timeframe"],
            start=doc["start"].isoformat(),
            end=doc["end"].isoformat(),
            bar_count=doc["bar_count"],
            created_at=doc["created_at"].isoformat(),
            metrics=doc["metrics"],
        )
        async for doc in cursor
    ]


@router.get("/{backtest_id}")
async def get_backtest(backtest_id: str, _current_user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(backtest_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Backtest not found")
    doc = await backtests_collection.find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="Backtest not found")
    doc["id"] = str(doc.pop("_id"))
    return doc
