"""Option-buying INTRADAY strategies, wave 2 (#116-140) — 15m bars, engine style
`options_intraday`. New families: Heikin-Ashi, PSAR, CCI, %R, TRIX, Aroon, LinReg,
Hull, DEMA, Camarilla/Woodie pivots, NR7, first-hour range, TTM squeeze, RSI
divergence, StochRSI, envelopes, chandelier, fractals, gap-fill, session windows."""

from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import (
    aroon, atr, cci, dema, ema, heikin_ashi, hull_ma, keltner, linreg_slope, macd,
    psar, rsi, sma, stdev, stoch_rsi, trix, williams_r,
)
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, prev_day_hlc, swing_points, today_bars,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

CAT = "options_intraday"
TF = Timeframe.M15
IST = timezone(timedelta(hours=5, minutes=30))


@register_strategy
class IntraHeikinTrend(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_heikin_trend", "Intraday: Heikin-Ashi Trend", CAT,
        "Two consecutive Heikin-Ashi candles of one color set the regime; two of the other end it.",
        TF, "trending",
    )

    class Params(BaseModel):
        confirm: int = Field(default=2, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.confirm + 4

    def direction(self, ctx: StrategyContext) -> int | None:
        ha = heikin_ashi(ctx.bars)
        n = self.params.confirm
        greens = all(c > o for o, c in ha[-n:])
        reds = all(c < o for o, c in ha[-n:])
        if greens:
            self.why = f"{n} green HA candles"
            return 1
        if reds:
            self.why = f"{n} red HA candles"
            return -1
        return None


@register_strategy
class IntraPsar(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_psar", "Intraday: Parabolic SAR", CAT,
        "PSAR side on 15m bars is the regime.", TF, "trending",
    )

    class Params(BaseModel):
        af_step: float = Field(default=0.02, gt=0)
        af_max: float = Field(default=0.2, gt=0)

    @property
    def warmup(self) -> int:
        return 10

    def direction(self, ctx: StrategyContext) -> int | None:
        d = psar(ctx.bars, self.params.af_step, self.params.af_max)[-1]
        self.why = f"PSAR {'long' if d > 0 else 'short'}"
        return d


@register_strategy
class IntraCciTrend(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_cci_trend", "Intraday: CCI ±100 Regime", CAT,
        "CCI(20) beyond ±100 sets the regime; decay inside ±20 stands down.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        c = cci(ctx.bars, self.params.period)[-1]
        if c > 100:
            self.why = f"CCI {c:.0f}"
            return 1
        if c < -100:
            self.why = f"CCI {c:.0f}"
            return -1
        if abs(c) < 20:
            self.why = "CCI neutral"
            return 0
        return None


@register_strategy
class IntraWillrRegime(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_willr_regime", "Intraday: Williams %R Regime", CAT,
        "%R above -45 holds CE, below -55 holds PE — a mid-line momentum regime with hysteresis.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        w = williams_r(ctx.bars, self.params.period)[-1]
        if w > -45:
            self.why = f"%R {w:.0f}"
            return 1
        if w < -55:
            self.why = f"%R {w:.0f}"
            return -1
        return None


@register_strategy
class IntraTrix(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_trix", "Intraday: TRIX Zero-Cross", CAT,
        "The sign of TRIX(15) — triple-smoothed momentum — is the regime.", TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=15, ge=3)

    @property
    def warmup(self) -> int:
        return self.params.period * 3 + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        t = trix(ctx.closes, self.params.period)[-1]
        self.why = f"TRIX {t:+.3f}%"
        return 1 if t > 0 else -1


@register_strategy
class IntraAroon(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_aroon", "Intraday: Aroon Trend", CAT,
        "Aroon-up over 70 with Aroon-down under 30 holds CE (mirror PE); both mid stands down.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=25, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        up, down = aroon(ctx.bars, self.params.period)
        if up[-1] > 70 and down[-1] < 30:
            self.why = f"Aroon up {up[-1]:.0f}/{down[-1]:.0f}"
            return 1
        if down[-1] > 70 and up[-1] < 30:
            self.why = f"Aroon down {down[-1]:.0f}/{up[-1]:.0f}"
            return -1
        if abs(up[-1] - down[-1]) < 20:
            self.why = "Aroon mixed"
            return 0
        return None


@register_strategy
class IntraLinregSlope(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_linreg_slope", "Intraday: Regression Slope", CAT,
        "The 20-bar least-squares slope, when meaningful vs ATR, sets the regime.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)
        min_slope_atr: float = Field(default=0.05, ge=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        s = linreg_slope(ctx.closes, self.params.period)[-1]
        a = atr(ctx.bars, 14)[-1]
        if a <= 0:
            return None
        norm = s / a
        if norm > self.params.min_slope_atr:
            self.why = f"slope {norm:+.2f} ATR/bar"
            return 1
        if norm < -self.params.min_slope_atr:
            self.why = f"slope {norm:+.2f} ATR/bar"
            return -1
        self.why = "flat regression"
        return 0


@register_strategy
class IntraHullCross(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_hull_cross", "Intraday: Hull MA Cross", CAT,
        "Price above a rising Hull(21) holds CE; below a falling Hull holds PE.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=21, ge=4)

    @property
    def warmup(self) -> int:
        return self.params.period + 6

    def direction(self, ctx: StrategyContext) -> int | None:
        h = hull_ma(ctx.closes, self.params.period)
        close = ctx.current.close
        if close > h[-1] and h[-1] > h[-2]:
            self.why = "above rising Hull"
            return 1
        if close < h[-1] and h[-1] < h[-2]:
            self.why = "below falling Hull"
            return -1
        return 0


@register_strategy
class IntraDemaCross(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_dema_cross", "Intraday: DEMA 10/30 Cross", CAT,
        "Double-EMA 10 over 30 is the regime — lower lag than the plain EMA pair.",
        TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=10, ge=2)
        slow: int = Field(default=30, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.slow * 2 + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        f = dema(ctx.closes, self.params.fast)[-1]
        s = dema(ctx.closes, self.params.slow)[-1]
        self.why = f"DEMA {'bull' if f > s else 'bear'}"
        return 1 if f > s else -1


@register_strategy
class IntraCamarilla(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_camarilla", "Intraday: Camarilla H4/L4 Break", CAT,
        "A close beyond the Camarilla H4/L4 breakout bands rides the expansion; back inside H3/L3 exits.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        pass

    @property
    def warmup(self) -> int:
        return 30

    def direction(self, ctx: StrategyContext) -> int | None:
        hlc = prev_day_hlc(ctx)
        if hlc is None:
            return 0
        high, low, close_prev = hlc
        rng = high - low
        h4, h3 = close_prev + rng * 1.1 / 2, close_prev + rng * 1.1 / 4
        l4, l3 = close_prev - rng * 1.1 / 2, close_prev - rng * 1.1 / 4
        close = ctx.current.close
        if close > h4:
            self.why = f"above Camarilla H4 {h4:.1f}"
            return 1
        if close < l4:
            self.why = f"below Camarilla L4 {l4:.1f}"
            return -1
        if self._dir != 0 and l3 < close < h3:
            self.why = "back inside H3/L3"
            return 0
        return None


@register_strategy
class IntraWoodie(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_woodie", "Intraday: Woodie Pivot Break", CAT,
        "Close-weighted Woodie pivot R1/S1 breaks set the side; back through the pivot exits.",
        TF, "trending",
    )

    class Params(BaseModel):
        pass

    @property
    def warmup(self) -> int:
        return 30

    def direction(self, ctx: StrategyContext) -> int | None:
        hlc = prev_day_hlc(ctx)
        if hlc is None:
            return 0
        high, low, close_prev = hlc
        pivot = (high + low + 2 * close_prev) / 4
        r1, s1 = 2 * pivot - low, 2 * pivot - high
        close = ctx.current.close
        if close > r1:
            self.why = f"above Woodie R1 {r1:.1f}"
            return 1
        if close < s1:
            self.why = f"below Woodie S1 {s1:.1f}"
            return -1
        if self._dir != 0 and ((self._dir > 0) != (close > pivot)):
            self.why = "recrossed the pivot"
            return 0
        return None


@register_strategy
class IntraNr7Break(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_nr7_break", "Intraday: NR7 Range Break", CAT,
        "After the narrowest daily range in 7 days, today's break of that day's extreme runs.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        lookback_days: int = Field(default=7, ge=3)

    @property
    def warmup(self) -> int:
        return 30

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._day_ranges: dict = {}

    def direction(self, ctx: StrategyContext) -> int | None:
        # maintain per-day high/low from the bars we see
        for b in ctx.bars[-2:]:
            d = b.ts.date()
            hi, lo = self._day_ranges.get(d, (b.high, b.low))
            self._day_ranges[d] = (max(hi, b.high), min(lo, b.low))
        today = ctx.current.ts.date()
        prior_days = sorted(d for d in self._day_ranges if d < today)[-self.params.lookback_days:]
        if len(prior_days) < self.params.lookback_days:
            return 0
        ranges = {d: self._day_ranges[d][0] - self._day_ranges[d][1] for d in prior_days}
        nr_day = min(ranges, key=ranges.get)
        if nr_day != prior_days[-1]:  # yesterday must be the NR7 day
            return 0
        hi, lo = self._day_ranges[nr_day]
        close = ctx.current.close
        if close > hi:
            self.why = f"broke NR7 high {hi:.1f}"
            return 1
        if close < lo:
            self.why = f"broke NR7 low {lo:.1f}"
            return -1
        return None


@register_strategy
class IntraFirstHourRange(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_first_hour_range", "Intraday: First-Hour Range Break", CAT,
        "The first four 15m bars set the hour range; a close beyond it rides the day's expansion.",
        TF, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=4, ge=2)

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
            self.why = f"above first-hour high {hi:.1f}"
            return 1
        if close < lo:
            self.why = f"below first-hour low {lo:.1f}"
            return -1
        self.why = "inside first-hour range"
        return 0


@register_strategy
class IntraPrevDayHl(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_prev_day_hl", "Intraday: Prior-Day H/L Break", CAT,
        "A 15m close through yesterday's high or low rides that side while it holds.",
        TF, "trending",
    )

    class Params(BaseModel):
        pass

    @property
    def warmup(self) -> int:
        return 30

    def direction(self, ctx: StrategyContext) -> int | None:
        hlc = prev_day_hlc(ctx)
        if hlc is None:
            return 0
        high, low, _ = hlc
        close = ctx.current.close
        if close > high:
            self.why = f"above yesterday's high {high:.1f}"
            return 1
        if close < low:
            self.why = f"below yesterday's low {low:.1f}"
            return -1
        self.why = "inside yesterday's range"
        return 0


@register_strategy
class IntraTtmSqueeze(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_ttm_squeeze", "Intraday: TTM Squeeze Fire", CAT,
        "Bollinger inside Keltner is the squeeze; on release, momentum's side is bought until the mid-line.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)
        bb_mult: float = Field(default=2.0, gt=0)
        kc_mult: float = Field(default=1.5, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 3

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._in_squeeze = False

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        p = self.params.period
        mid = sma(closes, p)[-1]
        sd = stdev(closes, p)[-1]
        upper_k, _, lower_k = keltner(ctx.bars, p, self.params.kc_mult)
        squeezed = (mid + self.params.bb_mult * sd) < upper_k[-1] and (mid - self.params.bb_mult * sd) > lower_k[-1]
        fired = self._in_squeeze and not squeezed
        self._in_squeeze = squeezed
        close = ctx.current.close
        if fired:
            self.why = "squeeze fired"
            return 1 if close > mid else -1
        if (self._dir > 0 and close < mid) or (self._dir < 0 and close > mid):
            self.why = "mid-line crossed"
            return 0
        return None


@register_strategy
class IntraRsiDivergence(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_rsi_divergence", "Intraday: RSI Divergence", CAT,
        "Price makes a lower low but RSI a higher low → bullish divergence buys the CE (mirrored bearish).",
        TF, "range-bound",
    )

    class Params(BaseModel):
        rsi_period: int = Field(default=14, ge=5)
        lookback: int = Field(default=40, ge=20)

    @property
    def warmup(self) -> int:
        return self.params.lookback + 8

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars[-self.params.lookback:]
        r = rsi(ctx.closes, self.params.rsi_period)
        highs, lows = swing_points(bars, 3)
        close = ctx.current.close
        # align: compare last two swing extremes with rsi at those approximate offsets
        if len(lows) >= 2 and lows[-1] < lows[-2]:
            # price lower low; rsi higher low over the same window?
            r_window = r[-self.params.lookback:]
            half = len(r_window) // 2
            if min(r_window[half:]) > min(r_window[:half]):
                self.why = "bullish RSI divergence"
                return 1
        if len(highs) >= 2 and highs[-1] > highs[-2]:
            r_window = r[-self.params.lookback:]
            half = len(r_window) // 2
            if max(r_window[half:]) < max(r_window[:half]):
                self.why = "bearish RSI divergence"
                return -1
        if (self._dir > 0 and r[-1] > 60) or (self._dir < 0 and r[-1] < 40):
            self.why = "divergence played out"
            return 0
        return None


@register_strategy
class IntraMacdHistTurn(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_macd_hist_turn", "Intraday: MACD Histogram Turn", CAT,
        "Histogram rising 3 bars off a negative trough buys the CE; falling 3 off a positive peak mirrors.",
        TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=12, ge=2)
        slow: int = Field(default=26, ge=3)
        signal: int = Field(default=9, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.slow + self.params.signal + 5

    def direction(self, ctx: StrategyContext) -> int | None:
        line, sig = macd(ctx.closes, self.params.fast, self.params.slow, self.params.signal)
        hist = [a - b for a, b in zip(line, sig)]
        rising3 = hist[-1] > hist[-2] > hist[-3]
        falling3 = hist[-1] < hist[-2] < hist[-3]
        if rising3 and hist[-3] < 0:
            self.why = "histogram turning up from trough"
            return 1
        if falling3 and hist[-3] > 0:
            self.why = "histogram turning down from peak"
            return -1
        if (self._dir > 0 and falling3) or (self._dir < 0 and rising3):
            self.why = "momentum turned against"
            return 0
        return None


@register_strategy
class IntraStochRsi(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_stoch_rsi", "Intraday: StochRSI Swings", CAT,
        "StochRSI crossing up through 20 buys the CE until 80 (mirrored from 80 down).",
        TF, "range-bound",
    )

    class Params(BaseModel):
        rsi_period: int = Field(default=14, ge=5)
        stoch_period: int = Field(default=14, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.rsi_period + self.params.stoch_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        s = stoch_rsi(ctx.closes, self.params.rsi_period, self.params.stoch_period)
        if s[-2] < 20 <= s[-1]:
            self.why = f"StochRSI up through 20 ({s[-1]:.0f})"
            return 1
        if s[-2] > 80 >= s[-1]:
            self.why = f"StochRSI down through 80 ({s[-1]:.0f})"
            return -1
        if (self._dir > 0 and s[-1] > 80) or (self._dir < 0 and s[-1] < 20):
            self.why = "swing complete"
            return 0
        return None


@register_strategy
class IntraMaEnvelope(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_ma_envelope", "Intraday: MA Envelope Break", CAT,
        "A close beyond the SMA20 ±0.3% envelope rides the breakout until the SMA goes.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)
        env_pct: float = Field(default=0.3, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        mid = sma(ctx.closes, self.params.period)[-1]
        band = mid * self.params.env_pct / 100
        close = ctx.current.close
        if close > mid + band:
            self.why = "above the envelope"
            return 1
        if close < mid - band:
            self.why = "below the envelope"
            return -1
        if (self._dir > 0 and close < mid) or (self._dir < 0 and close > mid):
            self.why = "SMA crossed"
            return 0
        return None


@register_strategy
class IntraChandelier(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_chandelier", "Intraday: Chandelier Flip", CAT,
        "Close above the long chandelier stop (22-high − 3×ATR) holds CE; below the short stop holds PE.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=22, ge=5)
        mult: float = Field(default=3.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.period:]
        a = atr(ctx.bars, self.params.period)[-1]
        long_stop = max(b.high for b in window) - self.params.mult * a
        short_stop = min(b.low for b in window) + self.params.mult * a
        close = ctx.current.close
        if close > short_stop:
            self.why = f"above chandelier short-stop {short_stop:.1f}"
            return 1
        if close < long_stop:
            self.why = f"below chandelier long-stop {long_stop:.1f}"
            return -1
        return None


@register_strategy
class IntraFractalBreak(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_fractal_break", "Intraday: Fractal Break", CAT,
        "A close through the last confirmed 5-bar fractal high buys the CE (fractal low mirrors).",
        TF, "trending",
    )

    class Params(BaseModel):
        strength: int = Field(default=2, ge=1)
        lookback: int = Field(default=50, ge=20)

    @property
    def warmup(self) -> int:
        return self.params.lookback + self.params.strength * 2

    def direction(self, ctx: StrategyContext) -> int | None:
        highs, lows = swing_points(ctx.bars[-self.params.lookback:], self.params.strength)
        if not highs or not lows:
            return None
        close = ctx.current.close
        if close > highs[-1]:
            self.why = f"broke fractal high {highs[-1]:.1f}"
            return 1
        if close < lows[-1]:
            self.why = f"broke fractal low {lows[-1]:.1f}"
            return -1
        if self._dir != 0 and lows[-1] < close < highs[-1]:
            self.why = "back between fractals"
            return 0
        return None


@register_strategy
class IntraHaReversal(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_ha_reversal", "Intraday: Heikin-Ashi Doji Flip", CAT,
        "An HA doji after a 5-candle one-color run fades the run; the next color confirms the exit.",
        TF, "range-bound",
    )

    class Params(BaseModel):
        run: int = Field(default=5, ge=3)
        doji_pct: float = Field(default=0.15, gt=0, lt=1)

    @property
    def warmup(self) -> int:
        return self.params.run + 4

    def direction(self, ctx: StrategyContext) -> int | None:
        ha = heikin_ashi(ctx.bars)
        o, c = ha[-1]
        bar = ctx.current
        rng = bar.high - bar.low
        n = self.params.run
        if rng <= 0:
            return None
        is_doji = abs(c - o) < rng * self.params.doji_pct
        run_up = all(cc > oo for oo, cc in ha[-n - 1: -1])
        run_down = all(cc < oo for oo, cc in ha[-n - 1: -1])
        if is_doji and run_up:
            self.why = "HA doji after up-run"
            return -1
        if is_doji and run_down:
            self.why = "HA doji after down-run"
            return 1
        if (self._dir > 0 and c < o) or (self._dir < 0 and c > o):
            self.why = "HA color against position"
            return 0
        return None


@register_strategy
class IntraGapFill(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_gap_fill", "Intraday: Gap Fill Fade", CAT,
        "An opening gap over 0.3% is faded toward yesterday's close; filled gap or EOD exits.",
        TF, "range-bound",
    )

    class Params(BaseModel):
        min_gap_pct: float = Field(default=0.3, gt=0)

    @property
    def warmup(self) -> int:
        return 30

    def direction(self, ctx: StrategyContext) -> int | None:
        hlc = prev_day_hlc(ctx)
        day = today_bars(ctx)
        if hlc is None or not day:
            return 0
        prev_close = hlc[2]
        gap_pct = (day[0].open - prev_close) / prev_close * 100
        close = ctx.current.close
        if gap_pct > self.params.min_gap_pct and close > prev_close:
            self.why = f"fading {gap_pct:.2f}% gap up"
            return -1
        if gap_pct < -self.params.min_gap_pct and close < prev_close:
            self.why = f"fading {gap_pct:.2f}% gap down"
            return 1
        if self._dir != 0:
            self.why = "gap filled"
            return 0
        return 0


@register_strategy
class IntraMorningMomentum(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_morning_momentum", "Intraday: 10:15 Momentum Lock", CAT,
        "At the fifth 15m bar, the day's direction from open (if >0.25%) is ridden for the day.",
        TF, "trending",
    )

    class Params(BaseModel):
        decision_bar: int = Field(default=5, ge=2)
        min_move_pct: float = Field(default=0.25, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.decision_bar + 1

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        if len(day) < self.params.decision_bar:
            return 0 if self._dir == 0 else None
        if len(day) > self.params.decision_bar:
            return None  # decision already made for today; hold (engine EODs it)
        move_pct = (ctx.current.close - day[0].open) / day[0].open * 100
        if move_pct > self.params.min_move_pct:
            self.why = f"morning momentum +{move_pct:.2f}%"
            return 1
        if move_pct < -self.params.min_move_pct:
            self.why = f"morning momentum {move_pct:.2f}%"
            return -1
        self.why = "no morning conviction"
        return 0
