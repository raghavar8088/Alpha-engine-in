"""One set of intraday session rules for every equity intraday desk — and the close-out job.

WHY THIS MODULE EXISTS
Five desks (the tournament, the pattern desk, the pattern paper books, Live Intraday and the
real-money Live Trading desk) each carried their own copy of "stop entering at 15:00, square
off at 15:15". Two things were wrong with that, and both were measured on 2026-10-01:

1. THE CLOSE COULD BE MISSED ENTIRELY. Square-off only happened inside each desk's manage
   cycle, and that cycle only ran if the shared intraday loop got a tick into the fifteen
   minutes between 15:15 and its 15:30 stop. On 2026-10-01 the backend was swapping and no
   tick landed in that window, so every open intraday position was carried overnight and
   closed into the next morning's gap. Across the tournament that was 291 of 764 trades —
   38% of an "intraday" desk's record was overnight gap risk. `squareoff_loop` below runs on
   its own task, calls each desk's own manage cycle every few seconds through the close-out
   window, and keeps going until the books are flat.

2. THE MARKET'S CLOSE MOVED. From 3 Aug 2026 NSE runs a Closing Auction Session for the
   stocks Angel flags `is_cas_enabled` (the F&O-backed names). In those stocks continuous
   trading ends at 15:15 and Angel auto-squares MIS positions at 15:10 (Angel SmartAPI
   notice, forum post 19209). A 15:15 paper square-off therefore closed CAS positions at a
   price no intraday account could have traded at, and on the real-money desk it would have
   tried to exit positions the broker had already closed. Non-CAS stocks keep continuous
   trading to 15:30 and Angel squares them at 15:15.

THE TIMES (each overridable by env, all IST)
  entry cutoff              14:30   no new intraday entries after this
  CAS-stock square-off      15:05   five minutes inside Angel's own 15:10
  non-CAS square-off        15:12   three minutes inside Angel's 15:15
  close-out window          15:00 – 15:45   the loop's active window
  missed-close alarm        15:20 (CAS) / 15:27 (non-CAS)

The entry cutoff moved from 15:00 to 14:30 because an entry at 14:59 in a CAS stock would be
force-closed six minutes later — a trade that measures the square-off, not the strategy.

WHAT COUNTS AS CAS
Read from Angel's own `is_cas_enabled` flag, which `angel_instruments.refresh_angel_tokens`
stamps onto each equity. Until that refresh has run once with the flag, the F&O-underlying
list is used instead (every source agrees the auction list is the F&O stocks) and the basis
is reported, so it is never silently a guess.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from app.core.db import db, instruments_collection
from app.services import market_calendar

logger = logging.getLogger("intraday_session")

IST = timezone(timedelta(hours=5, minutes=30))

ENTRY_CUTOFF_HHMM = os.getenv("INTRADAY_ENTRY_CUTOFF", "14:30")
CAS_SQUAREOFF_HHMM = os.getenv("INTRADAY_CAS_SQUAREOFF", "15:05")
NONCAS_SQUAREOFF_HHMM = os.getenv("INTRADAY_NONCAS_SQUAREOFF", "15:12")
WINDOW_OPEN_HHMM = os.getenv("INTRADAY_CLOSEOUT_FROM", "15:00")
WINDOW_CLOSE_HHMM = os.getenv("INTRADAY_CLOSEOUT_UNTIL", "15:45")
CAS_ALARM_HHMM = os.getenv("INTRADAY_CAS_MISSED_AT", "15:20")
NONCAS_ALARM_HHMM = os.getenv("INTRADAY_NONCAS_MISSED_AT", "15:27")
LOOP_SECONDS = float(os.getenv("INTRADAY_CLOSEOUT_SECONDS", "15"))
CAS_TTL_SECONDS = 6 * 3600

alarms_collection = db["system_alarms"]

_cas: set[str] = set()
_cas_at = 0.0
_cas_basis = "not loaded"
_cas_lock = asyncio.Lock()


def _hhmm(now: datetime | None = None) -> str:
    return (now or datetime.now(IST)).astimezone(IST).strftime("%H:%M")


# ── the auction list ─────────────────────────────────────────────────────────────


async def refresh_cas() -> dict:
    """Reload the set of closing-auction stocks. Cheap: one indexed query."""
    global _cas, _cas_at, _cas_basis
    syms = {d["symbol"] async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "is_cas_enabled": True}, {"symbol": 1})}
    basis = "angel_is_cas_enabled"
    if not syms:
        syms = {u for u in await instruments_collection.distinct(
            "underlying_symbol", {"asset_class": "EQUITY_OPTION"}) if u}
        basis = "fno_underlyings_fallback"
    _cas, _cas_at, _cas_basis = syms, time.monotonic(), basis
    return {"cas_symbols": len(syms), "basis": basis}


async def ensure_cas() -> None:
    """Load the auction list if it is missing or older than six hours. Never raises: a desk
    must still manage its book if this lookup fails — it then uses the last good list, or,
    with none at all, treats every stock as CAS, the EARLIER and therefore safer close."""
    if _cas and time.monotonic() - _cas_at < CAS_TTL_SECONDS:
        return
    async with _cas_lock:
        if _cas and time.monotonic() - _cas_at < CAS_TTL_SECONDS:
            return
        try:
            await refresh_cas()
        except Exception:  # noqa: BLE001
            logger.exception("auction-list refresh failed; keeping the previous list")


def is_cas(symbol: str) -> bool:
    if not _cas:
        return True           # unknown -> close at the earlier time, never the later one
    return symbol in _cas


def cas_basis() -> str:
    return _cas_basis


# ── the rules every desk applies ─────────────────────────────────────────────────


def entries_closed(now: datetime | None = None) -> bool:
    return _hhmm(now) >= ENTRY_CUTOFF_HHMM


def squareoff_hhmm(symbol: str) -> str:
    return CAS_SQUAREOFF_HHMM if is_cas(symbol) else NONCAS_SQUAREOFF_HHMM


def squareoff_due(symbol: str, now: datetime | None = None) -> bool:
    """Has this symbol's intraday square-off time arrived? Call `ensure_cas()` first."""
    return _hhmm(now) >= squareoff_hhmm(symbol)


