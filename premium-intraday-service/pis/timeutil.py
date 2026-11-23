"""IST clock and the NSE five-minute session grid (bars stamped with their START, as the app's bar store does)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
BAR_S = 300
OPEN_MIN = 9 * 60 + 15
CLOSE_MIN = 15 * 60 + 30
BARS_PER_DAY = (CLOSE_MIN - OPEN_MIN) // 5        # 75


def day_key(epoch: int) -> int:
    return (int(epoch) + 19800) // 86400


def day_of(epoch: int) -> date:
    return datetime.fromtimestamp(int(epoch), IST).date()


def day_start(d: date) -> int:
    """Epoch of 00:00 IST on d."""
    return int(datetime(d.year, d.month, d.day, tzinfo=IST).timestamp())


def at(d: date, minute_of_day: int) -> int:
    return day_start(d) + minute_of_day * 60


def open_epoch(d: date) -> int:
    return at(d, OPEN_MIN)


def bar_index(epoch: int) -> int:
    """Index of the five-minute bar that STARTS at epoch (0 = 09:15). Integer arithmetic (IST has no daylight
    saving): the same value as (epoch - 09:15 of its day) // 300, without a datetime per bar."""
    return ((int(epoch) + 19800) % 86400 - OPEN_MIN * 60) // BAR_S


def bar_start(d: date, k: int) -> int:
    return open_epoch(d) + k * BAR_S


def bar_close(d: date, k: int) -> int:
    """When bar k is complete (its end)."""
    return open_epoch(d) + (k + 1) * BAR_S


def minute(epoch: int) -> int:
    dt = datetime.fromtimestamp(int(epoch), IST)
    return dt.hour * 60 + dt.minute


def hhmm(epoch: int) -> str:
    return datetime.fromtimestamp(int(epoch), IST).strftime("%H:%M")


def hhmm_of_min(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def bars_closed_by(minute_of_day: int) -> int:
    """How many bars of the session have closed at minute_of_day (09:30 -> 3)."""
    return max(0, min(BARS_PER_DAY, (minute_of_day - OPEN_MIN) // 5))


def now_ist() -> datetime:
    return datetime.now(IST)
