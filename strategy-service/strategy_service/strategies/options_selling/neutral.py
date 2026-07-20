"""Delta-neutral premium sellers — straddles, strangles, condors, butterflies.

Every strategy here is one answer to the same question: *when is the tape quiet enough,
and the premium rich enough, that selling both sides pays?* They differ in the regime
read that gates the entry and in whether the tail is capped.

Structures, cheapest tail control to most expensive:
  short strangle / straddle  — naked both sides. Unbounded tail. Only justified when the
      regime read is genuinely selective and the stop is tight, which is why every naked
      variant here carries a stricter gate than its defined-risk cousin.
  iron condor / butterfly    — the same short legs with protective wings bought further
      out. Gives up part of the credit to make the worst case a known number. This is
      the structurally correct default for a selling desk and the sweep is expected to
      favour it.
"""

from pydantic import BaseModel, Field

from strategy_service.strategies.options_selling._base import (
    LegSpec,
    OptionSellStrategy,
    compression,
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


# --- naked two-sided sellers -----------------------------------------------------


@register_strategy
class DeadTapeStrangle(OptionSellStrategy):
    metadata = sell_meta(
        "sell_dead_tape_strangle", "Sell: Dead-Tape Strangle", INTRADAY,
        "ADX flat and price sitting mid-range: sell the 15-delta strangle and let theta "
        "work. Naked both sides, so the engine's strike buffer is the real risk control.",
        TF15, "range-bound",
    )

    class Params(BaseModel):
        adx_period: int = Field(default=14, ge=2)
        max_adx: float = Field(default=18.0, gt=0)
        range_period: int = Field(default=20, ge=5)
        mid_band: float = Field(default=0.25, gt=0, le=0.5, description="how far from the range edge counts as mid")
        target_delta: float = Field(default=0.15, gt=0, lt=0.5)

    @property
    def warmup(self) -> int:
        return max(self.params.range_period, 2 * self.params.adx_period + 1) + 2

    def want_open(self, ctx: StrategyContext) -> bool:
        flat, adx_now = is_range_bound(ctx.bars, self.params.adx_period, self.params.max_adx)
        if not flat:
            return False
        pos = range_position(ctx.bars, self.params.range_period)
        if not (self.params.mid_band <= pos <= 1 - self.params.mid_band):
            return False  # too close to a range edge — the near strike gets run over
        self.why = f"ADX {adx_now:.1f} flat, price mid-range ({pos:.2f})"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        d = self.params.target_delta
        return [
            LegSpec("CE", sell=True, target_delta=d),
            LegSpec("PE", sell=True, target_delta=d),
        ]


@register_strategy
class RichVolStrangle(OptionSellStrategy):
    metadata = sell_meta(
        "sell_rich_vol_strangle", "Sell: Rich-Vol Strangle", INTRADAY,
        "Sells the strangle only when realized vol is in the top third of its own recent "
        "range — premium is expensive relative to what this tape usually delivers.",
        TF15, "high-volatility",
    )

    class Params(BaseModel):
        vol_window: int = Field(default=20, ge=5)
        vol_lookback: int = Field(default=60, ge=20)
        min_vol_rank: float = Field(default=0.65, ge=0, le=1)
        target_delta: float = Field(default=0.12, gt=0, lt=0.5)

    @property
    def warmup(self) -> int:
        return self.params.vol_window + self.params.vol_lookback + 3

    def want_open(self, ctx: StrategyContext) -> bool:
        rank = vol_rank(ctx.closes, self.params.vol_window, self.params.vol_lookback)
        if rank is None or rank < self.params.min_vol_rank:
            return False
        self.why = f"realized-vol rank {rank:.2f} — premium rich"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        d = self.params.target_delta
        return [LegSpec("CE", sell=True, target_delta=d), LegSpec("PE", sell=True, target_delta=d)]


@register_strategy
class ExpiryDayStraddle(OptionSellStrategy):
    metadata = sell_meta(
        "sell_expiry_straddle", "Sell: Expiry-Day ATM Straddle", EXPIRY,
        "The classic expiry-day decay trade — sell the ATM straddle into the fastest "
        "theta in the cycle. Also the sharpest gamma, hence the library's tightest stop.",
        TF15, "range-bound",
    )

    class Params(BaseModel):
        max_gap_pct: float = Field(default=0.4, gt=0, description="skip the day entirely after a big gap")
        adx_period: int = Field(default=14, ge=2)
        max_adx: float = Field(default=25.0, gt=0)

    @property
    def warmup(self) -> int:
        return 2 * self.params.adx_period + 4

    def want_open(self, ctx: StrategyContext) -> bool:
        g = gap_pct(ctx)
        if abs(g) > self.params.max_gap_pct:
            return False  # a gapping tape on expiry day is a trend day, not a decay day
        flat, adx_now = is_range_bound(ctx.bars, self.params.adx_period, self.params.max_adx)
        if not flat:
            return False
        self.why = f"expiry decay: gap {g:+.2f}%, ADX {adx_now:.1f}"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        return [LegSpec("CE", sell=True, otm_pct=0.0), LegSpec("PE", sell=True, otm_pct=0.0)]


@register_strategy
class CoilStrangle(OptionSellStrategy):
    metadata = sell_meta(
        "sell_coil_strangle", "Sell: Coil Strangle", INTRADAY,
        "Sells into a volatility coil (deviation at its lowest in 30 bars). Profitable "
        "while the coil holds and painful when it resolves — the stop is what makes it "
        "tradeable at all.",
        TF15, "range-bound",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)
        lookback: int = Field(default=30, ge=10)
        target_delta: float = Field(default=0.18, gt=0, lt=0.5)

    @property
    def warmup(self) -> int:
        return self.params.period + self.params.lookback + 2

    def want_open(self, ctx: StrategyContext) -> bool:
        if not compression(ctx.bars, self.params.period, self.params.lookback):
            return False
        self.why = f"{self.params.lookback}-bar volatility coil"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        d = self.params.target_delta
        return [LegSpec("CE", sell=True, target_delta=d), LegSpec("PE", sell=True, target_delta=d)]


@register_strategy
class WideStrangleMonthly(OptionSellStrategy):
    metadata = sell_meta(
        "sell_wide_strangle_monthly", "Sell: Wide Monthly Strangle", POSITIONAL,
        "Held-to-monthly 8-delta strangle in a flat daily tape. Wide strikes, slow theta, "
        "and real overnight gap exposure on both sides.",
        TFD, "range-bound",
    )

    class Params(BaseModel):
        adx_period: int = Field(default=14, ge=2)
        max_adx: float = Field(default=20.0, gt=0)
        target_delta: float = Field(default=0.08, gt=0, lt=0.5)

    @property
    def warmup(self) -> int:
        return 2 * self.params.adx_period + 4

    def want_open(self, ctx: StrategyContext) -> bool:
        flat, adx_now = is_range_bound(ctx.bars, self.params.adx_period, self.params.max_adx)
        if not flat:
            return False
        self.why = f"daily ADX {adx_now:.1f} — flat monthly tape"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        d = self.params.target_delta
        return [LegSpec("CE", sell=True, target_delta=d), LegSpec("PE", sell=True, target_delta=d)]


# --- defined-risk two-sided sellers ----------------------------------------------


@register_strategy
class DeadTapeCondor(OptionSellStrategy):
    metadata = sell_meta(
        "sell_dead_tape_condor", "Sell: Dead-Tape Iron Condor", INTRADAY,
        "The same dead-tape read as the naked strangle, with wings bought 1.5% further "
        "out. Gives up credit to turn an unbounded tail into a known number — the "
        "like-for-like comparison that shows what the wings actually cost.",
        TF15, "range-bound",
    )

    class Params(BaseModel):
        adx_period: int = Field(default=14, ge=2)
        max_adx: float = Field(default=18.0, gt=0)
        range_period: int = Field(default=20, ge=5)
        mid_band: float = Field(default=0.25, gt=0, le=0.5)
        target_delta: float = Field(default=0.15, gt=0, lt=0.5)
        wing_pct: float = Field(default=0.015, gt=0, description="wing distance beyond the short strike")

    @property
    def warmup(self) -> int:
        return max(self.params.range_period, 2 * self.params.adx_period + 1) + 2

    def want_open(self, ctx: StrategyContext) -> bool:
        flat, adx_now = is_range_bound(ctx.bars, self.params.adx_period, self.params.max_adx)
        if not flat:
            return False
        pos = range_position(ctx.bars, self.params.range_period)
        if not (self.params.mid_band <= pos <= 1 - self.params.mid_band):
            return False
        self.why = f"ADX {adx_now:.1f} flat, mid-range ({pos:.2f}) — condor"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        d, w = self.params.target_delta, self.params.wing_pct
        # Shorts by delta (adaptive), wings by a fixed distance so the width — and
        # therefore the max loss — stays predictable regardless of volatility.
        return [
            LegSpec("CE", sell=True, target_delta=d),
            LegSpec("CE", sell=False, wing_pct=w),
            LegSpec("PE", sell=True, target_delta=d),
            LegSpec("PE", sell=False, wing_pct=w),
        ]


@register_strategy
class RichVolCondor(OptionSellStrategy):
    metadata = sell_meta(
        "sell_rich_vol_condor", "Sell: Rich-Vol Iron Condor", INTRADAY,
        "Defined-risk condor gated on realized-vol rank rather than trend — sells only "
        "when the premium being collected is expensive by this tape's own standards.",
        TF15, "high-volatility",
    )

    class Params(BaseModel):
        vol_window: int = Field(default=20, ge=5)
        vol_lookback: int = Field(default=60, ge=20)
        min_vol_rank: float = Field(default=0.60, ge=0, le=1)
        target_delta: float = Field(default=0.12, gt=0, lt=0.5)
        wing_pct: float = Field(default=0.02, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.vol_window + self.params.vol_lookback + 3

    def want_open(self, ctx: StrategyContext) -> bool:
        rank = vol_rank(ctx.closes, self.params.vol_window, self.params.vol_lookback)
        if rank is None or rank < self.params.min_vol_rank:
            return False
        self.why = f"vol rank {rank:.2f} — rich premium, capped tail"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        d, w = self.params.target_delta, self.params.wing_pct
        return [
            LegSpec("CE", sell=True, target_delta=d),
            LegSpec("CE", sell=False, wing_pct=w),
            LegSpec("PE", sell=True, target_delta=d),
            LegSpec("PE", sell=False, wing_pct=w),
        ]


@register_strategy
class ExpiryIronFly(OptionSellStrategy):
    metadata = sell_meta(
        "sell_expiry_iron_fly", "Sell: Expiry Iron Butterfly", EXPIRY,
        "ATM straddle with wings — the expiry-day decay trade with its tail capped. "
        "Collects less than the naked straddle and cannot be destroyed by one move.",
        TF15, "range-bound",
    )

    class Params(BaseModel):
        max_gap_pct: float = Field(default=0.5, gt=0)
        wing_pct: float = Field(default=0.01, gt=0)
        adx_period: int = Field(default=14, ge=2)
        max_adx: float = Field(default=28.0, gt=0)

    @property
    def warmup(self) -> int:
        return 2 * self.params.adx_period + 4

    def want_open(self, ctx: StrategyContext) -> bool:
        g = gap_pct(ctx)
        if abs(g) > self.params.max_gap_pct:
            return False
        flat, adx_now = is_range_bound(ctx.bars, self.params.adx_period, self.params.max_adx)
        if not flat:
            return False
        self.why = f"expiry iron fly: gap {g:+.2f}%, ADX {adx_now:.1f}"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        w = self.params.wing_pct
        return [
            LegSpec("CE", sell=True, otm_pct=0.0),
            LegSpec("CE", sell=False, wing_pct=w),
            LegSpec("PE", sell=True, otm_pct=0.0),
            LegSpec("PE", sell=False, wing_pct=w),
        ]


@register_strategy
class CoilCondor(OptionSellStrategy):
    metadata = sell_meta(
        "sell_coil_condor", "Sell: Coil Iron Condor", INTRADAY,
        "Defined-risk version of the coil sell. The coil breaking is the known failure "
        "mode, so this one pays for wings rather than relying on a stop to outrun a break.",
        TF15, "range-bound",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)
        lookback: int = Field(default=30, ge=10)
        target_delta: float = Field(default=0.18, gt=0, lt=0.5)
        wing_pct: float = Field(default=0.015, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + self.params.lookback + 2

    def want_open(self, ctx: StrategyContext) -> bool:
        if not compression(ctx.bars, self.params.period, self.params.lookback):
            return False
        self.why = f"{self.params.lookback}-bar coil, wings on"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        d, w = self.params.target_delta, self.params.wing_pct
        return [
            LegSpec("CE", sell=True, target_delta=d),
            LegSpec("CE", sell=False, wing_pct=w),
            LegSpec("PE", sell=True, target_delta=d),
            LegSpec("PE", sell=False, wing_pct=w),
        ]


@register_strategy
class MonthlyCondor(OptionSellStrategy):
    metadata = sell_meta(
        "sell_monthly_condor", "Sell: Monthly Iron Condor", POSITIONAL,
        "Held-to-monthly 10-delta condor in a flat daily tape — the textbook positional "
        "premium-selling structure, tail capped by construction.",
        TFD, "range-bound",
    )

    class Params(BaseModel):
        adx_period: int = Field(default=14, ge=2)
        max_adx: float = Field(default=22.0, gt=0)
        target_delta: float = Field(default=0.10, gt=0, lt=0.5)
        wing_pct: float = Field(default=0.03, gt=0)

    @property
    def warmup(self) -> int:
        return 2 * self.params.adx_period + 4

    def want_open(self, ctx: StrategyContext) -> bool:
        flat, adx_now = is_range_bound(ctx.bars, self.params.adx_period, self.params.max_adx)
        if not flat:
            return False
        self.why = f"daily ADX {adx_now:.1f} — monthly condor"
        return True

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        d, w = self.params.target_delta, self.params.wing_pct
        return [
            LegSpec("CE", sell=True, target_delta=d),
            LegSpec("CE", sell=False, wing_pct=w),
            LegSpec("PE", sell=True, target_delta=d),
            LegSpec("PE", sell=False, wing_pct=w),
        ]
