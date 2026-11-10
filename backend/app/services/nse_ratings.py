"""NSE Stock Ratings: every NSE-listed company on one table, kept current as results land.

The rules live in `nse_ratings_logic`. This module fetches, stores and schedules.

WHERE EACH COLUMN COMES FROM
  * The company list: NSE's own EQUITY_L.csv, every mainboard equity in the EQ, BE and
    BZ series (2,645 on 10 Nov 2026). SME-platform companies are not on that list and are
    not rated: they report half-yearly, so the quarterly read cannot apply to them.
  * The index: niftyindices.com's five broad-market slices (Nifty 50, Next 50, Midcap
    150, Smallcap 250, Microcap 250), fetched here rather than read from the shared
    stock_universe. That collection only ever adds members, so on 10 Nov 2026 its "Nifty
    500" held 530 names.
  * Sector: NSE's, from the index file, where the company is in an index. Otherwise
    screener.in's, which uses the same NSE taxonomy.
  * Fundamentals, latest quarter and P&L record: screener.in, through the same rate(),
    results_strength and pnl_strength calls the Rate tab makes. Every refresh also
    updates the Universe tab's row, so the module's tabs never disagree about a grade.
  * Results dates: NSE's board-meetings feed (meetings whose purpose is financial
    results). NSE's own financial-results feed returns almost nothing to this host
    (checked 10 Nov 2026: one filing for all of October), so the meeting date stands in
    for the filing date. Results are approved at that meeting and disclosed within 30
    minutes of it.
  * Price returns: NSE's end-of-day bhavcopy closes, adjusted with NSE's corporate-actions
    feed (see nse_ratings_logic). Nothing is stored but the result: about ten bhavcopy
    files are read per day and thrown away, so this adds no disk use (the box is near
    full) and no Atlas use beyond the rows themselves.

HOW IT STAYS CURRENT (one background loop, started by the fundamentals router)
  every cycle (15 min)   rebuild any row whose cached screener.in page is newer than the
                         row (a Rate-tab or Universe-scan read), without fetching;
                         then read screener.in again for whatever is due, at the Universe
                         scan's own polite pace, for at most 40 minutes per cycle
  every 6 hours          results board meetings, from 10 days back to 35 days ahead
                         (the first run backfills 100 days)
  daily, after 19:30     returns, once that day's bhavcopy is out
  daily                  re-evaluate the date-dependent fields: freshness, pending, overall
  weekly                 the company list and the index slices
"Due" means a results meeting newer than the rating's latest quarter, a company never read,
a quarter past its deadline, or a read more than 100 days old (see refresh_reason). The
loop gives way while a Universe scan runs, so screener.in never sees two scans at once,
and it stops when Main Control switches the Fundamental Rating module off.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import httpx
from pymongo import UpdateOne

from app.core.db import db, fundamental_ratings_collection, screener_fundamentals_collection
from app.services import (
    fundamental_brief,
    fundamental_universe,
    market_calendar,
    pnl_strength,
    results_strength,
    screener_in,
)
from app.services import nse_ratings_logic as L
from app.services.desk_switches import is_on
from app.services.fundamental_rating import rate
from app.services.grades import grade
from app.services.nse_client import nse

logger = logging.getLogger("nse_ratings")

rows = db["nse_stock_ratings"]
meta = db["nse_stock_ratings_meta"]

SWITCH = "fundamentals"
IST = L.IST

START_DELAY = float(os.getenv("NSE_RATINGS_START_DELAY", "240"))
CYCLE_SECONDS = float(os.getenv("NSE_RATINGS_CYCLE", "900"))
REFRESH_BUDGET = float(os.getenv("NSE_RATINGS_BUDGET", "2400"))
PACE_SECONDS = float(os.getenv("NSE_RATINGS_PACE", str(fundamental_universe.SCAN_PACE_SECONDS)))
COOLDOWN = fundamental_universe.RATE_LIMIT_COOLDOWN
RETURNS_AFTER_HHMM = "19:30"

EQUITY_LIST = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
INDEX_CSV = "https://niftyindices.com/IndexConstituent/{name}.csv"
BHAV = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
SYMBOL_CHANGES = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
BM_API = "/api/corporate-board-meetings?index=equities&from_date={a}&to_date={b}"
BM_REFERER = "/companies-listing/corporate-filings-board-meetings"
CA_API = "/api/corporates-corporateActions?index=equities&from_date={a}&to_date={b}"
CA_REFERER = "/companies-listing/corporate-filings-actions"
KEEP_SERIES = ("EQ", "BE", "BZ")

# The cached page minus what no score reads, so a rebuild of every row moves far fewer
# bytes from Atlas.
CACHE_PROJ = {"about": 0, "pros": 0, "cons": 0, "ratios_table": 0, "ratios_table_periods": 0,
              "balance_sheet_periods": 0, "cash_flow_periods": 0, "shareholding_periods": 0}

# What a rebuild needs from the existing row: everything that does not come from the page.
CTX_PROJ = {"name": 1, "series": 1, "nse_sector": 1, "indices": 1, "listed": 1, "listed_on": 1,
            "meetings": 1, "refresh": 1, "fetched_at": 1, "fetch_error": 1, "v": 1,
            "ret_asof": 1, "r1y": 1}

TIME_KEYS = ("freshness", "behind", "next_q", "next_due", "last_meeting", "next_meeting",
             "pending", "pending_key", "tflags", "overall", "ovr_key", "ovr_tier", "ovr_status",
             "ovr_reasons", "ovr_components", "ovr_formula", "t_day")
TIME_PROJ = {k: 1 for k in (*TIME_KEYS, "qend", "qlabel", "meetings", "fund", "quarter", "pnl",
                            "coverage", "pillars_n", "pillars_applicable", "fetch_error",
                            "fetched_at")}

# What the table reads. Kept explicit so a row's bookkeeping never rides along to the page.
TABLE_FIELDS = (
    "name", "screener_name", "series", "sector", "industry", "index_label", "index_tier",
    "idx_rank", "overall", "ovr_key", "ovr_tier", "ovr_status", "ovr_reasons", "ovr_formula",
    "fund", "fund_key", "fund_tier", "coverage", "is_lender", "quarter", "q_key", "q_tier",
    "pnl", "pnl_key", "pnl_tier", "qlabel", "qend", "qyoy_label", "qprev_label", "rev",
    "rev_yoy", "rev_qoq", "np", "np_yoy", "np_qoq", "np_flag", "np_note", "op_yoy", "roce",
    "roe", "de", "opm", "net_margin", "sales_cagr", "profit_cagr", "pe", "promoter",
    "no_promoter", "institutional", "mcap", "r3m", "r6m", "r1y", "r2y", "ret_asof",
    "ret_notes", "ret_check", "explain", "tflags", "sflags", "freshness", "behind", "next_q",
    "next_due", "pending", "last_meeting", "next_meeting", "basis", "source_url",
    "fetched_at", "fetch_error", "listed",
)

SORTS = {
    "overall": "overall", "fundamentals": "fund", "quarter": "quarter", "pnl": "pnl",
    "name": "name", "symbol": "_id", "sector": "sector", "index": "idx_rank",
    "latest_quarter": "qend", "revenue": "rev", "rev_yoy": "rev_yoy", "rev_qoq": "rev_qoq",
    "profit": "np", "np_yoy": "np_yoy", "np_qoq": "np_qoq", "roce": "roce", "roe": "roe",
    "de": "de", "opm": "opm", "sales_cagr": "sales_cagr", "profit_cagr": "profit_cagr",
    "pe": "pe", "promoter": "promoter", "mcap": "mcap", "r3m": "r3m", "r6m": "r6m",
    "r1y": "r1y", "r2y": "r2y", "updated": "fetched_at",
}

QUARTER_FILTERS = {
    "strong": ("Strong quarter (7.8+)", {"quarter": {"$gte": 7.8}}),
    "good": ("Good quarter (6.2-7.7)", {"quarter": {"$gte": 6.2, "$lt": 7.8}}),
    "average": ("Average quarter (4.6-6.1)", {"quarter": {"$gte": 4.6, "$lt": 6.2}}),
    "weak": ("Weak quarter (below 4.6)", {"quarter": {"$lt": 4.6}}),
    "growing": ("Sales and operating profit up YoY",
                {"rev_yoy": {"$gt": 0}, "op_yoy": {"$gt": 0}}),
    "declining": ("Sales or operating profit down YoY",
                  {"$or": [{"rev_yoy": {"$lt": 0}}, {"op_yoy": {"$lt": 0}}]}),
    "reported": ("Reported the latest quarter", {"freshness": "current"}),
    "unrated": ("Quarter not rated", {"quarter": None}),
}
DATA_FILTERS = {
    "current": ("Latest quarter in", {"freshness": "current"}),
    "due": ("Next results not due yet", {"freshness": "due"}),
    "pending": ("New results, refresh queued", {"pending": True}),
    "outdated": ("Outdated: past a filing deadline", {"freshness": "outdated"}),
    "insufficient": ("Insufficient Data", {"ovr_key": L.INSUFFICIENT_KEY}),
    "errors": ("screener.in read failed", {"fetch_error": {"$ne": None}}),
}

status: dict = {"running": False, "step": None, "started_at": None, "finished_at": None,
                "queue": 0, "done": 0, "ok": 0, "failed": 0, "current": None, "note": None,
                "last_error": None, "last_cycle": None}
_cycle_lock = asyncio.Lock()
_summary_cache: tuple[float, dict] | None = None


class RateLimited(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ist_now() -> datetime:
    return datetime.now(IST)


def _clean(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    doc = dict(doc)
    doc["symbol"] = doc.pop("_id", doc.get("symbol"))
    return doc


async def _bulk(ops: list) -> int:
    n = 0
    for i in range(0, len(ops), 500):
        chunk = ops[i:i + 500]
        if chunk:
            await rows.bulk_write(chunk, ordered=False)
            n += len(chunk)
    return n


def _score(data: dict) -> tuple[dict, dict, dict]:
    """The Rate tab's three reads, with the Rate tab's fallbacks when a table will not parse."""
    r = rate(data)
    try:
        q = results_strength.analyse(data)
    except Exception:
        logger.exception("quarterly read failed for %s", data.get("symbol") or data.get("_id"))
        q = {"rated": False, "score": None, "band": "unknown", "signals": [],
             "verdict": "Results could not be read", **grade(None, "quarter"),
             "headline": "The quarterly table could not be interpreted."}
    try:
        p = pnl_strength.analyse(data)
    except Exception:
        logger.exception("p&l read failed for %s", data.get("symbol") or data.get("_id"))
        p = {"rated": False, "score": None, "signals": [], **grade(None, "pnl"),
             "verdict": "P&L record could not be read",
             "headline": "The yearly table could not be interpreted."}
    return r, q, p


def _build(row: dict, data: dict, r: dict, q: dict, p: dict) -> dict:
    """One row's $set from the page plus the row's own context (index, meetings, returns)."""
    doc = L.static_row(data, r, q, p, series=row.get("series"))
    doc["sector"] = row.get("nse_sector") or doc.get("screener_sector") or "Unclassified"
    doc["ret_check"] = L.screener_check({**row, **doc}, L.as_date(row.get("ret_asof")))
    doc.update(L.time_fields({**row, **doc}, _ist_now().date()))
    return doc


async def _store_universe_row(symbol: str, r: dict, q: dict, p: dict, row: dict) -> None:
    """Keep the Universe tab's row in step, in the shape its own scan writes.

    $set rather than replace, so a row last written by the Rate tab keeps the fields only
    that path stores, and gains the flat fields the Universe tab filters on.
    """
    universe = {"name": row.get("name"), "sector": row.get("nse_sector"),
                "indices": row.get("indices") or []}
    doc = fundamental_universe.store_doc(symbol, r, q, p, universe)
    doc["band"] = r.get("band")
    await fundamental_ratings_collection.update_one({"_id": symbol}, {"$set": doc}, upsert=True)


# ── the company list and the index slices ────────────────────────────────────────


async def refresh_universe() -> dict:
    """Every NSE mainboard equity, with its one index slice and NSE sector. Idempotent."""
    resp = await nse.get(EQUITY_LIST)
    if resp is None:
        raise RuntimeError("NSE's EQUITY_L.csv could not be fetched")
    listed: dict[str, dict] = {}
    for raw in csv.DictReader(io.StringIO(resp.text)):
        x = {(k or "").strip().upper(): (v or "").strip() for k, v in raw.items()}
        sym, series = x.get("SYMBOL", "").upper(), x.get("SERIES", "")
        if not sym or series not in KEEP_SERIES:
            continue
        listed[sym] = {"name": x.get("NAME OF COMPANY") or sym, "series": series,
                       "isin": x.get("ISIN NUMBER") or None,
                       "listed_on": L.iso(L.parse_nse_date(x.get("DATE OF LISTING"))),
                       "face_value": L.num(x.get("FACE VALUE"))}
    # A blocked or truncated download must not mark two thousand companies as delisted.
    if len(listed) < 1500:
        raise RuntimeError(f"EQUITY_L.csv held only {len(listed)} equities; not applied")

    prev = await meta.find_one({"_id": "universe"}) or {}
    slices: dict[str, list[str]] = dict(prev.get("slices") or {})
    sectors: dict[str, str] = dict(prev.get("sectors") or {})
    fetched_lists = []
    async with httpx.AsyncClient(timeout=40, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"}) as c:
        for key, _label, fname in L.INDEX_SLICES:
            try:
                text = (await c.get(INDEX_CSV.format(name=fname))).text
                got = [{(k or "").strip(): (v or "").strip() for k, v in r_.items()}
                       for r_ in csv.DictReader(io.StringIO(text))]
                syms = [g.get("Symbol", "").upper() for g in got if g.get("Symbol")]
                # An error page parses to nothing; keep last week's list rather than an empty one.
                if len(syms) >= 40:
                    slices[key] = syms
                    fetched_lists.append(key)
                    for g in got:
                        if g.get("Symbol") and g.get("Industry"):
                            sectors[g["Symbol"].upper()] = g["Industry"]
            except Exception as exc:                       # noqa: BLE001
                logger.warning("index list %s not fetched: %s", fname, exc)
            await asyncio.sleep(0.4)

    slice_of: dict[str, str] = {}
    for key, _label, _f in reversed(L.INDEX_SLICES):     # the senior slice wins
        for s in slices.get(key, []):
            slice_of[s] = key

    screener_sector = {d["_id"]: d.get("screener_sector")
                       async for d in rows.find({}, {"screener_sector": 1})}
    now = _now()
    ops = []
    for sym, info in listed.items():
        nse_sector = sectors.get(sym) if sym in slice_of else None
        ops.append(UpdateOne({"_id": sym}, {
            "$set": {**info, "symbol": sym, "listed": True, "nse_sector": nse_sector,
                     "sector": nse_sector or screener_sector.get(sym) or "Unclassified",
                     **L.index_fields(slice_of.get(sym)), "universe_at": now},
            "$setOnInsert": {"v": 0, "meetings": []}}, upsert=True))
    await _bulk(ops)
    gone = await rows.update_many({"_id": {"$nin": list(listed)}, "listed": True},
                                  {"$set": {"listed": False}})
    by_series = Counter(v["series"] for v in listed.values())
    await meta.replace_one({"_id": "universe"}, {
        "_id": "universe", "at": now, "listed": len(listed), "by_series": dict(by_series),
        "slices": slices, "sectors": sectors, "fetched_lists": fetched_lists,
        "in_index": len(slice_of), "delisted_now": gone.modified_count}, upsert=True)
    logger.info("nse ratings universe: %d listed %s, %d in an index, %d marked delisted",
                len(listed), dict(by_series), len(slice_of), gone.modified_count)
    return {"listed": len(listed), "by_series": dict(by_series), "in_index": len(slice_of),
            "lists": fetched_lists, "delisted": gone.modified_count}


# ── results board meetings ───────────────────────────────────────────────────────

_RESULTS_DESC = re.compile(r"financial\s+results?|\bresults?\b.*\bquarter", re.I)


def _is_results_meeting(it: dict) -> bool:
    purpose = (it.get("bm_purpose") or "").lower()
    if "result" in purpose:
        return True
    # About half of NSE's rows are a bare "Board Meeting Intimation" whose description
    # carries the agenda; 8 of the 948 results meetings in 1-10 Nov 2026 appeared ONLY so.
    return "intimation" in purpose and bool(_RESULTS_DESC.search(it.get("bm_desc") or ""))


async def refresh_meetings(days_back: int = 10, days_ahead: int = 35) -> dict:
    """Merge NSE's results board meetings into each row's `meetings` list.

    Asked for seven days at a time: in results season one week is about a megabyte of
    JSON, so a 135-day window in one call would hold tens of megabytes in a backend that
    runs near its memory cap.
    """
    today = _ist_now().date()
    start, end = today - timedelta(days=days_back), today + timedelta(days=days_ahead)
    found: dict[str, set[str]] = {}
    chunks = failed = seen = 0
    cur = start
    while cur <= end:
        to = min(cur + timedelta(days=6), end)
        body = await nse.api(BM_API.format(a=cur.strftime("%d-%m-%Y"), b=to.strftime("%d-%m-%Y")),
                             BM_REFERER)
        items = body if isinstance(body, list) else (body.get("data") if isinstance(body, dict) else None)
        chunks += 1
        if items is None:
            failed += 1
        else:
            seen += len(items)
            for it in items:
                if not isinstance(it, dict) or not _is_results_meeting(it):
                    continue
                sym = (it.get("bm_symbol") or "").strip().upper()
                d = L.parse_nse_date(it.get("bm_date"))
                if sym and d:
                    found.setdefault(sym, set()).add(d.isoformat())
        body = items = None
        cur = to + timedelta(days=1)
    if chunks and failed == chunks:
        raise RuntimeError("NSE's board-meetings feed refused every request")

    existing = {d["_id"]: set(d.get("meetings") or [])
                async for d in rows.find({"_id": {"$in": list(found)}}, {"meetings": 1})}
    ops = []
    for sym, dates in found.items():
        if sym not in existing:
            continue                                    # SME or not a listed equity
        merged = existing[sym] | dates
        if merged != existing[sym]:
            ops.append(UpdateOne({"_id": sym}, {"$set": {"meetings": sorted(merged)[-12:]}}))
    await _bulk(ops)
    await meta.replace_one({"_id": "meetings"}, {
        "_id": "meetings", "at": _now(), "from": start.isoformat(), "to": end.isoformat(),
        "chunks": chunks, "failed_chunks": failed, "rows_seen": seen,
        "symbols": len(found), "rows_updated": len(ops)}, upsert=True)
    logger.info("nse ratings meetings %s..%s: %d results meetings for %d symbols, %d rows updated",
                start, end, sum(len(v) for v in found.values()), len(found), len(ops))
    return {"symbols": len(found), "updated": len(ops), "chunks": chunks, "failed": failed}


# ── the date-dependent fields ────────────────────────────────────────────────────


async def reevaluate(force: bool = False) -> dict:
    """Recompute freshness, pending and the overall for rows whose inputs have aged."""
    today = _ist_now().date()
    query = {} if force else {"t_day": {"$ne": today.isoformat()}}
    ops, seen = [], 0
    async for d in rows.find(query, TIME_PROJ):
        seen += 1
        t = L.time_fields(d, today)
        if any(d.get(k) != t[k] for k in TIME_KEYS):
            ops.append(UpdateOne({"_id": d["_id"]}, {"$set": t}))
        if len(ops) >= 500:
            await _bulk(ops)
            ops = []
    await _bulk(ops)
    return {"checked": seen}


# ── rows from the cached pages ───────────────────────────────────────────────────


async def sync_from_cache(force_all: bool = False) -> dict:
    """Rebuild rows whose cached screener.in page is newer than the row. No fetching.

    This is how a Rate-tab paste or a Universe scan reaches this table: they write the
    cache, and the next cycle notices.
    """
    ctx = {d["_id"]: d async for d in rows.find({}, CTX_PROJ)}
    cache_at = {d["_id"]: L.aware(d.get("fetched_at"))
                async for d in screener_fundamentals_collection.find(
                    {"_id": {"$in": list(ctx)}}, {"fetched_at": 1})}
    today = _ist_now().date()
    todo, ops = [], []
    for sym, d in ctx.items():
        cached = cache_at.get(sym)
        if cached is None:
            if d.get("v") != L.ROW_VERSION:             # never read: say so on the row
                ops.append(UpdateOne({"_id": sym}, {"$set": {
                    "v": L.ROW_VERSION, **L.time_fields(d, today)}}))
            continue
        mine = L.aware(d.get("fetched_at"))
        if force_all or d.get("v") != L.ROW_VERSION or mine is None or cached > mine + timedelta(seconds=1):
            todo.append(sym)
    await _bulk(ops)

    rebuilt = 0
    for i in range(0, len(todo), 20):
        batch, ops = todo[i:i + 20], []
        async for data in screener_fundamentals_collection.find({"_id": {"$in": batch}}, CACHE_PROJ):
            sym = data["_id"]
            try:
                r, q, p = _score(data)
                ops.append(UpdateOne({"_id": sym}, {"$set": _build(ctx[sym], data, r, q, p)}))
            except Exception:                               # one odd page must not stop the pass
                logger.exception("nse ratings: rebuilding %s failed", sym)
        rebuilt += await _bulk(ops)
        status["note"] = f"rebuilding rows from cached pages: {min(i + 20, len(todo))} of {len(todo)}"
        await asyncio.sleep(0)
    status["note"] = None
    return {"rebuilt": rebuilt, "candidates": len(todo)}


# ── reading screener.in again ────────────────────────────────────────────────────


async def _fetch(symbol: str, client: httpx.AsyncClient | None, force: bool) -> dict:
    """screener.in with the Universe scan's rate-limit backoff. Raises RateLimited."""
    attempt = 0
    while True:
        try:
            return await screener_in.get_fundamentals(symbol, force=force, client=client)
        except screener_in.ScreenerError as exc:
            if "rate-limit" not in exc.detail.lower():
                raise
            attempt += 1
            if attempt > fundamental_universe.MAX_RETRIES:
                raise RateLimited() from exc
            status["note"] = f"screener.in rate limit on {symbol}; waiting {COOLDOWN * attempt:.0f}s"
            await asyncio.sleep(COOLDOWN * attempt)
            status["note"] = None


