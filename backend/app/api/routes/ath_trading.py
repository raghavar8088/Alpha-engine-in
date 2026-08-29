"""All Time High Trading API.

  GET  /api/ath/summary      capital, P&L, hit rate, the exit rule
  GET  /api/ath/coverage     how much of the intended universe the desk can actually see
  GET  /api/ath/universe     eligible stocks with their stored all-time high
  GET  /api/ath/positions    open positions, marked live
  GET  /api/ath/trades       closed trades with costs
  GET  /api/ath/signals      every signal, taken or not, with the reason
  GET  /api/ath/near-highs   the watchlist — closest to an all-time high without breaking it
  GET  /api/ath/equity       equity curve
  POST /api/ath/run          run one cycle by hand
  POST /api/ath/seed-highs   walk history for stocks with no stored all-time high
  GET  /api/ath/gate         pre-entry checks: the open book scored, graded trades reviewed
  POST /api/ath/gate/mode    observe | enforce | off
  POST /api/ath/gate/refresh-nse  re-read NSE price bands + ASM/GSM
  POST /api/ath/reset        wipe the desk
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services import ath_trading
from app.services.response_cache import cached as _cached

router = APIRouter(prefix="/api/ath", tags=["ath-trading"])


@router.get("/summary")
async def summary(fresh: bool = Query(False), _u: dict = Depends(get_current_user)):
    return await _cached("ath:summary", ath_trading.summary, ttl=20, fresh=fresh)


@router.get("/coverage")
async def coverage(fresh: bool = Query(False), _u: dict = Depends(get_current_user)):
    return await _cached("ath:coverage", ath_trading.coverage, ttl=300, fresh=fresh)


@router.get("/universe")
async def universe(limit: int = Query(500, ge=1, le=2000),
                   fresh: bool = Query(False), _u: dict = Depends(get_current_user)):
    rows = await _cached("ath:universe", ath_trading.universe, ttl=300, fresh=fresh)
    ranked = sorted(rows, key=lambda r: -(r.get("market_cap") or 0))
    return {"count": len(ranked), "rows": ranked[:limit]}


@router.get("/positions")
async def positions(fresh: bool = Query(False), _u: dict = Depends(get_current_user)):
    return await _cached("ath:positions", ath_trading.positions, ttl=15, fresh=fresh)


@router.get("/trades")
async def trades(limit: int = Query(300, ge=1, le=1000),
                 _u: dict = Depends(get_current_user)):
    return await ath_trading.trades(limit)


@router.get("/signals")
async def signals(limit: int = Query(200, ge=1, le=1000),
                  taken: bool | None = Query(None),
                  _u: dict = Depends(get_current_user)):
    return await ath_trading.signals(limit, taken)


@router.get("/near-highs")
async def near_highs(limit: int = Query(50, ge=1, le=300),
                     fresh: bool = Query(False), _u: dict = Depends(get_current_user)):
    return await _cached(f"ath:near:{limit}", lambda: ath_trading.near_highs(limit),
                         ttl=60, fresh=fresh)


@router.get("/equity")
async def equity(limit: int = Query(500, ge=1, le=2000),
                 _u: dict = Depends(get_current_user)):
    return await ath_trading.equity_curve(limit)


@router.post("/run")
async def run(_u: dict = Depends(get_current_user)):
    """Run one manage-then-scan cycle now."""
    return await ath_trading.run_cycle()


@router.post("/seed-highs")
async def seed_highs(limit: int = Query(60, ge=1, le=150),
                     _u: dict = Depends(get_current_user)):
    """Walk history for eligible stocks that have no stored all-time high yet.

    Capped at 150. Angel throttles this endpoint hard enough that a bigger batch does not
    finish sooner — it just turns the tail of the batch into refusals.
    """
    return await ath_trading.seed_highs(limit)


@router.post("/reset")
async def reset(confirm: bool = Query(False), _u: dict = Depends(get_current_user)):
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Refusing to reset without ?confirm=true — this deletes every position, "
                   "trade and signal on the desk and cannot be undone.")
    return await ath_trading.reset()


# ── watchlist ───────────────────────────────────────────────────────────────────


class MapRequest(BaseModel):
    """`symbols` takes either a pasted blob or a list — the UI sends a blob from the
    textarea and a list when re-mapping an already-curated set."""
    symbols: str | list[str]


class EnterAllRequest(BaseModel):
    """Omit `symbols` to buy the whole saved watchlist."""
    symbols: list[str] | None = None


class SaveWatchlistRequest(BaseModel):
    symbols: list[str]
    mode: str | None = None                  # auto | manual | both
    enforce_market_cap: bool | None = None
    enforce_history: bool | None = None      # the 250-session minimum


@router.post("/watchlist/map")
async def map_watchlist(payload: MapRequest, _u: dict = Depends(get_current_user)):
    """Resolve pasted symbols against the instrument master, reporting every outcome.

    This is the step between pasting and committing: it says which symbols are tradable and,
    for the rest, exactly why not — not found, not quotable, no all-time high yet, too newly
    listed, or below the size floor.
    """
    return await ath_trading.map_symbols(payload.symbols)


@router.get("/watchlist")
async def get_watchlist(_u: dict = Depends(get_current_user)):
    """The saved list, re-mapped so its rows carry current status rather than what was
    true when it was saved — a stock's all-time high gets seeded, its market cap moves."""
    wl = await ath_trading.get_watchlist()
    mapped = await ath_trading.map_symbols(
        wl.get("symbols") or [], enforce_cap=wl.get("enforce_market_cap", False),
        enforce_history=wl.get("enforce_history", True))
    return {**wl, **mapped,
            "updated_at": wl["updated_at"].isoformat() if wl.get("updated_at") else None}


