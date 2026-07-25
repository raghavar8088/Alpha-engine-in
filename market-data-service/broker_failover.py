"""Angel One failover + the shared Dhan rate-limit cooldown, for market-data-service.

This is the sync analog of backend/app/services/broker_data.py — this service is a plain
`requests` poll loop, not asyncio. Two responsibilities:

1. The Dhan cooldown lives in the SAME Redis key the backend writes
   ("dhan:ratelimit:cooldown"). Before this, every process hitting the one Dhan account
   had its own private rate-limit handling, so a 429 tripped by the backend didn't slow
   this service and vice versa — which is how this service alone racked up 458 429s/24h.
   Now a 429 tripped by ANY process stands them all down.

2. Angel One failover for quotes: when Dhan can't price a security (cooldown, 429, or
   error), ask Angel — the same standby the buying/selling desks already use — instead of
   returning nothing and freezing the snapshot/bar. Uses the shared `AngelSyncClient` and
   the `angel_token`/`angel_exchange` the backend already stamps on the `instruments`
   collection. A contract without a stamped token is left unpriceable, never guessed.
"""

import os
import time

import redis

from db import _db
from tradingai_broker_clients.angel import AngelAPIError, AngelCredentials, AngelSyncClient

# Cross-process contract: keep this key in sync with broker_data.py's _COOLDOWN_KEY.
_COOLDOWN_KEY = "dhan:ratelimit:cooldown"
DHAN_COOLDOWN_SECONDS = 120

_redis = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
_instruments = _db["instruments"]
_angel = AngelSyncClient(AngelCredentials.from_env())

_local_blocked_until = 0.0  # process-local fallback when Redis is unreachable


def dhan_is_cooling_down() -> bool:
    """True while the shared Dhan cooldown is active (tripped by any process)."""
    try:
        return bool(_redis.exists(_COOLDOWN_KEY))
    except Exception:
        return time.monotonic() < _local_blocked_until


def note_dhan_rate_limit() -> None:
    """Trip the shared cooldown on a Dhan 429."""
    global _local_blocked_until
    _local_blocked_until = time.monotonic() + DHAN_COOLDOWN_SECONDS
    try:
        _redis.set(_COOLDOWN_KEY, "1", ex=DHAN_COOLDOWN_SECONDS)
    except Exception:
        pass


def angel_configured() -> bool:
    return _angel.configured()


def _angel_ref(security_id, exchange_segment) -> tuple[str, str] | None:
    """(angel_token, angel_exchange) for a Dhan (security_id, segment), or None (unmapped =
    unpriceable, never guessed). Security ids appear as both str and int across docs."""
    variants: list = [str(security_id)]
    try:
        variants.append(int(security_id))
    except (TypeError, ValueError):
        pass
    doc = _instruments.find_one(
        {"security_id": {"$in": variants}, "exchange_segment": exchange_segment},
        {"angel_token": 1, "angel_exchange": 1},
    )
    if not doc or not doc.get("angel_token"):
        return None
    return str(doc["angel_token"]), doc.get("angel_exchange") or "NSE"


def _resolve(ids_by_segment: dict[str, list]) -> tuple[dict[str, list[str]], dict[str, tuple[str, str]]]:
    by_exchange: dict[str, list[str]] = {}
    token_to_key: dict[str, tuple[str, str]] = {}
    for seg, ids in ids_by_segment.items():
        for sid in ids:
            ref = _angel_ref(sid, seg)
            if ref is None:
                continue
            token, exchange = ref
            by_exchange.setdefault(exchange, []).append(token)
            token_to_key[token] = (seg, str(sid))
    return by_exchange, token_to_key


def angel_ltp(ids_by_segment: dict[str, list]) -> dict[tuple[str, str], float]:
    """{(segment, security_id): last_price} for whatever Angel can price. Empty when Angel
    is unconfigured/unreachable — the caller keeps its Dhan-only behaviour."""
    if not _angel.configured():
        return {}
    by_exchange, token_to_key = _resolve(ids_by_segment)
    if not by_exchange:
        return {}
    try:
        prices = _angel.ltp(by_exchange)
    except (AngelAPIError, Exception):
        return {}
    return {token_to_key[t]: p for t, p in prices.items() if t in token_to_key}


def angel_full_quotes(ids_by_segment: dict[str, list]) -> dict[str, dict]:
    """{security_id: dhan-shaped quote} for whatever Angel can price — reshaped so the
    live_feed tick processor (which reads last_price / ohlc / volume / oi) consumes it
    unchanged. Angel has no open interest, so oi is None."""
    if not _angel.configured():
        return {}
    by_exchange, token_to_key = _resolve(ids_by_segment)
    if not by_exchange:
        return {}
    try:
        rows = _angel.full_quote(by_exchange)
    except (AngelAPIError, Exception):
        return {}
    out: dict[str, dict] = {}
    for token, q in rows.items():
        key = token_to_key.get(token)
        if key is None:
            continue
        _seg, sid = key
        out[sid] = {
            "last_price": q.get("ltp"),
            "ohlc": {"open": q.get("open"), "high": q.get("high"), "low": q.get("low")},
            "volume": q.get("volume") or 0,
            "oi": None,
        }
    return out
