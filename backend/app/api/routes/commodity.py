"""Commodity Trading desk API — 311 pattern strategies on MCX front-month futures.

  GET  /api/commodity/summary       desk capital, gate thresholds, market state
  GET  /api/commodity/leaderboard   every strategy with its verdict (filterable)
  GET  /api/commodity/scripts       one row per underlying — how the desk did on each
  GET  /api/commodity/scripts/{sym} the leaderboard for ONE contract, gate re-run on it
  GET  /api/commodity/catalog       the 39 templates x 8 timeframes, grouped
  GET  /api/commodity/positions     open + closed paper positions
  GET  /api/commodity/trades        closed-trade blotter, net of MCX charges
  GET  /api/commodity/equity        desk equity curve
  GET  /api/commodity/bars          bar-store coverage + a series for the chart
  GET  /api/commodity/universe      the 8 front-month contracts being traded
  POST /api/commodity/refresh-bars  force one paced bar refresh
  POST /api/commodity/run           force one scan+manage cycle
  GET  /api/commodity/records       honest per-strategy records, luck line, data quality (C1)
  POST /api/commodity/relabel       re-run the trade labels (honest / stale / void / repriced)
  GET  /api/commodity/market        MCX calendar, contract roll rules, quoted spreads (C0/C2)
  GET  /api/commodity/lab           latest Commodity Lab run + every verdict (C4)
  POST /api/commodity/lab/run       start the Lab job in its own process
  GET  /api/commodity/hypotheses    pre-registered HC1-HC4 with forward status (C5)
  GET  /api/commodity/trend-book    the HC1 paper book: legs, equity, trades, last targets
  GET  /api/commodity/real-money    MCX executor readiness — locked (C6)
  POST /api/commodity/real-money/arm | /disarm | /kill
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

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
    script_overview,
    script_leaderboard,
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


@router.get("/scripts")
async def scripts_overview(fresh: bool = Query(False),
                           _user: dict = Depends(get_current_user)):
    """How the whole desk performed on each underlying, side by side."""
    return await script_overview(fresh)


@router.get("/scripts/{symbol}")
async def script_board(
    symbol: str,
    family: str | None = Query(None, description="chart | candlestick | structure"),
    timeframe: str | None = Query(None),
    verdict: str | None = Query(None, description="READY | REJECTED | PENDING"),
    limit: int = Query(400, ge=1, le=1000),
    fresh: bool = Query(False),
    _user: dict = Depends(get_current_user),
):
    """The strategy leaderboard for ONE contract.

    The stats and the promotion gate are recomputed from that contract's trades alone, so
    a READY here means "clears the gate on THIS underlying" — which the blended board on
    the main page does not tell you.
    """
    data = await script_leaderboard(symbol, fresh)
    rows = data.get("rows") or []
    if family:
        rows = [r for r in rows if r["family"] == family]
    if timeframe:
        rows = [r for r in rows if r["timeframe"] == timeframe]
    if verdict:
        rows = [r for r in rows if r["verdict"] == verdict.upper()]
    return {**data, "rows": rows[:limit], "total": len(rows),
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


@router.get("/records")
async def records_endpoint(fresh: bool = Query(False), _user: dict = Depends(get_current_user)):
    """The desk's honest record: what each strategy did on trades filled at a live quote,
    with MCX open, on its own contract — and how many strong-looking records luck alone
    would produce among this many strategies."""
    from app.services.commodity_records import records

    return await records(fresh)


@router.post("/relabel")
async def relabel_endpoint(_user: dict = Depends(get_current_user)):
    from app.services.commodity_engine import rescore_all
    from app.services.commodity_records import relabel

    out = await relabel(force=True)
    out["rescored"] = await rescore_all()
    if out.get("at") is not None and hasattr(out["at"], "isoformat"):
        out["at"] = out["at"].isoformat()
    return out


@router.get("/market")
async def market_endpoint(_user: dict = Depends(get_current_user)):
    """MCX sessions and holidays, which contract each underlying trades and when it must be
    left (delivery window), and the spreads the market has actually quoted."""
    from tradingai_shared import mcx_calendar as mcal

    from app.services import mcx_market
    from app.services.commodity_bars import LIQUID_UNDERLYINGS

    listed = await mcx_market.listed_futures(LIQUID_UNDERLYINGS)
    today = mcal.as_date(None)
    rows = []
    for u in LIQUID_UNDERLYINGS:
        tradable = mcx_market.tradable_contract(listed.get(u, []), u, today)
        contracts = []
        for d in listed.get(u, [])[:4]:
            exp = d.get("expiry")
            contracts.append({"symbol": d.get("symbol"), "expiry": exp,
                              "trading_days_left": mcal.trading_days_to(exp, today),
                              "in_exit_window": mcx_market.in_exit_window(u, exp, today),
                              "tradable": bool(tradable and tradable.get("expiry") == exp)})
        rows.append({"underlying": u, "settlement": mcx_market.settlement(u),
                     "exit_days": mcx_market.exit_days(u),
                     "trading": tradable.get("symbol") if tradable else None, "contracts": contracts})
    from app.services.mcx_curve_recorder import status as curve_status

    return {"calendar": mcal.describe(), "contracts": rows,
            "spreads_30d": await mcx_market.spread_stats(30),
            "stale_after_min": mcx_market.STALE_AFTER_MIN,
            "curve_recorder": await curve_status()}


@router.get("/lab")
async def lab_endpoint(full: bool = Query(False), _user: dict = Depends(get_current_user)):
    from app.services.commodity_lab import latest_run, verdicts

    return {"run": await latest_run(full), "verdicts": await verdicts()}


_LAB_PROC: dict = {}


@router.post("/lab/run")
async def lab_run_endpoint(_user: dict = Depends(get_current_user)):
    """Start the Lab job in its own process (minutes of CPU). Poll GET /lab for the result."""
    import sys

    p = _LAB_PROC.get("proc")
    if p is not None and p.returncode is None:
        return {"started": False, "note": f"a Lab run is already in progress (pid {p.pid})"}
    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.services.commodity_lab_job")
    _LAB_PROC["proc"] = proc
    task = asyncio.create_task(proc.wait())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    return {"started": True, "pid": proc.pid, "note": "Runs for a few minutes; GET /api/commodity/lab shows the result."}


@router.get("/hypotheses")
async def hypotheses_endpoint(_user: dict = Depends(get_current_user)):
    from app.services.commodity_hypotheses import listing

    return {"hypotheses": await listing()}


@router.get("/trend-book")
async def trend_book_endpoint(_user: dict = Depends(get_current_user)):
    from app.services.commodity_trend_book import summary

    return await summary()


@router.get("/real-money")
async def real_money_endpoint(_user: dict = Depends(get_current_user)):
    from app.services.mcx_live_executor import readiness

    return await readiness()


class ArmRequest(BaseModel):
    strategy: str
    confirm: str


class KillRequest(BaseModel):
    active: bool
    reason: str | None = None


@router.post("/real-money/arm")
async def real_money_arm(req: ArmRequest, user: dict = Depends(get_current_user)):
    from app.services.mcx_live_executor import arm

    out = await arm(req.strategy, req.confirm, str(user.get("email") or user.get("sub") or "user"))
    if not out.get("armed"):
        raise HTTPException(status_code=409, detail={"refused": out.get("refused")})
    return out


@router.post("/real-money/disarm")
async def real_money_disarm(_user: dict = Depends(get_current_user)):
    from app.services.mcx_live_executor import disarm

    return await disarm("disarmed by the user")


@router.post("/real-money/kill")
async def real_money_kill(req: KillRequest, _user: dict = Depends(get_current_user)):
    from app.services.mcx_live_executor import set_kill_switch

    return await set_kill_switch(req.active, req.reason or "manual")
