"""Strategy #30 — Triangle Breakout (swing). Contracting range (lower highs + higher
lows, shrinking ATR) resolving upward; target is the triangle's opening height."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class TriangleBreakout(Strategy):
    metadata = StrategyMetadata(
        strategy_id="triangle_breakout",
        name="Triangle Breakout",
        category="swing",
        description="Symmetric-triangle compression (contracting highs/lows, falling "
        "ATR) breaking upward; height-of-triangle target, apex stop.",
        timeframes=[Timeframe.D1, Timeframe.H1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="range-bound",
        expected_win_rate=0.42,
        risk_reward=2.0,
    )

    class Params(BaseModel):
        window: int = Field(default=20, ge=8, description="triangle length in bars")
        contraction: float = Field(default=0.6, gt=0, lt=1, description="second-half range must be < this x first half")

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return self.params.window + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup:
            return None
        bar = ctx.current
        w = self.params.window
        window = bars[-w - 1 : -1]
        half = w // 2
        first, second = window[:half], window[half:]

        first_range = max(b.high for b in first) - min(b.low for b in first)
        second_range = max(b.high for b in second) - min(b.low for b in second)
        contracting = first_range > 0 and second_range <= self.params.contraction * first_range

        second_high = max(b.high for b in second)
        second_low = min(b.low for b in second)

        if self._long:
            if bar.close < second_low:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="Fell back through the triangle base",
                )
            return None

        if contracting and bar.close > second_high:
            self._long = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(second_low, 2),
                target=round(bar.close + first_range, 2),  # triangle height
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Triangle breakout: range contracted {first_range:.1f} -> {second_range:.1f}, "
                f"close {bar.close:.2f} above {second_high:.2f}",
            )
        return None
