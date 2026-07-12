"""Strategy #25 — Keltner Reversion. Close below the lower Keltner (ATR) band in an
uptrend reverts to the middle EMA. ATR bands adapt to volatility better than fixed-σ
Bollinger — the two reversions complement each other."""

from pydantic import BaseModel, Field

from strategy_service.indicators import keltner, sma
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class KeltnerReversion(Strategy):
    metadata = StrategyMetadata(
        strategy_id="keltner_reversion",
        name="Keltner Reversion",
        category="mean_reversion",
        description="Buy closes below the lower Keltner band in a long-term uptrend; "
        "exit at the middle EMA or on timeout.",
        timeframes=[Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="range-bound",
        expected_win_rate=0.58,
        risk_reward=1.0,
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=2)
        band_mult: float = Field(default=2.0, gt=0)
        trend_sma: int = Field(default=200, ge=10)
        stop_band_mult: float = Field(default=3.5, gt=0, description="stop = this many ATRs below mid")
        max_hold_bars: int = Field(default=15, ge=1)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._held = 0

    @property
    def warmup(self) -> int:
        return self.params.trend_sma + 1

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        bar = ctx.current
        upper, mid, lower = keltner(ctx.bars, self.params.period, self.params.band_mult)

        if self._long:
            self._held += 1
            if bar.close >= mid[-1] or self._held >= self.params.max_hold_bars:
                reason = "reached middle band" if bar.close >= mid[-1] else "timeout"
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"{reason} (close {bar.close:.2f}, mid {mid[-1]:.2f})",
                )
            return None

        trend = sma(closes, self.params.trend_sma)[-1]
        if bar.close < lower[-1] and bar.close > trend:
            band_width = (mid[-1] - lower[-1]) / self.params.band_mult  # one ATR
            self._long, self._held = True, 0
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55,
                stop_loss=round(mid[-1] - self.params.stop_band_mult * band_width, 2),
                target=round(mid[-1], 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close {bar.close:.2f} below lower Keltner {lower[-1]:.2f} in uptrend",
            )
        return None
