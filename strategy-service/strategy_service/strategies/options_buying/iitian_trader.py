"""IITian Trader (Saurabh Maurya) — 5 strategies (J1-J5). J3 (max pain) and J4 (OI
buildup) both need the live option chain/OI, which isn't stored historically on this
platform — both run as clearly-labeled PRICE-ONLY proxies of the real OI-based idea."""

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, ema
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, swing_points,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe


@register_strategy
class ItFakeBreakout(OptionBuyStrategy):
    metadata = buy_meta(
        "it_fake_breakout", "IITian Trader: Fake Breakout/Breakdown (J1)", "options_intraday",
        "Same failed-breakout-fade mechanic as A1/F4/I2, this channel's own framing.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=12, ge=5)
        confirm_within: int = Field(default=2, ge=1)

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
                self.why = "fake breakout, fading down"
                return -1
            elif d < 0 and bar.close > lo:
                self._trap = None
                self.why = "fake breakdown, fading up"
                return 1
            else:
                self._trap = (age, d)
        if bar.close > hi:
            self._trap = (0, 1)
        elif bar.close < lo:
            self._trap = (0, -1)
        return None


@register_strategy
class ItHeatmapBreakout(OptionBuyStrategy):
    metadata = buy_meta(
        "it_heatmap_breakout", "IITian Trader: Breakout by Heatmap/Indicators (J2)", "options_breakout",
        "No heatmap tool exists here; the 'indicator cluster' is proxied by requiring "
        "TWO independent trend indicators (ADX and EMA slope) to agree before the "
        "breakout is taken.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=20, ge=10)
        adx_period: int = Field(default=14, ge=5)
        trend_ema: int = Field(default=21, ge=5)

    @property
    def warmup(self) -> int:
        return max(self.params.range_bars, self.params.adx_period * 3, self.params.trend_ema) + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        adx_line, plus_di, minus_di = adx(ctx.bars, self.params.adx_period)
        e = ema(ctx.closes, self.params.trend_ema)
        bar = ctx.current
        adx_confirms_up = adx_line[-1] > 20 and plus_di[-1] > minus_di[-1]
        adx_confirms_down = adx_line[-1] > 20 and minus_di[-1] > plus_di[-1]
        ema_confirms_up = e[-1] > e[-5]
        ema_confirms_down = e[-1] < e[-5]
        if bar.close > hi and adx_confirms_up and ema_confirms_up:
            self.why = "breakout confirmed by ADX + EMA cluster"
            return 1
        if bar.close < lo and adx_confirms_down and ema_confirms_down:
            self.why = "breakdown confirmed by ADX + EMA cluster"
            return -1
        return 0


@register_strategy
class ItMaxPainProxy(OptionBuyStrategy):
    metadata = buy_meta(
        "it_max_pain_proxy", "IITian Trader: Max Pain Strategy (J3)", "options_swing",
        "The real strategy needs the live option-chain OI to compute max pain, which "
        "isn't stored historically here. Proxies the well-documented pinning tendency "
        "instead: as expiry (Tuesday) nears, price gravitates toward the nearest round "
        "100-point strike — trades the reversion toward that level.",
        Timeframe.D1, "range-bound",
    )

    class Params(BaseModel):
        strike_step: float = Field(default=100.0, gt=0)
        days_before_expiry: int = Field(default=2, ge=1)

    @property
    def warmup(self) -> int:
        return 5

    def direction(self, ctx: StrategyContext) -> int | None:
        from datetime import timedelta, timezone

        IST = timezone(timedelta(hours=5, minutes=30))
        weekday = ctx.current.ts.astimezone(IST).weekday()
        days_to_tue = (1 - weekday) % 7
        if days_to_tue > self.params.days_before_expiry:
            return 0
        close = ctx.current.close
        nearest_round = round(close / self.params.strike_step) * self.params.strike_step
        dist_pct = (close - nearest_round) / close * 100
        if dist_pct > 0.1:
            self.why = f"above pinning strike {nearest_round:.0f}, expiry approaching — reversion down"
            return -1
        if dist_pct < -0.1:
            self.why = f"below pinning strike {nearest_round:.0f}, expiry approaching — reversion up"
            return 1
        return 0


@register_strategy
class ItBuildupProxy(OptionBuyStrategy):
    metadata = buy_meta(
        "it_buildup_proxy", "IITian Trader: Buildup Strategy (J4)", "options_intraday",
        "The real strategy reads long/short buildup from OI+price quadrants, which "
        "needs option-chain OI not stored historically here. Proxies 'buildup' with "
        "sustained price momentum (persistent same-direction closes) as the stand-in "
        "for accumulating positioning.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        run_bars: int = Field(default=4, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.run_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        n = self.params.run_bars
        ups = all(closes[-i] > closes[-i - 1] for i in range(1, n + 1))
        downs = all(closes[-i] < closes[-i - 1] for i in range(1, n + 1))
        if ups:
            self.why = f"{n}-bar persistent buildup, long"
            return 1
        if downs:
            self.why = f"{n}-bar persistent buildup, short"
            return -1
        if (self._dir > 0 and closes[-1] < closes[-2]) or (self._dir < 0 and closes[-1] > closes[-2]):
            return 0
        return None


@register_strategy
class ItMarketStructure(OptionBuyStrategy):
    metadata = buy_meta(
        "it_market_structure", "IITian Trader: Market-Structure Reading (J5)", "options_intraday",
        "Higher-high/higher-low vs lower-high/lower-low swing-structure bias, as a "
        "standalone entry.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        lookback: int = Field(default=35, ge=15)
        pivot_strength: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.lookback + self.params.pivot_strength * 2

    def direction(self, ctx: StrategyContext) -> int | None:
        highs, lows = swing_points(ctx.bars[-self.params.lookback:], self.params.pivot_strength)
        if len(highs) < 2 or len(lows) < 2:
            return None
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            self.why = "HH/HL structure"
            return 1
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            self.why = "LH/LL structure"
            return -1
        self.why = "mixed structure"
        return 0
