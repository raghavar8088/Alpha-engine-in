"""Fundamental Rating — paste stocks, get a 1-10 verdict off screener.in.

  POST /api/fundamentals/rate      {"symbols": "RELIANCE, TCS" | ["RELIANCE"], "force": false}
  GET  /api/fundamentals/{symbol}  one company, rating + the parsed statements behind it
  GET  /api/fundamentals/recent    what was rated lately, newest first

  GET  /api/fundamentals/nse-ratings                every NSE-listed stock, filtered + sorted
  GET  /api/fundamentals/nse-ratings/summary        counts, filters, job status, methodology
  GET  /api/fundamentals/nse-ratings/stock/{sym}    one row with the calculation behind it
  POST /api/fundamentals/nse-ratings/stock/{sym}/refresh   read screener.in again now
  POST /api/fundamentals/nse-ratings/refresh        {"what": "due" | "universe" | "meetings"
                                                     | "returns" | "rebuild"}

`symbols` takes either the raw pasted text or an already-split list; the service does the
splitting so the UI never has to guess at the user's separators.

Live fetches are paced and capped at MAX_SYMBOLS per request. That cap exists for
screener.in's sake as much as ours: a 200-symbol paste would be 200 page loads against a
free public site. Anything already cached inside the day does not re-fetch, so a second
pass over the same basket returns immediately.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.core.db import fundamental_ratings_collection
from app.services import (
    fundamental_brief,
    fundamental_universe,
    fundamental_watchlist,
    nse_ratings,
    pnl_strength,
    results_strength,
    screener_in,
)
from app.services.fundamental_rating import PILLARS, PILLAR_LABELS, rate
from app.services.grades import ORDER as GRADE_ORDER, scale as grade_scale

router = APIRouter(prefix="/api/fundamentals", tags=["fundamentals"])
logger = logging.getLogger("fundamentals")

MAX_SYMBOLS = 40


async def _start_nse_ratings_loop() -> None:
    """The NSE Stock Ratings refresher, started with this router (see nse_ratings).

    Registered here rather than in main.py so the tab ships as one module. It is an
    ordinary startup handler, so FastAPI's include_router hands it to the app.
    """
    if os.getenv("NSE_RATINGS_ENABLED", "1") == "0":
        logger.info("NSE Stock Ratings refresher disabled (NSE_RATINGS_ENABLED=0)")
        return
    try:
        asyncio.create_task(nse_ratings.loop())
        logger.info("NSE Stock Ratings refresher started: first cycle in %.0fs, then every %.0fs",
                    nse_ratings.START_DELAY, nse_ratings.CYCLE_SECONDS)
    except Exception:                                    # a startup hook must never raise
        logger.exception("NSE Stock Ratings refresher failed to start")


router.add_event_handler("startup", _start_nse_ratings_loop)


def _clean(doc: dict | None) -> dict | None:
    if doc:
        doc.pop("_id", None)
    return doc


def _statements(f: dict) -> dict:
    """The two tables the user reads alongside the score, shaped for direct rendering.

    Sent with every rating rather than fetched on expand: the page already has the parsed
    document in hand, and a second round trip per company to redraw a table we have already
    read would be slower and would hit screener.in again for nothing.
    """
    return {
        "quarters": f.get("quarters") or {},
        "quarters_periods": f.get("quarters_periods") or [],
        "profit_loss": f.get("profit_loss") or {},
        "profit_loss_periods": f.get("profit_loss_periods") or [],
        "ranges": f.get("ranges") or {},
    }


@router.get("/methodology")
async def methodology(_current_user: dict = Depends(get_current_user)):
    """What the score is made of — so the UI can show the rules, not just the number."""
    return {
        "pillars": [{"pillar": k, "label": PILLAR_LABELS[k], "weight": w}
                    for k, w in PILLARS.items()],
        "bands": [
            {"from": 8.5, "to": 10.0, "verdict": "Fundamentally strong", "band": "strong"},
            {"from": 7.0, "to": 8.4, "verdict": "Good, with minor blemishes", "band": "good"},
            {"from": 5.5, "to": 6.9, "verdict": "Mixed — strengths and real weaknesses", "band": "mixed"},
            {"from": 4.0, "to": 5.4, "verdict": "Fundamentally weak", "band": "weak"},
            {"from": 1.0, "to": 3.9, "verdict": "Fundamentally poor", "band": "poor"},
        ],
        "note_on_three_grades":
            "The same nine-tier scale is applied three times: to the company overall, to "
            "its latest quarter, and to its multi-year P&L record. They are reported "
            "separately and often disagree — a company can post an explosive quarter on a "
            "below-average decade, and that is worth seeing rather than averaging away.",
        "grades": {
            "company": grade_scale("company"),
            "quarter": grade_scale("quarter"),
            "pnl": grade_scale("pnl"),
        },
        "source": "screener.in",
        "cache_hours": screener_in.CACHE_HOURS,
        "max_symbols": MAX_SYMBOLS,
        "notes": [
            "A pillar with no data is dropped and its weight shared across the rest, never "
            "scored as a zero. `coverage` says how much of the intended weight had data.",
            "Banks and NBFCs are scored on ROE and net margin; the debt and cash-conversion "
            "pillars are skipped because borrowing is a lender's raw material.",
            "This reads public filings only. It cannot see governance, related-party "
            "dealings or what the business does next. Research aid, not advice.",
        ],
    }


@router.get("/universe/scopes")
async def universe_scopes(_current_user: dict = Depends(get_current_user)):
    """Which indices and sectors can be scanned, and how many stocks in each."""
    return await fundamental_universe.scopes()


@router.get("/universe/scan/status")
async def universe_scan_status(_current_user: dict = Depends(get_current_user)):
    return await fundamental_universe.status()


@router.post("/universe/scan")
async def universe_scan(payload: dict = Body(default={}),
                        _current_user: dict = Depends(get_current_user)):
    """Start rating a whole index or sector in the background."""
    scope_type = (payload.get("type") or "index").strip()
    scope_key = (payload.get("key") or "").strip()
    if scope_type not in ("index", "sector", "watchlist"):
        raise HTTPException(status_code=400,
                            detail="type must be 'index', 'sector' or 'watchlist'.")
    if not scope_key:
        raise HTTPException(status_code=400, detail="Pick an index or a sector to scan.")
    return await fundamental_universe.start(scope_type, scope_key, bool(payload.get("force")))


@router.post("/universe/scan/cancel")
async def universe_scan_cancel(_current_user: dict = Depends(get_current_user)):
    return await fundamental_universe.cancel()


@router.get("/universe/stocks")
async def universe_stocks(
    index: str | None = None,
    sector: str | None = None,
    min_score: float | None = None,
    min_results: float | None = None,
    min_pnl: float | None = None,
    grades: str | None = Query(None, description="Comma-separated grade keys."),
    search: str | None = None,
    sort: str = "score",
    limit: int = Query(600, ge=1, le=2000),
    _current_user: dict = Depends(get_current_user),
):
    """The stored ratings, filtered — this is what the stock picker reads."""
    keys = [g for g in (grades or "").split(",") if g in GRADE_ORDER] or None
    return await fundamental_universe.browse(
        index=index, sector=sector, min_score=min_score, min_results=min_results,
        min_pnl=min_pnl, grades=keys, search=search, sort=sort, limit=limit)


@router.get("/watchlists")
async def list_watchlists(_current_user: dict = Depends(get_current_user)):
    return {"watchlists": await fundamental_watchlist.watchlists()}


@router.post("/watchlists")
async def save_watchlist(payload: dict = Body(...),
                         _current_user: dict = Depends(get_current_user)):
    """Create or replace a named list. Takes pasted TradingView text as-is."""
    try:
        return await fundamental_watchlist.save_watchlist(
            payload.get("name") or "", payload.get("symbols") or "")
    except fundamental_watchlist.WatchlistError as exc:
        raise HTTPException(status_code=400, detail=exc.detail)


@router.post("/watchlists/from-filter")
async def watchlist_from_filter(payload: dict = Body(...),
                                _current_user: dict = Depends(get_current_user)):
    """Save everything matching a set of filters as a named watchlist.

    The point is repeatability: grades move as companies report, so "the excellent and
    above names in the broad market" is a QUERY, not a list someone pasted once. Re-running
    this rebuilds the list against whatever the ratings say today.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the watchlist a name.")
    keys = [g for g in (payload.get("grades") or []) if g in GRADE_ORDER]
    res = await fundamental_universe.browse(
        index=payload.get("index"), sector=payload.get("sector"),
        min_score=payload.get("min_score"), min_results=payload.get("min_results"),
        min_pnl=payload.get("min_pnl"), grades=keys or None,
        sort="score", limit=int(payload.get("limit") or 2000),
        top_by_market_cap=payload.get("top_by_market_cap"))
    symbols = [s["symbol"] for s in res["stocks"]]
    if not symbols:
        raise HTTPException(status_code=400,
                            detail="Nothing matches those filters yet — scan the universe first.")
    try:
        wl = await fundamental_watchlist.save_watchlist(name, " ".join(symbols))
    except fundamental_watchlist.WatchlistError as exc:
        raise HTTPException(status_code=400, detail=exc.detail)
    return {**wl, "matched": len(symbols), "filters": {"grades": keys,
                                                       "index": payload.get("index"),
                                                       "sector": payload.get("sector")}}


