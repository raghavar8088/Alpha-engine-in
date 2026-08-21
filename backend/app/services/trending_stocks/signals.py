"""The one decision function this desk has — used by the backtest and by the paper desk.

ONE IMPLEMENTATION, TWO CALLERS, NO EXCEPTIONS
-----------------------------------------------
`evaluate_long()` is the only place a Trending Stocks strategy decides anything. The
replay in `backtest.py` hands it a historical slice; the paper engine hands it the live
slice. There is deliberately no second code path, because the moment backtest logic and
live logic exist twice they drift, and every number the backtest produced stops describing
what the desk will actually do.

It is a DROP-IN for the factory's `evaluate()`: same positional signature, same return
shape `(Signal | None, Rejection | None)`. That is what lets the shared no-look-ahead
replay in `strategy_factory.backtest` drive this desk without a forked copy of the replay
existing anywhere.

WHAT IT ADDS OVER THE FACTORY'S VERSION
----------------------------------------
  * **Long only.** A `SELL` setup is REJECTED, not silently dropped — recorded with its
    own stage so the ledger can say "we declined 340 setups purely for being shorts",
    which looks nothing like "no setups were found".
  * **Context-aware detection.** Relative strength needs a benchmark series; `detect_ext`
    threads it through without changing the factory's detector contract.
  * **The 1:6 gate.** Levels come from `feasibility.assess()`, not from the recipe's own
    reward multiple, so the target on the signal IS the target the desk will trade and the
    backtest will replay.

The caller controls what the function can see by choosing the slice it passes. There is no
global data access inside, no clock and no I/O — pass `bars[:i+1]` and it physically
cannot read bar i+1. The benchmark series is sliced by TIMESTAMP against the last bar for
exactly the same reason.
"""

from __future__ import annotations

from bisect import bisect_right
from typing import Callable, Optional

from strategy_service.indicators import atr as atr_series

from app.services.strategy_factory.confirmations import check_all
from app.services.strategy_factory.primitives import RegimeState, classify_regime
from app.services.strategy_factory.signals import Rejection, Signal

from .catalog import needs_benchmark
from .detectors_ext import detect_ext
from .feasibility import Feasibility, assess

# Rejection stages, so the No-Trade ledger groups on a fixed vocabulary rather than on
# whatever string happened to be written that day.
STAGE_BARS = "bars"
STAGE_REGIME = "regime"
STAGE_DETECTOR = "detector"
STAGE_DIRECTION = "direction"
STAGE_CONFIRMATION = "confirmation"
STAGE_LEVELS = "levels"
STAGE_FEASIBILITY = "feasibility"


def _confidence(strategy, regime: RegimeState, confirmations: list[str],
                feas: Feasibility) -> float:
    """A bounded, explainable score — not a probability.

    Starts from how many INDEPENDENT confirmations had to pass, nudged up when the market
    is actually in one of the regimes the strategy claims, and up again when the geometry
    was clean: a structural stop and a path to target with no known supply in it. A signal
    that had to be squeezed through the gate is not as good as one that walked through."""
    score = 0.42 + 0.08 * len(confirmations)
    if strategy.regimes and regime.tags & strategy.regimes:
        score += 0.10
    if feas.levels is not None and feas.levels.stop_basis == "structural":
        score += 0.05
    if not feas.tests.get("overhead_count"):
        score += 0.05
    drag = feas.tests.get("cost_pct_of_reward")
    if drag is not None and drag < 10:
        score += 0.03
    return round(max(0.05, min(0.95, score)), 3)


