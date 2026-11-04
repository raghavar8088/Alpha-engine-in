"""Company announcements, read by an LLM — Phase 8 of INTRADAY_STOCKS_AI_UPGRADE_PLAN.md.

Every five minutes in the session the data scheduler polls NSE's corporate announcements for
the day. Each new one is stored (local MongoDB, alpha_engine_intraday.market_events, beside
the decision ledger) with the exchange's dissemination time. Announcements of stocks in today's
intraday universe are then classified by the configured provider (ai_service: Anthropic Claude
by default, or OpenAI with AI_PROVIDER=openai), within a daily cap (AI_EVENTS_DAILY_MAX, 300):

  category     results / board_outcome / order_or_contract / mna / capital_raise / rating /
               management_change / legal_regulatory / dividend_or_corporate_action /
               routine_compliance / other
  materiality  low / medium / high — how likely the news moves the stock several percent today
  direction    positive / negative / unclear
  confidence   0-1, and `evidence`: one line quoted from the text

Each result is stored ONCE with the model and prompt version; replays read the stored answer
and never ask again with hindsight. With no key configured nothing is classified and the
announcements are still stored. The LLM never decides a trade: its output is a flag that the
gated paper accounts' event gate MAY use (off until a pre-registered test justifies it).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from app.services import intraday_signal_ledger as ledger

logger = logging.getLogger("event_classifier")

IST = ledger.IST
COLLECTION = "market_events"
ANN_API = "/api/corporate-announcements?index=equities&from_date={d}&to_date={d}"
ANN_REFERER = "/companies-listing/corporate-filings-announcements"
DAILY_MAX = int(os.getenv("AI_EVENTS_DAILY_MAX", "300"))
RETENTION_DAYS = 400
TEXT_MAX = 2000

SYSTEM = (
    "You read announcements that companies listed on India's National Stock Exchange file with "
    "the exchange, and classify each one for an intraday trading risk check. Judge only from the "
    "text you are given; never assume facts it does not state. Materiality: 'high' when the news "
    "is likely to move the stock several percent today (results with a clear surprise, a large "
    "order relative to the company's size, an acquisition, a fund raise at a discount, a rating "
    "change, a regulatory action, a senior management exit, fraud or default); 'medium' when it "
    "may move it noticeably; 'low' for routine compliance (trading-window closures, investor-meet "
    "intimations, newspaper copies, certificates). Direction is 'unclear' unless the text itself "
    "makes it plain. Quote one short line of the text as evidence."
)
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category": {"type": "string", "enum": [
            "results", "board_outcome", "order_or_contract", "mna", "capital_raise", "rating",
            "management_change", "legal_regulatory", "dividend_or_corporate_action",
            "routine_compliance", "other"]},
        "materiality": {"type": "string", "enum": ["low", "medium", "high"]},
        "direction": {"type": "string", "enum": ["positive", "negative", "unclear"]},
        "confidence": {"type": "number"},
        "evidence": {"type": "string"},
    },
    "required": ["category", "materiality", "direction", "confidence", "evidence"],
}
PROMPT_VERSION = hashlib.sha256((SYSTEM + json.dumps(SCHEMA, sort_keys=True)).encode()).hexdigest()[:10]

stats: dict = {"polls": 0, "stored": 0, "classified": 0, "refused": 0, "errors": 0,
               "capped_day": None, "last_error": None}
_indexed = False


def _when(s) -> datetime | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(str(s).strip(), fmt).replace(tzinfo=IST).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _prompt(doc: dict) -> str:
    return (f"Company: {doc.get('name') or doc['symbol']} (NSE: {doc['symbol']})\n"
            f"Subject: {doc.get('desc') or ''}\n"
            f"Filed at: {doc['t'].astimezone(IST).strftime('%d %b %Y %H:%M') if doc.get('t') else 'unknown'} IST\n\n"
            f"Text:\n{(doc.get('text') or '')[:TEXT_MAX]}")


async def _coll():
    global _indexed
    c = ledger._db()[COLLECTION]
    if not _indexed:
        await c.create_index([("symbol", 1), ("t", 1)], name="sym_t")
        await c.create_index("t", expireAfterSeconds=RETENTION_DAYS * 86400, name="ttl")
        _indexed = True
    return c


async def poll(now: datetime | None = None) -> dict:
    """Store today's new announcements and classify the universe stocks' ones. Never raises."""
    if not ledger.ENABLED:
        return {"enabled": False}
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(IST)
    stats["polls"] += 1
    out = {"new": 0, "classified": 0}
    try:
        from app.services.nse_client import nse
        items = await nse.api(ANN_API.format(d=day.strftime("%d-%m-%Y")), ANN_REFERER)
        if not isinstance(items, list):
            return {**out, "fetched": False}
        coll = await _coll()
        for it in items:
            if not isinstance(it, dict) or not it.get("symbol") or not it.get("seq_id"):
                continue
            key = f"{it['symbol']}:{it['seq_id']}"
            if await coll.find_one({"_id": key}, {"_id": 1}):
                continue
            await coll.insert_one({
                "_id": key, "symbol": it["symbol"], "name": it.get("sm_name"), "desc": it.get("desc"),
                "text": (it.get("attchmntText") or "")[:TEXT_MAX], "file": it.get("attchmntFile"),
                "t": _when(it.get("exchdisstime") or it.get("an_dt")) or now, "d": day.date().isoformat(),
                "industry": it.get("smIndustry"), "classified": False, "stored_at": now})
            out["new"] += 1
            stats["stored"] += 1
        out["classified"] = await classify_pending(day.date().isoformat())
    except Exception as exc:  # noqa: BLE001 - a feed or provider failure must not stop the scheduler
        stats["errors"] += 1
        stats["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
        logger.warning("[events] poll failed: %s", exc)
    return out


async def classify_pending(day: str) -> int:
    from ai_service.provider import ProviderError, ProviderRefusalError, get_provider
    provider = get_provider()
    if not getattr(provider, "configured", False):
        return 0
    from app.services import intraday_universe
    universe = set(await intraday_universe.symbols())
    coll = await _coll()
    done_today = await coll.count_documents({"d": day, "classified": True})
    budget = DAILY_MAX - done_today
    if budget <= 0:
        stats["capped_day"] = day
        return 0
    n = 0
    async for doc in coll.find({"d": day, "classified": False, "symbol": {"$in": sorted(universe)}}).sort("t", 1):
        if n >= budget:
            stats["capped_day"] = day
            break
        update: dict = {"classified": True, "model": getattr(provider, "model", None),
                        "provider": getattr(provider, "name", None), "prompt_version": PROMPT_VERSION,
                        "classified_at": datetime.now(timezone.utc)}
        try:
            raw = await provider.complete(SYSTEM, _prompt(doc), max_tokens=4000, json_schema=SCHEMA)
            update["label"] = json.loads(raw)
            stats["classified"] += 1
        except ProviderRefusalError as exc:
            update["label"], update["status"] = None, f"refused: {exc}"
            stats["refused"] += 1
        except (ProviderError, ValueError) as exc:
            update["label"], update["status"] = None, f"error: {exc}"[:300]
            stats["errors"] += 1
        await coll.update_one({"_id": doc["_id"]}, {"$set": update})
        n += 1
    return n


async def recent_high(symbol: str, minutes: int = 120, now: datetime | None = None) -> bool:
    """A high-materiality announcement of `symbol` in the last `minutes` (for the event gate)."""
    if not ledger.ENABLED:
        return False
    now = now or datetime.now(timezone.utc)
    coll = await _coll()
    return bool(await coll.find_one({"symbol": symbol, "t": {"$gte": now - timedelta(minutes=minutes), "$lte": now},
                                     "label.materiality": "high"}, {"_id": 1}))


async def listing(day: str | None = None, only_universe: bool = False, limit: int = 300) -> dict:
    if not ledger.ENABLED:
        return {"enabled": False, "events": []}
    day = day or datetime.now(IST).date().isoformat()
    q: dict = {"d": day}
    if only_universe:
        from app.services import intraday_universe
        q["symbol"] = {"$in": sorted(await intraday_universe.symbols())}
    coll = await _coll()
    rows = []
    async for d in coll.find(q, {"text": 0}).sort("t", -1).limit(max(1, min(limit, 2000))):
        for k in ("t", "stored_at", "classified_at"):
            if isinstance(d.get(k), datetime):
                d[k] = d[k].isoformat()
        rows.append(d)
    from ai_service.provider import get_provider
    p = get_provider()
    return {"enabled": True, "day": day, "provider": getattr(p, "name", None), "configured": getattr(p, "configured", False),
            "model": getattr(p, "model", None), "prompt_version": PROMPT_VERSION, "daily_max": DAILY_MAX,
            "stats": stats, "events": rows}
