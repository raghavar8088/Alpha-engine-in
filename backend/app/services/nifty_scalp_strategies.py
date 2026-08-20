"""Strategy library for the NIFTY 50 Option Scalping desk.

SIXTY-THREE templates, each one a rule over CANDLES and INDICATORS — no fundamental,
news or sentiment inputs — instantiated on every timeframe from 1 minute to 1 day.
63 x 8 = 504 strategies, each with its own Rs2,00,000 book.

Fifty are single-bar or short-window rules that can be checked exactly on the last closed
bar. THIRTEEN are the classic geometric chart patterns — head & shoulders, double and
triple tops/bottoms, the three triangles, wedges, flags, pennants, cup & handle, rounding
tops/bottoms, diamonds and broadening formations. Those are a different kind of rule: they
are statements about the shape of the last several SWING POINTS, not about a candle, so
they need pivot detection and trendline fitting first. Each also requires price to close
through the pattern's own boundary before it fires — a shape that has not broken is not a
signal, and firing on the shape alone is how these patterns earn their reputation for
being imaginary.

WHY THE SAME 50 ON EVERY TIMEFRAME: the point of this desk is to find which edges survive
into real money, and an edge is a pairing of a RULE with a HORIZON. Running "EMA 9/21
cross" on 1-minute and on daily candles is not duplication — it is the experiment. Holding
the rule constant across timeframes is the only way the leaderboard can answer "does this
rule work, and at what horizon", instead of confounding the two.

Lookbacks scale with the timeframe (`speed`): a 200-period EMA on 1-minute candles is
about three sessions, on daily candles it is a year. Using one fixed number would quietly
turn the same template into a different strategy at each horizon, which is exactly the
confound above. Each template therefore reads its periods from the timeframe profile.

Every template returns +1 (bullish -> buy an ATM CALL), -1 (bearish -> buy an ATM PUT) or
0 (no trade). Direction only; the engine owns strike selection, sizing and exits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

# ── candle series ──────────────────────────────────────────────────────────────


@dataclass
class Series:
    """OHLCV columns for one timeframe, oldest first. Indicators are computed once per
    cycle and cached here, because 50 strategies per timeframe would otherwise recompute
    the same EMA 50 times."""

    ts: list
    o: list[float]
    h: list[float]
    l: list[float]
    c: list[float]
    v: list[float]

    def __post_init__(self):
        self._cache: dict = {}

    def __len__(self) -> int:
        return len(self.c)

    def cached(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]


def from_rows(rows: list[list]) -> Series:
    """Angel candle rows: [timestamp, open, high, low, close, volume]."""
    ts, o, h, l, c, v = [], [], [], [], [], []
    for r in rows:
        if len(r) < 6:
            continue
        try:
            o.append(float(r[1])); h.append(float(r[2])); l.append(float(r[3]))
            c.append(float(r[4])); v.append(float(r[5] or 0)); ts.append(r[0])
        except (TypeError, ValueError):
            continue
    return Series(ts, o, h, l, c, v)


def resample(s: Series, factor: int) -> Series:
    """Aggregate `factor` bars into one. Angel has no native 4-hour interval, so the 4H
    series is built from 1H bars here rather than being silently skipped. NSE trades
    6h15m a day, so the last bucket of a session is a partial bar — real, but shorter
    than the others, which is worth knowing before trusting a 4H signal."""
    ts, o, h, l, c, v = [], [], [], [], [], []
    for i in range(0, len(s) - factor + 1, factor):
        j = i + factor
        ts.append(s.ts[i]); o.append(s.o[i]); h.append(max(s.h[i:j]))
        l.append(min(s.l[i:j])); c.append(s.c[j - 1]); v.append(sum(s.v[i:j]))
    return Series(ts, o, h, l, c, v)


# ── indicators ─────────────────────────────────────────────────────────────────


def ema(vals: list[float], n: int) -> list[float]:
    if not vals:
        return []
    k = 2.0 / (n + 1)
    out = [vals[0]]
    for x in vals[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def sma(vals: list[float], n: int) -> list[float]:
    out, run = [], 0.0
    for i, x in enumerate(vals):
        run += x
        if i >= n:
            run -= vals[i - n]
        out.append(run / min(i + 1, n))
    return out


def wma(vals: list[float], n: int) -> list[float]:
    out = []
    for i in range(len(vals)):
        w = vals[max(0, i - n + 1): i + 1]
        d = sum(range(1, len(w) + 1))
        out.append(sum(x * (k + 1) for k, x in enumerate(w)) / d)
    return out


def rsi(vals: list[float], n: int) -> list[float]:
    if len(vals) < 2:
        return [50.0] * len(vals)
    out, ag, al = [50.0], 0.0, 0.0
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        g, l = max(d, 0.0), max(-d, 0.0)
        ag = (ag * (n - 1) + g) / n if i > 1 else g
        al = (al * (n - 1) + l) / n if i > 1 else l
        out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return out


def true_range(s: Series) -> list[float]:
    out = [s.h[0] - s.l[0]] if len(s) else []
    for i in range(1, len(s)):
        out.append(max(s.h[i] - s.l[i], abs(s.h[i] - s.c[i - 1]), abs(s.l[i] - s.c[i - 1])))
    return out


def atr(s: Series, n: int) -> list[float]:
    return s.cached(("atr", n), lambda: ema(true_range(s), n))


def stdev(vals: list[float], n: int) -> list[float]:
    out = []
    for i in range(len(vals)):
        w = vals[max(0, i - n + 1): i + 1]
        m = sum(w) / len(w)
        out.append(math.sqrt(sum((x - m) ** 2 for x in w) / len(w)))
    return out


def macd(vals: list[float], f: int, sl: int, sig: int):
    fast, slow = ema(vals, f), ema(vals, sl)
    line = [a - b for a, b in zip(fast, slow)]
    signal = ema(line, sig)
    return line, signal, [a - b for a, b in zip(line, signal)]


def stoch(s: Series, n: int, d: int):
    k = []
    for i in range(len(s)):
        hi = max(s.h[max(0, i - n + 1): i + 1]); lo = min(s.l[max(0, i - n + 1): i + 1])
        k.append(50.0 if hi == lo else (s.c[i] - lo) / (hi - lo) * 100)
    return k, sma(k, d)


def adx_di(s: Series, n: int):
    if len(s) < 2:
        return [0.0] * len(s), [0.0] * len(s), [0.0] * len(s)
    pdm, ndm = [0.0], [0.0]
    for i in range(1, len(s)):
        up, dn = s.h[i] - s.h[i - 1], s.l[i - 1] - s.l[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)
    tr = ema(true_range(s), n)
    pdi = [100 * a / b if b else 0.0 for a, b in zip(ema(pdm, n), tr)]
    ndi = [100 * a / b if b else 0.0 for a, b in zip(ema(ndm, n), tr)]
    dx = [100 * abs(a - b) / (a + b) if (a + b) else 0.0 for a, b in zip(pdi, ndi)]
    return ema(dx, n), pdi, ndi


def supertrend(s: Series, n: int, mult: float) -> list[int]:
    a = atr(s, n)
    dirs, prev_up, prev_dn, d = [], None, None, 1
    for i in range(len(s)):
        mid = (s.h[i] + s.l[i]) / 2
        up, dn = mid - mult * a[i], mid + mult * a[i]
        if prev_up is not None:
            up = max(up, prev_up) if s.c[i - 1] > prev_up else up
            dn = min(dn, prev_dn) if s.c[i - 1] < prev_dn else dn
            d = 1 if s.c[i] > dn else -1 if s.c[i] < up else d
        dirs.append(d); prev_up, prev_dn = up, dn
    return dirs


def psar(s: Series, step=0.02, mx=0.2) -> list[int]:
    if len(s) < 2:
        return [1] * len(s)
    out, bull, af, ep, sar = [1], True, step, s.h[0], s.l[0]
    for i in range(1, len(s)):
        sar += af * (ep - sar)
        if bull:
            if s.l[i] < sar:
                bull, sar, ep, af = False, ep, s.l[i], step
            elif s.h[i] > ep:
                ep, af = s.h[i], min(af + step, mx)
        else:
            if s.h[i] > sar:
                bull, sar, ep, af = True, ep, s.h[i], step
            elif s.l[i] < ep:
                ep, af = s.l[i], min(af + step, mx)
        out.append(1 if bull else -1)
    return out


def cci(s: Series, n: int) -> list[float]:
    tp = [(s.h[i] + s.l[i] + s.c[i]) / 3 for i in range(len(s))]
    m = sma(tp, n)
    out = []
    for i in range(len(s)):
        w = tp[max(0, i - n + 1): i + 1]
        md = sum(abs(x - m[i]) for x in w) / len(w)
        out.append(0.0 if md == 0 else (tp[i] - m[i]) / (0.015 * md))
    return out


def heikin(s: Series):
    ho, hc = [s.o[0]], [(s.o[0] + s.h[0] + s.l[0] + s.c[0]) / 4]
    for i in range(1, len(s)):
        hc.append((s.o[i] + s.h[i] + s.l[i] + s.c[i]) / 4)
        ho.append((ho[-1] + hc[-2]) / 2)
    return ho, hc


def vwap(s: Series) -> list[float]:
    pv = cum = 0.0
    out = []
    for i in range(len(s)):
        tp = (s.h[i] + s.l[i] + s.c[i]) / 3
        pv += tp * s.v[i]; cum += s.v[i]
        out.append(pv / cum if cum else s.c[i])
    return out


def aroon(s: Series, n: int):
    up, dn = [], []
    for i in range(len(s)):
        w_h = s.h[max(0, i - n + 1): i + 1]; w_l = s.l[max(0, i - n + 1): i + 1]
        up.append(100 * (len(w_h) - 1 - w_h.index(max(w_h))) / max(len(w_h) - 1, 1))
        dn.append(100 * (len(w_l) - 1 - w_l.index(min(w_l))) / max(len(w_l) - 1, 1))
    return [100 - x for x in up], [100 - x for x in dn]


# ── swing structure, for the geometric chart patterns ──────────────────────────
#
# Everything below this line needs SWING POINTS, not bars. A head-and-shoulders is not a
# statement about the last candle; it is a statement about the shape of the last several
# turning points. So these first find pivots, then test the pivot sequence for a shape,
# then require a BREAK of the pattern's own boundary before firing — a shape that has not
# broken is not yet a signal, and firing on the shape alone is how these patterns get a
# reputation for being imaginary.


def pivots(s: Series, k: int) -> list[tuple[int, float, int]]:
    """Fractal turning points as (bar index, price, +1 high | -1 low).

    A bar is a pivot high when its high is the highest in the +/-k window around it. The
    last k bars can never qualify — a turning point is only known once price has moved
    away from it — which is what keeps this from repainting."""
    out: list[tuple[int, float, int]] = []
    for i in range(k, len(s) - k):
        if s.h[i] == max(s.h[i - k:i + k + 1]):
            out.append((i, s.h[i], 1))
        elif s.l[i] == min(s.l[i - k:i + k + 1]):
            out.append((i, s.l[i], -1))
    return out


def swings(s: Series, k: int) -> list[tuple[int, float, int]]:
    """Pivots reduced to a strictly alternating high/low sequence.

    Raw fractals often produce two highs in a row with no low between them; keeping only
    the more extreme of each run is what makes "the last five swings" a meaningful phrase
    for the pattern matchers."""
    def build():
        out: list[tuple[int, float, int]] = []
        for p in pivots(s, k):
            if out and out[-1][2] == p[2]:
                better = p[1] > out[-1][1] if p[2] == 1 else p[1] < out[-1][1]
                if better:
                    out[-1] = p
            else:
                out.append(p)
        return out
    return s.cached(("swings", k), build)


def _near(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9)


def _slope(pts: list[tuple[float, float]]) -> float:
    """Least-squares slope, normalised by mean price so it is comparable across
    timeframes and price levels."""
    n = len(pts)
    if n < 2:
        return 0.0
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    den = sum((p[0] - mx) ** 2 for p in pts)
    if den == 0:
        return 0.0
    return (sum((p[0] - mx) * (p[1] - my) for p in pts) / den) / max(abs(my), 1e-9)


def _quadfit(ys: list[float]):
    """Fit y = a*x^2 + b*x + c over x = 0..n-1. Returns (a_normalised, vertex_position)
    with vertex_position in 0..1 across the window.

    A rounding bottom is a positive quadratic whose vertex sits near the middle; testing
    that directly is more honest than eyeballing "looks like a U" with slope rules."""
    n = len(ys)
    if n < 5:
        return 0.0, 0.5
    sx = sx2 = sx3 = sx4 = sy = sxy = sx2y = 0.0
    for x, y in enumerate(ys):
        x2 = x * x
        sx += x; sx2 += x2; sx3 += x2 * x; sx4 += x2 * x2
        sy += y; sxy += x * y; sx2y += x2 * y
    m = [[sx4, sx3, sx2, sx2y], [sx3, sx2, sx, sxy], [sx2, sx, float(n), sy]]
    for col in range(3):                       # Gaussian elimination, 3x3
        piv = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return 0.0, 0.5
        m[col], m[piv] = m[piv], m[col]
        for r in range(3):
            if r == col:
                continue
            f = m[r][col] / m[col][col]
            for c in range(col, 4):
                m[r][c] -= f * m[col][c]
    a = m[0][3] / m[0][0]
    b = m[1][3] / m[1][1]
    if abs(a) < 1e-12:
        return 0.0, 0.5
    vertex = (-b / (2 * a)) / max(n - 1, 1)
    mean = sy / n
    return a * (n ** 2) / max(abs(mean), 1e-9), vertex


def _broke_up(s: Series, level: float) -> bool:
    return len(s) > 1 and s.c[-1] > level and s.c[-2] <= level


def _broke_dn(s: Series, level: float) -> bool:
    return len(s) > 1 and s.c[-1] < level and s.c[-2] >= level


# ── the geometric patterns ─────────────────────────────────────────────────────


def t_head_shoulders(s, p):
    """Head & shoulders / inverse: five swings, a dominant middle, matched shoulders,
    and a close through the neckline."""
    w = swings(s, p["pivot"])
    if len(w) < 5:
        return 0
    a, b, c, d, e = w[-5:]
    kinds = [x[2] for x in (a, b, c, d, e)]
    neck = (b[1] + d[1]) / 2
    if kinds == [1, -1, 1, -1, 1]:
        if c[1] > a[1] and c[1] > e[1] and _near(a[1], e[1], 0.03) and _near(b[1], d[1], 0.03):
            return -1 if _broke_dn(s, neck) else 0
    if kinds == [-1, 1, -1, 1, -1]:
        if c[1] < a[1] and c[1] < e[1] and _near(a[1], e[1], 0.03) and _near(b[1], d[1], 0.03):
            return 1 if _broke_up(s, neck) else 0
    return 0


def t_double_top_bottom(s, p):
    """Two matched extremes either side of a single counter-swing, then a break of it."""
    w = swings(s, p["pivot"])
    if len(w) < 3:
        return 0
    a, b, c = w[-3:]
    if not _near(a[1], c[1], 0.015):
        return 0
    if a[2] == 1 and b[2] == -1:
        return -1 if _broke_dn(s, b[1]) else 0
    if a[2] == -1 and b[2] == 1:
        return 1 if _broke_up(s, b[1]) else 0
    return 0


def t_triple_top_bottom(s, p):
    """Three matched extremes — unlike head & shoulders, the middle one is NOT dominant,
    which is the whole distinction between the two shapes."""
    w = swings(s, p["pivot"])
    if len(w) < 5:
        return 0
    a, b, c, d, e = w[-5:]
    kinds = [x[2] for x in (a, b, c, d, e)]
    if kinds == [1, -1, 1, -1, 1] and _near(a[1], c[1], 0.02) and _near(c[1], e[1], 0.02):
        return -1 if _broke_dn(s, min(b[1], d[1])) else 0
    if kinds == [-1, 1, -1, 1, -1] and _near(a[1], c[1], 0.02) and _near(c[1], e[1], 0.02):
        return 1 if _broke_up(s, max(b[1], d[1])) else 0
    return 0


def _tri_lines(s, p, need=2):
    """Recent highs and lows as (index, price) lists, for trendline fitting."""
    w = swings(s, p["pivot"])
    hi = [(x[0], x[1]) for x in w if x[2] == 1][-3:]
    lo = [(x[0], x[1]) for x in w if x[2] == -1][-3:]
    if len(hi) < need or len(lo) < need:
        return None, None
    return hi, lo


FLAT = 0.0004   # a trendline this shallow counts as horizontal


def t_ascending_triangle(s, p):
    """Flat resistance, rising support — bullish on a close through the resistance."""
    hi, lo = _tri_lines(s, p)
    if hi is None:
        return 0
    if abs(_slope(hi)) < FLAT and _slope(lo) > FLAT:
        return 1 if _broke_up(s, max(h[1] for h in hi)) else 0
    return 0


def t_descending_triangle(s, p):
    hi, lo = _tri_lines(s, p)
    if hi is None:
        return 0
    if abs(_slope(lo)) < FLAT and _slope(hi) < -FLAT:
        return -1 if _broke_dn(s, min(l[1] for l in lo)) else 0
    return 0


def t_symmetrical_triangle(s, p):
    """Both boundaries converging. Direction is taken from the break, not guessed."""
    hi, lo = _tri_lines(s, p)
    if hi is None:
        return 0
    if _slope(hi) < -FLAT and _slope(lo) > FLAT:
        if _broke_up(s, max(h[1] for h in hi)):
            return 1
        if _broke_dn(s, min(l[1] for l in lo)):
            return -1
    return 0


def t_wedge(s, p):
    """Rising wedge (both lines up, converging) breaks DOWN; falling wedge breaks UP.
    A wedge points the opposite way to its slope, which is what separates it from a
    trend channel."""
    hi, lo = _tri_lines(s, p)
    if hi is None:
        return 0
    sh, sl = _slope(hi), _slope(lo)
    if sh > FLAT and sl > FLAT and sl > sh:              # rising, converging
        return -1 if _broke_dn(s, min(l[1] for l in lo)) else 0
    if sh < -FLAT and sl < -FLAT and sh > sl:            # falling, converging
        return 1 if _broke_up(s, max(h[1] for h in hi)) else 0
    return 0


# A pole must be a move the market does not make by drifting. Over an n-bar window a
# random walk covers roughly sqrt(n) x ATR, so a 3x-ATR gate is about a one-sigma move —
# it lets ordinary noise through and then the range test rejects everything, which is how
# the flag and pennant templates managed to never fire once in 3,200 evaluations. 4x ATR
# is a genuine thrust, and the consolidation is then measured RELATIVE to it.
POLE_ATR_MULT = 4.0
# The consolidation may be as wide as the pole itself but no wider; what makes it a flag
# is that the thrust stopped, not that the range collapsed to nothing.
FLAG_RANGE_FRAC = 1.0


def _pole(s, p):
    """(direction, size) of the impulse leading into the current consolidation."""
    n, m = p["pole"], p["flag"]
    if len(s) < n + m + 2:
        return 0, 0.0
    start, end = s.c[-(n + m)], s.c[-m]
    move = (end - start) / max(abs(start), 1e-9)
    a = atr(s, 14)[-1] / max(s.c[-1], 1e-9)
    if abs(move) < POLE_ATR_MULT * a:
        return 0, 0.0
    return (1 if move > 0 else -1), abs(move)


def t_flag(s, p):
    """Sharp pole, then a shallow counter-drift in a tight range, then continuation."""
    d, size = _pole(s, p)
    if not d:
        return 0
    m = p["flag"]
    # The consolidation is measured on bars BEFORE the current one. Including the current
    # bar puts its own high into the level it must exceed, so `close > max(...)` can never
    # be true and the template silently never fires — which is exactly what a 3,200-bar
    # sweep caught here. Any breakout level must be built from history only.
    seg_h, seg_l = max(s.h[-(m + 1):-1]), min(s.l[-(m + 1):-1])
    if (seg_h - seg_l) / max(s.c[-1], 1e-9) > FLAG_RANGE_FRAC * size:
        return 0                                        # too loose to be a flag
    if d > 0 and _broke_up(s, seg_h):
        return 1
    if d < 0 and _broke_dn(s, seg_l):
        return -1
    return 0


def t_pennant(s, p):
    """Pole, then a small SYMMETRICAL convergence — a flag whose range narrows."""
    d, _ = _pole(s, p)
    if not d:
        return 0
    m = p["flag"]
    if m < 6:
        return 0
    half = m // 2
    early = max(s.h[-(m + 1):-half - 1]) - min(s.l[-(m + 1):-half - 1])
    late_h, late_l = max(s.h[-(half + 1):-1]), min(s.l[-(half + 1):-1])
    if (late_h - late_l) >= early * 0.7:
        return 0                                        # not converging
    if d > 0 and _broke_up(s, late_h):
        return 1
    if d < 0 and _broke_dn(s, late_l):
        return -1
    return 0


def _rounded(win: list[float], bullish: bool, floor_depth: float) -> bool:
    """Is this window a U (or an upside-down U) rather than a V or a straight line?

    Three things have to hold, and none of them alone is enough: the quadratic must curve
    the right way, the move must be deep enough to be a pattern rather than noise, and the
    base must be FLAT — a V-bottom and a U-bottom both put their extreme in the middle,
    and only the width of the base distinguishes them. Basing the depth test on ATR
    instead of a fixed percentage is what makes the same rule work on 1-minute and daily
    candles."""
    a, vx = _quadfit(win)
    if not (0.3 <= vx <= 0.7):
        return False
    if (a <= 0) if bullish else (a >= 0):
        return False
    extreme = min(win) if bullish else max(win)
    rim = max(win[0], win[-1]) if bullish else min(win[0], win[-1])
    depth = abs(rim - extreme)
    if depth < floor_depth:
        return False
    # a genuine base spends time near the extreme; a V touches it once
    near_base = sum(1 for y in win if abs(y - extreme) < 0.35 * depth)
    return near_base >= max(4, len(win) // 5)


def t_cup_handle(s, p):
    """Rounded base with matched rims, a shallow handle, then a break of the rim.

    The roundness test is a quadratic fit: a V-bottom and a U-bottom both have a low in
    the middle, and only the curvature tells them apart."""
    n = p["cup"]
    h = max(4, n // 6)
    if len(s) < n + h + 2:
        return 0
    cup = s.c[-(n + h):-h]
    left, right = cup[0], cup[-1]
    if not _near(left, right, 0.05):
        return 0
    floor_depth = 2.0 * atr(s, 14)[-1]
    handle_hi, handle_lo = max(s.h[-h:]), min(s.l[-h:])
    if _rounded(cup, True, floor_depth):
        rim = max(left, right)
        if (handle_hi - handle_lo) < 0.6 * abs(rim - min(cup)) and _broke_up(s, rim):
            return 1
    if _rounded(cup, False, floor_depth):
        rim = min(left, right)
        if (handle_hi - handle_lo) < 0.6 * abs(max(cup) - rim) and _broke_dn(s, rim):
            return -1
    return 0


def t_rounding(s, p):
    """Rounding bottom / top with no handle: curvature plus a centred vertex, then a
    close through the rim."""
    n = p["cup"]
    if len(s) < n + 2:
        return 0
    win = s.c[-(n + 1):-1]          # rim from history; the last bar is the break
    # A saucer has LEVEL rims, and "level" has to be judged against the pattern's own
    # DEPTH rather than against price. A 6%-of-price tolerance sounds strict but is ~1440
    # NIFTY points, wider than the whole window — it excluded nothing. Depth-relative is
    # both the real definition and the only version that scales across timeframes.
    depth = max(win) - min(win)
    if depth <= 0 or abs(win[0] - win[-1]) > 0.35 * depth:
        return 0
    floor_depth = 2.0 * atr(s, 14)[-1]
    if _rounded(win, True, floor_depth) and _broke_up(s, max(win[0], win[-1])):
        return 1
    if _rounded(win, False, floor_depth) and _broke_dn(s, min(win[0], win[-1])):
        return -1
    return 0


def t_diamond(s, p):
    """Broadening then narrowing — range expands in the first half of the window and
    contracts in the second. Direction comes from the break."""
    n = p["cup"]
    if len(s) < n + 2 or n < 12:
        return 0
    t = n // 3
    r1 = max(s.h[-n:-2 * t]) - min(s.l[-n:-2 * t])
    r2 = max(s.h[-2 * t:-t]) - min(s.l[-2 * t:-t])
    r3 = max(s.h[-t:]) - min(s.l[-t:])
    if not (r2 > r1 * 1.2 and r3 < r2 * 0.8):
        return 0
    if _broke_up(s, max(s.h[-t:-1])):
        return 1
    if _broke_dn(s, min(s.l[-t:-1])):
        return -1
    return 0


def t_broadening(s, p):
    """Higher highs AND lower lows — a megaphone. Widening, so the break is taken
    against the last expansion."""
    hi, lo = _tri_lines(s, p, need=3)
    if hi is None:
        return 0
    if _slope(hi) > FLAT and _slope(lo) < -FLAT:
        if _broke_up(s, hi[-1][1]):
            return 1
        if _broke_dn(s, lo[-1][1]):
            return -1
    return 0


def _x_up(a: list[float], b: list[float]) -> bool:
    """`a` crossed above `b` on the last closed bar — a CROSS, not merely 'is above',
    so a strategy fires once at the event instead of every bar of a long trend."""
    return len(a) > 1 and a[-2] <= b[-2] and a[-1] > b[-1]


def _x_dn(a: list[float], b: list[float]) -> bool:
    return len(a) > 1 and a[-2] >= b[-2] and a[-1] < b[-1]


def _body(s: Series, i: int) -> float:
    return abs(s.c[i] - s.o[i])


def _rng(s: Series, i: int) -> float:
    return max(s.h[i] - s.l[i], 1e-9)


# ── the 50 templates ───────────────────────────────────────────────────────────
# Each takes (Series, profile) and returns +1 bullish / -1 bearish / 0 no trade.

P = dict  # profile: scaled lookbacks for this timeframe


def t_ema_fast_cross(s, p):
    f, sl = ema(s.c, p["fast"]), ema(s.c, p["mid"])
    return 1 if _x_up(f, sl) else -1 if _x_dn(f, sl) else 0


def t_ema_slow_cross(s, p):
    f, sl = ema(s.c, p["mid"]), ema(s.c, p["slow"])
    return 1 if _x_up(f, sl) else -1 if _x_dn(f, sl) else 0


def t_sma_cross(s, p):
    f, sl = sma(s.c, p["fast"]), sma(s.c, p["slow"])
    return 1 if _x_up(f, sl) else -1 if _x_dn(f, sl) else 0


def t_triple_ema_stack(s, p):
    a, b, c = ema(s.c, p["fast"]), ema(s.c, p["mid"]), ema(s.c, p["slow"])
    if a[-1] > b[-1] > c[-1] and not (a[-2] > b[-2] > c[-2]):
        return 1
    if a[-1] < b[-1] < c[-1] and not (a[-2] < b[-2] < c[-2]):
        return -1
    return 0


def t_ema_ribbon_squeeze(s, p):
    es = [ema(s.c, n)[-1] for n in (p["fast"], p["mid"], p["slow"])]
    spread = (max(es) - min(es)) / max(s.c[-1], 1e-9)
    if spread > 0.0015:
        return 0
    return 1 if s.c[-1] > max(es) else -1 if s.c[-1] < min(es) else 0


def t_trend_pullback(s, p):
    e = ema(s.c, p["trend"])
    if s.c[-1] > e[-1] and s.l[-1] <= e[-1] < s.l[-2]:
        return 1
    if s.c[-1] < e[-1] and s.h[-1] >= e[-1] > s.h[-2]:
        return -1
    return 0


def t_wma_cross(s, p):
    f, sl = wma(s.c, p["fast"]), wma(s.c, p["mid"])
    return 1 if _x_up(f, sl) else -1 if _x_dn(f, sl) else 0


def t_dema_cross(s, p):
    d = lambda n: [2 * a - b for a, b in zip(ema(s.c, n), ema(ema(s.c, n), n))]
    f, sl = d(p["fast"]), d(p["mid"])
    return 1 if _x_up(f, sl) else -1 if _x_dn(f, sl) else 0


def t_rsi_oversold(s, p):
    r = rsi(s.c, p["rsi"])
    return 1 if r[-2] < 30 <= r[-1] else 0


def t_rsi_overbought(s, p):
    r = rsi(s.c, p["rsi"])
    return -1 if r[-2] > 70 >= r[-1] else 0


def t_rsi_50_cross(s, p):
    r = rsi(s.c, p["rsi"])
    return 1 if r[-2] <= 50 < r[-1] else -1 if r[-2] >= 50 > r[-1] else 0


def t_rsi_divergence(s, p):
    n = p["mid"]
    if len(s) < n + 2:
        return 0
    r = rsi(s.c, p["rsi"])
    lo_now, lo_prev = min(s.l[-3:]), min(s.l[-n:-3])
    hi_now, hi_prev = max(s.h[-3:]), max(s.h[-n:-3])
    if lo_now < lo_prev and r[-1] > min(r[-n:-3]):
        return 1
    if hi_now > hi_prev and r[-1] < max(r[-n:-3]):
        return -1
    return 0


def t_stoch_cross(s, p):
    k, d = stoch(s, p["mid"], 3)
    if k[-1] < 25 and _x_up(k, d):
        return 1
    if k[-1] > 75 and _x_dn(k, d):
        return -1
    return 0


def t_cci_zero(s, p):
    c = cci(s, p["mid"])
    return 1 if c[-2] <= 0 < c[-1] else -1 if c[-2] >= 0 > c[-1] else 0


def t_williams_r(s, p):
    k, _ = stoch(s, p["mid"], 3)
    w = [x - 100 for x in k]
    return 1 if w[-2] < -80 <= w[-1] else -1 if w[-2] > -20 >= w[-1] else 0


def t_roc_flip(s, p):
    n = p["fast"]
    if len(s) < n + 2:
        return 0
    r = [(s.c[i] / s.c[i - n] - 1) * 100 for i in range(n, len(s))]
    return 1 if r[-2] <= 0 < r[-1] else -1 if r[-2] >= 0 > r[-1] else 0


def t_macd_cross(s, p):
    line, sig, _ = macd(s.c, p["fast"], p["mid"], 9)
    return 1 if _x_up(line, sig) else -1 if _x_dn(line, sig) else 0


def t_macd_hist_flip(s, p):
    _, _, hist = macd(s.c, p["fast"], p["mid"], 9)
    return 1 if hist[-2] <= 0 < hist[-1] else -1 if hist[-2] >= 0 > hist[-1] else 0


def t_macd_zero(s, p):
    line, _, _ = macd(s.c, p["fast"], p["mid"], 9)
    return 1 if line[-2] <= 0 < line[-1] else -1 if line[-2] >= 0 > line[-1] else 0


def t_macd_divergence(s, p):
    n = p["mid"]
    if len(s) < n + 2:
        return 0
    _, _, hist = macd(s.c, p["fast"], p["mid"], 9)
    if s.l[-1] < min(s.l[-n:-1]) and hist[-1] > min(hist[-n:-1]):
        return 1
    if s.h[-1] > max(s.h[-n:-1]) and hist[-1] < max(hist[-n:-1]):
        return -1
    return 0


def t_bb_squeeze_break(s, p):
    n = p["mid"]
    m, sd = sma(s.c, n), stdev(s.c, n)
    w = [2 * sd[i] / max(m[i], 1e-9) for i in range(len(s))]
    if len(w) < n or w[-2] > min(w[-n:]) * 1.2:
        return 0
    if s.c[-1] > m[-1] + 2 * sd[-1]:
        return 1
    if s.c[-1] < m[-1] - 2 * sd[-1]:
        return -1
    return 0


def t_bb_mean_revert(s, p):
    n = p["mid"]
    m, sd = sma(s.c, n), stdev(s.c, n)
    if s.l[-1] <= m[-1] - 2 * sd[-1] and s.c[-1] > s.o[-1]:
        return 1
    if s.h[-1] >= m[-1] + 2 * sd[-1] and s.c[-1] < s.o[-1]:
        return -1
    return 0


def t_bb_percent_b(s, p):
    n = p["mid"]
    m, sd = sma(s.c, n), stdev(s.c, n)
    lo, hi = m[-1] - 2 * sd[-1], m[-1] + 2 * sd[-1]
    if hi == lo:
        return 0
    b = (s.c[-1] - lo) / (hi - lo)
    return 1 if b > 1.0 else -1 if b < 0.0 else 0


def t_keltner_break(s, p):
    n = p["mid"]
    e, a = ema(s.c, n), atr(s, n)
    if s.c[-1] > e[-1] + 2 * a[-1] and s.c[-2] <= e[-2] + 2 * a[-2]:
        return 1
    if s.c[-1] < e[-1] - 2 * a[-1] and s.c[-2] >= e[-2] - 2 * a[-2]:
        return -1
    return 0


def t_donchian_fast(s, p):
    n = p["mid"]
    if len(s) < n + 1:
        return 0
    if s.c[-1] > max(s.h[-n - 1:-1]):
        return 1
    if s.c[-1] < min(s.l[-n - 1:-1]):
        return -1
    return 0


def t_donchian_slow(s, p):
    n = p["slow"]
    if len(s) < n + 1:
        return 0
    if s.c[-1] > max(s.h[-n - 1:-1]):
        return 1
    if s.c[-1] < min(s.l[-n - 1:-1]):
        return -1
    return 0


def t_atr_expansion(s, p):
    a = atr(s, p["mid"])
    if len(a) < 2 or a[-2] <= 0:
        return 0
    if _rng(s, len(s) - 1) < 1.5 * a[-2]:
        return 0
    return 1 if s.c[-1] > s.o[-1] else -1


def t_ttm_squeeze(s, p):
    n = p["mid"]
    m, sd, a = sma(s.c, n), stdev(s.c, n), atr(s, n)
    squeezed = 2 * sd[-2] < 1.5 * a[-2]
    if not squeezed:
        return 0
    return 1 if s.c[-1] > m[-1] else -1 if s.c[-1] < m[-1] else 0


def t_supertrend_flip(s, p):
    d = supertrend(s, p["mid"], 3.0)
    return 0 if len(d) < 2 or d[-1] == d[-2] else d[-1]


def t_adx_di_cross(s, p):
    a, pdi, ndi = adx_di(s, p["mid"])
    if a[-1] < 25:
        return 0
    return 1 if _x_up(pdi, ndi) else -1 if _x_dn(pdi, ndi) else 0


def t_psar_flip(s, p):
    d = psar(s)
    return 0 if len(d) < 2 or d[-1] == d[-2] else d[-1]


def t_aroon_cross(s, p):
    up, dn = aroon(s, p["mid"])
    return 1 if _x_up(up, dn) else -1 if _x_dn(up, dn) else 0


def t_engulfing(s, p):
    if len(s) < 2:
        return 0
    if s.c[-1] > s.o[-1] and s.c[-2] < s.o[-2] and s.c[-1] > s.o[-2] and s.o[-1] < s.c[-2]:
        return 1
    if s.c[-1] < s.o[-1] and s.c[-2] > s.o[-2] and s.c[-1] < s.o[-2] and s.o[-1] > s.c[-2]:
        return -1
    return 0


def t_hammer_star(s, p):
    i = len(s) - 1
    body, rng = _body(s, i), _rng(s, i)
    if body > 0.35 * rng:
        return 0
    lower = min(s.o[i], s.c[i]) - s.l[i]
    upper = s.h[i] - max(s.o[i], s.c[i])
    if lower > 2 * body and lower > 2 * upper:
        return 1
    if upper > 2 * body and upper > 2 * lower:
        return -1
    return 0


def t_doji_reversal(s, p):
    i = len(s) - 1
    if _body(s, i) > 0.1 * _rng(s, i) or len(s) < p["fast"] + 1:
        return 0
    if s.c[i] <= min(s.c[-p["fast"]:]):
        return 1
    if s.c[i] >= max(s.c[-p["fast"]:]):
        return -1
    return 0


def t_marubozu(s, p):
    i = len(s) - 1
    if _body(s, i) < 0.9 * _rng(s, i):
        return 0
    return 1 if s.c[i] > s.o[i] else -1


def t_inside_bar_break(s, p):
    if len(s) < 3:
        return 0
    inside = s.h[-2] < s.h[-3] and s.l[-2] > s.l[-3]
    if not inside:
        return 0
    return 1 if s.c[-1] > s.h[-2] else -1 if s.c[-1] < s.l[-2] else 0


def t_outside_bar(s, p):
    if len(s) < 2:
        return 0
    if not (s.h[-1] > s.h[-2] and s.l[-1] < s.l[-2]):
        return 0
    return 1 if s.c[-1] > s.o[-1] else -1


def t_three_soldiers(s, p):
    if len(s) < 3:
        return 0
    up = all(s.c[-i] > s.o[-i] for i in (1, 2, 3)) and s.c[-1] > s.c[-2] > s.c[-3]
    dn = all(s.c[-i] < s.o[-i] for i in (1, 2, 3)) and s.c[-1] < s.c[-2] < s.c[-3]
    return 1 if up else -1 if dn else 0


def t_star_pattern(s, p):
    if len(s) < 3:
        return 0
    small = _body(s, len(s) - 2) < 0.3 * _body(s, len(s) - 3) if _body(s, len(s) - 3) else False
    if not small:
        return 0
    if s.c[-3] < s.o[-3] and s.c[-1] > s.o[-1] and s.c[-1] > (s.o[-3] + s.c[-3]) / 2:
        return 1
    if s.c[-3] > s.o[-3] and s.c[-1] < s.o[-1] and s.c[-1] < (s.o[-3] + s.c[-3]) / 2:
        return -1
    return 0


def t_pin_bar_level(s, p):
    n = p["mid"]
    if len(s) < n:
        return 0
    i = len(s) - 1
    lower = min(s.o[i], s.c[i]) - s.l[i]
    upper = s.h[i] - max(s.o[i], s.c[i])
    if lower > 0.6 * _rng(s, i) and s.l[i] <= min(s.l[-n:]):
        return 1
    if upper > 0.6 * _rng(s, i) and s.h[i] >= max(s.h[-n:]):
        return -1
    return 0


def t_heikin_flip(s, p):
    ho, hc = heikin(s)
    if len(hc) < 3:
        return 0
    now, prev = hc[-1] > ho[-1], hc[-2] > ho[-2]
    return 0 if now == prev else (1 if now else -1)


def t_open_range_break(s, p):
    n = p["orb"]
    if len(s) < n + 1:
        return 0
    hi, lo = max(s.h[:n]), min(s.l[:n])
    if s.c[-1] > hi and s.c[-2] <= hi:
        return 1
    if s.c[-1] < lo and s.c[-2] >= lo:
        return -1
    return 0


def t_prev_extreme_break(s, p):
    n = p["session"]
    if len(s) < n + 2:
        return 0
    hi, lo = max(s.h[-n - 1:-1]), min(s.l[-n - 1:-1])
    if s.c[-1] > hi and s.c[-2] <= hi:
        return 1
    if s.c[-1] < lo and s.c[-2] >= lo:
        return -1
    return 0


def t_pivot_break(s, p):
    n = p["session"]
    if len(s) < n + 1:
        return 0
    hi, lo, cl = max(s.h[-n - 1:-1]), min(s.l[-n - 1:-1]), s.c[-2]
    pivot = (hi + lo + cl) / 3
    r1, s1 = 2 * pivot - lo, 2 * pivot - hi
    if s.c[-1] > r1 and s.c[-2] <= r1:
        return 1
    if s.c[-1] < s1 and s.c[-2] >= s1:
        return -1
    return 0


def t_round_number(s, p):
    step = 50.0  # NIFTY strikes are 50 apart; these are where option flow clusters
    lvl = round(s.c[-1] / step) * step
    if s.c[-2] < lvl <= s.c[-1]:
        return 1
    if s.c[-2] > lvl >= s.c[-1]:
        return -1
    return 0


def t_structure_hh_hl(s, p):
    n = p["fast"]
    if len(s) < 2 * n:
        return 0
    hi_now, hi_prev = max(s.h[-n:]), max(s.h[-2 * n:-n])
    lo_now, lo_prev = min(s.l[-n:]), min(s.l[-2 * n:-n])
    if hi_now > hi_prev and lo_now > lo_prev:
        return 1
    if hi_now < hi_prev and lo_now < lo_prev:
        return -1
    return 0


def t_fib_retrace(s, p):
    n = p["mid"]
    if len(s) < n:
        return 0
    hi, lo = max(s.h[-n:]), min(s.l[-n:])
    if hi == lo:
        return 0
    up_618, dn_618 = hi - 0.618 * (hi - lo), lo + 0.618 * (hi - lo)
    if s.l[-1] <= up_618 and s.c[-1] > up_618 and s.c[-1] > s.o[-1]:
        return 1
    if s.h[-1] >= dn_618 and s.c[-1] < dn_618 and s.c[-1] < s.o[-1]:
        return -1
    return 0


def t_gap_fade(s, p):
    if len(s) < 2:
        return 0
    gap = (s.o[-1] - s.c[-2]) / max(s.c[-2], 1e-9)
    if gap > 0.002 and s.c[-1] < s.o[-1]:
        return -1
    if gap < -0.002 and s.c[-1] > s.o[-1]:
        return 1
    return 0


def t_vwap_reclaim(s, p):
    w = vwap(s)
    return 1 if _x_up(s.c, w) else -1 if _x_dn(s.c, w) else 0


TEMPLATES: list[tuple[str, str, Callable]] = [
    ("EMA Fast Cross", "trend", t_ema_fast_cross),
    ("EMA Slow Cross", "trend", t_ema_slow_cross),
    ("SMA Cross", "trend", t_sma_cross),
    ("Triple EMA Stack", "trend", t_triple_ema_stack),
    ("EMA Ribbon Squeeze", "trend", t_ema_ribbon_squeeze),
    ("Trend Pullback to EMA", "trend", t_trend_pullback),
    ("WMA Cross", "trend", t_wma_cross),
    ("DEMA Cross", "trend", t_dema_cross),
    ("RSI Oversold Bounce", "mean_reversion", t_rsi_oversold),
    ("RSI Overbought Fade", "mean_reversion", t_rsi_overbought),
    ("RSI 50 Momentum Cross", "momentum", t_rsi_50_cross),
    ("RSI Divergence", "mean_reversion", t_rsi_divergence),
    ("Stochastic Extreme Cross", "mean_reversion", t_stoch_cross),
    ("CCI Zero Cross", "momentum", t_cci_zero),
    ("Williams %R Reversal", "mean_reversion", t_williams_r),
    ("ROC Sign Flip", "momentum", t_roc_flip),
    ("MACD Signal Cross", "momentum", t_macd_cross),
    ("MACD Histogram Flip", "momentum", t_macd_hist_flip),
    ("MACD Zero Line", "momentum", t_macd_zero),
    ("MACD Divergence", "mean_reversion", t_macd_divergence),
    ("Bollinger Squeeze Break", "breakout", t_bb_squeeze_break),
    ("Bollinger Mean Revert", "mean_reversion", t_bb_mean_revert),
    ("Bollinger %B Extreme", "breakout", t_bb_percent_b),
    ("Keltner Breakout", "breakout", t_keltner_break),
    ("Donchian Fast Break", "breakout", t_donchian_fast),
    ("Donchian Slow Break", "breakout", t_donchian_slow),
    ("ATR Expansion Thrust", "breakout", t_atr_expansion),
    ("TTM Squeeze Release", "breakout", t_ttm_squeeze),
    ("Supertrend Flip", "trend", t_supertrend_flip),
    ("ADX + DI Cross", "trend", t_adx_di_cross),
    ("Parabolic SAR Flip", "trend", t_psar_flip),
    ("Aroon Cross", "trend", t_aroon_cross),
    ("Engulfing Candle", "pattern", t_engulfing),
    ("Hammer / Shooting Star", "pattern", t_hammer_star),
    ("Doji Reversal", "pattern", t_doji_reversal),
    ("Marubozu Continuation", "pattern", t_marubozu),
    ("Inside Bar Breakout", "pattern", t_inside_bar_break),
    ("Outside Bar Reversal", "pattern", t_outside_bar),
    ("Three Soldiers / Crows", "pattern", t_three_soldiers),
    ("Morning / Evening Star", "pattern", t_star_pattern),
    ("Pin Bar at Extreme", "pattern", t_pin_bar_level),
    ("Heikin Ashi Flip", "pattern", t_heikin_flip),
    ("Opening Range Breakout", "breakout", t_open_range_break),
    ("Prior Extreme Breakout", "breakout", t_prev_extreme_break),
    ("Pivot R1/S1 Break", "breakout", t_pivot_break),
    ("Round Number Break", "breakout", t_round_number),
    ("HH/HL Structure Shift", "trend", t_structure_hh_hl),
    ("Fibonacci 61.8% Bounce", "mean_reversion", t_fib_retrace),
    ("Gap Fade", "mean_reversion", t_gap_fade),
    ("VWAP Reclaim", "momentum", t_vwap_reclaim),
    ("Head & Shoulders", "chart_pattern", t_head_shoulders),
    ("Double Top / Bottom", "chart_pattern", t_double_top_bottom),
    ("Triple Top / Bottom", "chart_pattern", t_triple_top_bottom),
    ("Ascending Triangle", "chart_pattern", t_ascending_triangle),
    ("Descending Triangle", "chart_pattern", t_descending_triangle),
    ("Symmetrical Triangle", "chart_pattern", t_symmetrical_triangle),
    ("Rising / Falling Wedge", "chart_pattern", t_wedge),
    ("Bull / Bear Flag", "chart_pattern", t_flag),
    ("Pennant", "chart_pattern", t_pennant),
    ("Cup & Handle", "chart_pattern", t_cup_handle),
    ("Rounding Top / Bottom", "chart_pattern", t_rounding),
    ("Diamond", "chart_pattern", t_diamond),
    ("Broadening Formation", "chart_pattern", t_broadening),
]
# A MINIMUM, not an exact count: an exact count makes adding a template an outage.
assert len(TEMPLATES) >= 63, f"templates shrank to {len(TEMPLATES)}"


# ── timeframes ─────────────────────────────────────────────────────────────────
#
# `style` decides how the position is HELD, and it follows the candle rather than being
# chosen separately: a 1-minute signal that is held for days is not the edge that was
# tested. target/stop are on OPTION PREMIUM, which moves several times faster than the
# index — a 0.3% index move can be 10% of an ATM premium — so these are much wider than
# equity percentages and deliberately so.


@dataclass(frozen=True)
class Timeframe:
    key: str
    label: str
    resolution: str        # Angel interval key, or the source for an aggregate
    aggregate: int         # >1 = build these bars by combining `resolution` bars
    style: str             # scalping | intraday | swing
    lookback_days: int
    target_pct: float      # on option premium
    stop_pct: float
    max_hold_bars: int
    profile: dict


def _profile(fast, mid, slow, trend, orb, session, pivot=3, pole=10, flag=8, cup=40):
    """`pivot` is the fractal half-width that defines a swing point, and `cup`/`pole`/
    `flag` are the windows the geometric patterns measure over. They scale with the
    timeframe for the same reason the moving averages do: a 40-bar cup is half a session
    on 5-minute candles and two months on daily ones."""
    return {"fast": fast, "mid": mid, "slow": slow, "trend": trend,
            "rsi": 14, "orb": orb, "session": session,
            "pivot": pivot, "pole": pole, "flag": flag, "cup": cup}


TIMEFRAMES: list[Timeframe] = [
    Timeframe("1m", "1 minute", "1", 1, "scalping", 5, 25, 15, 15,
              _profile(5, 9, 21, 50, 5, 375, pivot=6, pole=20, flag=15, cup=90)),
    Timeframe("5m", "5 minutes", "5", 1, "scalping", 15, 30, 18, 12,
              _profile(5, 9, 21, 50, 3, 75, pivot=5, pole=15, flag=12, cup=70)),
    Timeframe("10m", "10 minutes", "10", 1, "intraday", 30, 35, 20, 10,
              _profile(5, 10, 20, 50, 3, 38, pivot=4, pole=12, flag=10, cup=55)),
    Timeframe("15m", "15 minutes", "15", 1, "intraday", 45, 40, 22, 8,
              _profile(5, 10, 20, 50, 2, 25, pivot=4, pole=10, flag=8, cup=45)),
    Timeframe("30m", "30 minutes", "30", 1, "intraday", 90, 45, 25, 6,
              _profile(5, 9, 21, 50, 2, 13, pivot=3, pole=10, flag=8, cup=40)),
    Timeframe("1h", "1 hour", "60", 1, "intraday", 180, 50, 28, 5,
              _profile(5, 9, 21, 50, 1, 7, pivot=3, pole=8, flag=6, cup=35)),
    # Angel has no 4-hour interval; these bars are aggregated from 1-hour candles.
    Timeframe("4h", "4 hours", "60", 4, "swing", 365, 60, 32, 4,
              _profile(3, 6, 12, 30, 1, 2, pivot=2, pole=6, flag=5, cup=25)),
    Timeframe("1d", "1 day", "D", 1, "swing", 900, 70, 35, 5,
              _profile(5, 10, 20, 50, 1, 1, pivot=3, pole=8, flag=6, cup=35)),
]
TIMEFRAME_BY_KEY = {t.key: t for t in TIMEFRAMES}


@dataclass(frozen=True)
class ScalpStrategy:
    strategy_id: str
    name: str
    template: str
    family: str
    timeframe: str
    style: str
    fn: Callable


def build_catalog() -> list[ScalpStrategy]:
    out: list[ScalpStrategy] = []
    for tf in TIMEFRAMES:
        for i, (name, family, fn) in enumerate(TEMPLATES, start=1):
            out.append(ScalpStrategy(
                strategy_id=f"ns_{tf.key}_{i:02d}",
                name=f"{name} · {tf.label}",
                template=name, family=family, timeframe=tf.key, style=tf.style, fn=fn,
            ))
    return out


CATALOG: list[ScalpStrategy] = build_catalog()
CATALOG_BY_ID = {s.strategy_id: s for s in CATALOG}


def evaluate(strategy: ScalpStrategy, series: Series) -> int:
    """Direction for this strategy on the latest CLOSED bar, or 0. A template that raises
    on thin history is treated as 'no signal' — an indicator that cannot be computed is
    not a reason to take a trade."""
    tf = TIMEFRAME_BY_KEY[strategy.timeframe]
    if len(series) < 30:
        return 0
    try:
        d = strategy.fn(series, tf.profile)
    except (IndexError, ValueError, ZeroDivisionError):
        return 0
    return d if d in (1, -1) else 0
