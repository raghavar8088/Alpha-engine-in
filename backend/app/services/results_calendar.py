"""Quarterly results: when each company files, and which session reacts to it.

WHY: results days are the single biggest predictable source of MOVEMENT. Measured over
516 sessions (2026-10-02 research): the 09:45->15:00 move on a stock's reaction day
averaged 177 bp against 106 bp on other days. Direction on that day was NOT predictable
from anything at 09:45, and the day-after drift was not either — so this calendar feeds
"where to trade", never "which way".

THE REACTION DAY is the first session whose trading can see the filing: filed before
15:30 on a trading day -> that day; filed after 15:30, or on a weekend/holiday -> the next
trading day (NSE calendar).

Sources, in order of trust:
  filed      NSE corporates-financial-results API: the exchange's own dissemination time.
  scheduled  NSE corporate-board-meetings API: "Financial Results" meetings announced ahead.
  seed       the 2026-10-02 research collection (NSE filings + Yahoo earnings dates).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone

from app.core.db import db
from app.services import market_calendar
from app.services.nse_client import nse

logger = logging.getLogger("results_calendar")

IST = timezone(timedelta(hours=5, minutes=30))
coll = db["results_calendar"]
status: dict = {"last_refresh": None, "filed": 0, "scheduled": 0}


def reaction_day(filed_at: datetime) -> date:
    t = filed_at.astimezone(IST)
    d = t.date()
    if market_calendar.is_listed_trading_day(d) and t.time() < time(15, 30):
        return d
    return market_calendar.next_trading_day(d)


def _parse_nse(ts: str | None) -> datetime | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(ts.strip(), fmt).replace(tzinfo=IST)
        except (AttributeError, ValueError):
            continue
    return None


async def _upsert(symbol: str, kind: str, at: datetime | None, day: date, source: str, extra: dict | None = None):
    rd = reaction_day(at) if at else day
    await coll.update_one(
        {"_id": f"{symbol}:{kind}:{(at.date() if at else day).isoformat()}"},
        {"$set": {"symbol": symbol, "kind": kind, "at": at, "date": (at.date() if at else day).isoformat(),
                  "reaction_day": rd.isoformat(), "source": source, **(extra or {})}},
        upsert=True)


async def refresh(days_back: int = 3, days_ahead: int = 30) -> dict:
    """Pull recent filings and upcoming results meetings from NSE. Never raises."""
    today = datetime.now(IST).date()
    f, s = 0, 0
    try:
        frm, to = (today - timedelta(days=days_back)).strftime("%d-%m-%Y"), today.strftime("%d-%m-%Y")
        body = await nse.api(f"/api/corporates-financial-results?index=equities&period=Quarterly"
                             f"&from_date={frm}&to_date={to}",
                             "/companies-listing/corporate-filings-financial-results")
        for it in (body if isinstance(body, list) else (body or {}).get("data", [])) or []:
            at = _parse_nse(it.get("exchdisstime") or it.get("broadCastDate"))
            if it.get("symbol") and at:
                await _upsert(it["symbol"], "filed", at, at.date(), "nse-financial-results",
                              {"period_to": it.get("toDate"), "consolidated": it.get("consolidated")})
                f += 1
    except Exception:  # noqa: BLE001
        logger.exception("financial-results refresh failed")
    try:
        frm, to = today.strftime("%d-%m-%Y"), (today + timedelta(days=days_ahead)).strftime("%d-%m-%Y")
        body = await nse.api(f"/api/corporate-board-meetings?index=equities&from_date={frm}&to_date={to}",
                             "/companies-listing/corporate-filings-board-meetings")
        for it in (body if isinstance(body, list) else (body or {}).get("data", [])) or []:
            if "result" not in (it.get("bm_purpose") or "").lower():
                continue
            d = _parse_nse(it.get("bm_date"))
            if it.get("bm_symbol") and d:
                await _upsert(it["bm_symbol"], "scheduled", None, d.date(), "nse-board-meetings",
                              {"purpose": it.get("bm_purpose")})
                s += 1
    except Exception:  # noqa: BLE001
        logger.exception("board-meetings refresh failed")
    status.update({"last_refresh": datetime.now(timezone.utc).isoformat(), "filed": f, "scheduled": s})
    return {"filed": f, "scheduled": s}


async def seed(results_json: str, earnings_json: str) -> dict:
    """One-off: load the research collection. NSE filings exact; Yahoo dates only where
    NSE has nothing within 3 days."""
    n = 0
    exact: dict[str, list[date]] = {}
    try:
        for it in json.load(open(results_json)):
            at = _parse_nse(it.get("exchdisstime") or it.get("broadCastDate"))
            if it.get("symbol") and at:
                await _upsert(it["symbol"], "filed", at, at.date(), "seed-nse")
                exact.setdefault(it["symbol"], []).append(at.date())
                n += 1
    except FileNotFoundError:
        pass
    try:
        dates = json.load(open(earnings_json)).get("dates", {})
    except FileNotFoundError:
        dates = {}
    for sym, stamps in dates.items():
        for s_ in stamps:
            try:
                at = datetime.fromisoformat(s_).astimezone(IST)
            except ValueError:
                continue
            if any(abs((at.date() - e).days) <= 3 for e in exact.get(sym, [])):
                continue
            if at.date() > datetime.now(IST).date():
                await _upsert(sym, "scheduled", None, at.date(), "seed-yahoo")
            else:
                await _upsert(sym, "filed", at, at.date(), "seed-yahoo")
            n += 1
    return {"seeded": n}


async def reacting_on(day: date) -> dict[str, dict]:
    """Symbols whose results reaction day is `day`: filed ones (with time), else scheduled."""
    out: dict[str, dict] = {}
    async for d in coll.find({"reaction_day": day.isoformat()}):
        prev = out.get(d["symbol"])
        if prev is None or (prev["kind"] == "scheduled" and d["kind"] == "filed"):
            out[d["symbol"]] = {"kind": d["kind"], "at": d.get("at").isoformat() if d.get("at") else None,
                                "source": d.get("source")}
    return out


async def upcoming(days: int = 7) -> list[dict]:
    today = datetime.now(IST).date()
    rows = []
    async for d in coll.find({"reaction_day": {"$gte": today.isoformat(),
                                               "$lte": (today + timedelta(days=days)).isoformat()}}).sort("reaction_day", 1):
        d.pop("_id", None)
        if isinstance(d.get("at"), datetime):
            d["at"] = d["at"].isoformat()
        rows.append(d)
    return rows


async def ensure_indexes() -> None:
    try:
        await coll.create_index([("reaction_day", 1)], name="rc_reaction_day", background=True)
        await coll.create_index([("symbol", 1), ("reaction_day", -1)], name="rc_symbol", background=True)
    except Exception:  # noqa: BLE001
        logger.warning("results_calendar indexes skipped")
