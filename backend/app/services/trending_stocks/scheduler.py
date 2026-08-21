"""Background loops for the Trending Stocks desk.

THREE LOOPS, THREE DIFFERENT CLOCKS, ON PURPOSE
------------------------------------------------
*Session loop* — tops the basket's bars up and runs one scan+manage cycle every few
minutes while NSE is open. It tops bars up FIRST: a scan against a stale last bar would
evaluate patterns on a chart that is minutes behind the price it is about to fill at.

*Nightly loop* — after the close, when the day's bar is final: full bar refresh, then the
backtest sweep, then walk-forward and Monte Carlo on the survivors, then re-grade. This is
the loop that decides which strategies are allowed to trade tomorrow, and it runs once a
day because one trading day is exactly how much new information exists.

*News loop* — pulls the RSS feeds every 30 minutes. `research-service` has always had an
ingest function and an endpoint, but nothing in this app ever scheduled it, so the news
store only ever filled when somebody clicked a button. The evidence layer's news pillar is
only as fresh as this loop makes it.

Every loop is gated by an env flag and every tick is wrapped: a failure logs and waits for
the next tick rather than killing the task, because a dead scheduler task looks exactly
like a desk with nothing to do.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from anyio import to_thread

from .bars import IST, is_market_open

logger = logging.getLogger("trending_stocks.scheduler")

ENABLED = os.getenv("TRENDING_STOCKS_ENABLED", "1").lower() not in ("0", "false", "")
TICK_SECONDS = int(os.getenv("TS_TICK_SECONDS", "180"))
# 16:00 IST: after the 15:30 close and after the day's bar has settled.
EOD_HHMM = os.getenv("TS_EOD_RUN_AFTER", "16:00")
EOD_CHECK_SECONDS = int(os.getenv("TS_EOD_CHECK_SECONDS", str(20 * 60)))
NEWS_ENABLED = os.getenv("TS_NEWS_INGEST_ENABLED", "1").lower() not in ("0", "false", "")
NEWS_INTERVAL_SECONDS = int(os.getenv("TS_NEWS_INTERVAL_SECONDS", str(30 * 60)))
# Whether the nightly pass also runs walk-forward + Monte Carlo. On by default; turn it
# off on a small box where the sweep alone already fills the night.
VALIDATE_NIGHTLY = os.getenv("TS_VALIDATE_NIGHTLY", "1").lower() not in ("0", "false", "")


async def trending_session_loop() -> None:
    """Top up bars, then scan and manage, every tick while the market is open."""
    from . import basket
    from .bars import refresh_many
    from .engine import run_paper_cycle

    while True:
        try:
            if is_market_open():
                universe = await basket.active()
                if universe:
                    await refresh_many(universe, full=False)
                    result = await run_paper_cycle()
                    logger.info("[trending_stocks] cycle: opened=%s managed=%s closed=%s",
                                result.get("opened"), result.get("managed"),
                                result.get("closed"))
                else:
                    logger.debug("[trending_stocks] basket empty — nothing to scan")
        except Exception:
            logger.exception("[trending_stocks] session tick failed — retrying next tick")
        await asyncio.sleep(TICK_SECONDS)


def _due(now: datetime, last_run_date) -> bool:
    if now.weekday() >= 5:
        return False
    if now.strftime("%H:%M") < EOD_HHMM:
        return False
    return last_run_date != now.date()


async def trending_eod_loop() -> None:
    """Once a trading day, after the close: refresh, sweep, validate, re-grade."""
    from . import basket
    from .bars import refresh_many
    from .engine import run_backtests, run_validation

    last_run_date = None
    while True:
        try:
            now = datetime.now(IST)
            if _due(now, last_run_date):
                universe = await basket.active()
                if universe:
                    refreshed = await refresh_many(universe, full=False)
                    for sym, written in (refreshed.get("symbols") or {}).items():
                        await basket.mark_backfilled(sym, written)
                    swept = await run_backtests()
                    logger.info("[trending_stocks] nightly sweep: %s", swept)
                    if VALIDATE_NIGHTLY:
                        validated = await run_validation()
                        logger.info("[trending_stocks] nightly validation: %s", validated)
                last_run_date = now.date()
        except Exception:
            logger.exception("[trending_stocks] nightly pass failed — will retry tomorrow")
        await asyncio.sleep(EOD_CHECK_SECONDS)


async def news_ingest_loop() -> None:
    """Pull the syndicated RSS feeds so the news pillar has something to read.

    `ingest_all` is synchronous and does network I/O, so it runs on a worker thread — left
    inline it would block the event loop for however long three feeds take to answer."""
    while True:
        try:
            from research_service.ingest import ingest_all
            counts = await to_thread.run_sync(ingest_all)
            logger.info("[trending_stocks] news ingest: %s", counts)
        except Exception as exc:  # noqa: BLE001 — a feed being down is not an outage
            logger.info("[trending_stocks] news ingest skipped: %s", exc)
        await asyncio.sleep(NEWS_INTERVAL_SECONDS)


__all__ = ["ENABLED", "TICK_SECONDS", "EOD_HHMM", "NEWS_ENABLED",
           "trending_session_loop", "trending_eod_loop", "news_ingest_loop"]
