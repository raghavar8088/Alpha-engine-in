"""Live Paper Buying API — the Pre-Live leaderboard's winners on real-sized books.

Every endpoint takes `book`: `50k` (Live Paper Buying · ₹50k, the default, so the page
that existed before books did keeps working unchanged) or `2L` (Live Paper Trade · ₹2 lakh).

  GET  /api/live-paper/summary       capital, realised / unrealised / total P&L with %
  GET  /api/live-paper/leaderboard   the roster, ranked on this book's own trades
  GET  /api/live-paper/positions     open or closed positions
  GET  /api/live-paper/trades        closed-trade blotter
  GET  /api/live-paper/daily         realised P&L per session
  POST /api/live-paper/run           run one cycle now for BOTH books (?force=true outside
                                     market hours) — signals are shared, so a cycle is never
                                     per-book
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services.live_paper_buying import (
    daily_pnl,
    leaderboard as lp_leaderboard,
    positions as lp_positions,
    run_cycle,
    summary as lp_summary,
    trades as lp_trades,
)

router = APIRouter(prefix="/api/live-paper", tags=["live-paper"])

BOOK = Query("50k", pattern="^(50k|2L)$", description="50k | 2L")


@router.get("/summary")
async def summary_endpoint(book: str = BOOK, _u: dict = Depends(get_current_user)):
    return await lp_summary(book)


@router.get("/leaderboard")
async def leaderboard_endpoint(book: str = BOOK, _u: dict = Depends(get_current_user)):
    return {"leaderboard": await lp_leaderboard(book)}


@router.get("/positions")
async def positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED"),
    limit: int = Query(300, ge=1, le=1000),
    book: str = BOOK,
    _u: dict = Depends(get_current_user),
):
    return {"positions": await lp_positions(status, limit, book), "summary": await lp_summary(book)}


@router.get("/trades")
async def trades_endpoint(limit: int = Query(300, ge=1, le=1000), book: str = BOOK,
                          _u: dict = Depends(get_current_user)):
    return {"trades": await lp_trades(limit, book)}


@router.get("/daily")
async def daily_endpoint(limit: int = Query(60, ge=1, le=365), book: str = BOOK,
                         _u: dict = Depends(get_current_user)):
    return {"daily": await daily_pnl(limit, book)}


@router.post("/run")
async def run_endpoint(
    force: bool = Query(False, description="run outside market hours"),
    _u: dict = Depends(get_current_user),
):
    return await run_cycle(force=force)
