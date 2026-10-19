"""Angel One Commodity Live Trading Data - the owner's real Angel One MCX account, READ-ONLY
(app.services.angel_commodity_ledger). Nothing here can place or change an order.

  GET  /api/angel-commodity/summary   today's trades, orders and positions; every day's P&L,
                                      capital and ROI; averages and the month / year arithmetic
  POST /api/angel-commodity/sync      poll Angel now (inside the MCX window only)
  POST /api/angel-commodity/import    {"csv": <Angel trade-history CSV text>, "apply": false}
                                      preview first; apply=true writes the older days
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
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
