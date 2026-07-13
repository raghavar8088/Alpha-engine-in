"""Strategy #33 — Delivery Breakout (swing). True delivery-percentage data (NSE
security-wise delivery positions) is a research-service feed (Phase 6); until it lands
this uses the documented proxy of SUSTAINED elevated volume (multi-bar z-score, not a
single spike) alongside a price base breakout — the footprint delivery buying leaves
on the tape."""

from pydantic import BaseModel, Field

from strategy_service.indicators import zscore
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class DeliveryBreakout(Strategy):
    metadata = StrategyMetadata(
        strategy_id="delivery_breakout",
        name="Delivery Breakout",
        category="swing",
        description="Base breakout with SUSTAINED volume elevation (3-bar z-score - "
        "the delivery-buying footprint; real delivery % data wires in with the "
        "research service). Equities only.",
        timeframes=[Timeframe.D1],
        asset_classes=[AssetClass.EQUITY],
        suitable_market="trending",
        expected_win_rate=0.42,
        risk_reward=2.0,
    )

    class Params(BaseModel):
        base_period: int = Field(default=30, ge=10)
        sustained_bars: int = Field(default=3, ge=2)
        volume_z: float = Field(default=1.0, gt=0, description="each of the sustained bars must clear this")
        volume_window: int = Field(default=50, ge=10)
        stop_pct: float = Field(default=6.0, gt=0)
        reward_ratio: float = Field(default=2.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return max(self.params.base_period, self.params.volume_window) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup or ctx.current.volume == 0:
            return None
        bar = ctx.current

        if self._long:
            base_low = min(b.low for b in bars[-self.params.base_period :])
            if bar.close < base_low:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="Close below the base low",
                )
            return None

        base_high = max(b.high for b in bars[-self.params.base_period - 1 : -1])
        vol_z = zscore([float(b.volume) for b in bars], self.params.volume_window)
        sustained = all(z >= self.params.volume_z for z in vol_z[-self.params.sustained_bars :])

        if bar.close > base_high and sustained:
            risk = bar.close * self.params.stop_pct / 100
            self._long = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(bar.close - risk, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Base breakout with {self.params.sustained_bars} sustained high-volume bars "
                f"(delivery-buying footprint)",
            )
        return None
