"""Strategy #6 — Ichimoku. Long when price closes above the cloud with a bullish
Tenkan/Kijun cross; exit when price closes back below Kijun. Cloud values are current
(non-displaced) — see indicators.ichimoku."""

from pydantic import BaseModel, Field

from strategy_service.indicators import ichimoku
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class Ichimoku(Strategy):
    metadata = StrategyMetadata(
        strategy_id="ichimoku",
        name="Ichimoku",
        category="trend",
        description="Close above the Kumo cloud + bullish Tenkan/Kijun cross to enter; "
        "close below Kijun to exit. Kijun doubles as the trailing stop.",
        timeframes=[Timeframe.D1, Timeframe.W1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.42,
        risk_reward=2.0,
    )

    class Params(BaseModel):
        tenkan: int = Field(default=9, ge=2)
        kijun: int = Field(default=26, ge=3)
        senkou_b: int = Field(default=52, ge=4)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return self.params.senkou_b + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < self.warmup:
            return None
        bar = ctx.current
        t, k, span_a, span_b = ichimoku(ctx.bars, self.params.tenkan, self.params.kijun, self.params.senkou_b)
        cloud_top = max(span_a[-1], span_b[-1])

        if not self._long:
            tk_cross = t[-2] <= k[-2] and t[-1] > k[-1]
            if tk_cross and bar.close > cloud_top:
                self._long = True
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.55, stop_loss=round(k[-1], 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"Tenkan/Kijun bullish cross above cloud (close {bar.close:.2f} > {cloud_top:.2f})",
                )
        elif bar.close < k[-1]:
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close {bar.close:.2f} below Kijun {k[-1]:.2f}",
            )
        return None
