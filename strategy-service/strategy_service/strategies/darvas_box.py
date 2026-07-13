"""Strategy #26 — Darvas Box (swing). A box forms when the N-bar high holds for
`settle_bars` bars without a new high; a close above the box top buys, the box bottom
is the stop."""

from pydantic import BaseModel, Field

from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class DarvasBox(Strategy):
    metadata = StrategyMetadata(
        strategy_id="darvas_box",
        name="Darvas Box",
        category="swing",
        description="Classic box theory: ceiling that holds for k bars defines the "
        "box; buy the close above it with the box floor as stop.",
        timeframes=[Timeframe.D1, Timeframe.W1],
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.42,
        risk_reward=2.2,
    )

    class Params(BaseModel):
        settle_bars: int = Field(default=3, ge=2, description="bars the ceiling must hold")
        max_box_bars: int = Field(default=40, ge=5, description="stale boxes are discarded")
        reward_ratio: float = Field(default=2.2, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._top: float | None = None
        self._bottom: float | None = None
        self._age = 0
        self._long = False

    @property
    def warmup(self) -> int:
        return self.params.settle_bars + 3

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup:
            return None
        bar = ctx.current
        settle = self.params.settle_bars

        if self._long:
            if self._bottom is not None and bar.close < self._bottom:
                self._long, self._top, self._bottom = False, None, None
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="Close fell through the box floor",
                )
            return None

        # Box detection: the high `settle` bars ago is the ceiling if nothing since exceeded it
        candidate = bars[-settle - 1].high
        ceiling_holds = all(b.high <= candidate for b in bars[-settle:])
        if ceiling_holds and self._top != candidate:
            self._top = candidate
            self._bottom = min(b.low for b in bars[-settle - 1 :])
            self._age = 0
        elif self._top is not None:
            self._age += 1
            if self._age > self.params.max_box_bars:
                self._top = self._bottom = None

        if self._top is not None and self._bottom is not None and bar.close > self._top:
            risk = bar.close - self._bottom
            self._long = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(self._bottom, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2) if risk > 0 else None,
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close {bar.close:.2f} broke Darvas box top {self._top:.2f} "
                f"(floor {self._bottom:.2f})",
            )
        return None
