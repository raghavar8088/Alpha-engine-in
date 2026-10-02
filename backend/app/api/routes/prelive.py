"""Pre-Live paper desk API — status, live positions, trade blotter, per-strategy records,
equity curve, and the daily P&L history. Read-only: the prelive-service daemon owns all
writes; the backend just surfaces what it has recorded.

Since the 2026-10-02 audit the per-strategy endpoint is a set of RECORDS, not a ranking:
nothing in the library predicts NIFTY's direction, so ordering 148 strategies by net P&L
ranks luck. The ANTI-<name> rows it used to add (sign flips of the worst records, never
traded, shown at the top as the "best") are gone. See app.services.prelive_stats."""

import os

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services import prelive_stats
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
    """Per-strategy research records (kept at this path for the existing page). Sorted by
    strategy id — deliberately not by P&L."""
    per_cap = float(os.getenv("PRELIVE_PER_STRATEGY_CAPITAL", "1000000"))
    rec = await prelive_stats.strategy_records()
    seeded = {s["key"]: s async for s in prelive_scores_collection.find({}, {"_id": 0})}
    rows = []
    for r in rec["rows"]:
        rows.append({**r, "name": (seeded.get(r["key"]) or {}).get("name"),
                     "allocated_capital": round(per_cap + r["net_pnl"], 2)})
    traded = {r["key"] for r in rows}
    for k, sc in sorted(seeded.items()):
        if k not in traded:
            rows.append({"key": k, "strategy_id": sc.get("strategy_id"), "timeframe": sc.get("timeframe"),
                         "name": sc.get("name"), "trades": 0, "net_pnl": 0.0, "allocated_capital": per_cap})
    return {"count": len(rows), "strategies": rows, "ranking": False, "luck": rec["luck"], "desk": rec["desk"],
            "real_money_basis": rec["real_money_basis"], "computed_at": rec["computed_at"],
            "note": "Records, not a ranking: no strategy here has shown it can predict NIFTY's direction."}


@router.get("/hypotheses")
async def hypotheses(_user: dict = Depends(get_current_user)):
    """The pre-registered option hypotheses (H1, H1b, H2) and H3's rejection on history."""
    from app.services import option_hypotheses
    return {"hypotheses": await option_hypotheses.listing()}


@router.get("/vol-desk")
async def vol_desk(_user: dict = Depends(get_current_user)):
    """H1/H1b paper incubation: today's signal decision, open straddles, closed trades."""
    from app.services import vol_desk as vd
    return await vd.summary()


@router.get("/lab")
async def lab(_user: dict = Depends(get_current_user)):
    """The latest Buying Lab v2 run (U3): every strategy's direction test, deflated Sharpe and
    gate verdict. Written by the job `python -m app.services.buying_lab_job`."""
    doc = await prelive_scores_collection.database["option_lab_runs"].find_one({}, sort=[("created_at", -1)])
    if not doc:
        return {"run": None}
    doc.pop("_id", None)
    return {"run": doc}


@router.get("/real-money")
async def real_money(_user: dict = Depends(get_current_user)):
    """U6 readiness: the executor's state and, per hypothesis, why it can or cannot be armed."""
    from app.services import live_options_executor as lx
    return await lx.readiness()


@router.post("/real-money/arm")
async def real_money_arm(body: dict, user: dict = Depends(get_current_user)):
    from app.services import live_options_executor as lx
    return await lx.arm(str(body.get("hypothesis", "")), str(body.get("confirm", "")), str(user.get("email") or user.get("id")))


@router.post("/real-money/disarm")
async def real_money_disarm(_user: dict = Depends(get_current_user)):
    from app.services import live_options_executor as lx
    return await lx.disarm("manual")


@router.post("/real-money/kill")
async def real_money_kill(body: dict, _user: dict = Depends(get_current_user)):
    from app.services import live_options_executor as lx
    if body.get("panic"):
        return await lx.panic_close_all("manual panic")
    return await lx.set_kill_switch(bool(body.get("active", True)), "manual")


@router.get("/chain-recorder")
async def chain_recorder(_user: dict = Depends(get_current_user)):
    """The option-chain recorder's health and what it has kept so far."""
    from app.services import index_derivatives, option_chain_recorder as rec
    return {"status": rec.status, "coverage": rec.coverage(), "instrument_master": index_derivatives.status}


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
    """Computed from the trades (the daily documents had missed six sessions). The
    cumulative columns run over the WHOLE history, then the last `limit` days are returned."""
    rows = await prelive_stats.daily_from_trades()
    cum = cum_real = 0.0
    for r in rows:
        cum = round(cum + (r.get("net_pnl") or 0), 2)
        cum_real = round(cum_real + (r.get("real_net") or 0), 2)
        r["cumulative_pnl"], r["cumulative_real"] = cum, cum_real
    return {"count": len(rows[-limit:]), "days": rows[-limit:], "sessions_total": len(rows),
            "total_net": cum, "total_real_net": cum_real}
