import threading
import time
from datetime import datetime, timedelta, timezone

from collector.dhan_index_client import DhanIndexClient
from collector.nse_client import NSEClient
from collector.symbols import EQUITY_SYMBOLS, INDEX_SYMBOLS
from db import _db, get_connection, upsert_quote
from redis_pub import publish_quote

IST = timezone(timedelta(hours=5, minutes=30))
DAILY_TOPUP_AFTER = "16:00"  # post-close, once per trading day
_topup_state = _db["market_data_topup_state"]


def _maybe_start_daily_topup() -> None:
    """Keeps the F&O-universe daily bars current so the Trading Calls stock scan
    always sees yesterday's close. Runs in a thread so quote polling never
    blocks; the backfill upsert is idempotent, so re-running it writes nothing new.

    The 'already ran today' marker lives in Mongo, not in memory: it used to be a
    module global, so every container restart after 16:00 IST re-fired the whole
    ~208-symbol backfill. Several deploys in one evening therefore meant several
    hundred extra Dhan requests, which is enough on its own to trip the account's
    rate limit (HTTP 429) and take the live feed down with it."""
    now = datetime.now(IST)
    today = now.date().isoformat()
    if now.weekday() >= 5 or now.strftime("%H:%M") < DAILY_TOPUP_AFTER:
        return
    # Atomic claim — only the first caller to insert today's marker runs the topup,
    # so a restart (or a second worker) can't duplicate the request burst.
    try:
        _topup_state.insert_one({"_id": f"daily-topup-{today}", "claimed_at": now})
    except Exception:
        return  # already claimed today (duplicate key) — nothing to do
    threading.Thread(target=_run_topup, daemon=True).start()


def _run_topup() -> None:
    try:
        from backfill import backfill, fno_universe
        from tradingai_shared.domain import Timeframe

        symbols = fno_universe()
        print(f"[topup] daily-bars top-up for {len(symbols)} F&O symbols", flush=True)
        backfill(symbols=symbols, timeframes=[Timeframe.D1], years=0.1)

        # The pre-live desk bootstraps each strategy's warmup history from NIFTY
        # 5m/15m bars, but nothing was ever refreshing those — only D1 was topped
        # up here, so the intraday bars went stale (found 2 days behind) and every
        # strategy warmed up on a discontinuous series before its first live bar.
        # Two extra requests a day keeps that warmup honest.
        print("[topup] NIFTY intraday-bars top-up (5m/15m) for pre-live warmup", flush=True)
        backfill(symbols=["NIFTY"], timeframes=[Timeframe.M5, Timeframe.M15], years=0.08)
    except Exception as exc:
        print(f"[warn] daily-bars top-up failed: {exc}", flush=True)


def run(poll_interval_seconds: int) -> None:
    index_client = DhanIndexClient()
    equity_client = NSEClient()  # equities still have no authenticated feed wired up
    conn = get_connection()

    print(f"market-data-service: polling every {poll_interval_seconds}s (indices via Dhan)", flush=True)
    while True:
        for index_name in INDEX_SYMBOLS:
            _fetch_and_store(lambda i=index_name: index_client.get_index_quote(i), conn, index_name)

        for symbol in EQUITY_SYMBOLS:
            _fetch_and_store(lambda s=symbol: equity_client.get_equity_quote(s), conn, symbol)

        _maybe_start_daily_topup()
        # If Dhan has throttled the shared account, re-polling every 7s just keeps
        # the block alive — back off to 4x the interval until the limit lifts.
        sleep_for = poll_interval_seconds * 4 if index_client.rate_limited else poll_interval_seconds
        time.sleep(sleep_for)


_redis_warned = False


def _fetch_and_store(fetch_fn, conn, label: str) -> None:
    global _redis_warned
    try:
        quote = fetch_fn()
        if quote is None or quote.get("price") is None:
            print(f"[warn] no data for {label}", flush=True)
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
                print(f"[warn] Redis publish unavailable ({exc}) — continuing with Mongo-only quotes", flush=True)
    except Exception as exc:
        print(f"[error] failed to fetch/store {label}: {exc}", flush=True)