async def refresh_one(symbol: str, client: httpx.AsyncClient | None = None,
                      reason: str = "manual", force: bool = True) -> dict:
    """Read one company from screener.in, rate it, and store both tabs' rows."""
    sym = screener_in.normalise_symbol(symbol)
    row = await rows.find_one({"_id": sym}, {**CTX_PROJ, "pending_key": 1})
    if row is None:
        raise KeyError(sym)
    ref = row.get("refresh") or {}
    key = (row.get("pending_key") if reason == "results" else None) or reason
    attempts = (ref.get("attempts", 0) + 1) if ref.get("key") == key else 1
    refresh_doc = {"key": key, "attempts": attempts, "last_try": _now(), "reason": reason}
    try:
        data = await _fetch(sym, client, force)
    except screener_in.ScreenerError as exc:
        upd = {"fetch_error": exc.detail, "refresh": refresh_doc, "v": L.ROW_VERSION}
        upd.update(L.time_fields({**row, **upd}, _ist_now().date()))
        await rows.update_one({"_id": sym}, {"$set": upd})
        return {"ok": False, "error": exc.detail, "live": True}
    r, q, p = _score(data)
    await _store_universe_row(sym, r, q, p, row)
    doc = _build(row, data, r, q, p)
    doc["refresh"] = refresh_doc
    await rows.update_one({"_id": sym}, {"$set": doc})
    return {"ok": True, "live": not data.get("cached"), "quarter": doc.get("qlabel"),
            "pending": doc.get("pending")}


