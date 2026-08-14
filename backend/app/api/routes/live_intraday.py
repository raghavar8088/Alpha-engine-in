"""Live Intraday desks API — the curated 8-strategy shortlist inside the Intraday Stocks
module, paper-trading on the live Angel-One feed across three books that differ only in
capital: Rs80,000, Rs30,000 and Rs10,000.

Every endpoint takes `?book=80k|30k|10k` (default 80k). The books are separate accounts,
not filters over one account, so a request without a book returns the 80k desk rather
than a blend of all three.

  GET  /api/live-intraday/summary      capital + ROI tiles for one book
  GET  /api/live-intraday/leaderboard  the 8 selected strategies, ranked, with ROI
  GET  /api/live-intraday/positions    open/closed paper positions
  GET  /api/live-intraday/trades       closed-trade blotter, with the cost of each
  GET  /api/live-intraday/daily        per-day realised P&L, fees and ROI
  POST /api/live-intraday/run          manually trigger one scan+manage cycle (all books)
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import (
    live_intraday_positions_collection,
    live_intraday_state_collection,
    live_intraday_trades_collection,
)
from app.services.dhan_client import DhanClient
from app.services.live_intraday_engine import (
    BOOKS,
    DEFAULT_BOOK,
    _state_id,
    daily as live_daily,
    leaderboard as live_leaderboard,
    run_cycle,
    summary as live_summary,
)

router = APIRouter(prefix="/api/live-intraday", tags=["live-intraday"])


def _book(book: str) -> str:
    if book not in BOOKS:
        raise HTTPException(400, f"unknown book {book!r} — expected one of {BOOKS}")
    return book


async def _optional_dhan(user_id: str) -> DhanClient | None:
    try:
        return await _get_dhan_client(user_id)
    except HTTPException:
        return None


def _serialize(doc: dict, ts_fields: tuple[str, ...]) -> dict:
    doc.pop("_id", None)
    for key in ts_fields:
        if doc.get(key) is not None:
            doc[key] = doc[key].isoformat()
    return doc


@router.get("/summary")
async def summary_endpoint(
    book: str = Query(DEFAULT_BOOK),
    current_user: dict = Depends(get_current_user),
):
    book = _book(book)
    snap = await live_summary(book)
    state = await live_intraday_state_collection.find_one({"_id": _state_id(book)}) or {}
    snap["last_run_at"] = state["last_run_at"].isoformat() if state.get("last_run_at") else None
    snap["broker_connected"] = state.get("broker_connected", False)
    snap["angel_configured"] = state.get("angel_configured", False)
    return snap


@router.get("/leaderboard")
async def leaderboard_endpoint(
    book: str = Query(DEFAULT_BOOK),
    current_user: dict = Depends(get_current_user),
):
    return {"book": _book(book), "leaderboard": await live_leaderboard(book)}


@router.get("/positions")
async def list_positions(
    strategy_id: str | None = Query(None),
    status: str | None = Query(None, description="OPEN | CLOSED"),
    book: str = Query(DEFAULT_BOOK),
    limit: int = Query(300, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    book = _book(book)
    query: dict = {"book": book}
    if strategy_id:
        query["strategy_id"] = strategy_id
    if status:
        query["status"] = status.upper()
    cursor = live_intraday_positions_collection.find(query).sort("opened_at", -1).limit(limit)
    positions = [_serialize(d, ("opened_at", "updated_at", "closed_at")) async for d in cursor]
    return {"positions": positions, "summary": await live_summary(book)}


@router.get("/trades")
async def list_trades(
    book: str = Query(DEFAULT_BOOK),
    limit: int = Query(200, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    cursor = live_intraday_trades_collection.find({"book": _book(book)}).sort("closed_at", -1).limit(limit)
    trades = [_serialize(d, ("opened_at", "closed_at")) async for d in cursor]
    return {"book": book, "trades": trades}


@router.get("/daily")
async def daily_endpoint(
    book: str = Query(DEFAULT_BOOK),
    limit: int = Query(60, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
):
    return {"book": _book(book), "daily": await live_daily(book, limit)}


@router.post("/run")
async def run_now(current_user: dict = Depends(get_current_user)):
    """One cycle drives ALL books — they share a single market-data sweep, so running
    them separately would triple the load on Angel for no benefit."""
    dhan = await _optional_dhan(str(current_user["_id"]))
    result = await run_cycle(dhan)
    result["broker_connected"] = dhan is not None
    return result
