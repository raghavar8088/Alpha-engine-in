"""Pattern desk API — 63 chart/candle/indicator templates x 8 timeframes on NSE equities.

  GET  /api/pattern/summary       capital, ROI, costs, universe and timeframe config
  GET  /api/pattern/leaderboard   every strategy ranked, filterable by timeframe/family
  GET  /api/pattern/timeframes    which horizon is working, aggregated
  GET  /api/pattern/positions     open / closed
  POST /api/pattern/run           trigger one manage+scan cycle
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services.response_cache import cached as _cached
from app.services import intraday_pattern_engine as pat

router = APIRouter(prefix="/api/pattern", tags=["pattern"])


async def _env(key: str, coro):
    return {key: await coro}


@router.get("/summary")
async def summary_endpoint(
    fresh: bool = Query(False, description="bypass the short cache"),
    current_user: dict = Depends(get_current_user),
):
    return await _cached("pat:summary", pat.summary, fresh=fresh)


@router.get("/leaderboard")
async def leaderboard_endpoint(
    timeframe: str | None = Query(None, description="1m|5m|15m|30m|45m|1h|4h|1d"),
    family: str | None = Query(None, description="chart_pattern|pattern|trend|breakout|momentum|mean_reversion"),
    limit: int = Query(600, ge=1, le=600),
    fresh: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    return await _cached(
        f"pat:lb:{timeframe}:{family}:{limit}",
        lambda: _env("leaderboard", pat.leaderboard(timeframe, family, limit)), fresh=fresh)


@router.get("/timeframes")
async def timeframes_endpoint(
    fresh: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    return await _cached("pat:tf", lambda: _env("timeframes", pat.timeframe_stats()), fresh=fresh)


@router.get("/positions")
async def positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED | ALL"),
    timeframe: str | None = Query(None),
    limit: int = Query(400, ge=1, le=1000),
    fresh: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    async def build():
        return {"positions": await pat.positions(status, limit, timeframe),
                "summary": await pat.summary()}

    return await _cached(f"pat:pos:{status}:{timeframe}:{limit}", build, fresh=fresh)


@router.post("/run")
async def run_endpoint(current_user: dict = Depends(get_current_user)):
    return await pat.run_cycle()
