"""Indian Market Option Auto Selling API - paper accounts selling an index option call + put pair a day.

  GET /api/index-auto/summary              per-index totals, the schedule, the next entry, the last run
  GET /api/index-auto/accounts?index=...   the 55 accounts of one index (11 strategies x 5 sizes)
  GET /api/index-auto/trades               closed trades (?index=&offset=&size=&limit=)
  GET /api/index-auto/runs                 the last daily entry runs

Paper only (app.services.index_auto): nothing here reaches a broker.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services import index_auto as ia

router = APIRouter(prefix="/api/index-auto", tags=["index-auto"])


def _index(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.upper()
    if v not in ia.INDICES:
        raise HTTPException(status_code=404, detail=f"Not one of this module's indices: {', '.join(ia.INDICES)}")
    return v


@router.get("/summary")
async def summary(_user: dict = Depends(get_current_user)):
    return await ia.summary()


@router.get("/accounts")
async def accounts(index: str = Query(..., description="one of the configured indices, e.g. NIFTY"),
                   _user: dict = Depends(get_current_user)):
    ix = _index(index)
    return {"index": ix, "accounts": await ia.accounts(ix)}


@router.get("/trades")
async def trades(index: str | None = Query(None), offset: int | None = Query(None, ge=0, le=10),
                 size: int | None = Query(None), limit: int = Query(200, ge=1, le=1000),
                 _user: dict = Depends(get_current_user)):
    return {"trades": await ia.trades(_index(index), offset, size, limit)}


@router.get("/runs")
async def runs(limit: int = Query(10, ge=1, le=60), _user: dict = Depends(get_current_user)):
    return {"runs": await ia.runs(limit)}
