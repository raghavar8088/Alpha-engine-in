"""Strategy #35 — Earnings Momentum (PEAD — post-earnings announcement drift). The true
earnings calendar is a research-service feed (Phase 6); until it lands, an announcement
is detected by its tape signature — an outsized gap WITH extreme volume — and the drift
is ridden with a trailing exit. Documented proxy, equities only."""

from pydantic import BaseModel, Field

from strategy_service.indicators import zscore
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class EarningsMomentum(Strategy):
    metadata = StrategyMetadata(
        strategy_id="earnings_momentum",
        name="Earnings Momentum",
        category="swing",
        description="Post-earnings drift: outsized gap + extreme volume (announcement "
        "signature; calendar feed wires in with the research service) ridden for the "
        "drift window with a trailing stop. Equities only.",
        timeframes=[Timeframe.D1],
        asset_classes=[AssetClass.EQUITY],
        suitable_market="high-volatility",
        expected_win_rate=0.46,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        min_gap_pct: float = Field(default=3.0, gt=0)
        volume_z: float = Field(default=3.0, gt=0, description="announcement-day volume z-score")
        volume_window: int = Field(default=50, ge=10)
        drift_bars: int = Field(default=15, ge=3, description="max drift-hold window")
        trail_lookback: int = Field(default=5, ge=2)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._held = 0

    @property
    def warmup(self) -> int:
        return self.params.volume_window + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup or ctx.current.volume == 0:
            return None
        bar, prev = bars[-1], bars[-2]

        if self._long:
            self._held += 1
            trail = min(b.low for b in bars[-self.params.trail_lookback :])
            timed_out = self._held >= self.params.drift_bars
            if bar.close < trail or timed_out:
                self._long = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                    confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning="drift window over" if timed_out else "trailing low broken",
                )
            return None

        gap_pct = (bar.open - prev.close) / prev.close * 100
        vol_z = zscore([float(b.volume) for b in bars], self.params.volume_window)[-1]
        held_into_close = bar.close >= bar.open

        if gap_pct >= self.params.min_gap_pct and vol_z >= self.params.volume_z and held_into_close:
            self._long, self._held = True, 0
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(prev.close, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Announcement signature: gap {gap_pct:.1f}% on volume z={vol_z:.1f}, "
                "riding post-announcement drift",
            )
        return None
