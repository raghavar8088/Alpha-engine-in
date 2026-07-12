"""Render-ready chart series from a BacktestRun — plain JSON the frontend draws as-is.
Dense series are downsampled to <= MAX_POINTS so a 5-year minute backtest doesn't ship
hundreds of thousands of points to the browser."""

from backtesting_service.engine import BacktestRun

MAX_POINTS = 2000
ROLLING_WINDOW_BARS = 63  # ~one quarter on daily bars


def compute_charts(run: BacktestRun) -> dict:
    equity_points = [
        {"ts": ts.isoformat(), "value": round(value, 2)}
        for ts, value in zip(run.equity_ts, run.equity)
    ]

    # Drawdown series (pct below running peak)
    drawdown_points = []
    peak = float("-inf")
    for ts, value in zip(run.equity_ts, run.equity):
        peak = max(peak, value)
        dd = (value - peak) / peak * 100 if peak > 0 else 0.0
        drawdown_points.append({"ts": ts.isoformat(), "value": round(dd, 2)})

    # Rolling return over a fixed bar window
    rolling_points = []
    for i in range(ROLLING_WINDOW_BARS, len(run.equity)):
        base = run.equity[i - ROLLING_WINDOW_BARS]
        if base > 0:
            rolling_points.append(
                {
                    "ts": run.equity_ts[i].isoformat(),
                    "value": round((run.equity[i] - base) / base * 100, 2),
                }
            )

    # Trade P&L distribution (fixed bucket count across the observed range)
    pnls = [t.pnl for t in run.trades if t.pnl is not None]
    distribution = _histogram(pnls, buckets=15)

    return {
        "equity_curve": _downsample(equity_points),
        "drawdown_curve": _downsample(drawdown_points),
        "rolling_return": _downsample(rolling_points),
        "trade_distribution": distribution,
        "trades": [
            {
                "entry_ts": t.entry_ts.isoformat(),
                "exit_ts": t.exit_ts.isoformat() if t.exit_ts else None,
                "direction": t.direction.value,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "pnl": t.pnl,
                "charges": t.charges,
                "exit_reason": t.exit_reason,
            }
            for t in run.trades
        ],
    }


def _histogram(values: list[float], buckets: int) -> list[dict]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if lo == hi:
        return [{"from": round(lo, 2), "to": round(hi, 2), "count": len(values)}]
    width = (hi - lo) / buckets
    counts = [0] * buckets
    for v in values:
        idx = min(int((v - lo) / width), buckets - 1)
        counts[idx] += 1
    return [
        {"from": round(lo + i * width, 2), "to": round(lo + (i + 1) * width, 2), "count": c}
        for i, c in enumerate(counts)
    ]


def _downsample(points: list[dict]) -> list[dict]:
    """Stride-sample keeping first and last point (fidelity beyond ~2k points is
    invisible at chart resolution)."""
    n = len(points)
    if n <= MAX_POINTS:
        return points
    stride = n / MAX_POINTS
    sampled = [points[int(i * stride)] for i in range(MAX_POINTS)]
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled
