"""Strategy #29 — Flag Pattern (swing). Sharp impulse leg (pole) followed by a shallow,
tight consolidation (flag) that breaks upward: continuation entry with a measured-move
target."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, roc
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class FlagPattern(Strategy):
    metadata = StrategyMetadata(
        strategy_id="flag_pattern",
        name="Flag Pattern",
        category="swing",
        description="Pole (sharp N-bar rally) + flag (tight consolidation with shallow "
        "drift) breaking up; measured-move target, flag low stop.",
        timeframes=[Timeframe.D1, Timeframe.H1],
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.45,
        risk_reward=2.0,
    )

    class Params(BaseModel):
        pole_bars: int = Field(default=10, ge=3)
        pole_min_pct: float = Field(default=8.0, gt=0, description="impulse strength over pole_bars")
        flag_bars: int = Field(default=5, ge=3)
        flag_max_retrace: float = Field(default=0.5, gt=0, le=1, description="flag depth vs pole")

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return self.params.pole_bars + self.params.flag_bars + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup:
            return None
        bar = ctx.current
        p, f = self.params.pole_bars, self.params.flag_bars

        if self._long:
            flag_low = min(b.low for b in bars[-f - 1 : -1])
            if bar.close < flag_low:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="Close under the flag low - pattern failed",
                )
            return None

        # Pole: strong rally ending f bars ago
        pole = bars[-(p + f) : -f]
        pole_gain = (pole[-1].close - pole[0].close) / pole[0].close * 100
        if pole_gain < self.params.pole_min_pct:
            return None
        pole_height = pole[-1].close - pole[0].close

        # Flag: last f bars stay tight and shallow
        flag = bars[-f:]
        flag_high = max(b.high for b in flag)
        flag_low = min(b.low for b in flag)
        retrace = (pole[-1].close - flag_low) / pole_height if pole_height > 0 else 1.0
        if retrace > self.params.flag_max_retrace:
            return None

        if bar.close > flag_high and bar.ts == flag[-1].ts:
            self._long = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(flag_low, 2),
                target=round(bar.close + pole_height, 2),  # measured move
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Flag break after {pole_gain:.1f}% pole; measured move {pole_height:.1f}",
            )
        return None
