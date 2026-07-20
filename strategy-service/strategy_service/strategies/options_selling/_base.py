"""Shared base for the option-SELLING library — premium sellers, not premium buyers.

WHY THIS IS NOT `OptionBuyStrategy` WITH A FLIPPED SIGN
------------------------------------------------------
The buying library's contract is a single number: +1 long CE, -1 long PE, 0 flat. That
works because every buying trade has the same shape (one ATM leg) and the same risk
(the premium paid). Selling has neither property:

  * The STRUCTURE is the strategy. "Sell premium because the tape is dead" is not a
    trade until you say which legs, at which strikes, and whether the tail is capped.
    A short strangle and an iron condor fire on identical regime reads and have
    completely different risk. So a selling strategy declares its legs, not a direction.

  * STRIKE SELECTION is part of the edge. Real sellers pick strikes by delta ("sell the
    15-delta strangle"), which floats with volatility — the same 15-delta strike sits
    2% out in a quiet tape and 5% out in a violent one. A fixed OTM percentage does not
    adapt; `target_delta` does. Both are supported here, per leg.

  * There is no exit-on-signal-flip symmetry. A buyer flat-to-long-to-flat is a
    complete lifecycle. A seller's position is usually closed by premium decay (take
    profit), premium expansion (stop), or expiry — the regime read only ever OPENS a
    position and, occasionally, forces it shut early.

So the contract here is: `want_open(ctx)` says whether the regime is worth selling into,
`legs(ctx)` says what to sell, and the selling backtest engine
(`options_service.options_selling_backtest`) materializes strikes, prices the structure,
blocks margin, and owns every exit. Signals carry SELL to open the credit structure and
EXIT_SHORT to close it — the desk is net SHORT premium, so that is the honest direction.

Index spot bars carry no volume (NSE publishes none for indices), so nothing here keys
off volume.
"""

from dataclasses import dataclass

from strategy_service.indicators import adx, atr, donchian, stdev
from tradingai_shared.contracts import Strategy, StrategyContext, StrategyMetadata
from tradingai_shared.domain import AssetClass, Bar, Signal, SignalAction, Timeframe

CONFIDENCE = 0.55


@dataclass(frozen=True)
class LegSpec:
    """One leg of a structure, declared RELATIVE to spot (or to its own short leg) so
    the engine can materialize the actual strike at entry.

    Exactly one of these positions the strike:
      * `otm_pct`  — signed distance from spot: +0.03 is 3% ABOVE spot, -0.03 is 3%
                     below, 0.0 is ATM. Simple, deterministic, does not adapt to vol.
      * `target_delta` — absolute delta to aim for (0.15 = the 15-delta strike). The
                     engine solves for the strike whose |delta| is closest, using the
                     same volatility it prices the structure with, then rounds to the
                     strike step. Adapts to volatility the way a real seller does.
      * `wing_pct` — protective legs only: this far BEYOND the short strike of the same
                     option type (a CE wing sits above the short call, a PE wing below
                     the short put).

    `wing_pct` exists because a wing anchored to SPOT does not do the job a wing is for.
    When the short leg is delta-selected its strike floats with volatility, so a
    spot-anchored wing produces a spread whose width — and therefore whose maximum loss
    and margin — changes trade to trade for reasons that have nothing to do with the
    strategy. Anchoring the wing to the short leg keeps the width fixed, which is the
    entire point of buying it.
    """

    option_type: str  # "CE" | "PE"
    sell: bool  # True = short this leg (collect), False = long (protection)
    otm_pct: float | None = None
    target_delta: float | None = None
    wing_pct: float | None = None

    def __post_init__(self):
        given = [x is not None for x in (self.otm_pct, self.target_delta, self.wing_pct)]
        if sum(given) != 1:
            raise ValueError("LegSpec needs exactly one of otm_pct / target_delta / wing_pct")
        if self.wing_pct is not None and self.sell:
            raise ValueError("wing_pct is for protective (long) legs only")
        if self.option_type.upper() not in ("CE", "PE"):
            raise ValueError(f"bad option_type {self.option_type!r}")


def sell_meta(
    strategy_id: str, name: str, category: str, description: str,
    timeframe: Timeframe, suitable_market: str,
) -> StrategyMetadata:
    return StrategyMetadata(
        strategy_id=strategy_id, name=name, category=category, description=description,
        timeframes=[timeframe], asset_classes=[AssetClass.INDEX_OPTION, AssetClass.INDEX],
        suitable_market=suitable_market,
    )


