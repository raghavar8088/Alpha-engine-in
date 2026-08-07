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
# Stocks Range module — index constituents (Nifty 50/100/250/500) with sector, seeded from
# niftyindices.com, plus the user's per-stock manual "buy range" price.
stock_universe_collection = db["stock_universe"]
stock_ranges_collection = db["stock_ranges"]
# Bullish Stocks module. One small doc per symbol holding the ALL-TIME high (and the date
# it was set), so the screener can test "at an all-time high" without keeping decades of
# daily bars in bars_collection. Seeded by a deep one-off Angel backfill, then nudged
# forward incrementally as new daily bars arrive.
stock_highs_collection = db["stock_highs"]
# Per-symbol fundamentals (growth, margins, debt, ROE, holding, analyst view) refreshed
# daily from Yahoo Finance. Quarterly-changing data, so a daily snapshot is ample.
stock_fundamentals_collection = db["stock_fundamentals"]
# F&O Positions module — user-initiated paper trades on index/stock options & futures
fno_positions_collection = db["fno_positions"]
fno_orders_collection = db["fno_orders"]
# Named paper-trading accounts for the F&O Positions module — each with its own
# capital pool (default ₹1 crore, editable), mirroring manual_accounts.
fno_accounts_collection = db["fno_accounts"]
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
# Live Intraday desk — the curated ₹80k shortlist (8 strategies, ₹10k each) inside the
# Intraday Stocks module; paper today, real money later. Separate from the tournament above.
live_intraday_positions_collection = db["live_intraday_positions"]
live_intraday_trades_collection = db["live_intraday_trades"]
live_intraday_scores_collection = db["live_intraday_scores"]
live_intraday_state_collection = db["live_intraday_state"]
live_intraday_equity_collection = db["live_intraday_equity"]
# Live Trading desk — the REAL-MONEY twin of the Live Intraday shortlist. Same 8
# strategies / ₹10k-per-strategy structure, but routes real Dhan orders when ARMED, with a
# per-strategy enable flag, an ₹80k desk ceiling, a kill switch and panic close-all.
live_trading_positions_collection = db["live_trading_positions"]
live_trading_trades_collection = db["live_trading_trades"]
live_trading_scores_collection = db["live_trading_scores"]
live_trading_state_collection = db["live_trading_state"]
live_trading_equity_collection = db["live_trading_equity"]
live_trading_flags_collection = db["live_trading_flags"]  # per-strategy enabled toggle
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
