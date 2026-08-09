"""Momentum Trading desk API — the pre-live gate for the 37-strategy momentum catalog.

  GET  /api/momentum/summary       desk capital tiles, regime, promotion-gate thresholds
  GET  /api/momentum/leaderboard   every strategy with its verdict (READY/REJECTED/PENDING)
  GET  /api/momentum/catalog       the catalog itself, grouped by style (no trading needed)
  GET  /api/momentum/positions     open + closed paper positions
  GET  /api/momentum/trades        closed-trade blotter, net of real costs
  GET  /api/momentum/equity        desk equity curve
  GET  /api/momentum/ready         only the strategies that cleared the gate
  POST /api/momentum/run           trigger one scan+manage cycle now
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import (
    momentum_equity_collection,
    momentum_positions_collection,
    momentum_state_collection,
    momentum_trades_collection,
)
from app.services.dhan_client import DhanClient
from app.services.momentum_engine import (
    STATE_ID,
    _regime,
    leaderboard as momentum_leaderboard,
    run_cycle,
    summary as momentum_summary,
)
from app.services.momentum_strategies import MOMENTUM_CATALOG, STYLE_LABELS

router = APIRouter(prefix="/api/momentum", tags=["momentum"])


async def _optional_dhan(user_id: str) -> DhanClient | None:
    try:
        return await _get_dhan_client(user_id)
    except HTTPException:
        return None


def _serialize(doc: dict, ts_fields: tuple[str, ...]) -> dict:
    doc.pop("_id", None)
    for key in ts_fields:
        if doc.get(key) is not None:
            doc[key] = doc[key].isoformat()
    return doc


@router.get("/summary")
async def summary_endpoint(current_user: dict = Depends(get_current_user)):
    snap = await momentum_summary()
    state = await momentum_state_collection.find_one({"_id": STATE_ID}) or {}
    snap["last_run_at"] = state["last_run_at"].isoformat() if state.get("last_run_at") else None
    snap["last_notes"] = state.get("last_notes", [])
    snap["broker_connected"] = state.get("broker_connected", False)
    snap["angel_configured"] = state.get("angel_configured", False)
    # The regime is recomputed rather than read from state so the page is right even
    # before the first scheduler tick of the day has run.
    snap["regime"] = state.get("regime") or await _regime()
    return snap


@router.get("/leaderboard")
async def leaderboard_endpoint(
    style: str | None = Query(None, description="filter to one style, e.g. breakout_52w"),
    verdict: str | None = Query(None, description="READY | REJECTED | PENDING"),
    current_user: dict = Depends(get_current_user),
):
    rows = await momentum_leaderboard()
    if style:
        rows = [r for r in rows if r["style"] == style]
    if verdict:
        rows = [r for r in rows if r["verdict"] == verdict.upper()]
    return {"leaderboard": rows, "styles": STYLE_LABELS}


@router.get("/ready")
async def ready_endpoint(current_user: dict = Depends(get_current_user)):
    """The strategies that have cleared the promotion gate net of real costs — the
    shortlist worth considering for the real-money Live Trading desk."""
    rows = [r for r in await momentum_leaderboard() if r["verdict"] == "READY"]
    return {"ready": rows, "count": len(rows)}


@router.get("/catalog")
async def catalog_endpoint(current_user: dict = Depends(get_current_user)):
    by_style: dict[str, list[dict]] = {}
    for spec in MOMENTUM_CATALOG:
        by_style.setdefault(spec.style, []).append({
            "strategy_id": spec.strategy_id, "name": spec.name, "horizon": spec.horizon,
            "timeframe": spec.timeframe, "rationale": spec.rationale,
            "max_hold_days": spec.max_hold_days, "params": spec.params,
        })
    return {
        "styles": [
            {"style": style, "label": STYLE_LABELS.get(style, style), "strategies": rows}
            for style, rows in by_style.items()
        ],
        "total": len(MOMENTUM_CATALOG),
    }


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
    cursor = momentum_positions_collection.find(query).sort("opened_at", -1).limit(limit)
    rows = [_serialize(d, ("opened_at", "updated_at", "closed_at")) async for d in cursor]
    return {
        "positions": rows,
        "open": [r for r in rows if r.get("status") == "OPEN"],
        "summary": await momentum_summary(),
    }


@router.get("/trades")
async def list_trades(
    strategy_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    query = {"strategy_id": strategy_id} if strategy_id else {}
    cursor = momentum_trades_collection.find(query).sort("closed_at", -1).limit(limit)
    return {"trades": [_serialize(d, ("opened_at", "closed_at")) async for d in cursor]}


@router.get("/equity")
async def equity_curve(limit: int = Query(500, ge=1, le=2000), current_user: dict = Depends(get_current_user)):
    cursor = momentum_equity_collection.find({}).sort("ts", -1).limit(limit)
    points = [_serialize(d, ("ts",)) async for d in cursor]
    points.reverse()
    return {"equity": points}


@router.post("/run")
async def run_now(current_user: dict = Depends(get_current_user)):
    dhan = await _optional_dhan(str(current_user["_id"]))
    result = await run_cycle(dhan)
    result["broker_connected"] = dhan is not None
    return result
