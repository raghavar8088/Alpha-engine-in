"""Strategy #32 — High Volume Breakout (swing hold). Like volume_breakout but a swing
variant: breakout of the 52-bar high on 90th-percentile volume, held with a wide
trailing channel instead of a tight target. Needs real volume."""

from pydantic import BaseModel, Field

from strategy_service.indicators import donchian
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class HighVolumeBreakout(Strategy):
    metadata = StrategyMetadata(
        strategy_id="high_volume_breakout",
        name="High Volume Breakout",
        category="swing",
        description="52-bar-high breakout on top-decile volume, held with a Donchian "
        "trailing exit - the swing/positional cousin of volume_breakout.",
        timeframes=[Timeframe.D1, Timeframe.W1],
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.40,
        risk_reward=2.5,
    )

    class Params(BaseModel):
        breakout_period: int = Field(default=52, ge=10)
        exit_period: int = Field(default=15, ge=3)
        volume_percentile: float = Field(default=0.9, gt=0, lt=1)
        volume_window: int = Field(default=60, ge=10)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return max(self.params.breakout_period, self.params.volume_window) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup or ctx.current.volume == 0:
            return None
        bar = ctx.current

        entry_high = donchian(bars, self.params.breakout_period)[0][-1]
        exit_low = donchian(bars, self.params.exit_period)[1][-1]

        if self._long:
            if bar.close < exit_low:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"Trailing exit: close below {self.params.exit_period}-bar low {exit_low:.2f}",
                )
            return None

        recent_volumes = sorted(b.volume for b in bars[-self.params.volume_window :])
        threshold = recent_volumes[int(len(recent_volumes) * self.params.volume_percentile)]
        if bar.close > entry_high and bar.volume >= threshold:
            self._long = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(exit_low, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"{self.params.breakout_period}-bar high broken on top-decile volume "
                f"({bar.volume:,} >= {threshold:,})",
            )
        return None
