"""Fundamental Rating — paste stocks, get a 1-10 verdict off screener.in.

  POST /api/fundamentals/rate      {"symbols": "RELIANCE, TCS" | ["RELIANCE"], "force": false}
  GET  /api/fundamentals/{symbol}  one company, rating + the parsed statements behind it
  GET  /api/fundamentals/recent    what was rated lately, newest first

`symbols` takes either the raw pasted text or an already-split list; the service does the
splitting so the UI never has to guess at the user's separators.

Live fetches are paced and capped at MAX_SYMBOLS per request. That cap exists for
screener.in's sake as much as ours: a 200-symbol paste would be 200 page loads against a
free public site. Anything already cached inside the day does not re-fetch, so a second
pass over the same basket returns immediately.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.core.db import fundamental_ratings_collection
from app.services import (
    fundamental_brief,
    fundamental_universe,
    fundamental_watchlist,
    pnl_strength,
    results_strength,
    screener_in,
)
from app.services.fundamental_rating import PILLARS, PILLAR_LABELS, rate
from app.services.grades import ORDER as GRADE_ORDER, scale as grade_scale

router = APIRouter(prefix="/api/fundamentals", tags=["fundamentals"])

MAX_SYMBOLS = 40


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
    if scope_type not in ("index", "sector"):
        raise HTTPException(status_code=400, detail="type must be 'index' or 'sector'.")
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
