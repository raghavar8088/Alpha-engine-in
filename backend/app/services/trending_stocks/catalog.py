"""The Trending Stocks library: 86 long-only hypotheses x 8 timeframes = 678 strategies.

HOW THIS RELATES TO THE STRATEGY FACTORY
-----------------------------------------
The factory's 69 recipes are two-sided and sweep their own universe. This desk trades ONE
direction on the symbols the user names, so it takes the factory's recipes as a starting
library, drops the two that can only ever be short, and adds 19 long-only hypotheses of
its own. Nothing in `strategy_factory/` is modified — this module imports it.

  67 inherited long-capable recipes  (69 - descending triangle - hanging man)
+ 19 new long-only recipes           (recipes.py)
= 86 recipes x 8 timeframes
- 10 session-anchored recipes that have no meaning on a daily bar
= 678 strategies

TIMEFRAMES ARE SCALED, NOT COPIED
-----------------------------------
`TF_PROFILE` (the factory's) already scales pivots, stop lookbacks, pattern windows and
EMA lengths with the bar size. `TS_PROFILE` below extends that with the parameters the six
NEW detectors need, on the same principle: "the long-horizon high" means 250 bars on a
daily chart (one year, the 52-week high) and 750 on a 1-minute chart (two sessions). The
same NUMBER on both would be meaningless on one of them.

FINGERPRINTS ARE NAMESPACED
----------------------------
Structural identity is computed with the factory's own `fingerprint()` — which
deliberately ignores numeric parameters — and prefixed `ts:`. Collisions are checked
WITHIN this library only: the factory's 546 and this desk's 678 are allowed to describe
the same shape, because one is two-sided on its own universe and the other is long-only
on yours. What must never happen is two entries in THIS library differing only in a
constant, and that raises on import.
"""

from __future__ import annotations

from app.services.strategy_factory.catalog import (
    HTF_OF, RECIPES as FACTORY_RECIPES, TF_PROFILE, TIMEFRAMES, Recipe, Strategy,
    fingerprint as _structural_fingerprint,
)

from .detectors_ext import known_detector
from .recipes import NEW_RECIPES, SHORT_ONLY_KEYS

# Parameters the six new detectors need, scaled per timeframe. Everything else comes from
# the factory's TF_PROFILE, which this merges on top of.
#
#   high_window   the "long-horizon high" lookback. 250 daily bars IS the 52-week high;
#                 on faster charts it is the deepest high the timeframe can honestly
#                 carry given how much intraday history a broker will serve.
#   rs_window     bars over which relative strength versus the index is measured.
#   fs_window     bars searched for an RSI failure swing.
#   roc_period    rate-of-change lookback.
TS_PROFILE: dict[str, dict] = {
    "1m":  dict(high_window=750, rs_window=120, fs_window=40, roc_period=10),
    "5m":  dict(high_window=750, rs_window=100, fs_window=40, roc_period=10),
    "15m": dict(high_window=500, rs_window=80,  fs_window=36, roc_period=12),
    "30m": dict(high_window=400, rs_window=60,  fs_window=32, roc_period=12),
    "45m": dict(high_window=350, rs_window=60,  fs_window=32, roc_period=12),
    "1h":  dict(high_window=350, rs_window=60,  fs_window=30, roc_period=12),
    "4h":  dict(high_window=250, rs_window=50,  fs_window=30, roc_period=12),
    "1d":  dict(high_window=250, rs_window=60,  fs_window=30, roc_period=12),
}

# Ichimoku's 9/26/52 are bar counts, so they already scale with the chart — a kijun is 26
# bars of whatever this chart is. They are constants on purpose.
ICHIMOKU = dict(tenkan=9, kijun=26, senkou_b=52)

# Detectors that need a benchmark series (NIFTY) alongside the symbol's own bars.
BENCH_DETECTORS = {"rs_vs_bench"}

# Every strategy in this library is long. Stated once, enforced in signals.evaluate_long().
DIRECTION = "BUY"


def _inherited() -> list[Recipe]:
    """The factory's recipes minus the ones that can only ever produce a short.

    Dropped rather than kept-and-filtered: a recipe that can never fire on this desk
    would still occupy a scan slot on every bar of every backtest of every symbol, and
    would show on the leaderboard as a strategy with zero trades — indistinguishable from
    one that is simply not working."""
    return [r for r in FACTORY_RECIPES if r.key not in SHORT_ONLY_KEYS]


