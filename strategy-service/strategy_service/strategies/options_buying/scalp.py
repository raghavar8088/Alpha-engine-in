"""Option-buying SCALP strategies (#51-65) — 5-minute index bars, engine style
`options_scalp` (2-DTE premium, 25% premium stop / 50% target, hard EOD square-off).

Each class is one classic scalping read on index spot; +1 buys the ATM CE, -1 the ATM
PE. See _base.py for the direction-regime contract."""

from pydantic import BaseModel, Field

from strategy_service.indicators import atr, ema, macd, roc, rsi, sma, stdev, stochastic, keltner, session_vwap, zscore
from strategy_service.strategies.options_buying._base import OptionBuyStrategy, buy_meta, today_bars
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

CAT = "options_scalp"
TF = Timeframe.M5


def _vwap(ctx: StrategyContext) -> list[float]:
    return session_vwap(ctx.bars, lambda b: b.ts.date())


@register_strategy
class ScalpEmaRibbon(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_ema_ribbon", "Scalp: EMA Ribbon", CAT,
        "5/8/13 EMA ribbon fully stacked up buys the CE, stacked down buys the PE, mixed exits.",
        TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=5, ge=2)
        mid: int = Field(default=8, ge=3)
        slow: int = Field(default=13, ge=4)

    @property
    def warmup(self) -> int:
        return self.params.slow + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        f, m, s = ema(closes, self.params.fast)[-1], ema(closes, self.params.mid)[-1], ema(closes, self.params.slow)[-1]
        if f > m > s:
            self.why = f"ribbon stacked up ({f:.1f}>{m:.1f}>{s:.1f})"
            return 1
        if f < m < s:
            self.why = f"ribbon stacked down ({f:.1f}<{m:.1f}<{s:.1f})"
            return -1
        self.why = "ribbon mixed"
        return 0


@register_strategy
class ScalpVwapMomentum(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_vwap_momentum", "Scalp: VWAP Momentum", CAT,
        "Price on one side of session VWAP with 3-bar ROC agreeing rides that side.",
        TF, "trending",
    )

    class Params(BaseModel):
        roc_period: int = Field(default=3, ge=1)
        roc_threshold_pct: float = Field(default=0.05, ge=0)

    @property
    def warmup(self) -> int:
        return self.params.roc_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        vwap = _vwap(ctx)[-1]
        r = roc(ctx.closes, self.params.roc_period)[-1]
        close = ctx.current.close
        if close > vwap and r > self.params.roc_threshold_pct:
            self.why = f"above VWAP {vwap:.1f} with ROC {r:.2f}%"
            return 1
        if close < vwap and r < -self.params.roc_threshold_pct:
            self.why = f"below VWAP {vwap:.1f} with ROC {r:.2f}%"
            return -1
        return 0


