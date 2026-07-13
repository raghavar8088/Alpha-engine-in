"""Strategy #46 — Long Call. Directional bullish trigger for buying calls: momentum
ignition + volatility expansion on the underlying. Until options-service (Phase 7)
prices real premiums/Greeks, backtests run the signal as a defined-risk long on the
underlying (stop = premium-at-risk proxy)."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema, rsi
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class LongCall(Strategy):
    metadata = StrategyMetadata(
        strategy_id="long_call",
        name="Long Call",
        category="options",
        description="Bullish ignition trigger for call buying: RSI thrust + close above "
        "EMA with expanding range. Defined-risk proxy on the underlying until Phase 7 "
        "wires real option premiums/Greeks.",
        timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.D1],
        asset_classes=[AssetClass.INDEX_OPTION, AssetClass.EQUITY_OPTION, AssetClass.INDEX],
        suitable_market="trending",
        expected_win_rate=0.40,
        risk_reward=2.5,
    )

    class Params(BaseModel):
        rsi_period: int = Field(default=14, ge=2)
        rsi_thrust: float = Field(default=60.0, gt=0, lt=100)
        trend_ema: int = Field(default=21, ge=2)
        atr_period: int = Field(default=14, ge=2)
        risk_atr: float = Field(default=1.5, gt=0, description="premium-at-risk proxy")
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

        thrust = r[-2] <= self.params.rsi_thrust < r[-1]
        expanding = a[-1] > a[-2]
        if thrust and expanding and bar.close > trend:
            risk = self.params.risk_atr * a[-1]
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.5, stop_loss=round(bar.close - risk, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Call-buy trigger: RSI thrust to {r[-1]:.1f} above EMA{self.params.trend_ema} "
                "with range expansion",
            )
        return None
