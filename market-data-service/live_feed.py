"""Live bar aggregator (roadmap Phase 5) — the data-plumbing half of Paper/Live mode.

Polls Dhan quotes for every (symbol, timeframe) an active strategy run has registered
in the `live_watchlist` collection (populated/depopulated by the backend when a
Paper/Live run starts/stops), rolls ticks up into OHLCV bars per timeframe, and on
every bucket boundary publishes the FINALIZED bar to Redis (`bars_updates`) and upserts
it into the same `bars` collection the historical backfill writes to — so a strategy
run's bootstrap history and its live continuation are the same series.

Daily bars use Dhan's own day OHLC/volume fields directly (accurate, one quote call);
intraday bars are built from LTP ticks bucketed to the timeframe boundary (Dhan's quote
API has no sub-day OHLC of its own). Only FINALIZED bars (`"final": true`) drive
strategy signals — a forming bar is published too (`"final": false`) purely so a UI can
show a live mark, and strategy runners must ignore it.

Run as its own long-lived process, like broker-service: `python live_feed.py`.
"""

import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from bars_store import upsert_bars
from credentials import get_dhan_access
from db import _db
from redis_pub import publish as redis_publish

load_dotenv()

IST = timezone(timedelta(hours=5, minutes=30))
DHAN_BASE_URL = "https://api.dhan.co/v2"
BARS_UPDATES_CHANNEL = "bars_updates"
INTRADAY_BUCKET_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}

watchlist_collection = _db["live_watchlist"]

_buckets: dict[tuple[str, str], dict] = {}  # (symbol, timeframe) -> forming bar state
_last_cumulative_volume: dict[tuple[str, str], int] = {}  # daily-volume baseline per bucket


def _bucket_start(now_ist: datetime, timeframe: str) -> datetime:
    if timeframe == "1d":
        session_start = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        return session_start if now_ist >= session_start else session_start - timedelta(days=1)
    minutes = INTRADAY_BUCKET_MINUTES[timeframe]
    total_min = now_ist.hour * 60 + now_ist.minute
    bucket_min = (total_min // minutes) * minutes
    return now_ist.replace(hour=bucket_min // 60, minute=bucket_min % 60, second=0, microsecond=0)


def _fetch_quotes(client_id: str, access_token: str, watch: list[dict]) -> dict[str, dict]:
    """One batched POST per exchange segment; returns {security_id: quote_fields}."""
    headers = {
        "access-token": access_token, "client-id": client_id,
        "Content-Type": "application/json", "Accept": "application/json",
    }
    by_segment: dict[str, list[str]] = {}
    for w in watch:
        by_segment.setdefault(w["exchange_segment"], []).append(w["security_id"])

    out: dict[str, dict] = {}
    for segment, security_ids in by_segment.items():
        payload = {segment: [int(sid) for sid in security_ids]}
        try:
            response = requests.post(
                f"{DHAN_BASE_URL}/marketfeed/quote", json=payload, headers=headers, timeout=15
            )
            data = response.json().get("data", {})
        except Exception as exc:
            print(f"[error] quote fetch failed for {segment}: {exc}", flush=True)
            continue
        segment_data = data.get(segment, {}) if isinstance(data, dict) else {}
        for security_id, fields in segment_data.items():
            out[str(security_id)] = fields
    return out


def _publish(symbol: str, timeframe: str, bar_doc: dict, final: bool) -> None:
    payload = {**bar_doc, "ts": bar_doc["ts"].isoformat(), "final": final}
    redis_publish(BARS_UPDATES_CHANNEL, payload)


def _process_tick(w: dict, quote: dict, now_ist: datetime) -> None:
    symbol, timeframe = w["symbol"], w["timeframe"]
    key = (symbol, timeframe)
    ltp = quote.get("last_price")
    if ltp is None:
        return
    bstart = _bucket_start(now_ist, timeframe)
    forming = _buckets.get(key)

    if forming is not None and forming["ts"] != bstart:
        # boundary crossed - finalize the previous bucket
        upsert_bars([{k: v for k, v in forming.items() if k != "volume_baseline"}])
        _publish(symbol, timeframe, forming, final=True)
        forming = None

    if timeframe == "1d":
        ohlc = quote.get("ohlc", {}) or {}
        day_volume = int(quote.get("volume") or 0)
        bar = {
            "symbol": symbol, "timeframe": timeframe, "ts": bstart,
            "open": ohlc.get("open", ltp), "high": max(ohlc.get("high", ltp), ltp),
            "low": min(ohlc.get("low", ltp), ltp) if ohlc.get("low") else ltp,
            "close": ltp, "volume": day_volume, "oi": quote.get("oi"),
        }
    elif forming is None:
        bar = {
            "symbol": symbol, "timeframe": timeframe, "ts": bstart,
            "open": ltp, "high": ltp, "low": ltp, "close": ltp, "volume": 0, "oi": quote.get("oi"),
        }
    else:
        cumulative = int(quote.get("volume") or 0)
        baseline = _last_cumulative_volume.get(key, cumulative)
        delta = max(cumulative - baseline, 0)
        bar = {
            **forming,
            "high": max(forming["high"], ltp),
            "low": min(forming["low"], ltp),
            "close": ltp,
            "volume": forming["volume"] + delta,
            "oi": quote.get("oi", forming.get("oi")),
        }
        _last_cumulative_volume[key] = cumulative

    _buckets[key] = bar
    _publish(symbol, timeframe, bar, final=False)


def run(poll_interval_seconds: int = 10) -> None:
    print(f"live_feed: polling every {poll_interval_seconds}s", flush=True)
    while True:
        watch = list(watchlist_collection.find())
        if watch:
            try:
                client_id, access_token = get_dhan_access()
                quotes = _fetch_quotes(client_id, access_token, watch)
                now_ist = datetime.now(IST)
            except Exception as exc:
                print(f"[error] live_feed cycle failed: {exc}", flush=True)
                quotes = {}
            # Each (symbol, timeframe) is processed independently so one bad tick
            # (or a downstream failure inside _process_tick) can't silently drop
            # every timeframe queued after it in the same cycle - this is what let
            # 15m/1h never finalize while 5m worked (see redis_pub.py fix).
            for w in watch:
                quote = quotes.get(w["security_id"])
                if quote is None:
                    continue
                try:
                    _process_tick(w, quote, now_ist)
                except Exception as exc:
                    print(f"[error] _process_tick failed for {w['symbol']}@{w['timeframe']}: {exc}", flush=True)
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    run()
