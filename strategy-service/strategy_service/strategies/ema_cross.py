"""Strategy #1 — EMA Cross (trend following). The reference implementation that proves
the Strategy contract end-to-end.

Logic: fast EMA crossing above slow EMA opens a long bias (BUY); crossing back below
exits it (EXIT_LONG). Stop = recent swing low; target = entry + risk × reward ratio.
Suited to trending markets on 15m–daily; whipsaws in ranges (the ADX filter variant is
strategy #4)."""

from pydantic import BaseModel, Field

from strategy_service.indicators import ema
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class EmaCross(Strategy):
    metadata = StrategyMetadata(
        strategy_id="ema_cross",
        name="EMA Cross",
        category="trend",
        description="Fast/slow EMA crossover: long on golden cross, exit on death cross. "
        "Swing-low stop, fixed risk-reward target.",
        timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.42,
        risk_reward=2.0,
    )

    class Params(BaseModel):
        fast: int = Field(default=20, ge=2)
        slow: int = Field(default=50, ge=3)
        swing_lookback: int = Field(default=10, ge=2, description="bars for the swing-low stop")
        reward_ratio: float = Field(default=2.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.slow + 1

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None

        fast = ema(closes, self.params.fast)
        slow = ema(closes, self.params.slow)
        crossed_up = fast[-2] <= slow[-2] and fast[-1] > slow[-1]
        crossed_down = fast[-2] >= slow[-2] and fast[-1] < slow[-1]
        if not (crossed_up or crossed_down):
            return None

        bar = ctx.current
        if crossed_up:
            stop = min(b.low for b in ctx.bars[-self.params.swing_lookback :])
            risk = bar.close - stop
            return Signal(
                symbol=bar.symbol,
                timeframe=bar.timeframe,
                signal=SignalAction.BUY,
                confidence=0.6,
                stop_loss=round(stop, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2) if risk > 0 else None,
                source=self.metadata.strategy_id,
                timestamp=bar.ts,
                reasoning=f"EMA{self.params.fast} crossed above EMA{self.params.slow} "
                f"({fast[-1]:.2f} > {slow[-1]:.2f}) at {bar.close:.2f}",
            )
        return Signal(
            symbol=bar.symbol,
            timeframe=bar.timeframe,
            signal=SignalAction.EXIT_LONG,
            confidence=0.6,
            source=self.metadata.strategy_id,
            timestamp=bar.ts,
            reasoning=f"EMA{self.params.fast} crossed below EMA{self.params.slow} "
            f"({fast[-1]:.2f} < {slow[-1]:.2f}) at {bar.close:.2f}",
        )
