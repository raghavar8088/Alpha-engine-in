"""Keeps the INDEX derivative contracts in the instrument master current.

WHY THIS EXISTS (found 2026-10-02)
The instrument master's NIFTY options came from `market-data-service/universe.py`, a script
that is run by hand. It was last run in July, so the master held NIFTY weeklies only up to
11 Aug, then the 25 Aug and 29 Sep monthlies, then 29 Dec. Every desk that picks "the nearest
NIFTY expiry from the master" silently traded whatever was left: the Pre-Live tournament's
"weekly ATM" buys were monthlies from mid-August (1,500 trades 11-35 days out) and a
December contract from 30 Sep (259 trades 88-90 days out). The Angel token refresh below it
runs every 12 hours but only stamps tokens onto contracts that already exist, so new weeklies
never appeared.

This streams Dhan's public scrip master (the same file and the same document shape as
universe.py, keyed by Dhan security id, which the Dhan feeds need) and upserts the index
futures and options of the whitelisted indices. It never deletes: expired contracts stay so
past trades can still be resolved to their real expiry. Streaming matters: the file is tens
of megabytes and the backend runs close to its memory cap, so it is read line by line and
only the few thousand index-derivative rows are kept.
"""

from __future__ import annotations

import csv
import logging
from datetime import date, datetime, timedelta, timezone

import httpx
from pymongo import UpdateOne

from app.core.db import instruments_collection

logger = logging.getLogger("index_derivatives")

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
INDEX_WHITELIST = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
CLASSES = {"OPTIDX": "INDEX_OPTION", "FUTIDX": "INDEX_FUTURE"}
KEEP_EXPIRED_DAYS = 7          # a contract that expired last week is still worth refreshing
status: dict = {"last_sync": None, "contracts": 0, "nifty_expiries": [], "error": None}


def _expiry(raw: str) -> str | None:
    raw = (raw or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def row_to_doc(row: dict, cutoff: str) -> dict | None:
    """The universe.py document shape, for NSE index futures/options only."""
    if row.get("SEM_SEGMENT", "").strip() != "D" or row.get("SEM_EXM_EXCH_ID", "").strip() != "NSE":
        return None
    cls = CLASSES.get(row.get("SEM_INSTRUMENT_NAME", "").strip())
    symbol = row.get("SEM_TRADING_SYMBOL", "").strip()
    underlying = symbol.split("-")[0].strip()
    if cls is None or underlying not in INDEX_WHITELIST:
        return None
    expiry = _expiry(row.get("SEM_EXPIRY_DATE", ""))
    if not expiry or expiry < cutoff:
        return None
    option_type = (row.get("SEM_OPTION_TYPE") or "").strip() or None
    strike = (row.get("SEM_STRIKE_PRICE") or "").strip()
    return {
        "symbol": symbol,
        "name": (row.get("SM_SYMBOL_NAME") or row.get("SEM_CUSTOM_SYMBOL") or "").strip(),
        "security_id": row["SEM_SMST_SECURITY_ID"].strip(),
        "exchange_segment": "NSE_FNO",
        "asset_class": cls,
        "lot_size": int(float(row.get("SEM_LOT_UNITS") or 1)),
        "tick_size": float(row.get("SEM_TICK_SIZE") or 0.05),
        "underlying_symbol": underlying,
        "expiry": expiry,
        "strike": float(strike) if strike and option_type in ("CE", "PE") else None,
        "option_type": option_type if option_type in ("CE", "PE") else None,
    }


async def sync(dry_run: bool = False) -> dict:
    """Stream the scrip master and upsert current index derivatives. Never raises."""
    cutoff = (date.today() - timedelta(days=KEEP_EXPIRED_DAYS)).isoformat()
    now = datetime.now(timezone.utc)
    ops: list[UpdateOne] = []
    kept = 0
    header: list[str] | None = None
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            async with client.stream("GET", SCRIP_MASTER_URL) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    if header is None:
                        header = next(csv.reader([line]))
                        continue
                    if "IDX" not in line or not line.startswith("NSE,"):
                        continue            # cheap pre-filter before the csv parse
                    vals = next(csv.reader([line]))
                    if len(vals) != len(header):
                        continue
                    try:
                        doc = row_to_doc(dict(zip(header, vals)), cutoff)
                    except (KeyError, ValueError):
                        continue
                    if doc is None:
                        continue
                    kept += 1
                    ops.append(UpdateOne({"security_id": doc["security_id"], "exchange_segment": "NSE_FNO"},
                                         {"$set": {**doc, "synced_at": now}}, upsert=True))
        if dry_run:
            exp_new = sorted({op._doc["$set"]["expiry"] for op in ops
                              if op._doc["$set"]["underlying_symbol"] == "NIFTY" and op._doc["$set"]["asset_class"] == "INDEX_OPTION"})
            return {"dry_run": True, "contracts": kept, "nifty_option_expiries": exp_new[:10],
                    "nifty_lot": next((op._doc["$set"]["lot_size"] for op in ops
                                       if op._doc["$set"]["underlying_symbol"] == "NIFTY"), None)}
        written = 0
        for i in range(0, len(ops), 1000):
            res = await instruments_collection.bulk_write(ops[i:i + 1000], ordered=False)
            written += res.upserted_count + res.modified_count
        exps = sorted(e for e in await instruments_collection.distinct(
            "expiry", {"asset_class": "INDEX_OPTION", "underlying_symbol": "NIFTY"})
            if e and e >= date.today().isoformat())
        status.update({"last_sync": now.isoformat(), "contracts": kept, "written": written,
                       "nifty_expiries": exps[:8], "error": None})
        logger.info("index derivatives synced: %d contracts (%d written); NIFTY expiries ahead %s",
                    kept, written, exps[:6])
        return dict(status)
    except Exception as exc:  # noqa: BLE001 - a failed sync leaves the old master in place
        status["error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("index derivative sync failed")
        return dict(status)


async def weekly_expiry_ok(underlying: str = "NIFTY", max_days: int = 7) -> tuple[bool, str | None]:
    """Is a contract expiring within `max_days` listed? False means the master is stale."""
    today = date.today().isoformat()
    exps = sorted(e for e in await instruments_collection.distinct(
        "expiry", {"asset_class": "INDEX_OPTION", "underlying_symbol": underlying}) if e and e >= today)
    if not exps:
        return False, None
    return (date.fromisoformat(exps[0]) - date.today()).days <= max_days, exps[0]
