"""Strategy #13 — MACD Momentum. Histogram-acceleration entry: rising histogram turning
positive means momentum is EXPANDING (vs macd_trend's slower line/signal-above-zero
trend confirmation). Exit when the histogram contracts for consecutive bars."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, macd
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class MacdMomentum(Strategy):
    metadata = StrategyMetadata(
        strategy_id="macd_momentum",
        name="MACD Momentum",
        category="momentum",
        description="MACD histogram turning positive while expanding = momentum "
        "ignition; exit after consecutive contracting-histogram bars.",
        timeframes=[Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.43,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        fast: int = Field(default=12, ge=2)
        slow: int = Field(default=26, ge=3)
        signal: int = Field(default=9, ge=2)
        exit_contraction_bars: int = Field(default=3, ge=1)
        atr_period: int = Field(default=14, ge=2)
        atr_stop_mult: float = Field(default=2.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._contracting = 0

    @property
    def warmup(self) -> int:
        return self.params.slow + self.params.signal + 3

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        bar = ctx.current
        line, sig = macd(closes, self.params.fast, self.params.slow, self.params.signal)
        hist = [l - s for l, s in zip(line, sig)]

        if not self._long:
            turned_positive = hist[-2] <= 0 < hist[-1]
            expanding = hist[-1] > hist[-2] > hist[-3]
            if turned_positive and expanding:
                a = atr(ctx.bars, self.params.atr_period)[-1]
                self._long, self._contracting = True, 0
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.5, stop_loss=round(bar.close - a * self.params.atr_stop_mult, 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"MACD histogram ignition ({hist[-3]:.2f} -> {hist[-1]:.2f})",
                )
        else:
            self._contracting = self._contracting + 1 if hist[-1] < hist[-2] else 0
            if self._contracting >= self.params.exit_contraction_bars or hist[-1] < 0:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"histogram contracting {self._contracting} bars" if hist[-1] >= 0 else "histogram negative",
                )
        return None
