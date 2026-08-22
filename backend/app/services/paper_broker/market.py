"""Instruments and live prices for the paper broker — Angel One only.

WHY ANGEL RATHER THAN DHAN. The two existing paper desks (`manual_positions`,
`fno_positions`) price off Dhan and fall back to Angel. This module is Angel-first and
Angel-only, because that is what was asked for and because a single source removes a class
of confusion these desks already hit: a position marked on Dhan and a chain priced on Angel
can disagree by a tick, and the resulting P&L is then not attributable to either feed.

QUOTES ARE BATCHED, ALWAYS. Angel takes up to 50 tokens per request grouped by exchange.
Every read here goes through `quotes()` with the full set of tokens the caller needs, never
one call per instrument — a per-contract loop against this endpoint is what has taken the
option chain down before.

MISSING QUOTES ARE MISSING, NOT ZERO. A token Angel does not answer for is absent from the
returned dict. Callers must treat absence as "cannot price right now" and refuse to fill,
rather than marking a position at zero and booking a fictional loss.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.db import instruments_collection
from app.services.angel_client import AngelAPIError, angel_client
from app.services.paper_broker.core import SEGMENT_EQUITY, SEGMENT_FNO, OrderError
from tradingai_broker_clients.angel.auth import batches

logger = logging.getLogger("paper_broker.market")

QUOTE_PACE_SECONDS = 0.15

OPTION_CLASSES = ("INDEX_OPTION", "EQUITY_OPTION")
FUTURE_CLASSES = ("INDEX_FUTURE", "EQUITY_FUTURE")
FNO_CLASSES = OPTION_CLASSES + FUTURE_CLASSES


def _exchange_for(inst: dict) -> str:
    """Angel's exchange code for an instrument doc."""
    return inst.get("angel_exchange") or ("NFO" if inst.get("asset_class") in FNO_CLASSES else "NSE")


def instrument_kind(inst: dict) -> str:
    ac = inst.get("asset_class") or ""
    if ac in OPTION_CLASSES:
        return "OPTION"
    if ac in FUTURE_CLASSES:
        return "FUTURE"
    return "EQUITY"


def to_contract(inst: dict) -> dict:
    """The instrument fields an order needs, flattened and stable.

    Orders store a snapshot rather than a reference, because the instrument master is
    rebuilt daily as contracts list and expire — a position that outlives its master row
    must still be able to describe itself.
    """
    return {
        "symbol": inst["symbol"],
        "name": inst.get("name") or inst["symbol"],
        "security_id": inst.get("security_id"),
        "angel_token": str(inst["angel_token"]) if inst.get("angel_token") else None,
        "exchange": _exchange_for(inst),
        "exchange_segment": inst.get("exchange_segment"),
        "asset_class": inst.get("asset_class"),
        "kind": instrument_kind(inst),
        "lot_size": int(inst.get("lot_size") or 1),
        "tick_size": float(inst.get("tick_size") or 0.05),
        "expiry": inst.get("expiry"),
        "strike": inst.get("strike"),
        "option_type": inst.get("option_type"),
        "underlying": inst.get("underlying_symbol"),
    }


async def quotes(contracts: list[dict]) -> dict[str, float]:
    """{angel_token: ltp} for a list of contract snapshots. Never raises."""
    by_ex: dict[str, list[str]] = {}
    for c in contracts:
        tok = c.get("angel_token")
        if tok:
            by_ex.setdefault(c.get("exchange") or "NSE", []).append(str(tok))
    if not by_ex or not angel_client.configured():
        return {}

    # Warm the session once with a single retry: a momentarily rate-limited login
    # otherwise fails the first chunk and blanks every price behind it.
    for attempt in range(2):
        try:
            await angel_client._session()
            break
        except AngelAPIError:
            if attempt == 0:
                await asyncio.sleep(0.7)

    out: dict[str, float] = {}
    for grouped in batches(by_ex):
        try:
            for tok, q in (await angel_client.full_quote(grouped)).items():
                if q.get("ltp"):
                    out[str(tok)] = float(q["ltp"])
        except AngelAPIError:
            # Per-chunk catch: one bad chunk must not blank every other instrument.
            pass
        await asyncio.sleep(QUOTE_PACE_SECONDS)
    return out


async def quote_one(contract: dict) -> float | None:
    return (await quotes([contract])).get(str(contract.get("angel_token")))


async def full_quotes(contracts: list[dict]) -> dict[str, dict]:
    """Same batching, but the whole FULL payload (OHLC, volume, OI) for the order ticket."""
    by_ex: dict[str, list[str]] = {}
    for c in contracts:
        tok = c.get("angel_token")
        if tok:
            by_ex.setdefault(c.get("exchange") or "NSE", []).append(str(tok))
    if not by_ex or not angel_client.configured():
        return {}
    try:
        await angel_client._session()
    except AngelAPIError:
        return {}
    out: dict[str, dict] = {}
    for grouped in batches(by_ex):
        try:
            out.update(await angel_client.full_quote(grouped))
        except AngelAPIError:
            pass
        await asyncio.sleep(QUOTE_PACE_SECONDS)
    return out


# ── lookup ──────────────────────────────────────────────────────────────────────


