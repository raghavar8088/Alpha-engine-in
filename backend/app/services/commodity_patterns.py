"""Commodity Trading — the pattern library.

39 templates in three families, each instantiated on 8 timeframes (1m, 5m, 15m, 30m,
45m, 1h, 4h, 1d) to give 312 strategies:

  chart       13  Head & Shoulders, Double/Triple Top & Bottom, Ascending/Descending/
                  Symmetrical Triangle, Wedge, Flag, Pennant, Cup & Handle, Rounding,
                  Diamond, Broadening
  candlestick 10  Engulfing, Hammer/Shooting Star, Doji Reversal, Marubozu, Inside Bar,
                  Outside Bar, Three Soldiers/Crows, Morning/Evening Star, Pin Bar,
                  Heikin Ashi Flip
  structure   16  Donchian (fast+slow), Keltner, Bollinger %B, Prior-session break,
                  Round-number break, Bollinger squeeze, TTM squeeze, EMA ribbon
                  compression, ATR expansion, HH/HL shift, Opening Range Breakout,
                  Pivot R1/S1, Fib 61.8% bounce, EMA pullback, Gap fade

LONG **AND** SHORT
------------------
Unlike the equity desks in this app, these are FUTURES: a short is a normal position, not
a borrow. Every template that has a bearish mirror emits it (a head-and-shoulders sells,
its inverse buys), so the library covers both directions rather than testing only half of
each pattern.

WHAT THESE IMPLEMENTATIONS ARE
------------------------------
The classical chart patterns are drawn by eye on a chart; here they are geometry over
detected swing pivots — a head-and-shoulders is "three consecutive swing highs where the
middle is the highest and the shoulders sit within `shoulder_tol` of each other, with a
neckline through the two intervening lows". That is a faithful, testable reading of the
pattern, not the same thing as a human's judgement of one, and the rationale string on
every signal says exactly which measurements fired so a trade can be argued with.

Every template returns None rather than guessing when it lacks the bars it needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from strategy_service.indicators import atr as atr_series
from strategy_service.indicators import donchian, ema, keltner, sma, stdev

# --------------------------------------------------------------------------------
# Contracts
# --------------------------------------------------------------------------------


@dataclass
class PatternSignal:
    side: str            # BUY or SELL — futures, both directions are real positions
    entry: float
    target: float
    stoploss: float
    confidence: float
    rationale: str
    pattern: str


@dataclass
class PatternSpec:
    strategy_id: str
    name: str
    family: str          # chart | candlestick | structure
    template: str
    timeframe: str
    rationale: str
    params: dict = field(default_factory=dict)
    min_bars: int = 60


FAMILY_LABELS = {"chart": "Chart Pattern", "candlestick": "Candlestick", "structure": "Price Structure"}


# --------------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------------


def _c(bars) -> list[float]:
    return [b.close for b in bars]


def _atr(bars, n: int = 14) -> float:
    s = atr_series(bars, n)
    return s[-1] if s else 0.0


def pivots(bars, left: int = 3, right: int = 3) -> tuple[list[int], list[int]]:
    """Indices of swing highs and swing lows.

    A swing high is a bar whose high is >= every high within `left` bars before and
    `right` bars after it. The `right` lookahead means the most recent `right` bars can
    never be pivots — which is correct: a swing is only confirmed once price has turned
    away from it, and treating an unconfirmed extreme as a pivot is how backtests
    accidentally see the future."""
    highs, lows = [], []
    n = len(bars)
    for i in range(left, n - right):
        h, l = bars[i].high, bars[i].low
        if all(bars[j].high <= h for j in range(i - left, i)) and \
           all(bars[j].high <= h for j in range(i + 1, i + right + 1)):
            highs.append(i)
        if all(bars[j].low >= l for j in range(i - left, i)) and \
           all(bars[j].low >= l for j in range(i + 1, i + right + 1)):
            lows.append(i)
    return highs, lows


def _slope(values: list[float]) -> float:
    """Least-squares slope per bar, normalised by the mean level so it is comparable
    across instruments priced in the hundreds (ZINC) and the hundred-thousands (SILVER)."""
    n = len(values)
    if n < 2:
        return 0.0
    xm = (n - 1) / 2
    ym = sum(values) / n
    denom = sum((i - xm) ** 2 for i in range(n))
    if denom == 0:
        return 0.0
    slope = sum((i - xm) * (values[i] - ym) for i in range(n)) / denom
    return slope / ym if ym else 0.0


def _near(a: float, b: float, tol: float) -> bool:
    """Within `tol` (fraction) of each other, measured against their average."""
    m = (abs(a) + abs(b)) / 2
    return m > 0 and abs(a - b) / m <= tol


def _bollinger(bars, period: int, mult: float) -> tuple[list[float], list[float], list[float]]:
    closes = _c(bars)
    mid = sma(closes, period)
    sd = stdev(closes, period)
    if not mid or not sd:
        return [], [], []
    n = min(len(mid), len(sd))
    mid, sd = mid[-n:], sd[-n:]
    return ([m + mult * s for m, s in zip(mid, sd)], mid,
            [m - mult * s for m, s in zip(mid, sd)])


def _heikin(bars) -> list[tuple[float, float]]:
    """(ha_open, ha_close) per bar."""
    out: list[tuple[float, float]] = []
    for i, b in enumerate(bars):
        ha_c = (b.open + b.high + b.low + b.close) / 4
        ha_o = (b.open + b.close) / 2 if i == 0 else (out[-1][0] + out[-1][1]) / 2
        out.append((ha_o, ha_c))
    return out


def _mk(side: str, entry: float, atr: float, target_atr: float, stop_atr: float,
        pattern: str, rationale: str, confidence: float = 0.6) -> Optional[PatternSignal]:
    """Build a signal with ATR-scaled target/stop in the given direction, rejecting
    anything degenerate (non-positive prices, inverted levels)."""
    if entry <= 0 or atr <= 0:
        return None
    if side == "BUY":
        target, stop = entry + target_atr * atr, entry - stop_atr * atr
        if not (stop < entry < target):
            return None
    else:
        target, stop = entry - target_atr * atr, entry + stop_atr * atr
        if not (target < entry < stop):
            return None
    if stop <= 0 or target <= 0:
        return None
    return PatternSignal(side=side, entry=entry, target=target, stoploss=stop,
                         confidence=min(0.95, max(0.1, confidence)),
                         rationale=rationale, pattern=pattern)


# --------------------------------------------------------------------------------
# Family 1 — chart patterns (13)
# --------------------------------------------------------------------------------


def head_shoulders(spec, bars) -> Optional[PatternSignal]:
    """Three swing extremes, the middle one dominant, shoulders roughly level. Fires on
    the close through the neckline drawn between the two intervening opposite pivots."""
    p = spec.params
    hi, lo = pivots(bars, p["pivot"], p["pivot"])
    atr, last = _atr(bars), bars[-1].close
    for idxs, bearish in ((hi, True), (lo, False)):
        if len(idxs) < 3:
            continue
        a, b, c = idxs[-3], idxs[-2], idxs[-1]
        va = bars[a].high if bearish else bars[a].low
        vb = bars[b].high if bearish else bars[b].low
        vc = bars[c].high if bearish else bars[c].low
        head_ok = (vb > va and vb > vc) if bearish else (vb < va and vb < vc)
        if not head_ok or not _near(va, vc, p["shoulder_tol"]):
            continue
        inner = [bars[i].low for i in range(a, c + 1)] if bearish else [bars[i].high for i in range(a, c + 1)]
        neckline = min(inner) if bearish else max(inner)
        broken = last < neckline if bearish else last > neckline
        if not broken:
            continue
        kind = "Head & Shoulders" if bearish else "Inverse Head & Shoulders"
        return _mk("SELL" if bearish else "BUY", last, atr, p["target_atr"], p["stop_atr"],
                   kind, f"{kind}: head {vb:.2f} vs shoulders {va:.2f}/{vc:.2f}, "
                         f"neckline {neckline:.2f} broken at {last:.2f}", 0.65)
    return None


def double_top_bottom(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    hi, lo = pivots(bars, p["pivot"], p["pivot"])
    atr, last = _atr(bars), bars[-1].close
    for idxs, bearish in ((hi, True), (lo, False)):
        if len(idxs) < 2:
            continue
        a, b = idxs[-2], idxs[-1]
        if b - a < p["min_sep"]:
            continue
        va = bars[a].high if bearish else bars[a].low
        vb = bars[b].high if bearish else bars[b].low
        if not _near(va, vb, p["level_tol"]):
            continue
        mid = [bars[i].low for i in range(a, b + 1)] if bearish else [bars[i].high for i in range(a, b + 1)]
        neckline = min(mid) if bearish else max(mid)
        if (last < neckline) if bearish else (last > neckline):
            kind = "Double Top" if bearish else "Double Bottom"
            return _mk("SELL" if bearish else "BUY", last, atr, p["target_atr"], p["stop_atr"],
                       kind, f"{kind}: two turns at {va:.2f}/{vb:.2f} {b-a} bars apart, "
                             f"neckline {neckline:.2f} given way at {last:.2f}", 0.62)
    return None


def triple_top_bottom(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    hi, lo = pivots(bars, p["pivot"], p["pivot"])
    atr, last = _atr(bars), bars[-1].close
    for idxs, bearish in ((hi, True), (lo, False)):
        if len(idxs) < 3:
            continue
        a, b, c = idxs[-3], idxs[-2], idxs[-1]
        vals = [bars[i].high if bearish else bars[i].low for i in (a, b, c)]
        if not (_near(vals[0], vals[1], p["level_tol"]) and _near(vals[1], vals[2], p["level_tol"])):
            continue
        mid = [bars[i].low for i in range(a, c + 1)] if bearish else [bars[i].high for i in range(a, c + 1)]
        neckline = min(mid) if bearish else max(mid)
        if (last < neckline) if bearish else (last > neckline):
            kind = "Triple Top" if bearish else "Triple Bottom"
            return _mk("SELL" if bearish else "BUY", last, atr, p["target_atr"], p["stop_atr"],
                       kind, f"{kind}: three rejections at ~{sum(vals)/3:.2f}, "
                             f"neckline {neckline:.2f} broken at {last:.2f}", 0.66)
    return None


def _triangle(spec, bars, mode: str) -> Optional[PatternSignal]:
    """Shared engine for the three triangles. `mode` selects which boundary must be flat
    and which must slope."""
    p = spec.params
    hi, lo = pivots(bars, p["pivot"], p["pivot"])
    if len(hi) < 2 or len(lo) < 2:
        return None
    hs = [bars[i].high for i in hi[-3:]]
    ls = [bars[i].low for i in lo[-3:]]
    if len(hs) < 2 or len(ls) < 2:
        return None
    sh, sl = _slope(hs), _slope(ls)
    flat, rise = p["flat_tol"], p["slope_min"]
    atr, last = _atr(bars), bars[-1].close
    resistance, support = max(hs), min(ls)

    if mode == "ascending" and abs(sh) <= flat and sl >= rise:
        if last > resistance:
            return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Ascending Triangle",
                       f"Ascending triangle: flat resistance ~{resistance:.2f} with rising lows "
                       f"(slope {sl*100:.2f}%/bar), broken at {last:.2f}", 0.64)
    if mode == "descending" and abs(sl) <= flat and sh <= -rise:
        if last < support:
            return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Descending Triangle",
                       f"Descending triangle: flat support ~{support:.2f} with falling highs "
                       f"(slope {sh*100:.2f}%/bar), broken at {last:.2f}", 0.64)
    if mode == "symmetrical" and sh <= -rise and sl >= rise:
        if last > resistance:
            return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Symmetrical Triangle",
                       f"Symmetrical triangle converging (highs {sh*100:.2f}%/bar, lows "
                       f"{sl*100:.2f}%/bar), upside break at {last:.2f}", 0.6)
        if last < support:
            return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Symmetrical Triangle",
                       f"Symmetrical triangle converging (highs {sh*100:.2f}%/bar, lows "
                       f"{sl*100:.2f}%/bar), downside break at {last:.2f}", 0.6)
    return None


def ascending_triangle(spec, bars):
    return _triangle(spec, bars, "ascending")


def descending_triangle(spec, bars):
    return _triangle(spec, bars, "descending")


def symmetrical_triangle(spec, bars):
    return _triangle(spec, bars, "symmetrical")


def wedge(spec, bars) -> Optional[PatternSignal]:
    """Both boundaries sloping the SAME way while converging. A rising wedge resolves
    down, a falling wedge up — the direction is the opposite of the wedge's own slope,
    which is what separates a wedge from a channel."""
    p = spec.params
    hi, lo = pivots(bars, p["pivot"], p["pivot"])
    if len(hi) < 2 or len(lo) < 2:
        return None
    hs = [bars[i].high for i in hi[-3:]]
    ls = [bars[i].low for i in lo[-3:]]
    sh, sl = _slope(hs), _slope(ls)
    m = p["slope_min"]
    atr, last = _atr(bars), bars[-1].close
    if sh >= m and sl >= m and sl > sh and last < min(ls):
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Rising Wedge",
                   f"Rising wedge (highs {sh*100:.2f}%/bar, lows {sl*100:.2f}%/bar converging), "
                   f"support {min(ls):.2f} lost at {last:.2f}", 0.62)
    if sh <= -m and sl <= -m and sh > sl and last > max(hs):
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Falling Wedge",
                   f"Falling wedge (highs {sh*100:.2f}%/bar, lows {sl*100:.2f}%/bar converging), "
                   f"resistance {max(hs):.2f} cleared at {last:.2f}", 0.62)
    return None


def flag(spec, bars) -> Optional[PatternSignal]:
    """A sharp impulse, then a shallow counter-sloping consolidation, then continuation."""
    p = spec.params
    imp, cons = p["impulse"], p["consol"]
    if len(bars) < imp + cons + 2:
        return None
    closes = _c(bars)
    pole_start, pole_end = closes[-(imp + cons)], closes[-cons]
    if pole_start <= 0:
        return None
    pole = (pole_end - pole_start) / pole_start
    # The consolidation is measured WITHOUT the breakout bar. Including it drags the
    # flag's own slope in the direction of the break, so a textbook flag that resolves
    # cleanly fails its own slope test — the pattern would only ever fire on weak breaks.
    flag_bars = bars[-cons:-1]
    if len(flag_bars) < 3:
        return None
    fs = _slope([b.close for b in flag_bars])
    rng = max(b.high for b in flag_bars) - min(b.low for b in flag_bars)
    atr, last = _atr(bars), bars[-1].close
    if atr <= 0 or rng > atr * p["max_flag_atr"]:
        return None
    if pole >= p["min_pole"] and fs <= 0 and last > max(b.high for b in flag_bars):
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Bull Flag",
                   f"Bull flag: {pole*100:+.1f}% pole then a {cons}-bar drift "
                   f"({fs*100:+.2f}%/bar), broken up at {last:.2f}", 0.63)
    if pole <= -p["min_pole"] and fs >= 0 and last < min(b.low for b in flag_bars):
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Bear Flag",
                   f"Bear flag: {pole*100:+.1f}% pole then a {cons}-bar drift "
                   f"({fs*100:+.2f}%/bar), broken down at {last:.2f}", 0.63)
    return None


def pennant(spec, bars) -> Optional[PatternSignal]:
    """Like a flag, but the consolidation CONVERGES (a small symmetrical triangle)."""
    p = spec.params
    imp, cons = p["impulse"], p["consol"]
    if len(bars) < imp + cons + 2:
        return None
    closes = _c(bars)
    pole_start, pole_end = closes[-(imp + cons)], closes[-cons]
    if pole_start <= 0:
        return None
    pole = (pole_end - pole_start) / pole_start
    seg = bars[-cons:-1]          # consolidation only; the breakout bar is the trigger
    if len(seg) < 4:
        return None
    half = max(2, len(seg) // 2)
    r1 = max(b.high for b in seg[:half]) - min(b.low for b in seg[:half])
    r2 = max(b.high for b in seg[half:]) - min(b.low for b in seg[half:])
    if r1 <= 0 or r2 >= r1 * p["converge"]:
        return None
    atr, last = _atr(bars), bars[-1].close
    if pole >= p["min_pole"] and last > max(b.high for b in seg):
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Bull Pennant",
                   f"Bull pennant: {pole*100:+.1f}% pole, range contracted {r1:.2f}->{r2:.2f}, "
                   f"broken up at {last:.2f}", 0.63)
    if pole <= -p["min_pole"] and last < min(b.low for b in seg):
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Bear Pennant",
                   f"Bear pennant: {pole*100:+.1f}% pole, range contracted {r1:.2f}->{r2:.2f}, "
                   f"broken down at {last:.2f}", 0.63)
    return None


def cup_handle(spec, bars) -> Optional[PatternSignal]:
    """Rounded base (rim-dip-rim, dip near the middle) then a shallow handle, then a
    break of the rim. The inverted form is the same shape reflected."""
    p = spec.params
    cup, handle = p["cup"], p["handle"]
    if len(bars) < cup + handle + 2:
        return None
    seg = bars[-(cup + handle):-handle] if handle else bars[-cup:]
    hs = [b.high for b in seg]
    ls = [b.low for b in seg]
    n = len(seg)
    mid_lo = min(range(n), key=lambda i: seg[i].low)
    mid_hi = max(range(n), key=lambda i: seg[i].high)
    # The handle excludes the breakout bar, for the same reason the flag's consolidation
    # does: the bar that clears the rim would otherwise fail the "handle stays under the
    # rim" test it is supposed to trigger.
    hseg = bars[-handle:-1] if handle else []
    atr, last = _atr(bars), bars[-1].close
    centred = lambda i: abs(i - (n - 1) / 2) <= n * p["centre_tol"]

    rim = max(hs[0], hs[-1])
    if centred(mid_lo) and _near(hs[0], hs[-1], p["rim_tol"]) and \
            (not hseg or max(b.high for b in hseg) <= rim):
        if last > rim:
            return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Cup & Handle",
                       f"Cup & handle: rims {hs[0]:.2f}/{hs[-1]:.2f} with the base at "
                       f"{seg[mid_lo].low:.2f}, rim broken at {last:.2f}", 0.64)
    base = min(ls[0], ls[-1])
    if centred(mid_hi) and _near(ls[0], ls[-1], p["rim_tol"]) and \
            (not hseg or min(b.low for b in hseg) >= base):
        if last < base:
            return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Inverted Cup & Handle",
                       f"Inverted cup & handle: rims {ls[0]:.2f}/{ls[-1]:.2f} with the dome at "
                       f"{seg[mid_hi].high:.2f}, rim broken at {last:.2f}", 0.64)
    return None


def rounding(spec, bars) -> Optional[PatternSignal]:
    """A saucer: the slope rotates smoothly from one sign to the other across the window,
    without the sharp V that would make it a spike instead."""
    p = spec.params
    w = p["window"]
    if len(bars) < w + 2:
        return None
    seg = bars[-w:]
    closes = [b.close for b in seg]
    third = max(3, w // 3)
    s1, s3 = _slope(closes[:third]), _slope(closes[-third:])
    m = p["slope_min"]
    atr, last = _atr(bars), bars[-1].close
    lo_i = min(range(w), key=lambda i: seg[i].low)
    hi_i = max(range(w), key=lambda i: seg[i].high)
    centred = lambda i: abs(i - (w - 1) / 2) <= w * p["centre_tol"]

    confirm = seg[-third:-1] or seg[-2:-1]
    if s1 <= -m and s3 >= m and centred(lo_i) and last > max(b.high for b in confirm):
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Rounding Bottom",
                   f"Rounding bottom: slope rotated {s1*100:+.2f}% -> {s3*100:+.2f}%/bar "
                   f"around a base at {seg[lo_i].low:.2f}", 0.6)
    if s1 >= m and s3 <= -m and centred(hi_i) and last < min(b.low for b in confirm):
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Rounding Top",
                   f"Rounding top: slope rotated {s1*100:+.2f}% -> {s3*100:+.2f}%/bar "
                   f"around a dome at {seg[hi_i].high:.2f}", 0.6)
    return None


def broadening(spec, bars) -> Optional[PatternSignal]:
    """Megaphone: highs rising while lows fall. Traded as a fade of the extreme, since a
    broadening formation has no clean breakout level to chase."""
    p = spec.params
    hi, lo = pivots(bars, p["pivot"], p["pivot"])
    if len(hi) < 2 or len(lo) < 2:
        return None
    hs = [bars[i].high for i in hi[-3:]]
    ls = [bars[i].low for i in lo[-3:]]
    sh, sl = _slope(hs), _slope(ls)
    m = p["slope_min"]
    if not (sh >= m and sl <= -m):
        return None
    atr, last = _atr(bars), bars[-1].close
    if last >= max(hs):
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Broadening Formation",
                   f"Broadening formation (highs {sh*100:+.2f}%, lows {sl*100:+.2f}%/bar): "
                   f"fading the upper rail at {last:.2f}", 0.55)
    if last <= min(ls):
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Broadening Formation",
                   f"Broadening formation (highs {sh*100:+.2f}%, lows {sl*100:+.2f}%/bar): "
                   f"fading the lower rail at {last:.2f}", 0.55)
    return None


def diamond(spec, bars) -> Optional[PatternSignal]:
    """Broadening then narrowing — range expands over the first half and contracts over
    the second. Traded on the break of the contracted half."""
    p = spec.params
    w = p["window"]
    if len(bars) < w + 2:
        return None
    seg = bars[-w:]
    q = max(3, w // 4)
    r1 = max(b.high for b in seg[:q]) - min(b.low for b in seg[:q])
    r2 = max(b.high for b in seg[q:2 * q]) - min(b.low for b in seg[q:2 * q])
    r4 = max(b.high for b in seg[-q:]) - min(b.low for b in seg[-q:])
    if not (r2 > r1 * p["expand"] and r4 < r2 * p["contract"]):
        return None
    atr, last = _atr(bars), bars[-1].close
    hi4 = max(b.high for b in seg[-q:-1])
    lo4 = min(b.low for b in seg[-q:-1])
    if last > hi4:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Diamond",
                   f"Diamond: range {r1:.2f}->{r2:.2f}->{r4:.2f}, upside break at {last:.2f}", 0.58)
    if last < lo4:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Diamond",
                   f"Diamond: range {r1:.2f}->{r2:.2f}->{r4:.2f}, downside break at {last:.2f}", 0.58)
    return None


# --------------------------------------------------------------------------------
# Family 2 — candlestick patterns (10)
# --------------------------------------------------------------------------------


def _body(b) -> float:
    return abs(b.close - b.open)


def _range(b) -> float:
    return b.high - b.low


def engulfing(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    if len(bars) < 3:
        return None
    prev, cur = bars[-2], bars[-1]
    if _body(prev) <= 0 or _body(cur) < _body(prev) * p["min_ratio"]:
        return None
    atr = _atr(bars)
    up = cur.close > cur.open and prev.close < prev.open
    dn = cur.close < cur.open and prev.close > prev.open
    if up and cur.close >= prev.open and cur.open <= prev.close:
        return _mk("BUY", cur.close, atr, p["target_atr"], p["stop_atr"], "Bullish Engulfing",
                   f"Bullish engulfing: body {_body(cur):.2f} swallows the prior "
                   f"{_body(prev):.2f} ({_body(cur)/_body(prev):.1f}x)", 0.58)
    if dn and cur.close <= prev.open and cur.open >= prev.close:
        return _mk("SELL", cur.close, atr, p["target_atr"], p["stop_atr"], "Bearish Engulfing",
                   f"Bearish engulfing: body {_body(cur):.2f} swallows the prior "
                   f"{_body(prev):.2f} ({_body(cur)/_body(prev):.1f}x)", 0.58)
    return None


def hammer_star(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    if len(bars) < 2:
        return None
    b = bars[-1]
    body, rng = _body(b), _range(b)
    if body <= 0 or rng <= 0:
        return None
    upper = b.high - max(b.open, b.close)
    lower = min(b.open, b.close) - b.low
    atr = _atr(bars)
    k = p["wick_mult"]
    if lower >= body * k and lower >= upper * k:
        return _mk("BUY", b.close, atr, p["target_atr"], p["stop_atr"], "Hammer",
                   f"Hammer: lower wick {lower:.2f} vs body {body:.2f} and upper wick {upper:.2f}", 0.56)
    if upper >= body * k and upper >= lower * k:
        return _mk("SELL", b.close, atr, p["target_atr"], p["stop_atr"], "Shooting Star",
                   f"Shooting star: upper wick {upper:.2f} vs body {body:.2f} and lower wick {lower:.2f}", 0.56)
    return None


def doji_reversal(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    w = p["extreme_window"]
    if len(bars) < w + 2:
        return None
    b = bars[-1]
    rng = _range(b)
    if rng <= 0 or _body(b) > rng * p["max_body"]:
        return None
    seg = bars[-w:]
    atr = _atr(bars)
    if b.low <= min(x.low for x in seg):
        return _mk("BUY", b.close, atr, p["target_atr"], p["stop_atr"], "Doji at Low",
                   f"Doji (body {_body(b)/rng*100:.0f}% of range) at a {w}-bar low", 0.55)
    if b.high >= max(x.high for x in seg):
        return _mk("SELL", b.close, atr, p["target_atr"], p["stop_atr"], "Doji at High",
                   f"Doji (body {_body(b)/rng*100:.0f}% of range) at a {w}-bar high", 0.55)
    return None


def marubozu(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    if len(bars) < 2:
        return None
    b = bars[-1]
    rng = _range(b)
    if rng <= 0 or _body(b) < rng * p["min_body"]:
        return None
    atr = _atr(bars)
    side = "BUY" if b.close > b.open else "SELL"
    return _mk(side, b.close, atr, p["target_atr"], p["stop_atr"], "Marubozu",
               f"Marubozu: body is {_body(b)/rng*100:.0f}% of range — no rejection at either end", 0.57)


def inside_bar(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    if len(bars) < 3:
        return None
    mother, inside, cur = bars[-3], bars[-2], bars[-1]
    if not (inside.high <= mother.high and inside.low >= mother.low):
        return None
    if _range(mother) <= 0 or _range(inside) > _range(mother) * p["max_inside"]:
        return None
    atr = _atr(bars)
    if cur.close > mother.high:
        return _mk("BUY", cur.close, atr, p["target_atr"], p["stop_atr"], "Inside Bar Breakout",
                   f"Inside bar ({_range(inside)/_range(mother)*100:.0f}% of its mother) "
                   f"broken up through {mother.high:.2f}", 0.6)
    if cur.close < mother.low:
        return _mk("SELL", cur.close, atr, p["target_atr"], p["stop_atr"], "Inside Bar Breakout",
                   f"Inside bar ({_range(inside)/_range(mother)*100:.0f}% of its mother) "
                   f"broken down through {mother.low:.2f}", 0.6)
    return None


def outside_bar(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    if len(bars) < 3:
        return None
    prev, cur = bars[-2], bars[-1]
    if not (cur.high > prev.high and cur.low < prev.low):
        return None
    if _range(prev) <= 0 or _range(cur) < _range(prev) * p["min_ratio"]:
        return None
    atr = _atr(bars)
    side = "BUY" if cur.close > cur.open else "SELL"
    return _mk(side, cur.close, atr, p["target_atr"], p["stop_atr"], "Outside Bar Reversal",
               f"Outside bar: took both sides of the prior bar and closed "
               f"{'up' if side == 'BUY' else 'down'} ({_range(cur)/_range(prev):.1f}x its range)", 0.58)


def soldiers_crows(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    n = p["count"]
    if len(bars) < n + 2:
        return None
    seg = bars[-n:]
    atr = _atr(bars)
    ups = all(b.close > b.open for b in seg) and all(
        seg[i].close > seg[i - 1].close for i in range(1, n))
    dns = all(b.close < b.open for b in seg) and all(
        seg[i].close < seg[i - 1].close for i in range(1, n))
    if ups:
        return _mk("BUY", seg[-1].close, atr, p["target_atr"], p["stop_atr"], "Three White Soldiers",
                   f"{n} consecutive higher closes, each candle up", 0.6)
    if dns:
        return _mk("SELL", seg[-1].close, atr, p["target_atr"], p["stop_atr"], "Three Black Crows",
                   f"{n} consecutive lower closes, each candle down", 0.6)
    return None


def star(spec, bars) -> Optional[PatternSignal]:
    """Morning/Evening star: a big bar, a small-bodied pause, then a bar closing back
    past the midpoint of the first."""
    p = spec.params
    if len(bars) < 4:
        return None
    a, b, c = bars[-3], bars[-2], bars[-1]
    if _range(a) <= 0 or _body(b) > _range(a) * p["star_body"]:
        return None
    mid = (a.open + a.close) / 2
    atr = _atr(bars)
    if a.close < a.open and c.close > c.open and c.close > mid:
        return _mk("BUY", c.close, atr, p["target_atr"], p["stop_atr"], "Morning Star",
                   f"Morning star: down bar, small pause ({_body(b):.2f}), then a close "
                   f"{c.close:.2f} back above the midpoint {mid:.2f}", 0.63)
    if a.close > a.open and c.close < c.open and c.close < mid:
        return _mk("SELL", c.close, atr, p["target_atr"], p["stop_atr"], "Evening Star",
                   f"Evening star: up bar, small pause ({_body(b):.2f}), then a close "
                   f"{c.close:.2f} back below the midpoint {mid:.2f}", 0.63)
    return None


def pin_bar(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    w = p["extreme_window"]
    if len(bars) < w + 2:
        return None
    b = bars[-1]
    rng = _range(b)
    if rng <= 0:
        return None
    upper = b.high - max(b.open, b.close)
    lower = min(b.open, b.close) - b.low
    seg = bars[-w:]
    atr = _atr(bars)
    frac = p["wick_frac"]
    if lower / rng >= frac and b.low <= min(x.low for x in seg):
        return _mk("BUY", b.close, atr, p["target_atr"], p["stop_atr"], "Pin Bar at Low",
                   f"Pin bar: {lower/rng*100:.0f}% lower-wick rejection at a {w}-bar low", 0.6)
    if upper / rng >= frac and b.high >= max(x.high for x in seg):
        return _mk("SELL", b.close, atr, p["target_atr"], p["stop_atr"], "Pin Bar at High",
                   f"Pin bar: {upper/rng*100:.0f}% upper-wick rejection at a {w}-bar high", 0.6)
    return None


def heikin_flip(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    n = p["confirm"]
    if len(bars) < n + 4:
        return None
    ha = _heikin(bars)
    colours = [1 if c > o else -1 for o, c in ha[-(n + 1):]]
    atr = _atr(bars)
    if colours[0] == -1 and all(x == 1 for x in colours[1:]):
        return _mk("BUY", bars[-1].close, atr, p["target_atr"], p["stop_atr"], "Heikin Ashi Flip",
                   f"Heikin-Ashi turned green and held {n} bar(s)", 0.58)
    if colours[0] == 1 and all(x == -1 for x in colours[1:]):
        return _mk("SELL", bars[-1].close, atr, p["target_atr"], p["stop_atr"], "Heikin Ashi Flip",
                   f"Heikin-Ashi turned red and held {n} bar(s)", 0.58)
    return None


# --------------------------------------------------------------------------------
# Family 3 — price structure (16)
# --------------------------------------------------------------------------------


def donchian_break(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    n = p["period"]
    if len(bars) < n + 3:
        return None
    up, dn = donchian(bars[:-1], n)
    if not up or not dn:
        return None
    atr, last = _atr(bars), bars[-1].close
    if last > up[-1]:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Donchian Breakout",
                   f"Cleared the {n}-bar high {up[-1]:.2f} at {last:.2f}", 0.6)
    if last < dn[-1]:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Donchian Breakdown",
                   f"Lost the {n}-bar low {dn[-1]:.2f} at {last:.2f}", 0.6)
    return None


def keltner_break(spec, bars) -> Optional[PatternSignal]:
    p = spec.params
    up, mid, lo = keltner(bars, p["period"], p["mult"])
    if not up or not lo:
        return None
    atr, last = _atr(bars), bars[-1].close
    if last > up[-1]:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Keltner Breakout",
                   f"Closed {last:.2f} above the upper Keltner band {up[-1]:.2f}", 0.58)
    if last < lo[-1]:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Keltner Breakdown",
                   f"Closed {last:.2f} below the lower Keltner band {lo[-1]:.2f}", 0.58)
    return None


def bollinger_pctb(spec, bars) -> Optional[PatternSignal]:
    """%B extreme — a mean-reversion fade of a close outside the band."""
    p = spec.params
    up, mid, lo = _bollinger(bars, p["period"], p["mult"])
    if not up:
        return None
    last = bars[-1].close
    width = up[-1] - lo[-1]
    if width <= 0:
        return None
    pctb = (last - lo[-1]) / width
    atr = _atr(bars)
    if pctb <= p["low"]:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Bollinger %B Low",
                   f"%B {pctb:.2f} — stretched below the band, fading back toward {mid[-1]:.2f}", 0.55)
    if pctb >= p["high"]:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Bollinger %B High",
                   f"%B {pctb:.2f} — stretched above the band, fading back toward {mid[-1]:.2f}", 0.55)
    return None


def prior_session_break(spec, bars) -> Optional[PatternSignal]:
    """Break of the previous trading day's high/low."""
    p = spec.params
    days = sorted({b.ts.date() for b in bars})
    if len(days) < 2:
        return None
    prev_day = days[-2]
    prev = [b for b in bars if b.ts.date() == prev_day]
    if not prev:
        return None
    ph, pl = max(b.high for b in prev), min(b.low for b in prev)
    atr, last = _atr(bars), bars[-1].close
    if last > ph:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Prior Session High Break",
                   f"Above the previous session high {ph:.2f} at {last:.2f}", 0.6)
    if last < pl:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Prior Session Low Break",
                   f"Below the previous session low {pl:.2f} at {last:.2f}", 0.6)
    return None