@router.post("/universe/refresh-broad")
async def refresh_broad(_current_user: dict = Depends(get_current_user)):
    """Re-pull the wide NSE constituent lists (Total Market, Microcap 250)."""
    return await fundamental_universe.refresh_broad_universe()


@router.post("/universe/refresh-rest")
async def refresh_rest(_current_user: dict = Depends(get_current_user)):
    """Seed every EQ-series NSE equity that sits outside Nifty Total Market."""
    return await fundamental_universe.refresh_nse_rest()


@router.delete("/watchlists/{name}")
async def remove_watchlist(name: str, _current_user: dict = Depends(get_current_user)):
    return await fundamental_watchlist.delete_watchlist(name)


@router.post("/watchlists/{name}/fund")
async def fund_watchlist(name: str, payload: dict = Body(default={}),
                         _current_user: dict = Depends(get_current_user)):
    """Open a paper position of `per_stock` rupees in every name not already held."""
    try:
        per = float(payload.get("per_stock") or fundamental_watchlist.DEFAULT_PER_STOCK)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="per_stock must be a number.")
    try:
        r = await fundamental_watchlist.fund(name, per)
    except fundamental_watchlist.WatchlistError as exc:
        raise HTTPException(status_code=404, detail=exc.detail)
    await fundamental_watchlist.mark(name)
    return r


