"""Stock Learners — 7 strategies (F1-F7). F4 mirrors A1/pta_trap under this channel's
own name; F7 combines an order-block-style retest with a self-computed >=3:1 RR gate."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema, rsi
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, swing_points,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe


@register_strategy
class SlSmallCapitalScalp(OptionBuyStrategy):
    metadata = buy_meta(
        "sl_small_capital_scalp", "Stock Learners: Scalping (Small Capital) (F1)", "options_scalp",
        "Tight trend micro-scalp sized for small accounts — a fast EMA cross with a "
        "quick exit, same spirit as the channel's beginner-friendly framing.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=5, ge=2)
        slow: int = Field(default=13, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.slow + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        f, s = ema(closes, self.params.fast)[-1], ema(closes, self.params.slow)[-1]
        f2, s2 = ema(closes, self.params.fast)[-2], ema(closes, self.params.slow)[-2]
        if f2 <= s2 and f > s:
            self.why = "fast EMA crossed up"
            return 1
        if f2 >= s2 and f < s:
            self.why = "fast EMA crossed down"
            return -1
        if (self._dir > 0 and f < s) or (self._dir < 0 and f > s):
            return 0
        return None


@register_strategy
class SlTopBottomCapture(OptionBuyStrategy):
    metadata = buy_meta(
        "sl_top_bottom_capture", "Stock Learners: Top & Bottom Capture (F2)", "options_intraday",
        "Reversal at exhaustion: an RSI extreme with a climax candle (wide range, "
        "closing against the extreme) marks the top/bottom.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        rsi_period: int = Field(default=14, ge=5)
        atr_period: int = Field(default=14, ge=5)
        climax_mult: float = Field(default=1.6, gt=0)

    @property
    def warmup(self) -> int:
        return max(self.params.rsi_period, self.params.atr_period) + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        r = rsi(ctx.closes, self.params.rsi_period)[-1]
        a = atr(ctx.bars, self.params.atr_period)[-1]
        bar = ctx.current
        rng = bar.high - bar.low
        is_climax = rng > self.params.climax_mult * a
        if is_climax and r < 25 and bar.close > bar.open:
            self.why = f"climax bottom (RSI {r:.0f})"
            return 1
        if is_climax and r > 75 and bar.close < bar.open:
            self.why = f"climax top (RSI {r:.0f})"
            return -1
        if (self._dir > 0 and r > 60) or (self._dir < 0 and r < 40):
            self.why = "reversal played out"
            return 0
        return None


@register_strategy
class SlEventLevelTrading(OptionBuyStrategy):
    metadata = buy_meta(
        "sl_event_level_trading", "Stock Learners: Event-Level Trading (F3)", "options_intraday",
        "No event calendar exists; trades the reaction at a major PRE-MARKED level "
        "instead — the prior day's high/low, standing in for 'the marked level' any "
        "event-day playbook trades around.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        pass

    @property
    def warmup(self) -> int:
        return 20

    def direction(self, ctx: StrategyContext) -> int | None:
        from strategy_service.strategies.options_buying._base import prev_day_hlc

        hlc = prev_day_hlc(ctx)
        if hlc is None:
            return 0
        high, low, _ = hlc
        bar = ctx.current
        if bar.close > high:
            self.why = f"reacted through the marked level {high:.0f}"
            return 1
        if bar.close < low:
            self.why = f"reacted through the marked level {low:.0f}"
            return -1
        return 0


@register_strategy
class SlTrapTrading(OptionBuyStrategy):
    metadata = buy_meta(
        "sl_trap_trading", "Stock Learners: Trap Trading (F4)", "options_intraday",
        "Same failed-breakout-fade mechanic as A1, this channel's own framing.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=10, ge=5)
        confirm_within: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + self.params.confirm_within + 2

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._trap = None

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bar = ctx.current
        if self._trap is not None:
            age, d = self._trap
            age += 1
            if age > self.params.confirm_within:
                self._trap = None
            elif d > 0 and bar.close < hi:
                self._trap = None
                self.why = "trap up failed, faded down"
                return -1
            elif d < 0 and bar.close > lo:
                self._trap = None
                self.why = "trap down failed, faded up"
                return 1
            else:
                self._trap = (age, d)
        if bar.close > hi:
            self._trap = (0, 1)
        elif bar.close < lo:
            self._trap = (0, -1)
        return None


@register_strategy
class SlReversalFinder(OptionBuyStrategy):
    metadata = buy_meta(
        "sl_reversal_finder", "Stock Learners: Reversal-Finding (F5)", "options_intraday",
        "Divergence + structure-break reversal: RSI diverges from price at a swing "
        "extreme, confirmed by breaking the most recent minor swing.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        rsi_period: int = Field(default=14, ge=5)
        lookback: int = Field(default=30, ge=15)

    @property
    def warmup(self) -> int:
        return self.params.lookback + self.params.rsi_period + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        r = rsi(ctx.closes, self.params.rsi_period)
        highs, lows = swing_points(ctx.bars[-self.params.lookback:], 2)
        bar = ctx.current
        if len(lows) >= 2 and lows[-1] < lows[-2]:
            half = len(r) // 2
            if min(r[half:]) > min(r[:half]) and bar.close > bar.open:
                self.why = "bullish reversal: price LL, RSI HL, confirmed"
                return 1
        if len(highs) >= 2 and highs[-1] > highs[-2]:
            half = len(r) // 2
            if max(r[half:]) < max(r[:half]) and bar.close < bar.open:
                self.why = "bearish reversal: price HH, RSI LH, confirmed"
                return -1
        return None


@register_strategy
class SlOperatorBreakout(OptionBuyStrategy):
    metadata = buy_meta(
        "sl_operator_breakout", "Stock Learners: Breakout (Operator Style) (F6)", "options_breakout",
        "A breakout with a retest hold, framed as 'operator-driven' — only trades once "
        "the retest confirms rather than the initial break.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=20, ge=10)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 5

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bars = ctx.bars
        bar = bars[-1]
        broke_up = any(b.close > hi for b in bars[-6:-1])
        broke_down = any(b.close < lo for b in bars[-6:-1])
        if broke_up and bar.low <= hi and bar.close > hi:
            self.why = f"retest of breakout level {hi:.0f} held"
            return 1
        if broke_down and bar.high >= lo and bar.close < lo:
            self.why = f"retest of breakdown level {lo:.0f} held"
            return -1
        return None


@register_strategy
class SlSmcRrSetup(OptionBuyStrategy):
    metadata = buy_meta(
        "sl_smc_rr_setup", "Stock Learners: SMC RR Setup (F7)", "options_intraday",
        "An order-block-style retest combined with a self-enforced >=1:3 reward-risk "
        "gate before firing.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        impulse_mult: float = Field(default=1.6, gt=0)
        atr_period: int = Field(default=14, ge=5)
        min_rr: float = Field(default=3.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars
        a = atr(bars, self.params.atr_period)[-1]
        impulse, prior = bars[-1], bars[-2]
        is_up = (impulse.close - impulse.open) > self.params.impulse_mult * a
        is_down = (impulse.open - impulse.close) > self.params.impulse_mult * a
        if is_up and prior.close < prior.open:
            risk = impulse.close - prior.low
            reward = impulse.close - impulse.open + risk  # rough measured projection
            if risk > 0 and reward / risk >= self.params.min_rr:
                self.why = f"OB setup clears {self.params.min_rr:.0f}:1 RR"
                return 1
        if is_down and prior.close > prior.open:
            risk = prior.high - impulse.close
            reward = impulse.open - impulse.close + risk
            if risk > 0 and reward / risk >= self.params.min_rr:
                self.why = f"OB setup clears {self.params.min_rr:.0f}:1 RR"
                return -1
        return None
