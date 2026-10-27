"""Top-10 paper books API - Rs 2 lakh / Rs 10 lakh accounts on six desks' top 10 by Rank.

  GET  /api/top10-books/desks                          the desks, their picks and when they were picked
  GET  /api/top10-books/{desk}/summary?book=top2L      capital, equity, return, costs, skips
  GET  /api/top10-books/{desk}/leaderboard?book=       the ten: their record here and where they stood when picked
  GET  /api/top10-books/{desk}/positions?book=&status= OPEN | CLOSED | ALL
  POST /api/top10-books/{desk}/run                     copy that desk once, now

The books copy the desks' own trades (app.services.top10_books); nothing here places an order or
asks a broker for a price. `book` is normalized rather than rejected, as on the other book APIs.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services import top10_books as t10

router = APIRouter(prefix="/api/top10-books", tags=["top10-books"])


def _desk(desk: str) -> str:
    if t10.desk(desk) is None:
        raise HTTPException(status_code=404, detail=f"No top-10 books on '{desk}'")
    return desk


@router.get("/desks")
async def desks(_user: dict = Depends(get_current_user)):
    return {"picked_at": t10.PICKED_AT, "books": t10.BOOKS, "book_labels": t10.BOOK_LABEL,
            "desks": [{"desk": d.key, "label": d.label, "route": d.route, "instrument": d.instrument,
                       "max_open_positions": d.max_open,
                       "picks": [{"key": p.key, "name": p.name, "rank": p.rank, "score": p.score,
                                  "trades": p.trades} for p in d.picks]}
                      for d in t10.DESKS.values()]}


@router.get("/{desk}/summary")
async def summary(desk: str, book: str = Query("top2L"), _user: dict = Depends(get_current_user)):
    return await t10.summary(_desk(desk), book)


@router.get("/{desk}/leaderboard")
async def leaderboard(desk: str, book: str = Query("top2L"), _user: dict = Depends(get_current_user)):
    rows = await t10.leaderboard(_desk(desk), book)
    return {"desk": desk, "book": t10.normalize_book(book), "rows": rows, "total": len(rows)}


@router.get("/{desk}/positions")
async def positions(desk: str, book: str = Query("top2L"),
                    status: str = Query("OPEN", description="OPEN | CLOSED | ALL"),
                    limit: int = Query(200, ge=1, le=1000), _user: dict = Depends(get_current_user)):
    return {"desk": desk, "book": t10.normalize_book(book), "status": status.upper(),
            "positions": await t10.positions(_desk(desk), book, status, limit)}


@router.post("/{desk}/run")
async def run(desk: str, _user: dict = Depends(get_current_user)):
    return await t10.sync(entries=True, only=_desk(desk))