def round_number_break(spec, bars) -> Optional[PatternSignal]:
    """Break of a psychological round level, sized to the instrument's own price scale."""
    p = spec.params
    if len(bars) < 3:
        return None
    last, prev = bars[-1].close, bars[-2].close
    if last <= 0:
        return None
    step = 10 ** (math.floor(math.log10(last)) - p["digits"])
    if step <= 0:
        return None
    level = round(last / step) * step
    if abs(last - level) > step * p["tol"]:
        return None
    atr = _atr(bars)
    if prev < level <= last:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Round Number Break",
                   f"Crossed the round level {level:g} from below", 0.55)
    if prev > level >= last:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Round Number Break",
                   f"Crossed the round level {level:g} from above", 0.55)
    return None


def bollinger_squeeze(spec, bars) -> Optional[PatternSignal]:
    """Band width at a multi-bar minimum, then price leaves the band — the classic
    volatility-contraction-then-expansion trade."""
    p = spec.params
    up, mid, lo = _bollinger(bars, p["period"], p["mult"])
    if len(up) < p["lookback"] + 2:
        return None
    widths = [(u - l) / m if m else 0 for u, m, l in zip(up, mid, lo)]
    recent = widths[-p["lookback"]:]
    prev_w = widths[-2]
    if prev_w > min(recent[:-1]) * p["squeeze_tol"]:
        return None
    atr, last = _atr(bars), bars[-1].close
    if last > up[-1]:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Bollinger Squeeze Release",
                   f"Band width was at a {p['lookback']}-bar low, released upward at {last:.2f}", 0.62)
    if last < lo[-1]:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Bollinger Squeeze Release",
                   f"Band width was at a {p['lookback']}-bar low, released downward at {last:.2f}", 0.62)
    return None


