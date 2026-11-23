"""Walk-forward analysis of a replay run, and the ladder (ablation) tables.

  python analyze.py dev                  -> runs/dev_x1/analysis.json (+ the final target choices)
  python analyze.py final --prereg H     -> runs/final_x1/analysis.json, judged with the FROZEN choices in prereg.json
"""
import argparse
import json
import pickle
import sys
from collections import defaultdict
from datetime import date
from statistics import mean

from common import RUNS, HERE
import protocol as P
from pis.stats import summarize, t_crit
from pis.strategies import REGISTRY
from pis.timeutil import day_of


def load(tag):
    out = {}
    d = RUNS / tag
    for sid in REGISTRY:
        p = d / f"{sid}.pkl"
        if p.exists():
            out[sid] = pickle.load(open(p, "rb"))
    return out


def tday(p):
    return day_of(p["t_entry"])


def cut(trades, a, b, side=None):
    return [p for p in trades if a <= tday(p) <= b and (side is None or p["side"] == side)]


def mean_r(xs):
    return mean(p["r_net"] for p in xs) if xs else None


def choose(trades_by_target, a, b, side):
    best, best_r = P.DEFAULT_TARGET, None
    for tr in P.TARGETS:
        xs = cut(trades_by_target.get(tr, []), a, b, side)
        if len(xs) < P.MIN_TRAIN_TRADES:
            continue
        r = mean_r(xs)
        if best_r is None or r > best_r:
            best, best_r = tr, r
    return best, best_r


def by_target(res, sid, level):
    out = {}
    for tr in P.TARGETS:
        out[tr] = res["trades"].get(f"{sid}|R{tr:g}|{level}", [])
    return out


def sessions_between(res, a, b):
    return sum(1 for d, *_ in res["log"]["coverage"] if a <= date.fromisoformat(d) <= b)


def dev(res_all):
    out = {"folds": [[str(x) for x in f] for f in P.FOLDS], "strategies": {}}
    choices = {}
    for sid, res in res_all.items():
        S = {}
        for lv in P.LEVELS:
            bt = by_target(res, sid, lv)
            for side in (1, -1):
                oos, picks = [], []
                for (a, b, c, d) in P.FOLDS:
                    tr, r = choose(bt, a, b, side)
                    xs = cut(bt[tr], c, d, side)
                    picks.append({"test": [str(c), str(d)], "target_R": tr, "train_mean_R": r,
                                  "test_trades": len(xs), "test_mean_R": mean_r(xs)})
                    oos += xs
                ftr, fr = choose(bt, *P.FINAL_TRAIN, side)
                choices[f"{sid}|{lv}|{side}"] = ftr
                sess = sum(sessions_between(res, c, d) for (_, _, c, d) in P.FOLDS)
                st = summarize(oos, sessions=sess)
                st["folds_positive"] = sum(1 for x in picks if (x["test_mean_R"] or 0) > 0 and x["test_trades"] > 0)
                full = {f"R{tr:g}": summarize(cut(bt[tr], P.DEV_START, P.DEV_END, side)) for tr in P.TARGETS}
                S[f"{lv}|{'LONG' if side > 0 else 'SHORT'}"] = {"wf_oos": st, "picks": picks, "final_target_R": ftr,
                                                               "final_train_mean_R": fr, "dev_full_by_target": full}
        out["strategies"][sid] = {"name": REGISTRY[sid].name, "primary": REGISTRY[sid].primary, "levels": S,
                                  "setup_ends": res["setup_ends"], "seconds": res["seconds"]}
    out["final_choices"] = choices
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("period", choices=["dev"])
    a = ap.parse_args()
    res = load("dev_x1")
    if not res:
        sys.exit("no dev run")
    an = dev(res)
    (RUNS / "dev_x1" / "analysis.json").write_text(json.dumps(an, indent=1, default=str))
    # compact console table: WF-OOS by strategy, level, side
    print(f"{'strategy':8} {'lvl':3} {'side':5} {'n':>5} {'meanR':>7} {'bp':>7} {'PF':>5} {'t':>6} {'DD%':>5} {'folds+':>6}")
    for sid, s in an["strategies"].items():
        for key, v in s["levels"].items():
            st = v["wf_oos"]
            if not st.get("trades"):
                print(f"{sid:8} {key.split('|')[0]:3} {key.split('|')[1]:5} {0:5}")
                continue
            print(f"{sid:8} {key.split('|')[0]:3} {key.split('|')[1]:5} {st['trades']:5} {st['mean_R']:7.3f} "
                  f"{(st['mean_net_bp'] or 0):7.1f} {(st['profit_factor'] or 0):5.2f} {(st['t_day'] or 0):6.2f} "
                  f"{st['max_dd_pct']:5.1f} {st['folds_positive']:6}")


if __name__ == "__main__":
    main()
