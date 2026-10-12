"""Reset buttons for the Intraday Stocks paper books (app.services.book_reset).

Mounted under each desk's own prefix, so Main Control's switch for that desk gates its reset
exactly as it gates the desk's other endpoints:
  GET  /api/pattern-books/resets            last reset of the Rs50k / Rs2 lakh books
  GET  /api/pattern-books/reset-preview     what a reset of ?book= would delete
  POST /api/pattern-books/reset             {"book": "50k" | "2L", "confirm": "RESET"}
  (and the same three under /api/live-intraday for the Rs80k / Rs30k / Rs10k books)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import book_reset


class ResetRequest(BaseModel):
    book: str
    confirm: str = ""


def _router(desk: str) -> APIRouter:
    r = APIRouter(prefix=f"/api/{desk}", tags=[desk])

    @r.get("/resets")
    async def resets() -> dict:
        return await book_reset.history(desk)

    @r.get("/reset-preview")
    async def preview(book: str) -> dict:
        try:
            return await book_reset.preview(desk, book)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @r.post("/reset")
    async def reset(req: ResetRequest) -> dict:
        try:
            return await book_reset.reset(desk, req.book, req.confirm)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return r


pattern_books_router = _router("pattern-books")
live_intraday_router = _router("live-intraday")