@router.post("/watchlist")
async def save_watchlist(payload: SaveWatchlistRequest,
                         _u: dict = Depends(get_current_user)):
    try:
        saved = await ath_trading.save_watchlist(
            payload.symbols, payload.mode, payload.enforce_market_cap,
            payload.enforce_history)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    mapped = await ath_trading.map_symbols(
        saved.get("symbols") or [], enforce_cap=saved.get("enforce_market_cap", False),
        enforce_history=saved.get("enforce_history", True))
    return {**saved, **mapped,
            "updated_at": saved["updated_at"].isoformat() if saved.get("updated_at") else None}


@router.post("/enter-all")
async def enter_all(payload: EnterAllRequest | None = None,
                    confirm: bool = Query(False, description="must be true — this opens real paper positions"),
                    _u: dict = Depends(get_current_user)):
    """Buy the whole watchlist at the current price, bypassing the all-time-high signal.

    Gated on ?confirm=true because it commits capital across every name at once rather than
    one break at a time. Positions are tagged entry_reason='manual' so the desk's own
    signalled trades stay separable from these.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Refusing without ?confirm=true — this opens a position in every tradable "
                   "symbol on the watchlist at once, bypassing the all-time-high rule.")
    return await ath_trading.enter_all((payload.symbols if payload else None))


class GateModeRequest(BaseModel):
    mode: str


@router.get("/gate")
async def gate(limit: int = Query(500, ge=1, le=1000),
               fresh: bool = Query(False), _u: dict = Depends(get_current_user)):
    """The pre-entry gate: what it says about the open book, and how graded trades did.

    Cached for a few minutes because it reads NSE's band and surveillance files plus 20
    days of bhavcopy — none of which changes inside a session.
    """
    return await _cached("ath:gate", lambda: ath_trading.gate_report(limit),
                         ttl=300, fresh=fresh)


@router.post("/gate/mode")
async def set_gate_mode(payload: GateModeRequest, _u: dict = Depends(get_current_user)):
    """observe (score and record, still trade) | enforce (block failures) | off.

    Starts in observe on purpose — see app.services.ath_gate. A gate in enforce mode has
    no counterfactual, so it can never be shown to help.
    """
    try:
        return await ath_trading.set_gate_mode(payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/gate/refresh-nse")
async def refresh_nse(_u: dict = Depends(get_current_user)):
    """Re-read NSE's price-band list and the ASM/GSM registers."""
    from app.services import nse_surveillance
    return await nse_surveillance.refresh()
