"""Option-buying strategies (#169-178) modeled on well-documented, publicly taught
methodologies from famous traders/authors — the same public-domain technique every
trading book/course/YouTube channel teaches under that name, adapted to the
direction-regime contract (see _base.py) and priced as a premium buyer. These are
"in the style of," not verbatim reproductions of any individual's actual live system
(no such thing is public) — attribution is to the published/taught CONCEPT.

Roster in this file:
- Linda Raschke  — "Holy Grail" (ADX>30 trend + 20-EMA pullback continuation)
- Linda Raschke  — "80-20" (fade a gap that fails to hold in the gap direction)
- Larry Williams — "Oops!" (gap beyond yesterday's extreme that reverses back inside)
- Larry Williams — classic %R 90/10 reversal (his originally published thresholds)
- Jesse Livermore — "Pivotal Point" breakout (multi-day base break with follow-through)
- Mark Minervini  — Trend Template (stage-2 uptrend: price/50/150/200-day MA stack)
- Kristjan Kullamägi ("Qullamaggie") — EMA10/20 flag breakout in an established trend
- Brian Shannon   — Anchored VWAP reclaim/loss from a significant swing point
- John Carter     — "Gap and Go" momentum (distinct parameterization from the
  breakout-category version; Carter's own rule set uses relative volume + first-candle
  break, approximated here with range + follow-through since volume isn't in this
  universe's index-spot bars)
- Ross Cameron ("Warrior Trading") — micro-pullback continuation after a strong
  opening thrust, the core setup of his momentum day-trading style
"""

from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, ema, sma, session_vwap
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, prev_day_hlc, swing_points, today_bars,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