async def refresh_due(budget_seconds: float = REFRESH_BUDGET) -> dict:
    """Work through what is due, newest results first, Nifty 50 before smaller names."""
    now = _ist_now()
    queue = []
    async for d in rows.find({"listed": True}, {
            "listed": 1, "fetched_at": 1, "fetch_error": 1, "pending": 1, "pending_key": 1,
            "last_meeting": 1, "freshness": 1, "refresh": 1, "idx_rank": 1, "mcap": 1}):
        why = L.refresh_reason(d, now)
        if why:
            queue.append((why[0], d.get("idx_rank") or 9, -(d.get("mcap") or 0), d["_id"], why[1]))
    queue.sort()
    reasons = Counter(q[4] for q in queue)
    status.update(queue=len(queue), done=0, ok=0, failed=0, current=None,
                  queue_reasons=dict(reasons))
    if not queue:
        return {"queue": 0}

    started = time.monotonic()
    stopped = None
    async with httpx.AsyncClient(timeout=screener_in.TIMEOUT, follow_redirects=True,
                                 headers=screener_in.BROWSER_HEADERS) as client:
        for n, (_prio, _rank, _cap, sym, reason) in enumerate(queue):
            if time.monotonic() - started > budget_seconds:
                stopped = "time budget used; continuing next cycle"
                break
            if n % 5 == 0:
                if not await is_on(SWITCH):
                    stopped = "Fundamental Rating switched off in Main Control"
                    break
                if (await fundamental_universe.status()).get("running"):
                    stopped = "paused while a Universe scan runs"
                    break
            status["current"] = sym
            try:
                res = await refresh_one(sym, client=client, reason=reason)
            except RateLimited:
                stopped = "screener.in rate limit; resuming next cycle"
                break
            except Exception as exc:                       # noqa: BLE001
                logger.exception("nse ratings: refreshing %s failed", sym)
                res = {"ok": False, "live": False, "error": f"{type(exc).__name__}: {exc}"}
            status["done"] += 1
            status["ok" if res.get("ok") else "failed"] += 1
            if res.get("live"):
                await asyncio.sleep(PACE_SECONDS)
    status["current"] = None
    status["note"] = stopped
    logger.info("nse ratings refresh: %d of %d due done (%d ok, %d failed)%s", status["done"],
                len(queue), status["ok"], status["failed"], f"; {stopped}" if stopped else "")
    return {"queue": len(queue), "done": status["done"], "ok": status["ok"],
            "failed": status["failed"], "stopped": stopped, "reasons": dict(reasons)}


