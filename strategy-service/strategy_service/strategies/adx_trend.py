"""Strategy #4 — ADX Trend. Directional-movement entry only when the trend is STRONG:
+DI over -DI with ADX above threshold; exit when ADX decays or DI flips."""

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, atr
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class AdxTrend(Strategy):
    metadata = StrategyMetadata(
        strategy_id="adx_trend",
        name="ADX Trend",
        category="trend",
        description="Long when +DI crosses over -DI with ADX above the strength "
        "threshold; exit on DI flip or ADX decay below the floor. ATR stop.",
        timeframes=[Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.44,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=2)
        adx_entry: float = Field(default=25.0, gt=0)
        adx_floor: float = Field(default=18.0, gt=0)
        atr_stop_mult: float = Field(default=2.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return 2 * self.params.period + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < self.warmup:
            return None
        bar = ctx.current
        adx_v, plus_di, minus_di = adx(ctx.bars, self.params.period)

        if not self._long:
            crossed = plus_di[-2] <= minus_di[-2] and plus_di[-1] > minus_di[-1]
            if crossed and adx_v[-1] >= self.params.adx_entry:
                a = atr(ctx.bars, self.params.period)[-1]
                self._long = True
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.55, stop_loss=round(bar.close - a * self.params.atr_stop_mult, 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"+DI {plus_di[-1]:.1f} over -DI {minus_di[-1]:.1f}, ADX {adx_v[-1]:.1f}",
                )
        else:
            di_flip = plus_di[-1] < minus_di[-1]
            adx_dead = adx_v[-1] < self.params.adx_floor
            if di_flip or adx_dead:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="DI flip" if di_flip else f"ADX decayed to {adx_v[-1]:.1f}",
                )
        return None
