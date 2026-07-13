"""Strategy #49 — Bull Put Spread. Sell put spreads below support in an uptrend —
profits if price stays ABOVE the short strike. The directional condition (uptrend
holding above support) backtests as a long proxy with support-based stop; spread
premiums/strike selection wire in with Phase 7."""

from pydantic import BaseModel, Field

from strategy_service.indicators import donchian, sma
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class BullPutSpread(Strategy):
    metadata = StrategyMetadata(
        strategy_id="bull_put_spread",
        name="Bull Put Spread",
        category="options",
        description="Uptrend holding above N-bar support = sell the put spread below "
        "support. Proxy: long with support stop and time-boxed exit (theta expiry). "
        "Strike/premium selection lands with Phase 7.",
        timeframes=[Timeframe.D1],
        asset_classes=[AssetClass.INDEX_OPTION, AssetClass.EQUITY_OPTION, AssetClass.INDEX],
        suitable_market="trending",
        expected_win_rate=0.60,
        risk_reward=0.8,
    )

    class Params(BaseModel):
        support_period: int = Field(default=20, ge=5)
        trend_sma: int = Field(default=50, ge=10)
        expiry_bars: int = Field(default=20, ge=5, description="monthly-expiry proxy hold")
        support_buffer_pct: float = Field(default=1.0, ge=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._held = 0

    @property
    def warmup(self) -> int:
        return max(self.params.support_period, self.params.trend_sma) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup:
            return None
        bar = ctx.current
        support = donchian(bars, self.params.support_period)[1][-1]

        if self._long:
            self._held += 1
            if self._held >= self.params.expiry_bars:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"expiry proxy: {self.params.expiry_bars} bars held, spread expires worthless",
                )
            return None

        trend = sma(ctx.closes, self.params.trend_sma)[-1]
        buffer = 1 - self.params.support_buffer_pct / 100
        above_support = bar.close > support / buffer if buffer > 0 else False

        if bar.close > trend and above_support and bar.close > bars[-2].close:
            self._long, self._held = True, 0
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(support, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Sell put spread below support {support:.2f} in uptrend "
                f"(close {bar.close:.2f} > SMA{self.params.trend_sma})",
            )
        return None
