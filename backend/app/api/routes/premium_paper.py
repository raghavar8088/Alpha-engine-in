"""Premium Strategies paper desk API. Read only.

  GET /api/premium-paper/summary                 every Rs 10 lakh account, and how fresh each feed is
  GET /api/premium-paper/accounts/{id}           one account: equity curve, open positions, P&L by market
  GET /api/premium-paper/accounts/{id}/trades    its trades, newest first (?limit=&offset=)
  GET /api/premium-paper/today-bars              today's finished bars from this process's memory, for the desk's cycle

  GET  /api/premium-paper/live                   the Delta real-money desk on ten of these strategies (premium_live)
  POST /api/premium-paper/live/mode              {"mode": "off" | "shadow" | "live", "pin", "confirm"}
  POST /api/premium-paper/live/flatten           {"pin"}: close its open positions now and switch it off

The desk itself runs in its own container (premium-paper-service), because this process sits at its memory cap; its
records are in the box's second MongoDB (FACTORY_MONGO_URL), never on the near-quota Atlas cluster. Everything above
the live routes is paper. The live routes are the one part that reaches a broker: premium_live sends real orders to Delta
Exchange India for ten strategies, at the owner's size. Going live and flattening need the owner's PIN; switching off
never does.
"""

import json
import logging
import os
import time
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response

from app.api.deps import get_current_user

logger = logging.getLogger("premium_paper")
router = APIRouter(prefix="/api/premium-paper", tags=["premium-paper"])

IST = timezone(timedelta(hours=5, minutes=30))
_URL = os.getenv("FACTORY_MONGO_URL", "").strip()
_DB = os.getenv("PREMIUM_MONGO_DB", "alpha_engine_premium")
_db = None


def _database():
    global _db
    if _db is None and _URL:
        from motor.motor_asyncio import AsyncIOMotorClient
        _db = AsyncIOMotorClient(_URL, serverSelectionTimeoutMS=5000, maxPoolSize=4)[_DB]
    return _db


@router.get("/summary")
async def summary(_user: dict = Depends(get_current_user)):
    db = _database()
    if db is None:
        return {"accounts": [], "status": {}, "configured": False}
    # every account (277 on 10 Nov 2026 with the 20-channel books; a cap of 200 hid the newest ones)
    rows = await db.premium_accounts.find({}, {"positions": 0, "curve": 0}).to_list(1000)
    for r in rows:
        r["id"] = r.pop("_id")
    status = await db.premium_meta.find_one({"_id": "status"}) or {}
    status.pop("_id", None)
    return {"accounts": rows, "status": status, "configured": True}


@router.get("/accounts/{account_id}")
async def account(account_id: str, _user: dict = Depends(get_current_user)):
    db = _database()
    doc = await db.premium_accounts.find_one({"_id": account_id}) if db is not None else None
    if doc is None:
        raise HTTPException(status_code=404, detail="No such paper account")
    doc["id"] = doc.pop("_id")
    return doc


@router.get("/accounts/{account_id}/trades")
async def trades(account_id: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                 _user: dict = Depends(get_current_user)):
    db = _database()
    if db is None:
        return {"trades": [], "total": 0}
    q = {"acct": account_id}
    fields = {"sym": 1, "mkt": 1, "side": 1, "setup": 1, "date": 1, "entry_t": 1, "exit_t": 1, "entry": 1, "exit": 1, "stop": 1, "target": 1,
              "reason": 1, "open": 1, "last": 1, "qty": 1, "pnl": 1, "skip": 1, "sealed": 1, "r_net": 1}
    rows = await db.premium_trades.find(q, fields).sort("entry_t", -1).skip(offset).limit(limit).to_list(limit)
    for r in rows:
        r["id"] = r.pop("_id")
    return {"trades": rows, "total": await db.premium_trades.count_documents(q)}


def _rows(b, lo: int, hi: int) -> list:
    return [[b.t[i], b.o[i], b.h[i], b.l[i], b.c[i], b.v[i]] for i in range(lo, hi)]


@router.get("/today-bars")
async def today_bars(group: str = Query("index"), _user: dict = Depends(get_current_user)):
    """Runs on the event loop on purpose: these structures are written there, and building the answer takes milliseconds.
    Answers a plain Response: FastAPI's encoder walks every number, which is seconds for a whole universe."""
    now = datetime.now(IST)
    out: dict = {}
    if group == "index":
        from app.services.index_intraday.feed import feed
        for sym in ("NIFTY", "BANKNIFTY"):
            out[sym] = [[t, *bar] for t, bar in sorted(feed.today(sym, now).items())]
    elif group == "stocks":
        from app.services.intraday_store import store5
        open_t = int(now.replace(hour=9, minute=15, second=0, microsecond=0).timestamp())
        close_t = int(time.time()) - 300        # a bar is finished five minutes after it starts
        stocks = {}
        for sym, b in list(store5._mem.items()):
            lo, hi = bisect_left(b.t, open_t), bisect_right(b.t, close_t)
            if hi > lo:
                stocks[sym] = _rows(b, lo, hi)
        out["stocks"] = stocks
    else:
        raise HTTPException(status_code=422, detail="group is index or stocks")
    return Response(content=json.dumps(out, separators=(",", ":")), media_type="application/json")


# -- the Delta real-money desk (premium_live, 2026-11-13) ---------------------------------------------------
# Imported inside each route and the startup hook, so a fault there can only break these routes, never the paper
# desk's or the app's start.

_live_tasks: set = set()


@router.on_event("startup")
async def _start_premium_live() -> None:
    # FastAPI 0.115 runs an included router's startup handler twice (the app's list and the router's own lifespan,
    # both). The loop must start once.
    if _live_tasks:
        return
    try:
        import asyncio
        from app.services import premium_live
        _live_tasks.add(asyncio.create_task(premium_live.loop()))
    except Exception:  # noqa: BLE001
        logger.exception("premium live desk not started")


@router.get("/live")
async def live_status(_user: dict = Depends(get_current_user)):
    from app.services import premium_live
    return await premium_live.status()


@router.post("/live/mode")
async def live_mode(payload: dict = Body(...), _user: dict = Depends(get_current_user)):
    from app.services import premium_live
    r = await premium_live.set_mode(str(payload.get("mode") or ""), payload.get("pin"), payload.get("confirm"))
    return {**r, "status": await premium_live.status()}


@router.post("/live/flatten")
async def live_flatten(payload: dict = Body(...), _user: dict = Depends(get_current_user)):
    from app.services import premium_live
    r = await premium_live.flatten(payload.get("pin"))
    return {**r, "status": await premium_live.status()}
