"""Strategy #12 — Stochastic Momentum. %K crossing above %D out of the mid-zone (not
oversold — that's reversion) rides continuation; exit on the overbought roll-down."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, stochastic
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class StochasticMomentum(Strategy):
    metadata = StrategyMetadata(
        strategy_id="stochastic_momentum",
        name="Stochastic Momentum",
        category="momentum",
        description="%K/%D bullish cross in the 40-75 continuation zone; exit when %K "
        "rolls down out of overbought. ATR stop.",
        timeframes=[Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.45,
        risk_reward=1.5,
    )

    class Params(BaseModel):
        k_period: int = Field(default=14, ge=2)
        d_period: int = Field(default=3, ge=2)
        zone_low: float = Field(default=40.0, ge=0, lt=100)
        zone_high: float = Field(default=75.0, gt=0, le=100)
        exit_level: float = Field(default=80.0, gt=0, le=100)
        atr_period: int = Field(default=14, ge=2)
        atr_stop_mult: float = Field(default=2.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return self.params.k_period + self.params.d_period + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < self.warmup:
            return None
        bar = ctx.current
        k, d = stochastic(ctx.bars, self.params.k_period, self.params.d_period)

        if not self._long:
            crossed = k[-2] <= d[-2] and k[-1] > d[-1]
            in_zone = self.params.zone_low <= k[-1] <= self.params.zone_high
            if crossed and in_zone:
                a = atr(ctx.bars, self.params.atr_period)[-1]
                self._long = True
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.5, stop_loss=round(bar.close - a * self.params.atr_stop_mult, 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"%K {k[-1]:.1f} crossed %D {d[-1]:.1f} in continuation zone",
                )
        else:
            rolled_down = k[-2] >= self.params.exit_level > k[-1]
            bear_cross = k[-2] >= d[-2] and k[-1] < d[-1]
            if rolled_down or bear_cross:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="overbought roll-down" if rolled_down else "%K/%D bear cross",
                )
        return None