def ttm_squeeze(spec, bars) -> Optional[PatternSignal]:
    """Bollinger bands inside the Keltner channel = squeeze on; the trade is the bar the
    squeeze releases, in the direction of the momentum at release."""
    p = spec.params
    up, mid, lo = _bollinger(bars, p["period"], p["bb_mult"])
    ku, km, kl = keltner(bars, p["period"], p["kc_mult"])
    if len(up) < 3 or len(ku) < 3:
        return None
    # Both band sets are aligned to the END of the series, so compare tail-relative.
    # Mixing `ku[n-2]` (head-relative) with `up[-2]` (tail-relative) silently compared
    # bands from two different points in time whenever the two series had different
    # warm-up lengths, which they do.
    inside_prev = up[-2] < ku[-2] and lo[-2] > kl[-2]
    inside_now = up[-1] < ku[-1] and lo[-1] > kl[-1]
    if not (inside_prev and not inside_now):
        return None
    atr = _atr(bars)
    closes = _c(bars)
    mom = closes[-1] - (sum(closes[-p["period"]:]) / p["period"])
    side = "BUY" if mom > 0 else "SELL"
    return _mk(side, closes[-1], atr, p["target_atr"], p["stop_atr"], "TTM Squeeze Release",
               f"Bollinger bands left the Keltner channel with momentum {mom:+.2f}", 0.62)


