import asyncio
import json

import redis.asyncio as redis
from fastapi import WebSocket

from app.core.config import settings

MARKET_DATA_CHANNEL = "market_data_updates"


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._redis: redis.Redis | None = None
        self._listener_task: asyncio.Task | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        if self._listener_task is None:
            self._listener_task = asyncio.create_task(self._listen())

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def _listen(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(MARKET_DATA_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            await self._broadcast(message["data"])

    async def _broadcast(self, data: str) -> None:
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_snapshot(self, websocket: WebSocket, snapshot: list[dict]) -> None:
        await websocket.send_text(json.dumps({"type": "snapshot", "data": snapshot}))


manager = ConnectionManager()
