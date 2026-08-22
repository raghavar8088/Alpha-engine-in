"""Runs the paper broker while nobody is watching.

Ticks fast during the session and stops entirely outside it. That second half matters: an
engine that keeps ticking overnight burns Angel quota on a market that is not moving, and
worse, it can fill a resting order against a stale price hours after the close.

Settlement runs once after the close, moving unsold CNC buys into Holdings.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from app.services.paper_broker.core import MARKET_CLOSE, is_trading_day, market_is_open, now_ist
from app.services.paper_broker.engine import ENABLED, TICK_SECONDS, settle_delivery, tick

logger = logging.getLogger("paper_broker.scheduler")

# Keep ticking briefly after the close so the square-off and DAY-order expiry passes
# actually run — both are triggered by the clock passing a cutoff, so the engine has to be
# awake on the other side of it.
GRACE_MINUTES = 20


def _within_grace() -> bool:
    now = now_ist()
    if not is_trading_day(now):
        return False
    h, m = MARKET_CLOSE.split(":")
    close = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    return close <= now <= close + timedelta(minutes=GRACE_MINUTES)


async def paper_broker_loop() -> None:
    settled_on = None
    while True:
        try:
            if market_is_open() or _within_grace():
                result = await tick()
                if any(result.get(k) for k in ("filled", "armed", "expired", "squared_off")):
                    logger.info("paper broker tick: %s", result)

                today = now_ist().date().isoformat()
                if _within_grace() and settled_on != today:
                    logger.info("paper broker settlement: %s", await settle_delivery())
                    settled_on = today
        except Exception:
            logger.exception("paper broker tick failed — retrying next cycle")
        await asyncio.sleep(TICK_SECONDS)


def enabled() -> bool:
    return ENABLED
