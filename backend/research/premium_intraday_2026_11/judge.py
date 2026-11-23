"""Judge the new strategies on the frozen pre-registration: final period at 1x/2x/3x slippage, pooled with the
walk-forward out-of-sample trades; the ladder (ablation) tables; lifecycle status with every criterion shown.

  python judge.py --prereg <sha256>    -> results/new_strategies.json
"""
import argparse
import hashlib
import json
import pickle
import sys
from collections import defaultdict
from datetime import date
from statistics import mean

from common import HERE, RUNS
import protocol as P
from analyze import by_target, choose, cut, load, sessions_between, tday
from pis.stats import summarize, t_crit
from pis.strategies import REGISTRY
from pis.timeutil import day_of

CAP = 1_000_000.0


def utilization(trades, sessions):
    """Time-weighted average notional deployed over the session's 375 minutes, as a share of capital."""
    if not trades or not sessions:
        return 0.0, 0.0
    tw, peak_by_day = 0.0, defaultdict(float)
    for p in trades:
        mins = max(5, (p["t_exit"] - p["t_entry"]) / 60)
        tw += p["notional"] * mins
        peak_by_day[str(day_of(p["t_entry"]))] += p["notional"]
    return tw / (375 * sessions) / CAP * 100, max(peak_by_day.values()) / CAP * 100


def wf_oos(res, sid, lv, side):
    bt = by_target(res, sid, lv)
    out = []
    for (a, b, c, d) in P.FOLDS:
        tr, _ = choose(bt, a, b, side)
        out += cut(bt[tr], c, d, side)
    return out


def fold_means(res, sid, lv, side):
    bt = by_target(res, sid, lv)
    xs = []
    for (a, b, c, d) in P.FOLDS:
        tr, _ = choose(bt, a, b, side)
        f = cut(bt[tr], c, d, side)
        xs.append(mean(p["r_net"] for p in f) if f else None)
    return xs


