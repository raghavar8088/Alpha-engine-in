from abc import ABC, abstractmethod
from typing import AsyncIterator

from tradingai_shared.domain.enums import OrderType, ProductType, TransactionType
from tradingai_shared.domain.models import Fill, Instrument


class Broker(ABC):
    """Contract for order execution + account state. Dhan is the first implementation
    (wrapping backend/app/services/dhan_client.py); the paper-trading simulator is the
    second. Async to match the FastAPI backend where execution lives."""

    @abstractmethod
    async def place(
        self,
        instrument: Instrument,
        transaction_type: TransactionType,
        quantity: int,
        order_type: OrderType,
        product_type: ProductType,
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> str:
        """Place an order; return the broker order id."""

    @abstractmethod
    async def cancel(self, order_id: str) -> None: ...

    @abstractmethod
    async def positions(self) -> list[dict]: ...

    @abstractmethod
    async def funds(self) -> dict: ...

    @abstractmethod
    def order_stream(self) -> AsyncIterator[Fill]:
        """Yield fills/status changes as they happen (Dhan impl relays the
        broker-service Redis channel)."""
