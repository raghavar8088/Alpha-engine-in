"""Strategy #8 — VWAP Trend. Price holding above VWAP with rising VWAP = institutional
accumulation; ride it until price loses VWAP. Uses session VWAP on intraday bars and
rolling VWAP on daily. Requires real volume — index synthetic bars (volume 0) yield no
signals by design."""

from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, rolling_vwap, session_vwap
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))
INTRADAY = {Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1}


@register_strategy
class VwapTrend(Strategy):
    metadata = StrategyMetadata(
        strategy_id="vwap_trend",
        name="VWAP Trend",
        category="trend",
        description="Long when price crosses and holds above a rising VWAP (session "
        "VWAP intraday, rolling VWAP daily); exit on a close back below. Needs volume "
        "data - equities/ETFs, not synthetic index bars.",
        timeframes=[Timeframe.M15, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.45,
        risk_reward=1.6,
    )

    class Params(BaseModel):
        rolling_period: int = Field(default=20, ge=2, description="daily-timeframe VWAP window")
        confirm_bars: int = Field(default=2, ge=1)
        atr_period: int = Field(default=14, ge=2)
        atr_stop_mult: float = Field(default=2.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._above = 0

    @property
    def warmup(self) -> int:
        return max(self.params.rolling_period, self.params.atr_period) + 2

    def _vwap(self, ctx: StrategyContext) -> list[float]:
        if ctx.current.timeframe in INTRADAY:
            return session_vwap(ctx.bars, lambda b: b.ts.astimezone(IST).date())
        return rolling_vwap(ctx.bars, self.params.rolling_period)

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < self.warmup or ctx.current.volume == 0:
            return None
        bar = ctx.current
        vwap = self._vwap(ctx)

        if bar.close > vwap[-1]:
            self._above += 1
        else:
            self._above = 0

        if not self._long:
            rising = vwap[-1] > vwap[-2]
            if self._above >= self.params.confirm_bars and rising:
                a = atr(ctx.bars, self.params.atr_period)[-1]
                self._long = True
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.5, stop_loss=round(bar.close - a * self.params.atr_stop_mult, 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"{self._above} closes above rising VWAP {vwap[-1]:.2f}",
                )
        elif bar.close < vwap[-1]:
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close {bar.close:.2f} lost VWAP {vwap[-1]:.2f}",
            )
        return None
