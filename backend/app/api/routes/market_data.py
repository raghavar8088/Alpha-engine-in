from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.db import market_data_history_collection, market_data_snapshot_collection
from app.schemas.market_data import MarketDataHistoryPoint, MarketDataSnapshotResponse

router = APIRouter(prefix="/api/market-data", tags=["market-data"])


@router.get("/latest", response_model=list[MarketDataSnapshotResponse])
async def latest(_current_user: dict = Depends(get_current_user)):
    cursor = market_data_snapshot_collection.find().sort("symbol", 1)
    return [doc async for doc in cursor]


@router.get("/{symbol}/history", response_model=list[MarketDataHistoryPoint])
async def history(symbol: str, limit: int = Query(50, ge=1, le=500), _current_user: dict = Depends(get_current_user)):
    cursor = (
        market_data_history_collection.find({"symbol": symbol.upper()})
        .sort("recorded_at", -1)
        .limit(limit)
    )
    points = [doc async for doc in cursor]
    points.reverse()
    return points


@router.get("/{symbol}", response_model=MarketDataSnapshotResponse | None)
async def by_symbol(symbol: str, _current_user: dict = Depends(get_current_user)):
    return await market_data_snapshot_collection.find_one({"symbol": symbol.upper()})
