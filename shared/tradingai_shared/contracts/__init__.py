"""The four plugin contracts. Adding a new strategy/data-provider/broker/AI-model means
one new module implementing one of these — never an edit to existing code."""

from tradingai_shared.contracts.ai_provider import AIProvider
from tradingai_shared.contracts.broker import Broker
from tradingai_shared.contracts.data_provider import DataProvider
from tradingai_shared.contracts.strategy import (
    STRATEGY_REGISTRY,
    Strategy,
    StrategyContext,
    StrategyMetadata,
    register_strategy,
)

__all__ = [
    "AIProvider",
    "Broker",
    "DataProvider",
    "STRATEGY_REGISTRY",
    "Strategy",
    "StrategyContext",
    "StrategyMetadata",
    "register_strategy",
]
