"""Neeraj Joshi — remaining ICT/SMC strategies E2,E4,E5,E6,E7,E8 (E1=ict_judas_swing,
E3=cisd_flip already coded). E7 (SMT) is the one genuine cross-symbol strategy here,
using _cross_symbol's lazy BANKNIFTY lookup."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr
from strategy_service.strategies.options_buying import _cross_symbol
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, prev_day_hlc, swing_points, today_bars,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe


@register_strategy
class NjOrderBlockPoi(OptionBuyStrategy):
    metadata = buy_meta(
        "nj_order_block_poi", "Neeraj Joshi: Order Block + POI (E2)", "options_intraday",
        "Order-block retest refined to a specific point-of-interest: the 50% level of "
        "the order block, rather than the whole block.",
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
        self._poi = None

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars
        a = atr(bars, self.params.atr_period)[-1]
        impulse, prior = bars[-1], bars[-2]
        is_up = (impulse.close - impulse.open) > self.params.impulse_mult * a
        is_down = (impulse.open - impulse.close) > self.params.impulse_mult * a
        if is_up and prior.close < prior.open:
            self._poi = ((prior.low + prior.high) / 2, 1, 0)
        elif is_down and prior.close > prior.open:
            self._poi = ((prior.low + prior.high) / 2, -1, 0)
        if self._poi:
            level, d, age = self._poi
            age += 1
            if age > self.params.retest_within:
                self._poi = None
                return None
            bar = ctx.current
            touched = (d > 0 and bar.low <= level) or (d < 0 and bar.high >= level)
            if touched:
                self.why = f"POI {level:.0f} (50% of OB) retested"
                self._poi = None
                return d
            self._poi = (level, d, age)
        return None


@register_strategy
class NjLiquidityFib(OptionBuyStrategy):
    metadata = buy_meta(
        "nj_liquidity_fib", "Neeraj Joshi: Liquidity Sweep + Fibonacci (E4)", "options_intraday",
        "After a liquidity sweep, enters on the retrace into the 62-79% OTE Fibonacci "
        "zone of the reversal leg, rather than an immediate re-entry.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        lookback: int = Field(default=20, ge=8)
        ote_lo: float = Field(default=0.62, gt=0, lt=1)
        ote_hi: float = Field(default=0.79, gt=0, lt=1)

    @property
    def warmup(self) -> int:
        return self.params.lookback + 5

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._leg = None

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.lookback - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bar = ctx.current
        if bar.high > hi and bar.close < hi:
            self._leg = (hi, bar.low, -1)  # sweep-high reversal leg down (approx anchor)
        elif bar.low < lo and bar.close > lo:
            self._leg = (bar.high, lo, 1)
        if self._leg:
            top, bot, d = self._leg
            rng = top - bot
            if rng <= 0:
                self._leg = None
                return None
            if d > 0:
                zone_lo = bot + rng * self.params.ote_lo
                zone_hi = bot + rng * self.params.ote_hi
            else:
                zone_lo = top - rng * self.params.ote_hi
                zone_hi = top - rng * self.params.ote_lo
            if zone_lo <= bar.close <= zone_hi:
                self.why = f"retraced into the {self.params.ote_lo:.0%}-{self.params.ote_hi:.0%} OTE zone"
                self._leg = None
                return d
        return None


@register_strategy
class NjPremiumDiscount(OptionBuyStrategy):
    metadata = buy_meta(
        "nj_premium_discount", "Neeraj Joshi: Premium & Discount Zones (E5)", "options_intraday",
        "Only buys CE in the 'discount' half (below 50%) of the recent dealing range, "
        "only buys PE in the 'premium' half (above 50%) — an entry-location gate on a "
        "simple trend trigger.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=30, ge=15)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        mid = (hi + lo) / 2
        bar = ctx.current
        prev = ctx.bars[-2]
        if bar.close < mid and bar.close > prev.close:
            self.why = "in discount zone, turning up"
            return 1
        if bar.close > mid and bar.close < prev.close:
            self.why = "in premium zone, turning down"
            return -1
        return None


@register_strategy
class NjDailyBias(OptionBuyStrategy):
    metadata = buy_meta(
        "nj_daily_bias", "Neeraj Joshi: Daily Bias (E6)", "options_intraday",
        "Same daily-bias mechanic as Booming Bulls' D6, Neeraj Joshi's ICT framing of it.",
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
        bullish = close_prev > (high + low) / 2
        bar = ctx.current
        if bullish and bar.close > day[0].open:
            self.why = "ICT daily bias bullish"
            return 1
        if not bullish and bar.close < day[0].open:
            self.why = "ICT daily bias bearish"
            return -1
        return 0


@register_strategy
class NjSmtDivergence(OptionBuyStrategy):
    metadata = buy_meta(
        "nj_smt_divergence", "Neeraj Joshi: SMT Divergence (E7)", "options_intraday",
        "Smart Money Technique: NIFTY makes a new swing extreme that BANKNIFTY fails to "
        "confirm (or vice versa) -> the divergence signals a reversal. The one strategy "
        "in this catalog that genuinely needs a second instrument; looks up BANKNIFTY's "
        "aligned close via a direct Mongo query (see _cross_symbol.py) since the engine's "
        "own contract only feeds one instrument's bars at a time.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        lookback: int = Field(default=20, ge=8)

    @property
    def warmup(self) -> int:
        return self.params.lookback + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        window = ctx.bars[-self.params.lookback - 1: -1]
        n_hi, n_lo = max(b.high for b in window), min(b.low for b in window)
        if bar.high <= n_hi and bar.low >= n_lo:
            return None
        bn_close = _cross_symbol.close_at("BANKNIFTY", ctx.current.timeframe.value, bar.ts)
        if bn_close is None:
            return None
        bn_window_closes = []
        for b in window:
            c = _cross_symbol.close_at("BANKNIFTY", ctx.current.timeframe.value, b.ts)
            if c is not None:
                bn_window_closes.append(c)
        if len(bn_window_closes) < len(window) * 0.7:
            return None  # not enough aligned BANKNIFTY data to judge divergence
        bn_hi, bn_lo = max(bn_window_closes), min(bn_window_closes)
        if bar.high > n_hi and bn_close < bn_hi:
            self.why = "NIFTY new high, BANKNIFTY failed to confirm — SMT bearish"
            return -1
        if bar.low < n_lo and bn_close > bn_lo:
            self.why = "NIFTY new low, BANKNIFTY failed to confirm — SMT bullish"
            return 1
        return None


@register_strategy
class NjSupplyDemandSmc(OptionBuyStrategy):
    metadata = buy_meta(
        "nj_supply_demand_smc", "Neeraj Joshi: Supply & Demand + SMC (E8)", "options_intraday",
        "Same supply/demand fade mechanic as A7, combined with an SMC-style trend "
        "filter, Neeraj Joshi's curriculum framing.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        lookback: int = Field(default=40, ge=15)
        pivot_strength: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.lookback + self.params.pivot_strength * 2

    def direction(self, ctx: StrategyContext) -> int | None:
        highs, lows = swing_points(ctx.bars[-self.params.lookback:], self.params.pivot_strength)
        if len(highs) < 2 or len(lows) < 2:
            return None
        smc_trend_up = highs[-1] > highs[-2] and lows[-1] > lows[-2]
        smc_trend_down = highs[-1] < highs[-2] and lows[-1] < lows[-2]
        bar = ctx.current
        if smc_trend_up and bar.low <= lows[-1] * 1.001 and bar.close > lows[-1]:
            self.why = "SMC uptrend + demand-zone hold"
            return 1
        if smc_trend_down and bar.high >= highs[-1] * 0.999 and bar.close < highs[-1]:
            self.why = "SMC downtrend + supply-zone reject"
            return -1
        return None
