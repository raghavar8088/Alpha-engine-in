"""Strategy #23 — VWAP Reversion (intraday). Price stretched far below session VWAP
with no trend break = snap-back to VWAP. Target IS the VWAP; flat by session close.
Needs real volume (equities)."""

from datetime import time, timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, session_vwap
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


@register_strategy
class VwapReversion(Strategy):
    metadata = StrategyMetadata(
        strategy_id="vwap_reversion",
        name="VWAP Reversion",
        category="mean_reversion",
        description="Buy stretches of k*ATR below session VWAP, target the VWAP "
        "itself, flat by close. Needs volume - equities on 15m bars.",
        timeframes=[Timeframe.M15],
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        suitable_market="range-bound",
        expected_win_rate=0.58,
        risk_reward=1.0,
    )

    class Params(BaseModel):
        stretch_atr: float = Field(default=2.0, gt=0, description="entry distance below VWAP in ATRs")
        atr_period: int = Field(default=14, ge=2)
        stop_atr: float = Field(default=1.5, gt=0, description="stop below entry in ATRs")

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < self.warmup or ctx.current.volume == 0:
            return None
        bar = ctx.current
        ist = bar.ts.astimezone(IST)
        vwap = session_vwap(ctx.bars, lambda b: b.ts.astimezone(IST).date())[-1]

        # session-close square off
        if self._long and ist.time() >= time(15, 0):
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning="Session close square-off",
            )

        a = atr(ctx.bars, self.params.atr_period)[-1]
        if not self._long:
            if ist.time() < time(10, 0) or ist.time() >= time(14, 30):
                return None  # skip the open chaos and the close
            stretch = vwap - bar.close
            if stretch >= self.params.stretch_atr * a:
                self._long = True
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.55, stop_loss=round(bar.close - self.params.stop_atr * a, 2),
                    target=round(vwap, 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"Stretched {stretch / a:.1f} ATR below session VWAP {vwap:.2f}",
                )
        elif bar.close >= vwap:
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Reverted to VWAP {vwap:.2f}",
            )
        return None
