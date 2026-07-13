import asyncio

import redis.asyncio as redis
from fastapi import WebSocket

from app.core.config import settings

BROKER_ORDER_CHANNEL_PATTERN = "broker_order_updates:*"
BROKER_ORDER_CHANNEL_PREFIX = "broker_order_updates:"


class BrokerOrderManager:
    """Routes Dhan order-update pushes to only the browser connection(s) belonging
    to the same user, using one shared Redis psubscribe connection fanning out by
    the user_id encoded in the channel name (broker_order_updates:{user_id})."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._redis: redis.Redis | None = None
        self._listener_task: asyncio.Task | None = None

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, set()).add(websocket)
        if self._listener_task is None:
            self._listener_task = asyncio.create_task(self._listen())

    def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        connections = self._connections.get(user_id)
        if connections is not None:
            connections.discard(websocket)
            if not connections:
                self._connections.pop(user_id, None)

    async def _listen(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(BROKER_ORDER_CHANNEL_PATTERN)
        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue
            channel: str = message["channel"]
            user_id = channel[len(BROKER_ORDER_CHANNEL_PREFIX) :]
            await self._send_to_user(user_id, message["data"])

    async def _send_to_user(self, user_id: str, data: str) -> None:
        dead = []
        for ws in self._connections.get(user_id, set()):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)


manager = BrokerOrderManager()
