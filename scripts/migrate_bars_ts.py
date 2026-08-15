"""Convert the 169,601 string-typed `ts` daily bars to real BSON dates.

WHY THIS IS NOT A ONE-LINE UPDATE. There is a UNIQUE index on (symbol, timeframe, ts),
and 209 symbols hold BOTH representations of the same bar — one written as a date by the
market-data service, one written as a string by a backend writer. Converting a string
whose instant already exists as a date violates that index, so every conversion has to
check first and DELETE the duplicate instead. The two rows describe the same candle from
the same source, so dropping the string copy loses nothing.

Runs symbol by symbol: the dedupe needs the set of instants a symbol already holds as
dates, and holding that for one symbol at a time keeps this inside an M0's memory.

Idempotent — a second run finds nothing left to convert.
"""

import asyncio
import sys
from datetime import datetime

sys.path.insert(0, "/app/backend")

from pymongo import DeleteOne, UpdateOne  # noqa: E402

from app.core.db import bars_collection  # noqa: E402

DRY_RUN = "--apply" not in sys.argv
BATCH = 500


async def main():
    print("DRY RUN — pass --apply to write\n" if DRY_RUN else "APPLYING\n")
    symbols = await bars_collection.distinct("symbol", {"ts": {"$type": "string"}})
    print(f"symbols carrying string bars: {len(symbols)}")

    conv = dup = bad = 0
    for i, sym in enumerate(symbols, 1):
        # instants this symbol already holds correctly, so duplicates can be spotted
        have: set[datetime] = set()
        async for d in bars_collection.find(
            {"symbol": sym, "ts": {"$type": "date"}}, {"ts": 1, "timeframe": 1}
        ):
            have.add((d["timeframe"], d["ts"].replace(tzinfo=None)))

        ops = []
        async for d in bars_collection.find(
            {"symbol": sym, "ts": {"$type": "string"}}, {"ts": 1, "timeframe": 1}
        ):
            try:
                parsed = datetime.fromisoformat(d["ts"])
            except (ValueError, TypeError):
                bad += 1
                continue
            key = (d["timeframe"], parsed.replace(tzinfo=None))
            if key in have:
                ops.append(DeleteOne({"_id": d["_id"]}))       # same bar already correct
                dup += 1
            else:
                ops.append(UpdateOne({"_id": d["_id"]}, {"$set": {"ts": parsed}}))
                have.add(key)                                   # guard duplicate strings
                conv += 1
            if len(ops) >= BATCH and not DRY_RUN:
                await bars_collection.bulk_write(ops, ordered=False)
                ops = []
        if ops and not DRY_RUN:
            await bars_collection.bulk_write(ops, ordered=False)
        if i % 50 == 0:
            print(f"  {i}/{len(symbols)} symbols · converted {conv} · deduped {dup}")

    print(f"\nconverted {conv} | deleted as duplicates {dup} | unparseable {bad}")
    if not DRY_RUN:
        left = await bars_collection.count_documents({"ts": {"$type": "string"}})
        dates = await bars_collection.count_documents({"timeframe": "1d", "ts": {"$type": "date"}})
        print(f"strings remaining: {left} | 1d date-typed bars now: {dates}")


asyncio.run(main())