# ── price returns ────────────────────────────────────────────────────────────────


async def _bhav(day: date, cache: dict) -> dict | None:
    """{symbol: (close, prev_close)} for EQ/BE/BZ on `day`, or None when NSE has no file."""
    if day in cache:
        return cache[day]
    resp = await nse.get(BHAV.format(ddmmyyyy=day.strftime("%d%m%Y")), tries=2)
    out = None
    if resp is not None:
        got = {}
        for raw in csv.DictReader(io.StringIO(resp.text)):
            x = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
            if x.get("SERIES") not in KEEP_SERIES:
                continue
            sym, close = x.get("SYMBOL", "").upper(), L.num(x.get("CLOSE_PRICE"))
            if sym and close:
                got[sym] = (close, L.num(x.get("PREV_CLOSE")))
        out = got if len(got) > 500 else None          # a block page is not a market
    cache[day] = out
    return out


def _maybe_session(d: date) -> bool:
    return d.weekday() < 5 and market_calendar.is_listed_trading_day(d)


async def _bhav_on_or_before(day: date, cache: dict, tries: int = 8) -> tuple[date | None, dict | None]:
    d = day
    for _ in range(tries):
        if _maybe_session(d):
            got = await _bhav(d, cache)
            if got:
                return d, got
        d -= timedelta(days=1)
    return None, None


