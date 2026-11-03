"""Run the tournament's backtest (code from a git commit) over a date range on exported data.

    python runner.py --name live50 --start 2026-10-06 --slot 1000000 --live-rules --live-universe
    python runner.py --name y2 --start 2024-11-04 --live-rules --features six

Outputs in DATA/runs/<name>/:
  summary.json          the backtest's own summary and per-strategy metrics
  trades.jsonl.gz       every accepted trade (the backtest's tuple format)
  features.jsonl.gz     with --features: one row per signal of those strategies, taken or not —
                        point-in-time features + the simulated outcome (features.py)
Read-only: the database stand-ins serve exports only (stubpkg.py).
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import gzip
import json
import logging
import pathlib
import sys
import time
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stubpkg import DATA, activate, build  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--start", required=True, help="first IST session date (YYYY-MM-DD)")
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--slot", type=float, default=1_000_000.0, help="rupees per position (capital = 5 x slot)")
    ap.add_argument("--live-rules", action="store_true")
    ap.add_argument("--live-universe", action="store_true", help="each day's STORED universe where one exists")
    ap.add_argument("--features", default="", help="'six' or comma-separated strategy ids")
    a = ap.parse_args()

    pkg = build(a.commit)
    activate(pkg)
    import features as F
    from app.services import intraday_v2_backtest as bt

    bt.SLOT, bt.CAPITAL = a.slot, a.slot * bt.SLOTS
    out = DATA / "runs" / a.name
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    taken: dict = {}
    _accept = bt.accept

    def accept(rows):
        r = _accept(rows)
        taken.update(r)
        return r
    bt.accept = accept
    _live = bt._live_accept

    def live_accept(con, meta):
        t, s = _live(con, meta)
        taken.update(t)
        return t, s
    bt._live_accept = live_accept

    want = set(F.SIX if a.features == "six" else [x for x in a.features.split(",") if x])
    fw = gzip.open(out / "features.jsonl.gz", "wt", encoding="utf-8") if want else None
    n_feat = [0]
    if want:
        def on_signal(spec, sig, ctx, t, tr):
            if spec.strategy_id in want:
                fw.write(json.dumps(F.extract(spec, sig, ctx, t, tr)) + "\n")
                n_feat[0] += 1
        bt.replay_symbol = functools.partial(bt.replay_symbol, on_signal=on_signal)

    if a.live_universe:
        stored = {(date.fromisoformat(u["_id"]) - date(1970, 1, 1)).days: set(u["members"])
                  for u in json.load(open(DATA / "exports" / "universe_days.json", encoding="utf-8"))}
        _pit = bt.pit_universe

        async def pit_live(start, end, need, size=200):
            rebuilt = await _pit(start, end, need, size)
            return {dk: stored.get(dk, rebuilt.get(dk, set())) for dk in need}
        bt.pit_universe = pit_live

    days_back = (datetime.now(IST).date() - date.fromisoformat(a.start)).days
    t0 = time.time()
    summary = asyncio.run(bt.run(days_back, None, pit=True, save=False, live_rules=a.live_rules))
    results = summary.pop("results")
    if fw:
        fw.close()
    with gzip.open(out / "trades.jsonl.gz", "wt", encoding="utf-8") as f:
        for sid, rows in taken.items():
            if not sid.endswith(bt.OPT_SUFFIX):
                for r in rows:
                    f.write(json.dumps(list(r)) + "\n")
    meta = {"args": vars(a), "commit_pkg": pkg.name, "elapsed_s": round(time.time() - t0, 1),
            "feature_rows": n_feat[0], "capital_per_strategy": bt.CAPITAL}
    json.dump({"meta": meta, "summary": {k: v for k, v in summary.items() if k != "created_at"},
               "results": results}, open(out / "summary.json", "w", encoding="utf-8"), default=str, indent=1)
    print(json.dumps(meta, default=str))


if __name__ == "__main__":
    main()
