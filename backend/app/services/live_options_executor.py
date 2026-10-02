"""Real-money readiness for NIFTY option strategies (U6 of the 2026-10-02 Pre-Live plan).

SHIPS DISARMED, AND CANNOT BE ARMED TODAY. Real orders need ALL of:
  1. a CONFIRMED forward verdict for the hypothesis in app.services.option_hypotheses —
     earned on forward REAL-money paper P&L; at registration nothing is confirmed;
  2. LIVE_OPTIONS_ENABLED=1 in the server environment (default 0);
  3. the user arming it, authenticated, typing the confirmation phrase;
  4. LIVE_OPTIONS_DRY_RUN=0 (default 1: orders are recorded as SIMULATED, never sent).
Every check below runs before every opening order:
  - kill switch off; armed for THIS hypothesis
  - 1-lot cap: no leg larger than LIVE_OPTIONS_MAX_LOTS (default 1) lots
  - daily loss cap: realized + open loss today < LIVE_OPTIONS_DAILY_LOSS_CAP (default Rs5,000)
  - margin: Angel's available cash covers ask x qty + 2% + charges (option buying is
    premium-only, so this is the whole requirement)
  - market hours on an NSE trading day
Closing orders are always allowed (a real position must always be able to exit), even when
disarmed — only the kill switch's PANIC path and closes may send orders after disarming.
Three consecutive rejected orders auto-disarm. Every real fill is compared with the paper
reference price at the same moment (the ask for a buy, the bid for a sell) — the
paper-vs-real slippage monitor — and a mean slippage beyond LIVE_OPTIONS_SLIPPAGE_ALARM_PCT
over the last 20 orders raises an alarm and disarms.
"""

from __future__ import annotations

import asyncio
import logging
import os
import statistics
from datetime import datetime, timedelta, timezone

from app.core.db import db
from app.services import market_calendar
from tradingai_shared.option_fees import option_round_trip

logger = logging.getLogger("live_options_executor")

IST = timezone(timedelta(hours=5, minutes=30))
ENABLED = os.getenv("LIVE_OPTIONS_ENABLED", "0").lower() in ("1", "true", "yes")
DRY_RUN = os.getenv("LIVE_OPTIONS_DRY_RUN", "1").lower() not in ("0", "false", "no")
MAX_LOTS = int(os.getenv("LIVE_OPTIONS_MAX_LOTS", "1"))
DAILY_LOSS_CAP = float(os.getenv("LIVE_OPTIONS_DAILY_LOSS_CAP", "5000"))
SLIPPAGE_ALARM_PCT = float(os.getenv("LIVE_OPTIONS_SLIPPAGE_ALARM_PCT", "2.0"))
MAX_CONSECUTIVE_REJECTS = 3
CONFIRM_PHRASE = "ARM REAL MONEY"
state = db["live_options_state"]
orders = db["live_options_orders"]
lpositions = db["live_options_positions"]
STATE_ID = "engine"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_state() -> dict:
    st = await state.find_one({"_id": STATE_ID}) or {}
    return {"armed": bool(st.get("armed")), "armed_hypothesis": st.get("armed_hypothesis"),
            "kill_switch": bool(st.get("kill_switch")), "consecutive_rejects": st.get("consecutive_rejects", 0),
            "disarmed_reason": st.get("disarmed_reason"), "armed_at": st.get("armed_at"), "armed_by": st.get("armed_by"),
            "env_enabled": ENABLED, "dry_run": DRY_RUN, "max_lots": MAX_LOTS, "daily_loss_cap": DAILY_LOSS_CAP}


async def can_arm(hypothesis: str) -> tuple[bool, list[str]]:
    from app.services.option_hypotheses import hypotheses
    why = []
    h = await hypotheses.find_one({"_id": hypothesis}, {"status": 1})
    if not h:
        why.append(f"{hypothesis} is not a registered hypothesis")
    elif h.get("status") != "CONFIRMED":
        why.append(f"{hypothesis} is {h.get('status')}: only a CONFIRMED forward verdict may trade real money")
    if not ENABLED:
        why.append("LIVE_OPTIONS_ENABLED is not set on the server")
    st = await get_state()
    if st["kill_switch"]:
        why.append("the kill switch is on")
    return (not why), why


