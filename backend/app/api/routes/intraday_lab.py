"""Intraday Strategy Lab — sub-module of Trading Calls. 50 intraday equity
scalping/momentum/mean-reversion/swing strategies, each auto-trading paper
positions off its own slice of a shared ₹1cr capital pool.

  GET  /api/intraday-lab/strategies   catalog + live leaderboard stats
  GET  /api/intraday-lab/positions    open/closed paper positions
  GET  /api/intraday-lab/leaderboard  per-strategy ranked scoreboard
  GET  /api/intraday-lab/summary      pool-level capital tiles
  POST /api/intraday-lab/run          manually trigger one scan+manage cycle
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import intraday_lab_positions_collection, intraday_lab_scores_collection
from app.services.dhan_client import DhanClient
from app.services.intraday_lab_engine import run_cycle, summary as lab_summary
from app.services.intraday_strategies import STRATEGY_CATALOG

router = APIRouter(prefix="/api/intraday-lab", tags=["intraday-lab"])


async def _optional_dhan(user_id: str) -> DhanClient | None:
    try:
        return await _get_dhan_client(user_id)
    except HTTPException:
        return None


def _serialize_position(doc: dict) -> dict:
    doc.pop("_id", None)
    for key in ("opened_at", "updated_at", "closed_at"):
        if doc.get(key) is not None:
            doc[key] = doc[key].isoformat()
    return doc


@router.get("/strategies")
async def list_strategies(current_user: dict = Depends(get_current_user)):
    scores = {s["strategy_id"]: s async for s in intraday_lab_scores_collection.find({})}
    out = []
    for spec in STRATEGY_CATALOG:
        score = scores.get(spec.strategy_id) or {}
        out.append({
            "strategy_id": spec.strategy_id, "name": spec.name, "category": spec.category,
            "timeframe": spec.timeframe, "rationale": spec.rationale,
            "max_hold_days": spec.max_hold_days, "risk_pct": spec.risk_pct,
            "trades": score.get("trades", 0), "win_rate": score.get("win_rate", 0.0),
            "net_pnl": score.get("net_pnl", 0.0), "allocated_capital": score.get("allocated_capital"),
        })
    return {"strategies": out, "count": len(out)}


@router.get("/positions")
async def list_positions(
    strategy_id: str | None = Query(None),
    status: str | None = Query(None, description="OPEN | CLOSED"),
    limit: int = Query(300, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    query: dict = {}
    if strategy_id:
        query["strategy_id"] = strategy_id
    if status:
        query["status"] = status.upper()
    cursor = intraday_lab_positions_collection.find(query).sort("opened_at", -1).limit(limit)
    positions = [_serialize_position(d) async for d in cursor]
    return {"positions": positions}


@router.get("/leaderboard")
async def leaderboard(current_user: dict = Depends(get_current_user)):
    scores = {s["strategy_id"]: s async for s in intraday_lab_scores_collection.find({})}
    rows = []
    for spec in STRATEGY_CATALOG:
        score = scores.get(spec.strategy_id) or {}
        rows.append({
            "strategy_id": spec.strategy_id, "name": spec.name, "category": spec.category,
            "trades": score.get("trades", 0), "win_rate": score.get("win_rate", 0.0),
            "net_pnl": score.get("net_pnl", 0.0),
            "allocated_capital": score.get("allocated_capital", None),
        })
    rows.sort(key=lambda r: r["net_pnl"], reverse=True)
    return {"leaderboard": rows}


@router.get("/summary")
async def summary_endpoint(current_user: dict = Depends(get_current_user)):
    return await lab_summary()


@router.post("/run")
async def run_now(current_user: dict = Depends(get_current_user)):
    dhan = await _optional_dhan(str(current_user["_id"]))
    result = await run_cycle(dhan)
    result["broker_connected"] = dhan is not None
    return result
