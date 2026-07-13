"""Trading Calls — Kotak-Neo-style research calls across Stocks / F&O / Commodity.

Generation and lifecycle live in app.services.call_engine; this router exposes:
  GET  /api/trading-calls              list (LTP/status auto-refreshed, throttled)
  POST /api/trading-calls/generate     run the call engine now (also opens paper positions)
  POST /api/trading-calls/{id}/close   close a call manually
  GET  /api/trading-calls/positions    the auto-opened paper-position ledger (see call_positions)
"""

import time

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import trading_call_positions_collection, trading_calls_collection
from app.services.call_engine import generate_calls, refresh_calls
from app.services.call_positions import open_positions_for_calls, summary as positions_summary, sync_positions
from app.services.dhan_client import DhanClient

router = APIRouter(prefix="/api/trading-calls", tags=["trading-calls"])

REFRESH_THROTTLE_SECONDS = 45
_last_refresh = 0.0

SEGMENTS = ("STOCK", "FNO", "COMMODITY")


async def _optional_dhan(user_id: str) -> DhanClient | None:
    """The module degrades honestly without a broker: bar-close LTPs, model premiums."""
    try:
        return await _get_dhan_client(user_id)
    except HTTPException:
        return None


def _serialize(doc: dict) -> dict:
    doc.pop("_id", None)
    for key in ("created_at", "updated_at", "closed_at"):
        if doc.get(key) is not None:
            doc[key] = doc[key].isoformat()
    return doc


def _serialize_position(doc: dict) -> dict:
    doc.pop("_id", None)
    for key in ("opened_at", "updated_at", "closed_at"):
        if doc.get(key) is not None:
            doc[key] = doc[key].isoformat()
    return doc


@router.get("")
async def list_calls(
    segment: str | None = Query(None, description="STOCK | FNO | COMMODITY"),
    status: str | None = Query(None),
    refresh: bool = Query(True, description="refresh LTPs/statuses first (throttled)"),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    global _last_refresh
    if refresh and time.monotonic() - _last_refresh > REFRESH_THROTTLE_SECONDS:
        _last_refresh = time.monotonic()
        await refresh_calls(await _optional_dhan(str(current_user["_id"])))

    query: dict = {}
    if segment:
        if segment.upper() not in SEGMENTS:
            raise HTTPException(status_code=422, detail=f"segment must be one of {SEGMENTS}")
        query["segment"] = segment.upper()
    if status:
        query["status"] = status.upper()

    cursor = trading_calls_collection.find(query).sort("created_at", -1).limit(limit)
    calls = [_serialize(d) async for d in cursor]

    counts = {s: 0 for s in SEGMENTS}
    pipeline = [
        {"$match": {"status": {"$in": ["OPEN", "PARTIAL_EXIT"]}}},
        {"$group": {"_id": "$segment", "n": {"$sum": 1}}},
    ]
    async for row in trading_calls_collection.aggregate(pipeline):
        counts[row["_id"]] = row["n"]

    return {"calls": calls, "live_counts": counts}


@router.post("/generate")
async def generate(
    segments: list[str] | None = None,
    current_user: dict = Depends(get_current_user),
):
    if segments:
        segments = [s.upper() for s in segments]
        bad = [s for s in segments if s not in SEGMENTS]
        if bad:
            raise HTTPException(status_code=422, detail=f"unknown segments {bad}; valid: {SEGMENTS}")
    dhan = await _optional_dhan(str(current_user["_id"]))
    result = await generate_calls(dhan, segments)
    result["positions_opened"] = await open_positions_for_calls(result["calls"])
    result["calls"] = [_serialize(c) for c in result["calls"]]
    result["broker_connected"] = dhan is not None
    return result


@router.post("/{call_id}/close")
async def close_call(call_id: str, current_user: dict = Depends(get_current_user)):
    from datetime import datetime, timezone

    doc = await trading_calls_collection.find_one({"call_id": call_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown call")
    if doc["status"] not in ("OPEN", "PARTIAL_EXIT"):
        raise HTTPException(status_code=409, detail=f"Call is already {doc['status']}")
    now = datetime.now(timezone.utc)
    await trading_calls_collection.update_one(
        {"call_id": call_id},
        {"$set": {"status": "CLOSED", "closed_at": now, "updated_at": now}},
    )
    return _serialize(await trading_calls_collection.find_one({"call_id": call_id}))


@router.get("/positions")
async def list_positions(
    status: str | None = Query(None, description="OPEN | TARGET_HIT | STOPLOSS | EXPIRED | CLOSED"),
    segment: str | None = Query(None, description="STOCK | FNO | COMMODITY"),
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    global _last_refresh
    if time.monotonic() - _last_refresh > REFRESH_THROTTLE_SECONDS:
        _last_refresh = time.monotonic()
        await refresh_calls(await _optional_dhan(str(current_user["_id"])))
    await sync_positions()

    query: dict = {}
    if status:
        query["status"] = status.upper()
    if segment:
        if segment.upper() not in SEGMENTS:
            raise HTTPException(status_code=422, detail=f"segment must be one of {SEGMENTS}")
        query["segment"] = segment.upper()

    cursor = trading_call_positions_collection.find(query).sort("opened_at", -1).limit(limit)
    positions = [_serialize_position(d) async for d in cursor]
    return {"positions": positions, "summary": await positions_summary()}
