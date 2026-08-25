"""Load the WHOLE MCX board into the instrument master, straight from the broker.

WHY THIS EXISTS
---------------
Measured on production, 2026-08-22: MCX lists **28 underlyings**; the instrument master
carried **8**. Everything missing was invisible to every commodity module in the app —
including the mini contracts, which are the ones a smaller book actually trades:

    CRUDEOILM     6 futures, 1044 options   -- MISSING
    NATGASMINI    6 futures,  352 options   -- MISSING
    ALUMINIUM / ALUMINI / LEAD / LEADMINI / NICKEL / ZINCMINI / SILVERMIC /
    SILVER100 / GOLDGUINEA / GOLDPETAL / GOLDTEN / CARDAMOM / COTTON /
    COTTONOIL / KAPAS / MENTHAOIL / STEELREBAR / ELECDMBL   -- all MISSING

The gap comes from `market-data-service/universe.py`, a separate service that has to be
run by hand. Rather than depend on that, this reads Angel's own scrip master — the same
file the token mapper already downloads — and upserts every MCX futures and options
contract directly. It is the authoritative source, it is always current, and it carries
the one field our master gets wrong.

IT ALSO FIXES `lot_size`
-------------------------
Our master stores `lot_size: 1` for every MCX contract. Angel publishes the real
order-quantity unit, so this stamps it as `lot_size` AND keeps it verbatim in
`angel_lotsize`. Those are not the same thing as the VALUE multiplier — see
`commodity_positions.CONTRACT_SPEC` for why they disagree on GOLD, GOLDM and ZINC — but a
wrong 1 is worse than either.

SAFE TO RE-RUN, AND IT NEVER DELETES
-------------------------------------
Upserts keyed on (security_id, exchange_segment), which is the master's own unique index.
Expired contracts are left alone rather than removed: other desks hold closed positions
that point at them, and a position whose instrument vanished cannot render its own history.
"""

import logging
import os
from datetime import date, datetime

import httpx
from pymongo import UpdateOne

from app.core.db import instruments_collection

logger = logging.getLogger("commodity_instruments")

SCRIP_MASTER_URL = os.getenv(
    "ANGEL_SCRIP_MASTER_URL",
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json")

# Angel instrument types -> our asset classes. Only the two that are tradable contracts;
# COMDTY (spot), FUTIDX/OPTIDX (MCX indices) and AMXIDX are deliberately excluded.
KIND_TO_CLASS = {"FUTCOM": "COMMODITY_FUTURE", "OPTFUT": "COMMODITY_OPTION"}

# Angel publishes MCX strikes and ticks in PAISE. The master stores strikes in rupees
# (a SILVER 272000 strike against a 2,42,107 futures price) and ticks as published.
PAISE = 100.0

_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}


def _parse_expiry(raw: str) -> str | None:
    """Angel writes MCX expiries as `31AUG2026`. Returns an ISO date, or None."""
    if not raw or len(raw) < 9:
        return None
    try:
        day = int(raw[:2])
        month = _MONTHS[raw[2:5].upper()]
        year = int(raw[5:9])
        return date(year, month, day).isoformat()
    except (ValueError, KeyError):
        return None


def _symbol_for(row: dict, asset_class: str, expiry: str, strike_rupees: float | None,
                option_type: str | None) -> str:
    """The app's own contract naming, matching what the master already holds:
    `NATURALGAS-26Aug2026-FUT` / `SILVER-28Aug2026-272000-CE`."""
    name = (row.get("name") or "").upper()
    d = datetime.fromisoformat(expiry)
    stamp = f"{d.day:02d}{d.strftime('%b')}{d.year}"
    if asset_class == "COMMODITY_FUTURE":
        return f"{name}-{stamp}-FUT"
    return f"{name}-{stamp}-{strike_rupees:g}-{option_type}"


