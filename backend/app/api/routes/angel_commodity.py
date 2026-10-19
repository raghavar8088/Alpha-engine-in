"""Angel One Commodity Live Trading Data - the owner's real Angel One MCX account, READ-ONLY
(app.services.angel_commodity_ledger). Nothing here can place or change an order.

  GET  /api/angel-commodity/summary   today's trades, orders and positions; every day's P&L,
                                      capital and ROI; averages and the month / year arithmetic
  POST /api/angel-commodity/sync      poll Angel now (inside the MCX window only)
  POST /api/angel-commodity/import    {"csv": <Angel trade-history CSV text>, "apply": false}
                                      preview first; apply=true writes the older days
  GET  /api/angel-commodity/analytics trades, statistics, breakdowns, performance, periods, charges
  GET  /api/angel-commodity/risk      open positions now: Greeks, margin, scenarios
  GET  /api/angel-commodity/day/{d}   one day in full
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.services import angel_commodity_analytics as A
from app.services import angel_commodity_ledger as L

router = APIRouter(prefix="/api/angel-commodity", tags=["angel-commodity"])


class ImportRequest(BaseModel):
    csv: str = Field(..., max_length=20_000_000)
    apply: bool = False


@router.get("/summary")
async def summary(current_user: dict = Depends(get_current_user)) -> dict:
    return await L.summary()


@router.post("/sync")
async def sync(current_user: dict = Depends(get_current_user)) -> dict:
    try:
        return await L.capture()
    except Exception as exc:  # noqa: BLE001 - shown to the user as the reason
        raise HTTPException(status_code=502, detail=f"Angel One did not answer: {exc}") from exc


@router.post("/import")
async def import_tradebook(req: ImportRequest, current_user: dict = Depends(get_current_user)) -> dict:
    try:
        return await L.import_tradebook(req.csv, apply=req.apply)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Could not read the file: {exc}") from exc


@router.get("/analytics")
async def analytics(current_user: dict = Depends(get_current_user)) -> dict:
    """Round trips, trade statistics and breakdowns, drawdown and risk-adjusted returns,
    weekly / monthly periods, charges by component, orders, data coverage."""
    return await A.analytics()


@router.get("/risk")
async def risk(current_user: dict = Depends(get_current_user)) -> dict:
    """Open positions re-quoted now: Greeks, days to expiry, moneyness, breakeven, margin per
    position, totals by commodity and the what-if grid."""
    return await A.risk()


@router.get("/day/{day}")
async def day_detail(day: str, current_user: dict = Depends(get_current_user)) -> dict:
    """One day in full: its fills, orders, positions at the last poll, the 5-minute P&L and
    capital curve, the trades closed that day and each order's charges."""
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD") from exc
    return await A.day_detail(day)
