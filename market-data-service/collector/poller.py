import threading
import time
from datetime import datetime, timedelta, timezone

from collector.dhan_index_client import DhanIndexClient
from collector.nse_client import NSEClient
from collector.symbols import EQUITY_SYMBOLS, INDEX_SYMBOLS
from db import get_connection, upsert_quote
from redis_pub import publish_quote

IST = timezone(timedelta(hours=5, minutes=30))
DAILY_TOPUP_AFTER = "16:00"  # post-close, once per trading day
_last_topup_date: str | None = None


def _maybe_start_daily_topup() -> None:
    """Keeps the F&O-universe daily bars current so the Trading Calls stock scan
    always sees yesterday's close. Runs in a thread so quote polling never
    blocks; the backfill upsert is idempotent, so a restart re-running it is
    harmless."""
    global _last_topup_date
    now = datetime.now(IST)
    today = now.date().isoformat()
    if now.weekday() >= 5 or _last_topup_date == today or now.strftime("%H:%M") < DAILY_TOPUP_AFTER:
        return
    _last_topup_date = today
    threading.Thread(target=_run_topup, daemon=True).start()


def _run_topup() -> None:
    try:
        from backfill import backfill, fno_universe
        from tradingai_shared.domain import Timeframe

        symbols = fno_universe()
        print(f"[topup] daily-bars top-up for {len(symbols)} F&O symbols")
        backfill(symbols=symbols, timeframes=[Timeframe.D1], years=0.1)
    except Exception as exc:
        print(f"[warn] daily-bars top-up failed: {exc}")


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

        _maybe_start_daily_topup()
        time.sleep(poll_interval_seconds)


_redis_warned = False


def _fetch_and_store(fetch_fn, conn, label: str) -> None:
    global _redis_warned
    try:
        quote = fetch_fn()
        if quote is None or quote.get("price") is None:
            print(f"[warn] no data for {label}")
            return
        now = datetime.now(timezone.utc)
        upsert_quote(conn, quote, now)
        try:
            publish_quote({**quote, "updated_at": now.isoformat()})
        except Exception as exc:
            # Redis only feeds the live WebSocket stream — quotes are already in
            # Mongo, so a down Redis must not abort the poll (warn once, not 5x/7s)
            if not _redis_warned:
                _redis_warned = True
                print(f"[warn] Redis publish unavailable ({exc}) — continuing with Mongo-only quotes")
    except Exception as exc:
        print(f"[error] failed to fetch/store {label}: {exc}")
