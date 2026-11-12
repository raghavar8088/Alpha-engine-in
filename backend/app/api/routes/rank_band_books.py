"""Commodity Trading rank-band paper accounts (12 Nov 2026): Top 5, Top 5-10, Top 10-15, Top 15-20. Read only.

  GET /api/rank-band-books/books                       the four books, their five strategies each and when they were picked
  GET /api/rank-band-books/summary?book=top5           capital (Rs 10 lakh a strategy), equity, return, costs, skips
  GET /api/rank-band-books/leaderboard?book=           the five: each one's own Rs 10 lakh account and where it stood when picked
  GET /api/rank-band-books/positions?book=&status=     OPEN | CLOSED | ALL

The books copy the Commodity desk's own trades (app.services.rank_band_books); nothing here places an order. Paper only.
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services import rank_band_books as rb

router = APIRouter(prefix="/api/rank-band-books", tags=["rank-band-books"])


@router.get("/books")
async def books(_user: dict = Depends(get_current_user)):
    return {"desk": rb.DESK_KEY, "books": rb.books(), "enabled": rb.ENABLED}


@router.get("/summary")
async def summary(book: str = Query("top5"), _user: dict = Depends(get_current_user)):
    return await rb.summary(book)


@router.get("/leaderboard")
async def leaderboard(book: str = Query("top5"), _user: dict = Depends(get_current_user)):
    return {"book": rb.normalize_book(book), "rows": await rb.leaderboard(book)}


@router.get("/positions")
async def positions(book: str = Query("top5"), status: str = Query("OPEN"), limit: int = Query(200, ge=1, le=500),
                    _user: dict = Depends(get_current_user)):
    return {"book": rb.normalize_book(book), "positions": await rb.positions(book, status, limit)}
