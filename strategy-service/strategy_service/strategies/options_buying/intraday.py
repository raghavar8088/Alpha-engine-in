"""Option-buying INTRADAY strategies (#66-85) — 15-minute index bars, engine style
`options_intraday` (3-DTE premium, 30% premium stop / 60% target, EOD square-off).

Each class is one classic intraday read on index spot; +1 buys the ATM CE, -1 the ATM
PE. See _base.py for the direction-regime contract."""

from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import (
    adx, atr, donchian, ema, ichimoku, keltner, macd, prev_period_cpr, roc, rsi, sma,
    stdev, stochastic, session_vwap, zscore,
)
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, prev_day_hlc, swing_points, supertrend_direction, today_bars,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe

CAT = "options_intraday"
TF = Timeframe.M15
IST = timezone(timedelta(hours=5, minutes=30))


def _vwap(ctx: StrategyContext) -> list[float]:
    return session_vwap(ctx.bars, lambda b: b.ts.astimezone(IST).date())


def _ist_minutes(ctx: StrategyContext) -> int:
    ist = ctx.current.ts.astimezone(IST)
    return ist.hour * 60 + ist.minute


@register_strategy
class IntraOrb30(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_orb30", "Intraday: 30-min ORB", CAT,
        "First two 15m bars set the opening range; a close beyond it rides the break until re-entry.",
        TF, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=2, ge=1)

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
            self.why = f"above 30-min range high {or_high:.1f}"
            return 1
        if close < or_low:
            self.why = f"below 30-min range low {or_low:.1f}"
            return -1
        self.why = "inside opening range"
        return 0


