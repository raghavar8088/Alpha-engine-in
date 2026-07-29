"""Intraday Strategy Lab — catalog of 150 distinctly-configured intraday equity
strategies (scalping, momentum/breakout, mean-reversion, swing-style).

Data reality check (same honesty convention as call_engine.py): this backend only
keeps *daily* bars locally for equities; true intraday (1m/5m) history is not
backfilled. So, exactly like call_engine's existing GAP-GO / PDH-BREAKOUT setups,
every "intraday" signal here is computed from (a) daily bars for trend/ATR/RSI/
Donchian context and (b) the *live* day OHLC + LTP from a single Dhan quote call
for today's actual intraday behaviour (open/high/low so far, volume so far).
Strategies are skipped honestly (no signal) when a live quote isn't available —
we never fabricate an intraday high/low from stale data.

150 strategies are produced by instantiating ~30 well-reasoned strategy *families*
with different, meaningfully distinct parameters (thresholds, ATR multiples,
lookbacks) — not 150 copies of one stub. Each StrategySpec carries a concrete
signal function bound via `family`.

The catalog is split into two blocks: the original 50 (11 families) and a +100
extension (20 additional families — Keltner, Donchian, MACD, RSI-momentum, CCI,
Aroon, ADX/DMI, PSAR, Heikin-Ashi, stochastic, Williams %R, z-score, pivot-R1,
gap-fill, prev-day-low bounce, …). The extension lives entirely in the three
same-day-squared-off categories (scalping / momentum / mean_reversion) — swing is
deliberately not extended, since the live desk excludes swing from new entries.
Every extension family is long-only (cash equities) and is only ever evaluated
when a live quote is present, so each enters at the live LTP with ATR-derived
target/stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from strategy_service.indicators import (
    adx,
    aroon,
    cci,
    donchian,
    ema,
    heikin_ashi,
    keltner,
    macd,
    psar,
    roc,
    rolling_vwap,
    rsi,
    stdev,
    stochastic,
    williams_r,
    zscore,
)
from tradingai_shared.domain import Bar

# --------------------------------------------------------------------------------
# Signal contract
# --------------------------------------------------------------------------------


@dataclass
class Signal:
    side: str  # "BUY" (long-only, cash equities — mirrors call_engine's convention)
    entry: float
    target: float
    stoploss: float
    confidence: float
    rationale: str


@dataclass
class StrategySpec:
    strategy_id: str
    name: str
    category: str  # scalping | momentum | mean_reversion | swing
    timeframe: str  # human label, e.g. "1-5m", "15m-1h", "1d"
    rationale: str
    max_hold_days: int  # 0 = must square off same day (EOD 15:15 IST)
    risk_pct: float  # fraction of this strategy's allocated capital risked per trade
    family: str
    params: dict = field(default_factory=dict)


Ctx = dict  # {"bars": list[Bar], "atr14": float, "quote": dict|None, "prev_bar": Bar}


# --------------------------------------------------------------------------------
# Family evaluators — each takes (spec, symbol, ctx) -> Signal | None
# --------------------------------------------------------------------------------


def _quote_ohlc(ctx: Ctx) -> tuple[float, float, float, float, float] | None:
    """(day_open, day_high, day_low, ltp, day_volume) from the live quote, or None
    when no live quote is available — callers must skip honestly, not guess."""
    q = ctx.get("quote")
    if not q:
        return None
    ohlc = q.get("ohlc") or {}
    day_open, day_high, day_low = float(ohlc.get("open") or 0), float(ohlc.get("high") or 0), float(ohlc.get("low") or 0)
    ltp = float(q.get("last_price") or 0)
    vol = float(q.get("volume") or 0)
    if day_open <= 0 or ltp <= 0:
        return None
    return day_open, day_high, day_low, ltp, vol


def _avg_volume(bars: list[Bar], n: int = 20) -> float:
    rows = bars[-n:]
    return sum(b.volume for b in rows) / max(len(rows), 1)


def orb_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Opening-range-breakout scalp: the "opening range" is proxied by how far
    price has already travelled from the day's open (range_pct) — a tighter
    range_pct fires earlier/faster (a "15-min-style" ORB), a wider one waits for
    more range to build (a "60-min-style" ORB). Target = ATR fraction, stop = the
    day low (or half the move, whichever is tighter)."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    day_open, day_high, day_low, ltp, vol = o
    range_pct = spec.params["range_pct"]
    if ltp < day_open * (1 + range_pct / 100):
        return None
    if day_high <= 0 or ltp < day_high * 0.999:  # only fire while making new day highs
        return None
    atr14 = ctx["atr14"]
    stop = max(day_low, ltp - 0.5 * atr14)
    if stop >= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=min(0.9, 0.4 + range_pct / 2),
        rationale=(
            f"ORB({range_pct:.2f}%): price extended {range_pct:.2f}% above the day's open "
            f"{day_open:.2f} and is making new day highs — breakout continuation scalp"
        ),
    )


def vwap_reversion_scalp_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Fade an intraday stretch away from the rolling VWAP proxy back toward it —
    classic mean-reversion scalp, but tiny ATR target/stop (this is the scalping
    variant; the mean_reversion category below runs the same idea with wider
    targets and daily granularity for slower reversion trades)."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    _, _, day_low, ltp, _ = o
    bars = ctx["bars"]
    closes = [b.close for b in bars]
    vwap_proxy = rolling_vwap(bars, spec.params["vwap_period"])[-1]
    if vwap_proxy <= 0:
        return None
    dev_pct = (ltp - vwap_proxy) / vwap_proxy * 100
    if dev_pct > -spec.params["deviation_pct"]:
        return None  # only buy the dip variant (long-only cash equities)
    atr14 = ctx["atr14"]
    stop = min(ltp - spec.params["stop_atr"] * atr14, day_low * 0.997)
    return Signal(
        side="BUY", entry=ltp, target=vwap_proxy, stoploss=stop,
        confidence=min(0.85, 0.35 + spec.params["deviation_pct"] / 3),
        rationale=(
            f"VWAP-reversion scalp: price is {abs(dev_pct):.2f}% below its "
            f"{spec.params['vwap_period']}-bar rolling VWAP proxy ({vwap_proxy:.2f}) — "
            "fading back toward fair value"
        ),
    )


def tick_momentum_scalp_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Fast EMA(fast)/EMA(slow) cross on daily closes as a trend-direction gate,
    triggered intraday only when the live LTP is pushing through the day's high
    with volume already running hot — a tick-momentum-style scalp confirmed by a
    slower directional filter."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    day_open, day_high, day_low, ltp, vol = o
    bars = ctx["bars"]
    closes = [b.close for b in bars]
    fast, slow = spec.params["ema_fast"], spec.params["ema_slow"]
    if len(closes) < slow + 1:
        return None
    ema_fast, ema_slow = ema(closes, fast), ema(closes, slow)
    if ema_fast[-1] <= ema_slow[-1]:
        return None
    avg_vol = _avg_volume(bars)
    if not (avg_vol and vol > 0.5 * avg_vol and day_high > 0 and ltp >= day_high * 0.998):
        return None
    atr14 = ctx["atr14"]
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14,
        stoploss=ltp - spec.params["stop_atr"] * atr14,
        confidence=0.5,
        rationale=(
            f"Tick-momentum scalp: EMA{fast} above EMA{slow} (uptrend filter) and price is "
            f"pushing through today's high on {vol / avg_vol:.1f}x-of-average volume"
        ),
    )


def gap_go_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Gap-and-go momentum continuation — same idea as call_engine's GAP-GO setup,
    parametrized by how large the gap must be (tighter gap = more signals/lower
    conviction, wider gap = fewer/higher conviction)."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    day_open, day_high, day_low, ltp, vol = o
    prev_bar = ctx["prev_bar"]
    prev_close, prev_high = prev_bar.close, prev_bar.high
    if prev_close <= 0:
        return None
    gap_pct = (day_open / prev_close - 1) * 100
    if gap_pct < spec.params["gap_pct"] or ltp <= day_open or ltp <= prev_high:
        return None
    atr14 = ctx["atr14"]
    stop = max(day_low, ltp - spec.params["stop_atr"] * atr14)
    if stop >= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=min(0.9, 0.4 + gap_pct / 5),
        rationale=(
            f"Gap-go({spec.params['gap_pct']:.2f}%): gapped up {gap_pct:.2f}% and holding above "
            f"both the open and yesterday's high {prev_high:.2f} — momentum continuation"
        ),
    )


def pdh_breakout_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Previous-day-high breakout without a gap, confirmed by participation
    (today's volume-so-far already a meaningful fraction of a normal day)."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    day_open, day_high, day_low, ltp, vol = o
    prev_bar = ctx["prev_bar"]
    prev_close, prev_high = prev_bar.close, prev_bar.high
    if prev_close <= 0 or day_open >= prev_close * 1.005:
        return None  # gap_go_family owns the gapped case
    breakout_pct = spec.params["breakout_pct"]
    if not (prev_high < ltp <= prev_high * (1 + breakout_pct / 100)):
        return None
    avg_vol = _avg_volume(ctx["bars"])
    if not (avg_vol and vol > spec.params["vol_participation"] * avg_vol):
        return None
    atr14 = ctx["atr14"]
    stop = max(prev_high * 0.99, ltp - spec.params["stop_atr"] * atr14)
    if stop >= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=0.55,
        rationale=(
            f"PDH breakout: crossed yesterday's high {prev_high:.2f} on "
            f"{vol / avg_vol:.1f}x-of-average participation — range-expansion breakout"
        ),
    )


def volume_surge_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Volume-surge continuation: today's volume-so-far already exceeds a
    multiple of the 20-day average AND price is in the top third of today's
    range — momentum participants are still in control."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    day_open, day_high, day_low, ltp, vol = o
    if day_high <= day_low:
        return None
    avg_vol = _avg_volume(ctx["bars"])
    vol_mult = spec.params["vol_mult"]
    if not (avg_vol and vol > vol_mult * avg_vol):
        return None
    range_pos = (ltp - day_low) / (day_high - day_low)
    if range_pos < 0.66:
        return None
    atr14 = ctx["atr14"]
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14,
        stoploss=ltp - spec.params["stop_atr"] * atr14,
        confidence=min(0.9, 0.4 + vol_mult / 5),
        rationale=(
            f"Volume-surge continuation: {vol / avg_vol:.1f}x average volume with price in the "
            f"top third of today's range — strong participants still buying"
        ),
    )


def vwap_fade_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Slower VWAP-fade mean-reversion (vs the scalping VWAP variant): wider
    deviation trigger, wider ATR target/stop, meant to hold minutes-to-an-hour
    rather than seconds."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    _, _, day_low, ltp, _ = o
    bars = ctx["bars"]
    vwap_proxy = rolling_vwap(bars, spec.params["vwap_period"])[-1]
    if vwap_proxy <= 0:
        return None
    dev_pct = (ltp - vwap_proxy) / vwap_proxy * 100
    if dev_pct > -spec.params["deviation_pct"]:
        return None
    atr14 = ctx["atr14"]
    return Signal(
        side="BUY", entry=ltp, target=vwap_proxy, stoploss=ltp - spec.params["stop_atr"] * atr14,
        confidence=min(0.8, 0.3 + spec.params["deviation_pct"] / 4),
        rationale=(
            f"VWAP fade: price is {abs(dev_pct):.2f}% below its {spec.params['vwap_period']}-bar "
            f"VWAP proxy — reversion trade back to {vwap_proxy:.2f}"
        ),
    )


def rsi2_extreme_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Larry Connors-style RSI(2) extreme-oversold bounce inside a longer uptrend
    (EMA200 filter, or EMA50 for shorter-history names) — one of the
    best-documented mean-reversion setups on liquid large caps."""
    bars = ctx["bars"]
    closes = [b.close for b in bars]
    trend_period = 200 if len(closes) >= 201 else 50
    if len(closes) < trend_period + 3:
        return None
    trend_ema = ema(closes, trend_period)[-1]
    if closes[-1] < trend_ema:
        return None  # only buy dips inside an uptrend
    rsi2 = rsi(closes, 2)[-1]
    if rsi2 > spec.params["oversold_th"]:
        return None
    atr14 = ctx["atr14"]
    entry = closes[-1]
    return Signal(
        side="BUY", entry=entry, target=entry + spec.params["target_atr"] * atr14,
        stoploss=entry - spec.params["stop_atr"] * atr14,
        confidence=min(0.85, 0.5 + (spec.params["oversold_th"] - rsi2) / 20),
        rationale=(
            f"RSI(2) extreme: RSI2 at {rsi2:.1f} (<= {spec.params['oversold_th']}) inside an "
            f"uptrend above EMA{trend_period} — short-term oversold bounce"
        ),
    )


