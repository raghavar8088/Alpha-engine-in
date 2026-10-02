"""Operations for the intraday desks: alarms and the daily edge report.

  GET  /api/intraday-ops/alarms           alarms of the last ?days= sessions, active first
  POST /api/intraday-ops/alarms/check     evaluate every alarm condition now
  GET  /api/intraday-ops/edge-report      the edge report for ?date= (default: the latest)
  GET  /api/intraday-ops/edge-reports     the last ?limit= reports' desk lines
  POST /api/intraday-ops/edge-report      rebuild the report for ?date=
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services import intraday_ops

router = APIRouter(prefix="/api/intraday-ops", tags=["intraday-ops"])


@router.get("/alarms")
async def alarms(days: int = Query(7, ge=1, le=60)):
    rows = await intraday_ops.open_alarms(days)
    rows.sort(key=lambda a: (not a.get("active"), a.get("session", "")), reverse=False)
    return {"active": [a for a in rows if a.get("active")], "recent": rows}


@router.post("/alarms/check")
async def check(_u: dict = Depends(get_current_user)):
    return await intraday_ops.check_once()


@router.get("/edge-report")
async def edge_report(date_: str | None = Query(None, alias="date")):
    if date_:
        doc = await intraday_ops.reports.find_one({"_id": date_})
    else:
        doc = await intraday_ops.reports.find_one({}, sort=[("_id", -1)])
    if not doc:
        return {}
    doc.pop("_id", None)
    return doc


@router.get("/edge-reports")
async def edge_reports(limit: int = Query(30, ge=1, le=250)):
    out = []
    async for d in intraday_ops.reports.find({}, {"date": 1, "desk": 1, "calibration.median_gap_per_trade": 1,
                                                  "calibration.strategies_compared": 1}).sort("_id", -1).limit(limit):
        d.pop("_id", None)
        out.append(d)
    return {"reports": out}


@router.post("/edge-report")
async def rebuild(date_: str | None = Query(None, alias="date"), _u: dict = Depends(get_current_user)):
    try:
        day = date.fromisoformat(date_) if date_ else None
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    return await intraday_ops.build_edge_report(day)
