"""Strategy #16 — Price Breakout (momentum). Close above the N-bar closing high with an
EMA trend filter; fixed ATR stop and R-multiple target, EMA loss-of-trend exit."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class PriceBreakout(Strategy):
    metadata = StrategyMetadata(
        strategy_id="price_breakout",
        name="Price Breakout",
        category="momentum",
        description="N-bar closing-high breakout with EMA trend filter; ATR stop, "
        "R-multiple target, exit if close loses the EMA.",
        timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.42,
        risk_reward=2.0,
    )

    class Params(BaseModel):
        lookback: int = Field(default=100, ge=5)
        trend_ema: int = Field(default=20, ge=2)
        atr_period: int = Field(default=14, ge=2)
        atr_stop_mult: float = Field(default=2.0, gt=0)
        reward_ratio: float = Field(default=2.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return max(self.params.lookback, self.params.trend_ema, self.params.atr_period) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        bar = ctx.current
        trend = ema(closes, self.params.trend_ema)[-1]

        if not self._long:
            prior_high = max(closes[-self.params.lookback - 1 : -1])
            if bar.close > prior_high and bar.close > trend:
                self._long = True
                a = atr(ctx.bars, self.params.atr_period)[-1]
                risk = a * self.params.atr_stop_mult
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.55, stop_loss=round(bar.close - risk, 2),
                    target=round(bar.close + risk * self.params.reward_ratio, 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"Close {bar.close:.2f} broke {self.params.lookback}-bar closing high {prior_high:.2f}",
                )
        elif bar.close < trend:
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close {bar.close:.2f} lost EMA{self.params.trend_ema} {trend:.2f}",
            )
        return None
