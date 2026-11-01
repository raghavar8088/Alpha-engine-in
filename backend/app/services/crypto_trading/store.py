"""Crypto Trading's collections - in the box's second MongoDB (FACTORY_MONGO_URL, the compose
`mongodb` service) like the other new desks, never on the near-quota Atlas cluster.

  ct_universe    the selection: the ten coins, every candidate's verdict, the ranking source and time
  ct_library     one document per strategy: its rules, its crypto verdict (as the sweep read them)
  ct_backtests   one document per strategy-cryptocurrency pair: its crypto backtest and grade
  ct_accounts    one document per pair: its own $10,000 - cash, equity, costs, trades, state
  ct_positions   open and closed paper positions (one open at most per account)
  ct_signals     the live signal feed (expires after 14 days)
  ct_equity      equity snapshots: the desk hourly, each traded account daily
  ct_state       the engine's switch, its per-series progress, the sweep's progress
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("crypto_trading")

_URL = os.getenv("FACTORY_MONGO_URL", "").strip()
_DB = os.getenv("CRYPTO_TRADING_MONGO_DB", "alpha_engine_crypto_trading")


def _open():
    if not _URL:
        from app.core.db import db
        return db
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(_URL, serverSelectionTimeoutMS=5000, maxPoolSize=10)[_DB]


DB = _open()
UNIVERSE = DB["ct_universe"]
LIBRARY = DB["ct_library"]
BACKTESTS = DB["ct_backtests"]
ACCOUNTS = DB["ct_accounts"]
POSITIONS = DB["ct_positions"]
SIGNALS = DB["ct_signals"]
EQUITY = DB["ct_equity"]
STATE = DB["ct_state"]


async def ensure_indexes() -> None:
    try:
        await LIBRARY.create_index([("strategy_id", 1)], name="ct_lib_id", unique=True)
        await BACKTESTS.create_index([("pair_id", 1)], name="ct_bt_pair", unique=True)
        await BACKTESTS.create_index([("status", 1), ("grade", -1)], name="ct_bt_status_grade")
        await BACKTESTS.create_index([("symbol", 1), ("timeframe", 1)], name="ct_bt_symbol_tf")
        await ACCOUNTS.create_index([("eligible", 1), ("status", 1)], name="ct_acc_eligible")
        await ACCOUNTS.create_index([("symbol", 1), ("timeframe", 1)], name="ct_acc_symbol_tf")
        await POSITIONS.create_index([("status", 1), ("symbol", 1)], name="ct_pos_status")
        await POSITIONS.create_index([("pair_id", 1), ("signal_bar_ts", 1)], name="ct_pos_once", unique=True)
        await POSITIONS.create_index([("closed_at", -1)], name="ct_pos_closed")
        await SIGNALS.create_index([("at", -1)], name="ct_sig_at")
        await SIGNALS.create_index([("expires", 1)], name="ct_sig_ttl", expireAfterSeconds=0)
        await EQUITY.create_index([("scope", 1), ("ts", -1)], name="ct_eq_scope_ts")
    except Exception:  # noqa: BLE001 - an index is a speed-up, never a precondition
        logger.warning("[crypto_trading] index creation skipped", exc_info=True)


def store_name() -> str:
    return DB.name
