"""Strategy #7 — MACD Trend (trend following). Long when the MACD line crosses above its
signal line while BOTH are above zero (trend confirmation, not just momentum); exit on
the cross back below the signal line."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, macd
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class MacdTrend(Strategy):
    metadata = StrategyMetadata(
        strategy_id="macd_trend",
        name="MACD Trend",
        category="trend",
        description="MACD/signal cross above the zero line for entries (trend-side "
        "only), cross-down exit, ATR stop.",
        timeframes=[Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.42,
        risk_reward=2.0,
    )

    class Params(BaseModel):
        fast: int = Field(default=12, ge=2)
        slow: int = Field(default=26, ge=3)
        signal: int = Field(default=9, ge=2)
        atr_period: int = Field(default=14, ge=2)
        atr_stop_mult: float = Field(default=2.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.slow + self.params.signal + 1

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        line, sig = macd(closes, self.params.fast, self.params.slow, self.params.signal)
        bar = ctx.current

        crossed_up = line[-2] <= sig[-2] and line[-1] > sig[-1]
        crossed_down = line[-2] >= sig[-2] and line[-1] < sig[-1]

        if crossed_up and line[-1] > 0 and sig[-1] > 0:
            a = atr(ctx.bars, self.params.atr_period)[-1]
            stop = bar.close - a * self.params.atr_stop_mult
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(stop, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"MACD {line[-1]:.2f} crossed above signal {sig[-1]:.2f}, both above zero",
            )
        if crossed_down:
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"MACD {line[-1]:.2f} crossed below signal {sig[-1]:.2f}",
            )
        return None