def build_rows(scrip_master: list[dict]) -> list[dict]:
    """Every MCX futures/options contract as an instrument document. Pure — testable
    without the network."""
    out: list[dict] = []
    for row in scrip_master:
        if row.get("exch_seg") != "MCX":
            continue
        asset_class = KIND_TO_CLASS.get(row.get("instrumenttype") or "")
        if asset_class is None:
            continue
        expiry = _parse_expiry(row.get("expiry") or "")
        if not expiry:
            continue

        option_type = None
        strike_rupees = None
        if asset_class == "COMMODITY_OPTION":
            raw_symbol = (row.get("symbol") or "").upper()
            if raw_symbol.endswith("CE"):
                option_type = "CE"
            elif raw_symbol.endswith("PE"):
                option_type = "PE"
            else:
                continue
            try:
                strike_rupees = round(float(row.get("strike") or 0) / PAISE, 4)
            except (TypeError, ValueError):
                continue
            if strike_rupees <= 0:
                continue

        try:
            lot = int(float(row.get("lotsize") or 1))
        except (TypeError, ValueError):
            lot = 1
        try:
            tick = float(row.get("tick_size") or 0)
        except (TypeError, ValueError):
            tick = 0.0

        token = str(row.get("token") or "")
        if not token:
            continue

        out.append({
            "symbol": _symbol_for(row, asset_class, expiry, strike_rupees, option_type),
            "name": (row.get("name") or "").upper(),
            "underlying_symbol": (row.get("name") or "").upper(),
            "asset_class": asset_class,
            "exchange_segment": "MCX_COMM",
            "security_id": token,
            "angel_token": token,
            "angel_exchange": "MCX",
            "angel_tradingsymbol": row.get("symbol"),
            "expiry": expiry,
            "strike": strike_rupees,
            "option_type": option_type,
            # The broker's order-quantity unit. NOT the value multiplier — see
            # commodity_positions.CONTRACT_SPEC.
            "lot_size": lot,
            "angel_lotsize": lot,
            "tick_size": tick,
        })
    return out


async def sync(only_unexpired: bool = True) -> dict:
    """Download the scrip master and upsert every MCX contract."""
    async with httpx.AsyncClient(timeout=240) as client:
        scrip = (await client.get(SCRIP_MASTER_URL)).json()

    rows = build_rows(scrip)
    today = date.today().isoformat()
    if only_unexpired:
        rows = [r for r in rows if r["expiry"] >= today]

    ops = [UpdateOne(
        {"security_id": r["security_id"], "exchange_segment": r["exchange_segment"]},
        {"$set": r}, upsert=True) for r in rows]

    written = 0
    for i in range(0, len(ops), 1000):
        res = await instruments_collection.bulk_write(ops[i:i + 1000], ordered=False)
        written += (res.upserted_count or 0) + (res.modified_count or 0)

    underlyings = sorted({r["underlying_symbol"] for r in rows})
    futures = sum(1 for r in rows if r["asset_class"] == "COMMODITY_FUTURE")
    options = len(rows) - futures
    stats = {"scrip_rows": len(scrip), "mcx_contracts": len(rows),
             "futures": futures, "options": options,
             "underlyings": len(underlyings), "written": written,
             "underlying_list": underlyings}
    logger.info("[commodity_instruments] synced %d MCX contracts across %d underlyings "
                "(%d futures, %d options)", len(rows), len(underlyings), futures, options)
    return stats


async def coverage() -> dict:
    """What the master holds per MCX underlying — futures, options, and lot size."""
    today = date.today().isoformat()
    names = await instruments_collection.distinct(
        "underlying_symbol",
        {"asset_class": {"$in": list(KIND_TO_CLASS.values())}, "expiry": {"$gte": today}})
    out = []
    for sym in sorted(n for n in names if n):
        f = await instruments_collection.count_documents(
            {"underlying_symbol": sym, "asset_class": "COMMODITY_FUTURE",
             "expiry": {"$gte": today}})
        o = await instruments_collection.count_documents(
            {"underlying_symbol": sym, "asset_class": "COMMODITY_OPTION",
             "expiry": {"$gte": today}})
        doc = await instruments_collection.find_one(
            {"underlying_symbol": sym, "asset_class": "COMMODITY_FUTURE"},
            {"lot_size": 1, "angel_lotsize": 1, "tick_size": 1})
        out.append({"underlying": sym, "futures": f, "options": o,
                    "lot_size": (doc or {}).get("lot_size"),
                    "angel_lotsize": (doc or {}).get("angel_lotsize"),
                    "tick_paise": (doc or {}).get("tick_size")})
    return {"underlyings": out, "count": len(out)}


__all__ = ["sync", "coverage", "build_rows", "KIND_TO_CLASS", "SCRIP_MASTER_URL"]
