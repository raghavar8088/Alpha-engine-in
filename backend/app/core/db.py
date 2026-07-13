from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings

client = AsyncIOMotorClient(settings.mongo_url, tz_aware=True)
db = client[settings.mongo_db_name]

users_collection = db["users"]
market_data_snapshot_collection = db["market_data_snapshot"]
market_data_history_collection = db["market_data_history"]
broker_credentials_collection = db["broker_credentials"]
paper_orders_collection = db["paper_orders"]
strategy_validation_collection = db["strategy_validation"]
bars_collection = db["bars"]
risk_config_collection = db["risk_config"]
instruments_collection = db["instruments"]
strategy_runs_collection = db["strategy_runs"]
live_watchlist_collection = db["live_watchlist"]
option_backtests_collection = db["option_backtests"]
option_sweeps_collection = db["option_sweeps"]
research_signals_collection = db["research_signals"]
trading_calls_collection = db["trading_calls"]
# Paper positions auto-opened off each trading call (see app.services.call_positions)
trading_call_positions_collection = db["trading_call_positions"]
# Pre-Live paper desk (real-premium forward paper trading of the top-20 basket)
prelive_trades_collection = db["prelive_trades"]
prelive_positions_collection = db["prelive_positions"]
prelive_equity_collection = db["prelive_equity"]
prelive_daily_pnl_collection = db["prelive_daily_pnl"]
prelive_scores_collection = db["prelive_strategy_scores"]
prelive_state_collection = db["prelive_state"]
