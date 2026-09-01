"""Daily 3 PM ATM short-straddle roll for one dedicated F&O paper account.

WHAT IT DOES
------------
On every trading day at ROLL_HHMM (15:00 IST, before the 15:30 close):

  1. close every open NIFTY option position in the target account, then
  2. sell 1 lot of the ATM CE and 1 lot of the ATM PE of the "next week" expiry,
     with the ATM strike re-picked from the LIVE spot at roll time.

So the book is a short straddle that is re-centred on spot once a day and always
carries at least MIN_DAYS_TO_EXPIRY of time value. Closing before re-opening is what
makes the whole thing safe to retry: a half-finished roll is undone by the next
attempt's close step rather than doubling the position.

"NEXT WEEK EXPIRY" IS RESOLVED FROM THE INSTRUMENT MASTER, NOT ARITHMETIC
-------------------------------------------------------------------------
The target is the nearest expiry at least MIN_DAYS_TO_EXPIRY (7) calendar days out,
chosen from the expiries that actually exist on file. That distinction matters here:
on 2026-08-11 the NIFTY master held 2026-08-11 and 2026-08-25 but NOT 2026-08-18, so
"one week from now" as a date would have resolved to a contract that cannot be traded,
while "the first expiry at least a week out" correctly lands on 2026-08-25 — which is
exactly the contract the account already holds. If 08-18 later appears in the master,
the roll will prefer it, because that genuinely is next week's expiry.

The ATM strike is likewise the nearest LISTED strike to spot that has BOTH a CE and a
PE, not `round(spot/50)*50` — a computed strike that happens not to exist would fail
the whole basket.

PAPER ONLY
----------
This drives `fno_positions`, which is a paper desk: no real broker order is ever
placed. Prices are live (Angel/Dhan), the money is not.

SAFETY
------
- Runs at most once per calendar day (`last_rolled_on` in Mongo). A restart mid-day
  neither repeats a finished roll nor loses a due one inside the grace window.
- Aborts BEFORE closing anything if the live spot, the expiry or the strike cannot be
  resolved — it will never flatten the book and then fail to re-open because of data
  it could have checked first.
- If the re-open fails after the close succeeded, the day is NOT marked done, so the
  next tick inside the grace window retries; the failure is recorded either way.
- Weekday + live-spot gate, plus an explicit holiday list, so it does not roll on a
  day the market never opened.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    fno_auto_roll_log_collection,
    fno_auto_roll_state_collection,
    fno_positions_collection,
    instruments_collection,
)
from app.services.dhan_client import DhanClient
from app.services.fno_positions import (
    OPTION_CLASSES,
    OrderError,
    _underlying_spot,
    execute_basket,
    exit_position,
    list_accounts,
    option_expiries,
    summary,
)

logger = logging.getLogger("fno_auto_roll")

IST = timezone(timedelta(hours=5, minutes=30))
STATE_ID = "fno_auto_roll"

ENABLED = os.getenv("FNO_AUTO_ROLL_ENABLED", "1").lower() not in ("0", "false", "")
# Matched case-insensitively against the F&O paper account names. Only this one account
# is ever touched — every other book on the desk is left completely alone.
ACCOUNT_NAME = os.getenv("FNO_AUTO_ROLL_ACCOUNT", "AUTO SELLING 2 LAKH")
# Pin the roller to one account by id. Set this and the name is ignored entirely, which is
# the only binding a rename cannot break.
ACCOUNT_ID = os.getenv("FNO_AUTO_ROLL_ACCOUNT_ID", "").strip()
SYMBOL = os.getenv("FNO_AUTO_ROLL_SYMBOL", "NIFTY")
LOTS = int(os.getenv("FNO_AUTO_ROLL_LOTS", "1"))
PRODUCT_TYPE = os.getenv("FNO_AUTO_ROLL_PRODUCT", "MARGIN")
ROLL_HHMM = os.getenv("FNO_AUTO_ROLL_TIME", "15:00")
# A roll missed by less than this (restart, hiccup, transient quote failure) still runs.
# Kept short enough that a retry still lands before the 15:30 close.
GRACE_MINUTES = int(os.getenv("FNO_AUTO_ROLL_GRACE_MINUTES", "25"))
MIN_DAYS_TO_EXPIRY = int(os.getenv("FNO_AUTO_ROLL_MIN_DAYS", "7"))
TICK_SECONDS = int(os.getenv("FNO_AUTO_ROLL_TICK_SECONDS", "60"))
# NSE trading holidays that fall on a weekday, ISO dates, comma-separated. There is no
# holiday feed in this app, and a live LTP alone cannot prove the market is open (a
# quote endpoint happily returns the previous close on a holiday), so the honest
# options are an explicit list or rolling on a closed day. This is the list.
HOLIDAYS = {d.strip() for d in os.getenv("FNO_AUTO_ROLL_HOLIDAYS", "").split(",") if d.strip()}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist() -> date:
    return datetime.now(IST).date()


def is_trading_day(now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    return now.weekday() < 5 and now.date().isoformat() not in HOLIDAYS


async def resolve_account() -> tuple[dict | None, str]:
    """Find the account this roller owns, and say HOW it was found.

    Exact-name matching alone is why this silently stopped working. The account was
    renamed "AUTO SELLING 2 LAKH 1 ST SEPT", the configured name stayed "AUTO SELLING 2
    LAKH", and the roller skipped every session for eighteen days while logging a message
    nobody had a reason to read.

    So three rules, narrowest first, and the winner is reported rather than assumed:
      1. an explicit account id, which no rename can break;
      2. an exact name match;
      3. a name that STARTS WITH the configured one — and only if exactly one does.
         Dated variants of the same book are the normal case here. Two matches is
         ambiguous, and guessing between two funded accounts is worse than not trading.

    Returns (account, how). `how` is one of: id, exact, prefix, ambiguous, none.
    """
    accounts = await list_accounts()
    if ACCOUNT_ID:
        for acct in accounts:
            if str(acct.get("account_id")) == ACCOUNT_ID:
                return acct, "id"
        return None, "none"

    wanted = ACCOUNT_NAME.strip().lower()
    for acct in accounts:
        if str(acct.get("name", "")).strip().lower() == wanted:
            return acct, "exact"

    starts = [a for a in accounts
              if str(a.get("name", "")).strip().lower().startswith(wanted)]
    if len(starts) == 1:
        logger.info("fno auto-roll: bound to %r by prefix — configured name is %r",
                    starts[0].get("name"), ACCOUNT_NAME)
        return starts[0], "prefix"
    if len(starts) > 1:
        logger.warning("fno auto-roll: %s accounts start with %r (%s) — refusing to guess",
                       len(starts), ACCOUNT_NAME,
                       ", ".join(str(a.get("name")) for a in starts))
        return None, "ambiguous"
    return None, "none"


async def _target_account() -> dict | None:
    acct, _how = await resolve_account()
    return acct


async def resolve_expiry(dhan: DhanClient | None) -> tuple[str | None, str]:
    """The nearest listed expiry at least MIN_DAYS_TO_EXPIRY days out."""
    expiries = await option_expiries(dhan, SYMBOL)
    today = _today_ist()
    for e in sorted(expiries):
        try:
            days = (date.fromisoformat(e) - today).days
        except ValueError:
            continue
        if days >= MIN_DAYS_TO_EXPIRY:
            return e, f"{e} ({days} days out)"
    return None, (
        f"No {SYMBOL} expiry at least {MIN_DAYS_TO_EXPIRY} days out is on file "
        f"(have: {', '.join(sorted(expiries)[:5]) or 'none'})"
    )


async def resolve_atm_strike(expiry: str, spot: float) -> tuple[float | None, str]:
    """The nearest LISTED strike to spot that has both a CE and a PE for `expiry`.

    Checked against the instrument master rather than computed, and both wings verified,
    because a strike that exists for one option type but not the other would fail the
    basket after the book had already been closed."""
    strikes = await instruments_collection.distinct(
        "strike",
        {"underlying_symbol": SYMBOL, "expiry": expiry, "asset_class": {"$in": list(OPTION_CLASSES)}},
    )
    candidates = sorted((float(k) for k in strikes if k), key=lambda k: (abs(k - spot), k))
    for strike in candidates[:6]:
        types = await instruments_collection.distinct(
            "option_type",
            {"underlying_symbol": SYMBOL, "expiry": expiry, "strike": strike,
             "asset_class": {"$in": list(OPTION_CLASSES)}},
        )
        if {"CE", "PE"} <= {str(t).upper() for t in types}:
            return strike, f"{strike:g} (spot {spot:,.2f})"
    return None, f"No strike near spot {spot:,.2f} has both a CE and a PE for {expiry}"


async def _open_option_positions(account_id: str) -> list[dict]:
    return [
        p async for p in fno_positions_collection.find({
            "account_id": account_id, "status": "OPEN",
            "instrument.underlying_symbol": SYMBOL.upper(),
            "instrument_kind": "OPTION",
        })
    ]


async def preview(dhan: DhanClient | None) -> dict:
    """What the next roll would do, without doing it — the read model behind the UI."""
    acct = await _target_account()
    if acct is None:
        return {"ok": False, "reason": f"No F&O paper account named {ACCOUNT_NAME!r}", "account": None}
    spot = await _underlying_spot(dhan, SYMBOL)
    expiry, expiry_note = await resolve_expiry(dhan)
    strike, strike_note = (None, "spot unavailable")
    if spot and expiry:
        strike, strike_note = await resolve_atm_strike(expiry, spot)
    open_positions = await _open_option_positions(acct["account_id"])
    return {
        "ok": bool(spot and expiry and strike),
        "account": {"account_id": acct["account_id"], "name": acct.get("name"),
                    "initial_capital": acct.get("initial_capital")},
        "symbol": SYMBOL, "lots": LOTS, "product_type": PRODUCT_TYPE,
        "spot": round(spot, 2) if spot else None,
        "target_expiry": expiry, "expiry_note": expiry_note,
        "target_strike": strike, "strike_note": strike_note,
        "would_close": [
            {"position_id": p["position_id"], "display_name": p.get("display_name"),
             "side": p.get("side"), "quantity": p.get("quantity")}
            for p in open_positions
        ],
        "would_open": (
            [f"{SYMBOL} {expiry} {strike:g}CE SELL {LOTS} lot",
             f"{SYMBOL} {expiry} {strike:g}PE SELL {LOTS} lot"] if strike and expiry else []
        ),
        "reason": None if (spot and expiry and strike) else (
            "Live spot unavailable" if not spot else expiry_note if not expiry else strike_note
        ),
    }


async def run_roll(dhan: DhanClient | None, trigger: str = "scheduler") -> dict:
    """Close the account's NIFTY option book, then sell the next-week ATM straddle.

    Everything that can be validated is validated BEFORE the first exit, so a failure
    to resolve data can never leave the account flat.
    """
    started = _now_utc()
    acct = await _target_account()
    if acct is None:
        return await _record(trigger, "skipped", started, None,
                             f"No F&O paper account named {ACCOUNT_NAME!r} — nothing to roll.")
    account_id = acct["account_id"]

    # ---- resolve everything first -------------------------------------------------
    spot = await _underlying_spot(dhan, SYMBOL)
    if not spot:
        return await _record(trigger, "aborted", started, account_id,
                             f"Live {SYMBOL} spot unavailable — refusing to roll on a price we do not have.")
    expiry, expiry_note = await resolve_expiry(dhan)
    if expiry is None:
        return await _record(trigger, "aborted", started, account_id, expiry_note)
    strike, strike_note = await resolve_atm_strike(expiry, spot)
    if strike is None:
        return await _record(trigger, "aborted", started, account_id, strike_note)

    # ---- close ---------------------------------------------------------------------
    closed, close_errors = [], []
    for pos in await _open_option_positions(account_id):
        try:
            await exit_position(dhan, account_id, pos["position_id"])
            closed.append(pos.get("display_name") or pos["position_id"])
        except (OrderError, Exception) as exc:  # noqa: BLE001
            close_errors.append(f"{pos.get('display_name')}: {getattr(exc, 'detail', str(exc))}")
    if close_errors:
        # Re-opening on top of a book we failed to flatten would double the position.
        return await _record(trigger, "failed", started, account_id,
                             "Could not close the existing book, so nothing was re-opened: "
                             + "; ".join(close_errors), closed=closed)

    # ---- re-open -------------------------------------------------------------------
    legs = [
        {"instrument_kind": "OPTION", "symbol": SYMBOL, "expiry": expiry, "strike": strike,
         "option_type": ot, "transaction_type": "SELL", "lots": LOTS}
        for ot in ("CE", "PE")
    ]
    try:
        result = await execute_basket(dhan, account_id, legs, PRODUCT_TYPE)
    except (OrderError, Exception) as exc:  # noqa: BLE001
        return await _record(
            trigger, "failed", started, account_id,
            f"Closed {len(closed)} leg(s) but could NOT open the new straddle "
            f"({SYMBOL} {expiry} {strike:g}): {getattr(exc, 'detail', str(exc))}. "
            "The account is currently FLAT; the next tick inside the grace window will retry.",
            closed=closed,
        )

    opened = [p.get("display_name") for p in result.get("positions", [])]
    return await _record(
        trigger, "rolled", started, account_id,
        f"Closed {len(closed)} leg(s); sold {LOTS} lot ATM {strike:g}CE + {strike:g}PE "
        f"of {expiry} at spot {spot:,.2f}.",
        closed=closed, opened=opened, expiry=expiry, strike=strike, spot=spot,
        margin_added=result.get("margin_added"), net_premium=result.get("net_premium"),
    )


async def _record(trigger: str, status: str, started: datetime, account_id: str | None,
                  message: str, **extra) -> dict:
    """One log row per attempt, and the day is marked done ONLY on a clean roll."""
    doc = {
        "roll_id": uuid4().hex[:12], "trigger": trigger, "status": status,
        "account_id": account_id, "account_name": ACCOUNT_NAME, "symbol": SYMBOL,
        "configured_account": ACCOUNT_NAME,
        "message": message, "started_at": started, "finished_at": _now_utc(),
        "trading_date": _today_ist().isoformat(),
        **extra,
    }
    await fno_auto_roll_log_collection.insert_one(dict(doc))
    update = {"last_status": status, "last_message": message, "last_run_at": _now_utc(),
              "last_trigger": trigger, "enabled": ENABLED, "account_name": ACCOUNT_NAME,
              "roll_time": ROLL_HHMM, "lots": LOTS, "symbol": SYMBOL}
    if status == "rolled":
        update["last_rolled_on"] = _today_ist().isoformat()
    await fno_auto_roll_state_collection.update_one({"_id": STATE_ID}, {"$set": update}, upsert=True)
    doc.pop("_id", None)
    (logger.info if status == "rolled" else logger.warning)("[fno-auto-roll] %s — %s", status, message)
    return doc


async def status() -> dict:
    state = await fno_auto_roll_state_collection.find_one({"_id": STATE_ID}) or {}
    recent = [
        {k: (v.isoformat() if isinstance(v, datetime) else v)
         for k, v in doc.items() if k != "_id"}
        async for doc in fno_auto_roll_log_collection.find({}).sort("finished_at", -1).limit(20)
    ]
    acct, how = await resolve_account()
    snap = await summary(acct["account_id"]) if acct else None
    now = datetime.now(IST)
    return {
        "enabled": ENABLED,
        "account_name": ACCOUNT_NAME,
        "account_found": acct is not None,
        "account_id": acct["account_id"] if acct else None,
        # The name the roller is ACTUALLY trading, which may differ from the configured
        # one when it bound by prefix. The panel keys its visibility off this — keying it
        # off the configured name is why the failure stayed invisible for eighteen days.
        "matched_account_name": acct.get("name") if acct else None,
        "matched_by": how,
        "binding_note": {
            "id": "Pinned to this account by id — a rename cannot break it.",
            "exact": "Bound by an exact name match.",
            "prefix": f"Bound by prefix: the configured name is {ACCOUNT_NAME!r} and this "
                      f"account's name starts with it. Set FNO_AUTO_ROLL_ACCOUNT_ID to "
                      f"pin it properly.",
            "ambiguous": f"More than one account's name starts with {ACCOUNT_NAME!r}, so "
                         f"the roller will not guess between them. Rename all but one, or "
                         f"set FNO_AUTO_ROLL_ACCOUNT_ID.",
            "none": f"No account matches {ACCOUNT_NAME!r}. NOTHING IS BEING AUTO-TRADED. "
                    f"Rename an account to that, or set FNO_AUTO_ROLL_ACCOUNT_ID.",
        }.get(how),
        "symbol": SYMBOL, "lots": LOTS, "product_type": PRODUCT_TYPE,
        "roll_time_ist": ROLL_HHMM, "grace_minutes": GRACE_MINUTES,
        "min_days_to_expiry": MIN_DAYS_TO_EXPIRY,
        "holidays": sorted(HOLIDAYS),
        "now_ist": now.strftime("%Y-%m-%d %H:%M:%S"),
        "is_trading_day": is_trading_day(now),
        "rolled_today": state.get("last_rolled_on") == _today_ist().isoformat(),
        "last_status": state.get("last_status"),
        "last_message": state.get("last_message"),
        "last_run_at": state["last_run_at"].isoformat() if state.get("last_run_at") else None,
        "last_rolled_on": state.get("last_rolled_on"),
        "account_summary": snap,
        "recent": recent,
    }


# --------------------------------------------------------------------------------
# Scheduler
# --------------------------------------------------------------------------------


def _is_due(now: datetime, rolled_today: bool) -> bool:
    if rolled_today or not is_trading_day(now):
        return False
    hhmm = now.strftime("%H:%M")
    if hhmm < ROLL_HHMM:
        return False
    slot = now.replace(hour=int(ROLL_HHMM[:2]), minute=int(ROLL_HHMM[3:]), second=0, microsecond=0)
    # Past the grace window the roll is stale: firing a 15:00 straddle at 15:29 (or
    # after the close) is a different trade than the one being tested, so it is skipped
    # and the day simply goes unrolled rather than half-executed at the bell.
    return now - slot <= timedelta(minutes=GRACE_MINUTES)


async def _dhan_or_none():
    from app.api.deps import get_current_user
    from app.api.routes.broker import _get_dhan_client

    try:
        user = await get_current_user()
        return await _get_dhan_client(str(user["_id"]))
    except Exception:  # noqa: BLE001
        return None


async def fno_auto_roll_loop() -> None:
    logger.info(
        "[fno-auto-roll] armed for account %r — %s %d lot ATM straddle, roll at %s IST, "
        "expiry >= %d days out",
        ACCOUNT_NAME, SYMBOL, LOTS, ROLL_HHMM, MIN_DAYS_TO_EXPIRY,
    )
    while True:
        try:
            now = datetime.now(IST)
            state = await fno_auto_roll_state_collection.find_one({"_id": STATE_ID}) or {}
            rolled_today = state.get("last_rolled_on") == now.date().isoformat()
            if _is_due(now, rolled_today):
                await run_roll(await _dhan_or_none(), trigger="scheduler")
        except Exception:
            logger.exception("[fno-auto-roll] tick failed — will retry next tick")
        await asyncio.sleep(TICK_SECONDS)
