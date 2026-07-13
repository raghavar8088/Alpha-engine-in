"""TradingAI strategy library. Importing this package registers every strategy in
`strategy_service.strategies` into tradingai_shared's STRATEGY_REGISTRY — the backend
and backtester just import and read the registry."""

import strategy_service.strategies  # noqa: F401  (import-for-side-effect: registration)
from tradingai_shared.contracts import STRATEGY_REGISTRY

__all__ = ["STRATEGY_REGISTRY"]
