"""Instrument-universe loader: streams Dhan's public scrip-master CSV into the Mongo
`instruments` collection (the NSE WAF blocks equity scraping, but this CSV is Dhan's
own public file — no auth needed).

Kept in the universe:
- Major indices (whitelist below) — NSE + BSE(SENSEX), segment IDX_I
- All NSE equities (series EQ) and ETFs
- All BSE equities (instrument type ES) and ETFs — mostly BSE-exclusive small/micro
  caps not dual-listed on NSE, for the manual Positions module's stock search
- All NSE index/stock futures
- Index options for the whitelisted indices only (stock options are deferred to the
  options phase — they multiply the row count ~50x for no Phase-1 benefit)
- MCX commodity futures + options for the whitelisted commodities (Trading Calls
  module's Commodity segment)

Run: python universe.py
"""

import csv
import io
from datetime import datetime

import requests

from bars_store import ensure_indexes, upsert_instruments

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

INDEX_WHITELIST = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}
COMMODITY_WHITELIST = {"GOLD", "GOLDM", "SILVER", "SILVERM", "CRUDEOIL", "NATURALGAS", "COPPER", "ZINC"}

# CSV SEM_SEGMENT + SEM_EXM_EXCH_ID → Dhan API exchange segment
_SEGMENT = {
    ("E", "NSE"): "NSE_EQ",
    ("D", "NSE"): "NSE_FNO",
    ("E", "BSE"): "BSE_EQ",
    ("D", "BSE"): "BSE_FNO",
    ("M", "MCX"): "MCX_COMM",
}
_DERIVATIVE_CLASS = {
    "FUTIDX": "INDEX_FUTURE",
    "FUTSTK": "EQUITY_FUTURE",
    "OPTIDX": "INDEX_OPTION",
    "OPTSTK": "EQUITY_OPTION",
}
_COMMODITY_CLASS = {"FUTCOM": "COMMODITY_FUTURE", "OPTFUT": "COMMODITY_OPTION"}


def _parse_expiry(raw: str) -> str | None:
    raw = (raw or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _row_to_instrument(row: dict) -> dict | None:
    exchange = row["SEM_EXM_EXCH_ID"].strip()
    segment = row["SEM_SEGMENT"].strip()
    instrument_name = row["SEM_INSTRUMENT_NAME"].strip()
    symbol = row["SEM_TRADING_SYMBOL"].strip()
    underlying = symbol.split("-")[0].strip()

    if segment == "I" and instrument_name == "INDEX":
        if symbol not in INDEX_WHITELIST:
            return None
        asset_class, api_segment = "INDEX", "IDX_I"
    elif segment == "E" and exchange == "NSE":
        instrument_type = row.get("SEM_EXCH_INSTRUMENT_TYPE", "").strip()
        series = row.get("SEM_SERIES", "").strip()
        if instrument_type == "ETF":
            asset_class = "ETF"
        elif series == "EQ":
            asset_class = "EQUITY"
        else:
            return None  # skip non-EQ series (BE/BZ/GS/partly-paid/...)
        api_segment = _SEGMENT[(segment, exchange)]
    elif segment == "E" and exchange == "BSE":
        # BSE has no single "EQ series" like NSE — SEM_SERIES is a trading-group
        # letter (A/B/T/M/X/Z/NS/...) that doesn't distinguish equity from debt.
        # SEM_EXCH_INSTRUMENT_TYPE does: "ES" = Equity Stock, "ETF" = ETF; other
        # values (DEB/CB/DBT/GB/MF/PTC/TB) are fixed-income/other, excluded.
        instrument_type = row.get("SEM_EXCH_INSTRUMENT_TYPE", "").strip()
        if instrument_type == "ETF":
            asset_class = "ETF"
        elif instrument_type == "ES":
            asset_class = "EQUITY"
        else:
            return None
        api_segment = _SEGMENT[(segment, exchange)]
    elif segment == "D" and exchange == "NSE" and instrument_name in _DERIVATIVE_CLASS:
        if instrument_name == "OPTSTK":
            return None  # deferred to the options phase
        if instrument_name == "OPTIDX" and underlying not in INDEX_WHITELIST:
            return None
        asset_class = _DERIVATIVE_CLASS[instrument_name]
        api_segment = _SEGMENT[(segment, exchange)]
    elif segment == "M" and exchange == "MCX" and instrument_name in _COMMODITY_CLASS:
        if underlying not in COMMODITY_WHITELIST:
            return None
        asset_class = _COMMODITY_CLASS[instrument_name]
        api_segment = _SEGMENT[(segment, exchange)]
    else:
        return None

    option_type = row.get("SEM_OPTION_TYPE", "").strip() or None
    strike = row.get("SEM_STRIKE_PRICE", "").strip()
    return {
        "symbol": symbol,
        "name": (row.get("SM_SYMBOL_NAME") or row.get("SEM_CUSTOM_SYMBOL") or "").strip(),
        "security_id": row["SEM_SMST_SECURITY_ID"].strip(),
        "exchange_segment": api_segment,
        "asset_class": asset_class,
        "lot_size": int(float(row.get("SEM_LOT_UNITS") or 1)),
        "tick_size": float(row.get("SEM_TICK_SIZE") or 0.05),
        "underlying_symbol": underlying if segment in ("D", "M") else None,
        "expiry": _parse_expiry(row.get("SEM_EXPIRY_DATE", "")) if segment in ("D", "M") else None,
        "strike": float(strike) if strike and option_type in ("CE", "PE") else None,
        "option_type": option_type if option_type in ("CE", "PE") else None,
    }


def refresh_universe() -> int:
    print(f"universe: downloading scrip master from {SCRIP_MASTER_URL}")
    response = requests.get(SCRIP_MASTER_URL, timeout=120)
    response.raise_for_status()

    ensure_indexes()
    reader = csv.DictReader(io.StringIO(response.text))
    batch: list[dict] = []
    total = 0
    for row in reader:
        try:
            doc = _row_to_instrument(row)
        except (KeyError, ValueError):
            continue  # malformed row in the master file
        if doc is None:
            continue
        batch.append(doc)
        if len(batch) >= 1000:
            total += upsert_instruments(batch)
            batch = []
    total += upsert_instruments(batch)
    print(f"universe: upserted {total} instruments")
    return total


if __name__ == "__main__":
    refresh_universe()
