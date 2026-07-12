"""Option-buying strategies (#179-182) modeled on the publicly-taught setups of
The Trade Room (Mayank Raj's YouTube channel) — NIFTY/BANKNIFTY option scalping.
Like famous_traders.py, these are "in the style of" the CONCEPTS taught in his free
public videos (the 9/15 EMA scalping strategy, its EMA-pullback re-entry, trap
trading, and the "modified" 9/15 with a 200-EMA trend filter), not a reproduction
of any live calls or paid content.

The channel's taught rules and how they map here:
- 9 & 15 EMA on a 5-minute chart; trade only with "clear directional movement",
  EMA angle "above 30 degrees" -> a chart angle isn't scale-invariant, so the proxy
  is a normalized EMA slope threshold + minimum EMA separation (sideways filter).
- Entry on a strong candle (full-body / big bar / pin-bar rejection) crossing or
  bouncing off the EMAs -> body-ratio and wick-rejection checks on the signal bar.
- Buy ITM/ATM CE on bullish setups, PE on bearish -> the engine buys the ATM leg.
- Small candle-low stop, ~1:2 reward, exit fast on candle character change -> the
  options_scalp engine style (25% premium stop / 50% target / EOD square-off) is
  the premium-space equivalent; regime exits below fire on EMA loss.
"""

from pydantic import BaseModel, Field

from strategy_service.indicators import ema
from strategy_service.strategies.options_buying._base import OptionBuyStrategy, buy_meta
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe


def _bullish_entry_candle(bar, min_body_ratio: float) -> bool:
    """Full-body/big-bar candle up, or a pin bar rejecting lower prices."""
    rng = bar.high - bar.low
    if rng <= 0:
        return False
    body = bar.close - bar.open
    full_body = body > 0 and body / rng >= min_body_ratio
    lower_wick = min(bar.open, bar.close) - bar.low
    pin_bar = body >= 0 and lower_wick >= 2 * abs(body) and bar.close >= bar.high - rng / 3
    return full_body or pin_bar


def _bearish_entry_candle(bar, min_body_ratio: float) -> bool:
    rng = bar.high - bar.low
    if rng <= 0:
        return False
    body = bar.open - bar.close
    full_body = body > 0 and body / rng >= min_body_ratio
    upper_wick = bar.high - max(bar.open, bar.close)
    pin_bar = body >= 0 and upper_wick >= 2 * abs(body) and bar.close <= bar.low + rng / 3
    return full_body or pin_bar


