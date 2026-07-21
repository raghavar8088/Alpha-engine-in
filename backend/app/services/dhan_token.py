"""Single-owner Dhan token manager — one owner, one lock, one token.

Dhan permits exactly ONE active session token per account, and its auth endpoint
(`/app/generateAccessToken`) is itself rate-limited. Before this module, four
uncoordinated paths logged in with the same account:

  * the background refresh loop in app/main.py,
  * an unlocked per-request refresh inside `_get_dhan_client` — so N concurrent
    requests arriving on a stale token fired N simultaneous logins,
  * the manual /api/broker/refresh-token endpoint,
  * prelive-service/rotate_dhan_token.py, in a different runtime entirely.

Because of the one-session rule, every login silently invalidated the token the
other paths were holding. The invalidated path's next call failed, which tripped
its own refresh, which invalidated the others again — a self-sustaining cascade
whose bursts tripped Dhan's 429 and surfaced as "TOTP login failed".

The fix is to serialise logins behind a Redis lock. Redis is already the shared
bus for backend + prelive + market-data, so a single lock covers every runtime,
not just this process. Exactly one caller mints at a time; everyone else waits
briefly and then re-reads the token that one stored. A 429 sets a short cooldown
so nobody retries into the throttle.

Deliberate design choices:

* Refresh is decided from the token's real JWT expiry, never a wall-clock age.
  A healthy token means reads perform no login at all, which is what removes the
  per-request stampede.
* Redis being unavailable degrades to the old unlocked behaviour rather than
  refusing to refresh — a broken cache must not take the broker offline.
* Nothing here raises on failure. Callers fall back to the stored token, which is
  usually still valid; a hard failure would take down every Dhan-backed feature.
"""

import asyncio
import logging
from datetime import datetime, timezone

import redis.asyncio as redis

from app.core.config import settings
from app.core.db import broker_credentials_collection
from app.core.encryption import decrypt_secret, encrypt_secret
from app.services.dhan_client import (
    DhanRateLimitError,
    token_expiry,
    token_seconds_remaining,
    totp_login,
)

logger = logging.getLogger("dhan_token")


def _ensure_visible_logging() -> None:
    """Make token lifecycle events actually reach the container log.

    This app configures no logging at all, and uvicorn only sets up its own
    `uvicorn.*` loggers — so a named logger propagates to a bare root logger that
    defaults to WARNING with no handler. The practical effect was that every
    successful refresh (INFO) was silently dropped while failures still surfaced
    through Python's last-resort handler. Token refresh therefore *looked*
    permanently broken in the logs even when it was working, because a failure
    was the only outcome that could ever be seen.

    `dhan_totp_refresh` is app.main's own logger, configured here too so the
    background loop's successes become visible without a second config site.
    """
    for name in ("dhan_token", "dhan_totp_refresh"):
        target = logging.getLogger(name)
        if not target.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s:     [%(name)s] %(message)s"))
            target.addHandler(handler)
            target.propagate = False
        target.setLevel(logging.INFO)


_ensure_visible_logging()

_LOCK_KEY = "dhan:totp:lock"
_COOLDOWN_KEY = "dhan:totp:cooldown"

# Longer than a worst-case login round-trip, so the lock auto-frees if a holder
# is killed mid-login rather than wedging every other process behind it.
_LOCK_TTL_SECONDS = 120
# After a 429, serve the stored token for this long instead of re-attempting.
_COOLDOWN_SECONDS = 90
# The read path only mints inside this window of expiry. Deliberately much
# smaller than the background loop's own margin (2h, app/main.py) so the loop
# refreshes proactively and this stays a genuine last-resort safety net.
_REFRESH_MARGIN_SECONDS = 30 * 60
_WAIT_POLL_SECONDS = 0.5
_WAIT_MAX_SECONDS = 25

# Only the lock's owner may release it: a login that overran the TTL must not
# delete a lock some later winner is now holding.
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

_redis: redis.Redis | None = None
_owner_seq = 0


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def totp_configured() -> bool:
    return bool(settings.dhan_client_id and settings.dhan_pin and settings.dhan_totp_secret)


