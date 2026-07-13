"""Strategy #3 — SuperTrend (trend following). ATR bands around the HL2 midpoint with
the standard band-ratchet: in an uptrend the lower band only rises, in a downtrend the
upper band only falls. Flip = signal. The trailing stop IS the supertrend line."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class SuperTrend(Strategy):
    metadata = StrategyMetadata(
        strategy_id="supertrend",
        name="SuperTrend",
        category="trend",
        description="ATR-band trend flip: long when close crosses above the ratcheted "
        "upper band; the rising lower band is the trailing stop.",
        timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.45,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        atr_period: int = Field(default=10, ge=2)
        multiplier: float = Field(default=3.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._trend: int = 0  # +1 up, -1 down, 0 unknown
        self._lower: float | None = None  # ratcheted stop band in an uptrend
        self._upper: float | None = None  # ratcheted band in a downtrend

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < self.warmup:
            return None
        bar = ctx.current
        a = atr(ctx.bars, self.params.atr_period)[-1]
        mid = (bar.high + bar.low) / 2
        basic_upper = mid + self.params.multiplier * a
        basic_lower = mid - self.params.multiplier * a

        # Ratchet the active band; a close through it flips the trend.
        if self._trend >= 0:
            self._lower = basic_lower if self._lower is None else max(self._lower, basic_lower)
            if self._trend == 0:
                self._trend = 1
                return None
            if bar.close < self._lower:
                self._trend, self._upper, self._lower = -1, basic_upper, None
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.6, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"SuperTrend flip down: close {bar.close:.2f} below band",
                )
        else:
            self._upper = basic_upper if self._upper is None else min(self._upper, basic_upper)
            if bar.close > self._upper:
                self._trend, self._lower, self._upper = 1, basic_lower, None
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.6, stop_loss=round(basic_lower, 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"SuperTrend flip up: close {bar.close:.2f} above band "
                    f"(ATR {a:.1f} x {self.params.multiplier})",
                )
        return None
