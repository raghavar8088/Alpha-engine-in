"""Monika Rajput Official — 8 strategies (C1-C8). C4 already coded as big_bar_scalp.
C2/no-1m-bars and C3/no-FII-feed run as honestly-labeled proxies (see docstrings)."""

from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema
from strategy_service.strategies.options_buying._base import OptionBuyStrategy, buy_meta, today_bars
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_minutes(ctx: StrategyContext) -> int:
    return ctx.current.ts.astimezone(IST).hour * 60 + ctx.current.ts.astimezone(IST).minute


@register_strategy
class Mr9EmaScalp(OptionBuyStrategy):
    metadata = buy_meta(
        "mr_9ema_scalp", "Monika Rajput: 9 EMA Scalping (C1)", "options_scalp",
        "Same 9-EMA bounce mechanic as Stock Burner's B2, this channel's own framing.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=9, ge=3)

    @property
    def warmup(self) -> int:
        return self.params.period + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        e = ema(ctx.closes, self.params.period)
        bar = ctx.current
        if bar.low <= e[-1] and bar.close > e[-1] and e[-1] > e[-3]:
            self.why = "9-EMA bounce, rising"
            return 1
        if bar.high >= e[-1] and bar.close < e[-1] and e[-1] < e[-3]:
            self.why = "9-EMA rejection, falling"
            return -1
        if (self._dir > 0 and bar.close < e[-1]) or (self._dir < 0 and bar.close > e[-1]):
            self.why = "9-EMA lost"
            return 0
        return None


@register_strategy
class Mr1MinScalp(OptionBuyStrategy):
    metadata = buy_meta(
        "mr_1min_scalp", "Monika Rajput: 1-Minute Scalping (C2)", "options_scalp",
        "No 1-minute NIFTY history is backfilled on this platform; runs on 5m as the "
        "nearest available timeframe — a faithful adaptation of the momentum-micro-scalp "
        "idea, not the literal 1-minute version.",
        Timeframe.M5, "high-volatility",
    )

    class Params(BaseModel):
        atr_period: int = Field(default=10, ge=3)
        burst_mult: float = Field(default=1.3, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        a = atr(ctx.bars, self.params.atr_period)[-1]
        rng = bar.high - bar.low
        if rng > self.params.burst_mult * a:
            if bar.close > bar.open:
                self.why = "micro-momentum burst, bullish"
                return 1
            self.why = "micro-momentum burst, bearish"
            return -1
        if self._dir != 0:
            self.why = "exit after one bar (scalp)"
            return 0
        return None


@register_strategy
class MrFiiBias(OptionBuyStrategy):
    metadata = buy_meta(
        "mr_fii_bias", "Monika Rajput: FII-Data Strategy (C3)", "options_swing",
        "No FII/DII cash-flow feed exists on this platform, so real institutional-flow "
        "bias can't be computed. This proxies the intent with NIFTY's own multi-day "
        "price trend as the directional bias — explicitly NOT real FII/DII data.",
        Timeframe.D1, "trending",
    )

    class Params(BaseModel):
        trend_days: int = Field(default=5, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.trend_days + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        n = self.params.trend_days
        if closes[-1] > closes[-1 - n]:
            self.why = f"{n}-day price trend up (FII-flow proxy)"
            return 1
        if closes[-1] < closes[-1 - n]:
            self.why = f"{n}-day price trend down (FII-flow proxy)"
            return -1
        return 0


@register_strategy
class MrEventVolatility(OptionBuyStrategy):
    metadata = buy_meta(
        "mr_event_volatility", "Monika Rajput: Volatility/Event Trading (C5)", "options_intraday",
        "No economic-event calendar exists on this platform, so 'event days' are proxied "
        "by any session whose range materially exceeds its own recent ATR — the same "
        "expansion an event day would actually produce.",
        Timeframe.M5, "high-volatility",
    )

    class Params(BaseModel):
        atr_period: int = Field(default=14, ge=5)
        expand_mult: float = Field(default=1.8, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        if len(day) < 3:
            return 0
        a = atr(ctx.bars, self.params.atr_period)[-1]
        day_range = max(b.high for b in day) - min(b.low for b in day)
        bar = ctx.current
        if day_range > self.params.expand_mult * a:
            if bar.close > day[0].open:
                self.why = f"event-scale expansion ({day_range/a:.1f}x ATR), bullish"
                return 1
            self.why = f"event-scale expansion ({day_range/a:.1f}x ATR), bearish"
            return -1
        return 0


@register_strategy
class MrBtstFinnifty(OptionBuyStrategy):
    metadata = buy_meta(
        "mr_btst_finnifty", "Monika Rajput: BTST (FinNifty) (C6)", "options_swing",
        "Buy near the close on a strong-close day, carry overnight, exit next morning on "
        "gap/continuation — the FinNifty framing applied here to the index it's run on.",
        Timeframe.D1, "trending",
    )

    class Params(BaseModel):
        strong_close_pct: float = Field(default=0.5, gt=0, description="close within this % of the day's high/low")

    @property
    def warmup(self) -> int:
        return 3

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        rng = bar.high - bar.low
        if rng <= 0:
            return None
        pos_from_high = (bar.high - bar.close) / rng * 100
        pos_from_low = (bar.close - bar.low) / rng * 100
        if pos_from_high < self.params.strong_close_pct * 100:
            self.why = "strong close near day high — BTST long"
            return 1
        if pos_from_low < self.params.strong_close_pct * 100:
            self.why = "weak close near day low — BTST short"
            return -1
        if self._dir != 0:
            self.why = "exit next session (BTST is one day)"
            return 0
        return 0


@register_strategy
class Mr12pmScalp(OptionBuyStrategy):
    metadata = buy_meta(
        "mr_12pm_scalp", "Monika Rajput: 12 PM Scalping (C7)", "options_scalp",
        "A midday-range break scalp after the lunch lull — a time-filtered opening-range "
        "variant anchored to midday instead of the open.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        window_start: int = Field(default=12 * 60, description="minutes since IST midnight")
        window_bars: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return 5

    def direction(self, ctx: StrategyContext) -> int | None:
        minutes = _ist_minutes(ctx)
        if minutes < self.params.window_start:
            return 0
        day = today_bars(ctx)
        midday = [b for b in day if _ist_minutes_of(b.ts) >= self.params.window_start]
        n = self.params.window_bars
        if len(midday) <= n:
            return None
        hi = max(b.high for b in midday[:n])
        lo = min(b.low for b in midday[:n])
        close = ctx.current.close
        if close > hi:
            self.why = f"broke the 12 PM range high {hi:.0f}"
            return 1
        if close < lo:
            self.why = f"broke the 12 PM range low {lo:.0f}"
            return -1
        return 0


def _ist_minutes_of(ts) -> int:
    ist = ts.astimezone(IST)
    return ist.hour * 60 + ist.minute


@register_strategy
class MrSidewaysScalp(OptionBuyStrategy):
    metadata = buy_meta(
        "mr_sideways_scalp", "Monika Rajput: Sideways Scalping (C8)", "options_scalp",
        "Same range-fade mechanic as A9/B8, Monika Rajput's own framing.",
        Timeframe.M5, "range-bound",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=14, ge=8)
        min_range_pct: float = Field(default=0.15, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bar = ctx.current
        if (hi - lo) / bar.close * 100 < self.params.min_range_pct:
            return 0
        mid = (hi + lo) / 2
        if bar.low <= lo * 1.0005:
            self.why = f"range support {lo:.0f}"
            return 1
        if bar.high >= hi * 0.9995:
            self.why = f"range resistance {hi:.0f}"
            return -1
        if (self._dir > 0 and bar.close >= mid) or (self._dir < 0 and bar.close <= mid):
            self.why = "range mid reached"
            return 0
        return None
