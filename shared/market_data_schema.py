"""Shared field names/constants for market data, used by both backend and market-data-service
to keep the snapshot dict shape consistent without a hard package dependency between them."""

MARKET_DATA_FIELDS = ["symbol", "price", "change", "pct_change", "volume", "updated_at"]
MARKET_DATA_REDIS_CHANNEL = "market_data_updates"
