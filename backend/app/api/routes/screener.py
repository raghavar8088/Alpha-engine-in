"""Stock Screener API — momentum, sector rotation and chart patterns over the NSE universe.

  GET  /api/screener/summary          breadth header + market status + coverage
  GET  /api/screener/momentum         the ranked board for one horizon
  GET  /api/screener/momentum/{sym}   one stock: all horizons, reasons, trade plans
  GET  /api/screener/sectors          sector rotation across all four horizons
  GET  /api/screener/sectors/{name}   drill-down: constituents + what drives the move
  GET  /api/screener/patterns         daily/weekly chart-pattern hits
  GET  /api/screener/setups           intraday | swing | breakout shortlists
  GET  /api/screener/sources          per-feed honesty for the Sources tab
  GET  /api/screener/chartink         optional delayed secondary feed
  POST /api/screener/refresh          force a full recompute and persist

Every GET is plain and cacheable — the app-wide 20s door cache applies, and `?fresh=true`
bypasses both it and the per-module snapshot caches. Nothing here streams, so none of these
belong in NEVER_CACHE.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services.response_cache import cached as _cached
from app.services.screener import chartink as CK
from app.services.screener import engine as E
from app.services.screener import horizons as H
from app.services.screener import momentum as M
from app.services.screener import patterns as P
from app.services.screener import sectors as S
from app.services.stocks_range import INDEX_LABELS

router = APIRouter(prefix="/api/screener", tags=["screener"])


def _guard(exc: M.ScreenerError) -> HTTPException:
    return HTTPException(status_code=422, detail=exc.detail)


@router.get("/config")
async def config(_current_user: dict = Depends(get_current_user)):
    """Everything the UI needs to render its controls without hardcoding it."""
    return {
        "indices": [{"key": k, "label": v} for k, v in INDEX_LABELS.items()],
        "default_index": M.DEFAULT_INDEX,
        "horizons": [{"key": h, "label": H.HORIZON_LABELS[h], "sessions": H.HORIZONS[h]}
                     for h in H.HORIZON_ORDER],
        "timeframes": [{"key": t, "label": P.TIMEFRAME_LABELS[t]} for t in P.TIMEFRAMES],
        "pattern_catalog": P.catalog(),
        "setup_kinds": E.SETUP_KINDS,
        "chartink": CK.status(),
    }


@router.get("/summary")
async def summary(
    index: str | None = Query(None),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    try:
        return await _cached(f"scr:sum:{index}", lambda: E.summary(index, fresh=fresh),
                             ttl=30, fresh=fresh)
    except M.ScreenerError as exc:
        raise _guard(exc)


@router.get("/momentum")
async def momentum_board(
    horizon: str = Query("1d", description="1d | 1w | 1m | 6m"),
    index: str | None = Query(None),
    sector: str | None = Query(None),
    limit: int = Query(100, ge=1, le=600),
    min_turnover: float | None = Query(None, description="rupees of daily turnover; 0 disables"),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    key = f"scr:mom:{index}:{horizon}:{sector}:{limit}:{min_turnover}"
    try:
        return await _cached(
            key,
            lambda: M.board(index or M.DEFAULT_INDEX, horizon, sector, limit,
                            min_turnover, fresh=fresh),
            ttl=30, fresh=fresh,
        )
    except M.ScreenerError as exc:
        raise _guard(exc)


@router.get("/momentum/{symbol}")
async def momentum_detail(
    symbol: str,
    index: str | None = Query(None),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    try:
        return await _cached(f"scr:det:{index}:{symbol.upper()}",
                             lambda: M.detail(symbol, index or M.DEFAULT_INDEX, fresh=fresh),
                             ttl=30, fresh=fresh)
    except M.ScreenerError as exc:
        raise _guard(exc)


@router.get("/sectors")
async def sector_board(
    index: str | None = Query(None),
    horizon: str | None = Query(None, description="omit for all four horizons at once"),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    async def _run():
        snap = await M.universe_snapshot(index or M.DEFAULT_INDEX, fresh=fresh)
        if horizon:
            if horizon not in H.HORIZONS:
                raise M.ScreenerError(f"unknown horizon {horizon!r}")
            return S.roll_up(snap, horizon)
        return S.all_horizons(snap)

    try:
        return await _cached(f"scr:sec:{index}:{horizon}", _run, ttl=30, fresh=fresh)
    except M.ScreenerError as exc:
        raise _guard(exc)


@router.get("/sectors/{sector}")
async def sector_drilldown(
    sector: str,
    horizon: str = Query("1d"),
    index: str | None = Query(None),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    async def _run():
        if horizon not in H.HORIZONS:
            raise M.ScreenerError(f"unknown horizon {horizon!r}")
        snap = await M.universe_snapshot(index or M.DEFAULT_INDEX, fresh=fresh)
        try:
            return S.drill_down(snap, sector, horizon)
        except KeyError:
            raise M.ScreenerError(
                f"no sector named {sector!r} in this index — the sector label comes from the "
                f"niftyindices 'Industry' column, not from NSE's sectoral index names")

    try:
        return await _cached(f"scr:secd:{index}:{sector}:{horizon}", _run, ttl=30, fresh=fresh)
    except M.ScreenerError as exc:
        raise _guard(exc)


@router.get("/patterns")
async def pattern_board(
    timeframe: str | None = Query(None, description="1d | 1w"),
    pattern: str | None = Query(None, description="template key, e.g. double_top_bottom"),
    family: str | None = Query(None, description="chart | candlestick | structure"),
    state: str | None = Query(None, description="TRIGGERED | FORMING"),
    direction: str | None = Query(None, description="bullish | bearish"),
    sector: str | None = Query(None),
    index: str | None = Query(None),
    limit: int = Query(300, ge=1, le=2000),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    key = f"scr:pat:{index}:{timeframe}:{pattern}:{family}:{state}:{direction}:{sector}:{limit}"
    return await _cached(
        key,
        lambda: P.board(index, timeframe, pattern, family, state, direction, sector,
                        limit, fresh=fresh),
        ttl=120, fresh=fresh,
    )


@router.get("/setups")
async def setup_board(
    kind: str = Query("intraday", description="intraday | swing | breakout"),
    index: str | None = Query(None),
    limit: int = Query(40, ge=1, le=200),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    try:
        return await _cached(f"scr:set:{index}:{kind}:{limit}",
                             lambda: E.setups(kind, index, limit, fresh=fresh),
                             ttl=60, fresh=fresh)
    except M.ScreenerError as exc:
        raise _guard(exc)


@router.get("/sources")
async def source_status(
    index: str | None = Query(None),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    return await _cached(f"scr:src:{index}", lambda: E.sources(index), ttl=60, fresh=fresh)


@router.get("/chartink")
async def chartink_preset(
    scan: str = Query(..., description="preset key; see /config for the list"),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    """Optional, delayed, secondary. Disabled unless SCREENER_CHARTINK_ENABLED=1."""
    return await CK.preset(scan, fresh=fresh)


@router.post("/refresh")
async def refresh(
    index: str | None = Query(None),
    _current_user: dict = Depends(get_current_user),
):
    """Recompute everything and persist today's snapshots."""
    try:
        return await E.refresh_all(index)
    except M.ScreenerError as exc:
        raise _guard(exc)
