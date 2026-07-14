"""Intraday Strategy Lab — catalog of 50 distinctly-configured intraday equity
strategies (scalping, momentum/breakout, mean-reversion, swing-style).

Data reality check (same honesty convention as call_engine.py): this backend only
keeps *daily* bars locally for equities; true intraday (1m/5m) history is not
backfilled. So, exactly like call_engine's existing GAP-GO / PDH-BREAKOUT setups,
every "intraday" signal here is computed from (a) daily bars for trend/ATR/RSI/
Donchian context and (b) the *live* day OHLC + LTP from a single Dhan quote call
for today's actual intraday behaviour (open/high/low so far, volume so far).
Strategies are skipped honestly (no signal) when a live quote isn't available —
we never fabricate an intraday high/low from stale data.

50 strategies are produced by instantiating a handful of well-reasoned strategy
*families* with different, meaningfully distinct parameters (thresholds, ATR
multiples, lookbacks) — not 50 copies of one stub. Each StrategySpec carries a
concrete signal function bound via `family`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from strategy_service.indicators import donchian, ema, roc, rolling_vwap, rsi, stdev
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
# Catalog: 50 distinctly-configured strategies
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

    return specs


STRATEGY_CATALOG: list[StrategySpec] = _build_catalog()
STRATEGY_BY_ID: dict[str, StrategySpec] = {s.strategy_id: s for s in STRATEGY_CATALOG}

assert len(STRATEGY_CATALOG) == 50, f"expected 50 strategies, got {len(STRATEGY_CATALOG)}"
