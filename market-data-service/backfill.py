"""Historical bar backfill CLI — pulls Dhan candles into the Mongo `bars` collection.

Examples:
    python backfill.py --symbols NIFTY,BANKNIFTY --timeframes 1d --years 5
    python backfill.py --symbols RELIANCE --timeframes 15m,1h --years 1
    python backfill.py --universe fno --timeframes 1d --years 2

`--universe fno` resolves the symbol list to every F&O-listed equity (distinct
underlying of the EQUITY_FUTURE instruments, ~190 liquid names) — the same
universe broker research desks cover, and what the Trading Calls stock scan
feeds on.

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


def fno_universe() -> list[str]:
    """Every equity with a listed stock future — liquid by construction.
    NSE's exchange test scrips (…NSETEST) carry futures too; drop them."""
    return sorted(
        u for u in instruments_collection.distinct("underlying_symbol", {"asset_class": "EQUITY_FUTURE"})
        if u and "NSETEST" not in u
        and instruments_collection.find_one({"asset_class": "EQUITY", "symbol": u}) is not None
    )


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
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbols", help="comma-separated, e.g. NIFTY,RELIANCE")
    group.add_argument("--universe", choices=["fno"], help="fno = all F&O-listed equities (~190)")
    parser.add_argument("--timeframes", default="1d", help="comma-separated: 1m,5m,15m,1h,1d,1w")
    parser.add_argument("--years", type=float, default=5.0, help="lookback window in years")
    args = parser.parse_args()

    if args.universe:
        symbols = fno_universe()
        print(f"--universe {args.universe}: {len(symbols)} symbols")
    else:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    backfill(
        symbols=symbols,
        timeframes=[Timeframe(t.strip()) for t in args.timeframes.split(",") if t.strip()],
        years=args.years,
    )