class OptionSellStrategy(Strategy):
    """Subclasses implement `want_open(ctx) -> bool` (is this a regime worth selling
    into?) and `legs(ctx) -> list[LegSpec]` (what to sell). Set `self.why` inside
    `want_open` for the signal's reasoning string.

    Optionally override `force_close(ctx) -> bool` to shut a position early on a regime
    read (e.g. a trend igniting under a short strangle). The engine's own stop-loss,
    take-profit, strike-pressure and expiry exits run regardless — a strategy can never
    opt OUT of risk control, only add to it.
    """

    why: str = ""

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._open = False

    def want_open(self, ctx: StrategyContext) -> bool:
        raise NotImplementedError

    def legs(self, ctx: StrategyContext) -> list[LegSpec]:
        raise NotImplementedError

    def force_close(self, ctx: StrategyContext) -> bool:
        """Regime-driven early close. Default: never — let the engine's risk controls
        and expiry own the exit."""
        return False

    def position_closed(self) -> None:
        """Called by the engine whenever the structure closes for ANY reason (stop,
        target, expiry, EOD), so the strategy's own open/flat flag can never drift out
        of sync with the engine's actual position. A strategy that thought it was still
        short would refuse to re-enter for the rest of the run."""
        self._open = False

    def on_bar(self, ctx: StrategyContext) -> Signal | None:
        bar = ctx.current
        if self._open:
            if self.force_close(ctx):
                self._open = False
                return Signal(
                    symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.EXIT_SHORT,
                    confidence=CONFIDENCE, source=self.metadata.strategy_id, timestamp=bar.ts,
                    reasoning=self.why or "regime turned against the short",
                )
            return None

        if self.want_open(ctx):
            self._open = True
            return Signal(
                symbol=bar.symbol, timeframe=bar.timeframe, signal=SignalAction.SELL,
                confidence=CONFIDENCE, source=self.metadata.strategy_id, timestamp=bar.ts,
                reasoning=self.why or self.metadata.name,
            )
        return None


# --- regime helpers shared across the selling library ----------------------------
#
# These answer the seller's only real question: is premium RICH relative to what the
# tape is likely to deliver? Selling into a cheap, about-to-explode tape is how selling
# strategies blow up, so most of these are filters that say NO.


def realized_vol(closes: list[float], window: int) -> float:
    """Annualized realized vol over the last `window` closes (0.0 if too short).

    Deliberately computed on whatever series the STRATEGY sees, unlike the pricing
    engine's IV proxy which always uses daily closes — here it is a regime read
    ("is this tape quiet relative to itself?"), not a premium level.
    """
    import math

    recent = closes[-window - 1:]
    if len(recent) < 3:
        return 0.0
    rets = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent)) if recent[i - 1] > 0]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def vol_rank(closes: list[float], window: int, lookback: int) -> float | None:
    """Where current realized vol sits in its own recent range, 0.0-1.0 (None if short).

    This is the closest honest stand-in for IV RANK available here: real IV rank needs a
    historical implied-vol series, and Dhan serves no expired-chain history to build one
    from (the same constraint that forces Black-Scholes synthetic premiums throughout
    this app). Realized-vol rank is well correlated with IV rank and is computed from
    data that actually exists. It is NOT the same number, and nothing in this library
    should claim it is.
    """
    if len(closes) < window + lookback + 2:
        return None
    series = [realized_vol(closes[: len(closes) - i], window) for i in range(lookback)]
    series = [v for v in series if v > 0]
    if len(series) < 5:
        return None
    current, lo, hi = series[0], min(series), max(series)
    if hi <= lo:
        return None
    return (current - lo) / (hi - lo)


def is_range_bound(bars: list[Bar], adx_period: int, max_adx: float) -> tuple[bool, float]:
    """(verdict, adx_now) — the classic dead-trend read every neutral seller wants."""
    adx_now = adx(bars, adx_period)[0][-1]
    return adx_now <= max_adx, adx_now


def range_position(bars: list[Bar], period: int) -> float:
    """Where the last close sits inside its N-bar Donchian range, 0.0 (low) to 1.0
    (high). Sellers use this to avoid selling puts at the top of a range or calls at
    the bottom, where the short strike is closest to being run over.

    Computes only the CURRENT window rather than calling `donchian()`, which builds the
    channel for every bar in the context and then throws all but the last value away.
    Identical arithmetic — `donchian`'s final element is the high/low of the `period`
    bars ending just before the current one — but O(period) instead of O(bars x period).
    Profiling the selling sweep, the discarded-series version was 25 of every 36 seconds
    of runtime; the strategies themselves were nearly free by comparison.
    """
    if len(bars) < period + 1:
        raise ValueError(f"need at least {period + 1} bars, got {len(bars)}")
    window = bars[-(period + 1):-1]  # excludes the current bar, matching donchian()
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    if hi <= lo:
        return 0.5
    return max(0.0, min(1.0, (bars[-1].close - lo) / (hi - lo)))


def compression(bars: list[Bar], period: int, lookback: int) -> bool:
    """True when the close-to-close deviation is at the bottom of its recent range — a
    coil. Sellers like coils; they also die in them when the coil resolves, which is why
    every strategy that uses this pairs it with a hard stop rather than trusting it."""
    closes = [b.close for b in bars]
    sd = stdev(closes, period)
    if len(sd) < lookback + 1:
        return False
    return sd[-1] <= min(sd[-lookback:]) * 1.05


def atr_pct(bars: list[Bar], period: int) -> float:
    """ATR as a percentage of price — a scale-free read on how wide the tape is."""
    a = atr(bars, period)[-1]
    close = bars[-1].close
    return (a / close * 100) if close > 0 else 0.0


def gap_pct(ctx: StrategyContext) -> float:
    """Today's open vs the previous session's close, in percent (0.0 if unknowable).

    Gaps are the seller's specific enemy: they are exactly the move a stop-loss cannot
    protect against, because the position reprices before any stop can fire.
    """
    today = ctx.current.ts.date()
    prev_close, first_open = None, None
    for bar in reversed(ctx.bars):
        if bar.ts.date() == today:
            first_open = bar.open
            continue
        prev_close = bar.close
        break
    if prev_close is None or first_open is None or prev_close <= 0:
        return 0.0
    return (first_open - prev_close) / prev_close * 100
