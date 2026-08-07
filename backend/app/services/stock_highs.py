"""All-time highs for the stock universe.

The Bullish Stocks screener wants "is this stock at an all-time high?", which needs the
whole price history — but keeping decades of daily bars for 500 symbols in bars_collection
would be ~1.5M documents that every screen run has to read. So the history is walked ONCE,
per symbol, and collapsed to a single small document:

    {symbol, all_time_high, all_time_high_date, first_bar, last_checked, sessions}

After that, `bump_from_bars()` keeps it current from the daily bars the Stocks Range
backfill already stores, which is O(universe) per day instead of O(history).

Angel caps a single historical-candle request, so `_deep_history()` walks backwards in
CHUNK_YEARS windows until the API stops returning candles — that is the stock's listing
date, and gives a genuine all-time high rather than a windowed one.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from pymongo import UpdateOne

from app.core.db import (
    bars_collection,
    instruments_collection,
    stock_highs_collection,
    stock_universe_collection,
)
from app.services.angel_client import AngelAPIError, angel_client

logger = logging.getLogger("stock_highs")

IST = timezone(timedelta(hours=5, minutes=30))
CHUNK_YEARS = 5          # Angel returns a bounded number of candles per call
MAX_CHUNKS = 6           # walk back at most ~30 years (NSE itself only dates to 1994)
PACE_SECONDS = 0.4       # Angel's historical endpoint is the rate-limited one


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _deep_history(exchange: str, token: str) -> list[list]:
    """Every daily candle Angel will give us, oldest→newest, walking back in windows
    until a window comes back empty (i.e. before the stock listed)."""
    rows: list[list] = []
    end = _now()
    for _ in range(MAX_CHUNKS):
        start = end - timedelta(days=365 * CHUNK_YEARS)
        try:
            chunk = await angel_client.candles(
                exchange, token, "D",
                start.astimezone(IST).strftime("%Y-%m-%d 09:15"),
                end.astimezone(IST).strftime("%Y-%m-%d 15:30"),
            )
        except Exception:
            break
        await asyncio.sleep(PACE_SECONDS)
        if not chunk:
            break
        rows = list(chunk) + rows
        end = start
        if len(chunk) < 100:      # a barely-populated window means we reached listing
            break
    return rows


def _high_of(rows: list[list]) -> tuple[float, str] | None:
    """Highest high across raw Angel candle rows → (high, its ISO date)."""
    best, best_ts = None, None
    for r in rows:
        try:
            h = float(r[2])
        except (ValueError, TypeError, IndexError):
            continue
        if best is None or h > best:
            best, best_ts = h, r[0]
    if best is None:
        return None
    try:
        date = datetime.fromisoformat(best_ts).astimezone(timezone.utc).date().isoformat()
    except (ValueError, TypeError):
        date = None
    return best, date


async def backfill_all_time_highs(only_missing: bool = True) -> dict:
    """Walk each universe symbol's full history once and store its all-time high.

    `only_missing=True` (the default, and what startup uses) skips symbols already seeded,
    so this is safe to call on every boot — it costs nothing once warm and picks up any
    stock newly added to the index lists.
    """
    if not angel_client.configured():
        logger.info("all-time-high backfill skipped — Angel One not configured")
        return {"ok": 0, "failed": 0, "skipped": True}

    syms = [d["symbol"] async for d in stock_universe_collection.find({}, {"symbol": 1})]
    if only_missing:
        have = set(await stock_highs_collection.distinct("symbol"))
        syms = [s for s in syms if s not in have]
    if not syms:
        return {"ok": 0, "failed": 0, "already_seeded": True}

    inst = {
        d["symbol"]: d async for d in instruments_collection.find(
            {"asset_class": "EQUITY", "symbol": {"$in": syms}, "angel_token": {"$ne": None}},
            {"symbol": 1, "angel_token": 1, "angel_exchange": 1},
        )
    }
    try:
        await angel_client._session()
    except AngelAPIError:
        pass

    ok = fail = 0
    for sym, i in inst.items():
        rows = await _deep_history(i.get("angel_exchange") or "NSE", str(i["angel_token"]))
        got = _high_of(rows) if rows else None
        if not got:
            fail += 1
            continue
        high, date = got
        first = None
        try:
            first = datetime.fromisoformat(rows[0][0]).astimezone(timezone.utc).date().isoformat()
        except (ValueError, TypeError, IndexError):
            pass
        await stock_highs_collection.update_one(
            {"symbol": sym},
            {"$set": {
                "symbol": sym, "all_time_high": round(high, 2), "all_time_high_date": date,
                "first_bar": first, "sessions": len(rows), "last_checked": _now(),
            }},
            upsert=True,
        )
        ok += 1

    logger.info("all-time-high backfill: %s ok, %s failed (of %s)", ok, fail, len(inst))
    return {"ok": ok, "failed": fail, "symbols": len(inst)}


async def bump_from_bars() -> dict:
    """Raise stored all-time highs using the daily bars already in bars_collection.

    Cheap and idempotent: this is how a stock that breaks out TODAY gets its all-time high
    updated without re-walking its history. Only ever moves a high upward.
    """
    stored = {d["symbol"]: d async for d in stock_highs_collection.find(
        {}, {"symbol": 1, "all_time_high": 1})}
    if not stored:
        return {"raised": 0}

    peaks: dict[str, tuple[float, str]] = {}
    async for b in bars_collection.find(
        {"timeframe": "1d", "symbol": {"$in": list(stored)}}, {"symbol": 1, "high": 1, "ts": 1}
    ):
        h = b.get("high")
        if h is None:
            continue
        cur = peaks.get(b["symbol"])
        if cur is None or h > cur[0]:
            peaks[b["symbol"]] = (h, b.get("ts"))

    ops = []
    for sym, (h, ts) in peaks.items():
        if h > (stored[sym].get("all_time_high") or 0):
            date = None
            try:
                date = datetime.fromisoformat(ts).astimezone(timezone.utc).date().isoformat()
            except (ValueError, TypeError):
                pass
            ops.append(UpdateOne(
                {"symbol": sym},
                {"$set": {"all_time_high": round(h, 2), "all_time_high_date": date,
                          "last_checked": _now()}},
            ))
    if ops:
        await stock_highs_collection.bulk_write(ops, ordered=False)
    logger.info("all-time highs raised for %s symbols", len(ops))
    return {"raised": len(ops)}


async def load_highs(symbols: list[str]) -> dict[str, dict]:
    return {
        d["symbol"]: d async for d in stock_highs_collection.find(
            {"symbol": {"$in": symbols}},
            {"_id": 0, "symbol": 1, "all_time_high": 1, "all_time_high_date": 1, "sessions": 1},
        )
    }