@router.get("/watchlists/{name}/book")
async def watchlist_book(name: str, refresh: bool = False,
                         _current_user: dict = Depends(get_current_user)):
    """The paper book: every position, and the per-grade-tier aggregate."""
    if refresh:
        try:
            await fundamental_watchlist.mark(name)
        except Exception:                                # a stale mark beats a 500
            pass
    return await fundamental_watchlist.summary(name)


@router.get("/watchlists/{name}/daily")
async def watchlist_daily(name: str, limit: int = Query(120, ge=1, le=500),
                          _current_user: dict = Depends(get_current_user)):
    """One row per session: the book's day, and each tier's day."""
    return await fundamental_watchlist.daily(name, limit)


@router.post("/watchlists/{name}/snapshot")
async def watchlist_snapshot(name: str, force: bool = False,
                             _current_user: dict = Depends(get_current_user)):
    """Write today's row now instead of waiting for the post-close tick."""
    await fundamental_watchlist.mark(name)
    return await fundamental_watchlist.snapshot(name, force=force)


@router.get("/recent")
async def recent(limit: int = Query(50, ge=1, le=200),
                 _current_user: dict = Depends(get_current_user)):
    rows = [_clean(d) async for d in
            fundamental_ratings_collection.find({}).sort("rated_at", -1).limit(limit)]
    return {"ratings": rows, "count": len(rows)}


