from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.core.db import strategy_runs_collection
from app.schemas.live import RunDetail, RunSummary, StartRunRequest
from app.services.live_engine import engine

router = APIRouter(prefix="/api/live", tags=["live"])


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _to_summary(doc: dict) -> RunSummary:
    return RunSummary(
        run_id=doc["run_id"], strategy_id=doc["strategy_id"], symbol=doc["symbol"],
        timeframe=doc["timeframe"], mode=doc["mode"], status=doc["status"],
        started_at=_iso(doc["started_at"]), stopped_at=_iso(doc.get("stopped_at")),
        snapshot=doc.get("snapshot"),
    )


@router.post("/runs", response_model=RunDetail)
async def start_run(request: StartRunRequest, current_user: dict = Depends(get_current_user)):
    try:
        doc = await engine.start_run(str(current_user["_id"]), request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return RunDetail(**_to_summary(doc).model_dump(), result=doc.get("result"), error=doc.get("error"))


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(limit: int = Query(50, ge=1, le=200), _current_user: dict = Depends(get_current_user)):
    cursor = strategy_runs_collection.find().sort("started_at", -1).limit(limit)
    return [_to_summary(doc) async for doc in cursor]


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, _current_user: dict = Depends(get_current_user)):
    doc = await strategy_runs_collection.find_one({"run_id": run_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunDetail(**_to_summary(doc).model_dump(), result=doc.get("result"), error=doc.get("error"))


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str, _current_user: dict = Depends(get_current_user)):
    stopped = await engine.stop_run(run_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="No active run with that ID (already stopped or one-shot)")
    return {"stopped": True}
