"""Pattern Paper Books API — the pattern desk's shortlist at Rs 50,000 and Rs 2,00,000.

Two independent paper books running the SAME eight shortlisted strategies, differing only
in capital, so the effect of account size on a real edge is visible rather than assumed.
They mirror the pattern desk's fills; they never call Angel themselves.

  GET  /api/pattern-books/summary      capital, equity, ROI, fees, unaffordable skips
  GET  /api/pattern-books/leaderboard  the eight strategies, scored on this book
  GET  /api/pattern-books/positions    open or closed positions for one book
  GET  /api/pattern-books/trades       closed-trade blotter, net of real Angel fees
  GET  /api/pattern-books/strategies   the shortlist itself, with what it resolved to
  POST /api/pattern-books/run          force one mirror cycle
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services import pattern_books_engine as pb

router = APIRouter(prefix="/api/pattern-books", tags=["pattern-books"])


@router.get("/summary")
async def summary_endpoint(
    book: str = Query(pb.DEFAULT_BOOK, description="50k | 2L"),
    _user: dict = Depends(get_current_user),
):
    return await pb.summary(book)


@router.get("/leaderboard")
async def leaderboard_endpoint(
    book: str = Query(pb.DEFAULT_BOOK, description="50k | 2L"),
    _user: dict = Depends(get_current_user),
):
    rows = await pb.leaderboard(book)
    return {"book": pb.normalize_book(book), "rows": rows, "total": len(rows),
            "per_strategy_allocation": round(pb.per_strategy_allocation(book), 2),
            "note": ("ROI is on the strategy's own slice of the book, not on the whole "
                     "desk — eight slices each quoting a desk-level return would sum to "
                     "eight times what the book actually made.")}


@router.get("/positions")
async def positions_endpoint(
    book: str = Query(pb.DEFAULT_BOOK),
    status: str = Query("OPEN", description="OPEN | CLOSED | ALL"),
    limit: int = Query(300, ge=1, le=1000),
    _user: dict = Depends(get_current_user),
):
    rows = await pb.positions(book, status, limit)
    return {"book": pb.normalize_book(book), "positions": rows}


@router.get("/trades")
async def trades_endpoint(
    book: str = Query(pb.DEFAULT_BOOK),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(get_current_user),
):
    return {"book": pb.normalize_book(book), "trades": await pb.trades(book, limit)}


@router.get("/strategies")
async def strategies_endpoint(_user: dict = Depends(get_current_user)):
    """What the shortlist asked for, and what it actually resolved to.

    Reported rather than asserted: a template renamed upstream drops out with a warning
    instead of breaking startup, and this is where that becomes visible."""
    resolved = {(s.template, s.timeframe) for s in pb.SELECTED}
    return {
        "selected": [{"strategy_id": s.strategy_id, "name": s.name, "template": s.template,
                      "family": s.family, "timeframe": s.timeframe, "style": s.style}
                     for s in pb.SELECTED],
        "requested": [{"template": t, "timeframe": tf, "resolved": (t, tf) in resolved}
                      for t, tf in pb.SELECTED_SPECS],
        "count": len(pb.SELECTED),
        "books": pb.BOOKS, "book_capitals": pb.BOOK_CAPITAL, "book_labels": pb.BOOK_LABEL,
    }


@router.post("/run")
async def run_endpoint(_user: dict = Depends(get_current_user)):
    return await pb.run_cycle()
