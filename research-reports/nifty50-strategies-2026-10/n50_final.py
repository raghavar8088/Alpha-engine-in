"""Phase 2: the final test, run ONCE (PREREG_A1 sections 6, 8-10) on 2025-01-01 .. 2026-10-23, for the nine
configurations frozen in FROZEN_A1.json: the measures, the baselines B1-B3, the robustness variants, the
deflated Sharpe, the gate, the breakdowns and the membership sensitivity.

    python n50_final.py <data dir: n50_clean.pkl, universe.json> <out dir> [--dry]

--dry rehearses every code path with the validation year standing in for the final test (the panel is cut at
2024-12-31, so no final-test candle is read), so that the one real run cannot fail halfway through.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import n50_engine as E  # noqa: E402

POOLS = {"base": {}, "costs x1.5": {"cost_mult": 1.5}, "costs x2": {"cost_mult": 2.0}, "slippage +5bp": {"slip_bp": 7.0},
         "stop at range midpoint": {"stop_mid": True}, "target 1.5R": {"target_r": 1.5}, "target 3R": {"target_r": 3.0}}
VARIANTS = [  # (name, pool, n, threshold, setups it applies to)
    ("costs x1.5", "costs x1.5", 5, 0.25, E.SETUPS), ("costs x2", "costs x2", 5, 0.25, E.SETUPS),
    ("slippage +5bp", "slippage +5bp", 5, 0.25, E.SETUPS), ("N=3", "base", 3, 0.25, E.SETUPS),
    ("N=10", "base", 10, 0.25, E.SETUPS), ("threshold 0.15", "base", 5, 0.15, E.SETUPS),
    ("threshold 0.35", "base", 5, 0.35, E.SETUPS), ("30-minute range", "30-minute range", 5, 0.25, E.SETUPS),
    ("stop at range midpoint", "stop at range midpoint", 5, 0.25, ("S1", "S2")),
    ("target 1.5R", "target 1.5R", 5, 0.25, ("S1", "S3")), ("target 3R", "target 3R", 5, 0.25, ("S1", "S3")),
]
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)


def load_frozen():
    raw = (HERE / "FROZEN_A1.json").read_bytes().replace(b"\r\n", b"\n")
    want = (HERE / "FROZEN_A1.sha256").read_text().split()[0]
    got = hashlib.sha256(raw).hexdigest()
    if got != want:
        raise SystemExit(f"FROZEN_A1.json differs from its frozen sha256 ({got[:16]} != {want[:16]})")
    git = ["git", "-C", str(HERE)]
    dirty = subprocess.run(git + ["status", "--porcelain", "--", "FROZEN_A1.json"], capture_output=True, text=True).stdout
    commit = subprocess.run(git + ["log", "-1", "--format=%h %cI", "--", "FROZEN_A1.json"],
                            capture_output=True, text=True).stdout.strip()
    if dirty.strip() or not commit:
        raise SystemExit("FROZEN_A1.json is not committed unchanged")
    return json.loads(raw), commit, got


def make_pools(P, f, thr_min=0.25, **kw):
    return {st: {sd: E.pool(P, f, st, sd, thr_min=thr_min, **kw) for sd in (1, -1)} for st in E.SETUPS}


def run(pools, cfg, n=5, thr=0.25):
    filt = {int(k): v for k, v in cfg["filters"].items()}
    return E.select(pools[cfg["setup"]], filt, n=n, thr=thr, sides=tuple(cfg["sides"]))


def by_year(T):
    g = T.groupby(T.day.dt.year).net.sum() if len(T) else pd.Series(dtype=float)
    return {int(y): round(float(g.get(y, 0.0)), 0) for y in YEARS}


def brief(T):
    return {"trades": int(len(T)), "net": round(float(T.net.sum()), 0) if len(T) else 0.0,
            "mean_R": round(float(T.R.mean()), 4) if len(T) else None}


def breakdowns(T, P):
    if T.empty:
        return {}
    T = T.copy()
    di = T.d.to_numpy()
    T["year"] = T.day.dt.year
    T["sector"] = T.stock.map(P.sector)
    T["day type"] = np.where(np.abs(P.nifty_dayret[di]) > 0.01, "trend (|NIFTY day| > 1%)", "range")
    T["VIX regime"] = np.where(P.vix_high[di], "VIX above its 60-day median", "VIX at or below")
    T["gap"] = pd.cut(T.gap * T.side, [-np.inf, -0.01, 0.0, 0.01, np.inf],
                      labels=["against, over 1%", "against, up to 1%", "with, up to 1%", "with, over 1%"])
    T["direction"] = np.where(T.side > 0, "long", "short")
    T["exit"] = T.reason.map(E.REASONS)
    out = {}
    for col in ("year", "direction", "exit", "day type", "VIX regime", "gap", "sector", "stock"):
        out[col] = {str(k): {"trades": int(len(x)), "net": round(float(x.net.sum()), 0),
                             "mean_R": round(float(x.R.mean()), 4), "win_rate": round(float((x.net > 0).mean()), 3)}
                    for k, x in T.groupby(col, observed=True)}
    return out


def main(data, out, dry):
    t0 = time.time()
    data, out = Path(data), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    frozen, commit, fsha = load_frozen()
    print(f"frozen configurations: FROZEN_A1.json sha256 {fsha[:16]}, committed {commit}")
    psha = hashlib.sha256((data / "n50_clean.pkl").read_bytes()).hexdigest()
    if psha != frozen["panel_sha256"]:
        raise SystemExit("the clean panel is not the one the configurations were frozen on")
    if dry:
        E.PERIODS["final"] = E.PERIODS["val"]
        print("DRY RUN: the validation year stands in for the final test; no final-test candle is read")
    mem, uni = HERE / "phase0" / "membership.json", data / "universe.json"
    P = E.Panel(data / "n50_clean.pkl", mem, uni, end="2024-12-31" if dry else None)
    f3, f6 = P.screen(3), P.screen(6)
    pools = {k: make_pools(P, f3, thr_min=0.15 if k == "base" else 0.25, **kw) for k, kw in POOLS.items()}
    pools["30-minute range"] = make_pools(P, f6)
    days_final = E.period_days(P, "final")
    print(f"panel {P.days[0].date()}..{P.days[-1].date()}; final test {days_final[0].date()}..{days_final[-1].date()}"
          f" ({len(days_final)} sessions); pools built in {time.time() - t0:.0f}s")

    abl = json.load(open(out / "ablation_A1.json"))["configs"] if (out / "ablation_A1.json").exists() else {}
    results = {}
    for key, cfg in frozen["configs"].items():
        st = cfg["setup"]
        T = run(pools["base"], cfg)
        Tf = E.in_period(T, "final")
        r = {per: E.summarize(E.in_period(T, per), E.period_days(P, per)) for per in ("dev", "val", "final")}
        if not dry and key in abl:                     # the full panel must reproduce the cut panel's results
            for per in ("dev", "val"):
                a, b = abl[key][per], r[per]
                if (a["trades"], a["net"]) != (b["trades"], b["net"]):
                    raise SystemExit(f"{key} {per}: full panel {b['trades']}/{b['net']} != ablation {a['trades']}/{a['net']}")
        r["net_by_year"] = by_year(T)
        r["B2"] = E.vs_random(Tf, E.baseline_random(P, Tf, random_side=True, seed=17)) if len(Tf) > 2 else None
        r["B3"] = E.vs_random(Tf, E.baseline_random(P, Tf, random_side=False, seed=18)) if len(Tf) > 2 else None
        rob = {}
        for name, pl, n, thr, setups in VARIANTS:
            if st in setups:
                rob[name] = brief(E.in_period(run(pools[pl], cfg, n=n, thr=thr), "final"))
        if len(Tf):
            ns = Tf.groupby("stock").net.sum()
            ny = Tf.groupby(Tf.day.dt.year).net.sum()
            rob[f"without the best stock ({ns.idxmax()})"] = brief(Tf[Tf.stock != ns.idxmax()])
            rob[f"without the best year ({int(ny.idxmax())})"] = brief(Tf[Tf.day.dt.year != ny.idxmax()])
            net = float(Tf.net.sum())
            r["max_stock_share_of_net"] = round(float(ns.max()) / net, 3) if net > 0 else None
            r["top_stocks"] = {k: round(float(v), 0) for k, v in ns.sort_values(ascending=False).head(5).items()}
        r["robustness"] = rob
        r["breakdowns"] = {"final": breakdowns(Tf, P), "dev+val": breakdowns(T[T.day < pd.Timestamp("2025-01-01")], P)}
        results[key] = r
        b2 = r["B2"] or {}
        print(f"{key:9} final: {r['final']['trades']:>4} trades  net {r['final']['net']:>10,.0f}  mean R "
              f"{r['final']['mean_R']}  B2 t {b2.get('t')}  ({time.time() - t0:.0f}s)")

    n_trials = frozen["ablation_trials"] + sum(len(r["robustness"]) for r in results.values())
    for key, r in results.items():
        fs, rob = r["final"], r["robustness"]
        dsr, sr0 = E.deflated_sharpe(fs["sharpe_daily"], fs["days"], fs["skew"], fs["kurt"],
                                     frozen["ablation_trial_sharpe_daily_var"], n_trials)
        r["deflated_sharpe"], r["dsr_benchmark_sharpe_daily"] = round(dsr, 4), round(sr0, 5)
        # Diagnostics outside the gate: the same deflation with the trials' spread set to pure sampling noise
        # (1 / development-and-validation sessions) instead of the observed spread, and the plain probability
        # that the true Sharpe is above zero (no deflation at all).
        lenient, sr0l = E.deflated_sharpe(fs["sharpe_daily"], fs["days"], fs["skew"], fs["kurt"],
                                          1.0 / frozen.get("devval_sessions", 800), n_trials)
        psr, _ = E.deflated_sharpe(fs["sharpe_daily"], fs["days"], fs["skew"], fs["kurt"], 0.0, n_trials)
        r["dsr_noise_only_spread"], r["dsr_noise_only_benchmark"] = round(lenient, 4), round(sr0l, 5)
        r["prob_sharpe_above_zero"] = round(psr, 4)
        gate = {"final net > 0": fs["net"] > 0,
                "final net > 0 at 2x costs": rob["costs x2"]["net"] > 0,
                "mean R beats B2 with t >= 2.5": bool(r["B2"] and r["B2"]["t"] >= 2.5),
                "deflated Sharpe >= 0.95": dsr >= 0.95,
                "net > 0 in 2022, 2023 and 2024": all(r["net_by_year"][y] > 0 for y in (2022, 2023, 2024)),
                "no stock above 20% of the net profit": r.get("max_stock_share_of_net") is not None
                and r["max_stock_share_of_net"] <= 0.20,
                "every robustness variant net > 0": all(v["net"] > 0 for v in rob.values())}
        r["gate"], r["passes"] = gate, all(gate.values())

    b1 = {}
    for per in ("dev", "val", "final"):
        B = E.baseline_b1(P, f3, np.isin(P.days, E.period_days(P, per)))
        b1[per] = E.summarize(B, E.period_days(P, per))
    result = {"dry_run": dry, "frozen_sha256": fsha, "frozen_commit": commit, "n_trials_for_dsr": n_trials,
              "final_period": [str(days_final[0].date()), str(days_final[-1].date())], "configs": results, "B1": b1}
    name = "final_A1_DRYRUN.json" if dry else "final_A1.json"
    json.dump(result, open(out / name, "w"), indent=1, default=str)

    print(f"\nB1 plain ORB final: {b1['final']['trades']} trades, net {b1['final']['net']:,.0f}, mean R {b1['final']['mean_R']}")
    print(f"deflated Sharpe counts {n_trials} configurations")
    print(f"{'config':9} {'trades':>6} {'net Rs':>10} {'net%':>6} {'meanR':>7} {'win':>5} {'PF':>5} {'maxDD%':>7}"
          f" {'Sh.ann':>6} {'B2 t':>5} {'B3 t':>5} {'DSR':>5} {'DSRn':>5} {'PSR0':>5}  gate")
    for key, r in results.items():
        fs = r["final"]
        print(f"{key:9} {fs['trades']:>6} {fs['net']:>10,.0f} {fs['net_pct']:>6} {fs['mean_R'] or 0:>7.4f}"
              f" {fs['win_rate'] or 0:>5.2f} {fs['pf'] or 0:>5.2f} {fs['max_dd_pct']:>7} {fs['sharpe_ann']:>6}"
              f" {(r['B2'] or {}).get('t', 0):>5} {(r['B3'] or {}).get('t', 0):>5} {r['deflated_sharpe']:>5.2f}"
              f" {r['dsr_noise_only_spread']:>5.2f} {r['prob_sharpe_above_zero']:>5.2f}  "
              f"{'PASS' if r['passes'] else 'fail: ' + ', '.join(k for k, v in r['gate'].items() if not v)}")

    if not dry:                                        # the pre-registered membership sensitivity
        del pools, P
        P2 = E.Panel(data / "n50_clean.pkl", mem, uni, swap_date="2026-09-30")
        f2 = P2.screen(3)
        pools2 = make_pools(P2, f2)
        sens = {key: brief(E.in_period(run(pools2, cfg), "final")) for key, cfg in frozen["configs"].items()}
        result["bse_wipro_swap_2026_09_30"] = sens
        json.dump(result, open(out / name, "w"), indent=1, default=str)
        print("BSE-for-WIPRO on 2026-09-30 instead:", {k: v["net"] for k, v in sens.items()})
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    main(a.data, a.out, a.dry)
