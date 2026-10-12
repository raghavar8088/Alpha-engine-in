"""Index intraday research, stage 0: 1-minute history from Angel One, run ON THE SERVER.

    docker exec -d alpha-engine-backend-1 sh -c \
      "PYTHONPATH=/app/backend python /data/intraday/idx1m/ii_fetch.py >> /data/intraday/idx1m/fetch.log 2>&1"

Angel's candle endpoint (licensed broker data, the app's own feed) serves ONE_MINUTE bars 30
days a request; measured 2026-10-11 it holds the NSE and BSE indexes complete from 2016, NIFTY
MIDCAP SELECT from its 2022 launch, and the index ETFs complete from 2020 (thin before). Every
call goes through the app's shared candle pacer as a BULK caller, so it yields to live desks.

Resumable: one gzip CSV per (symbol, 30-day window) under /data/intraday/idx1m/<SYMBOL>/;
an existing file is never re-fetched. Rows: epoch seconds of the minute's start, O, H, L, C, V.
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import json
import os
import time
from datetime import date, datetime, timedelta

ROOT = os.getenv("IDX1M_DIR", "/data/intraday/idx1m")
END = date.fromisoformat(os.getenv("IDX1M_END", "2026-10-09"))

# (exchange, token, name, first day wanted)
SYMBOLS = [
    ("NSE", "99926000", "NIFTY", "2016-01-01"),
    ("NSE", "99926009", "BANKNIFTY", "2016-01-01"),
    ("BSE", "99919000", "SENSEX", "2016-01-01"),
    ("NSE", "99926037", "FINNIFTY", "2016-01-01"),
    ("NSE", "99926013", "NIFTYNXT50", "2016-01-01"),
    ("NSE", "99926012", "NIFTY100", "2016-01-01"),
    ("BSE", "99919012", "BANKEX", "2016-01-01"),
    ("NSE", "99926074", "MIDCPNIFTY", "2022-01-01"),
    ("NSE", "99926017", "INDIAVIX", "2016-01-01"),
    ("NSE", "10576", "NIFTYBEES", "2019-01-01"),
    ("NSE", "11439", "BANKBEES", "2019-01-01"),
    ("NSE", "10939", "JUNIORBEES", "2019-01-01"),
    ("NSE", "12578", "FINIETF", "2020-01-01"),
    ("NSE", "17702", "MIDSELIETF", "2022-01-01"),
    ("NSE", "29577", "NIF100BEES", "2020-01-01"),
    ("NSE", "4378", "SENSEXIETF", "2020-01-01"),
]
WINDOW_DAYS = 30


def _epoch(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp).timestamp())


async def fetch_symbol(exch: str, tok: str, name: str, first: str, client) -> dict:
    out_dir = os.path.join(ROOT, name)
    os.makedirs(out_dir, exist_ok=True)
    d = date.fromisoformat(first)
    stats = {"windows": 0, "fetched": 0, "rows": 0, "errors": 0, "empty": 0}
    while d <= END:
        e = min(d + timedelta(days=WINDOW_DAYS - 1), END)
        path = os.path.join(out_dir, f"{d.isoformat()}.csv.gz")
        stats["windows"] += 1
        if os.path.exists(path):
            d = e + timedelta(days=1)
            continue
        rows = None
        for attempt in range(4):
            try:
                rows = await client.candles(exch, tok, "1", f"{d} 09:15", f"{e} 15:30", bulk=True)
                break
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                print(f"{name} {d}: attempt {attempt + 1} failed: {str(exc)[:120]}", flush=True)
                await asyncio.sleep(5 * (attempt + 1))
        if rows is None:
            d = e + timedelta(days=1)            # leave the window missing; a rerun retries it
            continue
        tmp = path + ".part"
        with gzip.open(tmp, "wt", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts", "open", "high", "low", "close", "volume"])
            for r in rows:
                try:
                    w.writerow([_epoch(r[0]), r[1], r[2], r[3], r[4], r[5]])
                except Exception:  # noqa: BLE001 - one malformed row costs one row
                    continue
        os.replace(tmp, path)
        stats["fetched"] += 1
        stats["rows"] += len(rows)
        stats["empty"] += 0 if rows else 1
        d = e + timedelta(days=1)
    return stats


async def main() -> None:
    from app.services.angel_client import angel_client
    os.makedirs(ROOT, exist_ok=True)
    started = time.time()
    report = {}
    for exch, tok, name, first in SYMBOLS:
        s = await fetch_symbol(exch, tok, name, first, angel_client)
        report[name] = s
        print(f"{datetime.now():%H:%M:%S} {name}: {s} ({time.time() - started:.0f}s so far)", flush=True)
        with open(os.path.join(ROOT, "fetch_report.json"), "w") as f:
            json.dump({"at": datetime.now().isoformat(), "report": report}, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
