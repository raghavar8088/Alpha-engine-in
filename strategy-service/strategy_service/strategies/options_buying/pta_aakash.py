"""Pro Trader Aakash — 10 strategies (A1-A10) from
D:/INDIAN MARKET/YOUTUBE_76_STRATEGIES_FULL_DETAILS.md. Mechanical form of each named
setup per that doc; channel names are confirmed from real video titles, mechanics are
the standard published form of each technique (not per-video transcript-verified)."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, prev_day_hlc, swing_points, today_bars,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe


@register_strategy
class PtaTrap(OptionBuyStrategy):
    metadata = buy_meta(
        "pta_trap", "Pro Trader Aakash: Option-Buying Trap (A1)", "options_intraday",
        "Price closes beyond an intraday range extreme, trapping breakout traders, then "
        "closes back inside within 3 bars — fade the failed break.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=8, ge=3)
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
                self.why = f"trap above {hi:.0f} failed, faded down"
                return -1
            elif d < 0 and bar.close > lo:
                self._trap = None
                self.why = f"trap below {lo:.0f} failed, faded up"
                return 1
            else:
                self._trap = (age, d)
        if bar.close > hi:
            self._trap = (0, 1)
        elif bar.close < lo:
            self._trap = (0, -1)
        return None


@register_strategy
class PtaSuperScalping(OptionBuyStrategy):
    metadata = buy_meta(
        "pta_super_scalping", "Pro Trader Aakash: Super Scalping (A2)", "options_scalp",
        "A strong full-body candle after a one-bar pause, in the trend direction; exits "
        "on the first opposite-color candle.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        body_ratio: float = Field(default=0.65, gt=0, lt=1)

    @property
    def warmup(self) -> int:
        return 5

    def direction(self, ctx: StrategyContext) -> int | None:
        bar, prev = ctx.bars[-1], ctx.bars[-2]
        rng = bar.high - bar.low
        body = abs(bar.close - bar.open)
        pause = abs(prev.close - prev.open) < (prev.high - prev.low) * 0.4
        if rng > 0 and body / rng > self.params.body_ratio and pause:
            if bar.close > bar.open:
                self.why = "strong full-body candle after a pause, bullish"
                return 1
            self.why = "strong full-body candle after a pause, bearish"
            return -1
        if (self._dir > 0 and bar.close < bar.open) or (self._dir < 0 and bar.close > bar.open):
            self.why = "opposite-color candle"
            return 0
        return None


@register_strategy
class PtaPullbackScalping(OptionBuyStrategy):
    metadata = buy_meta(
        "pta_pullback_scalping", "Pro Trader Aakash: Pullback Scalping (A3)", "options_scalp",
        "In an established intraday trend, buy the shallow pullback to a fast EMA that "
        "resumes with a continuation candle.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        fast_ema: int = Field(default=8, ge=3)
        trend_ema: int = Field(default=21, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        f = ema(closes, self.params.fast_ema)
        t = ema(closes, self.params.trend_ema)
        bar = ctx.current
        if f[-1] > t[-1] and bar.low <= f[-1] and bar.close > f[-1] and bar.close > bar.open:
            self.why = "pullback to fast EMA resumed the uptrend"
            return 1
        if f[-1] < t[-1] and bar.high >= f[-1] and bar.close < f[-1] and bar.close < bar.open:
            self.why = "pullback to fast EMA resumed the downtrend"
            return -1
        if (self._dir > 0 and bar.close < t[-1]) or (self._dir < 0 and bar.close > t[-1]):
            self.why = "trend EMA lost"
            return 0
        return None


@register_strategy
class PtaLiquidityAwareEntry(OptionBuyStrategy):
    metadata = buy_meta(
        "pta_liquidity_aware_entry", "Pro Trader Aakash: Stop-Hunt-Aware Reversal (A4)", "options_intraday",
        "A4 is a stop-placement rule in the source (place SL beyond the liquidity pool, "
        "not the obvious level), not a standalone entry. Implemented as its natural "
        "companion signal: enter only AFTER a swing-low/high wick sweep (where retail "
        "stops cluster) reverses — the setup that rule is meant to protect.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        lookback: int = Field(default=15, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.lookback + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.lookback - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bar = ctx.current
        if bar.low < lo and bar.close > lo:
            self.why = f"swept the liquidity pool below {lo:.0f} and reclaimed"
            return 1
        if bar.high > hi and bar.close < hi:
            self.why = f"swept the liquidity pool above {hi:.0f} and rejected"
            return -1
        if self._dir != 0 and lo <= bar.close <= hi:
            self.why = "back inside the range"
            return 0
        return None


@register_strategy
class PtaRrGate(OptionBuyStrategy):
    metadata = buy_meta(
        "pta_rr_gate", "Pro Trader Aakash: 1:3 RR Option-Buying Plan (A5)", "options_intraday",
        "A5 is a risk-reward FILTER in the source (only take trades whose measured "
        "target is >=3x the risk), not its own entry. Implemented as a breakout entry "
        "that self-computes the RR from the measured range projection and only fires "
        "when that ratio clears 3:1.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=20, ge=10)
        min_rr: float = Field(default=3.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        rng = hi - lo
        bar = ctx.current
        if rng <= 0:
            return 0
        if bar.close > hi:
            risk = bar.close - lo
            reward = rng  # measured-move projection above the breakout
            if risk > 0 and reward / risk >= self.params.min_rr:
                self.why = f"breakout clears {self.params.min_rr:.0f}:1 RR (measured move)"
                return 1
        if bar.close < lo:
            risk = hi - bar.close
            reward = rng
            if risk > 0 and reward / risk >= self.params.min_rr:
                self.why = f"breakdown clears {self.params.min_rr:.0f}:1 RR (measured move)"
                return -1
        return 0


@register_strategy
class PtaBreakoutDirection(OptionBuyStrategy):
    metadata = buy_meta(
        "pta_breakout_direction", "Pro Trader Aakash: 3 Ways to Find Breakout Direction (A6)", "options_breakout",
        "Confirms breakout direction via 2 of 3: retest-hold, higher-high/higher-low "
        "follow-through, and prior-range flipping to support (or the bearish mirror).",
        Timeframe.M15, "high-volatility",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=20, ge=10)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 6

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bars = ctx.bars
        bar = bars[-1]
        highs, lows = swing_points(bars[-10:], 2)
        hh_hl = len(highs) >= 2 and len(lows) >= 2 and highs[-1] > highs[-2] and lows[-1] > lows[-2]
        ll_lh = len(highs) >= 2 and len(lows) >= 2 and highs[-1] < highs[-2] and lows[-1] < lows[-2]
        retest_hold_up = any(b.low <= hi for b in bars[-4:-1]) and bar.close > hi
        retest_hold_down = any(b.high >= lo for b in bars[-4:-1]) and bar.close < lo
        flip_support = bar.close > hi and bars[-2].low >= hi * 0.998
        flip_resist = bar.close < lo and bars[-2].high <= lo * 1.002
        up_confirms = sum([retest_hold_up, hh_hl, flip_support])
        down_confirms = sum([retest_hold_down, ll_lh, flip_resist])
        if bar.close > hi and up_confirms >= 2:
            self.why = f"breakout confirmed by {up_confirms}/3 checks"
            return 1
        if bar.close < lo and down_confirms >= 2:
            self.why = f"breakdown confirmed by {down_confirms}/3 checks"
            return -1
        return 0


@register_strategy
class PtaSupplyDemandBankNifty(OptionBuyStrategy):
    metadata = buy_meta(
        "pta_supply_demand_bn", "Pro Trader Aakash: BankNifty Supply-Demand (A7)", "options_intraday",
        "Marks supply/demand zones (the last consolidation before a strong move); fades "
        "the first touch with the higher-timeframe trend.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        trend_ema: int = Field(default=50, ge=10)
        zone_lookback: int = Field(default=60, ge=20)
        pivot_strength: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.zone_lookback + self.params.pivot_strength * 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        trend = ema(closes, self.params.trend_ema)[-1]
        window = ctx.bars[-self.params.zone_lookback:]
        highs, lows = swing_points(window, self.params.pivot_strength)
        if not highs or not lows:
            return 0
        supply, demand = highs[-1], lows[-1]
        bar = ctx.current
        if bar.close < trend and bar.high >= supply and bar.close < supply:
            self.why = f"faded supply {supply:.0f} with the downtrend"
            return -1
        if bar.close > trend and bar.low <= demand and bar.close > demand:
            self.why = f"faded demand {demand:.0f} with the uptrend"
            return 1
        return 0


@register_strategy
class PtaSmartMoneyFlow(OptionBuyStrategy):
    metadata = buy_meta(
        "pta_smart_money_flow", "Pro Trader Aakash: Intraday SmartMoney Flow (A8)", "options_intraday",
        "A displacement candle leaves a gap (imbalance) between its neighbors; enter on "
        "the retrace back into that gap, with the displacement's direction.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        atr_period: int = Field(default=14, ge=5)
        disp_mult: float = Field(default=1.6, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 3

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._gap = None

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars
        a = atr(bars, self.params.atr_period)[-1]
        disp = bars[-2]
        is_disp_up = (disp.close - disp.open) > self.params.disp_mult * a
        is_disp_down = (disp.open - disp.close) > self.params.disp_mult * a
        if len(bars) >= 3:
            if is_disp_up and bars[-3].high < disp.low:
                self._gap = (bars[-3].high, disp.low, 1)
            elif is_disp_down and bars[-3].low > disp.high:
                self._gap = (disp.high, bars[-3].low, -1)
        if self._gap:
            lo, hi, d = self._gap
            close = ctx.current.close
            if d > 0 and lo <= close <= hi:
                self.why = f"retraced into the bullish imbalance [{lo:.0f}-{hi:.0f}]"
                self._gap = None
                return 1
            if d < 0 and lo <= close <= hi:
                self.why = f"retraced into the bearish imbalance [{lo:.0f}-{hi:.0f}]"
                self._gap = None
                return -1
        return None


@register_strategy
class PtaSidewaysBuying(OptionBuyStrategy):
    metadata = buy_meta(
        "pta_sideways_buying", "Pro Trader Aakash: Option Buying in Sideways Market (A9)", "options_scalp",
        "Range-scalp: buy the CE at range support, the PE at range resistance, exit at "
        "mid or the opposite band. Only when the range is wide enough to be worth it.",
        Timeframe.M5, "range-bound",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=20, ge=10)
        min_range_pct: float = Field(default=0.2, gt=0)

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
            self.why = f"tagged range support {lo:.0f}"
            return 1
        if bar.high >= hi * 0.9995:
            self.why = f"tagged range resistance {hi:.0f}"
            return -1
        if (self._dir > 0 and bar.close >= mid) or (self._dir < 0 and bar.close <= mid):
            self.why = "reached range mid"
            return 0
        return None


@register_strategy
class PtaAutomatedSignal(OptionBuyStrategy):
    metadata = buy_meta(
        "pta_automated_signal", "Pro Trader Aakash: Fully Automated Option-Buying (A10)", "options_intraday",
        "A10 is an execution wrapper around his own algo (Tradefinder), not a distinct "
        "edge — no independent setup is described. Implemented as a plain trend-momentum "
        "signal standing in for 'a generic automated trend signal', not his proprietary logic.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=10, ge=2)
        slow: int = Field(default=30, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.slow + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        f, s = ema(closes, self.params.fast)[-1], ema(closes, self.params.slow)[-1]
        self.why = f"auto-signal EMA{self.params.fast}/{self.params.slow}"
        return 1 if f > s else -1
