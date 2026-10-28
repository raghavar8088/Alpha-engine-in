"""Strategy Factory tabs API - the Factory's 546 strategies on six modules' own instruments.

  GET  /api/factory-desks                          the six tabs
  GET  /api/factory-desks/{desk}/summary           capital, equity, P&L, charges, data coverage
  GET  /api/factory-desks/{desk}/leaderboard       one row per strategy (?family=&timeframe=)
  GET  /api/factory-desks/{desk}/positions         OPEN | CLOSED | ALL
  POST /api/factory-desks/{desk}/run               one cycle of that tab, now

Paper only (app.services.factory_desks): no order reaches a broker or an exchange from here.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services import factory_desks as fdk

router = APIRouter(prefix="/api/factory-desks", tags=["factory-desks"])


def _tab(desk: str) -> str:
    if desk not in fdk.TABS:
        raise HTTPException(status_code=404, detail=f"No Strategy Factory tab '{desk}'")
    return desk


@router.get("")
async def tabs(_user: dict = Depends(get_current_user)):
    return {"strategies": len(fdk.FACTORY_CATALOG),
            "tabs": [{"desk": t.key, "module": t.module, "route": t.route, "label": t.label, "kind": t.kind,
                      "instrument": t.instrument, "per_strategy_capital": t.capital, "currency": t.currency}
                     for t in fdk.TABS.values()]}


@router.get("/{desk}/summary")
async def summary(desk: str, _user: dict = Depends(get_current_user)):
    return await fdk.summary(_tab(desk))


@router.get("/{desk}/leaderboard")
async def leaderboard(desk: str, family: str | None = Query(None), timeframe: str | None = Query(None),
                      _user: dict = Depends(get_current_user)):
    rows = await fdk.leaderboard(_tab(desk), family, timeframe)
    return {"desk": desk, "rows": rows, "total": len(rows)}


@router.get("/{desk}/positions")
async def positions(desk: str, status: str = Query("OPEN", description="OPEN | CLOSED | ALL"),
                    limit: int = Query(200, ge=1, le=1000), _user: dict = Depends(get_current_user)):
    return {"desk": desk, "status": status.upper(), "positions": await fdk.positions(_tab(desk), status, limit)}


@router.post("/{desk}/run")
async def run(desk: str, _user: dict = Depends(get_current_user)):
    return await fdk.run_all(only=_tab(desk))
