import asyncio
import os

from dotenv import load_dotenv

from db import get_dhan_credentials
from encryption import decrypt_secret
from order_listener import listen_for_user

load_dotenv()

POLL_SECONDS = int(os.getenv("CREDENTIAL_POLL_SECONDS", "30"))


async def main() -> None:
    active: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}

    print(f"broker-service: watching for connected Dhan accounts every {POLL_SECONDS}s")
    while True:
        creds = get_dhan_credentials()
        current_user_ids = set()

        for cred in creds:
            user_id = cred["user_id"]
            current_user_ids.add(user_id)
            if user_id in active:
                continue
            try:
                access_token = decrypt_secret(cred["access_token_encrypted"])
            except Exception as exc:
                print(f"[broker-service] failed to decrypt token for user {user_id}: {exc}")
                continue

            stop_event = asyncio.Event()
            task = asyncio.create_task(listen_for_user(user_id, cred["client_id"], access_token, stop_event))
            active[user_id] = (task, stop_event)
            print(f"[broker-service] started order feed listener for user {user_id}")

        for user_id in list(active.keys()):
            if user_id not in current_user_ids:
                task, stop_event = active.pop(user_id)
                stop_event.set()
                task.cancel()
                print(f"[broker-service] stopped order feed listener for user {user_id}")

        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
