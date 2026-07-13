"""Devansh Rai K2 (K1=ema_200_trend, K3=ema_5_close already coded) and Umar Punjabi L1
— the last 2 of the 76-strategy catalog."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema
from strategy_service.strategies.options_buying._base import OptionBuyStrategy, buy_meta
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe


@register_strategy
class Dr9x20Ema(OptionBuyStrategy):
    metadata = buy_meta(
        "dr_9_20_ema", "Devansh Rai: 9-20 EMA Strategy (K2)", "options_scalp",
        "Same 9/20 EMA cross mechanic as Stock Burner's B1, Devansh Rai's own framing.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=9, ge=2)
        slow: int = Field(default=20, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.slow + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        f = ema(closes, self.params.fast)
        s = ema(closes, self.params.slow)
        bar = ctx.current
        crossed_up = f[-2] <= s[-2] and f[-1] > s[-1]
        crossed_down = f[-2] >= s[-2] and f[-1] < s[-1]
        if crossed_up and bar.close > f[-1]:
            self.why = "9-EMA crossed above 20-EMA"
            return 1
        if crossed_down and bar.close < f[-1]:
            self.why = "9-EMA crossed below 20-EMA"
            return -1
        if (self._dir > 0 and f[-1] < s[-1]) or (self._dir < 0 and f[-1] > s[-1]):
            return 0
        return None


@register_strategy
class UpSniperScalp(OptionBuyStrategy):
    metadata = buy_meta(
        "up_sniper_scalp", "Umar Punjabi: 1-Minute Sniper Scalping (L1)", "options_scalp",
        "No 1-minute NIFTY history is backfilled on this platform; runs on 5m as the "
        "nearest available timeframe — the 'sniper' precision-entry idea (a sharp "
        "momentum burst off a tight base) adapted to the timeframe this platform has, "
        "not the literal 1-minute version.",
        Timeframe.M5, "high-volatility",
    )

    class Params(BaseModel):
        base_bars: int = Field(default=4, ge=2)
        atr_period: int = Field(default=10, ge=3)
        burst_mult: float = Field(default=1.4, gt=0)

    @property
    def warmup(self) -> int:
        return max(self.params.base_bars, self.params.atr_period) + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        base = ctx.bars[-self.params.base_bars - 1: -1]
        base_hi = max(b.high for b in base)
        base_lo = min(b.low for b in base)
        a = atr(ctx.bars, self.params.atr_period)[-1]
        tight = (base_hi - base_lo) < a * 1.2
        bar = ctx.current
        if not tight:
            return None if self._dir != 0 else 0
        if bar.close > base_hi and (bar.high - bar.low) > self.params.burst_mult * a:
            self.why = "sniper burst out of a tight base, up"
            return 1
        if bar.close < base_lo and (bar.high - bar.low) > self.params.burst_mult * a:
            self.why = "sniper burst out of a tight base, down"
            return -1
        return None
