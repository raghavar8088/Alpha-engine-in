"""The intraday data loop: universe before the open, gap-fill in the session, then flush,
reconcile and backfill after the close. The live stream runs as its own task.

Never raises out (each step is isolated), and does nothing on a day the exchange is shut
except continue an unfinished history backfill — a holiday is the cheapest time for it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime

from app.services import intraday_backfill, intraday_universe, market_calendar
from app.services.intraday_store import store

logger = logging.getLogger("intraday_data_scheduler")

ENABLED = os.getenv("INTRADAY_DATA_ENABLED", "1").lower() not in ("0", "false", "no")
TICK_S = 30
GAPFILL_EVERY_S = 300
BACKFILL_RETRY_S = 6 * 3600          # re-check history (new universe members) this often
UNIVERSE_FROM = "08:45"
RECONCILE_FROM = "15:50"


async def intraday_data_loop() -> None:
    last_gapfill = 0.0
    last_backfill = 0.0
    flushed_on = reconciled_on = preloaded_on = None
    while True:
        try:
            now = datetime.now(market_calendar.IST)
            hhmm = now.strftime("%H:%M")
            today = now.date().isoformat()
            trading = market_calendar.is_trading_day(now)

            if trading and hhmm >= UNIVERSE_FROM:
                await intraday_universe.today()                     # builds once a day
                if preloaded_on != today and hhmm <= "15:30":
                    syms = await intraday_universe.symbols()
                    n = await store.preload(syms + ["NIFTY"])
                    preloaded_on = today
                    logger.info("bar store preloaded: %d of %d symbols read from disk", n, len(syms) + 1)

            if trading and "09:30" <= hhmm <= "15:35" and time.monotonic() - last_gapfill > GAPFILL_EVERY_S:
                last_gapfill = time.monotonic()
                r = await intraday_backfill.gapfill(now)
                if r.get("requests"):
                    logger.info("gap-fill %s", r)

            if trading and hhmm >= "15:40" and flushed_on != today:
                r = await store.flush_dirty()
                flushed_on = today
                logger.info("end-of-day flush: %s", r)

            if trading and hhmm >= RECONCILE_FROM and reconciled_on != today:
                reconciled_on = today
                await intraday_backfill.reconcile(now.date())
                await store.flush_dirty()
                # Phase 3: test each incubating strategy's forward record against the
                # expectation frozen when it was registered.
                from app.services.intraday_v2_registry import evaluate_forward
                r = await evaluate_forward()
                if r.get("decided"):
                    logger.warning("incubation verdicts: %s", r["decided"])
                # Phase 4: the day's edge report — gross, slippage, fees, net per strategy,
                # and the forward record against the backtest's expectation.
                from app.services.intraday_ops import build_edge_report
                rep = await build_edge_report(now.date())
                logger.info("edge report %s: %s", now.date(), rep["desk"])

            if intraday_backfill.off_hours(now) and time.monotonic() - last_backfill > BACKFILL_RETRY_S \
                    and (not trading or hhmm >= RECONCILE_FROM and reconciled_on == today):
                last_backfill = time.monotonic()
                r = await intraday_backfill.backfill()
                logger.info("history backfill: %s", r)
                if r.get("incomplete"):
                    last_backfill -= BACKFILL_RETRY_S - 900       # retry the rest in 15 min
        except Exception:  # noqa: BLE001
            logger.exception("intraday data loop tick failed — retrying")
        await asyncio.sleep(TICK_S)
