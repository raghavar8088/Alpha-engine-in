"""Run the pre-registered YouTube top-20 backtests and write results/ (same discipline as the Booming Bulls study).

    python -I yt_run.py                 # every strategy and market
    python -I yt_run.py YT-01 YT-07     # some of them
    python -I yt_run.py --summary       # Holm correction + classification (opens the hold-out)

The chosen variant is picked from development + validation trades before any hold-out number is computed;
hold-out trades are kept for V0 and the chosen variant only. Stock "markets" (NSE15, NSE5, NSED) are pools of
single-stock books; their statistics use per-trade R, with the t-statistic clustered by day (trades on the same
day in different stocks are not independent), and their equity uses a 1% daily risk budget split over that
day's trades.
"""

from __future__ import annotations

import copy
import csv
import gzip
import hashlib
import json
import math
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I does not add the script's folder
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

import yt_markets as M  # noqa: E402
from yt_engine import Engine, forced_exit_rows, run_book  # noqa: E402
from yt_strategies import STRATEGIES, build_bars, exits_for  # noqa: E402

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
STOCK_POOLS = ("NSE15", "NSE5", "NSED")


def prereg_hash() -> str:
    return hashlib.sha256((HERE / "specs" / "PREREGISTRATION.md").read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def metrics(trades, pooled: bool = False) -> dict:
    tr = [t for t in trades if not t.excluded]
    n = len(tr)
    if n == 0:
        return {"n": 0}
    tr.sort(key=lambda t: (t.date, t.entry_k))
    r = np.array([t.r_net for t in tr])
    g = np.array([t.r_gross for t in tr])
    by_day = {}
    for t in tr:
        by_day.setdefault(t.date, []).append(t.r_net)
    days = sorted(by_day)
    day_mean = np.array([np.mean(by_day[d]) for d in days])
    eq_steps = (0.01 * day_mean) if pooled else (0.01 * r)
    eq = np.cumprod(1 + eq_steps)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    dd = float(((peak - eq) / peak).max())
    years = max((np.datetime64(days[-1]) - np.datetime64(days[0])).astype(int) / 365.25, 1 / 12)
    sd = float(r.std(ddof=1)) if n > 1 else float("nan")
    t_trade = float(r.mean() / (sd / math.sqrt(n))) if n > 1 and sd > 0 else float("nan")
    sdd = float(day_mean.std(ddof=1)) if len(day_mean) > 1 else float("nan")
    t_day = float(day_mean.mean() / (sdd / math.sqrt(len(day_mean)))) if len(day_mean) > 1 and sdd > 0 else float("nan")
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    srt = np.sort(r)[::-1]
    tot = r.sum()
    streak = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0
        streak = max(streak, cur)
    months = {}
    for d, x in zip(days, day_mean if pooled else [np.sum(by_day[d]) for d in days]):
        months[d[:7]] = months.get(d[:7], 0.0) + x
    return {
        "n": n, "days": len(days), "per_year": round(n / years, 1), "win_rate": round(float((r > 0).mean()), 3),
        "mean_r": round(float(r.mean()), 4), "mean_r_gross": round(float(g.mean()), 4),
        "t": round(t_day if pooled else t_trade, 2), "t_per_trade": round(t_trade, 2),
        "profit_factor": round(float(wins / losses), 3) if losses > 0 else float("inf"),
        "total_return_pct_1pct_risk": round(100 * float(eq[-1] - 1), 1),
        "cagr_pct": round(100 * float(eq[-1] ** (1 / years) - 1), 2) if eq[-1] > 0 else -100.0,
        "max_dd_pct": round(100 * dd, 1), "longest_losing_streak": int(streak),
        "best_r": round(float(r.max()), 2), "worst_r": round(float(r.min()), 2),
        "top5_share_of_net": round(float(srt[:5].sum() / tot), 3) if tot > 0 else float("nan"),
        "months_positive_pct": round(100 * float(np.mean([v > 0 for v in months.values()])), 1),
        "cost_r_mean": round(float(np.mean([t.cost_r for t in tr])), 4),
        "avg_rows_held": round(float(np.mean([t.rows_held for t in tr])), 1),
        "first": days[0], "last": days[-1],
        "exit_reasons": {k: int(v) for k, v in zip(*np.unique([t.reason for t in tr], return_counts=True))},
    }


def by_year(trades) -> dict:
    out = {}
    for t in trades:
        if not t.excluded:
            out.setdefault(t.date[:4], []).append(t.r_net)
    return {y: {"n": len(v), "mean_r": round(float(np.mean(v)), 3)} for y, v in sorted(out.items())}


def write_csv_gz(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
        if not rows:
            return
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()})