def ema_ribbon(spec, bars) -> Optional[PatternSignal]:
    """Several EMAs compressed into a narrow band, then price breaks away from them."""
    p = spec.params
    closes = _c(bars)
    periods = p["periods"]
    if len(closes) < max(periods) + 3:
        return None
    vals = []
    for per in periods:
        e = ema(closes, per)
        if not e:
            return None
        vals.append(e[-1])
    spread = (max(vals) - min(vals)) / (sum(vals) / len(vals))
    if spread > p["max_spread"]:
        return None
    atr, last = _atr(bars), closes[-1]
    if last > max(vals) * (1 + p["break_pct"]):
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "EMA Ribbon Compression",
                   f"EMA ribbon compressed to {spread*100:.2f}% then price broke above it", 0.6)
    if last < min(vals) * (1 - p["break_pct"]):
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "EMA Ribbon Compression",
                   f"EMA ribbon compressed to {spread*100:.2f}% then price broke below it", 0.6)
    return None


def atr_thrust(spec, bars) -> Optional[PatternSignal]:
    """A single bar whose range dwarfs recent ATR — a volatility expansion thrust."""
    p = spec.params
    if len(bars) < 20:
        return None
    atr = _atr(bars)
    b = bars[-1]
    if atr <= 0 or _range(b) < atr * p["thrust"]:
        return None
    if _body(b) < _range(b) * p["min_body"]:
        return None
    side = "BUY" if b.close > b.open else "SELL"
    return _mk(side, b.close, atr, p["target_atr"], p["stop_atr"], "ATR Expansion Thrust",
               f"Bar range {_range(b):.2f} = {_range(b)/atr:.1f}x ATR, closing "
               f"{'up' if side == 'BUY' else 'down'}", 0.6)