async def search(query: str, segment: str = SEGMENT_EQUITY, limit: int = 20) -> list[dict]:
    """Scrip search for the order ticket. Only instruments Angel can actually quote."""
    q = (query or "").strip().upper()
    if not q:
        return []
    classes = list(FNO_CLASSES) if segment == SEGMENT_FNO else ["EQUITY"]
    cursor = instruments_collection.find(
        {
            "asset_class": {"$in": classes},
            "angel_token": {"$ne": None},
            "$or": [{"symbol": {"$regex": f"^{q}"}}, {"name": {"$regex": q}}],
        },
        {"_id": 0},
    ).limit(limit)
    return [to_contract(d) async for d in cursor]


async def resolve_equity(symbol: str) -> dict:
    doc = await instruments_collection.find_one(
        {"symbol": symbol.upper(), "asset_class": "EQUITY", "angel_token": {"$ne": None}})
    if doc is None:
        raise OrderError(
            f"{symbol.upper()} is not an Angel-quotable NSE equity in the instrument master")
    return to_contract(doc)


async def fno_underlyings() -> list[dict]:
    """Underlyings that actually have listed contracts on file, with their kinds."""
    rows = await instruments_collection.aggregate([
        {"$match": {"asset_class": {"$in": list(FNO_CLASSES)}, "angel_token": {"$ne": None}}},
        {"$group": {"_id": "$underlying_symbol",
                    "classes": {"$addToSet": "$asset_class"},
                    "lot_size": {"$first": "$lot_size"}}},
        {"$sort": {"_id": 1}},
    ]).to_list(length=500)
    return [
        {
            "symbol": r["_id"],
            "lot_size": int(r.get("lot_size") or 1),
            "has_options": any(c in OPTION_CLASSES for c in r.get("classes", [])),
            "has_futures": any(c in FUTURE_CLASSES for c in r.get("classes", [])),
        }
        for r in rows if r.get("_id")
    ]


async def expiries(symbol: str, kind: str = "OPTION") -> list[str]:
    classes = list(OPTION_CLASSES) if kind == "OPTION" else list(FUTURE_CLASSES)
    vals = await instruments_collection.distinct(
        "expiry", {"underlying_symbol": symbol.upper(), "asset_class": {"$in": classes},
                   "angel_token": {"$ne": None}})
    return sorted(v for v in vals if v)


async def resolve_option(symbol: str, expiry: str, strike: float, option_type: str) -> dict:
    doc = await instruments_collection.find_one({
        "underlying_symbol": symbol.upper(), "expiry": expiry, "strike": strike,
        "option_type": option_type.upper(), "asset_class": {"$in": list(OPTION_CLASSES)},
        "angel_token": {"$ne": None},
    })
    if doc is None:
        raise OrderError(
            f"No Angel-quotable contract for {symbol.upper()} {expiry} {strike:g}"
            f"{option_type.upper()}")
    return to_contract(doc)


async def resolve_future(symbol: str, expiry: str) -> dict:
    doc = await instruments_collection.find_one({
        "underlying_symbol": symbol.upper(), "expiry": expiry,
        "asset_class": {"$in": list(FUTURE_CLASSES)}, "angel_token": {"$ne": None},
    })
    if doc is None:
        raise OrderError(f"No Angel-quotable future for {symbol.upper()} expiring {expiry}")
    return to_contract(doc)


async def option_chain(symbol: str, expiry: str) -> dict:
    """Strike ladder with live premiums and OI, for the F&O order ticket.

    Built here off the instrument master plus one batched FULL quote rather than reusing
    `angel_option_chain`, because the ticket needs the exact contract snapshot it will
    place an order against — the chain module returns a display structure, and re-resolving
    a strike from a display row is where an order ends up on the wrong contract.
    """
    docs = [d async for d in instruments_collection.find({
        "underlying_symbol": symbol.upper(), "expiry": expiry,
        "asset_class": {"$in": list(OPTION_CLASSES)}, "angel_token": {"$ne": None},
    }, {"_id": 0})]
    if not docs:
        raise OrderError(f"No option contracts on file for {symbol.upper()} {expiry}")

    contracts = [to_contract(d) for d in docs]
    fq = await full_quotes(contracts)

    by_strike: dict[float, dict] = {}
    for c in contracts:
        strike = float(c["strike"] or 0)
        if not strike:
            continue
        row = by_strike.setdefault(strike, {"strike": strike, "CE": None, "PE": None})
        q = fq.get(str(c["angel_token"])) or {}
        leg = {
            "contract": c,
            "ltp": q.get("ltp"),
            "oi": q.get("oi"),
            "volume": q.get("volume"),
            "close": q.get("close"),
            "change_pct": (round((q["ltp"] / q["close"] - 1) * 100, 2)
                           if q.get("ltp") and q.get("close") else None),
        }
        row[(c["option_type"] or "").upper()] = leg

    strikes = [by_strike[k] for k in sorted(by_strike)]

    # ATM from put-call parity across the ladder: the strike where |CE - PE| is smallest is
    # the market's own view of the forward, and it needs no separate spot quote — which
    # matters because index spot and the option chain can be a beat apart.
    atm = None
    best = None
    for row in strikes:
        ce, pe = (row.get("CE") or {}).get("ltp"), (row.get("PE") or {}).get("ltp")
        if ce is None or pe is None:
            continue
        gap = abs(ce - pe)
        if best is None or gap < best:
            best, atm = gap, row["strike"]

    return {
        "symbol": symbol.upper(),
        "expiry": expiry,
        "atm_strike": atm,
        "lot_size": contracts[0]["lot_size"],
        "count": len(strikes),
        "strikes": strikes,
        "priced": sum(1 for r in strikes
                      if (r.get("CE") or {}).get("ltp") or (r.get("PE") or {}).get("ltp")),
    }
