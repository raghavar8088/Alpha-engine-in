"""Run the study in two locked stages.

  python xa_run.py select     IN-SAMPLE ONLY (2010-01-01 .. 2021-09-30). Every configuration of every
                              family is backtested; each family's configuration is chosen by the rule
                              below and written to results/selection_locked.json together with a hash
                              of the code. Nothing after 2021-09-30 is read.
  python xa_run.py evaluate   OUT-OF-SAMPLE (2021-10-01 .. latest). Refuses to run unless the lock exists
                              and the code is unchanged since it was written. Evaluates the locked
                              choices once, plus the diagnostics, and writes the report data.

SELECTION RULE (fixed before any result): within a family, among configurations with at least
MIN_IS_TRADES in-sample trades and an in-sample average net return per trade (base costs C1) of at
least 2.0%, choose the highest t-statistic of the per-trade returns. A family with no such
configuration FAILS in-sample.

PASS RULE (fixed before any result): the locked configuration passes when, out of sample under C1,
it has at least MIN_OOS_TRADES trades, an average net return per trade of at least 2.0%, and a
profit factor above 1. Everything else (harsher costs, random-entry timing test, bootstrap interval,
the 2021-23 vs 2024-26 split, neighbouring parameters, buy-and-hold) is reported, not used to pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # own modules only; data/ is never on the path

import hashlib
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

import xa_data
import xa_strategies as S
from xa_engine import COSTS, Market, curve_stats, equity_curve, net_returns, run, stats, trades_frame

ROOT = Path(__file__).resolve().parent
RES = ROOT / ("results_debug" if os.environ.get("XA_DEBUG_WINDOWS") == "1" else "results")
IS_START, OOS_START = "2010-01-01", "2021-10-01"
TARGET = 0.02
# Minimum trade counts, set from how often the rules CAN trade (monthly rules switch about once or
# twice a year), not from results: ~1 a year in-sample, ~1.6 a year out of sample. A pass on fewer
# than SMALL_SAMPLE out-of-sample trades is flagged as a small sample in every table.
MIN_IS_TRADES, MIN_OOS_TRADES, SMALL_SAMPLE = 12, 8, 20
LOCK = RES / "selection_locked.json"
CODE_FILES = ("xa_engine.py", "xa_strategies.py", "xa_run.py", "xa_data.py")

_M: Market | None = None


def market() -> Market:
    global _M
    if _M is None:
        _M = Market.from_bars(xa_data.load())
    return _M


DEBUG = os.environ.get("XA_DEBUG_WINDOWS") == "1"


def windows(m: Market) -> dict:
    """XA_DEBUG_WINDOWS=1 tests the pipeline on 2010-2017 / 2018-2021-09 - inside the real in-sample
    period - so the code can be debugged without ever reading the real out-of-sample data."""
    if DEBUG:
        is_first, oos_first = m.session_index(IS_START), m.session_index("2018-01-01")
        return {"IS": (is_first, oos_first - 1), "OOS": (oos_first, m.session_index(OOS_START) - 1)}
    is_first = m.session_index(IS_START)
    oos_first = m.session_index(OOS_START)
    return {"IS": (is_first, oos_first - 1), "OOS": (oos_first, len(m.d_date) - 1)}


def code_hash() -> str:
    h = hashlib.sha256()
    for f in CODE_FILES:
        h.update((ROOT / f).read_bytes())
    return h.hexdigest()[:16]


def simulate(fam: S.Family, cfg: dict, first: int, last: int):
    m = market()
    if fam.key == "london_breakout":
        tr = S.run_london_breakout(m, first, last, cfg["tp_r"], cfg["range_filter"])
    elif fam.key == "session_drift":
        tr = S.run_session_drift(m, first, last, cfg["exit_hour"])
    else:
        tr = run(m, S.build_plan(fam, m, cfg), first, last)
    return trades_frame(m, tr)


def evaluate_window(fam: S.Family, cfg: dict, first: int, last: int, curves: bool = True) -> dict:
    m = market()
    tf = simulate(fam, cfg, first, last)
    out = {"tf": tf}
    for ck, c in COSTS.items():
        r = net_returns(m, tf, c)
        st = stats(r)
        if curves:
            st.update(curve_stats(equity_curve(m, tf, r, first, last, c)))
        out[ck] = st
    held = np.zeros(last - first + 1, bool)
    for a, b in zip(tf["entry_session"].values, tf["exit_session"].values):
        held[a - first:b - first + 1] = True
    out["exposure"] = float(held.mean())          # share of sessions with a position open at some point
    out["avg_hold_sessions"] = float((tf["exit_session"] - tf["entry_session"]).mean()) if not tf.empty else np.nan
    out["long_share"] = float((tf["side"] == 1).mean()) if not tf.empty else np.nan
    return out


def _family_is(key: str) -> list[dict]:
    fam = next(f for f in S.FAMILIES if f.key == key)
    m = market()
    first, last = windows(m)["IS"]
    rows = []
    for cfg in fam.configs():
        t0 = time.time()
        res = evaluate_window(fam, cfg, first, last, curves=False)
        rows.append({"family": key, "config": S.label(cfg), "cfg": cfg, "is_default": cfg == fam.default,
                     **{f"IS_{ck}_{k}": v for ck in COSTS for k, v in res[ck].items() if k != "by_year"},
                     "IS_exposure": res["exposure"], "IS_avg_hold_sessions": res["avg_hold_sessions"],
                     "IS_long_share": res["long_share"], "secs": round(time.time() - t0, 2)})
    return rows


def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if (x != x or math.isinf(x)) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def stage_select() -> None:
    RES.mkdir(exist_ok=True)
    m = market()
    w = windows(m)
    print(f"in-sample sessions {m.d_date[w['IS'][0]]} .. {m.d_date[w['IS'][1]]}; families {len(S.FAMILIES)}; "
          f"configurations {sum(len(list(f.configs())) for f in S.FAMILIES)}", flush=True)
    with ProcessPoolExecutor(max_workers=12) as ex:
        allrows = [r for rows in ex.map(_family_is, [f.key for f in S.FAMILIES]) for r in rows]
    df = pd.DataFrame(allrows)
    df.drop(columns=["cfg"]).to_csv(RES / "is_all_configs.csv", index=False)
    chosen = {}
    for fam in S.FAMILIES:
        sub = df[df["family"] == fam.key]
        elig = sub[(sub["IS_C1_trades"] >= MIN_IS_TRADES) & (sub["IS_C1_avg"] >= TARGET)]
        if len(elig):
            best = elig.sort_values(["IS_C1_t_stat", "IS_C1_avg"], ascending=False).iloc[0]
            chosen[fam.key] = {"status": "selected", "config": best["cfg"], "label": best["config"],
                               "IS_trades": int(best["IS_C1_trades"]), "IS_avg": float(best["IS_C1_avg"]), "IS_t": float(best["IS_C1_t_stat"]),
                               "eligible_configs": int(len(elig)), "configs": int(len(sub))}
        else:
            ok_n = sub[sub["IS_C1_trades"] >= MIN_IS_TRADES]
            top = (ok_n if len(ok_n) else sub).sort_values("IS_C1_avg", ascending=False).iloc[0]
            chosen[fam.key] = {"status": "failed in-sample", "config": fam.default, "label": S.label(fam.default),
                               "best_is_avg_with_enough_trades": float(top["IS_C1_avg"]) if len(ok_n) else None,
                               "best_is_label": top["config"], "eligible_configs": 0, "configs": int(len(sub)),
                               "why": ("no configuration reached a 2% average with " f">= {MIN_IS_TRADES} trades")}
    lock = {"locked_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "code_hash": code_hash(),
            "in_sample": [str(m.d_date[w["IS"][0]]), str(m.d_date[w["IS"][1]])], "out_of_sample_from": OOS_START,
            "rules": {"target_avg_per_trade": TARGET, "min_is_trades": MIN_IS_TRADES, "min_oos_trades": MIN_OOS_TRADES,
                      "selection": "max in-sample t-stat among configs with >= min trades and avg >= target (costs C1)",
                      "pass": "OOS (C1): trades >= min, avg >= target, profit factor > 1"},
            "configurations_tested": int(len(df)), "families": _jsonable(chosen)}
    body = json.dumps(lock, indent=1, default=str)
    lock["lock_sha256"] = hashlib.sha256(body.encode()).hexdigest()[:16]
    LOCK.write_text(json.dumps(lock, indent=1, default=str))
    print(f"locked {LOCK.name}: code {lock['code_hash']}, lock {lock['lock_sha256']}")
    for k, v in chosen.items():
        if v["status"] == "selected":
            print(f"  {k:<18} SELECTED  {v['label']:<55} IS trades {v['IS_trades']:>4}  avg {v['IS_avg']*100:6.2f}%  t {v['IS_t']:5.2f}  ({v['eligible_configs']}/{v['configs']} eligible)")
        else:
            b = v.get("best_is_avg_with_enough_trades")
            print(f"  {k:<18} FAILED IS  best avg with enough trades {('%.2f%%' % (b*100)) if b is not None else 'n/a'} ({v['best_is_label']})")


# ── out-of-sample stage ─────────────────────────────────────────────────────────


def random_entry_test(m: Market, tf: pd.DataFrame, first: int, last: int, c, sims: int = 5000, seed: int = 7) -> dict:
    """Same trades (side and holding length), random entry sessions inside the window: what the
    period's drift alone pays a strategy that times nothing."""
    if tf.empty:
        return {}
    rng = np.random.default_rng(seed)
    L = (tf["exit_session"] - tf["entry_session"]).values
    side = tf["side"].values
    opens = m.h_o[m.s_start]
    ri = m.rate.index.get_indexer(pd.to_datetime(m.d_date))
    cumr = np.concatenate([[0.0], np.cumsum(m.rate.values)])
    span = (last - L - first + 1).clip(min=1)
    e = first + np.floor(rng.random((sims, len(L))) * span).astype(int)
    x = np.minimum(e + L, last)
    ent = opens[e]
    ext = np.where(L == 0, m.d_c[e], np.where(x == last, m.d_c[x], opens[x]))
    adv = c.spread / 2 + c.slippage
    efill = ent + side * adv
    xfill = ext - side * adv
    r = (side * (xfill - efill) - 2 * c.commission) / efill
    if c.fin_long_add is not None:
        nights = ri[x] - ri[e]
        avg = np.where(nights > 0, (cumr[ri[x]] - cumr[ri[e]]) / np.maximum(nights, 1), 0.0)
        ann = np.where(side == 1, avg + c.fin_long_add, c.fin_short_add - avg)
        r = r - ann * nights / 365.0
    means = r.mean(axis=1)
    return {"random_mean_avg": float(means.mean()), "random_p95_avg": float(np.quantile(means, 0.95)),
            "random_share_reaching_2pct": float((means >= TARGET).mean()), "means": means}


