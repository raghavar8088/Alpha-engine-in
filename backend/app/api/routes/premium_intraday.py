"""Premium Strategies -> Premium Intraday Strategies: the backend's ONLY part of that desk (2026-11-22).

The desk itself runs in its own container (premium-intraday-service) with its own scheduler, database
(alpha_engine_premium_intraday on the box's second MongoDB, FACTORY_MONGO_URL), paper books, risk limits, logs and
switch. This file gives it two things and nothing else:

  FEED (read only, for the desk's worker; no broker call, no file I/O, no write anywhere)
    GET /api/premium-intraday/feed/bars?since=<epoch>   today's CLOSED five-minute bars from the bar store's memory
                                                        (the same structure /api/premium-paper/today-bars reads),
                                                        only bars starting at or after `since`
    GET /api/premium-intraday/feed/quotes               the Angel stream's day open / previous close / LTP per stock
    GET /api/premium-intraday/feed/context?day=          stored documents only: the results calendar, the morning
                                                        brief, the stored intraday universe (never built from here)
  DASHBOARD (reads the desk's own database)
    GET  /api/premium-intraday/status | /day | /journal | /positions | /books | /days
    POST /api/premium-intraday/control   {"enabled": bool}: the desk's own switch, written to ITS database

Mounted in main.py inside try/except: if anything here fails to import, the rest of the app starts as before.
Removing the desk = removing this file, its include in main.py, the compose service and the frontend route.
"""
from __future__ import annotations

import json
import logging
import os
import time
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response

from app.api.deps import get_current_user

logger = logging.getLogger("premium_intraday")
router = APIRouter(prefix="/api/premium-intraday", tags=["premium-intraday"])

IST = timezone(timedelta(hours=5, minutes=30))
_URL = os.getenv("FACTORY_MONGO_URL", "").strip()
_DB = os.getenv("PIS_MONGO_DB", "alpha_engine_premium_intraday")
_db = None


def _database():
    global _db
    if _db is None and _URL:
        from motor.motor_asyncio import AsyncIOMotorClient
        _db = AsyncIOMotorClient(_URL, serverSelectionTimeoutMS=5000, maxPoolSize=2)[_DB]
    return _db


def _json(obj) -> Response:
    return Response(content=json.dumps(obj, separators=(",", ":"), default=str), media_type="application/json")


# ── feed (for the desk's worker) ─────────────────────────────────────────────────────────────────────────────

@router.get("/feed/bars")
async def feed_bars(since: int = Query(0, ge=0), _user: dict = Depends(get_current_user)):
    """Runs on the event loop on purpose, like /api/premium-paper/today-bars: the bar store is written there and this
    only slices arrays already in memory (store5._mem; never store5.get(), which would read files)."""
    now = datetime.now(IST)
    open_t = int(now.replace(hour=9, minute=15, second=0, microsecond=0).timestamp())
    close_t = int(time.time()) - 300                 # a five-minute bar is finished five minutes after it starts
    lo_t = max(open_t, int(since))
    bars, stream = {}, None
    try:
        from app.services.intraday_store import store5
        for sym, b in list(store5._mem.items()):
            lo, hi = bisect_left(b.t, lo_t), bisect_right(b.t, close_t)
            if hi > lo:
                bars[sym] = [[b.t[i], b.o[i], b.h[i], b.l[i], b.c[i], b.v[i]] for i in range(lo, hi)]
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": f"bar store unavailable: {type(exc).__name__}", "now": time.time()})
    try:
        from app.services.angel_stream import stream as _s
        stream = _s.describe()
    except Exception:  # noqa: BLE001
        stream = None
    return _json({"ok": True, "now": time.time(), "since": lo_t, "bars": bars, "stream": stream})


@router.get("/feed/quotes")
async def feed_quotes(_user: dict = Depends(get_current_user)):
    out = {}
    try:
        from app.services.angel_stream import stream as _s
        for sym, st in list(_s.states.items()):
            d = _s.day_stats(sym)
            if d:
                d["last_tick"] = getattr(st, "last_tick", None)
                out[sym] = d
        desc = _s.describe()
    except Exception as exc:  # noqa: BLE001
        return _json({"ok": False, "error": f"stream unavailable: {type(exc).__name__}", "now": time.time()})
    return _json({"ok": True, "now": time.time(), "quotes": out, "stream": desc})


