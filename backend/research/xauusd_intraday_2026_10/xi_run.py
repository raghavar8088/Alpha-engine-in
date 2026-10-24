"""The intraday study, in two locked stages (same discipline as ../xauusd_2026_10).

  python xi_run.py select     IN-SAMPLE ONLY (sessions 2010-01-01 .. 2021-09-30): every configuration;
                              one locked per family; results/selection_locked.json with a code hash.
  python xi_run.py evaluate   OUT OF SAMPLE (2021-10-01 .. latest), once, for the locked choices.

THE 2% TARGET FOR INTRADAY TRADES (fixed before any result). Gold's median session spans 1.25% from
high to low, so 2% a trade is only reachable on the ACCOUNT, with leverage. The study allows up to
20x (the EU retail cap for gold CFDs, and about what MCX gold futures margins allow). 2% of the account
at 20x needs +0.10% a trade on the position, after costs. So:
  selection  among configurations with >= 100 in-sample trades and an in-sample average net return of
             >= +0.10% a trade (base costs C1), the highest t-statistic;
  pass       out of sample: >= 50 trades, average >= +0.10% a trade (C1), profit factor > 1.
Reported, not used to pass: the account at 10x and 20x (drawdown, ruin), harsh and measured costs,
the random-entry test, a bootstrap interval, the leverage 2% a trade would need, monthly returns.
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
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

import xi_data
import xi_strategies as S
from xi_engine import COSTS, account, net_returns, stats, trades_frame

ROOT = Path(__file__).resolve().parent
DEBUG = os.environ.get("XI_DEBUG_WINDOWS") == "1"
RES = ROOT / ("results_debug" if DEBUG else "results")
IS_START, OOS_START = "2010-01-01", "2021-10-01"
TARGET_ACCOUNT, MAX_LEV = 0.02, 20.0
TARGET = TARGET_ACCOUNT / MAX_LEV                      # +0.10% a trade on the position
MIN_IS, MIN_OOS = 100, 50
LOCK = RES / "selection_locked.json"
CODE_FILES = ("xi_engine.py", "xi_strategies.py", "xi_run.py", "xi_data.py")

_D = None
_C = None


def data():
    global _D, _C
    if _D is None:
        _D = xi_data.load()
        _C = S.Context(_D)
    return _D, _C


def windows(D) -> dict:
    sd = D["sess_date"]
    if DEBUG:      # pipeline test inside the real in-sample period: 2010-2017 / 2018-2021-09
        a = int(np.searchsorted(sd, np.datetime64(IS_START)))
        b = int(np.searchsorted(sd, np.datetime64("2018-01-01")))
        c = int(np.searchsorted(sd, np.datetime64(OOS_START)))
        return {"IS": (a, b - 1), "OOS": (b, c - 1)}
    a = int(np.searchsorted(sd, np.datetime64(IS_START)))
    b = int(np.searchsorted(sd, np.datetime64(OOS_START)))
    return {"IS": (a, b - 1), "OOS": (b, len(sd) - 1)}


def code_hash() -> str:
    h = hashlib.sha256()
    for f in CODE_FILES:
        h.update((ROOT / f).read_bytes())
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


def simulate(fam: S.Family, cfg: dict, a: int, b: int) -> pd.DataFrame:
    D, C = data()
    rows = fam.fn(D, C, range(a, b + 1), **cfg)
    return trades_frame(D, rows)


def _family_is(key: str) -> list[dict]:
    fam = next(f for f in S.FAMILIES if f.key == key)
    D, _ = data()
    a, b = windows(D)["IS"]
    out = []
    for cfg in fam.configs():
        t0 = time.time()
        tf = simulate(fam, cfg, a, b)
        r = net_returns(D, tf, COSTS["C1"])
        st = stats(r)
        out.append({"family": key, "config": S.label(cfg), "cfg": cfg, "is_default": cfg == fam.default,
                    **{f"IS_{k}": v for k, v in st.items()}, "IS_avg_minutes": float(tf["minutes"].mean()) if len(tf) else None,
                    "secs": round(time.time() - t0, 2)})
    return out


def stage_select() -> None:
    RES.mkdir(exist_ok=True)
    D, _ = data()
    w = windows(D)
    print(f"in-sample sessions {D['sess_date'][w['IS'][0]]} .. {D['sess_date'][w['IS'][1]]}; families {len(S.FAMILIES)}; "
          f"configurations {sum(len(list(f.configs())) for f in S.FAMILIES)}", flush=True)
    with ProcessPoolExecutor(max_workers=6) as ex:
        rows = [r for rs in ex.map(_family_is, [f.key for f in S.FAMILIES]) for r in rs]
    df = pd.DataFrame(rows)
    df.drop(columns=["cfg"]).to_csv(RES / "is_all_configs.csv", index=False)
    chosen = {}
    for fam in S.FAMILIES:
        sub = df[df["family"] == fam.key]
        elig = sub[(sub["IS_trades"] >= MIN_IS) & (sub["IS_avg"] >= TARGET)]
        ok_n = sub[sub["IS_trades"] >= MIN_IS]
        best = (ok_n if len(ok_n) else sub).sort_values("IS_avg", ascending=False).iloc[0]
        if len(elig):
            pick = elig.sort_values(["IS_t_stat", "IS_avg"], ascending=False).iloc[0]
            chosen[fam.key] = {"status": "selected", "config": pick["cfg"], "label": pick["config"], "IS_trades": int(pick["IS_trades"]),
                               "IS_avg": float(pick["IS_avg"]), "IS_t": float(pick["IS_t_stat"]), "eligible_configs": int(len(elig)), "configs": int(len(sub))}
        else:
            chosen[fam.key] = {"status": "failed in-sample", "config": fam.default, "label": S.label(fam.default),
                               "best_is_avg": float(best["IS_avg"]), "best_is_label": best["config"], "best_is_trades": int(best["IS_trades"]),
                               "eligible_configs": 0, "configs": int(len(sub))}
    lock = {"locked_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "code_hash": code_hash(),
            "in_sample": [str(D["sess_date"][w["IS"][0]]), str(D["sess_date"][w["IS"][1]])], "out_of_sample_from": OOS_START,
            "rules": {"target_account_per_trade": TARGET_ACCOUNT, "max_leverage": MAX_LEV, "target_position_per_trade": TARGET,
                      "min_is_trades": MIN_IS, "min_oos_trades": MIN_OOS,
                      "selection": "max in-sample t-stat among configs with >= min trades and an average >= +0.10% a trade (C1)",
                      "pass": "OOS (C1): trades >= 50, average >= +0.10% a trade (2% of the account at 20x), profit factor > 1"},
            "configurations_tested": int(len(df)), "families": jsonable(chosen)}
    body = json.dumps(lock, indent=1, default=str)
    lock["lock_sha256"] = hashlib.sha256(body.encode()).hexdigest()[:16]
    LOCK.write_text(json.dumps(lock, indent=1, default=str))
    print(f"locked: code {lock['code_hash']}, lock {lock['lock_sha256']}")
    for k, v in chosen.items():
        if v["status"] == "selected":
            print(f"  {k:<18} SELECTED  {v['label']:<52} IS trades {v['IS_trades']:>5}  avg {v['IS_avg']*100:+.3f}%  t {v['IS_t']:.2f}")
        else:
            print(f"  {k:<18} FAILED IS best {v['best_is_avg']*100:+.3f}% over {v['best_is_trades']} trades ({v['best_is_label']})")


# ── out of sample ───────────────────────────────────────────────────────────────


def minute_map(D) -> np.ndarray:
    """[session, session-minute] -> minute index (or -1)."""
    m = np.full((len(D["s_start"]), 1440), -1, dtype=np.int64)
    m[D["sess"], D["sm"]] = np.arange(len(D["sess"]))
    return m


def random_entry(D, MM, tf: pd.DataFrame, a: int, b: int, c, sims: int = 2000, seed: int = 5) -> dict:
    """Each trade re-run on a random session of the same window: same side, same entry minute of the
    session, same holding time. What the time of day pays a rule that times nothing."""
    if tf.empty:
        return {}
    rng = np.random.default_rng(seed)
    sm_e = D["sm"][tf["ei"].values].astype(np.int64)
    sm_x = D["sm"][tf["xi"].values].astype(np.int64)
    side = tf["side"].values
    days = rng.integers(a, b + 1, size=(sims, len(tf)))
    ei = MM[days, sm_e]
    xi = MM[days, sm_x]
    ok = (ei >= 0) & (xi >= 0)
    ep = np.where(ok, D["o"][np.maximum(ei, 0)], np.nan)
    xp = np.where(ok, D["c"][np.maximum(xi, 0)], np.nan)
    adv = c.spread / 2 + c.slippage
    ef = ep + side * adv
    xf = xp - side * adv
    r = (side * (xf - ef) - 2 * c.commission) / ef
    means = np.nanmean(r, axis=1)
    return {"random_mean_avg": float(np.nanmean(means)), "random_p95": float(np.nanquantile(means, 0.95)), "means": means}


def bootstrap(r: np.ndarray, sims: int = 10000, seed: int = 11):
    if len(r) < 2:
        return (None, None)
    b = r[np.random.default_rng(seed).integers(0, len(r), (sims, len(r)))].mean(axis=1)
    return float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))


def holm(p: dict) -> dict:
    items = sorted((v, k) for k, v in p.items() if v == v and v is not None)
    out, mx = {}, 0.0
    for i, (v, k) in enumerate(items):
        mx = max(mx, min(1.0, (len(items) - i) * v))
        out[k] = mx
    return out


def monthly(tf: pd.DataFrame, r: np.ndarray, lev: float, start: str, end: str) -> dict:
    """Account return of each calendar month at leverage `lev` (months without trades: 0%)."""
    months = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    out = {str(m): 0.0 for m in months}
    if len(r):
        g = pd.Series(np.log(np.maximum(1 + lev * r, 1e-12)), index=pd.to_datetime(tf["date"].values).to_period("M")).groupby(level=0).sum()
        for k, v in g.items():
            out[str(k)] = float(np.exp(v) - 1)
    return out


def _family_oos(key: str) -> dict:
    lock = json.loads(LOCK.read_text())
    fam = next(f for f in S.FAMILIES if f.key == key)
    D, _ = data()
    w = windows(D)
    MM = minute_map(D)
    e = lock["families"][key]
    cfg = {k: (tuple(v) if isinstance(v, list) else v) for k, v in e["config"].items()}
    out = {"key": key, "status_is": e["status"], "label": S.label(cfg)}
    for wn, (a, b) in w.items():
        tf = simulate(fam, cfg, a, b)
        span = (str(D["sess_date"][a]), str(D["sess_date"][b]))
        res = {ck: stats(net_returns(D, tf, c)) for ck, c in COSTS.items()}
        r = net_returns(D, tf, COSTS["C1"])
        res["avg_minutes"] = float(tf["minutes"].mean()) if len(tf) else None
        res["long_share"] = float((tf["side"] == 1).mean()) if len(tf) else None
        res["trades_per_year"] = len(tf) / max((pd.Timestamp(span[1]) - pd.Timestamp(span[0])).days / 365.25, 1e-9)
        res["accounts"] = {f"{int(L)}x": {k: v for k, v in account(r, tf["date"].values if len(tf) else [], L, *span).items() if k != "path"}
                           for L in (1.0, 10.0, 20.0)}
        res["monthly"] = {f"{int(L)}x": monthly(tf, r, L, *span) for L in (1.0, 10.0, 20.0)}
        res["by_year"] = ({int(y): {"trades": int(len(g)), "avg": float(g.mean())} for y, g in pd.Series(r, index=pd.to_datetime(tf["date"].values).year).groupby(level=0)}
                          if len(tf) else {})
        if wn == "OOS" and len(tf):
            re = random_entry(D, MM, tf, a, b, COSTS["C1"])
            res["random_mean_avg"] = re["random_mean_avg"]
            res["timing_p"] = float(np.nanmean(re["means"] >= r.mean()))
            res["ci95"] = bootstrap(r)
            res["leverage_for_2pct"] = (TARGET_ACCOUNT / r.mean()) if r.mean() > 0 else None
        out[wn] = res
        t = tf.copy()
        for ck, c in COSTS.items():
            t[f"net_{ck}"] = net_returns(D, tf, c)
        if len(t):
            t["entry_utc"] = pd.to_datetime(D["t"][t["ei"].values], unit="s", utc=True).astype(str)
            t["exit_utc"] = pd.to_datetime(D["t"][t["xi"].values], unit="s", utc=True).astype(str)
        out[f"trades_{wn}"] = t
    o = out["OOS"]["C1"]
    out["PASS"] = e["status"] == "selected" and o.get("trades", 0) >= MIN_OOS and o.get("avg", -1) >= TARGET and (o.get("profit_factor") or 0) > 1
    return out


def stage_evaluate() -> None:
    if not LOCK.exists():
        sys.exit("no lock: run `python xi_run.py select` first")
    lock = json.loads(LOCK.read_text())
    if lock["code_hash"] != code_hash():
        sys.exit(f"code changed since the lock ({lock['code_hash']} -> {code_hash()})")
    D, _ = data()
    w = windows(D)
    with ProcessPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(_family_oos, [f.key for f in S.FAMILIES]))
    padj = holm({r["key"]: r["OOS"].get("timing_p") for r in res if r["status_is"] == "selected" and r["OOS"]["C1"].get("trades")})
    tdir = RES / "trades"
    tdir.mkdir(exist_ok=True)
    rows = []
    for r in res:
        pd.concat([r["trades_IS"].assign(window="IS"), r["trades_OOS"].assign(window="OOS")]).to_csv(tdir / f"{r['key']}.csv", index=False)
        i, o = r["IS"]["C1"], r["OOS"]["C1"]
        rows.append({"family": r["key"], "is_status": r["status_is"], "config": r["label"], "PASS": r["PASS"],
                     "IS_trades": i.get("trades"), "IS_avg": i.get("avg"), "OOS_trades": o.get("trades"), "OOS_avg": o.get("avg"),
                     "OOS_pf": o.get("profit_factor"), "OOS_win": o.get("win_rate"), "OOS_avg_C2": r["OOS"]["C2"].get("avg"),
                     "OOS_avg_C3": r["OOS"]["C3"].get("avg"), "random_avg": r["OOS"].get("random_mean_avg"), "timing_p": r["OOS"].get("timing_p"),
                     "timing_p_holm": padj.get(r["key"]), "lev_for_2pct": r["OOS"].get("leverage_for_2pct"),
                     "OOS_20x_total": r["OOS"]["accounts"]["20x"]["total_return"], "OOS_20x_mdd": r["OOS"]["accounts"]["20x"]["max_drawdown"],
                     "OOS_20x_ruined": r["OOS"]["accounts"]["20x"]["ruined_on"], "OOS_avg_minutes": r["OOS"].get("avg_minutes")})
    sm = pd.DataFrame(rows)
    sm.to_csv(RES / "summary.csv", index=False)
    detail = {"lock": {k: lock[k] for k in ("locked_at", "code_hash", "lock_sha256", "rules", "configurations_tested")},
              "evaluated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
              "windows": {wn: [str(D["sess_date"][a]), str(D["sess_date"][b])] for wn, (a, b) in w.items()},
              "costs": {k: v.__dict__ for k, v in COSTS.items()}, "holm": padj,
              "families": {r["key"]: {k: v for k, v in r.items() if not k.startswith("trades_")} for r in res}}
    (RES / "oos_detail.json").write_text(json.dumps(jsonable(detail), indent=1, default=str))
    pd.set_option("display.width", 260)
    print(sm.drop(columns=["config"]).to_string(index=False, float_format=lambda v: f"{v:.5f}"))


if __name__ == "__main__":
    {"select": stage_select, "evaluate": stage_evaluate}[sys.argv[1]]()
