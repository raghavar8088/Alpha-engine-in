"""Verify the six NEW detectors on purpose-built series. No Mongo, no Angel, no network.

Run:  python backend/tests/trending_stocks/verify_detectors.py

Thirteen of this module's nineteen recipes reuse detectors the Strategy Factory already
ships and the commodity library already tests. These six are new code, so each one is
checked twice: it MUST fire on a series built to contain its shape, and it MUST NOT fire
on a control series that contains the shape's near-miss. A detector that only ever fires
is worth nothing — every setup would become a signal and the library would be noise.

Three things this file exists to pin down, all of which bit while writing them:

  * **The Ichimoku cross needs price BELOW its own cloud on the prior bar.** A base that
    slopes up puts price above its own kumo before the breakout, so the cross never
    happens. The fixture uses a high base, a deep low, and a partial recovery — the only
    shape where price is under the cloud and the conversion line can still be above the
    base line.
  * **Anchored VWAP needs an out-and-back.** If price only rises from the anchor it is
    above its own AVWAP from the second bar onward and there is nothing to reclaim.
  * **Relative strength must NOT fire once price has already broken out.** That is a plain
    Donchian breakout, which other recipes own; this one is about leadership appearing
    BEFORE the breakout, so the fixture keeps price inside its range.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.trending_stocks.detectors_ext import (
    anchored_vwap_reclaim, fifty_two_week_high, ichimoku_kumo, rs_vs_benchmark,
    rsi_failure_swing, vcp,
)

IST = timezone(timedelta(hours=5, minutes=30))
FAILURES: list[str] = []


class Bar:
    __slots__ = ("ts", "open", "high", "low", "close", "volume")

    def __init__(self, ts, o, h, l, c, v):
        self.ts, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, v


def mk(closes, vols=None, spread=0.004, start=None):
    """Bars from a close path, with highs/lows a fixed fraction either side."""
    t0 = start or datetime(2022, 1, 3, 9, 15, tzinfo=IST)
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        h = max(o, c) * (1 + spread)
        l = min(o, c) * (1 - spread)
        v = (vols[i] if vols else 500_000)
        out.append(Bar(t0 + timedelta(days=i), o, h, l, c, v))
        prev = c
    return out


def ramp(a, b, n):
    if n <= 1:
        return [b]
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def flat(v, n, wobble=0.0):
    return [v + (wobble if i % 2 else -wobble) for i in range(n)]


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


P = dict(pivot=3, stop_lookback=14, window=30, min_since_anchor=6, rsi_period=14,
         fs_window=30, oversold=35, min_dip=3.0, high_window=250, min_base=40,
         min_bars_required=120, tenkan=9, kijun=26, senkou_b=52, rs_window=40,
         contractions=3, tighten=0.75, vol_window=20, vol_dryup=0.9)


# --------------------------------------------------------------------------------
print("\n== 52-week / long-horizon high breakout ==")
# A high that stood for ~250 bars, then a close through it.
closes = flat(100, 45, 0.5) + ramp(100, 120, 5) + ramp(120, 98, 10) + flat(100, 238, 0.6) + [126]
bars = mk(closes)
s = fifty_two_week_high(bars, P)
check("fires on a close above a long-standing high", s is not None and s.side == "BUY",
      s.detail if s else "no setup")
check("stop is below entry", s is None or s.structural_stop < s.entry)

# Control: the same series without the breakout bar.
s2 = fifty_two_week_high(mk(closes[:-1] + [101]), P)
check("does NOT fire while price is inside the range", s2 is None)

# Control: a vertical move making a new high on every bar has no base to break.
s3 = fifty_two_week_high(mk(ramp(100, 300, 300)), P)
check("does NOT fire on a vertical move with no base", s3 is None)


# --------------------------------------------------------------------------------
print("\n== Ichimoku kumo breakout ==")
# High base -> deep low -> partial recovery (price under the cloud) -> break through it.
closes = flat(118, 41, 0.4) + flat(92, 15, 0.3) + flat(100, 15, 0.3) + [112]
bars = mk(closes, spread=0.002)
s = ichimoku_kumo(bars, P)
check("fires when price closes above the cloud with tenkan over kijun",
      s is not None and s.side == "BUY", s.detail if s else "no setup")
check("stop sits below entry", s is None or s.structural_stop < s.entry)

s2 = ichimoku_kumo(mk(closes[:-1] + [100.2], spread=0.002), P)
check("does NOT fire while price is still inside the cloud", s2 is None)


# --------------------------------------------------------------------------------
print("\n== Volatility contraction (VCP) ==")
# Three progressively shallower pullbacks on drying volume, then a break.
path = (ramp(80, 100, 8) + ramp(100, 85, 8)          # -15%
        + ramp(85, 102, 8) + ramp(102, 94, 8)        # -7.8%
        + ramp(94, 104, 8) + ramp(104, 100.5, 8)     # -3.4%
        + ramp(100.5, 107, 4))
vols = ([900_000] * 24) + ([500_000] * 24) + ([300_000] * (len(path) - 48))
bars = mk(path, vols, spread=0.002)
s = vcp(bars, P)
check("fires on tightening pullbacks with drying volume",
      s is not None and s.side == "BUY", s.detail if s else "no setup")

# Control: same price path, RISING volume — tightening on rising volume is distribution.
rising = ([300_000] * 24) + ([500_000] * 24) + ([1_200_000] * (len(path) - 48))
check("does NOT fire when volume is expanding into the contraction",
      vcp(mk(path, rising, spread=0.002), P) is None)

# Control: pullbacks getting DEEPER is not a contraction.
widening = (ramp(80, 100, 8) + ramp(100, 96, 8)
            + ramp(96, 102, 8) + ramp(102, 94, 8)
            + ramp(94, 104, 8) + ramp(104, 85, 8)
            + ramp(85, 107, 4))
check("does NOT fire when the pullbacks are widening",
      vcp(mk(widening, vols, spread=0.002), P) is None)


# --------------------------------------------------------------------------------
print("\n== Anchored VWAP reclaim ==")
# Swing low -> rally -> give it all back below AVWAP -> reclaim on the last bar.
path = flat(110, 20, 0.3) + ramp(110, 90, 10) + ramp(90, 104, 10) + ramp(104, 92, 10) + [99]
bars = mk(path, spread=0.003)
s = anchored_vwap_reclaim(bars, P)
check("fires when price crosses back above the anchored VWAP",
      s is not None and s.side == "BUY", s.detail if s else "no setup")
check("stop is a real swing low below entry",
      s is None or (s.structural_stop < s.entry))

# Control: still under the AVWAP.
check("does NOT fire while price is still below it",
      anchored_vwap_reclaim(mk(path[:-1] + [92.5], spread=0.003), P) is None)

# Control: a straight rally from the low is above its own AVWAP throughout — nothing to
# reclaim, so there is no cross to detect.
check("does NOT fire on a one-way rally from the anchor",
      anchored_vwap_reclaim(mk(flat(110, 20, .3) + ramp(110, 90, 10) + ramp(90, 130, 25),
                               spread=0.003), P) is None)


# --------------------------------------------------------------------------------
print("\n== Relative strength vs the benchmark ==")
sym_path = flat(100, 3, 0) + ramp(100, 106, 3) + ramp(106, 100, 4) + flat(100, 40, 0.2)
bench_path = ramp(100, 70, len(sym_path))
sym = mk(sym_path, spread=0.002)
bench = mk(bench_path, spread=0.002)
s = rs_vs_benchmark(sym, P, {"bench": bench})
check("fires when the ratio line makes a new high before price does",
      s is not None and s.side == "BUY", s.detail if s else "no setup")

check("does NOT fire without a benchmark series", rs_vs_benchmark(sym, P, None) is None)
check("does NOT fire when the benchmark is outperforming",
      rs_vs_benchmark(sym, P, {"bench": mk(ramp(70, 140, len(sym_path)), spread=0.002)}) is None)

# Control: price already at a new high -> that is a breakout, not leadership.
broken = flat(100, 40, 0.2) + ramp(100, 130, 10)
check("does NOT fire once price has already broken out",
      rs_vs_benchmark(mk(broken, spread=0.002), P,
                      {"bench": mk(ramp(100, 70, len(broken)), spread=0.002)}) is None)


# --------------------------------------------------------------------------------
print("\n== RSI bullish failure swing ==")
# Oversold trough -> rally -> higher RSI low on the retest -> clears the intervening peak.
path = (flat(100, 20, 0.2) + ramp(100, 84, 12) + ramp(84, 95, 8)
        + ramp(95, 91, 5) + ramp(91, 99, 4))
bars = mk(path, spread=0.003)
s = rsi_failure_swing(bars, P)
check("fires on a completed failure swing", s is not None and s.side == "BUY",
      s.detail if s else "no setup")

# Control: the retest makes a LOWER RSI low — that is not a failure swing.
lower = (flat(100, 20, 0.2) + ramp(100, 84, 12) + ramp(84, 95, 8)
         + ramp(95, 80, 6) + ramp(80, 86, 4))
check("does NOT fire when the retest makes a lower low",
      rsi_failure_swing(mk(lower, spread=0.003), P) is None)

# Control: no oversold trough at all.
check("does NOT fire without an oversold trough",
      rsi_failure_swing(mk(ramp(100, 140, 60), spread=0.003), P) is None)


print("\n== every detector is long-only by construction ==")
import inspect

from app.services.trending_stocks import detectors_ext as dx

for name, fn in {**dx.EXT_DETECTORS, **dx.CTX_DETECTORS}.items():
    src = inspect.getsource(fn)
    check(f"{name} never emits SELL", '"SELL"' not in src and "'SELL'" not in src)

print(f"\n{'ALL CHECKS PASSED' if not FAILURES else 'FAILURES: ' + '; '.join(FAILURES)}")
sys.exit(1 if FAILURES else 0)