@register_strategy
class RaschkeHolyGrail(OptionBuyStrategy):
    metadata = buy_meta(
        "raschke_holy_grail", "Linda Raschke: Holy Grail", "options_intraday",
        "Linda Raschke's published setup: once ADX confirms a strong trend (>30), wait for a "
        "pullback to the 20-EMA and buy the resumption — trading WITH an established trend's "
        "first retracement rather than chasing the breakout itself.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        adx_period: int = Field(default=14, ge=5)
        adx_trend: float = Field(default=30, gt=0)
        ema_period: int = Field(default=20, ge=5)
        pullback_pct: float = Field(default=0.15, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.adx_period * 3 + self.params.ema_period

    def direction(self, ctx: StrategyContext) -> int | None:
        adx_line, plus_di, minus_di = adx(ctx.bars, self.params.adx_period)
        e = ema(ctx.closes, self.params.ema_period)
        bar = ctx.current
        trending_up = adx_line[-1] > self.params.adx_trend and plus_di[-1] > minus_di[-1]
        trending_down = adx_line[-1] > self.params.adx_trend and minus_di[-1] > plus_di[-1]
        near_ema = abs(bar.low - e[-1]) / e[-1] * 100 < self.params.pullback_pct or bar.low <= e[-1]
        near_ema_short = abs(bar.high - e[-1]) / e[-1] * 100 < self.params.pullback_pct or bar.high >= e[-1]
        if trending_up and near_ema and bar.close > e[-1]:
            self.why = f"strong uptrend (ADX {adx_line[-1]:.0f}) pulled back to 20-EMA and resumed"
            return 1
        if trending_down and near_ema_short and bar.close < e[-1]:
            self.why = f"strong downtrend (ADX {adx_line[-1]:.0f}) pulled back to 20-EMA and resumed"
            return -1
        if adx_line[-1] < 20:
            self.why = "trend faded — Holy Grail setup no longer valid"
            return 0
        return None


@register_strategy
class Raschke8020(OptionBuyStrategy):
    metadata = buy_meta(
        "raschke_80_20", "Linda Raschke: 80-20 Fade", "options_intraday",
        "Linda Raschke's published gap-fade rule: a big opening gap that fails to make a new "
        "extreme within the first hour is faded back toward the prior close — the market rejecting "
        "the initial move, a classic reversal-day tell.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        min_gap_pct: float = Field(default=0.4, gt=0)
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
        session_high = max(b.high for b in day)
        session_low = min(b.low for b in day)
        close = ctx.current.close
        if gap_pct > self.params.min_gap_pct and day[0].open >= session_high and close < day[0].open:
            self.why = f"gap up {gap_pct:.2f}% failed to extend — fading back to prior close"
            return -1
        if gap_pct < -self.params.min_gap_pct and day[0].open <= session_low and close > day[0].open:
            self.why = f"gap down {gap_pct:.2f}% failed to extend — fading back to prior close"
            return 1
        return 0


@register_strategy
class WilliamsOops(OptionBuyStrategy):
    metadata = buy_meta(
        "williams_oops", "Larry Williams: Oops!", "options_intraday",
        "From Larry Williams' 'Long-Term Secrets to Short-Term Trading': a gap that opens BEYOND "
        "yesterday's high/low and then trades back through it is a trapped-trader reversal — the "
        "'Oops, wrong way' moment that Williams built an entire short-term system around.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        pass

    @property
    def warmup(self) -> int:
        return 5

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        if not day:
            return 0
        hlc = prev_day_hlc(ctx)
        if hlc is None:
            return 0
        prev_high, prev_low, _ = hlc
        open_ = day[0].open
        close = ctx.current.close
        if open_ > prev_high and close < prev_high:
            self.why = f"gapped above yesterday's high {prev_high:.0f} then reversed back through it"
            return -1
        if open_ < prev_low and close > prev_low:
            self.why = f"gapped below yesterday's low {prev_low:.0f} then reversed back through it"
            return 1
        if self._dir != 0:
            self.why = "Oops setup resolved"
            return 0
        return 0


@register_strategy
class WilliamsPctR9010(OptionBuyStrategy):
    metadata = buy_meta(
        "williams_pctr_9010", "Larry Williams: %R 90/10", "options_swing",
        "Larry Williams' own published Williams %R thresholds (-90 oversold / -10 overbought, "
        "not the commonly-used -80/-20) — a stricter, rarer-firing version of the indicator he "
        "invented, from his original writings on it.",
        Timeframe.D1, "range-bound",
    )

    class Params(BaseModel):
        period: int = Field(default=10, ge=3)  # Williams' own originally published period

    @property
    def warmup(self) -> int:
        return self.params.period + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        from strategy_service.indicators import williams_r

        w = williams_r(ctx.bars, self.params.period)
        if w[-2] < -90 <= w[-1]:
            self.why = f"%R({self.params.period}) snapped up from below -90"
            return 1
        if w[-2] > -10 >= w[-1]:
            self.why = f"%R({self.params.period}) snapped down from above -10"
            return -1
        if (self._dir > 0 and w[-1] > -20) or (self._dir < 0 and w[-1] < -80):
            self.why = "extreme reading unwound"
            return 0
        return None


@register_strategy
class LivermorePivotalPoint(OptionBuyStrategy):
    metadata = buy_meta(
        "livermore_pivotal_point", "Jesse Livermore: Pivotal Point Breakout", "options_swing",
        "From Livermore's 'Reminiscences of a Stock Operator' / 'How to Trade in Stocks': wait "
        "for a stock (or index) to build a base at a 'pivotal point,' then buy the breakout with "
        "conviction only once the level is cleanly cleared — no anticipation, no averaging down.",
        Timeframe.D1, "trending",
    )

    class Params(BaseModel):
        base_period: int = Field(default=15, ge=5)
        base_max_range_pct: float = Field(default=6.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.base_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.base_period - 1: -1]
        hi = max(b.high for b in window)
        lo = min(b.low for b in window)
        close = ctx.current.close
        range_pct = (hi - lo) / close * 100
        if range_pct > self.params.base_max_range_pct:
            return 0  # no clean base formed — Livermore would not act here
        if close > hi:
            self.why = f"cleared the pivotal point at {hi:.0f} out of a {range_pct:.1f}% base"
            return 1
        if close < lo:
            self.why = f"broke the pivotal point at {lo:.0f} out of a {range_pct:.1f}% base"
            return -1
        return 0


@register_strategy
class MinerviniTrendTemplate(OptionBuyStrategy):
    metadata = buy_meta(
        "minervini_trend_template", "Mark Minervini: Trend Template", "options_swing",
        "Mark Minervini's published 'Stage 2 uptrend' filter from 'Trade Like a Stock Market "
        "Wizard': price above the 50, 150, and 200-day MAs; 50 above 150 above 200; and the "
        "200-day itself trending up. Only trades in a confirmed Stage 2 regime, flat otherwise.",
        Timeframe.D1, "trending",
    )

    class Params(BaseModel):
        ma_fast: int = Field(default=50, ge=10)
        ma_mid: int = Field(default=150, ge=20)
        ma_slow: int = Field(default=200, ge=30)
        slope_lookback: int = Field(default=20, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.ma_slow + self.params.slope_lookback + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        ma50 = sma(closes, self.params.ma_fast)
        ma150 = sma(closes, self.params.ma_mid)
        ma200 = sma(closes, self.params.ma_slow)
        close = closes[-1]
        stage2 = (
            close > ma50[-1] > ma150[-1] > ma200[-1]
            and ma200[-1] > ma200[-self.params.slope_lookback]
        )
        stage4 = (  # the bearish mirror: Stage 4 decline
            close < ma50[-1] < ma150[-1] < ma200[-1]
            and ma200[-1] < ma200[-self.params.slope_lookback]
        )
        if stage2:
            self.why = "Stage 2 uptrend confirmed (price>50>150>200MA, 200MA rising)"
            return 1
        if stage4:
            self.why = "Stage 4 decline confirmed (price<50<150<200MA, 200MA falling)"
            return -1
        self.why = "no confirmed stage — Trend Template not met"
        return 0


@register_strategy
class QullamaggieFlag(OptionBuyStrategy):
    metadata = buy_meta(
        "qullamaggie_flag", "Kristjan Kullamägi (Qullamaggie): EMA Flag Breakout", "options_swing",
        "The breakout-momentum setup Kullamägi has publicly taught (YouTube/Twitter): in an "
        "established uptrend (price above a rising 20-EMA), a tight multi-day flag pulling back "
        "to the 10-EMA that then breaks the flag's high resumes the trend.",
        Timeframe.D1, "trending",
    )

    class Params(BaseModel):
        fast_ema: int = Field(default=10, ge=3)
        trend_ema: int = Field(default=20, ge=5)
        flag_bars: int = Field(default=5, ge=3)
        flag_max_range_pct: float = Field(default=8.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + self.params.flag_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        e10 = ema(closes, self.params.fast_ema)
        e20 = ema(closes, self.params.trend_ema)
        trend_up = e20[-1] > e20[-5]
        trend_down = e20[-1] < e20[-5]
        flag = ctx.bars[-self.params.flag_bars - 1: -1]
        flag_hi = max(b.high for b in flag)
        flag_lo = min(b.low for b in flag)
        close = closes[-1]
        tight = (flag_hi - flag_lo) / close * 100 < self.params.flag_max_range_pct
        pulled_to_ema = flag_lo <= e10[-1] * 1.02
        pulled_to_ema_short = flag_hi >= e10[-1] * 0.98
        if trend_up and tight and pulled_to_ema and close > flag_hi:
            self.why = "tight flag pulled back to 10-EMA in an uptrend, broke the flag high"
            return 1
        if trend_down and tight and pulled_to_ema_short and close < flag_lo:
            self.why = "tight flag pulled back to 10-EMA in a downtrend, broke the flag low"
            return -1
        if (self._dir > 0 and close < e20[-1]) or (self._dir < 0 and close > e20[-1]):
            self.why = "trend EMA lost — flag thesis invalidated"
            return 0
        return None


@register_strategy
class ShannonAnchoredVwap(OptionBuyStrategy):
    metadata = buy_meta(
        "shannon_anchored_vwap", "Brian Shannon: Anchored VWAP Reclaim", "options_intraday",
        "Brian Shannon's Anchored VWAP concept (from 'Technical Analysis Using Multiple "
        "Timeframes'): anchor VWAP to the most recent significant swing low/high rather than the "
        "session open — a reclaim of that anchored line signals institutional participants are "
        "now, on average, in profit from that pivot.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        swing_lookback: int = Field(default=40, ge=15)
        pivot_strength: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.swing_lookback + self.params.pivot_strength * 2 + 2

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._anchor_idx: int | None = None

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars
        window = bars[-self.params.swing_lookback:]
        highs, lows = swing_points(window, self.params.pivot_strength)
        if not highs and not lows:
            return None
        # anchor to whichever pivot (high or low) is more recent in the window
        anchor_price = None
        for i in range(len(window) - 1, -1, -1):
            b = window[i]
            if lows and abs(b.low - lows[-1]) < 1e-6:
                anchor_price, anchor_is_low = lows[-1], True
                anchor_i = len(bars) - len(window) + i
                break
            if highs and abs(b.high - highs[-1]) < 1e-6:
                anchor_price, anchor_is_low = highs[-1], False
                anchor_i = len(bars) - len(window) + i
                break
        if anchor_price is None:
            return None
        anchored_bars = bars[anchor_i:]
        if len(anchored_bars) < 2:
            return None
        cum_pv = sum((b.high + b.low + b.close) / 3 * max(b.volume, 1) for b in anchored_bars)
        cum_v = sum(max(b.volume, 1) for b in anchored_bars)
        avwap = cum_pv / cum_v if cum_v else anchored_bars[-1].close
        close = ctx.current.close
        prev_close = anchored_bars[-2].close if len(anchored_bars) > 1 else close
        crossed_up = prev_close <= avwap < close
        crossed_down = prev_close >= avwap > close
        if anchor_is_low and crossed_up:
            self.why = f"reclaimed anchored VWAP {avwap:.0f} from the recent swing low"
            return 1
        if not anchor_is_low and crossed_down:
            self.why = f"lost anchored VWAP {avwap:.0f} from the recent swing high"
            return -1
        if (self._dir > 0 and close < avwap) or (self._dir < 0 and close > avwap):
            self.why = "anchored VWAP re-crossed against the position"
            return 0
        return None


@register_strategy
class CarterGapAndGo(OptionBuyStrategy):
    metadata = buy_meta(
        "carter_gap_and_go", "John Carter: Gap and Go", "options_intraday",
        "John Carter's (Simpler Trading) 'Gap and Go' momentum setup: a stock/index gapping in "
        "one direction that holds above (or below) its opening 15-minute range continues that "
        "direction for the session — buy strength, don't fade it.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        min_gap_pct: float = Field(default=0.25, gt=0)
        confirm_bars: int = Field(default=1, ge=1)

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
        if gap_pct > self.params.min_gap_pct and close >= day[0].open:
            self.why = f"gapped up {gap_pct:.2f}% and holding above the open — go with it"
            return 1
        if gap_pct < -self.params.min_gap_pct and close <= day[0].open:
            self.why = f"gapped down {gap_pct:.2f}% and holding below the open — go with it"
            return -1
        return 0


@register_strategy
class WarriorMicroPullback(OptionBuyStrategy):
    metadata = buy_meta(
        "warrior_micro_pullback", "Ross Cameron (Warrior Trading): Micro Pullback", "options_scalp",
        "Ross Cameron's core momentum day-trading setup: after a strong opening thrust, a shallow "
        "1-2 bar pullback that holds well above the thrust's midpoint and resumes is bought for a "
        "continuation — the 'micro pullback' his Warrior Trading course is built around.",
        Timeframe.M5, "high-volatility",
    )

    class Params(BaseModel):
        thrust_lookback: int = Field(default=6, ge=3)
        thrust_min_pct: float = Field(default=0.3, gt=0)
        pullback_max_pct: float = Field(default=0.4, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.thrust_lookback + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars
        window = bars[-self.params.thrust_lookback - 1: -1]
        move_pct = (window[-1].close - window[0].open) / window[0].open * 100
        mid = (window[-1].close + window[0].open) / 2
        bar = ctx.current
        if move_pct > self.params.thrust_min_pct and bar.low > mid:
            pullback_pct = (window[-1].close - bar.low) / window[-1].close * 100
            if pullback_pct < self.params.pullback_max_pct and bar.close > window[-1].close:
                self.why = f"micro pullback held after a +{move_pct:.2f}% thrust, resuming"
                return 1
        if move_pct < -self.params.thrust_min_pct and bar.high < mid:
            pullback_pct = (bar.high - window[-1].close) / window[-1].close * 100
            if pullback_pct < self.params.pullback_max_pct and bar.close < window[-1].close:
                self.why = f"micro pullback held after a {move_pct:.2f}% thrust, resuming"
                return -1
        if self._dir != 0 and abs(bar.close - mid) / mid * 100 > self.params.thrust_min_pct * 2:
            self.why = "thrust fully retraced — pullback thesis invalidated"
            return 0
        return None