@register_strategy
class TradeRoom915Scalp(OptionBuyStrategy):
    metadata = buy_meta(
        "trade_room_915_scalp", "The Trade Room: 9/15 EMA Scalp", "options_scalp",
        "The Trade Room's (Mayank Raj) signature 9/15 EMA scalping setup as publicly taught: "
        "on 5-minute bars, a fresh 9-over-15 EMA crossover with a steep EMA slope (his '30-degree "
        "angle' rule, proxied scale-invariantly) confirmed by a strong full-body or pin-bar "
        "candle closing beyond both EMAs buys the ATM CE (PE on the bearish mirror). The slope "
        "gate keeps it out of sideways tape; losing the 15 EMA exits immediately.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=9, ge=3)
        slow: int = Field(default=15, ge=5)
        cross_within: int = Field(default=3, ge=1)     # bars since cross for a "fresh" entry
        slope_bars: int = Field(default=3, ge=2)
        # EMA-9 move over slope_bars, % — the scale-invariant "30-degree angle" proxy.
        # This is also the sideways filter: a flat market can't clear it at the cross.
        # (EMA separation can't gate entries — it is ~0 on the cross bar by definition.)
        min_slope_pct: float = Field(default=0.02, ge=0)
        min_body_ratio: float = Field(default=0.55, gt=0, le=1)

    @property
    def warmup(self) -> int:
        return self.params.slow + self.params.slope_bars + self.params.cross_within + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        p = self.params
        closes = ctx.closes
        e9 = ema(closes, p.fast)
        e15 = ema(closes, p.slow)
        bar = ctx.current
        close = closes[-1]

        slope_pct = (e9[-1] - e9[-1 - p.slope_bars]) / e9[-1] * 100
        crossed_up_recently = any(
            e9[-i - 1] <= e15[-i - 1] for i in range(1, p.cross_within + 1)
        ) and e9[-1] > e15[-1]
        crossed_down_recently = any(
            e9[-i - 1] >= e15[-i - 1] for i in range(1, p.cross_within + 1)
        ) and e9[-1] < e15[-1]

        if (
            crossed_up_recently and slope_pct >= p.min_slope_pct
            and close > e9[-1] and close > e15[-1]
            and _bullish_entry_candle(bar, p.min_body_ratio)
        ):
            self.why = f"fresh 9/15 EMA bull cross, steep slope (+{slope_pct:.2f}%), strong entry candle"
            return 1
        if (
            crossed_down_recently and slope_pct <= -p.min_slope_pct
            and close < e9[-1] and close < e15[-1]
            and _bearish_entry_candle(bar, p.min_body_ratio)
        ):
            self.why = f"fresh 9/15 EMA bear cross, steep slope ({slope_pct:.2f}%), strong entry candle"
            return -1

        # quick exit: the scalp is over the moment price loses the slow EMA
        if (self._dir > 0 and close < e15[-1]) or (self._dir < 0 and close > e15[-1]):
            self.why = "price re-crossed the 15 EMA — scalp over, exit fast"
            return 0
        return None


@register_strategy
class TradeRoom915Pullback(OptionBuyStrategy):
    metadata = buy_meta(
        "trade_room_915_pullback", "The Trade Room: 9 EMA Pullback Re-entry", "options_scalp",
        "The Trade Room's continuation entry: with the 9 EMA stacked over the 15 (established "
        "5-minute trend), a candle that dips to touch the 9 EMA and closes back above it with a "
        "strong body is the re-entry — buying the trend's first shallow pullback instead of "
        "chasing, exactly as taught for riding a move with multiple small entries.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=9, ge=3)
        slow: int = Field(default=15, ge=5)
        stacked_bars: int = Field(default=5, ge=2)     # bars the 9>15 stack must already hold
        min_sep_pct: float = Field(default=0.03, ge=0)
        min_body_ratio: float = Field(default=0.5, gt=0, le=1)

    @property
    def warmup(self) -> int:
        return self.params.slow + self.params.stacked_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        p = self.params
        closes = ctx.closes
        e9 = ema(closes, p.fast)
        e15 = ema(closes, p.slow)
        bar = ctx.current
        close = closes[-1]

        sep_pct = abs(e9[-1] - e15[-1]) / close * 100
        if sep_pct < p.min_sep_pct:
            self.why = "EMAs pinched — no trend to pull back within"
            return 0

        stacked_up = all(e9[-i] > e15[-i] for i in range(1, p.stacked_bars + 1))
        stacked_down = all(e9[-i] < e15[-i] for i in range(1, p.stacked_bars + 1))

        if (
            stacked_up and bar.low <= e9[-1] and close > e9[-1]
            and _bullish_entry_candle(bar, p.min_body_ratio)
        ):
            self.why = "trend intact (9>15 EMA), pullback touched the 9 EMA and bounced"
            return 1
        if (
            stacked_down and bar.high >= e9[-1] and close < e9[-1]
            and _bearish_entry_candle(bar, p.min_body_ratio)
        ):
            self.why = "trend intact (9<15 EMA), pullback touched the 9 EMA and rejected"
            return -1

        if (self._dir > 0 and close < e15[-1]) or (self._dir < 0 and close > e15[-1]):
            self.why = "15 EMA lost — pullback thesis dead"
            return 0
        return None


@register_strategy
class TradeRoom915Modified(OptionBuyStrategy):
    metadata = buy_meta(
        "trade_room_915_modified", "The Trade Room: 915 EMA Modified (200-EMA filter)", "options_scalp",
        "The Trade Room's '915 EMA Modified' upgrade of his signature scalp: identical fresh "
        "9/15 crossover + slope + strong-candle entry, but a cross only counts WITH the higher "
        "trend — CE entries require price above the 200 EMA, PE entries below it. Fewer, "
        "cleaner trades: counter-trend crosses (the original's main bleed) are simply skipped.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=9, ge=3)
        slow: int = Field(default=15, ge=5)
        trend: int = Field(default=200, ge=50)
        cross_within: int = Field(default=3, ge=1)
        slope_bars: int = Field(default=3, ge=2)
        min_slope_pct: float = Field(default=0.02, ge=0)
        min_body_ratio: float = Field(default=0.55, gt=0, le=1)

    @property
    def warmup(self) -> int:
        return self.params.trend + self.params.slope_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        p = self.params
        closes = ctx.closes
        e9 = ema(closes, p.fast)
        e15 = ema(closes, p.slow)
        e200 = ema(closes, p.trend)
        bar = ctx.current
        close = closes[-1]

        slope_pct = (e9[-1] - e9[-1 - p.slope_bars]) / e9[-1] * 100
        crossed_up_recently = any(
            e9[-i - 1] <= e15[-i - 1] for i in range(1, p.cross_within + 1)
        ) and e9[-1] > e15[-1]
        crossed_down_recently = any(
            e9[-i - 1] >= e15[-i - 1] for i in range(1, p.cross_within + 1)
        ) and e9[-1] < e15[-1]

        if (
            close > e200[-1]
            and crossed_up_recently and slope_pct >= p.min_slope_pct
            and close > e9[-1] and close > e15[-1]
            and _bullish_entry_candle(bar, p.min_body_ratio)
        ):
            self.why = f"9/15 bull cross above the 200 EMA (trend-aligned), slope +{slope_pct:.2f}%"
            return 1
        if (
            close < e200[-1]
            and crossed_down_recently and slope_pct <= -p.min_slope_pct
            and close < e9[-1] and close < e15[-1]
            and _bearish_entry_candle(bar, p.min_body_ratio)
        ):
            self.why = f"9/15 bear cross below the 200 EMA (trend-aligned), slope {slope_pct:.2f}%"
            return -1

        if (self._dir > 0 and close < e15[-1]) or (self._dir < 0 and close > e15[-1]):
            self.why = "price re-crossed the 15 EMA — scalp over, exit fast"
            return 0
        return None


@register_strategy
class TradeRoomTrap(OptionBuyStrategy):
    metadata = buy_meta(
        "trade_room_trap", "The Trade Room: Trap Trading", "options_scalp",
        "The Trade Room's trap-trading concept: price pokes beyond a recent obvious high/low, "
        "pulls breakout traders in, then closes back inside the range on a rejection candle — "
        "the trapped side's unwinding fuels the reversal. Buys the PE on a failed upside "
        "breakout, the CE on a failed downside break; invalidated if price reclaims the level.",
        Timeframe.M5, "high-volatility",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=20, ge=5)      # window defining the "obvious" level
        min_poke_pct: float = Field(default=0.03, ge=0)  # wick must clear the level by this much

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 3

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._trap_level: float | None = None

    def direction(self, ctx: StrategyContext) -> int | None:
        p = self.params
        window = ctx.bars[-p.range_bars - 1: -1]
        level_hi = max(b.high for b in window)
        level_lo = min(b.low for b in window)
        bar = ctx.current
        close = bar.close

        poke = p.min_poke_pct / 100
        trapped_bulls = (
            bar.high > level_hi * (1 + poke) and close < level_hi and close < bar.open
        )
        trapped_bears = (
            bar.low < level_lo * (1 - poke) and close > level_lo and close > bar.open
        )

        if trapped_bulls and self._dir >= 0:
            self._trap_level = level_hi
            self.why = f"breakout above {level_hi:.0f} failed and closed back inside — bulls trapped"
            return -1
        if trapped_bears and self._dir <= 0:
            self._trap_level = level_lo
            self.why = f"breakdown below {level_lo:.0f} failed and closed back inside — bears trapped"
            return 1

        if self._trap_level is not None:
            if self._dir < 0 and close > self._trap_level:
                self._trap_level = None
                self.why = "price reclaimed the trap level — reversal thesis invalidated"
                return 0
            if self._dir > 0 and close < self._trap_level:
                self._trap_level = None
                self.why = "price lost the trap level again — reversal thesis invalidated"
                return 0
        return None
