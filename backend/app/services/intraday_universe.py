"""The liquid intraday universe: the N most-traded NSE stocks, fixed for the day.

WHY LIQUIDITY AND NOT SCORE
The desks used to draw their symbols from the shared daily screen, ranked by a daily
technical score — a list that rotates every day and, until 2026-10-02, was not even
ranked (it was alphabetical). An intraday edge has to survive the spread and the impact
of getting in and out within hours; in thin names it does not, whatever the score said.
So the intraday universe is the top N names by 20-session average traded value (close x
volume), from the same Atlas pre-filter the daily screen uses (`_eligible_symbols`:
≥ Rs 10 cr a day, traded in the last 7 days, ≥ 15 sessions of history), restricted to
stocks MIS intraday is actually allowed in.

EXCLUDED: series BE (trade-to-trade — no intraday allowed) and SM (SME platform), ETFs,
indices, and anything without an Angel token (it could not be streamed or charted).

FIXED FOR THE DAY. It is computed once per session before the open and stored, so every
desk and the stream see the same list all day, and a backtest can later ask what the
universe WAS on a given date — a universe chosen with today's knowledge is look-ahead.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from app.core.db import db, instruments_collection
from app.services import market_calendar

logger = logging.getLogger("intraday_universe")

IST = timezone(timedelta(hours=5, minutes=30))
UNIVERSE_SIZE = int(os.getenv("INTRADAY_UNIVERSE_SIZE", "200"))
MIN_PRICE = float(os.getenv("INTRADAY_UNIVERSE_MIN_PRICE", "50"))
NIFTY_TOKEN = "99926000"

# Indices streamed and stored alongside the stocks (NSE cash-index tokens in Angel's scrip
# master, resolved 2026-10-02). Volume is always 0 for an index; prices are what matter.
INDEX_TOKENS = {
    "NIFTY": "99926000", "INDIAVIX": "99926017", "NIFTYBANK": "99926009", "NIFTYIT": "99926008",
    "FINNIFTY": "99926037", "NIFTYPVTBANK": "99926047", "NIFTYPSUBANK": "99926025",
    "NIFTYAUTO": "99926029", "NIFTYPHARMA": "99926023", "NIFTYFMCG": "99926021",
    "NIFTYMETAL": "99926030", "NIFTYENERGY": "99926020", "NIFTYREALTY": "99926018",
    "NIFTYINFRA": "99926019", "NIFTYMEDIA": "99926031", "NIFTYCOMMODITIES": "99926035",
    "NIFTYCONSUMPTION": "99926036", "NIFTYMIDCAP100": "99926011", "NIFTYNXT50": "99926013",
}

# `stock_universe.sector` holds the niftyindices "Industry" column. Each industry is read
# against the NSE sectoral index that covers it; the mapping is approximate (the Industry
# column does not separate banks from NBFCs, so both read against FINNIFTY) and anything
# unmapped reads against NIFTY itself.
SECTOR_INDEX = {
    "Financial Services": "FINNIFTY", "Information Technology": "NIFTYIT",
    "Automobile and Auto Components": "NIFTYAUTO", "Healthcare": "NIFTYPHARMA",
    "Fast Moving Consumer Goods": "NIFTYFMCG", "Metals & Mining": "NIFTYMETAL",
    "Oil Gas & Consumable Fuels": "NIFTYENERGY", "Power": "NIFTYENERGY",
    "Capital Goods": "NIFTYINFRA", "Construction": "NIFTYINFRA", "Telecommunication": "NIFTYINFRA",
    "Services": "NIFTYINFRA", "Construction Materials": "NIFTYCOMMODITIES", "Chemicals": "NIFTYCOMMODITIES",
    "Consumer Durables": "NIFTYCONSUMPTION", "Consumer Services": "NIFTYCONSUMPTION",
    "Textiles": "NIFTYCONSUMPTION", "Realty": "NIFTYREALTY",
    "Media Entertainment & Publication": "NIFTYMEDIA",
}


def sector_index(industry: str | None) -> str:
    return SECTOR_INDEX.get((industry or "").strip(), "NIFTY")

universe_collection = db["intraday_universe"]

_cache: dict = {"date": None, "doc": None}
_lock = asyncio.Lock()


async def _last_close(symbols: list[str]) -> dict[str, float]:
    from app.core.db import bars_collection
    since = datetime.now(timezone.utc) - timedelta(days=12)
    pipe = [{"$match": {"timeframe": "1d", "symbol": {"$in": symbols}, "ts": {"$gte": since}}},
            {"$sort": {"ts": 1}},
            {"$group": {"_id": "$symbol", "close": {"$last": "$close"}}}]
    return {r["_id"]: float(r["close"] or 0) async for r in bars_collection.aggregate(pipe)}


async def build(for_date: str | None = None) -> dict:
    """Compute and store the universe for `for_date` (default: today, IST)."""
    from app.services.call_engine import _eligible_symbols

    day = for_date or datetime.now(IST).date().isoformat()
    eligible, info, turnover = await _eligible_symbols()
    if not eligible:
        raise RuntimeError(f"eligibility pre-filter returned nothing ({info})")
    ranked = sorted(eligible, key=lambda s: -turnover.get(s, 0.0))
    docs = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": ranked[: UNIVERSE_SIZE * 2]},
         "angel_token": {"$ne": None}, "series": {"$nin": ["BE", "SM"]}},
        {"symbol": 1, "angel_token": 1, "angel_exchange": 1, "is_cas_enabled": 1,
         "security_id": 1, "exchange_segment": 1})}
    closes = await _last_close(ranked[: UNIVERSE_SIZE * 2])
    members, skipped = [], {"no_token_or_series": 0, "price_below_min": 0}
    for sym in ranked:
        if len(members) >= UNIVERSE_SIZE:
            break
        d = docs.get(sym)
        if d is None:
            skipped["no_token_or_series"] += 1
            continue
        if closes.get(sym, 0.0) < MIN_PRICE:
            skipped["price_below_min"] += 1
            continue
        members.append({"symbol": sym, "token": str(d["angel_token"]),
                        "exchange": d.get("angel_exchange") or "NSE",
                        "cas": bool(d.get("is_cas_enabled")),
                        "turnover_cr": round(turnover.get(sym, 0.0) / 1e7, 1),
                        "security_id": d.get("security_id"),
                        "exchange_segment": d.get("exchange_segment")})
    doc = {"_id": day, "date": day, "members": members, "size": len(members),
           "min_turnover_cr": members[-1]["turnover_cr"] if members else None,
           "prefilter": info, "skipped": skipped, "built_at": datetime.now(timezone.utc),
           "rule": f"top {UNIVERSE_SIZE} by 20-session traded value; EQ series; price >= {MIN_PRICE:g}"}
    await universe_collection.replace_one({"_id": day}, doc, upsert=True)
    logger.info("intraday universe %s: %d names, Rs %.0f cr/day down to Rs %s cr/day",
                day, len(members), members[0]["turnover_cr"] if members else 0,
                doc["min_turnover_cr"])
    return doc


async def today(build_if_missing: bool = True) -> dict | None:
    """Today's stored universe; built on first ask. On a closed day, the last one built."""
    day = datetime.now(IST).date().isoformat()
    if _cache["date"] == day and _cache["doc"]:
        return _cache["doc"]
    async with _lock:
        if _cache["date"] == day and _cache["doc"]:
            return _cache["doc"]
        doc = await universe_collection.find_one({"_id": day})
        if doc is None and build_if_missing:
            if market_calendar.is_trading_day():
                doc = await build(day)
            else:
                # A closed day: the universe that matters is the NEXT session's. No daily
                # bar arrives in between, so building it now gives exactly what that
                # morning would — and lets the history backfill use the holiday.
                nxt = market_calendar.next_trading_day().isoformat()
                doc = await universe_collection.find_one({"_id": nxt}) or await build(nxt)
        if doc is None:
            doc = await universe_collection.find_one({}, sort=[("_id", -1)])
        if doc is not None:
            _cache.update({"date": day, "doc": doc})
        return doc


async def on(date: str) -> dict | None:
    """The universe as it was on `date` — what a backtest must use for that day."""
    return await universe_collection.find_one({"_id": date})


async def members() -> list[dict]:
    doc = await today()
    return list(doc["members"]) if doc else []


async def symbols() -> list[str]:
    return [m["symbol"] for m in await members()]
