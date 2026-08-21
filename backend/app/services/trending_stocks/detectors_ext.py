"""Six long-only setup detectors the Strategy Factory does not ship.

WHY THESE SIX AND NOT MORE
---------------------------
The factory already carries 28 detectors plus 23 shapes adapted from the tested
`commodity_patterns` library, and five of its own detectors are not referenced by any
recipe at all (`pivot_level_break`, `channel_break`, `roc_momentum`, `obv_breakout`,
`rvol_thrust`). Most of what this module needs is therefore a new *recipe* over an
existing detector, not new detection code. Only these six shapes have no implementation
anywhere in the app:

  anchored_vwap_reclaim  the average price everyone who bought this leg actually paid
  fifty_two_week_high    the one level with no overhead supply above it
  ichimoku_kumo          the cloud (the indicator exists; nothing detects a break of it)
  vcp                    Minervini's volatility contraction — tightening ranges on falling volume
  rs_vs_benchmark        relative strength against NIFTY, which needs a SECOND series
  rsi_failure_swing      Wilder's own confirmation, distinct from the divergence detector

EVERY DETECTOR HERE IS LONG-ONLY, by construction rather than by filtering. This desk
never shorts, so a detector that can only return `SELL` would be dead code that still
costs a scan slot on every bar of every backtest.

NO LOOK-AHEAD
-------------
Same contract as the factory: read `bars[:-1]` for context and `bars[-1]` as the completed
signal bar, and use `CP.pivots`, whose right-hand confirmation means the last `right` bars
can never be pivots. Nothing indexes past the end.

THE BENCHMARK PROBLEM
---------------------
`rs_vs_benchmark` needs NIFTY bars alongside the symbol's own — something the factory's
`detect(name, bars, params)` signature cannot express. Rather than change that signature
(and every caller of it), this module adds `detect_ext()`, which takes an optional
`ctx` dict. Detectors that need nothing extra are looked up in the factory's registry
unchanged, so there is exactly one implementation of each shape in the app.
"""

from __future__ import annotations

from typing import Callable, Optional

from strategy_service.indicators import atr as atr_series, ichimoku, rsi

from app.services import commodity_patterns as CP
from app.services.strategy_factory.detectors import DETECTORS as FACTORY_DETECTORS, Setup


# --------------------------------------------------------------------------------
# Shared helpers (mirrors of the factory's, kept local so this module stands alone)
# --------------------------------------------------------------------------------


def _atr(bars, n: int = 14) -> float:
    s = atr_series(bars, n)
    return s[-1] if s else 0.0


def _swing_low(bars, lookback: int) -> float:
    return min(b.low for b in bars[-lookback:])


def _closes(bars) -> list[float]:
    return [b.close for b in bars]


def _distinct_pivots(indices: list[int], min_gap: int) -> list[int]:
    """Collapse runs of adjacent pivot indices into one.

    `CP.pivots` marks EVERY bar that ties the extreme of its window, so a flat-topped
    turn produces three or four consecutive "swing highs" at the same price. Any rule that
    then zips the last N highs against the last N lows — as the contraction detector does
    — ends up pairing one peak with three different troughs and measuring nonsense. Keeping
    the last index of each run picks the bar the market actually turned on."""
    if not indices:
        return []
    out = [indices[0]]
    for i in indices[1:]:
        if i - out[-1] <= min_gap:
            out[-1] = i
        else:
            out.append(i)
    return out


def _structural_low(bars, lookback: int, entry: float) -> Optional[float]:
    """A recent swing low, but only if it is actually below the entry.

    A 'structural stop' at or above entry is not a stop; returning None makes the caller
    drop the setup instead of building inverted levels that `build_levels` would reject
    a moment later anyway."""
    low = _swing_low(bars, max(lookback, 2))
    return low if low < entry else None


# --------------------------------------------------------------------------------
# 1. Anchored VWAP
# --------------------------------------------------------------------------------


