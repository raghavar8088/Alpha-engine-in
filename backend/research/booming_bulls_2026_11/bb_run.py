"""Run the pre-registered backtests (Phases 7-8) and write results/.

    python -I bb_run.py                 # every strategy and market
    python -I bb_run.py BB-01 BB-07     # some of them
    python -I bb_run.py --summary       # study-level Holm correction + classification (after the runs)

Hold-out discipline: the chosen variant is picked from development + validation trades BEFORE any
hold-out number is computed. Hold-out trades are written and scored for V0 and the chosen variant only;
other variants' hold-out trades are dropped unread. Every result file carries the pre-registration hash.
"""

from __future__ import annotations

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
import numpy as np

from bb_engine import Engine, Exits, forced_exit_rows, run_book
from bb_markets import Minutes, load
from bb_strategies import STRATEGIES, Strategy, build_bars, exits_for, signals

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
NIFTY_LOT, NIFTY_MARGIN, CAPITAL_INR = 65, 0.12, 1_000_000


def prereg_hash() -> str:
    return hashlib.sha256((HERE / "specs" / "PREREGISTRATION.md").read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ── metrics ───────────────────────────────────────────────────────────────────────────

def metrics(trades: list, key: str = "r_net") -> dict:
    tr = [t for t in trades if not t.excluded]
    n = len(tr)
    if n == 0:
        return {"n": 0}
    r = np.array([getattr(t, key) for t in tr])
    g = np.array([t.r_gross for t in tr])
    wins = r[r > 0].sum()
    losses = -r[r < 0].sum()
    eq = np.cumprod(1 + 0.01 * r)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    dd = float(((peak - eq) / peak).max())
    dates = np.array([t.date for t in tr])
    years = max((np.datetime64(dates[-1]) - np.datetime64(dates[0])).astype(int) / 365.25, 1 / 12)
    total = float(eq[-1] - 1)
    cagr = float(eq[-1] ** (1 / years) - 1) if eq[-1] > 0 else -1.0
    # daily Sharpe over trading days with a trade (risk 1% a trade)
    by_day = {}
    for t, x in zip(tr, r):
        by_day[t.date] = by_day.get(t.date, 0.0) + 0.01 * x
    dr = np.array(list(by_day.values()))
    streak = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0
        streak = max(streak, cur)
    srt = np.sort(r)[::-1]
    pos_total = r.sum()
    top5 = float(srt[:5].sum() / pos_total) if pos_total > 0 else float("nan")
    top10p = float(srt[:max(1, n // 10)].sum() / pos_total) if pos_total > 0 else float("nan")
    months = {}
    for t, x in zip(tr, r):
        months[t.date[:7]] = months.get(t.date[:7], 0.0) + x
    sd = float(r.std(ddof=1)) if n > 1 else float("nan")
    return {
        "n": n, "per_year": round(n / years, 1), "win_rate": round(float((r > 0).mean()), 3),
        "mean_r": round(float(r.mean()), 4), "mean_r_gross": round(float(g.mean()), 4),
        "median_r": round(float(np.median(r)), 3), "sd_r": round(sd, 3),
        "t": round(float(r.mean() / (sd / math.sqrt(n))), 2) if n > 1 and sd > 0 else float("nan"),
        "profit_factor": round(float(wins / losses), 3) if losses > 0 else float("inf"),
        "total_return_pct_1pct_risk": round(100 * total, 1), "cagr_pct": round(100 * cagr, 2),
        "max_dd_pct": round(100 * dd, 1),
        "sharpe_daily_ann": round(float(dr.mean() / dr.std(ddof=1) * math.sqrt(252)), 2) if len(dr) > 2 and dr.std() > 0 else float("nan"),
        "longest_losing_streak": int(streak), "avg_minutes_held": round(float(np.mean([t.minutes_held for t in tr])), 1),
        "best_r": round(float(r.max()), 2), "worst_r": round(float(r.min()), 2),
        "top5_share_of_net": round(top5, 3), "top10pct_share_of_net": round(top10p, 3),
        "months_positive_pct": round(100 * float(np.mean([v > 0 for v in months.values()])), 1),
        "cost_r_mean": round(float(np.mean([t.cost_r for t in tr])), 4),
        "first": tr[0].date, "last": tr[-1].date,
        "exit_reasons": {k: int(v) for k, v in zip(*np.unique([t.reason for t in tr], return_counts=True))},
    }


def by_year(trades) -> dict:
    out = {}
    for t in trades:
        if t.excluded:
            continue
        y = t.date[:4]
        out.setdefault(y, []).append(t.r_net)
    return {y: {"n": len(v), "mean_r": round(float(np.mean(v)), 3), "sum_r": round(float(np.sum(v)), 2)} for y, v in sorted(out.items())}


def inr_account(trades, m: Minutes) -> dict:
    """NIFTY: Rs 10 lakh account, whole lots of 65, 1% risk, margin cap 12% of notional per lot."""
    eq, peak, dd, skipped, taken, lots_used = CAPITAL_INR, CAPITAL_INR, 0.0, 0, 0, []
    for t in trades:
        if t.excluded:
            continue
        lots = int(0.01 * eq // (t.risk * NIFTY_LOT))
        lots = min(lots, int(eq // (NIFTY_MARGIN * t.entry * NIFTY_LOT)))
        if lots <= 0:
            skipped += 1
            continue
        taken += 1
        lots_used.append(lots)
        eq += lots * NIFTY_LOT * t.r_net * t.risk
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
        if eq <= 0:
            break
    return {"start_inr": CAPITAL_INR, "end_inr": round(eq), "return_pct": round(100 * (eq / CAPITAL_INR - 1), 1),
            "max_dd_pct": round(100 * dd, 1), "trades": taken, "skipped_zero_lots": skipped,
            "median_lots": float(np.median(lots_used)) if lots_used else 0}


def equity_rows(trades) -> list:
    eq, rows = 1.0, []
    for t in trades:
        if t.excluded:
            continue
        eq *= 1 + 0.01 * t.r_net
        rows.append((t.date, t.split, round(t.r_net, 4), round(eq, 6)))
    return rows


def write_trades(path: Path, trades):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(t) for t in trades]
    with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
        if not rows:
            fh.write("")
            return
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()})


# ── one strategy on one market ────────────────────────────────────────────────────────

_MK: dict[str, Minutes] = {}
_BARS: dict = {}


def market(name: str) -> Minutes:
    if name not in _MK:
        _MK[name] = load(name)
    return _MK[name]


def bars_for(m: Minutes, tfs) -> dict:
    out = {}
    for tf in tfs:
        key = (m.name, tf)
        if key not in _BARS:
            _BARS[key] = build_bars(m, (tf,))[tf]
        out[tf] = _BARS[key]
    return out


def run_one(st: Strategy, mname: str) -> dict:
    t_start = time.time()
    m = market(mname)
    tfs = tuple(sorted(set(st.tfs) | {v.sig.get("tf", st.base_sig.get("tf", st.tfs[0])) for v in st.variants}
                       | {v.exits.get("trail_tf") for v in st.variants if v.exits.get("trail_tf")}))
    B = bars_for(m, tfs)
    other = None
    if st.sid == "BB-03":
        bn = market("BANKNIFTY")
        other = (bn, bars_for(bn, (5,)))
    clock, minute = st.exit_clock[mname]
    k_end = forced_exit_rows(m, clock, minute)
    sig_cache = {}
    log = {"strategy": st.sid, "market": mname, "prereg_sha256": prereg_hash(), "variants": {}}

    def sigs_for(v):
        key = json.dumps(v.sig, sort_keys=True)
        if key not in sig_cache:
            sig_cache[key] = signals(st, m, B, v.sig, other)
        return sig_cache[key]

    base = Engine(m)
    results = {}
    for v in st.variants:
        S = sigs_for(v)
        ex = exits_for(v, B)
        trades, rej = run_book(base, S, ex, st.limits, k_end, st.sid, v.tag)
        results[v.tag] = trades
        log["variants"][v.tag] = {"signals": len(S), "trades": len(trades), "rejected": rej,
                                  "setups": {k: int(n) for k, n in zip(*np.unique([s.setup for s in S], return_counts=True))} if S else {},
                                  "sig_params": v.sig, "exits": {k: v_ for k, v_ in v.exits.items()}}
    # choose on development + validation only
    dv = {tag: [t for t in tr if t.split in ("dev", "val")] for tag, tr in results.items()}
    scores = {tag: (metrics(tr)["mean_r"] if metrics(tr)["n"] >= 30 else None) for tag, tr in dv.items()}
    eligible = {k: s for k, s in scores.items() if s is not None}
    chosen = max(eligible, key=lambda k: (eligible[k], k == "V0")) if eligible else "V0"
    log["selection"] = {"rule": "highest dev+val net mean R with >= 30 trades; tie -> V0",
                        "dev_val_mean_r": scores, "chosen": chosen}
    keep = ["V0"] + ([chosen] if chosen != "V0" else [])
    for tag, tr in results.items():
        visible = tr if tag in keep else [t for t in tr if t.split != "hold"]
        write_trades(RES / "trades" / f"{st.sid}_{mname}_{tag}.csv.gz", visible)
        entry = log["variants"][tag]
        for sp in ("dev", "val"):
            entry[sp] = metrics([t for t in tr if t.split == sp])
        entry["dev_val"] = metrics(dv[tag])
        if tag in keep:
            entry["hold"] = metrics([t for t in tr if t.split == "hold"])
            entry["all"] = metrics(tr)
            entry["by_year"] = by_year(tr)
            entry["post_publication"] = metrics([t for t in tr if t.date >= st.first_upload])
            if mname == "NIFTY":
                entry["inr_10_lakh_all"] = inr_account(tr, m)
                entry["inr_10_lakh_hold"] = inr_account([t for t in tr if t.split == "hold"], m)
            (RES / "equity").mkdir(parents=True, exist_ok=True)
            with gzip.open(RES / "equity" / f"{st.sid}_{mname}_{tag}.csv.gz", "wt", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["date", "split", "r_net", "equity_1pct_risk"])
                w.writerows(equity_rows(tr))
    # robustness on V0 and the chosen variant
    rob = {}
    tf_main = st.base_sig.get("tf", st.tfs[0])
    for tag in keep:
        v = next(x for x in st.variants if x.tag == tag)
        S = sigs_for(v)
        ex = exits_for(v, B)
        runs = {"gross": Engine(m, 0, 0, 0), "costs_x2": Engine(m, 2, 2, 2), "slippage_x3": Engine(m, 1, 3, 1),
                "delay_1min": Engine(m, entry_delay=1), "delay_1bar": Engine(m, entry_delay=v.sig.get("tf", tf_main))}
        out = {}
        for name, eng in runs.items():
            tr, _ = run_book(eng, S, ex, st.limits, k_end, st.sid, tag)
            out[name] = {sp: metrics([t for t in tr if t.split in sps]) for sp, sps in (("dev_val", ("dev", "val")), ("hold", ("hold",)))}
        if ex.target_r is not None:
            for dlt in (-0.5, 0.5):
                ex2 = replace(ex, target_r=ex.target_r + dlt)
                tr, _ = run_book(base, S, ex2, st.limits, k_end, st.sid, tag)
                out[f"target_{ex.target_r + dlt:g}R"] = {sp: metrics([t for t in tr if t.split in sps]) for sp, sps in (("dev_val", ("dev", "val")), ("hold", ("hold",)))}
        rob[tag] = {k: {sp: {kk: vv for kk, vv in mm.items() if kk in ("n", "mean_r", "t", "profit_factor", "max_dd_pct")} for sp, mm in d.items()} for k, d in out.items()}
    log["robustness"] = rob
    # walk-forward: each year trades the variant with the best mean R over all prior years
    years = sorted({t.date[:4] for tr in results.values() for t in tr})
    wf, picks = [], {}
    for i, y in enumerate(years):
        if i < 3:
            continue
        prior = {tag: [t.r_net for t in tr if t.date[:4] < y and not t.excluded] for tag, tr in results.items()}
        prior = {k: v for k, v in prior.items() if len(v) >= 30}
        if not prior:
            continue
        pick = max(prior, key=lambda k: (np.mean(prior[k]), k == "V0"))
        picks[y] = pick
        wf += [t for t in results[pick] if t.date[:4] == y]
    log["walk_forward"] = {"picks": picks, "oos": metrics(wf),
                           "oos_hold_years": metrics([t for t in wf if t.split == "hold"])}
    log["seconds"] = round(time.time() - t_start, 1)
    (RES / "runs").mkdir(parents=True, exist_ok=True)
    (RES / "runs" / f"{st.sid}_{mname}.json").write_text(json.dumps(log, indent=1, default=str))
    return log


# ── study level ───────────────────────────────────────────────────────────────────────

def holm(pvals: dict) -> dict:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    k = len(items)
    out, running = {}, 0.0
    for i, (key, p) in enumerate(items):
        adj = min(1.0, (k - i) * p)
        running = max(running, adj)
        out[key] = running
    return out


def one_sided_p(t: float, n: int) -> float:
    from math import erf, sqrt
    if not (isinstance(t, float) or isinstance(t, int)) or not math.isfinite(t) or n < 2:
        return 1.0
    return 0.5 * (1 - erf(t / sqrt(2)))      # normal approximation (n >= 30 in every gated test)


def summarize():
    runs = [json.loads(p.read_text()) for p in sorted((RES / "runs").glob("*.json"))]
    tests = {}
    for r in runs:
        for tag in {"V0", r["selection"]["chosen"]}:
            h = r["variants"][tag].get("hold", {"n": 0})
            if h.get("n", 0) >= 2:
                tests[f'{r["strategy"]}|{r["market"]}|{tag}'] = one_sided_p(h.get("t", float("nan")), h["n"])
    adj = holm(tests)
    rows = []
    for r in runs:
        chosen = r["selection"]["chosen"]
        for tag in dict.fromkeys(["V0", chosen]):
            v = r["variants"][tag]
            h, dv = v.get("hold", {"n": 0}), v["dev_val"]
            d_, va = v["dev"], v["val"]
            rb = r["robustness"].get(tag, {})
            key = f'{r["strategy"]}|{r["market"]}|{tag}'
            n_total = (v.get("all") or {}).get("n", 0)
            gates = {
                "hold_t>=2": h.get("n", 0) > 1 and h.get("mean_r", -1) > 0 and h.get("t", 0) >= 2.0,
                "holm_p<0.05": adj.get(key, 1.0) < 0.05,
                "dev_and_val_positive": d_.get("mean_r", -1) > 0 and va.get("mean_r", -1) > 0,
                "hold_n>=50": h.get("n", 0) >= 50,
                "hold_costs_x2_positive": rb.get("costs_x2", {}).get("hold", {}).get("mean_r", -1) > 0,
                "hold_delay_1min_positive": rb.get("delay_1min", {}).get("hold", {}).get("mean_r", -1) > 0,
                "hold_top5_share<0.5": (h.get("top5_share_of_net") or 9) < 0.5,
                "hold_max_dd<20pct": h.get("max_dd_pct", 100) < 20,
            }
            if n_total < 30 or h.get("n", 0) == 0:
                cls = "unable to evaluate"
            elif all(gates.values()):
                cls = "candidate for paper trading"
            elif h.get("mean_r", -1) > 0 and dv.get("mean_r", -1) > 0:
                cls = "needs more evidence"
            else:
                cls = "not supported"
            rows.append({"strategy": r["strategy"], "market": r["market"], "variant": tag, "chosen": tag == chosen,
                         "class": cls, "holm_p": round(adj.get(key, 1.0), 4), "gates": gates,
                         "dev": {k: d_.get(k) for k in ("n", "mean_r", "t")}, "val": {k: va.get(k) for k in ("n", "mean_r", "t")},
                         "hold": {k: h.get(k) for k in ("n", "mean_r", "mean_r_gross", "t", "win_rate", "profit_factor", "max_dd_pct", "cagr_pct", "top5_share_of_net")},
                         "post_publication": {k: v.get("post_publication", {}).get(k) for k in ("n", "mean_r", "t", "first")},
                         "walk_forward_oos": {k: r["walk_forward"]["oos"].get(k) for k in ("n", "mean_r", "t")},
                         "inr_10_lakh_hold": v.get("inr_10_lakh_hold")})
    out = {"prereg_sha256": prereg_hash(), "holdout_tests": len(tests), "rows": rows}
    (RES / "summary.json").write_text(json.dumps(out, indent=1, default=str))
    for x in rows:
        print(f'{x["strategy"]:6} {x["market"]:9} {x["variant"]:3}{"*" if x["chosen"] else " "} '
              f'dev {x["dev"]["mean_r"]!s:>8} val {x["val"]["mean_r"]!s:>8} hold {x["hold"].get("mean_r")!s:>8} '
              f'(n {x["hold"].get("n")!s:>4}, t {x["hold"].get("t")!s:>6}) -> {x["class"]}')


def main(argv):
    if "--summary" in argv:
        summarize()
        return
    want = [a for a in argv if a.startswith("BB-")] or list(STRATEGIES)
    for sid in want:
        st = STRATEGIES[sid]
        for mk in st.markets:
            t0 = time.time()
            try:
                lg = run_one(st, mk)
            except Exception as e:  # noqa: BLE001
                print(f"{sid} {mk}: FAILED {type(e).__name__}: {e}", flush=True)
                raise
            v0 = lg["variants"]["V0"]
            ch = lg["selection"]["chosen"]
            print(f"{sid} {mk}: signals {v0['signals']} trades {v0['trades']} | dev+val V0 mean R "
                  f"{v0['dev_val'].get('mean_r')} (n {v0['dev_val'].get('n')}) | chosen {ch} | {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1:])
