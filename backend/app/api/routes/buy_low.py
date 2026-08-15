"""Buy Low Options API — buy a cheap OTM call on F&O stocks that crashed today.

  GET  /api/buy-low/summary     capital tiles + the rule set in force
  GET  /api/buy-low/fallers     live board of today's biggest F&O fallers
  GET  /api/buy-low/positions   open or closed positions
  GET  /api/buy-low/trades      closed-trade blotter
  GET  /api/buy-low/signals     every faller evaluated, taken or skipped (with the reason)
  GET  /api/buy-low/daily       realised P&L per session
  GET  /api/buy-low/nse-volume  NSE's own volume-gainers capture (volume vs its habit)
  POST /api/buy-low/nse-volume/capture  pull it now instead of waiting for 16:15 IST
  POST /api/buy-low/run         run one cycle now (?force=true to bypass the 3 PM window)
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.services import nse_volume_gainers as nse_vol
from app.services.buy_low_options import (
    daily_pnl,
    fallers as bl_fallers,
    refresh_fno_bars,
    screener as bl_screener,
    positions as bl_positions,
    run_cycle,
    signals as bl_signals,
    summary as bl_summary,
    trades as bl_trades,
)

router = APIRouter(prefix="/api/buy-low", tags=["buy-low"])


@router.get("/summary")
async def summary_endpoint(_u: dict = Depends(get_current_user)):
    return await bl_summary()


@router.get("/fallers")
async def fallers_endpoint(limit: int = Query(40, ge=1, le=250), _u: dict = Depends(get_current_user)):
    return {"fallers": await bl_fallers(limit)}


@router.get("/screener")
async def screener_endpoint(limit: int = Query(15, ge=1, le=50), _u: dict = Depends(get_current_user)):
    """Biggest F&O movers — gainers and losers over 1 day / 1 week / 1 month."""
    return await bl_screener(limit)


@router.post("/refresh-bars")
async def refresh_bars_endpoint(_u: dict = Depends(get_current_user)):
    """Re-pull recent daily candles for the F&O universe (used by the week/month columns)."""
    return await refresh_fno_bars()


@router.get("/positions")
async def positions_endpoint(
    status: str = Query("OPEN", description="OPEN | CLOSED"),
    limit: int = Query(500, ge=1, le=1000),
    _u: dict = Depends(get_current_user),
):
    return {"positions": await bl_positions(status, limit), "summary": await bl_summary()}


@router.get("/trades")
async def trades_endpoint(limit: int = Query(500, ge=1, le=1000), _u: dict = Depends(get_current_user)):
    return {"trades": await bl_trades(limit)}


@router.get("/signals")
async def signals_endpoint(limit: int = Query(500, ge=1, le=1000), _u: dict = Depends(get_current_user)):
    return {"signals": await bl_signals(limit)}


@router.get("/daily")
async def daily_endpoint(limit: int = Query(60, ge=1, le=365), _u: dict = Depends(get_current_user)):
    return {"daily": await daily_pnl(limit)}


@router.post("/run")
async def run_endpoint(
    force: bool = Query(False, description="bypass the 3 PM entry window"),
    _u: dict = Depends(get_current_user),
):
    return await run_cycle(force_scan=force)


# ── NSE volume gainers ─────────────────────────────────────────────────────────
# Lives on this router because it feeds the screener tab: Angel gives price and today's
# volume, NSE gives today's volume against the stock's OWN weekly and monthly habit, which
# is what separates a fall on ordinary turnover from a fall someone is causing.


@router.get("/nse-volume")
async def nse_volume(
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """Latest successful capture. Returns ok=false with the reason when NSE refused —
    never an empty table pretending to be a quiet day."""
    return await nse_vol.latest(limit)


@router.get("/nse-volume/history")
async def nse_volume_history(
    limit: int = Query(30, ge=1, le=180),
    current_user: dict = Depends(get_current_user),
):
    """Capture log: which days succeeded, which failed and why."""
    return {"history": await nse_vol.history(limit)}


@router.post("/nse-volume/capture")
async def nse_volume_capture(
    force: bool = Query(False, description="re-pull even if today is already captured"),
    current_user: dict = Depends(get_current_user),
):
    return await nse_vol.capture(force=force)
