"""Phase 5 support: synthetic bar generation for SIMULATION mode. The `StrategyRunner`
mode-dispatcher itself lives in the backend (`app/services/strategy_runner.py`), not
here — it needs both `backtesting_service.BacktestEngine` and the backend's Dhan
client, and backtesting-service already depends on strategy-service, so putting the
runner here would create a dependency cycle."""

from strategy_service.live.synthetic import generate_synthetic_bars

__all__ = ["generate_synthetic_bars"]
