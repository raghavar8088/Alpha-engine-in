"""NIFTY 50 Option Scalping API — 504 candle/indicator strategies (63 templates x 8
timeframes) buying near-expiry ATM NIFTY options on Rs2,00,000 each. Thirteen of the
templates are geometric chart patterns, filterable via `family=chart_pattern`.

  GET  /api/nifty-scalp/summary      desk capital, ROI, costs, expiry in use
  GET  /api/nifty-scalp/leaderboard  every strategy ranked, filterable by timeframe
  GET  /api/nifty-scalp/timeframes   which HORIZON is working, 50 strategies aggregated
  GET  /api/nifty-scalp/positions    open/closed option positions
  GET  /api/nifty-scalp/signals      signal history, including ones not funded
  GET  /api/nifty-scalp/daily        per-day realised P&L, fees and ROI
  POST /api/nifty-scalp/run          trigger one manage+scan cycle

The Rs 2,00,000 PAPER BOOK — a hand-picked roster of those same strategies sharing ONE
book, which is the question the desk above cannot answer because there every strategy has
its own Rs 2 lakh and none of them compete for it.

  GET  /api/nifty-scalp/paper/summary    book capital, ROI, cash, breaker
  GET  /api/nifty-scalp/paper/roster     the picks, with their record HERE and on the desk
  PUT  /api/nifty-scalp/paper/roster     replace the picks
  GET  /api/nifty-scalp/paper/positions  open/closed option positions on the book
  GET  /api/nifty-scalp/paper/daily      per-day realised P&L, fees and ROI
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.services import nifty_scalp_paper as paper
from app.services.response_cache import cached as _cached, invalidate as _invalidate
from app.services.nifty_scalp_engine import (
    daily as ns_daily,
    leaderboard as ns_leaderboard,
    positions as ns_positions,
    run_cycle,
    signals as ns_signals,
    summary as ns_summary,
    timeframe_stats,
)


async def _wrap(key: str, coro):
    """Cache the wrapped envelope, not the bare list, so the cached value is exactly the
    response body."""
    return {key: await coro}


async def _envelope(key: str, coro):
    """Cache the response BODY, not the bare list, so a hit and a miss are identical."""
    return {key: await coro}

router = APIRouter(prefix="/api/nifty-scalp", tags=["nifty-scalp"])


@router.get("/summary")
async def summary_endpoint(
    fresh: bool = Query(False, description="bypass the short cache; the refresh button sends this"),
    current_user: dict = Depends(get_current_user),
):
    return await _cached("nscalp:summary", ns_summary, fresh=fresh)


@router.get("/leaderboard")
async def leaderboard_endpoint(
    timeframe: str | None = Query(None, description="1m|5m|10m|15m|30m|1h|4h|1d"),
    family: str | None = Query(None, description="e.g. chart_pattern, trend, breakout"),
    limit: int = Query(1000, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
    fresh: bool = Query(False, description="bypass the short cache"),
):
    async def build():
        rows = await ns_leaderboard(timeframe, limit)
        if family:
            rows = [r for r in rows if r["family"] == family]
        return {"leaderboard": rows}

    return await _cached(f"nscalp:lb:{timeframe}:{family}:{limit}", build, fresh=fresh)


@router.get("/timeframes")
async def timeframes_endpoint(
    fresh: bool = Query(False, description="bypass the short cache"),
    current_user: dict = Depends(get_current_user),
):
    return await _cached(
        "nscalp:timeframes", lambda: _wrap("timeframes", timeframe_stats()), fresh=fresh)


@router.get("/positions")
async def positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED | ALL"),
    timeframe: str | None = Query(None),
    limit: int = Query(300, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
    fresh: bool = Query(False, description="bypass the short cache"),
):
    async def build():
        return {"positions": await ns_positions(status, limit, timeframe),
                "summary": await ns_summary()}

    return await _cached(f"nscalp:pos:{status}:{timeframe}:{limit}", build, fresh=fresh)


@router.get("/signals")
async def signals_endpoint(
    limit: int = Query(200, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    return {"signals": await ns_signals(limit)}


@router.get("/daily")
async def daily_endpoint(
    limit: int = Query(60, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
    fresh: bool = Query(False, description="bypass the short cache"),
):
    return await _cached(f"nscalp:daily:{limit}",
                         lambda: _envelope("daily", ns_daily(limit)), fresh=fresh)


@router.post("/run")
async def run_endpoint(current_user: dict = Depends(get_current_user)):
    return await run_cycle()


# ── the Rs 2 lakh paper book ───────────────────────────────────────────────────


class RosterRequest(BaseModel):
    strategy_ids: list[str] = Field(..., min_length=1, max_length=100)


@router.get("/paper/summary")
async def paper_summary_endpoint(
    fresh: bool = Query(False, description="bypass the short cache"),
    current_user: dict = Depends(get_current_user),
):
    return await _cached("nscalp:paper:summary", paper.summary, fresh=fresh)


@router.get("/paper/roster")
async def paper_roster_endpoint(
    fresh: bool = Query(False, description="bypass the short cache"),
    current_user: dict = Depends(get_current_user),
):
    return await _cached("nscalp:paper:roster",
                         lambda: _envelope("roster", paper.roster_rows()), fresh=fresh)


@router.put("/paper/roster")
async def paper_set_roster_endpoint(
    payload: RosterRequest,
    current_user: dict = Depends(get_current_user),
):
    """Replace the roster. Ids that this desk does not know are REPORTED, not silently
    dropped — a typo that quietly shrinks the book would be invisible otherwise."""
    try:
        res = await paper.set_roster(payload.strategy_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # Every paper read is cached for a few seconds. Without this drop, the reload the UI
    # fires straight after saving is served the PREVIOUS roster, and adding a strategy
    # looks like it silently did nothing.
    _invalidate("nscalp:paper:")
    return res


@router.get("/paper/positions")
async def paper_positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED | ALL"),
    limit: int = Query(300, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
    fresh: bool = Query(False, description="bypass the short cache"),
):
    async def build():
        return {"positions": await paper.positions(status, limit),
                "summary": await paper.summary()}

    return await _cached(f"nscalp:paper:pos:{status}:{limit}", build, fresh=fresh)


@router.get("/paper/daily")
async def paper_daily_endpoint(
    limit: int = Query(60, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
    fresh: bool = Query(False, description="bypass the short cache"),
):
    return await _cached(f"nscalp:paper:daily:{limit}",
                         lambda: _envelope("daily", paper.daily(limit)), fresh=fresh)
