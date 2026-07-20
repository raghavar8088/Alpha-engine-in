"""Defined-risk DIRECTIONAL credit spreads — bull put and bear call.

A credit spread is the honest way to express "I think price won't go below X" without
taking unbounded risk. You sell the near strike, buy a further one, and the difference in
strikes minus the credit is the exact worst case — knowable at entry, blocked as margin,
and impossible to exceed no matter how the tape gaps.

Compared to the neutral book: these need a directional read to be right (or at least not
badly wrong), but they only need it to be right *loosely*. A bull put spread makes full
credit whether price rallies, drifts, or chops sideways — it only loses if price falls
through the short strike. That "two out of three outcomes win" property is the entire
appeal, and it is why spreads carry a wider gate than the naked book does.
"""

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, ema, rsi, sma
from strategy_service.strategies.options_selling._base import (
    LegSpec,
    OptionSellStrategy,
    range_position,
    sell_meta,
    vol_rank,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

INTRADAY, POSITIONAL = "options_sell_intraday", "options_sell_positional"
TF15, TFD = Timeframe.M15, Timeframe.D1


def _put_spread(short_delta: float, width_pct: float) -> list[LegSpec]:
    """Short put by delta, long put a fixed distance below it. Width is fixed rather
    than delta-based so the max loss stays a predictable number."""
    return [
        LegSpec("PE", sell=True, target_delta=short_delta),
        LegSpec("PE", sell=False, otm_pct=-width_pct),
    ]


def _call_spread(short_delta: float, width_pct: float) -> list[LegSpec]:
    return [
        LegSpec("CE", sell=True, target_delta=short_delta),
        LegSpec("CE", sell=False, otm_pct=+width_pct),
    ]


# --- bull put spreads (sell into strength / support) ------------------------------


@register_strategy
class TrendBullPutSpread(OptionSellStrategy):
    metadata = sell_meta(
        "sell_trend_bull_put", "Sell: Trend Bull Put Spread", INTRADAY,
        "Price above a rising EMA stack: sell the 20-delta put spread under the trend. "
        "Wins on up, flat and mildly down tape — loses only through the short strike.",
        TF15, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=20, ge=5)
        slow: int = Field(default=50, ge=10)
        short_delta: float = Field(default=0.20, gt=0, lt=0.5)
        width_pct: float = Field(default=0.02, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.slow + 3

    def want_open(self, ctx: StrategyContext) -> bool:
        closes = ctx.closes
        f, s = ema(closes, self.params.fast), ema(closes, self.params.slow)
        rising = f[-1] > s[-1] and f[-1] > f[-2]
        if not (rising and ctx.current.close > f[-1]):
            return False
        self.why = f"above rising EMA{self.params.fast} ({f[-1]:.0f}>{s[-1]:.0f})"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return _put_spread(self.params.short_delta, self.params.width_pct)


@register_strategy
class DipBullPutSpread(OptionSellStrategy):
    metadata = sell_meta(
        "sell_dip_bull_put", "Sell: Dip Bull Put Spread", INTRADAY,
        "Sells the put spread into an oversold RSI bounce inside an intact uptrend — "
        "premium is fattest exactly when the dip has just scared everyone.",
        TF15, "trending",
    )

    class Params(BaseModel):
        rsi_period: int = Field(default=14, ge=2)
        oversold: float = Field(default=38.0, gt=0, lt=60)
        trend_period: int = Field(default=50, ge=10)
        short_delta: float = Field(default=0.22, gt=0, lt=0.5)
        width_pct: float = Field(default=0.02, gt=0)

    @property
    def warmup(self) -> int:
        return max(self.params.trend_period, self.params.rsi_period) + 3

    def want_open(self, ctx: StrategyContext) -> bool:
        closes = ctx.closes
        trend_ok = ctx.current.close > sma(closes, self.params.trend_period)[-1]
        r = rsi(closes, self.params.rsi_period)
        bouncing = r[-2] < self.params.oversold <= r[-1]
        if not (trend_ok and bouncing):
            return False
        self.why = f"RSI bounced off {r[-2]:.0f} inside an uptrend"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return _put_spread(self.params.short_delta, self.params.width_pct)


@register_strategy
class RangeLowBullPutSpread(OptionSellStrategy):
    metadata = sell_meta(
        "sell_range_low_bull_put", "Sell: Range-Low Bull Put Spread", INTRADAY,
        "Price in the bottom third of its 20-bar range with the trend not breaking down: "
        "sell the put spread beneath the range floor.",
        TF15, "range-bound",
    )

    class Params(BaseModel):
        range_period: int = Field(default=20, ge=5)
        max_position: float = Field(default=0.35, gt=0, lt=1)
        adx_period: int = Field(default=14, ge=2)
        max_adx: float = Field(default=25.0, gt=0)
        short_delta: float = Field(default=0.20, gt=0, lt=0.5)
        width_pct: float = Field(default=0.02, gt=0)

    @property
    def warmup(self) -> int:
        return max(self.params.range_period, 2 * self.params.adx_period + 1) + 2

    def want_open(self, ctx: StrategyContext) -> bool:
        pos = range_position(ctx.bars, self.params.range_period)
        adx_now = adx(ctx.bars, self.params.adx_period)[0][-1]
        # Low in the range is only an opportunity if the range is HOLDING. A low reading
        # with a strong trend is a breakdown in progress, which is the one tape that
        # runs a put spread over.
        if pos > self.params.max_position or adx_now > self.params.max_adx:
            return False
        self.why = f"range position {pos:.2f} with ADX {adx_now:.1f} — floor holding"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return _put_spread(self.params.short_delta, self.params.width_pct)


@register_strategy
class MonthlyBullPutSpread(OptionSellStrategy):
    metadata = sell_meta(
        "sell_monthly_bull_put", "Sell: Monthly Bull Put Spread", POSITIONAL,
        "Daily uptrend intact: sell the monthly 15-delta put spread and hold. The index's "
        "long-run upward drift is the tailwind this one is actually harvesting.",
        TFD, "trending",
    )

    class Params(BaseModel):
        trend_period: int = Field(default=50, ge=10)
        short_delta: float = Field(default=0.15, gt=0, lt=0.5)
        width_pct: float = Field(default=0.04, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.trend_period + 3

    def want_open(self, ctx: StrategyContext) -> bool:
        s = sma(ctx.closes, self.params.trend_period)
        if not (ctx.current.close > s[-1] and s[-1] > s[-2]):
            return False
        self.why = f"daily close above a rising SMA{self.params.trend_period}"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return _put_spread(self.params.short_delta, self.params.width_pct)


# --- bear call spreads (sell into weakness / resistance) --------------------------


@register_strategy
class TrendBearCallSpread(OptionSellStrategy):
    metadata = sell_meta(
        "sell_trend_bear_call", "Sell: Trend Bear Call Spread", INTRADAY,
        "Price below a falling EMA stack: sell the 20-delta call spread above the "
        "downtrend. The mirror of the bull put, and structurally the harder side — "
        "index drift works against it.",
        TF15, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=20, ge=5)
        slow: int = Field(default=50, ge=10)
        short_delta: float = Field(default=0.20, gt=0, lt=0.5)
        width_pct: float = Field(default=0.02, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.slow + 3

    def want_open(self, ctx: StrategyContext) -> bool:
        closes = ctx.closes
        f, s = ema(closes, self.params.fast), ema(closes, self.params.slow)
        falling = f[-1] < s[-1] and f[-1] < f[-2]
        if not (falling and ctx.current.close < f[-1]):
            return False
        self.why = f"below falling EMA{self.params.fast} ({f[-1]:.0f}<{s[-1]:.0f})"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return _call_spread(self.params.short_delta, self.params.width_pct)


@register_strategy
class RallyFadeBearCallSpread(OptionSellStrategy):
    metadata = sell_meta(
        "sell_rally_fade_bear_call", "Sell: Rally-Fade Bear Call Spread", INTRADAY,
        "Sells the call spread into an overbought push that is still under a falling "
        "longer-term average — fading strength that the bigger trend disagrees with.",
        TF15, "trending",
    )

    class Params(BaseModel):
        rsi_period: int = Field(default=14, ge=2)
        overbought: float = Field(default=62.0, gt=40, lt=100)
        trend_period: int = Field(default=50, ge=10)
        short_delta: float = Field(default=0.22, gt=0, lt=0.5)
        width_pct: float = Field(default=0.02, gt=0)

    @property
    def warmup(self) -> int:
        return max(self.params.trend_period, self.params.rsi_period) + 3

    def want_open(self, ctx: StrategyContext) -> bool:
        closes = ctx.closes
        below_trend = ctx.current.close < sma(closes, self.params.trend_period)[-1]
        r = rsi(closes, self.params.rsi_period)
        faded = r[-2] > self.params.overbought >= r[-1]
        if not (below_trend and faded):
            return False
        self.why = f"RSI rolled over from {r[-2]:.0f} beneath the trend"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return _call_spread(self.params.short_delta, self.params.width_pct)


@register_strategy
class RangeHighBearCallSpread(OptionSellStrategy):
    metadata = sell_meta(
        "sell_range_high_bear_call", "Sell: Range-High Bear Call Spread", INTRADAY,
        "Price in the top third of its 20-bar range with no trend to carry it through: "
        "sell the call spread above the ceiling.",
        TF15, "range-bound",
    )

    class Params(BaseModel):
        range_period: int = Field(default=20, ge=5)
        min_position: float = Field(default=0.65, gt=0, lt=1)
        adx_period: int = Field(default=14, ge=2)
        max_adx: float = Field(default=25.0, gt=0)
        short_delta: float = Field(default=0.20, gt=0, lt=0.5)
        width_pct: float = Field(default=0.02, gt=0)

    @property
    def warmup(self) -> int:
        return max(self.params.range_period, 2 * self.params.adx_period + 1) + 2

    def want_open(self, ctx: StrategyContext) -> bool:
        pos = range_position(ctx.bars, self.params.range_period)
        adx_now = adx(ctx.bars, self.params.adx_period)[0][-1]
        if pos < self.params.min_position or adx_now > self.params.max_adx:
            return False
        self.why = f"range position {pos:.2f} with ADX {adx_now:.1f} — ceiling holding"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return _call_spread(self.params.short_delta, self.params.width_pct)


@register_strategy
class RichVolBearCallSpread(OptionSellStrategy):
    metadata = sell_meta(
        "sell_rich_vol_bear_call", "Sell: Rich-Vol Bear Call Spread", INTRADAY,
        "Call spreads sold only when realized vol is elevated — upside premium is dearest "
        "right after a scare, and that is when the spread is worth selling.",
        TF15, "high-volatility",
    )

    class Params(BaseModel):
        vol_window: int = Field(default=20, ge=5)
        vol_lookback: int = Field(default=60, ge=20)
        min_vol_rank: float = Field(default=0.60, ge=0, le=1)
        trend_period: int = Field(default=50, ge=10)
        short_delta: float = Field(default=0.18, gt=0, lt=0.5)
        width_pct: float = Field(default=0.025, gt=0)

    @property
    def warmup(self) -> int:
        return max(self.params.vol_window + self.params.vol_lookback + 3, self.params.trend_period + 3)

    def want_open(self, ctx: StrategyContext) -> bool:
        rank = vol_rank(ctx.closes, self.params.vol_window, self.params.vol_lookback)
        if rank is None or rank < self.params.min_vol_rank:
            return False
        if ctx.current.close > sma(ctx.closes, self.params.trend_period)[-1]:
            return False  # never sell calls into a tape that is already grinding up
        self.why = f"vol rank {rank:.2f} beneath the trend"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return _call_spread(self.params.short_delta, self.params.width_pct)
