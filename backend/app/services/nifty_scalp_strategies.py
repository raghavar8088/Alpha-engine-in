"""Strategy library for the NIFTY 50 Option Scalping desk.

FIFTY templates, each one a rule over CANDLES and INDICATORS — no fundamental, news or
sentiment inputs — instantiated on every timeframe from 1 minute to 1 day. 50 x 8 = 400
strategies, each with its own Rs2,00,000 book.

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
]
assert len(TEMPLATES) == 50, f"expected 50 templates, got {len(TEMPLATES)}"


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


def _profile(fast, mid, slow, trend, orb, session):
    return {"fast": fast, "mid": mid, "slow": slow, "trend": trend,
            "rsi": 14, "orb": orb, "session": session}


TIMEFRAMES: list[Timeframe] = [
    Timeframe("1m", "1 minute", "1", 1, "scalping", 5, 25, 15, 15,
              _profile(5, 9, 21, 50, 5, 375)),
    Timeframe("5m", "5 minutes", "5", 1, "scalping", 15, 30, 18, 12,
              _profile(5, 9, 21, 50, 3, 75)),
    Timeframe("10m", "10 minutes", "10", 1, "intraday", 30, 35, 20, 10,
              _profile(5, 10, 20, 50, 3, 38)),
    Timeframe("15m", "15 minutes", "15", 1, "intraday", 45, 40, 22, 8,
              _profile(5, 10, 20, 50, 2, 25)),
    Timeframe("30m", "30 minutes", "30", 1, "intraday", 90, 45, 25, 6,
              _profile(5, 9, 21, 50, 2, 13)),
    Timeframe("1h", "1 hour", "60", 1, "intraday", 180, 50, 28, 5,
              _profile(5, 9, 21, 50, 1, 7)),
    # Angel has no 4-hour interval; these bars are aggregated from 1-hour candles.
    Timeframe("4h", "4 hours", "60", 4, "swing", 365, 60, 32, 4,
              _profile(3, 6, 12, 30, 1, 2)),
    Timeframe("1d", "1 day", "D", 1, "swing", 900, 70, 35, 5,
              _profile(5, 10, 20, 50, 1, 1)),
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
