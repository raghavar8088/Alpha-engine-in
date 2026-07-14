"""Background loop for the Intraday Strategy Lab — mirrors call_scheduler.py's
`while True` + try/except + asyncio.sleep pattern. Runs the scan+manage cycle
every TICK_SECONDS during market hours only (09:15-15:30 IST, weekdays)."""

import asyncio
import logging
import os
from datetime import datetime

from fastapi import HTTPException

from app.services.call_engine import IST

logger = logging.getLogger("intraday_lab_scheduler")

INTRADAY_LAB_ENABLED = os.getenv("INTRADAY_LAB_ENABLED", "1").lower() not in ("0", "false")
TICK_SECONDS = int(os.getenv("INTRADAY_LAB_TICK_SECONDS", "180"))  # every 3 minutes
MARKET_OPEN, MARKET_CLOSE = "09:15", "15:30"


def _in_market_hours(now: datetime) -> bool:
    return now.weekday() < 5 and MARKET_OPEN <= now.strftime("%H:%M") <= MARKET_CLOSE


async def _dhan_or_none():
    from app.api.deps import get_current_user
    from app.api.routes.broker import _get_dhan_client

    try:
        user = await get_current_user()
        return await _get_dhan_client(str(user["_id"]))
    except (HTTPException, Exception):
        return None


async def intraday_lab_loop() -> None:
    from app.services.intraday_lab_engine import run_cycle

    while True:
        try:
            now = datetime.now(IST)
            if _in_market_hours(now):
                dhan = await _dhan_or_none()
                result = await run_cycle(dhan)
                logger.info(
                    "intraday-lab cycle: %d opened, %d managed, %d symbols scanned",
                    result["opened"], result["managed"], result["scanned_symbols"],
                )
        except Exception:
            logger.exception("intraday-lab scheduler tick failed — will retry next tick")
        await asyncio.sleep(TICK_SECONDS)
