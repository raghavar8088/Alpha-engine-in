"""Auto-generation scheduler for the Trading Calls module.

Runs the call engine on fixed IST slots on trading weekdays, the way broker
research desks publish through the day:

    09:25 / 11:25 / 13:25  — 2-hour intraday+positional scans
    15:20                  — last scan, doubles as the BTST scan
    17:30                  — evening positional-only scan (next-day ideas)

plus a 5-minute status-refresh tick during market hours so SL/target hits and
the paper positions ledger roll even when nobody has the page open.

Same background-task pattern as the Dhan TOTP refresh loop in app.main: a
`while True` + try/except + asyncio.sleep task created at startup, guarded by
CALLS_AUTOGEN_ENABLED (default on). Slot state is persisted in Mongo so a
backend restart mid-day neither re-runs finished slots nor misses a due one
(a slot stays runnable for GRACE_MINUTES past its time).
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.core.db import call_scheduler_state_collection
from app.services.call_engine import IST, generate_calls, refresh_calls
from app.services.call_positions import open_positions_for_calls, sync_positions

logger = logging.getLogger("trading_calls_scheduler")

AUTOGEN_ENABLED = os.getenv("CALLS_AUTOGEN_ENABLED", "1").lower() not in ("0", "false")
GENERATION_SLOTS = tuple(
    s.strip() for s in (os.getenv("CALLS_AUTOGEN_SLOTS") or "09:25,11:25,13:25,15:20,17:30").split(",") if s.strip()
)
GRACE_MINUTES = 20      # a slot missed by less than this (restart, hiccup) still runs
TICK_SECONDS = 60
REFRESH_TICK_SECONDS = 300
MARKET_OPEN, MARKET_CLOSE = "09:15", "15:35"

STATE_ID = "trading_calls_scheduler"


def _is_trading_day(now: datetime) -> bool:
    return now.weekday() < 5


def _due_slot(now: datetime, ran_slots: set[str]) -> str | None:
    """The earliest slot whose time has passed today, is within the grace
    window, and hasn't run yet. Stale slots (grace expired) are skipped — a
    backend down all morning must not fire stale intraday scans at 2pm."""
    if not _is_trading_day(now):
        return None
    hhmm = now.strftime("%H:%M")
    for slot in sorted(GENERATION_SLOTS):
        if slot in ran_slots or slot > hhmm:
            continue
        slot_dt = now.replace(hour=int(slot[:2]), minute=int(slot[3:]), second=0, microsecond=0)
        if now - slot_dt <= timedelta(minutes=GRACE_MINUTES):
            return slot
    return None


def next_slot(now: datetime) -> str:
    """Human-readable next run, e.g. "15:20 IST today" / "09:25 IST Mon"."""
    slots = sorted(GENERATION_SLOTS)
    if _is_trading_day(now):
        hhmm = now.strftime("%H:%M")
        for slot in slots:
            if slot > hhmm:
                return f"{slot} IST today"
    nxt = now + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return f"{slots[0]} IST {nxt.strftime('%a')}"


async def _dhan_or_none():
    """The module degrades honestly without a broker (same contract as the
    router's _optional_dhan): bar-close prices, no intraday setups."""
    from app.api.deps import get_current_user
    from app.api.routes.broker import _get_dhan_client

    try:
        user = await get_current_user()
        return await _get_dhan_client(str(user["_id"]))
    except (HTTPException, Exception):
        return None


async def _run_slot(slot: str, today_iso: str) -> None:
    dhan = await _dhan_or_none()
    result = await generate_calls(dhan, run_slot=slot)
    opened = await open_positions_for_calls(result["calls"])
    await refresh_calls(dhan)
    await sync_positions()
    await call_scheduler_state_collection.update_one(
        {"_id": STATE_ID},
        {
            "$set": {
                "enabled": True,
                "slots": list(GENERATION_SLOTS),
                "ran_date": today_iso,
                "last_run_at": datetime.now(timezone.utc),
                "last_slot": slot,
                "last_created": result["created"],
                "last_positions_opened": opened,
                "broker_connected": dhan is not None,
            },
            "$addToSet": {"ran_slots": slot},
        },
        upsert=True,
    )
    logger.info(
        "auto-scan %s: %d new calls (%d scanned), %d positions opened",
        slot, result["created"], result["scanned"], opened,
    )


async def call_scheduler_loop() -> None:
    last_refresh = 0.0
    while True:
        try:
            now = datetime.now(IST)
            today_iso = now.date().isoformat()

            state = await call_scheduler_state_collection.find_one({"_id": STATE_ID})
            ran_slots = set(state.get("ran_slots") or []) if state and state.get("ran_date") == today_iso else set()
            if state and state.get("ran_date") != today_iso:
                await call_scheduler_state_collection.update_one(
                    {"_id": STATE_ID}, {"$set": {"ran_date": today_iso, "ran_slots": []}}
                )

            slot = _due_slot(now, ran_slots)
            if slot:
                await _run_slot(slot, today_iso)

            # market-hours status refresh so calls/positions roll headlessly
            in_market = _is_trading_day(now) and MARKET_OPEN <= now.strftime("%H:%M") <= MARKET_CLOSE
            if in_market and time.monotonic() - last_refresh > REFRESH_TICK_SECONDS:
                last_refresh = time.monotonic()
                await refresh_calls(await _dhan_or_none())
                await sync_positions()
        except Exception:
            logger.exception("trading-calls scheduler tick failed — will retry next tick")
        await asyncio.sleep(TICK_SECONDS)
