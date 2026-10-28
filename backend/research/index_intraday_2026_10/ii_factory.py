"""Index intraday research, round F: the Strategy Factory's 546 strategies traded intraday on the indexes.

    python backend/research/index_intraday_2026_10/ii_factory.py [--indexes NIFTY,BANKNIFTY] [--workers 5]
                                                                 [--years 2019-2023] [--pilot]

The strategies are the factory's own (69 hypotheses x 8 timeframes), fixed before this round ran —
nothing is tuned on index data. The rules are app/services/index_intraday/factory.py (intraday only,
the factory's evaluate(), the module's fills and costs).

WINDOW  2019-01-01 .. 2023-12-31: in-sample 2019-21, out-of-sample 2022-23 (the research's validation
        years). It starts in 2019 because the factory's volume rules read the tracking ETF's volume and
        the ETF history starts there. The 2024-26 HOLDOUT IS NEVER USED: rows stamped from
        2024-01-01 are dropped as each file is read, before anything is built from them.
GRADE   the factory's own 1-5 grading on this module's numbers (factory.grade); the luck bar is the
        deflated Sharpe over every strategy with 20+ trades on that index.

Writes app/services/index_intraday/factory_catalog.json.gz (what the module serves) and
factory_registry.csv beside this script (one row per trial).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from multiprocessing import get_context
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for _p in (ROOT / "strategy-service", ROOT / "shared", ROOT / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("IDX1M_DIR", str(HERE / "data" / "1m"))

import numpy as np  # noqa: E402

START, IS_END, END = date(2019, 1, 1), date(2021, 12, 31), date(2023, 12, 31)
HOLDOUT_FROM = int(datetime(2024, 1, 1, tzinfo=timezone(timedelta(hours=5, minutes=30))).timestamp())
WARMUP_DAYS = 430                   # calendar days before a year: ~290 sessions (the 1d window is 230)
REASONS = ("stop", "target", "trail", "square_off", "signal", "time")
TRADE = np.dtype([("day", "i4"), ("side", "i1"), ("entry", "i2"), ("exit", "i2"), ("reason", "i1"),
                  ("gross", "f4"), ("net", "f4")])
OUT = ROOT / "backend" / "app" / "services" / "index_intraday" / "factory_catalog.json.gz"
KEEP = ("trades", "trades_per_day", "win_rate", "mean_net_bp", "mean_gross_bp", "t_trade", "profit_factor",
        "total_bp", "ann_bp", "sharpe", "max_dd_bp", "months_positive", "years_positive", "years", "sr_daily",
        "skew", "kurt")


def _load(name: str, since: date, until: date):
    from app.services.index_intraday import data as D
    rows = D._read(name, since, until)
    rows = rows[rows[:, 0] < HOLDOUT_FROM]                  # the holdout is never used
    d = D._build(name, rows)
    keep = (d.dates >= np.datetime64(since.isoformat())) & (d.dates <= np.datetime64(until.isoformat()))
    return D.Days(d.name, d.dates[keep], d.o[keep], d.h[keep], d.l[keep], d.c[keep], d.v[keep], d.quality)


def task(args):
    """One (index, year, strategies): every trade, per strategy, as a compact array."""
    index, year, sf_ids = args
    from app.services.index_intraday import factory as FX
    from app.services.index_intraday.costs import ROUTE, costs_for
    from app.services.strategy_factory.catalog import FACTORY_BY_ID
    t0 = time.time()
    y0, y1 = date(year, 1, 1), min(date(year, 12, 31), END)
    d = _load(index, y0 - timedelta(days=WARMUP_DAYS), y1)
    etf_name = ROUTE[index][0]
    etf = None
    if etf_name:
        try:
            etf = _load(etf_name, y0 - timedelta(days=WARMUP_DAYS), y1)
        except FileNotFoundError:
            etf = None
    assert d.dates.max() <= np.datetime64(END.isoformat())
    lo = int(np.searchsorted(d.dates, np.datetime64(y0.isoformat())))
    costs = costs_for(index)
    ctx = FX._Ctx(d, etf, lo)
    out = {}
    for sf in sf_ids:
        s = FACTORY_BY_ID[sf]
        rej: dict = {}
        tr = FX.run(s, d, etf, lo, costs, ctx=ctx, rejections=rej)
        a = np.zeros(len(tr), TRADE)
        for k, t in enumerate(tr):
            a[k] = (int(d.dates[lo + t.day].astype("datetime64[D]").astype(np.int64)), t.side, t.entry_min,
                    t.exit_min, REASONS.index(t.reason), t.gross_bp, t.net_bp)
        out[sf] = (a, rej)
    days = d.dates[lo:].astype("datetime64[D]").astype(np.int64)
    return index, year, out, days, round(time.time() - t0, 1)


def _finite(v):
    if isinstance(v, float):
        return None if not math.isfinite(v) else round(v, 4)
    return v


def summarize(arr: np.ndarray, days: np.ndarray) -> dict:
    """engine.summarize on the trades of `arr` inside the day list `days` (day ordinals)."""
    from app.services.index_intraday.engine import Trade, summarize as S
    if not len(arr):
        return {"trades": 0}
    pos = np.searchsorted(days, arr["day"])
    trades = [Trade(int(p), int(t["side"]), int(t["entry"]), 0.0, int(t["exit"]), 0.0, REASONS[int(t["reason"])],
                    float(t["gross"]), float(t["net"])) for p, t in zip(pos, arr)]
    st = S(trades, len(days), days.astype("datetime64[D]"))
    st.pop("reasons", None)
    return {k: _finite(st.get(k)) for k in KEEP}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexes", default="NIFTY,BANKNIFTY")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--years", default="2019-2023")
    ap.add_argument("--pilot", action="store_true", help="3 strategies a timeframe, one year, no catalogue written")
    ap.add_argument("--recipes", default="", help="only these factory recipes (keys, comma-separated)")
    ap.add_argument("--merge", action="store_true", help="replace these strategies in the existing catalogue")
    a = ap.parse_args()
    from app.services.index_intraday import factory as FX
    from app.services.index_intraday.costs import ROUTE, costs_for
    from app.services.index_intraday.engine import deflated_sr
    from app.services.strategy_factory.catalog import FACTORY_CATALOG

    indexes = a.indexes.split(",")
    y_from, y_to = (int(x) for x in a.years.split("-"))
    years = list(range(y_from, y_to + 1))
    only = {k for k in a.recipes.split(",") if k}
    by_tf: dict[str, list[str]] = {}
    for s in FACTORY_CATALOG:
        if only and FX.RECIPE_OF[s.strategy_id].key not in only:
            continue
        by_tf.setdefault(s.timeframe, []).append(s.strategy_id)
    run_ids = {sid for ids in by_tf.values() for sid in ids}
    if a.pilot:
        by_tf = {tf: ids[:3] for tf, ids in by_tf.items()}
        years = years[-1:]
    groups = []
    for tf, ids in by_tf.items():                      # the 1m strategies cost ~70% of the run: split them
        n = min(3, len(ids)) if tf == "1m" and not a.pilot else 1
        for g in range(n):
            groups.append(ids[g::n])
    tasks = [(ix, y, g) for ix in indexes for y in years for g in groups]
    tasks.sort(key=lambda t: -(70 if FX.FACTORY_BY_ID[t[2][0]].timeframe == "1m" else
                               17 if FX.FACTORY_BY_ID[t[2][0]].timeframe == "5m" else 5))
    print(f"{len(tasks)} tasks: {len(indexes)} indexes x {len(years)} years x {len(groups)} groups; "
          f"{a.workers} workers", flush=True)
    t0 = time.time()
    trades: dict[tuple, list] = {}
    rejections: dict[tuple, dict] = {}
    days: dict[str, set] = {ix: set() for ix in indexes}
    with get_context("spawn").Pool(a.workers, maxtasksperchild=4) as pool:
        for k, (ix, y, out, dlist, secs) in enumerate(pool.imap_unordered(task, tasks), 1):
            days[ix].update(int(x) for x in dlist)
            for sf, (arr, rej) in out.items():
                trades.setdefault((ix, sf), []).append(arr)
                agg = rejections.setdefault((ix, sf), {})
                for st, n in rej.items():
                    agg[st] = agg.get(st, 0) + n
            print(f"[{k}/{len(tasks)}] {ix} {y} {FX.FACTORY_BY_ID[next(iter(out))].timeframe if out else ''} "
                  f"x{len(out)} {secs}s  (elapsed {time.time() - t0:.0f}s)", flush=True)
    if a.pilot:
        for (ix, sf), parts in sorted(trades.items()):
            arr = np.concatenate(parts)
            print(ix, sf, FX.FACTORY_BY_ID[sf].name, "trades", len(arr), "net bp", round(float(arr["net"].sum()), 1),
                  rejections.get((ix, sf)))
        return

    rows, registry = [], []
    is_end = np.datetime64(IS_END.isoformat()).astype(np.int64)
    old = {}
    if a.merge and OUT.exists():
        with gzip.open(OUT, "rb") as f:
            old = {e["id"]: e for e in json.loads(f.read().decode("utf-8"))["strategies"]}
    for ix in indexes:
        dall = np.array(sorted(days[ix]), dtype=np.int64)
        d_is, d_oos = dall[dall <= is_end], dall[dall > is_end]
        per = []
        for s in FACTORY_CATALOG:
            if s.strategy_id not in run_ids:
                kept = old.get(FX.sid_for(s.strategy_id, ix))
                if kept is None:
                    raise SystemExit(f"--merge: {s.strategy_id} on {ix} is in neither this run nor the catalogue")
                per.append(kept)
                continue
            arr = np.concatenate(trades.get((ix, s.strategy_id), [np.zeros(0, TRADE)]))
            arr = arr[np.argsort(arr["day"], kind="stable")]
            st_all = summarize(arr, dall)
            st_is = summarize(arr[arr["day"] <= is_end], d_is)
            st_oos = summarize(arr[arr["day"] > is_end], d_oos)
            g, why = FX.grade(st_all, st_oos) if st_all.get("trades") else (1, ["no trade in 2019-23"])
            daily = np.zeros(len(dall))
            if len(arr):
                np.add.at(daily, np.searchsorted(dall, arr["day"]), arr["net"].astype(float))
            months = dall.astype("datetime64[D]").astype("datetime64[M]")
            mk = np.unique(months)
            monthly = [round(float(daily[months == m].sum()), 1) for m in mk]
            exits = {REASONS[r]: int((arr["reason"] == r).sum()) for r in range(len(REASONS)) if (arr["reason"] == r).any()}
            entry = {"id": FX.sid_for(s.strategy_id, ix), "index": ix, "etf": ROUTE[ix][0], **FX.describe(s),
                     "status": "Backtested", "grade": g, "grade_reasons": why,
                     "failed": why[0] if g <= 2 else ("graded by the Strategy Factory's rules; not put through this "
                                                       "module's Validated protocol (luck bar, ETF track, walk-forward)"),
                     "all": st_all, "is": st_is, "oos": st_oos, "exits": exits,
                     "rejections": rejections.get((ix, s.strategy_id), {}),
                     "monthly": {"start": str(mk[0]) if len(mk) else None, "bp": monthly}}
            per.append(entry)
        enough = [e for e in per if (e["all"].get("trades") or 0) >= FX.MIN_TRADES and e["all"].get("sr_daily") is not None]
        srs = np.array([e["all"]["sr_daily"] for e in enough])
        in_bar = {id(e) for e in enough}
        sr_var = float(srs.var(ddof=1)) if len(srs) > 1 else 0.0
        for e in per:
            al = e["all"]
            e["dsr"] = None
            if id(e) in in_bar and len(enough) > 1:
                v = deflated_sr(al["sr_daily"], len(dall), al["skew"] or 0.0, al["kurt"] or 3.0, sr_var, len(enough))
                e["dsr"] = None if not math.isfinite(v) else round(v, 4)
            registry.append({"id": e["id"], "index": ix, "timeframe": e["timeframe"], "family": e["family"],
                             "name": e["name"], "trades": al.get("trades"), "total_bp": al.get("total_bp"),
                             "sharpe": al.get("sharpe"), "oos_total_bp": e["oos"].get("total_bp"), "grade": e["grade"],
                             "dsr": e["dsr"]})
        rows += per
        print(f"{ix}: {len(enough)} strategies with {FX.MIN_TRADES}+ trades, luck-bar variance {sr_var:.6f}", flush=True)

    if a.merge and old:
        done = {r["id"] for r in rows}
        rows += [e for e in old.values() if e["id"] not in done]
        indexes = sorted({r["index"] for r in rows}, key=lambda x: (x != "NIFTY", x))
    counts = {str(g): sum(1 for r in rows if r["grade"] == g) for g in range(1, 6)}
    doc = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "round": "F — the Strategy Factory's strategies, intraday",
        "indexes": indexes, "strategies_per_index": len(FACTORY_CATALOG), "trials": len(rows),
        "periods": {"in_sample": ["2019-01-01", "2021-12-31"], "out_of_sample": ["2022-01-01", "2023-12-31"],
                    "holdout": "2024-01-01 onward — never used"},
        "costs": {ix: {"fee_rt_bp": round(costs_for(ix).fee_rt_bp, 3), "slip_bp_a_side": costs_for(ix).slip_bp,
                       "etf": ROUTE[ix][0]} for ix in indexes},
        "grade_counts": counts, "seconds": round(time.time() - t0),
        "strategies": rows,
    }
    raw = json.dumps(doc, separators=(",", ":"), allow_nan=False).encode()
    with gzip.open(OUT, "wb", compresslevel=9) as f:
        f.write(raw)
    with open(HERE / "factory_registry.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(registry[0]))
        w.writeheader()
        w.writerows(registry)
    print(f"wrote {OUT.name} ({OUT.stat().st_size / 1e6:.2f} MB): {len(rows)} trials, grades {counts}, "
          f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
