import json
import os

import redis
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MARKET_DATA_CHANNEL = "market_data_updates"

_client = redis.from_url(REDIS_URL, decode_responses=True)
_warned = False


def _warn_once(exc: Exception) -> None:
    # Redis only feeds live WebSocket streams; bars/quotes are already durably
    # written to Mongo by the caller before publish() runs, so a down Redis must
    # never abort the caller's loop (that used to abort live_feed's per-symbol
    # loop entirely, silently dropping every timeframe after the first).
    global _warned
    if not _warned:
        _warned = True
        print(f"[warn] Redis publish unavailable ({exc}) — continuing Mongo-only", flush=True)


def publish_quote(quote: dict) -> None:
    try:
        _client.publish(MARKET_DATA_CHANNEL, json.dumps({"type": "update", "data": quote}))
    except Exception as exc:
        _warn_once(exc)


def publish(channel: str, payload: dict) -> None:
    try:
        _client.publish(channel, json.dumps(payload))
    except Exception as exc:
        _warn_once(exc)
