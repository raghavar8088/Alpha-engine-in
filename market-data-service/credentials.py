"""Read the connected Dhan account's credentials from Mongo, mirroring broker-service's
db.py/encryption.py pattern: broker_credentials docs hold a Fernet-encrypted access token
and BROKER_ENCRYPTION_KEY must match the backend's exactly."""

import os

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from db import _db

load_dotenv()

credentials_collection = _db["broker_credentials"]


def get_dhan_access() -> tuple[str, str]:
    """Return (client_id, decrypted access_token) for the single local user's Dhan
    account. Raises if no account is connected — historical fetches need it."""
    doc = credentials_collection.find_one({"broker": "dhan"})
    if doc is None:
        raise RuntimeError(
            "No Dhan account connected — connect one via the app's /settings/broker first"
        )
    fernet = Fernet(os.getenv("BROKER_ENCRYPTION_KEY", "").encode())
    return doc["client_id"], fernet.decrypt(doc["access_token_encrypted"].encode()).decode()
