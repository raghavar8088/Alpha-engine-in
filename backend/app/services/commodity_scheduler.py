"""Background loops for the Commodity Trading desk.

TWO loops, deliberately separate and on different clocks:

  bars   — pulls native Angel candles into the store. Paced internally (a full pass is
           8 symbols x 5 intervals = 40 throttled requests, ~60s), so it runs on its own
           slow tick and is the ONLY thing in the app that talks to the candle endpoint
           for commodities.
  desk   — scans patterns and manages open positions off whatever is already in the store.

Keeping them apart is the point: if Angel throttles the bar refresh, the desk still
manages its open book on live quotes (a different, far more permissive endpoint) instead
of being blocked behind a rate limiter.

MCX runs 09:00-23:30 IST, a much longer session than NSE, so these loops stay awake well
into the night and idle cheaply outside it.
"""

import asyncio
import logging
import os
from datetime import datetime

from app.services.commodity_bars import IST, is_market_open

logger = logging.getLogger("commodity_scheduler")

ENABLED = os.getenv("COMMODITY_ENABLED", "1").lower() not in ("0", "false", "")
BARS_TICK_SECONDS = int(os.getenv("COMMODITY_BARS_TICK_SECONDS", "300"))   # 5 min
DESK_TICK_SECONDS = int(os.getenv("COMMODITY_DESK_TICK_SECONDS", "120"))   # 2 min
# One refresh is still run outside market hours so the store is warm (and the page is not
# empty) before the session opens; after that the loops idle until MCX is live.
IDLE_TICK_SECONDS = int(os.getenv("COMMODITY_IDLE_TICK_SECONDS", "1800"))


async def commodity_bars_loop() -> None:
    from app.services.commodity_bars import refresh_all

    first = True
    while True:
        try:
            open_now = is_market_open(datetime.now(IST))
            if open_now or first:
                result = await refresh_all()
                first = False
                logger.info("[commodity] bar refresh: %s symbols in %ss, %s failed fetches",
                            result.get("symbols"), result.get("seconds"), result.get("failed_fetches"))
        except Exception:
            logger.exception("[commodity] bar refresh failed — will retry next tick")
        await asyncio.sleep(BARS_TICK_SECONDS if is_market_open() else IDLE_TICK_SECONDS)


async def commodity_desk_loop() -> None:
    from app.services.commodity_engine import run_cycle

    while True:
        try:
            if is_market_open(datetime.now(IST)):
                r = await run_cycle()
                logger.info("[commodity] desk cycle: %d opened, %d managed, %d evaluated",
                            r["opened"], r["managed"], r["evaluated"])
        except Exception:
            logger.exception("[commodity] desk cycle failed — will retry next tick")
        await asyncio.sleep(DESK_TICK_SECONDS if is_market_open() else IDLE_TICK_SECONDS)
