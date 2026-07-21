"""Daily Dhan token rotation - RC-2's recurring driver.

Dhan access tokens expire ~24h after issue regardless of auth method (SEBI-mandated),
so a token that was valid yesterday is dead by tomorrow's open. This script generates
a fresh token via TOTP (same flow as backend/app/services/dhan_client.py:totp_login,
DhanLogin.generate_token per dhan_api_reference.py) and writes it to BOTH places
credentials.py can read from:

  1. Mongo broker_credentials (Fernet-encrypted, same doc the backend/prelive/
     market-data services all read) - the primary path.
  2. dhan_config.py at the repo root (plaintext) - the fallback path, kept in sync
     so it's never the thing silently serving a stale token again.

RETIRED AS A ROUTINE ROTATOR. The backend now owns Dhan token refresh: it mints
from the token's real expiry and serialises every login behind a Redis lock
(backend/app/services/dhan_token.py). Because Dhan permits exactly one active
session per account, this script rotating on its own schedule *invalidated the
backend's token every time it ran*, which forced the backend to re-mint, which
invalidated this one — a cascade whose bursts tripped Dhan's rate limit and
surfaced as "TOTP login failed".

So it no longer logs in unconditionally. It first checks the token the backend
maintains in Mongo and exits without touching Dhan if that token is still good,
which is the normal case. It remains useful as a break-glass tool for when the
backend is down or its token is genuinely dead — force that with `--force`.

Prefer the backend's POST /api/broker/refresh-token, which takes the same lock.
Run here only if the backend can't: python rotate_dhan_token.py [--force]
"""

import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import pyotp
import requests
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

from db import _db  # noqa: E402

DHAN_AUTH_BASE_URL = os.getenv("DHAN_AUTH_BASE_URL", "https://auth.dhan.co")
CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
PIN = os.getenv("DHAN_PIN")
TOTP_SECRET = os.getenv("DHAN_TOTP_SECRET")
USER_ID = os.getenv("DHAN_USER_ID")
ENCRYPTION_KEY = os.getenv("BROKER_ENCRYPTION_KEY")
DHAN_CONFIG_PATH = os.path.join(os.getenv("DHAN_CONFIG_DIR", "D:/INDIAN MARKET"), "dhan_config.py")

credentials_collection = _db["broker_credentials"]


def _require_config() -> None:
    missing = [name for name, val in (
        ("DHAN_CLIENT_ID", CLIENT_ID), ("DHAN_PIN", PIN), ("DHAN_TOTP_SECRET", TOTP_SECRET),
        ("DHAN_USER_ID", USER_ID), ("BROKER_ENCRYPTION_KEY", ENCRYPTION_KEY),
    ) if not val]
    if missing:
        print(f"[error] rotate_dhan_token: missing env vars {missing} - cannot rotate. "
              f"Set them in prelive-service/.env (PIN/TOTP secret are the same ones "
              f"used by the backend's own auto-refresh, in backend/.env).", flush=True)
        sys.exit(1)


def generate_token() -> dict:
    code = pyotp.TOTP(TOTP_SECRET).now()
    resp = requests.post(
        f"{DHAN_AUTH_BASE_URL}/app/generateAccessToken",
        params={"dhanClientId": CLIENT_ID, "pin": PIN, "totp": code},
        timeout=30,
    )
    data = resp.json()
    if resp.status_code >= 300 or not data.get("accessToken"):
        raise RuntimeError(f"Dhan TOTP login failed: {data.get('remarks') or data.get('errorMessage') or data}")
    return data


def update_mongo(client_id: str, access_token: str, dhan_name: str | None) -> None:
    fernet = Fernet(ENCRYPTION_KEY.encode())
    credentials_collection.find_one_and_update(
        {"user_id": USER_ID, "broker": "dhan"},
        {
            "$set": {
                "user_id": USER_ID,
                "broker": "dhan",
                "client_id": client_id,
                "access_token_encrypted": fernet.encrypt(access_token.encode()).decode(),
                "connected_at": datetime.now(timezone.utc),
                **({"dhan_name": dhan_name} if dhan_name else {}),
            }
        },
        upsert=True,
    )


def update_dhan_config_py(access_token: str, expiry_time: str | None) -> None:
    if not os.path.isfile(DHAN_CONFIG_PATH):
        print(f"[warn] {DHAN_CONFIG_PATH} not found - skipping plaintext fallback update", flush=True)
        return
    with open(DHAN_CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    comment = f"  # expires {expiry_time}" if expiry_time else ""
    new_content, n = re.subn(
        r'"access_token":\s*".*?",(\s*#.*)?',
        lambda m: f'"access_token": "{access_token}",{comment}',
        content,
        count=1,
    )
    if n == 0:
        print(f"[warn] could not find access_token line in {DHAN_CONFIG_PATH} - skipping", flush=True)
        return
    with open(DHAN_CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)


def _exp_str(access_token: str) -> str:
    try:
        payload_b64 = access_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload_b64))
        return datetime.fromtimestamp(data["exp"], tz=timezone.utc).isoformat()
    except Exception:
        return "unknown"


# A token with more life than this is left alone: minting over it would revoke
# the one the backend and every other consumer is actively using.
STILL_GOOD_MARGIN = timedelta(hours=2)


def _stored_token_remaining() -> timedelta | None:
    """Life left on the token the backend maintains, or None if unreadable."""
    if not ENCRYPTION_KEY:
        return None
    try:
        doc = credentials_collection.find_one({"broker": "dhan"})
        if not doc:
            return None
        token = Fernet(ENCRYPTION_KEY.encode()).decrypt(doc["access_token_encrypted"].encode()).decode()
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload_b64))["exp"]
        return datetime.fromtimestamp(exp, tz=timezone.utc) - datetime.now(timezone.utc)
    except Exception:
        return None


def main() -> None:
    _require_config()

    if "--force" not in sys.argv:
        remaining = _stored_token_remaining()
        if remaining is not None and remaining > STILL_GOOD_MARGIN:
            print(
                f"[rotate] backend-managed token still valid for {remaining} "
                f"(> {STILL_GOOD_MARGIN}) — skipping. Minting now would revoke the "
                f"token every service is currently using. Use --force to override.",
                flush=True,
            )
            return

    print(f"[rotate] {datetime.now(timezone.utc).isoformat()} requesting fresh Dhan token via TOTP...", flush=True)
    for attempt in range(3):
        try:
            data = generate_token()
            break
        except Exception as e:
            print(f"[error] rotate attempt {attempt + 1}/3 failed: {e}", flush=True)
            if attempt == 2:
                sys.exit(1)
            time.sleep(5)

    access_token = data["accessToken"]
    client_id = str(data.get("dhanClientId") or CLIENT_ID)
    dhan_name = data.get("dhanClientName")
    exp = _exp_str(access_token)

    update_mongo(client_id, access_token, dhan_name)
    update_dhan_config_py(access_token, data.get("expiryTime") or exp)

    print(f"[rotate] done - client {client_id}, new token expires {exp} "
          f"(Mongo broker_credentials + dhan_config.py both updated)", flush=True)


if __name__ == "__main__":
    main()
