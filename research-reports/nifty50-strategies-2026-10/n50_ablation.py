"""Phase 1: the confirmation filters earn their place on development and validation data (PREREG_A1 §3),
then the configurations are frozen before the final test.

    python n50_ablation.py <data dir: n50_clean.pkl, universe.json> <out dir>

The panel is cut at 2024-12-31 before anything is computed, so no final-test candle is ever read here.
Writes <out>/ablation_A1.json (every configuration tried, with its development and validation measures)
and FROZEN_A1.json beside this file (the frozen configurations, the trial count and the trials' Sharpe
spread for the deflated Sharpe), with its sha256.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import n50_engine as E  # noqa: E402

SIDES = {"long": (1,), "short": (-1,), "both": (1, -1)}
YEARS = (2021, 2022, 2023, 2024)


def measure(T, P):
    out = {per: E.summarize(E.in_period(T, per), E.period_days(P, per)) for per in ("dev", "val")}
    out["dev+val"] = E.summarize(T, P.days)
    return out


def by_year(T):
    g = T.groupby(T.day.dt.year).net.sum() if len(T) else pd.Series(dtype=float)
    return {int(y): round(float(g.get(y, 0.0)), 0) for y in YEARS}


def describe(P, f):
    """Data and screen mechanics only - no strategy measure."""
    el = f["eligible"]
    yr = P.days.year.to_numpy()
    hs = pd.Series(P.spread_table)
    hs_year = hs.groupby(hs.index.str[-4:]).describe()[["min", "50%", "max"]].round(2)
    with np.errstate(invalid="ignore"):
        lc = el & (f["or_move"] >= 0.25)
        sc = el & (f["or_move"] <= -0.25)
    o71 = P.S["o"][:, :, E.B1510]
    return {
        "sessions": len(P.days), "first": str(P.days[0].date()), "last": str(P.days[-1].date()),
        "members_per_session": [int(P.member.sum(axis=0).min()), int(P.member.sum(axis=0).max())],
        "eligible_stock_days_by_year": {int(y): int(el[:, yr == y].sum()) for y in np.unique(yr)},
        "eligible_per_session_mean": round(float(el.sum(axis=0)[el.sum(axis=0) > 0].mean()), 1),
        "long_candidates_share": round(float(lc.sum() / el.sum()), 4),
        "short_candidates_share": round(float(sc.sum() / el.sum()), 4),
        "sessions_with_a_long_candidate": int((lc.sum(axis=0) > 0).sum()),
        "sessions_with_a_short_candidate": int((sc.sum(axis=0) > 0).sum()),
        "eligible_without_1510_candle": int((el & ~np.isfinite(o71)).sum()),
        "sector_index_fallbacks": f["sector_fallback"],
        "half_spread_bp_by_year": {k: v for k, v in hs_year.to_dict("index").items()},
        "widest_half_spreads_bp": hs.sort_values(ascending=False).head(8).to_dict(),
    }


def main(data, out):
    t0 = time.time()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    data = Path(data)
    P = E.Panel(data / "n50_clean.pkl", HERE / "phase0" / "membership.json", data / "universe.json", end="2024-12-31")
    assert P.days.max() <= pd.Timestamp("2024-12-31")
    f = P.screen(3)
    desc = describe(P, f)
    print(f"panel {desc['first']}..{desc['last']}, {desc['sessions']} sessions, built in {time.time() - t0:.0f}s")
    print(json.dumps({k: v for k, v in desc.items() if k not in ("half_spread_bp_by_year", "widest_half_spreads_bp")}))
    print("half-spread bp by year:", desc["half_spread_bp_by_year"])

    pools = {st: {sd: E.pool(P, f, st, sd) for sd in (1, -1)} for st in E.SETUPS}
    for st in E.SETUPS:
        for sd in (1, -1):
            p = pools[st][sd]
            print(f"pool {st} {'long ' if sd > 0 else 'short'}: {len(p)} candidates, {int(p.ok.sum())} trade")

    trials, steps_log, frozen = [], {}, {}
    for st in E.SETUPS:
        frozen[st] = {}
        for name in ("long", "short"):
            sd = SIDES[name][0]
            cur = []
            T = E.select(pools[st], {sd: cur}, sides=(sd,))
            m = measure(T, P)
            trials.append({"setup": st, "side": name, "filters": [], "dev": m["dev"], "val": m["val"],
                           "sharpe_daily_devval": m["dev+val"]["sharpe_daily"]})
            log = [{"filters": [], "dev_mean_R": m["dev"]["mean_R"], "val_mean_R": m["val"]["mean_R"],
                    "dev_trades": m["dev"]["trades"], "val_trades": m["val"]["trades"]}]
            while len(cur) < 3:
                best, tried = None, []
                for fl in E.FILTERS:
                    if fl in cur:
                        continue
                    T2 = E.select(pools[st], {sd: cur + [fl]}, sides=(sd,))
                    m2 = measure(T2, P)
                    trials.append({"setup": st, "side": name, "filters": cur + [fl], "dev": m2["dev"], "val": m2["val"],
                                   "sharpe_daily_devval": m2["dev+val"]["sharpe_daily"]})
                    d2, v2 = m2["dev"], m2["val"]
                    ok = (d2["trades"] >= 100 and v2["trades"] >= 100 and d2["mean_R"] is not None
                          and v2["mean_R"] is not None and d2["mean_R"] > m["dev"]["mean_R"]
                          and v2["mean_R"] > m["val"]["mean_R"])
                    gain = (v2["mean_R"] - m["val"]["mean_R"]) if v2["mean_R"] is not None else None
                    tried.append({"add": fl, "dev_mean_R": d2["mean_R"], "val_mean_R": v2["mean_R"],
                                  "dev_trades": d2["trades"], "val_trades": v2["trades"], "qualifies": ok})
                    if ok and (best is None or gain > best[1]):
                        best = (fl, gain, m2)
                log.append({"tried": tried, "added": best[0] if best else None})
                if best is None:
                    break
                cur = cur + [best[0]]
                m = best[2]
            frozen[st][name] = cur
            steps_log[f"{st} {name}"] = log
            print(f"{st} {name:5}: filters {cur or '-'}  dev mean R {m['dev']['mean_R']}  val mean R {m['val']['mean_R']}"
                  f"  ({m['dev']['trades']}/{m['val']['trades']} trades)")

    configs, report = {}, {}
    for st in E.SETUPS:
        for name, sides in SIDES.items():
            filt = {1: frozen[st]["long"], -1: frozen[st]["short"]}
            T = E.select(pools[st], {sd: filt[sd] for sd in sides}, sides=sides)
            m = measure(T, P)
            key = f"{st} {name}"
            configs[key] = {"setup": st, "sides": list(sides), "filters": {str(sd): filt[sd] for sd in sides}}
            if name == "both":
                trials.append({"setup": st, "side": name, "filters": [filt[1], filt[-1]], "dev": m["dev"],
                               "val": m["val"], "sharpe_daily_devval": m["dev+val"]["sharpe_daily"]})
            r = {"dev": m["dev"], "val": m["val"], "net_by_year": by_year(T)}
            for per in ("dev", "val"):
                Tp = E.in_period(T, per)
                if len(Tp) >= 30:
                    r[f"B2_{per}"] = E.vs_random(Tp, E.baseline_random(P, Tp, random_side=True, seed=7))
                    r[f"B3_{per}"] = E.vs_random(Tp, E.baseline_random(P, Tp, random_side=False, seed=8))
            report[key] = r
            b2 = r.get("B2_val", {})
            print(f"{key:9}: dev net {m['dev']['net']:>10,.0f} R {m['dev']['mean_R']}  val net {m['val']['net']:>10,.0f}"
                  f" R {m['val']['mean_R']}  by year {r['net_by_year']}  val vs B2 t {b2.get('t')}")

    b1 = {}
    for per in ("dev", "val"):
        mask = np.isin(P.days, E.period_days(P, per))
        B = E.baseline_b1(P, f, mask)
        b1[per] = E.summarize(B, E.period_days(P, per))
        print(f"B1 {per}: {b1[per]['trades']} trades, net {b1[per]['net']:,.0f}, mean R {b1[per]['mean_R']}")

    sr = np.array([t["sharpe_daily_devval"] for t in trials], dtype=float)
    result = {"describe": desc, "trials": trials, "steps": steps_log, "frozen": frozen, "configs": report, "B1": b1,
              "n_trials": len(trials), "trial_sharpe_daily_var": float(np.var(sr, ddof=1)),
              "seconds": round(time.time() - t0, 1)}
    json.dump(result, open(out / "ablation_A1.json", "w"), indent=1, default=str)

    frozen_doc = {
        "prereg": "PREREG_A1.md", "prereg_sha256": hashlib.sha256((HERE / "PREREG_A1.md").read_bytes()).hexdigest(),
        "panel_sha256": hashlib.sha256((data / "n50_clean.pkl").read_bytes()).hexdigest(),
        "configs": configs,
        "ablation_trials": len(trials),
        "ablation_trial_sharpe_daily_var": round(float(np.var(sr, ddof=1)), 10),
        "frozen_at_utc": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M:%S"),
        "note": "Frozen before any final-test (2025-01-01 .. 2026-10-23) candle was read. n50_final.py runs these once.",
    }
    raw = json.dumps(frozen_doc, indent=1).encode()
    (HERE / "FROZEN_A1.json").write_bytes(raw)
    (HERE / "FROZEN_A1.sha256").write_text(hashlib.sha256(raw).hexdigest() + "  FROZEN_A1.json\n")
    print(f"frozen: {json.dumps(frozen)}  trials {len(trials)}  sha256 {hashlib.sha256(raw).hexdigest()[:16]}"
          f"  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
