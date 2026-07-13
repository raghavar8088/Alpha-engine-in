"""Strategy #28 — Pivot Swing. Bounce off the rolling-period pivot support (S1) in an
uptrend: price dips to S1 and closes back above the pivot's floor, targeting R1."""

from pydantic import BaseModel, Field

from strategy_service.indicators import sma
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class PivotSwing(Strategy):
    metadata = StrategyMetadata(
        strategy_id="pivot_swing",
        name="Pivot Swing",
        category="swing",
        description="Buy the bounce off rolling-pivot S1 in an uptrend; target R1, "
        "stop below S2. Classic floor-trader pivots from the prior N-bar range.",
        timeframes=[Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="range-bound",
        expected_win_rate=0.52,
        risk_reward=1.4,
    )

    class Params(BaseModel):
        pivot_period: int = Field(default=5, ge=2, description="bars defining the prior range")
        trend_sma: int = Field(default=100, ge=10)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return max(self.params.pivot_period + 1, self.params.trend_sma) + 1

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup:
            return None
        bar = ctx.current
        window = bars[-self.params.pivot_period - 1 : -1]
        hi = max(b.high for b in window)
        lo = min(b.low for b in window)
        close = window[-1].close
        pivot = (hi + lo + close) / 3
        s1 = 2 * pivot - hi
        s2 = pivot - (hi - lo)
        r1 = 2 * pivot - lo

        if self._long:
            if bar.close >= r1:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"Reached R1 {r1:.2f}",
                )
            return None

        trend = sma(ctx.closes, self.params.trend_sma)[-1]
        dipped_to_s1 = bar.low <= s1
        closed_back = bar.close > s1
        if dipped_to_s1 and closed_back and bar.close > trend:
            self._long = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(s2, 2), target=round(r1, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Bounced off S1 {s1:.2f} in uptrend (close {bar.close:.2f})",
            )
        return None
