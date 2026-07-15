"""One-shot heartbeat watchdog - run every few minutes by Task Scheduler
(see setup_scheduler.ps1). Flags prelive_state as stale if the daemon hasn't
beaten in >10min during market hours, so the dashboard (frontend/app/prelive/
page.tsx) can surface it instead of silently showing an old status forever
(this is exactly how RC-1 went 45h unnoticed)."""

from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from db import _db  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
STALE_AFTER = timedelta(minutes=10)
MARKET_OPEN = 9 * 60 + 15
MARKET_CLOSE = 15 * 60 + 30

state_collection = _db["prelive_state"]


def market_hours_now() -> bool:
    now = datetime.now(IST)
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and MARKET_OPEN <= mins < MARKET_CLOSE


def main() -> None:
    if not market_hours_now():
        return  # nothing to watch outside market hours - daemon is expected to idle
    doc = state_collection.find_one({})
    now = datetime.now(timezone.utc)
    heartbeat = doc.get("heartbeat") if doc else None
    if heartbeat is None:
        age = None
        stale = True
    else:
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        age = (now - heartbeat).total_seconds()
        stale = age > STALE_AFTER.total_seconds()

    state_collection.update_one({}, {"$set": {
        "heartbeat_stale": stale,
        "heartbeat_age_seconds": age,
    }}, upsert=True)

    if stale:
        print(f"[watchdog] ALERT - prelive heartbeat stale during market hours "
              f"(age={age}s, threshold={STALE_AFTER.total_seconds()}s). "
              f"main.py is likely dead - check the supervisor.", flush=True)
    else:
        print(f"[watchdog] ok - heartbeat age {age:.0f}s", flush=True)


if __name__ == "__main__":
    main()
