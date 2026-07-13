"""Orchestrator + persistence: the one entry point (`run_backtest`) shared by the CLI
and the backend route. Loads bars and instrument metadata from Mongo, runs the engine +
analyses, persists the result document to the `backtests` collection, returns it.

Sync pymongo by design — the FastAPI route calls this in a worker thread so a long
simulation never blocks the event loop."""

import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import DESCENDING, MongoClient

from backtesting_service.charts import compute_charts
from backtesting_service.engine import BacktestConfig, BacktestEngine
from backtesting_service.metrics import compute_metrics
from backtesting_service.montecarlo import monte_carlo
from backtesting_service.optimizer import optimize
from backtesting_service.walkforward import walk_forward
from tradingai_shared.contracts import STRATEGY_REGISTRY
from tradingai_shared.domain import AssetClass, Bar, Timeframe

load_dotenv()

_client: MongoClient | None = None


def _db():
    global _client
    if _client is None:
        _client = MongoClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"), tz_aware=True)
    return _client[os.getenv("MONGO_DB_NAME", "tradingai")]


def load_bars(symbol: str, timeframe: Timeframe, years: float | None = None) -> list[Bar]:
    query: dict = {"symbol": symbol, "timeframe": timeframe.value}
    if years:
        query["ts"] = {"$gte": datetime.now(timezone.utc) - timedelta(days=int(years * 365))}
    cursor = _db()["bars"].find(query).sort("ts", 1)
    return [Bar(**{k: v for k, v in doc.items() if k != "_id"}) for doc in cursor]


BENCHMARK_SYMBOL = "NIFTY"


def load_benchmark(strategy, symbol: str, timeframe: Timeframe, years: float | None) -> list[Bar] | None:
    """NIFTY series for relative-strength strategies (None for NIFTY itself — a symbol
    is never its own benchmark)."""
    if not getattr(strategy, "requires_benchmark", False) or symbol == BENCHMARK_SYMBOL:
        return None
    return load_bars(BENCHMARK_SYMBOL, timeframe, years)


def run_backtest(
    strategy_id: str,
    symbol: str,
    timeframe: Timeframe,
    years: float | None = None,
    initial_capital: float = 1_000_000,
    params: dict | None = None,
    config_overrides: dict | None = None,
    param_grid: dict | None = None,
    with_walk_forward: bool = False,
    with_monte_carlo: bool = False,
    persist: bool = True,
) -> dict:
    if strategy_id not in STRATEGY_REGISTRY:
        raise ValueError(f"unknown strategy {strategy_id!r}")
    bars = load_bars(symbol, timeframe, years)
    if not bars:
        raise ValueError(
            f"no bars for {symbol} {timeframe.value} — run market-data-service/backfill.py first"
        )

    instrument = _db()["instruments"].find_one({"symbol": symbol})
    config = BacktestConfig(
        strategy_id=strategy_id,
        symbol=symbol,
        timeframe=timeframe,
        initial_capital=initial_capital,
        asset_class=AssetClass(instrument["asset_class"]) if instrument else AssetClass.INDEX,
        lot_size=instrument.get("lot_size", 1) if instrument else 1,
        params=params or {},
        **(config_overrides or {}),
    )

    strategy = STRATEGY_REGISTRY[strategy_id](params=config.params)
    benchmark = load_benchmark(strategy, symbol, timeframe, years)
    run = BacktestEngine(strategy, config).run(bars, benchmark_bars=benchmark)

    doc = {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "timeframe": timeframe.value,
        "start": bars[0].ts,
        "end": bars[-1].ts,
        "bar_count": len(bars),
        "config": config.model_dump(mode="json"),
        "metrics": compute_metrics(run),
        "charts": compute_charts(run),
        "created_at": datetime.now(timezone.utc),
    }
    if with_walk_forward:
        grid = param_grid or _default_grid(strategy_id, config.params)
        doc["walk_forward"] = walk_forward(config, bars, grid)
    if with_monte_carlo:
        doc["monte_carlo"] = monte_carlo(run)
    if param_grid and not with_walk_forward:
        doc["optimization"] = optimize(config, bars, param_grid)[:20]

    if persist:
        collection = _db()["backtests"]
        collection.create_index([("created_at", DESCENDING)], name="created_at")
        result = collection.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
    return doc


def _default_grid(strategy_id: str, base_params: dict) -> dict:
    """Fallback walk-forward grid: +/-50% around each numeric int param default. A real
    research grid should come from the caller; this keeps WF usable out of the box."""
    defaults = STRATEGY_REGISTRY[strategy_id].Params().model_dump()
    merged = {**defaults, **base_params}
    grid = {}
    for key, value in merged.items():
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        candidates = sorted({max(2, value // 2), value, value + value // 2})
        grid[key] = candidates
    return grid
