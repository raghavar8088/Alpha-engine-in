"""Load a sweep into the desk: the universe, every pair's backtest, and one account per pair.

    python -m app.services.crypto_trading.importer --universe U.json --library L.json --results R.jsonl [--no-start]

`--library` is the strategy library exactly as the sweep read it (`sweep.py --dump-library`), so the
page shows the rules that were graded even where this process imports a smaller registry. The
results file may be gzipped (R.jsonl.gz).
Idempotent. Backtests are upserted by pair id. An account is created once, with $10,000; after that
an import changes only its grade, status and eligibility - never its money, its trades or an open
position. A pair that stops being eligible takes no new entries, and a position it holds is still
managed to its exit. The first import starts the desk (it auto-trades); later ones leave its
running / paused / stopped state alone, and --no-start leaves a new desk stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import sys
from datetime import datetime

from pymongo import UpdateOne

from . import store
from .config import ACCOUNT_CAPITAL_USD, UTC
from .engine import STATE_ID, fresh_account_fields

TRADES_KEPT = 40          # per pair, the latest backtest trades stored for the pair's page
SUMMARY = ("trades", "net_pnl", "profit_factor", "win_rate", "max_drawdown_pct", "return_pct", "sharpe", "expectancy")


def _summary(m: dict | None) -> dict:
    return {k: (m or {}).get(k) for k in SUMMARY}


async def run(universe_path: str, library_path: str, results_path: str, start: bool = True) -> dict:
    await store.ensure_indexes()
    uni = json.load(open(universe_path, encoding="utf-8"))
    rows = json.load(open(library_path, encoding="utf-8"))
    now = datetime.now(UTC)
    await store.LIBRARY.bulk_write([UpdateOne({"_id": r["strategy_id"]}, {"$set": {**r, "imported_at": now}}, upsert=True)
                                    for r in rows], ordered=False)
    await store.LIBRARY.delete_many({"imported_at": {"$lt": now}})       # a strategy no longer in the library
    await store.UNIVERSE.replace_one({"_id": "current"}, {**uni, "_id": "current", "imported_at": now}, upsert=True)
    await store.UNIVERSE.replace_one({"_id": f"selection@{uni['selected_at']}"},
                                     {**uni, "_id": f"selection@{uni['selected_at']}", "imported_at": now}, upsert=True)

    counts: dict[str, int] = {}
    meta: dict = {}
    bt_ops, acc_ops = [], []
    n = 0

    async def flush() -> None:
        if bt_ops:
            await store.BACKTESTS.bulk_write(bt_ops, ordered=False)
            bt_ops.clear()
        if acc_ops:
            await store.ACCOUNTS.bulk_write(acc_ops, ordered=False)
            acc_ops.clear()

    opener = gzip.open if results_path.endswith(".gz") else open
    with opener(results_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            n += 1
            counts[d["status"]] = counts.get(d["status"], 0) + 1
            if not meta and d.get("libraries"):
                meta = {"libraries": d.get("libraries"), "code_version": d.get("code_version"), "run_on": d.get("run_on")}
            if d.get("trades_sample"):
                d["trades_sample"] = d["trades_sample"][-TRADES_KEPT:]
            d["_id"] = d["pair_id"]
            bt_ops.append(UpdateOne({"_id": d["_id"]}, {"$set": {**d, "imported_at": now}}, upsert=True))
            ident = {k: d.get(k) for k in ("strategy_id", "library", "base_id", "name", "family", "timeframe", "symbol",
                                           "coin")}
            acc_ops.append(UpdateOne({"_id": d["pair_id"]}, {
                "$setOnInsert": {**fresh_account_fields(None), **ident, "pair_id": d["pair_id"],
                                 "capital": ACCOUNT_CAPITAL_USD, "created_at": now},
                "$set": {"status": d["status"], "status_reason": d.get("status_reason"), "grade": d.get("grade"),
                         "eligible": d["status"] == "eligible", "unit_contracts": d.get("unit_contracts") or 1,
                         "backtest": {**_summary(d.get("overall")), "oos": _summary(d.get("out_of_sample")),
                                      "funding": d.get("funding_total"), "window_start": d.get("window_start"),
                                      "window_end": d.get("window_end"), "run_at": d.get("run_at")},
                         "imported_at": now}}, upsert=True))
            if len(bt_ops) >= 500:
                await flush()
    await flush()

    sweep = {"_id": "sweep", "imported_at": now, "results_file": results_path, "pairs": n, "counts": counts,
             "strategies": len(rows), "universe_selected_at": uni.get("selected_at"), **meta}
    await store.STATE.replace_one({"_id": "sweep"}, sweep, upsert=True)
    st = await store.STATE.find_one({"_id": STATE_ID})
    if st is None or not st.get("status"):
        await store.STATE.update_one({"_id": STATE_ID}, {"$set": {
            "status": "running" if start else "stopped", "since": now, "by": "importer",
            "last_action": "first import"}}, upsert=True)
    return {"pairs": n, "counts": counts, "accounts": await store.ACCOUNTS.count_documents({}),
            "eligible": await store.ACCOUNTS.count_documents({"eligible": True}),
            "desk": (await store.STATE.find_one({"_id": STATE_ID}) or {}).get("status"), "store": store.store_name()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--universe", required=True)
    ap.add_argument("--library", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--no-start", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(asyncio.run(run(a.universe, a.library, a.results, start=not a.no_start)), default=str, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
