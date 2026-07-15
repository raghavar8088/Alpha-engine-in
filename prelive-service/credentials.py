"""Read the connected Dhan account's credentials from Mongo (same pattern as
market-data-service): a Fernet-encrypted access token whose key must match the
backend's BROKER_ENCRYPTION_KEY. Falls back to the plaintext dhan_config.py at the
repo root if no encrypted account is connected - convenient for the local single user.

Every token handed back is validated for expiry first (RC-2 fix): a stale token used
to be swallowed silently by credentials.py and then by every 401 in DhanFeed. Now an
expired/near-expiry token is a loud RuntimeError at startup instead of a quiet no-op."""

import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from db import _db

load_dotenv()

credentials_collection = _db["broker_credentials"]

TOKEN_MIN_REMAINING = timedelta(minutes=15)


def _token_exp(token: str) -> datetime | None:
    """Decode (not verify - we don't have Dhan's signing key) the JWT `exp` claim."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload_b64))
        return datetime.fromtimestamp(data["exp"], tz=timezone.utc)
    except Exception:
        return None


def _check_fresh(client_id: str, token: str, source: str) -> tuple[str, str]:
    exp = _token_exp(token)
    if exp is None:
        print(f"[error] Dhan token from {source} has no decodable exp claim - treating as invalid", flush=True)
        raise RuntimeError(f"Dhan token from {source} is not a decodable JWT")
    now = datetime.now(timezone.utc)
    remaining = exp - now
    if remaining <= timedelta(0):
        print(f"[error] Dhan token from {source} EXPIRED at {exp.isoformat()} "
              f"({-remaining} ago) - refusing to start session", flush=True)
        raise RuntimeError(f"Dhan token from {source} expired at {exp.isoformat()}")
    if remaining < TOKEN_MIN_REMAINING:
        print(f"[error] Dhan token from {source} expires in {remaining} (< {TOKEN_MIN_REMAINING}) "
              f"- refusing to start session, refresh the token first", flush=True)
        raise RuntimeError(f"Dhan token from {source} expires too soon ({exp.isoformat()})")
    return client_id, token


def get_dhan_access() -> tuple[str, str]:
    doc = credentials_collection.find_one({"broker": "dhan"})
    if doc is not None and os.getenv("BROKER_ENCRYPTION_KEY"):
        try:
            fernet = Fernet(os.getenv("BROKER_ENCRYPTION_KEY", "").encode())
            client_id = doc["client_id"]
            token = fernet.decrypt(doc["access_token_encrypted"].encode()).decode()
            return _check_fresh(client_id, token, "Mongo broker_credentials")
        except RuntimeError:
            raise
        except Exception as e:
            print(f"[error] Mongo broker_credentials token could not be decrypted: {e}", flush=True)
    # fallback: plaintext dhan_config.py at D:/INDIAN MARKET
    for root in (r"d:/INDIAN MARKET", os.getenv("DHAN_CONFIG_DIR", "")):
        if root and os.path.isdir(root):
            sys.path.insert(0, root)
            try:
                from dhan_config import DHAN_CONFIG  # type: ignore

                return _check_fresh(DHAN_CONFIG["client_id"], DHAN_CONFIG["access_token"], "dhan_config.py")
            except RuntimeError:
                raise
            except Exception:
                continue
    raise RuntimeError("No Dhan credentials - connect via /settings/broker or set dhan_config.py")
