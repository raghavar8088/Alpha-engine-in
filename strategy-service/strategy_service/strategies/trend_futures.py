"""Strategy #42 — Trend Futures. EMA-channel trend rider sized for futures (lot-based,
wider stops for leverage). Validates on the underlying index series until continuous
futures bars are backfilled — same signal logic either way; the engine applies futures
costs when the instrument is a future."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class TrendFutures(Strategy):
    metadata = StrategyMetadata(
        strategy_id="trend_futures",
        name="Trend Futures",
        category="futures",
        description="EMA-trend rider for index/stock futures: long above a rising EMA "
        "with ATR buffer, exit on close below it. Wide ATR stop sized for leverage.",
        timeframes=[Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.INDEX_FUTURE, AssetClass.EQUITY_FUTURE, AssetClass.INDEX],
        suitable_market="trending",
        expected_win_rate=0.42,
        risk_reward=2.0,
    )

    class Params(BaseModel):
        trend_ema: int = Field(default=34, ge=2)
        buffer_atr: float = Field(default=0.5, gt=0, description="entry needs close > EMA + buffer")
        atr_period: int = Field(default=14, ge=2)
        stop_atr: float = Field(default=3.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return max(self.params.trend_ema, self.params.atr_period) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        bar = ctx.current
        trend = ema(closes, self.params.trend_ema)
        a = atr(ctx.bars, self.params.atr_period)[-1]

        if not self._long:
            rising = trend[-1] > trend[-2]
            if rising and bar.close > trend[-1] + self.params.buffer_atr * a:
                self._long = True
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.5, stop_loss=round(bar.close - self.params.stop_atr * a, 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"Close {bar.close:.2f} above rising EMA{self.params.trend_ema} + "
                    f"{self.params.buffer_atr} ATR buffer",
                )
        elif bar.close < trend[-1]:
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close below EMA{self.params.trend_ema}",
            )
        return None
