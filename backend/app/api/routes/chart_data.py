"""Chart module — live candlestick charting backed by real Dhan OHLCV data,
rendered on the frontend with `lightweight-charts` (TradingView's free,
open-source charting library; the paid/gated Charting Library wasn't
available). See app.services.chart_data for the fetch/aggregation logic.

  GET /api/chart/search    instrument autocomplete (equities/ETFs/indices/futures)
  GET /api/chart/symbol     resolve one instrument's chart metadata
  GET /api/chart/history    OHLCV bars for a resolution + time range (UDF-ish shape)
  GET /api/chart/trendline  auto-detected swing-based trend line over recent bars
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.services.chart_data import ChartError, find_trend_points, get_bars, resolve_symbol, search_symbols

router = APIRouter(prefix="/api/chart", tags=["chart"])


async def _dhan(current_user: dict):
    try:
        return await _get_dhan_client(str(current_user["_id"]))
    except HTTPException:
        raise HTTPException(
            status_code=400,
            detail="Dhan account not connected — the Chart module needs a live broker connection for real candles.",
        )


@router.get("/search")
async def search(q: str = Query(..., min_length=1), current_user: dict = Depends(get_current_user)):
    return {"results": await search_symbols(q)}


@router.get("/symbol")
async def symbol(security_id: str, exchange_segment: str, current_user: dict = Depends(get_current_user)):
    try:
        return await resolve_symbol(security_id, exchange_segment)
    except ChartError as exc:
        raise HTTPException(status_code=404, detail=exc.detail)


@router.get("/history")
async def history(
    security_id: str, exchange_segment: str, resolution: str, from_ts: int = Query(..., alias="from"),
    to_ts: int = Query(..., alias="to"), current_user: dict = Depends(get_current_user),
):
    dhan = await _dhan(current_user)
    try:
        return await get_bars(dhan, security_id, exchange_segment, resolution, from_ts, to_ts)
    except ChartError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)


@router.get("/trendline")
async def trendline(
    security_id: str, exchange_segment: str, resolution: str = "D", lookback: int = Query(60, ge=10, le=300),
    current_user: dict = Depends(get_current_user),
):
    import time

    dhan = await _dhan(current_user)
    now = int(time.time())
    lookback_seconds = lookback * (86400 if resolution in ("D", "W") else int(resolution) * 60 * 3)
    try:
        bars = await get_bars(dhan, security_id, exchange_segment, resolution, now - lookback_seconds, now)
    except ChartError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    if bars["s"] != "ok":
        return {"trend": None}
    trend = find_trend_points(bars["h"], bars["l"], bars["t"], lookback=lookback)
    return {"trend": trend}
