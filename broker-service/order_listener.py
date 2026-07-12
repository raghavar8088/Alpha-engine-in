import asyncio
import json

import websockets

from redis_pub import publish_order_update

ORDER_FEED_WSS = "wss://api-order-update.dhan.co"
RECONNECT_DELAY_SECONDS = 5


async def listen_for_user(user_id: str, client_id: str, access_token: str, stop_event: asyncio.Event) -> None:
    """Maintains a persistent Dhan order-update WebSocket for one user, reconnecting
    on drop, until stop_event is set (credential removed / service shutting down)."""
    while not stop_event.is_set():
        try:
            async with websockets.connect(ORDER_FEED_WSS) as ws:
                auth_message = {
                    "LoginReq": {"MsgCode": 42, "ClientId": str(client_id), "Token": str(access_token)},
                    "UserType": "SELF",
                }
                await ws.send(json.dumps(auth_message))
                print(f"[broker-service] connected order feed for user {user_id}")

                while not stop_event.is_set():
                    message = await asyncio.wait_for(ws.recv(), timeout=RECONNECT_DELAY_SECONDS)
                    data = json.loads(message)
                    if data.get("Type") == "order_alert":
                        publish_order_update(user_id, data.get("Data", {}))
        except asyncio.TimeoutError:
            continue
        except Exception as exc:
            print(f"[broker-service] order feed error for user {user_id}: {exc}, reconnecting in {RECONNECT_DELAY_SECONDS}s")
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)