def hh_hl_shift(spec, bars) -> Optional[PatternSignal]:
    """Market-structure shift: the sequence of swing highs and lows flips from
    lower-highs/lower-lows to higher-highs/higher-lows, or the reverse."""
    p = spec.params
    hi, lo = pivots(bars, p["pivot"], p["pivot"])
    if len(hi) < 3 or len(lo) < 3:
        return None
    h = [bars[i].high for i in hi[-3:]]
    l = [bars[i].low for i in lo[-3:]]
    atr, last = _atr(bars), bars[-1].close
    was_down = h[0] > h[1] and l[0] > l[1]
    now_up = h[2] > h[1] and l[2] > l[1]
    was_up = h[0] < h[1] and l[0] < l[1]
    now_dn = h[2] < h[1] and l[2] < l[1]
    if was_down and now_up and last > h[1]:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "HH/HL Structure Shift",
                   f"Structure flipped to higher-high/higher-low and took out {h[1]:.2f}", 0.63)
    if was_up and now_dn and last < l[1]:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "LH/LL Structure Shift",
                   f"Structure flipped to lower-high/lower-low and took out {l[1]:.2f}", 0.63)
    return None


def opening_range(spec, bars) -> Optional[PatternSignal]:
    """True opening-range breakout — MCX opens at 09:00 and these are real intraday bars,
    so the range is measured, not proxied the way the equity desks have to."""
    p = spec.params
    today = bars[-1].ts.date()
    session = [b for b in bars if b.ts.date() == today]
    n = p["or_bars"]
    if len(session) < n + 2:
        return None
    orb = session[:n]
    hi, lo = max(b.high for b in orb), min(b.low for b in orb)
    atr, last = _atr(bars), bars[-1].close
    if last > hi:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Opening Range Breakout",
                   f"Above the {n}-bar opening range high {hi:.2f}", 0.6)
    if last < lo:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Opening Range Breakout",
                   f"Below the {n}-bar opening range low {lo:.2f}", 0.6)
    return None


