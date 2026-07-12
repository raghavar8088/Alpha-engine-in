"""Option-buying strategies (#183-187) modeled on the publicly-shown system of
Trade For Sure (Rahul Singh's YouTube channel) — the "Option Trading Challenge"
series (daily NIFTY option trades, 3 lots). Extracted from 18 episode transcripts
(Hindi auto-captions) on 2026-07-12; see D:\\INDIAN MARKET\\TRADEFORSURE_NIFTY_
OPTION_STRATEGIES.md for the full extraction. "In the style of" the taught
CONCEPTS, not a reproduction of live calls or his paid course.

His system is pure price action — pre-marked levels, zero indicators except the
daily 200 EMA used AS a level. Stated series rules: analysis before entry only;
full SL or full target (min 1:2 RR), never book early; square off ~3:00 PM; max
2 trades/day, the 2nd only after an SL and with double confirmation; no revenge
trades; enter at the lower/middle of a zone when price struggles toward it, at
the upper edge when it runs straight in. The engine's premium stop/target (1:2)
and EOD square-off mirror the money rules; he buys ~0.8-delta ITM strikes where
the engine prices ATM (noted honestly, not hidden).
"""

from pydantic import BaseModel, Field

from strategy_service.indicators import ema
from strategy_service.strategies.options_buying._base import (
    OptionBuyStrategy, buy_meta, prev_day_hlc, swing_points, today_bars,
)
from strategy_service.strategies.options_buying.trade_room import (
    _bearish_entry_candle, _bullish_entry_candle,
)
from tradingai_shared.contracts import StrategyContext, register_strategy
from tradingai_shared.domain import Timeframe


