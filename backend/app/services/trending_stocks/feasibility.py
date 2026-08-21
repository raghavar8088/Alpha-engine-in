"""The 1:6 gate — eligibility, not arithmetic.

Any signal can be given a 6R target: multiply the stop distance by six and write the
number down. That is worthless, and the brief says so — *"Do NOT artificially force a 1:6
target onto a setup that cannot realistically achieve it."* So this module asks whether
the market structure supports the target, and says NO TRADE when it does not.

FOUR TESTS, ALL OF WHICH MUST PASS
-----------------------------------
1. **The stop must be the pattern's own invalidation.** `build_levels` clamps every stop
   into [0.35, 6.0] ATR, and a stop that got clamped is no longer the level the setup
   actually gave. The two clamps fail for OPPOSITE reasons and are reported separately:
   `stop_too_tight` (the invalidation was inside the volatility floor — the gaming case,
   six times a stop ordinary noise would have taken out) and `stop_too_wide` (the
   invalidation is beyond the cap, so the position would be stopped out while the pattern
   was still valid). Merging them into one bucket hid a whole detector family failing for
   the second reason, which is why they are two verdicts.

2. **Volatility budget.** Can this instrument travel 6R in the number of bars the
   strategy is allowed to hold? Priced as `k * ATR * sqrt(max_hold)` — the random-walk
   scaling, which is the right shape here: over N bars a price's expected excursion grows
   with the square root of N, not linearly with it. A target beyond that budget is not a
   target, it is a wish.

3. **Overhead supply.** Where is the nearest level above entry that has already stopped
   price — a confirmed swing high, last week's or last month's high, the long-horizon
   high, a round number? If a wall sits in the first half of the journey, the 6R target is
   behind it. The blocking level is NAMED in the rejection, because "rejected" and
   "rejected because ₹1,480 capped it four times" are different amounts of information.

4. **The edge must survive costs.** NSE round-trip friction is ~0.10-0.14% intraday
   (~0.24% delivery, STT both sides) plus slippage. On a 1-minute chart a 6R target can be
   0.3%, which clears the R:R test comfortably and still loses money. Reported as its own
   verdict — `edge_below_costs` — because it is a completely different finding from
   `rr_infeasible` and the two must never be added together on a summary tile.

A strategy that never produces a feasible setup anywhere in its backtest is stamped
FAILED_RR and barred from paper trading.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

from app.services import commodity_patterns as CP
from app.services.strategy_factory.backtest import DEFAULT_MAX_HOLD
from app.services.strategy_factory.primitives import (
    MAX_STOP_ATR, MIN_STOP_ATR, Levels, build_levels, round_trip_cost,
)

# The house minimum. Configurable ONLY so the same 678 strategies can be re-run at 1:3 to
# measure what the 1:6 constraint actually costs — not so it can be quietly relaxed when
# the answer is unwelcome. Every stored row records the value it was judged at.
MIN_RR = float(os.getenv("TS_MIN_RR", "6.0"))

# Reject a 6R target built on a stop that is not the pattern's own invalidation level.
REQUIRE_STRUCTURAL_STOP = os.getenv("TS_REQUIRE_STRUCTURAL_STOP", "1").lower() not in ("0", "false", "")

# Multiplier on the sqrt-time volatility budget. 1.0 means "the target must be inside the
# instrument's own typical excursion over the holding period"; above 1 allows for the fact
# that a strategy fires on setups, not on random bars, and setups are chosen precisely
# because they precede larger-than-typical moves.
VOL_BUDGET_K = float(os.getenv("TS_VOL_BUDGET_K", "1.35"))

# How much of the distance to target must be clear of a known wall.
OVERHEAD_CLEAR_FRACTION = float(os.getenv("TS_OVERHEAD_CLEAR", "0.5"))

# Reward must beat round-trip friction by this multiple, and the risk must too — a stop
# whose loss is mostly brokerage is not a risk model, it is a fee schedule.
MIN_REWARD_COST_MULT = float(os.getenv("TS_MIN_REWARD_COST_MULT", "3.0"))
MIN_RISK_COST_MULT = float(os.getenv("TS_MIN_RISK_COST_MULT", "1.5"))

# Round numbers people actually watch, as a fraction of price.
ROUND_STEPS = (1000.0, 500.0, 100.0, 50.0, 10.0)

VERDICT_OK = "ok"
VERDICT_DEGENERATE = "degenerate_levels"
# Two DIFFERENT failures, deliberately not merged into one "stop_not_structural" bucket.
# Measured on a 76-strategy daily sweep: the floor case is the gaming one, the cap case is
# a breakout pattern whose invalidation is genuinely far away (a previous-week low, say).
# Lumping them together hid the fact that one detector family was failing for the opposite
# reason to the other.
VERDICT_STOP_TOO_TIGHT = "stop_too_tight"       # clamped UP off the ATR floor
VERDICT_STOP_TOO_WIDE = "stop_too_wide"         # clamped DOWN onto the ATR cap
VERDICT_RR_INFEASIBLE = "rr_infeasible"
VERDICT_OVERHEAD = "overhead_supply"
VERDICT_COSTS = "edge_below_costs"


@dataclass
class Feasibility:
    ok: bool
    verdict: str
    min_rr: float
    levels: Optional[Levels] = None
    detail: str = ""
    blocking_level: Optional[float] = None
    blocking_label: Optional[str] = None
    tests: dict = field(default_factory=dict)

    def as_doc(self) -> dict:
        lv = self.levels
        return {
            "ok": self.ok, "verdict": self.verdict, "min_rr": self.min_rr,
            "detail": self.detail,
            "blocking_level": self.blocking_level, "blocking_label": self.blocking_label,
            "tests": self.tests,
            "entry": round(lv.entry, 4) if lv else None,
            "stop": round(lv.stop, 4) if lv else None,
            "target": round(lv.target, 4) if lv else None,
            "risk": round(lv.risk, 4) if lv else None,
            "reward": round(lv.reward, 4) if lv else None,
            "r_multiple": lv.r_multiple if lv else None,
            "stop_basis": lv.stop_basis if lv else None,
        }


def _round_number_above(price: float, ceiling: float) -> tuple[Optional[float], Optional[str]]:
    """The nearest psychologically-watched round level strictly between price and ceiling.

    The step scales with the price so this means the same thing on a ₹45 stock and a
    ₹45,000 one: ₹50 steps matter on the first and are invisible on the second."""
    for step in ROUND_STEPS:
        if price < step * 2:
            continue
        level = math.floor(price / step) * step + step
        if price < level < ceiling:
            return level, f"the ₹{step:,.0f} round number {level:,.0f}"
    return None, None


def overhead_levels(bars, entry: float, ceiling: float, pivot: int = 4) -> list[tuple[float, str]]:
    """Every known level of supply strictly between entry and ceiling, nearest first.

    'Known' means it has already stopped price at least once, or it is a level a large
    number of participants are looking at. Untested air above a breakout is not supply,
    and treating it as such would reject every genuine new high."""
    found: list[tuple[float, str]] = []
    if ceiling <= entry or len(bars) < 10:
        return found

    highs, _lows = CP.pivots(bars, pivot, pivot)
    for idx in reversed(highs[-12:]):
        level = bars[idx].high
        if entry < level < ceiling:
            found.append((level, f"the swing high {level:,.2f} from {len(bars) - idx} bars ago"))

    # Previous calendar week and month highs — the levels swing traders actually mark.
    for label, keyfn in (("week", lambda b: (b.ts.isocalendar()[0], b.ts.isocalendar()[1])),
                         ("month", lambda b: (b.ts.year, b.ts.month))):
        groups: dict = {}
        for b in bars:
            groups.setdefault(keyfn(b), []).append(b)
        ordered = sorted(groups)
        if len(ordered) >= 2:
            prev_high = max(b.high for b in groups[ordered[-2]])
            if entry < prev_high < ceiling:
                found.append((prev_high, f"last {label}'s high {prev_high:,.2f}"))

    # The long-horizon high, but only from bars old enough to have been REJECTED from.
    # Without the guard this reads the current bar's own high — which is always a hair
    # above entry — as a wall, and every genuine new high gets refused for being blocked
    # by itself. That is the single most damaging false positive this scanner can have,
    # because "no overhead supply" is the whole reason a breakout to a new high is worth
    # taking.
    guard = max(pivot * 2, 5)
    if len(bars) > guard + 5:
        older = bars[:-guard]
        long_high = max(b.high for b in older)
        if entry < long_high < ceiling:
            found.append((long_high, f"the {len(older)}-bar high {long_high:,.2f}"))

    rn, rn_label = _round_number_above(entry, ceiling)
    if rn is not None and rn_label:
        found.append((rn, rn_label))

    found.sort(key=lambda t: t[0])
    return found


def assess(bars, side: str, entry: float, atr: float, timeframe: str,
           structural_stop: Optional[float], measured_target: Optional[float],
           cost_model: str, slippage_bps: float = 5.0,
           pivot: int = 4, min_rr: float | None = None) -> Feasibility:
    """Can this setup realistically pay `min_rr` times what it risks?"""
    rr = float(min_rr if min_rr is not None else MIN_RR)
    tests: dict = {"min_rr": rr}

    # ---- levels ------------------------------------------------------------------
    # The measured move is deliberately NOT used as the target: the desk's target is the
    # R multiple, and the projection's job here is to say whether that R is believable.
    levels = build_levels(side, entry, atr, rr, structural_stop=structural_stop,
                          measured_target=None)
    if levels is None:
        return Feasibility(False, VERDICT_DEGENERATE, rr,
                           detail=f"entry {entry:.2f} with stop reference "
                                  f"{structural_stop} produces no valid geometry",
                           tests=tests)

    # ---- 1. the stop must be the pattern's own invalidation -----------------------
    tests["stop_basis"] = levels.stop_basis
    tests["stop_distance_atr"] = round(levels.risk / atr, 3) if atr else None
    if REQUIRE_STRUCTURAL_STOP and levels.stop_basis == "atr_floor":
        # The gaming case: the pattern's invalidation was TIGHTER than the volatility
        # floor, so the risk model widened it. Six times a stop that ordinary noise would
        # have taken out is a ratio, not a plan.
        return Feasibility(
            False, VERDICT_STOP_TOO_TIGHT, rr, levels,
            detail=(f"the setup's own invalidation was inside the {MIN_STOP_ATR} ATR "
                    f"volatility floor, so the stop had to be widened to "
                    f"{levels.risk/atr:.2f} ATR — a {rr:.0f}R target measured from a level "
                    "the pattern never gave is an arithmetic ratio, not a trade"),
            tests=tests)
    if REQUIRE_STRUCTURAL_STOP and levels.stop_basis == "atr_cap":
        # The opposite failure, and it needs its own name: the pattern's invalidation is
        # further away than the risk model permits, so the position would be stopped out
        # while the hypothesis is still intact. That is not the trade the strategy
        # described, so it is declined rather than silently taken with a tighter stop.
        return Feasibility(
            False, VERDICT_STOP_TOO_WIDE, rr, levels,
            detail=(f"the setup's invalidation sits beyond the {MAX_STOP_ATR} ATR cap, so "
                    f"the stop was pulled in to {levels.risk/atr:.2f} ATR — the position "
                    "would be stopped out while the pattern was still valid"),
            tests=tests)

    # ---- 2. volatility budget ----------------------------------------------------
    max_hold = DEFAULT_MAX_HOLD.get(timeframe, 60)
    budget = VOL_BUDGET_K * atr * math.sqrt(max_hold)
    tests["reward"] = round(levels.reward, 4)
    tests["vol_budget"] = round(budget, 4)
    tests["max_hold_bars"] = max_hold
    if levels.reward > budget:
        return Feasibility(
            False, VERDICT_RR_INFEASIBLE, rr, levels,
            detail=(f"{rr:.0f}R is {levels.reward:.2f} but this instrument's typical "
                    f"excursion over {max_hold} bars is {budget:.2f} "
                    f"({levels.reward/budget:.1f}x the volatility budget)"),
            tests=tests)

    # ---- 2b. the pattern's own projection, where it has one ----------------------
    if measured_target is not None and measured_target > entry:
        projected = measured_target - entry
        tests["measured_move"] = round(projected, 4)
        if levels.reward > projected * float(os.getenv("TS_MEASURED_TOLERANCE", "1.75")):
            return Feasibility(
                False, VERDICT_RR_INFEASIBLE, rr, levels,
                detail=(f"the pattern projects {projected:.2f} but {rr:.0f}R needs "
                        f"{levels.reward:.2f} — the target is beyond what this shape claims"),
                tests=tests)

    # ---- 3. overhead supply ------------------------------------------------------
    walls = overhead_levels(bars, levels.entry, levels.target, pivot)
    clear_to = levels.entry + levels.reward * OVERHEAD_CLEAR_FRACTION
    tests["overhead_count"] = len(walls)
    if walls:
        nearest, label = walls[0]
        tests["nearest_overhead"] = round(nearest, 4)
        if nearest < clear_to:
            return Feasibility(
                False, VERDICT_OVERHEAD, rr, levels, blocking_level=round(nearest, 4),
                blocking_label=label,
                detail=(f"{label} sits at {(nearest - levels.entry)/levels.risk:.1f}R, "
                        f"inside the first {OVERHEAD_CLEAR_FRACTION*100:.0f}% of the way "
                        f"to a {rr:.0f}R target"),
                tests=tests)

    # ---- 4. costs ----------------------------------------------------------------
    # Per-unit: charges scale with turnover, so one unit is the honest unit rate. Slippage
    # is added on both fills at the configured bps.
    is_long = side == "BUY"
    friction = round_trip_cost(cost_model, levels.entry, levels.target, 1.0, is_long)
    friction += (levels.entry + levels.target) * slippage_bps / 10000.0
    stop_friction = round_trip_cost(cost_model, levels.entry, levels.stop, 1.0, is_long)
    stop_friction += (levels.entry + levels.stop) * slippage_bps / 10000.0
    tests["round_trip_cost_per_unit"] = round(friction, 5)
    tests["cost_pct_of_reward"] = round(friction / levels.reward * 100, 2) if levels.reward else None
    if levels.reward < friction * MIN_REWARD_COST_MULT:
        return Feasibility(
            False, VERDICT_COSTS, rr, levels,
            detail=(f"a {rr:.0f}R win pays {levels.reward:.3f}/unit but the round trip "
                    f"costs {friction:.3f}/unit — {friction/levels.reward*100:.0f}% of the "
                    "reward goes to friction"),
            tests=tests)
    if levels.risk < stop_friction * MIN_RISK_COST_MULT:
        return Feasibility(
            False, VERDICT_COSTS, rr, levels,
            detail=(f"the stop risks {levels.risk:.3f}/unit against {stop_friction:.3f} of "
                    "friction — a loss here is mostly fees, not a trade"),
            tests=tests)

    return Feasibility(
        True, VERDICT_OK, rr, levels,
        detail=(f"{rr:.0f}R = {levels.reward:.2f} against a structural stop "
                f"{levels.risk:.2f} away ({levels.risk/atr:.2f} ATR); clear of overhead "
                f"supply and {friction/levels.reward*100:.0f}% cost drag"),
        tests=tests)


FAILED_RR_LABEL = "FAILED — DOES NOT MEET 1:6 RISK/REWARD"

__all__ = ["Feasibility", "assess", "overhead_levels", "MIN_RR", "FAILED_RR_LABEL",
           "VERDICT_OK", "VERDICT_RR_INFEASIBLE", "VERDICT_OVERHEAD", "VERDICT_COSTS",
           "VERDICT_STOP_TOO_TIGHT", "VERDICT_STOP_TOO_WIDE", "VERDICT_DEGENERATE"]
