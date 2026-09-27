"""Rate a whole index or sector at once, store it, and let the user shop from the result.

WHY THIS IS A SCAN AND NOT A REQUEST
Rating one stock is a page load from screener.in. Rating the Nifty 500 is five hundred of
them, and at the pace this module holds itself to that is roughly five minutes of wall
clock — far past any sensible HTTP timeout, and not something to make a browser hold open.
So a scan is a background task with its progress in Mongo, and the page polls it. Starting
a scan returns immediately with the job, not the answer.

THE UNIVERSE IS ALREADY HERE
`stock_universe` carries every Nifty 50/100/250/500 constituent with NSE's own sector for
each, refreshed from niftyindices.com by `stocks_range`. This module does not fetch its own
constituent lists — a second copy would drift from the first, and the whole point of
picking stocks by index is that the index membership is right. Nifty Next 50 is not
published as its own CSV there, so it is derived exactly as the index is defined: the
Nifty 100 minus the Nifty 50.

TWO SECTOR TAXONOMIES, AND WHICH ONE IS USED WHERE
NSE labels the constituent ("Industry" in its CSV); screener.in labels the company from
its own tree. They disagree often enough to matter. Scanning is BY the NSE sector, because
that is what the index publishes and what a user means by "scan all of Financial Services".
The screener sector is stored alongside and shown on the row, because that is the taxonomy
the rating itself was computed under. Neither is silently preferred.

CACHED WORK IS NOT REDONE
Every symbol goes through `screener_in.get_fundamentals`, which serves anything fetched in
the last day from Mongo. So a rescan an hour later costs almost nothing, and a scan of the
Nifty 500 straight after a scan of the Nifty 50 pays only for the 450 it has not seen.
That is also why a scan can be safely re-run rather than resumed: re-running IS resuming.

A FAILURE IS A ROW, NOT AN ABORT
A symbol screener.in has no page for — a recent listing, a renamed ticker, a symbol NSE
spells differently — records its reason and the scan carries on. Five hundred stocks will
always contain a few, and losing the other 495 to them would be absurd.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx

from app.core.db import (
    fundamental_ratings_collection,
    fundamental_scan_state_collection,
    stock_universe_collection,
)
from app.services import pnl_strength, results_strength, screener_in
from app.services.fundamental_rating import rate

logger = logging.getLogger("fundamental_universe")

STATE_ID = "scan"

# A SCAN IS PACED MORE GENTLY THAN AN INTERACTIVE PASTE, AND THIS WAS MEASURED.
# The interactive path's 1.2s at two-at-a-time is ~1.7 requests/second, which screener.in
# serves happily in the short bursts a pasted list produces. Sustained, it does not: the
# first live Nifty 50 scan got 44 companies through and then took six straight 429s. So a
# scan goes one at a time with a wider gap, and a 429 pauses the whole run rather than
# burning the symbol — the alternative is a 500-stock scan that fails its own tail.
SCAN_PACE_SECONDS = float(os.getenv("FUND_SCAN_PACE", "2.8"))
SCAN_CONCURRENCY = int(os.getenv("FUND_SCAN_CONCURRENCY", "1"))
RATE_LIMIT_COOLDOWN = float(os.getenv("FUND_SCAN_COOLDOWN", "75"))
MAX_RETRIES = 2

# Index keys as stock_universe stores them, plus the one we derive.
INDEX_LABELS = {
    "nifty50": "Nifty 50",
    "niftynext50": "Nifty Next 50",
    "nifty100": "Nifty 100",
    "nifty250": "Nifty LargeMidcap 250",
    "nifty500": "Nifty 500",
}
DERIVED = {"niftynext50": ("nifty100", "nifty50")}   # in the first, not in the second

_task: asyncio.Task | None = None
_cancel = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── the universe ─────────────────────────────────────────────────────────────────


async def _symbols_for(scope_type: str, scope_key: str) -> list[dict]:
    """The constituent rows for an index key or an NSE sector name."""
    if scope_type == "index":
        if scope_key in DERIVED:
            outer, inner = DERIVED[scope_key]
            rows = [d async for d in stock_universe_collection.find(
                {"indices": outer}, {"symbol": 1, "name": 1, "sector": 1, "indices": 1})]
            return [r for r in rows if inner not in (r.get("indices") or [])]
        query = {"indices": scope_key}
    elif scope_type == "sector":
        query = {"sector": scope_key}
    else:
        query = {}
    return [d async for d in stock_universe_collection.find(
        query, {"symbol": 1, "name": 1, "sector": 1, "indices": 1})]


async def scopes() -> dict:
    """What can be scanned, with how many stocks in each."""
    indices, sectors = [], {}
    async for d in stock_universe_collection.find({}, {"indices": 1, "sector": 1}):
        for i in d.get("indices") or []:
            sectors.setdefault("__idx__" + i, 0)
            sectors["__idx__" + i] += 1
        sec = d.get("sector") or "Unclassified"
        sectors[sec] = sectors.get(sec, 0) + 1

    for key, label in INDEX_LABELS.items():
        if key in DERIVED:
            outer, inner = DERIVED[key]
            count = sectors.get("__idx__" + outer, 0) - sectors.get("__idx__" + inner, 0)
        else:
            count = sectors.get("__idx__" + key, 0)
        if count > 0:
            indices.append({"key": key, "label": label, "count": count})

    sector_rows = sorted(
        ({"key": k, "label": k, "count": v} for k, v in sectors.items() if not k.startswith("__idx__")),
        key=lambda r: -r["count"])
    rated = await fundamental_ratings_collection.count_documents({})
    return {"indices": indices, "sectors": sector_rows, "rated_stored": rated}


# ── scan state ───────────────────────────────────────────────────────────────────


async def status() -> dict:
    doc = await fundamental_scan_state_collection.find_one({"_id": STATE_ID})
    if not doc:
        return {"running": False, "status": "idle", "done": 0, "total": 0,
                "ok": 0, "failed": 0, "failures": [], "scope": None}
    doc.pop("_id", None)
    # "cooling" is a scan waiting out a rate limit — still running, and the page must
    # keep polling or the progress bar freezes mid-scan and looks dead.
    doc["running"] = doc.get("status") in ("running", "cooling", "cancelling")
    return doc


async def _write(**fields) -> None:
    await fundamental_scan_state_collection.update_one(
        {"_id": STATE_ID}, {"$set": fields}, upsert=True)


def store_doc(symbol: str, r: dict, q: dict, p: dict, universe: dict | None) -> dict:
    """One flat, filterable row per stock — what the picker reads.

    Flat on purpose: the browse view filters and sorts on these fields, and a query that
    has to reach into a nested rating document to sort by the quarterly grade would need
    an index per nesting level for no gain.
    """
    return {
        "symbol": symbol,
        "name": r.get("name") or (universe or {}).get("name"),
        "nse_sector": (universe or {}).get("sector"),
        "sector": r.get("sector"),
        "industry": r.get("industry"),
        "indices": (universe or {}).get("indices") or [],
        "score": r.get("score"),
        "grade": r.get("grade"),
        "grade_key": r.get("grade_key"),
        "verdict": r.get("verdict"),
        "coverage": r.get("coverage"),
        "is_lender": r.get("is_lender"),
        "results_score": q.get("score"),
        "results_grade": q.get("grade"),
        "results_grade_key": q.get("grade_key"),
        "latest_quarter": q.get("latest_quarter"),
        "pnl_score": p.get("score"),
        "pnl_grade": p.get("grade"),
        "pnl_grade_key": p.get("grade_key"),
        "price": r.get("price"),
        "market_cap_cr": r.get("market_cap_cr"),
        "pe": r.get("pe"),
        "roce": r.get("roce"),
        "summary": r.get("summary"),
        "basis": r.get("basis"),
        "source_url": r.get("source_url"),
        "rated_at": _now(),
    }


async def rate_one(symbol: str, universe: dict | None = None,
                   client: httpx.AsyncClient | None = None, force: bool = False) -> dict:
    """Fetch, rate on all three axes, store. Raises ScreenerError upward."""
    data = await screener_in.get_fundamentals(symbol, force=force, client=client)
    r = rate(data)
    try:
        q = results_strength.analyse(data)
    except Exception:
        logger.exception("quarterly read failed for %s", symbol)
        q = {}
    try:
        p = pnl_strength.analyse(data)
    except Exception:
        logger.exception("p&l read failed for %s", symbol)
        p = {}
    doc = store_doc(symbol, r, q, p, universe)
    await fundamental_ratings_collection.replace_one(
        {"_id": symbol}, {**doc, "_id": symbol}, upsert=True)
    doc["cached"] = bool(data.get("cached"))
    return doc


async def _rate_with_backoff(symbol: str, row: dict, client: httpx.AsyncClient,
                             force: bool) -> dict:
    """Rate one symbol, waiting out a 429 instead of spending the symbol on it.

    Only rate-limiting is retried. A company with no screener.in page will not grow one,
    so retrying that would just cost the scan two extra minutes to reach the same answer.
    """
    attempt = 0
    while True:
        try:
            return await rate_one(symbol, universe=row, client=client, force=force)
        except screener_in.ScreenerError as exc:
            if "rate-limit" not in exc.detail.lower() or attempt >= MAX_RETRIES or _cancel:
                raise
            attempt += 1
            wait = RATE_LIMIT_COOLDOWN * attempt
            logger.warning("scan hit screener.in rate limit on %s — cooling down %.0fs "
                           "(attempt %d/%d)", symbol, wait, attempt, MAX_RETRIES)
            await _write(status="cooling", current=f"{symbol} — rate limited, waiting {wait:.0f}s")
            await asyncio.sleep(wait)
            await _write(status="running")


async def _run(scope_type: str, scope_key: str, label: str, force: bool) -> None:
    global _cancel
    rows = await _symbols_for(scope_type, scope_key)
    total = len(rows)
    await _write(status="running", scope={"type": scope_type, "key": scope_key, "label": label},
                 total=total, done=0, ok=0, failed=0, failures=[], current=None,
                 started_at=_now(), finished_at=None, forced=force)
    if not total:
        await _write(status="done", finished_at=_now(),
                     note="No stocks found for that scope — is the universe seeded?")
        return

    done = ok = failed = 0
    failures: list[dict] = []
    sem = asyncio.Semaphore(max(1, SCAN_CONCURRENCY))

    async with httpx.AsyncClient(timeout=screener_in.TIMEOUT, follow_redirects=True,
                                 headers=screener_in.BROWSER_HEADERS) as client:
        async def one(row: dict) -> None:
            nonlocal done, ok, failed
            if _cancel:
                return
            sym = screener_in.normalise_symbol(row.get("symbol") or "")
            if not sym:
                return
            async with sem:
                if _cancel:
                    return
                try:
                    res = await _rate_with_backoff(sym, row, client, force)
                    ok += 1
                    if not res.get("cached"):
                        await asyncio.sleep(SCAN_PACE_SECONDS)
                except screener_in.ScreenerError as exc:
                    failed += 1
                    failures.append({"symbol": sym, "error": exc.detail})
                except Exception as exc:
                    failed += 1
                    failures.append({"symbol": sym, "error": f"{type(exc).__name__}: {exc}"})
                    logger.exception("scan failed for %s", sym)
                finally:
                    done += 1
                    # Progress is written every few symbols rather than on each one: the
                    # page polls every couple of seconds, and 500 extra writes would be
                    # 500 round trips to Atlas for numbers nobody reads.
                    if done % 5 == 0 or done == total:
                        await _write(done=done, ok=ok, failed=failed,
                                     failures=failures[-25:], current=sym)

        await asyncio.gather(*(one(r) for r in rows))

    await _write(status="cancelled" if _cancel else "done", done=done, ok=ok, failed=failed,
                 failures=failures[-25:], current=None, finished_at=_now())
    logger.info("fundamental scan %s: %s ok, %s failed of %s", label, ok, failed, total)
    _cancel = False


async def start(scope_type: str, scope_key: str, force: bool = False) -> dict:
    """Kick off a scan unless one is already running."""
    global _task, _cancel
    st = await status()
    if st.get("running") and _task and not _task.done():
        return {"started": False, "reason": "A scan is already running.", "status": st}

    label = (INDEX_LABELS.get(scope_key, scope_key) if scope_type == "index" else scope_key)
    _cancel = False
    _task = asyncio.create_task(_run(scope_type, scope_key, label, force))
    rows = await _symbols_for(scope_type, scope_key)
    eta = int(len(rows) * SCAN_PACE_SECONDS / max(1, SCAN_CONCURRENCY) / 60)
    return {"started": True, "scope": {"type": scope_type, "key": scope_key, "label": label},
            "symbols": len(rows),
            "eta_minutes": eta,
            "note": (f"About {eta} minute(s) if nothing is cached — anything rated in the "
                     "last day is reused, so a rescan is far quicker.")}


async def cancel() -> dict:
    global _cancel
    _cancel = True
    await _write(status="cancelling")
    return {"cancelling": True}


# ── browsing what was scanned ────────────────────────────────────────────────────

SORTS = {
    "score": ("score", -1), "results": ("results_score", -1), "pnl": ("pnl_score", -1),
    "symbol": ("symbol", 1), "market_cap": ("market_cap_cr", -1), "pe": ("pe", 1),
    "roce": ("roce", -1),
}


async def browse(index: str | None = None, sector: str | None = None,
                 min_score: float | None = None, min_results: float | None = None,
                 min_pnl: float | None = None, grades: list[str] | None = None,
                 search: str | None = None, sort: str = "score",
                 limit: int = 600) -> dict:
    """Stored ratings, filtered the way the picker asks for them."""
    q: dict = {"score": {"$ne": None}}
    if index:
        if index in DERIVED:
            outer, inner = DERIVED[index]
            q["indices"] = {"$all": [outer], "$nin": [inner]}
        else:
            q["indices"] = index
    if sector:
        q["$or"] = [{"nse_sector": sector}, {"sector": sector}]
    if min_score is not None:
        q["score"] = {"$gte": min_score, "$ne": None}
    if min_results is not None:
        q["results_score"] = {"$gte": min_results}
    if min_pnl is not None:
        q["pnl_score"] = {"$gte": min_pnl}
    if grades:
        q["grade_key"] = {"$in": grades}
    if search:
        rx = {"$regex": screener_in.normalise_symbol(search), "$options": "i"}
        q["$and"] = [{"$or": [{"symbol": rx}, {"name": {"$regex": search, "$options": "i"}}]}]

    field, direction = SORTS.get(sort, SORTS["score"])
    rows = [d async for d in
            fundamental_ratings_collection.find(q).sort(field, direction).limit(limit)]
    for d in rows:
        d.pop("_id", None)
    return {"stocks": rows, "count": len(rows), "sort": sort}
