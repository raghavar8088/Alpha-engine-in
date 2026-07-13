"""Strategy #50 — Iron Condor. Sell both wings in a LOW-volatility range — profits if
price stays inside the band until expiry. Regime detection (tight range, dead
momentum) backtests now via a range-fade proxy; four-leg pricing lands with Phase 7."""

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, atr, donchian
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class IronCondor(Strategy):
    metadata = StrategyMetadata(
        strategy_id="iron_condor",
        name="Iron Condor",
        category="options",
        description="Low-ADX, compressed-range regime = sell the condor. Proxy: fade "
        "the range low back toward the middle (the long half of the condor's payoff "
        "zone), time-boxed to expiry. Four-leg pricing lands with Phase 7.",
        timeframes=[Timeframe.D1],
        asset_classes=[AssetClass.INDEX_OPTION, AssetClass.INDEX],
        suitable_market="range-bound",
        expected_win_rate=0.62,
        risk_reward=0.6,
    )

    class Params(BaseModel):
        range_period: int = Field(default=20, ge=5)
        max_adx: float = Field(default=20.0, gt=0, description="dead-trend ceiling")
        adx_period: int = Field(default=14, ge=2)
        expiry_bars: int = Field(default=15, ge=3)
        atr_period: int = Field(default=14, ge=2)
        stop_atr: float = Field(default=1.5, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._held = 0

    @property
    def warmup(self) -> int:
        return max(self.params.range_period, 2 * self.params.adx_period + 1) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup:
            return None
        bar = ctx.current
        highs, lows = donchian(bars, self.params.range_period)
        range_mid = (highs[-1] + lows[-1]) / 2

        if self._long:
            self._held += 1
            reverted = bar.close >= range_mid
            expired = self._held >= self.params.expiry_bars
            if reverted or expired:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="back to range middle" if reverted else "expiry proxy reached",
                )
            return None

        adx_now = adx(bars, self.params.adx_period)[0][-1]
        dead_trend = adx_now <= self.params.max_adx
        near_range_low = bar.low <= lows[-1] * 1.002 and bar.close > lows[-1]

        if dead_trend and near_range_low:
            a = atr(bars, self.params.atr_period)[-1]
            self._long, self._held = True, 0
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(bar.close - self.params.stop_atr * a, 2),
                target=round(range_mid, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Condor regime: ADX {adx_now:.1f} dead, fading range low "
                f"{lows[-1]:.2f} toward {range_mid:.2f}",
            )
        return None
