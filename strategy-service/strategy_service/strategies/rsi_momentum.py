"""Strategy #11 — RSI Momentum. Momentum-regime entry: RSI crossing UP through the
strength threshold (60) signals expanding momentum; exit when it decays back through
the floor (45). The opposite of the mean-reversion use of RSI."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, rsi
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class RsiMomentum(Strategy):
    metadata = StrategyMetadata(
        strategy_id="rsi_momentum",
        name="RSI Momentum",
        category="momentum",
        description="Long when RSI crosses above the strength threshold (momentum "
        "ignition), exit when it falls back through the floor. ATR stop.",
        timeframes=[Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.44,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=2)
        entry_level: float = Field(default=60.0, gt=0, lt=100)
        exit_level: float = Field(default=45.0, gt=0, lt=100)
        atr_period: int = Field(default=14, ge=2)
        atr_stop_mult: float = Field(default=2.0, gt=0)

    @property
    def warmup(self) -> int:
        return max(self.params.period, self.params.atr_period) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        r = rsi(closes, self.params.period)
        bar = ctx.current

        if r[-2] <= self.params.entry_level < r[-1]:
            a = atr(ctx.bars, self.params.atr_period)[-1]
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(bar.close - a * self.params.atr_stop_mult, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"RSI{self.params.period} crossed above {self.params.entry_level:.0f} ({r[-1]:.1f})",
            )
        if r[-2] >= self.params.exit_level > r[-1]:
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"RSI{self.params.period} fell below {self.params.exit_level:.0f} ({r[-1]:.1f})",
            )
        return None
