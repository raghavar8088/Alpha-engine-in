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
from app.services import screener_in
from app.services.fundamental_rating import PILLARS, PILLAR_LABELS, rate

router = APIRouter(prefix="/api/fundamentals", tags=["fundamentals"])

MAX_SYMBOLS = 40


def _clean(doc: dict | None) -> dict | None:
    if doc:
        doc.pop("_id", None)
    return doc


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
        results.append(r)
        await fundamental_ratings_collection.replace_one(
            {"_id": sym}, {**r, "_id": sym}, upsert=True)

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
