"""Strategy #9 — Multi-Timeframe EMA. Higher-timeframe trend filter + current-timeframe
trigger, approximated on a single series: the higher timeframe is emulated with a
proportionally longer EMA (e.g. 4x period on 15m ~ hourly EMA). True cross-timeframe
feeds arrive with the live engine's multi-stream context (Phase 5)."""

from pydantic import BaseModel, Field

from strategy_service.indicators import ema
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class MtfEma(Strategy):
    metadata = StrategyMetadata(
        strategy_id="mtf_ema",
        name="Multi-Timeframe EMA",
        category="trend",
        description="Trade fast EMA crosses only in the direction of the higher-"
        "timeframe trend (emulated with a 4x-length EMA on the same series).",
        timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.45,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        fast: int = Field(default=9, ge=2)
        slow: int = Field(default=21, ge=3)
        htf_multiplier: int = Field(default=4, ge=2, description="higher-timeframe emulation factor")
        swing_lookback: int = Field(default=10, ge=2)
        reward_ratio: float = Field(default=2.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.slow * self.params.htf_multiplier + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        bar = ctx.current
        fast = ema(closes, self.params.fast)
        slow = ema(closes, self.params.slow)
        htf = ema(closes, self.params.slow * self.params.htf_multiplier)

        crossed_up = fast[-2] <= slow[-2] and fast[-1] > slow[-1]
        crossed_down = fast[-2] >= slow[-2] and fast[-1] < slow[-1]

        if crossed_up and bar.close > htf[-1] and htf[-1] > htf[-2]:
            stop = min(b.low for b in ctx.bars[-self.params.swing_lookback :])
            risk = bar.close - stop
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(stop, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2) if risk > 0 else None,
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"EMA{self.params.fast}/{self.params.slow} bull cross with rising "
                f"HTF EMA{self.params.slow * self.params.htf_multiplier}",
            )
        if crossed_down:
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning="Fast/slow EMA bear cross",
            )
        return None