def bootstrap_ci(r: np.ndarray, sims: int = 10000, seed: int = 11) -> tuple[float, float]:
    if len(r) < 2:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    b = r[rng.integers(0, len(r), (sims, len(r)))].mean(axis=1)
    return float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))


def holm(pvals: dict) -> dict:
    items = sorted((p, k) for k, p in pvals.items() if p == p)
    n, out, run_max = len(items), {}, 0.0
    for i, (p, k) in enumerate(items):
        adj = min(1.0, (n - i) * p)
        run_max = max(run_max, adj)
        out[k] = run_max
    return out


def _passes(st: dict) -> bool:
    return st.get("trades", 0) >= MIN_OOS_TRADES and st.get("avg", -1) >= TARGET and (st.get("profit_factor") or 0) > 1.0


def _family_oos(key: str) -> dict:
    """Every configuration of a family out of sample (for the diagnostics), plus the locked one in full."""
    lock = json.loads(LOCK.read_text())
    fam = next(f for f in S.FAMILIES if f.key == key)
    m = market()
    w = windows(m)
    first, last = w["OOS"]
    grid = []
    for cfg in fam.configs():
        res = evaluate_window(fam, cfg, first, last, curves=False)
        grid.append({"config": S.label(cfg), "cfg": cfg, "C1": res["C1"]})
    entry = lock["families"][key]
    cfg = entry["config"]
    if isinstance(cfg, dict):
        cfg = {k: (tuple(v) if isinstance(v, list) else v) for k, v in cfg.items()}
    full = {}
    for wn, (a, b) in w.items():
        full[wn] = evaluate_window(fam, cfg, a, b, curves=True)
    tf_oos = full["OOS"]["tf"]
    r_oos = net_returns(m, tf_oos, COSTS["C1"])
    re = random_entry_test(m, tf_oos, first, last, COSTS["C1"])
    pval = float((re["means"] >= r_oos.mean()).mean()) if len(r_oos) and re else np.nan
    ci = bootstrap_ci(r_oos)
    split = {}
    if not tf_oos.empty:
        cut = np.datetime64("2024-01-01")
        for nm, mask in (("2021-10..2023-12", tf_oos["entry_date"].values < cut), ("2024-01..latest", tf_oos["entry_date"].values >= cut)):
            rr = r_oos[mask]
            split[nm] = {"trades": int(mask.sum()), "avg": float(rr.mean()) if len(rr) else None}
    # neighbours: configurations one parameter away from the locked one
    def dist(a, b):
        return sum(1 for k in a if a[k] != b.get(k))
    neigh = [g for g in grid if dist(g["cfg"], cfg) == 1]
    trades_out = {}
    for wn in w:
        tf = full[wn]["tf"].copy()
        for ck, c in COSTS.items():
            tf[f"net_{ck}"] = net_returns(m, tf, c)
        tf["entry_time_utc"] = pd.to_datetime(m.h_t[tf["entry_hour"].values], unit="s", utc=True).astype(str) if not tf.empty else []
        tf["exit_time_utc"] = pd.to_datetime(m.h_t[tf["exit_hour"].values], unit="s", utc=True).astype(str) if not tf.empty else []
        trades_out[wn] = tf
    curves = {}
    for wn, (a, b) in w.items():
        tf = full[wn]["tf"]
        eq = equity_curve(m, tf, net_returns(m, tf, COSTS["C1"]), a, b, COSTS["C1"])
        curves[wn] = eq
    return {"key": key, "status_is": entry["status"], "label": S.label(cfg), "cfg": cfg,
            "IS": {ck: full["IS"][ck] for ck in COSTS} | {"exposure": full["IS"]["exposure"], "avg_hold_sessions": full["IS"]["avg_hold_sessions"], "long_share": full["IS"]["long_share"]},
            "OOS": {ck: full["OOS"][ck] for ck in COSTS} | {"exposure": full["OOS"]["exposure"], "avg_hold_sessions": full["OOS"]["avg_hold_sessions"], "long_share": full["OOS"]["long_share"]},
            "random_entry": {k: v for k, v in re.items() if k != "means"}, "timing_p_value": pval, "oos_ci95": ci, "oos_split": split,
            "neighbours": {"count": len(neigh), "pass": sum(1 for g in neigh if _passes(g["C1"]))},
            "grid_oos": {"count": len(grid), "pass": sum(1 for g in grid if _passes(g["C1"])),
                         "rows": [{"config": g["config"], **{k: g["C1"].get(k) for k in ("trades", "avg", "profit_factor")}} for g in grid]},
            "trades": trades_out, "curves": curves}