def bollinger_snapback_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Bollinger-band snap-back: price closes below the lower band (mean - k*sd)
    then reclaims it — classic squeeze-release mean reversion."""
    bars = ctx["bars"]
    closes = [b.close for b in bars]
    period = 20
    if len(closes) < period + 2:
        return None
    from strategy_service.indicators import sma

    mean = sma(closes, period)[-1]
    sd = stdev(closes, period)[-1]
    lower = mean - spec.params["stdev_mult"] * sd
    prev_close = closes[-2]
    entry = closes[-1]
    if not (prev_close < lower and entry >= lower):
        return None
    atr14 = ctx["atr14"]
    return Signal(
        side="BUY", entry=entry, target=mean, stoploss=entry - spec.params["stop_atr"] * atr14,
        confidence=0.55,
        rationale=(
            f"Bollinger snap-back: closed below the lower band ({lower:.2f}, {spec.params['stdev_mult']}sd) "
            f"and reclaimed it — mean-reversion toward the {period}-bar average {mean:.2f}"
        ),
    )


def ema_pullback_swing_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Swing continuation: uptrend (EMA20 > EMA50) pulls back to within
    pullback_pct of EMA20 with RSI cooling off — enter intraday, manage over
    multiple days targeting the recent swing high."""
    bars = ctx["bars"]
    closes = [b.close for b in bars]
    if len(closes) < 55:
        return None
    ema20, ema50 = ema(closes, 20), ema(closes, 50)
    if ema20[-1] <= ema50[-1]:
        return None
    entry = closes[-1]
    if abs(entry - ema20[-1]) / ema20[-1] > spec.params["pullback_pct"] / 100:
        return None
    rsi14 = rsi(closes, 14)[-1]
    if not (35 <= rsi14 <= 55):
        return None
    swing_high = max(b.high for b in bars[-10:])
    swing_low = min(b.low for b in bars[-5:])
    if not (swing_low < entry < swing_high):
        return None
    return Signal(
        side="BUY", entry=entry, target=swing_high, stoploss=swing_low,
        confidence=0.5,
        rationale=(
            f"EMA20 pullback swing: uptrend intact (EMA20>{ema50[-1]:.2f} EMA50), price within "
            f"{spec.params['pullback_pct']:.1f}% of EMA20 with RSI {rsi14:.0f} cooling — swing continuation "
            f"toward {swing_high:.2f}, held up to {spec.max_hold_days} days"
        ),
    )


