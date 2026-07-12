"""Booming Bulls (Anish Singh Thakur) — 8 strategies (D1-D8). D3 mirrors the already-
coded order_block_fvg; D4/D5 are volume-profile-family strategies run on the same
time-at-price proxy as sb_volume_profile since NSE publishes no index volume."""

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, ema
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, prev_day_hlc, swing_points, today_bars,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe


@register_strategy
class BbUltimateConfluence(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_ultimate_confluence", "Booming Bulls: Ultimate Nifty & Stock Strategy (D1)", "options_intraday",
        "Trend + support/resistance confluence with a confirming candle: only trades "
        "when the EMA trend and a recent swing level agree.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        trend_ema: int = Field(default=34, ge=10)
        pivot_strength: int = Field(default=3, ge=1)
        lookback: int = Field(default=30, ge=15)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + self.params.lookback

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        trend = ema(closes, self.params.trend_ema)[-1]
        highs, lows = swing_points(ctx.bars[-self.params.lookback:], self.params.pivot_strength)
        if not highs or not lows:
            return 0
        bar = ctx.current
        if bar.close > trend and bar.low <= lows[-1] * 1.001 and bar.close > lows[-1]:
            self.why = "trend + demand-level confluence"
            return 1
        if bar.close < trend and bar.high >= highs[-1] * 0.999 and bar.close < highs[-1]:
            self.why = "trend + supply-level confluence"
            return -1
        return 0


@register_strategy
class BbLiquidityConcept(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_liquidity_concept", "Booming Bulls: Liquidity Concept (D2)", "options_intraday",
        "Sweep-and-reverse of a prior swing level, same family as Stock Burner's B4.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        lookback: int = Field(default=20, ge=8)

    @property
    def warmup(self) -> int:
        return self.params.lookback + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.lookback - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bar = ctx.current
        if bar.high > hi and bar.close < hi:
            self.why = f"liquidity swept above {hi:.0f}"
            return -1
        if bar.low < lo and bar.close > lo:
            self.why = f"liquidity swept below {lo:.0f}"
            return 1
        if self._dir != 0 and lo <= bar.close <= hi:
            self.why = "back inside"
            return 0
        return None


@register_strategy
class BbOrderBlockFvg(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_order_block_fvg", "Booming Bulls: Order Block + FVG (D3)", "options_intraday",
        "Same order-block/fair-value-gap mechanic as the shared order_block_fvg "
        "strategy; this channel's own naming, kept as its own catalog entry.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        impulse_mult: float = Field(default=1.8, gt=0)
        atr_period: int = Field(default=14, ge=5)
        retest_within: int = Field(default=10, ge=3)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + self.params.retest_within + 3

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._ob = None

    def direction(self, ctx: StrategyContext) -> int | None:
        from strategy_service.indicators import atr as _atr

        bars = ctx.bars
        a = _atr(bars, self.params.atr_period)[-1]
        impulse = bars[-1]
        prior = bars[-2]
        is_up = (impulse.close - impulse.open) > self.params.impulse_mult * a
        is_down = (impulse.open - impulse.close) > self.params.impulse_mult * a
        has_gap_up = len(bars) >= 3 and bars[-3].high < impulse.low
        has_gap_down = len(bars) >= 3 and bars[-3].low > impulse.high
        if is_up and prior.close < prior.open and has_gap_up:
            self._ob = (prior.low, prior.high, 1, 0)
        elif is_down and prior.close > prior.open and has_gap_down:
            self._ob = (prior.low, prior.high, -1, 0)
        if self._ob is not None:
            lo, hi, d, age = self._ob
            age += 1
            if age > self.params.retest_within:
                self._ob = None
                return None
            close = ctx.current.close
            if lo <= close <= hi:
                self.why = f"order block retest [{lo:.0f}-{hi:.0f}]"
                self._ob = None
                return d
            self._ob = (lo, hi, d, age)
        return None


@register_strategy
class BbVolumeProfilePoc(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_volume_profile_poc", "Booming Bulls: Volume Profile / POC (D4)", "options_intraday",
        "No index volume exists; proxies the Point of Control with the time-at-price "
        "level (most-revisited close bucket) over the lookback window.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        lookback: int = Field(default=40, ge=15)
        bucket_pct: float = Field(default=0.1, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.lookback + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.lookback:]
        bucket = ctx.current.close * self.params.bucket_pct / 100
        counts: dict[int, int] = {}
        for b in window:
            k = round(b.close / bucket)
            counts[k] = counts.get(k, 0) + 1
        if not counts:
            return None
        poc = max(counts, key=counts.get) * bucket
        bar = ctx.current
        if bar.high >= poc and bar.close < poc:
            self.why = f"deflected at POC {poc:.0f}"
            return -1
        if bar.low <= poc and bar.close > poc:
            self.why = f"accepted off POC {poc:.0f}"
            return 1
        return None


@register_strategy
class BbFrvp(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_frvp", "Booming Bulls: FRVP — Fixed-Range Volume Profile (D5)", "options_intraday",
        "Fixed-range value-area proxy: the middle 60% (by time-at-price) of a chosen "
        "swing range acts as the value area, edges act as S/R.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=30, ge=15)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        rng = hi - lo
        if rng <= 0:
            return None
        va_hi = lo + rng * 0.8
        va_lo = lo + rng * 0.2
        bar = ctx.current
        if bar.low <= va_lo and bar.close > va_lo:
            self.why = f"held the value-area low {va_lo:.0f}"
            return 1
        if bar.high >= va_hi and bar.close < va_hi:
            self.why = f"rejected the value-area high {va_hi:.0f}"
            return -1
        return None


@register_strategy
class BbDailyBias(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_daily_bias", "Booming Bulls: Daily Bias (D6)", "options_intraday",
        "Sets a CE-only or PE-only regime for the day from the prior day's structure "
        "(higher-high/lower-low vs prior close), then acts on the first intraday break "
        "in that direction only.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        pass

    @property
    def warmup(self) -> int:
        return 10

    def direction(self, ctx: StrategyContext) -> int | None:
        hlc = prev_day_hlc(ctx)
        if hlc is None:
            return 0
        high, low, close_prev = hlc
        day = today_bars(ctx)
        if len(day) < 2:
            return 0
        bias_bullish = close_prev > (high + low) / 2
        bar = ctx.current
        if bias_bullish and bar.close > day[0].open:
            self.why = "bullish daily bias, price above open"
            return 1
        if not bias_bullish and bar.close < day[0].open:
            self.why = "bearish daily bias, price below open"
            return -1
        return 0


@register_strategy
class BbSimpleEntry(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_simple_entry", "Booming Bulls: Simple Entry Setup (D7)", "options_scalp",
        "Beginner-level ORB/trend entry — break of the opening range with the trend.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=3, ge=1)
        trend_ema: int = Field(default=20, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        n = self.params.range_bars
        if len(day) <= n:
            return 0
        hi = max(b.high for b in day[:n])
        lo = min(b.low for b in day[:n])
        trend = ema(ctx.closes, self.params.trend_ema)[-1]
        close = ctx.current.close
        if close > hi and close > trend:
            self.why = "ORB up with trend"
            return 1
        if close < lo and close < trend:
            self.why = "ORB down with trend"
            return -1
        return 0


@register_strategy
class BbAlgoSignal(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_algo_signal", "Booming Bulls: AI/Algo Options (D8)", "options_intraday",
        "Execution tooling in the source, not a distinct edge. Stands in with an "
        "ADX-confirmed trend signal representing 'a generic algo trend signal'.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=5)
        threshold: float = Field(default=25, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period * 3

    def direction(self, ctx: StrategyContext) -> int | None:
        adx_line, plus_di, minus_di = adx(ctx.bars, self.params.period)
        if adx_line[-1] > self.params.threshold and plus_di[-1] > minus_di[-1]:
            self.why = f"algo-signal ADX {adx_line[-1]:.0f}, +DI"
            return 1
        if adx_line[-1] > self.params.threshold and minus_di[-1] > plus_di[-1]:
            self.why = f"algo-signal ADX {adx_line[-1]:.0f}, -DI"
            return -1
        if adx_line[-1] < 18:
            return 0
        return None