def _params_for(recipe: Recipe, tf: str) -> dict:
    """Timeframe profile + this desk's extra scales + the recipe's own overrides."""
    p = dict(TF_PROFILE[tf])
    p.update(TS_PROFILE[tf])
    p.update(ICHIMOKU)
    p.setdefault("stop_lookback", TF_PROFILE[tf]["stop_lookback"])
    p.setdefault("wick_mult", 2.0)
    p.setdefault("tol", 0.08)
    # `min_base` keeps the new-high detector from firing on a vertical move that makes a
    # new high on every bar: the high it clears must have stood for a while first.
    p.setdefault("min_base", max(20, TS_PROFILE[tf]["high_window"] // 8))
    p.setdefault("min_bars_required", min(120, TS_PROFILE[tf]["high_window"] // 2))
    p.setdefault("period", TS_PROFILE[tf]["roc_period"])
    p.setdefault("rs_window", TS_PROFILE[tf]["rs_window"])
    p.setdefault("fs_window", TS_PROFILE[tf]["fs_window"])
    p.setdefault("min_since_anchor", max(6, TF_PROFILE[tf]["pivot"] * 2))
    p.setdefault("vol_window", TF_PROFILE[tf]["vol_window"])
    p.update(recipe.params)          # the recipe always wins
    return p


def _confirmations_for(recipe: Recipe, tf: str) -> list[tuple[str, dict]]:
    """Fill each confirmation's timeframe-dependent defaults — identical rules to the
    factory's builder, so an inherited recipe behaves here exactly as it does there."""
    prof = TF_PROFILE[tf]
    out: list[tuple[str, dict]] = []
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
        out.append((name, merged))
    return out


def _min_bars(recipe: Recipe, params: dict) -> int:
    """The longest lookback the strategy can touch.

    Extends the factory's version with the new detectors' windows. Getting this wrong is
    not a crash — it is worse: a detector reading a truncated series returns a confident
    answer computed on data that is not there."""
    candidates = [
        params.get("window"), params.get("cup"), params.get("rounding"), params.get("rect"),
        params.get("slow"), params.get("trend"), params.get("stop_lookback", 20) * 2,
        params.get("period"), params.get("rsi_period"),
    ]
    if recipe.detector == "high_52w":
        candidates.append(params.get("high_window"))
    if recipe.detector == "rs_vs_bench":
        candidates.append(params.get("rs_window"))
    if recipe.detector == "rsi_failure_swing":
        candidates.append((params.get("fs_window") or 30) + (params.get("rsi_period") or 14))
    if recipe.detector == "ichimoku_kumo":
        candidates.append(params.get("senkou_b"))
    if recipe.detector == "vcp":
        # Needs two full volume windows to compare recent participation against earlier.
        candidates.append((params.get("vol_window") or 20) * 2)
    if recipe.detector in ("prev_period_break",) and params.get("period") == "month":
        # Two calendar months of bars, whatever this timeframe means by that.
        candidates.append(45 if params.get("trend", 0) >= 100 else 400)

    nums = [float(v) for v in candidates if isinstance(v, (int, float))]
    return max(60, int(max(nums)) + 15) if nums else 60


def _build() -> list[Strategy]:
    recipes = _inherited() + NEW_RECIPES
    out: list[Strategy] = []
    seen: dict[str, str] = {}

    for recipe in recipes:
        if not known_detector(recipe.detector):
            raise ValueError(f"recipe {recipe.key!r} names unknown detector "
                             f"{recipe.detector!r}")
        for tf in TIMEFRAMES:
            # "The opening range of a daily candle" is not a thing, and neither is its
            # session VWAP or its previous-session pivot.
            if recipe.intraday_only and tf == "1d":
                continue
            prof = TF_PROFILE[tf]
            style = prof["style"]
            fp = "ts:" + _structural_fingerprint(recipe, tf, style)
            if fp in seen:
                raise ValueError(
                    f"duplicate strategy fingerprint: {recipe.key}@{tf} collides with "
                    f"{seen[fp]} — two recipes share a hypothesis and differ only in "
                    "constants. Change what the recipe DOES, not its numbers.")
            seen[fp] = f"{recipe.key}@{tf}"

            params = _params_for(recipe, tf)
            out.append(Strategy(
                strategy_id=f"TS{len(out) + 1:04d}",
                name=f"{recipe.name} · {tf}",
                family=recipe.family,
                sub_family=recipe.sub_family,
                hypothesis=recipe.hypothesis,
                detector=recipe.detector,
                timeframe=tf,
                htf=HTF_OF[tf] if recipe.uses_htf else None,
                style=style,
                target_r=recipe.target_r,
                regimes=set(recipe.regimes),
                confirmations=_confirmations_for(recipe, tf),
                params=params,
                fingerprint=fp,
                min_bars=_min_bars(recipe, params),
            ))
    return out


LONG_CATALOG: list[Strategy] = _build()
LONG_BY_ID: dict[str, Strategy] = {s.strategy_id: s for s in LONG_CATALOG}
ALL_RECIPES: list[Recipe] = _inherited() + NEW_RECIPES

assert len(LONG_CATALOG) >= 500, f"expected 500+ strategies, built {len(LONG_CATALOG)}"
assert len({s.fingerprint for s in LONG_CATALOG}) == len(LONG_CATALOG), "fingerprint collision"
assert len(LONG_BY_ID) == len(LONG_CATALOG), "duplicate strategy_id"


def family_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for s in LONG_CATALOG:
        out[s.family] = out.get(s.family, 0) + 1
    return out


def style_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for s in LONG_CATALOG:
        out[s.style] = out.get(s.style, 0) + 1
    return out


def needs_benchmark(strategy: Strategy) -> bool:
    return strategy.detector in BENCH_DETECTORS


def bars_needed(strategy: Strategy) -> int:
    """How many bars to load so this strategy can actually be evaluated, with headroom
    for the indicator warm-up inside its detectors."""
    return max(strategy.min_bars + 60, 200)


__all__ = ["LONG_CATALOG", "LONG_BY_ID", "ALL_RECIPES", "TIMEFRAMES", "TS_PROFILE",
           "DIRECTION", "BENCH_DETECTORS", "family_counts", "style_counts",
           "needs_benchmark", "bars_needed"]
