"""Internal domain model — the lingua franca between TradingAI services. Services must
pass these models (or their .model_dump() dicts) between each other, never raw
broker/exchange JSON."""

from tradingai_shared.domain.enums import (
    AssetClass,
    ExchangeSegment,
    ExecutionMode,
    OptionType,
    OrderType,
    ProductType,
    RunStatus,
    SignalAction,
    Timeframe,
    TradeStatus,
    TransactionType,
)
from tradingai_shared.domain.models import (
    BacktestResult,
    Bar,
    Fill,
    Instrument,
    Position,
    RiskDecision,
    Signal,
    Trade,
)

__all__ = [
    "AssetClass",
    "BacktestResult",
    "Bar",
    "ExchangeSegment",
    "ExecutionMode",
    "Fill",
    "Instrument",
    "OptionType",
    "OrderType",
    "Position",
    "ProductType",
    "RiskDecision",
    "RunStatus",
    "Signal",
    "SignalAction",
    "Timeframe",
    "Trade",
    "TradeStatus",
    "TransactionType",
]
