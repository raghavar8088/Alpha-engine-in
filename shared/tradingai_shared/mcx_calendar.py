"""MCX trading calendar — sessions, holidays and the US-daylight-saving close.

WHY THIS EXISTS
The commodity desks decided "is MCX open" with `weekday() < 5` and a fixed 09:00-23:30
window. On 2026-10-02 (Mahatma Gandhi Jayanti, MCX shut for BOTH sessions) that test said
open, and the pattern desk made 81 round trips on a quote that never moved: every fill was
the previous session's last price plus or minus the desk's own slippage. A quote endpoint
does not refuse on a holiday — it hands back the last traded price.

MCX IS NOT NSE
MCX trades two sessions (non-agricultural commodities):
  morning  09:00 - 17:00 IST
  evening  17:00 - 23:30 IST while the US is on daylight saving time,
           17:00 - 23:55 IST while it is not (the close follows NYMEX/COMEX)
and most Indian holidays close only the MORNING session — the evening opens at 17:00 as
usual because the international markets it tracks are open. A few close both, and
1 January closes only the evening. So "holiday" is per session, not per day.

The 2026 list below is MCX's circular as republished by three brokers (5paisa, Kotak Neo,
Jainam), checked 2026-10-03; all three agree session by session. It must be extended each
December — `LIST_COVERS_THROUGH` says until when it is right, and `describe()` reports it.

Overrides without a deploy (comma-separated ISO dates):
  MCX_EXTRA_HOLIDAYS          both sessions shut (short-notice closure)
  MCX_EXTRA_MORNING_CLOSED    morning only shut
  MCX_NOT_HOLIDAYS            a listed closure that was withdrawn
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

MORNING_OPEN = time(9, 0)
EVENING_OPEN = time(17, 0)
CLOSE_US_DST = time(23, 30)       # US on daylight saving (mid-March .. early November)
CLOSE_US_STANDARD = time(23, 55)  # US on standard time

# date -> (name, morning_closed, evening_closed)
MCX_HOLIDAYS: dict[str, tuple[str, bool, bool]] = {
    "2026-01-01": ("New Year Day", False, True),
    "2026-01-26": ("Republic Day", True, True),
    "2026-03-03": ("Holi", True, False),
    "2026-03-26": ("Shri Ram Navami", True, False),
    "2026-03-31": ("Shri Mahavir Jayanti", True, False),
    "2026-04-03": ("Good Friday", True, True),
    "2026-04-14": ("Dr. Baba Saheb Ambedkar Jayanti", True, False),
    "2026-05-01": ("Maharashtra Day", True, False),
    "2026-05-28": ("Bakri Id", True, False),
    "2026-06-26": ("Muharram", True, False),
    "2026-09-14": ("Ganesh Chaturthi", True, False),
    "2026-10-02": ("Mahatma Gandhi Jayanti", True, True),
    "2026-10-20": ("Dussehra", True, False),
    "2026-11-10": ("Diwali Balipratipada", True, False),
    "2026-11-24": ("Guru Nanak Jayanti", True, False),
    "2026-12-25": ("Christmas", True, True),
}
LIST_COVERS_THROUGH = date(2026, 12, 31)


def _dates(env: str) -> set[str]:
    return {d.strip() for d in os.getenv(env, "").split(",") if d.strip()}


EXTRA_FULL = _dates("MCX_EXTRA_HOLIDAYS")
EXTRA_MORNING = _dates("MCX_EXTRA_MORNING_CLOSED")
REMOVED = _dates("MCX_NOT_HOLIDAYS")


def as_date(when: date | datetime | None) -> date:
    if when is None:
        return datetime.now(IST).date()
    if isinstance(when, datetime):
        return (when.astimezone(IST) if when.tzinfo else when).date()
    return when


def _nth_sunday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    first = d + timedelta(days=(6 - d.weekday()) % 7)
    return first + timedelta(weeks=n - 1)


def us_daylight_saving(d: date) -> bool:
    """US DST runs from the second Sunday of March to the first Sunday of November.
    MCX changes its close on the next Indian trading day (2026: Mon 9 March, Mon 2 Nov),
    which is what comparing the IST date against the Sunday gives."""
    return _nth_sunday(d.year, 3, 2) < d <= _nth_sunday(d.year, 11, 1)


def session_close(d: date) -> time:
    return CLOSE_US_DST if us_daylight_saving(d) else CLOSE_US_STANDARD


def holiday(d: date | datetime | None = None) -> dict | None:
    """{"name", "morning_closed", "evening_closed"} for a listed weekday closure, else None."""
    iso = as_date(d).isoformat()
    if iso in REMOVED:
        return None
    if iso in EXTRA_FULL:
        return {"name": "exchange closure (MCX_EXTRA_HOLIDAYS)", "morning_closed": True, "evening_closed": True}
    if iso in EXTRA_MORNING:
        return {"name": "morning closure (MCX_EXTRA_MORNING_CLOSED)", "morning_closed": True, "evening_closed": False}
    row = MCX_HOLIDAYS.get(iso)
    if row is None:
        return None
    return {"name": row[0], "morning_closed": row[1], "evening_closed": row[2]}


def sessions(d: date | datetime | None = None) -> list[tuple[datetime, datetime, str]]:
    """The open intervals of one IST date: [(start, end, "morning"|"evening"), ...]."""
    day = as_date(d)
    if day.weekday() >= 5:
        return []
    h = holiday(day) or {}
    out = []
    if not h.get("morning_closed"):
        out.append((datetime.combine(day, MORNING_OPEN, IST), datetime.combine(day, EVENING_OPEN, IST), "morning"))
    if not h.get("evening_closed"):
        out.append((datetime.combine(day, EVENING_OPEN, IST), datetime.combine(day, session_close(day), IST), "evening"))
    return out


def session_at(now: datetime | None = None) -> str | None:
    """"morning" | "evening" while MCX is trading, else None."""
    now = (now or datetime.now(IST)).astimezone(IST)
    for start, end, name in sessions(now.date()):
        if start <= now < end:
            return name
    return None


def is_open(now: datetime | None = None) -> bool:
    return session_at(now) is not None


def is_trading_day(d: date | datetime | None = None) -> bool:
    """True when at least one session trades on this date."""
    return bool(sessions(d))


def is_full_trading_day(d: date | datetime | None = None) -> bool:
    return len(sessions(d)) == 2


def trading_days_between(start: date, end: date) -> int:
    """Trading days in (start, end] — days with any session. 0 when end <= start."""
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return n


def trading_days_to(expiry: date | str, today: date | None = None) -> int:
    """Trading days left INCLUDING the expiry day itself, counted from `today` (inclusive
    when today trades). Expiry day = 1, the trading day before it = 2, expired = 0."""
    exp = date.fromisoformat(expiry) if isinstance(expiry, str) else expiry
    d = today or as_date(None)
    n = 0
    while d <= exp:
        if is_trading_day(d):
            n += 1
        d += timedelta(days=1)
    return n


def trading_minutes_between(a: datetime, b: datetime) -> float:
    """Minutes MCX was actually trading between two instants (holidays, nights and
    weekends excluded)."""
    a, b = a.astimezone(IST), b.astimezone(IST)
    if b <= a:
        return 0.0
    total, d = 0.0, a.date()
    while d <= b.date():
        for start, end, _ in sessions(d):
            lo, hi = max(start, a), min(end, b)
            if hi > lo:
                total += (hi - lo).total_seconds() / 60.0
        d += timedelta(days=1)
    return total


def bars_elapsed(since: datetime, minutes: int, now: datetime | None = None) -> int:
    """Bars of a `minutes`-long timeframe that have elapsed in TRADING time since `since`.
    Daily bars count trading days. Wall-clock time counted nights and weekends as bars, so
    a 4h position "aged" six bars over a Saturday and Sunday without one trade."""
    now = now or datetime.now(IST)
    if minutes >= 1440:
        return trading_days_between(since.astimezone(IST).date(), now.astimezone(IST).date())
    return int(trading_minutes_between(since, now) // max(minutes, 1))


def last_session_end(before: datetime | None = None) -> datetime | None:
    """End of the most recent session that has CLOSED by `before` (searches 15 days)."""
    now = (before or datetime.now(IST)).astimezone(IST)
    for back in range(0, 15):
        d = now.date() - timedelta(days=back)
        for start, end, _ in reversed(sessions(d)):
            if end <= now:
                return end
    return None


def current_session_start(now: datetime | None = None) -> datetime | None:
    now = (now or datetime.now(IST)).astimezone(IST)
    for start, end, _ in sessions(now.date()):
        if start <= now < end:
            return start
    return None


def describe(now: datetime | None = None) -> dict:
    now = (now or datetime.now(IST)).astimezone(IST)
    today = now.date()
    h = holiday(today)
    upcoming = []
    for iso, (name, mc, ec) in sorted(MCX_HOLIDAYS.items()):
        if iso >= today.isoformat():
            upcoming.append({"date": iso, "name": name, "morning_closed": mc, "evening_closed": ec})
    return {
        "now_ist": now.isoformat(), "session": session_at(now), "open": is_open(now),
        "today_holiday": h, "today_sessions": [(s.isoformat(), e.isoformat(), n) for s, e, n in sessions(today)],
        "close_today": session_close(today).strftime("%H:%M"),
        "us_daylight_saving": us_daylight_saving(today),
        "list_covers_through": LIST_COVERS_THROUGH.isoformat(),
        "list_expired": today > LIST_COVERS_THROUGH,
        "upcoming_holidays": upcoming[:6],
        "overrides": {"extra_full": sorted(EXTRA_FULL), "extra_morning": sorted(EXTRA_MORNING),
                      "removed": sorted(REMOVED)},
    }
