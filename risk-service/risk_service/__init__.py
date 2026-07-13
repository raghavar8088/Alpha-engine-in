"""TradingAI risk engine (roadmap Phase 4): position sizing + exposure/drawdown limits
+ kill-switch. `backtesting-service` and the future live engine both call
`RiskEngine.evaluate()` before turning a Signal into an order."""

from risk_service.engine import PositionSnapshot, RiskEngine, RiskLimits, SizingConfig, SizingMethod

__all__ = ["PositionSnapshot", "RiskEngine", "RiskLimits", "SizingConfig", "SizingMethod"]