def buy_and_hold(m: Market, first: int, last: int, with_curve: bool = False) -> dict:
    """Holding gold over the window as one trade, charged like the strategies (C1 includes the
    financing a long pays for the whole period)."""
    from xa_engine import Trade
    tf = trades_frame(m, [Trade(1, first, int(m.s_start[first]), float(m.h_o[m.s_start[first]]), last, int(m.s_end[last] - 1), float(m.d_c[last]), "hold")])
    out = {}
    for ck, c in COSTS.items():
        r = net_returns(m, tf, c)
        eq = equity_curve(m, tf, r, first, last, c)
        out[ck] = {"total_return": float(r[0])} | curve_stats(eq)
        if with_curve and ck == "C1":
            out["curve"] = {"dates": [str(x.date()) for x in eq.index[::5]], "equity": [round(float(v), 5) for v in eq.values[::5]]}
    return out


def stage_evaluate() -> None:
    if not LOCK.exists():
        sys.exit("no selection lock: run `python xa_run.py select` first")
    lock = json.loads(LOCK.read_text())
    if lock["code_hash"] != code_hash():
        sys.exit(f"code changed since the lock ({lock['code_hash']} -> {code_hash()}): re-run select and disclose it")
    m = market()
    w = windows(m)
    with ProcessPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(_family_oos, [f.key for f in S.FAMILIES]))
    padj = holm({r["key"]: r["timing_p_value"] for r in results if r["status_is"] == "selected"})
    bh = {wn: buy_and_hold(m, a, b, with_curve=True) for wn, (a, b) in w.items()}
    a, b = w["OOS"]
    cut = int(np.searchsorted(m.d_date, np.datetime64("2024-01-01"), side="left"))
    bh_split = {}
    if a < cut <= b:
        bh_split = {"2021-10..2023-12": buy_and_hold(m, a, cut - 1)["C1"]["total_return"],
                    "2024-01..latest": buy_and_hold(m, cut, b)["C1"]["total_return"]}
    summary = []
    for r in results:
        o, i = r["OOS"]["C1"], r["IS"]["C1"]
        passed = r["status_is"] == "selected" and _passes(o)
        summary.append({"family": r["key"], "is_status": r["status_is"], "config": r["label"], "PASS": passed,
                        "IS_trades": i.get("trades"), "IS_avg": i.get("avg"), "OOS_trades": o.get("trades"), "OOS_avg": o.get("avg"),
                        "OOS_pf": o.get("profit_factor"), "OOS_avg_C2": r["OOS"]["C2"].get("avg"), "OOS_avg_C0": r["OOS"]["C0"].get("avg"),
                        "OOS_avg_C3": r["OOS"]["C3"].get("avg"),
                        "timing_p": r["timing_p_value"], "timing_p_holm": padj.get(r["key"]), "random_avg": r["random_entry"].get("random_mean_avg"),
                        "ci_low": r["oos_ci95"][0], "ci_high": r["oos_ci95"][1],
                        "OOS_21_23_avg": r["oos_split"].get("2021-10..2023-12", {}).get("avg"), "OOS_24_26_avg": r["oos_split"].get("2024-01..latest", {}).get("avg"),
                        "neighbours_pass": f"{r['neighbours']['pass']}/{r['neighbours']['count']}", "grid_pass": f"{r['grid_oos']['pass']}/{r['grid_oos']['count']}",
                        "OOS_cagr": o.get("cagr"), "OOS_mdd": o.get("max_drawdown"), "IS_cagr": i.get("cagr"), "IS_mdd": i.get("max_drawdown")})
        tdir = RES / "trades"
        tdir.mkdir(exist_ok=True)
        pd.concat([r["trades"]["IS"].assign(window="IS"), r["trades"]["OOS"].assign(window="OOS")]).to_csv(tdir / f"{r['key']}.csv", index=False)
    sm = pd.DataFrame(summary)
    sm.to_csv(RES / "summary.csv", index=False)
    detail = {"lock": {k: lock[k] for k in ("locked_at", "code_hash", "lock_sha256", "rules", "configurations_tested")},
              "evaluated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
              "windows": {wn: [str(m.d_date[a]), str(m.d_date[b])] for wn, (a, b) in w.items()},
              "buy_and_hold": bh, "buy_and_hold_oos_split": bh_split, "costs": {k: v.__dict__ for k, v in COSTS.items()},
              "families": {r["key"]: {k: v for k, v in r.items() if k not in ("trades", "curves", "cfg")} for r in results},
              "curves": {r["key"]: {wn: {"dates": [str(x.date()) for x in eq.index[::5]], "equity": [round(float(v), 5) for v in eq.values[::5]]}
                                    for wn, eq in r["curves"].items()} for r in results},
              "holm": padj}
    (RES / "oos_detail.json").write_text(json.dumps(_jsonable(detail), indent=1, default=str))
    pd.set_option("display.width", 250)
    cols = ["family", "is_status", "PASS", "IS_trades", "IS_avg", "OOS_trades", "OOS_avg", "OOS_pf", "OOS_avg_C2", "timing_p", "timing_p_holm",
            "random_avg", "OOS_21_23_avg", "OOS_24_26_avg", "neighbours_pass", "grid_pass"]
    print(sm[cols].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print("buy & hold IS C1:", {k: round(v, 4) for k, v in bh["IS"]["C1"].items() if k != "by_year"})
    print("buy & hold OOS C1:", {k: round(v, 4) for k, v in bh["OOS"]["C1"].items() if k != "by_year"})


if __name__ == "__main__":
    {"select": stage_select, "evaluate": stage_evaluate}[sys.argv[1]]()
