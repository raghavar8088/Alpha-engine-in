"""The basket — the stocks the user names, and the only stocks this desk will ever trade.

WHY A NAMED BASKET RATHER THAN A SCREEN
----------------------------------------
Every other desk in this app picks its own universe: the factory takes the 120 deepest
histories, Momentum Trading takes the top 1000 by market cap, the Long-Horizon desk ranks
on factors. This one does not choose. The user says which stocks are trending and the desk
works only on those, which changes two things structurally:

  * **Intraday bars become affordable.** Five paced Angel candle requests per symbol is a
    few minutes for thirty names and hours for five hundred. The small basket is what buys
    honest 8-timeframe coverage (see `bars.py`).
  * **Crowding becomes the main risk instead of coverage.** 678 strategies pointed at
    fifteen names will pile into the same print by construction, which is exactly how the
    options buying desk lost 29% in one day. The engine's per-symbol cap is the defence,
    and it matters more here than anywhere else in the app.

REMOVAL DOES NOT ORPHAN A POSITION
-----------------------------------
Taking a symbol out of the basket stops NEW entries on it and leaves open positions to be
managed to their stop, target or square-off. A desk that stopped managing a book because a
row was deleted from a list would leave real risk untracked, which is worse than the
untidiness of a position on a name no longer in the basket.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.db import ts_basket_collection
from app.services.manual_positions import search_instruments

from .bars import resolve_instrument

logger = logging.getLogger("trending_stocks.basket")

STATUS_ACTIVE = "ACTIVE"
STATUS_QUARANTINED = "QUARANTINED"
STATUS_REMOVED = "REMOVED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ser(doc: dict) -> dict:
    doc.pop("_id", None)
    for k in ("added_at", "updated_at", "backfilled_at", "removed_at"):
        v = doc.get(k)
        if v is not None and not isinstance(v, str):
            doc[k] = v.isoformat()
    return doc


async def search(query: str, limit: int = 15) -> list[dict]:
    """Autocomplete for the Basket tab. Reuses the Positions module's instrument search so
    a symbol found here is a symbol the rest of the app can already price."""
    return await search_instruments(query, limit)


async def list_basket(include_removed: bool = False) -> list[dict]:
    q: dict = {} if include_removed else {"status": {"$ne": STATUS_REMOVED}}
    return [_ser(d) async for d in ts_basket_collection.find(q).sort("added_at", 1)]


async def active() -> dict[str, dict]:
    """symbol -> instrument, for every tradable name in the basket.

    A QUARANTINED symbol is deliberately excluded: its stored bars and its live quote
    disagree by more than a corporate action's worth, and until that is resolved every
    statistic computed on it is about a different instrument."""
    out: dict[str, dict] = {}
    async for d in ts_basket_collection.find({"status": STATUS_ACTIVE}):
        inst = d.get("instrument") or {}
        if inst.get("angel_token"):
            out[d["symbol"]] = inst
    return out


async def add(symbol: str, note: str | None = None) -> dict:
    """Add one stock. Resolves it to a tradable instrument first — a symbol Angel cannot
    price is rejected here rather than silently sitting in the basket producing no bars,
    no signals and no explanation."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return {"error": "no symbol given"}

    existing = await ts_basket_collection.find_one({"symbol": sym})
    inst = await resolve_instrument(sym)
    if inst is None:
        return {"error": f"{sym} has no Angel-tradable instrument on file — the desk "
                         "cannot fetch candles or quotes for it"}

    doc = {
        "symbol": sym,
        "name": inst.get("name") or sym,
        "asset_class": inst.get("asset_class"),
        "instrument": {
            "symbol": sym,
            "name": inst.get("name"),
            "security_id": inst.get("security_id"),
            "exchange_segment": inst.get("exchange_segment"),
            "angel_token": str(inst.get("angel_token")),
            "angel_exchange": inst.get("angel_exchange") or "NSE",
            "lot_size": int(inst.get("lot_size") or 1),
            "asset_class": inst.get("asset_class"),
        },
        "status": STATUS_ACTIVE,
        "note": note,
        "updated_at": _now(),
    }
    if existing is None:
        doc["added_at"] = _now()
        doc["backfilled_at"] = None
        doc["backfill"] = None
        await ts_basket_collection.insert_one(dict(doc))
        action = "added"
    else:
        await ts_basket_collection.update_one({"symbol": sym}, {"$set": doc})
        action = "re-activated" if existing.get("status") == STATUS_REMOVED else "updated"

    stored = await ts_basket_collection.find_one({"symbol": sym})
    return {"ok": True, "action": action, "symbol": sym, "basket": _ser(stored or doc)}


