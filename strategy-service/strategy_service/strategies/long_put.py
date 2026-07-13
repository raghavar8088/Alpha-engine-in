"""Strategy #47 — Long Put. Bearish mirror of long_call: downside ignition for buying
puts, backtested as a defined-risk SHORT on the underlying until Phase 7 premium data.
The engine's short path (SELL entry / EXIT_SHORT) models the directional P&L."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema, rsi
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class LongPut(Strategy):
    metadata = StrategyMetadata(
        strategy_id="long_put",
        name="Long Put",
        category="options",
        description="Bearish ignition trigger for put buying: RSI breakdown + close "
        "below EMA with expanding range. Defined-risk short proxy on the underlying "
        "until Phase 7 premiums.",
        timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.INDEX_OPTION, AssetClass.EQUITY_OPTION, AssetClass.INDEX],
        suitable_market="high-volatility",
        expected_win_rate=0.38,
        risk_reward=2.5,
    )

    class Params(BaseModel):
        rsi_period: int = Field(default=14, ge=2)
        rsi_breakdown: float = Field(default=40.0, gt=0, lt=100)
        trend_ema: int = Field(default=21, ge=2)
        atr_period: int = Field(default=14, ge=2)
        risk_atr: float = Field(default=1.5, gt=0)
        reward_ratio: float = Field(default=2.5, gt=0)

    @property
    def warmup(self) -> int:
        return max(self.params.trend_ema, self.params.atr_period, self.params.rsi_period) + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        bar = ctx.current
        r = rsi(closes, self.params.rsi_period)
        trend = ema(closes, self.params.trend_ema)[-1]
        a = atr(ctx.bars, self.params.atr_period)

        breakdown = r[-2] >= self.params.rsi_breakdown > r[-1]
        expanding = a[-1] > a[-2]
        if breakdown and expanding and bar.close < trend:
            risk = self.params.risk_atr * a[-1]
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.SELL,
                confidence=0.5, stop_loss=round(bar.close + risk, 2),
                target=round(bar.close - risk * self.params.reward_ratio, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Put-buy trigger: RSI breakdown to {r[-1]:.1f} below EMA{self.params.trend_ema} "
                "with range expansion",
            )
        return None