def anchored_vwap_reclaim(bars, p) -> Optional[Setup]:
    """VWAP anchored to the most recent CONFIRMED swing low.

    Session VWAP answers "what did today's participants pay". Anchored VWAP answers the
    more useful question for a swing long: *what did everyone who bought this advance
    pay*. Price crossing back above it means the average buyer of the leg is back in
    profit, which is where supply from trapped holders stops.

    The anchor is a `CP.pivots` low, so it is only used once price has turned away from
    it — an unconfirmed low would move under us bar by bar and repaint the level."""
    k = p.get("pivot", 4)
    _highs, lows = CP.pivots(bars, k, k)
    if not lows:
        return None
    anchor = lows[-1]
    seg = bars[anchor:]
    if len(seg) < p.get("min_since_anchor", 8) or len(bars) < 3:
        return None

    vals: list[float] = []
    pv = tv = 0.0
    for b in seg:
        typical = (b.high + b.low + b.close) / 3
        # Volume can legitimately be 0 on an illiquid bar; weight it as 1 rather than
        # dropping the bar, so the anchor still advances through quiet patches.
        v = b.volume if b.volume and b.volume > 0 else 1.0
        pv += typical * v
        tv += v
        vals.append(pv / tv)
    if len(vals) < 3 or tv <= 0:
        return None

    last, prev = bars[-1].close, bars[-2].close
    if not (prev <= vals[-2] and last > vals[-1]):
        return None
    stop = _structural_low(bars, p.get("stop_lookback", 14), last)
    if stop is None:
        return None
    return Setup("BUY", last, stop, None, "Anchored VWAP Reclaim",
                 f"Reclaimed VWAP {vals[-1]:.2f} anchored to the swing low "
                 f"{bars[anchor].low:.2f} {len(seg)} bars ago")


# --------------------------------------------------------------------------------
# 2. 52-week / all-time high
# --------------------------------------------------------------------------------


def fifty_two_week_high(bars, p) -> Optional[Setup]:
    """A close above the highest high of the lookback window.

    The reason this is not just another Donchian breakout: at a 52-week (or all-time)
    high there is nobody holding a losing position from higher up, so the supply that
    normally caps an advance does not exist. The lookback is expressed in BARS and comes
    from the timeframe profile, so "52 weeks" means the same amount of market time on a
    daily chart as the equivalent window does on an hourly one.

    Requires a real base: the window's high must be at least `min_base` bars old, so a
    series that has been making new highs every single bar (a vertical move) does not
    fire this on every bar of the run."""
    n = p.get("high_window", 250)
    if len(bars) < min(n, p.get("min_bars_required", 120)) + 2:
        return None
    seg = bars[-(n + 1):-1]
    if len(seg) < p.get("min_base", 40):
        return None
    prior_high = max(b.high for b in seg)
    last = bars[-1]
    if last.close <= prior_high:
        return None
    idx = max(range(len(seg)), key=lambda i: seg[i].high)
    age = len(seg) - idx
    if age < p.get("min_base", 40):
        return None
    stop = _structural_low(bars, p.get("stop_lookback", 20), last.close)
    if stop is None:
        return None
    label = "All-Time High Breakout" if len(bars) <= n + 2 else f"{n}-Bar High Breakout"
    return Setup("BUY", last.close, stop, None, label,
                 f"Closed {last.close:.2f} above the {n}-bar high {prior_high:.2f}, "
                 f"which had stood for {age} bars")


# --------------------------------------------------------------------------------
# 3. Ichimoku cloud
# --------------------------------------------------------------------------------


def ichimoku_kumo(bars, p) -> Optional[Setup]:
    """Price crossing up out of the cloud, with the conversion line above the base line.

    Two independent statements have to agree: price has left the zone of equilibrium
    (the kumo) to the upside, and the short-term midline (tenkan) is above the medium
    one (kijun). The cloud alone fires on every chop through a thin kumo; the tenkan/
    kijun alignment is what makes it a trend statement.

    `strategy_service.indicators.ichimoku` returns the lines WITHOUT forward
    displacement, which is what we want — a displaced cloud drawn 26 bars ahead is a
    projection, and comparing today's price to it is not look-ahead but it is also not
    what the classic rule says."""
    t_len, k_len, b_len = p.get("tenkan", 9), p.get("kijun", 26), p.get("senkou_b", 52)
    if len(bars) < b_len + 3:
        return None
    try:
        tenkan, kijun, span_a, span_b = ichimoku(bars, t_len, k_len, b_len)
    except ValueError:
        return None
    if len(tenkan) < 3:
        return None

    top_now = max(span_a[-1], span_b[-1])
    top_prev = max(span_a[-2], span_b[-2])
    last, prev = bars[-1].close, bars[-2].close
    if not (prev <= top_prev and last > top_now):
        return None
    if tenkan[-1] <= kijun[-1]:
        return None
    # The cloud's own floor is the natural invalidation: back inside it and the break
    # was noise. Fall back to a swing low when the cloud bottom sits above entry.
    bottom = min(span_a[-1], span_b[-1])
    stop = bottom if bottom < last else _structural_low(bars, p.get("stop_lookback", 16), last)
    if stop is None or stop >= last:
        return None
    return Setup("BUY", last, stop, None, "Ichimoku Kumo Breakout",
                 f"Closed {last:.2f} above the cloud top {top_now:.2f} with "
                 f"tenkan {tenkan[-1]:.2f} over kijun {kijun[-1]:.2f}")


