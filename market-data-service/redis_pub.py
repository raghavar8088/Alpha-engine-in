import json
import os

import redis
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MARKET_DATA_CHANNEL = "market_data_updates"

_client = redis.from_url(REDIS_URL, decode_responses=True)


def publish_quote(quote: dict) -> None:
    _client.publish(MARKET_DATA_CHANNEL, json.dumps({"type": "update", "data": quote}))


def publish(channel: str, payload: dict) -> None:
    _client.publish(channel, json.dumps(payload))
