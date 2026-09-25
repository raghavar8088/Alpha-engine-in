"""Background loop for the Intraday Strategy Lab — a `while True` + try/except +
asyncio.sleep pattern. Runs the scan+manage cycle every TICK_SECONDS during
market hours only (09:15-15:30 IST, weekdays)."""

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

# Set once a day after the close, so the F&O screener bar refresh runs exactly once.


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
    from app.services.live_intraday_engine import run_cycle as live_run_cycle
    from app.services.nifty_scalp_engine import run_cycle as nifty_scalp_run
    from app.services.intraday_pattern_engine import run_cycle as pattern_run
    from app.services.pattern_books_engine import run_cycle as pattern_books_run
    from app.services.swing_trading import run_cycle as swing_run
    from app.services.live_trading_engine import run_cycle as live_trading_run_cycle
    from app.services.stock_desk import BUYING, SELLING, run_cycle as stock_desk_run_cycle
    from app.services.zero_hero import run_cycle as zero_hero_run_cycle
    from app.services.live_paper_buying import run_cycle as live_paper_run_cycle
    from app.services.fno_stock_roll import ENABLED as STOCK_ROLL_ENABLED, roll as stock_roll
    from app.services.morning_momentum import run_cycle as momentum_run
    from app.services.momentum_engine import run_cycle as momentum_run_cycle
    # Every desk below runs only while its module switch is ON. `gated` returns {}
    # when off, so the existing `result.get(...)` logging simply finds nothing.
    from app.services.desk_switches import gated

    while True:
        try:
            now = datetime.now(IST)
            if _in_market_hours(now):
                dhan = await _dhan_or_none()
                result = await gated("intraday_lab", run_cycle, dhan)
                logger.info(
                    "intraday-lab cycle: %d opened, %d managed, %d symbols scanned",
                    result["opened"], result["managed"], result["scanned_symbols"],
                )
                # The curated ₹80k Live Intraday shortlist rides the same tick + feed.
                try:
                    live_result = await gated("live_intraday", live_run_cycle, dhan)
                    logger.info(
                        "live-intraday cycle: %d opened, %d managed",
                        live_result["opened"], live_result["managed"],
                    )
                except Exception:
                    logger.exception("live-intraday cycle failed — tournament tick already committed")
                # The REAL-MONEY Live Trading desk rides the same tick + real Dhan client.
                # It is inert unless ARMED, so this is a no-op until the user turns it on.
                try:
                    lt_result = await gated("live_trading", live_trading_run_cycle, dhan)
                    if lt_result["opened"] or lt_result["managed"]:
                        logger.warning(
                            "LIVE-TRADING (real money) cycle: %d opened, %d managed",
                            lt_result["opened"], lt_result["managed"],
                        )
                except Exception:
                    logger.exception("live-trading (real) cycle failed — other ticks already committed")
                # Stock-option Pre-Live desks (paper) ride the same tick. Each is
                # rate-limit paced internally; a failure in one never stops the other.
                for _side in (BUYING, SELLING):
                    try:
                        sd = await gated("stock_desk", stock_desk_run_cycle, _side)
                        if sd["opened"] or sd["managed"]:
                            logger.info("stock-desk[%s]: %d opened, %d managed",
                                        _side, sd["opened"], sd["managed"])
                    except Exception:
                        logger.exception("stock-desk[%s] cycle failed", _side)
                # Zero Hero (expiry-day index lottery tickets, paper). Inert on any day no
                # index expires, so this is a cheap no-op most of the week.
                try:
                    zh = await gated("zero_hero", zero_hero_run_cycle)
                    if zh["opened"] or zh["managed"]:
                        logger.info("zero-hero: %d opened, %d managed", zh["opened"], zh["managed"])
                except Exception:
                    logger.exception("zero-hero cycle failed")
                # Live Paper Buying: the 5 leaderboard winners on a Rs50k book. Trades
                # automatically through the session and squares off at 15:15.
                try:
                    lp = await gated("live_paper", live_paper_run_cycle)
                    if lp["opened"] or lp["managed"]:
                        logger.info("live-paper: %d opened, %d managed, %d signals",
                                    lp["opened"], lp["managed"], lp["signals"])
                except Exception:
                    logger.exception("live-paper cycle failed")
                # Daily 15:00 ATM straddle roll across the whole stock-option universe.
                # Self-guarded: trading day, window, and once per session.
                try:
                    if STOCK_ROLL_ENABLED:
                        sr = await gated("fno_stock_roll", stock_roll)
                        if sr.get("ran"):
                            logger.warning("fno stock-roll: closed %s, sold %s legs",
                                           sr["closed"]["closed"], sr["opened"]["sold"])
                except Exception:
                    logger.exception("fno stock-roll failed")
                # Morning-momentum option buying: self-guarded to its 09:20/09:30/10:00
                # checkpoints, and manages its own book to target/stop/15:10 every tick.
                try:
                    mm = await gated("morning_momentum", momentum_run)
                    if mm.get("ran"):
                        logger.warning("morning-momentum %s: bought %s",
                                       mm.get("checkpoint"), mm.get("bought"))
                except Exception:
                    logger.exception("morning-momentum failed")
                # Swing Trading: fills user-placed buy orders when price reaches
                # them, then manages each to its stop/target.
                try:
                    sw = await gated("swing_trading", swing_run)
                    if sw.get("filled") or sw.get("closed"):
                        logger.warning("swing: filled %s closed %s of %s watching",
                                       sw["filled"], sw["closed"], sw["watching"])
                except Exception:
                    logger.exception("swing trading failed")
                # Pattern desk: 63 templates x 8 timeframes on equities. Self-guarded
                # on its own entry cutoff and candle-fetch budget.
                try:
                    pt = await gated("pattern", pattern_run)
                    if pt.get("opened") or pt.get("closed"):
                        logger.info("pattern: opened %s closed %s (%s evaluated)",
                                    pt["opened"], pt["closed"], pt.get("evaluated"))
                except Exception:
                    logger.exception("pattern desk failed")
                # The Rs 50,000 / Rs 2,00,000 books MIRROR the desk above, so they run
                # in the same tick and immediately after it: they read its fills rather
                # than the market, and a cycle's worth of lag would have them entering a
                # position the parent had already closed. Failure here must not touch the
                # parent, which has already done the expensive part.
                try:
                    pb = await gated("pattern_books", pattern_books_run)
                    if pb.get("opened") or pb.get("closed"):
                        logger.info("pattern-books: opened %s closed %s",
                                    pb["opened"], pb["closed"])
                except Exception:
                    logger.exception("pattern books failed")
                # NIFTY 50 Option Scalping: 400 candle/indicator strategies across 8
                # timeframes, buying near-expiry ATM options. Self-guarded on cutoffs.
                try:
                    ns = await gated("nifty_scalp", nifty_scalp_run)
                    if ns.get("opened") or ns.get("closed"):
                        logger.info("nifty-scalp: opened %s closed %s of %s signals",
                                    ns["opened"], ns["closed"], ns.get("signals"))
                except Exception:
                    logger.exception("nifty-scalp failed")
                # The Momentum pre-live desk (paper, ₹10k/strategy, fee-honest) rides the
                # same tick and feed. Isolated like the others: a failure here must not
                # roll back ticks that already committed above.
                try:
                    mom = await gated("momentum_engine", momentum_run_cycle, dhan)
                    logger.info(
                        "momentum cycle: %d opened, %d managed, %d symbols scanned (regime: %s)",
                        mom["opened"], mom["managed"], mom["scanned_symbols"],
                        "ok" if mom["regime"]["ok"] else "risk-off",
                    )
                except Exception:
                    logger.exception("momentum cycle failed — other ticks already committed")
        except Exception:
            logger.exception("intraday-lab scheduler tick failed — will retry next tick")
        await asyncio.sleep(TICK_SECONDS)
