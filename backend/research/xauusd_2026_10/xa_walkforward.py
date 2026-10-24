"""Two supplementary out-of-sample checks. Both were designed AFTER the locked evaluation had been
seen (only one strategy passed, on a single trade), and the report says so. Neither changes a
locked verdict; the rules below were fixed before either check was run.

  python xa_walkforward.py presample
      The locked configurations on 2005-01-01 .. 2009-12-31: years no stage has read (they were
      indicator warm-up only). Before 2008 the ask is the bid plus 2008's median spread.
  python xa_walkforward.py walk
      Expanding-window walk-forward, test years 2014 .. latest. Each calendar year's configuration
      is chosen by the SAME selection rule as the locked study, on 2010-01-01 .. the end of the
      previous year only. Consecutive years with the same choice trade as one run, so no trade is
      cut at a year end; a year with no eligible configuration is flat.

WALK-FORWARD PASS (fixed before running): at least 20 trades (the locked test's rate of ~1.6 a
year, over ~12.8 years), an average net return of at least 2% a trade under base costs C1, and a
profit factor above 1. Timing is tested against the same trades entered at random dates over the
same years, and Holm-corrected across the families tested.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # own modules only; data/ is never on the path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

import xa_strategies as S
from xa_engine import COSTS, curve_stats, equity_curve, net_returns, stats, trades_frame
from xa_run import (IS_START, MIN_IS_TRADES, RES, TARGET, _jsonable, bootstrap_ci, buy_and_hold, evaluate_window, holm,
                    market, random_entry_test, simulate)

WF_FIRST_YEAR = 2014
WF_MIN_TRADES = 20
PRE = ("2005-01-01", "2010-01-01")


def _select(fam: S.Family, train_last: int):
    """The locked study's selection rule on 2010-01-01 .. train_last."""
    m = market()
    first = m.session_index(IS_START)
    best = None
    for cfg in fam.configs():
        tf = simulate(fam, cfg, first, train_last)
        st = stats(net_returns(m, tf, COSTS["C1"]))
        if st.get("trades", 0) >= MIN_IS_TRADES and st.get("avg", -1) >= TARGET:
            key = (st["t_stat"] if st["t_stat"] == st["t_stat"] else -9, st["avg"])
            if best is None or key > best[0]:
                best = (key, cfg)
    return None if best is None else best[1]


def _walk_family(key: str) -> dict:
    fam = next(f for f in S.FAMILIES if f.key == key)
    m = market()
    years = list(range(WF_FIRST_YEAR, int(str(m.d_date[-1])[:4]) + 1))
    choice = {}
    for y in years:
        train_last = m.session_index(f"{y}-01-01") - 1
        choice[y] = _select(fam, train_last)
    # runs of consecutive years with the same configuration
    runs, cur = [], None
    for y in years:
        c = choice[y]
        if cur and cur["cfg"] == c:
            cur["years"].append(y)
        else:
            cur = {"cfg": c, "years": [y]}
            runs.append(cur)
    frames = []
    for r in runs:
        if r["cfg"] is None:
            continue
        a = m.session_index(f"{r['years'][0]}-01-01")
        b = min(m.session_index(f"{r['years'][-1] + 1}-01-01") - 1, len(m.d_date) - 1)
        frames.append(simulate(fam, r["cfg"], a, b))
    tf = pd.concat(frames, ignore_index=True) if frames else trades_frame(m, [])
    first = m.session_index(f"{WF_FIRST_YEAR}-01-01")
    last = len(m.d_date) - 1
    out = {"key": key, "choices": {str(y): (S.label(c) if c else None) for y, c in choice.items()},
           "years_traded": sum(1 for c in choice.values() if c)}
    for ck, c in COSTS.items():
        r = net_returns(m, tf, c)
        out[ck] = stats(r)
        if ck == "C1":
            out[ck].update(curve_stats(equity_curve(m, tf, r, first, last, c)))
    r1 = net_returns(m, tf, COSTS["C1"])
    if len(r1):
        re = random_entry_test(m, tf, first, last, COSTS["C1"])
        out["random_mean_avg"] = re["random_mean_avg"]
        out["timing_p"] = float((re["means"] >= r1.mean()).mean())
        out["ci95"] = bootstrap_ci(r1)
        out["share_of_profit_from_best_trade"] = float(r1.max() / r1[r1 > 0].sum()) if (r1 > 0).any() else None
        t2 = tf.copy()
        t2["net"] = r1
        out["by_entry_year"] = {int(y): {"trades": int(len(g)), "avg": float(g["net"].mean())}
                                for y, g in t2.groupby(pd.to_datetime(t2["entry_date"]).dt.year)}
    out["PASS"] = (out["C1"].get("trades", 0) >= WF_MIN_TRADES and out["C1"].get("avg", -1) >= TARGET
                   and (out["C1"].get("profit_factor") or 0) > 1)
    return out


