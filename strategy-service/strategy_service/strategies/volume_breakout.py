"""Strategy #17 — Volume Breakout. Price breaking the N-bar high WITH a volume z-score
spike — participation confirms the move. Needs real volume (equities/ETFs)."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, zscore
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class VolumeBreakout(Strategy):
    metadata = StrategyMetadata(
        strategy_id="volume_breakout",
        name="Volume Breakout",
        category="momentum",
        description="N-bar high breakout confirmed by a volume z-score spike; ATR stop, "
        "R-multiple target. Needs real volume - equities/ETFs.",
        timeframes=[Timeframe.M15, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.43,
        risk_reward=2.0,
    )

    class Params(BaseModel):
        lookback: int = Field(default=50, ge=5)
        volume_z: float = Field(default=2.0, gt=0)
        volume_window: int = Field(default=50, ge=5)
        atr_period: int = Field(default=14, ge=2)
        atr_stop_mult: float = Field(default=2.0, gt=0)
        reward_ratio: float = Field(default=2.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return max(self.params.lookback, self.params.volume_window, self.params.atr_period) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < self.warmup or ctx.current.volume == 0:
            return None
        bar = ctx.current
        volumes = [float(b.volume) for b in ctx.bars]

        if not self._long:
            prior_high = max(b.high for b in ctx.bars[-self.params.lookback - 1 : -1])
            vol_z = zscore(volumes, self.params.volume_window)[-1]
            if bar.close > prior_high and vol_z >= self.params.volume_z:
                a = atr(ctx.bars, self.params.atr_period)[-1]
                risk = a * self.params.atr_stop_mult
                self._long = True
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.55, stop_loss=round(bar.close - risk, 2),
                    target=round(bar.close + risk * self.params.reward_ratio, 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"Breakout of {prior_high:.2f} on volume z={vol_z:.1f}",
                )
        else:
            # Momentum burst either hits target/stop (engine) or fizzles: exit on a
            # close below the breakout bar's low region approximated by 10-bar low.
            recent_low = min(b.low for b in ctx.bars[-10:])
            if bar.close < recent_low:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="Close below 10-bar low - breakout failed",
                )
        return None
