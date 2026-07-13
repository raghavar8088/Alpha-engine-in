"""Strategy #22 — Bollinger Reversion (mean reversion). Close below the lower band
inside a long-term uptrend = overextension; exit at the middle band (the mean it
reverts to). ATR stop, max-hold timeout."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, sma, stdev
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class BollingerReversion(Strategy):
    metadata = StrategyMetadata(
        strategy_id="bollinger_reversion",
        name="Bollinger Reversion",
        category="mean_reversion",
        description="Buy closes below the lower Bollinger band in an uptrend; exit at "
        "the middle band or on timeout. ATR stop.",
        timeframes=[Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="range-bound",
        expected_win_rate=0.60,
        risk_reward=1.0,
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=3)
        band_mult: float = Field(default=2.0, gt=0)
        trend_sma: int = Field(default=200, ge=10)
        max_hold_bars: int = Field(default=15, ge=1)
        atr_period: int = Field(default=14, ge=2)
        atr_stop_mult: float = Field(default=2.5, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._held = 0
        self._long = False

    @property
    def warmup(self) -> int:
        return self.params.trend_sma + 1

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        bar = ctx.current
        mid = sma(closes, self.params.period)[-1]

        if self._long:
            self._held += 1
            if bar.close >= mid or self._held >= self.params.max_hold_bars:
                reason = "reached middle band" if bar.close >= mid else f"max hold {self.params.max_hold_bars} bars"
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.6, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"{reason} (close {bar.close:.2f}, mid {mid:.2f})",
                )
            return None

        sd = stdev(closes, self.params.period)[-1]
        lower = mid - self.params.band_mult * sd
        trend = sma(closes, self.params.trend_sma)[-1]
        if bar.close < lower and bar.close > trend:
            a = atr(ctx.bars, self.params.atr_period)[-1]
            self._long, self._held = True, 0
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.6, stop_loss=round(bar.close - a * self.params.atr_stop_mult, 2),
                target=round(mid, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close {bar.close:.2f} below lower band {lower:.2f} in uptrend",
            )
        return None
