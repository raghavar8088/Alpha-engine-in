"""The single signal function shared by backtesting and paper trading.

ONE IMPLEMENTATION, TWO CALLERS
--------------------------------
`evaluate()` is the only place a strategy decides anything. The backtester calls it on a
historical bar slice; the paper desk calls it on the live slice. There is deliberately no
second code path, because the moment backtest logic and live logic are written twice they
drift, and every number the backtest produced stops describing what the desk will do.

The caller controls what the function can see by choosing the slice it passes. Pass
`bars[:i+1]` and the function cannot look at bar i+1 — there is no global data access
inside, no clock, and no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from strategy_service.indicators import atr as atr_series

from .catalog import Strategy
from .confirmations import check_all
from .detectors import detect
from .primitives import Levels, RegimeState, build_levels, classify_regime


@dataclass
class Signal:
    """Everything §16 of the brief asks a signal to carry, so a trade can be audited
    later without re-deriving why it was taken."""

    strategy_id: str
    strategy_name: str
    family: str
    sub_family: str
    timeframe: str
    htf: Optional[str]
    symbol: str
    exchange: str
    side: str                      # BUY | SELL
    entry: float
    stop: float
    target: float
    risk: float
    reward: float
    r_multiple: float
    stop_basis: str
    target_basis: str
    pattern: str
    detail: str
    confirmations: list[str]
    regime_primary: str
    regime_tags: list[str]
    atr: float
    bar_ts: datetime
    confidence: float
    hypothesis: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class Rejection:
    """Why a setup did NOT become a trade.

    Recorded rather than discarded: "no signals today" and "forty setups all vetoed by
    the regime filter" look identical from the outside, and only one of them means the
    strategy is working as designed."""

    strategy_id: str
    reason: str
    stage: str                     # bars | regime | detector | confirmation | levels | sizing
    detail: str = ""


def _confidence(strategy: Strategy, regime: RegimeState, confirmations: list[str],
                levels: Levels) -> float:
    """A bounded, explainable score — not a probability.

    Starts from the number of independent confirmations that had to pass, nudged up when
    the market is in one of the regimes the strategy actually claims, and down when the
    stop had to be forced off its structural level (which means the geometry was not
    really what the pattern described)."""
    score = 0.45 + 0.08 * len(confirmations)
    if strategy.regimes and regime.tags & strategy.regimes:
        score += 0.10
    if levels.stop_basis == "structural":
        score += 0.05
    if levels.target_basis == "measured_move":
        score += 0.05
    return round(max(0.05, min(0.95, score)), 3)


def evaluate(strategy: Strategy, bars, symbol: str, exchange: str = "MCX",
             htf_bars=None, regime: RegimeState | None = None
             ) -> tuple[Optional[Signal], Optional[Rejection]]:
    """Decide whether `strategy` fires on the LAST bar of `bars`.

    Returns (signal, None) or (None, rejection). Never raises on bad data — a malformed
    series costs one signal, not the whole scan."""
    sid = strategy.strategy_id

    if len(bars) < strategy.min_bars:
        return None, Rejection(sid, "insufficient history", "bars",
                               f"{len(bars)}/{strategy.min_bars} bars")

    regime = regime or classify_regime(bars)
    if not regime.allows(strategy.regimes):
        return None, Rejection(sid, "market regime not suitable", "regime",
                               f"regime {sorted(regime.tags) or ['unknown']}, "
                               f"strategy wants {sorted(strategy.regimes)}")

    try:
        setup = detect(strategy.detector, bars, strategy.params)
    except Exception:  # noqa: BLE001 — a detector must never break a scan
        return None, Rejection(sid, "detector error", "detector")
    if setup is None:
        return None, Rejection(sid, "setup not present", "detector")

    ok, reasons = check_all(strategy.confirmations, bars, setup.side, htf_bars)
    if not ok:
        return None, Rejection(sid, "confirmation failed", "confirmation",
                               reasons[-1] if reasons else "")

    a = atr_series(bars, 14)
    atr = a[-1] if a else 0.0
    if atr <= 0:
        return None, Rejection(sid, "no ATR — cannot size risk", "levels")

    levels = build_levels(setup.side, setup.entry, atr, strategy.target_r,
                          structural_stop=setup.structural_stop,
                          measured_target=setup.measured_target)
    if levels is None:
        return None, Rejection(sid, "degenerate levels", "levels",
                               f"entry {setup.entry:.4f}, stop ref {setup.structural_stop}")

    return Signal(
        strategy_id=sid, strategy_name=strategy.name, family=strategy.family,
        sub_family=strategy.sub_family, timeframe=strategy.timeframe, htf=strategy.htf,
        symbol=symbol, exchange=exchange, side=setup.side,
        entry=levels.entry, stop=levels.stop, target=levels.target,
        risk=levels.risk, reward=levels.reward, r_multiple=levels.r_multiple,
        stop_basis=levels.stop_basis, target_basis=levels.target_basis,
        pattern=setup.pattern, detail=setup.detail, confirmations=reasons,
        regime_primary=regime.primary, regime_tags=sorted(regime.tags),
        atr=round(atr, 6), bar_ts=bars[-1].ts,
        confidence=_confidence(strategy, regime, reasons, levels),
        hypothesis=strategy.hypothesis,
    ), None


__all__ = ["Signal", "Rejection", "evaluate"]