def pivot_break(spec, bars) -> Optional[PatternSignal]:
    """Classic floor-trader pivots off the previous session, traded on the R1/S1 break."""
    p = spec.params
    days = sorted({b.ts.date() for b in bars})
    if len(days) < 2:
        return None
    prev = [b for b in bars if b.ts.date() == days[-2]]
    if not prev:
        return None
    ph, pl, pc = max(b.high for b in prev), min(b.low for b in prev), prev[-1].close
    pivot = (ph + pl + pc) / 3
    r1, s1 = 2 * pivot - pl, 2 * pivot - ph
    atr, last = _atr(bars), bars[-1].close
    prev_close = bars[-2].close
    if prev_close <= r1 < last:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Pivot R1 Break",
                   f"Broke R1 {r1:.2f} (pivot {pivot:.2f}) at {last:.2f}", 0.58)
    if prev_close >= s1 > last:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Pivot S1 Break",
                   f"Broke S1 {s1:.2f} (pivot {pivot:.2f}) at {last:.2f}", 0.58)
    return None


def fib_bounce(spec, bars) -> Optional[PatternSignal]:
    """Retracement to the 61.8% level of the last measured swing, then a turn back in
    the direction of that swing."""
    p = spec.params
    w = p["window"]
    if len(bars) < w + 3:
        return None
    seg = bars[-w:]
    hi_i = max(range(len(seg)), key=lambda i: seg[i].high)
    lo_i = min(range(len(seg)), key=lambda i: seg[i].low)
    hi, lo = seg[hi_i].high, seg[lo_i].low
    if hi <= lo:
        return None
    atr, last, prev = _atr(bars), bars[-1].close, bars[-2].close
    tol = (hi - lo) * p["tol"]
    if lo_i < hi_i:   # up-swing: retrace down to 61.8% and hold
        level = hi - (hi - lo) * 0.618
        if abs(prev - level) <= tol and last > prev:
            return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Fib 61.8% Bounce",
                       f"Held the 61.8% retracement {level:.2f} of the {lo:.2f}->{hi:.2f} swing", 0.6)
    else:             # down-swing: retrace up to 61.8% and fail
        level = lo + (hi - lo) * 0.618
        if abs(prev - level) <= tol and last < prev:
            return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Fib 61.8% Rejection",
                       f"Rejected the 61.8% retracement {level:.2f} of the {hi:.2f}->{lo:.2f} swing", 0.6)
    return None