@router.get("/feed/context")
async def feed_context(day: str = Query(""), _user: dict = Depends(get_current_user)):
    """Stored documents only. Nothing here builds, refreshes or fetches: a missing document is reported missing."""
    d = date.fromisoformat(day) if day else datetime.now(IST).date()
    out: dict = {"day": d.isoformat(), "now": time.time()}
    try:
        from app.services import results_calendar
        out["results"] = await results_calendar.reacting_on(d)
    except Exception as exc:  # noqa: BLE001
        out["results"] = None
        out["results_error"] = type(exc).__name__
    try:
        from app.services.global_cues import brief_coll
        doc = await brief_coll.find_one({"_id": d.isoformat()})
        if doc:
            doc.pop("_id", None)
        out["brief"] = doc
    except Exception as exc:  # noqa: BLE001
        out["brief"] = None
        out["brief_error"] = type(exc).__name__
    try:
        from app.services import intraday_universe
        u = await intraday_universe.on(d.isoformat())
        out["universe"] = ({"members": [m.get("symbol") for m in (u or {}).get("members", [])], "asof": d.isoformat()}
                           if u else None)
    except Exception as exc:  # noqa: BLE001
        out["universe"] = None
        out["universe_error"] = type(exc).__name__
    return _json(out)


# ── dashboard (the desk's own database) ──────────────────────────────────────────────────────────────────────

def _need():
    db = _database()
    if db is None:
        raise HTTPException(status_code=503, detail="The desk's database is not configured (FACTORY_MONGO_URL)")
    return db


@router.get("/status")
async def status(_user: dict = Depends(get_current_user)):
    db = _database()
    if db is None:
        return {"configured": False}
    ctl = await db.control.find_one({"_id": "control"}) or {"enabled": True}
    hb = await db.status.find_one({"_id": "worker"}) or {}
    books = await db.books.find({}, {"summary": 1, "status": 1, "updated": 1}).to_list(200)
    alerts = await db.alerts.find({"resolved": {"$ne": True}}).sort("t", -1).to_list(50)
    ctl.pop("_id", None)
    hb.pop("_id", None)
    for x in books + alerts:
        x["id"] = x.pop("_id")
    return {"configured": True, "control": ctl, "worker": hb, "books": books, "alerts": alerts, "now": time.time()}


@router.get("/days")
async def days(limit: int = Query(30, ge=1, le=250), _user: dict = Depends(get_current_user)):
    db = _need()
    rows = await db.days.find({}, {"_id": 1, "status": 1, "summary": 1}).sort("_id", -1).limit(limit).to_list(limit)
    return {"days": rows}


@router.get("/day")
async def day(d: str = Query(""), _user: dict = Depends(get_current_user)):
    db = _need()
    q = {"_id": d} if d else {}
    doc = await db.days.find_one(q, sort=[("_id", -1)])
    if not doc:
        return {"day": None}
    doc["day"] = doc.pop("_id")
    return doc


@router.get("/journal")
async def journal(d: str = Query(""), kind: str = Query(""), symbol: str = Query(""), book: str = Query(""),
                  limit: int = Query(300, ge=1, le=2000), _user: dict = Depends(get_current_user)):
    db = _need()
    q: dict = {}
    if d:
        q["day"] = d
    if kind:
        q["kind"] = {"$in": kind.split(",")}
    if symbol:
        q["symbol"] = symbol.upper()
    if book:
        q["book"] = book
    rows = await db.journal.find(q).sort([("day", -1), ("k", -1), ("seq", -1)]).limit(limit).to_list(limit)
    for r in rows:
        r["id"] = r.pop("_id")
    return {"rows": rows}


@router.get("/positions")
async def positions(status: str = Query("OPEN"), book: str = Query(""), limit: int = Query(500, ge=1, le=5000),
                    _user: dict = Depends(get_current_user)):
    db = _need()
    q: dict = {"status": status.upper()} if status else {}
    if book:
        q["book"] = book
    rows = await db.positions.find(q, {"knew": 0} if status.upper() != "OPEN" else None).sort("t_entry", -1) \
        .limit(limit).to_list(limit)
    for r in rows:
        r["id"] = r.pop("_id")
    return {"rows": rows}


@router.get("/position/{pid:path}")
async def position(pid: str, _user: dict = Depends(get_current_user)):
    db = _need()
    doc = await db.positions.find_one({"_id": pid})
    if not doc:
        raise HTTPException(status_code=404, detail="No such paper position")
    doc["id"] = doc.pop("_id")
    return doc


@router.get("/books")
async def books(_user: dict = Depends(get_current_user)):
    db = _need()
    rows = await db.books.find({}).to_list(200)
    for r in rows:
        r["id"] = r.pop("_id")
    return {"books": rows}


@router.post("/control")
async def control(payload: dict = Body(...), _user: dict = Depends(get_current_user)):
    """The desk's own ON/OFF. OFF stops new scans and new entries; open paper positions keep being managed to their
    exits. Writes one document in the desk's own database; nothing else in the app reads it."""
    if "enabled" not in payload or not isinstance(payload["enabled"], bool):
        raise HTTPException(status_code=422, detail='Send {"enabled": true} or {"enabled": false}')
    db = _need()
    doc = {"enabled": payload["enabled"], "updated_at": datetime.now(timezone.utc), "reason": str(payload.get("reason") or "")[:200]}
    await db.control.update_one({"_id": "control"}, {"$set": doc, "$inc": {"revision": 1}}, upsert=True)
    await db.control_log.insert_one({**doc, "t": doc["updated_at"]})
    return {"ok": True, "control": doc}
