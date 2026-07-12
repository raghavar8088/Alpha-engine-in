"""Strategy #37 — VWAP Scalping (intraday). In an up session (price above rising VWAP),
buy shallow pullbacks TO the VWAP and scalp the bounce. Tight ATR stop, quick target,
flat by close. Needs volume — equities on 15m."""

from datetime import time, timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, session_vwap
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


@register_strategy
class VwapScalping(Strategy):
    metadata = StrategyMetadata(
        strategy_id="vwap_scalping",
        name="VWAP Scalping",
        category="intraday",
        description="Buy shallow pullbacks to a rising VWAP in an up session; tight "
        "ATR stop, 1R quick target, flat by close. Equities on 15m.",
        timeframes=[Timeframe.M15, Timeframe.M5],
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.52,
        risk_reward=1.0,
    )

    class Params(BaseModel):
        touch_atr: float = Field(default=0.3, gt=0, description="how close to VWAP counts as a touch")
        stop_atr: float = Field(default=1.0, gt=0)
        reward_ratio: float = Field(default=1.0, gt=0)
        atr_period: int = Field(default=14, ge=2)
        max_trades_per_day: int = Field(default=2, ge=1)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._day = None
        self._trades_today = 0

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < self.warmup or ctx.current.volume == 0:
            return None
        bar = ctx.current
        ist = bar.ts.astimezone(IST)
        if ist.date() != self._day:
            self._day, self._trades_today, self._long = ist.date(), 0, False

        vwap = session_vwap(ctx.bars, lambda b: b.ts.astimezone(IST).date())

        if self._long and ist.time() >= time(15, 0):
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning="Session close square-off",
            )
        if self._long or self._trades_today >= self.params.max_trades_per_day:
            return None
        if not (time(10, 0) <= ist.time() < time(14, 30)):
            return None

        a = atr(ctx.bars, self.params.atr_period)[-1]
        rising = vwap[-1] > vwap[-2]
        touched = abs(bar.low - vwap[-1]) <= self.params.touch_atr * a
        closed_above = bar.close > vwap[-1]

        if rising and touched and closed_above:
            risk = self.params.stop_atr * a
            self._long = True
            self._trades_today += 1
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(bar.close - risk, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Pullback bounce off rising VWAP {vwap[-1]:.2f} ({ist:%H:%M} IST)",
            )
        return None
