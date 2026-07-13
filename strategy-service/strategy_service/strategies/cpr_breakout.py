"""Strategy #27 — CPR Breakout (swing, daily). A NARROW previous-day Central Pivot
Range signals compression; a close above its top continues higher. Narrowness is
measured against ATR."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, prev_period_cpr
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class CprBreakout(Strategy):
    metadata = StrategyMetadata(
        strategy_id="cpr_breakout",
        name="CPR Breakout",
        category="swing",
        description="Narrow previous-period CPR (compression) + close above the CPR "
        "top = expansion entry; stop at the CPR bottom.",
        timeframes=[Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="high-volatility",
        expected_win_rate=0.44,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        narrow_atr_frac: float = Field(default=0.3, gt=0, description="CPR width < this x ATR = narrow")
        atr_period: int = Field(default=14, ge=2)
        reward_ratio: float = Field(default=1.8, gt=0)
        max_hold_bars: int = Field(default=8, ge=1)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._held = 0

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup:
            return None
        bar, prev = bars[-1], bars[-2]

        if self._long:
            self._held += 1
            if self._held >= self.params.max_hold_bars:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"time-boxed exit after {self._held} bars",
                )
            return None

        bottom, pivot, top = prev_period_cpr(prev.high, prev.low, prev.close)
        a = atr(bars, self.params.atr_period)[-1]
        narrow = (top - bottom) < self.params.narrow_atr_frac * a

        if narrow and bar.close > top:
            risk = bar.close - bottom
            self._long, self._held = True, 0
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(bottom, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2) if risk > 0 else None,
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Narrow CPR ({top - bottom:.2f} < {self.params.narrow_atr_frac} ATR) "
                f"broken at {bar.close:.2f}",
            )
        return None
