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
# Option-SELLING sweeps live in their own collection, never mixed with the buying ones:
# the two are gated on different rules (selling ignores win rate entirely) and carry
# different columns, so a shared history would produce leaderboards that silently
# compare strategies judged by different standards.
option_sweeps_selling_collection = db["option_sweeps_selling"]
research_signals_collection = db["research_signals"]
trading_calls_collection = db["trading_calls"]
# Paper positions auto-opened off each trading call (see app.services.call_positions)
trading_call_positions_collection = db["trading_call_positions"]
# Single state doc for the trading-calls auto-generation scheduler
call_scheduler_state_collection = db["call_scheduler_state"]
# Manual "Positions" module — user-initiated paper trades (search -> buy -> exit)
manual_positions_collection = db["manual_positions"]
manual_orders_collection = db["manual_orders"]
# Named paper-trading accounts for the manual Positions module — each with its own
# independent capital pool, so different strategies can be tracked separately
manual_accounts_collection = db["manual_accounts"]
# F&O Positions module — user-initiated paper trades on index/stock options & futures
fno_positions_collection = db["fno_positions"]
fno_orders_collection = db["fno_orders"]
# Pre-Live paper desk (real-premium forward paper trading of the top-20 basket)
prelive_trades_collection = db["prelive_trades"]
prelive_positions_collection = db["prelive_positions"]
prelive_equity_collection = db["prelive_equity"]
prelive_daily_pnl_collection = db["prelive_daily_pnl"]
prelive_scores_collection = db["prelive_strategy_scores"]
prelive_state_collection = db["prelive_state"]
# Watchlist module — user-created named lists of symbols with live price tracking
watchlists_collection = db["watchlists"]
# Intraday Strategy Lab — 50-strategy auto-trading paper desk (sub-module of Trading Calls)
intraday_lab_positions_collection = db["intraday_lab_positions"]
intraday_lab_trades_collection = db["intraday_lab_trades"]
intraday_lab_scores_collection = db["intraday_lab_scores"]
intraday_lab_state_collection = db["intraday_lab_state"]
intraday_lab_equity_collection = db["intraday_lab_equity"]
intraday_lab_backtests_collection = db["intraday_lab_backtests"]
# Long-Horizon factor desk — cross-sectional (top-K basket) momentum/low-vol/reversal
# strategies, own capital pool, own sweep, mirroring the prelive_* / prelive_selling_*
# separation: different capital, different risk model, different qualification rule.
long_horizon_sweeps_collection = db["long_horizon_sweeps"]
long_horizon_positions_collection = db["long_horizon_positions"]
long_horizon_trades_collection = db["long_horizon_trades"]
long_horizon_scores_collection = db["long_horizon_scores"]
long_horizon_equity_collection = db["long_horizon_equity"]
long_horizon_state_collection = db["long_horizon_state"]
# Telegram Signal Copier — raw channel messages parsed into trade ideas and
# auto-opened as paper positions via the manual Positions module
telegram_signals_collection = db["telegram_signals"]
# Chart module's own durable candle store. Deliberately separate from `bars`:
# that collection is written by two producers with different timestamp
# conventions (backfill stores Dhan's epoch read as UTC, live_feed stores an
# IST-aware bucket), which can't be told apart after the fact. These rows store
# the chart epoch verbatim, so what goes in is exactly what the history endpoint
# serves back out. See app.services.chart_cache.
chart_bars_collection = db["chart_bars"]
# Chart workspace (Phase 7): user drawings/annotations per instrument, named
# layouts (indicator set + timeframe + drawings), and price/indicator alerts.
chart_drawings_collection = db["chart_drawings"]
chart_layouts_collection = db["chart_layouts"]
chart_alerts_collection = db["chart_alerts"]
