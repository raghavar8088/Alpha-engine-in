"""Option-buying SCALP strategies, wave 2 (#101-115) — 5m bars, engine style
`options_scalp`. New families: Connors RSI-2, IBS, PSAR, Hull, TEMA, CCI, Williams %R,
candle patterns, %B, VWAP bands, prior-day levels, round numbers, streaks."""

from pydantic import BaseModel, Field

from strategy_service.indicators import (
    cci, ema, hull_ma, psar, roc, rsi, sma, stdev, session_vwap, tema, williams_r,
)
from strategy_service.strategies.options_buying._base import OptionBuyStrategy, buy_meta
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

CAT = "options_scalp"
TF = Timeframe.M5


@register_strategy
class ScalpRsi2(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_rsi2", "Scalp: Connors RSI-2", CAT,
        "RSI(2) under 10 buys the dip until RSI 60; over 90 buys the PE until RSI 40.",
        TF, "range-bound",
    )

    class Params(BaseModel):
        low: float = Field(default=10, gt=0)
        high: float = Field(default=90, lt=100)

    @property
    def warmup(self) -> int:
        return 6

    def direction(self, ctx: StrategyContext) -> int | None:
        r = rsi(ctx.closes, 2)[-1]
        if r < self.params.low:
            self.why = f"RSI2 washed out ({r:.0f})"
            return 1
        if r > self.params.high:
            self.why = f"RSI2 overheated ({r:.0f})"
            return -1
        if (self._dir > 0 and r > 60) or (self._dir < 0 and r < 40):
            self.why = "snap done"
            return 0
        return None


@register_strategy
class ScalpIbs(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_ibs", "Scalp: Internal Bar Strength", CAT,
        "A close in the bottom 15% of the bar's range fades down-pressure (top 15% mirrors).",
        TF, "range-bound",
    )

    class Params(BaseModel):
        edge: float = Field(default=0.15, gt=0, lt=0.5)

    @property
    def warmup(self) -> int:
        return 3

    def direction(self, ctx: StrategyContext) -> int | None:
        b = ctx.current
        rng = b.high - b.low
        if rng <= 0:
            return None
        ibs = (b.close - b.low) / rng
        if ibs < self.params.edge:
            self.why = f"IBS {ibs:.2f} washout"
            return 1
        if ibs > 1 - self.params.edge:
            self.why = f"IBS {ibs:.2f} blowoff"
            return -1
        if 0.45 <= ibs <= 0.55 and self._dir != 0:
            self.why = "bar balance restored"
            return 0
        return None


@register_strategy
class ScalpPsar(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_psar", "Scalp: Parabolic SAR", CAT,
        "Rides the PSAR(0.02/0.2) side — SAR below price holds CE, above holds PE.",
        TF, "trending",
    )

    class Params(BaseModel):
        af_step: float = Field(default=0.02, gt=0)
        af_max: float = Field(default=0.2, gt=0)

    @property
    def warmup(self) -> int:
        return 10

    def direction(self, ctx: StrategyContext) -> int | None:
        d = psar(ctx.bars, self.params.af_step, self.params.af_max)[-1]
        self.why = f"PSAR {'below' if d > 0 else 'above'} price"
        return d


