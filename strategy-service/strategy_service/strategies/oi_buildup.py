"""Strategy #45 — OI Build-Up. Long build-up = price rising WITH open interest rising
(fresh longs, not short covering). Requires bars with OI — i.e. futures bars; emits
nothing on cash/index series, so validation reports insufficient data until the
futures backfill lands (backfill.py already requests OI for derivative instruments)."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class OiBuildup(Strategy):
    metadata = StrategyMetadata(
        strategy_id="oi_buildup",
        name="OI Build-Up",
        category="futures",
        description="Long build-up detector: price +X% with OI +Y% over the window "
        "(fresh long positioning); exits on OI unwind. Requires futures bars with "
        "open interest.",
        timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.INDEX_FUTURE, AssetClass.EQUITY_FUTURE],
        suitable_market="trending",
        expected_win_rate=0.45,
        risk_reward=1.8,
    )

    class Params(BaseModel):
        window: int = Field(default=5, ge=2)
        min_price_pct: float = Field(default=0.5, gt=0)
        min_oi_pct: float = Field(default=3.0, gt=0)
        atr_period: int = Field(default=14, ge=2)
        stop_atr: float = Field(default=2.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return max(self.params.window, self.params.atr_period) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bars = ctx.bars
        if len(bars) < self.warmup:
            return None
        bar = ctx.current
        window = bars[-self.params.window - 1 :]
        if any(b.oi is None or b.oi == 0 for b in window):
            return None  # no OI data on this series - futures bars required

        price_chg = (bar.close - window[0].close) / window[0].close * 100
        oi_chg = (bar.oi - window[0].oi) / window[0].oi * 100

        if not self._long:
            if price_chg >= self.params.min_price_pct and oi_chg >= self.params.min_oi_pct:
                a = atr(bars, self.params.atr_period)[-1]
                self._long = True
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.55, stop_loss=round(bar.close - self.params.stop_atr * a, 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"Long build-up: price +{price_chg:.1f}% with OI +{oi_chg:.1f}%",
                )
        elif oi_chg < 0 and price_chg < 0:  # long unwinding
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Long unwind: price {price_chg:.1f}% with OI {oi_chg:.1f}%",
            )
        return None
