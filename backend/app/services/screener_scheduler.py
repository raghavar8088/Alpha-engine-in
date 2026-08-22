"""Scheduler for the Stock Screener.

TWO CADENCES, FOR TWO DIFFERENT KINDS OF NUMBER.

  Intraday (every ~5 min, 09:15-15:30 IST): the live half — breadth, today's momentum,
  NSE gainers. These change through the session and are what the page shows while the
  market is open. It is a snapshot recompute, not a persist: writing a row every five
  minutes for 500 stocks is exactly the churn that filled a 512MB Atlas tier once already.

  End of day (16:15 IST, once): the recorded half — all four horizons, sector rotation,
  the daily pattern scan, and the NSE capture, all persisted. 16:15 rather than 15:30 so
  the closing auction has settled and the numbers are final rather than a mid-auction
  snapshot that would be revised half an hour later.

  Weekly (after Friday's close): weekly bars are rebuilt and rescanned. A weekly bar is
  only complete once the week is, and scanning a partial week produces patterns that
  un-form themselves on Monday.

COST. The EOD scan is pure CPU over stored bars — no broker calls at all. The intraday
tick's only external call is the batched Angel quote sweep the snapshot already needs, so
this scheduler adds roughly ten broker requests per tick for the entire Nifty 500.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from app.services.screener import bhavcopy, engine, momentum, nse_breadth, paper, patterns
from app.services.screener.horizons import IST

logger = logging.getLogger("screener_scheduler")

ENABLED = os.getenv("SCREENER_ENABLED", "1").lower() not in ("0", "false", "")
TICK_SECONDS = int(os.getenv("SCREENER_TICK_SECONDS", "300"))
EOD_HHMM = os.getenv("SCREENER_EOD_HHMM", "16:15")
SESSION_OPEN = os.getenv("SCREENER_OPEN_HHMM", "09:15")
SESSION_CLOSE = os.getenv("SCREENER_CLOSE_HHMM", "15:30")

_state = {"last_eod": None, "last_weekly": None, "last_tick": None, "ticks": 0, "errors": 0}


def _hhmm(now: datetime | None = None) -> str:
    return (now or datetime.now(IST)).strftime("%H:%M")


def _is_weekday(now: datetime | None = None) -> bool:
    return (now or datetime.now(IST)).weekday() < 5


def _in_session(now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    return _is_weekday(now) and SESSION_OPEN <= _hhmm(now) <= SESSION_CLOSE


async def _intraday_tick() -> None:
    """Refresh the in-memory snapshot so the next page load is already warm, then run the
    paper desk. Deliberately does NOT persist the snapshot — see the module docstring.

    The paper desk runs on the SAME tick rather than its own loop, because it has to see
    the snapshot that produced its signals. A separate loop would open positions against
    prices from a different moment than the reasons attached to them, which would make the
    leaderboard measure the gap between two clocks as if it were edge."""
    await momentum.universe_snapshot(momentum.DEFAULT_INDEX, fresh=True)
    await nse_breadth.snapshot(persist=False)
    if paper.ENABLED:
        try:
            await paper.run_cycle(momentum.DEFAULT_INDEX)
        except Exception:
            logger.exception("screener paper cycle failed — desk skips this tick")


async def _eod() -> None:
    # Bhavcopy first: it publishes after the close and every delivery-based reason in the
    # EOD recompute wants today's row, not yesterday's.
    try:
        cap = await bhavcopy.capture()
        logger.info("screener bhavcopy capture: %s", cap)
    except Exception:
        logger.exception("bhavcopy capture failed — delivery columns read n/a for today")
    result = await engine.refresh_all(momentum.DEFAULT_INDEX)
    logger.info("screener EOD refresh: %s", result)
    if paper.ENABLED:
        try:
            await paper.run_cycle(momentum.DEFAULT_INDEX)
        except Exception:
            logger.exception("screener paper EOD cycle failed")


async def _weekly() -> None:
    """Rescan weekly bars now the week is complete."""
    res = await patterns.persist(momentum.DEFAULT_INDEX)
    logger.info("screener weekly pattern rescan: %s", res)


async def screener_loop() -> None:
    while True:
        try:
            now = datetime.now(IST)
            today = now.date().isoformat()
            hhmm = _hhmm(now)

            if _is_weekday(now) and hhmm >= EOD_HHMM and _state["last_eod"] != today:
                await _eod()
                _state["last_eod"] = today
                # Friday's EOD is also the week's close, so the weekly rescan rides on it
                # rather than needing its own wake-up.
                if now.weekday() == 4 and _state["last_weekly"] != today:
                    await _weekly()
                    _state["last_weekly"] = today

            elif _in_session(now):
                await _intraday_tick()
                _state["last_tick"] = now.isoformat()
                _state["ticks"] += 1

        except Exception:
            _state["errors"] += 1
            logger.exception("screener tick failed — will retry next cycle")

        await asyncio.sleep(TICK_SECONDS)


def state() -> dict:
    return {**_state, "enabled": ENABLED, "tick_seconds": TICK_SECONDS,
            "eod_hhmm": EOD_HHMM, "index": momentum.DEFAULT_INDEX}
