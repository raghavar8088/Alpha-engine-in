"""Grid-search parameter optimization. The grid is explicit ({"fast": [10, 20], ...})
rather than auto-derived — parameter ranges are a research decision, not a code one.
Used standalone (rank a grid over one period) and by walk-forward (re-optimize per
training window)."""

from itertools import product

from backtesting_service.engine import BacktestConfig, BacktestEngine
from backtesting_service.metrics import compute_metrics
from tradingai_shared.contracts import STRATEGY_REGISTRY
from tradingai_shared.domain import Bar

DEFAULT_RANK_METRIC = "profit_factor"


def grid_combinations(param_grid: dict[str, list]) -> list[dict]:
    if not param_grid:
        return [{}]
    keys = sorted(param_grid)
    return [dict(zip(keys, combo)) for combo in product(*(param_grid[k] for k in keys))]


def optimize(
    config: BacktestConfig,
    bars: list[Bar],
    param_grid: dict[str, list],
    rank_metric: str = DEFAULT_RANK_METRIC,
    benchmark_bars: list[Bar] | None = None,
) -> list[dict]:
    """Run every grid combination over `bars`; return [{params, metrics}] sorted best
    first by `rank_metric` (None-metric runs sink to the bottom)."""
    strategy_cls = STRATEGY_REGISTRY[config.strategy_id]
    results = []
    for combo in grid_combinations(param_grid):
        merged = {**config.params, **combo}
        run_config = config.model_copy(update={"params": merged})
        engine = BacktestEngine(strategy_cls(params=merged), run_config)
        metrics = compute_metrics(engine.run(bars, benchmark_bars=benchmark_bars))
        results.append({"params": combo, "metrics": metrics})
    results.sort(
        key=lambda r: (r["metrics"][rank_metric] is not None, r["metrics"][rank_metric] or 0),
        reverse=True,
    )
    return results
