"""The 19 long-only hypotheses this desk adds to the Strategy Factory's 67.

WHAT COUNTS AS A NEW RECIPE HERE
---------------------------------
The factory's `fingerprint()` hashes STRUCTURE — detector, the set of confirmation
dimensions, the regimes claimed, the rounded reward multiple, the timeframe and the style
— and deliberately NOT numeric parameters. That rule is load-bearing and this module
obeys it rather than working around it:

  * "Fib 38.2 / 50 / 61.8 / 78.6" is **one** structure, not four strategies. What makes a
    shallow retracement a different trade from a deep one is not the number: it is that a
    shallow pullback implies a strong trend (so it is confirmed with participation and
    trend location, and held for less) while a deep one implies a tiring trend (so it is
    confirmed with trend STRENGTH and given a larger objective, because the reversal it
    survived leaves more room). Two hypotheses, two recipes.
  * Same for pivot R1 vs R2 (one recipe, a `level` parameter) and for a 15-minute versus a
    30-minute opening range.

Any recipe below that collides with an inherited one raises `ValueError` at import. That
is the point: this library cannot fill up with cosmetic variants even by accident.

THIRTEEN OF THE NINETEEN NEED NO NEW DETECTION CODE. The factory already ships
`pivot_level_break`, `channel_break`, `roc_momentum`, `obv_breakout` and `rvol_thrust`
which **no factory recipe references**, plus `fib_retracement` used at exactly one ratio.
Those are finished, tested shapes with no hypothesis attached to them yet. Six genuinely
new shapes live in `detectors_ext.py`.
"""

from __future__ import annotations

from app.services.strategy_factory.catalog import (
    ANY_REGIME, REVERTING, TREND_UP, TRENDING, Recipe,
)

# Long-only, so a bearish regime is never a reason to trade — but "weak_bear" is not the
# same as "no longs allowed": a pullback inside a larger uptrend routinely tags it. What
# this desk refuses to do is trade a hypothesis that only pays off if price falls.
LONG_TREND = TREND_UP                    # strong_bull | weak_bull | breakout
LONG_ANY = ANY_REGIME                    # regime-agnostic (the gate still applies)


