"""Gold Desk — MCX gold futures and Delta's gold perpetual, after the 2026-10 research.

  GET  /api/gold-desk/venues              both tabs' headline numbers in one call
  GET  /api/gold-desk/summary?venue=      book, switch, breakers, what the venue trades and why
  GET  /api/gold-desk/strategies?venue=   every enabled or traded strategy, with its RECORD
  GET  /api/gold-desk/positions?venue=    ?status=OPEN|CLOSED
  GET  /api/gold-desk/coverage?venue=     bars per symbol and timeframe
  GET  /api/gold-desk/basis               what the two venues say the same ounce is worth
  GET  /api/gold-desk/costs               measured fees, spreads and funding (I5)
  GET  /api/gold-desk/h1                  the pre-registered forward test: rule, progress, verdict
  POST /api/gold-desk/toggle?venue=       {"enabled": bool} — entries only; 409 when nothing can trade
  POST /api/gold-desk/run?venue=          one cycle now (manage + scan)
  POST /api/gold-desk/close-all?venue=    square off that venue's open positions at the market

  GET  /api/gold-desk/lab                 the Gold Lab book: seven tested strategies, holdings, decision
  GET  /api/gold-desk/lab/fills           its rebalancing fills, newest first
  POST /api/gold-desk/lab/toggle          {"enabled": bool} — stores its pre-registration on first use
  POST /api/gold-desk/lab/run             one lab cycle now (decides / executes only when due)
  POST /api/gold-desk/lab/close-all       flatten every lab holding at the touch
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services import gold_desk, gold_h1, gold_lab

router = APIRouter(prefix="/api/gold-desk", tags=["gold-desk"])

VenueQ = Query("delta", pattern="^(mcx|delta)$", description="mcx | delta")


def _v(key: str):
    try:
        return gold_desk.venue(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/venues")
async def venues(_current_user: dict = Depends(get_current_user)):
    """Both books at once, for the tab strip."""
    return {"venues": [await gold_desk.summary(gold_desk.VENUES[k]) for k in gold_desk.VENUE_KEYS]}


@router.get("/summary")
async def summary(venue: str = VenueQ, _current_user: dict = Depends(get_current_user)):
    return await gold_desk.summary(_v(venue))


@router.get("/strategies")
async def strategies(venue: str = VenueQ, limit: int = Query(400, ge=1, le=2000),
                     _current_user: dict = Depends(get_current_user)):
    return {"strategies": await gold_desk.strategies(_v(venue), limit)}


@router.get("/positions")
async def positions(venue: str = VenueQ,
                    status: str = Query("OPEN", pattern="^(OPEN|CLOSED)$"),
                    limit: int = Query(200, ge=1, le=1000),
                    _current_user: dict = Depends(get_current_user)):
    return {"positions": await gold_desk.positions(_v(venue), status, limit)}


@router.get("/coverage")
async def coverage(venue: str = VenueQ, _current_user: dict = Depends(get_current_user)):
    return await gold_desk.coverage(_v(venue))


@router.get("/basis")
async def basis(_current_user: dict = Depends(get_current_user)):
    return await gold_desk.basis()


@router.get("/costs")
async def costs(_current_user: dict = Depends(get_current_user)):
    return await gold_desk.costs()


@router.get("/h1")
async def h1(_current_user: dict = Depends(get_current_user)):
    return await gold_h1.report()


@router.post("/toggle")
async def toggle(venue: str = VenueQ, payload: dict = Body(...),
                 _current_user: dict = Depends(get_current_user)):
    try:
        return await gold_desk.set_enabled(_v(venue), bool(payload.get("enabled")))
    except gold_desk.GoldDeskError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc


@router.post("/run")
async def run(venue: str = VenueQ, _current_user: dict = Depends(get_current_user)):
    from app.services.desk_switches import is_on
    return await gold_desk.run_cycle(_v(venue), entries_allowed=await is_on("gold_desk"))


@router.post("/close-all")
async def close_all(venue: str = VenueQ, _current_user: dict = Depends(get_current_user)):
    return await gold_desk.close_all(_v(venue))


# ── the Gold Lab book: the seven Tier-B strategies of the 2026-10 search ───────────


@router.get("/lab")
async def lab(_current_user: dict = Depends(get_current_user)):
    return await gold_lab.summary()


@router.get("/lab/fills")
async def lab_fills(limit: int = Query(200, ge=1, le=2000), _current_user: dict = Depends(get_current_user)):
    return {"fills": await gold_lab.fills(limit)}


@router.post("/lab/toggle")
async def lab_toggle(payload: dict = Body(...), _current_user: dict = Depends(get_current_user)):
    try:
        return await gold_lab.set_enabled(bool(payload.get("enabled")))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/lab/run")
async def lab_run(_current_user: dict = Depends(get_current_user)):
    from app.services.desk_switches import is_on
    return await gold_lab.cycle(entries_allowed=await is_on("gold_desk"))


@router.post("/lab/close-all")
async def lab_close_all(_current_user: dict = Depends(get_current_user)):
    return await gold_lab.close_all()
