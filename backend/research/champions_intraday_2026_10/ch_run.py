"""The champion traders' intraday test, in two locked stages (PREREGISTRATION.md).

  python ch_run.py select     IN-SAMPLE ONLY: every configuration of every rule on every market; one locked per
                              market and rule (highest t-statistic among >= 100 trades); results/selection_locked.json
                              with a code hash.
  python ch_run.py evaluate   OUT OF SAMPLE, once, for the locked choices: verdicts (EDGE / TARGET / NO EDGE),
                              Unger's portfolio, monthly returns on the account, trade lists.
CH_DEBUG_WINDOWS=1 runs both stages inside the in-sample period (to 2017 / 2018 to the split) to test the pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "xauusd_intraday_2026_10"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import hashlib
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

import ch_data
import ch_strategies as S
from xi_engine import Costs, account, net_returns, stats, trades_frame

ROOT = Path(__file__).resolve().parent
DEBUG = os.environ.get("CH_DEBUG_WINDOWS") == "1"
RES = ROOT / ("results_debug" if DEBUG else "results")
OOS_START = "2021-10-01"
IS_START = {"XAUUSD": "2010-01-01"}           # the index markets start at their first session (2010-11-15)
TARGET_ACCOUNT, MAX_LEV = 0.02, 20.0
TARGET = TARGET_ACCOUNT / MAX_LEV             # +0.10% a trade on the position
MIN_IS, MIN_OOS = 100, 50
GAP_DAYS, WARMUP = 10, 10
LOCK = RES / "selection_locked.json"
CODE_FILES = [ROOT / f for f in ("ch_data.py", "ch_strategies.py", "ch_run.py")] + \
             [ROOT.parent / "xauusd_intraday_2026_10" / f for f in ("xi_engine.py", "xi_strategies.py")]

COSTS = {
    "XAUUSD": {"base": Costs("retail CFD: spread $0.40, slippage $0.10 a side, commission $0.035/oz a side", 0.40, 0.10, 0.035),
               "harsh": Costs("harsh: spread $0.50, slippage $0.25 a side, commission $0.05/oz a side", 0.50, 0.25, 0.05),
               "futures": Costs("COMEX futures: spread $0.10, slippage $0.10 a side, commission $0.025/oz a side", 0.10, 0.10, 0.025),
               "measured": Costs("Dukascopy's quoted spread in the entry and exit hours + base slippage and commission", 0.40, 0.10, 0.035, True)},
    "SPXUSD": {"base": Costs("ES futures: spread 0.25 pt, slippage 0.125 pt a side, commission 0.05 pt a side", 0.25, 0.125, 0.05),
               "harsh": Costs("2 x base", 0.50, 0.25, 0.10)},
    "NSXUSD": {"base": Costs("NQ futures: spread 0.5 pt, slippage 0.25 pt a side, commission 0.125 pt a side", 0.5, 0.25, 0.125),
               "harsh": Costs("2 x base", 1.0, 0.5, 0.25)},
    "GRXEUR": {"base": Costs("FDAX futures: spread 1.0 pt, slippage 0.5 pt a side, commission 0.1 pt a side", 1.0, 0.5, 0.1),
               "harsh": Costs("2 x base", 2.0, 1.0, 0.2)},
}

_M = {}


def market(sym: str):
    """(arrays, context, market) with the not-traded mask of PREREGISTRATION.md."""
    if sym not in _M:
        D = ch_data.load(sym)
        m = ch_data.MARKETS[sym]
        sd = D["sess_date"].astype("datetime64[D]")
        gap = np.r_[0, np.diff(sd).astype(np.int64)]
        warm = np.zeros(len(sd), dtype=bool)
        for i in np.flatnonzero(gap > GAP_DAYS):
            warm[i:i + WARMUP] = True
        skip = D["prev_dropped"].astype(bool) | warm
        _M[sym] = (D, S.Context(D, m.length, skip), m)
    return _M[sym]


def windows(sym: str, D: dict) -> dict:
    sd = D["sess_date"]
    a = int(np.searchsorted(sd, np.datetime64(IS_START.get(sym, str(sd[0])))))
    b = int(np.searchsorted(sd, np.datetime64(OOS_START)))
    if DEBUG:
        c = int(np.searchsorted(sd, np.datetime64("2018-01-01")))
        return {"IS": (a, c - 1), "OOS": (c, b - 1)}
    return {"IS": (a, b - 1), "OOS": (b, len(sd) - 1)}


def code_hash() -> str:
    h = hashlib.sha256()
    for f in CODE_FILES:
        h.update(f.read_bytes())
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


def family(key: str) -> S.Family:
    return next(f for f in S.FAMILIES if f.key == key)


def simulate(sym: str, fam: S.Family, cfg: dict, a: int, b: int) -> pd.DataFrame:
    D, C, _ = market(sym)
    return trades_frame(D, fam.fn(D, C, range(a, b + 1), **cfg))


# ── stage 1: in-sample selection ────────────────────────────────────────────────


def _select_task(job) -> list[dict]:
    sym, key = job
    D, _, m = market(sym)
    fam = family(key)
    a, b = windows(sym, D)["IS"]
    out = []
    for cfg in fam.configs(m.length):
        tf = simulate(sym, fam, cfg, a, b)
        st = stats(net_returns(D, tf, COSTS[sym]["base"]))
        out.append({"market": sym, "family": key, "config": S.label(cfg), "cfg": cfg,
                    **{f"IS_{k}": v for k, v in st.items()},
                    "IS_avg_harsh": stats(net_returns(D, tf, COSTS[sym]["harsh"])).get("avg"),
                    "IS_avg_minutes": float(tf["minutes"].mean()) if len(tf) else None})
    return out


def stage_select() -> None:
    RES.mkdir(exist_ok=True)
    jobs = [(sym, f.key) for sym in ch_data.MARKETS for f in S.FAMILIES]
    with ProcessPoolExecutor(max_workers=6) as ex:
        rows = [r for rs in ex.map(_select_task, jobs) for r in rs]
    df = pd.DataFrame(rows)
    df.drop(columns=["cfg"]).to_csv(RES / "is_all_configs.csv", index=False)
    chosen, wins = {}, {}
    for sym in ch_data.MARKETS:
        D, _, _ = market(sym)
        w = windows(sym, D)
        wins[sym] = {k: [str(D["sess_date"][a]), str(D["sess_date"][b])] for k, (a, b) in w.items()}
        chosen[sym] = {}
        for fam in S.FAMILIES:
            sub = df[(df["market"] == sym) & (df["family"] == fam.key)]
            ok = sub[sub["IS_trades"] >= MIN_IS]
            if not len(ok):
                chosen[sym][fam.key] = {"status": "too few in-sample trades", "configs": int(len(sub))}
                continue
            pick = ok.sort_values(["IS_t_stat", "IS_avg"], ascending=False).iloc[0]
            chosen[sym][fam.key] = {"status": "locked", "config": pick["cfg"], "label": pick["config"], "configs": int(len(sub)),
                                    "IS_trades": int(pick["IS_trades"]), "IS_avg": float(pick["IS_avg"]), "IS_t": float(pick["IS_t_stat"]),
                                    "IS_profit_factor": pick["IS_profit_factor"], "IS_win_rate": float(pick["IS_win_rate"]),
                                    "configs_with_positive_IS_avg": int((ok["IS_avg"] > 0).sum()),
                                    "configs_reaching_target_IS": int((ok["IS_avg"] >= TARGET).sum())}
    lock = {"locked_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "code_hash": code_hash(), "debug_windows": DEBUG,
            "windows": wins, "out_of_sample_from": OOS_START, "configurations_tested": int(len(df)),
            "rules": {"selection": "per market and rule: highest in-sample t-statistic (base costs) among configurations with >= 100 trades",
                      "edge": "IS avg > 0; OOS >= 50 trades, avg > 0 at base and harsh costs, Holm-adjusted one-sided p < 0.05, timing p < 0.05",
                      "target": "EDGE and avg >= +0.10% a trade in- and out-of-sample (2% of the account at 20x)",
                      "portfolio": "locked rules with IS avg > 0, equal shares; WORKING if OOS mean monthly return > 0 with t >= 2 and > 0 at harsh costs"},
            "selected": jsonable(chosen)}
    lock["lock_sha256"] = hashlib.sha256(json.dumps(lock, indent=1, default=str).encode()).hexdigest()[:16]
    LOCK.write_text(json.dumps(lock, indent=1, default=str))
    print(f"locked: code {lock['code_hash']}, lock {lock['lock_sha256']}, {len(df)} configurations")
    for sym, fams in chosen.items():
        for k, v in fams.items():
            if v["status"] == "locked":
                print(f"  {sym} {k:<15} {v['label']:<44} IS {v['IS_trades']:>5} trades  avg {v['IS_avg'] * 100:+.4f}%  t {v['IS_t']:+.2f}  "
                      f"(+avg configs {v['configs_with_positive_IS_avg']}/{v['configs']})")
            else:
                print(f"  {sym} {k:<15} {v['status']}")


# ── stage 2: out of sample, once ────────────────────────────────────────────────


def minute_map(D: dict, length: int) -> np.ndarray:
    m = np.full((len(D["s_start"]), length), -1, dtype=np.int64)
    m[D["sess"], D["sm"]] = np.arange(len(D["sess"]))
    return m


def _costed(D, side, ei, xi, c) -> np.ndarray:
    ok = (ei >= 0) & (xi >= 0)
    ep = np.where(ok, D["o"][np.maximum(ei, 0)], np.nan)
    xp = np.where(ok, D["c"][np.maximum(xi, 0)], np.nan)
    adv = c.spread / 2 + c.slippage
    ef, xf = ep + side * adv, xp - side * adv
    return (side * (xf - ef) - 2 * c.commission) / ef


def random_timing(D, MM, tf: pd.DataFrame, a: int, b: int, c, bias: bool, sims: int = 2000, seed: int = 7) -> np.ndarray:
    """Mean net return of `sims` placebo versions of the trade list. Non-bias rules: the same side, entry minute
    of the session and holding time on random sessions of the window. Bias rules: the same sessions, side and
    holding time at a random minute of the session."""
    rng = np.random.default_rng(seed)
    side = tf["side"].values
    sm_e = D["sm"][tf["ei"].values].astype(np.int64)
    sm_x = D["sm"][tf["xi"].values].astype(np.int64)
    L = MM.shape[1]
    if bias:
        dur = sm_x - sm_e
        days = np.broadcast_to(tf["day"].values, (sims, len(tf)))
        s0 = (rng.random((sims, len(tf))) * (L - dur)).astype(np.int64)
        ei, xi = MM[days, s0], MM[days, np.minimum(s0 + dur, L - 1)]
    else:
        days = rng.integers(a, b + 1, size=(sims, len(tf)))
        ei, xi = MM[days, sm_e], MM[days, sm_x]
    return np.nanmean(_costed(D, side, ei, xi, c), axis=1)


def bootstrap(r: np.ndarray, sims: int = 10000, seed: int = 11):
    if len(r) < 2:
        return (None, None)
    m = r[np.random.default_rng(seed).integers(0, len(r), (sims, len(r)))].mean(axis=1)
    return float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


def p_positive(r: np.ndarray) -> float | None:
    """One-sided p-value that the mean is > 0 (normal approximation of the t-test)."""
    if len(r) < 2 or r.std(ddof=1) == 0:
        return None
    t = r.mean() / (r.std(ddof=1) / math.sqrt(len(r)))
    return 0.5 * math.erfc(t / math.sqrt(2))


def holm(p: dict) -> dict:
    items = sorted((v, k) for k, v in p.items() if v is not None)
    out, mx = {}, 0.0
    for i, (v, k) in enumerate(items):
        mx = max(mx, min(1.0, (len(items) - i) * v))
        out[k] = mx
    return out


def monthly(dates, r: np.ndarray, lev: float, start: str, end: str) -> dict:
    """The account's return in each calendar month at leverage `lev` (months without trades: 0%)."""
    months = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    out = {str(m): 0.0 for m in months}
    if len(r):
        g = pd.Series(np.log(np.maximum(1 + lev * r, 1e-12)), index=pd.to_datetime(dates).to_period("M")).groupby(level=0).sum()
        for k, v in g.items():
            out[str(k)] = float(np.exp(v) - 1)
    return out


