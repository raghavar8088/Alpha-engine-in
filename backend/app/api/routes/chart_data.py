"""Chart module — live candlestick charting backed by real Dhan OHLCV data,
rendered on the frontend with `lightweight-charts` (TradingView's free,
open-source charting library; the paid/gated Charting Library wasn't
available). See app.services.chart_data for the fetch/aggregation logic.

  GET /api/chart/search    instrument autocomplete (equities/ETFs/indices/futures)
  GET /api/chart/symbol     resolve one instrument's chart metadata
  GET /api/chart/history    OHLCV bars for a resolution + time range (UDF-ish shape)
  GET /api/chart/trendline  auto-detected swing-based trend line over recent bars
  GET /api/chart/stream     SSE feed of in-progress bar updates for one instrument
  GET /api/chart/overlays   open positions + active trading calls for this instrument
  GET /api/chart/backtests  stored backtest runs for a symbol (overlay/replay sources)
  GET /api/chart/backtests/{id}/trades   one run's trade log
  GET /api/chart/option-context          max pain / PCR / key OI strikes for an underlying
  GET /api/chart/structure  multi-touch S/R zones, fitted channel, swing structure
  POST /api/chart/explain   AI plain-English read of the visible window (Claude)

Workspace (Phase 7) — drawings, saved layouts and alerts:
  GET/POST /api/chart/drawings, DELETE /api/chart/drawings/{id}
  GET/POST /api/chart/layouts,  DELETE /api/chart/layouts/{id}
  GET/POST /api/chart/alerts,   DELETE /api/chart/alerts/{id}
  POST /api/chart/alerts/evaluate  fire alerts crossed by a price move
"""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ai_service import modules as ai_modules
from app.api.deps import get_current_user
from app.api.routes.broker import _get_dhan_client
from app.core.db import instruments_collection
from app.services import chart_workspace
from app.services.chart_data import (
    ChartError,
    analyze_structure,
    find_trend_points,
    get_bars,
    instrument_for_stream,
    resolve_symbol,
    search_symbols,
)
from app.services.chart_overlays import active_calls, backtest_runs, backtest_trades, open_positions
from app.services.chart_stream import bar_epoch, hub, stream_timeframe
from app.services.dhan_client import DhanAPIError
from options_service.chain import parse_chain

# Long enough to stay clear of chatty reconnects, short enough that an idle
# proxy doesn't reap the connection and that the client can tell "market quiet"
# from "connection dead".
_HEARTBEAT_SECONDS = 15

router = APIRouter(prefix="/api/chart", tags=["chart"])


async def _dhan(current_user: dict):
    try:
        return await _get_dhan_client(str(current_user["_id"]))
    except HTTPException:
        raise HTTPException(
            status_code=400,
            detail="Dhan account not connected — the Chart module needs a live broker connection for real candles.",
        )


@router.get("/search")
async def search(q: str = Query(..., min_length=1), current_user: dict = Depends(get_current_user)):
    return {"results": await search_symbols(q)}


@router.get("/symbol")
async def symbol(security_id: str, exchange_segment: str, current_user: dict = Depends(get_current_user)):
    try:
        return await resolve_symbol(security_id, exchange_segment)
    except ChartError as exc:
        raise HTTPException(status_code=404, detail=exc.detail)


@router.get("/history")
async def history(
    security_id: str, exchange_segment: str, resolution: str, from_ts: int = Query(..., alias="from"),
    to_ts: int = Query(..., alias="to"), current_user: dict = Depends(get_current_user),
):
    dhan = await _dhan(current_user)
    try:
        return await get_bars(dhan, security_id, exchange_segment, resolution, from_ts, to_ts)
    except ChartError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)


@router.get("/trendline")
async def trendline(
    security_id: str, exchange_segment: str, resolution: str = "D", lookback: int = Query(60, ge=10, le=300),
    current_user: dict = Depends(get_current_user),
):
    import time

    dhan = await _dhan(current_user)
    now = int(time.time())
    lookback_seconds = lookback * (86400 if resolution in ("D", "W") else int(resolution) * 60 * 3)
    try:
        bars = await get_bars(dhan, security_id, exchange_segment, resolution, now - lookback_seconds, now)
    except ChartError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    if bars["s"] != "ok":
        return {"trend": None}
    trend = find_trend_points(bars["h"], bars["l"], bars["t"], lookback=lookback)
    return {"trend": trend}


