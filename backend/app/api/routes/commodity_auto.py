"""Commodity Auto Positions API - 220 paper accounts selling an MCX option strangle every evening.

  GET /api/commodity-auto/summary                 per-commodity totals, the next entry, the last run
  GET /api/commodity-auto/accounts?commodity=...  the 55 accounts of one commodity (11 strategies x 5 sizes)
  GET /api/commodity-auto/trades                  closed trades (?commodity=&offset=&size=&limit=)
  GET /api/commodity-auto/runs                    the last daily entry runs

Paper only (app.services.commodity_auto): nothing here reaches a broker.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services import commodity_auto as ca

router = APIRouter(prefix="/api/commodity-auto", tags=["commodity-auto"])


def _commodity(c: str | None) -> str | None:
    if c is None:
        return None
    c = c.upper()
    if c not in ca.MINIS:
        raise HTTPException(status_code=404, detail=f"Not one of this module's commodities: {', '.join(ca.MINIS)}")
    return c


@router.get("/summary")
async def summary(_user: dict = Depends(get_current_user)):
    return await ca.summary()


@router.get("/accounts")
async def accounts(commodity: str = Query(..., description="NATGASMINI | CRUDEOILM | GOLDM | SILVERM"),
                   _user: dict = Depends(get_current_user)):
    c = _commodity(commodity)
    return {"commodity": c, "accounts": await ca.accounts(c)}


@router.get("/trades")
async def trades(commodity: str | None = Query(None), offset: int | None = Query(None, ge=0, le=10),
                 size: int | None = Query(None), limit: int = Query(200, ge=1, le=1000),
                 _user: dict = Depends(get_current_user)):
    return {"trades": await ca.trades(_commodity(commodity), offset, size, limit)}


@router.get("/runs")
async def runs(limit: int = Query(10, ge=1, le=60), _user: dict = Depends(get_current_user)):
    return {"runs": await ca.runs(limit)}
