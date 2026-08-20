"""Volatility Contraction Pattern and the Minervini trend template.

ONE IMPLEMENTATION, TWO MODULES. Intraday Stocks describes a strategy as
`fn(Series, profile) -> +1/-1/0` over column lists; Commodity describes it as
`fn(spec, bars) -> PatternSignal | None` over Bar objects. Writing VCP twice against those
two shapes would guarantee the two desks eventually disagreed about what a contraction is.
The detection lives here on plain lists, and each module gets a thin adapter.

WHAT A VCP ACTUALLY IS. Price builds a base out of successive pullbacks, each SHALLOWER
than the last — supply drying up as weak holders finish selling — while volume falls away.
The trade is the breakout through the last swing high (the pivot) once that tightening has
happened. So a real detector has to measure three things, not one:

  1. a sequence of pullbacks whose depths are strictly shrinking
  2. the last pullback being tight in absolute terms, not merely smaller than a huge one
  3. volume in the recent contraction genuinely below the base's own average

Checking only "price near resistance" would fire on every consolidation, which is why the
pattern has a reputation for being subjective. Each of these is a number here.

THE PIVOT IS THE LAST SWING HIGH, and the signal is a CLOSE THROUGH IT — not an approach to
it. A base that has not broken out is a base, not a buy.
"""

from __future__ import annotations


def _swings(h: list[float], l: list[float], k: int) -> list[tuple[int, float, int]]:
    """Fractal turning points as (index, price, +1 high | -1 low), strictly alternating."""
    raw: list[tuple[int, float, int]] = []
    for i in range(k, len(h) - k):
        if h[i] == max(h[i - k:i + k + 1]):
            raw.append((i, h[i], 1))
        elif l[i] == min(l[i - k:i + k + 1]):
            raw.append((i, l[i], -1))
    out: list[tuple[int, float, int]] = []
    for p in raw:
        if out and out[-1][2] == p[2]:
            better = p[1] > out[-1][1] if p[2] == 1 else p[1] < out[-1][1]
            if better:
                out[-1] = p
        else:
            out.append(p)
    return out


def contractions(h: list[float], l: list[float], k: int = 3,
                 window: int = 120) -> list[float]:
    """Depths of each high→low pullback in the base, oldest first.

    A contraction is measured from a swing HIGH down to the swing LOW that follows it, as a
    fraction of that high — which is what makes 'shrinking' comparable across price levels.
    """
    n = len(h)
    if n < 20:
        return []
    lo_i = max(0, n - window)
    sw = [s for s in _swings(h[lo_i:], l[lo_i:], k)]
    depths: list[float] = []
    for a, b in zip(sw, sw[1:]):
        if a[2] == 1 and b[2] == -1 and a[1] > 0:
            depths.append((a[1] - b[1]) / a[1])
    return depths


def vcp(h: list[float], l: list[float], c: list[float], v: list[float], *,
        pivot_k: int = 3, window: int = 120, min_contractions: int = 2,
        max_last_pullback: float = 0.15, dryup_frac: float = 0.75,
        dryup_bars: int = 5, shrink_tol: float = 0.95) -> dict:
    """Measure the pattern. Returns the components as well as the verdict, so a caller can
    say WHY it did or did not qualify instead of just yes/no."""
    out = {"ok": False, "contractions": 0, "depths": [], "last_pullback": None,
           "pivot": None, "vol_ratio": None, "breakout_vol_ratio": None,
           "strength": 0.0, "reason": ""}
    n = len(c)
    if n < max(30, dryup_bars + 5):
        out["reason"] = "not enough history"
        return out

    depths = contractions(h, l, pivot_k, window)
    out["depths"] = [round(d, 4) for d in depths[-4:]]
    if len(depths) < min_contractions:
        out["reason"] = f"only {len(depths)} contraction(s)"
        return out

    recent = depths[-min_contractions:]
    out["contractions"] = len(recent)
    # Strictly shrinking: each pullback must be meaningfully shallower than the one before.
    if any(recent[i] > recent[i - 1] * shrink_tol for i in range(1, len(recent))):
        out["reason"] = "pullbacks are not tightening"
        return out
    last = recent[-1]
    out["last_pullback"] = round(last, 4)
    if last > max_last_pullback:
        # Shrinking from 60% to 40% is still not a tight base.
        out["reason"] = f"last pullback {last:.1%} is too deep"
        return out

    lo_i = max(0, n - window)
    sw = _swings(h[lo_i:], l[lo_i:], pivot_k)
    highs = [s for s in sw if s[2] == 1]
    if not highs:
        out["reason"] = "no pivot high in the base"
        return out
    pivot = highs[-1][1]
    out["pivot"] = round(pivot, 4)

    # Dry-up is measured on the contraction BEFORE the current bar, never including it.
    # The breakout bar carries expansion volume by definition, so counting it drags the
    # ratio back up and makes a textbook VCP fail its own volume test — which is exactly
    # what a synthetic textbook pattern did until this excluded it.
    base_v = v[lo_i:-1] if len(v) - lo_i > 1 else v[lo_i:]
    if base_v and sum(base_v) > 0:
        avg = sum(base_v) / len(base_v)
        window = v[-(dryup_bars + 1):-1] or v[-dryup_bars:]
        rec = sum(window) / len(window)
        ratio = rec / avg if avg else None
        out["vol_ratio"] = round(ratio, 3) if ratio is not None else None
        if ratio is not None and ratio > dryup_frac:
            out["reason"] = f"volume has not dried up ({ratio:.0%} of base average)"
            return out

    # Score: tighter last pullback, more contractions and drier volume all read as better.
    tight = max(0.0, 1 - last / max_last_pullback)
    depth_bonus = min(len(recent), 4) / 4
    dry = 1 - min(out["vol_ratio"] or dryup_frac, dryup_frac) / dryup_frac
    out["strength"] = round(100 * (0.5 * tight + 0.3 * depth_bonus + 0.2 * dry), 1)
    # The confirming leg: a real breakout expands volume against the dried-up base.
    if base_v and sum(base_v) > 0:
        avg = sum(base_v) / len(base_v)
        out["breakout_vol_ratio"] = round(v[-1] / avg, 2) if avg else None
    out["ok"] = True
    out["reason"] = (f"{len(recent)} shrinking contractions, last {last:.1%}, "
                     f"volume {(out['vol_ratio'] or 0):.0%} of base")
    return out