async def _bhav_after(day: date, limit: date, cache: dict, tries: int = 8) -> dict | None:
    d = day + timedelta(days=1)
    for _ in range(tries):
        if d > limit:
            return None
        if _maybe_session(d):
            got = await _bhav(d, cache)
            if got:
                return got
        d += timedelta(days=1)
    return None


async def _corporate_actions(frm: date, to: date) -> dict[str, list[dict]] | None:
    body = await nse.api(CA_API.format(a=frm.strftime("%d-%m-%Y"), b=to.strftime("%d-%m-%Y")),
                         CA_REFERER)
    items = body if isinstance(body, list) else (body.get("data") if isinstance(body, dict) else None)
    if items is None:
        return None
    out: dict[str, list[dict]] = {}
    for it in items:
        if not isinstance(it, dict) or (it.get("series") or "EQ") not in KEEP_SERIES:
            continue
        act = L.parse_action(it.get("subject") or "")
        ex = L.parse_nse_date(it.get("exDate"))
        sym = (it.get("symbol") or "").strip().upper()
        if act and ex and sym:
            out.setdefault(sym, []).append({**act, "ex": ex, "subject": it.get("subject")})
    return out


async def _symbol_changes(since: date) -> dict[str, list[tuple[str, date]]]:
    """new symbol -> [(old symbol, effective date)] for changes on or after `since`."""
    resp = await nse.get(SYMBOL_CHANGES, tries=2)
    out: dict[str, list[tuple[str, date]]] = {}
    if resp is None:
        return out
    for raw in csv.DictReader(io.StringIO(resp.text)):
        x = {(k or "").strip().upper(): (v or "").strip() for k, v in raw.items()}
        old, new = x.get("OLD SYMBOL", "").upper(), x.get("NEW SYMBOL", "").upper()
        eff = L.parse_nse_date(x.get("EFFECTIVE DATE"))
        if old and new and eff and eff >= since:
            out.setdefault(new, []).append((old, eff))
    return out


