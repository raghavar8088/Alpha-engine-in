"""Morning-momentum option buying on F&O stocks, for one F&O paper account.

THE RULE, as specified:
  At 09:20, 09:30 and 10:00 IST on every active trading day, scan all ~208 F&O stocks
  against their previous close:
      up   more than 2%  ->  BUY a CALL on it
      down more than 2%  ->  BUY a PUT  on it
  Pick the strike whose whole position costs under Rs10,000. Stop at -Rs5,000, target at
  +Rs5,000 on the position's rupees; whichever hits first closes it. Anything still open at
  15:10 is squared off the same day.

  The later checkpoints only add NEW names: a stock already holding an open position from
  09:20 is not bought again at 09:30 or 10:00.

WHY BUYING, NOT SELLING: every position is a long option, so the most it can lose is the
premium paid — which is what makes "however many stocks qualify" survivable. The Rs5,000
stop usually binds first, but on a gap the premium is still the floor.

RATE LIMITS: the scan is one batched sweep for all 208 spots, and the candidate premiums
for a checkpoint are priced in batched 50-token chunks — not one call per contract. This
desk shares Angel's quota with every other module, and a per-contract loop here is exactly
what took the option chain down once already.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from app.core.db import (
    fno_accounts_collection,
    fno_positions_collection,
    instruments_collection,
    momentum_buy_state_collection,
)
from app.services.buy_low_options import scan_falls
from app.services.fno_positions import exit_position, place_order
from app.services.stock_options import batched_ltp, current_expiry

logger = logging.getLogger("morning_momentum")

IST = timezone(timedelta(hours=5, minutes=30))
STATE_ID = "morning_momentum"

ENABLED = os.getenv("MM_ENABLED", "1").lower() not in ("0", "false", "")
ACCOUNT_NAME = os.getenv(
    "MM_ACCOUNT", "5LAKH , OPTION BUYING MORNING MOMENTUM STCOKS 2% UP INITIAL 5 TO 15 MINUTES")
ACCOUNT_ID = os.getenv("MM_ACCOUNT_ID", "")
# "repeat at 10" in a morning-momentum rule means 10:00 AM, not 22:00.
CHECKPOINTS = [c.strip() for c in os.getenv("MM_CHECKPOINTS", "09:20,09:30,10:00").split(",") if c.strip()]
CHECKPOINT_GRACE_MIN = int(os.getenv("MM_GRACE_MINUTES", "6"))
MOVE_PCT = float(os.getenv("MM_MOVE_PCT", "2.0"))
MAX_COST = float(os.getenv("MM_MAX_COST", "10000"))
TARGET_RUPEES = float(os.getenv("MM_TARGET", "5000"))
STOP_RUPEES = float(os.getenv("MM_STOP", "5000"))
SQUAREOFF = os.getenv("MM_SQUAREOFF", "15:10")
LOTS = int(os.getenv("MM_LOTS", "1"))
PRODUCT = os.getenv("MM_PRODUCT", "MARGIN")
MAX_STRIKES_SCAN = int(os.getenv("MM_MAX_STRIKES", "10"))
ORDER_PACE = float(os.getenv("MM_PACE", "0.4"))


class MomentumError(Exception):
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


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def due_checkpoint(done: list[str]) -> str | None:
    """The checkpoint we are inside now and have not already run today."""
    now = _mins(_hhmm())
    for cp in CHECKPOINTS:
        if cp in done:
            continue
        start = _mins(cp)
        if start <= now <= start + CHECKPOINT_GRACE_MIN:
            return cp
    return None


async def target_account() -> dict:
    if ACCOUNT_ID:
        a = await fno_accounts_collection.find_one({"account_id": ACCOUNT_ID})
        if a:
            return a
    a = await fno_accounts_collection.find_one({"name": ACCOUNT_NAME})
    if a is None:
        async for c in fno_accounts_collection.find({}):
            if (c.get("name") or "").split() == ACCOUNT_NAME.split():
                return c
        raise MomentumError(f"No F&O account named {ACCOUNT_NAME!r} — create it first.")
    return a


# ── candidate selection ──────────────────────────────────────────────────────────


async def _pick_contract(symbol: str, spot: float, kind: str) -> tuple[dict, float] | None:
    """The cheapest tradable strike costing under MAX_COST, walking outward from ATM.

    A CALL walks UP the ladder and a PUT walks DOWN — further out is cheaper — so the
    first strike inside the budget is also the closest one we can afford."""
    expiry = await current_expiry(symbol)
    if not expiry:
        return None
    q = {"asset_class": "EQUITY_OPTION", "underlying_symbol": symbol,
         "expiry": expiry, "option_type": kind}
    order = 1 if kind == "CE" else -1
    q["strike"] = {"$gte": spot} if kind == "CE" else {"$lte": spot}
    rows = [d async for d in instruments_collection.find(
        q, {"symbol": 1, "strike": 1, "lot_size": 1, "angel_token": 1, "angel_tradingsymbol": 1}
    ).sort("strike", order).limit(MAX_STRIKES_SCAN)]
    if not rows:
        return None
    prices = await batched_ltp({"NFO": [str(r["angel_token"]) for r in rows]})
    for r in rows:
        prem = prices.get(str(r["angel_token"]))
        lot = int(r.get("lot_size") or 0)
        if not prem or prem <= 0 or lot <= 0:
            continue
        cost = prem * lot * LOTS
        if cost <= MAX_COST:
            return {**r, "expiry": expiry, "premium": prem, "cost": cost, "lot": lot}, cost
    return None


async def _already_open(account_id: str, symbol: str) -> bool:
    return await fno_positions_collection.find_one(
        {"account_id": account_id, "status": "OPEN",
         "instrument.underlying_symbol": symbol}) is not None


# ── the checkpoint run ───────────────────────────────────────────────────────────


async def run_checkpoint(dhan, account_id: str, checkpoint: str) -> dict:
    rows = await scan_falls()                    # one batched sweep for all 208 spots
    if not rows:
        return {"checkpoint": checkpoint, "bought": 0, "candidates": 0,
                "notes": ["no F&O quotes this cycle"]}

    ups = [r for r in rows if r["change_pct"] >= MOVE_PCT]
    downs = [r for r in rows if r["change_pct"] <= -MOVE_PCT]
    cands = [(r, "CE") for r in ups] + [(r, "PE") for r in downs]

    bought = skipped = failed = 0
    notes: list[str] = []
    picks: list[dict] = []
    for r, kind in cands:
        sym = r["symbol"]
        # Later checkpoints only add NEW names.
        if await _already_open(account_id, sym):
            skipped += 1
            continue
        chosen = await _pick_contract(sym, r["ltp"], kind)
        if not chosen:
            skipped += 1
            if len(notes) < 5:
                notes.append(f"{sym} {kind}: no strike under Rs{MAX_COST:,.0f}")
            continue
        c, cost = chosen
        try:
            await place_order(
                dhan, account_id=account_id, instrument_kind="OPTION", symbol=sym,
                expiry=c["expiry"], transaction_type="BUY", lots=LOTS, order_type="MARKET",
                product_type=PRODUCT, strike=c["strike"], option_type=kind,
            )
            bought += 1
            picks.append({"symbol": sym, "type": kind, "strike": c["strike"],
                          "change_pct": r["change_pct"], "premium": round(c["premium"], 2),
                          "cost": round(cost, 2)})
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if len(notes) < 6:
                notes.append(f"{sym} {c['strike']:g}{kind}: {getattr(exc, 'detail', str(exc))}")
        await asyncio.sleep(ORDER_PACE)

    return {"checkpoint": checkpoint, "scanned": len(rows), "up": len(ups), "down": len(downs),
            "candidates": len(cands), "bought": bought, "skipped": skipped, "failed": failed,
            "picks": picks, "notes": notes}


async def manage(dhan, account_id: str) -> dict:
    """Mark the book and exit on target / stop / the 15:10 square-off."""
    pos = [p async for p in fno_positions_collection.find(
        {"account_id": account_id, "status": "OPEN"})]
    if not pos:
        return {"managed": 0, "closed": 0}

    toks: list[str] = []
    tok_of: dict[str, str] = {}
    for p in pos:
        sid = str(p["instrument"].get("security_id"))
        d = await instruments_collection.find_one(
            {"security_id": sid, "angel_token": {"$ne": None}}, {"angel_token": 1})
        if d:
            tok_of[p["position_id"]] = str(d["angel_token"])
            toks.append(str(d["angel_token"]))
    prices = await batched_ltp({"NFO": toks}) if toks else {}

    eod = _hhmm() >= SQUAREOFF
    closed = 0
    for p in pos:
        tok = tok_of.get(p["position_id"])
        ltp = prices.get(tok) if tok else None
        reason = None
        if ltp is not None:
            # long option: P&L is (now - paid) * quantity
            pnl = (ltp - p["avg_price"]) * p["quantity"]
            if pnl >= TARGET_RUPEES:
                reason = "target"
            elif pnl <= -STOP_RUPEES:
                reason = "stoploss"
        if reason is None and eod:
            reason = "eod"
        if reason:
            try:
                await exit_position(dhan, account_id, p["position_id"])
                closed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("mm: could not exit %s (%s)", p.get("display_name"), exc)
            await asyncio.sleep(ORDER_PACE)
    return {"managed": len(pos), "closed": closed}


async def run_cycle(force_checkpoint: str | None = None) -> dict:
    if not ENABLED:
        return {"ran": False, "reason": "disabled"}
    acct = await target_account()
    account_id = acct["account_id"]
    session = _today()

    st = await momentum_buy_state_collection.find_one({"_id": STATE_ID}) or {}
    done = st.get("done", []) if st.get("session") == session else []

    from app.api.deps import get_current_user
    from app.api.routes.broker import _get_dhan_client
    try:
        user = await get_current_user()
        dhan = await _get_dhan_client(str(user["_id"]))
    except Exception:  # noqa: BLE001
        dhan = None

    managed = await manage(dhan, account_id)

    cp = force_checkpoint or (due_checkpoint(done) if _trading_day() else None)
    if not cp:
        await momentum_buy_state_collection.update_one(
            {"_id": STATE_ID},
            {"$set": {"session": session, "done": done, "last_run_at": _now(),
                      "last_managed": managed}}, upsert=True)
        return {"ran": False, "reason": f"no checkpoint due (now {_hhmm()} IST, done {done})",
                "managed": managed}

    result = await run_checkpoint(dhan, account_id, cp)
    done = sorted(set(done + [cp]))
    await momentum_buy_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {"session": session, "done": done, "last_run_at": _now(),
                  "last_checkpoint": result, "last_managed": managed}}, upsert=True)
    logger.warning("[morning_momentum] %s: bought %s of %s candidates",
                   cp, result["bought"], result["candidates"])
    return {"ran": True, "account": acct.get("name"), "managed": managed, **result}


async def status() -> dict:
    try:
        acct = await target_account()
    except MomentumError as exc:
        return {"configured": False, "reason": exc.detail}
    st = await momentum_buy_state_collection.find_one({"_id": STATE_ID}) or {}
    session = _today()
    done = st.get("done", []) if st.get("session") == session else []
    open_n = await fno_positions_collection.count_documents(
        {"account_id": acct["account_id"], "status": "OPEN"})
    return {
        "configured": True, "enabled": ENABLED,
        "account": acct.get("name"), "account_id": acct["account_id"],
        "initial_capital": acct.get("initial_capital"),
        "checkpoints": CHECKPOINTS, "done_today": done,
        "move_pct": MOVE_PCT, "max_cost": MAX_COST,
        "target_rupees": TARGET_RUPEES, "stop_rupees": STOP_RUPEES,
        "squareoff": SQUAREOFF, "lots": LOTS,
        "open_positions": open_n,
        "now_ist": _hhmm(),
        "next_due": due_checkpoint(done),
        "last_run_at": st.get("last_run_at").isoformat() if st.get("last_run_at") else None,
        "last_checkpoint": st.get("last_checkpoint"), "last_managed": st.get("last_managed"),
    }


async def preview() -> dict:
    """Who would be bought right now, without placing anything."""
    acct = await target_account()
    rows = await scan_falls()
    ups = [r for r in rows if r["change_pct"] >= MOVE_PCT]
    downs = [r for r in rows if r["change_pct"] <= -MOVE_PCT]
    out = []
    for r, kind in [(x, "CE") for x in ups[:10]] + [(x, "PE") for x in downs[:10]]:
        if await _already_open(acct["account_id"], r["symbol"]):
            continue
        c = await _pick_contract(r["symbol"], r["ltp"], kind)
        out.append({"symbol": r["symbol"], "change_pct": r["change_pct"], "type": kind,
                    "strike": c[0]["strike"] if c else None,
                    "cost": round(c[1], 2) if c else None,
                    "affordable": bool(c)})
    return {"account": acct.get("name"), "scanned": len(rows),
            "up_over_pct": len(ups), "down_over_pct": len(downs), "candidates": out}
