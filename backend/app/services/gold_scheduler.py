"""Background loops for the Gold Desk.

TWO LOOPS, BECAUSE THE TWO VENUES KEEP DIFFERENT HOURS
------------------------------------------------------
The MCX leg ticks only while MCX is open (09:00-23:30 IST, weekdays) and reads the
commodity bar store that the pattern desk already fills — no second poller, because that
store exists precisely so one paced task owns Angel's candle endpoint and nothing else
competes with it for a rate limit that answered five HTTP 403s to eight unpaced calls.

The Delta leg ticks around the clock and owns its own bar poller, because nothing else in
this app fetches Delta candles. Perpetual futures have no session: a loop that slept when
MCX closed would miss the London and New York hours, which is most of where gold actually
moves.

BOTH LOOPS RUN WHETHER OR NOT THE DESK IS SWITCHED ON
-----------------------------------------------------
`run_cycle` manages open positions before it looks for new ones, and a position taken
before the switch was flipped is still exposure that still has a stop. The switch gates
ENTRIES. That is the same rule every other desk in this app follows, and it is the rule
the module this desk was ported from had no way to express, because it had no switch.
"""

import asyncio
import logging
import os
from datetime import datetime

from app.services.commodity_bars import IST, is_market_open

logger = logging.getLogger("gold_scheduler")

ENABLED = os.getenv("GOLD_DESK_SCHEDULER", "1").lower() not in ("0", "false", "")

# The MCX leg rides the same 180s cadence as the Pre-Live Commodity desk: the bars
# underneath it are 1-minute at the fastest, and a whole-lot position on margin is not
# something to re-scan faster than the data can change.
MCX_TICK_SECONDS = int(os.getenv("GOLD_MCX_TICK_SECONDS", "180"))
MCX_IDLE_TICK_SECONDS = int(os.getenv("GOLD_MCX_IDLE_TICK_SECONDS", "1800"))

# The Delta leg. Bars every 2 minutes, the desk every 3 — the same relationship the
# commodity desk has between its poller and its scan, so a cycle never evaluates a series
# it has just asked for and not yet received.
DELTA_BARS_TICK_SECONDS = int(os.getenv("GOLD_DELTA_BARS_TICK_SECONDS", "120"))
DELTA_TICK_SECONDS = int(os.getenv("GOLD_DELTA_TICK_SECONDS", "180"))


async def gold_mcx_loop() -> None:
    from app.services.desk_switches import is_on
    from app.services.gold_desk import VENUES, run_cycle

    while True:
        try:
            if is_market_open(datetime.now(IST)) and await is_on("gold_desk"):
                r = await run_cycle(VENUES["mcx"])
                if r["opened"] or r["managed"]:
                    logger.info("[gold mcx] %d opened, %d managed, %d evaluated",
                                r["opened"], r["managed"], r["evaluated"])
        except Exception:
            logger.exception("[gold mcx] cycle failed — will retry next tick")
        await asyncio.sleep(MCX_TICK_SECONDS if is_market_open() else MCX_IDLE_TICK_SECONDS)


async def gold_delta_bars_loop() -> None:
    from app.services.gold_delta_feed import refresh_all

    while True:
        try:
            out = await refresh_all()
            if out.get("failed_fetches"):
                logger.warning("[gold delta bars] %d failed fetches: %s",
                               out["failed_fetches"], out.get("errors"))
        except Exception:
            logger.exception("[gold delta bars] refresh failed — will retry next tick")
        await asyncio.sleep(DELTA_BARS_TICK_SECONDS)


async def gold_delta_loop() -> None:
    from app.services.desk_switches import is_on
    from app.services.gold_desk import VENUES, run_cycle

    while True:
        try:
            if await is_on("gold_desk"):
                r = await run_cycle(VENUES["delta"])
                if r["opened"] or r["managed"]:
                    logger.info("[gold delta] %d opened, %d managed, %d evaluated",
                                r["opened"], r["managed"], r["evaluated"])
        except Exception:
            logger.exception("[gold delta] cycle failed — will retry next tick")
        await asyncio.sleep(DELTA_TICK_SECONDS)
