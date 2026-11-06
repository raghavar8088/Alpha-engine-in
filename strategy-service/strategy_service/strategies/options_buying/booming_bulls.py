"""Booming Bulls (Anish Singh Thakur) — 9 strategies (D1-D9). D3 mirrors the already-
coded order_block_fvg; D4/D5 are volume-profile-family strategies run on the same
time-at-price proxy as sb_volume_profile since NSE publishes no index volume. D9 is the
Nov-2026 "Liquidity Sweep" video + PDF, mechanised rule for rule (see its docstring)."""

import math
from datetime import timedelta, timezone

from pydantic import BaseModel, Field

from strategy_service.indicators import adx, ema
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, prev_day_hlc, swing_points, today_bars,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import SignalAction, Timeframe


@register_strategy
class BbUltimateConfluence(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_ultimate_confluence", "Booming Bulls: Ultimate Nifty & Stock Strategy (D1)", "options_intraday",
        "Trend + support/resistance confluence with a confirming candle: only trades "
        "when the EMA trend and a recent swing level agree.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        trend_ema: int = Field(default=34, ge=10)
        pivot_strength: int = Field(default=3, ge=1)
        lookback: int = Field(default=30, ge=15)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + self.params.lookback

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        trend = ema(closes, self.params.trend_ema)[-1]
        highs, lows = swing_points(ctx.bars[-self.params.lookback:], self.params.pivot_strength)
        if not highs or not lows:
            return 0
        bar = ctx.current
        if bar.close > trend and bar.low <= lows[-1] * 1.001 and bar.close > lows[-1]:
            self.why = "trend + demand-level confluence"
            return 1
        if bar.close < trend and bar.high >= highs[-1] * 0.999 and bar.close < highs[-1]:
            self.why = "trend + supply-level confluence"
            return -1
        return 0


@register_strategy
class BbLiquidityConcept(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_liquidity_concept", "Booming Bulls: Liquidity Concept (D2)", "options_intraday",
        "Sweep-and-reverse of a prior swing level, same family as Stock Burner's B4.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        lookback: int = Field(default=20, ge=8)

    @property
    def warmup(self) -> int:
        return self.params.lookback + 3

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.lookback - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        bar = ctx.current
        if bar.high > hi and bar.close < hi:
            self.why = f"liquidity swept above {hi:.0f}"
            return -1
        if bar.low < lo and bar.close > lo:
            self.why = f"liquidity swept below {lo:.0f}"
            return 1
        if self._dir != 0 and lo <= bar.close <= hi:
            self.why = "back inside"
            return 0
        return None


@register_strategy
class BbOrderBlockFvg(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_order_block_fvg", "Booming Bulls: Order Block + FVG (D3)", "options_intraday",
        "Same order-block/fair-value-gap mechanic as the shared order_block_fvg "
        "strategy; this channel's own naming, kept as its own catalog entry.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        impulse_mult: float = Field(default=1.8, gt=0)
        atr_period: int = Field(default=14, ge=5)
        retest_within: int = Field(default=10, ge=3)

    @property
    def warmup(self) -> int:
        return self.params.atr_period + self.params.retest_within + 3

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._ob = None

    def direction(self, ctx: StrategyContext) -> int | None:
        from strategy_service.indicators import atr as _atr

        bars = ctx.bars
        a = _atr(bars, self.params.atr_period)[-1]
        impulse = bars[-1]
        prior = bars[-2]
        is_up = (impulse.close - impulse.open) > self.params.impulse_mult * a
        is_down = (impulse.open - impulse.close) > self.params.impulse_mult * a
        has_gap_up = len(bars) >= 3 and bars[-3].high < impulse.low
        has_gap_down = len(bars) >= 3 and bars[-3].low > impulse.high
        if is_up and prior.close < prior.open and has_gap_up:
            self._ob = (prior.low, prior.high, 1, 0)
        elif is_down and prior.close > prior.open and has_gap_down:
            self._ob = (prior.low, prior.high, -1, 0)
        if self._ob is not None:
            lo, hi, d, age = self._ob
            age += 1
            if age > self.params.retest_within:
                self._ob = None
                return None
            close = ctx.current.close
            if lo <= close <= hi:
                self.why = f"order block retest [{lo:.0f}-{hi:.0f}]"
                self._ob = None
                return d
            self._ob = (lo, hi, d, age)
        return None


@register_strategy
class BbVolumeProfilePoc(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_volume_profile_poc", "Booming Bulls: Volume Profile / POC (D4)", "options_intraday",
        "No index volume exists; proxies the Point of Control with the time-at-price "
        "level (most-revisited close bucket) over the lookback window.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        lookback: int = Field(default=40, ge=15)
        bucket_pct: float = Field(default=0.1, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.lookback + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.lookback:]
        bucket = ctx.current.close * self.params.bucket_pct / 100
        counts: dict[int, int] = {}
        for b in window:
            k = round(b.close / bucket)
            counts[k] = counts.get(k, 0) + 1
        if not counts:
            return None
        poc = max(counts, key=counts.get) * bucket
        bar = ctx.current
        if bar.high >= poc and bar.close < poc:
            self.why = f"deflected at POC {poc:.0f}"
            return -1
        if bar.low <= poc and bar.close > poc:
            self.why = f"accepted off POC {poc:.0f}"
            return 1
        return None


@register_strategy
class BbFrvp(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_frvp", "Booming Bulls: FRVP — Fixed-Range Volume Profile (D5)", "options_intraday",
        "Fixed-range value-area proxy: the middle 60% (by time-at-price) of a chosen "
        "swing range acts as the value area, edges act as S/R.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=30, ge=15)

    @property
    def warmup(self) -> int:
        return self.params.range_bars + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        window = ctx.bars[-self.params.range_bars - 1: -1]
        hi, lo = max(b.high for b in window), min(b.low for b in window)
        rng = hi - lo
        if rng <= 0:
            return None
        va_hi = lo + rng * 0.8
        va_lo = lo + rng * 0.2
        bar = ctx.current
        if bar.low <= va_lo and bar.close > va_lo:
            self.why = f"held the value-area low {va_lo:.0f}"
            return 1
        if bar.high >= va_hi and bar.close < va_hi:
            self.why = f"rejected the value-area high {va_hi:.0f}"
            return -1
        return None


@register_strategy
class BbDailyBias(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_daily_bias", "Booming Bulls: Daily Bias (D6)", "options_intraday",
        "Sets a CE-only or PE-only regime for the day from the prior day's structure "
        "(higher-high/lower-low vs prior close), then acts on the first intraday break "
        "in that direction only.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        pass

    @property
    def warmup(self) -> int:
        return 10

    def direction(self, ctx: StrategyContext) -> int | None:
        hlc = prev_day_hlc(ctx)
        if hlc is None:
            return 0
        high, low, close_prev = hlc
        day = today_bars(ctx)
        if len(day) < 2:
            return 0
        bias_bullish = close_prev > (high + low) / 2
        bar = ctx.current
        if bias_bullish and bar.close > day[0].open:
            self.why = "bullish daily bias, price above open"
            return 1
        if not bias_bullish and bar.close < day[0].open:
            self.why = "bearish daily bias, price below open"
            return -1
        return 0


@register_strategy
class BbSimpleEntry(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_simple_entry", "Booming Bulls: Simple Entry Setup (D7)", "options_scalp",
        "Beginner-level ORB/trend entry — break of the opening range with the trend.",
        Timeframe.M5, "trending",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=3, ge=1)
        trend_ema: int = Field(default=20, ge=5)

    @property
    def warmup(self) -> int:
        return self.params.trend_ema + 2

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        n = self.params.range_bars
        if len(day) <= n:
            return 0
        hi = max(b.high for b in day[:n])
        lo = min(b.low for b in day[:n])
        trend = ema(ctx.closes, self.params.trend_ema)[-1]
        close = ctx.current.close
        if close > hi and close > trend:
            self.why = "ORB up with trend"
            return 1
        if close < lo and close < trend:
            self.why = "ORB down with trend"
            return -1
        return 0


@register_strategy
class BbAlgoSignal(OptionBuyStrategy):
    metadata = buy_meta(
        "bb_algo_signal", "Booming Bulls: AI/Algo Options (D8)", "options_intraday",
        "Execution tooling in the source, not a distinct edge. Stands in with an "
        "ADX-confirmed trend signal representing 'a generic algo trend signal'.",
        Timeframe.M15, "trending",
    )

    class Params(BaseModel):
        period: int = Field(default=14, ge=5)
        threshold: float = Field(default=25, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.period * 3

    def direction(self, ctx: StrategyContext) -> int | None:
        adx_line, plus_di, minus_di = adx(ctx.bars, self.params.period)
        if adx_line[-1] > self.params.threshold and plus_di[-1] > minus_di[-1]:
            self.why = f"algo-signal ADX {adx_line[-1]:.0f}, +DI"
            return 1
        if adx_line[-1] > self.params.threshold and minus_di[-1] > plus_di[-1]:
            self.why = f"algo-signal ADX {adx_line[-1]:.0f}, -DI"
            return -1
        if adx_line[-1] < 18:
            return 0
        return None


# ── D9: Liquidity Sweep (the Nov-2026 video + PDF) ─────────────────────────────────────

_IST = timezone(timedelta(hours=5, minutes=30))
_SESSION_OPEN = 9 * 60 + 15
_DAY_LEVELS = ("PDH", "PDL", "PDC")  # rebuilt every session; the swing levels carry over


class _Level:
    """One liquidity level. kind +1 = a high (buy-side liquidity above price), -1 = a low
    (sell-side liquidity below). `src` holds every merged source as (name, price, session);
    the level sits at the outermost of them."""

    __slots__ = ("kind", "src", "price", "state", "extreme", "beyond")

    def __init__(self, kind: int, name: str, price: float, session: int):
        self.kind = kind
        self.src = [(name, price, session)]
        self.price = price
        self.state = "armed"   # armed -> breached -> swept (closed back inside) | broken (accepted)
        self.extreme = 0.0     # furthest price since the breach began
        self.beyond = 0        # candles that closed beyond the level so far

    def reprice(self) -> None:
        prices = [p for _, p, _ in self.src]
        self.price = max(prices) if self.kind > 0 else min(prices)

    @property
    def names(self) -> str:
        return "+".join(dict.fromkeys(n for n, _, _ in self.src))


@register_strategy
class BbLiquiditySweep(OptionBuyStrategy):
    """Booming Bulls' liquidity-sweep video and PDF, mechanised.

    Levels: PDH, PDL, PDC, equal highs/lows (two swings within 0.04%) and 1-hour swing
    highs/lows. A sweep is a candle trading beyond one; the trade needs a candle CLOSING back
    inside within 30 minutes (else it was a breakout, which the video says never to trade).
    Entry at that close, stop just past the sweep's extreme, target 2R, flat by 15:15, at most
    2 trades a day. Every number the video leaves open is pinned (and justified) in
    backend/research/liquidity_sweep_2026_11/PREREGISTRATION.md, whose harness drives this
    class.

    State is incremental: each call processes only the bars it has not seen, so the result
    does not depend on how many bars the runner's context keeps. Bars older than the current
    one (a first call's history) only build levels; entries happen on the current bar alone.
    Entry signals carry the index stop and target (`Signal.stop_loss` / `Signal.target`),
    and `last_plan` holds the full plan for harnesses."""

    metadata = buy_meta(
        "bb_liquidity_sweep", "Booming Bulls: Liquidity Sweep — PDH/PDL/PDC (D9)", "options_intraday",
        "The Booming Bulls liquidity-sweep video + PDF (Nov 2026) as rules: mark PDH/PDL/PDC, "
        "equal highs/lows and 1-hour swing highs/lows; when price trades beyond one and a "
        "5-minute candle closes back inside within 30 minutes, fade it. Entry at that close, "
        "stop just past the sweep's extreme, target 1:2, flat by 15:15, never a direct breakout.",
        Timeframe.M5, "range-bound",
    )

    class Params(BaseModel):
        bar_minutes: int = Field(default=5, ge=1, le=15, description="candle length the rules run on (the video: 5)")
        equal_tol_pct: float = Field(default=0.04, gt=0, description="two swing highs/lows this close (% of price) are 'equal'")
        pivot_strength: int = Field(default=2, ge=1, description="candles each side that make a swing on the trading chart")
        hourly_pivot_strength: int = Field(default=2, ge=1, description="1-hour candles each side that make a 1H swing")
        swing_memory_days: int = Field(default=5, ge=1, description="sessions an untaken equal-H/L or 1H swing stays a level")
        max_minutes_beyond: int = Field(default=30, ge=1, description="minutes price may stay beyond a level before it is a breakout")
        stop_buffer_pct: float = Field(default=0.02, ge=0, description="stop distance past the sweep's extreme, % of price")
        min_risk_pct: float = Field(default=0.05, ge=0, description="skip a trade whose risk is below this % of price")
        max_risk_pct: float = Field(default=0.35, gt=0, description="skip a trade whose risk is above this % of price")
        reward_risk: float = Field(default=2.0, gt=0, description="target as a multiple of the risk")
        max_trades_per_day: int = Field(default=2, ge=1)
        last_entry_minute: int = Field(default=14 * 60 + 45, description="IST minute an entry candle must close by")
        square_off_minute: int = Field(default=15 * 60 + 15, description="IST minute an open trade is closed")
        ema_filter: int = Field(default=0, ge=0, description="0 = off; N = longs only above the N-EMA, shorts only below")

    @property
    def warmup(self) -> int:
        return 2

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._last_ts = None
        self._day = None
        self._sn = 0                 # session number
        self._hi = self._lo = self._close = 0.0
        self._prev = None            # (high, low, close) of the previous session
        self._n = 0                  # candle number
        self._first_n = (1, 1)       # first candle number of (previous, current) session
        self._bars: list[tuple[int, int, float, float]] = []   # (n, session, high, low)
        self._piv_hi: list[tuple[int, float]] = []
        self._piv_lo: list[tuple[int, float]] = []
        self._hour = None            # [session, bucket, high, low] of the forming 1-hour candle
        self._hourly: list[tuple[int, float, float]] = []      # (session, high, low)
        self._levels: list[_Level] = []
        self._pos: dict | None = None
        self._trades_today = 0
        self._ema: float | None = None
        self._ema_seed: list[float] = []
        self.last_plan: dict | None = None

    # -- runner interface --------------------------------------------------------------

    def on_bar(self, ctx: StrategyContext):
        signal = super().on_bar(ctx)
        if signal is not None and self._pos is not None and signal.signal in (SignalAction.BUY, SignalAction.SELL):
            signal.stop_loss = round(self._pos["stop"], 2)
            signal.target = round(self._pos["target"], 2)
        return signal

    def direction(self, ctx: StrategyContext) -> int | None:
        fresh = []
        for bar in reversed(ctx.bars):
            if self._last_ts is not None and bar.ts <= self._last_ts:
                break
            fresh.append(bar)
        out = None
        for bar in reversed(fresh):
            out = self._step(bar, live=bar is ctx.current)
        return out

    # -- one candle --------------------------------------------------------------------

    def _step(self, bar, live: bool) -> int | None:
        p = self.params
        self._last_ts = bar.ts
        ts = bar.ts if bar.ts.tzinfo else bar.ts.replace(tzinfo=timezone.utc)
        t = ts.astimezone(_IST)
        minute = t.hour * 60 + t.minute
        end = minute + p.bar_minutes
        if t.date() != self._day:
            self._new_session(t.date(), bar.open)
        self._n += 1
        n = self._n
        self._hi, self._lo, self._close = max(self._hi, bar.high), min(self._lo, bar.low), bar.close
        self._bars.append((n, self._sn, bar.high, bar.low))
        self._update_ema(bar.close)

        swept = self._run_levels(bar)        # live levels see this candle first ...
        self._find_swings(minute, end, bar)  # ... then levels it confirms (they lie beyond it)

        if self._pos is not None:
            return self._manage(bar, n, end)
        if not swept or not live:
            return 0
        return self._enter(bar, n, minute, end, swept)

    def _new_session(self, day, open_price: float) -> None:
        p = self.params
        if self._day is not None:
            self._prev = (self._hi, self._lo, self._close)
        self._close_hour()
        self._day = day
        self._sn += 1
        self._first_n = (self._first_n[1], self._n + 1)
        self._bars = [b for b in self._bars if b[0] >= self._first_n[0]]
        self._piv_hi = [x for x in self._piv_hi if x[0] >= self._first_n[0]]
        self._piv_lo = [x for x in self._piv_lo if x[0] >= self._first_n[0]]
        self._hi = self._lo = self._close = open_price
        self._trades_today = 0
        self._pos = None
        keep_from = self._sn - p.swing_memory_days
        kept = []
        for lv in self._levels:
            if lv.state != "armed":
                continue  # a break still unresolved at the close is spent
            lv.src = [s for s in lv.src if s[0] not in _DAY_LEVELS and s[2] >= keep_from]
            if not lv.src:
                continue
            lv.reprice()
            if (lv.kind > 0 and lv.price <= open_price) or (lv.kind < 0 and lv.price >= open_price):
                continue  # the gap already traded through it
            kept.append(lv)
        self._levels = kept
        if self._prev is not None:
            high, low, close = self._prev
            if high > open_price:
                self._add(+1, "PDH", high)
            if low < open_price:
                self._add(-1, "PDL", low)
            if close != open_price:
                self._add(+1 if close > open_price else -1, "PDC", close)

    def _add(self, kind: int, name: str, price: float) -> None:
        tol = price * self.params.equal_tol_pct / 100
        for lv in self._levels:
            if lv.kind == kind and lv.state == "armed" and abs(lv.price - price) <= tol:
                lv.src.append((name, price, self._sn))
                lv.reprice()
                return
        self._levels.append(_Level(kind, name, price, self._sn))

    def _run_levels(self, bar) -> list[_Level]:
        p = self.params
        limit = max(1, math.ceil(p.max_minutes_beyond / p.bar_minutes))
        swept = []
        for lv in self._levels:
            high_side = lv.kind > 0
            if lv.state == "armed":
                if not (bar.high > lv.price if high_side else bar.low < lv.price):
                    continue
                lv.state, lv.beyond = "breached", 0
                lv.extreme = bar.high if high_side else bar.low
            else:
                lv.extreme = max(lv.extreme, bar.high) if high_side else min(lv.extreme, bar.low)
            if (bar.close < lv.price) if high_side else (bar.close > lv.price):
                lv.state = "swept"
                swept.append(lv)
            else:
                lv.beyond += 1
                if lv.beyond >= limit:
                    lv.state = "broken"
        self._levels = [lv for lv in self._levels if lv.state in ("armed", "breached")]
        return swept

    def _find_swings(self, minute: int, end: int, bar) -> None:
        k = self.params.pivot_strength
        if len(self._bars) >= 2 * k + 1:
            win = self._bars[-(2 * k + 1):]
            if win[0][1] == self._sn:   # the whole window is this session
                c, left, right = win[k], win[:k], win[k + 1:]
                if c[2] >= max(x[2] for x in left) and c[2] > max(x[2] for x in right):
                    self._pivot(c[0], c[2], +1)
                if c[3] <= min(x[3] for x in left) and c[3] < min(x[3] for x in right):
                    self._pivot(c[0], c[3], -1)
        bucket = (minute - _SESSION_OPEN) // 60   # 1-hour candles 09:15, 10:15 ... 14:15
        if 0 <= bucket < 6:
            h = self._hour
            if h is None or h[0] != self._sn or h[1] != bucket:
                self._close_hour()
                self._hour = [self._sn, bucket, bar.high, bar.low]
            else:
                h[2], h[3] = max(h[2], bar.high), min(h[3], bar.low)
            if (end - _SESSION_OPEN) % 60 == 0:
                self._close_hour()

    def _pivot(self, n_c: int, price: float, kind: int) -> None:
        """A new swing on the trading chart; pair it with an older one into equal highs/lows."""
        pivots = self._piv_hi if kind > 0 else self._piv_lo
        tol = price * self.params.equal_tol_pct / 100
        base = self._bars[0][0]
        idx = n_c - base - 1          # walk the candles between the two swings, newest first
        between = None
        for n_old, p_old in reversed(pivots):
            while idx > n_old - base:
                v = self._bars[idx][2] if kind > 0 else self._bars[idx][3]
                between = v if between is None else (max(between, v) if kind > 0 else min(between, v))
                idx -= 1
            level = max(price, p_old) if kind > 0 else min(price, p_old)
            clean = between is None or (between <= level if kind > 0 else between >= level)
            if n_c - n_old >= 3 and abs(price - p_old) <= tol and clean:
                self._add(kind, "EQH" if kind > 0 else "EQL", level)
                break
            if between is not None and (between > price + tol if kind > 0 else between < price - tol):
                break                 # price already went past every older swing that could pair
        pivots.append((n_c, price))

    def _close_hour(self) -> None:
        h, self._hour = self._hour, None
        if h is None:
            return
        self._hourly.append((h[0], h[2], h[3]))
        del self._hourly[:-60]
        k = self.params.hourly_pivot_strength
        if len(self._hourly) < 2 * k + 1:
            return
        win = self._hourly[-(2 * k + 1):]
        c, left, right = win[k], win[:k], win[k + 1:]
        if c[1] >= max(x[1] for x in left) and c[1] > max(x[1] for x in right) and c[1] > self._close:
            self._add(+1, "1H high", c[1])
        if c[2] <= min(x[2] for x in left) and c[2] < min(x[2] for x in right) and c[2] < self._close:
            self._add(-1, "1H low", c[2])

    def _update_ema(self, close: float) -> None:
        n = self.params.ema_filter
        if not n:
            return
        if self._ema is None:
            self._ema_seed.append(close)
            if len(self._ema_seed) >= n:
                self._ema, self._ema_seed = sum(self._ema_seed) / n, []
            return
        k = 2 / (n + 1)
        self._ema = close * k + self._ema * (1 - k)

    # -- trades ------------------------------------------------------------------------

    def _manage(self, bar, n: int, end: int) -> int | None:
        pos = self._pos
        if n == pos["n"]:
            return None
        short = pos["side"] < 0
        stop_hit = bar.high >= pos["stop"] if short else bar.low <= pos["stop"]
        target_hit = bar.low <= pos["target"] if short else bar.high >= pos["target"]
        if stop_hit:   # a candle reaching both counts as the stop (minute data decides in the harness)
            why = f"stop {pos['stop']:.2f} hit"
        elif target_hit:
            why = f"target {pos['target']:.2f} reached (1:{self.params.reward_risk:g})"
        elif end >= self.params.square_off_minute:
            why = f"square-off at {bar.close:.2f}"
        else:
            return None
        self._pos = None
        self.why = why
        return 0

    def _enter(self, bar, n: int, minute: int, end: int, swept: list[_Level]) -> int:
        p = self.params
        if minute < _SESSION_OPEN or end > p.last_entry_minute or self._trades_today >= p.max_trades_per_day:
            return 0
        kinds = {lv.kind for lv in swept}
        if len(kinds) != 1:
            return 0   # one candle swept a high AND a low: ambiguous, skipped
        kind = kinds.pop()
        side = -kind
        entry = bar.close
        extreme = max(lv.extreme for lv in swept) if kind > 0 else min(lv.extreme for lv in swept)
        buffer = entry * p.stop_buffer_pct / 100
        stop = extreme + buffer if side < 0 else extreme - buffer
        risk = abs(entry - stop)
        if not p.min_risk_pct <= risk / entry * 100 <= p.max_risk_pct:
            return 0
        if p.ema_filter and (self._ema is None or (entry <= self._ema if side > 0 else entry >= self._ema)):
            return 0
        target = entry + side * p.reward_risk * risk
        self._pos = {"side": side, "n": n, "entry": entry, "stop": stop, "target": target}
        self._trades_today += 1
        levels = [(lv.names, lv.price) for lv in swept]
        self.last_plan = {"ts": bar.ts, "side": side, "entry": entry, "stop": stop, "target": target,
                          "risk": risk, "extreme": extreme, "levels": levels}
        named = " + ".join(f"{name} {price:.2f}" for name, price in levels)
        self.why = (f"swept {named} to {extreme:.2f}, closed back {'below' if side < 0 else 'above'} at "
                    f"{entry:.2f}: {'short (buy PE)' if side < 0 else 'long (buy CE)'}, stop {stop:.2f}, "
                    f"target {target:.2f}")
        return side
