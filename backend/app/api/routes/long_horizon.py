"""Long-Horizon factor desk — cross-sectional momentum/low-vol/reversal strategies held
for months, on their own paper capital pool. See `long_horizon_backtest.py` and
`long_horizon_engine.py` for why this desk exists and how it differs from the
per-symbol Intraday Stocks desk and the tick-driven option desks.

  POST /api/long-horizon/sweep        run the OOS sweep, persist the qualified basket
  GET  /api/long-horizon/sweep        the latest sweep's full result set
  GET  /api/long-horizon/status       engine heartbeat, capital, open positions
  GET  /api/long-horizon/leaderboard  per-strategy running record
  GET  /api/long-horizon/positions    currently open positions
  GET  /api/long-horizon/trades       closed trades, newest first
  GET  /api/long-horizon/equity       equity-curve snapshots
  POST /api/long-horizon/rebalance    manually trigger one rebalance pass
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.db import (
    long_horizon_equity_collection,
    long_horizon_positions_collection,
    long_horizon_scores_collection,
    long_horizon_state_collection,
    long_horizon_sweeps_collection,
    long_horizon_trades_collection,
)
from app.services.long_horizon_backtest import DEFAULT_GATE, DEFAULT_TOP_K, run_long_horizon_sweep
from app.services.long_horizon_engine import balance, rebalance

router = APIRouter(prefix="/api/long-horizon", tags=["long-horizon"])


def _clean(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    doc.pop("_id", None)
    for key in ("created_at", "ts", "opened_at", "closed_at", "heartbeat", "last_rebalance_at", "updated_at"):
        if doc.get(key) is not None and hasattr(doc[key], "isoformat"):
            doc[key] = doc[key].isoformat()
    return doc


class SweepRequest(BaseModel):
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=50)
    train_fraction: float = Field(default=0.70, gt=0.3, lt=0.95)
    min_trades: int = Field(default=DEFAULT_GATE["min_trades"], ge=1)
    min_profit_factor: float = Field(default=DEFAULT_GATE["min_profit_factor"], gt=0)
    min_expectancy: float = Field(default=DEFAULT_GATE["min_expectancy"])
    max_drawdown_pct: float = Field(default=DEFAULT_GATE["max_drawdown_pct"], gt=0)
    overlap_threshold: float = Field(default=0.6, gt=0, le=1)


@router.post("/sweep")
async def sweep(request: SweepRequest = SweepRequest(), _current_user: dict = Depends(get_current_user)):
    """Run the cross-sectional OOS sweep against this app's own bars, and persist
    whichever strategies clear the gate on BOTH train and test AND survive the
    overlap de-dup as the qualified basket the engine will trade."""
    return await run_long_horizon_sweep(
        top_k=request.top_k, train_fraction=request.train_fraction,
        gate={
            "min_trades": request.min_trades, "min_profit_factor": request.min_profit_factor,
            "min_expectancy": request.min_expectancy, "max_drawdown_pct": request.max_drawdown_pct,
        },
        overlap_threshold=request.overlap_threshold,
    )


@router.get("/sweep")
async def latest_sweep(_current_user: dict = Depends(get_current_user)):
    doc = await long_horizon_sweeps_collection.find_one({}, sort=[("created_at", -1)])
    return _clean(doc)


@router.post("/rebalance")
async def run_rebalance(_current_user: dict = Depends(get_current_user)):
    return await rebalance()


@router.get("/status")
async def status(_current_user: dict = Depends(get_current_user)):
    bal = await balance()
    state = _clean(await long_horizon_state_collection.find_one({"_id": "long_horizon"})) or {
        "heartbeat": None, "basket_size": 0,
    }
    positions = [_clean(d) async for d in long_horizon_positions_collection.find({}).sort("opened_at", 1)]
    sessions = await long_horizon_trades_collection.count_documents({})
    return {
        "desk": "long_horizon", **bal, **state,
        "open_positions": len(positions), "open_positions_detail": positions,
        "trades_closed": sessions,
    }


@router.get("/leaderboard")
async def leaderboard(_current_user: dict = Depends(get_current_user)):
    rows = []
    async for doc in long_horizon_scores_collection.find({}).sort("net_pnl", -1):
        rows.append(_clean(doc))
    return rows


@router.get("/positions")
async def positions(_current_user: dict = Depends(get_current_user)):
    return [_clean(d) async for d in long_horizon_positions_collection.find({}).sort("opened_at", -1)]


@router.get("/trades")
async def trades(limit: int = Query(100, ge=1, le=500), _current_user: dict = Depends(get_current_user)):
    return [_clean(d) async for d in long_horizon_trades_collection.find({}).sort("closed_at", -1).limit(limit)]


@router.get("/equity")
async def equity(limit: int = Query(500, ge=1, le=5000), _current_user: dict = Depends(get_current_user)):
    out = [_clean(d) async for d in long_horizon_equity_collection.find({}).sort("ts", -1).limit(limit)]
    out.reverse()
    return out
