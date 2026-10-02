"""NSE trading holidays — the single list every service reads.

Every service here decided "is the market open" with `weekday() < 5`. On 2026-10-02 (Gandhi
Jayanti, exchange shut) the backend desks AND the prelive NIFTY option desks (separate
containers) traded all morning at the previous session's prices. The backend got a calendar
first (app.services.market_calendar, which also runs a live closure probe); this module is
the list itself, shared so the prelive daemons and anything else use the same days.

Weekday closures only (a weekend is already closed). Sources: the NSE circular for 2026 plus
the January civic-election closure; cross-checked against two broker copies on 2026-10-02.
Overrides without a deploy (comma-separated ISO dates):
  NSE_EXTRA_HOLIDAYS    closures announced at short notice
  NSE_NOT_HOLIDAYS      a listed closure that was withdrawn
  NSE_SPECIAL_SESSIONS  a weekend day the exchange opens
The list must be extended each December — LIST_COVERS_THROUGH says until when it is right.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

NSE_HOLIDAYS: dict[str, str] = {
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


EXTRA = _dates("NSE_EXTRA_HOLIDAYS")
REMOVED = _dates("NSE_NOT_HOLIDAYS")
SPECIAL = _dates("NSE_SPECIAL_SESSIONS")


def as_date(when: date | datetime | None) -> date:
    if when is None:
        return datetime.now(IST).date()
    if isinstance(when, datetime):
        return (when.astimezone(IST) if when.tzinfo else when).date()
    return when


def holiday_name(when: date | datetime | None = None) -> str | None:
    iso = as_date(when).isoformat()
    if iso in REMOVED:
        return None
    if iso in EXTRA:
        return "exchange closure (NSE_EXTRA_HOLIDAYS)"
    return NSE_HOLIDAYS.get(iso)


def is_listed_trading_day(when: date | datetime | None = None) -> bool:
    d = as_date(when)
    if d.isoformat() in SPECIAL:
        return True
    if d.weekday() >= 5:
        return False
    return holiday_name(d) is None


def next_trading_day(when: date | datetime | None = None) -> date:
    d = as_date(when) + timedelta(days=1)
    while not is_listed_trading_day(d):
        d += timedelta(days=1)
    return d


def previous_trading_day(when: date | datetime | None = None) -> date:
    d = as_date(when) - timedelta(days=1)
    while not is_listed_trading_day(d):
        d -= timedelta(days=1)
    return d


def closed_reason(when: datetime | None = None) -> str | None:
    """Why the exchange is shut on this day ('weekend', a holiday name), or None if open."""
    d = as_date(when)
    if d.isoformat() in SPECIAL:
        return None
    if d.weekday() >= 5:
        return "weekend"
    return holiday_name(d)
