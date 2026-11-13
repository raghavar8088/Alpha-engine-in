"""Index Option Buying picked-strategy paper accounts (12 Nov 2026). Read only.

  GET /api/prelive-pick-books/books                         the three books, their picks and when they were picked
  GET /api/prelive-pick-books/summary?book=best2L           capital, equity, return, costs, skips
  GET /api/prelive-pick-books/leaderboard?book=             each pick: its record here and where it stood when picked
  GET /api/prelive-pick-books/positions?book=&status=       OPEN | CLOSED | ALL

Books: best2L (Best Strategies of Top 10, Rs 2 lakh), sf_top10 and sf_top10_20 (the Strategy Factory tab's
Rank 1-10 and 11-20, Rs 10 lakh each). They copy the desks' own trades (app.services.prelive_pick_books);
nothing here places an order. Paper only. The copy loop starts with this router.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services import prelive_pick_books as pb

router = APIRouter(prefix="/api/prelive-pick-books", tags=["prelive-pick-books"])
logger = logging.getLogger("prelive_pick_books")


async def _start_loop() -> None:
    """Registered on this router, not in main.py, so the books ship as one module; FastAPI's
    include_router hands the handler to the app. A startup hook must never raise."""
    if not pb.ENABLED:
        logger.info("Index Option Buying pick books disabled (PRELIVE_PICK_BOOKS_ENABLED=0)")
        return
    try:
        asyncio.create_task(pb.loop())
    except Exception:  # noqa: BLE001
        logger.exception("could not start the Index Option Buying pick books")


router.add_event_handler("startup", _start_loop)


@router.get("/books")
async def books(_user: dict = Depends(get_current_user)):
    return {"books": pb.books(), "enabled": pb.ENABLED, "picked_at": pb.PICKED_AT}


@router.get("/summary")
async def summary(book: str = Query("best2L"), _user: dict = Depends(get_current_user)):
    return await pb.summary(book)


@router.get("/leaderboard")
async def leaderboard(book: str = Query("best2L"), _user: dict = Depends(get_current_user)):
    rows = await pb.leaderboard(book)
    return {"book": pb.normalize_book(book), "rows": rows, "total": len(rows)}


@router.get("/positions")
async def positions(book: str = Query("best2L"), status: str = Query("OPEN", description="OPEN | CLOSED | ALL"),
                    limit: int = Query(200, ge=1, le=500), _user: dict = Depends(get_current_user)):
    return {"book": pb.normalize_book(book), "status": status.upper(),
            "positions": await pb.positions(book, status, limit)}