@router.get("/stream")
async def stream(
    request: Request, security_id: str, exchange_segment: str, resolution: str,
    current_user: dict = Depends(get_current_user),
):
    """Server-sent events carrying live bar updates for one instrument.

    SSE rather than a WebSocket even though the rest of the app's live data uses
    WS: the production frontend on Vercel reaches the backend through the
    same-origin HTTP proxy in `app/api/[...path]/route.ts`, which cannot carry a
    WebSocket upgrade (see the comment in `lib/useMarketDataSocket.ts` — the
    dashboard socket is skipped there for exactly this reason and falls back to
    polling). SSE is plain HTTP, so it survives that hop.

    Deliberately does NOT require a connected broker: the stream is fed from
    Redis, so it degrades to "no updates" rather than a 400 for a user with no
    Dhan session, and the static chart keeps working underneath.
    """
    timeframe = stream_timeframe(resolution)
    if timeframe is None:
        raise HTTPException(
            status_code=422,
            detail=f"Live streaming isn't available for the {resolution} resolution.",
        )
    try:
        inst = await instrument_for_stream(security_id, exchange_segment)
    except ChartError as exc:
        raise HTTPException(status_code=404, detail=exc.detail)

    symbol = inst["symbol"]
    queue = await hub.subscribe(symbol, timeframe, security_id, exchange_segment)

    async def events():
        try:
            yield f"data: {json.dumps({'type': 'hello', 'symbol': symbol, 'timeframe': timeframe})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # A real data frame, not an SSE comment: EventSource drops
                    # comments without notifying the page, so a comment could not
                    # be used to tell "market quiet" apart from "link dead".
                    yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"
                    continue
                bar = {
                    "type": "bar",
                    "time": bar_epoch(payload["ts"]),
                    "open": payload["open"], "high": payload["high"],
                    "low": payload["low"], "close": payload["close"],
                    "volume": payload.get("volume") or 0,
                    "final": bool(payload.get("final")),
                }
                yield f"data: {json.dumps(bar)}\n\n"
        finally:
            # Runs on client disconnect too, so a closed tab releases its slot and
            # the last viewer leaving deregisters the symbol from live_watchlist.
            await hub.unsubscribe(symbol, timeframe, queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/structure")
async def structure(
    security_id: str, exchange_segment: str, resolution: str = "D",
    lookback: int = Query(120, ge=20, le=400), current_user: dict = Depends(get_current_user),
):
    """Support/resistance zones, fitted channel and swing structure.

    The older `/trendline` endpoint is deliberately left untouched — it still
    backs the existing "Auto trend line" toggle — so this can be adopted without
    regressing anything that already works.
    """
    import time

    dhan = await _dhan(current_user)
    now = int(time.time())
    lookback_seconds = lookback * (86400 if resolution in ("D", "W") else int(resolution) * 60 * 3)
    try:
        bars = await get_bars(dhan, security_id, exchange_segment, resolution, now - lookback_seconds, now)
    except ChartError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    if bars["s"] != "ok":
        return {"available": False, "reason": "No candles available for this symbol/timeframe."}
    return analyze_structure(bars["h"], bars["l"], bars["c"], bars["t"], lookback=lookback)


@router.post("/explain")
async def explain(payload: dict, _current_user: dict = Depends(get_current_user)):
    """AI read of the window the user is looking at.

    The frontend sends the digest (it alone knows the visible range and which
    indicators are on); this route adds nothing and simply forwards to the same
    ai_service the AI Research module uses. When no ANTHROPIC_API_KEY is set the
    provider returns `status: "not_configured"` rather than inventing an
    answer — the frontend surfaces that verbatim.
    """
    return await ai_modules.explain_chart(payload)


@router.get("/overlays")
async def overlays(security_id: str, exchange_segment: str, _current_user: dict = Depends(get_current_user)):
    """Open positions and active trading calls for the charted instrument.

    Reads Mongo only — no broker call — so it is safe to refresh whenever the
    chart symbol changes without touching the Dhan rate limit.
    """
    try:
        inst = await instrument_for_stream(security_id, exchange_segment)
    except ChartError as exc:
        raise HTTPException(status_code=404, detail=exc.detail)
    return {
        "positions": await open_positions(security_id, exchange_segment),
        "calls": await active_calls(security_id, exchange_segment, inst["symbol"]),
    }


@router.get("/backtests")
async def chart_backtests(symbol: str, _current_user: dict = Depends(get_current_user)):
    return {"runs": await backtest_runs(symbol)}


@router.get("/backtests/{backtest_id}/trades")
async def chart_backtest_trades(backtest_id: str, _current_user: dict = Depends(get_current_user)):
    result = await backtest_trades(backtest_id)
    if not result["found"]:
        raise HTTPException(status_code=404, detail="No stored backtest with that id")
    return result


@router.get("/option-context")
async def option_context(
    symbol: str, expiry: str | None = None, current_user: dict = Depends(get_current_user),
):
    """Max pain / PCR / heaviest-OI strikes for an F&O underlying.

    This one *does* call Dhan (option chain), which is why the UI keeps it behind
    an explicit toggle instead of loading it with every chart. Analytics come
    from options_service.chain — the same code the Options module uses — rather
    than being recomputed here.
    """
    instrument = await instruments_collection.find_one({"symbol": symbol.upper(), "asset_class": "INDEX"})
    if instrument is None:
        raise HTTPException(
            status_code=422,
            detail=f"Option-chain context is only available for index underlyings, not {symbol}.",
        )
    client = await _dhan(current_user)
    try:
        if not expiry:
            expiries = await client.option_chain_expiry_list(
                int(instrument["security_id"]), instrument["exchange_segment"]
            )
            available = expiries.get("data") or []
            if not available:
                return {"available": False, "reason": "Dhan returned no expiries for this underlying."}
            expiry = available[0]
        raw = await client.option_chain(
            int(instrument["security_id"]), instrument["exchange_segment"], expiry
        )
    except DhanAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.remarks)
    if raw.get("status") != "success":
        raise HTTPException(status_code=502, detail=raw.get("remarks") or "Dhan option chain request failed")

    parsed = parse_chain(raw, expiry)
    strikes = parsed.get("strikes") or []
    top_call_oi = sorted(strikes, key=lambda s: (s["ce"].get("oi") or 0), reverse=True)[:3]
    top_put_oi = sorted(strikes, key=lambda s: (s["pe"].get("oi") or 0), reverse=True)[:3]
    return {
        "available": True,
        "symbol": symbol.upper(),
        "expiry": expiry,
        "spot": parsed.get("spot"),
        "days_to_expiry": parsed.get("days_to_expiry"),
        "max_pain": parsed.get("max_pain"),
        "pcr_oi": parsed.get("pcr_oi"),
        "top_call_oi": [{"strike": s["strike"], "oi": s["ce"].get("oi") or 0} for s in top_call_oi],
        "top_put_oi": [{"strike": s["strike"], "oi": s["pe"].get("oi") or 0} for s in top_put_oi],
    }