NEW_RECIPES: list[Recipe] = [

    # ---- LEVELS ---------------------------------------------------------------
    Recipe("ts_fib_shallow", "Fib Shallow Pullback", "structure", "level",
           "A 38-50% give-back in an uptrend is profit-taking, not distribution — the "
           "trend is strong enough that buyers step in before the midpoint.",
           "fib_retracement", 2.5, LONG_TREND,
           [("volume", {"mult": 1.2}), ("ema_trend", {})],
           dict(ratio=0.5, tol=0.08)),

    Recipe("ts_fib_deep", "Fib Deep Reclaim", "structure", "level",
           "A 78.6% retracement that holds and reclaims is a reversal that failed; the "
           "trend survived its hardest test, so the objective is larger.",
           "fib_retracement", 4.0, LONG_ANY,
           [("volume", {"mult": 1.3}), ("adx", {"min": 20})],
           dict(ratio=0.786, tol=0.06)),

    Recipe("ts_pivot_break", "Pivot Resistance Break", "structure", "session",
           "Floor-trader pivots are the one intraday level every desk computes the same "
           "way, so clearing R1/R2 removes orders that are genuinely there.",
           "pivot_level_break", 2.5, LONG_ANY,
           [("volume", {"mult": 1.3})],
           dict(level="R1"), intraday_only=True),

    Recipe("ts_pivot_bounce", "Pivot Support Hold", "structure", "session",
           "The same shared level read as support: price reaching S1 and turning is the "
           "cheapest long in the session because the invalidation is inches away.",
           "pivot_level_break", 2.0, LONG_TREND,
           [("rsi", {}), ("ema_trend", {})],
           dict(level="S1"), intraday_only=True),

    Recipe("ts_prev_month", "Previous Month High Break", "structure", "level",
           "A monthly extreme is a slower, better-defended level than a weekly one — it "
           "takes more to clear, so it is worth more when it goes.",
           "prev_period_break", 4.0, LONG_ANY,
           [("volume", {"mult": 1.2}), ("adx", {"min": 20})],
           dict(period="month")),

    # ---- SESSION --------------------------------------------------------------
    Recipe("ts_vwap_solo", "VWAP Reclaim", "structure", "session",
           "Reclaiming session VWAP flips who is offside intraday; taken on its own "
           "terms, with momentum rather than a higher timeframe as the check.",
           "vwap_reclaim", 2.0, LONG_ANY,
           [("volume", {"mult": 1.2}), ("rsi", {})],
           dict(stop_atr=1.0), intraday_only=True),

    Recipe("ts_first_range", "First-Range Breakout + HTF", "structure", "session",
           "The session's first range is a reference every participant shares; leaving it "
           "matters far more when the timeframe above already points the same way.",
           "opening_range", 2.5, LONG_ANY,
           [("volume", {"mult": 1.3}), ("htf_trend", {})],
           intraday_only=True, uses_htf=True),

    # ---- TREND / STRUCTURE ----------------------------------------------------
    Recipe("ts_channel_up", "Falling Channel Break", "structure", "trend",
           "Parallel rails mean an orderly decline; clearing the upper rail is the "
           "orderliness failing, which is a different event from a wedge resolving.",
           "channel_break", 3.0, LONG_ANY,
           [("volume", {"mult": 1.3}), ("adx", {"min": 18})],
           dict(parallel_tol=0.004, slope_min=0.0005)),

    Recipe("ts_mtf_pullback", "HTF Trend + LTF Pullback", "hybrid", "pullback+mtf",
           "Enter on the small chart, decide on the big one: the pullback is only worth "
           "buying while the timeframe above is still going the same way.",
           "ema_pullback", 3.5, LONG_TREND,
           [("htf_trend", {}), ("volume", {"mult": 1.1})],
           uses_htf=True),

    Recipe("ts_ichimoku", "Ichimoku Kumo Breakout", "indicator", "trend",
           "The cloud is a zone of equilibrium; leaving it upward with the conversion "
           "line above the base line is the classic statement that equilibrium broke.",
           "ichimoku_kumo", 3.0, LONG_ANY,
           [("volume", {"mult": 1.2})]),

    Recipe("ts_rsi_fs", "RSI Bullish Failure Swing", "indicator", "momentum",
           "Wilder's own confirmation: RSI refusing to make a new low on the retest is "
           "the oscillator failing to confirm itself, with no reference to price at all.",
           "rsi_failure_swing", 3.0, LONG_ANY,
           [("ema_trend", {})],
           dict(oversold=35, min_dip=3.0)),

    Recipe("ts_stoch_trend", "Stochastic Cross in Trend", "indicator", "trend",
           "The same %K/%D cross used the opposite way: not to fade an extreme, but to "
           "time re-entry while an established trend is merely resting.",
           "stochastic_cross", 3.0, LONG_TREND,
           [("ema_trend", {}), ("adx", {"min": 22})],
           dict(k=14, d=3, low=25, high=75)),

    Recipe("ts_roc_thrust", "Rate-of-Change Thrust", "indicator", "momentum",
           "Momentum measured as a rate rather than a level: the crossing itself is the "
           "event, and it happens before any moving average can register it.",
           "roc_momentum", 2.5, LONG_TREND,
           [("ema_trend", {}), ("volume", {"mult": 1.2})],
           dict(threshold=1.0)),

    # ---- VOLUME / PARTICIPATION -----------------------------------------------
    Recipe("ts_obv_lead", "OBV Leads Price", "indicator", "volume",
           "Accumulation shows up in volume before it shows up in price; OBV at a new "
           "high while price is not is somebody buying without paying up yet.",
           "obv_breakout", 3.0, LONG_ANY,
           [("ema_trend", {})]),

    Recipe("ts_rvol_cont", "Relative Volume Continuation", "structure", "volume",
           "A directional bar on outsized participation is the market repricing, and the "
           "higher timeframe says whether the repricing is with the trend or against it.",
           "rvol_thrust", 2.5, TRENDING,
           [("htf_trend", {})],
           dict(rvol=2.0, min_body=0.5), uses_htf=True),

    Recipe("ts_vcp", "Volatility Contraction Breakout", "chart", "continuation",
           "Each shallower pullback on lighter volume means one more tranche of weak "
           "holders is gone; when there is nothing left to sell, the base gives way up.",
           "vcp", 4.0, LONG_ANY,
           [("volume", {"mult": 1.4})],
           dict(contractions=3, tighten=0.75, vol_dryup=0.9)),

    # ---- LEADERSHIP -----------------------------------------------------------
    Recipe("ts_high_52w", "New High Breakout", "structure", "breakout",
           "Above a long-horizon high (the 52-week high on a daily chart) nobody is "
           "holding a loss from higher up, so the supply that normally caps a move is "
           "simply not there.",
           "high_52w", 4.0, LONG_ANY,
           [("volume", {"mult": 1.4})]),

    Recipe("ts_avwap", "Anchored VWAP Reclaim", "structure", "retest",
           "VWAP anchored to the leg's own swing low is what every buyer of this advance "
           "actually paid; reclaiming it puts them back onside and removes their supply.",
           "avwap_swing", 3.0, LONG_ANY,
           [("volume", {"mult": 1.2}), ("rsi", {})]),

    Recipe("ts_rs_leader", "Relative Strength Leadership", "hybrid", "cross-sectional",
           "Dividing the stock by the index strips out the market's move; a ratio line at "
           "a new high while price is not yet is leadership appearing before the breakout.",
           "rs_vs_bench", 3.5, LONG_ANY,
           [("ema_trend", {}), ("volume", {"mult": 1.1})]),
]


# Recipes inherited from the factory that this desk REFUSES, and why. Kept as data rather
# than a comment so `verify_catalog.py` can assert the library actually excludes them.
SHORT_ONLY_KEYS = {
    "desc_tri": "Descending Triangle only ever emits SELL — falling highs into flat "
                "support is a bearish hypothesis with no long expression.",
    "hanging_man": "Hanging Man is hammer geometry at a HIGH; it is bearish by "
                   "definition, and its long mirror is already the Hammer recipe.",
}

__all__ = ["NEW_RECIPES", "SHORT_ONLY_KEYS"]
