"""Scheduler for the All Time High desk.

Two jobs on different clocks:

  SCAN, every few minutes while the market is open. An all-time high is broken intraday, so
  a once-a-day check would miss the break and buy the next morning at whatever the gap left
  behind — which is a different strategy from the one specified.

  SEED, slowly and continuously. About 600 of the stocks above the market-cap floor have no
  stored all-time high yet, and each one costs several calls to Angel's rate-limited
  historical endpoint. Seeding is therefore spread over many runs rather than attempted in
  one pass, and the desk's coverage grows over the first few days rather than being
  complete on boot. That is stated in the UI rather than left to be discovered.
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.services import ath_trading

logger = logging.getLogger("ath_scheduler")

SCAN_SECONDS = int(os.getenv("ATH_SCAN_SECONDS", "180"))
SEED_SECONDS = int(os.getenv("ATH_SEED_SECONDS", "900"))
SEED_BATCH = int(os.getenv("ATH_SEED_BATCH", "60"))


async def ath_scan_loop() -> None:
    while True:
        try:
            if ath_trading.market_is_open():
                result = await ath_trading.run_cycle()
                if result.get("opened") or result.get("closed"):
                    logger.info("ath cycle: %s", result)
        except Exception:
            logger.exception("ath scan failed — retrying next cycle")
        await asyncio.sleep(SCAN_SECONDS)


async def ath_seed_loop() -> None:
    # Let the instrument map and fundamentals settle before walking history.
    await asyncio.sleep(420)
    while True:
        try:
            result = await ath_trading.seed_highs(limit=SEED_BATCH)
            if result.get("ok"):
                logger.info("ath all-time-high seed: %s", result)
            if result.get("complete"):
                # Nothing left to seed; check again far less often, since the only new work
                # is a stock newly crossing the market-cap floor.
                await asyncio.sleep(6 * 3600)
                continue
        except Exception:
            logger.exception("ath high seeding failed — retrying next cycle")
        await asyncio.sleep(SEED_SECONDS)
