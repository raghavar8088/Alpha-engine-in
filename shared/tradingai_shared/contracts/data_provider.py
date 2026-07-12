from abc import ABC, abstractmethod
from datetime import datetime

from tradingai_shared.domain.models import Bar, Instrument
from tradingai_shared.domain.enums import Timeframe


class DataProvider(ABC):
    """Contract for historical/streaming market-data sources. Implementations: Dhan
    (market-data-service/providers/dhan_history.py); the Phase-1 NSE indices poller
    predates this contract and is left as-is."""

    @abstractmethod
    def get_history(
        self, instrument: Instrument, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        """Return completed bars for [start, end], oldest first."""

    def subscribe(self, instruments: list[Instrument]) -> None:
        """Start streaming live data for these instruments (optional; historical-only
        providers keep the default no-op)."""
        return None
