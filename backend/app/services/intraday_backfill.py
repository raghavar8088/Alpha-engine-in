"""History, gap-fill and nightly reconcile for the intraday bar store.

THREE JOBS, ONE PACED DOOR (every candle call goes through angel_client's shared pacer)

1. BACKFILL (off-hours only). Two years of 15-minute bars per universe symbol, newest
   first, in 200-day requests — the largest window Angel's FIFTEEN_MINUTE endpoint serves
   (measured 2026-10-02: a request from 2026-01-01 came back starting 2026-03-16, exactly
   200 days before its end; there is NO 500-candle cap — one request returned 3,137 bars).
   Resumable: progress is the files themselves plus a small state doc of symbols Angel has
   nothing older for. Runs as a BULK caller, so it yields to any live desk's candle call.

2. GAP-FILL (in session). A stream bucket the stream did not cover in full — a restart, a
   reconnect, a late join — is never built from partial ticks (see angel_stream). Instead,
   once the stream has produced a bar AFTER a hole, one candle request per symbol fetches
   the whole session so far and fills every hole at once.

3. RECONCILE (after the close). Today's bars are re-fetched from the candle endpoint, the
   authoritative record, and replace the stream's. The differences are recorded — how
   faithful the live bars were is a number, not an assumption.
"""

from __future__ import annotations

import asyncio
import logging
import os
import statistics
from datetime import date, datetime, timedelta, timezone

from app.core.db import db
from app.services import intraday_universe, market_calendar
from app.services.angel_client import AngelAPIError, angel_client, candle_pacer
from app.services.intraday_store import (SRC_CANDLE, SRC_STREAM, rows_from_angel, store,
                                         _ist)

logger = logging.getLogger("intraday_backfill")

IST = timezone(timedelta(hours=5, minutes=30))
HISTORY_DAYS = int(os.getenv("INTRADAY_HISTORY_DAYS", "730"))
WINDOW_DAYS = 199                        # Angel serves 200 calendar days of 15m per request
OFF_HOURS_FROM, OFF_HOURS_UNTIL = "15:50", "08:50"

state_collection = db["intraday_data_state"]

status: dict = {"backfill": {"running": False, "done_symbols": 0, "requests": 0, "bars": 0,
                             "errors": 0, "last": None},
                "gapfill": {"requests": 0, "bars": 0, "last": None},
                "reconcile": {"last_date": None}}


def off_hours(now: datetime | None = None) -> bool:
    now = (now or datetime.now(IST)).astimezone(IST)
    if not market_calendar.is_trading_day(now):
        return True
    hhmm = now.strftime("%H:%M")
    return hhmm >= OFF_HOURS_FROM or hhmm < OFF_HOURS_UNTIL


async def _fetch(member: dict, frm: datetime, to: datetime, bulk: bool) -> list[tuple] | None:
    """One candle request. None on failure (the caller retries later)."""
    for attempt in (1, 2, 3):
        try:
            rows = await angel_client.candles(
                member.get("exchange") or "NSE", str(member["token"]), "15",
                frm.strftime("%Y-%m-%d %H:%M"), to.strftime("%Y-%m-%d %H:%M"), bulk=bulk)
            return rows_from_angel(rows or [], SRC_CANDLE)
        except AngelAPIError as exc:
            # The pacer has already started a cooldown on a refusal; just try again.
            if attempt == 3:
                logger.warning("candles %s %s..%s failed: %s", member["symbol"],
                               frm.date(), to.date(), exc)
    return None


# ── 1. backfill ──────────────────────────────────────────────────────────────────


async def _exhausted() -> dict:
    doc = await state_collection.find_one({"_id": "backfill"}) or {}
    return doc.get("exhausted", {})


def _windows(have_from: date | None, have_to: date | None, today: date,
             floor: date) -> tuple[list[tuple[date, date]], list[tuple[date, date]]]:
    """(newer, older) request windows, each at most WINDOW_DAYS long.
    newer: from the last day on disk (re-fetched, it may have been partial) up to today.
    older: from the day before the first day on disk back to `floor`, newest first."""
    newer: list[tuple[date, date]] = []
    if have_to is not None and have_to < today:
        start = have_to
        while True:
            w_end = min(today, start + timedelta(days=WINDOW_DAYS))
            newer.append((start, w_end))
            if w_end >= today:
                break
            start = w_end + timedelta(days=1)
    older: list[tuple[date, date]] = []
    cursor = (have_from - timedelta(days=1)) if have_from else today
    while cursor >= floor:
        w_start = max(floor, cursor - timedelta(days=WINDOW_DAYS))
        older.append((w_start, cursor))
        cursor = w_start - timedelta(days=1)
    return newer, older


