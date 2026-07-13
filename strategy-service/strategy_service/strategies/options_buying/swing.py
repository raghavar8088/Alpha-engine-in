"""Option-buying SWING strategies (#86-100) — daily index bars, engine style
`options_swing` (30-DTE premium, 40% premium stop / 80% target, positions carried).

Each class is one classic swing/positional read on index spot; +1 buys the ATM CE,
-1 the ATM PE. See _base.py for the direction-regime contract."""

from pydantic import BaseModel, Field

from strategy_service.indicators import (
    adx, atr, donchian, ema, ichimoku, macd, roc, rsi, sma, stdev, stochastic, zscore,
)
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, supertrend_direction,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

CAT = "options_swing"
TF = Timeframe.D1


@register_strategy
class SwingEmaCross(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_ema_cross", "Swing: EMA 20/50 Regime", CAT,
        "EMA20 over EMA50 holds the CE, under holds the PE — the golden/death cross played with premium.",
        TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=20, ge=2)
        slow: int = Field(default=50, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.slow + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        f = ema(ctx.closes, self.params.fast)[-1]
        s = ema(ctx.closes, self.params.slow)[-1]
        self.why = f"EMA{self.params.fast} {'>' if f > s else '<'} EMA{self.params.slow}"
        return 1 if f > s else -1


@register_strategy
class SwingDonchian55(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_donchian55", "Swing: Donchian 55 Breakout", CAT,
        "Turtle-style: a 55-day extreme enters, the opposite 20-day channel exits.",
        TF, "trending",
    )

    class Params(BaseModel):
        entry_period: int = Field(default=55, ge=10)
        exit_period: int = Field(default=20, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.entry_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        entry_hi, entry_lo = donchian(ctx.bars[:-1], self.params.entry_period)
        exit_hi, exit_lo = donchian(ctx.bars[:-1], self.params.exit_period)
        close = ctx.current.close
        if close > entry_hi[-1]:
            self.why = f"broke {self.params.entry_period}-day high"
            return 1
        if close < entry_lo[-1]:
            self.why = f"broke {self.params.entry_period}-day low"
            return -1
        if self._dir > 0 and close < exit_lo[-1]:
            self.why = f"lost the {self.params.exit_period}-day low"
            return 0
        if self._dir < 0 and close > exit_hi[-1]:
            self.why = f"reclaimed the {self.params.exit_period}-day high"
            return 0
        return None


@register_strategy
class SwingRsiPullback(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_rsi_pullback", "Swing: RSI Pullback in Trend", CAT,
        "Uptrend (close>EMA50): RSI dipping under 40 then turning up buys the CE until RSI 65 (mirrored short side).",
        TF, "trending",
    )

    class Params(BaseModel):
        rsi_period: int = Field(default=14, ge=3)
        trend_ema: int = Field(default=50, ge=10)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        trend = ema(closes, self.params.trend_ema)[-1]
        r = rsi(closes, self.params.rsi_period)
        close = ctx.current.close
        if close > trend and r[-2] < 40 and r[-1] > r[-2]:
            self.why = f"uptrend RSI dip turned up ({r[-1]:.0f})"
            return 1
        if close < trend and r[-2] > 60 and r[-1] < r[-2]:
            self.why = f"downtrend RSI pop turned down ({r[-1]:.0f})"
            return -1
        if (self._dir > 0 and r[-1] > 65) or (self._dir < 0 and r[-1] < 35):
            self.why = "swing complete"
            return 0
        if (self._dir > 0 and close < trend) or (self._dir < 0 and close > trend):
            self.why = "trend filter broke"
            return 0
        return None


@register_strategy
class SwingMacdZero(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_macd_zero", "Swing: MACD Zero-Line", CAT,
        "The MACD line's side of zero is the regime — above holds CE, below holds PE.",
        TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=12, ge=2)
        slow: int = Field(default=26, ge=3)

    @property
    def warmup(self) -> int:
        return self.params.slow + 10

    def direction(self, ctx: StrategyContext) -> int | None:
        line, _sig = macd(ctx.closes, self.params.fast, self.params.slow)
        self.why = f"MACD {line[-1]:.1f}"
        return 1 if line[-1] > 0 else -1


@register_strategy
class SwingSupertrend(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_supertrend", "Swing: Daily Supertrend", CAT,
        "The 10/3 supertrend regime on daily bars, played with 30-DTE ATM premium.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=10, ge=3)
        mult: float = Field(default=3.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period * 3

    def direction(self, ctx: StrategyContext) -> int | None:
        d = supertrend_direction(ctx.bars, self.params.period, self.params.mult)
        self.why = f"supertrend {'up' if d > 0 else 'down' if d < 0 else 'flat'}"
        return d


@register_strategy
class SwingAdxTrend(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_adx_trend", "Swing: ADX Trend Strength", CAT,
        "ADX>25 with the dominant DI picks the side; ADX under 20 stands aside.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=5)
        adx_entry: float = Field(default=25, gt=0)
        adx_exit: float = Field(default=20, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period * 3

    def direction(self, ctx: StrategyContext) -> int | None:
        adx_line, plus_di, minus_di = adx(ctx.bars, self.params.period)
        a = adx_line[-1]
        if a > self.params.adx_entry and plus_di[-1] > minus_di[-1]:
            self.why = f"ADX {a:.0f}, +DI leads"
            return 1
        if a > self.params.adx_entry and minus_di[-1] > plus_di[-1]:
            self.why = f"ADX {a:.0f}, -DI leads"
            return -1
        if a < self.params.adx_exit:
            self.why = f"trendless (ADX {a:.0f})"
            return 0
        return None


@register_strategy
class SwingBbReversion(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_bb_reversion", "Swing: Band Reversion", CAT,
        "A close back inside after breaching the 2σ band plays the reversion to the 20-SMA.",
        TF, "range-bound",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)
        mult: float = Field(default=2.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        mid_series = sma(closes, self.params.period)
        sd_series = stdev(closes, self.params.period)
        lower_prev = mid_series[-2] - self.params.mult * sd_series[-2]
        upper_prev = mid_series[-2] + self.params.mult * sd_series[-2]
        lower, upper = (
            mid_series[-1] - self.params.mult * sd_series[-1],
            mid_series[-1] + self.params.mult * sd_series[-1],
        )
        if closes[-2] < lower_prev and closes[-1] > lower:
            self.why = "re-entered from below the band"
            return 1
        if closes[-2] > upper_prev and closes[-1] < upper:
            self.why = "re-entered from above the band"
            return -1
        if (self._dir > 0 and closes[-1] >= mid_series[-1]) or (self._dir < 0 and closes[-1] <= mid_series[-1]):
            self.why = "reached the mean"
            return 0
        return None


@register_strategy
class SwingRocMomentum(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_roc_momentum", "Swing: Quarterly ROC Momentum", CAT,
        "63-day ROC beyond ±4% is persistent momentum; it exits when the ROC decays inside ±1%.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=63, ge=10)
        entry_pct: float = Field(default=4.0, gt=0)
        exit_pct: float = Field(default=1.0, ge=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        r = roc(ctx.closes, self.params.period)[-1]
        if r > self.params.entry_pct:
            self.why = f"quarter ROC +{r:.1f}%"
            return 1
        if r < -self.params.entry_pct:
            self.why = f"quarter ROC {r:.1f}%"
            return -1
        if abs(r) < self.params.exit_pct:
            self.why = "momentum flat"
            return 0
        return None


@register_strategy
class SwingStochCycle(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_stoch_cycle", "Swing: Slow Stochastic Cycle", CAT,
        "Slow stoch (21/5) K over D under 25 buys the CE until 75 — riding the multi-week cycle (mirrored).",
        TF, "range-bound",
    )

    class Params(BaseModel):
        k_period: int = Field(default=21, ge=5)
        d_period: int = Field(default=5, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.k_period + self.params.d_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        k, d = stochastic(ctx.bars, self.params.k_period, self.params.d_period)
        crossed_up = k[-2] <= d[-2] and k[-1] > d[-1]
        crossed_down = k[-2] >= d[-2] and k[-1] < d[-1]
        if crossed_up and k[-1] < 25:
            self.why = f"cycle turning up (K={k[-1]:.0f})"
            return 1
        if crossed_down and k[-1] > 75:
            self.why = f"cycle turning down (K={k[-1]:.0f})"
            return -1
        if (self._dir > 0 and k[-1] > 75) or (self._dir < 0 and k[-1] < 25):
            self.why = "cycle complete"
            return 0
        return None


@register_strategy
class SwingIchimokuKumo(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_ichimoku_kumo", "Swing: Kumo Breakout", CAT,
        "A daily close breaking out of the Ichimoku cloud holds that side until price re-enters the cloud.",
        TF, "trending",
    )

    class Params(BaseModel):
        tenkan: int = Field(default=9, ge=3)
        kijun: int = Field(default=26, ge=5)
        senkou_b: int = Field(default=52, ge=10)

    @property
    def warmup(self) -> int:
        return self.params.senkou_b + self.params.kijun + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        _t, _k, span_a, span_b = ichimoku(ctx.bars, self.params.tenkan, self.params.kijun, self.params.senkou_b)
        close = ctx.current.close
        top = max(span_a[-1], span_b[-1])
        bot = min(span_a[-1], span_b[-1])
        if close > top:
            self.why = "above the cloud"
            return 1
        if close < bot:
            self.why = "below the cloud"
            return -1
        self.why = "inside the cloud"
        return 0


@register_strategy
class SwingAtrChannel(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_atr_channel", "Swing: ATR Channel Break", CAT,
        "A close 1×ATR beyond the EMA20 rides the expansion until price crosses back through the EMA20.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        ema_period: int = Field(default=20, ge=5)
        atr_period: int = Field(default=14, ge=5)
        mult: float = Field(default=1.0, gt=0)

    @property
    def warmup(self) -> int:
        return max(self.params.ema_period, self.params.atr_period) + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        mid = ema(ctx.closes, self.params.ema_period)[-1]
        a = atr(ctx.bars, self.params.atr_period)[-1]
        close = ctx.current.close
        if close > mid + self.params.mult * a:
            self.why = f"1×ATR above EMA{self.params.ema_period}"
            return 1
        if close < mid - self.params.mult * a:
            self.why = f"1×ATR below EMA{self.params.ema_period}"
            return -1
        if (self._dir > 0 and close < mid) or (self._dir < 0 and close > mid):
            self.why = "crossed the EMA"
            return 0
        return None


@register_strategy
class SwingNewHighMomentum(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_new_high_momentum", "Swing: 100-Day High Momentum", CAT,
        "A close at a 100-day high buys the CE and holds it while EMA20 holds (100-day low mirrors with the PE).",
        TF, "trending",
    )

    class Params(BaseModel):
        lookback: int = Field(default=100, ge=20)
        exit_ema: int = Field(default=20, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.lookback + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.lookback - 1: -1]
        hi = max(b.high for b in window)
        lo = min(b.low for b in window)
        close = ctx.current.close
        e = ema(ctx.closes, self.params.exit_ema)[-1]
        if close > hi:
            self.why = f"new {self.params.lookback}-day high"
            return 1
        if close < lo:
            self.why = f"new {self.params.lookback}-day low"
            return -1
        if (self._dir > 0 and close < e) or (self._dir < 0 and close > e):
            self.why = f"EMA{self.params.exit_ema} lost"
            return 0
        return None


@register_strategy
class SwingPullbackSma50(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_pullback_sma50", "Swing: SMA50 Bounce", CAT,
        "In a rising-SMA50 market, a tag of the SMA50 that closes back above it buys the dip (mirrored).",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=50, ge=10)
        slope_bars: int = Field(default=10, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.period + self.params.slope_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        s = sma(ctx.closes, self.params.period)
        rising = s[-1] > s[-self.params.slope_bars]
        falling = s[-1] < s[-self.params.slope_bars]
        bar = ctx.current
        if rising and bar.low <= s[-1] and bar.close > s[-1]:
            self.why = "bounced off rising SMA50"
            return 1
        if falling and bar.high >= s[-1] and bar.close < s[-1]:
            self.why = "rejected at falling SMA50"
            return -1
        if (self._dir > 0 and bar.close < s[-1] * 0.99) or (self._dir < 0 and bar.close > s[-1] * 1.01):
            self.why = "SMA50 decisively broken"
            return 0
        return None


@register_strategy
class SwingGapTrend(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_gap_trend", "Swing: Gap With Trend", CAT,
        "A ≥0.75% daily gap in the EMA20 trend's direction continues; against-EMA10 close exits.",
        TF, "trending",
    )

    class Params(BaseModel):
        min_gap_pct: float = Field(default=0.75, gt=0)
        trend_ema: int = Field(default=20, ge=5)
        exit_ema: int = Field(default=10, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars
        gap_pct = (bars[-1].open - bars[-2].close) / bars[-2].close * 100
        trend = ema(ctx.closes, self.params.trend_ema)
        exit_line = ema(ctx.closes, self.params.exit_ema)[-1]
        close = ctx.current.close
        trend_up = trend[-1] > trend[-3]
        if gap_pct > self.params.min_gap_pct and trend_up:
            self.why = f"gap up {gap_pct:.2f}% with trend"
            return 1
        if gap_pct < -self.params.min_gap_pct and not trend_up:
            self.why = f"gap down {gap_pct:.2f}% with trend"
            return -1
        if (self._dir > 0 and close < exit_line) or (self._dir < 0 and close > exit_line):
            self.why = f"EMA{self.params.exit_ema} crossed against"
            return 0
        return None


@register_strategy
class SwingZscoreReversion(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_zscore_reversion", "Swing: 60-Day Z-Score Reversion", CAT,
        "A 2σ stretch against the 60-day mean plays the snap back to the mean (z through 0 exits).",
        TF, "range-bound",
    )

    class Params(BaseModel):
        period: int = Field(default=60, ge=20)
        entry_z: float = Field(default=2.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 1

    def direction(self, ctx: StrategyContext) -> int | None:
        z = zscore(ctx.closes, self.params.period)[-1]
        if z < -self.params.entry_z:
            self.why = f"z={z:.2f} washout"
            return 1
        if z > self.params.entry_z:
            self.why = f"z={z:.2f} euphoria"
            return -1
        if (self._dir > 0 and z >= 0) or (self._dir < 0 and z <= 0):
            self.why = "back at the mean"
            return 0
        return None
