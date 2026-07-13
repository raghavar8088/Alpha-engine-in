"""Small pure-python indicator helpers shared by strategies. Deliberately dependency-free
(no pandas/numpy) — strategy modules must stay importable everywhere, including the
backend API process that only lists them.

Alignment convention: every function returns a list the SAME length as its input, with
the warm-up region padded by repeating the first computed value. Strategies only read
the last one or two elements, so the padding never influences signals past warmup."""

import math

from tradingai_shared.domain import Bar


def ema(values: list[float], period: int) -> list[float]:
    """Standard EMA seeded with the SMA of the first `period` values."""
    if len(values) < period:
        raise ValueError(f"need at least {period} values, got {len(values)}")
    seed = sum(values[:period]) / period
    k = 2 / (period + 1)
    out = [seed] * period
    prev = seed
    for value in values[period:]:
        prev = value * k + prev * (1 - k)
        out.append(prev)
    return out


def sma(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        raise ValueError(f"need at least {period} values, got {len(values)}")
    out = []
    window_sum = sum(values[:period])
    seed = window_sum / period
    out.extend([seed] * period)
    for i in range(period, len(values)):
        window_sum += values[i] - values[i - period]
        out.append(window_sum / period)
    return out


def stdev(values: list[float], period: int) -> list[float]:
    """Rolling population standard deviation (matches classic Bollinger bands)."""
    if len(values) < period:
        raise ValueError(f"need at least {period} values, got {len(values)}")
    means = sma(values, period)
    out = []
    for i in range(len(values)):
        j = max(0, i - period + 1)
        window = values[j : i + 1]
        m = means[i]
        out.append(math.sqrt(sum((v - m) ** 2 for v in window) / len(window)))
    return out


def rsi(values: list[float], period: int) -> list[float]:
    """Wilder's RSI."""
    if len(values) < period + 1:
        raise ValueError(f"need at least {period + 1} values, got {len(values)}")
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def to_rsi(g: float, l: float) -> float:
        if l == 0:
            return 100.0
        return 100.0 - 100.0 / (1 + g / l)

    seed = to_rsi(avg_gain, avg_loss)
    out = [seed] * (period + 1)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out.append(to_rsi(avg_gain, avg_loss))
    return out


def atr(bars: list[Bar], period: int) -> list[float]:
    """Wilder's Average True Range."""
    if len(bars) < period + 1:
        raise ValueError(f"need at least {period + 1} bars, got {len(bars)}")
    trs = []
    for i in range(1, len(bars)):
        b, prev_close = bars[i], bars[i - 1].close
        trs.append(max(b.high - b.low, abs(b.high - prev_close), abs(b.low - prev_close)))
    seed = sum(trs[:period]) / period
    out = [seed] * (period + 1)
    prev = seed
    for tr in trs[period:]:
        prev = (prev * (period - 1) + tr) / period
        out.append(prev)
    return out


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float], list[float]]:
    """Returns (macd_line, signal_line), both aligned to `values`."""
    if len(values) < slow + signal:
        raise ValueError(f"need at least {slow + signal} values, got {len(values)}")
    line = [f - s for f, s in zip(ema(values, fast), ema(values, slow))]
    sig = ema(line, signal)
    return line, sig


def roc(values: list[float], period: int) -> list[float]:
    """Rate of change, percent."""
    if len(values) < period + 1:
        raise ValueError(f"need at least {period + 1} values, got {len(values)}")
    out = []
    for i in range(len(values)):
        j = max(0, i - period)
        base = values[j]
        out.append((values[i] - base) / base * 100 if base else 0.0)
    return out


def donchian(bars: list[Bar], period: int) -> tuple[list[float], list[float]]:
    """Rolling (highest high, lowest low) over `period` bars, EXCLUDING the current bar
    — a breakout compares today's close against yesterday's channel."""
    if len(bars) < period + 1:
        raise ValueError(f"need at least {period + 1} bars, got {len(bars)}")
    highs, lows = [], []
    for i in range(len(bars)):
        j = max(0, i - period)
        window = bars[j:i] or bars[:1]
        highs.append(max(b.high for b in window))
        lows.append(min(b.low for b in window))
    return highs, lows