def ema_pullback(spec, bars) -> Optional[PatternSignal]:
    """Trend intact, price pulls back to the fast EMA and turns — a continuation entry."""
    p = spec.params
    closes = _c(bars)
    f, s = ema(closes, p["fast"]), ema(closes, p["slow"])
    if not f or not s or len(bars) < p["slow"] + 3:
        return None
    atr, last, prev = _atr(bars), closes[-1], closes[-2]
    near = abs(prev - f[-1]) <= atr * p["touch_atr"]
    if f[-1] > s[-1] and near and last > prev:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Trend Pullback to EMA",
                   f"Uptrend ({p['fast']}>{p['slow']} EMA), pulled back to {f[-1]:.2f} and turned up", 0.6)
    if f[-1] < s[-1] and near and last < prev:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Trend Pullback to EMA",
                   f"Downtrend ({p['fast']}<{p['slow']} EMA), pulled back to {f[-1]:.2f} and turned down", 0.6)
    return None


def gap_fade(spec, bars) -> Optional[PatternSignal]:
    """Session opens away from the prior close; fade it back toward that close."""
    p = spec.params
    days = sorted({b.ts.date() for b in bars})
    if len(days) < 2:
        return None
    today = [b for b in bars if b.ts.date() == days[-1]]
    prev = [b for b in bars if b.ts.date() == days[-2]]
    if not today or not prev or len(today) < 2:
        return None
    prev_close, open_px = prev[-1].close, today[0].open
    if prev_close <= 0:
        return None
    gap = (open_px - prev_close) / prev_close
    if abs(gap) < p["min_gap"]:
        return None
    atr, last = _atr(bars), bars[-1].close
    if gap > 0 and last < open_px:
        return _mk("SELL", last, atr, p["target_atr"], p["stop_atr"], "Gap Fade",
                   f"Gapped up {gap*100:+.2f}% and is fading back toward {prev_close:.2f}", 0.56)
    if gap < 0 and last > open_px:
        return _mk("BUY", last, atr, p["target_atr"], p["stop_atr"], "Gap Fade",
                   f"Gapped down {gap*100:+.2f}% and is fading back toward {prev_close:.2f}", 0.56)
    return None


# --------------------------------------------------------------------------------
# Registry + catalog
# --------------------------------------------------------------------------------

