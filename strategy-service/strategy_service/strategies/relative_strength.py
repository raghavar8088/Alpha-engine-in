"""Strategy #15 — Relative Strength (vs NIFTY benchmark). Long the symbol only while it
OUTPERFORMS the index over the ratio-momentum window and its own trend is up. The
first benchmark-aware strategy (requires_benchmark=True — runners feed NIFTY closes)."""

from pydantic import BaseModel, Field

from strategy_service.indicators import ema, roc
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class RelativeStrength(Strategy):
    requires_benchmark = True

    metadata = StrategyMetadata(
        strategy_id="relative_strength",
        name="Relative Strength",
        category="momentum",
        description="Long while the symbol's price/NIFTY ratio momentum is positive "
        "and its own EMA trend is up; exit when relative strength turns negative. "
        "Needs a benchmark series (not applicable to NIFTY itself).",
        timeframes=[Timeframe.D1, Timeframe.W1],
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.44,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        rs_period: int = Field(default=20, ge=2, description="ratio momentum window")
        trend_ema: int = Field(default=50, ge=2)
        atr_stop_pct: float = Field(default=5.0, gt=0, description="stop distance as % of entry")

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return max(self.params.rs_period, self.params.trend_ema) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        bench = ctx.benchmark_closes()
        if bench is None:
            return None  # no aligned benchmark -> no signal, never a guess
        bar = ctx.current
        ratio = [c / b for c, b in zip(closes, bench)]
        rs_mom = roc(ratio, self.params.rs_period)
        trend = ema(closes, self.params.trend_ema)[-1]

        if not self._long:
            if rs_mom[-2] <= 0 < rs_mom[-1] and bar.close > trend:
                self._long = True
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.55,
                    stop_loss=round(bar.close * (1 - self.params.atr_stop_pct / 100), 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"RS vs NIFTY turned positive ({rs_mom[-1]:.2f}%) in uptrend",
                )
        elif rs_mom[-1] < 0:
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"RS vs NIFTY turned negative ({rs_mom[-1]:.2f}%)",
            )
        return None