def stochastic(bars: list[Bar], k_period: int = 14, d_period: int = 3) -> tuple[list[float], list[float]]:
    """Returns (%K, %D) aligned to bars."""
    if len(bars) < k_period + d_period:
        raise ValueError(f"need at least {k_period + d_period} bars, got {len(bars)}")
    ks = []
    for i in range(len(bars)):
        j = max(0, i - k_period + 1)
        window = bars[j : i + 1]
        hi = max(b.high for b in window)
        lo = min(b.low for b in window)
        ks.append(50.0 if hi == lo else (bars[i].close - lo) / (hi - lo) * 100)
    return ks, sma(ks, d_period)


def adx(bars: list[Bar], period: int = 14) -> tuple[list[float], list[float], list[float]]:
    """Wilder's ADX. Returns (adx, +DI, -DI) aligned to bars."""
    n = len(bars)
    if n < 2 * period + 1:
        raise ValueError(f"need at least {2 * period + 1} bars, got {n}")
    trs, plus_dm, minus_dm = [], [], []
    for i in range(1, n):
        b, prev = bars[i], bars[i - 1]
        trs.append(max(b.high - b.low, abs(b.high - prev.close), abs(b.low - prev.close)))
        up, down = b.high - prev.high, prev.low - b.low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)

    def wilder_smooth(series: list[float]) -> list[float]:
        smoothed = [sum(series[:period])]
        for value in series[period:]:
            smoothed.append(smoothed[-1] - smoothed[-1] / period + value)
        return smoothed

    atr_s, pdm_s, mdm_s = wilder_smooth(trs), wilder_smooth(plus_dm), wilder_smooth(minus_dm)
    plus_di = [100 * p / a if a else 0.0 for p, a in zip(pdm_s, atr_s)]
    minus_di = [100 * m / a if a else 0.0 for m, a in zip(mdm_s, atr_s)]
    dxs = [
        100 * abs(p - m) / (p + m) if (p + m) else 0.0
        for p, m in zip(plus_di, minus_di)
    ]
    adx_vals = [sum(dxs[:period]) / period]
    for dx in dxs[period:]:
        adx_vals.append((adx_vals[-1] * (period - 1) + dx) / period)

    pad = n - len(adx_vals)
    pad_di = n - len(plus_di)
    return (
        [adx_vals[0]] * pad + adx_vals,
        [plus_di[0]] * pad_di + plus_di,
        [minus_di[0]] * pad_di + minus_di,
    )


def keltner(bars: list[Bar], period: int = 20, mult: float = 2.0) -> tuple[list[float], list[float], list[float]]:
    """Keltner channel: (upper, middle=EMA, lower) using ATR bands."""
    closes = [b.close for b in bars]
    mid = ema(closes, period)
    a = atr(bars, period)
    return (
        [m + mult * x for m, x in zip(mid, a)],
        mid,
        [m - mult * x for m, x in zip(mid, a)],
    )


def session_vwap(bars: list[Bar], session_key) -> list[float]:
    """Cumulative VWAP resetting per session (session_key(bar) groups bars, e.g. IST
    date). Bars with zero volume contribute nothing; a session with no volume yet
    falls back to typical price."""
    out = []
    key = None
    cum_pv = cum_v = 0.0
    for b in bars:
        k = session_key(b)
        if k != key:
            key, cum_pv, cum_v = k, 0.0, 0.0
        typical = (b.high + b.low + b.close) / 3
        cum_pv += typical * b.volume
        cum_v += b.volume
        out.append(cum_pv / cum_v if cum_v > 0 else typical)
    return out