@router.post("/rate")
async def rate_symbols(payload: dict = Body(...),
                       _current_user: dict = Depends(get_current_user)):
    """Rate one stock or a pasted group of them."""
    raw = payload.get("symbols")
    force = bool(payload.get("force"))

    if isinstance(raw, list):
        symbols = screener_in.split_symbols(" ".join(str(s) for s in raw))
    else:
        symbols = screener_in.split_symbols(str(raw or ""))

    if not symbols:
        raise HTTPException(status_code=400, detail="No stock symbols found in that input.")
    truncated = symbols[MAX_SYMBOLS:]
    symbols = symbols[:MAX_SYMBOLS]

    fetched = await screener_in.get_many(symbols, force=force)

    results, failures = [], []
    now = datetime.now(timezone.utc)
    for sym in symbols:
        got = fetched.get(sym)
        if isinstance(got, screener_in.ScreenerError):
            failures.append({"symbol": sym, "error": got.detail})
            continue
        if not isinstance(got, dict):
            failures.append({"symbol": sym, "error": "no data returned"})
            continue
        try:
            r = rate(got)
        except Exception as exc:                        # never let one company sink the batch
            failures.append({"symbol": sym, "error": f"rating failed: {exc}"})
            continue
        r["symbol"] = sym
        r["rated_at"] = now
        r["from_cache"] = bool(got.get("cached"))
        try:
            r["results"] = results_strength.analyse(got)
        except Exception:                               # a bad quarterly table is not fatal
            r["results"] = {"rated": False, "score": None, "band": "unknown",
                            "verdict": "Results could not be read", "signals": [],
                            "headline": "The quarterly table could not be interpreted."}
        try:
            r["pnl"] = pnl_strength.analyse(got)
        except Exception:
            r["pnl"] = {"rated": False, "score": None, "signals": [],
                        "verdict": "P&L record could not be read",
                        "headline": "The yearly table could not be interpreted."}
        r.update(fundamental_brief.compose(r, r.get("results"), r.get("pnl")))
        r["statements"] = _statements(got)
        results.append(r)
        # The statements are already cached in screener_fundamentals; storing a second copy
        # per rating would double the write for data that is keyed by symbol either way.
        await fundamental_ratings_collection.replace_one(
            {"_id": sym}, {**{k: v for k, v in r.items() if k != "statements"}, "_id": sym},
            upsert=True)

    results.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))
    for r in results:
        r.pop("_id", None)

    return {
        "ratings": results,
        "failures": failures,
        "requested": len(symbols),
        "rated": len(results),
        "truncated": truncated,
        "note": (f"Only the first {MAX_SYMBOLS} symbols were rated; {len(truncated)} were "
                 "left out." if truncated else None),
    }


# ── NSE Stock Ratings: every NSE-listed company on one table ─────────────────────
# Declared before /{symbol} below, which would otherwise take "nse-ratings" as a ticker.


