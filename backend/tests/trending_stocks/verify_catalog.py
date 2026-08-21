"""Verify the Trending Stocks library without touching Mongo, Angel or the network.

Run:  python backend/tests/trending_stocks/verify_catalog.py

What this pins down, all of which would otherwise fail silently:

  * The library really is 500+ and really is LONG ONLY. A catalog that quietly lost its
    long-only property would still import, still backtest, and still look fine on the
    leaderboard while shorting the user's stocks.
  * No two strategies share a structural fingerprint. This is the anti-padding rule the
    brief demands in §17, and it only works if it is actually enforced.
  * The two short-only recipes are EXCLUDED rather than carried as strategies that can
    never fire — otherwise they occupy a scan slot on every bar of every backtest and
    show on the leaderboard as zero-trade strategies, indistinguishable from broken ones.
  * Timeframe parameters are SCALED, not copied. A 40-bar cup on 1m is forty minutes; on
    daily it is two months. If the profile ever collapses to one parameter set, the eight
    timeframes stop being eight different strategies.
  * `min_bars` covers the deepest lookback each detector will actually read. Getting this
    wrong is worse than a crash: a detector reading a truncated series returns a confident
    answer computed on data that is not there.
"""

import sys
from pathlib import Path

# Import the real `app.services.*` — this module needs the actual Strategy Factory
# primitives and the tested commodity pattern library, not stubs. None of them touch
# Mongo, Angel or the network at import time, which is what makes that safe here.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.trending_stocks.catalog import (
    LONG_BY_ID, LONG_CATALOG, TS_PROFILE, bars_needed, family_counts, needs_benchmark,
    style_counts,
)
from app.services.trending_stocks.detectors_ext import known_detector
from app.services.trending_stocks.recipes import NEW_RECIPES, SHORT_ONLY_KEYS
from app.services.strategy_factory.catalog import RECIPES as FACTORY_RECIPES, TF_PROFILE

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


print("\n== size and shape ==")
check("500+ strategies", len(LONG_CATALOG) >= 500, f"{len(LONG_CATALOG)} built")
check("86 recipes (67 inherited + 19 new)",
      len(FACTORY_RECIPES) - len(SHORT_ONLY_KEYS) + len(NEW_RECIPES) == 86,
      f"{len(FACTORY_RECIPES)} factory - {len(SHORT_ONLY_KEYS)} short-only + {len(NEW_RECIPES)} new")
check("19 new long-only recipes", len(NEW_RECIPES) == 19, f"{len(NEW_RECIPES)}")
check("unique strategy ids", len(LONG_BY_ID) == len(LONG_CATALOG))
check("every family represented", len(family_counts()) == 5, str(family_counts()))
check("every style represented", len(style_counts()) == 4, str(style_counts()))

print("\n== long only ==")
short_keys_present = [s for s in LONG_CATALOG
                      if any(s.name.startswith(k) for k in ("Descending Triangle", "Hanging Man"))]
check("no descending-triangle or hanging-man strategies", not short_keys_present,
      f"{len(short_keys_present)} found")
check("both short-only recipes are documented with a reason",
      all(isinstance(v, str) and len(v) > 30 for v in SHORT_ONLY_KEYS.values()))

print("\n== fingerprints (the anti-padding rule) ==")
fps = [s.fingerprint for s in LONG_CATALOG]
check("no duplicate fingerprints", len(set(fps)) == len(fps),
      f"{len(fps) - len(set(fps))} collisions")
check("all namespaced to this desk", all(f.startswith("ts:") for f in fps))

print("\n== detectors resolve ==")
unknown = sorted({s.detector for s in LONG_CATALOG if not known_detector(s.detector)})
check("every detector named by a recipe exists", not unknown, str(unknown))
bench = {s.detector for s in LONG_CATALOG if needs_benchmark(s)}
check("relative strength is the only benchmark-dependent detector",
      bench == {"rs_vs_bench"}, str(bench))

print("\n== timeframes are scaled, not copied ==")
by_tf: dict[str, set] = {}
for s in LONG_CATALOG:
    by_tf.setdefault(s.timeframe, set()).add(
        (s.params.get("window"), s.params.get("trend"), s.params.get("high_window")))
check("8 timeframes present", len(by_tf) == 8, str(sorted(by_tf)))
check("1m and 1d use different lookbacks",
      TF_PROFILE["1m"]["window"] != TF_PROFILE["1d"]["window"]
      and TS_PROFILE["1m"]["high_window"] != TS_PROFILE["1d"]["high_window"],
      f"1m window {TF_PROFILE['1m']['window']} vs 1d {TF_PROFILE['1d']['window']}; "
      f"high_window {TS_PROFILE['1m']['high_window']} vs {TS_PROFILE['1d']['high_window']}")
check("the 52-week high really is 250 daily bars", TS_PROFILE["1d"]["high_window"] == 250)

print("\n== session-anchored strategies are not built on daily bars ==")
session_on_daily = [s for s in LONG_CATALOG if s.timeframe == "1d"
                    and s.detector in ("opening_range", "vwap_reclaim", "pivot_level_break",
                                       "gap_continuation", "prior_session_break")]
check("no opening range / VWAP / pivot strategy on 1d", not session_on_daily,
      f"{len(session_on_daily)} found")

print("\n== min_bars covers the deepest lookback ==")
bad = []
for s in LONG_CATALOG:
    deepest = max([v for v in (s.params.get("window"), s.params.get("trend"),
                               s.params.get("slow"), s.params.get("cup"),
                               s.params.get("high_window") if s.detector == "high_52w" else None,
                               s.params.get("rs_window") if s.detector == "rs_vs_bench" else None,
                               s.params.get("senkou_b") if s.detector == "ichimoku_kumo" else None)
                   if isinstance(v, (int, float))] or [0])
    if s.min_bars < deepest:
        bad.append(f"{s.strategy_id} {s.detector} min_bars {s.min_bars} < {deepest}")
check("every strategy's min_bars >= its deepest window", not bad, "; ".join(bad[:3]))
check("bars_needed always leaves warm-up headroom",
      all(bars_needed(s) > s.min_bars for s in LONG_CATALOG))

print("\n== hypotheses are written, not generated ==")
short_hyp = [s.strategy_id for s in LONG_CATALOG if len(s.hypothesis) < 40]
check("every strategy carries a real hypothesis", not short_hyp, f"{len(short_hyp)} too short")

print(f"\n{len(LONG_CATALOG)} strategies · {family_counts()} · {style_counts()}")
print(f"\n{'ALL CHECKS PASSED' if not FAILURES else 'FAILURES: ' + ', '.join(FAILURES)}")
sys.exit(1 if FAILURES else 0)
