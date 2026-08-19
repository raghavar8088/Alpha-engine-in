"""Setup detectors for the Strategy Factory.

A detector answers one question: *is my setup present on the last bar?* It returns the
raw geometry — side, entry, the level that invalidates the idea, and (where the pattern
projects one) a measured move — and nothing about position size, targets-as-multiples or
costs. Those belong to the recipe and the engine, so the same detector can be reused by
several strategies that manage the trade differently.

REUSE, NOT REIMPLEMENTATION
---------------------------
The 13 chart and 10 candlestick shapes already exist, tested, in
`app.services.commodity_patterns` (39 templates, 50 assertions, all verified firing on
purpose-built data). Rewriting them here would create a second copy to keep in step, so
they are adapted through `_from_commodity` instead: that module detects the shape, and
this one keeps the side/entry/invalidation and discards its target, because in the
factory the TARGET is the recipe's decision, not the detector's.

Everything the commodity library does not already cover — market structure, session
levels, the indicator families, volume — is implemented below.

NO LOOK-AHEAD
-------------
Every detector reads `bars[:-1]` for context and `bars[-1]` as the completed signal bar.
Nothing indexes past the end, and swing pivots require right-hand confirmation, so a
detector can never see a bar that would not have existed at decision time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

from strategy_service.indicators import (
    adx, atr as atr_series, cci, donchian, ema, keltner, macd, psar, roc, rsi,
    session_vwap, sma, stdev, stochastic, williams_r,
)

from app.services import commodity_patterns as CP


@dataclass
class Setup:
    side: str                              # BUY | SELL
    entry: float
    structural_stop: Optional[float]       # level that invalidates the idea
    measured_target: Optional[float]       # pattern projection, when it has one
    pattern: str
    detail: str


def _atr(bars, n: int = 14) -> float:
    s = atr_series(bars, n)
    return s[-1] if s else 0.0


def _c(bars) -> list[float]:
    return [b.close for b in bars]


def _swing_low(bars, lookback: int) -> float:
    return min(b.low for b in bars[-lookback:])


def _swing_high(bars, lookback: int) -> float:
    return max(b.high for b in bars[-lookback:])


# --------------------------------------------------------------------------------
# Adapter: reuse the tested commodity chart / candlestick detectors
# --------------------------------------------------------------------------------


class _Shim:
    """Minimal stand-in for commodity_patterns.PatternSpec — those detectors only ever
    read `.params`."""

    __slots__ = ("params",)

    def __init__(self, params: dict):
        self.params = params


def _from_commodity(template: str):
    """Wrap a commodity_patterns template as a factory detector.

    Its stoploss becomes our structural invalidation level; its target is dropped so the
    recipe can set reward from its own hypothesis."""
    entry = CP.TEMPLATES.get(template)
    if entry is None:
        raise KeyError(f"unknown commodity template {template!r}")
    _family, label, fn, default_params, _min_bars = entry

    def detect(bars, params: dict) -> Optional[Setup]:
        merged = {**default_params, **(params or {})}
        try:
            sig = fn(_Shim(merged), bars)
        except (IndexError, ValueError, ZeroDivisionError, TypeError, KeyError):
            return None
        if sig is None:
            return None
        return Setup(side=sig.side, entry=sig.entry, structural_stop=sig.stoploss,
                     measured_target=None, pattern=sig.pattern, detail=sig.rationale)

    detect.__name__ = f"cp_{template}"
    detect.label = label
    return detect


# --------------------------------------------------------------------------------
# Extra candlestick shapes the commodity library does not separate out
# --------------------------------------------------------------------------------


def inverted_hammer(bars, p) -> Optional[Setup]:
    """Small body, long UPPER wick, at a local low — a failed push down that closed near
    the bottom of the bar is a hammer; this is the mirror that closed near the top after
    being rejected upward, read as exhaustion of the decline."""
    if len(bars) < p["window"] + 2:
        return None
    b = bars[-1]
    rng, body = b.high - b.low, abs(b.close - b.open)
    if rng <= 0 or body <= 0:
        return None
    upper = b.high - max(b.open, b.close)
    lower = min(b.open, b.close) - b.low
    if upper < body * p["wick_mult"] or upper < lower * p["wick_mult"]:
        return None
    if b.low > min(x.low for x in bars[-p["window"]:]):
        return None
    return Setup("BUY", b.close, b.low, None, "Inverted Hammer",
                 f"Inverted hammer at a {p['window']}-bar low: upper wick {upper:.2f} vs body {body:.2f}")


def hanging_man(bars, p) -> Optional[Setup]:
    """Hammer shape appearing at a local HIGH after an advance — same geometry, opposite
    meaning, because the location is what makes it bearish."""
    if len(bars) < p["window"] + 2:
        return None
    b = bars[-1]
    rng, body = b.high - b.low, abs(b.close - b.open)
    if rng <= 0 or body <= 0:
        return None
    upper = b.high - max(b.open, b.close)
    lower = min(b.open, b.close) - b.low
    if lower < body * p["wick_mult"] or lower < upper * p["wick_mult"]:
        return None
    if b.high < max(x.high for x in bars[-p["window"]:]):
        return None
    return Setup("SELL", b.close, b.high, None, "Hanging Man",
                 f"Hanging man at a {p['window']}-bar high: lower wick {lower:.2f} vs body {body:.2f}")


def multi_inside_compression(bars, p) -> Optional[Setup]:
    """Two or more consecutive inside bars — compression tightening inside one mother bar
    — then a break of the mother's range. More inside bars means a coiled spring, so this
    is a distinct hypothesis from the single inside bar, not a parameter tweak."""
    n = p["min_inside"]
    if len(bars) < n + 3:
        return None
    mother = bars[-(n + 2)]
    inside = bars[-(n + 1):-1]
    if len(inside) < n:
        return None
    if not all(x.high <= mother.high and x.low >= mother.low for x in inside):
        return None
    mrng = mother.high - mother.low
    if mrng <= 0:
        return None
    if not all(inside[i].high - inside[i].low <= (inside[i - 1].high - inside[i - 1].low)
               for i in range(1, len(inside))):
        return None
    cur = bars[-1]
    if cur.close > mother.high:
        return Setup("BUY", cur.close, mother.low, None, "Multi Inside Bar Breakout",
                     f"{len(inside)} tightening inside bars, mother high {mother.high:.2f} broken")
    if cur.close < mother.low:
        return Setup("SELL", cur.close, mother.high, None, "Multi Inside Bar Breakdown",
                     f"{len(inside)} tightening inside bars, mother low {mother.low:.2f} broken")
    return None


# --------------------------------------------------------------------------------
# Market structure
# --------------------------------------------------------------------------------


def _sessions(bars) -> dict:
    out: dict = {}
    for b in bars:
        out.setdefault(b.ts.date(), []).append(b)
    return out


def break_of_structure(bars, p) -> Optional[Setup]:
    """Break of Structure: price takes out the most recent confirmed swing in the
    direction of the prevailing swing sequence — trend continuation."""
    hi, lo = CP.pivots(bars, p["pivot"], p["pivot"])
    if len(hi) < 2 or len(lo) < 2:
        return None
    h1, h2 = bars[hi[-2]].high, bars[hi[-1]].high
    l1, l2 = bars[lo[-2]].low, bars[lo[-1]].low
    last = bars[-1].close
    if h2 > h1 and l2 > l1 and last > h2:
        return Setup("BUY", last, l2, None, "Break of Structure",
                     f"Higher-high sequence intact and swing high {h2:.2f} taken out")
    if h2 < h1 and l2 < l1 and last < l2:
        return Setup("SELL", last, h2, None, "Break of Structure",
                     f"Lower-low sequence intact and swing low {l2:.2f} taken out")
    return None


def change_of_character(bars, p) -> Optional[Setup]:
    """Change of Character: the FIRST break against an established swing sequence — the
    earliest objective evidence a trend has stopped behaving like one."""
    hi, lo = CP.pivots(bars, p["pivot"], p["pivot"])
    if len(hi) < 2 or len(lo) < 2:
        return None
    h1, h2 = bars[hi[-2]].high, bars[hi[-1]].high
    l1, l2 = bars[lo[-2]].low, bars[lo[-1]].low
    last = bars[-1].close
    if h2 < h1 and l2 < l1 and last > h2:
        return Setup("BUY", last, l2, None, "Change of Character",
                     f"Downtrend structure broken upward through {h2:.2f}")
    if h2 > h1 and l2 > l1 and last < l2:
        return Setup("SELL", last, h2, None, "Change of Character",
                     f"Uptrend structure broken downward through {l2:.2f}")
    return None


def support_resistance_flip(bars, p) -> Optional[Setup]:
    """A level that capped price becomes the floor it holds (or the reverse) — the retest
    entry, rather than chasing the initial break."""
    hi, lo = CP.pivots(bars, p["pivot"], p["pivot"])
    atr = _atr(bars)
    if atr <= 0:
        return None
    last, prev = bars[-1], bars[-2]
    tol = atr * p["tol_atr"]
    for idx in reversed(hi[-4:] if hi else []):
        level = bars[idx].high
        if prev.low <= level + tol and prev.close > level and last.close > prev.close:
            return Setup("BUY", last.close, level - tol, None, "Resistance-turned-Support",
                         f"Old resistance {level:.2f} retested and held as support")
    for idx in reversed(lo[-4:] if lo else []):
        level = bars[idx].low
        if prev.high >= level - tol and prev.close < level and last.close < prev.close:
            return Setup("SELL", last.close, level + tol, None, "Support-turned-Resistance",
                         f"Old support {level:.2f} retested and rejected as resistance")
    return None


def prev_period_break(bars, p) -> Optional[Setup]:
    """Break of the previous WEEK's or MONTH's extreme — a slower structural level than
    the prior session, and the one swing traders actually watch."""
    period = p["period"]
    key = (lambda b: (b.ts.isocalendar()[0], b.ts.isocalendar()[1])) if period == "week" \
        else (lambda b: (b.ts.year, b.ts.month))
    groups: dict = {}
    for b in bars:
        groups.setdefault(key(b), []).append(b)
    ordered = [groups[k] for k in sorted(groups)]
    if len(ordered) < 2:
        return None
    prev = ordered[-2]
    ph, pl = max(b.high for b in prev), min(b.low for b in prev)
    last = bars[-1].close
    if last > ph:
        return Setup("BUY", last, pl, None, f"Previous {period.title()} High Break",
                     f"Above the previous {period}'s high {ph:.2f}")
    if last < pl:
        return Setup("SELL", last, ph, None, f"Previous {period.title()} Low Break",
                     f"Below the previous {period}'s low {pl:.2f}")
    return None


def vwap_reclaim(bars, p) -> Optional[Setup]:
    """Price crossing back through the session VWAP — the level institutional execution
    is benchmarked to, so a reclaim flips the intraday balance of who is offside."""
    vw = session_vwap(bars)
    if not vw or len(vw) < 3:
        return None
    last, prev = bars[-1].close, bars[-2].close
    v = vw[-1]
    atr = _atr(bars)
    if atr <= 0:
        return None
    if prev < v <= last:
        return Setup("BUY", last, v - atr * p["stop_atr"], None, "VWAP Reclaim",
                     f"Reclaimed session VWAP {v:.2f} from below")
    if prev > v >= last:
        return Setup("SELL", last, v + atr * p["stop_atr"], None, "VWAP Rejection",
                     f"Rejected at session VWAP {v:.2f} from above")
    return None


def gap_continuation(bars, p) -> Optional[Setup]:
    """A session opening away from the prior close and CONTINUING in the gap direction —
    the opposite hypothesis to the gap fade, and it needs its own strategy."""
    days = sorted({b.ts.date() for b in bars})
    if len(days) < 2:
        return None
    today = [b for b in bars if b.ts.date() == days[-1]]
    prev = [b for b in bars if b.ts.date() == days[-2]]
    if len(today) < 2 or not prev:
        return None
    prev_close, open_px = prev[-1].close, today[0].open
    if prev_close <= 0:
        return None
    gap = (open_px - prev_close) / prev_close
    if abs(gap) < p["min_gap"]:
        return None
    last = bars[-1].close
    if gap > 0 and last > max(b.high for b in today[:-1]):
        return Setup("BUY", last, min(b.low for b in today), None, "Gap-Up Continuation",
                     f"Gapped up {gap*100:+.2f}% and is extending above the session high")
    if gap < 0 and last < min(b.low for b in today[:-1]):
        return Setup("SELL", last, max(b.high for b in today), None, "Gap-Down Continuation",
                     f"Gapped down {gap*100:+.2f}% and is extending below the session low")
    return None


def pivot_level_break(bars, p) -> Optional[Setup]:
    """Floor-trader pivots off the previous session. `level` selects R1/R2/S1/S2 so the
    aggressive first-target break and the extended second-target break are separate
    hypotheses rather than one with a tweaked constant."""
    days = sorted({b.ts.date() for b in bars})
    if len(days) < 2:
        return None
    prev = [b for b in bars if b.ts.date() == days[-2]]
    if not prev:
        return None
    ph, pl, pc = max(b.high for b in prev), min(b.low for b in prev), prev[-1].close
    pivot = (ph + pl + pc) / 3
    rng = ph - pl
    levels = {"R1": 2 * pivot - pl, "R2": pivot + rng, "S1": 2 * pivot - ph, "S2": pivot - rng}
    lv = levels[p["level"]]
    last, prev_close = bars[-1].close, bars[-2].close
    if p["level"].startswith("R") and prev_close <= lv < last:
        return Setup("BUY", last, pivot, None, f"Pivot {p['level']} Break",
                     f"Broke {p['level']} {lv:.2f} (pivot {pivot:.2f})")
    if p["level"].startswith("S") and prev_close >= lv > last:
        return Setup("SELL", last, pivot, None, f"Pivot {p['level']} Break",
                     f"Broke {p['level']} {lv:.2f} (pivot {pivot:.2f})")
    return None


def fib_retracement(bars, p) -> Optional[Setup]:
    """Reaction at a Fibonacci retracement of the last measured swing. `ratio` selects
    38.2 / 50 / 61.8 / 78.6 — shallow retracements imply a strong trend and deep ones a
    tiring trend, so they are genuinely different trades."""
    w = p["window"]
    if len(bars) < w + 3:
        return None
    seg = bars[-w:]
    hi_i = max(range(len(seg)), key=lambda i: seg[i].high)
    lo_i = min(range(len(seg)), key=lambda i: seg[i].low)
    hi, lo = seg[hi_i].high, seg[lo_i].low
    if hi <= lo:
        return None
    ratio = p["ratio"]
    rng = hi - lo
    tol = rng * p["tol"]
    last, prev = bars[-1].close, bars[-2].close
    if lo_i < hi_i:
        level = hi - rng * ratio
        if abs(prev - level) <= tol and last > prev:
            return Setup("BUY", last, level - tol, hi, f"Fib {ratio*100:.1f}% Bounce",
                         f"Held the {ratio*100:.1f}% retracement {level:.2f} of {lo:.2f}->{hi:.2f}")
    else:
        level = lo + rng * ratio
        if abs(prev - level) <= tol and last < prev:
            return Setup("SELL", last, level + tol, lo, f"Fib {ratio*100:.1f}% Rejection",
                         f"Rejected the {ratio*100:.1f}% retracement {level:.2f} of {hi:.2f}->{lo:.2f}")
    return None


def range_rectangle_break(bars, p) -> Optional[Setup]:
    """A rectangle / trading range: a band that has contained price for N bars, then a
    close outside it. The measured move projects the range height from the break."""
    n = p["window"]
    if len(bars) < n + 3:
        return None
    seg = bars[-(n + 1):-1]
    hi, lo = max(b.high for b in seg), min(b.low for b in seg)
    height = hi - lo
    if height <= 0:
        return None
    mid = (hi + lo) / 2
    # A rectangle needs to have CONTAINED price, not merely bracketed a trend.
    closes = [b.close for b in seg]
    if max(closes) > hi * (1 - p["contain"]) and min(closes) < lo * (1 + p["contain"]):
        pass
    band = height / mid if mid else 1
    if band > p["max_band"]:
        return None
    last = bars[-1].close
    if last > hi:
        return Setup("BUY", last, lo, last + height, "Rectangle Breakout",
                     f"Cleared a {n}-bar range {lo:.2f}-{hi:.2f}; measured move {height:.2f}")
    if last < lo:
        return Setup("SELL", last, hi, last - height, "Rectangle Breakdown",
                     f"Lost a {n}-bar range {lo:.2f}-{hi:.2f}; measured move {height:.2f}")
    return None


def channel_break(bars, p) -> Optional[Setup]:
    """A sloping channel — parallel rails through the swing highs and lows — broken
    against its own slope. Distinct from a wedge: the rails here are parallel, so the
    break is a trend failure rather than a compression resolution."""
    hi, lo = CP.pivots(bars, p["pivot"], p["pivot"])
    if len(hi) < 2 or len(lo) < 2:
        return None
    hs = [bars[i].high for i in hi[-3:]]
    ls = [bars[i].low for i in lo[-3:]]
    sh, sl = CP._slope(hs), CP._slope(ls)
    if abs(sh - sl) > p["parallel_tol"]:
        return None
    m = p["slope_min"]
    last = bars[-1].close
    if sh >= m and sl >= m and last < min(ls):
        return Setup("SELL", last, max(hs), None, "Rising Channel Break",
                     f"Rising channel (highs {sh*100:+.2f}%, lows {sl*100:+.2f}%/bar) lost its lower rail")
    if sh <= -m and sl <= -m and last > max(hs):
        return Setup("BUY", last, min(ls), None, "Falling Channel Break",
                     f"Falling channel (highs {sh*100:+.2f}%, lows {sl*100:+.2f}%/bar) cleared its upper rail")
    return None


# --------------------------------------------------------------------------------
# Indicator families
# --------------------------------------------------------------------------------


def ema_cross(bars, p) -> Optional[Setup]:
    """Fast EMA crossing the slow one. `fast`/`slow` select the pair; the 50/200 pair is
    the golden/death cross and is given its own recipe because its horizon and its
    interpretation differ from a 9/21 scalp cross."""
    closes = _c(bars)
    f, s = ema(closes, p["fast"]), ema(closes, p["slow"])
    if len(f) < 2 or len(s) < 2:
        return None
    n = min(len(f), len(s))
    f, s = f[-n:], s[-n:]
    last = closes[-1]
    atr = _atr(bars)
    if atr <= 0:
        return None
    if f[-2] <= s[-2] and f[-1] > s[-1]:
        return Setup("BUY", last, min(_swing_low(bars, p["stop_lookback"]), last - atr), None,
                     p["label"], f"{p['fast']} EMA crossed above the {p['slow']} EMA")
    if f[-2] >= s[-2] and f[-1] < s[-1]:
        return Setup("SELL", last, max(_swing_high(bars, p["stop_lookback"]), last + atr), None,
                     p["label"], f"{p['fast']} EMA crossed below the {p['slow']} EMA")
    return None


def rsi_regime(bars, p) -> Optional[Setup]:
    """RSI used as a TREND regime filter (40/60 bands) rather than an overbought oscillator
    — crossing 60 from below marks momentum expansion, not an exit signal."""
    r = rsi(_c(bars), p["period"])
    if len(r) < 3:
        return None
    atr = _atr(bars)
    last = bars[-1].close
    if atr <= 0:
        return None
    if r[-2] < p["up"] <= r[-1]:
        return Setup("BUY", last, _swing_low(bars, p["stop_lookback"]), None, "RSI Trend Regime",
                     f"RSI crossed above {p['up']} ({r[-1]:.1f}) — momentum regime turned up")
    if r[-2] > p["down"] >= r[-1]:
        return Setup("SELL", last, _swing_high(bars, p["stop_lookback"]), None, "RSI Trend Regime",
                     f"RSI crossed below {p['down']} ({r[-1]:.1f}) — momentum regime turned down")
    return None


def rsi_extreme_reversal(bars, p) -> Optional[Setup]:
    """The classic 30/70 mean-reversion read — turning back OUT of the extreme, which is
    what separates a reversal from standing in front of a trend."""
    r = rsi(_c(bars), p["period"])
    if len(r) < 3:
        return None
    last = bars[-1].close
    if r[-2] <= p["low"] and r[-1] > r[-2]:
        return Setup("BUY", last, _swing_low(bars, p["stop_lookback"]), None, "RSI Oversold Reversal",
                     f"RSI turned up out of {p['low']} ({r[-2]:.1f} -> {r[-1]:.1f})")
    if r[-2] >= p["high"] and r[-1] < r[-2]:
        return Setup("SELL", last, _swing_high(bars, p["stop_lookback"]), None, "RSI Overbought Reversal",
                     f"RSI turned down out of {p['high']} ({r[-2]:.1f} -> {r[-1]:.1f})")
    return None


def rsi_divergence(bars, p) -> Optional[Setup]:
    """Price makes a new extreme, RSI does not — the momentum behind the move is fading.
    Measured on confirmed swing pivots so the divergence cannot repaint."""
    r = rsi(_c(bars), p["period"])
    if len(r) < p["window"] + 5:
        return None
    hi, lo = CP.pivots(bars, p["pivot"], p["pivot"])
    off = len(bars) - len(r)
    last = bars[-1].close
    if len(lo) >= 2:
        a, b = lo[-2], lo[-1]
        if a - off >= 0 and b - off >= 0 and bars[b].low < bars[a].low and r[b - off] > r[a - off]:
            return Setup("BUY", last, bars[b].low, None, "Bullish RSI Divergence",
                         f"Price low {bars[b].low:.2f} < {bars[a].low:.2f} but RSI "
                         f"{r[b-off]:.1f} > {r[a-off]:.1f}")
    if len(hi) >= 2:
        a, b = hi[-2], hi[-1]
        if a - off >= 0 and b - off >= 0 and bars[b].high > bars[a].high and r[b - off] < r[a - off]:
            return Setup("SELL", last, bars[b].high, None, "Bearish RSI Divergence",
                         f"Price high {bars[b].high:.2f} > {bars[a].high:.2f} but RSI "
                         f"{r[b-off]:.1f} < {r[a-off]:.1f}")
    return None


def macd_signal_cross(bars, p) -> Optional[Setup]:
    line, sig, hist = macd(_c(bars), p["fast"], p["slow"], p["signal"])
    if len(line) < 3 or len(sig) < 3:
        return None
    n = min(len(line), len(sig))
    line, sig = line[-n:], sig[-n:]
    last = bars[-1].close
    if line[-2] <= sig[-2] and line[-1] > sig[-1]:
        return Setup("BUY", last, _swing_low(bars, p["stop_lookback"]), None, "MACD Bullish Cross",
                     f"MACD {line[-1]:.4f} crossed above its signal {sig[-1]:.4f}")
    if line[-2] >= sig[-2] and line[-1] < sig[-1]:
        return Setup("SELL", last, _swing_high(bars, p["stop_lookback"]), None, "MACD Bearish Cross",
                     f"MACD {line[-1]:.4f} crossed below its signal {sig[-1]:.4f}")
    return None


def macd_histogram_turn(bars, p) -> Optional[Setup]:
    """The histogram turning while still on its own side of zero — an earlier, noisier
    read than the signal cross, and a genuinely different trade-off."""
    _line, _sig, hist = macd(_c(bars), p["fast"], p["slow"], p["signal"])
    if len(hist) < 4:
        return None
    last = bars[-1].close
    if hist[-3] > hist[-2] < hist[-1] and hist[-1] < 0:
        return Setup("BUY", last, _swing_low(bars, p["stop_lookback"]), None, "MACD Histogram Turn",
                     f"Histogram troughed below zero ({hist[-2]:.4f} -> {hist[-1]:.4f})")
    if hist[-3] < hist[-2] > hist[-1] and hist[-1] > 0:
        return Setup("SELL", last, _swing_high(bars, p["stop_lookback"]), None, "MACD Histogram Turn",
                     f"Histogram peaked above zero ({hist[-2]:.4f} -> {hist[-1]:.4f})")
    return None


def adx_di_cross(bars, p) -> Optional[Setup]:
    """DI+/DI- crossing while ADX confirms a trend is actually present — the cross alone
    fires constantly in chop, which is why ADX gates it."""
    a, plus, minus = adx(bars, p["period"])
    if len(a) < 3 or len(plus) < 3 or len(minus) < 3:
        return None
    if a[-1] < p["adx_min"]:
        return None
    last = bars[-1].close
    if plus[-2] <= minus[-2] and plus[-1] > minus[-1]:
        return Setup("BUY", last, _swing_low(bars, p["stop_lookback"]), None, "ADX / DI Cross",
                     f"DI+ crossed above DI- with ADX {a[-1]:.1f}")
    if plus[-2] >= minus[-2] and plus[-1] < minus[-1]:
        return Setup("SELL", last, _swing_high(bars, p["stop_lookback"]), None, "ADX / DI Cross",
                     f"DI- crossed above DI+ with ADX {a[-1]:.1f}")
    return None


def _supertrend(bars, period: int, mult: float) -> list[int]:
    """+1 / -1 trend direction. Implemented here because the shared indicator library has
    no supertrend and it is one of the most widely used trend rails in Indian retail."""
    a = atr_series(bars, period)
    if not a:
        return []
    off = len(bars) - len(a)
    dirs: list[int] = []
    upper = lower = None
    direction = 1
    for i, atr_v in enumerate(a):
        b = bars[off + i]
        mid = (b.high + b.low) / 2
        up, dn = mid + mult * atr_v, mid - mult * atr_v
        if upper is None:
            upper, lower = up, dn
        else:
            upper = min(up, upper) if bars[off + i - 1].close <= upper else up
            lower = max(dn, lower) if bars[off + i - 1].close >= lower else dn
        if b.close > upper:
            direction = 1
        elif b.close < lower:
            direction = -1
        dirs.append(direction)
    return dirs


def supertrend_flip(bars, p) -> Optional[Setup]:
    d = _supertrend(bars, p["period"], p["mult"])
    if len(d) < 3:
        return None
    last = bars[-1].close
    if d[-2] == -1 and d[-1] == 1:
        return Setup("BUY", last, _swing_low(bars, p["stop_lookback"]), None, "Supertrend Flip",
                     f"Supertrend({p['period']},{p['mult']}) flipped bullish")
    if d[-2] == 1 and d[-1] == -1:
        return Setup("SELL", last, _swing_high(bars, p["stop_lookback"]), None, "Supertrend Flip",
                     f"Supertrend({p['period']},{p['mult']}) flipped bearish")
    return None


def psar_flip(bars, p) -> Optional[Setup]:
    s = psar(bars, p["step"], p["max_step"])
    if len(s) < 3:
        return None
    off = len(bars) - len(s)
    prev, cur = bars[off + len(s) - 2], bars[-1]
    if s[-2] > prev.close and s[-1] < cur.close:
        return Setup("BUY", cur.close, s[-1], None, "Parabolic SAR Flip", "PSAR flipped below price")
    if s[-2] < prev.close and s[-1] > cur.close:
        return Setup("SELL", cur.close, s[-1], None, "Parabolic SAR Flip", "PSAR flipped above price")
    return None


def stochastic_cross(bars, p) -> Optional[Setup]:
    k, d = stochastic(bars, p["k"], p["d"])
    if len(k) < 3 or len(d) < 3:
        return None
    n = min(len(k), len(d))
    k, d = k[-n:], d[-n:]
    last = bars[-1].close
    if k[-2] <= d[-2] and k[-1] > d[-1] and k[-1] < p["low"]:
        return Setup("BUY", last, _swing_low(bars, p["stop_lookback"]), None, "Stochastic Cross",
                     f"%K crossed %D at {k[-1]:.1f}, inside the oversold zone")
    if k[-2] >= d[-2] and k[-1] < d[-1] and k[-1] > p["high"]:
        return Setup("SELL", last, _swing_high(bars, p["stop_lookback"]), None, "Stochastic Cross",
                     f"%K crossed %D at {k[-1]:.1f}, inside the overbought zone")
    return None


def williams_reversal(bars, p) -> Optional[Setup]:
    w = williams_r(bars, p["period"])
    if len(w) < 3:
        return None
    last = bars[-1].close
    if w[-2] <= p["low"] and w[-1] > w[-2]:
        return Setup("BUY", last, _swing_low(bars, p["stop_lookback"]), None, "Williams %R Reversal",
                     f"Williams %R turned up from {w[-2]:.1f}")
    if w[-2] >= p["high"] and w[-1] < w[-2]:
        return Setup("SELL", last, _swing_high(bars, p["stop_lookback"]), None, "Williams %R Reversal",
                     f"Williams %R turned down from {w[-2]:.1f}")
    return None


def cci_breakout(bars, p) -> Optional[Setup]:
    c = cci(bars, p["period"])
    if len(c) < 3:
        return None
    last = bars[-1].close
    if c[-2] <= p["level"] < c[-1]:
        return Setup("BUY", last, _swing_low(bars, p["stop_lookback"]), None, "CCI Breakout",
                     f"CCI crossed above {p['level']} ({c[-1]:.0f})")
    if c[-2] >= -p["level"] > c[-1]:
        return Setup("SELL", last, _swing_high(bars, p["stop_lookback"]), None, "CCI Breakdown",
                     f"CCI crossed below {-p['level']} ({c[-1]:.0f})")
    return None


def roc_momentum(bars, p) -> Optional[Setup]:
    r = roc(_c(bars), p["period"])
    if len(r) < 3:
        return None
    last = bars[-1].close
    if r[-2] <= p["threshold"] < r[-1]:
        return Setup("BUY", last, _swing_low(bars, p["stop_lookback"]), None, "Rate of Change Thrust",
                     f"ROC({p['period']}) crossed above {p['threshold']} ({r[-1]:.2f}%)")
    if r[-2] >= -p["threshold"] > r[-1]:
        return Setup("SELL", last, _swing_high(bars, p["stop_lookback"]), None, "Rate of Change Thrust",
                     f"ROC({p['period']}) crossed below {-p['threshold']} ({r[-1]:.2f}%)")
    return None


def _obv(bars) -> list[float]:
    out = [0.0]
    for prev, cur in zip(bars, bars[1:]):
        step = cur.volume if cur.close > prev.close else (-cur.volume if cur.close < prev.close else 0)
        out.append(out[-1] + step)
    return out


def obv_breakout(bars, p) -> Optional[Setup]:
    """On-Balance Volume making a new extreme BEFORE price does — accumulation showing up
    in volume ahead of the price break."""
    if len(bars) < p["window"] + 5:
        return None
    o = _obv(bars)
    seg = o[-p["window"]:]
    last = bars[-1].close
    price_seg = [b.close for b in bars[-p["window"]:]]
    if o[-1] >= max(seg) and last < max(price_seg):
        return Setup("BUY", last, _swing_low(bars, p["stop_lookback"]), None, "OBV Leading Breakout",
                     f"OBV at a {p['window']}-bar high while price has not yet broken out")
    if o[-1] <= min(seg) and last > min(price_seg):
        return Setup("SELL", last, _swing_high(bars, p["stop_lookback"]), None, "OBV Leading Breakdown",
                     f"OBV at a {p['window']}-bar low while price has not yet broken down")
    return None


def relative_volume_thrust(bars, p) -> Optional[Setup]:
    """A directional bar on outsized relative volume — participation confirming the move
    rather than price moving on air."""
    if len(bars) < p["window"] + 2:
        return None
    avg = sum(b.volume for b in bars[-p["window"]:-1]) / max(p["window"] - 1, 1)
    b = bars[-1]
    if avg <= 0 or b.volume < avg * p["rvol"]:
        return None
    rng = b.high - b.low
    if rng <= 0 or abs(b.close - b.open) < rng * p["min_body"]:
        return None
    if b.close > b.open:
        return Setup("BUY", b.close, b.low, None, "Relative Volume Thrust",
                     f"Up bar on {b.volume/avg:.1f}x average volume")
    return Setup("SELL", b.close, b.high, None, "Relative Volume Thrust",
                 f"Down bar on {b.volume/avg:.1f}x average volume")


# --------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------

# Chart + candlestick shapes adapted from the tested commodity library.
_CP_CHART = ["head_shoulders", "double_top_bottom", "triple_top_bottom", "ascending_triangle",
             "descending_triangle", "symmetrical_triangle", "wedge", "flag", "pennant",
             "cup_handle", "rounding", "diamond", "broadening"]
_CP_CANDLE = ["engulfing", "hammer_star", "doji_reversal", "marubozu", "inside_bar",
              "outside_bar", "soldiers_crows", "star", "pin_bar", "heikin_flip"]
_CP_STRUCT = ["donchian_fast", "donchian_slow", "keltner_break", "bollinger_pctb",
              "prior_session_break", "round_number_break", "bollinger_squeeze",
              "ttm_squeeze", "ema_ribbon", "atr_thrust", "hh_hl_shift", "opening_range",
              "ema_pullback", "gap_fade"]

DETECTORS: dict[str, Callable] = {}
for _t in _CP_CHART + _CP_CANDLE + _CP_STRUCT:
    DETECTORS[_t] = _from_commodity(_t)

DETECTORS.update({
    "inverted_hammer": inverted_hammer,
    "hanging_man": hanging_man,
    "multi_inside": multi_inside_compression,
    "break_of_structure": break_of_structure,
    "change_of_character": change_of_character,
    "sr_flip": support_resistance_flip,
    "prev_period_break": prev_period_break,
    "vwap_reclaim": vwap_reclaim,
    "gap_continuation": gap_continuation,
    "pivot_level_break": pivot_level_break,
    "fib_retracement": fib_retracement,
    "rectangle_break": range_rectangle_break,
    "channel_break": channel_break,
    "ema_cross": ema_cross,
    "rsi_regime": rsi_regime,
    "rsi_extreme": rsi_extreme_reversal,
    "rsi_divergence": rsi_divergence,
    "macd_cross": macd_signal_cross,
    "macd_histogram": macd_histogram_turn,
    "adx_di_cross": adx_di_cross,
    "supertrend_flip": supertrend_flip,
    "psar_flip": psar_flip,
    "stochastic_cross": stochastic_cross,
    "williams_reversal": williams_reversal,
    "cci_breakout": cci_breakout,
    "roc_momentum": roc_momentum,
    "obv_breakout": obv_breakout,
    "rvol_thrust": relative_volume_thrust,
})


def detect(name: str, bars, params: dict) -> Optional[Setup]:
    fn = DETECTORS.get(name)
    if fn is None:
        return None
    try:
        return fn(bars, params)
    except (IndexError, ValueError, ZeroDivisionError, TypeError, KeyError):
        # One malformed series costs one signal, never the whole scan.
        return None


__all__ = ["Setup", "DETECTORS", "detect"]
