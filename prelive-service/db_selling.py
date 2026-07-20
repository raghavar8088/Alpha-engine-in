"""Mongo wiring for the option-SELLING pre-live desk.

Every collection here is a `prelive_selling_*` sibling of the buying desk's `prelive_*`
set, and the separation is deliberate rather than tidy-minded. The two desks have
different capital pools, different risk models and different qualification rules, so a
shared collection would let a bad selling day be reported against the buying desk's
track record (or the reverse) and would make either desk's leaderboard meaningless. The
Phase 5 safety review has "is paper capital isolated between the desks" as an explicit
question; this module is the answer to it.

`option_sweeps_selling` is read-only from here — the backend writes it when a sweep runs,
the daemon only ever consumes the qualified basket.
"""

import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "tradingai")

_client = MongoClient(MONGO_URL)
_db = _client[MONGO_DB_NAME]

# Closed multi-leg paper trades (one doc per structure, legs nested)
trades_collection = _db["prelive_selling_trades"]
# Currently open structures, marked to market on every tick
positions_collection = _db["prelive_selling_positions"]
equity_collection = _db["prelive_selling_equity"]
daily_pnl_collection = _db["prelive_selling_daily_pnl"]
scores_collection = _db["prelive_selling_strategy_scores"]
state_collection = _db["prelive_selling_state"]

instruments_collection = _db["instruments"]
bars_collection = _db["bars"]
# Written by the backend's selling sweep; the daemon reads the qualified basket from it.
option_sweeps_selling_collection = _db["option_sweeps_selling"]
