import asyncio
import logging

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user
from app.api.routes import (
    ai,
    backtest,
    broker,
    fno_positions,
    intraday_lab,
    live,
    manual_positions,
    market_data,
    options,
    portfolio,
    prelive,
    research,
    risk,
    strategies,
    trading_calls,
    watchlist,
)
from app.api.routes.broker import store_dhan_credentials
from app.core.config import settings
from app.core.db import (
    live_watchlist_collection,
    market_data_snapshot_collection,
    strategy_runs_collection,
    trading_calls_collection,
)
from app.services.dhan_client import totp_login
from app.ws import broker_manager
from app.ws.manager import manager

logger = logging.getLogger("dhan_totp_refresh")

app = FastAPI(title="TradingAI API")

# Dhan access tokens expire in 24h (SEBI-mandated, fixed regardless of auth method).
# 20h leaves margin on both ends without refreshing needlessly often.
DHAN_TOKEN_REFRESH_INTERVAL_SECONDS = 20 * 60 * 60


async def _dhan_token_refresh_loop() -> None:
    while True:
        try:
            data = await totp_login(settings.dhan_client_id, settings.dhan_pin, settings.dhan_totp_secret)
            user = await get_current_user()
            await store_dhan_credentials(
                str(user["_id"]), str(data["dhanClientId"]), data["accessToken"], data.get("dhanClientName"),
            )
            logger.info("Dhan access token refreshed via TOTP, expires %s", data.get("expiryTime"))
        except Exception:
            logger.exception("Dhan TOTP auto-refresh failed — will retry next cycle")
        await asyncio.sleep(DHAN_TOKEN_REFRESH_INTERVAL_SECONDS)


@app.on_event("startup")
async def ensure_indexes() -> None:
    """No ODM here, so indexes aren't declarative — ensure the Phase 5 ones each
    startup (idempotent; init-mongo.js also declares them for a fresh install)."""
    await strategy_runs_collection.create_index("run_id", unique=True)
    await strategy_runs_collection.create_index("started_at")
    await live_watchlist_collection.create_index([("symbol", 1), ("timeframe", 1)], unique=True)
    await trading_calls_collection.create_index("call_id", unique=True)
    await trading_calls_collection.create_index([("status", 1), ("segment", 1)])


@app.on_event("startup")
async def start_dhan_auto_refresh() -> None:
    if settings.dhan_client_id and settings.dhan_pin and settings.dhan_totp_secret:
        asyncio.create_task(_dhan_token_refresh_loop())
        logger.info("Dhan TOTP auto-refresh enabled (every %ss)", DHAN_TOKEN_REFRESH_INTERVAL_SECONDS)
    else:
        logger.info("Dhan TOTP auto-refresh disabled — DHAN_CLIENT_ID/DHAN_PIN/DHAN_TOTP_SECRET not fully set")


@app.on_event("startup")
async def start_call_scheduler() -> None:
    from app.services.call_scheduler import AUTOGEN_ENABLED, GENERATION_SLOTS, call_scheduler_loop

    if AUTOGEN_ENABLED:
        asyncio.create_task(call_scheduler_loop())
        logger.info("Trading-calls auto-scan enabled (IST slots: %s)", ", ".join(GENERATION_SLOTS))
    else:
        logger.info("Trading-calls auto-scan disabled (CALLS_AUTOGEN_ENABLED=0)")


@app.on_event("startup")
async def start_intraday_lab_scheduler() -> None:
    from app.services.intraday_lab_scheduler import INTRADAY_LAB_ENABLED, TICK_SECONDS, intraday_lab_loop

    if INTRADAY_LAB_ENABLED:
        asyncio.create_task(intraday_lab_loop())
        logger.info("Intraday Strategy Lab auto-scan enabled (every %ss, market hours)", TICK_SECONDS)
    else:
        logger.info("Intraday Strategy Lab auto-scan disabled (INTRADAY_LAB_ENABLED=0)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_shared_secret(request: Request, call_next):
    """Cloud Run must allow unauthenticated calls for the Firebase Hosting rewrite
    to reach it, so this is the only gate stopping random internet traffic from
    hitting a backend whose get_current_user has no real login. No-op locally
    where app_shared_secret is unset."""
    if settings.app_shared_secret and request.url.path not in ("/health",):
        if request.headers.get("x-app-secret") != settings.app_shared_secret:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return await call_next(request)

app.include_router(market_data.router)
app.include_router(broker.router)
app.include_router(strategies.router)
app.include_router(backtest.router)
app.include_router(portfolio.router)
app.include_router(risk.router)
app.include_router(options.router)
app.include_router(ai.router)
app.include_router(research.router)
app.include_router(trading_calls.router)
app.include_router(prelive.router)
app.include_router(watchlist.router)
app.include_router(manual_positions.router)
app.include_router(fno_positions.router)
app.include_router(intraday_lab.router)

if settings.enable_live_trading:
    app.include_router(live.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws/market-data")
async def market_data_ws(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        cursor = market_data_snapshot_collection.find().sort("symbol", 1)
        snapshot = [
            {
                "symbol": doc["symbol"],
                "price": float(doc["price"]),
                "change": float(doc["change"]) if doc.get("change") is not None else None,
                "pct_change": float(doc["pct_change"]) if doc.get("pct_change") is not None else None,
                "volume": doc.get("volume"),
                "updated_at": doc["updated_at"].isoformat(),
            }
            async for doc in cursor
        ]
        await manager.send_snapshot(websocket, snapshot)

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.websocket("/ws/broker/orders")
async def broker_orders_ws(websocket: WebSocket):
    user = await get_current_user()
    user_id = str(user["_id"])

    await broker_manager.manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        broker_manager.manager.disconnect(user_id, websocket)
