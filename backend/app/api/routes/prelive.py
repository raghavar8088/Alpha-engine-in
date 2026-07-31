"""Pre-Live paper desk API — status, live positions, trade blotter, per-strategy
leaderboard, equity curve, and the daily P&L history. Read-only: the prelive-service
daemon owns all writes; the backend just surfaces what it has recorded."""

import os

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.db import (
    prelive_daily_pnl_collection,
    prelive_equity_collection,
    prelive_positions_collection,
    prelive_scores_collection,
    prelive_state_collection,
    prelive_trades_collection,
)

router = APIRouter(prefix="/api/prelive", tags=["prelive"])


@router.get("/status")
async def status(_user: dict = Depends(get_current_user)):
    state = await prelive_state_collection.find_one({"_id": "engine"})
    if state:
        state.pop("_id", None)
    open_positions = []
    async for p in prelive_positions_collection.find({}):
        p.pop("_id", None)
        open_positions.append(p)
    today_doc = None
    if state and state.get("session"):
        today_doc = await prelive_daily_pnl_collection.find_one({"session": state["session"]})
        if today_doc:
            today_doc.pop("_id", None)
    return {"engine": state or {"status": "offline"}, "open_positions": open_positions,
            "today": today_doc}


def _anti_row(s: dict, per_cap: float) -> dict:
    """The exact inverse of a strategy's running record — the ANTI-<name> that takes
    the reverse trade (SL/TP swapped). Net P&L negated, wins<->losses swapped, win rate
    and profit factor inverted; computed at read time so the trading engine is untouched."""
    trades = s.get("trades", 0) or 0
    wins = s.get("wins", 0) or 0
    net_pnl = s.get("net_pnl", 0.0) or 0.0
    gross_win = s.get("gross_win", 0.0) or 0.0
    gross_loss = s.get("gross_loss", 0.0) or 0.0
    anti_wins = trades - wins
    return {
        "key": f"anti_{s.get('key', '')}",
        "strategy_id": f"ANTI-{s.get('strategy_id', '')}",
        "name": f"ANTI-{s.get('name', s.get('strategy_id', ''))}",
        "timeframe": s.get("timeframe"),
        "trades": trades, "wins": anti_wins, "losses": wins,
        "gross_win": round(gross_loss, 2), "gross_loss": round(gross_win, 2),
        "net_pnl": round(-net_pnl, 2),
        "win_rate": round(anti_wins / trades, 4) if trades else 0.0,
        "profit_factor": round(gross_loss / gross_win, 3) if gross_win > 0 else None,
        "expectancy": round(-(s.get("expectancy") or 0.0), 2),
        "allocated_capital": round(per_cap - net_pnl, 2),
        "is_anti": True,
    }


@router.get("/leaderboard")
async def leaderboard(_user: dict = Depends(get_current_user)):
    per_cap = float(os.getenv("PRELIVE_PER_STRATEGY_CAPITAL", "1000000"))
    rows = []
    async for s in prelive_scores_collection.find({}).sort("net_pnl", -1):
        s.pop("_id", None)
        s["allocated_capital"] = round(per_cap + (s.get("net_pnl") or 0.0), 2)
        rows.append(s)
        rows.append(_anti_row(s, per_cap))
    rows.sort(key=lambda r: r.get("net_pnl") or 0.0, reverse=True)
    return {"count": len(rows), "strategies": rows}


@router.get("/trades")
async def trades(limit: int = Query(100, ge=1, le=500), session: str | None = None,
                 _user: dict = Depends(get_current_user)):
    q = {"session": session} if session else {}
    rows = []
    async for t in prelive_trades_collection.find(q).sort("exit_ts", -1).limit(limit):
        t["id"] = str(t.pop("_id"))
        for k in ("entry_ts", "exit_ts"):
            if hasattr(t.get(k), "isoformat"):
                t[k] = t[k].isoformat()
        rows.append(t)
    return {"count": len(rows), "trades": rows}


@router.get("/equity")
async def equity(session: str | None = None, _user: dict = Depends(get_current_user)):
    if not session:
        latest = await prelive_equity_collection.find_one({}, sort=[("ts", -1)])
        session = latest["session"] if latest else None
    pts = []
    if session:
        async for e in prelive_equity_collection.find({"session": session}).sort("ts", 1):
            e.pop("_id", None)
            pts.append(e)
    return {"session": session, "points": pts}


@router.get("/daily")
async def daily(limit: int = Query(60, ge=1, le=400), _user: dict = Depends(get_current_user)):
    rows = []
    async for d in prelive_daily_pnl_collection.find({}).sort("session", -1).limit(limit):
        d.pop("_id", None)
        rows.append(d)
    rows.reverse()
    cum = 0.0
    for r in rows:
        cum = round(cum + (r.get("net_pnl") or 0), 2)
        r["cumulative_pnl"] = cum
    return {"count": len(rows), "days": rows}
