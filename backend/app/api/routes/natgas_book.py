"""Natural Gas Paper Trading — the Rs 2 lakh book on two picked NATGASMINI strategies.

  GET  /api/natgas-book/summary      capital, realised / unrealised / total P&L with %
  GET  /api/natgas-book/strategies   each picked strategy's record IN THIS BOOK
  GET  /api/natgas-book/positions    ?status=OPEN|CLOSED
  POST /api/natgas-book/toggle       {"enabled": bool} — entries only; open positions are
                                     always managed to their target or stop
  POST /api/natgas-book/run          one cycle now (manage + scan)
  POST /api/natgas-book/close-all    square off everything

Its own prefix rather than a sub-path of /api/commodity-prelive, so the Main Control
switch for this book is its own: turning the Pre-Live desk off must not silently stop a
book that was set up to trade regardless of that desk.
"""

from fastapi import APIRouter, Body, Depends, Query

from app.api.deps import get_current_user
from app.services import natgas_book

router = APIRouter(prefix="/api/natgas-book", tags=["natgas-book"])


@router.get("/summary")
async def summary(_current_user: dict = Depends(get_current_user)):
    return await natgas_book.summary()


@router.get("/strategies")
async def strategies(_current_user: dict = Depends(get_current_user)):
    return {"strategies": await natgas_book.strategies()}


@router.get("/positions")
async def positions(status: str = Query("OPEN", pattern="^(OPEN|CLOSED)$"),
                    limit: int = Query(200, ge=1, le=1000),
                    _current_user: dict = Depends(get_current_user)):
    return {"positions": await natgas_book.positions(status, limit)}


@router.post("/toggle")
async def toggle(payload: dict = Body(...), _current_user: dict = Depends(get_current_user)):
    return await natgas_book.set_enabled(bool(payload.get("enabled")))


@router.post("/run")
async def run(_current_user: dict = Depends(get_current_user)):
    return await natgas_book.run_cycle()


@router.post("/close-all")
async def close_all(_current_user: dict = Depends(get_current_user)):
    return await natgas_book.close_all()
