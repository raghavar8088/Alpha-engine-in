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


@router.get("/leaderboard")
async def leaderboard(_user: dict = Depends(get_current_user)):
    per_cap = float(os.getenv("PRELIVE_PER_STRATEGY_CAPITAL", "1000000"))
    rows = []
    async for s in prelive_scores_collection.find({}).sort("net_pnl", -1):
        s.pop("_id", None)
        s["allocated_capital"] = round(per_cap + (s.get("net_pnl") or 0.0), 2)
        rows.append(s)
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
