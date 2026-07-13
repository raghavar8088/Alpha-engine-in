"""Shared base for the 50-strategy option-BUYING library (roadmap: options lab).

Every strategy here is a pure read of the UNDERLYING's bars (index spot), exactly like
the rest of the library — what makes it an *options* strategy is how the options
backtest engine consumes it: a BUY signal buys the ATM call, a SELL signal buys the
ATM put, and the engine manages premium stop/target, DTE and EOD square-off per style
(see options_service.options_backtest.OPTION_BUYING_CATEGORIES).

Subclasses implement `direction(ctx)` returning:
    +1  bullish regime  -> long CE
    -1  bearish regime  -> long PE
     0  no regime       -> exit any open structure
  None  keep whatever the previous direction was (hysteresis)

The base turns direction CHANGES into Signals, so each strategy stays a ~20-40 line
statement of its actual edge. Set `self.why` inside `direction()` for the signal's
reasoning string.

Index spot bars carry no volume (NSE publishes none for indices), so nothing in this
package keys off volume.
"""

from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata
from tradingai_shared.domain import AssetClass, Bar, Signal, SignalAction, Timeframe

CONFIDENCE = 0.55


def buy_meta(
    strategy_id: str, name: str, category: str, description: str,
    timeframe: Timeframe, suitable_market: str,
) -> StrategyMetadata:
    return StrategyMetadata(
        strategy_id=strategy_id, name=name, category=category, description=description,
        timeframes=[timeframe], asset_classes=[AssetClass.INDEX],
        suitable_market=suitable_market,
    )


class OptionBuyStrategy(Strategy):
    why: str = ""

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._dir = 0

    def direction(self, ctx: StrategyContext) -> int | None:
        raise NotImplementedError

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        new_dir = self.direction(ctx)
        if new_dir is None:
            new_dir = self._dir
        prev, self._dir = self._dir, new_dir
        if new_dir == prev:
            return None

        bar = ctx.current
        if new_dir > 0:
            action = SignalAction.BUY
        elif new_dir < 0:
            action = SignalAction.SELL
        else:
            action = SignalAction.EXIT_LONG if prev > 0 else SignalAction.EXIT_SHORT
        return Signal(
            symbol=bar.symbol, timeframe=bar.timeframe, signal=action,
            confidence=CONFIDENCE, source=self.metadata.strategy_id,
            timestamp=bar.ts, reasoning=self.why or self.metadata.name,
        )


# --- shared helpers -------------------------------------------------------------


def today_bars(ctx: StrategyContext) -> list[Bar]:
    """Bars belonging to the current bar's session (same calendar date)."""
    today = ctx.current.ts.date()
    out = []
    for bar in reversed(ctx.bars):
        if bar.ts.date() != today:
            break
        out.append(bar)
    out.reverse()
    return out


def prev_day_hlc(ctx: StrategyContext) -> tuple[float, float, float] | None:
    """Previous session's high/low/close, from whatever bars the context holds."""
    today = ctx.current.ts.date()
    prev_date = None
    high, low, close = None, None, None
    for bar in reversed(ctx.bars):
        d = bar.ts.date()
        if d == today:
            continue
        if prev_date is None:
            prev_date = d
            high, low, close = bar.high, bar.low, bar.close
            continue
        if d != prev_date:
            break
        high = max(high, bar.high)
        low = min(low, bar.low)
        # bars are chronological; iterating in reverse, the first bar seen for
        # prev_date already supplied the session close — don't overwrite it.
    if prev_date is None:
        return None
    return high, low, close


def supertrend_direction(bars: list[Bar], period: int = 10, mult: float = 3.0) -> int:
    """+1/-1 for the classic ATR-trailing supertrend at the last bar (0 if too short)."""
    if len(bars) < period + 2:
        return 0
    # Wilder ATR
    trs = []
    for i in range(1, len(bars)):
        b, p = bars[i], bars[i - 1]
        trs.append(max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close)))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period

    direction = 1
    upper = lower = None
    # recompute bands over the tail; enough history for the trail to settle
    tail = bars[-min(len(bars), period * 5):]
    for i in range(1, len(tail)):
        b = tail[i]
        mid = (b.high + b.low) / 2
        basic_upper, basic_lower = mid + mult * atr, mid - mult * atr
        upper = basic_upper if upper is None or basic_upper < upper or tail[i - 1].close > upper else upper
        lower = basic_lower if lower is None or basic_lower > lower or tail[i - 1].close < lower else lower
        if direction > 0 and b.close < lower:
            direction = -1
        elif direction < 0 and b.close > upper:
            direction = 1
    return direction


def swing_points(bars: list[Bar], strength: int = 3) -> tuple[list[float], list[float]]:
    """(swing_highs, swing_lows) — pivots stronger than `strength` bars each side."""
    highs, lows = [], []
    for i in range(strength, len(bars) - strength):
        window = bars[i - strength: i + strength + 1]
        if bars[i].high == max(b.high for b in window):
            highs.append(bars[i].high)
        if bars[i].low == min(b.low for b in window):
            lows.append(bars[i].low)
    return highs, lows