@register_strategy
class IntraVwapTrend(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_vwap_trend", "Intraday: VWAP + EMA Trend", CAT,
        "Above session VWAP with EMA9>EMA21 rides the CE; the mirror rides the PE; disagreement exits.",
        TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=9, ge=2)
        slow: int = Field(default=21, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.slow + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        vwap = _vwap(ctx)[-1]
        f = ema(ctx.closes, self.params.fast)[-1]
        s = ema(ctx.closes, self.params.slow)[-1]
        close = ctx.current.close
        if close > vwap and f > s:
            self.why = f"above VWAP {vwap:.1f}, EMAs up"
            return 1
        if close < vwap and f < s:
            self.why = f"below VWAP {vwap:.1f}, EMAs down"
            return -1
        return 0


@register_strategy
class IntraCprBreak(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_cpr_break", "Intraday: CPR Break", CAT,
        "A close above the previous day's CPR top rides CE; below the CPR bottom rides PE; inside is flat.",
        TF, "trending",
    )

    class Params(BaseModel):
        buffer_pct: float = Field(default=0.03, ge=0)

    @property
    def warmup(self) -> int:
        return 30

    def direction(self, ctx: StrategyContext) -> int | None:
        hlc = prev_day_hlc(ctx)
        if hlc is None:
            return 0
        bc, _pivot, tc = prev_period_cpr(*hlc)
        close = ctx.current.close
        buf = close * self.params.buffer_pct / 100
        if close > tc + buf:
            self.why = f"above CPR top {tc:.1f}"
            return 1
        if close < bc - buf:
            self.why = f"below CPR bottom {bc:.1f}"
            return -1
        self.why = "inside CPR"
        return 0


@register_strategy
class IntraSupertrend(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_supertrend", "Intraday: Supertrend Flip", CAT,
        "Classic 10/3 ATR supertrend regime on 15m bars — its side is the option bought.",
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
class IntraEmaStack(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_ema_stack", "Intraday: EMA 9/21/50 Stack", CAT,
        "Full EMA stack alignment (9>21>50) is the regime; mixed stack exits.",
        TF, "trending",
    )

    class Params(BaseModel):
        fast: int = Field(default=9, ge=2)
        mid: int = Field(default=21, ge=5)
        slow: int = Field(default=50, ge=10)

    @property
    def warmup(self) -> int:
        return self.params.slow + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        f, m, s = ema(closes, self.params.fast)[-1], ema(closes, self.params.mid)[-1], ema(closes, self.params.slow)[-1]
        if f > m > s:
            self.why = "EMA stack up"
            return 1
        if f < m < s:
            self.why = "EMA stack down"
            return -1
        return 0


@register_strategy
class IntraRsiRegime(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_rsi_regime", "Intraday: RSI 55/45 Regime", CAT,
        "RSI(14) crossing 55 starts a bull regime held above 48; crossing 45 a bear regime held below 52.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=3)

    @property
    def warmup(self) -> int:
        return self.params.period + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        r = rsi(ctx.closes, self.params.period)
        if r[-2] < 55 <= r[-1]:
            self.why = f"RSI crossed 55 ({r[-1]:.0f})"
            return 1
        if r[-2] > 45 >= r[-1]:
            self.why = f"RSI crossed 45 ({r[-1]:.0f})"
            return -1
        if (self._dir > 0 and r[-1] < 48) or (self._dir < 0 and r[-1] > 52):
            self.why = "regime lost"
            return 0
        return None


@register_strategy
class IntraMacdTrend(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_macd_trend", "Intraday: MACD Trend", CAT,
        "Standard MACD(12/26/9) line-over-signal is the regime on 15m bars.",
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
        self.why = f"MACD hist {hist:.2f}"
        return 1 if hist > 0 else -1


@register_strategy
class IntraDonchian(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_donchian", "Intraday: Donchian 20 Break", CAT,
        "A close at the 20-bar Donchian extreme rides the break until the mid-channel.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        upper, lower = donchian(ctx.bars[:-1], self.params.period)
        close = ctx.current.close
        mid = (upper[-1] + lower[-1]) / 2
        if close > upper[-1]:
            self.why = f"broke {self.params.period}-bar high {upper[-1]:.1f}"
            return 1
        if close < lower[-1]:
            self.why = f"broke {self.params.period}-bar low {lower[-1]:.1f}"
            return -1
        if (self._dir > 0 and close < mid) or (self._dir < 0 and close > mid):
            self.why = "back at mid-channel"
            return 0
        return None


@register_strategy
class IntraStochSwing(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_stoch_swing", "Intraday: Stochastic Swing", CAT,
        "K crossing D under 30 buys the CE until K reaches 70 (mirror for PE from above 70).",
        TF, "range-bound",
    )

    class Params(BaseModel):
        k_period: int = Field(default=14, ge=5)
        d_period: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.k_period + self.params.d_period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        k, d = stochastic(ctx.bars, self.params.k_period, self.params.d_period)
        crossed_up = k[-2] <= d[-2] and k[-1] > d[-1]
        crossed_down = k[-2] >= d[-2] and k[-1] < d[-1]
        if crossed_up and k[-1] < 30:
            self.why = f"K over D in oversold ({k[-1]:.0f})"
            return 1
        if crossed_down and k[-1] > 70:
            self.why = f"K under D in overbought ({k[-1]:.0f})"
            return -1
        if (self._dir > 0 and k[-1] > 70) or (self._dir < 0 and k[-1] < 30):
            self.why = "swing complete"
            return 0
        return None


@register_strategy
class IntraBbRide(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_bb_ride", "Intraday: Band Ride", CAT,
        "A close outside the 2σ Bollinger band rides the walk until price loses the 20-SMA.",
        TF, "high-volatility",
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
            self.why = "lost the mid-band"
            return 0
        return None


@register_strategy
class IntraAdxDi(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_adx_di", "Intraday: ADX + DI", CAT,
        "ADX>22 with +DI dominant buys the CE (mirror PE); ADX fading under 18 exits.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=5)
        adx_entry: float = Field(default=22, gt=0)
        adx_exit: float = Field(default=18, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period * 3

    def direction(self, ctx: StrategyContext) -> int | None:
        adx_line, plus_di, minus_di = adx(ctx.bars, self.params.period)
        a = adx_line[-1]
        if a > self.params.adx_entry and plus_di[-1] > minus_di[-1]:
            self.why = f"ADX {a:.0f}, +DI dominant"
            return 1
        if a > self.params.adx_entry and minus_di[-1] > plus_di[-1]:
            self.why = f"ADX {a:.0f}, -DI dominant"
            return -1
        if a < self.params.adx_exit:
            self.why = f"ADX faded to {a:.0f}"
            return 0
        return None


@register_strategy
class IntraPivotBreak(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_pivot_break", "Intraday: R1/S1 Pivot Break", CAT,
        "A close above classic R1 rides CE, below S1 rides PE; back inside the pivot span exits.",
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
        pivot = (high + low + close_prev) / 3
        r1 = 2 * pivot - low
        s1 = 2 * pivot - high
        close = ctx.current.close
        if close > r1:
            self.why = f"above R1 {r1:.1f}"
            return 1
        if close < s1:
            self.why = f"below S1 {s1:.1f}"
            return -1
        if self._dir != 0 and s1 <= close <= r1:
            self.why = "back inside pivots"
            return 0
        return None


@register_strategy
class IntraMiddayVwapFade(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_midday_vwap_fade", "Intraday: Midday VWAP Fade", CAT,
        "After 12:30 IST, the first VWAP cross fades the morning move in the cross direction into the close.",
        TF, "range-bound",
    )

    class Params(BaseModel):
        start_minute: int = Field(default=12 * 60 + 30, description="minutes since IST midnight")

    @property
    def warmup(self) -> int:
        return 10

    def direction(self, ctx: StrategyContext) -> int | None:
        if _ist_minutes(ctx) < self.params.start_minute:
            return 0
        vwap = _vwap(ctx)
        closes = ctx.closes
        if len(vwap) < 2 or len(closes) < 2:
            return 0
        crossed_up = closes[-2] <= vwap[-2] and closes[-1] > vwap[-1]
        crossed_down = closes[-2] >= vwap[-2] and closes[-1] < vwap[-1]
        if crossed_up:
            self.why = "afternoon VWAP reclaim"
            return 1
        if crossed_down:
            self.why = "afternoon VWAP loss"
            return -1
        return None  # hold whatever the first afternoon cross set (engine EODs it)


@register_strategy
class IntraPullbackTrend(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_pullback_trend", "Intraday: 38% Pullback Resume", CAT,
        "In an EMA21>EMA55 up-move, a ≥38% retrace of the last 20-bar swing that reclaims EMA9 buys the dip.",
        TF, "trending",
    )

    class Params(BaseModel):
        swing_bars: int = Field(default=20, ge=10)
        retrace_pct: float = Field(default=38.0, gt=0, lt=100)

    @property
    def warmup(self) -> int:
        return 60

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        e9, e21, e55 = ema(closes, 9)[-1], ema(closes, 21)[-1], ema(closes, 55)[-1]
        window = ctx.bars[-self.params.swing_bars:]
        hi = max(b.high for b in window)
        lo = min(b.low for b in window)
        close = ctx.current.close
        if hi <= lo:
            return 0
        retrace_from_high = (hi - close) / (hi - lo) * 100
        retrace_from_low = (close - lo) / (hi - lo) * 100
        if e21 > e55 and retrace_from_high >= self.params.retrace_pct and close > e9:
            self.why = f"pullback {retrace_from_high:.0f}% reclaimed EMA9"
            return 1
        if e21 < e55 and retrace_from_low >= self.params.retrace_pct and close < e9:
            self.why = f"rally {retrace_from_low:.0f}% rejected at EMA9"
            return -1
        if (self._dir > 0 and close < e21) or (self._dir < 0 and close > e21):
            self.why = "through EMA21"
            return 0
        return None


@register_strategy
class IntraKeltnerTrend(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_keltner_trend", "Intraday: Keltner Trend", CAT,
        "A close beyond the 2×ATR Keltner channel rides that side until the mid-line goes.",
        TF, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=20, ge=5)
        mult: float = Field(default=2.0, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        upper, mid, lower = keltner(ctx.bars, self.params.period, self.params.mult)
        close = ctx.current.close
        if close > upper[-1]:
            self.why = f"above Keltner {upper[-1]:.1f}"
            return 1
        if close < lower[-1]:
            self.why = f"below Keltner {lower[-1]:.1f}"
            return -1
        if (self._dir > 0 and close < mid[-1]) or (self._dir < 0 and close > mid[-1]):
            self.why = "mid-line lost"
            return 0
        return None


@register_strategy
class IntraZscoreFade(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_zscore_fade", "Intraday: Z-Score Fade", CAT,
        "Fades a 2.25σ stretch against its 50-bar mean, out when the stretch normalizes.",
        TF, "range-bound",
    )

    class Params(BaseModel):
        period: int = Field(default=50, ge=10)
        entry_z: float = Field(default=2.25, gt=0)
        exit_z: float = Field(default=0.25, ge=0)

    @property
    def warmup(self) -> int:
        return self.params.period + 1

    def direction(self, ctx: StrategyContext) -> int | None:
        z = zscore(ctx.closes, self.params.period)[-1]
        if z < -self.params.entry_z:
            self.why = f"z={z:.2f} washout"
            return 1
        if z > self.params.entry_z:
            self.why = f"z={z:.2f} blowoff"
            return -1
        if abs(z) < self.params.exit_z:
            self.why = "normalized"
            return 0
        return None


@register_strategy
class IntraIchimokuTk(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_ichimoku_tk", "Intraday: Ichimoku TK Cross", CAT,
        "Tenkan/Kijun cross on the cloud's own side is the regime; price inside the cloud is flat.",
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
        tenkan, kijun, span_a, span_b = ichimoku(ctx.bars, self.params.tenkan, self.params.kijun, self.params.senkou_b)
        close = ctx.current.close
        cloud_top = max(span_a[-1], span_b[-1])
        cloud_bot = min(span_a[-1], span_b[-1])
        if cloud_bot <= close <= cloud_top:
            self.why = "inside the cloud"
            return 0
        if tenkan[-1] > kijun[-1] and close > cloud_top:
            self.why = "TK bullish above cloud"
            return 1
        if tenkan[-1] < kijun[-1] and close < cloud_bot:
            self.why = "TK bearish below cloud"
            return -1
        return None


@register_strategy
class IntraVwapReject(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_vwap_reject", "Intraday: VWAP Rejection Wick", CAT,
        "A bar that pierces VWAP but closes back on its original side is a rejection — trade with the rejection.",
        TF, "range-bound",
    )

    class Params(BaseModel):
        pass

    @property
    def warmup(self) -> int:
        return 5

    def direction(self, ctx: StrategyContext) -> int | None:
        vwap = _vwap(ctx)[-1]
        bar = ctx.current
        if bar.low < vwap and bar.open > vwap and bar.close > vwap:
            self.why = f"wick rejected VWAP {vwap:.1f} from above"
            return 1
        if bar.high > vwap and bar.open < vwap and bar.close < vwap:
            self.why = f"wick rejected VWAP {vwap:.1f} from below"
            return -1
        if (self._dir > 0 and bar.close < vwap) or (self._dir < 0 and bar.close > vwap):
            self.why = "VWAP actually broke"
            return 0
        return None


@register_strategy
class IntraPowerHour(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_power_hour", "Intraday: Power Hour Drift", CAT,
        "After 14:00 IST, if the day is up/down more than 0.3% from open, rides that drift into the close.",
        TF, "trending",
    )

    class Params(BaseModel):
        start_minute: int = Field(default=14 * 60)
        min_move_pct: float = Field(default=0.3, gt=0)

    @property
    def warmup(self) -> int:
        return 5

    def direction(self, ctx: StrategyContext) -> int | None:
        if _ist_minutes(ctx) < self.params.start_minute:
            return 0
        day = today_bars(ctx)
        if not day:
            return 0
        move_pct = (ctx.current.close - day[0].open) / day[0].open * 100
        if move_pct > self.params.min_move_pct:
            self.why = f"day up {move_pct:.2f}% into the close"
            return 1
        if move_pct < -self.params.min_move_pct:
            self.why = f"day down {move_pct:.2f}% into the close"
            return -1
        return 0


@register_strategy
class IntraStructureShift(OptionBuyStrategy):
    metadata = buy_meta(
        "intra_structure_shift", "Intraday: Market Structure Shift", CAT,
        "Rising swing highs AND lows over the last 40 bars is bullish structure (mirror bearish); mixed is flat.",
        TF, "trending",
    )

    class Params(BaseModel):
        lookback: int = Field(default=40, ge=20)
        pivot_strength: int = Field(default=3, ge=1)

    @property
    def warmup(self) -> int:
        return self.params.lookback + self.params.pivot_strength * 2

    def direction(self, ctx: StrategyContext) -> int | None:
        highs, lows = swing_points(ctx.bars[-self.params.lookback:], self.params.pivot_strength)
        if len(highs) < 2 or len(lows) < 2:
            return None
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            self.why = "higher highs and higher lows"
            return 1
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            self.why = "lower highs and lower lows"
            return -1
        self.why = "mixed structure"
        return 0