# --- Phase 7: workspace (drawings, layouts, alerts) ------------------------


def _user_id(current_user: dict) -> str:
    return str(current_user["_id"])


@router.get("/drawings")
async def list_drawings(
    security_id: str, exchange_segment: str, current_user: dict = Depends(get_current_user),
):
    return {"drawings": await chart_workspace.list_drawings(_user_id(current_user), security_id, exchange_segment)}


@router.post("/drawings")
async def create_drawing(
    payload: dict, security_id: str, exchange_segment: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await chart_workspace.save_drawing(
            _user_id(current_user), security_id, exchange_segment, payload
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/drawings/{drawing_id}")
async def remove_drawing(drawing_id: str, current_user: dict = Depends(get_current_user)):
    if not await chart_workspace.delete_drawing(_user_id(current_user), drawing_id):
        raise HTTPException(status_code=404, detail="No such drawing")
    return {"deleted": True}


@router.get("/layouts")
async def list_layouts(current_user: dict = Depends(get_current_user)):
    return {"layouts": await chart_workspace.list_layouts(_user_id(current_user))}


@router.post("/layouts")
async def create_layout(payload: dict, current_user: dict = Depends(get_current_user)):
    try:
        return await chart_workspace.save_layout(_user_id(current_user), payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/layouts/{layout_id}")
async def remove_layout(layout_id: str, current_user: dict = Depends(get_current_user)):
    if not await chart_workspace.delete_layout(_user_id(current_user), layout_id):
        raise HTTPException(status_code=404, detail="No such layout")
    return {"deleted": True}


@router.get("/alerts")
async def list_alerts(security_id: str | None = None, current_user: dict = Depends(get_current_user)):
    return {"alerts": await chart_workspace.list_alerts(_user_id(current_user), security_id)}


@router.post("/alerts")
async def create_alert(payload: dict, current_user: dict = Depends(get_current_user)):
    try:
        return await chart_workspace.create_alert(_user_id(current_user), payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/alerts/{alert_id}")
async def remove_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    if not await chart_workspace.delete_alert(_user_id(current_user), alert_id):
        raise HTTPException(status_code=404, detail="No such alert")
    return {"deleted": True}


@router.post("/alerts/evaluate")
async def evaluate_alerts(payload: dict, current_user: dict = Depends(get_current_user)):
    """Fire any alert crossed by a price move the open chart just observed.

    Driven by the chart's own live stream rather than a server-side poller, so
    it costs no extra Dhan calls. The consequence is honest and worth stating:
    alerts are only evaluated while a chart for that instrument is open. A
    background evaluator would need its own quote loop, which is exactly the
    kind of Dhan-load increase this plan is meant to avoid — and out-of-app
    delivery is blocked on notification-service existing at all.
    """
    try:
        last_price = float(payload["last_price"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=422, detail="last_price must be a number")
    previous = payload.get("previous_price")
    fired = await chart_workspace.evaluate_alerts(
        _user_id(current_user),
        str(payload.get("security_id")),
        payload.get("exchange_segment"),
        last_price,
        float(previous) if previous is not None else None,
    )
    return {"triggered": fired}
