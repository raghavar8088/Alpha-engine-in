"""Strategy #24 — ATR Reversion. Close stretched k*ATR below its EMA in a non-crashing
market reverts to the mean; the EMA is the target, timeout guards against catching
falling knives."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema, sma
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class AtrReversion(Strategy):
    metadata = StrategyMetadata(
        strategy_id="atr_reversion",
        name="ATR Reversion",
        category="mean_reversion",
        description="Buy k*ATR stretches below the EMA inside a long-term uptrend; "
        "target the EMA, timeout exit, ATR stop.",
        timeframes=[Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="range-bound",
        expected_win_rate=0.58,
        risk_reward=1.0,
    )

    class Params(BaseModel):
        mean_ema: int = Field(default=20, ge=2)
        stretch_atr: float = Field(default=2.5, gt=0)
        trend_sma: int = Field(default=200, ge=10)
        atr_period: int = Field(default=14, ge=2)
        stop_atr: float = Field(default=2.0, gt=0)
        max_hold_bars: int = Field(default=12, ge=1)

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
        mean = ema(closes, self.params.mean_ema)[-1]

        if self._long:
            self._held += 1
            if bar.close >= mean or self._held >= self.params.max_hold_bars:
                reason = "reverted to EMA" if bar.close >= mean else f"timeout {self.params.max_hold_bars} bars"
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"{reason} (close {bar.close:.2f}, EMA {mean:.2f})",
                )
            return None

        a = atr(ctx.bars, self.params.atr_period)[-1]
        trend = sma(closes, self.params.trend_sma)[-1]
        stretch = mean - bar.close
        if stretch >= self.params.stretch_atr * a and bar.close > trend:
            self._long, self._held = True, 0
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(bar.close - self.params.stop_atr * a, 2),
                target=round(mean, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Stretched {stretch / a:.1f} ATR below EMA{self.params.mean_ema} in uptrend",
            )
        return None