def _at(d: date, hh: int, mm: int) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm)


async def backfill_symbol(member: dict, earliest_wanted: date, exhausted: dict) -> dict:
    """Bring one symbol's file to cover [earliest_wanted, today]."""
    from app.services.intraday_store import read_file

    sym = member["symbol"]
    disk = await asyncio.to_thread(read_file, sym)
    have_from = _ist(disk.t[0]).date() if len(disk) else None
    have_to = _ist(disk.t[-1]).date() if len(disk) else None
    del disk
    floor = earliest_wanted
    if exhausted.get(sym):              # Angel holds nothing at or before this date
        floor = max(floor, date.fromisoformat(exhausted[sym]) + timedelta(days=1))
    newer, older = _windows(have_from, have_to, datetime.now(IST).date(), floor)
    added = requests = 0
    for kind, windows in (("newer", newer), ("older", older)):
        for w_start, w_end in windows:
            if not off_hours():
                return {"symbol": sym, "added": added, "requests": requests, "complete": False}
            rows = await _fetch(member, _at(w_start, 9, 15), _at(w_end, 15, 30), bulk=True)
            requests += 1
            status["backfill"]["requests"] += 1
            if rows is None:                     # a failure is not an empty answer
                status["backfill"]["errors"] += 1
                return {"symbol": sym, "added": added, "requests": requests, "complete": False}
            if rows:
                changed, _total = await store.merge_history(sym, rows)
                added += changed
                status["backfill"]["bars"] += changed
            elif kind == "older":
                # A whole ~6.5-month window with no bars: the stock was not listed (or Angel
                # keeps nothing) that far back. Remember it so we never ask again.
                exhausted[sym] = w_end.isoformat()
                await state_collection.update_one(
                    {"_id": "backfill"}, {"$set": {f"exhausted.{sym}": w_end.isoformat()}},
                    upsert=True)
                break
    return {"symbol": sym, "added": added, "requests": requests, "complete": True}


async def backfill(symbols: list[str] | None = None, days: int = HISTORY_DAYS) -> dict:
    """Bring every universe symbol's history to `days` back. Stops when the session opens."""
    if status["backfill"]["running"]:
        return {"already_running": True}
    status["backfill"].update({"running": True, "done_symbols": 0, "started": datetime.now(IST).isoformat()})
    try:
        members = await intraday_universe.members()
        if symbols:
            members = [m for m in members if m["symbol"] in set(symbols)]
        earliest = datetime.now(IST).date() - timedelta(days=days)
        exhausted = await _exhausted()
        done = []
        for m in members:
            if not off_hours():
                logger.info("backfill paused for the session after %d symbols", len(done))
                break
            r = await backfill_symbol(m, earliest, exhausted)
            done.append(r)
            status["backfill"]["done_symbols"] = len(done)
            status["backfill"]["last"] = r
        await store.flush_dirty()
        return {"symbols": len(done), "bars_added": sum(r["added"] for r in done),
                "requests": sum(r["requests"] for r in done),
                "incomplete": [r["symbol"] for r in done if not r["complete"]]}
    finally:
        status["backfill"]["running"] = False


# ── 2. gap-fill ──────────────────────────────────────────────────────────────────


def _session_starts(day: date, upto: int) -> list[int]:
    base = int(datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST).timestamp())
    return [base + k * 900 for k in range(25) if base + k * 900 + 900 <= upto]


def holes_today(symbol: str, now: datetime | None = None) -> list[int]:
    """Closed 15m buckets of today's session with no bar, before the latest bar we have."""
    now = (now or datetime.now(IST)).astimezone(IST)
    b = store.get(symbol)
    today = now.date()
    have = {t for t in b.t if _ist(t).date() == today}
    if not have:
        return []
    latest = max(have)
    return [t for t in _session_starts(today, int(now.timestamp())) if t < latest and t not in have]


