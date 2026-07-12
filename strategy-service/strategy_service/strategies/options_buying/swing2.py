"""Option-buying SWING strategies, wave 2 (#141-161) — daily bars, engine style
`options_swing`. New families: PSAR, Heikin-Ashi, CCI, TRIX, Aroon, %R, Hull, DEMA,
Connors RSI-2, IBS, turtle-20, envelopes, regression, chandelier, fractals, MACD
histogram, StochRSI, band walk, TTM squeeze, gap trend, 3-day momentum."""

from pydantic import BaseModel, Field

from strategy_service.indicators import (
    aroon, atr, cci, dema, ema, heikin_ashi, hull_ma, keltner, linreg_slope, macd,
    psar, rsi, sma, stdev, stoch_rsi, trix, williams_r, donchian,
)
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, swing_points,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

CAT = "options_swing"
TF = Timeframe.D1


@register_strategy
class SwingPsar(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_psar", "Swing: Parabolic SAR", CAT,
        "Daily PSAR side, played with 30-DTE ATM premium.", TF, "trending",
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
class SwingHeikin(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_heikin", "Swing: Heikin-Ashi Regime", CAT,
        "Two consecutive daily HA candles of one color set the regime.", TF, "trending",
    )

    class Params(BaseModel):
        confirm: int = Field(default=2, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.confirm + 4

    def direction(self, ctx: StrategyContext) -> int | None:
        ha = heikin_ashi(ctx.bars)
        n = self.params.confirm
        if all(c > o for o, c in ha[-n:]):
            self.why = f"{n} green HA days"
            return 1
        if all(c < o for o, c in ha[-n:]):
            self.why = f"{n} red HA days"
            return -1
        return None


@register_strategy
class SwingCci(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_cci", "Swing: CCI ±100", CAT,
        "Daily CCI(20) beyond ±100 sets the side; decay inside ±20 exits.", TF, "trending",
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
class SwingTrix(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_trix", "Swing: TRIX Sign", CAT,
        "The sign of daily TRIX(15) is the regime.", TF, "trending",
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
class SwingAroon(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_aroon", "Swing: Aroon 25", CAT,
        "Aroon-up dominant over 70 holds CE (mirror PE); both mid is flat.", TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=25, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        up, down = aroon(ctx.bars, self.params.period)
        if up[-1] > 70 and down[-1] < 30:
            self.why = "Aroon bullish"
            return 1
        if down[-1] > 70 and up[-1] < 30:
            self.why = "Aroon bearish"
            return -1
        if abs(up[-1] - down[-1]) < 20:
            self.why = "Aroon mixed"
            return 0
        return None


@register_strategy
class SwingWillr(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_willr", "Swing: Williams %R Regime", CAT,
        "Daily %R above -40 holds CE, below -60 holds PE.", TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        w = williams_r(ctx.bars, self.params.period)[-1]
        if w > -40:
            self.why = f"%R {w:.0f}"
            return 1
        if w < -60:
            self.why = f"%R {w:.0f}"
            return -1
        return None


@register_strategy
class SwingHull(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_hull", "Swing: Hull MA Slope", CAT,
        "Daily Hull(20) slope direction is the regime.", TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=4)

    @property
    def warmup(self) -> int:
        return self.params.period + 6

    def direction(self, ctx: StrategyContext) -> int | None:
        h = hull_ma(ctx.closes, self.params.period)
        self.why = f"Hull {'rising' if h[-1] > h[-2] else 'falling'}"
        return 1 if h[-1] > h[-2] else -1


@register_strategy
class SwingDemaCross(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_dema_cross", "Swing: DEMA 21/55 Cross", CAT,
        "Double-EMA 21 over 55 holds CE, under holds PE.", TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=21, ge=2)
        slow: int = Field(default=55, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.slow * 2 + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        f = dema(ctx.closes, self.params.fast)[-1]
        s = dema(ctx.closes, self.params.slow)[-1]
        self.why = f"DEMA {'bull' if f > s else 'bear'}"
        return 1 if f > s else -1


@register_strategy
class SwingRsi2(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_rsi2", "Swing: Connors RSI-2 Dip", CAT,
        "Above the 200-SMA, RSI(2) under 10 buys the dip until RSI 65 (mirrored below the 200-SMA).",
        TF, "range-bound",
    )

    class Params(BaseModel):
        trend_period: int = Field(default=200, ge=20)

    @property
    def warmup(self) -> int:
        return self.params.trend_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        trend = sma(closes, self.params.trend_period)[-1]
        r = rsi(closes, 2)[-1]
        if closes[-1] > trend and r < 10:
            self.why = f"RSI2 dip in uptrend ({r:.0f})"
            return 1
        if closes[-1] < trend and r > 90:
            self.why = f"RSI2 pop in downtrend ({r:.0f})"
            return -1
        if (self._dir > 0 and r > 65) or (self._dir < 0 and r < 35):
            self.why = "dip played out"
            return 0
        return None


@register_strategy
class SwingIbs(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_ibs", "Swing: Internal Bar Strength", CAT,
        "IBS under 0.2 in an uptrend buys the dip; IBS over 0.6 exits (mirrored in downtrends).",
        TF, "range-bound",
    )

    class Params(BaseModel):
        trend_ema: int = Field(default=50, ge=10)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        b = ctx.current
        rng = b.high - b.low
        if rng <= 0:
            return None
        ibs = (b.close - b.low) / rng
        trend = ema(ctx.closes, self.params.trend_ema)[-1]
        if b.close > trend and ibs < 0.2:
            self.why = f"IBS {ibs:.2f} dip in uptrend"
            return 1
        if b.close < trend and ibs > 0.8:
            self.why = f"IBS {ibs:.2f} pop in downtrend"
            return -1
        if (self._dir > 0 and ibs > 0.6) or (self._dir < 0 and ibs < 0.4):
            self.why = "bar strength recovered"
            return 0
        return None


@register_strategy
class SwingTurtle20(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_turtle20", "Swing: Turtle 20/10", CAT,
        "Classic turtle: 20-day extreme enters, opposite 10-day channel exits.", TF, "trending",
    )

    class Params(BaseModel):
        entry_period: int = Field(default=20, ge=5)
        exit_period: int = Field(default=10, ge=3)

    @property
    def warmup(self) -> int:
        return self.params.entry_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        e_hi, e_lo = donchian(ctx.bars[:-1], self.params.entry_period)
        x_hi, x_lo = donchian(ctx.bars[:-1], self.params.exit_period)
        close = ctx.current.close
        if close > e_hi[-1]:
            self.why = "20-day breakout"
            return 1
        if close < e_lo[-1]:
            self.why = "20-day breakdown"
            return -1
        if self._dir > 0 and close < x_lo[-1]:
            self.why = "10-day low exit"
            return 0
        if self._dir < 0 and close > x_hi[-1]:
            self.why = "10-day high exit"
            return 0
        return None


@register_strategy
class SwingMaEnvelope(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_ma_envelope", "Swing: SMA50 ±2% Envelope", CAT,
        "A close beyond the SMA50 ±2% envelope rides the move until the SMA is lost.", TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=50, ge=10)
        env_pct: float = Field(default=2.0, gt=0)

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
            self.why = "SMA50 crossed"
            return 0
        return None


@register_strategy
class SwingLinreg(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_linreg", "Swing: 25-Day Regression Slope", CAT,
        "The 25-day least-squares slope, when meaningful vs ATR, sets the regime.", TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=25, ge=5)
        min_slope_atr: float = Field(default=0.08, ge=0)

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
            self.why = f"slope {norm:+.2f} ATR/day"
            return 1
        if norm < -self.params.min_slope_atr:
            self.why = f"slope {norm:+.2f} ATR/day"
            return -1
        self.why = "flat regression"
        return 0


@register_strategy
class SwingChandelier(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_chandelier", "Swing: Chandelier Flip", CAT,
        "Daily chandelier stops (22/3×ATR): above the short stop holds CE, below the long stop holds PE.",
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
            self.why = "above chandelier short-stop"
            return 1
        if close < long_stop:
            self.why = "below chandelier long-stop"
            return -1
        return None


@register_strategy
class SwingFractal(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_fractal", "Swing: Fractal Break", CAT,
        "A daily close through the last confirmed 7-bar fractal extreme rides that side.",
        TF, "trending",
    )

    class Params(BaseModel):
        strength: int = Field(default=3, ge=1)
        lookback: int = Field(default=60, ge=20)

    @property
    def warmup(self) -> int:
        return self.params.lookback + self.params.strength * 2

    def direction(self, ctx: StrategyContext) -> int | None:
        highs, lows = swing_points(ctx.bars[-self.params.lookback:], self.params.strength)
        if not highs or not lows:
            return None
        close = ctx.current.close
        if close > highs[-1]:
            self.why = f"broke fractal high {highs[-1]:.0f}"
            return 1
        if close < lows[-1]:
            self.why = f"broke fractal low {lows[-1]:.0f}"
            return -1
        if self._dir != 0 and lows[-1] < close < highs[-1]:
            self.why = "between fractals"
            return 0
        return None


@register_strategy
class SwingMacdHist(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_macd_hist", "Swing: MACD Histogram Sign", CAT,
        "The daily MACD histogram's sign (line vs signal) is the regime — earlier than the zero-line.",
        TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=12, ge=2)
        slow: int = Field(default=26, ge=3)
        signal: int = Field(default=9, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.slow + self.params.signal + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        line, sig = macd(ctx.closes, self.params.fast, self.params.slow, self.params.signal)
        hist = line[-1] - sig[-1]
        self.why = f"hist {hist:+.1f}"
        return 1 if hist > 0 else -1


@register_strategy
class SwingStochRsi(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_stoch_rsi", "Swing: StochRSI Cycle", CAT,
        "Daily StochRSI crossing up through 20 buys the CE until 80 (mirrored down).",
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
            self.why = "StochRSI cycle up"
            return 1
        if s[-2] > 80 >= s[-1]:
            self.why = "StochRSI cycle down"
            return -1
        if (self._dir > 0 and s[-1] > 80) or (self._dir < 0 and s[-1] < 20):
            self.why = "cycle complete"
            return 0
        return None


@register_strategy
class SwingBbWalk(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_bb_walk", "Swing: Band Walk", CAT,
        "A daily close outside the 2σ band walks that band until the 20-SMA is lost.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)
        mult: float = Field(default=2.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        mid = sma(closes, self.params.period)[-1]
        sd = stdev(closes, self.params.period)[-1]
        close = ctx.current.close
        if close > mid + self.params.mult * sd:
            self.why = "walking the upper band"
            return 1
        if close < mid - self.params.mult * sd:
            self.why = "walking the lower band"
            return -1
        if (self._dir > 0 and close < mid) or (self._dir < 0 and close > mid):
            self.why = "mid-band lost"
            return 0
        return None


@register_strategy
class SwingTtm(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_ttm", "Swing: TTM Squeeze Fire", CAT,
        "Daily Bollinger-inside-Keltner squeeze firing buys momentum's side until the mid-line.",
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
            self.why = "daily squeeze fired"
            return 1 if close > mid else -1
        if (self._dir > 0 and close < mid) or (self._dir < 0 and close > mid):
            self.why = "mid-line crossed"
            return 0
        return None


@register_strategy
class SwingThreeDayMomo(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_3day_momo", "Swing: Three-Day Momentum", CAT,
        "Three consecutive higher daily closes above EMA20 continue up (mirrored down); first opposite close exits.",
        TF, "trending",
    )

    class Params(BaseModel):
        run: int = Field(default=3, ge=2)
        trend_ema: int = Field(default=20, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + self.params.run + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        n = self.params.run
        trend = ema(closes, self.params.trend_ema)[-1]
        ups = all(closes[-i] > closes[-i - 1] for i in range(1, n + 1))
        downs = all(closes[-i] < closes[-i - 1] for i in range(1, n + 1))
        if ups and closes[-1] > trend:
            self.why = f"{n} higher closes above trend"
            return 1
        if downs and closes[-1] < trend:
            self.why = f"{n} lower closes below trend"
            return -1
        if (self._dir > 0 and closes[-1] < closes[-2]) or (self._dir < 0 and closes[-1] > closes[-2]):
            self.why = "momentum run broke"
            return 0
        return None


@register_strategy
class SwingGapAndGo(OptionBuyStrategy):
    metadata = buy_meta(
        "swing_gap_and_go", "Swing: Unfilled Gap Continuation", CAT,
        "A ≥0.5% daily gap that closes in the gap's direction continues until EMA10 crosses against.",
        TF, "trending",
    )

    class Params(BaseModel):
        min_gap_pct: float = Field(default=0.5, gt=0)
        exit_ema: int = Field(default=10, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.exit_ema + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        bars = ctx.bars
        b, p = bars[-1], bars[-2]
        gap_pct = (b.open - p.close) / p.close * 100
        exit_line = ema(ctx.closes, self.params.exit_ema)[-1]
        if gap_pct > self.params.min_gap_pct and b.close > b.open:
            self.why = f"gap up {gap_pct:.2f}% held"
            return 1
        if gap_pct < -self.params.min_gap_pct and b.close < b.open:
            self.why = f"gap down {gap_pct:.2f}% held"
            return -1
        if (self._dir > 0 and b.close < exit_line) or (self._dir < 0 and b.close > exit_line):
            self.why = "EMA10 crossed against"
            return 0
        return None
