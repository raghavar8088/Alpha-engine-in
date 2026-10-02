"""The NSE trading calendar: is the cash/F&O market actually open today?

WHY THIS MODULE EXISTS
Every NSE desk in this app decided "is the market open" with `weekday() < 5` and a clock
window. On 2026-10-02 — Mahatma Gandhi Jayanti, an exchange holiday — that test said yes,
and the desks traded all morning: 152 tournament positions, about 120 pattern-desk
positions and 43 Live Intraday positions were opened at the previous session's prices.
A quote endpoint does not refuse on a holiday; it hands back the last traded price, so
nothing downstream could tell. Those fills are not prices anyone could have dealt at, and
every one of them went into the record the promotion gates read.

TWO SOURCES, ONE ANSWER
1. The exchange's published list (NSE circular for calendar year 2026, cross-checked
   against two broker copies of it on 2026-10-02). Weekday closures only — a weekend is
   already closed. Overridable without a deploy:
     NSE_EXTRA_HOLIDAYS   ISO dates to ADD (closures announced at short notice — the
                          2026-01-15 Maharashtra civic-election closure was one)
     NSE_NOT_HOLIDAYS     ISO dates to REMOVE from the list (a closure withdrawn)
     NSE_SPECIAL_SESSIONS ISO dates of a weekend day the exchange opens (a Budget-day
                          Saturday session)
   The list has to be extended each December; `describe()` reports when it runs out and
   the log warns once, so an expired list is visible instead of quietly wrong.

2. A self-check that can only ADD a closure, never remove one. After 09:20 on a day the
   list calls open, it asks Angel for today's 5-minute candles of two of the most liquid
   stocks. An open session has them; a closed one has none. Both empty on two probes at
   least five minutes apart means the market is shut — a closure the list did not know
   about — and every gate below then says closed for the rest of the day. It keeps
   re-probing every 15 minutes, so one bad answer from the candle endpoint cannot keep a
   desk shut for a whole session: the first candle seen reopens it. A probe that errors
   concludes nothing.

Muhurat trading (an evening session on Diwali) is deliberately NOT treated as a session:
it is an hour of symbolic, thin trading the strategies were never built for.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger("market_calendar")

IST = timezone(timedelta(hours=5, minutes=30))

# NSE equity + equity-derivatives trading holidays falling on a weekday.
NSE_HOLIDAYS: dict[str, str] = {
    # 2026 — NSE circular (December 2025), plus the civic-election closure added in January
    "2026-01-15": "Municipal Corporation Election - Maharashtra",
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}
LIST_COVERS_THROUGH = date(2026, 12, 31)


def _dates(env: str) -> set[str]:
    return {d.strip() for d in os.getenv(env, "").split(",") if d.strip()}


_EXTRA = _dates("NSE_EXTRA_HOLIDAYS")
_NOT = _dates("NSE_NOT_HOLIDAYS")
_SPECIAL = _dates("NSE_SPECIAL_SESSIONS")

PROBE_ENABLED = os.getenv("NSE_SESSION_PROBE", "1").lower() not in ("0", "false", "no")
PROBE_FROM_HHMM = os.getenv("NSE_SESSION_PROBE_FROM", "09:20")
PROBE_UNTIL_HHMM = "15:30"
PROBE_CONFIRM_GAP_S = 5 * 60          # two empty probes at least this far apart
PROBE_EVERY_S = 15 * 60               # re-check cadence while undecided or shut
# Two of the most liquid NSE stocks; their NSE-EQ Angel tokens, used only if the
# instrument master lookup fails.
PROBE_SYMBOLS = {"RELIANCE": "2885", "HDFCBANK": "1333"}

_warned_past_list = False

# Probe state, per IST date: {"date", "open": bool|None, "empty_at": monotonic|None,
# "checked_at": monotonic, "detail": str}
_probe: dict = {"date": None, "open": None, "empty_at": None, "checked_at": 0.0, "detail": "not run"}
_probe_lock = asyncio.Lock()


def _as_date(when: date | datetime | None) -> date:
    if when is None:
        return datetime.now(IST).date()
    if isinstance(when, datetime):
        return (when.astimezone(IST) if when.tzinfo else when).date()
    return when


def holiday_name(when: date | datetime | None = None) -> str | None:
    """The published reason the exchange is shut on this weekday, or None."""
    iso = _as_date(when).isoformat()
    if iso in _NOT:
        return None
    if iso in _EXTRA:
        return "exchange closure (NSE_EXTRA_HOLIDAYS)"
    return NSE_HOLIDAYS.get(iso)


def is_listed_trading_day(when: date | datetime | None = None) -> bool:
    """What the published calendar alone says — no probe."""
    global _warned_past_list
    d = _as_date(when)
    if d.isoformat() in _SPECIAL:
        return True
    if d.weekday() >= 5:
        return False
    if d > LIST_COVERS_THROUGH and not _warned_past_list:
        _warned_past_list = True
        logger.warning("NSE holiday list ends %s — %s is past it, so only weekends are known "
                       "closed. Add the new year's circular to market_calendar.NSE_HOLIDAYS.",
                       LIST_COVERS_THROUGH, d)
    return holiday_name(d) is None


def probe_says_closed(when: date | datetime | None = None) -> bool:
    d = _as_date(when).isoformat()
    return _probe["date"] == d and _probe["open"] is False


def is_trading_day(when: date | datetime | None = None) -> bool:
    """The gate every NSE desk uses: the published calendar, minus any closure the live
    self-check has detected for today. Synchronous — it reads the last probe result."""
    return is_listed_trading_day(when) and not probe_says_closed(when)


def in_session(now: datetime | None = None, open_hhmm: str = "09:15",
               close_hhmm: str = "15:30") -> bool:
    now = (now or datetime.now(IST)).astimezone(IST)
    return is_trading_day(now) and open_hhmm <= now.strftime("%H:%M") <= close_hhmm


def next_trading_day(when: date | datetime | None = None) -> date:
    d = _as_date(when) + timedelta(days=1)
    while not is_listed_trading_day(d):
        d += timedelta(days=1)
    return d


def previous_trading_day(when: date | datetime | None = None) -> date:
    d = _as_date(when) - timedelta(days=1)
    while not is_listed_trading_day(d):
        d -= timedelta(days=1)
    return d


# ── the live self-check ──────────────────────────────────────────────────────────


async def _probe_tokens() -> dict[str, str]:
    try:
        from app.core.db import instruments_collection
        out = {}
        async for doc in instruments_collection.find(
                {"symbol": {"$in": list(PROBE_SYMBOLS)}, "asset_class": "EQUITY",
                 "angel_token": {"$ne": None}}, {"symbol": 1, "angel_token": 1}):
            out[doc["symbol"]] = str(doc["angel_token"])
        return out or dict(PROBE_SYMBOLS)
    except Exception:  # noqa: BLE001
        return dict(PROBE_SYMBOLS)


async def _candles_today(token: str, now: datetime) -> int | None:
    """How many 5-minute candles Angel has for today; None when the call failed."""
    from app.services.angel_client import AngelAPIError, angel_client

    try:
        rows = await angel_client.candles(
            "NSE", token, "5", now.strftime("%Y-%m-%d 09:15"), now.strftime("%Y-%m-%d %H:%M"))
    except (AngelAPIError, Exception):  # noqa: BLE001 - a failed probe concludes nothing
        return None
    today = now.date().isoformat()
    return sum(1 for r in rows if str(r[0])[:10] == today)


async def probe_if_due(now: datetime | None = None) -> dict:
    """Run the self-check when it is due. Cheap and safe to call every tick; never raises."""
    now = (now or datetime.now(IST)).astimezone(IST)
    today = now.date().isoformat()
    hhmm = now.strftime("%H:%M")
    if not PROBE_ENABLED or not is_listed_trading_day(now):
        return dict(_probe)
    if not (PROBE_FROM_HHMM <= hhmm <= PROBE_UNTIL_HHMM):
        return dict(_probe)
    async with _probe_lock:
        if _probe["date"] != today:
            _probe.update({"date": today, "open": None, "empty_at": None, "checked_at": 0.0,
                           "detail": "not run"})
        if _probe["open"] is True:
            return dict(_probe)                      # confirmed open: nothing more to learn
        mono = time.monotonic()
        wait = PROBE_EVERY_S if _probe["open"] is False else (
            PROBE_CONFIRM_GAP_S if _probe["empty_at"] else 0)
        if _probe["checked_at"] and mono - _probe["checked_at"] < wait:
            return dict(_probe)
        _probe["checked_at"] = mono
        counts = {}
        for sym, tok in (await _probe_tokens()).items():
            counts[sym] = await _candles_today(tok, now)
            await asyncio.sleep(0.5)                 # stay well inside Angel's 3 req/s
        seen = [c for c in counts.values() if c is not None]
        if any(c > 0 for c in seen):
            if _probe["open"] is False:
                logger.warning("NSE self-check: candles have appeared (%s) — the market is OPEN "
                               "after all; desks resume.", counts)
            _probe.update({"open": True, "empty_at": None, "detail": f"candles today {counts}"})
        elif len(seen) == len(counts) and seen:      # every probe answered, all empty
            if _probe["empty_at"] is None:
                _probe.update({"empty_at": mono, "detail": f"no candles yet {counts}; re-checking"})
            elif mono - _probe["empty_at"] >= PROBE_CONFIRM_GAP_S and _probe["open"] is not False:
                _probe.update({"open": False, "detail": f"no candles today at {hhmm} {counts}"})
                logger.error("NSE self-check: no candles for %s by %s IST on a day the holiday "
                             "list calls open — treating the market as CLOSED today. Add %s to "
                             "NSE_EXTRA_HOLIDAYS if this is a declared closure.",
                             list(counts), hhmm, today)
                await _record_alarm(today, hhmm, counts)
        else:
            _probe["detail"] = f"probe failed {counts}; no conclusion"
        return dict(_probe)


async def _record_alarm(today: str, hhmm: str, counts: dict) -> None:
    try:
        from app.core.db import db
        await db["system_alarms"].update_one(
            {"_id": f"market_closed_unlisted:{today}:nse"},
            {"$set": {"kind": "market_closed_unlisted", "session": today,
                      "detail": {"desk": "nse", "at": hhmm, "candles": counts},
                      "at": datetime.now(timezone.utc), "resolved": False}},
            upsert=True)
    except Exception:  # noqa: BLE001
        logger.exception("could not record the market-closed alarm")


def describe(now: datetime | None = None) -> dict:
    now = (now or datetime.now(IST)).astimezone(IST)
    d = now.date()
    return {
        "today": d.isoformat(),
        "trading_day": is_trading_day(d),
        "holiday": holiday_name(d),
        "listed_trading_day": is_listed_trading_day(d),
        "probe": {k: _probe[k] for k in ("date", "open", "detail")},
        "next_trading_day": next_trading_day(d).isoformat(),
        "list_covers_through": LIST_COVERS_THROUGH.isoformat(),
        "list_expired": d > LIST_COVERS_THROUGH,
        "overrides": {"extra": sorted(_EXTRA), "removed": sorted(_NOT),
                      "special_sessions": sorted(_SPECIAL)},
    }
