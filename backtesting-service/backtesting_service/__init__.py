"""TradingAI backtesting engine (roadmap Phase 2).

Event-driven simulation over the Mongo `bars` stream and the shared Strategy contract:
signals fill at next bar's open with slippage, stops/targets trigger intra-bar
(worst-case ordering), every fill pays the full Indian cost stack. Results carry the
complete metric set plus render-ready chart series, and feed walk-forward, parameter
optimization, and Monte Carlo analyses."""

import strategy_service  # noqa: F401  (import-for-side-effect: fills STRATEGY_REGISTRY)

from backtesting_service.costs import CostModel
from backtesting_service.engine import BacktestConfig, BacktestEngine, BacktestRun

__all__ = ["BacktestConfig", "BacktestEngine", "BacktestRun", "CostModel"]