@register_strategy
class ScalpOrb15(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_orb15", "Scalp: 15-min Opening Range Break", CAT,
        "First three 5m bars set the range; a close beyond it rides the break, re-entry into the range exits.",
        TF, "trending",
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
        or_high = max(b.high for b in day[:n])
        or_low = min(b.low for b in day[:n])
        close = ctx.current.close
        if close > or_high:
            self.why = f"above opening range high {or_high:.1f}"
            return 1
        if close < or_low:
            self.why = f"below opening range low {or_low:.1f}"
            return -1
        self.why = "inside opening range"
        return 0


@register_strategy
class ScalpZscoreSnap(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_zscore_snap", "Scalp: Z-Score Snapback", CAT,
        "Buys the CE when price stretches 2σ under its 20-bar mean (PE when 2σ over), out near the mean.",
        TF, "range-bound",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)
        entry_z: float = Field(default=2.0, gt=0)
        exit_z: float = Field(default=0.3, ge=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 1

    def direction(self, ctx: StrategyContext) -> int | None:
        z = zscore(ctx.closes, self.params.period)[-1]
        if z < -self.params.entry_z:
            self.why = f"z={z:.2f} stretched under mean"
            return 1
        if z > self.params.entry_z:
            self.why = f"z={z:.2f} stretched over mean"
            return -1
        if abs(z) < self.params.exit_z:
            self.why = f"z={z:.2f} back at mean"
            return 0
        return None  # between entry and exit bands: hold


@register_strategy
class ScalpMacdFlip(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_macd_flip", "Scalp: Fast MACD Flip", CAT,
        "Fast MACD (8/17/9) histogram sign is the regime — positive rides CE, negative PE.",
        TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=8, ge=2)
        slow: int = Field(default=17, ge=3)
        signal: int = Field(default=9, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.slow + self.params.signal + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        line, sig = macd(ctx.closes, self.params.fast, self.params.slow, self.params.signal)
        hist = line[-1] - sig[-1]
        self.why = f"MACD hist {hist:.2f}"
        return 1 if hist > 0 else -1


@register_strategy
class ScalpStochPop(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_stoch_pop", "Scalp: Stochastic Pop", CAT,
        "Fast stoch K crossing D out of the oversold zone buys the CE until overbought (mirror for PE).",
        TF, "range-bound",
    )

    class Params(BaseModel):
        k_period: int = Field(default=9, ge=3)
        d_period: int = Field(default=3, ge=1)
        oversold: float = Field(default=20, ge=1)
        overbought: float = Field(default=80, le=99)

    @property
    def warmup(self) -> int:
        return self.params.k_period + self.params.d_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        k, d = stochastic(ctx.bars, self.params.k_period, self.params.d_period)
        crossed_up = k[-2] <= d[-2] and k[-1] > d[-1]
        crossed_down = k[-2] >= d[-2] and k[-1] < d[-1]
        if crossed_up and k[-1] < self.params.oversold + 10:
            self.why = f"K crossed D near oversold (K={k[-1]:.0f})"
            return 1
        if crossed_down and k[-1] > self.params.overbought - 10:
            self.why = f"K crossed D near overbought (K={k[-1]:.0f})"
            return -1
        if self._dir > 0 and k[-1] > self.params.overbought:
            self.why = f"K={k[-1]:.0f} overbought"
            return 0
        if self._dir < 0 and k[-1] < self.params.oversold:
            self.why = f"K={k[-1]:.0f} oversold"
            return 0
        return None


@register_strategy
class ScalpBbSqueezeBreak(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_bb_squeeze_break", "Scalp: Bollinger Squeeze Break", CAT,
        "Volatility at a 30-bar low, then a close outside the band rides the expansion until the mid-band.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)
        squeeze_lookback: int = Field(default=30, ge=10)
        band_mult: float = Field(default=2.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + self.params.squeeze_lookback + 1

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        sd = stdev(closes, self.params.period)
        mid = sma(closes, self.params.period)[-1]
        close = ctx.current.close
        in_squeeze = sd[-2] <= min(sd[-self.params.squeeze_lookback:-1])
        if in_squeeze and close > mid + self.params.band_mult * sd[-1]:
            self.why = "squeeze broke up"
            return 1
        if in_squeeze and close < mid - self.params.band_mult * sd[-1]:
            self.why = "squeeze broke down"
            return -1
        if (self._dir > 0 and close < mid) or (self._dir < 0 and close > mid):
            self.why = "back at mid-band"
            return 0
        return None


@register_strategy
class ScalpKeltnerSurf(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_keltner_surf", "Scalp: Keltner Surf", CAT,
        "A close outside the tight Keltner channel surfs that side until price loses the mid-line.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)
        mult: float = Field(default=1.5, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        upper, mid, lower = keltner(ctx.bars, self.params.period, self.params.mult)
        close = ctx.current.close
        if close > upper[-1]:
            self.why = f"above Keltner upper {upper[-1]:.1f}"
            return 1
        if close < lower[-1]:
            self.why = f"below Keltner lower {lower[-1]:.1f}"
            return -1
        if (self._dir > 0 and close < mid[-1]) or (self._dir < 0 and close > mid[-1]):
            self.why = "lost the mid-line"
            return 0
        return None


@register_strategy
class ScalpPullbackEma(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_pullback_ema", "Scalp: EMA21 Pullback", CAT,
        "In an EMA9>EMA21 up-move, a tag of EMA21 that closes back above EMA9 buys the dip (mirror for PE).",
        TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=9, ge=2)
        slow: int = Field(default=21, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.slow + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        f = ema(closes, self.params.fast)[-1]
        s = ema(closes, self.params.slow)[-1]
        bar = ctx.current
        if f > s and bar.low <= s and bar.close > f:
            self.why = f"pullback tagged EMA{self.params.slow} and reclaimed EMA{self.params.fast}"
            return 1
        if f < s and bar.high >= s and bar.close < f:
            self.why = f"rally tagged EMA{self.params.slow} and rejected at EMA{self.params.fast}"
            return -1
        if (self._dir > 0 and bar.close < s) or (self._dir < 0 and bar.close > s):
            self.why = f"through EMA{self.params.slow}"
            return 0
        return None


@register_strategy
class ScalpRangePop(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_range_pop", "Scalp: Tight-Range Pop", CAT,
        "A very tight 12-bar coil (range < 0.15%) breaking out pops with the break direction.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        lookback: int = Field(default=12, ge=5)
        max_range_pct: float = Field(default=0.15, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.lookback + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.lookback - 1: -1]
        hi = max(b.high for b in window)
        lo = min(b.low for b in window)
        close = ctx.current.close
        tight = (hi - lo) / close * 100 < self.params.max_range_pct
        if tight and close > hi:
            self.why = f"popped out of {self.params.lookback}-bar coil"
            return 1
        if tight and close < lo:
            self.why = f"dropped out of {self.params.lookback}-bar coil"
            return -1
        if self._dir != 0 and lo <= close <= hi:
            self.why = "back inside the coil"
            return 0
        return None


@register_strategy
class ScalpAtrBurst(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_atr_burst", "Scalp: ATR Burst", CAT,
        "A single bar bigger than 1.5×ATR closing near its extreme is momentum ignition — ride it while EMA9 holds.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        atr_period: int = Field(default=14, ge=5)
        burst_mult: float = Field(default=1.5, gt=0)
        close_zone: float = Field(default=0.25, gt=0, le=0.5)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        a = atr(ctx.bars, self.params.atr_period)[-1]
        rng = bar.high - bar.low
        f = ema(ctx.closes, 9)[-1]
        if rng > self.params.burst_mult * a:
            pos = (bar.close - bar.low) / rng if rng > 0 else 0.5
            if pos > 1 - self.params.close_zone:
                self.why = f"burst bar {rng:.1f} vs ATR {a:.1f}, closed strong"
                return 1
            if pos < self.params.close_zone:
                self.why = f"burst bar {rng:.1f} vs ATR {a:.1f}, closed weak"
                return -1
        if (self._dir > 0 and bar.close < f) or (self._dir < 0 and bar.close > f):
            self.why = "lost EMA9"
            return 0
        return None


@register_strategy
class ScalpGapRun(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_gap_run", "Scalp: Gap-and-Run", CAT,
        "An opening gap beyond 0.2% that is still holding two bars in runs with the gap direction.",
        TF, "trending",
    )

    class Params(BaseModel):
        min_gap_pct: float = Field(default=0.2, gt=0)
        confirm_bars: int = Field(default=2, ge=1)

    @property
    def warmup(self) -> int:
        return 5

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        if len(day) < self.params.confirm_bars:
            return 0
        prev_close = None
        for b in reversed(ctx.bars):
            if b.ts.date() != ctx.current.ts.date():
                prev_close = b.close
                break
        if prev_close is None:
            return 0
        gap_pct = (day[0].open - prev_close) / prev_close * 100
        close = ctx.current.close
        if gap_pct > self.params.min_gap_pct and close > day[0].open:
            self.why = f"gap up {gap_pct:.2f}% still holding"
            return 1
        if gap_pct < -self.params.min_gap_pct and close < day[0].open:
            self.why = f"gap down {gap_pct:.2f}% still holding"
            return -1
        self.why = "gap filled or none"
        return 0


@register_strategy
class ScalpRocThrust(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_roc_thrust", "Scalp: ROC Thrust", CAT,
        "5-bar rate-of-change beyond ±0.25% is a thrust; ride it until momentum decays to ~0.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=5, ge=2)
        entry_pct: float = Field(default=0.25, gt=0)
        exit_pct: float = Field(default=0.05, ge=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        r = roc(ctx.closes, self.params.period)[-1]
        if r > self.params.entry_pct:
            self.why = f"ROC thrust +{r:.2f}%"
            return 1
        if r < -self.params.entry_pct:
            self.why = f"ROC thrust {r:.2f}%"
            return -1
        if abs(r) < self.params.exit_pct:
            self.why = "momentum decayed"
            return 0
        return None


@register_strategy
class ScalpRsiExtreme(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_rsi_extreme", "Scalp: RSI(7) Extreme Snap", CAT,
        "RSI(7) leaving the <25 zone upward buys the CE until RSI 55; leaving >75 downward buys the PE.",
        TF, "range-bound",
    )

    class Params(BaseModel):
        period: int = Field(default=7, ge=2)
        oversold: float = Field(default=25, gt=0)
        overbought: float = Field(default=75, lt=100)

    @property
    def warmup(self) -> int:
        return self.params.period + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        r = rsi(ctx.closes, self.params.period)
        if r[-2] < self.params.oversold <= r[-1]:
            self.why = f"RSI snapped up out of oversold ({r[-1]:.0f})"
            return 1
        if r[-2] > self.params.overbought >= r[-1]:
            self.why = f"RSI snapped down out of overbought ({r[-1]:.0f})"
            return -1
        if (self._dir > 0 and r[-1] > 55) or (self._dir < 0 and r[-1] < 45):
            self.why = "snap played out"
            return 0
        return None


@register_strategy
class ScalpMicroTrend(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_micro_trend", "Scalp: Micro HH/HL Trend", CAT,
        "Three consecutive higher-highs + higher-lows is a micro uptrend (mirror down); a 2-bar low break exits.",
        TF, "trending",
    )

    class Params(BaseModel):
        run_bars: int = Field(default=3, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.run_bars + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        n = self.params.run_bars
        bars = ctx.bars[-(n + 1):]
        higher = all(bars[i].high > bars[i - 1].high and bars[i].low > bars[i - 1].low for i in range(1, len(bars)))
        lower = all(bars[i].high < bars[i - 1].high and bars[i].low < bars[i - 1].low for i in range(1, len(bars)))
        close = ctx.current.close
        if higher:
            self.why = f"{n} bars of higher highs/lows"
            return 1
        if lower:
            self.why = f"{n} bars of lower highs/lows"
            return -1
        if self._dir > 0 and close < min(b.low for b in ctx.bars[-3:-1]):
            self.why = "2-bar low broken"
            return 0
        if self._dir < 0 and close > max(b.high for b in ctx.bars[-3:-1]):
            self.why = "2-bar high broken"
            return 0
        return None