def breakout_retest_swing_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Donchian-channel breakout followed by a retest of the broken level held as
    support — enter on the retest, not the initial breakout spike, for a better
    entry price; managed as a multi-day swing."""
    bars = ctx["bars"]
    period = spec.params["donchian_period"]
    if len(bars) < period + 5:
        return None
    upper, _ = donchian(bars, period)
    entry = bars[-1].close
    level = upper[-2]  # the channel level before today
    if level <= 0:
        return None
    # broke out within the last 5 bars, now retesting within 1% of the level
    broke_out = any(b.high > level for b in bars[-6:-1])
    retesting = abs(entry - level) / level <= 0.01 and entry >= level * 0.99
    if not (broke_out and retesting):
        return None
    atr14 = ctx["atr14"]
    return Signal(
        side="BUY", entry=entry, target=entry + 2.0 * atr14, stoploss=level * 0.98,
        confidence=0.5,
        rationale=(
            f"Breakout retest ({period}-bar Donchian): broke {level:.2f} then pulled back to retest it "
            f"as support — swing entry held up to {spec.max_hold_days} days"
        ),
    )


def momentum_swing_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Momentum swing: strong N-day rate-of-change plus MACD-histogram
    confirmation, held for several days to let the trend run further than a
    same-day scalp/breakout would capture."""
    bars = ctx["bars"]
    closes = [b.close for b in bars]
    period = spec.params["roc_period"]
    if len(closes) < max(period, 35) + 1:
        return None
    m = roc(closes, period)[-1]
    if m < spec.params["roc_th"]:
        return None
    ema12, ema26 = ema(closes, 12), ema(closes, 26)
    if ema12[-1] - ema26[-1] <= 0:
        return None
    atr14 = ctx["atr14"]
    entry = closes[-1]
    return Signal(
        side="BUY", entry=entry, target=entry + 2.5 * atr14, stoploss=entry - 1.0 * atr14,
        confidence=min(0.85, 0.4 + m / 20),
        rationale=(
            f"Momentum swing: {period}-day ROC +{m:.1f}% with MACD confirming — trend swing held "
            f"up to {spec.max_hold_days} days"
        ),
    )


# ================================================================================
# Extended catalog (+100): 20 additional intraday families across the three
# same-day-squared-off categories (scalping / momentum / mean_reversion).
#
# These are only ever evaluated when a live quote is present (the engine skips a
# non-swing strategy that has no live quote), so every one of them enters at the
# live LTP with ATR-derived target/stop. `_mk_long` is the shared constructor for
# the daily-signal families that don't clamp their stop to an intraday level.
# ================================================================================


def _mk_long(ltp: float, atr14: float, target_atr: float, stop_atr: float,
             conf: float, rationale: str) -> Optional[Signal]:
    """Long signal at the live LTP with an ATR target/stop; rejects degenerate legs."""
    if ltp <= 0 or atr14 <= 0:
        return None
    target = ltp + target_atr * atr14
    stop = ltp - stop_atr * atr14
    if stop >= ltp or target <= ltp:
        return None
    return Signal(side="BUY", entry=ltp, target=target, stoploss=stop, confidence=conf, rationale=rationale)


# ---- Scalping (33): Keltner ride, range expansion, prev-close reclaim, momentum burst, pivot R1, PSAR flip ----


def keltner_ride_scalp_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Keltner-channel ride: price trading above the upper Keltner band (EMA +
    mult*ATR) while making new day highs — a volatility-breakout continuation scalp."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    _, day_high, _, ltp, _ = o
    bars = ctx["bars"]
    period, mult = spec.params["kc_period"], spec.params["kc_mult"]
    if len(bars) < period + 1:
        return None
    upper, mid, lower = keltner(bars, period, mult)
    if upper[-1] <= 0 or ltp <= upper[-1]:
        return None
    if day_high <= 0 or ltp < day_high * 0.998:
        return None
    atr14 = ctx["atr14"]
    stop = max(mid[-1], ltp - spec.params["stop_atr"] * atr14)
    if stop >= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=0.5,
        rationale=(
            f"Keltner ride: price {ltp:.2f} above the {period}/{mult:g} upper Keltner band "
            f"({upper[-1]:.2f}) and making new day highs — volatility-breakout scalp"
        ),
    )


def range_expansion_scalp_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Range-expansion scalp: today's realised range already exceeds a multiple of
    the daily ATR and price sits near the top of that range — a wide-range day with
    buyers in control."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    _, day_high, day_low, ltp, _ = o
    atr14 = ctx["atr14"]
    if atr14 <= 0 or day_high <= day_low:
        return None
    if (day_high - day_low) < spec.params["range_mult"] * atr14:
        return None
    if (ltp - day_low) / (day_high - day_low) < spec.params["min_pos"]:
        return None
    stop = max(day_low, ltp - spec.params["stop_atr"] * atr14)
    if stop >= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=0.5,
        rationale=(
            f"Range expansion: today's range is {(day_high - day_low) / atr14:.1f}x ATR with price in "
            f"the top {(1 - spec.params['min_pos']) * 100:.0f}% of it — wide-range day, buyers in control"
        ),
    )


def prev_close_reclaim_scalp_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Previous-close reclaim: price dipped below yesterday's close intraday and has
    reclaimed it — a failed-breakdown / support-hold scalp."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    _, _, day_low, ltp, _ = o
    prev_close = ctx["prev_bar"].close
    if prev_close <= 0:
        return None
    if not (day_low < prev_close and prev_close < ltp <= prev_close * (1 + spec.params["band_pct"] / 100)):
        return None
    atr14 = ctx["atr14"]
    stop = max(day_low, ltp - spec.params["stop_atr"] * atr14)
    if stop >= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=0.45,
        rationale=(
            f"Prev-close reclaim: dipped below yesterday's close {prev_close:.2f} and reclaimed it — "
            "failed-breakdown scalp"
        ),
    )


def momentum_burst_scalp_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Momentum-burst scalp: a short-lookback rate-of-change spike confirmed by price
    pressing today's high — a fast continuation entry."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    _, day_high, _, ltp, _ = o
    closes = [b.close for b in ctx["bars"]]
    period = spec.params["roc_period"]
    if len(closes) < period + 1:
        return None
    m = roc(closes, period)[-1]
    if m < spec.params["roc_th"]:
        return None
    if day_high <= 0 or ltp < day_high * 0.998:
        return None
    atr14 = ctx["atr14"]
    stop = ltp - spec.params["stop_atr"] * atr14
    if stop >= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=min(0.85, 0.4 + m / 15),
        rationale=(
            f"Momentum burst: {period}-bar ROC +{m:.1f}% and price pressing today's high — "
            "fast continuation scalp"
        ),
    )