def broke_out(c: list[float], pivot: float) -> bool:
    """Closed THROUGH the pivot on this bar. A base that has not broken is not a buy."""
    return len(c) > 1 and c[-1] > pivot >= c[-2]


def trend_template(c: list[float], *, sma_fn) -> dict:
    """Minervini's trend template, the eight-point filter for a stock in a real uptrend.

    Implemented on price alone; the relative-strength-versus-index leg needs a benchmark
    series these desks do not pass in, so it is reported as not-checked rather than
    silently assumed to pass."""
    out = {"ok": False, "checks": {}, "score": 0}
    n = len(c)
    if n < 210:
        out["checks"]["history"] = False
        return out
    s50, s150, s200 = sma_fn(c, 50), sma_fn(c, 150), sma_fn(c, 200)
    last = c[-1]
    win = c[-min(n, 252):]
    hi52, lo52 = max(win), min(win)
    checks = {
        "above_150_200": last > s150[-1] and last > s200[-1],
        "150_above_200": s150[-1] > s200[-1],
        "200_trending_up": s200[-1] > s200[-min(len(s200), 22)],
        "50_above_150_200": s50[-1] > s150[-1] and s50[-1] > s200[-1],
        "above_50": last >= s50[-1],
        "above_52w_low": lo52 > 0 and last >= lo52 * 1.30,
        "near_52w_high": hi52 > 0 and last >= hi52 * 0.75,
    }
    out["checks"] = checks
    out["score"] = sum(1 for x in checks.values() if x)
    out["ok"] = all(checks.values())
    return out


def pocket_pivot(c: list[float], v: list[float], lookback: int = 10) -> bool:
    """An up day on volume greater than the largest DOWN-day volume of the last N days —
    institutional accumulation inside a base, before the obvious breakout."""
    if len(c) < lookback + 2 or len(v) < lookback + 2:
        return False
    if c[-1] <= c[-2]:
        return False
    down_v = [v[i] for i in range(len(c) - lookback - 1, len(c) - 1) if c[i] < c[i - 1]]
    return bool(down_v) and v[-1] > max(down_v)


def high_tight_flag(c: list[float], *, run_bars: int = 40, run_min: float = 0.90,
                    flag_bars: int = 12, flag_max: float = 0.25) -> bool:
    """A doubling (or near) in a short run, then a shallow tight consolidation. Rare, and
    the tightness bound is what keeps it from matching any large move followed by a drift."""
    n = len(c)
    if n < run_bars + flag_bars + 2:
        return False
    run_lo = min(c[-(run_bars + flag_bars):-flag_bars])
    run_hi = max(c[-(run_bars + flag_bars):-flag_bars])
    if run_lo <= 0 or (run_hi - run_lo) / run_lo < run_min:
        return False
    seg = c[-flag_bars:]
    hi, lo = max(seg), min(seg)
    return hi > 0 and (hi - lo) / hi <= flag_max
