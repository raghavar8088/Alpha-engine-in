"""Watchlist — user-created named lists of symbols with live price tracking.

  GET    /api/watchlist                     list all watchlists (with symbols)
  POST   /api/watchlist                     create a new watchlist {name}
  DELETE /api/watchlist/{id}                delete a watchlist
  POST   /api/watchlist/{id}/symbols        add a symbol to a watchlist
  DELETE /api/watchlist/{id}/symbols/{sym}  remove a symbol from a watchlist
  GET    /api/watchlist/{id}/quotes         live LTP/change/high/low for every symbol in it
  GET    /api/watchlist/search              instrument autocomplete (reuses Positions' search)
"""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import watchlists_collection
from app.schemas.watchlist import AddSymbolRequest, CreateWatchlistRequest
from app.services.dhan_client import DhanAPIError
from app.services.manual_positions import search_instruments

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _serialize(doc: dict) -> dict:
    doc.pop("_id", None)
    doc.pop("user_id", None)
    if doc.get("created_at") is not None:
        doc["created_at"] = doc["created_at"].isoformat()
    return doc


@router.get("/search")
async def search(q: str = Query(..., min_length=1), current_user: dict = Depends(get_current_user)):
    return {"results": await search_instruments(q)}


@router.get("")
async def list_watchlists(current_user: dict = Depends(get_current_user)):
    cursor = watchlists_collection.find({"user_id": str(current_user["_id"])}).sort("created_at", 1)
    return {"watchlists": [_serialize(d) async for d in cursor]}


@router.post("")
async def create_watchlist(payload: CreateWatchlistRequest, current_user: dict = Depends(get_current_user)):
    doc = {
        "watchlist_id": uuid4().hex[:12],
        "user_id": str(current_user["_id"]),
        "name": payload.name.strip(),
        "symbols": [],
        "created_at": datetime.now(timezone.utc),
    }
    await watchlists_collection.insert_one(doc)
    return _serialize(doc)


@router.delete("/{watchlist_id}")
async def delete_watchlist(watchlist_id: str, current_user: dict = Depends(get_current_user)):
    result = await watchlists_collection.delete_one(
        {"watchlist_id": watchlist_id, "user_id": str(current_user["_id"])}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
    return {"deleted": True}


@router.post("/{watchlist_id}/symbols")
async def add_symbol(watchlist_id: str, payload: AddSymbolRequest, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    wl = await watchlists_collection.find_one({"watchlist_id": watchlist_id, "user_id": user_id})
    if wl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
    if any(s["symbol"] == payload.symbol for s in wl.get("symbols", [])):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{payload.symbol} is already in this watchlist")

    entry = {
        "symbol": payload.symbol,
        "security_id": payload.security_id,
        "exchange_segment": payload.exchange_segment,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    await watchlists_collection.update_one(
        {"watchlist_id": watchlist_id, "user_id": user_id},
        {"$push": {"symbols": entry}},
    )
    return entry


@router.delete("/{watchlist_id}/symbols/{symbol}")
async def remove_symbol(watchlist_id: str, symbol: str, current_user: dict = Depends(get_current_user)):
    result = await watchlists_collection.update_one(
        {"watchlist_id": watchlist_id, "user_id": str(current_user["_id"])},
        {"$pull": {"symbols": {"symbol": symbol}}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
    return {"removed": True}


@router.get("/{watchlist_id}/quotes")
async def watchlist_quotes(watchlist_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])
    wl = await watchlists_collection.find_one({"watchlist_id": watchlist_id, "user_id": user_id})
    if wl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")

    symbols = wl.get("symbols", [])
    if not symbols:
        return {"quotes": []}

    dhan = await _get_dhan_client(user_id)
    by_segment: dict[str, list[int]] = {}
    for s in symbols:
        by_segment.setdefault(s["exchange_segment"], []).append(int(s["security_id"]))

    # Dhan first for the full OHLC/volume snapshot; if Dhan's data endpoint is
    # unavailable, fall back to Angel One for at least the LTP (broker_data.get_ltp owns
    # the failover) so the watchlist still shows a live price.
    from app.services.broker_data import get_ltp

    try:
        resp = await dhan.quote_data(by_segment)
        data = resp.get("data", {})
    except (DhanAPIError, Exception):
        data = {}

    quotes = []
    for s in symbols:
        seg_data = data.get(s["exchange_segment"], {})
        q = seg_data.get(str(s["security_id"]), {})
        ltp = q.get("last_price")
        ohlc = q.get("ohlc") or {}
        prev_close = ohlc.get("close")
        if ltp is None:
            ltp, _src = await get_ltp(dhan, str(s["security_id"]), s["exchange_segment"])
        change = (ltp - prev_close) if (ltp is not None and prev_close) else None
        pct_change = (change / prev_close * 100) if (change is not None and prev_close) else None
        quotes.append({
            "symbol": s["symbol"],
            "security_id": s["security_id"],
            "exchange_segment": s["exchange_segment"],
            "ltp": ltp,
            "change": round(change, 2) if change is not None else None,
            "pct_change": round(pct_change, 2) if pct_change is not None else None,
            "open": ohlc.get("open"),
            "high": ohlc.get("high"),
            "low": ohlc.get("low"),
            "prev_close": prev_close,
            "volume": q.get("volume"),
        })
    return {"quotes": quotes}
