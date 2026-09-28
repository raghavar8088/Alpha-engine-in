"""Stock Pre-Live Paper Books - the buying desk's strategies on a Rs 10L / Rs 2L account.

  GET  /api/stock-books/summary?book=10L
  GET  /api/stock-books/leaderboard?book=10L
  GET  /api/stock-books/positions?book=10L&status=OPEN
  GET  /api/stock-books/trades?book=10L
  POST /api/stock-books/run

Both books mirror the parent desk's fills, so the only differences between them are account
size and the fees that size has to carry. `book` is normalized rather than rejected: an
unknown value falls back to the default instead of 422-ing a page that is only trying to
render.
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services import stock_desk_books as books

router = APIRouter(prefix="/api/stock-books", tags=["stock-books"])


@router.get("/summary")
async def get_summary(book: str = Query(books.DEFAULT_BOOK),
                      _u: dict = Depends(get_current_user)):
    return await books.summary(book)


@router.get("/leaderboard")
async def get_leaderboard(book: str = Query(books.DEFAULT_BOOK),
                          _u: dict = Depends(get_current_user)):
    return {"book": books.normalize_book(book), "rows": await books.leaderboard(book)}


@router.get("/positions")
async def get_positions(book: str = Query(books.DEFAULT_BOOK),
                        status: str = Query("OPEN"),
                        limit: int = Query(400, ge=1, le=2000),
                        _u: dict = Depends(get_current_user)):
    return {"book": books.normalize_book(book), "status": status.upper(),
            "positions": await books.positions(book, status, limit)}


@router.get("/trades")
async def get_trades(book: str = Query(books.DEFAULT_BOOK),
                     limit: int = Query(200, ge=1, le=2000),
                     _u: dict = Depends(get_current_user)):
    return {"book": books.normalize_book(book), "trades": await books.trades(book, limit)}


@router.post("/run")
async def run_now(_u: dict = Depends(get_current_user)):
    """Follow the parent desk once, now. The scheduler does this on every desk tick; this is
    here so a change can be seen without waiting for one."""
    return await books.run_cycle()
