"""Historical runner: feed a bar sequence through a strategy, collect its signals.
Pure function of (strategy, bars) — storage lives at the caller (main.py CLI now, the
backtesting engine next phase)."""

from tradingai_shared.contracts import Strategy, StrategyContext
from tradingai_shared.domain import Bar, Signal


def run_historical(strategy: Strategy, bars: list[Bar], max_context_bars: int = 500) -> list[Signal]:
    ctx = StrategyContext(max_bars=max(max_context_bars, strategy.warmup + 2))
    signals: list[Signal] = []
    for i, bar in enumerate(bars):
        ctx.push(bar)
        if i + 1 < strategy.warmup:
            continue  # indicators not meaningful yet
        signal = strategy.on_bar(ctx)
        if signal is not None:
            signals.append(signal)
    return signals
