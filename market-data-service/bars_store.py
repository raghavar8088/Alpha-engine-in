"""Mongo storage for OHLCV bars and the instrument universe (Phase 1 foundation).

Collections:
- bars        — unique (symbol, timeframe, ts); one doc per completed candle
- instruments — unique (security_id, exchange_segment); the tradeable universe
"""

from pymongo import ASCENDING, UpdateOne

from db import _db

bars_collection = _db["bars"]
instruments_collection = _db["instruments"]


def ensure_indexes() -> None:
    bars_collection.create_index(
        [("symbol", ASCENDING), ("timeframe", ASCENDING), ("ts", ASCENDING)],
        unique=True,
        name="symbol_timeframe_ts",
    )
    instruments_collection.create_index(
        [("security_id", ASCENDING), ("exchange_segment", ASCENDING)],
        unique=True,
        name="security_id_segment",
    )
    instruments_collection.create_index("symbol", name="symbol")


def upsert_bars(bar_docs: list[dict]) -> int:
    """Idempotent bulk upsert (re-running a backfill overwrites identical candles
    instead of erroring on the unique index). Returns docs written."""
    if not bar_docs:
        return 0
    ops = [
        UpdateOne(
            {"symbol": d["symbol"], "timeframe": d["timeframe"], "ts": d["ts"]},
            {"$set": d},
            upsert=True,
        )
        for d in bar_docs
    ]
    result = bars_collection.bulk_write(ops, ordered=False)
    return result.upserted_count + result.modified_count


def upsert_instruments(instrument_docs: list[dict]) -> int:
    if not instrument_docs:
        return 0
    ops = [
        UpdateOne(
            {"security_id": d["security_id"], "exchange_segment": d["exchange_segment"]},
            {"$set": d},
            upsert=True,
        )
        for d in instrument_docs
    ]
    result = instruments_collection.bulk_write(ops, ordered=False)
    return result.upserted_count + result.modified_count
