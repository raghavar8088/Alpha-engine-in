"""Mongo wiring for the Pre-Live paper desk. Same DB as everything else; all pre-live
state lives in its own `prelive_*` collections so it never mixes with real broker data
(mirrors antigravity's pre_live account-key segregation)."""

import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "tradingai")

_client = MongoClient(MONGO_URL)
_db = _client[MONGO_DB_NAME]

trades_collection = _db["prelive_trades"]          # closed paper trades
positions_collection = _db["prelive_positions"]    # currently open paper positions
equity_collection = _db["prelive_equity"]          # intraday equity snapshots
daily_pnl_collection = _db["prelive_daily_pnl"]    # one doc per session
scores_collection = _db["prelive_strategy_scores"] # per-strategy leaderboard
state_collection = _db["prelive_state"]            # singleton engine heartbeat/status
instruments_collection = _db["instruments"]
