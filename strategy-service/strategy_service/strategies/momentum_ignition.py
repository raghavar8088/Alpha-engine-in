"""Strategy #20 — Momentum Ignition. A burst pattern: consecutive strong directional
closes with expanding range and (when available) rising volume — the tape signature of
aggressive initiative buying. Ride the burst briefly with a tight trail."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class MomentumIgnition(Strategy):
    metadata = StrategyMetadata(
        strategy_id="momentum_ignition",
        name="Momentum Ignition",
        category="momentum",
        description="Burst detector: N consecutive strong closes with expanding range "
        "(+ rising volume where available); short tight-trailed ride.",
        timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="high-volatility",
        expected_win_rate=0.44,
        risk_reward=1.6,
    )

    class Params(BaseModel):
        burst_bars: int = Field(default=3, ge=2)
        body_frac: float = Field(default=0.55, gt=0, le=1, description="min close-open body vs range per bar")
        atr_period: int = Field(default=14, ge=2)
        stop_atr: float = Field(default=1.5, gt=0)
        max_hold_bars: int = Field(default=8, ge=1)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._held = 0

    @property
    def warmup(self) -> int:
        return max(self.params.atr_period, self.params.burst_bars) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup:
            return None
        bar = ctx.current

        if self._long:
            self._held += 1
            trail = min(b.low for b in bars[-3:])
            if bar.close < trail or self._held >= self.params.max_hold_bars:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="3-bar trail broken" if bar.close < trail else "burst window over",
                )
            return None

        burst = bars[-self.params.burst_bars :]

        def strong(b) -> bool:
            r = b.high - b.low
            return r > 0 and b.close > b.open and (b.close - b.open) / r >= self.params.body_frac

        all_strong = all(strong(b) for b in burst)
        ranges_expanding = all(
            (burst[i].high - burst[i].low) >= (burst[i - 1].high - burst[i - 1].low)
            for i in range(1, len(burst))
        )
        volume_ok = burst[0].volume == 0 or burst[-1].volume >= burst[0].volume

        if all_strong and ranges_expanding and volume_ok:
            a = atr(bars, self.params.atr_period)[-1]
            self._long, self._held = True, 0
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(bar.close - self.params.stop_atr * a, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Ignition: {self.params.burst_bars} expanding strong closes",
            )
        return None
