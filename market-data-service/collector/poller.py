import time
from datetime import datetime, timezone

from collector.nse_client import NSEClient
from collector.symbols import EQUITY_SYMBOLS, INDEX_SYMBOLS
from db import get_connection, upsert_quote
from redis_pub import publish_quote


def run(poll_interval_seconds: int) -> None:
    client = NSEClient()
    conn = get_connection()

    print(f"market-data-service: polling every {poll_interval_seconds}s")
    while True:
        for index_name in INDEX_SYMBOLS:
            _fetch_and_store(lambda: client.get_index_quote(index_name), conn, index_name)

        for symbol in EQUITY_SYMBOLS:
            _fetch_and_store(lambda: client.get_equity_quote(symbol), conn, symbol)

        time.sleep(poll_interval_seconds)


def _fetch_and_store(fetch_fn, conn, label: str) -> None:
    try:
        quote = fetch_fn()
        if quote is None or quote.get("price") is None:
            print(f"[warn] no data for {label}")
            return
        now = datetime.now(timezone.utc)
        upsert_quote(conn, quote, now)
        publish_quote({**quote, "updated_at": now.isoformat()})
    except Exception as exc:
        print(f"[error] failed to fetch/store {label}: {exc}")
