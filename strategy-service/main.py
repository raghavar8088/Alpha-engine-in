"""Strategy-service CLI: run a registered strategy over bars stored in Mongo and print
the signals it emits.

Examples:
    python main.py --list
    python main.py --strategy ema_cross --symbol NIFTY --timeframe 1d
    python main.py --strategy ema_cross --symbol NIFTY --timeframe 1d --params "{\"fast\": 9, \"slow\": 21}"
"""

import argparse
import json
import os

from dotenv import load_dotenv
from pymongo import MongoClient

from strategy_service import STRATEGY_REGISTRY
from strategy_service.runner import run_historical
from tradingai_shared.domain import Bar, Timeframe

load_dotenv()


def load_bars(symbol: str, timeframe: Timeframe) -> list[Bar]:
    client = MongoClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"), tz_aware=True)
    collection = client[os.getenv("MONGO_DB_NAME", "tradingai")]["bars"]
    cursor = collection.find({"symbol": symbol, "timeframe": timeframe.value}).sort("ts", 1)
    return [Bar(**{k: v for k, v in doc.items() if k != "_id"}) for doc in cursor]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a strategy over stored bars")
    parser.add_argument("--list", action="store_true", help="list registered strategies")
    parser.add_argument("--strategy", help="strategy_id from the registry")
    parser.add_argument("--symbol", help="e.g. NIFTY")
    parser.add_argument("--timeframe", default="1d", help="1m,5m,15m,1h,1d,1w")
    parser.add_argument("--params", default="{}", help="JSON overrides for the strategy params")
    args = parser.parse_args()

    if args.list:
        for sid, cls in sorted(STRATEGY_REGISTRY.items()):
            m = cls.metadata
            print(f"{sid:24s} {m.category:14s} {m.name} — {m.description}")
        raise SystemExit(0)

    if not args.strategy or not args.symbol:
        parser.error("--strategy and --symbol are required (or use --list)")
    if args.strategy not in STRATEGY_REGISTRY:
        parser.error(f"unknown strategy {args.strategy!r} — run with --list")

    strategy = STRATEGY_REGISTRY[args.strategy](params=json.loads(args.params))
    bars = load_bars(args.symbol, Timeframe(args.timeframe))
    if not bars:
        raise SystemExit(f"no bars for {args.symbol} {args.timeframe} — run market-data-service/backfill.py first")

    signals = run_historical(strategy, bars)
    print(f"{len(bars)} bars -> {len(signals)} signals from {args.strategy}\n")
    for s in signals:
        sl = f" SL={s.stop_loss}" if s.stop_loss is not None else ""
        tgt = f" TGT={s.target}" if s.target is not None else ""
        print(f"{s.timestamp:%Y-%m-%d %H:%M} {s.signal.value:10s}{sl}{tgt}  {s.reasoning}")