@router.get("/nse-ratings")
async def nse_ratings_table(
    search: str | None = None,
    index: str | None = None,
    sector: str | None = None,
    rating: str | None = Query(None, description="Comma-separated overall grade keys, "
                                                 "or 'insufficient' for Insufficient Data."),
    quarter: str | None = None,
    data: str | None = None,
    sort: str = "overall",
    order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=3000),
    fields: str | None = None,
    include_delisted: bool = False,
    liquidity: str | None = None,
    vol: str | None = None,
    conf: str | None = None,
    _current_user: dict = Depends(get_current_user),
):
    keys = [k for k in (rating or "").split(",")
            if k in GRADE_ORDER or k == "insufficient"] or None
    return await nse_ratings.browse(
        search=search, index=index or None, sector=sector or None, ratings=keys,
        quarter=quarter or None, data=data or None, sort=sort, order=order, page=page,
        page_size=page_size, fields=fields, include_delisted=include_delisted,
        liquidity=liquidity or None, vol=vol or None, conf=conf or None)


@router.get("/nse-ratings/summary")
async def nse_ratings_summary(_current_user: dict = Depends(get_current_user)):
    return await nse_ratings.summary()


@router.get("/nse-ratings/stock/{symbol}")
async def nse_rating_detail(symbol: str, _current_user: dict = Depends(get_current_user)):
    out = await nse_ratings.detail(symbol)
    if out is None:
        raise HTTPException(status_code=404, detail=f"{symbol} is not on NSE's listed-equity list.")
    return out


@router.post("/nse-ratings/stock/{symbol}/refresh")
async def nse_rating_refresh_one(symbol: str, _current_user: dict = Depends(get_current_user)):
    """Read this one company from screener.in now, rather than waiting for the refresher."""
    from app.services.desk_switches import is_on

    if not await is_on(nse_ratings.SWITCH):
        raise HTTPException(status_code=409,
                            detail="Fundamental Rating is switched off in Main Control.")
    try:
        res = await nse_ratings.refresh_one(symbol, reason="manual")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"{symbol} is not on NSE's listed-equity list.")
    except nse_ratings.RateLimited:
        raise HTTPException(status_code=429,
                            detail="screener.in is rate-limiting this server; try again in a minute.")
    out = await nse_ratings.detail(symbol)
    return {**(out or {}), "refresh": res}


@router.post("/nse-ratings/refresh")
async def nse_ratings_refresh(payload: dict = Body(default={}),
                              _current_user: dict = Depends(get_current_user)):
    """Run the refresher now. `what` forces one job even when it is not due."""
    what = (payload.get("what") or "due").strip()
    if what not in ("due", "universe", "meetings", "returns", "rebuild"):
        raise HTTPException(status_code=400,
                            detail="what must be due, universe, meetings, returns or rebuild.")
    return await nse_ratings.trigger(what)


@router.get("/{symbol}")
async def one(symbol: str, force: bool = False,
              _current_user: dict = Depends(get_current_user)):
    """One company, with the statements the score was built from."""
    sym = screener_in.normalise_symbol(symbol)
    if not sym:
        raise HTTPException(status_code=400, detail="Not a usable symbol.")
    try:
        data = await screener_in.get_fundamentals(sym, force=force)
    except screener_in.ScreenerError as exc:
        raise HTTPException(status_code=404, detail=exc.detail)

    r = rate(data)
    r["symbol"] = sym
    r["from_cache"] = bool(data.get("cached"))
    r["results"] = results_strength.analyse(data)
    r["pnl"] = pnl_strength.analyse(data)
    r.update(fundamental_brief.compose(r, r["results"], r["pnl"]))
    r["statements"] = _statements(data)
    r["fundamentals"] = {
        "ratios": data.get("ratios"),
        "ranges": data.get("ranges"),
        "profit_loss": data.get("profit_loss"),
        "profit_loss_periods": data.get("profit_loss_periods"),
        "balance_sheet": data.get("balance_sheet"),
        "balance_sheet_periods": data.get("balance_sheet_periods"),
        "cash_flow": data.get("cash_flow"),
        "cash_flow_periods": data.get("cash_flow_periods"),
        "shareholding": data.get("shareholding"),
        "shareholding_periods": data.get("shareholding_periods"),
        "about": data.get("about"),
    }
    return r