def pivot_r1_scalp_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Classic floor-pivot R1 breakout: yesterday's (H+L+C)/3 pivot projects
    R1 = 2*PP - L; a push above R1 is an intraday strength signal, stop at the pivot."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    _, _, _, ltp, _ = o
    pb = ctx["prev_bar"]
    high, low, close = pb.high, pb.low, pb.close
    if min(high, low, close) <= 0 or high <= low:
        return None
    pp = (high + low + close) / 3
    r1 = 2 * pp - low
    if not (r1 < ltp <= r1 * (1 + spec.params["band_pct"] / 100)):
        return None
    atr14 = ctx["atr14"]
    stop = max(pp, ltp - spec.params["stop_atr"] * atr14)
    if stop >= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=0.5,
        rationale=(
            f"Pivot R1 breakout: crossed the floor-pivot R1 {r1:.2f} (PP {pp:.2f}) — intraday "
            "strength, stop at the pivot"
        ),
    )


def psar_flip_scalp_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Parabolic-SAR flip: SAR just flipped from bearish to bullish (a fresh trend
    turn) with price holding above the day's open — momentum-ignition scalp."""
    bars = ctx["bars"]
    if len(bars) < 3:
        return None
    flags = psar(bars, spec.params["af_step"], spec.params["af_max"])
    if len(flags) < 2 or not (flags[-1] == 1 and flags[-2] == -1):
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    day_open, _, day_low, ltp, _ = o
    if ltp <= day_open:
        return None
    atr14 = ctx["atr14"]
    stop = max(day_low, ltp - spec.params["stop_atr"] * atr14)
    if stop >= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=0.5,
        rationale="Parabolic-SAR flip: SAR turned bullish with price above the open — momentum-ignition scalp",
    )


# ---- Momentum (34): Donchian breakout, MACD cross, RSI momentum, CCI breakout, Aroon, ADX/DMI, Heikin-Ashi ----


def donchian_breakout_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """N-day Donchian (highest-high) breakout: price trades above the prior N-day
    channel top — a fresh N-day high, the canonical trend-following entry."""
    bars = ctx["bars"]
    period = spec.params["dc_period"]
    if len(bars) < period + 2:
        return None
    upper, _ = donchian(bars, period)
    level = upper[-2]
    if level <= 0:
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    _, _, _, ltp, _ = o
    if not (level < ltp <= level * (1 + spec.params["band_pct"] / 100)):
        return None
    atr14 = ctx["atr14"]
    stop = max(level * 0.995, ltp - spec.params["stop_atr"] * atr14)
    if stop >= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=0.55,
        rationale=f"Donchian breakout: new {period}-day high above {level:.2f} — trend-following entry",
    )


def macd_cross_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """MACD bullish cross: the MACD line crosses above its signal line (histogram
    turns positive) — a momentum-turn entry."""
    closes = [b.close for b in ctx["bars"]]
    fast, slow, sig = spec.params["fast"], spec.params["slow"], spec.params["signal"]
    if len(closes) < slow + sig + 2:
        return None
    ml, sl = macd(closes, fast, slow, sig)
    if len(ml) < 2:
        return None
    if not (ml[-2] - sl[-2] <= 0 < ml[-1] - sl[-1]):
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    return _mk_long(
        o[3], ctx["atr14"], spec.params["target_atr"], spec.params["stop_atr"], 0.5,
        f"MACD cross: MACD({fast},{slow},{sig}) line crossed above signal — momentum turn",
    )


def rsi_momentum_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """RSI momentum trigger: RSI crosses up through a mid-line threshold (50-60) —
    momentum shifting bullish, distinct from the RSI(2) extreme-oversold reversion."""
    closes = [b.close for b in ctx["bars"]]
    period, th = spec.params["rsi_period"], spec.params["threshold"]
    if len(closes) < period + 2:
        return None
    r = rsi(closes, period)
    if not (r[-2] <= th < r[-1]):
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    return _mk_long(
        o[3], ctx["atr14"], spec.params["target_atr"], spec.params["stop_atr"], 0.5,
        f"RSI momentum: RSI{period} crossed up through {th:.0f} ({r[-2]:.0f}->{r[-1]:.0f}) — momentum turning bullish",
    )


def cci_breakout_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """CCI breakout: the Commodity Channel Index crosses up through +threshold
    (typically +100) — price breaking out of its statistical range to the upside."""
    bars = ctx["bars"]
    period, th = spec.params["cci_period"], spec.params["threshold"]
    if len(bars) < period + 2:
        return None
    c = cci(bars, period)
    if not (c[-2] <= th < c[-1]):
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    return _mk_long(
        o[3], ctx["atr14"], spec.params["target_atr"], spec.params["stop_atr"], 0.5,
        f"CCI breakout: CCI{period} crossed above +{th:.0f} — upside range breakout",
    )


def aroon_trend_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Aroon uptrend: Aroon-Up is high (a very recent new high) and dominates
    Aroon-Down — a fresh, clean uptrend."""
    bars = ctx["bars"]
    period = spec.params["aroon_period"]
    if len(bars) < period + 2:
        return None
    up, dn = aroon(bars, period)
    if not (up[-1] >= spec.params["up_min"] and up[-1] - dn[-1] >= spec.params["spread_min"]):
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    return _mk_long(
        o[3], ctx["atr14"], spec.params["target_atr"], spec.params["stop_atr"], 0.5,
        f"Aroon trend: Aroon-Up {up[-1]:.0f} vs Aroon-Down {dn[-1]:.0f} over {period} bars — fresh uptrend",
    )


def adx_di_momentum_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """ADX/DMI trend: ADX above a strength threshold with +DI over -DI — an
    established, directional up-trend (trend-strength filter, not just direction)."""
    bars = ctx["bars"]
    period = spec.params["adx_period"]
    if len(bars) < 2 * period + 2:
        return None
    adx_v, pdi, mdi = adx(bars, period)
    if not (adx_v[-1] >= spec.params["adx_min"] and pdi[-1] > mdi[-1]):
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    return _mk_long(
        o[3], ctx["atr14"], spec.params["target_atr"], spec.params["stop_atr"], 0.55,
        f"ADX trend: ADX{period} {adx_v[-1]:.0f} (>={spec.params['adx_min']:.0f}) with +DI over -DI — strong uptrend",
    )


def heikin_momentum_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Heikin-Ashi momentum: N consecutive bullish HA candles (ha_close > ha_open) —
    smoothed trend persistence, filtering intrabar noise."""
    bars = ctx["bars"]
    streak = spec.params["streak"]
    if len(bars) < streak + 2:
        return None
    ha = heikin_ashi(bars)
    if len(ha) < streak:
        return None
    if not all(ha[-i][1] > ha[-i][0] for i in range(1, streak + 1)):
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    return _mk_long(
        o[3], ctx["atr14"], spec.params["target_atr"], spec.params["stop_atr"], 0.5,
        f"Heikin-Ashi momentum: {streak} consecutive bullish HA candles — smoothed trend persistence",
    )


# ---- Mean reversion (33): stochastic, Williams %R, CCI, Keltner-lower, z-score, gap-fill, prev-day-low bounce ----


