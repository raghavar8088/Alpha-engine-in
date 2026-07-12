"""Read the connected Dhan account's credentials from Mongo (same pattern as
market-data-service): a Fernet-encrypted access token whose key must match the
backend's BROKER_ENCRYPTION_KEY. Falls back to the plaintext dhan_config.py at the
repo root if no encrypted account is connected — convenient for the local single user."""

import os
import sys

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from db import _db

load_dotenv()

credentials_collection = _db["broker_credentials"]


def get_dhan_access() -> tuple[str, str]:
    doc = credentials_collection.find_one({"broker": "dhan"})
    if doc is not None and os.getenv("BROKER_ENCRYPTION_KEY"):
        try:
            fernet = Fernet(os.getenv("BROKER_ENCRYPTION_KEY", "").encode())
            return doc["client_id"], fernet.decrypt(doc["access_token_encrypted"].encode()).decode()
        except Exception:
            pass
    # fallback: plaintext dhan_config.py at D:/INDIAN MARKET
    for root in (r"d:/INDIAN MARKET", os.getenv("DHAN_CONFIG_DIR", "")):
        if root and os.path.isdir(root):
            sys.path.insert(0, root)
            try:
                from dhan_config import DHAN_CONFIG  # type: ignore

                return DHAN_CONFIG["client_id"], DHAN_CONFIG["access_token"]
            except Exception:
                continue
    raise RuntimeError("No Dhan credentials — connect via /settings/broker or set dhan_config.py")
