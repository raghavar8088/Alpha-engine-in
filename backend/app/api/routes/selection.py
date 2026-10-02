"""Stock selection — the Scanner Board, the pre-market brief, and the evidence behind them.

  GET  /api/selection/board              every scanner, ranked, with its evidence label (live, 60s cache)
  GET  /api/selection/snapshots          days with frozen snapshots, and each day's times (?date=)
  GET  /api/selection/snapshot           one frozen board (?date=YYYY-MM-DD&time=HH:MM)
  GET  /api/selection/brief              the pre-market brief (global, expected gap, VIX, results, ...)
  GET  /api/selection/evidence           every input considered, with its verdict and numbers
  GET  /api/selection/model              the expected-move model: weights, held-out accuracy, live record
  POST /api/selection/train              retrain the expected-move model (off-hours)
"""

import asyncio
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services import intraday_backfill, scanner_board, selection_brief

router = APIRouter(prefix="/api/selection", tags=["selection"])

_jobs: dict[str, asyncio.Task] = {}


@router.get("/board")
async def board():
    return await scanner_board.board()


@router.get("/snapshots")
async def snapshots(date_: str | None = Query(None, alias="date")):
    days = scanner_board.snapshot_days()
    day = date_ or (days[0] if days else None)
    return {"days": days, "date": day, "times": scanner_board.snapshots(day) if day else [],
            "schedule": list(scanner_board.SNAPSHOT_TIMES)}


@router.get("/snapshot")
async def snapshot(date_: str = Query(..., alias="date"), time_: str = Query(..., alias="time")):
    try:
        date.fromisoformat(date_)
        datetime.strptime(time_, "%H:%M")
    except ValueError as exc:
        raise HTTPException(400, "date must be YYYY-MM-DD and time HH:MM") from exc
    snap = scanner_board.load_snapshot(date_, time_)
    if snap is None:
        raise HTTPException(404, f"no snapshot for {date_} {time_}")
    return snap


@router.get("/brief")
async def brief():
    return await selection_brief.brief()


@router.get("/evidence")
async def evidence():
    return selection_brief.evidence()


@router.get("/model")
async def model():
    doc = await scanner_board.load_model()
    if doc:
        doc.pop("_id", None)
    return {"model": doc, "live_record": await scanner_board.accuracy_history(),
            "gap_model": await selection_brief.gap_model(), "gap_record": await selection_brief.gap_record(30)}


@router.post("/train")
async def train(_u: dict = Depends(get_current_user)):
    if not intraday_backfill.off_hours():
        raise HTTPException(409, "training reads two years of bars; it runs outside market hours")
    task = _jobs.get("train")
    if task is not None and not task.done():
        return {"started": False, "reason": "training already running"}
    _jobs["train"] = asyncio.create_task(scanner_board.train())
    return {"started": True}
