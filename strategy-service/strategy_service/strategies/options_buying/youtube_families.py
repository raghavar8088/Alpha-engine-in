"""Option-buying strategies (#181-190) mechanized from the genuinely NEW families
identified in D:/INDIAN MARKET/YOUTUBE_76_STRATEGIES_FULL_DETAILS.md — the 76-strategy
scan of 14 NIFTY-trading YouTube channels. Only families not already covered by
existing strategies AND codeable with data this platform actually has are built here
(skipped: 1-minute-bar setups — no 1m backfill; FII/DII-feed strategies; cross-symbol
SMT divergence — the engine's direction(ctx) sees one instrument at a time; OI/max-pain
— needs the live chain, not historical bars; multi-leg option SELLING — different
engine entirely).

Roster (channel attribution per the scan doc):
- ema_9_20      — Stock Burner "9-20 Strategy" (B1)
- ema_200_trend — Devansh Rai "200 EMA Strategy" (K1)
- ema_5_close   — Devansh Rai "5 EMA Strategy" (K3)
- crt_range     — Stock Burner "CRT / Candle Range Theory" (B3)
- amd_session   — Stock Burner "AMD" (B5)
- order_block_fvg — Stock Burner "Order Blocks/FVG" (B7) / Neeraj Joshi (E2/E3)
- ict_judas_swing — Neeraj Joshi "ICT Manipulation Model" (E1)
- cisd_flip     — Neeraj Joshi "CISD" (E3)
- big_bar_scalp — Monika Rajput "Big Bar Scalping" (C4)
- named_time_orb — Wizard Trader "833"/"8:30" (H1/H2) — time-anchored ORB variant

These are mechanical approximations of publicly-taught concepts, same disclosure as
famous_traders.py / stockforce.py: the channel names the concept, the mechanics here
are the standard textbook form of it.
"""

from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, today_bars,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_minutes(ctx: StrategyContext) -> int:
    ist = ctx.current.ts.astimezone(IST)
    return ist.hour * 60 + ist.minute


