"""Indian Index Intraday — the loops: the live feed, the minute engine and the after-close jobs.

  feed_loop    the module's own Angel connection (09:05-15:36 on NSE trading days) — only
               while the module is ON in Main Control or a paper position is open
  engine_loop  09:00 warm-up (heal missing history days, load ~280 sessions per deployed
               index); then one tick five seconds after every completed minute, 09:16-15:20.
               Main Control ("index_intraday") gates NEW ENTRIES only — exits and the 15:12
               square-off always run
  close_jobs   15:40, module ON: append the session's 1-minute candles to the history store,
               heal any missing day, write the day's report (OFF: the report only — no broker call)
  heal_once    three minutes after startup, module ON: fill missing days of the last 30
Started from main.py's startup hook; every task is held by a strong reference.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("index_intraday.scheduler")

IST = timezone(timedelta(hours=5, minutes=30))
ENABLED = os.getenv("INDEX_INTRADAY_SCHEDULER", "1").lower() not in ("0", "false", "")
_TASKS: set = set()


async def engine_loop() -> None:
    from app.services import market_calendar
    from app.services.desk_switches import is_on

    from .paper import engine
    warmed: str | None = None
    while True:
        now = datetime.now(IST)
        nxt = (now.replace(second=0, microsecond=0) + timedelta(minutes=1, seconds=5))
        await asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
        now = datetime.now(IST)
        hhmm = now.strftime("%H:%M")
        if not market_calendar.is_trading_day(now):
            continue
        if "09:00" <= hhmm < "09:16" and warmed != now.date().isoformat():
            try:                                   # load the ~280-session history before the first tick
                logger.info("[index intraday] history warmed for %s", await engine.warm(now.date()))
                warmed = now.date().isoformat()
            except Exception:  # noqa: BLE001
                logger.exception("[index intraday] history warm-up failed (the first tick will load it)")
        if not "09:16" <= hhmm <= "15:20":
            continue
        try:
            r = await engine.tick(now, entries_allowed=await is_on("index_intraday"))
            if r.get("opened") or r.get("closed"):
                logger.info("[index intraday] %s opened %d closed %d", hhmm, r["opened"], r["closed"])
        except Exception:  # noqa: BLE001 - one bad minute must not stop the engine
            logger.exception("[index intraday] tick failed at %s", hhmm)


async def close_jobs() -> None:
    from app.services import market_calendar
    from app.services.desk_switches import is_on

    from .feed import feed
    from .report import write_daily
    done: str | None = None
    while True:
        now = datetime.now(IST)
        day = now.date().isoformat()
        if market_calendar.is_trading_day(now) and now.strftime("%H:%M") >= "15:40" and done != day:
            try:
                appended: dict = {}
                if await is_on("index_intraday"):
                    appended = await feed.append_today(now.date())
                    appended["healed"] = await feed.heal()
                await write_daily(now.date(), appended)
                done = day
                logger.info("[index intraday] close jobs done for %s: %s", day, appended or "module OFF — report only")
            except Exception:  # noqa: BLE001
                logger.exception("[index intraday] close jobs failed")
        await asyncio.sleep(120)


async def heal_once(delay_s: float = 180.0) -> None:
    """After a (re)start: fill missing history days, so the next session's engine has yesterday."""
    from app.services.desk_switches import is_on

    from .feed import feed
    await asyncio.sleep(delay_s)
    try:
        if await is_on("index_intraday"):
            await feed.heal()
    except Exception:  # noqa: BLE001
        logger.exception("[index intraday] startup history heal failed")


async def feed_wanted() -> bool:
    """The stream runs while the module is ON, or while any paper position is open (exits need prices)."""
    from app.services.desk_switches import is_on

    from .paper import POS
    return await is_on("index_intraday") or bool(await POS.count_documents({"status": "OPEN"}, limit=1))


def start() -> None:
    if not ENABLED:
        logger.info("Index intraday loops disabled (INDEX_INTRADAY_SCHEDULER=0)")
        return
    from .feed import feed
    feed.wanted = feed_wanted
    for coro in (feed.run(), engine_loop(), close_jobs(), heal_once()):
        _TASKS.add(asyncio.create_task(coro))
    logger.info("Indian Index Intraday: feed, minute engine and close jobs started (paper only)")
