"""Strategy #38 — Volume Spike (intraday). An extreme single-bar volume z-score with a
directional close (wide-range up bar) marks aggressive buying; ride the follow-through
briefly. Flat by close. Needs volume — equities on 15m."""

from datetime import time, timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, zscore
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


@register_strategy
class VolumeSpike(Strategy):
    metadata = StrategyMetadata(
        strategy_id="volume_spike",
        name="Volume Spike",
        category="intraday",
        description="Extreme bar-volume z-score + wide-range bullish bar = aggressive "
        "buying; short follow-through hold, flat by close. Equities on 15m.",
        timeframes=[Timeframe.M15, Timeframe.M5],
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        suitable_market="high-volatility",
        expected_win_rate=0.46,
        risk_reward=1.4,
    )

    class Params(BaseModel):
        volume_z: float = Field(default=3.0, gt=0)
        volume_window: int = Field(default=50, ge=10)
        body_frac: float = Field(default=0.6, gt=0, le=1, description="close-open body vs bar range")
        max_hold_bars: int = Field(default=6, ge=1)
        atr_period: int = Field(default=14, ge=2)
        stop_atr: float = Field(default=1.5, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._held = 0

    @property
    def warmup(self) -> int:
        return self.params.volume_window + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < self.warmup or ctx.current.volume == 0:
            return None
        bar = ctx.current
        ist = bar.ts.astimezone(IST)

        if self._long:
            self._held += 1
            eod = ist.time() >= time(15, 0)
            if self._held >= self.params.max_hold_bars or eod:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="session close" if eod else f"follow-through window over ({self._held} bars)",
                )
            return None

        if not (time(9, 45) <= ist.time() < time(14, 30)):
            return None
        vol_z = zscore([float(b.volume) for b in ctx.bars], self.params.volume_window)[-1]
        bar_range = bar.high - bar.low
        bullish_body = bar_range > 0 and (bar.close - bar.open) / bar_range >= self.params.body_frac

        if vol_z >= self.params.volume_z and bullish_body:
            a = atr(ctx.bars, self.params.atr_period)[-1]
            self._long, self._held = True, 0
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(bar.close - self.params.stop_atr * a, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Volume spike z={vol_z:.1f} with {self.params.body_frac:.0%}+ bullish body",
            )
        return None
