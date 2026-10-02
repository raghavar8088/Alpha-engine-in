"""Run the Buying Lab v2 over every registered option-buying strategy (U3 of the 2026-10-02
Pre-Live plan). A JOB, not part of the API process: replaying ~167 strategies over two years
takes minutes of CPU, which the web worker must not spend.

    docker run --rm ... alpha-engine-backend python -m app.services.buying_lab_job [--limit N]

Reads NIFTY 5m/15m and India VIX 15m from the intraday bar store; writes the full result to
DATA_DIR/backtests/buying_lab_<run>.json and a compact summary to Atlas `option_lab_runs`
(what the Pre-Live page shows, and what the daemon's basket mode trades from — only strategies
that PASSED, and passing still only makes them candidates for pre-registration).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone

from app.core.db import db
from app.services.intraday_store import DATA_DIR, read_file

runs = db["option_lab_runs"]


def _rows(sym: str, tf: str) -> list:
    b = read_file(sym, tf)
    return [[b.t[i], b.o[i], b.h[i], b.l[i], b.c[i]] for i in range(len(b))]


def run_sync(limit: int | None = None) -> dict:
    from options_service import buying_lab as L
    t0 = time.time()
    mk = L.Market(_rows("NIFTY", "5m"), _rows("NIFTY", "15m"), _rows("INDIAVIX", "15m"))
    pairs = L.buying_pairs()[:limit] if limit else L.buying_pairs()
    results = {}
    for n, (sid, tf) in enumerate(pairs):
        results[f"{sid}@{tf}"] = L.replay(mk, sid, tf)
        if n % 20 == 0:
            print(f"  {n + 1}/{len(pairs)} replayed ({time.time() - t0:.0f}s)", flush=True)
    ev = L.evaluate(results, mk.days)
    return {"run_id": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M"), "seconds": round(time.time() - t0),
            "data": {"from": str(L._kdate(mk.days[0])), "to": str(L._kdate(mk.days[-1])), "sessions": len(mk.days)},
            "pairs": len(pairs), **ev}


async def main(limit: int | None, save: bool) -> dict:
    out = await asyncio.to_thread(run_sync, limit)
    if save:
        os.makedirs(os.path.join(DATA_DIR, "backtests"), exist_ok=True)
        with open(os.path.join(DATA_DIR, "backtests", f"buying_lab_{out['run_id']}.json"), "w") as f:
            json.dump(out, f, default=str)
        compact = {k: out[k] for k in ("run_id", "seconds", "data", "pairs", "passed", "pbo", "trials", "gate", "luck", "model")}
        compact["rows"] = [{"key": r["key"], "explore": r["explore"], "holdout": r["holdout"], "dsr": r["dsr"],
                            "gate": r["gate"], "passed": r["passed"]} for r in out["rows"].values()]
        compact["created_at"] = datetime.now(timezone.utc)
        await runs.insert_one(compact)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    res = asyncio.run(main(a.limit, not a.no_save))
    print(json.dumps({k: res[k] for k in ("run_id", "seconds", "data", "pairs", "passed", "pbo", "trials", "luck")},
                     default=str, indent=1))
