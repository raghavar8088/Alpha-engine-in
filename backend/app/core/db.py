from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings

# minPoolSize is the important one: without it the pool drains to zero between bursts
# and the next query pays a full SRV + TLS + auth handshake to Atlas before it runs —
# measured at 5.2s on a cold pool versus 0.037s on a warm one.
client = AsyncIOMotorClient(
    settings.mongo_url,
    tz_aware=True,
    minPoolSize=8,                 # never let the pool empty
    maxPoolSize=60,
    maxIdleTimeMS=270_000,         # recycle before Atlas drops the socket on its side
    waitQueueTimeoutMS=10_000,
    connectTimeoutMS=8_000,
    serverSelectionTimeoutMS=8_000,
    socketTimeoutMS=45_000,
    retryReads=True,
    retryWrites=True,
    # zlib only: snappy and zstd need optional C extensions this image does not carry,
    # and pymongo warns on every client build when they are advertised but missing.
    compressors="zlib",
)
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
# Stock-option Pre-Live desks — paper buying/selling desks on SINGLE-STOCK options, the
# stock twins of the NIFTY prelive desks. One set of collections for both sides; every doc
# carries `side` ("buying"/"selling") so the two desks stay separable but share the schema.
stock_desk_positions_collection = db["stock_desk_positions"]
stock_desk_trades_collection = db["stock_desk_trades"]
stock_desk_scores_collection = db["stock_desk_scores"]
stock_desk_state_collection = db["stock_desk_state"]
stock_desk_equity_collection = db["stock_desk_equity"]
# Zero Hero Trades — expiry-day deep-OTM INDEX option buying, 50 strategies on Rs1L each.
# Signals are stored separately from positions because most zero-hero signals are NOT
# taken (too expensive, unquotable), and knowing why is the point of the history.
zero_hero_positions_collection = db["zero_hero_positions"]
zero_hero_trades_collection = db["zero_hero_trades"]
zero_hero_scores_collection = db["zero_hero_scores"]
zero_hero_signals_collection = db["zero_hero_signals"]
zero_hero_state_collection = db["zero_hero_state"]
zero_hero_equity_collection = db["zero_hero_equity"]
# Buy Low Options — buys a cheap OTM CALL on any F&O stock down >4% at the 3 PM check.
# Long premium only, so each position's loss is bounded by its cost; signals are kept
# separately because a faller is often skipped (no strike fits the Rs5,100 budget).
buy_low_positions_collection = db["buy_low_positions"]
buy_low_trades_collection = db["buy_low_trades"]
buy_low_signals_collection = db["buy_low_signals"]
buy_low_state_collection = db["buy_low_state"]
buy_low_equity_collection = db["buy_low_equity"]
# Live Paper Buying — the 5 Pre-Live leaderboard winners on a realistic Rs50,000 book
# (Rs10k each), NIFTY ATM options at live Angel premiums. Paper.
live_paper_positions_collection = db["live_paper_positions"]
live_paper_trades_collection = db["live_paper_trades"]
live_paper_scores_collection = db["live_paper_scores"]
live_paper_state_collection = db["live_paper_state"]
live_paper_equity_collection = db["live_paper_equity"]
# Long-Horizon factor desk — cross-sectional (top-K basket) momentum/low-vol/reversal
# strategies, own capital pool, own sweep, mirroring the prelive_* / prelive_selling_*
# separation: different capital, different risk model, different qualification rule.
long_horizon_sweeps_collection = db["long_horizon_sweeps"]
long_horizon_positions_collection = db["long_horizon_positions"]
long_horizon_trades_collection = db["long_horizon_trades"]
long_horizon_scores_collection = db["long_horizon_scores"]
long_horizon_equity_collection = db["long_horizon_equity"]
long_horizon_state_collection = db["long_horizon_state"]
# Strategy Factory — 546 composed strategies (69 hypotheses x 8 timeframes), Rs10L paper
# each. ADDITIVE: every other desk keeps its own collections and engine untouched.
# `sf_backtests` holds one row per (strategy, symbol) rather than an average, because
# "works on crude, fails on gold" is the answer the library exists to give.
sf_backtests_collection = db["sf_backtests"]
sf_scores_collection = db["sf_scores"]
sf_positions_collection = db["sf_positions"]
sf_trades_collection = db["sf_trades"]
sf_signals_collection = db["sf_signals"]
sf_equity_collection = db["sf_equity"]
sf_state_collection = db["sf_state"]
# Commodity Trading desk — 311 chart/candlestick/structure pattern strategies over 8 MCX
# front-month futures on 8 timeframes, ₹10 lakh paper each. `commodity_bars` is the desk's
# own paced bar store (Angel throttles the candle endpoint hard, so strategies read from
# here rather than calling out); only NATIVE intervals are stored, 30m/45m/4h are derived.
commodity_bars_collection = db["commodity_bars"]
commodity_positions_collection = db["commodity_positions"]
commodity_trades_collection = db["commodity_trades"]
commodity_scores_collection = db["commodity_scores"]
commodity_state_collection = db["commodity_state"]
commodity_equity_collection = db["commodity_equity"]
# Daily 3 PM ATM short-straddle roll on ONE named F&O paper account (see
# app.services.fno_auto_roll). `state` holds the once-a-day guard (`last_rolled_on`);
# `log` keeps one row per attempt including aborts, so a day that did not roll always
# says why rather than just showing no trades.
fno_auto_roll_state_collection = db["fno_auto_roll_state"]
fno_auto_roll_log_collection = db["fno_auto_roll_log"]
# Sibling of the NIFTY roll above: the same daily 15:00 close-and-resell, but across the
# WHOLE stock-option universe on its own account (see app.services.fno_stock_roll).
fno_stock_roll_state_collection = db["fno_stock_roll_state"]
fno_stock_roll_log_collection = db["fno_stock_roll_log"]
# Morning-momentum option buying (app.services.morning_momentum): which of the 09:20 /
# 09:30 / 10:00 checkpoints have already run today, so a scheduler retry cannot re-buy.
momentum_buy_state_collection = db["momentum_buy_state"]
# Momentum Trading — intraday CASH-EQUITY momentum: long a stock up 2%, short one down 2%,
# +/-2% target and stop, squared off at 15:00. Separate from the option desks above.
pattern_positions_collection = db["pattern_positions"]
pattern_trades_collection = db["pattern_trades"]
pattern_scores_collection = db["pattern_scores"]
pattern_state_collection = db["pattern_state"]
pattern_equity_collection = db["pattern_equity"]
swing_watchlist_collection = db["swing_watchlist"]
swing_positions_collection = db["swing_positions"]
swing_trades_collection = db["swing_trades"]
swing_equity_collection = db["swing_equity"]
swing_state_collection = db["swing_state"]
nse_volume_gainers_collection = db["nse_volume_gainers"]
nifty_scalp_positions_collection = db["nifty_scalp_positions"]
nifty_scalp_trades_collection = db["nifty_scalp_trades"]
nifty_scalp_scores_collection = db["nifty_scalp_scores"]
nifty_scalp_state_collection = db["nifty_scalp_state"]
nifty_scalp_equity_collection = db["nifty_scalp_equity"]
nifty_scalp_signals_collection = db["nifty_scalp_signals"]
momentum_trading_positions_collection = db["momentum_trading_positions"]
momentum_trading_trades_collection = db["momentum_trading_trades"]
momentum_trading_state_collection = db["momentum_trading_state"]
momentum_trading_equity_collection = db["momentum_trading_equity"]
# The desk trades the top 1000 by market cap (TOTAL MARKET 750 + MICROCAP 250), not F&O.
momentum_universe_collection = db["momentum_universe"]
# Momentum Trading desk — the pre-live gate for the 37-strategy momentum catalog
# (52W-high breakout, relative strength, NSE momentum score, MA stack, ORB, sector
# rotation, volume breakout). ₹10,000 paper account per strategy, and unlike every
# desk above it, fills are charged real NSE transaction costs + slippage — its whole
# purpose is deciding which strategies deserve real money on the Live Trading desk.
momentum_positions_collection = db["momentum_positions"]
momentum_trades_collection = db["momentum_trades"]
momentum_scores_collection = db["momentum_scores"]
momentum_state_collection = db["momentum_state"]
momentum_equity_collection = db["momentum_equity"]
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
# Stock Screener module — momentum / sector rotation / chart patterns over the NSE
# universe. All four collections are DERIVED: every row can be recomputed from
# `bars` + `stock_universe`, so they are snapshots for history and fast first paint,
# never a source of truth. They are TTL'd in main.py accordingly.
screener_momentum_collection = db["screener_momentum"]
screener_sectors_collection = db["screener_sectors"]
screener_patterns_collection = db["screener_patterns"]
screener_breadth_collection = db["screener_breadth"]
# Trending Stocks — LONG-ONLY desk over a basket the USER names, 678 strategies at
# ₹10,00,000 paper each. `ts_basket` is the only user-authored collection in the module;
# everything else is produced by the engine. Two of these have no counterpart anywhere
# else in the app and are the point of the desk:
#   `ts_evidence`   the seven research pillars scored at ENTRY TIME, so the reason a
#                   position was taken is a record rather than a later reconstruction.
#   `ts_rejections` why a setup did NOT become a trade. "No trades today" and "forty
#                   setups all failed the 1:6 reachability test" look identical from the
#                   outside, and only one of them means the desk is working as designed.
# Bars are NOT stored here — they go into the shared `bars` collection, so the deeper
# intraday history this desk backfills is available to every other module.
ts_basket_collection = db["ts_basket"]
ts_backtests_collection = db["ts_backtests"]
ts_validation_collection = db["ts_validation"]
ts_scores_collection = db["ts_scores"]
ts_positions_collection = db["ts_positions"]
ts_trades_collection = db["ts_trades"]
ts_signals_collection = db["ts_signals"]
ts_rejections_collection = db["ts_rejections"]
ts_evidence_collection = db["ts_evidence"]
ts_equity_collection = db["ts_equity"]
ts_state_collection = db["ts_state"]
# Stock Screener upgrade: NSE end-of-day bhavcopy (delivery %, trade counts) and the
# Screener's own paper desk. The bhavcopy rows are a cache of a public archive file and
# are re-fetchable at any time; the paper desk's TRADES are the one thing here that is
# genuinely a record, which is why only equity snapshots expire.
screener_bhavcopy_collection = db["screener_bhavcopy"]
# NSE price bands + the ASM/GSM surveillance frameworks, one snapshot document. A cache of
# public files, re-fetchable at any time — see app.services.nse_surveillance.
screener_meta_collection = db["screener_meta"]
screener_paper_positions_collection = db["screener_paper_positions"]
screener_paper_trades_collection = db["screener_paper_trades"]
screener_paper_equity_collection = db["screener_paper_equity"]
screener_paper_state_collection = db["screener_paper_state"]
# Stock Paper Trading + F&O Paper Trading — a paper BROKER (app.services.paper_broker), not
# another position list. One account trades both segments out of one cash pool, exactly as a
# real broking account does, so every doc carries `segment` rather than the two modules
# owning separate wallets. The ledger is what makes the cash balance explainable; the trade
# book is the only genuinely irreplaceable record here, which is why nothing below expires
# except the engine's own scratch state.
pt_accounts_collection = db["pt_accounts"]
pt_orders_collection = db["pt_orders"]
pt_trades_collection = db["pt_trades"]
pt_positions_collection = db["pt_positions"]
pt_holdings_collection = db["pt_holdings"]
pt_ledger_collection = db["pt_ledger"]
# All Time High Trading — buys ₹1,00,000 of any NSE stock above ₹1,000cr market cap the day
# it prints a new all-time high, and holds to +20% or -20% and nothing else. `ath_signals`
# is kept separate from positions because most signals are NOT taken (no capital, share
# price above the position size) and knowing why is the point of the record.
ath_positions_collection = db["ath_positions"]
ath_trades_collection = db["ath_trades"]
ath_signals_collection = db["ath_signals"]
ath_equity_collection = db["ath_equity"]
ath_state_collection = db["ath_state"]
# All Time High Trading — the hand-built watchlist. One document: the curated symbol list,
# whether the desk runs on the screen / the list / both, and whether the market-cap floor
# still applies to hand-picked names.
ath_watchlist_collection = db["ath_watchlist"]
# Commodity Positions — the MCX twin of the F&O Positions desk (see
# app.services.commodity_positions). Separate collections rather than a `segment` field on
# the F&O ones: the two desks have different capital, different margin calibration, and
# different contract mathematics (an MCX lot carries a value multiplier that NSE F&O does
# not), so a shared book would produce summaries that silently mix them.
# `commodity_pos_*` is deliberately not `commodity_*` — those already belong to the
# 311-strategy Commodity Trading pattern desk and must not be confused with this one.
commodity_accounts_collection = db["commodity_accounts"]
commodity_pos_positions_collection = db["commodity_pos_positions"]
commodity_pos_orders_collection = db["commodity_pos_orders"]
