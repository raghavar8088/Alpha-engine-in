"""Commodity Trading desk API — 311 pattern strategies on MCX front-month futures.

  GET  /api/commodity/summary       desk capital, gate thresholds, market state
  GET  /api/commodity/leaderboard   every strategy with its verdict (filterable)
  GET  /api/commodity/catalog       the 39 templates x 8 timeframes, grouped
  GET  /api/commodity/positions     open + closed paper positions
  GET  /api/commodity/trades        closed-trade blotter, net of MCX charges
  GET  /api/commodity/equity        desk equity curve
  GET  /api/commodity/bars          bar-store coverage + a series for the chart
  GET  /api/commodity/universe      the 8 front-month contracts being traded
  POST /api/commodity/refresh-bars  force one paced bar refresh
  POST /api/commodity/run           force one scan+manage cycle
"""

import asyncio

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.db import (
    commodity_equity_collection,
    commodity_positions_collection,
    commodity_state_collection,
    commodity_trades_collection,
)
from app.services.commodity_bars import (
    coverage,
    front_month_universe,
    load_bars,
    refresh_all,
)
from app.services.commodity_engine import (
    STATE_ID,
    leaderboard as desk_leaderboard,
    run_cycle,
    summary as desk_summary,
)
from app.services.commodity_patterns import (
    CATALOG_TIMEFRAMES,
    COMMODITY_CATALOG,
    FAMILY_LABELS,
    TEMPLATES,
)

router = APIRouter(prefix="/api/commodity", tags=["commodity"])

# Strong refs to in-flight background refreshes (asyncio only holds weak ones).
_BACKGROUND: set[asyncio.Task] = set()


def _serialize(doc: dict, ts_fields: tuple[str, ...]) -> dict:
    doc.pop("_id", None)
    for key in ts_fields:
        if doc.get(key) is not None:
            doc[key] = doc[key].isoformat()
    return doc


@router.get("/summary")
async def summary_endpoint(_user: dict = Depends(get_current_user)):
    snap = await desk_summary()
    state = await commodity_state_collection.find_one({"_id": STATE_ID}) or {}
    snap["last_run_at"] = state["last_run_at"].isoformat() if state.get("last_run_at") else None
    snap["last_notes"] = state.get("last_notes", [])
    snap["last_evaluated"] = state.get("last_evaluated", 0)
    return snap


@router.get("/leaderboard")
async def leaderboard_endpoint(
    family: str | None = Query(None, description="chart | candlestick | structure"),
    timeframe: str | None = Query(None),
    verdict: str | None = Query(None, description="READY | REJECTED | PENDING"),
    limit: int = Query(400, ge=1, le=1000),
    _user: dict = Depends(get_current_user),
):
    rows = await desk_leaderboard()
    if family:
        rows = [r for r in rows if r["family"] == family]
    if timeframe:
        rows = [r for r in rows if r["timeframe"] == timeframe]
    if verdict:
        rows = [r for r in rows if r["verdict"] == verdict.upper()]
    return {"leaderboard": rows[:limit], "total": len(rows),
            "families": FAMILY_LABELS, "timeframes": CATALOG_TIMEFRAMES}


@router.get("/catalog")
async def catalog_endpoint(_user: dict = Depends(get_current_user)):
    by_family: dict[str, list[dict]] = {}
    for key, (family, label, _fn, params, min_bars) in TEMPLATES.items():
        by_family.setdefault(family, []).append(
            {"template": key, "label": label, "params": params, "min_bars": min_bars})
    return {
        "families": [{"family": f, "label": FAMILY_LABELS.get(f, f), "templates": t}
                     for f, t in by_family.items()],
        "timeframes": CATALOG_TIMEFRAMES,
        "template_count": len(TEMPLATES),
        "strategy_count": len(COMMODITY_CATALOG),
    }


@router.get("/universe")
async def universe_endpoint(_user: dict = Depends(get_current_user)):
    uni = await front_month_universe()
    return {"universe": [
        {"underlying": u, "symbol": d.get("symbol"), "expiry": d.get("expiry"),
         "security_id": str(d.get("security_id")), "lot_size": d.get("lot_size"),
         "tick_size": d.get("tick_size"), "exchange_segment": d.get("exchange_segment")}
        for u, d in sorted(uni.items())
    ]}


@router.get("/bars")
async def bars_endpoint(
    symbol: str | None = Query(None),
    timeframe: str = Query("15m"),
    limit: int = Query(200, ge=10, le=1000),
    _user: dict = Depends(get_current_user),
):
    cov = await coverage()
    series = []
    if symbol:
        series = [{"ts": b.ts.isoformat(), "open": b.open, "high": b.high,
                   "low": b.low, "close": b.close, "volume": b.volume}
                  for b in await load_bars(symbol, timeframe, limit)]
    return {"coverage": cov, "symbol": symbol, "timeframe": timeframe, "bars": series}


@router.get("/positions")
async def positions_endpoint(
    strategy_id: str | None = Query(None),
    status: str | None = Query(None, description="OPEN | CLOSED"),
    limit: int = Query(300, ge=1, le=1000),
    _user: dict = Depends(get_current_user),
):
    q: dict = {}
    if strategy_id:
        q["strategy_id"] = strategy_id
    if status:
        q["status"] = status.upper()
    cursor = commodity_positions_collection.find(q).sort("opened_at", -1).limit(limit)
    rows = [_serialize(d, ("opened_at", "updated_at", "closed_at", "entry_bar_ts")) async for d in cursor]
    return {"positions": rows, "open": [r for r in rows if r.get("status") == "OPEN"]}


@router.get("/trades")
async def trades_endpoint(
    strategy_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(get_current_user),
):
    q = {"strategy_id": strategy_id} if strategy_id else {}
    cursor = commodity_trades_collection.find(q).sort("closed_at", -1).limit(limit)
    return {"trades": [_serialize(d, ("opened_at", "closed_at")) async for d in cursor]}


@router.get("/equity")
async def equity_endpoint(limit: int = Query(500, ge=1, le=2000), _user: dict = Depends(get_current_user)):
    cursor = commodity_equity_collection.find({}).sort("ts", -1).limit(limit)
    points = [_serialize(d, ("ts",)) async for d in cursor]
    points.reverse()
    return {"equity": points}


@router.post("/refresh-bars")
async def refresh_bars_endpoint(_user: dict = Depends(get_current_user)):
    """Kick off one paced pass over every symbol x native interval.

    Fire-and-forget on purpose. A full pass is 40 throttled requests — at least a minute,
    and several if Angel starts 403ing and the backoff kicks in — which is far longer than
    any browser or proxy will hold a request open. Awaiting it here just produced an empty
    HTTP 000 while the work carried on regardless. Poll GET /bars for progress instead."""
    task = asyncio.create_task(refresh_all())
    # Hold a reference so the task is not garbage-collected mid-flight.
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    return {"started": True,
            "note": "Paced refresh started in the background (~1-3 min). Poll GET /api/commodity/bars "
                    "to watch the store fill."}


@router.post("/run")
async def run_endpoint(_user: dict = Depends(get_current_user)):
    return await run_cycle()
