"""Strategy #14 — ROC (rate-of-change momentum). Long when N-bar ROC crosses above a
positive threshold (price accelerating), exit when ROC turns negative."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, roc
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class RocMomentum(Strategy):
    metadata = StrategyMetadata(
        strategy_id="roc_momentum",
        name="ROC Momentum",
        category="momentum",
        description="Rate-of-change threshold: long when N-bar ROC accelerates through "
        "+X%, exit when momentum turns negative. ATR stop.",
        timeframes=[Timeframe.D1, Timeframe.W1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.40,
        risk_reward=2.0,
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=2)
        entry_threshold_pct: float = Field(default=4.0, gt=0)
        atr_period: int = Field(default=14, ge=2)
        atr_stop_mult: float = Field(default=2.5, gt=0)

    @property
    def warmup(self) -> int:
        return max(self.params.period, self.params.atr_period) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        r = roc(closes, self.params.period)
        bar = ctx.current
        threshold = self.params.entry_threshold_pct

        if r[-2] <= threshold < r[-1]:
            a = atr(ctx.bars, self.params.atr_period)[-1]
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(bar.close - a * self.params.atr_stop_mult, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"ROC{self.params.period} accelerated to {r[-1]:.1f}% (> {threshold}%)",
            )
        if r[-2] >= 0 > r[-1]:
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"ROC{self.params.period} turned negative ({r[-1]:.1f}%)",
            )
        return None