def _evaluate_task(job) -> dict:
    sym, key = job
    lock = json.loads(LOCK.read_text())
    e = lock["selected"][sym][key]
    D, C, m = market(sym)
    fam = family(key)
    cfg = e["config"]
    w = windows(sym, D)
    MM = minute_map(D, m.length)
    out = {"market": sym, "family": key, "label": e["label"], "IS_locked": e}
    for wn, (a, b) in w.items():
        tf = simulate(sym, fam, cfg, a, b)
        span = (str(D["sess_date"][a]), str(D["sess_date"][b]))
        res = {"span": span}
        nets = {ck: net_returns(D, tf, c) for ck, c in COSTS[sym].items()}
        for ck, r in nets.items():
            res[ck] = stats(r)
        r = nets["base"]
        dates = tf["date"].values if len(tf) else np.array([], dtype="datetime64[D]")
        years = max((pd.Timestamp(span[1]) - pd.Timestamp(span[0])).days / 365.25, 1e-9)
        res["trades_per_month"] = len(tf) / (years * 12)
        res["avg_minutes"] = float(tf["minutes"].mean()) if len(tf) else None
        res["sides"] = {"long": stats(r[tf["side"].values == 1]) if len(tf) else {}, "short": stats(r[tf["side"].values == -1]) if len(tf) else {}}
        res["by_year"] = ({int(y): {"trades": int(len(g)), "avg": float(g.mean()), "sum": float(g.sum())}
                           for y, g in pd.Series(r, index=pd.to_datetime(dates).year).groupby(level=0)} if len(tf) else {})
        res["accounts"] = {f"{int(L)}x": {k: v for k, v in account(r, dates, L, *span).items() if k != "path"} for L in (1.0, 10.0, 20.0)}
        res["monthly"] = {f"{int(L)}x": monthly(dates, r, L, *span) for L in (1.0, 10.0, 20.0)}
        res["p_positive"] = p_positive(r)
        if wn == "OOS" and len(tf):
            rnd = random_timing(D, MM, tf, a, b, COSTS[sym]["base"], bias=(key == "unger_bias"))
            res["random_mean"] = float(np.nanmean(rnd))
            res["timing_p"] = float(np.nanmean(rnd >= r.mean()))
            res["ci95"] = bootstrap(r)
            res["leverage_for_2pct"] = (TARGET_ACCOUNT / r.mean()) if r.mean() > 0 else None
        out[wn] = res
        t = tf.copy()
        for ck, rr in nets.items():
            t[f"net_{ck}"] = rr
        if len(t):
            t["entry_utc"] = pd.to_datetime(D["t"][t["ei"].values], unit="s", utc=True).astype(str)
            t["exit_utc"] = pd.to_datetime(D["t"][t["xi"].values], unit="s", utc=True).astype(str)
        out[f"trades_{wn}"] = t
    return out


