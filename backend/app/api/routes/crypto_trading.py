"""Crypto Trading API - the top ten cryptocurrencies paper traded by the Strategy Factory's and the
Strategies module's strategies, one $10,000 account per strategy-cryptocurrency pair.

  GET  /api/crypto-trading/overview     the desk: state, universe, accounts by status, money, equity
  GET  /api/crypto-trading/universe     the ten coins, every candidate's verdict, the ranking source and time
  GET  /api/crypto-trading/library      the strategy library and each strategy's crypto verdict
  GET  /api/crypto-trading/backtests    every pair's crypto backtest and grade (filters, sorting, pages)
  GET  /api/crypto-trading/pair?id=     one pair: its backtest, account, positions and equity
  GET  /api/crypto-trading/signals      the live signal feed
  GET  /api/crypto-trading/positions    open positions (?status=OPEN) and completed trades (?status=CLOSED)
  GET  /api/crypto-trading/accounts     the accounts, ranked (filters, sorting, pages)
  GET  /api/crypto-trading/equity       the desk's equity, hourly
  POST /api/crypto-trading/control      {"action": "start" | "pause" | "resume"}
  POST /api/crypto-trading/reset        {"confirm": "RESET CRYPTO TRADING"}

Paper only (app.services.crypto_trading): nothing here reaches a broker.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services.crypto_trading import engine, views
from app.services.crypto_trading.config import TIMEFRAMES

router = APIRouter(prefix="/api/crypto-trading", tags=["crypto-trading"])

_STATUS = Literal["eligible", "failed_validation", "insufficient_data", "unsupported", "error"]
_LIB = Literal["factory", "strategies"]


def _tf(tf: str | None) -> str | None:
    if tf is not None and tf not in TIMEFRAMES:
        raise HTTPException(status_code=422, detail=f"timeframe must be one of {', '.join(TIMEFRAMES)}")
    return tf


@router.get("/overview")
async def overview(_user: dict = Depends(get_current_user)):
    return await views.overview()


@router.get("/universe")
async def universe(_user: dict = Depends(get_current_user)):
    return await views.universe()


@router.get("/library")
async def library(q: str = Query("", max_length=80), library: _LIB | None = None,
                  support: Literal["supported", "adapted", "unsupported"] | None = None,
                  timeframe: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                  _user: dict = Depends(get_current_user)):
    return await views.library(q, library, support, _tf(timeframe), offset, limit)


@router.get("/backtests")
async def backtests(status: _STATUS | None = None, symbol: str | None = None, timeframe: str | None = None,
                    library: _LIB | None = None, min_grade: int | None = Query(None, ge=1, le=5),
                    q: str = Query("", max_length=80),
                    sort: Literal["grade", "net", "pf", "trades", "oos", "dd", "sharpe"] = "grade",
                    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                    _user: dict = Depends(get_current_user)):
    return await views.backtests(status, symbol, _tf(timeframe), library, min_grade, q, sort, offset, limit)


@router.get("/pair")
async def pair(id: str = Query(..., max_length=120), _user: dict = Depends(get_current_user)):
    d = await views.pair(id)
    if d is None:
        raise HTTPException(status_code=404, detail=f"no such strategy-cryptocurrency pair: {id}")
    return d


@router.get("/signals")
async def signals(limit: int = Query(200, ge=1, le=1000), symbol: str | None = None, taken: bool | None = None,
                  _user: dict = Depends(get_current_user)):
    return {"signals": await views.signals(limit, symbol, taken)}


@router.get("/positions")
async def positions(status: Literal["OPEN", "CLOSED"] = "OPEN", symbol: str | None = None,
                    library: _LIB | None = None, limit: int = Query(300, ge=1, le=2000),
                    _user: dict = Depends(get_current_user)):
    return {"positions": await views.positions(status, symbol, library, limit)}


@router.get("/accounts")
async def accounts(status: _STATUS | None = None, symbol: str | None = None, timeframe: str | None = None,
                   library: _LIB | None = None, min_grade: int | None = Query(None, ge=1, le=5),
                   q: str = Query("", max_length=80), trading: bool | None = None, traded: bool | None = None,
                   sort: Literal["equity", "realized", "trades", "grade", "drawdown", "costs", "worst"] = "equity",
                   offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                   _user: dict = Depends(get_current_user)):
    return await views.accounts(status, symbol, _tf(timeframe), library, min_grade, q, trading, traded, sort,
                                offset, limit)


@router.get("/equity")
async def equity(days: int = Query(45, ge=1, le=400), _user: dict = Depends(get_current_user)):
    return {"points": await views.equity(days)}


class ControlIn(BaseModel):
    action: Literal["start", "pause", "resume"]


class ResetIn(BaseModel):
    confirm: str


@router.post("/control")
async def control(body: ControlIn, _user: dict = Depends(get_current_user)):
    try:
        return views._clean(await engine.control(body.action, by="page"))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/reset")
async def reset(body: ResetIn, _user: dict = Depends(get_current_user)):
    try:
        return views._clean(await engine.reset(body.confirm, by="page"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
