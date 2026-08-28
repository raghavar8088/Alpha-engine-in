"""Stock Screener API — momentum, sector rotation and chart patterns over the NSE universe.

  GET  /api/screener/summary          breadth header + market status + coverage
  GET  /api/screener/momentum         the ranked board for one horizon
  GET  /api/screener/momentum/{sym}   one stock: all horizons, reasons, trade plans
  GET  /api/screener/sectors          sector rotation across all four horizons
  GET  /api/screener/sectors/{name}   drill-down: constituents + what drives the move
  GET  /api/screener/patterns         daily/weekly chart-pattern hits
  GET  /api/screener/setups           intraday | swing | breakout shortlists
  GET  /api/screener/sources          per-feed honesty for the Sources tab
  GET  /api/screener/chartink         optional delayed secondary feed (curated presets)
  GET  /api/screener/chartink/named   run ANY public Chartink screener by URL or slug
  POST /api/screener/refresh          force a full recompute and persist

Every GET is plain and cacheable — the app-wide 20s door cache applies, and `?fresh=true`
bypasses both it and the per-module snapshot caches. Nothing here streams, so none of these
belong in NEVER_CACHE.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services.response_cache import cached as _cached
from app.services.screener import bhavcopy as BC
from app.services.screener import chartink as CK
from app.services.screener import paper as PA
from app.services.screener import volume as V
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
        "volume_windows": [{"key": w, "label": V.WINDOW_LABELS[w], "sessions": V.WINDOWS[w]}
                           for w in V.WINDOW_ORDER],
        "volume_states": [{"key": k, "label": k.replace("_", " ").title(), "text": t}
                          for k, t in V.STATES.items()],
        "paper_families": [{"key": f, "label": PA.FAMILY_LABELS[f],
                            "product": PA.FAMILY_PRODUCT[f]} for f in PA.FAMILIES],
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


@router.get("/chartink/named")
async def chartink_named(
    slug: str = Query(..., description="a Chartink screener slug or its full URL, e.g. "
                                       "short-term-breakouts"),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    """Read a public Chartink screener by name and run it.

    Returns 200 with `ok: false` and a reason rather than raising: a Chartink outage, a
    typo'd slug and a private screener are all ordinary answers here, and none of them is
    a fault in this app.
    """
    return await CK.named(slug, fresh=fresh)


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


# ── volume ──────────────────────────────────────────────────────────────────────


@router.get("/volume")
async def volume_board(
    window: str = Query("1d", description="1d | 1w | 1m"),
    index: str | None = Query(None),
    state: str | None = Query(None, description="accumulation | distribution | weak_rally | selling_dried | churn"),
    limit: int = Query(60, ge=1, le=400),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    """Volume gainers with the price-volume state, the reason, and a labelled next target."""
    try:
        return await _cached(f"scr:vol:{index}:{window}:{state}:{limit}",
                             lambda: V.board(index, window, limit, state, fresh=fresh),
                             ttl=60, fresh=fresh)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/delivery")
async def delivery_status(_current_user: dict = Depends(get_current_user)):
    """How much NSE bhavcopy delivery history is stored, and from when."""
    return await BC.status()


@router.post("/delivery/backfill")
async def delivery_backfill(
    days: int = Query(30, ge=1, le=120),
    _current_user: dict = Depends(get_current_user),
):
    return await BC.backfill(days)


# ── paper desk ──────────────────────────────────────────────────────────────────


@router.get("/paper/summary")
async def paper_summary(
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    """Per-family leaderboard: which kind of Screener signal actually makes money."""
    return await _cached("scr:paper:sum", PA.summary, ttl=30, fresh=fresh)


@router.get("/paper/positions")
async def paper_positions(
    status: str = Query("OPEN", description="OPEN | CLOSED"),
    family: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    fresh: bool = Query(False),
    _current_user: dict = Depends(get_current_user),
):
    return await _cached(f"scr:paper:pos:{status}:{family}:{limit}",
                         lambda: PA.positions(status, family, limit), ttl=20, fresh=fresh)


@router.post("/paper/run")
async def paper_run(
    index: str | None = Query(None),
    _current_user: dict = Depends(get_current_user),
):
    """Trigger one manage-then-scan cycle by hand."""
    return await PA.run_cycle(index)


@router.post("/paper/reset")
async def paper_reset(
    confirm: bool = Query(False, description="must be true — this deletes the trade history"),
    _current_user: dict = Depends(get_current_user),
):
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Refusing to wipe the paper desk without ?confirm=true. The trade log is "
                   "the only record of which signals worked; deleting it is not undoable.")
    return await PA.reset()
