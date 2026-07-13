"""Strategy #31 — Cup & Handle (swing, simplified detection). A rounded base: prior
peak, a deep-enough trough, recovery back near the peak (cup), then a shallow pullback
(handle) breaking above the rim."""

from pydantic import BaseModel, Field

from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class CupHandle(Strategy):
    metadata = StrategyMetadata(
        strategy_id="cup_handle",
        name="Cup & Handle",
        category="swing",
        description="Rounded base recovering to the prior rim + shallow handle "
        "pullback; buy the rim breakout, cup-depth-fraction target.",
        timeframes=[Timeframe.D1, Timeframe.W1],
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.44,
        risk_reward=2.0,
    )

    class Params(BaseModel):
        cup_bars: int = Field(default=40, ge=10)
        handle_bars: int = Field(default=6, ge=3)
        min_cup_depth_pct: float = Field(default=8.0, gt=0)
        max_handle_depth: float = Field(default=0.35, gt=0, le=1, description="handle depth vs cup depth")

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return self.params.cup_bars + self.params.handle_bars + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup:
            return None
        bar = ctx.current
        c, h = self.params.cup_bars, self.params.handle_bars

        cup = bars[-(c + h) : -h]
        handle = bars[-h:]

        rim = max(cup[0].high, cup[-1].high)  # rim = the two lips
        trough = min(b.low for b in cup)
        depth_pct = (rim - trough) / rim * 100
        if depth_pct < self.params.min_cup_depth_pct:
            return None
        # both lips near the rim (rounded recovery, not a V into a downtrend)
        lips_close = abs(cup[0].high - cup[-1].high) / rim < 0.05

        handle_low = min(b.low for b in handle)
        handle_depth = (rim - handle_low) / (rim - trough) if rim > trough else 1.0

        if self._long:
            if bar.close < handle_low:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="Close below the handle low - pattern failed",
                )
            return None

        if lips_close and handle_depth <= self.params.max_handle_depth and bar.close > rim:
            self._long = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(handle_low, 2),
                target=round(bar.close + (rim - trough) * 0.5, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Cup ({depth_pct:.1f}% deep) + handle broke rim {rim:.2f}",
            )
        return None