def rolling_vwap(bars: list[Bar], period: int) -> list[float]:
    """N-bar rolling VWAP (daily-timeframe substitute for session VWAP)."""
    out = []
    for i in range(len(bars)):
        j = max(0, i - period + 1)
        window = bars[j : i + 1]
        vol = sum(b.volume for b in window)
        if vol > 0:
            out.append(sum((b.high + b.low + b.close) / 3 * b.volume for b in window) / vol)
        else:
            out.append((bars[i].high + bars[i].low + bars[i].close) / 3)
    return out


def zscore(values: list[float], period: int) -> list[float]:
    """Rolling z-score of the last value vs its window."""
    means = sma(values, period)
    sds = stdev(values, period)
    return [
        (v - m) / sd if sd > 1e-12 else 0.0
        for v, m, sd in zip(values, means, sds)
    ]


def ichimoku(bars: list[Bar], tenkan: int = 9, kijun: int = 26, senkou_b: int = 52) -> tuple[list[float], list[float], list[float], list[float]]:
    """Returns (tenkan, kijun, senkou_a, senkou_b) WITHOUT forward displacement —
    strategies compare price to the current cloud values directly."""
    if len(bars) < senkou_b:
        raise ValueError(f"need at least {senkou_b} bars, got {len(bars)}")

    def midline(period: int) -> list[float]:
        out = []
        for i in range(len(bars)):
            j = max(0, i - period + 1)
            window = bars[j : i + 1]
            out.append((max(b.high for b in window) + min(b.low for b in window)) / 2)
        return out

    t, k = midline(tenkan), midline(kijun)
    a = [(x + y) / 2 for x, y in zip(t, k)]
    return t, k, a, midline(senkou_b)


def prev_period_cpr(prev_high: float, prev_low: float, prev_close: float) -> tuple[float, float, float]:
    """Central Pivot Range from the previous period: (bottom, pivot, top)."""
    pivot = (prev_high + prev_low + prev_close) / 3
    bc = (prev_high + prev_low) / 2
    tc = 2 * pivot - bc
    return (min(bc, tc), pivot, max(bc, tc))


# --- additions for the extended option-buying library (strategies #101-160) ---


def psar(bars: list[Bar], af_step: float = 0.02, af_max: float = 0.2) -> list[int]:
    """Parabolic SAR direction per bar: +1 while SAR below price, -1 above."""
    n = len(bars)
    if n < 3:
        return [1] * n
    directions = [1]
    rising = True
    sar = bars[0].low
    ep = bars[0].high
    af = af_step
    for i in range(1, n):
        b = bars[i]
        sar = sar + af * (ep - sar)
        if rising:
            sar = min(sar, bars[i - 1].low, bars[i - 2].low if i >= 2 else bars[i - 1].low)
            if b.low < sar:
                rising, sar, ep, af = False, ep, b.low, af_step
            elif b.high > ep:
                ep, af = b.high, min(af + af_step, af_max)
        else:
            sar = max(sar, bars[i - 1].high, bars[i - 2].high if i >= 2 else bars[i - 1].high)
            if b.high > sar:
                rising, sar, ep, af = True, ep, b.high, af_step
            elif b.low < ep:
                ep, af = b.low, min(af + af_step, af_max)
        directions.append(1 if rising else -1)
    return directions


def wma(values: list[float], period: int) -> list[float]:
    """Linearly-weighted moving average (padded to input length)."""
    out = []
    denom = period * (period + 1) / 2
    for i in range(len(values)):
        if i + 1 < period:
            out.append(values[i])
            continue
        window = values[i - period + 1: i + 1]
        out.append(sum(v * (j + 1) for j, v in enumerate(window)) / denom)
    return out


