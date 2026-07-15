"""Pre-market warmup backfill - belt-and-suspenders for prelive's bootstrap_history().

live_feed.py keeps bars current only while it's actually running uninterrupted; if
the machine sleeps/reboots overnight (and the AtStartup/AtLogOn supervisor task isn't
registered yet - see setup_scheduler.ps1's elevation note), bars can go stale again by
morning. This script directly backfills the last few days of 5m/15m/1h NIFTY bars from
Dhan's historical API whenever the latest stored bar isn't from today, so
bootstrap_history() never seeds a session's strategies (including the three 15m ones:
intra_gap_fill, intra_stoch_rsi, nj_order_block_poi) from stale multi-day-old data.

Idempotent (bars_store.upsert_bars upserts on the unique symbol/timeframe/ts index) -
safe to run any time, not just pre-market. Scheduled daily at 09:05 IST (see
setup_scheduler.ps1), 10 minutes before the 09:15 open.
"""

import sys
from datetime import datetime, timedelta, timezone

from bars_store import upsert_bars
from credentials import get_dhan_access
from db import _db
from providers.dhan_history import DhanHistoryProvider

from tradingai_shared.domain import AssetClass, ExchangeSegment, Instrument, Timeframe

bars_collection = _db["bars"]

NIFTY_INSTRUMENT = Instrument(
    symbol="NIFTY", security_id="13", exchange_segment=ExchangeSegment.IDX_I,
    asset_class=AssetClass.INDEX,
)

# Covers the three live-desk timeframes; lookback wide enough to bridge any realistic
# gap (a long weekend + an outage) without hitting Dhan's 90-day intraday cap.
TIMEFRAMES = [Timeframe.M5, Timeframe.M15, Timeframe.H1]
LOOKBACK_DAYS = 10
STALE_AFTER_DAYS = 1  # if the latest bar isn't from today or yesterday, backfill


def _latest_ts(timeframe_label: str) -> datetime | None:
    doc = bars_collection.find_one({"symbol": "NIFTY", "timeframe": timeframe_label}, sort=[("ts", -1)])
    return doc["ts"] if doc else None


def main() -> None:
    try:
        client_id, access_token = get_dhan_access()
    except Exception as e:
        print(f"[error] warmup_backfill: no valid Dhan credentials: {e}", flush=True)
        sys.exit(1)

    provider = DhanHistoryProvider(client_id, access_token)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=LOOKBACK_DAYS)

    for tf in TIMEFRAMES:
        label = tf.value
        latest = _latest_ts(label)
        is_stale = latest is None or (now - latest.replace(tzinfo=timezone.utc)) > timedelta(days=STALE_AFTER_DAYS)
        if not is_stale:
            print(f"[warmup] {label}: latest bar {latest} is fresh - skipping backfill", flush=True)
            continue
        try:
            bars = provider.get_history(NIFTY_INSTRUMENT, tf, start, now)
        except Exception as e:
            print(f"[error] warmup_backfill {label} fetch failed: {e}", flush=True)
            continue
        docs = [
            {"symbol": b.symbol, "timeframe": label, "ts": b.ts.replace(tzinfo=None),
             "open": b.open, "high": b.high, "low": b.low, "close": b.close,
             "volume": b.volume, "oi": b.oi}
            for b in bars
        ]
        n = upsert_bars(docs)
        newest = docs[-1]["ts"] if docs else None
        print(f"[warmup] {label}: backfilled {n} bars (was stale, latest was {latest}), newest now {newest}", flush=True)


if __name__ == "__main__":
    main()