@register_strategy
class ScalpHullSlope(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_hull_slope", "Scalp: Hull MA Slope", CAT,
        "Hull(16) turning up holds CE, turning down holds PE — a fast, low-lag trend read.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=16, ge=4)

    @property
    def warmup(self) -> int:
        return self.params.period + 6

    def direction(self, ctx: StrategyContext) -> int | None:
        h = hull_ma(ctx.closes, self.params.period)
        self.why = f"Hull slope {'up' if h[-1] > h[-2] else 'down'}"
        return 1 if h[-1] > h[-2] else -1


@register_strategy
class ScalpTemaCross(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_tema_cross", "Scalp: TEMA 5/15 Cross", CAT,
        "Triple-EMA 5 over 15 is the regime — near-zero lag crossover for scalps.",
        TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=5, ge=2)
        slow: int = Field(default=15, ge=4)

    @property
    def warmup(self) -> int:
        return self.params.slow * 3

    def direction(self, ctx: StrategyContext) -> int | None:
        f = tema(ctx.closes, self.params.fast)[-1]
        s = tema(ctx.closes, self.params.slow)[-1]
        self.why = f"TEMA{self.params.fast} {'>' if f > s else '<'} TEMA{self.params.slow}"
        return 1 if f > s else -1


@register_strategy
class ScalpCciBurst(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_cci_burst", "Scalp: CCI Burst", CAT,
        "CCI(14) beyond ±150 is a momentum burst; it exits when CCI decays inside ±30.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=5)
        entry: float = Field(default=150, gt=0)
        exit: float = Field(default=30, ge=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        c = cci(ctx.bars, self.params.period)[-1]
        if c > self.params.entry:
            self.why = f"CCI burst +{c:.0f}"
            return 1
        if c < -self.params.entry:
            self.why = f"CCI burst {c:.0f}"
            return -1
        if abs(c) < self.params.exit:
            self.why = "burst decayed"
            return 0
        return None


@register_strategy
class ScalpWillrSnap(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_willr_snap", "Scalp: Williams %R Snap", CAT,
        "%R crossing up out of -80 buys the CE until -20; crossing down out of -20 mirrors.",
        TF, "range-bound",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.period + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        w = williams_r(ctx.bars, self.params.period)
        if w[-2] < -80 <= w[-1]:
            self.why = f"%R snapped out of oversold ({w[-1]:.0f})"
            return 1
        if w[-2] > -20 >= w[-1]:
            self.why = f"%R snapped out of overbought ({w[-1]:.0f})"
            return -1
        if (self._dir > 0 and w[-1] > -20) or (self._dir < 0 and w[-1] < -80):
            self.why = "snap complete"
            return 0
        return None


@register_strategy
class ScalpEngulfing(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_engulfing", "Scalp: Engulfing With Trend", CAT,
        "A bullish engulfing bar above EMA20 buys the CE (bearish engulfing below mirrors); EMA9 cross exits.",
        TF, "trending",
    )

    class Params(BaseModel):
        trend_ema: int = Field(default=20, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        b, p = ctx.bars[-1], ctx.bars[-2]
        trend = ema(ctx.closes, self.params.trend_ema)[-1]
        fast = ema(ctx.closes, 9)[-1]
        bull = b.close > b.open and p.close < p.open and b.close > p.open and b.open < p.close
        bear = b.close < b.open and p.close > p.open and b.close < p.open and b.open > p.close
        if bull and b.close > trend:
            self.why = "bullish engulfing above trend"
            return 1
        if bear and b.close < trend:
            self.why = "bearish engulfing below trend"
            return -1
        if (self._dir > 0 and b.close < fast) or (self._dir < 0 and b.close > fast):
            self.why = "EMA9 crossed against"
            return 0
        return None


@register_strategy
class ScalpInsideBreak(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_inside_break", "Scalp: Inside-Bar Break", CAT,
        "An inside bar's mother-bar high breaking buys the CE (low breaking mirrors); mid-range exits.",
        TF, "high-volatility",
    )

    class Params(BaseModel):
        pass

    @property
    def warmup(self) -> int:
        return 4

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._mother: tuple[float, float] | None = None

    def direction(self, ctx: StrategyContext) -> int | None:
        b, p, pp = ctx.bars[-1], ctx.bars[-2], ctx.bars[-3]
        if p.high <= pp.high and p.low >= pp.low:  # previous bar was inside its predecessor
            self._mother = (pp.high, pp.low)
        if self._mother:
            hi, lo = self._mother
            if b.close > hi:
                self.why = f"broke mother-bar high {hi:.1f}"
                return 1
            if b.close < lo:
                self.why = f"broke mother-bar low {lo:.1f}"
                return -1
            if self._dir != 0 and lo < b.close < hi:
                self.why = "back inside the range"
                return 0
        return None


@register_strategy
class ScalpThreeBarRev(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_3bar_reversal", "Scalp: Three-Bar Reversal", CAT,
        "Three falling closes then a bar closing above the prior high reverses up (mirrored down).",
        TF, "range-bound",
    )

    class Params(BaseModel):
        run: int = Field(default=3, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.run + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        n = self.params.run
        bars = ctx.bars
        b = bars[-1]
        prior = bars[-n - 1: -1]
        fell = all(prior[i].close < prior[i - 1].close for i in range(1, len(prior)))
        rose = all(prior[i].close > prior[i - 1].close for i in range(1, len(prior)))
        if fell and b.close > prior[-1].high:
            self.why = f"{n}-bar fall reversed"
            return 1
        if rose and b.close < prior[-1].low:
            self.why = f"{n}-bar rise reversed"
            return -1
        if self._dir > 0 and b.close < min(x.low for x in bars[-3:-1]):
            self.why = "reversal failed"
            return 0
        if self._dir < 0 and b.close > max(x.high for x in bars[-3:-1]):
            self.why = "reversal failed"
            return 0
        return None


@register_strategy
class ScalpPctB(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_pctb", "Scalp: Bollinger %B Walk", CAT,
        "%B above 1.0 walks the upper band while %B holds over 0.5 (below 0 mirrors).",
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
        if sd <= 0:
            return None
        pctb = (closes[-1] - (mid - self.params.mult * sd)) / (2 * self.params.mult * sd)
        if pctb > 1:
            self.why = f"%B {pctb:.2f} over the band"
            return 1
        if pctb < 0:
            self.why = f"%B {pctb:.2f} under the band"
            return -1
        if (self._dir > 0 and pctb < 0.5) or (self._dir < 0 and pctb > 0.5):
            self.why = "walk over"
            return 0
        return None


@register_strategy
class ScalpVwapBand(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_vwap_band", "Scalp: VWAP Band Fade", CAT,
        "Price stretched 1.5σ under session VWAP snaps back to it (above mirrors with the PE).",
        TF, "range-bound",
    )

    class Params(BaseModel):
        sigma_period: int = Field(default=20, ge=5)
        mult: float = Field(default=1.5, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.sigma_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        vwap = session_vwap(ctx.bars, lambda b: b.ts.date())[-1]
        sd = stdev(ctx.closes, self.params.sigma_period)[-1]
        close = ctx.current.close
        if sd <= 0:
            return None
        if close < vwap - self.params.mult * sd:
            self.why = f"{self.params.mult}σ under VWAP"
            return 1
        if close > vwap + self.params.mult * sd:
            self.why = f"{self.params.mult}σ over VWAP"
            return -1
        if (self._dir > 0 and close >= vwap) or (self._dir < 0 and close <= vwap):
            self.why = "back at VWAP"
            return 0
        return None


@register_strategy
class ScalpPrevDayLevel(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_prev_day_level", "Scalp: Prior-Day Level Break", CAT,
        "A close through yesterday's high rides the CE while it holds (yesterday's low mirrors).",
        TF, "trending",
    )

    class Params(BaseModel):
        pass

    @property
    def warmup(self) -> int:
        return 3

    def direction(self, ctx: StrategyContext) -> int | None:
        from strategy_service.strategies.options_buying._base import prev_day_hlc

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
class ScalpRoundLevel(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_round_level", "Scalp: Round-Number Break", CAT,
        "A momentum close through the nearest 100-point round level continues while it holds.",
        TF, "trending",
    )

    class Params(BaseModel):
        step: float = Field(default=100.0, gt=0)
        roc_period: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.roc_period + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        step = self.params.step
        level = round(closes[-1] / step) * step
        r = roc(closes, self.params.roc_period)[-1]
        crossed_up = closes[-2] < level <= closes[-1] and r > 0
        crossed_down = closes[-2] > level >= closes[-1] and r < 0
        if crossed_up:
            self._level = level
            self.why = f"took out {level:.0f}"
            return 1
        if crossed_down:
            self._level = level
            self.why = f"lost {level:.0f}"
            return -1
        held = getattr(self, "_level", None)
        if held is not None and self._dir != 0:
            if (self._dir > 0 and closes[-1] < held) or (self._dir < 0 and closes[-1] > held):
                self.why = f"level {held:.0f} recrossed"
                return 0
        return None


@register_strategy
class ScalpStreak(OptionBuyStrategy):
    metadata = buy_meta(
        "scalp_streak", "Scalp: Close Streak Continuation", CAT,
        "Four consecutive same-direction closes continue with the streak; the first opposite close exits.",
        TF, "trending",
    )

    class Params(BaseModel):
        run: int = Field(default=4, ge=2)

    @property
    def warmup(self) -> int:
        return self.params.run + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        n = self.params.run
        ups = all(closes[-i] > closes[-i - 1] for i in range(1, n + 1))
        downs = all(closes[-i] < closes[-i - 1] for i in range(1, n + 1))
        if ups:
            self.why = f"{n} straight up closes"
            return 1
        if downs:
            self.why = f"{n} straight down closes"
            return -1
        if (self._dir > 0 and closes[-1] < closes[-2]) or (self._dir < 0 and closes[-1] > closes[-2]):
            self.why = "streak broke"
            return 0
        return None
