"""Option-buying BREAKOUT strategies (#161-168) — high-conviction, SELECTIVE entries
only, engine style `options_breakout` (real-weekly DTE on NIFTY, 35% premium stop /
100% premium target, EOD square-off). Each strategy trades ONLY when its gate
condition confirms a genuinely large move is underway or imminent — most sessions
produce no signal at all, by design. The bigger target reflects that the entry gate
itself already filters for days expected to move enough to earn it; unlike the
scalp/intraday families, these are NOT meant to fire every day."""

from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, atr, donchian
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, prev_day_hlc, today_bars,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

CAT = "options_breakout"
TF = Timeframe.M15
IST = timezone(timedelta(hours=5, minutes=30))


@register_strategy
class BreakoutOrbExpansion(OptionBuyStrategy):
    metadata = buy_meta(
        "breakout_orb_expansion", "Breakout: Opening-Range Expansion", CAT,
        "Only trades when the first-hour range is itself unusually wide (top quartile of the last 20 "
        "sessions) AND price breaks it — a genuine early sign of a trend day, not just any ORB.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=4, ge=2)
        lookback_days: int = Field(default=20, ge=10)
        percentile: float = Field(default=0.75, gt=0, lt=1)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 1

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._day_ranges: dict = {}

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        n = self.params.range_bars
        if len(day) == n:
            self._day_ranges[ctx.current.ts.date()] = max(b.high for b in day) - min(b.low for b in day)
        if len(day) <= n:
            return 0
        today = ctx.current.ts.date()
        past = sorted((d, r) for d, r in self._day_ranges.items() if d < today)
        if len(past) < self.params.lookback_days:
            return 0
        recent = [r for _, r in past[-self.params.lookback_days:]]
        threshold = sorted(recent)[int(len(recent) * self.params.percentile)]
        todays_range = self._day_ranges.get(today)
        if todays_range is None or todays_range < threshold:
            return 0  # opening range wasn't wide enough — no trade today
        or_high = max(b.high for b in day[:n])
        or_low = min(b.low for b in day[:n])
        close = ctx.current.close
        if close > or_high:
            self.why = f"wide opening range ({todays_range:.0f}pt) broke up"
            return 1
        if close < or_low:
            self.why = f"wide opening range ({todays_range:.0f}pt) broke down"
            return -1
        return 0


@register_strategy
class BreakoutAdxSurge(OptionBuyStrategy):
    metadata = buy_meta(
        "breakout_adx_surge", "Breakout: ADX Surge", CAT,
        "Only trades when ADX(14) crosses above 30 (a strong, unambiguous trend, not the milder "
        "20-threshold used by the regular trend strategies) — rare, high-conviction confirmation.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=5)
        surge_level: float = Field(default=30, gt=0)
        exit_level: float = Field(default=22, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period * 3

    def direction(self, ctx: StrategyContext) -> int | None:
        adx_line, plus_di, minus_di = adx(ctx.bars, self.params.period)
        crossed = adx_line[-2] < self.params.surge_level <= adx_line[-1]
        if crossed and plus_di[-1] > minus_di[-1]:
            self.why = f"ADX surged to {adx_line[-1]:.0f}, +DI dominant"
            return 1
        if crossed and minus_di[-1] > plus_di[-1]:
            self.why = f"ADX surged to {adx_line[-1]:.0f}, -DI dominant"
            return -1
        if adx_line[-1] < self.params.exit_level:
            self.why = f"trend faded (ADX {adx_line[-1]:.0f})"
            return 0
        return None


@register_strategy
class BreakoutGapAndGo(OptionBuyStrategy):
    metadata = buy_meta(
        "breakout_gap_and_go", "Breakout: Big Gap Continuation", CAT,
        "Only trades a LARGE opening gap (>=0.6%, double the ordinary gap-momentum threshold) that "
        "is still extending an hour in — the rare gap day that keeps running instead of fading.",
        TF, "trending",
    )

    class Params(BaseModel):
        min_gap_pct: float = Field(default=0.6, gt=0)
        confirm_bars: int = Field(default=4, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.confirm_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        n = self.params.confirm_bars
        if len(day) != n:
            return 0 if len(day) < n else None
        hlc = prev_day_hlc(ctx)
        if hlc is None:
            return 0
        prev_close = hlc[2]
        gap_pct = (day[0].open - prev_close) / prev_close * 100
        close = ctx.current.close
        if gap_pct > self.params.min_gap_pct and close > day[0].open:
            self.why = f"big gap up {gap_pct:.2f}% still extending"
            return 1
        if gap_pct < -self.params.min_gap_pct and close < day[0].open:
            self.why = f"big gap down {gap_pct:.2f}% still extending"
            return -1
        return 0


@register_strategy
class BreakoutRangeCompression(OptionBuyStrategy):
    metadata = buy_meta(
        "breakout_range_compression", "Breakout: 20-Day Range Break", CAT,
        "Only trades a break of a genuinely tight multi-week consolidation (20-day range under "
        "3% of price) — a coiled-spring setup, not an everyday Donchian break.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        period: int = Field(default=80, ge=20)  # 20 trading days x 4 bars/hr approx on 15m -> use daily-scale window
        max_range_pct: float = Field(default=3.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        upper, lower = donchian(ctx.bars[:-1], self.params.period)
        close = ctx.current.close
        range_pct = (upper[-1] - lower[-1]) / close * 100
        if range_pct > self.params.max_range_pct:
            return 0  # not coiled tight enough — no trade
        if close > upper[-1]:
            self.why = f"broke a tight {range_pct:.1f}% range up"
            return 1
        if close < lower[-1]:
            self.why = f"broke a tight {range_pct:.1f}% range down"
            return -1
        return 0


@register_strategy
class BreakoutAtrThrust(OptionBuyStrategy):
    metadata = buy_meta(
        "breakout_atr_thrust", "Breakout: 2x ATR Thrust Bar", CAT,
        "Only trades a single bar's range exceeding 2x its 14-bar ATR closing near its extreme — "
        "a rare, unambiguous momentum-ignition bar, not the milder 1.5x scalp version.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        atr_period: int = Field(default=14, ge=5)
        thrust_mult: float = Field(default=2.0, gt=0)
        close_zone: float = Field(default=0.2, gt=0, le=0.5)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        a = atr(ctx.bars, self.params.atr_period)[-1]
        rng = bar.high - bar.low
        if rng <= self.params.thrust_mult * a:
            return None if self._dir != 0 else 0
        pos = (bar.close - bar.low) / rng if rng > 0 else 0.5
        if pos > 1 - self.params.close_zone:
            self.why = f"{rng:.0f}pt thrust bar ({rng/a:.1f}x ATR), closed strong"
            return 1
        if pos < self.params.close_zone:
            self.why = f"{rng:.0f}pt thrust bar ({rng/a:.1f}x ATR), closed weak"
            return -1
        return None


@register_strategy
class BreakoutFailedReversal(OptionBuyStrategy):
    metadata = buy_meta(
        "breakout_failed_reversal", "Breakout: Failed Breakdown/Breakout Reversal", CAT,
        "Only trades a V-shaped failure: price breaks a 10-bar extreme, then within 3 bars closes "
        "back beyond the ORIGINAL range's midpoint — a violent, high-conviction trap reversal.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        period: int = Field(default=10, ge=5)
        confirm_within: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.period + self.params.confirm_within + 2

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._trap: tuple[int, float, float] | None = None  # (bars_since, mid, broke_dir)

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars
        window = bars[-self.params.period - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        mid = (hi + lo) / 2
        close = ctx.current.close

        if self._trap is not None:
            age, tmid, broke_dir = self._trap
            age += 1
            if age > self.params.confirm_within:
                self._trap = None
            elif broke_dir > 0 and close < tmid:
                self._trap = None
                self.why = "failed breakout reversed down through the range"
                return -1
            elif broke_dir < 0 and close > tmid:
                self._trap = None
                self.why = "failed breakdown reversed up through the range"
                return 1
            else:
                self._trap = (age, tmid, broke_dir)

        if close > hi:
            self._trap = (0, mid, 1)
        elif close < lo:
            self._trap = (0, mid, -1)
        return None


@register_strategy
class BreakoutVwapReclaim(OptionBuyStrategy):
    metadata = buy_meta(
        "breakout_vwap_reclaim", "Breakout: Big VWAP Reclaim", CAT,
        "Only trades when price was pinned >=0.5% away from session VWAP for at least 6 bars and "
        "then reclaims it decisively — a rare capitulation/reclaim, not routine VWAP noise.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        pinned_bars: int = Field(default=6, ge=3)
        pin_pct: float = Field(default=0.5, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.pinned_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        from strategy_service.indicators import session_vwap

        vwap = session_vwap(ctx.bars, lambda b: b.ts.date())
        window = vwap[-self.params.pinned_bars - 1: -1]
        closes = ctx.closes[-self.params.pinned_bars - 1: -1]
        pinned_below = all((v - c) / v * 100 > self.params.pin_pct for v, c in zip(window, closes))
        pinned_above = all((c - v) / v * 100 > self.params.pin_pct for v, c in zip(window, closes))
        close, vw = ctx.current.close, vwap[-1]
        if pinned_below and close > vw:
            self.why = f"reclaimed VWAP after {self.params.pinned_bars} bars pinned below"
            return 1
        if pinned_above and close < vw:
            self.why = f"lost VWAP after {self.params.pinned_bars} bars pinned above"
            return -1
        if (self._dir > 0 and close < vw) or (self._dir < 0 and close > vw):
            self.why = "VWAP re-crossed against"
            return 0
        return None


@register_strategy
class BreakoutMultiDayThrust(OptionBuyStrategy):
    metadata = buy_meta(
        "breakout_multiday_thrust", "Breakout: 3-Day Range Break", CAT,
        "Only trades when today's session breaks the combined high/low of the PRIOR THREE full "
        "sessions — a break of meaningful multi-day structure, not just yesterday's range.",
        TF, "trending",
    )

    class Params(BaseModel):
        days: int = Field(default=3, ge=2)

    @property
    def warmup(self) -> int:
        return 100

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._day_hl: dict = {}

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        d = bar.ts.date()
        hi, lo = self._day_hl.get(d, (bar.high, bar.low))
        self._day_hl[d] = (max(hi, bar.high), min(lo, bar.low))
        prior_days = sorted(x for x in self._day_hl if x < d)[-self.params.days:]
        if len(prior_days) < self.params.days:
            return 0
        range_hi = max(self._day_hl[x][0] for x in prior_days)
        range_lo = min(self._day_hl[x][1] for x in prior_days)
        close = bar.close
        if close > range_hi:
            self.why = f"broke the prior {self.params.days}-day high {range_hi:.0f}"
            return 1
        if close < range_lo:
            self.why = f"broke the prior {self.params.days}-day low {range_lo:.0f}"
            return -1
        return 0