_POOLS: dict = {}
_SIMPLE: dict = {}


def markets_for(st, name):
    if name in ("NSE15", "NSE5"):
        if "NSE" not in _POOLS:
            _POOLS["NSE"] = M.nse_intraday()
        return _POOLS["NSE"]
    if name == "NSED":
        if "NSED" not in _POOLS:
            _POOLS["NSED"] = M.nse_daily()
        return _POOLS["NSED"]
    key = (name, st.kind == "overnight")
    if key not in _SIMPLE:
        m = M.load(name)
        if st.kind == "overnight" and not m.overnight:
            m = copy.copy(m)
            m.overnight = True
        _SIMPLE[key] = m
    return [_SIMPLE[key]]


def run_variant_all(st, mks, v, engines_kw=None, ex_override=None, cache=None):
    """All trades of one variant over the market list (one book per instrument)."""
    trades, rejects, nsig = [], {}, 0
    for m in mks:
        ck = (m.name, json.dumps(v.sig, sort_keys=True))
        if cache is not None and ck in cache:
            B, S = cache[ck]
        else:
            tfs = tuple(sorted(set(st.tfs) | {v.sig.get("tf", st.tfs[0])} | {v.exits.get("trail_tf")} - {None}))
            B = build_bars(m, tfs)
            S = st.fn(m, B, v.sig)
            if cache is not None:
                cache[ck] = (B, S)
        nsig += len(S)
        if not S:
            continue
        ex = ex_override(exits_for(st, v, m, B)) if ex_override else exits_for(st, v, m, B)
        clock, minute = st.exit_clock[st._mk]
        k_end = forced_exit_rows(m, clock, minute)
        eng = Engine(m, **(engines_kw or {}))
        tr, rej = run_book(eng, S, ex, st.limits, k_end, st.sid, v.tag)
        trades += tr
        for k, n in rej.items():
            rejects[k] = rejects.get(k, 0) + n
    return trades, rejects, nsig


