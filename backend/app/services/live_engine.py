"""Orchestrator for Phase 5 strategy runs: one-shot modes (HISTORICAL/BACKTEST/REPLAY/
SIMULATION) execute immediately and persist their result; PAPER/LIVE register an
in-memory `StrategyRunner`, add their (symbol, timeframe) to the `live_watchlist`
collection so market-data-service's live_feed.py starts polling it, and receive
finalized bars through one shared Redis subscription — the same pattern
`ws/manager.py` already uses for the dashboard feed."""

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import redis.asyncio as redis
from anyio import to_thread

from app.core.config import settings
from app.core.db import (
    broker_credentials_collection,
    instruments_collection,
    live_watchlist_collection,
    strategy_runs_collection,
)
from app.core.encryption import decrypt_secret
from app.services.dhan_client import DhanClient
from app.services.portfolio_analytics import get_risk_status
from app.services.strategy_runner import LiveExecutor, PaperExecutor, StrategyRunner, run_one_shot
from backtesting_service.costs import CostModel
from backtesting_service.service import load_bars
from risk_service import RiskEngine, RiskLimits, SizingConfig
from strategy_service.live.synthetic import generate_synthetic_bars
from tradingai_shared.contracts import STRATEGY_REGISTRY
from tradingai_shared.domain import AssetClass, Bar, ExecutionMode, Timeframe

BARS_UPDATES_CHANNEL = "bars_updates"
ONE_SHOT_MODES = {ExecutionMode.HISTORICAL, ExecutionMode.BACKTEST, ExecutionMode.REPLAY, ExecutionMode.SIMULATION}
BOOTSTRAP_BAR_COUNT = 300


