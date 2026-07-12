import json
import os

import redis
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_client = redis.from_url(REDIS_URL, decode_responses=True)


def publish_order_update(user_id: str, update: dict) -> None:
    channel = f"broker_order_updates:{user_id}"
    _client.publish(channel, json.dumps({"type": "order_update", "data": update}))
