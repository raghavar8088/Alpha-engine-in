"""Strategy #18 — Gap Momentum (gap-and-go, daily). An opening gap up beyond the
threshold that HOLDS (close above open) signals continuation; ride with a gap-fill
stop. Distinct from gap_fade, which bets the opposite on oversized gaps."""

from pydantic import BaseModel, Field

from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class GapMomentum(Strategy):
    metadata = StrategyMetadata(
        strategy_id="gap_momentum",
        name="Gap Momentum",
        category="momentum",
        description="Daily gap-up in the momentum band that holds into the close; "
        "stop at gap fill (prior close), R-multiple target, time-boxed hold.",
        timeframes=[Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF, AssetClass.INDEX],
        suitable_market="high-volatility",
        expected_win_rate=0.45,
        risk_reward=1.5,
    )

    class Params(BaseModel):
        min_gap_pct: float = Field(default=1.0, gt=0)
        max_gap_pct: float = Field(default=4.0, gt=0, description="beyond this it's exhaustion, not momentum")
        reward_ratio: float = Field(default=1.5, gt=0)
        max_hold_bars: int = Field(default=5, ge=1)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._held = 0

    @property
    def warmup(self) -> int:
        return 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < 2:
            return None
        bar, prev = ctx.bars[-1], ctx.bars[-2]

        if self._long:
            self._held += 1
            if self._held >= self.params.max_hold_bars:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"time-boxed exit after {self._held} bars",
                )
            return None

        gap_pct = (bar.open - prev.close) / prev.close * 100
        held_gap = bar.close > bar.open  # gap did not fade intraday
        if self.params.min_gap_pct <= gap_pct <= self.params.max_gap_pct and held_gap:
            risk = bar.close - prev.close
            self._long, self._held = True, 0
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(prev.close, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2) if risk > 0 else None,
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Gap up {gap_pct:.1f}% held into close ({bar.close:.2f} > open {bar.open:.2f})",
            )
        return None