# --------------------------------------------------------------------------------
# 4. Volatility Contraction Pattern
# --------------------------------------------------------------------------------


def vcp(bars, p) -> Optional[Setup]:
    """Successive pullbacks getting shallower while volume dries up, then a break.

    The hypothesis is about SUPPLY, not price: each pullback shakes out a tranche of
    weak holders, and when each successive shake-out is smaller than the last there is
    less stock left to sell. The volume contraction is what separates this from an
    ordinary triangle — a tightening range on RISING volume is distribution.

    Detection is mechanical: take the confirmed swing highs and lows, measure the depth
    of the last `contractions` pullbacks, require each to be meaningfully shallower than
    the one before it, require the recent volume average to be below the earlier one,
    and require the last bar to close above the most recent swing high."""
    k = p.get("pivot", 4)
    need = int(p.get("contractions", 3))
    highs, lows = CP.pivots(bars, k, k)
    highs, lows = _distinct_pivots(highs, k), _distinct_pivots(lows, k)
    if len(highs) < need or len(lows) < need:
        return None

    depths: list[float] = []
    for h_idx, l_idx in zip(highs[-need:], lows[-need:]):
        # Only count a high->low pair that is actually a pullback (low after the high).
        if l_idx <= h_idx:
            return None
        hi, lo = bars[h_idx].high, bars[l_idx].low
        if hi <= 0:
            return None
        depths.append((hi - lo) / hi)
    if len(depths) < need:
        return None
    tighten = float(p.get("tighten", 0.75))
    for earlier, later in zip(depths, depths[1:]):
        if later > earlier * tighten:
            return None

    w = int(p.get("vol_window", 20))
    if len(bars) < w * 2 + 2:
        return None
    recent_vol = sum(b.volume for b in bars[-w:]) / w
    earlier_vol = sum(b.volume for b in bars[-2 * w:-w]) / w
    if earlier_vol <= 0 or recent_vol > earlier_vol * float(p.get("vol_dryup", 0.9)):
        return None

    pivot_high = bars[highs[-1]].high
    last = bars[-1].close
    if last <= pivot_high:
        return None
    stop = bars[lows[-1]].low
    if stop >= last:
        return None
    return Setup("BUY", last, stop, None, "Volatility Contraction Breakout",
                 f"{need} tightening pullbacks ({', '.join(f'{d*100:.1f}%' for d in depths)}) "
                 f"on {recent_vol/earlier_vol:.2f}x volume, then cleared {pivot_high:.2f}")


# --------------------------------------------------------------------------------
# 5. Relative strength vs a benchmark  (needs a second series)
# --------------------------------------------------------------------------------


