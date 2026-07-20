"""NAKED single-side sellers — short call or short put with no protective leg.

These are here because they are what a large share of real Indian retail option selling
actually is, and a library that modelled only defined-risk structures would be quietly
telling the user that the risky thing they might do is unmeasurable. It is measurable.
The point of running them through the same sweep as the condors is to produce the
comparison, on this app's own data, rather than asserting it.

WHAT MAKES THESE DIFFERENT, MECHANICALLY
----------------------------------------
Nothing in the strategy classes below. The difference is entirely downstream:

  * `options_service.margin` charges them on the SPAN+exposure basis — roughly 10% of
    notional per uncovered leg, against a defined-risk spread's few thousand rupees.
    A naked seller is using an order of magnitude more capital per unit of credit, and
    the sweep's return-on-margin column is where that shows up.
  * `max_profit_loss` reports their max loss as unbounded, and the selling metrics count
    them in `naked_trade_pct`, which the Phase 2 gate reads.
  * The engine's strike-pressure exit and hard capital stop are the ONLY things standing
    between one of these and an arbitrarily large loss. For a spread the wings are a
    structural guarantee; here the guarantee is a stop, and a stop can be gapped through.

Every strategy here therefore carries a deliberately NARROWER entry gate than its
defined-risk equivalent — further-out strikes, stricter regime filters, and a gap check
where the structure allows one. That asymmetry is intentional, not tuning: if a naked
strategy needs a loose gate to find trades, it should not be finding them.
"""

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, atr, ema, sma
from strategy_service.strategies.options_selling._base import (
    LegSpec,
    OptionSellStrategy,
    atr_pct,
    gap_pct,
    is_range_bound,
    range_position,
    sell_meta,
    vol_rank,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

INTRADAY, EXPIRY, POSITIONAL = (
    "options_sell_intraday", "options_sell_expiry", "options_sell_positional",
)
TF15, TFD = Timeframe.M15, Timeframe.D1


@register_strategy
class UptrendNakedPut(OptionSellStrategy):
    metadata = sell_meta(
        "sell_uptrend_naked_pe", "Sell: Uptrend Naked Put", INTRADAY,
        "Sells the 12-delta put naked while price holds above a rising EMA50. The "
        "index's upward drift is the edge; a gap down through the strike is the whole "
        "risk, and no stop can fully protect against one.",
        TF15, "trending",
    )

    class Params(BaseModel):
        trend_period: int = Field(default=50, ge=10)
        target_delta: float = Field(default=0.12, gt=0, lt=0.5)
        max_gap_pct: float = Field(default=0.6, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.trend_period + 3

    def want_open(self, ctx: StrategyContext) -> bool:
        if abs(gap_pct(ctx)) > self.params.max_gap_pct:
            return False  # a gapping session is precisely when naked shorts get hurt
        e = ema(ctx.closes, self.params.trend_period)
        if not (ctx.current.close > e[-1] and e[-1] > e[-2]):
            return False
        self.why = f"holding above a rising EMA{self.params.trend_period}"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return [LegSpec("PE", sell=True, target_delta=self.params.target_delta)]


@register_strategy
class DowntrendNakedCall(OptionSellStrategy):
    metadata = sell_meta(
        "sell_downtrend_naked_ce", "Sell: Downtrend Naked Call", INTRADAY,
        "Sells the 12-delta call naked beneath a falling EMA50. The genuinely unbounded "
        "leg of the library — a short call has no ceiling above it at all.",
        TF15, "trending",
    )

    class Params(BaseModel):
        trend_period: int = Field(default=50, ge=10)
        target_delta: float = Field(default=0.12, gt=0, lt=0.5)
        max_gap_pct: float = Field(default=0.6, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.trend_period + 3

    def want_open(self, ctx: StrategyContext) -> bool:
        if abs(gap_pct(ctx)) > self.params.max_gap_pct:
            return False
        e = ema(ctx.closes, self.params.trend_period)
        if not (ctx.current.close < e[-1] and e[-1] < e[-2]):
            return False
        self.why = f"under a falling EMA{self.params.trend_period}"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return [LegSpec("CE", sell=True, target_delta=self.params.target_delta)]


@register_strategy
class RangeFloorNakedPut(OptionSellStrategy):
    metadata = sell_meta(
        "sell_range_floor_naked_pe", "Sell: Range-Floor Naked Put", INTRADAY,
        "Sells the naked put under a range floor that is holding — low in the range, no "
        "trend, and the tape not expanding. Three filters because there are no wings.",
        TF15, "range-bound",
    )

    class Params(BaseModel):
        range_period: int = Field(default=20, ge=5)
        max_position: float = Field(default=0.40, gt=0, lt=1)
        adx_period: int = Field(default=14, ge=2)
        max_adx: float = Field(default=20.0, gt=0)
        max_atr_pct: float = Field(default=0.45, gt=0, description="tape-width ceiling, % of price")
        target_delta: float = Field(default=0.12, gt=0, lt=0.5)

    @property
    def warmup(self) -> int:
        return max(self.params.range_period, 2 * self.params.adx_period + 1) + 2

    def want_open(self, ctx: StrategyContext) -> bool:
        pos = range_position(ctx.bars, self.params.range_period)
        flat, adx_now = is_range_bound(ctx.bars, self.params.adx_period, self.params.max_adx)
        width = atr_pct(ctx.bars, self.params.adx_period)
        if pos > self.params.max_position or not flat or width > self.params.max_atr_pct:
            return False
        self.why = f"range floor {pos:.2f}, ADX {adx_now:.1f}, ATR {width:.2f}%"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return [LegSpec("PE", sell=True, target_delta=self.params.target_delta)]


@register_strategy
class ExpiryNakedPut(OptionSellStrategy):
    metadata = sell_meta(
        "sell_expiry_naked_pe", "Sell: Expiry-Day Naked Put", EXPIRY,
        "Near-expiry naked put on a quiet, non-gapping session. Fastest decay in the "
        "cycle paired with the least room to be wrong.",
        TF15, "range-bound",
    )

    class Params(BaseModel):
        max_gap_pct: float = Field(default=0.3, gt=0)
        adx_period: int = Field(default=14, ge=2)
        max_adx: float = Field(default=22.0, gt=0)
        target_delta: float = Field(default=0.15, gt=0, lt=0.5)

    @property
    def warmup(self) -> int:
        return 2 * self.params.adx_period + 4

    def want_open(self, ctx: StrategyContext) -> bool:
        g = gap_pct(ctx)
        flat, adx_now = is_range_bound(ctx.bars, self.params.adx_period, self.params.max_adx)
        if abs(g) > self.params.max_gap_pct or not flat:
            return False
        self.why = f"quiet expiry session: gap {g:+.2f}%, ADX {adx_now:.1f}"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return [LegSpec("PE", sell=True, target_delta=self.params.target_delta)]


@register_strategy
class MonthlyNakedPut(OptionSellStrategy):
    metadata = sell_meta(
        "sell_monthly_naked_pe", "Sell: Monthly Naked Put", POSITIONAL,
        "The cash-secured-put trade without the cash: sell the monthly 8-delta put in a "
        "daily uptrend and carry it. Held across every overnight in the cycle.",
        TFD, "trending",
    )

    class Params(BaseModel):
        trend_period: int = Field(default=50, ge=10)
        target_delta: float = Field(default=0.08, gt=0, lt=0.5)

    @property
    def warmup(self) -> int:
        return self.params.trend_period + 3

    def want_open(self, ctx: StrategyContext) -> bool:
        s = sma(ctx.closes, self.params.trend_period)
        if not (ctx.current.close > s[-1] and s[-1] > s[-2]):
            return False
        self.why = f"daily uptrend above SMA{self.params.trend_period}"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return [LegSpec("PE", sell=True, target_delta=self.params.target_delta)]


@register_strategy
class VolSpikeNakedPut(OptionSellStrategy):
    metadata = sell_meta(
        "sell_vol_spike_naked_pe", "Sell: Vol-Spike Naked Put", INTRADAY,
        "Sells the naked put after a volatility spike has already happened and the tape "
        "has stopped falling — harvesting the fear premium rather than the drift.",
        TF15, "high-volatility",
    )

    class Params(BaseModel):
        vol_window: int = Field(default=20, ge=5)
        vol_lookback: int = Field(default=60, ge=20)
        min_vol_rank: float = Field(default=0.70, ge=0, le=1)
        stabilize_bars: int = Field(default=3, ge=1, description="bars of no new low required")
        target_delta: float = Field(default=0.10, gt=0, lt=0.5)

    @property
    def warmup(self) -> int:
        return self.params.vol_window + self.params.vol_lookback + self.params.stabilize_bars + 3

    def want_open(self, ctx: StrategyContext) -> bool:
        rank = vol_rank(ctx.closes, self.params.vol_window, self.params.vol_lookback)
        if rank is None or rank < self.params.min_vol_rank:
            return False
        n = self.params.stabilize_bars
        recent = ctx.bars[-n:]
        earlier_low = min(b.low for b in ctx.bars[-(n + n): -n])
        if min(b.low for b in recent) < earlier_low:
            return False  # still making new lows — the spike has not finished
        self.why = f"vol rank {rank:.2f}, {n} bars without a new low"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return [LegSpec("PE", sell=True, target_delta=self.params.target_delta)]