def _names(sym: str, changes: dict, after: date | None = None) -> list[str]:
    """The symbol, then the names it traded under before a change after `after`."""
    names, frontier = [sym], [sym]
    for _ in range(3):
        nxt = []
        for s in frontier:
            for old, eff in changes.get(s, []):
                if (after is None or eff > after) and old not in names:
                    names.append(old)
                    nxt.append(old)
        frontier = nxt
    return names


def _expected_close_day(now: datetime) -> date:
    d = now.date()
    if _maybe_session(d) and now.strftime("%H:%M") >= RETURNS_AFTER_HHMM:
        return d
    d -= timedelta(days=1)
    while not _maybe_session(d):
        d -= timedelta(days=1)
    return d


async def refresh_returns(force: bool = False) -> dict:
    """3M / 6M / 1Y / 2Y price returns for every listed row, as of the latest bhavcopy."""
    cache: dict[date, dict | None] = {}
    latest_day, latest = await _bhav_on_or_before(_expected_close_day(_ist_now()), cache)
    if not latest:
        raise RuntimeError("no NSE bhavcopy found in the last week")
    stored = await meta.find_one({"_id": "returns"}, {"as_of": 1, "v": 1})
    if (not force and stored and stored.get("as_of") == latest_day.isoformat()
            and stored.get("v") == L.ROW_VERSION):
        # Tonight's file is not out yet; what is stored is already as of the last close.
        await meta.update_one({"_id": "returns"}, {"$set": {"checked_at": _now()}})
        return {"skipped": f"no bhavcopy newer than {latest_day.isoformat()}"}
    prev_day, prev = await _bhav_on_or_before(latest_day - timedelta(days=1), cache)

    anchors: dict[str, tuple[date | None, dict | None, dict | None]] = {}
    for key, months, _label in L.HORIZONS:
        ad, adata = await _bhav_on_or_before(L.months_back(latest_day, months), cache)
        ndata = await _bhav_after(ad, latest_day, cache) if ad else None
        anchors[key] = (ad, adata, ndata)

    since = L.months_back(latest_day, 24) - timedelta(days=10)
    ca = await _corporate_actions(since, latest_day)
    if ca is None:
        raise RuntimeError("NSE's corporate-actions feed did not answer; returns not recomputed")
    changes = await _symbol_changes(since)

    ops, covered = [], 0
    async for d in rows.find({"listed": True}, {"listed_on": 1, "screener_1y": 1, "fetched_at": 1}):
        sym = d["_id"]
        all_names = _names(sym, changes)
        lt = None
        for day_, data in ((latest_day, latest), (prev_day, prev)):
            hit = next((data[n][0] for n in all_names if data and n in data), None)
            if hit:
                lt = (day_, hit)
                break
        vals = {}
        for key, (ad, adata, ndata) in anchors.items():
            if ad is None:
                vals[key] = (None, None)
                continue
            close = None
            for n in _names(sym, changes, after=ad):
                close = (adata or {}).get(n, (None, None))[0] or (ndata or {}).get(n, (None, None))[1]
                if close:
                    break
            vals[key] = (ad, close)
        acts = [a for n in all_names for a in ca.get(n, [])]
        res = L.compute_returns(lt, vals, acts, L.as_date(d.get("listed_on")))
        res["ret_asof"] = lt[0].isoformat() if lt else None
        # Only re-judged while the screener.in read is recent. Otherwise the verdict made
        # at the read stands until the next read (see screener_check).
        fetched = L.as_date(d.get("fetched_at"))
        if lt and fetched and abs((lt[0] - fetched).days) <= 4:
            res["ret_check"] = L.screener_check({**d, **res}, lt[0])
        covered += res.get("r1y") is not None
        ops.append(UpdateOne({"_id": sym}, {"$set": res}))
    await _bulk(ops)
    doc = {"_id": "returns", "at": _now(), "checked_at": _now(),
           "as_of": latest_day.isoformat(), "v": L.ROW_VERSION,
           "anchors": {k: (v[0].isoformat() if v[0] else None) for k, v in anchors.items()},
           "files_read": sum(1 for v in cache.values() if v), "actions_symbols": len(ca),
           "symbol_changes": sum(len(v) for v in changes.values()),
           "rows": len(ops), "with_1y": covered, "last_error": None}
    await meta.replace_one({"_id": "returns"}, doc, upsert=True)
    logger.info("nse ratings returns as of %s: %d rows, %d with a 1Y return, %d bhavcopies read",
                latest_day, len(ops), covered, doc["files_read"])
    return {k: v for k, v in doc.items() if k != "_id"}


# ── the loop ─────────────────────────────────────────────────────────────────────


def _age_h(doc: dict | None, field: str = "at") -> float | None:
    at = L.aware((doc or {}).get(field))
    return (_now() - at).total_seconds() / 3600 if at else None


