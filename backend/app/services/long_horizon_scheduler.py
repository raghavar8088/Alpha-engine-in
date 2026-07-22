"""Background loop for the Long-Horizon factor desk. Unlike the Intraday Lab's 3-minute
tick, this desk only ever needs ONE trading-day's worth of new information (it rebalances
on the close), so the loop wakes once a day, after the close is final, rather than
polling all session long.
"""

import asyncio
import logging
import os
from datetime import datetime

from app.services.call_engine import IST

logger = logging.getLogger("long_horizon_scheduler")

LONG_HORIZON_ENABLED = os.getenv("LONG_HORIZON_ENABLED", "1").lower() not in ("0", "false")
# 16:00 IST: after NSE's 15:30 close and after the day's bar has had time to be backfilled.
RUN_AFTER_HHMM = os.getenv("LONG_HORIZON_RUN_AFTER", "16:00")
CHECK_INTERVAL_SECONDS = 30 * 60  # only need to notice "has 16:00 IST passed today" once


def _due(now: datetime, last_run_date) -> bool:
    if now.weekday() >= 5:
        return False
    if now.strftime("%H:%M") < RUN_AFTER_HHMM:
        return False
    return last_run_date != now.date()


async def long_horizon_loop() -> None:
    from app.services.long_horizon_engine import rebalance

    last_run_date = None
    while True:
        try:
            now = datetime.now(IST)
            if _due(now, last_run_date):
                result = await rebalance()
                last_run_date = now.date()
                logger.info("long-horizon rebalance: basket=%d rebalanced=%d",
                           result.get("basket_size", 0), result.get("rebalanced", 0))
        except Exception:
            logger.exception("long-horizon scheduler tick failed — will retry next tick")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