async def store_token(user_id: str, client_id: str, access_token: str, dhan_name: str | None = None) -> None:
    """Persist a token along with its real expiry, so every later refresh decision
    (and /api/broker/status) can reason about time-to-live instead of guessing
    from how long ago it was stored."""
    await broker_credentials_collection.find_one_and_update(
        {"user_id": user_id, "broker": "dhan"},
        {
            "$set": {
                "user_id": user_id,
                "broker": "dhan",
                "client_id": client_id,
                "access_token_encrypted": encrypt_secret(access_token),
                "connected_at": datetime.now(timezone.utc),
                "token_expiry": token_expiry(access_token),
                **({"dhan_name": dhan_name} if dhan_name else {}),
            }
        },
        upsert=True,
    )


def seconds_remaining(creds: dict) -> float | None:
    """Life left on the stored token, or None if it can't be read."""
    try:
        return token_seconds_remaining(decrypt_secret(creds["access_token_encrypted"]))
    except Exception:
        return None


def should_refresh(creds: dict) -> bool:
    """True when the stored token is unreadable or close enough to expiry to be
    worth minting a replacement. A healthy token answers False, so ordinary
    requests never trigger a login."""
    if not totp_configured():
        return False
    remaining = seconds_remaining(creds)
    return remaining is None or remaining < _REFRESH_MARGIN_SECONDS


async def _wait_for_release(client: redis.Redis) -> None:
    waited = 0.0
    while waited < _WAIT_MAX_SECONDS:
        try:
            if not await client.exists(_LOCK_KEY):
                return
        except Exception:
            return
        await asyncio.sleep(_WAIT_POLL_SECONDS)
        waited += _WAIT_POLL_SECONDS


async def refresh_locked(user_id: str) -> bool:
    """Mint a new token under the cross-process lock.

    Returns True only if THIS call minted. False means it deferred — to a
    cooldown, to another holder, or to an error — and the caller should re-read
    the stored token, which the winning holder will have replaced.
    """
    if not totp_configured():
        return False

    client = _client()
    try:
        if await client.get(_COOLDOWN_KEY):
            logger.info("Dhan token refresh skipped — auth endpoint in 429 cooldown")
            return False
    except Exception:
        pass  # Redis unreachable: proceed unlocked rather than never refreshing

    global _owner_seq
    _owner_seq += 1
    owner = f"{id(asyncio.current_task())}:{_owner_seq}"

    try:
        acquired = await client.set(_LOCK_KEY, owner, nx=True, ex=_LOCK_TTL_SECONDS)
    except Exception:
        acquired = True  # degrade to the old unlocked behaviour

    if not acquired:
        # Another process is minting right now. Wait for it rather than adding
        # another login to the burst; the caller re-reads what it stored.
        await _wait_for_release(client)
        return False

    try:
        data = await totp_login(settings.dhan_client_id, settings.dhan_pin, settings.dhan_totp_secret)
        await store_token(
            user_id, str(data.get("dhanClientId") or settings.dhan_client_id),
            data["accessToken"], data.get("dhanClientName"),
        )
        logger.info("Dhan token refreshed under lock; expires %s", data.get("expiryTime"))
        return True
    except DhanRateLimitError:
        try:
            await client.set(_COOLDOWN_KEY, "1", ex=_COOLDOWN_SECONDS)
        except Exception:
            pass
        logger.warning("Dhan auth throttled (429) — cooling down %ss, serving stored token", _COOLDOWN_SECONDS)
        return False
    except Exception:
        logger.exception("Dhan token refresh failed — serving stored token")
        return False
    finally:
        try:
            await client.eval(_RELEASE_SCRIPT, 1, _LOCK_KEY, owner)
        except Exception:
            pass


def health(creds: dict | None) -> dict:
    """Token health for /api/broker/status — makes 'is refresh working?' answerable
    at a glance instead of by reading logs."""
    if creds is None:
        return {"token_expiry": None, "seconds_remaining": None, "token_healthy": False}
    remaining = seconds_remaining(creds)
    expiry = creds.get("token_expiry")
    if expiry is None:
        token_exp = None
        try:
            token_exp = token_expiry(decrypt_secret(creds["access_token_encrypted"]))
        except Exception:
            pass
        expiry = token_exp
    return {
        "token_expiry": expiry,
        "seconds_remaining": None if remaining is None else round(remaining),
        "token_healthy": remaining is not None and remaining > 0,
    }
