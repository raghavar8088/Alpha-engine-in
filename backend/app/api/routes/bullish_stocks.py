"""Bullish Stocks API — the momentum screener that sits under Stocks Range.

  GET  /api/bullish-stocks/indices   the selectable index lists (same four as Stocks Range)
  GET  /api/bullish-stocks/screen    the screened table for one index
  POST /api/bullish-stocks/refresh-fundamentals  re-pull Yahoo fundamentals on demand
  POST /api/bullish-stocks/refresh-highs         re-walk history for all-time highs

`?all=true` returns every screened stock with its score instead of only the qualifiers,
which is how you inspect near-misses. `?force=true` bypasses the 5-minute cache.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services.bullish_stocks import BullishError, screen
from app.services.stock_fundamentals import refresh_fundamentals
from app.services.stock_highs import backfill_all_time_highs
from app.services.stocks_range import INDEX_LABELS

router = APIRouter(prefix="/api/bullish-stocks", tags=["bullish-stocks"])


@router.get("/indices")
async def indices(_current_user: dict = Depends(get_current_user)):
    return {"indices": [{"key": k, "label": v} for k, v in INDEX_LABELS.items()]}


@router.get("/screen")
async def screen_index(
    index: str = Query("nifty500"),
    all: bool = Query(False, description="include non-qualifying stocks with their score"),
    force: bool = Query(False, description="bypass the screen cache"),
    _current_user: dict = Depends(get_current_user),
):
    try:
        return await screen(index, qualified_only=not all, force=force)
    except BullishError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)


@router.post("/refresh-fundamentals")
async def refresh_funds(
    force: bool = Query(False, description="re-pull even symbols fetched in the last day"),
    limit: int | None = Query(None, description="cap how many symbols to pull this call"),
    _current_user: dict = Depends(get_current_user),
):
    return await refresh_fundamentals(force=force, limit=limit)


@router.post("/refresh-highs")
async def refresh_highs(
    rebuild: bool = Query(False, description="re-walk full history even for seeded symbols"),
    _current_user: dict = Depends(get_current_user),
):
    return await backfill_all_time_highs(only_missing=not rebuild)
