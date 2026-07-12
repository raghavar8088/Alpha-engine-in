db = db.getSiblingDB("tradingai");

db.createCollection("users");
db.users.createIndex({ email: 1 }, { unique: true });

db.createCollection("market_data_snapshot");
db.market_data_snapshot.createIndex({ symbol: 1 }, { unique: true });

db.createCollection("market_data_history");
db.market_data_history.createIndex({ symbol: 1, recorded_at: -1 });

db.createCollection("broker_credentials");
db.broker_credentials.createIndex({ user_id: 1, broker: 1 }, { unique: true });

db.createCollection("paper_orders");
db.paper_orders.createIndex({ user_id: 1, created_at: -1 });

// Phase 1 foundation (also ensured in code by market-data-service/bars_store.py,
// so existing installs don't need to re-run this script)
db.createCollection("bars");
db.bars.createIndex({ symbol: 1, timeframe: 1, ts: 1 }, { unique: true });

db.createCollection("instruments");
db.instruments.createIndex({ security_id: 1, exchange_segment: 1 }, { unique: true });
db.instruments.createIndex({ symbol: 1 });

// Phase 4 (risk_config is a single upserted doc, no index needed beyond _id)
db.createCollection("risk_config");

// Phase 5 (also ensured in code, so existing installs don't need to re-run this script)
db.createCollection("strategy_runs");
db.strategy_runs.createIndex({ run_id: 1 }, { unique: true });
db.strategy_runs.createIndex({ started_at: -1 });

db.createCollection("live_watchlist");
db.live_watchlist.createIndex({ symbol: 1, timeframe: 1 }, { unique: true });
