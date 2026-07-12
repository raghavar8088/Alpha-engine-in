"""Strategy #5 — Donchian Breakout (trend following). The turtle rule: buy a close above
the N-bar channel high, exit on a close below the M-bar channel low (M < N)."""

from pydantic import BaseModel, Field

from strategy_service.indicators import donchian
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata, register_strategy
from tradingai_shared.domain import AssetClass, Signal, SignalAction, Timeframe


@register_strategy
class DonchianBreakout(Strategy):
    metadata = StrategyMetadata(
        strategy_id="donchian_breakout",
        name="Donchian Breakout",
        category="trend",
        description="Turtle-style channel breakout: long above the N-bar high, exit "
        "below the M-bar low; the exit channel doubles as the trailing stop.",
        timeframes=[Timeframe.D1, Timeframe.W1],
        asset_classes=[AssetClass.EQUITY, AssetClass.INDEX, AssetClass.ETF],
        suitable_market="trending",
        expected_win_rate=0.38,
        risk_reward=2.5,
    )

    class Params(BaseModel):
        entry_period: int = Field(default=55, ge=5)
        exit_period: int = Field(default=20, ge=2)

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._long = False

    @property
    def warmup(self) -> int:
        return self.params.entry_period + 1

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        if len(ctx.bars) < self.warmup:
            return None
        bar = ctx.current
        entry_high = donchian(ctx.bars, self.params.entry_period)[0][-1]
        exit_low = donchian(ctx.bars, self.params.exit_period)[1][-1]

        if not self._long and bar.close > entry_high:
            self._long = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.BUY,
                confidence=0.55, stop_loss=round(exit_low, 2),
                source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close {bar.close:.2f} broke {self.params.entry_period}-bar high {entry_high:.2f}",
            )
        if self._long and bar.close < exit_low:
            self._long = False
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_LONG,
                confidence=0.55, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=f"Close {bar.close:.2f} broke {self.params.exit_period}-bar low {exit_low:.2f}",
            )
        return None
