"""Out-of-sample check for the option-SELLING library.

WHY THIS EXISTS
---------------
The selling library contains a generated structure x regime matrix (see
`strategy_service.strategies.options_selling._matrix`). Testing ~130 candidates against
one price history is data mining, and at a PF 1.3 bar a handful will clear it on luck
alone even if nothing in the grid had a real edge. A sweep result on its own therefore
cannot distinguish "this works" from "this got lucky once".

This script re-runs every strategy on a CHRONOLOGICAL split — first 60% of the bars to
select on, last 40% held back — and reports which qualifiers survive on data they were
never chosen against. The split is strictly by time, never random: shuffling bars leaks
the future into the past and would make almost everything look robust.

Read the output as three tiers:
  ROBUST      qualified on the full history AND on the held-back period. The only tier
              that belongs in a live paper basket.
  FULL-ONLY   qualified overall but failed out of sample — the signature of a mining
              artifact, or of an edge that has decayed. Do not trade.
  DEGRADED    qualified out of sample but not overall — usually a strategy whose losses
              are concentrated in the early period. Interesting, not promotable.

Usage (repo root):
    python options-service/verify_selling_split.py [--min-test-trades 15]

Bars come from Mongo; set NIFTY_BAR_DUMP_15M / NIFTY_BAR_DUMP_1D to jsonl(.gz) exports
to run offline.
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path[:0] = ["shared", "strategy-service", "options-service", "backtesting-service"]

import strategy_service.strategies  # noqa: F401,E402
from options_service.options_selling_backtest import (  # noqa: E402
    OPTION_SELLING_CATEGORIES,
    qualify,
    run_options_selling_backtest,
)
from tradingai_shared.contracts import STRATEGY_REGISTRY  # noqa: E402
from tradingai_shared.domain import Bar, Timeframe  # noqa: E402

STYLE_TF = {
    "options_sell_intraday": Timeframe.M15,
    "options_sell_expiry": Timeframe.M15,
    "options_sell_swing": Timeframe.M15,
    "options_sell_positional": Timeframe.D1,
}
TRAIN_FRACTION = 0.6
_cache: dict = {}


def load(tf: Timeframe) -> list[Bar]:
    if tf in _cache:
        return _cache[tf]
    dump = os.environ.get(f"NIFTY_BAR_DUMP_{tf.value.upper()}")
    if dump:
        import gzip

        opener = gzip.open if dump.endswith(".gz") else open
        bars = []
        for line in opener(dump, "rt"):
            d = json.loads(line)
            if d["timeframe"] != tf.value or d["symbol"] != "NIFTY":
                continue
            d["ts"] = datetime.fromisoformat(d["ts"])
            bars.append(Bar(**d))
        bars.sort(key=lambda b: b.ts)
    else:
        from backtesting_service.service import load_bars

        bars = load_bars("NIFTY", tf, None)
    _cache[tf] = bars
    return bars


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-test-trades", type=int, default=15,
                    help="a held-back period with fewer trades than this is too thin to judge")
    args = ap.parse_args()

    strategies = sorted(
        (sid, cls) for sid, cls in STRATEGY_REGISTRY.items()
        if cls.metadata.category in OPTION_SELLING_CATEGORIES
    )
    robust, full_only, degraded, thin = [], [], [], []

    for sid, cls in strategies:
        tf = STYLE_TF[cls.metadata.category]
        bars = load(tf)
        if not bars:
            continue
        wd = 1 if cls.metadata.category in ("options_sell_intraday", "options_sell_expiry") else None
        cut = int(len(bars) * TRAIN_FRACTION)

        def go(window):
            return run_options_selling_backtest(
                sid, "NIFTY", tf, window, expiry_weekday=wd
            )["metrics"]

        try:
            full, test = go(bars), go(bars[cut:])
        except Exception as exc:
            print(f"  ERROR {sid}: {type(exc).__name__}: {exc}")
            continue

        fq, tq = qualify(full)["qualified"], qualify(test)["qualified"]
        row = (sid, full, test)
        if fq and tq:
            (thin if test["total_trades"] < args.min_test_trades else robust).append(row)
        elif fq:
            full_only.append(row)
        elif tq:
            degraded.append(row)

    def dump_tier(title, rows, note):
        print(f"\n{title}  ({len(rows)})\n{note}")
        if not rows:
            print("  none")
            return
        rows.sort(key=lambda r: -(r[2]["profit_factor"] or 0))
        print(f"  {'strategy':<38}{'full PF':>9}{'test PF':>9}{'test tr':>9}{'test net':>12}")
        for sid, full, test in rows:
            print(f"  {sid:<38}{full['profit_factor'] or 0:>9.2f}{test['profit_factor'] or 0:>9.2f}"
                  f"{test['total_trades']:>9}{test['net_profit']:>12,.0f}")

    print(f"Chronological split: first {TRAIN_FRACTION:.0%} selected on, last "
          f"{1 - TRAIN_FRACTION:.0%} held back. {len(strategies)} strategies tested.")
    dump_tier("ROBUST", robust,
              "  Qualified on the full history AND out of sample. Promotable to paper.")
    dump_tier("THIN", thin,
              f"  Qualified both ways but fewer than {args.min_test_trades} held-back "
              f"trades — too few to judge.")
    dump_tier("FULL-ONLY", full_only,
              "  Qualified overall, FAILED out of sample. Mining artifact or decayed edge.")
    dump_tier("DEGRADED", degraded,
              "  Qualified out of sample only. Losses concentrated early; not promotable.")

    print(f"\nSUMMARY: {len(robust)} robust, {len(thin)} thin, {len(full_only)} full-only, "
          f"{len(degraded)} degraded, out of {len(strategies)} tested.")
    if full_only:
        print(f"\n{len(full_only)} strategies would have entered a live basket on the full-history "
              f"sweep alone and are rejected here. That count is the value of this check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
