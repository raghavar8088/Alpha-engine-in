"""Gold Desk — the pattern library on gold, on MCX futures and Delta gold perpetuals.

  GET  /api/gold-desk/venues              both tabs' headline numbers in one call
  GET  /api/gold-desk/summary?venue=      book, switch, breakers, fee model
  GET  /api/gold-desk/strategies?venue=   every strategy that has traded, with its verdict
  GET  /api/gold-desk/positions?venue=    ?status=OPEN|CLOSED
  GET  /api/gold-desk/coverage?venue=     bars per symbol and timeframe
  GET  /api/gold-desk/basis               what the two venues say the same ounce is worth
  POST /api/gold-desk/toggle?venue=       {"enabled": bool} — entries only
  POST /api/gold-desk/run?venue=          one cycle now (manage + scan)
  POST /api/gold-desk/close-all?venue=    square off that venue's open positions

`venue` is a query parameter rather than two routes, because the two books differ in
currency and contract and in nothing else: one set of endpoints is what keeps the MCX tab
and the Delta tab reading the same code, and therefore the same on screen.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services import gold_desk

router = APIRouter(prefix="/api/gold-desk", tags=["gold-desk"])

VenueQ = Query("mcx", pattern="^(mcx|delta)$", description="mcx | delta")


def _v(key: str):
    try:
        return gold_desk.venue(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/venues")
async def venues(_current_user: dict = Depends(get_current_user)):
    """Both books at once, for the tab strip — so switching tabs never shows an empty
    header while the second book loads."""
    return {"venues": [await gold_desk.summary(gold_desk.VENUES[k])
                       for k in gold_desk.VENUE_KEYS]}


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


@router.post("/toggle")
async def toggle(venue: str = VenueQ, payload: dict = Body(...),
                 _current_user: dict = Depends(get_current_user)):
    return await gold_desk.set_enabled(_v(venue), bool(payload.get("enabled")))


@router.post("/run")
async def run(venue: str = VenueQ, _current_user: dict = Depends(get_current_user)):
    return await gold_desk.run_cycle(_v(venue))


@router.post("/close-all")
async def close_all(venue: str = VenueQ, _current_user: dict = Depends(get_current_user)):
    return await gold_desk.close_all(_v(venue))