def hull_ma(values: list[float], period: int = 16) -> list[float]:
    """Hull moving average: WMA(2*WMA(n/2) - WMA(n), sqrt(n))."""
    import math
    half = wma(values, max(2, period // 2))
    full = wma(values, period)
    diff = [2 * h - f for h, f in zip(half, full)]
    return wma(diff, max(2, int(math.sqrt(period))))


def dema(values: list[float], period: int) -> list[float]:
    e1 = ema(values, period)
    e2 = ema(e1, period)
    return [2 * a - b for a, b in zip(e1, e2)]


def tema(values: list[float], period: int) -> list[float]:
    e1 = ema(values, period)
    e2 = ema(e1, period)
    e3 = ema(e2, period)
    return [3 * a - 3 * b + c for a, b, c in zip(e1, e2, e3)]


def cci(bars: list[Bar], period: int = 20) -> list[float]:
    """Commodity Channel Index (padded)."""
    tps = [(b.high + b.low + b.close) / 3 for b in bars]
    out = []
    for i in range(len(tps)):
        if i + 1 < period:
            out.append(0.0)
            continue
        window = tps[i - period + 1: i + 1]
        mean = sum(window) / period
        mad = sum(abs(v - mean) for v in window) / period
        out.append((tps[i] - mean) / (0.015 * mad) if mad else 0.0)
    return out


def williams_r(bars: list[Bar], period: int = 14) -> list[float]:
    """Williams %R in [-100, 0] (padded with -50)."""
    out = []
    for i in range(len(bars)):
        if i + 1 < period:
            out.append(-50.0)
            continue
        window = bars[i - period + 1: i + 1]
        hh = max(b.high for b in window)
        ll = min(b.low for b in window)
        out.append(-100 * (hh - bars[i].close) / (hh - ll) if hh > ll else -50.0)
    return out


def trix(values: list[float], period: int = 15) -> list[float]:
    """TRIX: 1-bar ROC of triple-smoothed EMA, in percent (padded with 0)."""
    e3 = ema(ema(ema(values, period), period), period)
    out = [0.0]
    for i in range(1, len(e3)):
        out.append((e3[i] / e3[i - 1] - 1) * 100 if e3[i - 1] else 0.0)
    return out


def aroon(bars: list[Bar], period: int = 25) -> tuple[list[float], list[float]]:
    """(aroon_up, aroon_down) 0-100 (padded with 50)."""
    up, down = [], []
    for i in range(len(bars)):
        if i + 1 < period:
            up.append(50.0)
            down.append(50.0)
            continue
        window = bars[i - period + 1: i + 1]
        hi_idx = max(range(len(window)), key=lambda j: window[j].high)
        lo_idx = min(range(len(window)), key=lambda j: window[j].low)
        up.append(100 * (hi_idx + 1) / period)
        down.append(100 * (lo_idx + 1) / period)
    return up, down


def stoch_rsi(values: list[float], rsi_period: int = 14, stoch_period: int = 14) -> list[float]:
    """Stochastic RSI 0-100 (padded with 50)."""
    r = rsi(values, rsi_period)
    out = []
    for i in range(len(r)):
        if i + 1 < stoch_period:
            out.append(50.0)
            continue
        window = r[i - stoch_period + 1: i + 1]
        hi, lo = max(window), min(window)
        out.append(100 * (r[i] - lo) / (hi - lo) if hi > lo else 50.0)
    return out


def linreg_slope(values: list[float], period: int = 20) -> list[float]:
    """Least-squares slope of the last `period` values, per bar (padded with 0)."""
    out = []
    xs = list(range(period))
    x_mean = (period - 1) / 2
    denom = sum((x - x_mean) ** 2 for x in xs)
    for i in range(len(values)):
        if i + 1 < period:
            out.append(0.0)
            continue
        window = values[i - period + 1: i + 1]
        y_mean = sum(window) / period
        out.append(sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, window)) / denom)
    return out


def heikin_ashi(bars: list[Bar]) -> list[tuple[float, float]]:
    """(ha_open, ha_close) per bar."""
    out = []
    ha_open = bars[0].open if bars else 0.0
    for b in bars:
        ha_close = (b.open + b.high + b.low + b.close) / 4
        out.append((ha_open, ha_close))
        ha_open = (ha_open + ha_close) / 2
    return out