async def _step(name: str, fn, *args, **kwargs):
    status["step"] = name
    try:
        res = await fn(*args, **kwargs)
        await meta.delete_one({"_id": f"{name}_error"})
        return res
    except Exception as exc:                               # each step fails alone
        logger.exception("nse ratings step %s failed", name)
        status["last_error"] = f"{name}: {type(exc).__name__}: {exc}"
        await meta.update_one({"_id": f"{name}_error"},
                              {"$set": {"at": _now(), "error": status["last_error"]}}, upsert=True)
        return None
    finally:
        status["step"] = None


async def _error_recent(name: str, hours: float) -> bool:
    age = _age_h(await meta.find_one({"_id": f"{name}_error"}))
    return age is not None and age < hours


async def run_cycle(force: frozenset[str] = frozenset()) -> dict:
    """One pass of every job that is due. Runs one at a time."""
    if _cycle_lock.locked():
        return {"started": False}
    async with _cycle_lock:
        status.update(running=True, started_at=_now(), finished_at=None, last_error=None)
        out: dict = {}
        try:
            univ = await meta.find_one({"_id": "universe"}, {"at": 1})
            if "universe" in force or univ is None or (_age_h(univ) or 0) > 24 * 7:
                if "universe" in force or not await _error_recent("universe", 6):
                    out["universe"] = await _step("universe", refresh_universe)

            meet = await meta.find_one({"_id": "meetings"}, {"at": 1})
            meetings_ran = False
            if "meetings" in force or meet is None or (_age_h(meet) or 0) > 6:
                if "meetings" in force or not await _error_recent("meetings", 1):
                    back = 100 if (meet is None or "meetings" in force) else 10
                    out["meetings"] = await _step("meetings", refresh_meetings, back, 35)
                    meetings_ran = out["meetings"] is not None

            out["sync"] = await _step("sync", sync_from_cache, force_all="rebuild" in force)

            ret = await meta.find_one({"_id": "returns"}, {"as_of": 1, "v": 1, "checked_at": 1})
            want = _expected_close_day(_ist_now()).isoformat()
            stale = ret is None or ret.get("as_of") != want or ret.get("v") != L.ROW_VERSION
            checked_h = _age_h(ret, "checked_at")
            if "returns" in force or (stale and (checked_h is None or checked_h > 0.5)
                                      and not await _error_recent("returns", 1)):
                out["returns"] = await _step("returns", refresh_returns, force="returns" in force)

            out["reevaluate"] = await _step("reevaluate", reevaluate, force=meetings_ran)
            if "norefresh" not in force:
                out["refresh"] = await _step("refresh", refresh_due)
        finally:
            status.update(running=False, finished_at=_now(), last_cycle=out)
            try:
                await meta.replace_one({"_id": "status"}, {
                    "_id": "status", **{k: v for k, v in status.items() if k != "running"}},
                    upsert=True)
            except Exception:                              # noqa: BLE001
                logger.warning("nse ratings: status not persisted")
        return {"started": True, **out}


async def loop() -> None:
    """Started once at app startup by the fundamentals router; never raises."""
    await asyncio.sleep(START_DELAY)
    while True:
        try:
            if await is_on(SWITCH):
                await run_cycle()
        except Exception:                                  # noqa: BLE001
            logger.exception("nse ratings cycle failed")
        await asyncio.sleep(CYCLE_SECONDS)


async def trigger(what: str) -> dict:
    """Run a cycle now in the background; `what` forces one step even if it is not due."""
    if not await is_on(SWITCH):
        return {"started": False, "reason": "Fundamental Rating is switched off in Main Control."}
    if _cycle_lock.locked():
        return {"started": False, "reason": "A refresh cycle is already running.",
                "status": status_view()}
    force = frozenset({what}) if what in ("universe", "meetings", "returns", "rebuild") else frozenset()

    async def run():
        try:
            await run_cycle(force)
        except Exception:                                  # noqa: BLE001
            logger.exception("nse ratings manual cycle failed")

    asyncio.create_task(run())
    return {"started": True, "what": what}


def status_view() -> dict:
    return {k: v for k, v in status.items() if k != "last_cycle"} | {
        "last_cycle": status.get("last_cycle")}


# ── reading the table ────────────────────────────────────────────────────────────


def _query(search=None, index=None, sector=None, ratings=None, quarter=None, data=None,
           include_delisted=False) -> dict:
    q: dict = {} if include_delisted else {"listed": True}
    clauses = []
    if index:
        q["indices"] = index
    if sector:
        q["sector"] = sector
    if ratings:
        q["ovr_key"] = {"$in": ratings}
    if quarter in QUARTER_FILTERS:
        clauses.append(QUARTER_FILTERS[quarter][1])
    if data in DATA_FILTERS:
        clauses.append(DATA_FILTERS[data][1])
    if search and search.strip():
        s = search.strip()
        clauses.append({"$or": [
            {"_id": {"$regex": re.escape(screener_in.normalise_symbol(s) or s.upper())}},
            {"name": {"$regex": re.escape(s), "$options": "i"}},
            {"screener_name": {"$regex": re.escape(s), "$options": "i"}}]})
    if clauses:
        q["$and"] = clauses
    return q


