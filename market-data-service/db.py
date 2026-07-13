import os
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient, ReturnDocument

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "tradingai")

_client = MongoClient(MONGO_URL)
_db = _client[MONGO_DB_NAME]
snapshot_collection = _db["market_data_snapshot"]
history_collection = _db["market_data_history"]


def get_connection():
    """Kept for API-shape parity with the previous psycopg2 version; pymongo manages
    its own connection pool internally so this just returns the shared client."""
    return _client


def upsert_quote(conn, quote: dict, updated_at: datetime) -> None:
    fields = {
        "price": quote["price"],
        "change": quote.get("change"),
        "pct_change": quote.get("pct_change"),
        "volume": quote.get("volume"),
        "updated_at": updated_at,
    }
    snapshot_collection.find_one_and_update(
        {"symbol": quote["symbol"]},
        {"$set": fields},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    history_collection.insert_one({"symbol": quote["symbol"], "recorded_at": updated_at, **fields})