def judge_one(dev, fin, fin2, fin3, sid, lv, side, frozen, sessions_final, sessions_oos):
    tr = frozen.get(f"{sid}|{lv}|{side}", P.DEFAULT_TARGET)
    key = f"{sid}|R{tr:g}|{lv}"
    f1 = [p for p in fin["trades"].get(key, []) if p["side"] == side]
    f2 = [p for p in fin2["trades"].get(key, []) if p["side"] == side]
    f3 = [p for p in fin3["trades"].get(key, []) if p["side"] == side]
    oos = wf_oos(dev, sid, lv, side)
    pooled = oos + f1
    s_oos, s_fin = summarize(oos, sessions=sessions_oos), summarize(f1, sessions=sessions_final)
    s_f2, s_f3 = summarize(f2, sessions=sessions_final), summarize(f3, sessions=sessions_final)
    s_pool = summarize(pooled)
    folds = fold_means(dev, sid, lv, side)
    C = P.CRITERIA["backtest_qualified"]
    g = lambda s, k: s.get(k) if s.get("trades") else None
    checks = [
        ("walk-forward trades >= 60", g(s_oos, "trades") or 0, (g(s_oos, "trades") or 0) >= C["wf_oos_min_trades"]),
        ("walk-forward mean net R > 0", g(s_oos, "mean_R"), (g(s_oos, "mean_R") or -1) > 0),
        ("walk-forward folds positive >= 3 of 4", sum(1 for x in folds if x is not None and x > 0),
         sum(1 for x in folds if x is not None and x > 0) >= C["wf_folds_positive_min"]),
        ("final trades >= 30", g(s_fin, "trades") or 0, (g(s_fin, "trades") or 0) >= C["final_min_trades"]),
        ("final mean net R > 0", g(s_fin, "mean_R"), (g(s_fin, "mean_R") or -1) > 0),
        ("final profit factor >= 1.10", g(s_fin, "profit_factor"), (g(s_fin, "profit_factor") or 0) >= C["final_profit_factor_ge"]),
        ("final mean net R at 2x slippage >= 0", g(s_f2, "mean_R"), (g(s_f2, "mean_R") or -1) >= 0),
        ("pooled day-clustered t >= 2.0", g(s_pool, "t_day"), (g(s_pool, "t_day") or -99) >= C["pooled_t_day_ge"]),
        ("pooled net without the best 5% of days > 0", g(s_pool, "net_ex_best5pct_days"),
         (g(s_pool, "net_ex_best5pct_days") or -1) > 0),
        ("largest single stock <= 35% of profit", g(s_pool, "top_symbol_share"),
         g(s_pool, "top_symbol_share") is not None and g(s_pool, "top_symbol_share") <= C["pooled_top_symbol_share_le"]),
        ("final book drawdown <= 5%", g(s_fin, "max_dd_pct"), (g(s_fin, "max_dd_pct") if s_fin.get("trades") else 99) <= C["final_book_max_dd_pct_le"]),
    ]
    qualified = all(c[2] for c in checks)
    failed = [c[0] for c in checks if not c[2]]
    u_avg, u_peak = utilization(f1, sessions_final)
    return {"strategy": sid, "level": lv, "side": "LONG" if side > 0 else "SHORT", "target_R": tr,
            "walk_forward": s_oos, "wf_fold_mean_R": folds, "final": s_fin, "final_x2": s_f2, "final_x3": s_f3,
            "pooled": s_pool, "checks": [{"name": n, "value": v, "pass": ok} for n, v, ok in checks],
            "qualified": qualified,
            "status": "Forward Paper Observation" if qualified else "Rejected",
            "reason": ("passed every backtest criterion; now needs forward paper confirmation" if qualified else
                       "failed: " + "; ".join(failed)),
            "allocated": CAP, "utilized_avg_pct": u_avg, "utilized_peak_pct": u_peak}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prereg", required=True)
    a = ap.parse_args()
    if hashlib.sha256((HERE / "prereg.json").read_bytes()).hexdigest() != a.prereg:
        sys.exit("prereg.json does not match")
    pre = json.loads((HERE / "prereg.json").read_text())
    frozen = pre["frozen_final_targets"]
    dev, fin, fin2, fin3 = load("dev_x1"), load("final_x1"), load("final_x2"), load("final_x3")
    out = {"prereg_sha256": a.prereg, "K": P.K_TRIALS, "t_bonferroni": t_crit(P.K_TRIALS), "strategies": {}, "ladder": {}}
    for sid, cls in REGISTRY.items():
        sf = fin[sid]["sessions"]
        so = sum(sessions_between(dev[sid], c, d) for (_, _, c, d) in P.FOLDS)
        rows = {}
        for lv in P.LEVELS:
            for side in (1, -1):
                rows[f"{lv}|{'LONG' if side > 0 else 'SHORT'}"] = judge_one(dev[sid], fin[sid], fin2[sid], fin3[sid],
                                                                             sid, lv, side, frozen, sf, so)
        prim = cls.primary
        out["strategies"][sid] = {
            "name": cls.name, "family": cls.family, "primary_level": prim,
            "LONG": rows[f"{prim}|LONG"], "SHORT": rows[f"{prim}|SHORT"],
            "setup_ends_final": fin[sid]["setup_ends"], "sessions_final": sf, "sessions_wf_oos": so,
        }
        lad = {}
        for side in ("LONG", "SHORT"):
            base_fin = rows[f"L0|{side}"]["final"].get("trades") or 0
            base_oos = rows[f"L0|{side}"]["walk_forward"].get("trades") or 0
            lad[side] = [{
                "level": lv, "label": {"L0": "rule alone", "L1": "+ sector confirmation", "L2": "+ 09:40 checkpoint",
                                       "L3": "+ news"}[lv],
                "wf_trades": rows[f"{lv}|{side}"]["walk_forward"].get("trades") or 0,
                "wf_mean_R": rows[f"{lv}|{side}"]["walk_forward"].get("mean_R"),
                "wf_net_bp": rows[f"{lv}|{side}"]["walk_forward"].get("mean_net_bp"),
                "wf_max_dd_pct": rows[f"{lv}|{side}"]["walk_forward"].get("max_dd_pct"),
                "final_trades": rows[f"{lv}|{side}"]["final"].get("trades") or 0,
                "final_mean_R": rows[f"{lv}|{side}"]["final"].get("mean_R"),
                "final_net_bp": rows[f"{lv}|{side}"]["final"].get("mean_net_bp"),
                "final_max_dd_pct": rows[f"{lv}|{side}"]["final"].get("max_dd_pct"),
                "removed_vs_rule_alone_final": (1 - (rows[f"{lv}|{side}"]["final"].get("trades") or 0) / base_fin) if base_fin else None,
                "removed_vs_rule_alone_wf": (1 - (rows[f"{lv}|{side}"]["walk_forward"].get("trades") or 0) / base_oos) if base_oos else None,
                "news_period_only": lv == "L3",
            } for lv in P.LEVELS]
        out["ladder"][sid] = lad
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "new_strategies.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"{'sid':4} {'side':5} {'tgt':>4} {'WF n':>5} {'WF R':>7} {'fin n':>5} {'fin R':>7} {'x2 R':>7} {'x3 R':>7} {'PF':>5} {'pool t':>6}  status")
    for sid, s in out["strategies"].items():
        for side in ("LONG", "SHORT"):
            r = s[side]
            f = r["final"]
            print(f"{sid:4} {side:5} {r['target_R']:4} {r['walk_forward'].get('trades', 0):5} {(r['walk_forward'].get('mean_R') or 0):7.3f} "
                  f"{f.get('trades', 0):5} {(f.get('mean_R') or 0):7.3f} {(r['final_x2'].get('mean_R') or 0):7.3f} "
                  f"{(r['final_x3'].get('mean_R') or 0):7.3f} {(f.get('profit_factor') or 0):5.2f} {(r['pooled'].get('t_day') or 0):6.2f}  {r['status']}")
    print("\nladder (final mean R / trades):")
    for sid, lad in out["ladder"].items():
        for side, rows in lad.items():
            print(sid, side, " | ".join(f"{x['level']} {(x['final_mean_R'] or 0):+.3f} ({x['final_trades']})" for x in rows))


if __name__ == "__main__":
    main()
