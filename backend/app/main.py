from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user
from app.api.routes import (
    ai,
    backtest,
    broker,
    live,
    market_data,
    options,
    portfolio,
    prelive,
    research,
    risk,
    strategies,
    trading_calls,
)
from app.core.config import settings
from app.core.db import (
    live_watchlist_collection,
    market_data_snapshot_collection,
    strategy_runs_collection,
    trading_calls_collection,
)
from app.ws import broker_manager
from app.ws.manager import manager

app = FastAPI(title="TradingAI API")


@app.on_event("startup")
async def ensure_indexes() -> None:
    """No ODM here, so indexes aren't declarative — ensure the Phase 5 ones each
    startup (idempotent; init-mongo.js also declares them for a fresh install)."""
    await strategy_runs_collection.create_index("run_id", unique=True)
    await strategy_runs_collection.create_index("started_at")
    await live_watchlist_collection.create_index([("symbol", 1), ("timeframe", 1)], unique=True)
    await trading_calls_collection.create_index("call_id", unique=True)
    await trading_calls_collection.create_index([("status", 1), ("segment", 1)])

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