async def browse(search=None, index=None, sector=None, ratings=None, quarter=None, data=None,
                 sort="overall", order="desc", page=1, page_size=50, fields=None,
                 include_delisted=False) -> dict:
    q = _query(search, index, sector, ratings, quarter, data, include_delisted)
    total = await rows.count_documents(q)
    field = SORTS.get(sort, "overall")
    direction = 1 if order == "asc" else -1
    proj = {"ovr_key": 1, "ovr_tier": 1, "overall": 1} if fields == "export" else {f: 1 for f in TABLE_FIELDS}
    # Missing values sort LAST whichever way the column is sorted. Mongo's own order puts
    # nulls first going up, which would open an ascending P/E sort on a page of dashes.
    order_by = {"_null": 1, field: direction} if field == "_id" else {"_null": 1, field: direction, "_id": 1}
    pipeline = [
        {"$match": q},
        {"$addFields": {"_null": {"$cond": [{"$eq": [{"$ifNull": [f"${field}", None]}, None]}, 1, 0]}}},
        {"$sort": order_by},
        {"$skip": (page - 1) * page_size},
        {"$limit": page_size},
        {"$project": proj},
    ]
    out = [_clean(d) async for d in rows.aggregate(pipeline)]
    return {"rows": out, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size)), "sort": sort if sort in SORTS else "overall",
            "order": "asc" if direction == 1 else "desc"}


async def summary() -> dict:
    """Counts for the header and the filters, plus where every job stands."""
    global _summary_cache
    if _summary_cache and time.monotonic() - _summary_cache[0] < 30:
        base = _summary_cache[1]
    else:
        counts = Counter()
        by_index, by_sector, by_rating, by_quarter, by_series = (Counter() for _ in range(5))
        async for d in rows.find({"listed": True}, {
                "indices": 1, "sector": 1, "ovr_key": 1, "freshness": 1, "pending": 1,
                "quarter": 1, "fetched_at": 1, "fetch_error": 1, "series": 1}):
            counts["listed"] += 1
            for k in d.get("indices") or []:
                by_index[k] += 1
            by_sector[d.get("sector") or "Unclassified"] += 1
            by_rating[d.get("ovr_key") or L.INSUFFICIENT_KEY] += 1
            by_quarter[L.quarter_band(d.get("quarter"))] += 1
            by_series[d.get("series") or "?"] += 1
            counts[f"fresh_{d.get('freshness') or 'unknown'}"] += 1
            counts["pending"] += bool(d.get("pending"))
            counts["never_read"] += d.get("fetched_at") is None
            counts["errors"] += d.get("fetch_error") is not None
        counts["insufficient"] = by_rating.get(L.INSUFFICIENT_KEY, 0)
        counts["rated"] = counts["listed"] - counts["insufficient"]
        base = {
            "counts": dict(counts),
            "indices": [{"key": k, "label": lbl, "count": by_index.get(k, 0)} for k, lbl in L.INDEX_FILTERS],
            "sectors": [{"key": k, "count": v} for k, v in sorted(by_sector.items(), key=lambda x: -x[1])],
            "ratings": dict(by_rating),
            "quarter_bands": dict(by_quarter),
            "series": dict(by_series),
            "quarter_filters": [{"key": k, "label": v[0]} for k, v in QUARTER_FILTERS.items()],
            "data_filters": [{"key": k, "label": v[0]} for k, v in DATA_FILTERS.items()],
        }
        _summary_cache = (time.monotonic(), base)

    docs = {d["_id"]: d async for d in meta.find({"_id": {"$in": [
        "universe", "meetings", "returns", "status", "universe_error", "meetings_error",
        "returns_error"]}}, {"slices": 0, "sectors": 0})}
    persisted = docs.get("status") or {}
    live = status_view()
    return {
        **base,
        "jobs": {
            "universe": docs.get("universe"), "meetings": docs.get("meetings"),
            "returns": docs.get("returns"),
            "errors": {k.replace("_error", ""): v.get("error") for k, v in docs.items()
                       if k.endswith("_error") and v.get("error")},
        },
        "status": live if (live["running"] or live.get("finished_at")) else
        {k: v for k, v in persisted.items() if k != "_id"},
        "methodology": L.METHODOLOGY,
        "sources": {
            "companies": "NSE EQUITY_L.csv (mainboard EQ, BE, BZ series)",
            "indices": "niftyindices.com constituent lists",
            "fundamentals": "screener.in company pages (consolidated where published)",
            "results_dates": "NSE corporate board-meetings feed",
            "returns": "NSE bhavcopy closes + NSE corporate actions",
        },
    }


RATING_KEYS = ("score", "grade", "grade_key", "tier", "verdict", "band", "coverage", "is_lender",
               "pillars", "skipped", "summary", "screener_pros", "screener_cons", "basis",
               "source_url", "data_missing", "sector", "industry", "name")


async def detail(symbol: str) -> dict | None:
    """One row with the calculation behind it, recomputed from the cached page."""
    sym = screener_in.normalise_symbol(symbol)
    row = await rows.find_one({"_id": sym}, {"refresh": 0})
    if row is None:
        return None
    data = await screener_fundamentals_collection.find_one({"_id": sym}, {"ratios_table": 0})
    out = {"row": None, "rating": None, "results": None, "pnl": None, "brief": None,
           "statements": None, "about": None,
           "weights": L.OVERALL_WEIGHTS}
    if data:
        r, q, p = _score(data)
        r["symbol"] = sym
        cached, mine = L.aware(data.get("fetched_at")), L.aware(row.get("fetched_at"))
        # The page moved on since the row was built (a Rate-tab read): rebuild it now so
        # the drawer and the table describe the same page.
        if cached and (mine is None or cached > mine + timedelta(seconds=1) or row.get("v") != L.ROW_VERSION):
            doc = _build(row, data, r, q, p)
            await rows.update_one({"_id": sym}, {"$set": doc})
            row.update(doc)
        out["rating"] = {k: r.get(k) for k in RATING_KEYS}
        out["results"] = q
        out["pnl"] = p
        out["brief"] = fundamental_brief.compose(r, q, p).get("brief")
        out["statements"] = {
            "quarters": data.get("quarters") or {}, "quarters_periods": data.get("quarters_periods") or [],
            "profit_loss": data.get("profit_loss") or {},
            "profit_loss_periods": data.get("profit_loss_periods") or [],
        }
        out["about"] = data.get("about")
    row.pop("meetings", None)
    out["row"] = _clean(row)
    return out