def _presample_family(key: str) -> dict:
    lock = json.loads((RES / "selection_locked.json").read_text())
    fam = next(f for f in S.FAMILIES if f.key == key)
    entry = lock["families"][key]
    cfg = {k: (tuple(v) if isinstance(v, list) else v) for k, v in entry["config"].items()}
    m = market()
    a, b = m.session_index(PRE[0]), m.session_index(PRE[1]) - 1
    res = evaluate_window(fam, cfg, a, b, curves=True)
    tf = res["tf"]
    r1 = net_returns(m, tf, COSTS["C1"])
    out = {"key": key, "status_is": entry["status"], "label": S.label(cfg), "C1": res["C1"], "C2": res["C2"]}
    if len(r1):
        re = random_entry_test(m, tf, a, b, COSTS["C1"])
        out["random_mean_avg"] = re["random_mean_avg"]
        out["timing_p"] = float((re["means"] >= r1.mean()).mean())
        out["ci95"] = bootstrap_ci(r1)
    out["passes_2pct"] = (res["C1"].get("trades", 0) >= 8 and res["C1"].get("avg", -1) >= TARGET and (res["C1"].get("profit_factor") or 0) > 1)
    return out


def main(what: str) -> None:
    m = market()
    path = RES / "supplementary.json"
    sup = json.loads(path.read_text()) if path.exists() else {}
    keys = [f.key for f in S.FAMILIES]
    if what == "presample":
        with ProcessPoolExecutor(max_workers=12) as ex:
            rows = list(ex.map(_presample_family, keys))
        a, b = m.session_index(PRE[0]), m.session_index(PRE[1]) - 1
        sup["presample"] = {"window": [str(m.d_date[a]), str(m.d_date[b])], "buy_and_hold": buy_and_hold(m, a, b)["C1"],
                            "families": {r["key"]: r for r in rows}}
        for r in rows:
            c = r["C1"]
            print(f"{r['key']:<18} {r['status_is']:<17} {r['label']:<55} trades {c.get('trades', 0):>4} avg {(c.get('avg') or 0) * 100:7.2f}%  "
                  f"pf {(c.get('profit_factor') or 0):6.2f}  random {(r.get('random_mean_avg') or 0) * 100:6.2f}%  p {r.get('timing_p', float('nan')):.3f}  "
                  f"{'PASSES 2%' if r['passes_2pct'] else ''}")
        print("buy & hold 2005-2009:", {k: round(v, 4) for k, v in sup["presample"]["buy_and_hold"].items() if k != "by_year"})
    elif what == "walk":
        with ProcessPoolExecutor(max_workers=12) as ex:
            rows = list(ex.map(_walk_family, keys))
        padj = holm({r["key"]: r.get("timing_p", np.nan) for r in rows if r["C1"].get("trades", 0) > 0})
        a = m.session_index(f"{WF_FIRST_YEAR}-01-01")
        sup["walk_forward"] = {"first_year": WF_FIRST_YEAR, "min_trades": WF_MIN_TRADES,
                               "buy_and_hold": buy_and_hold(m, a, len(m.d_date) - 1)["C1"],
                               "families": {r["key"]: r | {"timing_p_holm": padj.get(r["key"])} for r in rows}}
        for r in rows:
            c = r["C1"]
            print(f"{r['key']:<18} years traded {r['years_traded']:>2}  trades {c.get('trades', 0):>4}  avg {(c.get('avg') or 0) * 100:7.2f}%  "
                  f"pf {(c.get('profit_factor') or 0):6.2f}  random {(r.get('random_mean_avg') or 0) * 100:6.2f}%  p {r.get('timing_p', float('nan')):.3f}  "
                  f"holm {padj.get(r['key'], float('nan')):.3f}  best-trade share {(r.get('share_of_profit_from_best_trade') or 0):.2f}  {'PASS' if r['PASS'] else ''}")
        print("buy & hold 2014-latest:", {k: round(v, 4) for k, v in sup["walk_forward"]["buy_and_hold"].items() if k != "by_year"})
    path.write_text(json.dumps(_jsonable(sup), indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
