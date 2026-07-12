"""Strategy #40 — Gap Fade (intraday). OVERSIZED opening gaps (beyond the momentum
band) statistically fill; fade a big gap-up short toward the prior close. Uses SELL
entries (short); flat by session close. The mirror of gap_momentum."""

from datetime import time, timedelta, timezone

from pydantic import BaseModel, Field

from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


@register_strategy
class GapFade(Strategy):
    metadata = StrategyMetadata(
        strategy_id="gap_fade",
        name="Gap Fade",
        category="intraday",
        description="Fade oversized opening gap-ups short toward the prior session "
        "close (gap fill); stop above the opening high, flat by close. 15m bars.",
        timeframes=[Timeframe.M15],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="range-bound",
        expected_win_rate=0.52,
        risk_reward=1.2,
    )

    class Params(BaseModel):
        min_gap_pct: float = Field(default=0.8, gt=0, description="fade only gaps larger than this")
        entry_deadline_hour_ist: int = Field(default=11, ge=10, le=14)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._day = None
        self._prev_session_close: float | None = None
        self._session_open: float | None = None
        self._session_first_high: float | None = None
        self._short = False
        self._done_today = False

    @property
    def warmup(self) -> int:
        return 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bar = ctx.current
        ist = bar.ts.astimezone(IST)

        if ist.date() != self._day:
            # previous bar was the prior session's last -> its close is the reference
            if len(ctx.bars) >= 2:
                self._prev_session_close = ctx.bars[-2].close
            self._day = ist.date()
            self._session_open = bar.open
            self._session_first_high = bar.high
            self._short = False
            self._done_today = False

        if self._short and ist.time() >= time(15, 0):
            self._short = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_SHORT,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning="Session close square-off",
            )
        if self._short or self._done_today:
            return None
        if self._prev_session_close is None or self._session_open is None:
            return None
        if ist.hour >= self.params.entry_deadline_hour_ist:
            return None

        gap_pct = (self._session_open - self._prev_session_close) / self._prev_session_close * 100
        # entry trigger: first bar that closes below its open (gap losing steam)
        if gap_pct >= self.params.min_gap_pct and bar.close < bar.open:
            self._short = True
            self._done_today = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.SELL,
                confidence=0.5,
                stop_loss=round(self._session_first_high, 2),
                target=round(self._prev_session_close, 2),  # the gap fill
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Fading {gap_pct:.1f}% gap-up toward prior close "
                f"{self._prev_session_close:.2f} ({ist:%H:%M} IST)",
            )
        return None
