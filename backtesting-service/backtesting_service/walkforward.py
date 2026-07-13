"""Walk-forward analysis: expanding-window re-optimization with strictly out-of-sample
testing. The timeline is cut into `n_windows` equal test segments; for each, parameters
are optimized on ALL data before the segment (anchored/expanding train window) and the
best set is evaluated on the segment alone. Concatenated segment metrics are the honest
out-of-sample estimate; plain train/test OOS is the n_windows=1 special case."""

from backtesting_service.engine import BacktestConfig, BacktestEngine
from backtesting_service.metrics import compute_metrics
from backtesting_service.optimizer import DEFAULT_RANK_METRIC, optimize
from tradingai_shared.contracts import STRATEGY_REGISTRY
from tradingai_shared.domain import Bar


def walk_forward(
    config: BacktestConfig,
    bars: list[Bar],
    param_grid: dict[str, list],
    n_windows: int = 4,
    train_fraction: float = 0.5,
    rank_metric: str = DEFAULT_RANK_METRIC,
    benchmark_bars: list[Bar] | None = None,
) -> dict:
    """`train_fraction` reserves the initial stretch as the first training set; the
    remainder is split into `n_windows` test segments. Returns per-window best params +
    OOS metrics, plus aggregate OOS stats."""
    strategy_cls = STRATEGY_REGISTRY[config.strategy_id]
    first_test_start = int(len(bars) * train_fraction)
    test_len = (len(bars) - first_test_start) // n_windows
    if test_len <= strategy_cls(params=config.params).warmup:
        raise ValueError(
            f"test windows of {test_len} bars are too short for warmup — "
            "use fewer windows, a smaller train_fraction, or more history"
        )

    windows = []
    oos_trades = 0
    oos_net = 0.0
    for w in range(n_windows):
        test_start = first_test_start + w * test_len
        test_end = len(bars) if w == n_windows - 1 else test_start + test_len

        ranked = optimize(config, bars[:test_start], param_grid, rank_metric, benchmark_bars=benchmark_bars)
        best_params = ranked[0]["params"]

        merged = {**config.params, **best_params}
        engine = BacktestEngine(
            strategy_cls(params=merged), config.model_copy(update={"params": merged})
        )
        test_metrics = compute_metrics(
            engine.run(bars[test_start:test_end], benchmark_bars=benchmark_bars)
        )

        windows.append(
            {
                "window": w + 1,
                "train_bars": test_start,
                "test_bars": test_end - test_start,
                "test_start": bars[test_start].ts.isoformat(),
                "test_end": bars[test_end - 1].ts.isoformat(),
                "best_params": best_params,
                "train_metric": {rank_metric: ranked[0]["metrics"][rank_metric]},
                "oos_metrics": test_metrics,
            }
        )
        oos_trades += test_metrics["total_trades"]
        oos_net += test_metrics["net_profit"]

    profitable = sum(1 for w in windows if w["oos_metrics"]["net_profit"] > 0)
    return {
        "n_windows": n_windows,
        "rank_metric": rank_metric,
        "windows": windows,
        "oos_net_profit": round(oos_net, 2),
        "oos_total_trades": oos_trades,
        "profitable_windows": profitable,
        "consistency": round(profitable / n_windows, 2),
    }
