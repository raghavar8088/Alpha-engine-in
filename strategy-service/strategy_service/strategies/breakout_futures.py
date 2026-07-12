"""Strategy #43 — Breakout Futures. N-bar range breakout with a range-contraction
filter (breakouts from compression carry further on leveraged instruments). Validates
on the underlying series until continuous futures bars are backfilled."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, donchian
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class BreakoutFutures(Strategy):
    metadata = StrategyMetadata(
        strategy_id="breakout_futures",
        name="Breakout Futures",
        category="futures",
        description="Compression-filtered Donchian breakout for futures: enter only "
        "when current ATR is below its own average (coiled spring), ride with a "
        "channel trail.",
        timeframes=[Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.INDEX_FUTURE, AssetClass.EQUITY_FUTURE, AssetClass.INDEX],
        suitable_market="high-volatility",
        expected_win_rate=0.40,
        risk_reward=2.2,
    )

    class Params(BaseModel):
        entry_period: int = Field(default=34, ge=5)
        exit_period: int = Field(default=13, ge=2)
        atr_period: int = Field(default=14, ge=2)
        compression: float = Field(default=0.85, gt=0, le=1, description="ATR now vs its 50-bar mean")

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return max(self.params.entry_period, 50) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup:
            return None
        bar = ctx.current
        entry_high = donchian(bars, self.params.entry_period)[0][-1]
        exit_low = donchian(bars, self.params.exit_period)[1][-1]

        if self._long:
            if bar.close < exit_low:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"Channel trail: close below {self.params.exit_period}-bar low",
                )
            return None

        a = atr(bars, self.params.atr_period)
        atr_mean = sum(a[-50:]) / 50
        compressed = a[-1] <= self.params.compression * atr_mean

        if compressed and bar.close > entry_high:
            self._long = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(exit_low, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Compressed-range breakout (ATR {a[-1]:.1f} vs mean {atr_mean:.1f}) "
                f"above {entry_high:.2f}",
            )
        return None
