"""The Madras Trader — 5 strategies (I1-I5). I3 (a backtest-walkthrough video, not a
standalone setup) is represented as a composite of his teaching points so the catalog
ID isn't empty. I5 (equity swing on Nifty-200 stocks) is adapted to the index itself
since this platform trades index options, not individual stocks."""

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, ema
from strategy_service.strategies.options_buying._base import OptionBuyStrategy, buy_meta
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe


@register_strategy
class MtBreakoutTrading(OptionBuyStrategy):
    metadata = buy_meta(
        "mt_breakout_trading", "The Madras Trader: Breakout Trading (I1)", "options_breakout",
        "Clean breakout of a chart-pattern/level, held for at least one bar before "
        "acting — avoids the instant-break false signal.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=25, ge=10)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bars = ctx.bars
        if bars[-2].close > hi and bars[-1].close > hi:
            self.why = f"clean breakout above {hi:.0f}, held"
            return 1
        if bars[-2].close < lo and bars[-1].close < lo:
            self.why = f"clean breakdown below {lo:.0f}, held"
            return -1
        return 0


@register_strategy
class MtBreakoutFailure(OptionBuyStrategy):
    metadata = buy_meta(
        "mt_breakout_failure", "The Madras Trader: Breakout-Failure Handling (I2)", "options_intraday",
        "Fades a failed breakout — same family as A1/F4, this channel's exit-focused "
        "framing of it.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=15, ge=8)
        confirm_within: int = Field(default=2, ge=1)

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
                self.why = "breakout failed, fading down"
                return -1
            elif d < 0 and bar.close > lo:
                self._trap = None
                self.why = "breakdown failed, fading up"
                return 1
            else:
                self._trap = (age, d)
        if bar.close > hi:
            self._trap = (0, 1)
        elif bar.close < lo:
            self._trap = (0, -1)
        return None


@register_strategy
class MtPriceActionComposite(OptionBuyStrategy):
    metadata = buy_meta(
        "mt_price_action_composite", "The Madras Trader: Price-Action Backtesting Composite (I3)", "options_intraday",
        "The source video is a backtest walkthrough, not a standalone setup. "
        "Represented as a composite of his teaching points: trend + support/resistance "
        "+ candle confirmation all agreeing.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        trend_ema: int = Field(default=21, ge=5)
        lookback: int = Field(default=20, ge=10)

    @property
    def warmup(self) -> int:
        return max(self.params.trend_ema, self.params.lookback) + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        trend = ema(closes, self.params.trend_ema)[-1]
        window = ctx.bars[-self.params.lookback - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bar = ctx.current
        candle_bull = bar.close > bar.open
        candle_bear = bar.close < bar.open
        if bar.close > trend and bar.close > hi and candle_bull:
            self.why = "trend + S/R break + bullish candle"
            return 1
        if bar.close < trend and bar.close < lo and candle_bear:
            self.why = "trend + S/R break + bearish candle"
            return -1
        return 0


@register_strategy
class MtBreakoutBuying(OptionBuyStrategy):
    metadata = buy_meta(
        "mt_breakout_buying", "The Madras Trader: Option-Buying on Breakouts (I4)", "options_breakout",
        "Buys the CE/PE directly on a directional pattern break — simpler and faster "
        "than I1's held-breakout variant.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=15, ge=8)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        close = ctx.current.close
        if close > hi:
            self.why = f"pattern break up {hi:.0f}"
            return 1
        if close < lo:
            self.why = f"pattern break down {lo:.0f}"
            return -1
        return 0


@register_strategy
class MtIndexSwing(OptionBuyStrategy):
    metadata = buy_meta(
        "mt_index_swing", "The Madras Trader: Swing Trading — Index Analog (I5)", "options_swing",
        "The source strategy trades multi-day breakouts on Nifty-200 STOCKS; adapted "
        "here to the index itself (this platform trades index options, not equity), "
        "using ADX-confirmed multi-day trend continuation.",
        Timeframe.D1, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=5)
        threshold: float = Field(default=22, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period * 3

    def direction(self, ctx: StrategyContext) -> int | None:
        adx_line, plus_di, minus_di = adx(ctx.bars, self.params.period)
        if adx_line[-1] > self.params.threshold and plus_di[-1] > minus_di[-1]:
            self.why = f"multi-day uptrend confirmed (ADX {adx_line[-1]:.0f})"
            return 1
        if adx_line[-1] > self.params.threshold and minus_di[-1] > plus_di[-1]:
            self.why = f"multi-day downtrend confirmed (ADX {adx_line[-1]:.0f})"
            return -1
        if adx_line[-1] < 17:
            return 0
        return None