def describe() -> dict:
    return {"entry_cutoff": ENTRY_CUTOFF_HHMM, "cas_squareoff": CAS_SQUAREOFF_HHMM,
            "noncas_squareoff": NONCAS_SQUAREOFF_HHMM, "cas_symbols": len(_cas),
            "cas_basis": _cas_basis}


# ── the close-out job ────────────────────────────────────────────────────────────

# (name, module, manage function, takes a Dhan client, positions collection, is-intraday test)
# Each entry calls the desk's OWN manage cycle, so fees, ledgers and scores are written by
# exactly the code that writes them the rest of the day. Every manage cycle here is now
# idempotent and serialised by a per-desk lock, so calling it every few seconds is safe.
def _desks() -> list[dict]:
    from app.core import db as D
    return [
        {"name": "intraday_lab", "module": "app.services.intraday_lab_engine",
         "fn": "manage_cycle", "dhan": True, "coll": D.intraday_lab_positions_collection,
         "intraday": {"category": {"$in": ["scalping", "momentum", "mean_reversion"]}}},
        {"name": "pattern", "module": "app.services.intraday_pattern_engine",
         "fn": "manage", "dhan": False, "coll": D.pattern_positions_collection,
         "intraday": {"style": {"$in": ["scalping", "intraday"]}}},
        {"name": "pattern_books", "module": "app.services.pattern_books_engine",
         "fn": "sync_closes", "dhan": False, "coll": D.pattern_book_positions_collection,
         "intraday": None},
        {"name": "live_intraday", "module": "app.services.live_intraday_engine",
         "fn": "manage_cycle", "dhan": True, "coll": D.live_intraday_positions_collection,
         "intraday": {"category": {"$in": ["scalping", "momentum", "mean_reversion"]}}},
        {"name": "live_trading", "module": "app.services.live_trading_engine",
         "fn": "manage_cycle", "dhan": True, "coll": D.live_trading_positions_collection,
         "intraday": {}},
    ]


