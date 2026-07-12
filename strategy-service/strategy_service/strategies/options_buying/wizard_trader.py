"""Wizard Trader (Harshit Patel) — remaining strategies H1,H3,H4,H5,H6 (H2 already
coded as named_time_orb). H4 is the second genuine cross-symbol strategy in this
catalog. H1/H2's exact numeric rules weren't transcript-confirmed (per the source doc);
H1 here is a distinct time-anchor variant from H2's, both plausible readings of a
named '8:33'-style setup."""

from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.strategies.options_buying import _cross_symbol
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, prev_day_hlc, today_bars,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_minutes(ts) -> int:
    ist = ts.astimezone(IST)
    return ist.hour * 60 + ist.minute


@register_strategy
class Wt833(OptionBuyStrategy):
    metadata = buy_meta(
        "wt_833", "Wizard Trader: '833' Strategy (H1)", "options_scalp",
        "Named setup whose exact channel-specific rules weren't transcript-confirmed "
        "(per the source doc). Implemented as an 8-bar opening range (5m bars: ~40 min) "
        "break with a 3-bar confirmation delay before entry — the most literal reading "
        "of an '8-3-3' framing.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=8, ge=3)
        confirm_bars: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + self.params.confirm_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        n, c = self.params.range_bars, self.params.confirm_bars
        if len(day) <= n + c:
            return 0
        hi = max(b.high for b in day[:n])
        lo = min(b.low for b in day[:n])
        confirm_window = day[n:n + c]
        close = ctx.current.close
        if all(b.close > hi for b in confirm_window) and close > hi:
            self.why = f"8-bar range high {hi:.0f} broken and held for {c} bars"
            return 1
        if all(b.close < lo for b in confirm_window) and close < lo:
            self.why = f"8-bar range low {lo:.0f} broken and held for {c} bars"
            return -1
        return 0


@register_strategy
class WtSrMasterclass(OptionBuyStrategy):
    metadata = buy_meta(
        "wt_sr_masterclass", "Wizard Trader: Support & Resistance Masterclass (H3)", "options_intraday",
        "Advanced S/R fade/break: fades a level on approach with a rejection wick, "
        "trades the break once a level is cleanly cleared with two confirming closes.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        lookback: int = Field(default=25, ge=10)

    @property
    def warmup(self) -> int:
        return self.params.lookback + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.lookback - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bars = ctx.bars
        bar = bars[-1]
        if bar.high >= hi and bar.close < hi * 0.999:
            self.why = f"rejection wick at resistance {hi:.0f}"
            return -1
        if bar.low <= lo and bar.close > lo * 1.001:
            self.why = f"rejection wick at support {lo:.0f}"
            return 1
        if bars[-2].close > hi and bar.close > hi:
            self.why = f"resistance {hi:.0f} cleanly cleared (2 closes)"
            return 1
        if bars[-2].close < lo and bar.close < lo:
            self.why = f"support {lo:.0f} cleanly broken (2 closes)"
            return -1
        return None


@register_strategy
class WtInducementCorrelation(OptionBuyStrategy):
    metadata = buy_meta(
        "wt_inducement_correlation", "Wizard Trader: Inducement Zone + Correlation (H4)", "options_intraday",
        "Enters after a minor liquidity grab (inducement) that is CONFIRMED by a "
        "correlated instrument (BANKNIFTY) making the same move — the second genuine "
        "cross-symbol strategy in this catalog, via the _cross_symbol lazy lookup.",
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
        induced_up = bar.high > hi and bar.close < hi
        induced_down = bar.low < lo and bar.close > lo
        if not (induced_up or induced_down):
            return None if self._dir != 0 else 0
        bn_close = _cross_symbol.close_at("BANKNIFTY", ctx.current.timeframe.value, bar.ts)
        bn_prior = _cross_symbol.close_at("BANKNIFTY", ctx.current.timeframe.value, window[-1].ts)
        if bn_close is None or bn_prior is None:
            return None
        bn_moved_same_way = (
            (induced_up and bn_close < bn_prior) or (induced_down and bn_close > bn_prior)
        )
        if induced_up and bn_moved_same_way:
            self.why = "inducement above range, confirmed by BANKNIFTY correlation"
            return -1
        if induced_down and bn_moved_same_way:
            self.why = "inducement below range, confirmed by BANKNIFTY correlation"
            return 1
        return None


@register_strategy
class WtBtst(OptionBuyStrategy):
    metadata = buy_meta(
        "wt_btst", "Wizard Trader: BTST Trade (H5)", "options_swing",
        "Same BTST mechanic as Monika Rajput's C6, Wizard Trader's own framing "
        "(claimed 80% accuracy in the source, not independently verified).",
        Timeframe.D1, "trending",
    )

    class Params(BaseModel):
        strong_close_pct: float = Field(default=0.4, gt=0)

    @property
    def warmup(self) -> int:
        return 3

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        rng = bar.high - bar.low
        if rng <= 0:
            return None
        pos_from_high = (bar.high - bar.close) / rng * 100
        pos_from_low = (bar.close - bar.low) / rng * 100
        if pos_from_high < self.params.strong_close_pct * 100:
            self.why = "strong close near high — BTST long"
            return 1
        if pos_from_low < self.params.strong_close_pct * 100:
            self.why = "weak close near low — BTST short"
            return -1
        if self._dir != 0:
            return 0
        return 0


@register_strategy
class WtSmcCombo(OptionBuyStrategy):
    metadata = buy_meta(
        "wt_smc_combo", "Wizard Trader: SMC (FVG/Liquidity/OB) Combo (H6)", "options_intraday",
        "Same order-block/FVG mechanic as B7/D3, Wizard Trader's own SMC framing.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        impulse_mult: float = Field(default=1.7, gt=0)
        atr_period: int = Field(default=14, ge=5)
        retest_within: int = Field(default=8, ge=3)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + self.params.retest_within + 3

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._ob = None

    def direction(self, ctx: StrategyContext) -> int | None:
        from strategy_service.indicators import atr

        bars = ctx.bars
        a = atr(bars, self.params.atr_period)[-1]
        impulse, prior = bars[-1], bars[-2]
        is_up = (impulse.close - impulse.open) > self.params.impulse_mult * a
        is_down = (impulse.open - impulse.close) > self.params.impulse_mult * a
        if is_up and prior.close < prior.open:
            self._ob = (prior.low, prior.high, 1, 0)
        elif is_down and prior.close > prior.open:
            self._ob = (prior.low, prior.high, -1, 0)
        if self._ob:
            lo, hi, d, age = self._ob
            age += 1
            if age > self.params.retest_within:
                self._ob = None
                return None
            close = ctx.current.close
            if lo <= close <= hi:
                self.why = "SMC order block retest"
                self._ob = None
                return d
            self._ob = (lo, hi, d, age)
        return None
