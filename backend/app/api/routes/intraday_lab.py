"""Intraday Strategy Lab — sub-module of Trading Calls. 50 intraday equity
scalping/momentum/mean-reversion/swing strategies, each auto-trading paper
positions off its own slice of a shared ₹1cr capital pool.

  GET  /api/intraday-lab/strategies   catalog + live leaderboard stats
  GET  /api/intraday-lab/positions    open/closed paper positions
  GET  /api/intraday-lab/leaderboard  per-strategy ranked scoreboard
  GET  /api/intraday-lab/summary      pool-level capital tiles
  POST /api/intraday-lab/run          manually trigger one scan+manage cycle
"""

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from pydantic import BaseModel, Field

from app.core.db import (
    intraday_lab_backtests_collection,
    intraday_lab_equity_collection,
    intraday_lab_positions_collection,
    intraday_lab_scores_collection,
    intraday_lab_state_collection,
    intraday_lab_trades_collection,
)
from app.services.intraday_backtest import run_intraday_backtest
from app.services.call_engine import IST
from app.services.dhan_client import DhanClient
from app.services.intraday_lab_engine import STATE_ID, run_cycle, summary as lab_summary
from app.services.intraday_strategies import STRATEGY_CATALOG

router = APIRouter(prefix="/api/intraday-lab", tags=["intraday-lab"])


async def _optional_dhan(user_id: str) -> DhanClient | None:
    try:
        return await _get_dhan_client(user_id)
    except HTTPException:
        return None


def _serialize_position(doc: dict) -> dict:
    doc.pop("_id", None)
    for key in ("opened_at", "updated_at", "closed_at"):
        if doc.get(key) is not None:
            doc[key] = doc[key].isoformat()
    return doc


@router.get("/strategies")
async def list_strategies(current_user: dict = Depends(get_current_user)):
    scores = {s["strategy_id"]: s async for s in intraday_lab_scores_collection.find({})}
    out = []
    for spec in STRATEGY_CATALOG:
        score = scores.get(spec.strategy_id) or {}
        out.append({
            "strategy_id": spec.strategy_id, "name": spec.name, "category": spec.category,
            "timeframe": spec.timeframe, "rationale": spec.rationale,
            "max_hold_days": spec.max_hold_days, "risk_pct": spec.risk_pct,
            "trades": score.get("trades", 0), "win_rate": score.get("win_rate", 0.0),
            "net_pnl": score.get("net_pnl", 0.0), "allocated_capital": score.get("allocated_capital"),
        })
    return {"strategies": out, "count": len(out)}


