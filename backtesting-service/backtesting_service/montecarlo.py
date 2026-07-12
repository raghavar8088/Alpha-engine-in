"""Monte Carlo robustness analysis: bootstrap-resample the closed-trade P&L sequence
(sampling with replacement, same trade count) to estimate how much of the backtest
outcome is sequence luck. Reports percentile bands for final equity and max drawdown,
and the probability of breaching a ruin threshold."""

import random

from backtesting_service.engine import BacktestRun


def monte_carlo(
    run: BacktestRun,
    n_runs: int = 1000,
    ruin_drawdown_pct: float = 30.0,
    seed: int | None = 42,
) -> dict:
    pnls = [t.pnl for t in run.trades if t.pnl is not None]
    if len(pnls) < 5:
        return {"error": f"only {len(pnls)} closed trades — too few for Monte Carlo"}

    rng = random.Random(seed)
    initial = run.config.initial_capital
    finals: list[float] = []
    max_dds: list[float] = []
    ruined = 0

    for _ in range(n_runs):
        equity = initial
        peak = initial
        max_dd = 0.0
        for _ in pnls:
            equity += rng.choice(pnls)
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak * 100)
        finals.append(equity)
        max_dds.append(max_dd)
        if max_dd >= ruin_drawdown_pct:
            ruined += 1

    finals.sort()
    max_dds.sort()
    return {
        "n_runs": n_runs,
        "trades_per_run": len(pnls),
        "final_equity": {
            "p5": round(_pct(finals, 5), 2),
            "p25": round(_pct(finals, 25), 2),
            "p50": round(_pct(finals, 50), 2),
            "p75": round(_pct(finals, 75), 2),
            "p95": round(_pct(finals, 95), 2),
        },
        "max_drawdown_pct": {
            "p5": round(_pct(max_dds, 5), 2),
            "p50": round(_pct(max_dds, 50), 2),
            "p95": round(_pct(max_dds, 95), 2),
        },
        "prob_profit": round(sum(1 for f in finals if f > initial) / n_runs, 4),
        "ruin_threshold_pct": ruin_drawdown_pct,
        "prob_ruin": round(ruined / n_runs, 4),
    }


def _pct(sorted_values: list[float], p: float) -> float:
    idx = min(int(len(sorted_values) * p / 100), len(sorted_values) - 1)
    return sorted_values[idx]
