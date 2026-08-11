"""Daily ATM short-straddle roll across the WHOLE stock-option universe.

Sibling of `fno_auto_roll`, which rolls a single NIFTY straddle on its own account. This
module does the same job for every option-enabled STOCK, on its own account, and keeps
that module's central safety rule: resolve every contract BEFORE closing anything, so a
quote outage can never flatten the account and then fail to re-open it.

Every active trading day at 15:00 IST:
  1. close every open position in the target account, then
  2. sell the ATM CALL and ATM PUT, 1 lot each, on every option-enabled stock
     (~208 underlyings, so ~416 short legs), on the current month's expiry.

EXPIRY RULE: use the current month's expiry unless it is less than 5 days away, in which
case use the next month's — rolling into a contract about to expire would put the whole
book into gamma the day after it opens.

WHAT THIS POSITION IS, PLAINLY: ~416 NAKED short option legs. A short straddle's loss is
unbounded on the upside and bounded only by the strike on the downside, and this holds one
on every F&O stock at once, so a single gap-heavy session hits the whole book the same
way. That is a real tail, not a theoretical one. It is paper money here, and the account
carries Rs10 crore against the SPAN-style margin the desk models — but nothing about the
structure gets safer at size.

The roll is idempotent per session: it records the session it last rolled and refuses to
run twice on the same day, so a scheduler retry cannot double the book.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from app.core.db import (
    fno_accounts_collection,
    fno_positions_collection,
    fno_stock_roll_log_collection,
    fno_stock_roll_state_collection,
    instruments_collection,
)
from app.services.dhan_client import DhanClient
from app.services.fno_positions import exit_position, place_order
from app.services.stock_options import batched_ltp

logger = logging.getLogger("fno_stock_roll")

IST = timezone(timedelta(hours=5, minutes=30))
STATE_ID = "fno_stock_roll"

ENABLED = os.getenv("FNO_STOCK_ROLL_ENABLED", "1").lower() not in ("0", "false", "")
ACCOUNT_NAME = os.getenv("FNO_STOCK_ROLL_ACCOUNT", "AUTO SELLING STOCKS  ATM DAILY 10 CR")
ACCOUNT_ID = os.getenv("FNO_STOCK_ROLL_ACCOUNT_ID", "")
ROLL_FROM = os.getenv("FNO_STOCK_ROLL_FROM", "15:00")
ROLL_TO = os.getenv("FNO_STOCK_ROLL_TO", "15:25")
MIN_DAYS_TO_EXPIRY = int(os.getenv("FNO_STOCK_ROLL_MIN_DTE", "5"))
LOTS = int(os.getenv("FNO_STOCK_ROLL_LOTS", "1"))
PRODUCT = os.getenv("FNO_STOCK_ROLL_PRODUCT", "MARGIN")
ORDER_PACE = float(os.getenv("FNO_STOCK_ROLL_PACE", "0.12"))


class StockRollError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return date.today().isoformat()


def _hhmm() -> str:
    return datetime.now(IST).strftime("%H:%M")


def _trading_day() -> bool:
    return datetime.now(IST).weekday() < 5


async def target_account() -> dict:
    if ACCOUNT_ID:
        a = await fno_accounts_collection.find_one({"account_id": ACCOUNT_ID})
        if a:
            return a
    a = await fno_accounts_collection.find_one({"name": ACCOUNT_NAME})
    if a is None:
        # tolerate whitespace drift in the account name (it has a double space today)
        async for c in fno_accounts_collection.find({}):
            if (c.get("name") or "").split() == ACCOUNT_NAME.split():
                return c
        raise StockRollError(f"No F&O account named {ACCOUNT_NAME!r} — create it first.")
    return a


# ── contract choice ──────────────────────────────────────────────────────────────


async def choose_expiry(symbol: str) -> tuple[str | None, str]:
    """Nearest expiry at least MIN_DAYS_TO_EXPIRY away, else the one after it."""
    today = date.today()
    exps = sorted(e for e in await instruments_collection.distinct(
        "expiry", {"asset_class": "EQUITY_OPTION", "underlying_symbol": symbol})
        if e and e >= today.isoformat())
    if not exps:
        return None, "no listed expiry"
    near = exps[0]
    dte = (date.fromisoformat(near) - today).days
    if dte >= MIN_DAYS_TO_EXPIRY:
        return near, f"{near} ({dte}d out)"
    if len(exps) > 1:
        nxt = exps[1]
        return nxt, f"{nxt} — skipped {near}, only {dte}d away"
    return near, f"{near} ({dte}d out, no later expiry listed)"


async def _atm_strike(symbol: str, expiry: str, spot: float) -> float | None:
    """Nearest strike that has BOTH a CE and a PE listed.

    The ladders are not symmetric — plenty of strikes exist on one side only — so picking
    the nearest strike overall gets a contract-not-found on the missing leg and leaves a
    naked single option where a straddle was intended. Intersecting the two sides is what
    makes the pair actually buildable; 162 of 416 legs failed before this.
    """
    base = {"asset_class": "EQUITY_OPTION", "underlying_symbol": symbol, "expiry": expiry}
    ce = set(await instruments_collection.distinct("strike", {**base, "option_type": "CE"}))
    pe = set(await instruments_collection.distinct("strike", {**base, "option_type": "PE"}))
    both = [s for s in (ce & pe) if s]
    return min(both, key=lambda s: abs(s - spot)) if both else None


async def resolve_all() -> tuple[list[dict], dict]:
    """Every straddle we intend to sell, worked out BEFORE the open book is touched."""
    unders = sorted(u for u in await instruments_collection.distinct(
        "underlying_symbol", {"asset_class": "EQUITY_OPTION"}) if u)
    eq = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": unders}, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1})}
    spots = await batched_ltp({"NSE": [str(d["angel_token"]) for d in eq.values()]})
    tok2sym = {str(d["angel_token"]): s for s, d in eq.items()}
    spot_by = {tok2sym[t]: p for t, p in spots.items() if t in tok2sym}

    plans: list[dict] = []
    skipped: list[str] = []
    for sym in unders:
        spot = spot_by.get(sym)
        if not spot:
            skipped.append(f"{sym}: no live spot")
            continue
        expiry, why = await choose_expiry(sym)
        if not expiry:
            skipped.append(f"{sym}: {why}")
            continue
        strike = await _atm_strike(sym, expiry, spot)
        if strike is None:
            skipped.append(f"{sym}: no listed strike near {spot:g}")
            continue
        plans.append({"symbol": sym, "spot": round(spot, 2), "expiry": expiry,
                      "strike": strike, "why": why})
    return plans, {"underlyings": len(unders), "priced": len(spot_by), "planned": len(plans),
                   "skipped": len(skipped), "skipped_examples": skipped[:6]}


# ── close / open ─────────────────────────────────────────────────────────────────


async def close_all(dhan: DhanClient | None, account_id: str) -> dict:
    pos = [p async for p in fno_positions_collection.find({"account_id": account_id, "status": "OPEN"})]
    closed = failed = 0
    errs: list[str] = []
    for p in pos:
        try:
            await exit_position(dhan, account_id, p["position_id"])
            closed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if len(errs) < 5:
                errs.append(f"{p.get('display_name')}: {getattr(exc, 'detail', str(exc))}")
        await asyncio.sleep(ORDER_PACE)
    return {"was_open": len(pos), "closed": closed, "failed": failed, "errors": errs}


async def sell_straddles(dhan: DhanClient | None, account_id: str, plans: list[dict]) -> dict:
    sold = failed = 0
    errs: list[str] = []
    for p in plans:
        for kind in ("CE", "PE"):
            try:
                await place_order(
                    dhan, account_id=account_id, instrument_kind="OPTION", symbol=p["symbol"],
                    expiry=p["expiry"], transaction_type="SELL", lots=LOTS, order_type="MARKET",
                    product_type=PRODUCT, strike=p["strike"], option_type=kind,
                )
                sold += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                if len(errs) < 6:
                    errs.append(f"{p['symbol']} {p['strike']:g}{kind}: {getattr(exc, 'detail', str(exc))}")
            await asyncio.sleep(ORDER_PACE)
    return {"straddles": len(plans), "sold": sold, "failed": failed, "errors": errs}


async def _log(session: str, started: datetime, status_: str, account_id: str | None, payload: dict) -> None:
    await fno_stock_roll_log_collection.insert_one({
        "session": session, "started_at": started, "finished_at": _now(),
        "status": status_, "account_id": account_id,
        "summary": {k: v for k, v in payload.items() if k != "meta"}, "meta": payload.get("meta"),
    })


async def roll(force: bool = False, trigger: str = "scheduler") -> dict:
    acct = await target_account()
    account_id = acct["account_id"]
    session = _today()
    started = _now()

    st = await fno_stock_roll_state_collection.find_one({"_id": STATE_ID}) or {}
    if not force:
        if not _trading_day():
            return {"ran": False, "reason": "not a trading day", "account": acct.get("name")}
        if not (ROLL_FROM <= _hhmm() <= ROLL_TO):
            return {"ran": False, "reason": f"outside the {ROLL_FROM}-{ROLL_TO} IST window (now {_hhmm()})",
                    "account": acct.get("name")}
        if st.get("last_session") == session:
            return {"ran": False, "reason": f"already rolled today ({session})", "account": acct.get("name")}

    from app.api.deps import get_current_user
    from app.api.routes.broker import _get_dhan_client
    try:
        user = await get_current_user()
        dhan = await _get_dhan_client(str(user["_id"]))
    except Exception:  # noqa: BLE001
        dhan = None      # premiums come from Angel; Dhan is only a quote fallback

    # 1) RESOLVE FIRST — never close a book we cannot replace
    plans, meta = await resolve_all()
    if not plans:
        out = {"ran": False, "reason": "resolved no straddles — nothing was closed", "meta": meta}
        await _log(session, started, "aborted", account_id, out)
        return out

    # 2) close
    closed = await close_all(dhan, account_id)
    if closed["was_open"] and closed["closed"] == 0:
        out = {"ran": False, "reason": "could not close the existing book — nothing re-opened",
               "closed": closed, "meta": meta}
        await _log(session, started, "failed", account_id, out)
        return out

    # 3) re-open
    opened = await sell_straddles(dhan, account_id, plans)

    await fno_stock_roll_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {"last_session": session, "last_run_at": _now(), "account_id": account_id,
                  "account_name": acct.get("name"), "closed": closed, "opened": opened,
                  "meta": meta, "trigger": trigger}},
        upsert=True)
    out = {"ran": True, "session": session, "account": acct.get("name"), "account_id": account_id,
           "closed": closed, "opened": opened, "meta": meta}
    await _log(session, started, "ok", account_id, out)
    logger.warning("[fno_stock_roll] closed %s, sold %s legs (%s failed) across %s straddles",
                   closed["closed"], opened["sold"], opened["failed"], opened["straddles"])
    return out


async def status() -> dict:
    try:
        acct = await target_account()
    except StockRollError as exc:
        return {"configured": False, "reason": exc.detail}
    st = await fno_stock_roll_state_collection.find_one({"_id": STATE_ID}) or {}
    open_n = await fno_positions_collection.count_documents(
        {"account_id": acct["account_id"], "status": "OPEN"})
    sample, why = await choose_expiry("RELIANCE")
    return {
        "configured": True, "enabled": ENABLED,
        "account": acct.get("name"), "account_id": acct["account_id"],
        "initial_capital": acct.get("initial_capital"),
        "roll_window": f"{ROLL_FROM}-{ROLL_TO} IST",
        "min_days_to_expiry": MIN_DAYS_TO_EXPIRY, "lots": LOTS, "product": PRODUCT,
        "open_positions": open_n,
        "last_session": st.get("last_session"),
        "last_run_at": st.get("last_run_at").isoformat() if st.get("last_run_at") else None,
        "last_closed": st.get("closed"), "last_opened": st.get("opened"), "last_meta": st.get("meta"),
        "example_expiry_RELIANCE": sample, "example_expiry_reason": why,
        "rolled_today": st.get("last_session") == _today(),
    }


async def preview() -> dict:
    """What the next roll would do, without touching anything."""
    acct = await target_account()
    plans, meta = await resolve_all()
    open_n = await fno_positions_collection.count_documents(
        {"account_id": acct["account_id"], "status": "OPEN"})
    return {"account": acct.get("name"), "would_close": open_n,
            "would_sell_legs": len(plans) * 2, "straddles": len(plans),
            "meta": meta, "sample": plans[:10]}