@router.get("/positions")
async def list_positions(
    strategy_id: str | None = Query(None),
    status: str | None = Query(None, description="OPEN | CLOSED"),
    limit: int = Query(300, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    query: dict = {}
    if strategy_id:
        query["strategy_id"] = strategy_id
    if status:
        query["status"] = status.upper()
    cursor = intraday_lab_positions_collection.find(query).sort("opened_at", -1).limit(limit)
    positions = [_serialize_position(d) async for d in cursor]
    return {"positions": positions}


@router.get("/leaderboard")
async def leaderboard(current_user: dict = Depends(get_current_user)):
    scores = {s["strategy_id"]: s async for s in intraday_lab_scores_collection.find({})}
    rows = []
    for spec in STRATEGY_CATALOG:
        score = scores.get(spec.strategy_id) or {}
        rows.append({
            "strategy_id": spec.strategy_id, "name": spec.name, "category": spec.category,
            "trades": score.get("trades", 0), "win_rate": score.get("win_rate", 0.0),
            "net_pnl": score.get("net_pnl", 0.0),
            "allocated_capital": score.get("allocated_capital", None),
        })
    rows.sort(key=lambda r: r["net_pnl"], reverse=True)
    return {"leaderboard": rows}


@router.get("/summary")
async def summary_endpoint(current_user: dict = Depends(get_current_user)):
    return await lab_summary()


@router.post("/run")
async def run_now(current_user: dict = Depends(get_current_user)):
    dhan = await _optional_dhan(str(current_user["_id"]))
    result = await run_cycle(dhan)
    result["broker_connected"] = dhan is not None
    return result


class BacktestRequest(BaseModel):
    years: float = Field(default=3.0, gt=0, le=15)
    max_symbols: int = Field(default=50, ge=1, le=300)
    min_trades: int = Field(default=30, ge=1)
    min_profit_factor: float = Field(default=1.2, gt=0)
    min_expectancy: float = Field(default=0.0)
    max_drawdown_pct: float = Field(default=25.0, gt=0)
    slippage_bps: float = Field(default=5.0, ge=0, le=100)


@router.post("/backtest")
async def backtest(
    request: BacktestRequest = BacktestRequest(),
    current_user: dict = Depends(get_current_user),
):
    """Replay the catalog on daily bars, fee-honest, and gate each strategy.

    Only the 16 strategies that read bars alone can be measured this way; the 34 that
    need intraday day-state are returned as `backtestable: false` with the reason, never
    as zero-trade rows that would read like failures on a leaderboard."""
    return await run_intraday_backtest(
        years=request.years,
        max_symbols=request.max_symbols,
        gate={
            "min_trades": request.min_trades,
            "min_profit_factor": request.min_profit_factor,
            "min_expectancy": request.min_expectancy,
            "max_drawdown_pct": request.max_drawdown_pct,
        },
        slippage_bps=request.slippage_bps,
    )


@router.get("/backtest")
async def latest_backtest(current_user: dict = Depends(get_current_user)):
    """The most recent backtest, or null if none has been run."""
    doc = await intraday_lab_backtests_collection.find_one({}, sort=[("created_at", -1)])
    if doc is None:
        return None
    doc.pop("_id", None)
    if hasattr(doc.get("created_at"), "isoformat"):
        doc["created_at"] = doc["created_at"].isoformat()
    return doc


@router.get("/status")
async def status(current_user: dict = Depends(get_current_user)):
    """Pool summary + engine heartbeat + open positions, in one call for the page.

    `feed_source` reports which broker the last cycle actually used: Angel One is the
    desk's primary equity feed, Dhan is the per-tick fallback, and "none" means neither
    was reachable (e.g. an off-whitelist host with no Dhan token — the desk then trades
    only daily-bar swing signals and marks on last-bar-close, honestly labelled)."""
    summ = await lab_summary()
    state = await intraday_lab_state_collection.find_one({"_id": STATE_ID}) or {}
    positions = [
        _serialize_position(d)
        async for d in intraday_lab_positions_collection.find({"status": "OPEN"}).sort("opened_at", -1)
    ]
    heartbeat = state.get("last_run_at")
    angel_on = bool(state.get("angel_configured"))
    dhan_on = bool(state.get("broker_connected"))
    return {
        **summ,
        "heartbeat": heartbeat.isoformat() if heartbeat is not None and hasattr(heartbeat, "isoformat") else heartbeat,
        "last_opened": state.get("last_opened"),
        "last_managed": state.get("last_managed"),
        "last_notes": state.get("last_notes", []),
        "broker_connected": dhan_on,
        "angel_configured": angel_on,
        "feed_source": "angel" if angel_on else ("dhan" if dhan_on else "none"),
        "paused": bool(state.get("paused")),
        "open_positions_detail": positions,
    }


@router.get("/trades")
async def trades(
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Closed paper trades, newest first."""
    out = []
    async for d in intraday_lab_trades_collection.find({}).sort("closed_at", -1).limit(limit):
        d.pop("_id", None)
        for key in ("opened_at", "closed_at"):
            if d.get(key) is not None and hasattr(d[key], "isoformat"):
                d[key] = d[key].isoformat()
        out.append(d)
    return out


@router.get("/equity")
async def equity(
    limit: int = Query(500, ge=1, le=5000),
    current_user: dict = Depends(get_current_user),
):
    """Equity-curve snapshots (one per cycle), oldest→newest for charting."""
    out = []
    async for d in intraday_lab_equity_collection.find({}).sort("ts", -1).limit(limit):
        d.pop("_id", None)
        if d.get("ts") is not None and hasattr(d["ts"], "isoformat"):
            d["ts"] = d["ts"].isoformat()
        out.append(d)
    out.reverse()
    return out


@router.get("/daily")
async def daily(
    limit: int = Query(60, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
):
    """Per-session net P&L, aggregated from closed trades by their IST close-date.

    Derived rather than stored: the desk has no fixed session boundary (swing positions
    close on whatever day their target/stop/max-hold hits), so the honest daily record is
    a rollup of when trades actually closed, in IST."""
    buckets: dict[str, dict] = {}
    async for t in intraday_lab_trades_collection.find({}, {"realized_pnl": 1, "closed_at": 1}):
        closed = t.get("closed_at")
        if closed is None:
            continue
        if hasattr(closed, "astimezone"):
            if closed.tzinfo is None:
                closed = closed.replace(tzinfo=timezone.utc)  # Mongo returns naive UTC
            session = closed.astimezone(IST).date().isoformat()
        else:
            session = str(closed)[:10]
        b = buckets.setdefault(session, {"session": session, "net_pnl": 0.0, "trades": 0, "wins": 0})
        pnl = t.get("realized_pnl") or 0.0
        b["net_pnl"] += pnl
        b["trades"] += 1
        if pnl > 0:
            b["wins"] += 1
    rows = sorted(buckets.values(), key=lambda r: r["session"], reverse=True)[:limit]
    for r in rows:
        r["net_pnl"] = round(r["net_pnl"], 2)
        r["win_rate"] = round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0
    return rows
