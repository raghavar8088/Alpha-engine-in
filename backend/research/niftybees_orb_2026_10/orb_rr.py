"""Risk-reward 1:3, 1:4, 1:5 and 1:6: the primary rules with ONLY the target changed (owner's request, 2026-10-25).

    python -I backend/research/niftybees_orb_2026_10/orb_rr.py

The target becomes 3x, 4x, 5x or 6x the distance from the entry fill to the stop. The opening range, entry, stop,
one trade a day, 09:30-15:00 entries, 15:15 exit, Rs10 lakh size, Angel One charges, 1 bp slippage,
trade-through target fills and the worse-path rule inside a candle are all unchanged. 1:2 is rerun
alongside for comparison, and each ratio is also walked on 1-minute candles.

Writes results/rr_compare.json, and the trade log and yearly table of each new ratio.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from orb_engine import Config, load, run  # noqa: E402
from orb_run import ambiguity, diagnostics, inr, stats, trade_rows, write_csv, yearly  # noqa: E402

RES = HERE / "results"
RATIOS = (2.0, 3.0, 4.0, 5.0, 6.0)


def check(r: dict, rr: float) -> None:
    """The invariants of orb_verify.py, for this ratio."""
    tr = r["trades"]
    days: dict[str, int] = {}
    for t in tr:
        days[t.date] = days.get(t.date, 0) + 1
    assert max(days.values()) == 1, "more than one trade a day"
    assert all(15 <= t.entry_bar < 345 and t.exit_bar < 360 for t in tr), "entry or exit outside its window"
    assert all(abs(abs(t.target - t.entry_fill) - rr * abs(t.entry_fill - t.stop)) <= 1 for t in tr), "target not rr x R"
    assert all(t.exit_reason != "target" or t.exit_fill == t.target for t in tr), "target filled off its price"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    data = load(HERE / "data")
    out = {}
    for rr in RATIOS:
        name = f"rr_1_{int(rr)}"
        cfg = replace(Config(), name=name, rr=rr)
        r5 = run(cfg, data)
        r1 = run(replace(cfg, name=name + "_1m", bars=1), data)
        check(r5, rr)
        check(r1, rr)
        s5 = stats(r5["trades"], r5["sessions"], cfg.capital)
        s1 = stats(r1["trades"], r1["sessions"], cfg.capital)
        before = s5["net_pnl"] + s5["charges"] + s5["slippage"]
        yr = yearly(r5["trades"], r5["sessions"], cfg.capital)
        for y in yr:                       # before-costs and costs per year, from the trades
            tt = [t for t in r5["trades"] if t.date.startswith(y["year"])]
            y["before"] = sum(t.net + t.fees + t.slippage for t in tt)
            y["costs"] = sum(t.fees + t.slippage for t in tt)
        out[name] = {"rr": rr, "config": asdict(cfg), "stats": s5, "before_costs": before, "yearly": yr,
                     "one_minute": {"stats": s1, "yearly": yearly(r1["trades"], r1["sessions"], cfg.capital)},
                     "ambiguity": ambiguity(r5, r1), "diagnostics": diagnostics(r5["trades"])}
        if rr != 2.0:
            write_csv(RES / f"trades_{name}.csv", trade_rows(r5["trades"], 5))
            write_csv(RES / f"yearly_{name}.csv", yr)
        ex = s5["exit_reasons"]
        print(f"1:{int(rr)}  trades {s5['trades']}  win {s5['win_rate']:.1f}%  net {inr(s5['net_pnl'])}  "
              f"PF {s5['profit_factor']:.3f}  maxDD {inr(s5['max_dd'])} ({s5['max_dd_pct_of_capital']:.1f}%)  "
              f"before costs {inr(before)}  R/trade {s5['avg_r_net']:+.3f}  t {s5['t_stat']:+.2f}  "
              f"exits T/S/EOD {ex.get('target', {}).get('trades', 0)}/{ex.get('stop', {}).get('trades', 0)}/"
              f"{ex.get('eod', {}).get('trades', 0)}  | 1m net {inr(s1['net_pnl'])}  ambiguous {s5['ambiguous_trades']}",
              flush=True)
        for y in yr:
            print(f"   {y['year']}  trades {y['trades']:3}  win {y['win_rate']:5.1f}%  net {inr(y['net_pnl']):>11}  "
                  f"ret {y['return_pct']:+6.1f}%  PF {y['profit_factor']:.2f}  maxDD {inr(y['max_dd']):>10}  "
                  f"T/S/E {y['targets']}/{y['stops']}/{y['eod']}")
    with open(RES / "rr_compare.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    main()
