"""Verify the 1:6 gate rejects for the RIGHT reason. No Mongo, no Angel, no network.

Run:  python backend/tests/trending_stocks/verify_feasibility.py

The gate's whole value is that it distinguishes between five different ways a 6R target
can be unrealistic. If they collapsed into one "rejected" bucket the No-Trade tab would be
useless and the honest question — *can this basket produce 1:6 trades at all, and if not,
why not* — would have no answer. So every verdict gets a fixture that produces it and only
it.

The measurement that motivated splitting `stop_too_tight` from `stop_too_wide`: on a
76-strategy daily sweep, 204 setups were rejected for "a stop that is not structural", and
they were failing for two OPPOSITE reasons — candlestick shapes whose invalidation was
inside the volatility floor, and previous-period breakouts whose invalidation was a whole
week's low away. One bucket hid that completely.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.trending_stocks.feasibility import (
    MIN_RR, VERDICT_COSTS, VERDICT_OK, VERDICT_OVERHEAD, VERDICT_RR_INFEASIBLE,
    VERDICT_STOP_TOO_TIGHT, VERDICT_STOP_TOO_WIDE, assess, overhead_levels,
)

IST = timezone(timedelta(hours=5, minutes=30))
FAILURES: list[str] = []


class Bar:
    __slots__ = ("ts", "open", "high", "low", "close", "volume")

    def __init__(self, ts, o, h, l, c, v):
        self.ts, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, v


def mk(closes, spread=0.004):
    t0 = datetime(2022, 1, 3, 9, 15, tzinfo=IST)
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append(Bar(t0 + timedelta(days=i), prev, max(prev, c) * (1 + spread),
                       min(prev, c) * (1 - spread), c, 500_000))
        prev = c
    return out


def ramp(a, b, n):
    return [b] if n <= 1 else [a + (b - a) * i / (n - 1) for i in range(n)]


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


# A clean, gently rising series ending at its own high: no overhead supply anywhere
# between entry and any plausible target.
RISING = mk(ramp(100, 160, 200), spread=0.002)
ENTRY = RISING[-1].close
ATR = ENTRY * 0.015                       # 1.5% ATR, typical for a liquid NSE name

print(f"\n== configuration ==")
check("the house minimum really is 1:6", MIN_RR == 6.0, f"TS_MIN_RR = {MIN_RR}")

print("\n== a feasible setup passes ==")
f = assess(RISING, "BUY", ENTRY, ATR, "1d", structural_stop=ENTRY - ATR,
           measured_target=None, cost_model="equity_delivery", slippage_bps=5.0, pivot=4)
check("clean 1-ATR structural stop at a new high is accepted",
      f.ok and f.verdict == VERDICT_OK, f"{f.verdict}: {f.detail}")
check("the target really is 6R", f.levels is not None and abs(f.levels.r_multiple - 6.0) < 0.01,
      f"r_multiple {f.levels.r_multiple if f.levels else None}")
check("the stop basis is the pattern's own level",
      f.levels is not None and f.levels.stop_basis == "structural")

print("\n== stop_too_tight — the gaming case ==")
f = assess(RISING, "BUY", ENTRY, ATR, "1d", structural_stop=ENTRY - ATR * 0.1,
           measured_target=None, cost_model="equity_delivery", pivot=4)
check("a stop inside the volatility floor is refused",
      f.verdict == VERDICT_STOP_TOO_TIGHT, f"{f.verdict}: {f.detail}")
check("and it says the target would be measured from a level the pattern never gave",
      "never gave" in f.detail)

print("\n== stop_too_wide — the opposite failure ==")
f = assess(RISING, "BUY", ENTRY, ATR, "1d", structural_stop=ENTRY - ATR * 9,
           measured_target=None, cost_model="equity_delivery", pivot=4)
check("an invalidation beyond the ATR cap is refused",
      f.verdict == VERDICT_STOP_TOO_WIDE, f"{f.verdict}: {f.detail}")
check("and it says the position would be stopped out while the pattern was still valid",
      "still valid" in f.detail)

print("\n== rr_infeasible — the volatility budget ==")
# A 3-ATR structural stop means 6R is an 18-ATR move; over 40 daily bars the instrument's
# own typical excursion is far less than that.
f = assess(RISING, "BUY", ENTRY, ATR, "1d", structural_stop=ENTRY - ATR * 3,
           measured_target=None, cost_model="equity_delivery", pivot=4)
check("a 6R target beyond the instrument's own excursion is refused",
      f.verdict == VERDICT_RR_INFEASIBLE, f"{f.verdict}: {f.detail}")
check("the rejection quotes both the target and the budget",
      "volatility budget" in f.detail)

print("\n== rr_infeasible — the pattern's own projection ==")
f = assess(RISING, "BUY", ENTRY, ATR, "1d", structural_stop=ENTRY - ATR,
           measured_target=ENTRY + ATR * 1.5, cost_model="equity_delivery", pivot=4)
check("a 6R target far beyond the measured move is refused",
      f.verdict == VERDICT_RR_INFEASIBLE, f"{f.verdict}: {f.detail}")
check("and it names what the pattern actually projects", "projects" in f.detail)

print("\n== overhead_supply — a wall in the first half of the journey ==")
# Same rise, but with a prior peak sitting just above the entry.
capped = mk(ramp(100, 150, 120) + ramp(150, 130, 20) + ramp(130, 149, 60), spread=0.002)
e = capped[-1].close
a = e * 0.012
f = assess(capped, "BUY", e, a, "1d", structural_stop=e - a, measured_target=None,
           cost_model="equity_delivery", pivot=4)
check("a known level inside the first half of the move blocks the target",
      f.verdict == VERDICT_OVERHEAD, f"{f.verdict}: {f.detail}")
check("the blocking level is NAMED, not just counted",
      bool(f.blocking_label) and bool(f.blocking_level),
      f"{f.blocking_label} @ {f.blocking_level}")
check("and the rejection says how many R away it sits", "R," in f.detail or "R " in f.detail)

print("\n== the overhead scanner itself ==")
walls = overhead_levels(capped, e, e * 1.30, pivot=4)
check("finds levels between entry and ceiling, nearest first",
      bool(walls) and all(e < lv < e * 1.30 for lv, _ in walls)
      and walls == sorted(walls, key=lambda t: t[0]),
      f"{len(walls)} levels")
check("finds nothing above an all-time high",
      not overhead_levels(RISING, ENTRY, ENTRY * 1.05, pivot=4))

print("\n== edge_below_costs — the fast-timeframe killer ==")
# A very quiet series: a 6R target off the 0.35-ATR floor is a fraction of a percent, and
# an NSE round trip costs more than that. This is the verdict that separates "the R:R is
# unreachable" from "the R:R is fine and the edge is smaller than the friction".
# Ends on a decisive new high so nothing sits overhead — this fixture is about
# COSTS, and the overhead test runs first.
quiet = mk(ramp(500.0, 500.5, 199) + [501.0], spread=0.0002)
qe = quiet[-1].close
qa = qe * 0.0006                          # 0.06% ATR
f = assess(quiet, "BUY", qe, qa, "1m", structural_stop=qe - qa, measured_target=None,
           cost_model="equity_intraday", slippage_bps=5.0, pivot=3)
check("a 6R target smaller than the round trip is refused",
      f.verdict == VERDICT_COSTS, f"{f.verdict}: {f.detail}")
check("and it quotes the cost as a share of the reward",
      "friction" in f.detail or "%" in f.detail)

print("\n== relaxing the rule changes the answer, and is recorded ==")
f6 = assess(RISING, "BUY", ENTRY, ATR, "1d", structural_stop=ENTRY - ATR * 1.6,
            measured_target=None, cost_model="equity_delivery", pivot=4)
f3 = assess(RISING, "BUY", ENTRY, ATR, "1d", structural_stop=ENTRY - ATR * 1.6,
            measured_target=None, cost_model="equity_delivery", pivot=4, min_rr=3.0)
check("a setup that fails at 1:6 can pass at 1:3",
      f6.verdict == VERDICT_RR_INFEASIBLE and f3.ok,
      f"1:6 -> {f6.verdict}, 1:3 -> {f3.verdict}")
check("every result records the ratio it was judged at",
      f6.as_doc()["min_rr"] == 6.0 and f3.as_doc()["min_rr"] == 3.0)

print(f"\n{'ALL CHECKS PASSED' if not FAILURES else 'FAILURES: ' + '; '.join(FAILURES)}")
sys.exit(1 if FAILURES else 0)
