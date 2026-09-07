"""Background loop for the Pre-Live Commodity Trading desk.

ONE loop, and deliberately no bar loop. The pattern desk's `commodity_bars_loop` already
polls Angel's candle endpoint for exactly these eight symbols, paced at one request every
three seconds because eight unpaced calls measured five HTTP 403s. A second poller for the
same data would not fetch anything new — it would only halve the pacing budget of the one
that works. This desk reads the same store.

The loop ticks whenever MCX is open, engine on or off, because `run_cycle` manages open
positions even while entries are switched off: a position taken before the switch was
flipped is still real exposure and still has a stop.
"""

import asyncio
import logging
import os
from datetime import datetime

from app.services.commodity_bars import IST, is_market_open

logger = logging.getLogger("commodity_prelive_scheduler")

ENABLED = os.getenv("COMMODITY_PRELIVE_SCHEDULER", "1").lower() not in ("0", "false", "")
# Slower than the pattern desk's 120s: this desk evaluates only the admitted handful per
# contract, and a whole-lot position on margin is not a thing you want re-scanned faster
# than the bars underneath it can change.
TICK_SECONDS = int(os.getenv("COMMODITY_PRELIVE_TICK_SECONDS", "180"))
IDLE_TICK_SECONDS = int(os.getenv("COMMODITY_PRELIVE_IDLE_TICK_SECONDS", "1800"))


async def commodity_prelive_loop() -> None:
    from app.services.commodity_prelive import get_state, run_cycle

    while True:
        try:
            if is_market_open(datetime.now(IST)):
                state = await get_state()
                r = await run_cycle()
                logger.info(
                    "[commodity_prelive] engine=%s — %d opened, %d managed, %d evaluated",
                    "ON" if state["enabled"] else "OFF",
                    r["opened"], r["managed"], r["evaluated"])
        except Exception:
            logger.exception("[commodity_prelive] cycle failed — will retry next tick")
        await asyncio.sleep(TICK_SECONDS if is_market_open() else IDLE_TICK_SECONDS)