async def gapfill(now: datetime | None = None) -> dict:
    """Fill today's holes. One request per symbol that has any."""
    now = (now or datetime.now(IST)).astimezone(IST)
    filled = asked = 0
    for m in await intraday_universe.members():
        holes = holes_today(m["symbol"], now)
        if not holes:
            continue
        rows = await _fetch(m, now.replace(hour=9, minute=15, second=0, microsecond=0),
                            now, bulk=True)
        asked += 1
        status["gapfill"]["requests"] += 1
        if not rows:
            continue
        end = int(now.timestamp())
        closed = [r for r in rows if r[0] + 900 <= end]
        filled += store.merge(m["symbol"], closed)
    status["gapfill"]["bars"] += filled
    status["gapfill"]["last"] = {"at": now.strftime("%H:%M"), "requests": asked, "bars": filled}
    return status["gapfill"]["last"]


# ── 3. reconcile ─────────────────────────────────────────────────────────────────


async def reconcile(day: date | None = None) -> dict:
    """Replace the day's stream bars with Angel's candles and measure the difference."""
    day = day or datetime.now(IST).date()
    frm = datetime(day.year, day.month, day.day, 9, 15)
    to = datetime(day.year, day.month, day.day, 15, 30)
    d_close, d_high, d_low, d_vol = [], [], [], []
    compared = replaced = missing_stream = symbols = 0
    worst: list[tuple[float, str, str]] = []
    for m in await intraday_universe.members():
        sym = m["symbol"]
        rows = await _fetch(m, frm, to, bulk=True)
        if rows is None:
            continue
        symbols += 1
        mem = {r[0]: r for r in store.get(sym).rows() if _ist(r[0]).date() == day}
        for r in rows:
            s = mem.get(r[0])
            if s is None:
                missing_stream += 1
                continue
            if s[6] != SRC_STREAM or r[5] == 0:
                continue
            compared += 1
            px = r[4] or 1.0
            d_close.append(abs(s[4] - r[4]) / px * 1e4)        # basis points
            d_high.append(abs(s[2] - r[2]) / px * 1e4)
            d_low.append(abs(s[3] - r[3]) / px * 1e4)
            d_vol.append(abs(s[5] - r[5]) / max(r[5], 1) * 100)  # percent
            worst.append((d_close[-1], sym, _ist(r[0]).strftime("%H:%M")))
        replaced += (await store.merge_history(sym, rows))[0]

    def pct(xs, q):
        if not xs:
            return None
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)

    worst.sort(reverse=True)
    report = {
        "_id": f"reconcile:{day.isoformat()}", "date": day.isoformat(), "symbols": symbols,
        "bars_compared": compared, "bars_replaced": replaced,
        "candle_bars_without_stream_bar": missing_stream,
        "close_bp": {"median": pct(d_close, 0.5), "p95": pct(d_close, 0.95), "max": pct(d_close, 1.0)},
        "high_bp": {"median": pct(d_high, 0.5), "p95": pct(d_high, 0.95)},
        "low_bp": {"median": pct(d_low, 0.5), "p95": pct(d_low, 0.95)},
        "volume_pct": {"median": pct(d_vol, 0.5), "p95": pct(d_vol, 0.95)},
        "exact_close_share": round(sum(1 for x in d_close if x < 0.01) / len(d_close), 3) if d_close else None,
        "worst_close": [{"bp": round(b, 1), "symbol": s, "bar": t} for b, s, t in worst[:10]],
        "at": datetime.now(timezone.utc),
    }
    await state_collection.replace_one({"_id": report["_id"]}, report, upsert=True)
    status["reconcile"]["last_date"] = day.isoformat()
    logger.info("reconcile %s: %d bars compared — close diff median %s bp, p95 %s bp; volume "
                "diff median %s%%", day, compared, report["close_bp"]["median"],
                report["close_bp"]["p95"], report["volume_pct"]["median"])
    return {k: v for k, v in report.items() if k != "_id"}


async def last_reconcile() -> dict | None:
    doc = await state_collection.find_one({"_id": {"$regex": "^reconcile:"}}, sort=[("_id", -1)])
    if doc:
        doc.pop("_id", None)
    return doc


def describe() -> dict:
    return {**status, "pacer": candle_pacer.describe(), "off_hours": off_hours()}


__all__ = ["backfill", "gapfill", "reconcile", "describe", "holes_today", "off_hours",
           "last_reconcile", "statistics"]
