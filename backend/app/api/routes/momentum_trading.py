"""Momentum Trading API — intraday cash-equity momentum (long 2% up / short 2% down).

  GET  /api/momentum-trading/summary     capital tiles, checkpoints, rule set
  GET  /api/momentum-trading/preview     who would be taken right now (read-only)
  GET  /api/momentum-trading/positions   open or closed positions
  GET  /api/momentum-trading/trades      closed-trade blotter
  GET  /api/momentum-trading/daily       realised P&L per session
  POST /api/momentum-trading/run         run a cycle now (?checkpoint=09:20 to force one)
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services.momentum_trading import (
    BUCKETS,
    TOP_BUCKET,
    daily_pnl,
    positions as mt_positions,
    preview as mt_preview,
    run_cycle,
    summary as mt_summary,
    trades as mt_trades,
)

router = APIRouter(prefix="/api/momentum-trading", tags=["momentum-trading"])


@router.get("/summary")
async def summary_endpoint(bucket: str = Query(TOP_BUCKET), _u: dict = Depends(get_current_user)):
    return await mt_summary(bucket if bucket in BUCKETS else TOP_BUCKET)


@router.get("/preview")
async def preview_endpoint(bucket: str = Query(TOP_BUCKET), _u: dict = Depends(get_current_user)):
    return await mt_preview(bucket if bucket in BUCKETS else TOP_BUCKET)


@router.get("/positions")
async def positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED"),
    limit: int = Query(300, ge=1, le=1000),
    bucket: str = Query(TOP_BUCKET),
    _u: dict = Depends(get_current_user),
):
    b = bucket if bucket in BUCKETS else TOP_BUCKET
    return {"positions": await mt_positions(status, limit, b), "summary": await mt_summary(b)}


@router.get("/trades")
async def trades_endpoint(limit: int = Query(300, ge=1, le=1000), bucket: str = Query(TOP_BUCKET),
                          _u: dict = Depends(get_current_user)):
    return {"trades": await mt_trades(limit, bucket if bucket in BUCKETS else TOP_BUCKET)}


@router.get("/daily")
async def daily_endpoint(limit: int = Query(60, ge=1, le=365), bucket: str = Query(TOP_BUCKET),
                         _u: dict = Depends(get_current_user)):
    return {"daily": await daily_pnl(limit, bucket if bucket in BUCKETS else TOP_BUCKET)}


@router.post("/run")
async def run_endpoint(
    checkpoint: str | None = Query(None, description="force a checkpoint, e.g. 09:20"),
    bucket: str = Query(TOP_BUCKET),
    _u: dict = Depends(get_current_user),
):
    return await run_cycle(force_checkpoint=checkpoint,
                           bucket=bucket if bucket in BUCKETS else TOP_BUCKET)


@router.post("/refresh-universe")
async def refresh_universe_endpoint(
    next_bucket: bool = Query(False, description="also rebuild the next-752 market-cap bucket"),
    cap_limit: int | None = Query(None, description="cap how many market caps to fetch this call"),
    _u: dict = Depends(get_current_user),
):
    from app.services.momentum_trading import refresh_next_bucket, refresh_universe

    out = {"top": await refresh_universe()}
    if next_bucket:
        out["next"] = await refresh_next_bucket(cap_limit=cap_limit)
    return out
