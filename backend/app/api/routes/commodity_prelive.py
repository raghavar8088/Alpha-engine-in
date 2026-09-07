"""Pre-Live Commodity Trading API — the graduation desk above the 311-pattern paper desk.

Only strategies that already cleared the paper desk's promotion gate trade here, in whole
MCX lots sized against margin, on a ₹1,00,000 book per CONTRACT. The engine ships OFF and
every contract has its own switch.

  GET  /api/commodity-prelive/summary          desk state, capital, admission counts
  GET  /api/commodity-prelive/scripts          one row per contract: switch, lakh, lot maths
  GET  /api/commodity-prelive/leaderboard      contract-wise strategy leaderboard
  GET  /api/commodity-prelive/admissions       who is admitted where, and on what evidence
  GET  /api/commodity-prelive/positions        open + closed positions
  GET  /api/commodity-prelive/trades           closed-trade blotter, net of MCX charges
  GET  /api/commodity-prelive/equity           desk equity curve
  POST /api/commodity-prelive/engine           master ON/OFF
  POST /api/commodity-prelive/script-enabled   one contract ON/OFF
  POST /api/commodity-prelive/scripts-enabled  every contract ON/OFF at once
  POST /api/commodity-prelive/admission-mode   per_script (default) | blended
  POST /api/commodity-prelive/run              force one manage+scan cycle
  POST /api/commodity-prelive/close-all        square off everything, or one contract
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.db import (
    commodity_prelive_equity_collection,
    commodity_prelive_positions_collection,
    commodity_prelive_trades_collection,
)
from app.services.commodity_prelive import (
    PreliveError,
    admissions,
    close_all,
    leaderboard as prelive_leaderboard,
    run_cycle,
    scripts_view,
    set_admission_mode,
    set_all_scripts,
    set_engine,
    set_script_enabled,
    summary as prelive_summary,
)

router = APIRouter(prefix="/api/commodity-prelive", tags=["commodity-prelive"])


class EngineRequest(BaseModel):
    enabled: bool
    reason: str | None = None


class ScriptEnabledRequest(BaseModel):
    symbol: str = Field(..., description="Underlying, e.g. NATURALGAS")
    enabled: bool


class AllScriptsRequest(BaseModel):
    enabled: bool


class AdmissionModeRequest(BaseModel):
    mode: str = Field(..., description="per_script | blended")


def _serialize(doc: dict, ts_fields: tuple) -> dict:
    doc.pop("_id", None)
    for key in ts_fields:
        if doc.get(key) is not None:
            doc[key] = doc[key].isoformat()
    return doc


@router.get("/summary")
async def summary_endpoint(_user: dict = Depends(get_current_user)):
    return await prelive_summary()


@router.get("/scripts")
async def scripts_endpoint(fresh: bool = Query(False), _user: dict = Depends(get_current_user)):
    return await scripts_view(fresh)


@router.get("/leaderboard")
async def leaderboard_endpoint(
    symbol: str | None = Query(None, description="one contract, e.g. NATURALGAS"),
    family: str | None = Query(None, description="chart | candlestick | structure"),
    timeframe: str | None = Query(None),
    verdict: str | None = Query(None, description="READY | REJECTED | PENDING"),
    limit: int = Query(400, ge=1, le=2000),
    _user: dict = Depends(get_current_user),
):
    data = await prelive_leaderboard(symbol)
    rows = data["rows"]
    if family:
        rows = [r for r in rows if r["family"] == family]
    if timeframe:
        rows = [r for r in rows if r["timeframe"] == timeframe]
    if verdict:
        rows = [r for r in rows if r["verdict"] == verdict.upper()]
    return {**data, "rows": rows[:limit], "shown": min(len(rows), limit), "total": len(rows)}


@router.get("/admissions")
async def admissions_endpoint(fresh: bool = Query(False), _user: dict = Depends(get_current_user)):
    """Who is allowed to trade which contract here, and the paper record that earned it."""
    data = await admissions(fresh)
    return {
        "mode": data["mode"], "counts": data["counts"], "total": data["total"],
        "per_symbol": {sym: [{"strategy_id": sid, **ev} for sid, ev in rows.items()]
                       for sym, rows in data["per_symbol"].items()},
        "note": ("per_script admits a strategy to a contract only if it cleared the paper "
                 "desk's gate on THAT contract's own trades. blended uses the paper desk's "
                 "headline verdict, which is pooled across all eight contracts and is "
                 "therefore not evidence about any one of them."),
    }


@router.get("/positions")
async def positions_endpoint(
    symbol: str | None = Query(None),
    strategy_id: str | None = Query(None),
    status: str | None = Query(None, description="OPEN | CLOSED"),
    limit: int = Query(300, ge=1, le=1000),
    _user: dict = Depends(get_current_user),
):
    q: dict = {}
    if symbol:
        q["symbol"] = symbol.strip().upper()
    if strategy_id:
        q["strategy_id"] = strategy_id
    if status:
        q["status"] = status.upper()
    cursor = commodity_prelive_positions_collection.find(q).sort("opened_at", -1).limit(limit)
    rows = [_serialize(d, ("opened_at", "updated_at", "closed_at", "entry_bar_ts"))
            async for d in cursor]
    return {"positions": rows, "open": [r for r in rows if r.get("status") == "OPEN"]}


@router.get("/trades")
async def trades_endpoint(
    symbol: str | None = Query(None),
    strategy_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(get_current_user),
):
    q: dict = {}
    if symbol:
        q["symbol"] = symbol.strip().upper()
    if strategy_id:
        q["strategy_id"] = strategy_id
    cursor = commodity_prelive_trades_collection.find(q).sort("closed_at", -1).limit(limit)
    return {"trades": [_serialize(d, ("opened_at", "closed_at")) async for d in cursor]}


@router.get("/equity")
async def equity_endpoint(limit: int = Query(500, ge=1, le=2000),
                          _user: dict = Depends(get_current_user)):
    cursor = commodity_prelive_equity_collection.find({}).sort("ts", -1).limit(limit)
    points = [_serialize(d, ("ts",)) async for d in cursor]
    points.reverse()
    return {"equity": points}


@router.post("/engine")
async def engine_endpoint(req: EngineRequest, _user: dict = Depends(get_current_user)):
    """Master switch. OFF stops NEW entries only — open positions keep being managed to
    their target, stop or hold limit, because an open position is exposure whether or not
    the desk is allowed to add to it."""
    state = await set_engine(req.enabled, reason=req.reason)
    return {"state": state, "summary": await prelive_summary()}


@router.post("/script-enabled")
async def script_enabled_endpoint(req: ScriptEnabledRequest,
                                  _user: dict = Depends(get_current_user)):
    try:
        result = await set_script_enabled(req.symbol, req.enabled)
    except PreliveError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    return {"result": result, "scripts": await scripts_view()}


@router.post("/scripts-enabled")
async def all_scripts_endpoint(req: AllScriptsRequest,
                               _user: dict = Depends(get_current_user)):
    result = await set_all_scripts(req.enabled)
    return {"result": result, "scripts": await scripts_view()}


@router.post("/admission-mode")
async def admission_mode_endpoint(req: AdmissionModeRequest,
                                  _user: dict = Depends(get_current_user)):
    try:
        state = await set_admission_mode(req.mode)
    except PreliveError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    return {"state": state, "summary": await prelive_summary()}


@router.post("/run")
async def run_endpoint(_user: dict = Depends(get_current_user)):
    return await run_cycle()


@router.post("/close-all")
async def close_all_endpoint(
    symbol: str | None = Query(None, description="one contract, or omit for the whole desk"),
    _user: dict = Depends(get_current_user),
):
    result = await close_all(symbol)
    return {"result": result, "summary": await prelive_summary()}