def stochastic_oversold_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Stochastic oversold turn: %K below an oversold threshold and turning up
    (%K rising) — a momentum-exhaustion bounce."""
    bars = ctx["bars"]
    kp = spec.params["k_period"]
    if len(bars) < kp + 4:
        return None
    k, _ = stochastic(bars, kp, spec.params.get("d_period", 3))
    if not (k[-2] < spec.params["oversold"] and k[-1] > k[-2]):
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    return _mk_long(
        o[3], ctx["atr14"], spec.params["target_atr"], spec.params["stop_atr"], 0.5,
        f"Stochastic bounce: %K turned up from oversold ({k[-2]:.0f}->{k[-1]:.0f}, <{spec.params['oversold']:.0f}) — exhaustion reversal",
    )


def williams_reversion_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Williams %R reversion: %R below the oversold line (e.g. -80) and turning up —
    a short-term oversold bounce on a bounded oscillator."""
    bars = ctx["bars"]
    period = spec.params["wr_period"]
    if len(bars) < period + 3:
        return None
    w = williams_r(bars, period)
    if not (w[-2] < spec.params["oversold"] and w[-1] > w[-2]):
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    return _mk_long(
        o[3], ctx["atr14"], spec.params["target_atr"], spec.params["stop_atr"], 0.5,
        f"Williams %R bounce: %R turned up from {w[-2]:.0f} (<{spec.params['oversold']:.0f}) — oversold reversal",
    )


def cci_reversion_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """CCI reversion: CCI below -threshold (e.g. -100) and turning up — price
    stretched below its statistical range and snapping back."""
    bars = ctx["bars"]
    period = spec.params["cci_period"]
    if len(bars) < period + 3:
        return None
    c = cci(bars, period)
    if not (c[-2] < spec.params["oversold"] and c[-1] > c[-2]):
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    return _mk_long(
        o[3], ctx["atr14"], spec.params["target_atr"], spec.params["stop_atr"], 0.5,
        f"CCI reversion: CCI{period} turning up from {c[-2]:.0f} (<{spec.params['oversold']:.0f}) — snap-back from oversold",
    )


def keltner_lower_reversion_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Keltner lower-band reversion: price closed below the lower Keltner band and
    has reclaimed it — mean reversion back toward the channel mid (EMA)."""
    bars = ctx["bars"]
    period, mult = spec.params["kc_period"], spec.params["kc_mult"]
    if len(bars) < period + 2:
        return None
    upper, mid, lower = keltner(bars, period, mult)
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    _, _, _, ltp, _ = o
    if not (bars[-2].close < lower[-2] and ltp >= lower[-1]):
        return None
    atr14 = ctx["atr14"]
    target = mid[-1]
    stop = ltp - spec.params["stop_atr"] * atr14
    if stop >= ltp or target <= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=target, stoploss=stop, confidence=0.5,
        rationale=(
            f"Keltner reversion: reclaimed the {period}/{mult:g} lower band — reverting toward the "
            f"mid {mid[-1]:.2f}"
        ),
    )


def zscore_reversion_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Z-score reversion: closing price more than N standard deviations below its
    rolling mean and ticking back up — a statistical mean-reversion entry."""
    closes = [b.close for b in ctx["bars"]]
    period = spec.params["z_period"]
    if len(closes) < period + 2:
        return None
    z = zscore(closes, period)
    if not (z[-2] <= -spec.params["z_th"] and z[-1] > z[-2]):
        return None
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    return _mk_long(
        o[3], ctx["atr14"], spec.params["target_atr"], spec.params["stop_atr"], 0.5,
        f"Z-score reversion: price {abs(z[-2]):.1f} sigma below its {period}-bar mean and turning up — statistical snap-back",
    )


def gap_fill_reversion_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Gap-fill reversion: a gap DOWN at the open that price is now climbing back to
    fill toward yesterday's close — the fade of an over-reaction gap."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    day_open, _, day_low, ltp, _ = o
    prev_close = ctx["prev_bar"].close
    if prev_close <= 0:
        return None
    gap_pct = (day_open / prev_close - 1) * 100
    if gap_pct > -spec.params["gap_pct"]:
        return None
    if not (ltp > day_open and ltp < prev_close):
        return None
    atr14 = ctx["atr14"]
    stop = max(day_low, ltp - spec.params["stop_atr"] * atr14)
    if stop >= ltp or prev_close <= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=prev_close, stoploss=stop, confidence=0.5,
        rationale=(
            f"Gap-fill: gapped down {gap_pct:.2f}% and recovering off the low — reversion toward "
            f"yesterday's close {prev_close:.2f}"
        ),
    )


