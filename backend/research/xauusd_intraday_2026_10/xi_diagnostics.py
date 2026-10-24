"""Stress tests of the intraday pass (python xi_diagnostics.py), run AFTER the locked evaluation; they
change no verdict. The payrolls straddle enters in the minute the US jobs report is released, when
spreads widen and stop orders slip: the base costs ($0.10 slippage a side) are kind to that minute.

  1. slippage per side the edge can absorb (extra $1, $2, $3, $5 a side, on entries and exits);
  2. late fills: entry at the close of the trigger minute, and at the open of the next minute;
  3. a placebo: the same straddle on every NON-payrolls weekday (is the edge the release, or the rule?);
  4. year by year, t-statistic and bootstrap interval.
Writes results/diagnostics.json.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json

import numpy as np
import pandas as pd

import xi_strategies as S
from xi_engine import COSTS, Costs, run_exit, stats, trades_frame, net_returns, stop_entry
from xi_run import RES, bootstrap, data, jsonable, windows

LOCKED = {"mode": "straddle", "exit": "end", "tp": "3R"}


def straddle(D, days, fill: str = "level", nfp_only: bool = True):
    """The locked rule with a choice of entry fill: 'level' (as tested), 'trigger_close' (the close of the
    minute the stop triggered in) or 'next_open' (the open of the following minute)."""
    rows = []
    for d in days:
        if nfp_only and D["sess_date"][d] not in S.NFP:
            continue
        if not nfp_only and D["sess_date"][d] in S.NFP:
            continue
        xl = S.last_before(D, d, S.T[LOCKED["exit"]])
        ia, ib = S.at(D, d, S.T["ny0800"]), S.at(D, d, S.T["data"])
        if None in (xl, ia, ib):
            continue
        hi, lo = D["h"][ia:ib].max(), D["l"][ia:ib].min()
        buf = 0.0002 * hi
        f = stop_entry(D, ib, xl, hi + buf, lo - buf)
        if f is None:
            continue
        ei, side, ep, inside = f
        stop = lo - buf if side == 1 else hi + buf
        if fill == "trigger_close":
            ep, inside = D["c"][ei], False
            if ei + 1 > xl:
                continue
            ei = ei + 1           # the position exists from the next minute
        elif fill == "next_open":
            if ei + 1 > xl:
                continue
            ei, ep, inside = ei + 1, D["o"][ei + 1], False
        risk = abs(ep - stop)
        if risk <= 0 or (side == 1 and ep <= stop) or (side == -1 and ep >= stop):
            continue
        tgt = ep + side * 3 * risk
        xi, xp, why = run_exit(D, side, ei, ep, stop, tgt, xl, inside)
        rows.append((d, side, ei, ep, xi, xp, why))
    return trades_frame(D, rows)


def main() -> None:
    D, C = data()
    w = windows(D)
    out = {}
    for wn, (a, b) in w.items():
        days = range(a, b + 1)
        base = straddle(D, days)
        r = net_returns(D, base, COSTS["C1"])
        res = {"C1": stats(r), "ci95": bootstrap(r),
               "by_year": {int(y): {"trades": int(len(g)), "avg": float(g.mean())}
                           for y, g in pd.Series(r, index=pd.to_datetime(base["date"].values).year).groupby(level=0)}}
        res["avg_price"] = float(base["ep"].mean())
        res["avg_gross_usd"] = float((base["side"] * (base["xp"] - base["ep"])).mean())
        res["avg_range_usd"] = None
        res["extra_slippage"] = {}
        for extra in (1.0, 2.0, 3.0, 5.0):
            c = Costs(f"C1 + ${extra:.0f} a side", 0.40, 0.10 + extra, 0.035)
            res["extra_slippage"][f"+${extra:.0f}"] = stats(net_returns(D, base, c))
        # break-even extra slippage a side (USD): net USD a trade / 2
        net_usd = r * base["ep"].values
        res["breakeven_extra_slippage_usd_a_side"] = float(net_usd.mean() / 2)
        for fill in ("trigger_close", "next_open"):
            tf = straddle(D, days, fill)
            res[f"fill_{fill}"] = stats(net_returns(D, tf, COSTS["C1"]))
        pl = straddle(D, days, nfp_only=False)
        res["placebo_non_payroll_days"] = stats(net_returns(D, pl, COSTS["C1"]))
        # the account at 10x and 20x, as tested and with the entry one minute late (realistic for a release)
        span = (str(D["sess_date"][a]), str(D["sess_date"][b]))
        from xi_engine import account
        from xi_run import monthly
        late = straddle(D, days, "trigger_close")
        r_late = net_returns(D, late, COSTS["C1"])
        res["accounts"] = {}
        res["monthly"] = {}
        for name, tf, rr in (("as_tested", base, r), ("entry_at_trigger_close", late, r_late)):
            for L in (10.0, 20.0):
                acc = account(rr, tf["date"].values, L, *span)
                res["accounts"][f"{name}_{int(L)}x"] = {k: v for k, v in acc.items() if k != "path"}
                res["monthly"][f"{name}_{int(L)}x"] = monthly(tf, rr, L, *span)
        out[wn] = res
        print(f"\n=== {wn} {D['sess_date'][a]} .. {D['sess_date'][b]}")
        c1 = res["C1"]
        print(f"  as tested: {c1['trades']} trades, avg {c1['avg']*100:+.3f}%, t {c1['t_stat']:.2f}, pf {c1['profit_factor']:.2f}, "
              f"95% CI {res['ci95'][0]*100:+.3f}% .. {res['ci95'][1]*100:+.3f}%; avg gross ${res['avg_gross_usd']:.2f} at ~${res['avg_price']:.0f}")
        for k, v in res["extra_slippage"].items():
            print(f"  extra slippage {k} a side: avg {v['avg']*100:+.3f}%  pf {v['profit_factor']:.2f}")
        print(f"  break-even extra slippage: ${res['breakeven_extra_slippage_usd_a_side']:.2f} a side")
        for fill in ("trigger_close", "next_open"):
            v = res[f"fill_{fill}"]
            print(f"  entry at {fill}: {v['trades']} trades avg {v['avg']*100:+.3f}% pf {v['profit_factor']:.2f}")
        v = res["placebo_non_payroll_days"]
        print(f"  placebo, same straddle on non-payroll days: {v['trades']} trades avg {v['avg']*100:+.3f}% pf {v['profit_factor']:.2f}")
        print("  by year:", {y: (v['trades'], round(v['avg'] * 100, 3)) for y, v in res["by_year"].items()})
        for k, v in res["accounts"].items():
            print(f"  account {k}: total {v['total_return']*100:+.1f}%  CAGR {v['cagr']*100:+.1f}%  max drawdown {v['max_drawdown']*100:.1f}%  ruined {v['ruined_on']}")
    (RES / "diagnostics.json").write_text(json.dumps(jsonable(out), indent=1))


if __name__ == "__main__":
    main()
