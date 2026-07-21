from datetime import datetime

from pydantic import BaseModel


class ConnectBrokerRequest(BaseModel):
    access_token: str
    client_id: str | None = None  # optional cross-check; the real ID is read from the token itself


class BrokerConnectionResponse(BaseModel):
    broker: str
    client_id: str
    connected_at: datetime
    dhan_name: str | None = None
    # Token health, so the UI (and a human with curl) can tell a working
    # auto-refresh from a silently-stalled one without reading server logs.
    token_expiry: datetime | None = None
    seconds_remaining: int | None = None
    token_healthy: bool = False
    auto_refresh_enabled: bool = False


class PlaceOrderRequest(BaseModel):
    security_id: str
    exchange_segment: str
    transaction_type: str  # BUY / SELL
    quantity: int
    order_type: str  # MARKET / LIMIT
    product_type: str  # CNC / INTRADAY / MARGIN
    price: float = 0
    trigger_price: float = 0
    paper_trading: bool = True


class OrderResponse(BaseModel):
    order_id: str
    status: str
    security_id: str
    exchange_segment: str
    transaction_type: str
    quantity: int
    order_type: str
    product_type: str
    price: float
    paper_trading: bool
    created_at: datetime
