"""Strategy #2 — SMA Cross (trend following). The classic golden/death cross:
SMA50 over SMA200. Slower than EMA cross; suited to positional trading on daily bars."""

from pydantic import BaseModel, Field

from strategy_service.indicators import sma
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class SmaCross(Strategy):
    metadata = StrategyMetadata(
        strategy_id="sma_cross",
        name="SMA Cross",
        category="trend",
        description="Golden cross (SMA fast over slow) long entry, death cross exit. "
        "Positional trend capture with a swing-low stop.",
        timeframes=[Timeframe.D1, Timeframe.W1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.40,
        risk_reward=2.5,
    )

    class Params(BaseModel):
        fast: int = Field(default=50, ge=2)
        slow: int = Field(default=200, ge=3)
        swing_lookback: int = Field(default=20, ge=2)
        reward_ratio: float = Field(default=2.5, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.slow + 1

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        fast = sma(closes, self.params.fast)
        slow = sma(closes, self.params.slow)
        bar = ctx.current

        if fast[-2] <= slow[-2] and fast[-1] > slow[-1]:
            stop = min(b.low for b in ctx.bars[-self.params.swing_lookback :])
            risk = bar.close - stop
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(stop, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2) if risk > 0 else None,
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Golden cross: SMA{self.params.fast} {fast[-1]:.2f} > SMA{self.params.slow} {slow[-1]:.2f}",
            )
        if fast[-2] >= slow[-2] and fast[-1] < slow[-1]:
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Death cross: SMA{self.params.fast} {fast[-1]:.2f} < SMA{self.params.slow} {slow[-1]:.2f}",
            )
        return None
