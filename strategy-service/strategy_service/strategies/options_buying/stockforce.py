"""Option-buying strategies (#179-180) mechanized from the Stock Force channel
(@stockforceofficial) extraction in D:/INDIAN MARKET/STOCKFORCE_NIFTY_OPTION_STRATEGIES.md.

These are faithful-as-possible MECHANICAL translations of a discretionary price-action
system — the parts that can't be coded (his read of "premium suppression" on the
option's own chart, big-picture bias from evening analysis) are approximated or
omitted, so results measure the mechanical skeleton, not the trader.

1. stockforce_zone_buy — the "Option Buying Challenge" system:
   15m supply/demand zones from recent swings (<=3 days), entries ONLY 13:30-15:00 IST,
   trend-side pullback into a zone (downtrend + rally into supply -> buy PE; uptrend +
   dip into demand -> buy CE), max 2 trades/day, flat by 15:00 (engine EOD + a hard
   15:00 exit signal). Engine intraday stop/target (30%/60%) approximates his
   Rs 2-4k risk : 1:2 reward rule.

2. stockforce_liquidity_sweep — the "sniper entry":
   price sweeps the prior 2-3 days' combined high/low (where stops cluster) and
   closes back inside -> fade the sweep. Only levels with multi-day standing count,
   per his rule that ordinary single-swing sweeps don't qualify.
"""

from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import ema
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, swing_points,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

CAT = "options_intraday"
TF = Timeframe.M15
IST = timezone(timedelta(hours=5, minutes=30))


def _ist_minutes(ctx: StrategyContext) -> int:
    ist = ctx.current.ts.astimezone(IST)
    return ist.hour * 60 + ist.minute


@register_strategy
class StockforceZoneBuy(OptionBuyStrategy):
    metadata = buy_meta(
        "stockforce_zone_buy", "Stock Force: Option Buying Challenge", CAT,
        "Mechanized Stock Force system: recent (<=3 day) 15m supply/demand zones, entries only "
        "13:30-15:00 IST, buy the trend-side option on a pullback INTO a zone (downtrend + rally "
        "to supply = PE; uptrend + dip to demand = CE), max 2 trades/day, flat by 15:00. His "
        "premium-chart confirmation and evening bias are discretionary and not modeled.",
        TF, "trending",
    )

    class Params(BaseModel):
        entry_start: int = Field(default=13 * 60 + 30, description="minutes since IST midnight")
        entry_end: int = Field(default=15 * 60)
        zone_lookback_bars: int = Field(default=75, ge=25, description="~3 sessions of 15m bars")
        pivot_strength: int = Field(default=3, ge=1)
        trend_ema: int = Field(default=50, ge=10)
        zone_tolerance_pct: float = Field(default=0.1, gt=0, description="how close to the zone counts as a tag")
        max_trades_per_day: int = Field(default=2, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.zone_lookback_bars + self.params.pivot_strength * 2

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._day = None
        self._trades_today = 0

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        day = bar.ts.astimezone(IST).date()
        if day != self._day:
            self._day = day
            self._trades_today = 0

        minutes = _ist_minutes(ctx)
        if minutes >= self.params.entry_end:
            if self._dir != 0:
                self.why = "flat by 15:00 (Stock Force hard rule)"
                return 0
            return 0
        if self._dir != 0:
            return None  # position open: engine's stop/target/EOD manage the exit
        if minutes < self.params.entry_start:
            return 0  # no morning trades — his most repeated rule
        if self._trades_today >= self.params.max_trades_per_day:
            return 0

        closes = ctx.closes
        trend = ema(closes, self.params.trend_ema)[-1]
        window = ctx.bars[-self.params.zone_lookback_bars:]
        highs, lows = swing_points(window, self.params.pivot_strength)
        if not highs or not lows:
            return 0
        supply = highs[-1]
        demand = lows[-1]
        tol = bar.close * self.params.zone_tolerance_pct / 100
        close = bar.close

        downtrend = close < trend
        uptrend = close > trend
        tagged_supply = bar.high >= supply - tol and close < supply  # rallied into the zone, rejected
        tagged_demand = bar.low <= demand + tol and close > demand  # dipped into the zone, held

        if downtrend and tagged_supply:
            self._trades_today += 1
            self.why = f"afternoon rally into supply {supply:.0f} in a downtrend — buying the PE"
            return -1
        if uptrend and tagged_demand:
            self._trades_today += 1
            self.why = f"afternoon dip into demand {demand:.0f} in an uptrend — buying the CE"
            return 1
        return 0


@register_strategy
class StockforceLiquiditySweep(OptionBuyStrategy):
    metadata = buy_meta(
        "stockforce_liquidity_sweep", "Stock Force: Liquidity Sweep", CAT,
        "Mechanized Stock Force 'sniper entry': price sweeps the prior 2-3 sessions' combined "
        "high/low (a multi-day level where stops cluster) and closes back inside — fade the sweep. "
        "Single-swing sweeps deliberately don't qualify, per his rule.",
        TF, "range-bound",
    )

    class Params(BaseModel):
        level_days: int = Field(default=2, ge=1, description="prior sessions forming the liquidity level")
        max_trades_per_day: int = Field(default=2, ge=1)
        cutoff: int = Field(default=15 * 60, description="no entries at/after this IST minute")

    @property
    def warmup(self) -> int:
        return 60

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._day_hl: dict = {}
        self._day = None
        self._trades_today = 0

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        d = bar.ts.astimezone(IST).date()
        hi, lo = self._day_hl.get(d, (bar.high, bar.low))
        self._day_hl[d] = (max(hi, bar.high), min(lo, bar.low))
        if d != self._day:
            self._day = d
            self._trades_today = 0

        minutes = _ist_minutes(ctx)
        if minutes >= self.params.cutoff:
            if self._dir != 0:
                self.why = "session over — flat"
                return 0
            return 0
        if self._dir != 0:
            return None
        if self._trades_today >= self.params.max_trades_per_day:
            return 0

        prior = sorted(x for x in self._day_hl if x < d)[-self.params.level_days:]
        if len(prior) < self.params.level_days:
            return 0
        level_hi = max(self._day_hl[x][0] for x in prior)
        level_lo = min(self._day_hl[x][1] for x in prior)
        close = bar.close

        if bar.high > level_hi and close < level_hi:
            self._trades_today += 1
            self.why = f"swept the {self.params.level_days}-day high {level_hi:.0f} and rejected — fading with a PE"
            return -1
        if bar.low < level_lo and close > level_lo:
            self._trades_today += 1
            self.why = f"swept the {self.params.level_days}-day low {level_lo:.0f} and reclaimed — fading with a CE"
            return 1
        return 0
