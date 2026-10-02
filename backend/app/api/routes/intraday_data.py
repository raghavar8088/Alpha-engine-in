"""Intraday data plumbing — the liquid universe, live 15m bars, history, stocks in play.

  GET  /api/intraday-data/status            everything in one call: calendar, universe, stream,
                                            store, backfill/gap-fill/reconcile, candle pacer
  GET  /api/intraday-data/universe          today's universe (or the one for ?date=)
  GET  /api/intraday-data/bars/{symbol}     CLOSED bars, ?tf=15m|30m|45m|1h&n=
  GET  /api/intraday-data/in-play           the universe ranked by relative volume
  GET  /api/intraday-data/reconcile         the latest live-vs-candle comparison
  POST /api/intraday-data/backfill          start a history backfill (off-hours only)
  POST /api/intraday-data/reconcile         re-run the reconcile for ?date=
"""

import asyncio
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services import (global_cues, in_play, intraday_backfill, intraday_data_scheduler,
                          intraday_universe, market_calendar, nse_archives, preopen,
                          results_calendar)
from app.services.angel_stream import stream
from app.services.intraday_store import AGG_MINUTES, store, store5

router = APIRouter(prefix="/api/intraday-data", tags=["intraday-data"])

_jobs: dict[str, asyncio.Task] = {}


@router.get("/status")
async def status():
    uni = await intraday_universe.today(build_if_missing=False)
    syms = [m["symbol"] for m in (uni or {}).get("members", [])]
    return {
        "calendar": market_calendar.describe(),
        "universe": {"date": (uni or {}).get("date"), "size": len(syms),
                     "min_turnover_cr": (uni or {}).get("min_turnover_cr"),
                     "rule": (uni or {}).get("rule")},
        "stream": stream.describe(),
        "store": {**store.coverage(syms), **store.mem_stats()},
        "jobs": intraday_backfill.describe(),
        "last_reconcile": await intraday_backfill.last_reconcile(),
        "store_5m": {**store5.coverage(syms), **store5.mem_stats()},
        "nse_archives": nse_archives.describe(),
        "preopen": preopen.status,
        "results_calendar": results_calendar.status,
        "scheduler": intraday_data_scheduler.describe(),
    }


@router.get("/brief")
async def brief(date_: str | None = Query(None, alias="date")):
    """The day's market brief: global cues (08:40 / 09:05) and the NSE pre-open summary."""
    day = date.fromisoformat(date_) if date_ else None
    return await global_cues.latest_brief(day) or {}


@router.get("/results-calendar")
async def results_upcoming(days: int = Query(7, ge=0, le=60)):
    return {"upcoming": await results_calendar.upcoming(days)}


@router.get("/universe")
async def universe(date_: str | None = Query(None, alias="date")):
    doc = await (intraday_universe.on(date_) if date_ else intraday_universe.today())
    if not doc:
        raise HTTPException(404, "no universe stored for that date")
    doc.pop("_id", None)
    return doc


@router.get("/bars/{symbol}")
async def bars(symbol: str, tf: str = "15m", n: int = Query(200, ge=1, le=5000)):
    if tf not in AGG_MINUTES:
        raise HTTPException(400, f"tf must be one of {sorted(AGG_MINUTES)}")
    s = store.series(symbol.upper(), tf, n)
    src = {r[0]: r[6] for r in store.get(symbol.upper()).rows()}
    return {"symbol": symbol.upper(), "tf": tf, "count": len(s), "closed_only": True,
            "bars": [{"t": s.ts[i], "o": s.o[i], "h": s.h[i], "l": s.l[i], "c": s.c[i],
                      "v": s.v[i]} for i in range(len(s))],
            "stream_bars_in_memory": sum(1 for v in src.values() if v == 2)}


@router.get("/in-play")
async def stocks_in_play(top: int = Query(25, ge=1, le=200), k: int | None = Query(None, ge=1, le=25)):
    return await in_play.ranked(top=top, k=k)


@router.get("/reconcile")
async def reconcile_report():
    return await intraday_backfill.last_reconcile() or {}


def _start(name: str, coro) -> dict:
    task = _jobs.get(name)
    if task is not None and not task.done():
        coro.close()
        return {"started": False, "reason": f"{name} already running"}
    _jobs[name] = asyncio.create_task(coro)
    return {"started": True}


@router.post("/backfill")
async def start_backfill(days: int = Query(intraday_backfill.HISTORY_DAYS, ge=5, le=2200),
                         _u: dict = Depends(get_current_user)):
    if not intraday_backfill.off_hours():
        raise HTTPException(409, "backfill runs outside market hours only — the candle endpoint "
                                 "is shared with the live desks during the session")
    return _start("backfill", intraday_backfill.backfill(days=days))


@router.post("/reconcile")
async def start_reconcile(date_: str | None = Query(None, alias="date"),
                          _u: dict = Depends(get_current_user)):
    day = date.fromisoformat(date_) if date_ else datetime.now(market_calendar.IST).date()
    if not market_calendar.is_listed_trading_day(day):
        raise HTTPException(400, f"{day} was not a trading day")
    return _start("reconcile", intraday_backfill.reconcile(day))
