"""Swing Trading Signals — research-gated swing calls and their ₹1 crore paper desk.

  GET  /api/swing-signals/scan       run the research over the universe (cached 15 min)
  GET  /api/swing-signals/board      the published calls
  GET  /api/swing-signals/desk       the ₹1cr paper book and its record
  GET  /api/swing-signals/research/{symbol}   the full working for ONE stock, pass or fail
  POST /api/swing-signals/publish    store today's calls and open a ₹1 lakh position each
  POST /api/swing-signals/run        publish, then mark and resolve the open book
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.core.db import stock_universe_collection
from app.services.screener import horizons as H
from app.services.swing_signals import desk as D
from app.services.swing_signals import engine as E
from app.services.swing_signals.research import evaluate
from app.services.swing_signals.signals import build

router = APIRouter(prefix="/api/swing-signals", tags=["swing-signals"])


@router.get("/scan")
async def scan(fresh: bool = Query(False), _u: dict = Depends(get_current_user)):
    """Every candidate judged, with the rejection reasons counted."""
    return await E.scan(fresh=fresh)


@router.get("/board")
async def board(horizon: str | None = Query(None, description="1 week | 10 days | 1 month"),
                conviction: str | None = Query(None, description="HIGH | MEDIUM | MODEST"),
                limit: int = Query(60, ge=1, le=300),
                _u: dict = Depends(get_current_user)):
    return await E.board(horizon, conviction, limit)


@router.get("/desk")
async def desk_summary(_u: dict = Depends(get_current_user)):
    return await D.summary()


@router.get("/research/{symbol}")
async def research_one(symbol: str, _u: dict = Depends(get_current_user)):
    """The whole verdict for one stock — including WHY it was rejected.

    Rejections are as much the point as the passes: a desk you cannot interrogate about
    the names it turned down is one you have to take on faith."""
    sym = symbol.upper()
    bars_by_sym = await H.load_daily_bars([sym], lookback=E.LOOKBACK)
    bars = bars_by_sym.get(sym) or []
    if not bars:
        raise HTTPException(404, f"No daily bars on file for {sym}")
    bench = (await H.load_daily_bars([E.BENCHMARK], lookback=E.LOOKBACK)
             ).get(E.BENCHMARK) or []
    doc = await stock_universe_collection.find_one({"symbol": sym},
                                                   {"_id": 0, "name": 1, "sector": 1})
    res = evaluate(sym, bars, bench)
    sig, why = (build(res, bars, (doc or {}).get("name"), (doc or {}).get("sector"),
                      H.ist_date(datetime.now(timezone.utc)).isoformat())
               if res.ok else (None, res.reject))
    return {
        "symbol": sym,
        "name": (doc or {}).get("name"),
        "sector": (doc or {}).get("sector"),
        "passes_research": res.ok,
        "score": res.score,
        "pillars_passed": res.pillars_passed,
        "pillars": [p.__dict__ for p in res.pillars],
        "facts": res.facts,
        "rejected_because": why if not sig else None,
        "signal": sig.to_dict() if sig else None,
    }


@router.post("/publish")
async def publish(_u: dict = Depends(get_current_user)):
    """Store today's signals and open a ₹1 lakh paper position on each."""
    return await E.publish(fresh=True)


@router.post("/run")
async def run(_u: dict = Depends(get_current_user)):
    """Publish, then walk every open position forward over the bars it has not seen."""
    return await E.run_daily()