async def arm(hypothesis: str, confirm: str, user: str) -> dict:
    ok, why = await can_arm(hypothesis)
    if confirm != CONFIRM_PHRASE:
        why.append(f'type "{CONFIRM_PHRASE}" to confirm')
        ok = False
    if not ok:
        return {"armed": False, "refused": why}
    await state.update_one({"_id": STATE_ID}, {"$set": {"armed": True, "armed_hypothesis": hypothesis, "armed_at": _now(),
                                                        "armed_by": user, "consecutive_rejects": 0, "disarmed_reason": None}},
                           upsert=True)
    logger.warning("[live_options] ARMED for %s by %s (dry_run=%s)", hypothesis, user, DRY_RUN)
    return {"armed": True, "hypothesis": hypothesis, "dry_run": DRY_RUN}


async def disarm(reason: str) -> dict:
    await state.update_one({"_id": STATE_ID}, {"$set": {"armed": False, "disarmed_reason": reason, "updated_at": _now()}},
                           upsert=True)
    logger.warning("[live_options] DISARMED: %s", reason)
    return await get_state()


async def set_kill_switch(active: bool, reason: str = "manual") -> dict:
    await state.update_one({"_id": STATE_ID}, {"$set": {"kill_switch": bool(active), "updated_at": _now()}}, upsert=True)
    if active:
        await disarm(f"kill switch: {reason}")
    return await get_state()


async def today_loss() -> float:
    start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    realized = 0.0
    async for p in lpositions.find({"closed_at": {"$gte": start}}, {"realized_pnl": 1}):
        realized += p.get("realized_pnl") or 0.0
    open_mtm = 0.0
    async for p in lpositions.find({"status": "OPEN"}, {"unrealized_pnl": 1}):
        open_mtm += p.get("unrealized_pnl") or 0.0
    return -(realized + open_mtm)


async def margin_ok(legs: list[dict]) -> tuple[bool, str]:
    from app.services.angel_client import angel_client
    need = sum(leg["ref_price"] * leg["qty"] * 1.02 + option_round_trip(leg["ref_price"], leg["ref_price"], leg["qty"])["total"]
               for leg in legs if leg["side"] == "BUY")
    try:
        funds = await angel_client.funds()
        avail = float(funds.get("availablecash") or 0)
    except Exception as exc:  # noqa: BLE001 - no margin read = no order
        return False, f"could not read Angel funds: {exc}"
    return avail >= need, f"available Rs{avail:,.0f}, needed Rs{need:,.0f}"


async def _fill_price(order_id: str) -> float | None:
    from app.services.angel_client import angel_client
    for _ in range(10):
        await asyncio.sleep(1)
        try:
            for t in await angel_client.trade_book():
                if str(t.get("orderid")) == str(order_id):
                    return float(t.get("fillprice") or t.get("averageprice") or 0) or None
        except Exception:  # noqa: BLE001
            continue
    return None


async def execute(hypothesis: str, purpose: str, legs: list[dict], product: str = "INTRADAY") -> dict:
    """Send (or, in dry run, record) the real orders for a paper decision.

    legs: [{tradingsymbol, token, exchange, side BUY|SELL, qty, lot_size, ref_price}]
    purpose: "open" (every check applies) or "close" (always allowed)."""
    st = await get_state()
    now = datetime.now(IST)
    if purpose == "open":
        refusals = []
        if st["kill_switch"]:
            refusals.append("kill switch on")
        if not st["armed"] or st["armed_hypothesis"] != hypothesis:
            refusals.append("not armed for this hypothesis")
        if not ENABLED:
            refusals.append("LIVE_OPTIONS_ENABLED off")
        if any(leg["qty"] > leg["lot_size"] * MAX_LOTS for leg in legs):
            refusals.append(f"over the {MAX_LOTS}-lot cap")
        if not (market_calendar.is_trading_day(now) and "09:15" <= now.strftime("%H:%M") <= "15:25"):
            refusals.append("outside market hours")
        if await today_loss() >= DAILY_LOSS_CAP:
            refusals.append(f"daily loss cap Rs{DAILY_LOSS_CAP:,.0f} reached")
        if not refusals:
            ok, msg = await margin_ok(legs)
            if not ok:
                refusals.append(f"margin: {msg}")
        if refusals:
            return {"sent": False, "refused": refusals}
    results = []
    for leg in legs:
        doc = {"hypothesis": hypothesis, "purpose": purpose, "at": _now(), "dry_run": DRY_RUN, **leg}
        if DRY_RUN:
            doc.update({"status": "SIMULATED", "fill": leg["ref_price"], "slippage_pct": 0.0})
        else:
            from app.services.angel_client import angel_client
            try:
                r = await angel_client.place_order(tradingsymbol=leg["tradingsymbol"], symboltoken=leg["token"],
                                                   transactiontype=leg["side"], exchange=leg.get("exchange") or "NFO",
                                                   quantity=leg["qty"], producttype=product)
                oid = (r.get("data") or {}).get("orderid")
                fill = await _fill_price(oid) if oid else None
                sign = 1 if leg["side"] == "BUY" else -1
                slip = sign * (fill - leg["ref_price"]) / leg["ref_price"] * 100 if fill else None
                doc.update({"status": "FILLED" if fill else "PLACED", "order_id": oid, "fill": fill, "slippage_pct": slip})
                await state.update_one({"_id": STATE_ID}, {"$set": {"consecutive_rejects": 0}}, upsert=True)
            except Exception as exc:  # noqa: BLE001 - a reject is recorded, counted, and may disarm
                doc.update({"status": "REJECTED", "error": str(exc)[:300]})
                st2 = await state.find_one_and_update({"_id": STATE_ID}, {"$inc": {"consecutive_rejects": 1}},
                                                      upsert=True, return_document=True)
                if (st2 or {}).get("consecutive_rejects", 0) >= MAX_CONSECUTIVE_REJECTS:
                    await disarm(f"auto-disarmed after {MAX_CONSECUTIVE_REJECTS} consecutive rejects")
        await orders.insert_one(dict(doc))
        results.append({k: v for k, v in doc.items() if k != "_id"})
    await _slippage_watch()
    return {"sent": not DRY_RUN, "dry_run": DRY_RUN, "orders": results}


