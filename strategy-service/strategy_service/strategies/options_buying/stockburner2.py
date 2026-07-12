"""Stock Burner (Dinesh Kirola) — remaining strategies B2,B4,B6,B8,B9 (B1,B3,B5,B7
already coded as ema_9_20/crt_range/amd_session/order_block_fvg)."""

from pydantic import BaseModel, Field

from strategy_service.indicators import ema
from strategy_service.strategies.options_buying._base import OptionBuyStrategy, buy_meta, today_bars
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe


@register_strategy
class Sb9EmaBounce(OptionBuyStrategy):
    metadata = buy_meta(
        "sb_9ema_bounce", "Stock Burner: 9 EMA Scalping (B2)", "options_scalp",
        "Trend-scalp along the 9-EMA: buy when price pulls to and bounces off the "
        "9-EMA in an up-move (mirrored short in a down-move).",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=9, ge=3)

    @property
    def warmup(self) -> int:
        return self.params.period + 4

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        e = ema(closes, self.params.period)
        bar = ctx.current
        up_trend = e[-1] > e[-4]
        down_trend = e[-1] < e[-4]
        if up_trend and bar.low <= e[-1] and bar.close > e[-1] and bar.close > bar.open:
            self.why = "bounced off the 9-EMA in an uptrend"
            return 1
        if down_trend and bar.high >= e[-1] and bar.close < e[-1] and bar.close < bar.open:
            self.why = "rejected at the 9-EMA in a downtrend"
            return -1
        if (self._dir > 0 and bar.close < e[-1]) or (self._dir < 0 and bar.close > e[-1]):
            self.why = "9-EMA lost"
            return 0
        return None


@register_strategy
class SbLiquiditySweep(OptionBuyStrategy):
    metadata = buy_meta(
        "sb_liquidity_sweep", "Stock Burner: Liquidity Sweep Entries (B4)", "options_intraday",
        "Price sweeps a prior swing high/low (grabbing liquidity) then reverses; enter "
        "on the reversal confirmation.",
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
            self.why = f"swept liquidity above {hi:.0f}, reversed"
            return -1
        if bar.low < lo and bar.close > lo:
            self.why = f"swept liquidity below {lo:.0f}, reversed"
            return 1
        if self._dir != 0 and lo <= bar.close <= hi:
            self.why = "back inside range"
            return 0
        return None


@register_strategy
class SbVolumeProfile(OptionBuyStrategy):
    metadata = buy_meta(
        "sb_volume_profile", "Stock Burner: Volume Profile Strategy (B6)", "options_intraday",
        "NSE publishes no index volume, so this uses TIME-AT-PRICE (bars revisiting a "
        "level) as the proxy for a high-volume node — fade/deflect there, as the real "
        "strategy would at an HVN.",
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
        node_k = max(counts, key=counts.get)
        node = node_k * bucket
        bar = ctx.current
        if bar.high >= node and bar.close < node:
            self.why = f"deflected at high-time-at-price node {node:.0f}"
            return -1
        if bar.low <= node and bar.close > node:
            self.why = f"deflected off high-time-at-price node {node:.0f}"
            return 1
        return None


@register_strategy
class SbSidewaysConsolidation(OptionBuyStrategy):
    metadata = buy_meta(
        "sb_sideways_consolidation", "Stock Burner: Sideways/Consolidation Strategy (B8)", "options_scalp",
        "Range-fade within a defined consolidation box until a decisive break — same "
        "mechanic as A9/C8, Stock Burner's framing of it.",
        Timeframe.M5, "range-bound",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=16, ge=8)
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
            self.why = f"box support {lo:.0f}"
            return 1
        if bar.high >= hi * 0.9995:
            self.why = f"box resistance {hi:.0f}"
            return -1
        if (self._dir > 0 and bar.close >= mid) or (self._dir < 0 and bar.close <= mid):
            self.why = "box mid reached"
            return 0
        return None


@register_strategy
class SbSimpleOrb(OptionBuyStrategy):
    metadata = buy_meta(
        "sb_simple_orb", "Stock Burner: Simple Option-Buying Setup (B9)", "options_scalp",
        "Beginner single-confirmation entry: break of the first-15-min range with the "
        "prevailing trend.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 1

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        n = self.params.range_bars
        if len(day) <= n:
            return 0
        hi = max(b.high for b in day[:n])
        lo = min(b.low for b in day[:n])
        close = ctx.current.close
        if close > hi:
            self.why = f"broke opening range high {hi:.0f}"
            return 1
        if close < lo:
            self.why = f"broke opening range low {lo:.0f}"
            return -1
        self.why = "inside opening range"
        return 0