async def remove(symbol: str) -> dict:
    sym = (symbol or "").strip().upper()
    res = await ts_basket_collection.update_one(
        {"symbol": sym}, {"$set": {"status": STATUS_REMOVED, "removed_at": _now(),
                                   "updated_at": _now()}})
    if res.matched_count == 0:
        return {"error": f"{sym} is not in the basket"}
    return {"ok": True, "symbol": sym,
            "note": "New entries stopped. Any open position on this symbol is still "
                    "managed to its stop, target or square-off."}


async def quarantine(symbol: str, reason: str) -> None:
    """Take a symbol out of the tradable set without deleting it, and say why on the row.

    Triggered by `bars.quote_sanity` — an unadjusted split or a bad tick. Recorded rather
    than silently skipped: 'this symbol produced no signals' and 'this symbol's data is
    untrustworthy' are different facts and only one of them is about the strategies."""
    await ts_basket_collection.update_one(
        {"symbol": symbol.upper()},
        {"$set": {"status": STATUS_QUARANTINED, "quarantine_reason": reason,
                  "updated_at": _now()}})
    logger.warning("[trending_stocks] quarantined %s: %s", symbol, reason)


async def unquarantine(symbol: str) -> dict:
    res = await ts_basket_collection.update_one(
        {"symbol": symbol.upper(), "status": STATUS_QUARANTINED},
        {"$set": {"status": STATUS_ACTIVE, "updated_at": _now()},
         "$unset": {"quarantine_reason": ""}})
    if res.matched_count == 0:
        return {"error": f"{symbol.upper()} is not quarantined"}
    return {"ok": True, "symbol": symbol.upper()}


async def mark_backfilled(symbol: str, written: dict) -> None:
    await ts_basket_collection.update_one(
        {"symbol": symbol.upper()},
        {"$set": {"backfill": written, "backfilled_at": _now(), "updated_at": _now()}})


async def set_all(symbols: list[str]) -> dict:
    """Replace the whole basket in one call — what the UI's bulk paste box uses.

    Names already present keep their history and their backfill state; names no longer
    listed are REMOVED, not deleted, so their trades and their reasons stay auditable."""
    wanted = [s.strip().upper() for s in symbols if s and s.strip()]
    seen: set[str] = set()
    ordered = [s for s in wanted if not (s in seen or seen.add(s))]

    added, failed = [], []
    for sym in ordered:
        res = await add(sym)
        (added if res.get("ok") else failed).append(res.get("symbol") or sym
                                                    if res.get("ok") else
                                                    {"symbol": sym, "error": res.get("error")})
    current = {d["symbol"] async for d in ts_basket_collection.find(
        {"status": {"$ne": STATUS_REMOVED}}, {"symbol": 1})}
    for sym in current - set(ordered):
        await remove(sym)
    return {"ok": True, "kept": added, "rejected": failed,
            "removed": sorted(current - set(ordered))}


__all__ = ["list_basket", "active", "add", "remove", "set_all", "search",
           "quarantine", "unquarantine", "mark_backfilled",
           "STATUS_ACTIVE", "STATUS_QUARANTINED", "STATUS_REMOVED"]