def run_one(st, mname):
    t_start = time.time()
    st._mk = mname
    mks = markets_for(st, mname)
    pooled = mname in STOCK_POOLS
    cache = {}
    log = {"strategy": st.sid, "name": st.name, "channel": st.channel, "market": mname, "instruments": len(mks),
           "prereg_sha256": prereg_hash(), "variants": {}}
    results = {}
    for v in st.variants:
        tr, rej, nsig = run_variant_all(st, mks, v, cache=cache)
        results[v.tag] = tr
        log["variants"][v.tag] = {"signals": nsig, "trades": len(tr), "rejected": rej, "sig_params": v.sig,
                                  "exits": {k: x for k, x in v.exits.items()}}
    dv = {tag: [t for t in tr if t.split in ("dev", "val")] for tag, tr in results.items()}
    scores = {}
    for tag, tr in dv.items():
        mm = metrics(tr, pooled)
        scores[tag] = mm["mean_r"] if mm.get("n", 0) >= 30 else None
    eligible = {k: s for k, s in scores.items() if s is not None}
    chosen = max(eligible, key=lambda k: (eligible[k], k == "V0")) if eligible else "V0"
    log["selection"] = {"rule": "highest dev+val net mean R with >= 30 trades; tie -> V0", "dev_val_mean_r": scores, "chosen": chosen}
    keep = ["V0"] + ([chosen] if chosen != "V0" else [])
    for tag, tr in results.items():
        visible = tr if tag in keep else [t for t in tr if t.split != "hold"]
        write_csv_gz(RES / "trades" / f"{st.sid}_{mname}_{tag}.csv.gz", [asdict(t) for t in visible])
        e = log["variants"][tag]
        for sp in ("dev", "val"):
            e[sp] = metrics([t for t in tr if t.split == sp], pooled)
        e["dev_val"] = metrics(dv[tag], pooled)
        if tag in keep:
            e["hold"] = metrics([t for t in tr if t.split == "hold"], pooled)
            e["all"] = metrics(tr, pooled)
            e["by_year"] = by_year(tr)
            e["post_publication"] = metrics([t for t in tr if t.date >= st.first_upload], pooled)
    rob = {}
    for tag in keep:
        v = next(x for x in st.variants if x.tag == tag)
        runs = {"gross": {"spread_x": 0, "slip_x": 0, "comm_x": 0}, "costs_x2": {"spread_x": 2, "slip_x": 2, "comm_x": 2},
                "slippage_x3": {"slip_x": 3}, "delay_1row": {"entry_delay": 1}}
        out = {}
        for name, kw in runs.items():
            tr, _, _ = run_variant_all(st, mks, v, kw, cache=cache)
            out[name] = {sp: metrics([t for t in tr if t.split in sps], pooled) for sp, sps in (("dev_val", ("dev", "val")), ("hold", ("hold",)))}
        tr0 = v.exits.get("target_r", 2.0)
        if tr0 is not None and "target_abs" not in v.exits:
            for dlt in (-0.5, 0.5):
                tr, _, _ = run_variant_all(st, mks, v, ex_override=lambda e, d=dlt: replace(e, target_r=tr0 + d), cache=cache)
                out[f"target_{tr0 + dlt:g}R"] = {sp: metrics([t for t in tr if t.split in sps], pooled) for sp, sps in (("dev_val", ("dev", "val")), ("hold", ("hold",)))}
        rob[tag] = {k: {sp: {kk: vv for kk, vv in mm.items() if kk in ("n", "mean_r", "t", "profit_factor", "max_dd_pct")} for sp, mm in d.items()} for k, d in out.items()}
    log["robustness"] = rob
    years = sorted({t.date[:4] for tr in results.values() for t in tr})
    wf, picks = [], {}
    for i, y in enumerate(years):
        if i < 3:
            continue
        prior = {tag: [t.r_net for t in tr if t.date[:4] < y and not t.excluded] for tag, tr in results.items()}
        prior = {k: x for k, x in prior.items() if len(x) >= 30}
        if not prior:
            continue
        pick = max(prior, key=lambda k: (np.mean(prior[k]), k == "V0"))
        picks[y] = pick
        wf += [t for t in results[pick] if t.date[:4] == y]
    log["walk_forward"] = {"picks": picks, "oos": metrics(wf, pooled)}
    for tag in keep:   # equity curves (by day) for the report
        tr = sorted([t for t in results[tag] if not t.excluded], key=lambda t: (t.date, t.entry_k))
        rows, eq, cum = [], 1.0, 0.0
        by_d = {}
        for t in tr:
            by_d.setdefault(t.date, []).append(t)
        for d in sorted(by_d):
            rr = [t.r_net for t in by_d[d]]
            step = float(np.mean(rr)) if pooled else float(np.sum(rr))
            cum += float(np.sum(rr)) if not pooled else step
            eq *= (1 + 0.01 * step) if pooled else float(np.prod([1 + 0.01 * x for x in rr]))
            rows.append({"date": d, "split": by_d[d][0].split, "n": len(rr), "cum_r": round(cum, 3), "equity_1pct": round(eq, 6)})
        write_csv_gz(RES / "equity" / f"{st.sid}_{mname}_{tag}.csv.gz", rows)
    log["seconds"] = round(time.time() - t_start, 1)
    (RES / "runs").mkdir(parents=True, exist_ok=True)
    (RES / "runs" / f"{st.sid}_{mname}.json").write_text(json.dumps(log, indent=1, default=str))
    return log


def holm(pvals: dict) -> dict:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    k, out, running = len(items), {}, 0.0
    for i, (key, p) in enumerate(items):
        running = max(running, min(1.0, (k - i) * p))
        out[key] = running
    return out


def one_sided_p(t) -> float:
    if t is None or not isinstance(t, (int, float)) or not math.isfinite(t):
        return 1.0
    return 0.5 * (1 - math.erf(t / math.sqrt(2)))