async def _still_open(desk: dict, today: str) -> list[dict]:
    """Same-day intraday positions this desk still holds."""
    if desk["intraday"] is None:            # a mirror book: it is flat when its parent is
        q: dict = {"status": "OPEN"}
    else:
        q = {"status": "OPEN", **desk["intraday"]}
    rows = []
    async for p in desk["coll"].find(q, {"symbol": 1, "opened_on": 1, "strategy_id": 1}):
        rows.append(p)
    return rows


async def _raise_alarm(kind: str, detail: dict) -> None:
    """Recorded for the monitoring page (Phase 4). Never raises."""
    try:
        today = datetime.now(IST).date().isoformat()
        await alarms_collection.update_one(
            {"_id": f"{kind}:{today}:{detail.get('desk', '')}"},
            {"$set": {"kind": kind, "session": today, "detail": detail,
                      "at": datetime.now(timezone.utc), "resolved": False}},
            upsert=True)
    except Exception:  # noqa: BLE001
        logger.exception("could not record alarm %s", kind)


async def closeout_pass(now: datetime | None = None) -> dict:
    """One pass: run every desk's manage cycle, then report what is still open and late."""
    import importlib

    now = now or datetime.now(IST)
    await ensure_cas()
    today = now.astimezone(IST).date().isoformat()
    hhmm = _hhmm(now)
    report: dict = {"at": hhmm, "desks": {}}
    for desk in _desks():
        name = desk["name"]
        try:
            fn = getattr(importlib.import_module(desk["module"]), desk["fn"])
            closed = await (fn(None) if desk["dhan"] else fn())
        except Exception as exc:  # noqa: BLE001 - one desk failing must not stop the others
            logger.exception("[closeout] %s manage failed", name)
            report["desks"][name] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        try:
            left = await _still_open(desk, today)
        except Exception:  # noqa: BLE001
            left = []
        late = [p["symbol"] for p in left
                if hhmm >= (CAS_ALARM_HHMM if is_cas(p.get("symbol", "")) else NONCAS_ALARM_HHMM)]
        report["desks"][name] = {"managed": closed, "still_open": len(left), "late": len(late)}
        if late:
            logger.error("[closeout] SQUARE-OFF MISSED on %s: %d position(s) still open past their "
                         "close time: %s", name, len(late), sorted(set(late))[:12])
            await _raise_alarm("squareoff_missed", {"desk": name, "count": len(late),
                                                    "symbols": sorted(set(late))[:50], "at": hhmm})
    return report


async def squareoff_loop() -> None:
    """Runs on its own task, independent of the shared intraday loop.

    Active on weekdays from WINDOW_OPEN to WINDOW_CLOSE. It does not respect the Main Control
    switches, deliberately: switching a desk OFF stops it trading, it must not leave that
    desk's open intraday positions to be carried overnight."""
    logger.info("intraday close-out loop started — entries stop %s; CAS stocks close %s, others "
                "%s; window %s-%s IST", ENTRY_CUTOFF_HHMM, CAS_SQUAREOFF_HHMM,
                NONCAS_SQUAREOFF_HHMM, WINDOW_OPEN_HHMM, WINDOW_CLOSE_HHMM)
    last_report_minute = None
    while True:
        try:
            now = datetime.now(IST)
            if market_calendar.is_trading_day(now) and WINDOW_OPEN_HHMM <= _hhmm(now) <= WINDOW_CLOSE_HHMM:
                report = await closeout_pass(now)
                minute = _hhmm(now)
                if minute != last_report_minute and any(
                        d.get("still_open") or d.get("managed") for d in report["desks"].values()):
                    logger.info("[closeout] %s", report)
                    last_report_minute = minute
                await asyncio.sleep(LOOP_SECONDS)
                continue
        except Exception:  # noqa: BLE001
            logger.exception("[closeout] pass failed — retrying")
        await asyncio.sleep(60)