def evaluate_long(strategy, bars, symbol: str, exchange: str = "NSE",
                  htf_bars=None, regime: RegimeState | None = None, *,
                  bench=None, bench_ts=None, cost_model: str = "equity_delivery",
                  slippage_bps: float = 5.0, min_rr: float | None = None
                  ) -> tuple[Optional[Signal], Optional[Rejection]]:
    """Decide whether `strategy` fires LONG on the last bar of `bars`.

    Returns (signal, None) or (None, rejection). Never raises on bad data — a malformed
    series costs one signal, not the whole scan."""
    sid = strategy.strategy_id

    if len(bars) < strategy.min_bars:
        return None, Rejection(sid, "insufficient history", STAGE_BARS,
                               f"{len(bars)}/{strategy.min_bars} bars")

    regime = regime or classify_regime(bars)
    if not regime.allows(strategy.regimes):
        return None, Rejection(sid, "market regime not suitable", STAGE_REGIME,
                               f"regime {sorted(regime.tags) or ['unknown']}, "
                               f"strategy wants {sorted(strategy.regimes)}")

    ctx = None
    if needs_benchmark(strategy):
        if not bench:
            return None, Rejection(sid, "benchmark series unavailable", STAGE_BARS,
                                   "relative-strength strategies need index bars")
        # Causal slice: only benchmark bars at or before this bar's timestamp.
        ts_list = bench_ts if bench_ts is not None else [b.ts for b in bench]
        cut = bisect_right(ts_list, bars[-1].ts)
        if cut < 10:
            return None, Rejection(sid, "benchmark history too short", STAGE_BARS,
                                   f"{cut} aligned benchmark bars")
        ctx = {"bench": bench[:cut]}

    setup = detect_ext(strategy.detector, bars, strategy.params, ctx)
    if setup is None:
        return None, Rejection(sid, "setup not present", STAGE_DETECTOR)

    if setup.side != "BUY":
        return None, Rejection(sid, "short setup — this desk is long only",
                               STAGE_DIRECTION, f"{setup.pattern} fired to the downside")

    ok, reasons = check_all(strategy.confirmations, bars, "BUY", htf_bars)
    if not ok:
        return None, Rejection(sid, "confirmation failed", STAGE_CONFIRMATION,
                               reasons[-1] if reasons else "")

    a = atr_series(bars, 14)
    atr = a[-1] if a else 0.0
    if atr <= 0:
        return None, Rejection(sid, "no ATR — cannot size risk", STAGE_LEVELS)

    feas = assess(bars, "BUY", setup.entry, atr, strategy.timeframe,
                  structural_stop=setup.structural_stop,
                  measured_target=setup.measured_target,
                  cost_model=cost_model, slippage_bps=slippage_bps,
                  pivot=int(strategy.params.get("pivot", 4)), min_rr=min_rr)
    if not feas.ok or feas.levels is None:
        return None, Rejection(sid, feas.verdict, STAGE_FEASIBILITY, feas.detail)

    lv = feas.levels
    return Signal(
        strategy_id=sid, strategy_name=strategy.name, family=strategy.family,
        sub_family=strategy.sub_family, timeframe=strategy.timeframe, htf=strategy.htf,
        symbol=symbol, exchange=exchange, side="BUY",
        entry=lv.entry, stop=lv.stop, target=lv.target,
        risk=lv.risk, reward=lv.reward, r_multiple=lv.r_multiple,
        stop_basis=lv.stop_basis, target_basis="r_multiple",
        pattern=setup.pattern, detail=setup.detail, confirmations=reasons,
        regime_primary=regime.primary, regime_tags=sorted(regime.tags),
        atr=round(atr, 6), bar_ts=bars[-1].ts,
        confidence=_confidence(strategy, regime, reasons, feas),
        hypothesis=strategy.hypothesis,
        meta={"feasibility": feas.as_doc(), "measured_target": setup.measured_target},
    ), None


def make_evaluator(bench=None, cost_model: str = "equity_delivery",
                   slippage_bps: float = 5.0, min_rr: float | None = None) -> Callable:
    """Bind the desk-level context and return something with the factory's exact
    `evaluate()` signature, so the shared replay can drive this desk unmodified.

    The benchmark timestamps are extracted ONCE here rather than per bar: a replay calls
    the evaluator tens of thousands of times, and rebuilding that list each time was the
    difference between a sweep that finishes and one that does not."""
    ts_list = [b.ts for b in bench] if bench else None

    def _evaluate(strategy, bars, symbol, exchange="NSE", htf_bars=None, regime=None):
        return evaluate_long(strategy, bars, symbol, exchange, htf_bars, regime,
                             bench=bench, bench_ts=ts_list, cost_model=cost_model,
                             slippage_bps=slippage_bps, min_rr=min_rr)

    return _evaluate


__all__ = ["evaluate_long", "make_evaluator", "Signal", "Rejection",
           "STAGE_BARS", "STAGE_REGIME", "STAGE_DETECTOR", "STAGE_DIRECTION",
           "STAGE_CONFIRMATION", "STAGE_LEVELS", "STAGE_FEASIBILITY"]