def prev_day_low_bounce_family(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    """Previous-day-low support bounce: price tested yesterday's low and is holding
    above it — buying a prior-support retest, stop just below the low."""
    o = _quote_ohlc(ctx)
    if o is None:
        return None
    _, _, day_low, ltp, _ = o
    prev_low = ctx["prev_bar"].low
    if prev_low <= 0:
        return None
    near = spec.params["near_pct"] / 100
    if not (day_low <= prev_low * (1 + near) and prev_low <= ltp <= prev_low * (1 + near)):
        return None
    atr14 = ctx["atr14"]
    stop = prev_low * (1 - spec.params["stop_buf_pct"] / 100)
    if stop >= ltp:
        return None
    return Signal(
        side="BUY", entry=ltp, target=ltp + spec.params["target_atr"] * atr14, stoploss=stop,
        confidence=0.45,
        rationale=(
            f"PDL bounce: tested yesterday's low {prev_low:.2f} and holding — prior-support retest, "
            "stop below the low"
        ),
    )


FAMILY_FUNCS: dict[str, Callable[[StrategySpec, str, Ctx], Optional[Signal]]] = {
    "orb": orb_family,
    "vwap_reversion_scalp": vwap_reversion_scalp_family,
    "tick_momentum_scalp": tick_momentum_scalp_family,
    "gap_go": gap_go_family,
    "pdh_breakout": pdh_breakout_family,
    "volume_surge": volume_surge_family,
    "vwap_fade": vwap_fade_family,
    "rsi2_extreme": rsi2_extreme_family,
    "bollinger_snapback": bollinger_snapback_family,
    "ema_pullback_swing": ema_pullback_swing_family,
    "breakout_retest_swing": breakout_retest_swing_family,
    "momentum_swing": momentum_swing_family,
    # ---- +100 extension ----
    "keltner_ride_scalp": keltner_ride_scalp_family,
    "range_expansion_scalp": range_expansion_scalp_family,
    "prev_close_reclaim_scalp": prev_close_reclaim_scalp_family,
    "momentum_burst_scalp": momentum_burst_scalp_family,
    "pivot_r1_scalp": pivot_r1_scalp_family,
    "psar_flip_scalp": psar_flip_scalp_family,
    "donchian_breakout": donchian_breakout_family,
    "macd_cross": macd_cross_family,
    "rsi_momentum": rsi_momentum_family,
    "cci_breakout": cci_breakout_family,
    "aroon_trend": aroon_trend_family,
    "adx_di_momentum": adx_di_momentum_family,
    "heikin_momentum": heikin_momentum_family,
    "stochastic_oversold": stochastic_oversold_family,
    "williams_reversion": williams_reversion_family,
    "cci_reversion": cci_reversion_family,
    "keltner_lower_reversion": keltner_lower_reversion_family,
    "zscore_reversion": zscore_reversion_family,
    "gap_fill_reversion": gap_fill_reversion_family,
    "prev_day_low_bounce": prev_day_low_bounce_family,
}


def evaluate(spec: StrategySpec, symbol: str, ctx: Ctx) -> Optional[Signal]:
    fn = FAMILY_FUNCS.get(spec.family)
    if fn is None:
        return None
    try:
        return fn(spec, symbol, ctx)
    except Exception:
        return None


# --------------------------------------------------------------------------------
# Catalog: 150 distinctly-configured strategies (original 50 + a 100-strategy
# extension across scalping / momentum / mean_reversion)
# --------------------------------------------------------------------------------


def _build_catalog() -> list[StrategySpec]:
    specs: list[StrategySpec] = []
    n = 0

    def add(name, category, timeframe, rationale, max_hold_days, risk_pct, family, params):
        nonlocal n
        n += 1
        specs.append(StrategySpec(
            strategy_id=f"intraday_{n:03d}", name=name, category=category, timeframe=timeframe,
            rationale=rationale, max_hold_days=max_hold_days, risk_pct=risk_pct, family=family, params=params,
        ))

    # ---- Scalping (15): ORB x5, VWAP-reversion x5, tick-momentum x5 ----
    for range_pct, target_atr in ((0.15, 0.30), (0.25, 0.35), (0.35, 0.40), (0.45, 0.45), (0.55, 0.50)):
        add(
            f"ORB {range_pct:.2f}% Scalp", "scalping", "1-5m",
            f"Enter once price extends {range_pct:.2f}% above the day's open and is making new "
            f"day highs; target {target_atr:.2f}xATR, stop at the day low.",
            0, 0.30, "orb", {"range_pct": range_pct, "target_atr": target_atr},
        )
    for vwap_period, deviation_pct in ((10, 0.3), (10, 0.5), (20, 0.7), (20, 1.0), (30, 1.5)):
        add(
            f"VWAP Reversion Scalp {deviation_pct:.1f}%", "scalping", "1-5m",
            f"Buy when price is {deviation_pct:.1f}% below its {vwap_period}-bar rolling-VWAP proxy, "
            "target the VWAP itself, tight stop.",
            0, 0.25, "vwap_reversion_scalp", {"vwap_period": vwap_period, "deviation_pct": deviation_pct, "stop_atr": 0.25},
        )
    for ema_fast, target_atr, stop_atr in ((5, 0.30, 0.15), (7, 0.35, 0.18), (9, 0.40, 0.20), (11, 0.45, 0.22), (13, 0.50, 0.25)):
        add(
            f"Tick Momentum EMA{ema_fast}/21 Scalp", "scalping", "1-5m",
            f"EMA{ema_fast} above EMA21 (uptrend filter) and price pushing through today's high on "
            "elevated volume — scalp the continuation.",
            0, 0.25, "tick_momentum_scalp", {"ema_fast": ema_fast, "ema_slow": 21, "target_atr": target_atr, "stop_atr": stop_atr},
        )

    # ---- Momentum / breakout (15): gap-go x5, PDH breakout x5, volume-surge x5 ----
    for gap_pct, target_atr, stop_atr in ((0.3, 0.7, 0.3), (0.5, 0.8, 0.35), (0.75, 0.9, 0.4), (1.0, 1.0, 0.45), (1.5, 1.2, 0.5)):
        add(
            f"Gap-Go {gap_pct:.2f}%", "momentum", "15m-1h",
            f"Gap up >= {gap_pct:.2f}% at the open and holding above both the open and PDH — "
            "momentum continuation.",
            0, 0.30, "gap_go", {"gap_pct": gap_pct, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for breakout_pct, vol_participation, target_atr in ((0.2, 0.4, 0.8), (0.4, 0.5, 0.9), (0.6, 0.6, 1.0), (0.8, 0.7, 1.1), (1.0, 0.8, 1.2)):
        add(
            f"PDH Breakout {breakout_pct:.1f}%", "momentum", "15m-1h",
            f"Crossed yesterday's high by up to {breakout_pct:.1f}% (no gap) with today's volume-so-far "
            f"already {vol_participation:.0%} of the 20-day average — range-expansion breakout.",
            0, 0.30, "pdh_breakout", {"breakout_pct": breakout_pct, "vol_participation": vol_participation, "target_atr": target_atr, "stop_atr": 0.5},
        )
    for vol_mult, target_atr, stop_atr in ((1.5, 1.0, 0.5), (2.0, 1.1, 0.55), (2.5, 1.2, 0.6), (3.0, 1.3, 0.65), (3.5, 1.4, 0.7)):
        add(
            f"Volume Surge {vol_mult:.1f}x Continuation", "momentum", "15m-1h",
            f"Today's volume-so-far exceeds {vol_mult:.1f}x the 20-day average with price in the top "
            "third of today's range — momentum participants still buying.",
            0, 0.30, "volume_surge", {"vol_mult": vol_mult, "target_atr": target_atr, "stop_atr": stop_atr},
        )

    # ---- Mean reversion (10): VWAP fade x4, RSI-2 extreme x3, Bollinger snap-back x3 ----
    for vwap_period, deviation_pct in ((20, 1.0), (20, 1.5), (30, 2.0), (30, 2.5)):
        add(
            f"VWAP Fade {deviation_pct:.1f}%", "mean_reversion", "15m-1h",
            f"Buy when price is {deviation_pct:.1f}% below its {vwap_period}-bar VWAP proxy; slower, "
            "wider-target sibling of the VWAP-reversion scalp.",
            0, 0.25, "vwap_fade", {"vwap_period": vwap_period, "deviation_pct": deviation_pct, "stop_atr": 0.6},
        )
    for oversold_th, target_atr, stop_atr in ((5, 1.0, 0.5), (10, 1.1, 0.55), (15, 1.2, 0.6)):
        add(
            f"RSI(2) Extreme <= {oversold_th}", "mean_reversion", "1d",
            f"RSI(2) at or below {oversold_th} while price sits above its long-term EMA (uptrend) — "
            "Connors-style short-term oversold bounce.",
            0, 0.25, "rsi2_extreme", {"oversold_th": oversold_th, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for stdev_mult in (2.0, 2.25, 2.5):
        add(
            f"Bollinger Snap-Back {stdev_mult:.2f}sd", "mean_reversion", "1d",
            f"Closed below the {stdev_mult:.2f}-sd lower Bollinger band and reclaimed it same/next "
            "session — squeeze-release mean reversion toward the 20-bar mean.",
            0, 0.25, "bollinger_snapback", {"stdev_mult": stdev_mult, "stop_atr": 0.6},
        )

    # ---- Swing-style, intraday-initiated (10): EMA pullback x4, breakout retest x3, momentum swing x3 ----
    for pullback_pct, hold_days in ((1.0, 3), (1.5, 4), (2.0, 4), (2.5, 5)):
        add(
            f"EMA20 Pullback Swing {pullback_pct:.1f}%", "swing", "1d",
            f"Uptrend (EMA20>EMA50) pulls back to within {pullback_pct:.1f}% of EMA20 with RSI "
            f"35-55 — enter intraday, manage as a swing for up to {hold_days} days targeting the "
            "recent swing high.",
            hold_days, 0.35, "ema_pullback_swing", {"pullback_pct": pullback_pct},
        )
    for donchian_period, hold_days in ((10, 3), (20, 4), (30, 5)):
        add(
            f"Breakout Retest ({donchian_period}d) Swing", "swing", "1d",
            f"Price broke the {donchian_period}-day Donchian high then pulled back to retest it as "
            f"support — swing entry on the retest, held up to {hold_days} days.",
            hold_days, 0.35, "breakout_retest_swing", {"donchian_period": donchian_period},
        )
    for roc_period, roc_th, hold_days in ((10, 5.0, 3), (20, 7.0, 4), (30, 9.0, 5)):
        add(
            f"Momentum Swing ROC{roc_period}", "swing", "1d",
            f"{roc_period}-day ROC above {roc_th:.0f}% with MACD confirming trend — momentum swing "
            f"held up to {hold_days} days to let the trend run.",
            hold_days, 0.35, "momentum_swing", {"roc_period": roc_period, "roc_th": roc_th},
        )

    # ================================================================================
    # +100 extension — all in the three same-day-squared-off categories (never swing),
    # so every one of them trades on the live desk.
    # ================================================================================

    # ---- Scalping (33) ----
    for kc_period, kc_mult, target_atr, stop_atr in (
        (20, 1.5, 0.35, 0.25), (20, 2.0, 0.40, 0.30), (14, 1.5, 0.30, 0.22),
        (14, 2.0, 0.45, 0.30), (30, 2.0, 0.50, 0.35), (30, 2.5, 0.55, 0.40),
    ):
        add(
            f"Keltner Ride {kc_period}/{kc_mult:g} Scalp", "scalping", "1-5m",
            f"Price trading above the {kc_period}-period, {kc_mult:g}x-ATR upper Keltner band while "
            "making new day highs — volatility-breakout continuation scalp.",
            0, 0.30, "keltner_ride_scalp",
            {"kc_period": kc_period, "kc_mult": kc_mult, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for range_mult, min_pos, target_atr, stop_atr in (
        (1.0, 0.70, 0.40, 0.40), (1.25, 0.72, 0.50, 0.45), (1.5, 0.75, 0.60, 0.50),
        (1.75, 0.78, 0.70, 0.50), (2.0, 0.80, 0.80, 0.55), (2.5, 0.85, 0.90, 0.60),
    ):
        add(
            f"Range Expansion {range_mult:g}xATR Scalp", "scalping", "1-5m",
            f"Today's realised range already exceeds {range_mult:g}x ATR with price in the top of "
            "that range — a wide-range day with buyers in control.",
            0, 0.30, "range_expansion_scalp",
            {"range_mult": range_mult, "min_pos": min_pos, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for band_pct, target_atr, stop_atr in (
        (0.3, 0.40, 0.30), (0.5, 0.50, 0.35), (0.75, 0.60, 0.40), (1.0, 0.70, 0.45), (1.5, 0.80, 0.50),
    ):
        add(
            f"Prev-Close Reclaim {band_pct:.2f}% Scalp", "scalping", "1-5m",
            f"Price dipped below yesterday's close and reclaimed it (within {band_pct:.2f}%) — "
            "failed-breakdown / support-hold scalp.",
            0, 0.25, "prev_close_reclaim_scalp",
            {"band_pct": band_pct, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for roc_period, roc_th, target_atr, stop_atr in (
        (2, 1.0, 0.30, 0.22), (3, 1.5, 0.35, 0.25), (3, 2.5, 0.40, 0.28),
        (5, 3.0, 0.45, 0.30), (5, 4.0, 0.50, 0.35), (7, 5.0, 0.55, 0.38),
    ):
        add(
            f"Momentum Burst ROC{roc_period}>{roc_th:g}% Scalp", "scalping", "1-5m",
            f"A {roc_period}-bar rate-of-change spike above {roc_th:g}% confirmed by price pressing "
            "today's high — fast continuation scalp.",
            0, 0.25, "momentum_burst_scalp",
            {"roc_period": roc_period, "roc_th": roc_th, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for band_pct, target_atr, stop_atr in (
        (0.2, 0.50, 0.35), (0.35, 0.60, 0.40), (0.5, 0.70, 0.45), (0.75, 0.80, 0.50), (1.0, 0.90, 0.55),
    ):
        add(
            f"Pivot R1 Breakout {band_pct:.2f}% Scalp", "scalping", "1-5m",
            f"Push above the classic floor-pivot R1 (2*PP - L) by up to {band_pct:.2f}% — intraday "
            "strength, stop back at the pivot.",
            0, 0.30, "pivot_r1_scalp",
            {"band_pct": band_pct, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for af_step, af_max, target_atr, stop_atr in (
        (0.02, 0.2, 0.40, 0.30), (0.02, 0.1, 0.45, 0.32), (0.03, 0.2, 0.50, 0.35),
        (0.04, 0.2, 0.55, 0.38), (0.01, 0.15, 0.35, 0.28),
    ):
        add(
            f"PSAR Flip Scalp af{af_step:g}/{af_max:g}", "scalping", "1-5m",
            f"Parabolic-SAR (step {af_step:g}, max {af_max:g}) just flipped bullish with price above "
            "the open — momentum-ignition scalp.",
            0, 0.30, "psar_flip_scalp",
            {"af_step": af_step, "af_max": af_max, "target_atr": target_atr, "stop_atr": stop_atr},
        )

    # ---- Momentum / breakout (34) ----
    for dc_period, band_pct, target_atr, stop_atr in (
        (10, 0.5, 0.8, 0.5), (20, 0.5, 1.0, 0.6), (20, 1.0, 1.0, 0.6),
        (30, 0.75, 1.2, 0.7), (40, 1.0, 1.3, 0.75), (55, 1.0, 1.5, 0.8),
    ):
        add(
            f"Donchian {dc_period}d Breakout", "momentum", "15m-1h",
            f"Price makes a fresh {dc_period}-day high above the prior Donchian channel top — "
            "canonical trend-following breakout.",
            0, 0.30, "donchian_breakout",
            {"dc_period": dc_period, "band_pct": band_pct, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for fast, slow, sig, target_atr, stop_atr in (
        (12, 26, 9, 1.0, 0.6), (8, 17, 9, 0.9, 0.55), (5, 35, 5, 1.2, 0.7),
        (10, 21, 7, 1.0, 0.6), (6, 19, 6, 0.9, 0.55),
    ):
        add(
            f"MACD Cross {fast}/{slow}/{sig}", "momentum", "15m-1h",
            f"MACD({fast},{slow},{sig}) line crosses above its signal (histogram turns positive) — "
            "momentum-turn entry.",
            0, 0.30, "macd_cross",
            {"fast": fast, "slow": slow, "signal": sig, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for rsi_period, threshold, target_atr, stop_atr in (
        (14, 50, 0.9, 0.55), (14, 55, 1.0, 0.6), (9, 50, 0.8, 0.5), (9, 60, 1.0, 0.6), (21, 55, 1.1, 0.65),
    ):
        add(
            f"RSI{rsi_period} Momentum >{threshold}", "momentum", "15m-1h",
            f"RSI{rsi_period} crosses up through {threshold} — momentum shifting bullish (distinct "
            "from the RSI(2) extreme-oversold reversion).",
            0, 0.30, "rsi_momentum",
            {"rsi_period": rsi_period, "threshold": threshold, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for cci_period, threshold, target_atr, stop_atr in (
        (20, 100, 1.0, 0.6), (14, 100, 0.9, 0.55), (20, 150, 1.1, 0.65), (30, 100, 1.2, 0.7), (14, 50, 0.8, 0.5),
    ):
        add(
            f"CCI{cci_period} Breakout +{threshold}", "momentum", "15m-1h",
            f"CCI{cci_period} crosses up through +{threshold} — price breaking out of its statistical "
            "range to the upside.",
            0, 0.30, "cci_breakout",
            {"cci_period": cci_period, "threshold": threshold, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for aroon_period, up_min, spread_min, target_atr, stop_atr in (
        (25, 80, 50, 1.0, 0.6), (25, 100, 60, 1.1, 0.65), (14, 80, 40, 0.9, 0.55),
        (30, 90, 50, 1.2, 0.7), (20, 100, 70, 1.1, 0.65),
    ):
        add(
            f"Aroon{aroon_period} Trend Up{up_min}", "momentum", "15m-1h",
            f"Aroon-Up >= {up_min} and beating Aroon-Down by {spread_min}+ over {aroon_period} bars — "
            "a fresh, clean uptrend.",
            0, 0.30, "aroon_trend",
            {"aroon_period": aroon_period, "up_min": up_min, "spread_min": spread_min,
             "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for adx_period, adx_min, target_atr, stop_atr in (
        (14, 25, 1.0, 0.6), (14, 30, 1.1, 0.65), (20, 25, 1.2, 0.7), (10, 20, 0.9, 0.55),
    ):
        add(
            f"ADX{adx_period} DMI Trend >={adx_min}", "momentum", "15m-1h",
            f"ADX{adx_period} >= {adx_min} with +DI over -DI — an established, directional uptrend "
            "(trend-strength filter, not just direction).",
            0, 0.30, "adx_di_momentum",
            {"adx_period": adx_period, "adx_min": adx_min, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for streak, target_atr, stop_atr in ((3, 0.9, 0.55), (4, 1.0, 0.6), (5, 1.1, 0.65), (2, 0.8, 0.5)):
        add(
            f"Heikin-Ashi {streak}-Candle Momentum", "momentum", "15m-1h",
            f"{streak} consecutive bullish Heikin-Ashi candles — smoothed trend persistence that "
            "filters intrabar noise.",
            0, 0.30, "heikin_momentum",
            {"streak": streak, "target_atr": target_atr, "stop_atr": stop_atr},
        )

    # ---- Mean reversion (33) ----
    for k_period, oversold, target_atr, stop_atr in (
        (14, 20, 0.9, 0.55), (14, 15, 1.0, 0.6), (9, 20, 0.8, 0.5),
        (21, 25, 1.0, 0.6), (14, 10, 1.1, 0.65), (5, 20, 0.7, 0.45),
    ):
        add(
            f"Stochastic{k_period} Oversold <{oversold}", "mean_reversion", "15m-1h",
            f"Stochastic %K({k_period}) below {oversold} and turning up — momentum-exhaustion bounce.",
            0, 0.25, "stochastic_oversold",
            {"k_period": k_period, "oversold": oversold, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for wr_period, oversold, target_atr, stop_atr in (
        (14, -80, 0.9, 0.55), (14, -90, 1.0, 0.6), (9, -80, 0.8, 0.5), (21, -85, 1.0, 0.6), (10, -90, 0.9, 0.55),
    ):
        add(
            f"Williams%R{wr_period} Reversion <{oversold}", "mean_reversion", "15m-1h",
            f"Williams %R({wr_period}) below {oversold} and turning up — a short-term oversold bounce.",
            0, 0.25, "williams_reversion",
            {"wr_period": wr_period, "oversold": oversold, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for cci_period, oversold, target_atr, stop_atr in (
        (20, -100, 1.0, 0.6), (14, -100, 0.9, 0.55), (20, -150, 1.1, 0.65), (30, -100, 1.2, 0.7), (14, -200, 1.0, 0.6),
    ):
        add(
            f"CCI{cci_period} Reversion <{oversold}", "mean_reversion", "15m-1h",
            f"CCI{cci_period} below {oversold} and turning up — price stretched below its statistical "
            "range, snapping back.",
            0, 0.25, "cci_reversion",
            {"cci_period": cci_period, "oversold": oversold, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for kc_period, kc_mult, stop_atr in ((20, 2.0, 0.6), (20, 1.5, 0.55), (14, 2.0, 0.5), (30, 2.5, 0.7), (14, 1.5, 0.5)):
        add(
            f"Keltner Lower Reversion {kc_period}/{kc_mult:g}", "mean_reversion", "15m-1h",
            f"Price closed below the {kc_period}/{kc_mult:g} lower Keltner band and reclaimed it — "
            "mean reversion back toward the channel mid (EMA).",
            0, 0.25, "keltner_lower_reversion",
            {"kc_period": kc_period, "kc_mult": kc_mult, "stop_atr": stop_atr},
        )
    for z_period, z_th, target_atr, stop_atr in ((20, 2.0, 1.0, 0.6), (20, 2.5, 1.1, 0.65), (30, 2.0, 1.2, 0.7), (14, 1.5, 0.9, 0.55)):
        add(
            f"Z-Score{z_period} Reversion <-{z_th:g}sd", "mean_reversion", "15m-1h",
            f"Close more than {z_th:g} sigma below its {z_period}-bar mean and ticking back up — "
            "statistical mean-reversion entry.",
            0, 0.25, "zscore_reversion",
            {"z_period": z_period, "z_th": z_th, "target_atr": target_atr, "stop_atr": stop_atr},
        )
    for gap_pct, stop_atr in ((0.5, 0.5), (0.75, 0.55), (1.0, 0.6), (1.5, 0.7)):
        add(
            f"Gap-Fill Reversion {gap_pct:.2f}%", "mean_reversion", "15m-1h",
            f"A gap down of at least {gap_pct:.2f}% that price is climbing back to fill toward "
            "yesterday's close — the fade of an over-reaction gap.",
            0, 0.25, "gap_fill_reversion",
            {"gap_pct": gap_pct, "stop_atr": stop_atr},
        )
    for near_pct, stop_buf_pct, target_atr in ((0.3, 0.5, 0.8), (0.5, 0.75, 1.0), (0.75, 1.0, 1.0), (1.0, 1.0, 1.2)):
        add(
            f"Prev-Day-Low Bounce {near_pct:.2f}%", "mean_reversion", "15m-1h",
            f"Price tested yesterday's low (within {near_pct:.2f}%) and is holding above it — a "
            "prior-support retest, stop just below the low.",
            0, 0.25, "prev_day_low_bounce",
            {"near_pct": near_pct, "stop_buf_pct": stop_buf_pct, "target_atr": target_atr},
        )

    return specs


STRATEGY_CATALOG: list[StrategySpec] = _build_catalog()
STRATEGY_BY_ID: dict[str, StrategySpec] = {s.strategy_id: s for s in STRATEGY_CATALOG}

assert len(STRATEGY_CATALOG) == 150, f"expected 150 strategies, got {len(STRATEGY_CATALOG)}"