def summarize():
    runs = [json.loads(p.read_text()) for p in sorted((RES / "runs").glob("*.json"))]
    tests = {}
    for r in runs:
        for tag in {"V0", r["selection"]["chosen"]}:
            h = r["variants"][tag].get("hold", {"n": 0})
            if h.get("n", 0) >= 2:
                tests[f'{r["strategy"]}|{r["market"]}|{tag}'] = one_sided_p(h.get("t"))
    adj = holm(tests)
    rows = []
    for r in runs:
        chosen = r["selection"]["chosen"]
        for tag in dict.fromkeys(["V0", chosen]):
            v = r["variants"][tag]
            h, dv, d_, va = v.get("hold", {"n": 0}), v["dev_val"], v["dev"], v["val"]
            rb = r["robustness"].get(tag, {})
            key = f'{r["strategy"]}|{r["market"]}|{tag}'
            gates = {
                "hold_t>=2": h.get("n", 0) > 1 and h.get("mean_r", -1) > 0 and (h.get("t") or 0) >= 2.0,
                "holm_p<0.05": adj.get(key, 1.0) < 0.05,
                "dev_and_val_positive": d_.get("mean_r", -1) > 0 and va.get("mean_r", -1) > 0,
                "hold_n>=50": h.get("n", 0) >= 50,
                "hold_costs_x2_positive": rb.get("costs_x2", {}).get("hold", {}).get("mean_r", -1) > 0,
                "hold_delay_positive": rb.get("delay_1row", {}).get("hold", {}).get("mean_r", -1) > 0,
                "hold_top5_share<0.5": (h.get("top5_share_of_net") or 9) < 0.5,
                "hold_max_dd<20pct": h.get("max_dd_pct", 100) < 20,
            }
            n_total = (v.get("all") or {}).get("n", 0)
            if n_total < 30 or h.get("n", 0) == 0:
                cls = "unable to evaluate"
            elif all(gates.values()):
                cls = "candidate for paper trading"
            elif h.get("mean_r", -1) > 0 and dv.get("mean_r", -1) > 0:
                cls = "needs more evidence"
            else:
                cls = "not supported"
            rows.append({"strategy": r["strategy"], "name": r["name"], "channel": r["channel"], "market": r["market"],
                         "instruments": r["instruments"], "variant": tag, "chosen": tag == chosen, "class": cls,
                         "holm_p": round(adj.get(key, 1.0), 4), "gates": gates,
                         "dev": {k: d_.get(k) for k in ("n", "mean_r", "t")}, "val": {k: va.get(k) for k in ("n", "mean_r", "t")},
                         "hold": {k: h.get(k) for k in ("n", "mean_r", "mean_r_gross", "t", "win_rate", "profit_factor", "max_dd_pct", "cagr_pct", "top5_share_of_net", "cost_r_mean")},
                         "post_publication": {k: v.get("post_publication", {}).get(k) for k in ("n", "mean_r", "t", "first")},
                         "walk_forward_oos": {k: r["walk_forward"]["oos"].get(k) for k in ("n", "mean_r", "t")}})
    out = {"prereg_sha256": prereg_hash(), "holdout_tests": len(tests), "rows": rows}
    (RES / "summary.json").write_text(json.dumps(out, indent=1, default=str))
    for x in rows:
        print(f'{x["strategy"]:6} {x["market"]:9} {x["variant"]:3}{"*" if x["chosen"] else " "} dev {x["dev"]["mean_r"]!s:>8} '
              f'val {x["val"]["mean_r"]!s:>8} hold {x["hold"].get("mean_r")!s:>8} (n {x["hold"].get("n")!s:>5}, t {x["hold"].get("t")!s:>6}) -> {x["class"]}')


def main(argv):
    if "--summary" in argv:
        summarize()
        return
    want = [a for a in argv if a.startswith("YT-")] or list(STRATEGIES)
    for sid in want:
        st = STRATEGIES[sid]
        for mk in st.markets:
            t0 = time.time()
            lg = run_one(st, mk)
            v0 = lg["variants"]["V0"]
            print(f"{sid} {mk}: instruments {lg['instruments']} signals {v0['signals']} trades {v0['trades']} | dev+val V0 "
                  f"mean R {v0['dev_val'].get('mean_r')} (n {v0['dev_val'].get('n')}) gross {v0['dev_val'].get('mean_r_gross')} | "
                  f"chosen {lg['selection']['chosen']} | {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
