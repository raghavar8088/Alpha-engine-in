"""MCX futures curve recorder (C2) — the data a carry strategy would need, from today on.

WHY
Commodity carry (the slope of the futures curve) is the best-documented commodity return
premium after trend, and it cannot be tested on MCX at all: no source this app can reach
keeps historical MCX curves. Yahoo serves one continuous front contract per commodity, and
Angel returns nothing for an expired contract (probed 2026-10-03). So the curve has to be
recorded going forward. Three snapshots a trading day — late morning, the evening open and
late evening — of EVERY listed future of each underlying: last price, the two-sided book,
open interest, volume and the time of the last trade. HC4 (carry) waits on this data.

One document per (date, slot, underlying), ~20 underlyings x 3 slots = ~60 small documents
a day. Each also carries the annualised slope between its first two contracts.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from datetime import date, datetime, time, timedelta, timezone

from tradingai_shared import mcx_calendar as mcal

from app.core.db import db

logger = logging.getLogger("mcx_curve_recorder")

curve_collection = db["mcx_curve"]
IST = mcal.IST

CURVE_UNDERLYINGS = [u.strip().upper() for u in os.getenv(
    "MCX_CURVE_UNDERLYINGS",
    "GOLD,GOLDM,GOLDTEN,GOLDPETAL,SILVER,SILVERM,SILVERMIC,CRUDEOIL,CRUDEOILM,NATURALGAS,"
    "NATGASMINI,COPPER,ZINC,ZINCMINI,ALUMINIUM,ALUMINI,LEAD,LEADMINI,NICKEL").split(",") if u.strip()]
# (slot name, IST time). 17:20 rather than 17:00 so the evening session has traded.
SLOTS = [("late_morning", time(11, 0)), ("evening_open", time(17, 20)), ("late_evening", time(22, 45))]
_status: dict = {"last": None, "error": None}


def _slope(c1: dict, c2: dict) -> float | None:
    """Annualised log slope between two contracts' prices — positive = contango."""
    try:
        p1, p2 = float(c1["ltp"]), float(c2["ltp"])
        d1, d2 = date.fromisoformat(c1["expiry"]), date.fromisoformat(c2["expiry"])
    except (TypeError, ValueError, KeyError):
        return None
    years = (d2 - d1).days / 365.0
    if p1 <= 0 or p2 <= 0 or years <= 0:
        return None
    return math.log(p2 / p1) / years


async def snapshot(slot: str) -> dict:
    from app.services import mcx_market

    today = mcal.as_date(None).isoformat()
    listed = await mcx_market.listed_futures(CURVE_UNDERLYINGS)
    contracts = [d for rows in listed.values() for d in rows]
    q = await mcx_market.quotes(contracts)
    written = 0
    for u, rows in listed.items():
        if not rows:
            continue
        legs = []
        for d in rows:
            tok = str(d.get("angel_token") or d.get("security_id"))
            qq = q.get(tok)
            legs.append({"symbol": d.get("symbol"), "expiry": d.get("expiry"), "token": tok,
                         "ltp": qq.ltp if qq else None, "bid": qq.bid if qq else None,
                         "ask": qq.ask if qq else None, "oi": qq.oi if qq else None,
                         "volume": qq.volume if qq else None,
                         "trade_time": qq.trade_time if qq else None, "fresh": bool(qq and qq.fresh)})
        priced = [x for x in legs if x["ltp"] and x["fresh"]]
        doc = {"date": today, "slot": slot, "underlying": u, "ts": datetime.now(timezone.utc),
               "contracts": legs, "n_priced": len(priced),
               "slope_1_2": _slope(priced[0], priced[1]) if len(priced) >= 2 else None}
        await curve_collection.update_one({"date": today, "slot": slot, "underlying": u}, {"$set": doc}, upsert=True)
        written += 1
    out = {"date": today, "slot": slot, "underlyings": written, "at": datetime.now(timezone.utc).isoformat()}
    _status.update({"last": out, "error": None})
    return out


def _next_slot(now: datetime) -> tuple[str, datetime]:
    """The next (slot, when) that falls inside an MCX session."""
    for back in range(0, 15):
        d = now.date() + timedelta(days=back)
        for name, t in SLOTS:
            at = datetime.combine(d, t, IST)
            if at > now and mcal.session_at(at) is not None:
                return name, at
    return SLOTS[0][0], now + timedelta(hours=6)


async def mcx_curve_loop() -> None:
    while True:
        now = datetime.now(IST)
        name, at = _next_slot(now)
        await asyncio.sleep(max(5.0, (at - now).total_seconds()))
        try:
            if mcal.session_at(datetime.now(IST)) is not None:
                out = await snapshot(name)
                logger.info("[mcx_curve] %s", out)
        except Exception as exc:  # noqa: BLE001 — a missed snapshot is a gap, not an outage
            _status["error"] = str(exc)[:200]
            logger.exception("[mcx_curve] snapshot failed")


async def status() -> dict:
    n = await curve_collection.estimated_document_count()
    first = await curve_collection.find_one({}, {"date": 1}, sort=[("date", 1)])
    days = len(await curve_collection.distinct("date"))
    nxt, at = _next_slot(datetime.now(IST))
    return {"documents": n, "first_date": first.get("date") if first else None, "trading_days_recorded": days,
            "next_slot": nxt, "next_at": at.isoformat(), "last": _status["last"], "error": _status["error"],
            "underlyings": CURVE_UNDERLYINGS}


async def ensure_indexes() -> None:
    try:
        await curve_collection.create_index([("date", 1), ("slot", 1), ("underlying", 1)],
                                            name="mcx_curve_key", unique=True, background=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcx_curve index skipped: %s", exc)
