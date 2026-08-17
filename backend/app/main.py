import asyncio
import base64
import json
import logging
import os
import time

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user
from app.api.routes import (
    swing_trading,
    nifty_scalp,
    ai,
    backtest,
    broker,
    bullish_stocks,
    chart_data,
    commodity,
    fno_positions,
    intraday_lab,
    live,
    live_intraday,
    live_trading,
    long_horizon,
    manual_positions,
    market_data,
    momentum,
    options,
    portfolio,
    prelive,
    prelive_selling,
    research,
    risk,
    stock_desk,
    buy_low,
    live_paper,
    momentum_trading,
    zero_hero,
    stocks_range,
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


# Every desk writes an equity snapshot on each scheduler tick (~every 180s). Left alone
# that is a few hundred rows per desk per day, forever — and with a dozen desks it is what
# filled a 512MB Atlas tier and blocked ALL writes, taking the whole app down. These
# collections are for charting recent history, not a permanent record, so they expire.
# Same for the high-churn snapshot/log collections.
# Every desk filters positions on these; without them each summary is a collection scan
# that gets slower as history grows. Cheap to create, idempotent, safe to re-run.
DESK_INDEXES: dict[str, list] = {
    "nifty_scalp_positions": [[("status", 1)], [("strategy_id", 1), ("status", 1)], [("closed_on", 1)], [("timeframe", 1)]],
    "live_intraday_positions": [[("book", 1), ("status", 1)], [("strategy_id", 1), ("book", 1), ("status", 1)], [("closed_on", 1)]],
    "intraday_lab_positions": [[("status", 1)], [("strategy_id", 1), ("status", 1)], [("closed_on", 1)]],
    "live_trading_positions": [[("status", 1)], [("strategy_id", 1), ("status", 1)]],
    "momentum_trading_positions": [[("bucket", 1), ("status", 1)], [("closed_on", 1)]],
    "swing_positions": [[("status", 1)], [("closed_on", 1)]],
    "swing_watchlist": [[("status", 1)], [("symbol", 1), ("status", 1)]],
    "buy_low_positions": [[("status", 1)], [("closed_on", 1)]],
    "zero_hero_positions": [[("status", 1)], [("closed_on", 1)]],
    "stock_desk_positions": [[("side", 1), ("status", 1)], [("closed_on", 1)]],
}


async def ensure_desk_indexes() -> None:
    from app.core.db import db as _db
    made = 0
    for coll, keys in DESK_INDEXES.items():
        for key in keys:
            try:
                await _db[coll].create_index(key, background=True)
                made += 1
            except Exception:  # noqa: BLE001 - a missing collection is not an error here
                pass
    logger.info("desk indexes ensured (%s)", made)


async def warm_mongo_pool() -> None:
    """Open the minimum pool before the first user request instead of during it."""
    from app.core.db import client as _client
    import asyncio as _asyncio
    try:
        await _asyncio.gather(*[_client.admin.command("ping") for _ in range(8)])
        logger.info("mongo pool warmed")
    except Exception:  # noqa: BLE001
        logger.warning("could not warm the mongo pool", exc_info=True)


EXPIRING_COLLECTIONS = {
    "swing_equity": 120,
    "nse_volume_gainers": 120,
    "nifty_scalp_equity": 30,
    "nifty_scalp_signals": 30,
    "stock_desk_equity": 14,
    "zero_hero_equity": 14,
    "buy_low_equity": 14,
    "live_paper_equity": 14,
    "live_trading_equity": 30,
    "momentum_trading_equity": 14,
    "intraday_lab_equity": 14,
    "prelive_equity": 30,
    "prelive_selling_equity": 30,
    "market_data_history": 7,
    "fno_stock_roll_log": 30,
    "zero_hero_signals": 30,
    "buy_low_signals": 30,
}


@app.on_event("startup")
async def ensure_ttl_indexes() -> None:
    """Give the high-churn snapshot collections a TTL so they cannot grow without bound.

    Mongo needs a DATE field to expire on; every one of these writes `ts`, so the index is
    on `ts` with expireAfterSeconds. Creating an index that already exists with the same
    spec is a no-op, so this is safe on every boot."""
    from app.core.db import db

    for name, days in EXPIRING_COLLECTIONS.items():
        try:
            await db[name].create_index("ts", expireAfterSeconds=days * 24 * 3600,
                                        name=f"{name}_ttl")
        except Exception as exc:  # an existing conflicting index must not block startup
            logger.warning("TTL index on %s skipped (%s)", name, exc)


@app.on_event("startup")
async def startup_warm_and_index() -> None:
    """Pay the Atlas handshake and the index creation here, not inside the first request
    a user makes. Both are idempotent and neither may block the app from starting."""
    try:
        await warm_mongo_pool()
        await ensure_desk_indexes()
    except Exception:  # noqa: BLE001
        logger.warning("startup warm/index step failed; serving anyway", exc_info=True)


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
async def start_commodity_scheduler() -> None:
    from app.services.commodity_patterns import COMMODITY_CATALOG
    from app.services.commodity_scheduler import (
        BARS_TICK_SECONDS, DESK_TICK_SECONDS, ENABLED as COMMODITY_ON,
        commodity_bars_loop, commodity_desk_loop,
    )

    if COMMODITY_ON:
        asyncio.create_task(commodity_bars_loop())
        asyncio.create_task(commodity_desk_loop())
        logger.info(
            "Commodity Trading desk enabled — %d pattern strategies on MCX front-month "
            "futures (bars every %ss, desk every %ss, 09:00-23:30 IST, paper)",
            len(COMMODITY_CATALOG), BARS_TICK_SECONDS, DESK_TICK_SECONDS,
        )
    else:
        logger.info("Commodity Trading desk disabled (COMMODITY_ENABLED=0)")


@app.on_event("startup")
async def start_fno_auto_roll_scheduler() -> None:
    from app.services.fno_auto_roll import (
        ACCOUNT_NAME, ENABLED as ROLL_ENABLED, LOTS, ROLL_HHMM, SYMBOL, fno_auto_roll_loop,
    )

    if ROLL_ENABLED:
        asyncio.create_task(fno_auto_roll_loop())
        logger.info(
            "F&O auto-roll enabled — %r rolls its %s %d-lot ATM straddle daily at %s IST (paper)",
            ACCOUNT_NAME, SYMBOL, LOTS, ROLL_HHMM,
        )
    else:
        logger.info("F&O auto-roll disabled (FNO_AUTO_ROLL_ENABLED=0)")


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
    """Stamp Angel `symboltoken`s onto our instrument docs so every desk can quote off
    Angel One. Idempotent; runs in the background (a slow scrip-master download never
    blocks startup) and then re-runs DAILY, so as weekly option expiries roll and new
    strikes list, the option chain stays fully mapped without a redeploy. No-op unless
    Angel is configured."""
    from app.services.angel_client import angel_client

    if not angel_client.configured():
        logger.info("Angel token-map refresh skipped — Angel One not configured")
        return

    interval = int(os.getenv("ANGEL_TOKEN_REFRESH_HOURS", "12")) * 3600

    async def _run() -> None:
        while True:
            try:
                from app.services.angel_instruments import refresh_angel_tokens

                result = await refresh_angel_tokens()
                logger.info("Angel token map refreshed: %s", result)
            except Exception:
                logger.exception("Angel token-map refresh failed — desks fall back to Dhan")
            await asyncio.sleep(interval)

    asyncio.create_task(_run())


@app.on_event("startup")
async def seed_stock_universe() -> None:
    """Load the Nifty 50/100/250/500 constituents (with sector) for the Stocks Range
    module from niftyindices.com. Background on startup, then weekly — the indices only
    rebalance quarterly."""
    async def _run() -> None:
        while True:
            try:
                from app.services.stocks_range import refresh_stock_universe

                result = await refresh_stock_universe()
                logger.info("Stocks Range universe seeded: %s", result)
            except Exception:
                logger.exception("Stock universe seed failed")
            await asyncio.sleep(7 * 24 * 3600)

    asyncio.create_task(_run())


@app.on_event("startup")
async def backfill_stock_bars() -> None:
    """Keep bars_collection topped up with recent daily candles for the whole Stocks Range
    universe, so the 1-week change and stock/sector trend columns fill in for every stock —
    not just the ~200 that carried bars from an old load. Runs shortly after startup (the
    universe seed + Angel token map are both already persisted), then daily. Paced; never
    blocks startup."""
    async def _run() -> None:
        await asyncio.sleep(90)  # let seed_stock_universe run first
        while True:
            try:
                from app.services.stocks_range import backfill_universe_bars

                result = await backfill_universe_bars()
                logger.info("Stocks Range bars backfill: %s", result)
            except Exception:
                logger.exception("Stocks Range bars backfill failed")
            await asyncio.sleep(24 * 3600)

    asyncio.create_task(_run())


@app.on_event("startup")
async def seed_all_time_highs() -> None:
    """Bullish Stocks needs a genuine all-time high, which no window of bars_collection can
    give. Walk each symbol's full Angel history ONCE into stock_highs (only_missing, so this
    is a no-op after the first run and only picks up newly-added constituents), then keep it
    current daily from the bars the Stocks Range backfill already stores."""
    async def _run() -> None:
        await asyncio.sleep(180)  # after the universe seed and the bars backfill
        while True:
            try:
                from app.services.stock_highs import backfill_all_time_highs, bump_from_bars

                seeded = await backfill_all_time_highs(only_missing=True)
                bumped = await bump_from_bars()
                logger.info("All-time highs: seeded=%s bumped=%s", seeded, bumped)
            except Exception:
                logger.exception("All-time-high backfill failed")
            await asyncio.sleep(24 * 3600)

    asyncio.create_task(_run())


@app.on_event("startup")
async def refresh_stock_fundamentals() -> None:
    """Daily Yahoo fundamentals for the Bullish Stocks screen (growth, margins, debt, ROE,
    institutional holding). Stale-only by default, paced, and entirely optional — if Yahoo
    or yfinance is unavailable the screen still runs and simply reports stocks as ungraded."""
    async def _run() -> None:
        await asyncio.sleep(300)  # last in the queue; nothing else depends on it
        while True:
            try:
                from app.services.stock_fundamentals import refresh_fundamentals

                result = await refresh_fundamentals()
                logger.info("Stock fundamentals refresh: %s", result)
            except Exception:
                logger.exception("Stock fundamentals refresh failed")
            await asyncio.sleep(24 * 3600)

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
app.include_router(live_intraday.router)
app.include_router(live_trading.router)
app.include_router(momentum.router)
app.include_router(commodity.router)
app.include_router(stock_desk.router)
app.include_router(zero_hero.router)
app.include_router(buy_low.router)
app.include_router(live_paper.router)
app.include_router(momentum_trading.router)
app.include_router(nifty_scalp.router)
app.include_router(swing_trading.router)
app.include_router(stocks_range.router)
app.include_router(bullish_stocks.router)
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