def rs_vs_benchmark(bars, p, ctx: dict | None = None) -> Optional[Setup]:
    """The ratio line (symbol / NIFTY) makes a new high before price does.

    Cross-sectional strength expressed as a single-instrument rule: dividing the stock by
    the index removes the market's own move, so what is left is the part that is this
    stock's. A ratio line at a new high while price is still inside its own range is the
    leadership showing up before the breakout does.

    The benchmark series is passed in `ctx["bench"]`. If it is missing the detector
    returns None rather than falling back to price alone — a strategy that advertises
    relative strength must not silently become an absolute-momentum strategy."""
    bench = (ctx or {}).get("bench") or []
    if not bench or len(bars) < 5:
        return None
    w = int(p.get("rs_window", 40))
    if len(bars) < w + 2:
        return None

    # Align on timestamp: the two series can differ in length and in holidays, and
    # zipping them positionally would compare a stock bar to an unrelated index bar.
    bench_by_ts = {b.ts: b.close for b in bench}
    ratio: list[float] = []
    for b in bars[-(w + 1):]:
        bc = bench_by_ts.get(b.ts)
        if not bc:
            continue
        ratio.append(b.close / bc)
    if len(ratio) < max(10, w // 2):
        return None
    if ratio[-1] < max(ratio[:-1]) or len(ratio) < 3:
        return None
    if ratio[-1] <= ratio[-2]:
        return None

    price_seg = [b.high for b in bars[-(w + 1):-1]]
    last = bars[-1].close
    if not price_seg or last > max(price_seg):
        # Price has ALREADY broken out — then this is a plain breakout, and the
        # `donchian` recipes own that hypothesis. This one is about leading it.
        return None
    stop = _structural_low(bars, p.get("stop_lookback", 16), last)
    if stop is None:
        return None
    lead = (ratio[-1] / ratio[0] - 1) * 100
    return Setup("BUY", last, stop, None, "Relative Strength Leadership",
                 f"Ratio vs benchmark at a {len(ratio)}-bar high ({lead:+.1f}% over the "
                 f"window) while price is still {(max(price_seg)/last - 1)*100:.1f}% "
                 "below its own high")


# --------------------------------------------------------------------------------
# 6. RSI failure swing
# --------------------------------------------------------------------------------


def rsi_failure_swing(bars, p) -> Optional[Setup]:
    """Wilder's bullish failure swing: RSI dips into oversold, recovers, pulls back
    WITHOUT making a new RSI low, then takes out the intervening RSI peak.

    This is not the divergence detector wearing a different name. Divergence compares
    RSI to PRICE. A failure swing is entirely inside the oscillator: it is RSI failing to
    confirm its own low, and Wilder considered it the stronger of the two signals
    precisely because it needs no reference to price at all."""
    period = int(p.get("rsi_period", 14))
    look = int(p.get("fs_window", 30))
    if len(bars) < period + look + 3:
        return None
    try:
        r = rsi(_closes(bars), period)
    except ValueError:
        return None
    seg = r[-look:]
    if len(seg) < 8:
        return None

    low_th = float(p.get("oversold", 35))
    trough = min(range(len(seg)), key=lambda i: seg[i])
    if seg[trough] > low_th or trough >= len(seg) - 4:
        return None
    after = seg[trough + 1:]
    if len(after) < 4:
        return None

    # Walk BACK from the current bar while RSI is still rising: that lands on the low the
    # final rally started from, which is the pullback. Taking the maximum of everything
    # after the trough instead would simply find the current bar — the highest reading is
    # usually now — and the "intervening peak" it is supposed to clear would be itself.
    i = len(after) - 1
    while i > 0 and after[i - 1] < after[i]:
        i -= 1
    if i == 0:
        return None            # RSI has risen monotonically — no retest to fail on
    pullback = after[i]
    before_pullback = after[:i]
    if not before_pullback:
        return None
    peak_val = max(before_pullback)

    if pullback <= seg[trough]:
        return None            # made a lower RSI low — that is not a failure swing
    if seg[-1] <= peak_val:
        return None            # has not yet taken out the intervening peak
    if peak_val - pullback < float(p.get("min_dip", 3.0)):
        return None            # no real pullback to fail on

    last = bars[-1].close
    stop = _structural_low(bars, p.get("stop_lookback", 14), last)
    if stop is None:
        return None
    return Setup("BUY", last, stop, None, "RSI Bullish Failure Swing",
                 f"RSI bottomed at {seg[trough]:.1f}, rallied to {peak_val:.1f}, held "
                 f"{pullback:.1f} on the retest and has now cleared the peak ({seg[-1]:.1f})")


# --------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------

# Detectors that need only (bars, params) — same contract as the factory's.
EXT_DETECTORS: dict[str, Callable] = {
    "avwap_swing": anchored_vwap_reclaim,
    "high_52w": fifty_two_week_high,
    "ichimoku_kumo": ichimoku_kumo,
    "vcp": vcp,
    "rsi_failure_swing": rsi_failure_swing,
}

# ...and those that additionally need context (a second series, today).
CTX_DETECTORS: dict[str, Callable] = {
    "rs_vs_bench": rs_vs_benchmark,
}

ALL_EXT_NAMES = set(EXT_DETECTORS) | set(CTX_DETECTORS)


def detect_ext(name: str, bars, params: dict, ctx: dict | None = None) -> Optional[Setup]:
    """Resolve a detector by name across this module AND the factory's registry.

    The factory is checked last and used unchanged, so there is exactly one
    implementation of every shape the app knows about. A detector error costs one signal,
    never the scan — the same rule the factory's `detect()` follows."""
    try:
        fn = CTX_DETECTORS.get(name)
        if fn is not None:
            return fn(bars, params, ctx)
        fn = EXT_DETECTORS.get(name) or FACTORY_DETECTORS.get(name)
        if fn is None:
            return None
        return fn(bars, params)
    except (IndexError, ValueError, ZeroDivisionError, TypeError, KeyError):
        return None


def known_detector(name: str) -> bool:
    return name in ALL_EXT_NAMES or name in FACTORY_DETECTORS


__all__ = ["Setup", "EXT_DETECTORS", "CTX_DETECTORS", "ALL_EXT_NAMES",
           "detect_ext", "known_detector", "_distinct_pivots"]
