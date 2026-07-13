"""Historical bar backfill CLI — pulls Dhan candles into the Mongo `bars` collection.

Examples:
    python backfill.py --symbols NIFTY,BANKNIFTY --timeframes 1d --years 5
    python backfill.py --symbols RELIANCE --timeframes 15m,1h --years 1

Requires a connected Dhan account (token comes from broker_credentials, decrypted with
BROKER_ENCRYPTION_KEY — same as broker-service). Run `python universe.py` first so the
symbols exist in the `instruments` collection."""

import argparse
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from bars_store import bars_collection, ensure_indexes, instruments_collection, upsert_bars
from credentials import get_dhan_access
from providers.dhan_history import DhanHistoryProvider
from tradingai_shared.domain import Instrument, Timeframe

load_dotenv()


def backfill(symbols: list[str], timeframes: list[Timeframe], years: float) -> None:
    client_id, access_token = get_dhan_access()
    provider = DhanHistoryProvider(client_id, access_token)
    ensure_indexes()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(years * 365))

    for symbol in symbols:
        doc = instruments_collection.find_one({"symbol": symbol})
        if doc is None:
            print(f"[warn] {symbol}: not in instruments collection (run universe.py?) — skipped")
            continue
        doc.pop("_id", None)
        instrument = Instrument(**doc)
        for timeframe in timeframes:
            try:
                bars = provider.get_history(instrument, timeframe, start, end)
            except Exception as exc:
                print(f"[error] {symbol} {timeframe.value}: {exc}")
                continue
            docs = []
            for bar in bars:
                d = bar.model_dump()
                d["timeframe"] = bar.timeframe.value
                docs.append(d)
            written = upsert_bars(docs)
            span = f"{bars[0].ts.date()} -> {bars[-1].ts.date()}" if bars else "no data"
            print(f"[ok] {symbol} {timeframe.value}: {written} bars ({span})")

    print(f"backfill done — bars collection now has {bars_collection.estimated_document_count()} docs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical bars from Dhan")
    parser.add_argument("--symbols", required=True, help="comma-separated, e.g. NIFTY,RELIANCE")
    parser.add_argument("--timeframes", default="1d", help="comma-separated: 1m,5m,15m,1h,1d,1w")
    parser.add_argument("--years", type=float, default=5.0, help="lookback window in years")
    args = parser.parse_args()

    backfill(
        symbols=[s.strip() for s in args.symbols.split(",") if s.strip()],
        timeframes=[Timeframe(t.strip()) for t in args.timeframes.split(",") if t.strip()],
        years=args.years,
    )
