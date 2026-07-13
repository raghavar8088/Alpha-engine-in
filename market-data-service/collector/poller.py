import time
from datetime import datetime, timezone

from collector.dhan_index_client import DhanIndexClient
from collector.nse_client import NSEClient
from collector.symbols import EQUITY_SYMBOLS, INDEX_SYMBOLS
from db import get_connection, upsert_quote
from redis_pub import publish_quote


def run(poll_interval_seconds: int) -> None:
    index_client = DhanIndexClient()
    equity_client = NSEClient()  # equities still have no authenticated feed wired up
    conn = get_connection()

    print(f"market-data-service: polling every {poll_interval_seconds}s (indices via Dhan)")
    while True:
        for index_name in INDEX_SYMBOLS:
            _fetch_and_store(lambda i=index_name: index_client.get_index_quote(i), conn, index_name)

        for symbol in EQUITY_SYMBOLS:
            _fetch_and_store(lambda s=symbol: equity_client.get_equity_quote(s), conn, symbol)

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