@register_strategy
class TFSLevelReversal(OptionBuyStrategy):
    metadata = buy_meta(
        "tfs_level_reversal", "Trade For Sure: Level Reversal", "options_intraday",
        "The core Trade For Sure system: pre-marked support/resistance zones from recent swing "
        "points and the prior day's extremes, faded on first touch with a rejection candle — "
        "'draw the level, wait with patience, never trade randomly in between.' Buys the PE on "
        "a resistance rejection, the CE on a support hold; thesis dies if the level breaks.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        swing_strength: int = Field(default=3, ge=1)
        lookback: int = Field(default=80, ge=20)       # bars scanned for swing levels
        zone_pct: float = Field(default=0.12, gt=0)    # zone half-width around a level, %
        break_pct: float = Field(default=0.15, gt=0)   # close beyond level by this = thesis dead

    @property
    def warmup(self) -> int:
        return self.params.lookback + self.params.swing_strength * 2 + 2

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._faded_level: float | None = None
        self._session = None

    def _levels(self, ctx: StrategyContext) -> list[float]:
        window = ctx.bars[-self.params.lookback:]
        highs, lows = swing_points(window, self.params.swing_strength)
        levels = highs + lows
        hlc = prev_day_hlc(ctx)
        if hlc:
            levels += [hlc[0], hlc[1]]
        return levels

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        close = bar.close
        zone = close * self.params.zone_pct / 100

        # his day boundary: everything squares off ~3 PM, next session starts flat
        if bar.ts.date() != self._session:
            self._session = bar.ts.date()
            if self._dir != 0:
                self._faded_level = None
                self.why = "new session — yesterday's trade is closed, view resets"
                return 0

        # open-position management first: level break kills the thesis
        if self._dir != 0 and self._faded_level is not None:
            brk = self._faded_level * self.params.break_pct / 100
            if (self._dir < 0 and close > self._faded_level + brk) or (
                self._dir > 0 and close < self._faded_level - brk
            ):
                self._faded_level = None
                self.why = "faded level broke with a closing — view was wrong, out"
                return 0
            return None

        prev_close = ctx.bars[-2].close
        for level in self._levels(ctx):
            # resistance: approached from below, touched, rejected back under
            if (
                prev_close < level and bar.high >= level - zone and close < level
                and _bearish_entry_candle(bar, 0.45)
            ):
                self._faded_level = level
                self.why = f"resistance zone {level:.0f} rejected on first touch — sell side"
                return -1
            # support: approached from above, touched, held
            if (
                prev_close > level and bar.low <= level + zone and close > level
                and _bullish_entry_candle(bar, 0.45)
            ):
                self._faded_level = level
                self.why = f"support zone {level:.0f} held on first touch — buy side"
                return 1
        return None


@register_strategy
class TFSIndexSniper(OptionBuyStrategy):
    metadata = buy_meta(
        "tfs_index_sniper", "Trade For Sure: Index Sniper", "options_scalp",
        "His named 'Index Sniper' setup: when the market OPENS into (or gaps beyond) a "
        "pre-marked zone at the prior day's extreme, the reversal is taken immediately in the "
        "first candles — strike pre-set before open, 'target often done in 2-3 candles.' "
        "No open near a level, no trade.",
        Timeframe.M5, "high-volatility",
    )

    class Params(BaseModel):
        entry_bars: int = Field(default=3, ge=1)     # only this many bars into the session
        tol_pct: float = Field(default=0.15, gt=0)   # how close the open must be to the extreme

    @property
    def warmup(self) -> int:
        return 80  # needs the previous session's bars in context

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._level: float | None = None
        self._session = None

    def direction(self, ctx: StrategyContext) -> int | None:
        day = today_bars(ctx)
        bar = ctx.current

        if bar.ts.date() != self._session:
            self._session = bar.ts.date()
            if self._dir != 0:
                self._level = None
                self.why = "new session — sniper trade is done, flat"
                return 0

        if self._dir != 0 and self._level is not None:
            if (self._dir < 0 and bar.close > self._level) or (
                self._dir > 0 and bar.close < self._level
            ):
                self._level = None
                self.why = "sniper level lost — out"
                return 0
            return None

        if len(day) > self.params.entry_bars:
            return None
        hlc = prev_day_hlc(ctx)
        if hlc is None:
            return None
        prev_high, prev_low, _ = hlc
        open_ = day[0].open
        tol = open_ * self.params.tol_pct / 100

        if open_ >= prev_high - tol and bar.close < open_ and bar.close < prev_high:
            self._level = prev_high
            self.why = f"opened into yesterday's high {prev_high:.0f} and rejected — sniper PE"
            return -1
        if open_ <= prev_low + tol and bar.close > open_ and bar.close > prev_low:
            self._level = prev_low
            self.why = f"opened into yesterday's low {prev_low:.0f} and held — sniper CE"
            return 1
        return None


@register_strategy
class TFSTrapFade(OptionBuyStrategy):
    metadata = buy_meta(
        "tfs_trap_fade", "Trade For Sure: Trap Trading (failed range break)", "options_intraday",
        "His trap read: a candle CLOSES beyond a well-watched range ('everyone sees the "
        "breakdown and sells') but the move fails within a few bars and closes back inside — "
        "the trapped side fuels the reversal. Differs from a wick-poke trap: here the break "
        "actually closed, which is exactly what pulls traders in.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        range_bars: int = Field(default=20, ge=5)
        fail_within: int = Field(default=3, ge=1)    # bars the break has to fail in
        ext_pct: float = Field(default=0.35, gt=0)   # extension that confirms the break is real

    @property
    def warmup(self) -> int:
        return self.params.range_bars + self.params.fail_within + 2

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._armed: tuple[int, float, int] | None = None  # (dir_of_break, level, bars_left)
        self._session = None

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        close = bar.close

        if bar.ts.date() != self._session:
            self._session = bar.ts.date()
            if self._dir != 0:
                self._armed = None
                self.why = "new session — trap trade closed, flat"
                return 0

        if self._dir != 0 and self._armed is None:
            return None  # position runs on engine stops until the session reset

        window = ctx.bars[-self.params.range_bars - 1: -1]
        range_hi = max(b.high for b in window)
        range_lo = min(b.low for b in window)

        if self._armed is not None:
            break_dir, level, left = self._armed
            ext = level * self.params.ext_pct / 100
            if break_dir > 0:
                if close < level:  # bulls trapped
                    self._armed = None
                    self.why = f"breakout above {level:.0f} closed, then failed back inside — bulls trapped"
                    return -1
                if close > level + ext or left <= 1:
                    self._armed = None  # break sustained: he does not chase, no trade
                    return None
            else:
                if close > level:  # bears trapped
                    self._armed = None
                    self.why = f"breakdown below {level:.0f} closed, then failed back inside — bears trapped"
                    return 1
                if close < level - ext or left <= 1:
                    self._armed = None
                    return None
            self._armed = (break_dir, level, left - 1)
            return None

        if close > range_hi:
            self._armed = (1, range_hi, self.params.fail_within)
        elif close < range_lo:
            self._armed = (-1, range_lo, self.params.fail_within)
        return None


@register_strategy
class TFSGapOriginFade(OptionBuyStrategy):
    metadata = buy_meta(
        "tfs_gap_origin", "Trade For Sure: Gap-Origin Support/Resistance", "options_intraday",
        "His gap rule (Day 2 logic): after a BIG gap-up, the area the gap launched from acts as "
        "support when the market later comes back to fill the gap — 'it tries to take support "
        "once at that area.' Buys the CE on the first revisit of a gap-up origin, the PE at a "
        "gap-down origin; only large gaps count, small ones carry no memory.",
        Timeframe.M15, "range-bound",
    )

    class Params(BaseModel):
        min_gap_pct: float = Field(default=0.35, gt=0)
        zone_pct: float = Field(default=0.12, gt=0)
        valid_days: int = Field(default=4, ge=1)     # sessions the origin level stays tradeable
        break_pct: float = Field(default=0.2, gt=0)

    @property
    def warmup(self) -> int:
        return 60

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._origin: tuple[float, int, int] | None = None  # (level, gap_dir, sessions_left)
        self._last_date = None

    def direction(self, ctx: StrategyContext) -> int | None:
        bar = ctx.current
        close = bar.close
        day = today_bars(ctx)

        # once per session: reset yesterday's trade, age the stored origin, detect a fresh gap
        if bar.ts.date() != self._last_date:
            self._last_date = bar.ts.date()
            if self._dir != 0:
                self.why = "new session — yesterday's gap trade closed, flat"
                if self._origin is not None:
                    level, gap_dir, left = self._origin
                    self._origin = (level, gap_dir, left - 1) if left > 1 else None
                return 0
            if self._origin is not None:
                level, gap_dir, left = self._origin
                self._origin = (level, gap_dir, left - 1) if left > 1 else None
            hlc = prev_day_hlc(ctx)
            if hlc is not None and day:
                prev_close = hlc[2]
                gap_pct = (day[0].open - prev_close) / prev_close * 100
                if abs(gap_pct) >= self.params.min_gap_pct:
                    self._origin = (prev_close, 1 if gap_pct > 0 else -1, self.params.valid_days)

        if self._dir != 0 and self._origin is not None:
            level = self._origin[0]
            brk = level * self.params.break_pct / 100
            if (self._dir > 0 and close < level - brk) or (self._dir < 0 and close > level + brk):
                self.why = "gap-origin level broke — no support/resistance there after all"
                self._origin = None
                return 0
            return None

        if self._origin is None or self._dir != 0 or len(day) < 2:
            return None
        level, gap_dir, _ = self._origin
        zone = level * self.params.zone_pct / 100
        if gap_dir > 0 and bar.low <= level + zone and close > level and _bullish_entry_candle(bar, 0.45):
            self.why = f"gap-fill reached the gap-up origin {level:.0f} and held — buy side"
            return 1
        if gap_dir < 0 and bar.high >= level - zone and close < level and _bearish_entry_candle(bar, 0.45):
            self.why = f"rally reached the gap-down origin {level:.0f} and rejected — sell side"
            return -1
        return None


@register_strategy
class TFS200DMAReject(OptionBuyStrategy):
    metadata = buy_meta(
        "tfs_200dma_reject", "Trade For Sure: Daily 200-EMA Level", "options_swing",
        "The one indicator he uses — as a LEVEL, not a signal: the daily 200 EMA marked in "
        "advance ('I gave this level on Friday') and faded when price runs into it. A rally "
        "into the 200-day EMA from below that closes rejected buys the PE; a dip onto it from "
        "above that closes held buys the CE.",
        Timeframe.D1, "range-bound",
    )

    class Params(BaseModel):
        ema_period: int = Field(default=200, ge=50)
        band_pct: float = Field(default=0.4, gt=0)

    @property
    def warmup(self) -> int:
        return self.params.ema_period + 5

    def direction(self, ctx: StrategyContext) -> int | None:
        closes = ctx.closes
        e200 = ema(closes, self.params.ema_period)
        bar = ctx.current
        close = closes[-1]
        level = e200[-1]
        band = level * self.params.band_pct / 100
        prev_close = closes[-2]

        if prev_close < level and bar.high >= level - band and close < level and close < bar.open:
            self.why = f"rallied into the 200-DMA {level:.0f} and closed rejected — sell side"
            return -1
        if prev_close > level and bar.low <= level + band and close > level and close > bar.open:
            self.why = f"dipped onto the 200-DMA {level:.0f} and closed held — buy side"
            return 1
        if (self._dir < 0 and close > level + band * 2) or (self._dir > 0 and close < level - band * 2):
            self.why = "200-DMA level cleanly broken — fade over"
            return 0
        return None
