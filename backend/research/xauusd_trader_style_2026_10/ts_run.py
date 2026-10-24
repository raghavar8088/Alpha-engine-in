"""Two locked stages, exactly as PREREGISTRATION.md.

  python ts_run.py select     gold in-sample only (2010-01-01 .. 2021-09-30): every configuration, one locked per
                              setup, results/selection_locked.json with a hash of all the code it ran.
  python ts_run.py evaluate   once: gold out-of-sample (2021-10-01 .. latest) and the locked rules, unchanged, on
                              XAGUSD, EURUSD and GBPUSD (2010-01-01 .. latest). Refuses to run on changed code.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import hashlib
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

import ts_data
import ts_strategies as S

ROOT = Path(__file__).resolve().parent
INTRA = ROOT.parent / "xauusd_intraday_2026_10"
DEBUG = os.environ.get("XT_DEBUG_WINDOWS") == "1"
RES = ROOT / ("results_debug" if DEBUG else "results")
LOCK = RES / "selection_locked.json"
CODE = [ROOT / f for f in ("ts_strategies.py", "ts_run.py", "ts_data.py")] + [INTRA / "xi_engine.py", INTRA / "xi_strategies.py"]
IS_START, OOS_START = "2010-01-01", "2021-10-01"
MIN_IS, MIN_OOS, TARGET_R, PF_MIN = 100, 40, 0.15, 1.2
MARKETS_CROSS = ["XAGUSD", "EURUSD", "GBPUSD"]
# round-trip cost in price units: spread + 2 x slippage + 2 x commission (PREREGISTRATION.md)
COSTS = {
    "XAUUSD": {"low": 0.25 + 2 * 0.05 + 2 * 0.035, "base": 0.40 + 2 * 0.10 + 2 * 0.035, "harsh": 0.50 + 2 * 0.25 + 2 * 0.05},
    "XAGUSD": {"base": 0.025 + 2 * 0.005 + 2 * 0.0007},
    "EURUSD": {"base": 0.00002 + 2 * 0.00001 + 2 * 0.000035},
    "GBPUSD": {"base": 0.00004 + 2 * 0.00002 + 2 * 0.000035},
}
for _m in MARKETS_CROSS:
    COSTS[_m]["harsh"] = 2 * COSTS[_m]["base"]

_cache: dict = {}


def market(sym: str):
    if sym not in _cache:
        D = ts_data.load(sym)
        _cache[sym] = (D, S.Context(D))
    return _cache[sym]


def window(D, start: str, end: str | None) -> tuple[int, int]:
    sd = D["sess_date"]
    a = int(np.searchsorted(sd, np.datetime64(start)))
    b = (int(np.searchsorted(sd, np.datetime64(end))) - 1) if end else len(sd) - 1
    return a, b


def windows_gold(D):
    if DEBUG:
        return {"IS": window(D, IS_START, "2018-01-01"), "OOS": window(D, "2018-01-01", OOS_START)}
    return {"IS": window(D, IS_START, OOS_START), "OOS": window(D, OOS_START, None)}


def code_hash() -> str:
    h = hashlib.sha256()
    for p in CODE:
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def jsonable(x):
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if (x != x or math.isinf(x)) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.datetime64):
        return str(x)
    return x


def frame(D, rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["day", "side", "ei", "ep", "xi", "xp", "reason", "risk"])
    if len(df):
        df["date"] = D["sess_date"][df["day"].values]
        df["minutes"] = ((D["t"][df["xi"].values] - D["t"][df["ei"].values]) // 60).astype(int)
    return df


def r_multiples(tf: pd.DataFrame, cost: float) -> np.ndarray:
    if tf.empty:
        return np.array([])
    return (tf["side"].values * (tf["xp"].values - tf["ep"].values) - cost) / tf["risk"].values


def rstats(R: np.ndarray, sides: np.ndarray | None = None) -> dict:
    n = len(R)
    if n == 0:
        return {"trades": 0}
    w, ls = R[R > 0], R[R < 0]
    st = best = 0
    for x in R:
        st = st + 1 if x < 0 else 0
        best = max(best, st)
    sd = R.std(ddof=1) if n > 1 else float("nan")
    out = {"trades": n, "expectancy_R": float(R.mean()), "median_R": float(np.median(R)), "win_rate": float(len(w) / n),
           "avg_win_R": float(w.mean()) if len(w) else None, "avg_loss_R": float(ls.mean()) if len(ls) else None,
           "profit_factor": float(w.sum() / -ls.sum()) if len(ls) and ls.sum() < 0 else None,
           "t_stat": float(R.mean() / (sd / math.sqrt(n))) if n > 1 and sd > 0 else None, "longest_losing_streak": int(best)}
    if sides is not None:
        for nm, sg in (("long", 1), ("short", -1)):
            m = sides == sg
            out[f"{nm}_trades"] = int(m.sum())
            out[f"{nm}_expectancy_R"] = float(R[m].mean()) if m.any() else None
    return out


def account(tf: pd.DataFrame, R: np.ndarray, risk_pct: float, start: str, end: str) -> dict:
    """Risk risk_pct of equity a trade (position = risk / stop distance, at most 20x); monthly returns."""
    months = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    monthly = {str(p): 0.0 for p in months}
    if tf.empty:
        return {"total": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "monthly": monthly}
    frac = np.minimum(risk_pct * tf["ep"].values / tf["risk"].values, 20.0)
    acct = frac * R * tf["risk"].values / tf["ep"].values           # account return of each trade
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in acct:
        eq *= max(1 + x, 0.0)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    per = pd.Series(np.log(np.maximum(1 + acct, 1e-12)), index=pd.to_datetime(tf["date"].values).to_period("M")).groupby(level=0).sum()
    for k, v in per.items():
        monthly[str(k)] = float(np.exp(v) - 1)
    yrs = max((pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25, 1e-9)
    mv = np.array(list(monthly.values()))
    return {"total": eq - 1, "cagr": eq ** (1 / yrs) - 1 if eq > 0 else -1.0, "max_drawdown": mdd,
            "month_compounded": float(np.prod(1 + mv) ** (1 / len(mv)) - 1), "months_up": float((mv > 0).mean()),
            "worst_month": float(mv.min()), "best_month": float(mv.max()), "capped_trades": int((frac >= 20.0).sum()), "monthly": monthly}


def run_setup(sym: str, setup: S.Setup, cfg: dict, a: int, b: int) -> pd.DataFrame:
    D, C = market(sym)
    return frame(D, setup.fn(D, C, range(a, b + 1), **cfg))


def _select(key: str) -> list[dict]:
    setup = next(s for s in S.SETUPS if s.key == key)
    D, _ = market("XAUUSD")
    a, b = windows_gold(D)["IS"]
    out = []
    for cfg in setup.configs():
        tf = run_setup("XAUUSD", setup, cfg, a, b)
        R = r_multiples(tf, COSTS["XAUUSD"]["base"])
        out.append({"setup": key, "config": S.label(cfg), "cfg": cfg, **{f"IS_{k}": v for k, v in rstats(R).items()}})
    return out


def stage_select():
    RES.mkdir(exist_ok=True)
    D, _ = market("XAUUSD")
    w = windows_gold(D)
    with ProcessPoolExecutor(max_workers=3) as ex:
        rows = [r for rs in ex.map(_select, [s.key for s in S.SETUPS]) for r in rs]
    df = pd.DataFrame(rows)
    df.drop(columns=["cfg"]).to_csv(RES / "is_all_configs.csv", index=False)
    chosen = {}
    for s in S.SETUPS:
        sub = df[df["setup"] == s.key]
        el = sub[(sub["IS_trades"] >= MIN_IS) & (sub["IS_expectancy_R"] >= TARGET_R)]
        best = sub.sort_values("IS_expectancy_R", ascending=False).iloc[0]
        if len(el):
            p = el.sort_values(["IS_t_stat", "IS_expectancy_R"], ascending=False).iloc[0]
            chosen[s.key] = {"status": "selected", "config": p["cfg"], "label": p["config"], "IS_trades": int(p["IS_trades"]),
                             "IS_expectancy_R": float(p["IS_expectancy_R"]), "IS_t": float(p["IS_t_stat"])}
        else:
            chosen[s.key] = {"status": "failed in-sample", "config": s.default, "label": S.label(s.default),
                             "best_IS_expectancy_R": float(best["IS_expectancy_R"]), "best_label": best["config"], "best_trades": int(best["IS_trades"])}
    lock = {"locked_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "code_hash": code_hash(),
            "gold_in_sample": [str(D["sess_date"][w["IS"][0]]), str(D["sess_date"][w["IS"][1]])],
            "rules": {"min_is_trades": MIN_IS, "min_oos_trades": MIN_OOS, "target_R": TARGET_R, "profit_factor_min": PF_MIN,
                      "cross_market": "expectancy > 0 in >= 2 of XAGUSD, EURUSD, GBPUSD (base costs)"},
            "configurations_tested": int(len(df)), "setups": jsonable(chosen)}
    body = json.dumps(lock, indent=1, default=str)
    lock["lock_sha256"] = hashlib.sha256(body.encode()).hexdigest()[:16]
    LOCK.write_text(json.dumps(lock, indent=1, default=str))
    print(f"locked: code {lock['code_hash']}, lock {lock['lock_sha256']}")
    for k, v in chosen.items():
        if v["status"] == "selected":
            print(f"  {k:<12} SELECTED {v['label']:<40} IS trades {v['IS_trades']:>4}  expectancy {v['IS_expectancy_R']:+.3f}R  t {v['IS_t']:.2f}")
        else:
            print(f"  {k:<12} FAILED IS: best {v['best_IS_expectancy_R']:+.3f}R over {v['best_trades']} trades ({v['best_label']})")


def _random_entry(D, tf: pd.DataFrame, a: int, b: int, cost: float, sims: int = 2000, seed: int = 3) -> float | None:
    if tf.empty:
        return None
    MM = np.full((len(D["s_start"]), 1440), -1, dtype=np.int64)
    MM[D["sess"], D["sm"]] = np.arange(len(D["sess"]))
    rng = np.random.default_rng(seed)
    sm_e, sm_x = D["sm"][tf["ei"].values].astype(int), D["sm"][tf["xi"].values].astype(int)
    days = rng.integers(a, b + 1, size=(sims, len(tf)))
    ei, xi = MM[days, sm_e], MM[days, sm_x]
    ok = (ei >= 0) & (xi >= 0)
    ep = np.where(ok, D["o"][np.maximum(ei, 0)], np.nan)
    xp = np.where(ok, D["c"][np.maximum(xi, 0)], np.nan)
    R = (tf["side"].values * (xp - ep) - cost) / tf["risk"].values
    return float(np.nanmean(R))


def _evaluate(key: str) -> dict:
    lock = json.loads(LOCK.read_text())
    setup = next(s for s in S.SETUPS if s.key == key)
    e = lock["setups"][key]
    cfg = e["config"]
    out = {"key": key, "status_is": e["status"], "label": e["label"], "markets": {}}
    D, _ = market("XAUUSD")
    jobs = [("XAUUSD", wn, a, b) for wn, (a, b) in windows_gold(D).items()]
    if not DEBUG:
        for m in MARKETS_CROSS:
            Dm, _ = market(m)
            a, b = window(Dm, IS_START, None)
            jobs.append((m, "ALL", a, b))
    for sym, wn, a, b in jobs:
        Dm, _ = market(sym)
        tf = run_setup(sym, setup, cfg, a, b)
        span = (str(Dm["sess_date"][a]), str(Dm["sess_date"][b]))
        res = {"span": span}
        for ck, cost in COSTS[sym].items():
            res[ck] = rstats(r_multiples(tf, cost), tf["side"].values if len(tf) else None)
        Rb = r_multiples(tf, COSTS[sym]["base"])
        res["random_entry_R"] = _random_entry(Dm, tf, a, b, COSTS[sym]["base"])
        res["accounts"] = {f"{p}%": {k: v for k, v in account(tf, Rb, p / 100, *span).items()} for p in (0.5, 1)}
        res["avg_minutes"] = float(tf["minutes"].mean()) if len(tf) else None
        res["trades_per_month"] = len(tf) / max(((pd.Timestamp(span[1]) - pd.Timestamp(span[0])).days / 30.44), 1e-9)
        out["markets"][f"{sym}_{wn}"] = res
        if len(tf):
            t = tf.copy()
            t["R_base"] = Rb
            t["entry_utc"] = pd.to_datetime(Dm["t"][t["ei"].values], unit="s", utc=True).astype(str)
            (RES / "trades").mkdir(exist_ok=True)
            t.to_csv(RES / "trades" / f"{key}_{sym}_{wn}.csv", index=False)
    g = out["markets"]["XAUUSD_OOS"]["base"]
    out["gold_oos_pass"] = (e["status"] == "selected" and g.get("trades", 0) >= MIN_OOS and (g.get("expectancy_R") or -9) >= TARGET_R
                            and (g.get("profit_factor") or 0) > PF_MIN)
    cross = [out["markets"].get(f"{m}_ALL", {}).get("base", {}).get("expectancy_R") for m in MARKETS_CROSS]
    out["cross_positive"] = sum(1 for x in cross if x is not None and x > 0)
    out["WORKING"] = out["gold_oos_pass"] and out["cross_positive"] >= 2
    return out


def stage_evaluate():
    if not LOCK.exists():
        sys.exit("no lock: run select first")
    lock = json.loads(LOCK.read_text())
    if lock["code_hash"] != code_hash():
        sys.exit(f"code changed since the lock ({lock['code_hash']} -> {code_hash()})")
    with ProcessPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(_evaluate, [s.key for s in S.SETUPS]))
    out = {"lock": {k: lock[k] for k in ("locked_at", "code_hash", "lock_sha256", "rules", "configurations_tested")},
           "evaluated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "costs": COSTS, "setups": {r["key"]: r for r in res}}
    (RES / "evaluation.json").write_text(json.dumps(jsonable(out), indent=1))
    for r in res:
        print(f"\n== {r['key']} ({r['status_is']}; {r['label']})  gold OOS pass: {r['gold_oos_pass']}  cross-market positive: {r['cross_positive']}/3  WORKING: {r['WORKING']}")
        for mk, v in r["markets"].items():
            b = v["base"]
            if not b.get("trades"):
                print(f"   {mk:<12} no trades")
                continue
            a1 = v["accounts"]["1%"]
            print(f"   {mk:<12} trades {b['trades']:>4} ({v['trades_per_month']:.1f}/mo)  win {b['win_rate']*100:4.1f}%  exp {b['expectancy_R']:+.3f}R  pf {b['profit_factor'] or 0:.2f}  "
                  f"long {b.get('long_expectancy_R') or 0:+.3f}R / short {b.get('short_expectancy_R') or 0:+.3f}R  random {v['random_entry_R'] if v['random_entry_R'] is not None else float('nan'):+.3f}R  "
                  f"| 1% risk: {a1['month_compounded']*100:+.2f}%/mo, max DD {a1['max_drawdown']*100:.1f}%, total {a1['total']*100:+.1f}%")


if __name__ == "__main__":
    {"select": stage_select, "evaluate": stage_evaluate}[sys.argv[1]]()