class LiveEngine:
    def __init__(self) -> None:
        self._runners: dict[str, StrategyRunner] = {}
        self._by_key: dict[tuple[str, str], set[str]] = {}
        self._redis: redis.Redis | None = None
        self._listener_task: asyncio.Task | None = None

    async def start_run(self, user_id: str, request) -> dict:
        if request.strategy_id not in STRATEGY_REGISTRY:
            raise ValueError(f"unknown strategy {request.strategy_id!r}")
        mode = ExecutionMode(request.mode)
        timeframe = Timeframe(request.timeframe)
        strategy_cls = STRATEGY_REGISTRY[request.strategy_id]
        run_id = uuid4().hex[:16]
        now = datetime.now(timezone.utc)

        if mode in ONE_SHOT_MODES:
            result = await self._run_one_shot(request, mode, timeframe)
            doc = {
                "run_id": run_id, "user_id": user_id, "strategy_id": request.strategy_id,
                "symbol": request.symbol, "timeframe": request.timeframe, "mode": mode.value,
                "status": "COMPLETED", "started_at": now, "stopped_at": now,
                "result": result, "snapshot": None,
            }
            await strategy_runs_collection.insert_one(doc)
            return {**doc, "_id": None}

        # PAPER / LIVE: a standing run against live bars
        if mode == ExecutionMode.LIVE and not request.confirm_live:
            raise ValueError("LIVE mode requires confirm_live=true — this places real orders")

        instrument = await instruments_collection.find_one({"symbol": request.symbol})
        if instrument is None:
            raise ValueError(f"{request.symbol} not in the instruments universe — run universe.py")

        client = await self._dhan_client(user_id)
        if mode == ExecutionMode.LIVE:
            risk_status = await get_risk_status(client)
            if risk_status["kill_switch_active"]:
                raise ValueError(f"risk kill-switch active ({', '.join(risk_status['kill_switch_reasons'])}) — refusing to start a LIVE run")

        bars = await to_thread.run_sync(load_bars, request.symbol, timeframe, None)
        bootstrap = bars[-BOOTSTRAP_BAR_COUNT:]
        if len(bootstrap) < strategy_cls(params=request.params or {}).warmup:
            raise ValueError(
                f"only {len(bootstrap)} bars available for {request.symbol} {timeframe.value} — "
                "not enough to cover the strategy's warmup"
            )

        cost_model = CostModel()
        asset_class = AssetClass(instrument["asset_class"])
        product = cost_model.product_for(asset_class, timeframe in {Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1})
        executor = (
            LiveExecutor(client, instrument["security_id"], instrument["exchange_segment"], "INTRADAY", cost_model, product)
            if mode == ExecutionMode.LIVE
            else PaperExecutor(cost_model, product)
        )
        risk = RiskEngine(RiskLimits(**request.risk_limits) if request.risk_limits else RiskLimits())
        sizing = SizingConfig(**request.sizing) if request.sizing else SizingConfig()

        runner = StrategyRunner(
            run_id=run_id, strategy=strategy_cls(params=request.params or {}), symbol=request.symbol,
            timeframe=timeframe, mode=mode, risk=risk, sizing=sizing, cost_model=cost_model,
            asset_class=asset_class, lot_size=instrument.get("lot_size", 1), executor=executor,
            initial_capital=request.initial_capital, bootstrap_bars=bootstrap,
        )
        self._runners[run_id] = runner
        key = (request.symbol, timeframe.value)
        self._by_key.setdefault(key, set()).add(run_id)

        await live_watchlist_collection.update_one(
            {"symbol": request.symbol, "timeframe": timeframe.value},
            {"$set": {
                "symbol": request.symbol, "timeframe": timeframe.value,
                "security_id": instrument["security_id"], "exchange_segment": instrument["exchange_segment"],
            }},
            upsert=True,
        )
        doc = {
            "run_id": run_id, "user_id": user_id, "strategy_id": request.strategy_id,
            "symbol": request.symbol, "timeframe": timeframe.value, "mode": mode.value,
            "status": "RUNNING", "started_at": now, "stopped_at": None,
            "result": None, "snapshot": runner.snapshot(),
        }
        await strategy_runs_collection.insert_one(doc)
        await self._ensure_listener()
        return {**doc, "_id": None}

    async def stop_run(self, run_id: str) -> bool:
        runner = self._runners.pop(run_id, None)
        if runner is None:
            return False
        key = (runner.symbol, runner.timeframe.value)
        self._by_key.get(key, set()).discard(run_id)
        if not self._by_key.get(key):
            self._by_key.pop(key, None)
            await live_watchlist_collection.delete_one({"symbol": key[0], "timeframe": key[1]})
        await strategy_runs_collection.update_one(
            {"run_id": run_id},
            {"$set": {"status": "STOPPED", "stopped_at": datetime.now(timezone.utc), "snapshot": runner.snapshot()}},
        )
        return True

    async def _run_one_shot(self, request, mode: ExecutionMode, timeframe: Timeframe) -> dict:
        if mode == ExecutionMode.SIMULATION:
            bars = generate_synthetic_bars(request.symbol, timeframe, n_bars=request.simulation_bars or 300)
        else:
            years = request.years if mode == ExecutionMode.REPLAY else None
            bars = await to_thread.run_sync(load_bars, request.symbol, timeframe, years)
        if not bars:
            raise ValueError(f"no bars for {request.symbol} {timeframe.value}")
        return await to_thread.run_sync(
            run_one_shot, request.strategy_id, request.symbol, timeframe, bars, mode,
            request.initial_capital, request.params or {}, None, None,
        )

    async def _dhan_client(self, user_id: str) -> DhanClient:
        creds = await broker_credentials_collection.find_one({"user_id": user_id, "broker": "dhan"})
        if creds is None:
            raise ValueError("Dhan account not connected")
        return DhanClient(client_id=creds["client_id"], access_token=decrypt_secret(creds["access_token_encrypted"]))

    async def _ensure_listener(self) -> None:
        if self._listener_task is None:
            self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(BARS_UPDATES_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, ValueError):
                continue
            if not payload.get("final"):
                continue
            key = (payload["symbol"], payload["timeframe"])
            for run_id in list(self._by_key.get(key, set())):
                await self._dispatch(run_id, payload)

    async def _dispatch(self, run_id: str, payload: dict) -> None:
        runner = self._runners.get(run_id)
        if runner is None:
            return
        bar = Bar(
            symbol=payload["symbol"], timeframe=payload["timeframe"],
            ts=datetime.fromisoformat(payload["ts"]), open=payload["open"], high=payload["high"],
            low=payload["low"], close=payload["close"], volume=payload.get("volume", 0), oi=payload.get("oi"),
        )
        try:
            snapshot = await runner.on_finalized_bar(bar)
            await strategy_runs_collection.update_one({"run_id": run_id}, {"$set": {"snapshot": snapshot}})
        except Exception as exc:
            await strategy_runs_collection.update_one(
                {"run_id": run_id},
                {"$set": {"status": "ERROR", "stopped_at": datetime.now(timezone.utc), "error": str(exc)}},
            )
            self._runners.pop(run_id, None)


engine = LiveEngine()
