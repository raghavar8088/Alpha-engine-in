"""Strategy #34 — Sector Rotation (benchmark-relative). Holds a symbol only while it is
in the LEADING phase of the rotation cycle: outperforming NIFTY on both the fast and
slow relative-strength windows (RRG-style quadrant logic on a single ratio series).
Runs per-symbol on sector proxies (sector ETFs / index constituents); portfolio-level
rotation across many sectors arrives with the risk engine's multi-strategy allocation."""

from pydantic import BaseModel, Field

from strategy_service.indicators import roc
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class SectorRotation(Strategy):
    requires_benchmark = True

    metadata = StrategyMetadata(
        strategy_id="sector_rotation",
        name="Sector Rotation",
        category="swing",
        description="RRG-style leading-quadrant filter on the price/NIFTY ratio: long "
        "only while both fast and slow relative momentum are positive (leading), exit "
        "when the fast leg rolls over (weakening).",
        timeframes=[Timeframe.D1, Timeframe.W1],
        asset_classes=[AssetClass.ETF, AssetClass.EQUITY],
        suitable_market="trending",
        expected_win_rate=0.46,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        fast_window: int = Field(default=10, ge=2)
        slow_window: int = Field(default=40, ge=5)
        stop_pct: float = Field(default=7.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return self.params.slow_window + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        bench = ctx.benchmark_closes()
        if bench is None:
            return None
        bar = ctx.current
        ratio = [c / b for c, b in zip(closes, bench)]
        fast = roc(ratio, self.params.fast_window)[-1]
        slow = roc(ratio, self.params.slow_window)[-1]

        if not self._long:
            if fast > 0 and slow > 0:  # leading quadrant
                self._long = True
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.55,
                    stop_loss=round(bar.close * (1 - self.params.stop_pct / 100), 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"Leading quadrant: RS momentum fast {fast:.2f}% / slow {slow:.2f}% vs NIFTY",
                )
        elif fast < 0:  # weakening
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Rotation weakening: fast RS momentum {fast:.2f}%",
            )
        return None
