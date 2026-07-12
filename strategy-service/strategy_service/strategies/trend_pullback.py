"""Strategy #39 — Trend Pullback (intraday). In an established intraday uptrend
(EMA20 > EMA50, both rising), buy the first close back above EMA20 after a dip below
it. Flat by session close."""

from datetime import time, timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


@register_strategy
class TrendPullback(Strategy):
    metadata = StrategyMetadata(
        strategy_id="trend_pullback",
        name="Trend Pullback",
        category="intraday",
        description="Intraday EMA20/EMA50 uptrend: buy the reclaim of EMA20 after a "
        "dip below it; ATR stop, 1.5R target, flat by close.",
        timeframes=[Timeframe.M15, Timeframe.M5],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.50,
        risk_reward=1.5,
    )

    class Params(BaseModel):
        fast: int = Field(default=20, ge=2)
        slow: int = Field(default=50, ge=3)
        atr_period: int = Field(default=14, ge=2)
        stop_atr: float = Field(default=1.2, gt=0)
        reward_ratio: float = Field(default=1.5, gt=0)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False
        self._dipped = False

    @property
    def warmup(self) -> int:
        return self.params.slow + 2

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        closes = ctx.closes
        if len(closes) < self.warmup:
            return None
        bar = ctx.current
        ist = bar.ts.astimezone(IST)
        fast = ema(closes, self.params.fast)
        slow = ema(closes, self.params.slow)

        if self._long and ist.time() >= time(15, 0):
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.5, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning="Session close square-off",
            )
        if self._long:
            return None

        uptrend = fast[-1] > slow[-1] and fast[-1] > fast[-2] and slow[-1] > slow[-2]
        if not uptrend:
            self._dipped = False
            return None

        if bar.low < fast[-1] and bar.close < fast[-1]:
            self._dipped = True  # pullback in progress
            return None

        reclaim = self._dipped and bar.close > fast[-1]
        if reclaim and time(9, 45) <= ist.time() < time(14, 30):
            a = atr(ctx.bars, self.params.atr_period)[-1]
            risk = self.params.stop_atr * a
            self._long, self._dipped = True, False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(bar.close - risk, 2),
                target=round(bar.close + risk * self.params.reward_ratio, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"EMA{self.params.fast} reclaim after pullback in intraday uptrend",
            )
        return None
