"""Strategy #48 — Covered Call. Own the underlying in a calm uptrend and harvest call
premium against it. The underlying leg (steady-uptrend entry/exit) backtests now; the
premium-income leg needs Phase 7 option pricing, so realized backtest P&L is the stock
leg only — documented, and conservative (premium income would only add)."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema, stdev
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class CoveredCall(Strategy):
    metadata = StrategyMetadata(
        strategy_id="covered_call",
        name="Covered Call",
        category="options",
        description="Hold quality underlying in a LOW-volatility uptrend (the regime "
        "where short calls decay best); exit when trend or calm breaks. Premium leg "
        "wires in with Phase 7 - backtest P&L is the stock leg only (conservative).",
        timeframes=[Timeframe.D1, Timeframe.W1],
        asset_classes=[AssetClass.EQUITY_OPTION, AssetClass.EQUITY],
        suitable_market="range-bound",
        expected_win_rate=0.55,
        risk_reward=1.2,
    )

    class Params(BaseModel):
        trend_ema: int = Field(default=50, ge=2)
        vol_window: int = Field(default=20, ge=5)
        max_vol_pct: float = Field(default=1.6, gt=0, description="daily stdev as % of price")
        atr_period: int = Field(default=14, ge=2)
        stop_atr: float = Field(default=3.0, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return max(self.params.trend_ema, self.params.vol_window) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        bar = ctx.current
        trend = ema(closes, self.params.trend_ema)
        vol_pct = stdev(closes, self.params.vol_window)[-1] / bar.close * 100
        calm = vol_pct <= self.params.max_vol_pct

        if not self._long:
            if calm and bar.close > trend[-1] and trend[-1] > trend[-2]:
                a = atr(ctx.bars, self.params.atr_period)[-1]
                self._long = True
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                    confidence=0.55, stop_loss=round(bar.close - self.params.stop_atr * a, 2),
                    source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=f"Covered-call regime: calm uptrend (vol {vol_pct:.1f}% <= "
                    f"{self.params.max_vol_pct}%), write calls against the holding",
                )
        elif bar.close < trend[-1] or not calm:
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning="trend broken" if bar.close < trend[-1] else f"volatility woke up ({vol_pct:.1f}%)",
            )
        return None
