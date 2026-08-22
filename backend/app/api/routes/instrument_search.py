"""Instrument search API — app-wide, not owned by any one desk.

  GET  /api/search/instruments      ranked, typo-tolerant, enriched matches
  GET  /api/search/trending         the zero-query state: what is moving today, and why
  GET  /api/search/resolve/{symbol} one symbol, fully enriched
  GET  /api/search/stats            index size, alias health, NL availability
  POST /api/search/natural          English -> a filter you can see -> deterministic results
  POST /api/search/reindex          force a rebuild (after an instrument-master refresh)

Deliberately mounted at `/api/search` rather than under `/api/trending-stocks`: the
Watchlist, Positions and Chart modules all need the same thing, and a second copy of this
is exactly what the codebase does not need.
"""

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.services import instrument_search as S
from app.services.instrument_search.index import ensure_index

logger = logging.getLogger("instrument_search.api")

router = APIRouter(prefix="/api/search", tags=["search"])


class NaturalQuery(BaseModel):
    query: str = Field(..., min_length=2, max_length=400)
    limit: int = Field(20, ge=1, le=100)


@router.get("/instruments")
async def instruments_endpoint(
    q: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(12, ge=1, le=50),
    include_untradable: bool = Query(
        False, description="also return instruments with no broker token — visible, "
                           "but the desk can never price them"),
    debug: bool = Query(False, description="include the raw score behind each result"),
    _u: dict = Depends(get_current_user),
):
    return await S.search(q, limit=limit, include_untradable=include_untradable, debug=debug)


@router.get("/trending")
async def trending_endpoint(
    limit: int = Query(12, ge=1, le=50),
    sort: str = Query("1d", pattern="^(1d|1w|1m|6m)$"),
    _u: dict = Depends(get_current_user),
):
    return await S.trending(limit=limit, sort=sort)


@router.get("/resolve/{symbol}")
async def resolve_endpoint(symbol: str, _u: dict = Depends(get_current_user)):
    doc = await S.resolve(symbol)
    if doc is None:
        return {"error": f"{symbol.upper()} is not in the instrument master"}
    return doc


@router.get("/stats")
async def stats_endpoint(_u: dict = Depends(get_current_user)):
    return await S.stats()


@router.post("/natural")
async def natural_endpoint(payload: NaturalQuery, _u: dict = Depends(get_current_user)):
    return await S.nl_search(payload.query, limit=payload.limit)


@router.post("/reindex")
async def reindex_endpoint(_u: dict = Depends(get_current_user)):
    idx = await ensure_index(force=True)
    from app.services.instrument_search.enrich import ensure_snapshot
    snap = await ensure_snapshot(force=True)
    return {"rebuilt": True, "instruments": idx.size, "snapshot": snap}