async def _slippage_watch() -> dict:
    """Paper-vs-real: the mean slippage of the last 20 real fills against the paper price."""
    xs = [o["slippage_pct"] async for o in orders.find({"status": "FILLED", "slippage_pct": {"$ne": None}},
                                                       {"slippage_pct": 1}).sort("at", -1).limit(20)]
    out = {"fills": len(xs), "mean_slippage_pct": round(statistics.mean(xs), 3) if xs else None,
           "alarm_at_pct": SLIPPAGE_ALARM_PCT}
    if len(xs) >= 5 and statistics.mean(xs) > SLIPPAGE_ALARM_PCT:
        out["alarm"] = True
        await disarm(f"slippage alarm: real fills {statistics.mean(xs):.2f}% worse than paper on average")
    return out


async def panic_close_all(reason: str = "panic") -> dict:
    """Square off every open real leg at market, disarm, and trip the kill switch."""
    closed = []
    async for p in lpositions.find({"status": "OPEN"}):
        leg = {"tradingsymbol": p["tradingsymbol"], "token": p["token"], "exchange": p.get("exchange", "NFO"),
               "side": "SELL", "qty": p["qty"], "lot_size": p.get("lot_size", p["qty"]), "ref_price": p.get("last") or 0.05}
        closed.append(await execute(p["hypothesis"], "close", [leg], product=p.get("product", "INTRADAY")))
        await lpositions.update_one({"_id": p["_id"]}, {"$set": {"status": "CLOSED", "closed_at": _now(), "close_reason": reason}})
    await set_kill_switch(True, reason)
    return {"closed": len(closed), "state": await get_state()}


async def readiness() -> dict:
    """What the page shows: state, why each hypothesis can / cannot be armed, slippage."""
    from app.services.option_hypotheses import hypotheses
    rows = []
    async for h in hypotheses.find({}, {"status": 1, "name": 1}).sort("_id", 1):
        ok, why = await can_arm(h["_id"])
        rows.append({"hypothesis": h["_id"], "name": h.get("name"), "status": h.get("status"), "can_arm": ok, "why_not": why})
    recent = [{k: v for k, v in o.items() if k != "_id"} async for o in orders.find({}).sort("at", -1).limit(20)]
    return {"state": await get_state(), "hypotheses": rows, "slippage": await _slippage_watch(), "recent_orders": recent,
            "confirm_phrase": CONFIRM_PHRASE,
            "checks": ["CONFIRMED forward verdict", "LIVE_OPTIONS_ENABLED=1", "user arms with the phrase",
                       "LIVE_OPTIONS_DRY_RUN=0 to send real orders", f"<= {MAX_LOTS} lot a leg",
                       f"daily loss cap Rs{DAILY_LOSS_CAP:,.0f}", "Angel margin covers the premium",
                       "market hours", "kill switch off", f"auto-disarm after {MAX_CONSECUTIVE_REJECTS} rejects",
                       f"slippage alarm at {SLIPPAGE_ALARM_PCT}% mean over 20 fills"]}
