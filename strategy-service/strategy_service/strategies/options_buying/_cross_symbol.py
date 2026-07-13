"""Lazy cross-symbol close lookup, for the two strategies in this catalog that
genuinely need a second instrument (SMT divergence, inducement+correlation). The
engine's direction(ctx) contract only ever hands a strategy its OWN instrument's bars,
so these query the same `bars` collection the backtester reads from directly, keyed by
timestamp, and cache per-run. Fails soft (returns None) if Mongo isn't reachable or the
other symbol has no bar at that timestamp — callers must treat None as "hold"."""

import os

_client = None
_cache: dict[tuple[str, str], float | None] = {}


def _bars_collection():
    global _client
    if _client is None:
        from pymongo import MongoClient

        _client = MongoClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"))
    return _client[os.getenv("MONGO_DB_NAME", "tradingai")]["bars"]


def close_at(symbol: str, timeframe: str, ts) -> float | None:
    key = (symbol, ts.isoformat())
    if key in _cache:
        return _cache[key]
    try:
        doc = _bars_collection().find_one({"symbol": symbol, "timeframe": timeframe, "ts": ts})
        val = doc["close"] if doc else None
    except Exception:
        val = None
    _cache[key] = val
    return val