def portfolio(results: list[dict], members: list[tuple], cost: str, wn: str, lev: float) -> dict:
    """Equal shares of the account per member; each share trades its rule at leverage `lev`."""
    if not members:
        return {"members": 0}
    by = {(r["market"], r["family"]): r for r in results}
    start = min(by[mk][wn]["span"][0] for mk in members)
    end = max(by[mk][wn]["span"][1] for mk in members)
    daily = []
    for mk in members:
        t = by[mk][f"trades_{wn}"]
        if len(t):
            daily.append(pd.Series(t[f"net_{cost}"].values * lev / len(members), index=pd.to_datetime(t["date"].values)).groupby(level=0).sum())
    if not daily:
        return {"members": len(members), "months": 0}
    d = pd.concat(daily, axis=1, sort=True).fillna(0.0).sum(axis=1)
    eq = (1 + d).cumprod()
    months = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    mr = (1 + d).groupby(d.index.to_period("M")).prod().reindex(months, fill_value=1.0) - 1
    t = mr.mean() / (mr.std(ddof=1) / math.sqrt(len(mr))) if len(mr) > 1 and mr.std(ddof=1) > 0 else None
    halves = np.array_split(mr.values, 2)
    return {"members": len(members), "leverage_per_share": lev, "cost": cost, "window": [start, end], "months": int(len(mr)),
            "mean_month": float(mr.mean()), "median_month": float(mr.median()), "t_months": t, "months_up": float((mr > 0).mean()),
            "worst_month": float(mr.min()), "best_month": float(mr.max()), "total": float(eq.iloc[-1] - 1),
            "max_drawdown": float((eq / eq.cummax() - 1).min()), "halves_mean_month": [float(h.mean()) for h in halves],
            "monthly": {str(k): float(v) for k, v in mr.items()}}


