"""Strategy #10 — ATR Trend (Keltner-channel trend breakout). A close above the upper
ATR band signals expansion in trend direction; the middle EMA is the exit line."""

from pydantic import BaseModel, Field

from strategy_service.indicators import keltner
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class AtrTrend(Strategy):
    metadata = StrategyMetadata(
        strategy_id="atr_trend",
        name="ATR Trend",
        category="trend",
        description="Keltner-style expansion breakout: long on a close above the upper "
        "ATR band, exit on a close below the middle EMA.",
        timeframes=[Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.42,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=2)
        band_mult: float = Field(default=2.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < self.warmup:
            return None
        bar = ctx.current
        upper, mid, lower = keltner(ctx.bars, self.params.period, self.params.band_mult)

        if not self._long and bar.close > upper[-1]:
            self._long = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(mid[-1], 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close {bar.close:.2f} above upper ATR band {upper[-1]:.2f}",
            )
        if self._long and bar.close < mid[-1]:
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close {bar.close:.2f} below middle EMA {mid[-1]:.2f}",
            )
        return None
