"""Selling Paper Books - picked rosters from the NIFTY option-SELLING desk, on one account.

  GET  /api/selling-books/summary?book=pt01
  GET  /api/selling-books/leaderboard?book=pt01
  GET  /api/selling-books/positions?book=pt01&status=OPEN|CLOSED|DECLINED|ALL
  POST /api/selling-books/run

Rs 10 lakh for EACH strategy (2026-11-13; app.services.selling_each_books), account = sf10 | desk10:
  GET  /api/selling-books/each/{account}/summary
  GET  /api/selling-books/each/{account}/strategies
  GET  /api/selling-books/each/{account}/positions?status=OPEN|CLOSED|SKIPPED|VOID|ALL
  POST /api/selling-books/each/run

The book follows the desk's own fills (see app.services.selling_paper_books), so there is
nothing here that places an order or asks the broker for a price. `book` is normalized
rather than rejected, so a stale tab asking for a book that has been renamed still renders.
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services import selling_each_books as each
from app.services import selling_paper_books as books

router = APIRouter(prefix="/api/selling-books", tags=["selling-books"])


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


@router.post("/run")
async def run_now(_u: dict = Depends(get_current_user)):
    """Follow the desk once, now. Safe at any hour: it only mirrors fills the desk has
    already made, so running it after the close cannot invent an after-hours entry."""
    return await books.run_cycle()


# -- Rs 10 lakh for EACH strategy: the top 10 of the Strategy Factory · 546 tab and the desk's top 10 -----------


@router.get("/each/{account}/summary")
async def get_each_summary(account: str, _u: dict = Depends(get_current_user)):
    return await each.summary(account)


@router.get("/each/{account}/strategies")
async def get_each_strategies(account: str, _u: dict = Depends(get_current_user)):
    return {"account": each.normalize_account(account), "rows": await each.strategies(account)}


@router.get("/each/{account}/positions")
async def get_each_positions(account: str, status: str = Query("OPEN"),
                             limit: int = Query(300, ge=1, le=2000),
                             _u: dict = Depends(get_current_user)):
    return {"account": each.normalize_account(account), "status": status.upper(),
            "positions": await each.positions(account, status, limit)}


@router.post("/each/run")
async def run_each_now(_u: dict = Depends(get_current_user)):
    """Bring both accounts up to their parents once, now. Safe at any hour: it only copies what the parents
    have already done."""
    return await each.run_cycle()