TEMPLATES: dict[str, tuple[str, str, Callable, dict, int]] = {
    # key: (family, display name, fn, default params, min_bars)
    "head_shoulders": ("chart", "Head & Shoulders", head_shoulders,
                       dict(pivot=3, shoulder_tol=0.03, target_atr=3.0, stop_atr=1.5), 70),
    "double_top_bottom": ("chart", "Double Top / Bottom", double_top_bottom,
                          dict(pivot=3, level_tol=0.02, min_sep=5, target_atr=3.0, stop_atr=1.5), 60),
    "triple_top_bottom": ("chart", "Triple Top / Bottom", triple_top_bottom,
                          dict(pivot=3, level_tol=0.025, target_atr=3.5, stop_atr=1.5), 80),
    "ascending_triangle": ("chart", "Ascending Triangle", ascending_triangle,
                           dict(pivot=3, flat_tol=0.002, slope_min=0.002, target_atr=3.0, stop_atr=1.5), 60),
    "descending_triangle": ("chart", "Descending Triangle", descending_triangle,
                            dict(pivot=3, flat_tol=0.002, slope_min=0.002, target_atr=3.0, stop_atr=1.5), 60),
    "symmetrical_triangle": ("chart", "Symmetrical Triangle", symmetrical_triangle,
                             dict(pivot=3, flat_tol=0.002, slope_min=0.002, target_atr=3.0, stop_atr=1.5), 60),
    "wedge": ("chart", "Rising / Falling Wedge", wedge,
              dict(pivot=3, slope_min=0.002, target_atr=3.0, stop_atr=1.5), 60),
    "flag": ("chart", "Bull / Bear Flag", flag,
             dict(impulse=8, consol=6, min_pole=0.015, max_flag_atr=4.0, target_atr=3.0, stop_atr=1.5), 40),
    "pennant": ("chart", "Pennant", pennant,
                dict(impulse=8, consol=8, min_pole=0.015, converge=0.7, target_atr=3.0, stop_atr=1.5), 40),
    "cup_handle": ("chart", "Cup & Handle", cup_handle,
                   dict(cup=40, handle=8, rim_tol=0.03, centre_tol=0.25, target_atr=4.0, stop_atr=2.0), 70),
    "rounding": ("chart", "Rounding Top / Bottom", rounding,
                 dict(window=40, slope_min=0.001, centre_tol=0.3, target_atr=3.5, stop_atr=2.0), 60),
    "diamond": ("chart", "Diamond", diamond,
                dict(window=40, expand=1.3, contract=0.7, target_atr=3.0, stop_atr=1.5), 60),
    "broadening": ("chart", "Broadening Formation", broadening,
                   dict(pivot=3, slope_min=0.002, target_atr=2.5, stop_atr=1.5), 60),

    "engulfing": ("candlestick", "Engulfing Candle", engulfing,
                  dict(min_ratio=1.2, target_atr=2.0, stop_atr=1.0), 30),
    "hammer_star": ("candlestick", "Hammer / Shooting Star", hammer_star,
                    dict(wick_mult=2.0, target_atr=2.0, stop_atr=1.0), 30),
    "doji_reversal": ("candlestick", "Doji Reversal", doji_reversal,
                      dict(max_body=0.10, extreme_window=20, target_atr=2.0, stop_atr=1.0), 30),
    "marubozu": ("candlestick", "Marubozu Continuation", marubozu,
                 dict(min_body=0.90, target_atr=2.0, stop_atr=1.0), 30),
    "inside_bar": ("candlestick", "Inside Bar Breakout", inside_bar,
                   dict(max_inside=0.7, target_atr=2.0, stop_atr=1.0), 30),
    "outside_bar": ("candlestick", "Outside Bar Reversal", outside_bar,
                    dict(min_ratio=1.2, target_atr=2.0, stop_atr=1.0), 30),
    "soldiers_crows": ("candlestick", "Three Soldiers / Crows", soldiers_crows,
                       dict(count=3, target_atr=2.5, stop_atr=1.2), 30),
    "star": ("candlestick", "Morning / Evening Star", star,
             dict(star_body=0.35, target_atr=2.5, stop_atr=1.2), 30),
    "pin_bar": ("candlestick", "Pin Bar at Extreme", pin_bar,
                dict(wick_frac=0.60, extreme_window=20, target_atr=2.5, stop_atr=1.2), 30),
    "heikin_flip": ("candlestick", "Heikin Ashi Flip", heikin_flip,
                    dict(confirm=2, target_atr=2.5, stop_atr=1.2), 30),

    "donchian_fast": ("structure", "Donchian Breakout (fast)", donchian_break,
                      dict(period=20, target_atr=3.0, stop_atr=1.5), 40),
    "donchian_slow": ("structure", "Donchian Breakout (slow)", donchian_break,
                      dict(period=55, target_atr=4.0, stop_atr=2.0), 70),
    "keltner_break": ("structure", "Keltner Breakout", keltner_break,
                      dict(period=20, mult=2.0, target_atr=3.0, stop_atr=1.5), 40),
    "bollinger_pctb": ("structure", "Bollinger %B Extreme", bollinger_pctb,
                       dict(period=20, mult=2.0, low=0.0, high=1.0, target_atr=2.0, stop_atr=1.2), 40),
    "prior_session_break": ("structure", "Prior Session High/Low Break", prior_session_break,
                            dict(target_atr=3.0, stop_atr=1.5), 40),
    "round_number_break": ("structure", "Round Number Break", round_number_break,
                           dict(digits=2, tol=0.15, target_atr=2.0, stop_atr=1.0), 30),
    "bollinger_squeeze": ("structure", "Bollinger Squeeze Release", bollinger_squeeze,
                          dict(period=20, mult=2.0, lookback=30, squeeze_tol=1.05,
                               target_atr=3.5, stop_atr=1.5), 60),
    "ttm_squeeze": ("structure", "TTM Squeeze", ttm_squeeze,
                    dict(period=20, bb_mult=2.0, kc_mult=1.5, target_atr=3.5, stop_atr=1.5), 50),
    "ema_ribbon": ("structure", "EMA Ribbon Compression", ema_ribbon,
                   dict(periods=(8, 13, 21, 34), max_spread=0.004, break_pct=0.001,
                        target_atr=3.0, stop_atr=1.5), 50),
    "atr_thrust": ("structure", "ATR Expansion Thrust", atr_thrust,
                   dict(thrust=2.0, min_body=0.6, target_atr=2.5, stop_atr=1.2), 30),
    "hh_hl_shift": ("structure", "HH/HL Structure Shift", hh_hl_shift,
                    dict(pivot=3, target_atr=3.0, stop_atr=1.5), 60),
    "opening_range": ("structure", "Opening Range Breakout", opening_range,
                      dict(or_bars=4, target_atr=2.5, stop_atr=1.2), 30),
    "pivot_break": ("structure", "Pivot R1/S1 Break", pivot_break,
                    dict(target_atr=2.5, stop_atr=1.2), 40),
    "fib_bounce": ("structure", "Fibonacci 61.8% Bounce", fib_bounce,
                   dict(window=40, tol=0.08, target_atr=3.0, stop_atr=1.5), 50),
    "ema_pullback": ("structure", "Trend Pullback to EMA", ema_pullback,
                     dict(fast=20, slow=50, touch_atr=0.4, target_atr=3.0, stop_atr=1.5), 60),
    "gap_fade": ("structure", "Gap Fade", gap_fade,
                 dict(min_gap=0.004, target_atr=2.0, stop_atr=1.2), 40),
}

# The timeframes every template is instantiated on. Kept here (not imported from
# commodity_bars) so the catalog is importable without touching Mongo.
CATALOG_TIMEFRAMES = ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"]

# Intraday-only templates: they read a session's own structure, which a daily bar has no
# concept of. Instantiating them on 1d would silently compare yesterday to the day before
# and call it an "opening range".
INTRADAY_ONLY = {"opening_range"}


def _build_catalog() -> list[PatternSpec]:
    specs: list[PatternSpec] = []
    for tf in CATALOG_TIMEFRAMES:
        for key, (family, label, _fn, params, min_bars) in TEMPLATES.items():
            if key in INTRADAY_ONLY and tf == "1d":
                continue
            specs.append(PatternSpec(
                strategy_id=f"cmd_{len(specs) + 1:04d}",
                name=f"{label} · {tf}",
                family=family, template=key, timeframe=tf,
                rationale=f"{label} evaluated on {tf} commodity futures bars.",
                params=dict(params), min_bars=min_bars,
            ))
    return specs


COMMODITY_CATALOG: list[PatternSpec] = _build_catalog()
COMMODITY_BY_ID: dict[str, PatternSpec] = {s.strategy_id: s for s in COMMODITY_CATALOG}

assert len(TEMPLATES) == 39, f"expected 39 templates, have {len(TEMPLATES)}"
assert len(COMMODITY_BY_ID) == len(COMMODITY_CATALOG), "duplicate commodity strategy_id"
assert {t[0] for t in TEMPLATES.values()} == {"chart", "candlestick", "structure"}


def evaluate(spec: PatternSpec, bars: list) -> Optional[PatternSignal]:
    entry = TEMPLATES.get(spec.template)
    if entry is None or len(bars) < spec.min_bars:
        return None
    fn = entry[2]
    try:
        return fn(spec, bars)
    except (IndexError, ValueError, ZeroDivisionError, TypeError, KeyError):
        # One malformed series must cost one signal, never the whole scan.
        return None


__all__ = ["COMMODITY_CATALOG", "COMMODITY_BY_ID", "TEMPLATES", "CATALOG_TIMEFRAMES",
           "FAMILY_LABELS", "INTRADAY_ONLY", "PatternSignal", "PatternSpec", "evaluate", "pivots"]
