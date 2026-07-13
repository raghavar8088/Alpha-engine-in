"""Strategy #19/#36 — Opening Range Breakout (intraday, 15m bars). The first 15-minute
bar of the NSE session (09:15-09:30 IST) defines the range; a close above its high
before the entry cutoff goes long with the range low as stop. Always flat by the last
bar of the session — no overnight risk.

Bars are stored in UTC; NSE session times are converted via the fixed IST offset
(+05:30, no DST)."""

from datetime import time, timedelta, timezone

from pydantic import BaseModel, Field

from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


@register_strategy
class OpeningRangeBreakout(Strategy):
    metadata = StrategyMetadata(
        strategy_id="opening_range_breakout",
        name="Opening Range Breakout",
        category="intraday",
        description="First-15m-bar range; long on a close above the range high before "
        "the cutoff, stop at range low, R-multiple target, flat by session close.",
        timeframes=[Timeframe.M15],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="high-volatility",
        expected_win_rate=0.45,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        entry_cutoff_hour_ist: int = Field(default=13, ge=10, le=15)
        reward_ratio: float = Field(default=1.8, gt=0)
        min_range_pct: float = Field(default=0.15, ge=0, description="skip days with a dead opening range")

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._day = None
        self._or_high: float | None = None
        self._or_low: float | None = None
        self._long = False
        self._done_today = False

    @property
    def warmup(self) -> int:
        return 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bar = ctx.current
        ist = bar.ts.astimezone(IST)

        if ist.date() != self._day:  # new session
            self._day = ist.date()
            self._or_high = self._or_low = None
            self._long = False
            self._done_today = False

        # First bar of the session defines the opening range
        if time(9, 0) <= ist.time() < time(9, 30):
            self._or_high, self._or_low = bar.high, bar.low
            return None
        if self._or_high is None or self._or_low is None:
            return None

        # Square off on the session's last bar (15:15 IST bar closes the day)
        if ist.time() >= time(15, 0):
            if self._long:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.6, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="Session close square-off",
                )
            return None

        if self._long or self._done_today:
            return None
        if ist.hour >= self.params.entry_cutoff_hour_ist:
            return None

        range_pct = (self._or_high - self._or_low) / bar.close * 100
        if range_pct < self.params.min_range_pct:
            return None

        if bar.close > self._or_high:
            risk = bar.close - self._or_low
            self._long = True
            self._done_today = True  # one attempt per session
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(self._or_low, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close {bar.close:.2f} above opening range high {self._or_high:.2f} "
                f"({ist:%H:%M} IST)",
            )
        return None
