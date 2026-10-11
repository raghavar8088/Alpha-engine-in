"""Export the stored MCX gold bars (GOLD, GOLDM — every timeframe, every contract). READ-ONLY.

    docker cp gd_export_mcx.py alpha-engine-backend-1:/tmp/
    docker exec -e PYTHONPATH=/app/backend alpha-engine-backend-1 python /tmp/gd_export_mcx.py

Writes /tmp/gd_mcx_bars.csv.gz: symbol, timeframe, expiry, ts (UTC epoch of the bar open), OHLCV.
The bar store is keyed by contract since 2026-10-03, so each contract's history is its own.
"""

import asyncio
import csv
import gzip
from datetime import timezone

from app.core.db import commodity_bars_collection as CB


async def main():
    n = 0
    with gzip.open("/tmp/gd_mcx_bars.csv.gz", "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "timeframe", "expiry", "ts", "open", "high", "low", "close", "volume"])
        async for d in CB.find({"symbol": {"$in": ["GOLD", "GOLDM"]}},
                               {"_id": 0, "symbol": 1, "timeframe": 1, "expiry": 1, "ts": 1,
                                "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}):
            ts = d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=timezone.utc)
            w.writerow([d["symbol"], d["timeframe"], d.get("expiry"), int(ts.timestamp()),
                        d["open"], d["high"], d["low"], d["close"], d.get("volume") or 0])
            n += 1
    print("rows", n)


asyncio.run(main())
