"""The intraday data loop — every data job, at the time of day it belongs to.

  07:30        results calendar: filings since yesterday + upcoming results meetings
  08:40/09:05  global cues snapshot (previous US session, live futures/Asia/FX/crude/VIX),
               then the expected NIFTY gap, frozen before the open so the close can score it
  08:45        today's universe; preload bar history (15m and 5m) off the event loop
  08:55 09:16  Scanner Board snapshots, frozen to disk as computed (the 09:45/10:15/11:15
  09:45 10:15  ones 30 s after the bar closes, so the bar is in; a late one after a restart
  11:15        is still computed AS OF its label time, and skipped if 15+ minutes late)
  09:08-09:14  NSE pre-open: IEP, imbalance, matched quantity for every stock
  09:30-15:35  gap-fill holes in today's stream bars (every 5 min)
  15:40        flush the day's stream bars to disk
  15:45/20:00  results calendar again (filings during and after the session)
  15:50        reconcile 15m and 5m against Angel's candles; incubation verdicts; edge report;
               score the 09:45 expected-move ranking and the gap forecast against the day
  19:00-23:30  NSE archives (delivery, F&O OI, participant OI), every 30 min until all in
  off-hours    history backfill: 15m first, then 5m (each resumable, stops at 08:50);
               expected-move model retrained when missing or a week old
  Sunday       global daily history refresh (for the expected-gap model)

Long jobs (backfills, archive catch-up) run as their OWN tasks so a two-hour 5-minute
backfill can never delay the 09:08 pre-open capture or the 15:40 flush. Every step is
isolated; a failure is logged and retried on a later tick, never raised.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime

from app.services import intraday_backfill, intraday_universe, market_calendar
from app.services.intraday_store import store, store5

logger = logging.getLogger("intraday_data_scheduler")

ENABLED = os.getenv("INTRADAY_DATA_ENABLED", "1").lower() not in ("0", "false", "no")
TICK_S = 30
GAPFILL_EVERY_S = 300
BACKFILL_RETRY_S = 1800             # a complete symbol costs no request (see _windows)
ARCHIVE_RETRY_S = 1800
UNIVERSE_FROM = "08:45"
RECONCILE_FROM = "15:50"

_tasks: dict[str, asyncio.Task] = {}
_done: dict[str, str] = {}           # job -> ISO date it last completed


def _spawn(name: str, coro) -> bool:
    t = _tasks.get(name)
    if t is not None and not t.done():
        coro.close()
        return False
    _tasks[name] = asyncio.create_task(coro)
    return True


def _once(job: str, today: str) -> bool:
    """True the first time `job` is asked for on `today`."""
    if _done.get(job) == today:
        return False
    _done[job] = today
    return True


async def _history_jobs() -> None:
    """15m backfill, then 5m once 15m is complete. Stops by itself at 08:50."""
    r = await intraday_backfill.backfill(tf="15m")
    logger.info("history backfill 15m: %s", r)
    if not r.get("incomplete") and intraday_backfill.off_hours():
        r5 = await intraday_backfill.backfill(tf="5m")
        logger.info("history backfill 5m: %s", r5)


async def _archive_job() -> None:
    from app.services import nse_archives
    r = await nse_archives.catch_up(10)
    logger.info("NSE archives: %s", r)


async def _train_if_stale() -> None:
    from datetime import timedelta, timezone

    from app.services import scanner_board
    m = await scanner_board.load_model()
    at = (m or {}).get("trained_at")
    if at is not None and datetime.now(timezone.utc) - at < timedelta(days=6, hours=12):
        return
    try:
        await scanner_board.train()
    except Exception:  # noqa: BLE001 - e.g. history still incomplete; tried again tomorrow
        logger.exception("expected-move training failed")


SNAPSHOT_LATE_S = 900


async def _snapshots(now: datetime, today: str) -> None:
    """Take each due Scanner Board snapshot once. Bar-based ones wait 30 s past the label
    for the bar that closed at the label to arrive."""
    from app.services import scanner_board
    for label in scanner_board.SNAPSHOT_TIMES:
        h, m = map(int, label.split(":"))
        due = now.replace(hour=h, minute=m, second=30 if label >= "09:30" else 0, microsecond=0)
        if now < due or _done.get("snap " + label) == today:
            continue
        _done["snap " + label] = today
        if (now - due).total_seconds() > SNAPSHOT_LATE_S:
            logger.warning("scanner snapshot %s skipped: %d s late", label, (now - due).total_seconds())
            continue
        r = await scanner_board.snapshot(label, now=due)
        logger.info("scanner snapshot %s: %d stocks", label, r["stocks"])


async def intraday_data_loop() -> None:
    from app.services import global_cues, preopen, results_calendar, scanner_board, selection_brief

    last_gapfill = 0.0
    last_backfill = 0.0
    last_archive = 0.0
    try:
        await results_calendar.ensure_indexes()
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services.intraday_v2_registry import preregister
        r = await preregister()
        if r["registered"]:
            logger.info("incubation: pre-registered %s", r["registered"])
    except Exception:  # noqa: BLE001 - never blocks the data loop
        logger.exception("pre-registration failed")
    if not global_cues.history("SPX"):
        _spawn("global_history", global_cues.refresh_history())   # the gap model needs it
    while True:
        try:
            now = datetime.now(market_calendar.IST)
            hhmm = now.strftime("%H:%M")
            today = now.date().isoformat()
            trading = market_calendar.is_trading_day(now)

            # ── before the open ──────────────────────────────────────────────────
            if trading and "07:30" <= hhmm < "15:30" and _once("results_am", today):
                logger.info("results calendar: %s", await results_calendar.refresh())
            if trading and "08:40" <= hhmm < "09:05" and _once("global_0840", today):
                await global_cues.snapshot()
                await selection_brief.record_gap_forecast(now.date())
            if trading and "09:05" <= hhmm < "09:15" and _once("global_0905", today):
                await global_cues.snapshot()
                fc = await selection_brief.record_gap_forecast(now.date())
                logger.info("expected NIFTY gap: %s", fc and {k: fc[k] for k in ("pred_bp", "call", "us_move_bp")})
            if trading and hhmm >= UNIVERSE_FROM:
                await intraday_universe.today()                     # builds once a day
                if hhmm <= "15:30" and _once("preload", today):
                    syms = await intraday_universe.symbols()
                    idx = list(intraday_universe.INDEX_TOKENS)
                    n = await store.preload(syms + idx)
                    n5 = await store5.preload(syms + idx)
                    logger.info("bar store preloaded: 15m %d, 5m %d of %d", n, n5, len(syms) + len(idx))
            preopen_window = "09:09" <= hhmm < "09:15" or (hhmm == "09:08" and now.second >= 30)
            if trading and preopen_window and _done.get("preopen") != today:
                uni = set(await intraday_universe.symbols())
                r = await preopen.capture(uni)
                if r.get("ok"):
                    _done["preopen"] = today
                    logger.info("pre-open captured: %d stocks, A/D %s/%s", r["stocks"], r["advances"], r["declines"])

            if trading and "08:55" <= hhmm < "12:00":
                await _snapshots(now, today)

            # ── in the session ───────────────────────────────────────────────────
            if trading and "09:30" <= hhmm <= "15:35" and time.monotonic() - last_gapfill > GAPFILL_EVERY_S:
                last_gapfill = time.monotonic()
                r = await intraday_backfill.gapfill(now)
                if r.get("requests"):
                    logger.info("gap-fill %s", r)

            # ── after the close ──────────────────────────────────────────────────
            if trading and hhmm >= "15:40" and _once("flush", today):
                logger.info("end-of-day flush: 15m %s, 5m %s", await store.flush_dirty(), await store5.flush_dirty())
            if trading and hhmm >= "15:45" and _once("results_pm", today):
                await results_calendar.refresh()
            if trading and hhmm >= "20:00" and _once("results_eve", today):
                await results_calendar.refresh()
            if trading and hhmm >= RECONCILE_FROM and _once("reconcile", today):
                await intraday_backfill.reconcile(now.date())
                await intraday_backfill.reconcile_5m(now.date())
                await store.flush_dirty()
                await store5.flush_dirty()
                from app.services.intraday_v2_registry import evaluate_forward
                r = await evaluate_forward()
                if r.get("decided"):
                    logger.warning("incubation verdicts: %s", r["decided"])
                logger.info("expected-move ranking today: %s", await scanner_board.score_day(now.date()))
                logger.info("NIFTY gap today: %s", await selection_brief.score_gap(now.date()))
                from app.services.intraday_ops import build_edge_report
                rep = await build_edge_report(now.date())
                logger.info("edge report %s: %s", now.date(), rep["desk"])
                from app.services.option_hypotheses import evaluate as evaluate_option_hypotheses
                logger.info("option hypotheses: %s", await evaluate_option_hypotheses())

            # ── off-hours ────────────────────────────────────────────────────────
            evening = (not trading) or hhmm >= "19:00"
            if evening and time.monotonic() - last_archive > ARCHIVE_RETRY_S:
                last_archive = time.monotonic()
                _spawn("archives", _archive_job())
            reconciled = (not trading) or (hhmm >= RECONCILE_FROM and _done.get("reconcile") == today)
            if intraday_backfill.off_hours(now) and reconciled and time.monotonic() - last_backfill > BACKFILL_RETRY_S:
                if _spawn("history", _history_jobs()):
                    last_backfill = time.monotonic()
            if now.weekday() == 6 and _once("global_history", today):
                logger.info("global history: %s", await global_cues.refresh_history())
            if intraday_backfill.off_hours(now) and reconciled and _once("train_check", today):
                _spawn("train", _train_if_stale())
        except Exception:  # noqa: BLE001
            logger.exception("intraday data loop tick failed — retrying")
        await asyncio.sleep(TICK_S)


def describe() -> dict:
    return {"jobs_done_today": dict(_done),
            "running": [k for k, t in _tasks.items() if not t.done()]}
