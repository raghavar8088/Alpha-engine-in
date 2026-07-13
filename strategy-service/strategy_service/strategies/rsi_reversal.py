"""Strategy #21 — RSI Reversal (mean reversion). Short-period RSI deeply oversold
inside a long-term uptrend (SMA filter) = buy the dip; exit when RSI normalizes or
after a max-hold timeout. Time-based exit is essential for mean reversion — a dip that
doesn't bounce quickly is a downtrend."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, rsi, sma
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class RsiReversal(Strategy):
    metadata = StrategyMetadata(
        strategy_id="rsi_reversal",
        name="RSI Reversal",
        category="mean_reversion",
        description="Buy deep RSI(2) oversold dips inside an SMA200 uptrend; exit on "
        "RSI normalization or max-hold timeout. ATR stop.",
        timeframes=[Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="range-bound",
        expected_win_rate=0.62,
        risk_reward=0.9,
    )

    class Params(BaseModel):
        rsi_period: int = Field(default=2, ge=2)
        oversold: float = Field(default=10.0, gt=0, lt=50)
        exit_rsi: float = Field(default=60.0, gt=50, lt=100)
        trend_sma: int = Field(default=200, ge=10)
        max_hold_bars: int = Field(default=10, ge=1)
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
        r = rsi(closes, self.params.rsi_period)[-1]

        if self._long:
            self._held += 1
            if r > self.params.exit_rsi or self._held >= self.params.max_hold_bars:
                reason = "RSI normalized" if r > self.params.exit_rsi else f"max hold {self.params.max_hold_bars} bars"
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.6, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"{reason} (RSI {r:.1f})",
                )
            return None

        trend = sma(closes, self.params.trend_sma)[-1]
        if r < self.params.oversold and bar.close > trend:
            a = atr(ctx.bars, self.params.atr_period)[-1]
            self._long, self._held = True, 0
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.6, stop_loss=round(bar.close - a * self.params.atr_stop_mult, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"RSI{self.params.rsi_period} oversold at {r:.1f} in uptrend "
                f"(close {bar.close:.2f} > SMA{self.params.trend_sma} {trend:.2f})",
            )
        return None
