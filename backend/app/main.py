import asyncio
import base64
import json
import logging
import time

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user
from app.api.routes import (
    ai,
    backtest,
    broker,
    chart_data,
    fno_positions,
    intraday_lab,
    live,
    long_horizon,
    manual_positions,
    market_data,
    options,
    portfolio,
    prelive,
    prelive_selling,
    research,
    risk,
    strategies,
    telegram_signals,
    trading_calls,
    watchlist,
)
from app.api.routes.broker import _get_dhan_client
from app.core.config import settings
from app.core.db import (
    live_watchlist_collection,
    market_data_snapshot_collection,
    strategy_runs_collection,
    trading_calls_collection,
)
from app.services import chart_cache, chart_workspace
from app.ws import broker_manager
from app.ws.manager import manager

logger = logging.getLogger("dhan_totp_refresh")

app = FastAPI(title="TradingAI API")

# Dhan access tokens expire in 24h (SEBI-mandated, fixed regardless of auth method)
# and Dhan permits exactly ONE active token per account — minting a new one can pull
# the token out from under whoever else is holding it (prelive-service rotates its
# own). So this loop wakes often but mints rarely: it only logs in when the stored
# token is missing, unreadable, or nearly expired. Refreshing unconditionally on
# startup is what turned an ordinary container redeploy into a token tug-of-war.
DHAN_TOKEN_CHECK_INTERVAL_SECONDS = 60 * 60
DHAN_TOKEN_REFRESH_MARGIN_SECONDS = 2 * 60 * 60


def _token_seconds_remaining(access_token: str) -> float | None:
    """Seconds left on Dhan's JWT, or None if the claim can't be read.

    Unverified decode on purpose — Dhan validates the token on every call; all we
    need here is the `exp` claim to decide whether a refresh is due.
    """
    try:
        segment = access_token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        exp = payload.get("exp")
        return float(exp) - time.time() if exp else None
    except Exception:
        return None


async def _stored_token_seconds_remaining() -> float | None:
    """Life left on the token already in storage; None if there isn't a usable one."""
    try:
        user = await get_current_user()
        client = await _get_dhan_client(str(user["_id"]))
    except Exception:
        return None
    return _token_seconds_remaining(client.access_token)


async def _dhan_token_refresh_loop() -> None:
    from app.services import dhan_token

    while True:
        try:
            remaining = await _stored_token_seconds_remaining()
            if remaining is None or remaining <= DHAN_TOKEN_REFRESH_MARGIN_SECONDS:
                # Mint through dhan_token.refresh_locked — the SAME cross-process Redis
                # lock that _get_dhan_client and the manual /refresh-token route already
                # use. The old code called totp_login() + store_dhan_credentials() here
                # directly, which was a second, UNLOCKED minting path racing the locked
                # ones: exactly the "token tug-of-war" (one active Dhan token per account,
                # so every unsynchronised login invalidates the others) that dhan_token
                # was built to end. This loop keeps its proactive 2h margin — it just no
                # longer mints outside the lock.
                user = await get_current_user()
                minted = await dhan_token.refresh_locked(str(user["_id"]))
                if minted:
                    logger.info("Dhan access token refreshed via TOTP (under lock)")
                else:
                    logger.info("Dhan token refresh deferred — another owner minted, or auth in cooldown")
            else:
                logger.info("Dhan token still valid for %.1fh — leaving it alone", remaining / 3600)
        except Exception:
            logger.exception("Dhan TOTP auto-refresh failed — will retry next cycle")
        await asyncio.sleep(DHAN_TOKEN_CHECK_INTERVAL_SECONDS)


@app.on_event("startup")
async def ensure_indexes() -> None:
    """No ODM here, so indexes aren't declarative — ensure the Phase 5 ones each
    startup (idempotent; init-mongo.js also declares them for a fresh install)."""
    await strategy_runs_collection.create_index("run_id", unique=True)
    await strategy_runs_collection.create_index("started_at")
    await live_watchlist_collection.create_index([("symbol", 1), ("timeframe", 1)], unique=True)
    await trading_calls_collection.create_index("call_id", unique=True)
    await trading_calls_collection.create_index([("status", 1), ("segment", 1)])
    await chart_cache.ensure_indexes()
    await chart_workspace.ensure_indexes()


@app.on_event("startup")
async def start_dhan_auto_refresh() -> None:
    if settings.dhan_client_id and settings.dhan_pin and settings.dhan_totp_secret:
        asyncio.create_task(_dhan_token_refresh_loop())
        logger.info(
            "Dhan TOTP auto-refresh enabled (checks every %ss, mints only within %sh of expiry)",
            DHAN_TOKEN_CHECK_INTERVAL_SECONDS, DHAN_TOKEN_REFRESH_MARGIN_SECONDS // 3600,
        )
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


@app.on_event("startup")
async def start_long_horizon_scheduler() -> None:
    from app.services.long_horizon_scheduler import LONG_HORIZON_ENABLED, RUN_AFTER_HHMM, long_horizon_loop

    if LONG_HORIZON_ENABLED:
        asyncio.create_task(long_horizon_loop())
        logger.info("Long-Horizon factor desk auto-rebalance enabled (once daily, after %s IST)",
                    RUN_AFTER_HHMM)
    else:
        logger.info("Long-Horizon factor desk auto-rebalance disabled (LONG_HORIZON_ENABLED=0)")


@app.on_event("startup")
async def refresh_angel_equity_tokens() -> None:
    """Stamp Angel `symboltoken`s onto our instrument docs so the Intraday Stocks desk
    can quote equities off Angel One (its primary feed). Idempotent; runs once in the
    background so a slow scrip-master download never blocks startup. No-op unless Angel
    is configured — off-whitelist/local dev falls back to Dhan and needs no map."""
    from app.services.angel_client import angel_client

    if not angel_client.configured():
        logger.info("Angel token-map refresh skipped — Angel One not configured")
        return

    async def _run() -> None:
        try:
            from app.services.angel_instruments import refresh_angel_tokens

            result = await refresh_angel_tokens()
            logger.info("Angel token map refreshed for Intraday Stocks desk: %s", result)
        except Exception:
            logger.exception("Angel token-map refresh failed — desk will fall back to Dhan")

    asyncio.create_task(_run())

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
app.include_router(prelive_selling.router)
app.include_router(watchlist.router)
app.include_router(manual_positions.router)
app.include_router(fno_positions.router)
app.include_router(intraday_lab.router)
app.include_router(long_horizon.router)
app.include_router(chart_data.router)
app.include_router(telegram_signals.router)

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
