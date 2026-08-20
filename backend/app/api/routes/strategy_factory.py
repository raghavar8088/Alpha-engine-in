"""Strategy Factory API — 546 composed strategies, Rs10L paper each.

  GET  /api/strategy-factory/summary       desk totals, grade histogram, gate config
  GET  /api/strategy-factory/library       the full library, filterable (the leaderboard)
  GET  /api/strategy-factory/strategy/{id} one strategy: rules, backtest, equity curve
  GET  /api/strategy-factory/recipes       the 69 hypotheses behind the 546 strategies
  GET  /api/strategy-factory/positions     open + closed paper positions
  GET  /api/strategy-factory/trades        closed-trade blotter, net of costs
  GET  /api/strategy-factory/signals       signal feed (the alert stream)
  GET  /api/strategy-factory/equity        desk equity curve
  POST /api/strategy-factory/backtest      run the batch backtest (background)
  POST /api/strategy-factory/run           run one paper scan+manage cycle
"""

import asyncio

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.db import (
    sf_backtests_collection,
    sf_equity_collection,
    sf_positions_collection,
    sf_signals_collection,
    sf_trades_collection,
)
from app.services.strategy_factory.catalog import (
    FACTORY_BY_ID, FACTORY_CATALOG, RECIPES, TIMEFRAMES, family_counts,
)
from app.services.strategy_factory.engine import (
    ACTIVE_SOURCES, leaderboard as sf_leaderboard, run_backtests, run_backtests_all,
    run_paper_cycle, summary as sf_summary,
)

router = APIRouter(prefix="/api/strategy-factory", tags=["strategy-factory"])

_BACKGROUND: set[asyncio.Task] = set()


def _ser(doc: dict, ts=()) -> dict:
    doc.pop("_id", None)
    for k in ts:
        if doc.get(k) is not None and not isinstance(doc[k], str):
            doc[k] = doc[k].isoformat()
    return doc


@router.get("/summary")
async def summary_endpoint(_u: dict = Depends(get_current_user)):
    return await sf_summary()


@router.get("/library")
async def library_endpoint(
    family: str | None = Query(None, description="chart|candlestick|structure|indicator|hybrid"),
    timeframe: str | None = Query(None),
    grade: int | None = Query(None, ge=0, le=5),
    limit: int = Query(600, ge=1, le=1000),
    _u: dict = Depends(get_current_user),
):
    rows = await sf_leaderboard(family=family, timeframe=timeframe, grade=grade, limit=limit)
    return {"library": rows, "total": len(rows), "timeframes": TIMEFRAMES,
            "families": family_counts(), "strategy_count": len(FACTORY_CATALOG)}


@router.get("/recipes")
async def recipes_endpoint(_u: dict = Depends(get_current_user)):
    """The hypotheses, not the instantiations — 69 distinct ideas, each run on 8 charts."""
    return {"recipes": [{
        "key": r.key, "name": r.name, "family": r.family, "sub_family": r.sub_family,
        "hypothesis": r.hypothesis, "detector": r.detector, "target_r": r.target_r,
        "regimes": sorted(r.regimes) or ["any"],
        "confirmations": [n for n, _ in r.confirmations],
        "intraday_only": r.intraday_only, "uses_htf": r.uses_htf,
    } for r in RECIPES], "count": len(RECIPES)}


@router.get("/strategy/{strategy_id}")
async def strategy_detail(strategy_id: str, _u: dict = Depends(get_current_user)):
    s = FACTORY_BY_ID.get(strategy_id)
    if s is None:
        return {"error": "unknown strategy_id"}
    backtests = [_ser(d, ("updated_at",)) async for d in
                 sf_backtests_collection.find({"strategy_id": strategy_id}).sort("grade", -1)]
    positions = [_ser(d, ("opened_at", "updated_at", "closed_at", "entry_bar_ts"))
                 async for d in sf_positions_collection.find({"strategy_id": strategy_id})
                 .sort("opened_at", -1).limit(50)]
    trades = [_ser(d, ("opened_at", "closed_at")) async for d in
              sf_trades_collection.find({"strategy_id": strategy_id})
              .sort("closed_at", -1).limit(100)]
    return {
        "strategy": {
            "strategy_id": s.strategy_id, "name": s.name, "family": s.family,
            "sub_family": s.sub_family, "hypothesis": s.hypothesis,
            "detector": s.detector, "timeframe": s.timeframe, "htf": s.htf,
            "style": s.style, "target_r": s.target_r, "regimes": sorted(s.regimes),
            "confirmations": [{"name": n, "params": p} for n, p in s.confirmations],
            "params": {k: v for k, v in s.params.items() if not k.startswith("_")},
            "min_bars": s.min_bars, "fingerprint": s.fingerprint,
        },
        "backtests": backtests, "positions": positions, "trades": trades,
    }


@router.get("/positions")
async def positions_endpoint(
    strategy_id: str | None = Query(None), status: str | None = Query(None),
    limit: int = Query(300, ge=1, le=1000), _u: dict = Depends(get_current_user),
):
    q: dict = {}
    if strategy_id:
        q["strategy_id"] = strategy_id
    if status:
        q["status"] = status.upper()
    rows = [_ser(d, ("opened_at", "updated_at", "closed_at", "entry_bar_ts")) async for d in
            sf_positions_collection.find(q).sort("opened_at", -1).limit(limit)]
    return {"positions": rows, "open": [r for r in rows if r.get("status") == "OPEN"]}


@router.get("/trades")
async def trades_endpoint(limit: int = Query(200, ge=1, le=1000),
                          _u: dict = Depends(get_current_user)):
    rows = [_ser(d, ("opened_at", "closed_at")) async for d in
            sf_trades_collection.find({}).sort("closed_at", -1).limit(limit)]
    return {"trades": rows}


@router.get("/signals")
async def signals_endpoint(limit: int = Query(100, ge=1, le=500),
                           _u: dict = Depends(get_current_user)):
    rows = [_ser(d, ("created_at",)) async for d in
            sf_signals_collection.find({}).sort("created_at", -1).limit(limit)]
    return {"signals": rows}


@router.get("/equity")
async def equity_endpoint(limit: int = Query(500, ge=1, le=2000),
                          _u: dict = Depends(get_current_user)):
    pts = [_ser(d, ("ts",)) async for d in
           sf_equity_collection.find({}).sort("ts", -1).limit(limit)]
    pts.reverse()
    return {"equity": pts}


@router.post("/backtest")
async def backtest_endpoint(
    symbols: str | None = Query(None, description="comma-separated; default = all"),
    bar_limit: int = Query(1500, ge=200, le=5000),
    _u: dict = Depends(get_current_user),
):
    """Kick off the batch backtest in the background.

    546 strategies across 8 symbols is tens of thousands of replays — minutes of CPU,
    far longer than any proxy will hold a request open, so this returns immediately and
    the caller polls /summary for `last_backtest_at` and the grade histogram."""
    syms = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    task = asyncio.create_task(
        run_backtests(symbols=syms, bar_limit=bar_limit) if syms
        else run_backtests_all(bar_limit=bar_limit))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    return {"started": True, "strategies": len(FACTORY_CATALOG),
            "markets": ACTIVE_SOURCES,
            "note": "Batch backtest running in the background. Poll GET /summary for "
                    "last_backtest_at and the grade histogram."}


@router.post("/run")
async def run_endpoint(_u: dict = Depends(get_current_user)):
    return await run_paper_cycle()