@register_strategy
class Ema9x20(OptionBuyStrategy):
    metadata = buy_meta(
        "ema_9_20", "Stock Burner: 9-20 EMA Cross", "options_scalp",
        "9-EMA crossing 20-EMA with the close confirming beyond both lines — a slower, "
        "more-confirmed cousin of the plain 9/20 cross family.",
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
        crossed_up = f[-2] <= s[-2] and f[-1] > s[-1] and bar.close > f[-1]
        crossed_down = f[-2] >= s[-2] and f[-1] < s[-1] and bar.close < f[-1]
        if crossed_up:
            self.why = f"9-EMA crossed above 20-EMA, close confirmed ({bar.close:.0f})"
            return 1
        if crossed_down:
            self.why = f"9-EMA crossed below 20-EMA, close confirmed ({bar.close:.0f})"
            return -1
        if (self._dir > 0 and f[-1] < s[-1]) or (self._dir < 0 and f[-1] > s[-1]):
            self.why = "EMAs re-crossed against the position"
            return 0
        return None


@register_strategy
class Ema200Trend(OptionBuyStrategy):
    metadata = buy_meta(
        "ema_200_trend", "Devansh Rai: 200 EMA Trend", "options_intraday",
        "Price above a RISING 200-EMA holds CE on pullbacks to it; below a FALLING "
        "200-EMA holds PE on rallies to it — the 200-line as the trend filter itself, "
        "not just a fade level.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=200, ge=50)
        slope_lookback: int = Field(default=10, ge=3)
        touch_pct: float = Field(default=0.15, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + self.params.slope_lookback + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        e = ema(closes, self.params.period)
        bar = ctx.current
        rising = e[-1] > e[-self.params.slope_lookback]
        falling = e[-1] < e[-self.params.slope_lookback]
        near = abs(bar.low - e[-1]) / e[-1] * 100 < self.params.touch_pct or bar.low <= e[-1]
        near_short = abs(bar.high - e[-1]) / e[-1] * 100 < self.params.touch_pct or bar.high >= e[-1]
        if rising and bar.close > e[-1] and near:
            self.why = f"pulled back to rising 200-EMA {e[-1]:.0f} and held"
            return 1
        if falling and bar.close < e[-1] and near_short:
            self.why = f"rallied to falling 200-EMA {e[-1]:.0f} and rejected"
            return -1
        if (self._dir > 0 and bar.close < e[-1]) or (self._dir < 0 and bar.close > e[-1]):
            self.why = "200-EMA trend broke"
            return 0
        return None


@register_strategy
class Ema5Close(OptionBuyStrategy):
    metadata = buy_meta(
        "ema_5_close", "Devansh Rai: 5 EMA Strategy", "options_scalp",
        "A full candle closing entirely above (or below) the fast 5-EMA at a swing point "
        "triggers on that candle's own high/low being taken out next — a tight, "
        "fast-reacting momentum entry.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=5, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.period + 4

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._armed_high = None
        self._armed_low = None

    def direction(self, ctx: StrategyContext) -> int | None:
        e = ema(ctx.closes, self.params.period)
        bar = ctx.current
        if bar.low > e[-1]:
            self._armed_high = bar.high
            self._armed_low = None
        elif bar.high < e[-1]:
            self._armed_low = bar.low
            self._armed_high = None
        if self._armed_high is not None and bar.close > self._armed_high:
            self.why = f"closed fully above 5-EMA then broke that candle's high {self._armed_high:.0f}"
            self._armed_high = None
            return 1
        if self._armed_low is not None and bar.close < self._armed_low:
            self.why = f"closed fully below 5-EMA then broke that candle's low {self._armed_low:.0f}"
            self._armed_low = None
            return -1
        if (self._dir > 0 and bar.close < e[-1]) or (self._dir < 0 and bar.close > e[-1]):
            self.why = "lost the 5-EMA"
            return 0
        return None


@register_strategy
class CrtRange(OptionBuyStrategy):
    metadata = buy_meta(
        "crt_range", "Stock Burner: CRT (Candle Range Theory)", "options_intraday",
        "A large 'range candle' sets a high/low; the NEXT candle sweeps one side of that "
        "range and closes back inside it — trade toward the opposite boundary (the "
        "liquidity-manipulation read CRT is built on).",
        Timeframe.M15, "high-volatility",
    )

    class Params(BaseModel):
        range_mult: float = Field(default=1.5, gt=0, description="range candle vs ATR")
        atr_period: int = Field(default=14, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars
        a = atr(bars, self.params.atr_period)[-1]
        range_bar = bars[-2]
        cur = bars[-1]
        is_range_candle = (range_bar.high - range_bar.low) > self.params.range_mult * a
        if not is_range_candle:
            return None if self._dir != 0 else 0
        swept_high = cur.high > range_bar.high and cur.close < range_bar.high
        swept_low = cur.low < range_bar.low and cur.close > range_bar.low
        if swept_high:
            self.why = f"CRT: swept range high {range_bar.high:.0f}, closed back inside"
            return -1
        if swept_low:
            self.why = f"CRT: swept range low {range_bar.low:.0f}, closed back inside"
            return 1
        return None


@register_strategy
class AmdSession(OptionBuyStrategy):
    metadata = buy_meta(
        "amd_session", "Stock Burner: AMD Session Model", "options_intraday",
        "Accumulation (first-hour range) -> Manipulation (a false break of that range) -> "
        "Distribution (the real move, opposite the manipulation). Enters when the "
        "manipulation fails and price reclaims the accumulation range.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        accumulation_bars: int = Field(default=4, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.accumulation_bars + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        n = self.params.accumulation_bars
        if len(day) <= n:
            return 0
        acc_hi = max(b.high for b in day[:n])
        acc_lo = min(b.low for b in day[:n])
        bar = ctx.current
        manipulated_up = any(b.high > acc_hi for b in day[n:-1])
        manipulated_down = any(b.low < acc_lo for b in day[n:-1])
        if manipulated_up and bar.close < acc_hi and not manipulated_down:
            self.why = f"AMD: manipulation above {acc_hi:.0f} failed, distribution down"
            return -1
        if manipulated_down and bar.close > acc_lo and not manipulated_up:
            self.why = f"AMD: manipulation below {acc_lo:.0f} failed, distribution up"
            return 1
        return 0


@register_strategy
class OrderBlockFvg(OptionBuyStrategy):
    metadata = buy_meta(
        "order_block_fvg", "SMC: Order Block + FVG Retest", "options_intraday",
        "The last down-candle before a strong up-move (bullish order block) that also "
        "leaves a gap between the surrounding candles' wicks (fair-value gap) is bought "
        "on its retest — the standard SMC/ICT order-block entry (Stock Burner, Neeraj Joshi).",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        impulse_mult: float = Field(default=1.8, gt=0, description="impulse candle vs ATR")
        atr_period: int = Field(default=14, ge=5)
        retest_within: int = Field(default=10, ge=3)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + self.params.retest_within + 3

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._ob = None  # (low, high, direction, age)

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars
        a = atr(bars, self.params.atr_period)[-1]
        impulse = bars[-1]
        prior = bars[-2]
        is_impulse_up = (impulse.close - impulse.open) > self.params.impulse_mult * a
        is_impulse_down = (impulse.open - impulse.close) > self.params.impulse_mult * a
        has_gap_up = len(bars) >= 3 and bars[-3].high < impulse.low
        has_gap_down = len(bars) >= 3 and bars[-3].low > impulse.high

        if is_impulse_up and prior.close < prior.open and has_gap_up:
            self._ob = (prior.low, prior.high, 1, 0)
        elif is_impulse_down and prior.close > prior.open and has_gap_down:
            self._ob = (prior.low, prior.high, -1, 0)

        if self._ob is not None:
            lo, hi, d, age = self._ob
            age += 1
            if age > self.params.retest_within:
                self._ob = None
                return None if self._dir != 0 else 0
            close = ctx.current.close
            if d > 0 and lo <= close <= hi:
                self.why = f"retested bullish order block [{lo:.0f}-{hi:.0f}]"
                self._ob = None
                return 1
            if d < 0 and lo <= close <= hi:
                self.why = f"retested bearish order block [{lo:.0f}-{hi:.0f}]"
                self._ob = None
                return -1
            self._ob = (lo, hi, d, age)
        return None


@register_strategy
class IctJudasSwing(OptionBuyStrategy):
    metadata = buy_meta(
        "ict_judas_swing", "ICT: Manipulation Model (Judas Swing)", "options_intraday",
        "ICT's session model: the first 30 minutes' move is a false 'Judas swing' meant "
        "to trap traders; the real trend runs opposite it once that swing's extreme is "
        "reclaimed. Enters on the reclaim.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        judas_bars: int = Field(default=2, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.judas_bars + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        n = self.params.judas_bars
        if len(day) <= n:
            return 0
        judas_hi = max(b.high for b in day[:n])
        judas_lo = min(b.low for b in day[:n])
        bar = ctx.current
        if len(day) == n + 1:
            return None  # need at least one bar past the judas window to judge direction
        if bar.close < judas_lo:
            self.why = f"reclaimed below the Judas-swing low {judas_lo:.0f}"
            return -1
        if bar.close > judas_hi:
            self.why = f"reclaimed above the Judas-swing high {judas_hi:.0f}"
            return 1
        return None


@register_strategy
class CisdFlip(OptionBuyStrategy):
    metadata = buy_meta(
        "cisd_flip", "ICT: CISD (Change in State of Delivery)", "options_intraday",
        "A close beyond the open of the last opposing-color candle in a short run — the "
        "'change in state of delivery' ICT teaches as an early trend-flip confirmation.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        run_bars: int = Field(default=3, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.run_bars + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars
        n = self.params.run_bars
        recent = bars[-n - 1: -1]
        bar = ctx.current
        down_run = all(b.close < b.open for b in recent)
        up_run = all(b.close > b.open for b in recent)
        last_opposing_up = next((b for b in reversed(recent) if b.close > b.open), None)
        last_opposing_down = next((b for b in reversed(recent) if b.close < b.open), None)
        if down_run and last_opposing_up is None and bar.close > recent[0].open:
            self.why = "CISD: flipped through the run's origin open, bullish"
            return 1
        if up_run and last_opposing_down is None and bar.close < recent[0].open:
            self.why = "CISD: flipped through the run's origin open, bearish"
            return -1
        return None


@register_strategy
class BigBarScalp(OptionBuyStrategy):
    metadata = buy_meta(
        "big_bar_scalp", "Monika Rajput: Big Bar Scalping", "options_scalp",
        "An outsized momentum candle (well beyond the recent ATR) closing near its "
        "extreme is bought for continuation, exiting on the first sign of exhaustion "
        "(a same-size opposite bar or a close back through the big bar's midpoint).",
        Timeframe.M5, "high-volatility",
    )

    class Params(BaseModel):
        atr_period: int = Field(default=14, ge=5)
        big_mult: float = Field(default=2.2, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        a = atr(ctx.bars, self.params.atr_period)[-1]
        rng = bar.high - bar.low
        mid = (bar.high + bar.low) / 2
        if rng > self.params.big_mult * a:
            if bar.close > mid and bar.close > bar.open:
                self.why = f"big bar {rng:.0f}pt ({rng/a:.1f}x ATR), closed strong"
                return 1
            if bar.close < mid and bar.close < bar.open:
                self.why = f"big bar {rng:.0f}pt ({rng/a:.1f}x ATR), closed weak"
                return -1
        if self._dir != 0:
            prev = ctx.bars[-2]
            prev_mid = (prev.high + prev.low) / 2
            if (self._dir > 0 and bar.close < prev_mid) or (self._dir < 0 and bar.close > prev_mid):
                self.why = "exhaustion: back through the big bar's midpoint"
                return 0
        return None


@register_strategy
class NamedTimeOrb(OptionBuyStrategy):
    metadata = buy_meta(
        "named_time_orb", "Wizard Trader: 8:30/833 Time-Anchored ORB", "options_scalp",
        "Wizard Trader's named-number setups anchor to a specific early-session clock "
        "time rather than a fixed bar count — the range from 9:15 to a chosen cutoff "
        "(default 08:30 elapsed = 8:45 IST) sets up the break.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        cutoff_minute: int = Field(default=8 * 60 + 45, description="minutes since IST midnight")

    @property
    def warmup(self) -> int:
        return 5

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        cutoff_bars = [b for b in day if _ist_minutes_of(b.ts) <= self.params.cutoff_minute]
        if len(cutoff_bars) < 2:
            return 0
        if len(day) == len(cutoff_bars):
            return None  # still inside the range-forming window
        or_hi = max(b.high for b in cutoff_bars)
        or_lo = min(b.low for b in cutoff_bars)
        close = ctx.current.close
        if close > or_hi:
            self.why = f"broke the 8:30-anchored range high {or_hi:.0f}"
            return 1
        if close < or_lo:
            self.why = f"broke the 8:30-anchored range low {or_lo:.0f}"
            return -1
        if self._dir != 0 and or_lo <= close <= or_hi:
            self.why = "back inside the anchored range"
            return 0
        return None


def _ist_minutes_of(ts) -> int:
    ist = ts.astimezone(IST)
    return ist.hour * 60 + ist.minute