def stage_evaluate() -> None:
    if not LOCK.exists():
        sys.exit("no lock: run `python ch_run.py select` first")
    lock = json.loads(LOCK.read_text())
    if lock["code_hash"] != code_hash():
        sys.exit(f"code changed since the lock ({lock['code_hash']} -> {code_hash()})")
    jobs = [(sym, k) for sym, fams in lock["selected"].items() for k, v in fams.items() if v["status"] == "locked"]
    with ProcessPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(_evaluate_task, jobs))
    padj = holm({(r["market"], r["family"]): r["OOS"].get("p_positive") for r in res})
    rows = []
    for r in res:
        i, o = r["IS"]["base"], r["OOS"]["base"]
        edge = bool(i.get("avg", -1) > 0 and o.get("trades", 0) >= MIN_OOS and o.get("avg", -1) > 0 and r["OOS"]["harsh"].get("avg", -1) > 0
                    and padj.get((r["market"], r["family"]), 1.0) < 0.05 and (r["OOS"].get("timing_p") if r["OOS"].get("timing_p") is not None else 1.0) < 0.05)
        target = bool(edge and i.get("avg", -1) >= TARGET and o.get("avg", -1) >= TARGET)
        r["verdict"] = "TARGET" if target else ("EDGE" if edge else "NO EDGE")
        r["p_holm"] = padj.get((r["market"], r["family"]))
        m1 = pd.Series(r["OOS"]["monthly"]["1x"])
        m10 = pd.Series(r["OOS"]["monthly"]["10x"])
        rows.append({"market": r["market"], "family": r["family"], "config": r["label"], "verdict": r["verdict"],
                     "IS_trades": i.get("trades"), "IS_avg": i.get("avg"), "IS_t": i.get("t_stat"),
                     "OOS_trades": o.get("trades"), "OOS_avg": o.get("avg"), "OOS_t": o.get("t_stat"), "OOS_pf": o.get("profit_factor"),
                     "OOS_win": o.get("win_rate"), "OOS_avg_harsh": r["OOS"]["harsh"].get("avg"),
                     "OOS_avg_futures": r["OOS"].get("futures", {}).get("avg"), "OOS_avg_measured": r["OOS"].get("measured", {}).get("avg"),
                     "p_holm": r["p_holm"], "random_mean": r["OOS"].get("random_mean"), "timing_p": r["OOS"].get("timing_p"),
                     "OOS_month_1x": float(m1.mean()), "OOS_month_10x": float(m10.mean()),
                     "OOS_10x_mdd": r["OOS"]["accounts"]["10x"]["max_drawdown"], "OOS_20x_ruined": r["OOS"]["accounts"]["20x"]["ruined_on"],
                     "lev_for_2pct": r["OOS"].get("leverage_for_2pct"), "OOS_trades_per_month": r["OOS"]["trades_per_month"]})
    sm = pd.DataFrame(rows)
    RES.mkdir(exist_ok=True)
    sm.to_csv(RES / "summary.csv", index=False)
    tdir = RES / "trades"
    tdir.mkdir(exist_ok=True)
    for r in res:
        pd.concat([r["trades_IS"].assign(window="IS"), r["trades_OOS"].assign(window="OOS")]).to_csv(tdir / f"{r['market']}_{r['family']}.csv", index=False)
    members = [(r["market"], r["family"]) for r in res if r["IS"]["base"].get("avg", -1) > 0]
    gold = [mk for mk in members if mk[0] == "XAUUSD"]
    every = [(r["market"], r["family"]) for r in res]
    ports = {}
    for name, mem in (("unger_all_markets", members), ("unger_gold_only", gold), ("every_locked_rule", every)):
        ports[name] = {"members": [f"{a}:{b}" for a, b in mem]}
        for wn in ("IS", "OOS"):
            for cost in ("base", "harsh"):
                for lev in (1.0, 10.0):
                    ports[name][f"{wn}_{cost}_{int(lev)}x"] = portfolio(res, mem, cost, wn, lev)
        o = ports[name].get("OOS_base_1x", {})
        oh = ports[name].get("OOS_harsh_1x", {})
        ports[name]["verdict"] = ("WORKING" if (o.get("months") and o["mean_month"] > 0 and (o.get("t_months") or 0) >= 2 and oh.get("mean_month", -1) > 0)
                                  else ("EMPTY" if not mem else "NOT WORKING"))
    detail = {"lock": {k: lock[k] for k in ("locked_at", "code_hash", "lock_sha256", "rules", "configurations_tested", "windows", "debug_windows")},
              "evaluated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
              "costs": {sym: {k: v.__dict__ for k, v in cs.items()} for sym, cs in COSTS.items()},
              "results": [{k: v for k, v in r.items() if not k.startswith("trades_")} for r in res], "portfolios": ports}
    (RES / "evaluation.json").write_text(json.dumps(jsonable(detail), indent=1, default=str))
    pd.set_option("display.width", 250)
    show = sm[["market", "family", "verdict", "IS_trades", "IS_avg", "OOS_trades", "OOS_avg", "OOS_t", "OOS_pf", "OOS_avg_harsh", "p_holm", "timing_p", "OOS_month_1x"]]
    print(show.to_string(index=False, float_format=lambda v: f"{v:.5f}"))
    for name, p in ports.items():
        o = p.get("OOS_base_1x", {})
        print(f"portfolio {name}: {p['verdict']}; members {len(p['members'])}; OOS mean month {o.get('mean_month', float('nan')) * 100:+.3f}% "
              f"(t {o.get('t_months')}), months up {o.get('months_up')}")


if __name__ == "__main__":
    {"select": stage_select, "evaluate": stage_evaluate}[sys.argv[1]]()
