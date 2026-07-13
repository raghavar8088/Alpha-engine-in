import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "tradingai")

_client = MongoClient(MONGO_URL)
_db = _client[MONGO_DB_NAME]
credentials_collection = _db["broker_credentials"]


def get_dhan_credentials() -> list[dict]:
    """One doc per user with a connected Dhan account: user_id, client_id, access_token_encrypted."""
    return list(credentials_collection.find({"broker": "dhan"}))
