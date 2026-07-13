"""Strategy #44 — VWAP Futures. Intraday futures bias off session VWAP with a
first-hour range filter: after 10:15 IST, trade in the VWAP-side direction on a range
break. Needs volume — validates on liquid equities until futures intraday bars land."""

from datetime import time, timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import session_vwap
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


@register_strategy
class VwapFutures(Strategy):
    metadata = StrategyMetadata(
        strategy_id="vwap_futures",
        name="VWAP Futures",
        category="futures",
        description="Intraday futures bias: after the first hour, break of the "
        "first-hour high while above session VWAP goes long; VWAP-cross exit, flat by "
        "close. Needs volume.",
        timeframes=[Timeframe.M15],
        asset_classes=[AssetClass.INDEX_FUTURE, AssetClass.EQUITY_FUTURE, AssetClass.EQUITY],
        suitable_market="trending",
        expected_win_rate=0.46,
        risk_reward=1.6,
    )

    class Params(BaseModel):
        reward_ratio: float = Field(default=1.6, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._day = None
        self._h1_high: float | None = None
        self._h1_low: float | None = None
        self._long = False
        self._done_today = False

    @property
    def warmup(self) -> int:
        return 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bar = ctx.current
        if bar.volume == 0:
            return None
        ist = bar.ts.astimezone(IST)

        if ist.date() != self._day:
            self._day = ist.date()
            self._h1_high = self._h1_low = None
            self._long = False
            self._done_today = False

        # accumulate the first hour's range (09:15-10:15)
        if ist.time() < time(10, 15):
            self._h1_high = bar.high if self._h1_high is None else max(self._h1_high, bar.high)
            self._h1_low = bar.low if self._h1_low is None else min(self._h1_low, bar.low)
            return None
        if self._h1_high is None or self._h1_low is None:
            return None

        vwap = session_vwap(ctx.bars, lambda b: b.ts.astimezone(IST).date())[-1]

        if self._long:
            eod = ist.time() >= time(15, 0)
            if eod or bar.close < vwap:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="session close" if eod else f"lost VWAP {vwap:.2f}",
                )
            return None

        if self._done_today or ist.hour >= 14:
            return None
        if bar.close > self._h1_high and bar.close > vwap:
            risk = bar.close - self._h1_low
            self._long = True
            self._done_today = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(self._h1_low, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2) if risk > 0 else None,
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"First-hour high break above VWAP ({ist:%H:%M} IST)",
            )
        return None
