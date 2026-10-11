"""Background loops for the Gold Desk.

TWO VENUES, TWO CLOCKS
----------------------
MCX ticks while MCX is open and reads the shared commodity bar store; Delta ticks around the
clock and owns its own (incremental) bar feed.

WHAT EACH SWITCH GATES (C8, D12 in GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md)
-------------------------------------------------------------------------
* The desk's own per-venue switch and Main Control both gate ENTRIES.
* Neither ever stops the management of an OPEN position: its stop and target are watched
  whenever it exists. (Main Control used to stop the whole cycle, stranding stops.)
* A venue that is off and holds nothing does no work at all — no cycle, no equity row, no bar
  refresh. The Delta feed then only samples the order book every few minutes for the cost
  monitor (I5) and prunes its store; it used to rewrite ~17,000 candles every 2 minutes (C7).
"""

import asyncio
import logging
import os
from datetime import datetime

from app.services.commodity_bars import IST, is_market_open

logger = logging.getLogger("gold_scheduler")

ENABLED = os.getenv("GOLD_DESK_SCHEDULER", "1").lower() not in ("0", "false", "")

MCX_TICK_SECONDS = int(os.getenv("GOLD_MCX_TICK_SECONDS", "180"))
MCX_IDLE_TICK_SECONDS = int(os.getenv("GOLD_MCX_IDLE_TICK_SECONDS", "1800"))
DELTA_BARS_TICK_SECONDS = int(os.getenv("GOLD_DELTA_BARS_TICK_SECONDS", "120"))
DELTA_TICK_SECONDS = int(os.getenv("GOLD_DELTA_TICK_SECONDS", "180"))
LAB_TICK_SECONDS = int(os.getenv("GOLD_LAB_TICK_SECONDS", "120"))
_TASKS: set = set()


async def venue_activity(key: str) -> tuple[bool, bool, bool]:
    """(entries allowed, has open positions, may enter) for one venue."""
    from app.services.desk_switches import is_on
    from app.services.gold_desk import VENUES, get_state, open_count, specs_for

    v = VENUES[key]
    on = await is_on("gold_desk")
    has_open = await open_count(v) > 0
    st = await get_state(v)
    return on, has_open, bool(st["enabled"] and on and specs_for(v))


async def gold_mcx_loop() -> None:
    from app.services.gold_desk import VENUES, run_cycle

    while True:
        try:
            if is_market_open(datetime.now(IST)):
                on, has_open, may_enter = await venue_activity("mcx")
                if has_open or may_enter:
                    r = await run_cycle(VENUES["mcx"], entries_allowed=on)
                    if r["opened"] or r["managed"]:
                        logger.info("[gold mcx] %d opened, %d managed, %d evaluated",
                                    r["opened"], r["managed"], r["evaluated"])
        except Exception:
            logger.exception("[gold mcx] cycle failed — will retry next tick")
        await asyncio.sleep(MCX_TICK_SECONDS if is_market_open() else MCX_IDLE_TICK_SECONDS)


async def gold_delta_bars_loop() -> None:
    from app.services import gold_delta_feed
    from app.services.gold_desk import VENUES, timeframes_in_use

    while True:
        try:
            _on, has_open, may_enter = await venue_activity("delta")
            if has_open or may_enter:
                # 1m for walking exits, the strategies' own timeframes, 1d for H1's alpha vs XAUT.
                intervals = sorted({"1m", "1d", *timeframes_in_use(VENUES["delta"])})
                out = await gold_delta_feed.refresh_all(intervals)
                if out.get("failed_fetches"):
                    logger.warning("[gold delta bars] %d failed fetches: %s", out["failed_fetches"], out.get("errors"))
            else:
                await gold_delta_feed.idle_pass()
        except Exception:
            logger.exception("[gold delta bars] refresh failed — will retry next tick")
        await asyncio.sleep(DELTA_BARS_TICK_SECONDS)


async def gold_lab_loop() -> None:
    """The Gold Lab book (gold_lab): fund and mark what it holds; decide after each New York
    close and rebalance at the next open. Main Control gates its decisions, never its funding."""
    from app.services import gold_lab
    from app.services.desk_switches import is_on

    while True:
        try:
            r = await gold_lab.cycle(entries_allowed=await is_on("gold_desk"))
            if (r.get("decision") or {}).get("decided") or (r.get("execution") or {}).get("executed"):
                logger.info("[gold lab] decision %s | execution %s", (r.get("decision") or {}).get("bar_date"),
                            r.get("execution"))
        except Exception:
            logger.exception("[gold lab] cycle failed — will retry next tick")
        await asyncio.sleep(LAB_TICK_SECONDS)


async def gold_delta_loop() -> None:
    from app.services.gold_desk import VENUES, run_cycle

    # The lab book rides on this loop's start (main.py starts three gold tasks; the lab is the
    # fourth, started here so no shared startup file had to change). A strong reference keeps
    # the task from being garbage-collected mid-run.
    _TASKS.add(asyncio.create_task(gold_lab_loop()))
    while True:
        try:
            on, has_open, may_enter = await venue_activity("delta")
            if has_open or may_enter:
                r = await run_cycle(VENUES["delta"], entries_allowed=on)
                if r["opened"] or r["managed"]:
                    logger.info("[gold delta] %d opened, %d managed, %d evaluated",
                                r["opened"], r["managed"], r["evaluated"])
        except Exception:
            logger.exception("[gold delta] cycle failed — will retry next tick")
        await asyncio.sleep(DELTA_TICK_SECONDS)
