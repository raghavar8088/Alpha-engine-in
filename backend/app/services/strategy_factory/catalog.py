"""The Strategy Factory catalog: 69 recipes x 8 timeframes = 500+ strategies.

A RECIPE IS A HYPOTHESIS, NOT A PARAMETER SET
----------------------------------------------
Each recipe pairs one setup detector with confirmations that test a DIFFERENT dimension
of the same idea — participation, momentum, trend location, trend strength, volatility,
or a higher timeframe — plus the market regimes it claims to work in and the reward
multiple its own logic supports. Two entries that differ only in a constant are not two
strategies, so `fingerprint()` deliberately hashes the STRUCTURE (detector, confirmation
set, regimes, rounded reward multiple, timeframe, style) and NOT the numeric parameters.
A duplicated hypothesis therefore collides and the module refuses to import.

TIMEFRAMES ARE PARAMETERISED, NOT COPIED
-----------------------------------------
The same recipe on 1m and on 1d is not the same strategy with the same numbers: swing
pivots, stop lookbacks, pattern windows and EMA lengths all scale with the bar size via
`TF_PROFILE`. A 40-bar cup on 1m is forty minutes; on daily it is two months. Copying one
parameter set across eight timeframes is exactly the cosmetic padding this catalog is
built to avoid.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

TIMEFRAMES = ["1m", "5m", "15m", "30m", "45m", "1h", "4h", "1d"]

# Higher timeframe used for confirmation, per entry timeframe. Roughly 4-6x the entry
# bar: close enough to be relevant, far enough to be a genuinely different view.
HTF_OF = {"1m": "15m", "5m": "30m", "15m": "1h", "30m": "4h",
          "45m": "4h", "1h": "4h", "4h": "1d", "1d": "1d"}

# Per-timeframe parameter profile. Lookbacks shrink on fast bars and stretch on slow ones
# so a "swing pivot" means a comparable amount of market time on every chart.
TF_PROFILE: dict[str, dict] = {
    "1m":  dict(pivot=3, stop_lookback=10, window=20, cup=40, rounding=30, rect=20,
                fast=9,  slow=21, trend=50,  rsi_period=14, vol_window=20, style="scalp"),
    "5m":  dict(pivot=3, stop_lookback=12, window=24, cup=45, rounding=35, rect=24,
                fast=9,  slow=21, trend=50,  rsi_period=14, vol_window=20, style="scalp"),
    "15m": dict(pivot=3, stop_lookback=14, window=30, cup=50, rounding=40, rect=28,
                fast=10, slow=21, trend=50,  rsi_period=14, vol_window=20, style="intraday"),
    "30m": dict(pivot=4, stop_lookback=16, window=32, cup=55, rounding=45, rect=30,
                fast=10, slow=30, trend=50,  rsi_period=14, vol_window=20, style="intraday"),
    "45m": dict(pivot=4, stop_lookback=16, window=34, cup=55, rounding=45, rect=30,
                fast=10, slow=30, trend=50,  rsi_period=14, vol_window=20, style="intraday"),
    "1h":  dict(pivot=4, stop_lookback=18, window=36, cup=60, rounding=48, rect=32,
                fast=12, slow=30, trend=100, rsi_period=14, vol_window=20, style="swing"),
    "4h":  dict(pivot=5, stop_lookback=20, window=40, cup=60, rounding=50, rect=36,
                fast=12, slow=34, trend=100, rsi_period=14, vol_window=20, style="swing"),
    "1d":  dict(pivot=5, stop_lookback=22, window=45, cup=60, rounding=55, rect=40,
                fast=20, slow=50, trend=200, rsi_period=14, vol_window=20, style="positional"),
}

TREND_UP = {"strong_bull", "weak_bull", "breakout"}
TREND_DN = {"strong_bear", "weak_bear", "breakout"}
TRENDING = TREND_UP | TREND_DN
REVERTING = {"sideways", "mean_reversion", "low_volatility"}
ANY_REGIME: set[str] = set()


@dataclass
class Recipe:
    key: str
    name: str
    family: str            # chart | candlestick | structure | indicator | hybrid
    sub_family: str
    hypothesis: str
    detector: str
    target_r: float
    regimes: set[str] = field(default_factory=set)
    confirmations: list[tuple[str, dict]] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    intraday_only: bool = False
    uses_htf: bool = False


@dataclass
class Strategy:
    strategy_id: str
    name: str
    family: str
    sub_family: str
    hypothesis: str
    detector: str
    timeframe: str
    htf: str | None
    style: str
    target_r: float
    regimes: set[str]
    confirmations: list[tuple[str, dict]]
    params: dict
    fingerprint: str
    min_bars: int


def _p(tf: str, **over) -> dict:
    """Timeframe profile merged with recipe-specific overrides."""
    base = dict(TF_PROFILE[tf])
    base.update(over)
    return base


# --------------------------------------------------------------------------------
# Recipes
# --------------------------------------------------------------------------------

RECIPES: list[Recipe] = [
    # ---- CHART (13) -----------------------------------------------------------
    Recipe("hns", "Head & Shoulders", "chart", "reversal",
           "A failed third push after a dominant middle peak marks distribution; the neckline break confirms it.",
           "head_shoulders", 3.0, TRENDING, [("volume", {"mult": 1.3})]),
    Recipe("double_tb", "Double Top / Bottom", "chart", "reversal",
           "Two rejections at one level means supply/demand is stacked there; losing the neckline releases it.",
           "double_top_bottom", 2.5, TRENDING, [("volume", {"mult": 1.3})]),
    Recipe("triple_tb", "Triple Top / Bottom", "chart", "reversal",
           "Three rejections is a stronger claim than two, so the break deserves a wider objective.",
           "triple_top_bottom", 3.0, TRENDING, [("volume", {"mult": 1.3}), ("rsi", {})]),
    Recipe("asc_tri", "Ascending Triangle", "chart", "continuation",
           "Rising lows into flat resistance means buyers pay up while sellers hold one price; the level eventually gives.",
           "ascending_triangle", 2.5, TREND_UP, [("volume", {"mult": 1.4})]),
    Recipe("desc_tri", "Descending Triangle", "chart", "continuation",
           "Falling highs into flat support is the mirror: sellers keep pressing while one bid holds.",
           "descending_triangle", 2.5, TREND_DN, [("volume", {"mult": 1.4})]),
    Recipe("sym_tri", "Symmetrical Triangle", "chart", "continuation",
           "Both boundaries converging is coiling energy; direction is unknown until the break.",
           "symmetrical_triangle", 2.5, ANY_REGIME, [("atr_expansion", {})]),
    Recipe("wedge", "Rising / Falling Wedge", "chart", "reversal",
           "A wedge advances on shrinking range — momentum is decaying, so it resolves against its own slope.",
           "wedge", 3.0, ANY_REGIME, [("rsi", {})]),
    Recipe("flag", "Bull / Bear Flag", "chart", "continuation",
           "A sharp pole then an orderly counter-drift is a pause, not a turn; the trend resumes.",
           "flag", 2.0, TRENDING, [("volume", {"mult": 1.2}), ("ema_trend", {})]),
    Recipe("pennant", "Pennant", "chart", "continuation",
           "Same as a flag but the pause converges, tightening the spring before continuation.",
           "pennant", 2.0, TRENDING, [("atr_expansion", {})]),
    Recipe("cup_handle", "Cup & Handle", "chart", "continuation",
           "A rounded base rebuilds a bid; the shallow handle shakes out the impatient before the rim goes.",
           "cup_handle", 4.0, TREND_UP, [("volume", {"mult": 1.3})]),
    Recipe("rounding", "Rounding Top / Bottom", "chart", "reversal",
           "A slow arc rather than a spike means the turn is gradual and broad — a bigger objective.",
           "rounding", 4.0, ANY_REGIME, [("ema_trend", {})]),
    Recipe("diamond", "Diamond", "chart", "reversal",
           "Range expands then contracts — confusion followed by resolution, which usually reverses the prior move.",
           "diamond", 3.0, ANY_REGIME, [("atr_expansion", {})]),
    Recipe("broadening", "Broadening Formation", "chart", "range",
           "A megaphone has no clean breakout to chase, so the rails are faded rather than followed.",
           "broadening", 1.5, REVERTING | {"high_volatility"}, []),

    # ---- CANDLESTICK (13) -----------------------------------------------------
    Recipe("engulfing", "Engulfing Candle", "candlestick", "reversal",
           "One bar erasing the prior body is a decisive transfer of control within a single period.",
           "engulfing", 2.0, ANY_REGIME, [("ema_trend", {})]),
    Recipe("hammer_star", "Hammer / Shooting Star", "candlestick", "reversal",
           "A long wick is rejection: price went there and was refused.",
           "hammer_star", 2.0, ANY_REGIME, [("rsi", {})]),
    Recipe("inv_hammer", "Inverted Hammer", "candlestick", "reversal",
           "An upper-wick bar at a low is a probe that found buyers on the retrace — exhaustion of the decline.",
           "inverted_hammer", 2.0, ANY_REGIME, [("volume", {"mult": 1.2})]),
    Recipe("hanging_man", "Hanging Man", "candlestick", "reversal",
           "Hammer geometry at a HIGH: the same shape means the opposite because of where it appears.",
           "hanging_man", 2.0, TREND_UP, [("ema_trend", {})]),
    Recipe("doji", "Doji Reversal", "candlestick", "reversal",
           "A body near zero at an extreme is indecision exactly where conviction was needed.",
           "doji_reversal", 2.0, ANY_REGIME, [("rsi", {})]),
    Recipe("marubozu", "Marubozu Continuation", "candlestick", "continuation",
           "No wick at either end means no rejection anywhere in the period — pure one-sided flow.",
           "marubozu", 2.0, TRENDING, [("volume", {"mult": 1.3})]),
    Recipe("inside_bar", "Inside Bar Breakout", "candlestick", "breakout",
           "A bar contained by its predecessor is compression; the mother-bar break releases it.",
           "inside_bar", 2.5, ANY_REGIME, [("atr_expansion", {})]),
    Recipe("multi_inside", "Multi Inside Bar Compression", "candlestick", "breakout",
           "Several tightening inside bars is a stronger coil than one, and deserves a larger objective.",
           "multi_inside", 3.0, ANY_REGIME, [("volume", {"mult": 1.3})], dict(min_inside=2)),
    Recipe("outside_bar", "Outside Bar Reversal", "candlestick", "reversal",
           "Taking both sides of the prior bar and closing decisively is a completed sweep.",
           "outside_bar", 2.0, ANY_REGIME, [("volume", {"mult": 1.2})]),
    Recipe("soldiers", "Three Soldiers / Crows", "candlestick", "continuation",
           "Three consecutive extending closes is persistence, not a single impulse.",
           "soldiers_crows", 2.5, TRENDING, [("ema_trend", {})]),
    Recipe("star", "Morning / Evening Star", "candlestick", "reversal",
           "Thrust, pause, reversal past the midpoint — a three-bar handover of control.",
           "star", 2.5, ANY_REGIME, [("volume", {"mult": 1.2})]),
    Recipe("pin_bar", "Pin Bar at Extreme", "candlestick", "reversal",
           "A dominant rejection wick precisely at a swing extreme, aligned with the higher timeframe.",
           "pin_bar", 2.5, ANY_REGIME, [("htf_trend", {})], uses_htf=True),
    Recipe("ha_flip", "Heikin Ashi Flip", "candlestick", "reversal",
           "Smoothed candles change colour only when the short-term drift genuinely turns.",
           "heikin_flip", 2.5, ANY_REGIME, [("adx", {"min": 18})]),

    # ---- PRICE STRUCTURE (18) --------------------------------------------------
    Recipe("donch_fast", "Donchian Breakout (fast)", "structure", "breakout",
           "A new short-window extreme is the simplest evidence the balance has broken.",
           "donchian_fast", 2.5, TRENDING, [("volume", {"mult": 1.3})]),
    Recipe("donch_slow", "Donchian Breakout (slow)", "structure", "breakout",
           "A long-window extreme is a rarer, more meaningful break and is held for more.",
           "donchian_slow", 3.5, TRENDING, [("adx", {"min": 22})]),
    Recipe("keltner", "Keltner Breakout", "structure", "breakout",
           "Closing outside a volatility envelope means the move exceeds normal noise for this instrument.",
           "keltner_break", 2.5, TRENDING, [("atr_expansion", {})]),
    Recipe("pctb", "Bollinger %B Extreme", "structure", "mean_reversion",
           "A close outside the band is a statistical stretch that usually retraces toward the mean.",
           "bollinger_pctb", 1.5, REVERTING, [("rsi", {})]),
    Recipe("prior_session", "Prior Session High/Low Break", "structure", "breakout",
           "Yesterday's extreme is the reference every intraday participant shares.",
           "prior_session_break", 2.5, ANY_REGIME, [("volume", {"mult": 1.2})], intraday_only=True),
    Recipe("round_number", "Round Number Break", "structure", "breakout",
           "Round levels attract resting orders; clearing one removes a visible barrier.",
           "round_number_break", 2.0, ANY_REGIME, [("volume", {"mult": 1.3})]),
    Recipe("bb_squeeze", "Bollinger Squeeze Release", "structure", "volatility",
           "Volatility mean-reverts: a multi-bar width minimum is followed by expansion.",
           "bollinger_squeeze", 3.0, ANY_REGIME, [("volume", {"mult": 1.3})]),
    Recipe("ttm", "TTM Squeeze", "structure", "volatility",
           "Bollinger bands inside the Keltner channel is the same compression, measured against volatility rather than itself.",
           "ttm_squeeze", 3.0, ANY_REGIME, [("macd", {})]),
    Recipe("ribbon", "EMA Ribbon Compression", "structure", "volatility",
           "When every EMA converges the market has no trend memory; the exit from that band starts one.",
           "ema_ribbon", 3.0, ANY_REGIME, [("adx", {"min": 20})]),
    Recipe("atr_thrust", "ATR Expansion Thrust", "structure", "volatility",
           "A bar several ATRs wide is an information event, and information tends to trend briefly.",
           "atr_thrust", 2.0, ANY_REGIME, [("volume", {"mult": 1.5})]),
    Recipe("hh_hl", "HH/HL Structure Shift", "structure", "trend",
           "The swing sequence flipping is the textbook definition of a trend change.",
           "hh_hl_shift", 3.0, ANY_REGIME, [("ema_trend", {})]),
    Recipe("bos", "Break of Structure", "structure", "trend",
           "Taking out the last swing WITH the sequence is continuation, not reversal.",
           "break_of_structure", 3.0, TRENDING, [("volume", {"mult": 1.2})]),
    Recipe("choch", "Change of Character", "structure", "reversal",
           "The first break AGAINST an established sequence is the earliest objective warning.",
           "change_of_character", 3.0, ANY_REGIME, [("volume", {"mult": 1.3})]),
    Recipe("sr_flip", "Support / Resistance Flip", "structure", "retest",
           "A broken level that holds on the retest proves the break was real; entering there is cheaper than chasing.",
           "sr_flip", 3.0, ANY_REGIME, [("volume", {"mult": 1.1})], dict(tol_atr=0.5)),
    Recipe("orb", "Opening Range Breakout", "structure", "session",
           "The first bars set the session's reference range; leaving it commits the day's direction.",
           "opening_range", 2.0, ANY_REGIME, [("volume", {"mult": 1.3})], intraday_only=True),
    Recipe("ema_pullback", "Trend Pullback to EMA", "structure", "trend",
           "Trends retrace to a moving average and resume; buying the pullback beats buying the extension.",
           "ema_pullback", 3.0, TRENDING, [("rsi", {})]),
    Recipe("prev_week", "Previous Week High/Low Break", "structure", "level",
           "The weekly extreme is the swing trader's reference and a slower, cleaner level than the daily one.",
           "prev_period_break", 3.0, ANY_REGIME, [("volume", {"mult": 1.2})], dict(period="week")),
    Recipe("rect", "Rectangle / Trading Range Break", "structure", "breakout",
           "A range that has contained price projects its own height on the break.",
           "rectangle_break", 2.5, ANY_REGIME, [("volume", {"mult": 1.3})],
           dict(contain=0.01, max_band=0.25)),

    # ---- INDICATOR (13) --------------------------------------------------------
    Recipe("ema_cross_fast", "EMA Crossover (fast)", "indicator", "trend",
           "A short-EMA cross is the earliest systematic read that short-term drift has changed sign.",
           "ema_cross", 2.5, ANY_REGIME, [("adx", {"min": 20})], dict(label="EMA Crossover")),
    Recipe("golden_cross", "Golden / Death Cross", "indicator", "trend",
           "The 50/200 cross is a regime statement, not a signal — held far longer and sized for it.",
           "ema_cross", 4.0, ANY_REGIME, [], dict(fast=50, slow=200, label="Golden / Death Cross")),
    Recipe("rsi_regime", "RSI Trend Regime (40/60)", "indicator", "momentum",
           "In trends RSI oscillates in the upper half; crossing 60 marks expansion, not an exit.",
           "rsi_regime", 3.0, ANY_REGIME, [("ema_trend", {})], dict(up=60, down=40)),
    Recipe("rsi_extreme", "RSI Overbought / Oversold Reversal", "indicator", "mean_reversion",
           "The classic 30/70 read, taken only as it turns back OUT of the extreme.",
           "rsi_extreme", 1.5, REVERTING, [], dict(low=30, high=70)),
    Recipe("rsi_div", "RSI Divergence", "indicator", "reversal",
           "A new price extreme unconfirmed by momentum means the move is running on fewer participants.",
           "rsi_divergence", 3.0, ANY_REGIME, [("volume", {"mult": 1.1})]),
    Recipe("macd_cross", "MACD Signal Cross", "indicator", "trend",
           "The signal cross is a smoothed momentum handover, slower and less noisy than a price cross.",
           "macd_cross", 2.5, ANY_REGIME, [("ema_trend", {})], dict(fast=12, slow=26, signal=9)),
    Recipe("macd_hist", "MACD Histogram Turn", "indicator", "momentum",
           "The histogram turns before the lines cross — earlier and noisier, a different trade-off.",
           "macd_histogram", 2.0, ANY_REGIME, [("rsi", {})], dict(fast=12, slow=26, signal=9)),
    Recipe("di_cross", "ADX / DI Cross", "indicator", "trend",
           "DI crossing says direction; ADX says whether direction is worth trading at all.",
           "adx_di_cross", 3.0, TRENDING, [], dict(period=14, adx_min=22)),
    Recipe("supertrend", "Supertrend Flip", "indicator", "trend",
           "A volatility-anchored trend rail flips rarely, so each flip carries more information.",
           "supertrend_flip", 3.0, ANY_REGIME, [("ema_trend", {})], dict(period=10, mult=3.0)),
    Recipe("psar", "Parabolic SAR Flip", "indicator", "trend",
           "SAR tightens behind a trend and flips on the first real pause.",
           "psar_flip", 2.5, TRENDING, [("adx", {"min": 20})], dict(step=0.02, max_step=0.2)),
    Recipe("stoch", "Stochastic Cross", "indicator", "mean_reversion",
           "%K crossing %D inside an extreme zone times the turn better than the zone alone.",
           "stochastic_cross", 1.5, REVERTING, [], dict(k=14, d=3, low=25, high=75)),
    Recipe("williams", "Williams %R Reversal", "indicator", "mean_reversion",
           "A close-relative-to-range oscillator; its turn out of an extreme is a distinct read from RSI's.",
           "williams_reversal", 1.5, REVERTING, [("rsi", {})], dict(period=14, low=-80, high=-20)),
    Recipe("cci", "CCI Breakout", "indicator", "momentum",
           "CCI leaving +/-100 marks a statistically unusual deviation from the typical price.",
           "cci_breakout", 2.5, ANY_REGIME, [("volume", {"mult": 1.2})], dict(period=20, level=100)),

    # ---- HYBRID / MULTI-CONDITION (12) ----------------------------------------
    Recipe("hyb_flag_htf", "Flag + Volume + HTF Trend", "hybrid", "chart+volume+mtf",
           "A continuation pattern is only worth taking in the direction the higher timeframe is already going.",
           "flag", 3.0, TRENDING,
           [("volume", {"mult": 1.4}), ("htf_trend", {})], uses_htf=True),
    Recipe("hyb_donch_htf", "Breakout + Volume + HTF Trend", "hybrid", "breakout+volume+mtf",
           "Breakouts against the higher-timeframe trend are the ones that fail; this filters them out.",
           "donchian_fast", 3.0, TRENDING,
           [("volume", {"mult": 1.4}), ("htf_trend", {})], uses_htf=True),
    Recipe("hyb_pullback", "Pullback + EMA + RSI + VWAP", "hybrid", "pullback+multi",
           "A pullback is worth buying when trend, momentum and the session benchmark all still agree.",
           "ema_pullback", 3.0, TRENDING,
           [("rsi", {}), ("vwap", {})], intraday_only=True),
    Recipe("hyb_squeeze", "Squeeze + Momentum + Volume", "hybrid", "volatility+momentum",
           "Compression says a move is coming; momentum and volume say which way and whether anyone is behind it.",
           "bollinger_squeeze", 3.5, ANY_REGIME,
           [("macd", {}), ("volume", {"mult": 1.4})]),
    Recipe("hyb_bos_retest", "Structure Break + Volume + HTF", "hybrid", "structure+mtf",
           "A break of structure confirmed by participation and by the timeframe above it.",
           "break_of_structure", 3.5, TRENDING,
           [("volume", {"mult": 1.3}), ("htf_trend", {})], uses_htf=True),
    Recipe("hyb_srflip_vol", "S/R Flip Retest + Volume", "hybrid", "retest+volume",
           "The retest entry, taken only when the hold happens on real participation.",
           "sr_flip", 3.5, ANY_REGIME,
           [("volume", {"mult": 1.2})], dict(tol_atr=0.4)),
    Recipe("hyb_engulf_vwap", "Engulfing + VWAP + Volume", "hybrid", "candle+vwap",
           "A reversal candle matters far more when it happens on the right side of the session benchmark.",
           "engulfing", 2.5, ANY_REGIME,
           [("vwap", {}), ("volume", {"mult": 1.3})], intraday_only=True),
    Recipe("hyb_pin_trend", "Pin Bar + Trend + ADX", "hybrid", "candle+trend",
           "Rejection wicks in the direction of an established, strong trend are continuation entries.",
           "pin_bar", 3.0, TRENDING,
           [("ema_trend", {}), ("adx", {"min": 22})]),
    Recipe("hyb_vwap_reclaim", "VWAP Reclaim + Volume + HTF", "hybrid", "session+mtf",
           "Reclaiming VWAP flips who is offside intraday; the higher timeframe says whether it will stick.",
           "vwap_reclaim", 2.5, ANY_REGIME,
           [("volume", {"mult": 1.2}), ("htf_trend", {})], dict(stop_atr=1.0),
           intraday_only=True, uses_htf=True),
    Recipe("hyb_gap_cont", "Gap Continuation + Volume", "hybrid", "session+volume",
           "A gap that keeps going is a repricing; one that fades was an overreaction — this trades the former.",
           "gap_continuation", 2.5, ANY_REGIME,
           [("volume", {"mult": 1.3})], dict(min_gap=0.004), intraday_only=True),
    Recipe("hyb_fib_htf", "Fib 61.8% + RSI + HTF Trend", "hybrid", "level+mtf",
           "The deepest retracement that still respects the trend, taken only with the higher timeframe.",
           "fib_retracement", 3.0, TRENDING,
           [("rsi", {}), ("htf_trend", {})], dict(ratio=0.618, tol=0.08), uses_htf=True),
    Recipe("hyb_rect_vol", "Rectangle + Volume + ATR", "hybrid", "range+volatility",
           "A range break is only real when both participation and volatility expand with it.",
           "rectangle_break", 3.0, ANY_REGIME,
           [("volume", {"mult": 1.4}), ("atr_expansion", {})], dict(contain=0.01, max_band=0.25)),
]


def fingerprint(recipe: Recipe, timeframe: str, style: str) -> str:
    """Structural identity — deliberately EXCLUDES numeric parameters.

    Changing RSI 29 to RSI 30 does not make a new strategy, so it must not make a new
    fingerprint. What counts is which setup, which confirmation dimensions, which
    regimes, roughly what reward multiple, and on what timeframe."""
    parts = [
        recipe.detector,
        ",".join(sorted(name for name, _ in recipe.confirmations)),
        ",".join(sorted(recipe.regimes)) or "any",
        f"{round(recipe.target_r, 1)}",
        timeframe,
        style,
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _min_bars(recipe: Recipe, prof: dict) -> int:
    """Longest lookback the strategy can touch, so the engine can skip a short series
    rather than letting a detector read a truncated one."""
    raw = [prof.get("window", 30), prof.get("cup", 40), prof.get("rounding", 40),
           prof.get("rect", 30), prof.get("slow", 50), prof.get("trend", 50),
           recipe.params.get("slow"), recipe.params.get("period"),
           prof.get("stop_lookback", 20) * 2]
    # `period` is a STRING on the week/month recipe ("week"), so filter to numbers rather
    # than assuming every parameter named period is a bar count.
    nums = [float(v) for v in raw if isinstance(v, (int, float))]
    return max(60, int(max(nums)) + 15) if nums else 60


def _build() -> list[Strategy]:
    out: list[Strategy] = []
    seen: dict[str, str] = {}
    for recipe in RECIPES:
        for tf in TIMEFRAMES:
            # Session-based ideas have no meaning on a daily bar: "the opening range" or
            # "session VWAP" of a single daily candle is not a thing.
            if recipe.intraday_only and tf in ("1d",):
                continue
            prof = TF_PROFILE[tf]
            style = prof["style"]
            fp = fingerprint(recipe, tf, style)
            if fp in seen:
                raise ValueError(
                    f"duplicate strategy fingerprint: {recipe.key}@{tf} collides with {seen[fp]} "
                    "— two recipes share a hypothesis and differ only in constants"
                )
            seen[fp] = f"{recipe.key}@{tf}"

            params = _p(tf, **recipe.params)
            # Detector-facing aliases so one profile feeds differently-named parameters.
            params.setdefault("stop_lookback", prof["stop_lookback"])
            params.setdefault("wick_mult", 2.0)
            params.setdefault("tol", params.get("tol", 0.08))
            confirmations = []
            for name, cp in recipe.confirmations:
                merged = dict(cp)
                if name == "volume":
                    merged.setdefault("window", prof["vol_window"])
                elif name == "rsi":
                    merged.setdefault("period", prof["rsi_period"])
                elif name == "ema_trend":
                    merged.setdefault("period", prof["trend"])
                elif name == "htf_trend":
                    merged.setdefault("fast", 20)
                    merged.setdefault("slow", 50)
                    merged.setdefault("label", HTF_OF[tf])
                confirmations.append((name, merged))

            out.append(Strategy(
                strategy_id=f"SF{len(out) + 1:04d}",
                name=f"{recipe.name} · {tf}",
                family=recipe.family, sub_family=recipe.sub_family,
                hypothesis=recipe.hypothesis, detector=recipe.detector,
                timeframe=tf, htf=HTF_OF[tf] if recipe.uses_htf else None,
                style=style, target_r=recipe.target_r, regimes=set(recipe.regimes),
                confirmations=confirmations, params=params, fingerprint=fp,
                min_bars=_min_bars(recipe, prof),
            ))
    return out


FACTORY_CATALOG: list[Strategy] = _build()
FACTORY_BY_ID: dict[str, Strategy] = {s.strategy_id: s for s in FACTORY_CATALOG}

assert len(FACTORY_CATALOG) >= 500, f"expected 500+ strategies, built {len(FACTORY_CATALOG)}"
assert len({s.fingerprint for s in FACTORY_CATALOG}) == len(FACTORY_CATALOG), "fingerprint collision"
assert len(FACTORY_BY_ID) == len(FACTORY_CATALOG), "duplicate strategy_id"


def family_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for s in FACTORY_CATALOG:
        out[s.family] = out.get(s.family, 0) + 1
    return out


__all__ = ["FACTORY_CATALOG", "FACTORY_BY_ID", "RECIPES", "Strategy", "Recipe",
           "TIMEFRAMES", "HTF_OF", "TF_PROFILE", "family_counts", "fingerprint"]
