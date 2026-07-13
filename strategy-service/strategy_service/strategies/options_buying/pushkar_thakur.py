"""Pushkar Raj Thakur — 6 strategies (G1-G6). This channel is an option SELLER
(calendars, strangles, hero-zero) — a fundamentally different engine (multi-leg,
theta-positive) than this platform's premium-BUYING lab. G2-G5 are implemented here as
their DIRECTIONAL MIRROR: the same market view a seller would express by shorting
premium is expressed instead as buying the option that view implies. This is an
explicit simplification, not a reproduction of the actual multi-leg/selling structure —
flagged clearly in each docstring. G1 (0DTE) and G6 (a checklist gate) are buying-
native and need no such mirroring."""

from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, ema
from strategy_service.strategies.options_buying._base import OptionBuyStrategy, buy_meta
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


@register_strategy
class PrtHeroZero(OptionBuyStrategy):
    metadata = buy_meta(
        "prt_hero_zero", "Pushkar Raj Thakur: Sensex Hero-Zero 'Brahmastra' (G1)", "options_breakout",
        "Expiry-day (0DTE) directional momentum play — the buy-side of the "
        "'hero-zero' trade (a violent move on the option's last day). Restricted to "
        "fire only on the actual weekly expiry day.",
        Timeframe.M15, "high-volatility",
    )

    class Params(BaseModel):
        atr_period: int = Field(default=14, ge=5)
        thrust_mult: float = Field(default=1.5, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        from strategy_service.indicators import atr

        if ctx.current.ts.astimezone(IST).weekday() != 1:  # Tuesday = NIFTY weekly expiry
            return 0
        bar = ctx.current
        a = atr(ctx.bars, self.params.atr_period)[-1]
        rng = bar.high - bar.low
        if rng > self.params.thrust_mult * a:
            if bar.close > bar.open:
                self.why = "expiry-day thrust, bullish (hero-zero buy side)"
                return 1
            self.why = "expiry-day thrust, bearish (hero-zero buy side)"
            return -1
        if self._dir != 0:
            return 0
        return None


@register_strategy
class PrtCalendarProxy(OptionBuyStrategy):
    metadata = buy_meta(
        "prt_calendar_proxy", "Pushkar Raj Thakur: Triple Calendar Spread — directional proxy (G2)", "options_swing",
        "The real strategy is a 3-strike multi-expiry CALENDAR SPREAD (short near-dated, "
        "long far-dated, structured for range-bound theta harvest) — not representable "
        "in this single-leg same-expiry buying engine. This proxy instead buys the "
        "swing-dated ATM option only when price sits inside a tight recent range (the "
        "same low-realized-vol condition that makes a calendar profitable), directionally "
        "toward the range's mid-reversion.",
        Timeframe.D1, "range-bound",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=10, ge=5)
        max_range_pct: float = Field(default=3.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bar = ctx.current
        if (hi - lo) / bar.close * 100 > self.params.max_range_pct:
            return 0
        mid = (hi + lo) / 2
        if bar.close < mid:
            self.why = "tight range, below mid — reversion long (calendar proxy)"
            return 1
        if bar.close > mid:
            self.why = "tight range, above mid — reversion short (calendar proxy)"
            return -1
        return None


@register_strategy
class PrtReverseCalendarProxy(OptionBuyStrategy):
    metadata = buy_meta(
        "prt_reverse_calendar_proxy", "Pushkar Raj Thakur: Reverse Calendar Spread — directional proxy (G3)", "options_swing",
        "The real strategy (short far-dated / long near-dated for a volatility EVENT) is "
        "a multi-expiry spread, not representable here. This proxy instead buys the "
        "near-dated ATM option directionally on a volatility EXPANSION day (the event "
        "the real spread is designed around).",
        Timeframe.D1, "high-volatility",
    )

    class Params(BaseModel):
        atr_period: int = Field(default=14, ge=5)
        expand_mult: float = Field(default=1.8, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        from strategy_service.indicators import atr

        a = atr(ctx.bars, self.params.atr_period)
        bar = ctx.current
        rng = bar.high - bar.low
        if rng > self.params.expand_mult * a[-1] and a[-1] > 0:
            if bar.close > bar.open:
                self.why = "volatility-event expansion, bullish (reverse-calendar proxy)"
                return 1
            self.why = "volatility-event expansion, bearish (reverse-calendar proxy)"
            return -1
        return None


@register_strategy
class PrtDirectionalMirror(OptionBuyStrategy):
    metadata = buy_meta(
        "prt_directional_mirror", "Pushkar Raj Thakur: Directional Option Selling — buying mirror (G4)", "options_intraday",
        "The channel SELLS OTM premium against the trend's opposite side. The buying "
        "mirror of the identical market view: buy the ATM option WITH the trend once "
        "ADX confirms it, instead of selling premium against the other side.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=5)
        threshold: float = Field(default=23, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period * 3

    def direction(self, ctx: StrategyContext) -> int | None:
        adx_line, plus_di, minus_di = adx(ctx.bars, self.params.period)
        if adx_line[-1] > self.params.threshold and plus_di[-1] > minus_di[-1]:
            self.why = f"trend confirmed (ADX {adx_line[-1]:.0f}) — buying mirror of the sell-side view"
            return 1
        if adx_line[-1] > self.params.threshold and minus_di[-1] > plus_di[-1]:
            self.why = f"trend confirmed (ADX {adx_line[-1]:.0f}) — buying mirror of the sell-side view"
            return -1
        if adx_line[-1] < 18:
            return 0
        return None


@register_strategy
class PrtDailyPremiumMirror(OptionBuyStrategy):
    metadata = buy_meta(
        "prt_daily_premium_mirror", "Pushkar Raj Thakur: Daily Premium Selling — buying mirror (G5)", "options_scalp",
        "The channel sells a straddle/strangle daily and manages with an SL. The buying "
        "mirror: buy the side of the first decisive intraday move, since a seller's "
        "loss is a buyer's gain on that same move.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        move_pct: float = Field(default=0.3, gt=0)

    @property
    def warmup(self) -> int:
        return 10

    def direction(self, ctx: StrategyContext) -> int | None:
        from strategy_service.strategies.options_buying._base import today_bars

        day = today_bars(ctx)
        if len(day) < 3:
            return 0
        move_pct = (ctx.current.close - day[0].open) / day[0].open * 100
        if move_pct > self.params.move_pct:
            self.why = f"day moved +{move_pct:.2f}% — buying mirror of a straddle-seller's loss side"
            return 1
        if move_pct < -self.params.move_pct:
            self.why = f"day moved {move_pct:.2f}% — buying mirror of a straddle-seller's loss side"
            return -1
        return 0


@register_strategy
class PrtCePeChecklist(OptionBuyStrategy):
    metadata = buy_meta(
        "prt_ce_pe_checklist", "Pushkar Raj Thakur: CE/PE Buy Checklist (G6)", "options_intraday",
        "A pre-trade confirmation gate: trend + level + momentum must all agree before "
        "buying a call vs a put — the one genuinely buying-native strategy on this "
        "selling-focused channel.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        trend_ema: int = Field(default=21, ge=5)
        rsi_period: int = Field(default=14, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + self.params.rsi_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        from strategy_service.indicators import rsi as _rsi

        closes = ctx.closes
        trend = ema(closes, self.params.trend_ema)[-1]
        r = _rsi(closes, self.params.rsi_period)[-1]
        bar = ctx.current
        trend_up = bar.close > trend
        trend_down = bar.close < trend
        momentum_up = r > 55
        momentum_down = r < 45
        level_up = bar.close > ctx.bars[-5].close
        level_down = bar.close < ctx.bars[-5].close
        if trend_up and momentum_up and level_up:
            self.why = "checklist: trend + momentum + level all bullish"
            return 1
        if trend_down and momentum_down and level_down:
            self.why = "checklist: trend + momentum + level all bearish"
            return -1
        if (self._dir > 0 and not trend_up) or (self._dir < 0 and not trend_down):
            return 0
        return None
