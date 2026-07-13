from datetime import datetime

from pydantic import BaseModel


class MarketDataSnapshotResponse(BaseModel):
    symbol: str
    price: float
    change: float | None = None
    pct_change: float | None = None
    volume: int | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class MarketDataHistoryPoint(BaseModel):
    price: float
    recorded_at: datetime
