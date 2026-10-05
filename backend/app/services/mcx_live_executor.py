"""Real-money readiness for MCX futures (C6 of the 2026-10-03 Commodity plan).

SHIPS DISARMED, AND CANNOT BE ARMED TODAY. A real opening order needs ALL of:
  1. a CONFIRMED verdict for the strategy — a pre-registered hypothesis CONFIRMED on its
     forward record (commodity_hypotheses) or a pattern CONFIRMED by the Commodity Lab after
     its incubation. At ship time nothing is confirmed;
  2. MCX_LIVE_ENABLED=1 on the server (default 0);
  3. the user arming it, authenticated, typing the confirmation phrase;
  4. MCX_LIVE_DRY_RUN=0 (default 1: orders are recorded as SIMULATED, never sent);
  5. MCX_LIVE_QTY_VERIFIED=1 — Angel's quantity unit for MCX orders (lots, or the broker's
     lot size?) has to be proven with a real one-lot round trip first. The instrument master's
     `angel_lotsize` reads GOLD 1, GOLDM 100, CRUDEOIL 100, SILVERMIC 1; a wrong guess sends
     a hundred lots instead of one. Until verified, every opening order is refused.
Checks before every opening order: kill switch off; armed for THIS strategy; whole lots only;
order notional <= MCX_LIVE_MAX_ORDER_NOTIONAL; the contract is outside its exit window (never
trade into a delivery period); MCX in session by its own calendar; today's loss < the daily
cap; Angel's available cash covers the SPAN-lite margin plus charges.
Closing orders are always allowed (a real position must always be able to exit). Three
consecutive rejects auto-disarm; a mean fill more than MCX_LIVE_SLIPPAGE_ALARM_BP worse than
the touch over the last 20 fills raises an alarm and disarms.
"""

from __future__ import annotations

import asyncio
import logging
import os
import statistics
from datetime import datetime, timedelta, timezone

from tradingai_shared import mcx_calendar as mcal
from tradingai_shared.mcx_fees import mcx_leg

from app.core.db import db

logger = logging.getLogger("mcx_live_executor")

ENABLED = os.getenv("MCX_LIVE_ENABLED", "0").lower() in ("1", "true", "yes")
DRY_RUN = os.getenv("MCX_LIVE_DRY_RUN", "1").lower() not in ("0", "false", "no")
QTY_VERIFIED = os.getenv("MCX_LIVE_QTY_VERIFIED", "0").lower() in ("1", "true", "yes")
MAX_ORDER_NOTIONAL = float(os.getenv("MCX_LIVE_MAX_ORDER_NOTIONAL", "500000"))
DAILY_LOSS_CAP = float(os.getenv("MCX_LIVE_DAILY_LOSS_CAP", "10000"))
SLIPPAGE_ALARM_BP = float(os.getenv("MCX_LIVE_SLIPPAGE_ALARM_BP", "15"))
MAX_CONSECUTIVE_REJECTS = 3
CONFIRM_PHRASE = "ARM REAL MONEY MCX"
state = db["mcx_live_state"]
orders = db["mcx_live_orders"]
STATE_ID = "engine"
IST = mcal.IST


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_state() -> dict:
    st = await state.find_one({"_id": STATE_ID}) or {}
    return {"armed": bool(st.get("armed")), "armed_for": st.get("armed_for"),
            "kill_switch": bool(st.get("kill_switch")), "consecutive_rejects": st.get("consecutive_rejects", 0),
            "disarmed_reason": st.get("disarmed_reason"),
            "armed_at": st["armed_at"].isoformat() if isinstance(st.get("armed_at"), datetime) else None,
            "armed_by": st.get("armed_by"), "env_enabled": ENABLED, "dry_run": DRY_RUN, "qty_verified": QTY_VERIFIED,
            "max_order_notional": MAX_ORDER_NOTIONAL, "daily_loss_cap": DAILY_LOSS_CAP}


async def strategy_status(key: str) -> str | None:
    """CONFIRMED / INCUBATING / ... for a hypothesis id (HC1) or a Lab verdict key."""
    from app.services.commodity_hypotheses import hypotheses
    from app.services.commodity_lab import lab_verdicts_collection

    h = await hypotheses.find_one({"_id": key}, {"status": 1})
    if h:
        return h.get("status")
    v = await lab_verdicts_collection.find_one({"_id": key}, {"verdict": 1})
    return v.get("verdict") if v else None


async def can_arm(key: str) -> tuple[bool, list[str]]:
    why = []
    status = await strategy_status(key)
    if status is None:
        why.append(f"{key} is neither a registered hypothesis nor a Lab candidate")
    elif status != "CONFIRMED":
        why.append(f"{key} is {status}: only a CONFIRMED verdict may trade real money")
    if not ENABLED:
        why.append("MCX_LIVE_ENABLED is not set on the server")
    if not QTY_VERIFIED:
        why.append("MCX order quantity unit not verified with a real 1-lot round trip (MCX_LIVE_QTY_VERIFIED)")
    if (await get_state())["kill_switch"]:
        why.append("the kill switch is on")
    return (not why), why


async def arm(key: str, confirm: str, user: str) -> dict:
    ok, why = await can_arm(key)
    if confirm != CONFIRM_PHRASE:
        why.append(f'type "{CONFIRM_PHRASE}" to confirm')
        ok = False
    if not ok:
        return {"armed": False, "refused": why}
    await state.update_one({"_id": STATE_ID}, {"$set": {"armed": True, "armed_for": key, "armed_at": _now(),
                                                        "armed_by": user, "consecutive_rejects": 0,
                                                        "disarmed_reason": None}}, upsert=True)
    logger.warning("[mcx_live] ARMED for %s by %s (dry_run=%s)", key, user, DRY_RUN)
    return {"armed": True, "for": key, "dry_run": DRY_RUN}


async def disarm(reason: str) -> dict:
    await state.update_one({"_id": STATE_ID}, {"$set": {"armed": False, "disarmed_reason": reason,
                                                        "updated_at": _now()}}, upsert=True)
    logger.warning("[mcx_live] DISARMED: %s", reason)
    return await get_state()


async def set_kill_switch(active: bool, reason: str = "manual") -> dict:
    await state.update_one({"_id": STATE_ID}, {"$set": {"kill_switch": bool(active), "updated_at": _now()}}, upsert=True)
    if active:
        await disarm(f"kill switch: {reason}")
    return await get_state()


async def today_loss() -> float:
    """Realised loss of today's REAL (non-simulated) closing fills."""
    start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    pnl = 0.0
    async for o in orders.find({"at": {"$gte": start}, "status": "FILLED", "realized_pnl": {"$ne": None}},
                               {"realized_pnl": 1}):
        pnl += o.get("realized_pnl") or 0.0
    return -pnl


async def margin_ok(legs: list[dict]) -> tuple[bool, str]:
    from app.services.angel_client import angel_client
    from app.services.mcx_risk import margin_per_lot

    need = sum(margin_per_lot(l["underlying"], l["ref_price"]) * l["lots"]
               + mcx_leg(l["ref_price"], l["lots"] * l["multiplier"], l["side"] == "BUY") for l in legs)
    try:
        funds = await angel_client.funds()
        avail = float(funds.get("availablecash") or 0)
    except Exception as exc:  # noqa: BLE001 — no margin read = no order
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


async def execute(key: str, purpose: str, legs: list[dict]) -> dict:
    """Send (or, in dry run / disarmed, record) real MCX orders for a paper decision.

    legs: [{tradingsymbol, token, exchange, side, lots, angel_lotsize, underlying, expiry,
            ref_price (the touch the paper fill used), multiplier}]"""
    st = await get_state()
    now = datetime.now(IST)
    refusals: list[str] = []
    if purpose == "open":
        if st["kill_switch"]:
            refusals.append("kill switch on")
        if not st["armed"] or st["armed_for"] != key:
            refusals.append("not armed for this strategy")
        if not ENABLED:
            refusals.append("MCX_LIVE_ENABLED off")
        if not QTY_VERIFIED:
            refusals.append("order quantity unit unverified")
        for l in legs:
            if int(l["lots"]) != l["lots"] or l["lots"] < 1:
                refusals.append(f"{l.get('tradingsymbol')}: whole lots only")
            if l["ref_price"] * l["lots"] * l["multiplier"] > MAX_ORDER_NOTIONAL:
                refusals.append(f"{l.get('tradingsymbol')}: order notional above Rs{MAX_ORDER_NOTIONAL:,.0f}")
            from app.services.mcx_market import in_exit_window
            if in_exit_window(l["underlying"], l["expiry"]):
                refusals.append(f"{l.get('tradingsymbol')}: contract inside its exit (delivery) window")
        if mcal.session_at(now) is None:
            refusals.append("MCX not in session")
        if await today_loss() >= DAILY_LOSS_CAP:
            refusals.append(f"daily loss cap Rs{DAILY_LOSS_CAP:,.0f} reached")
        if not refusals and not DRY_RUN:
            ok, msg = await margin_ok(legs)
            if not ok:
                refusals.append(f"margin: {msg}")
    send = (not DRY_RUN) and (purpose == "close" or not refusals)
    results = []
    for leg in legs:
        doc = {"strategy": key, "purpose": purpose, "at": _now(), "dry_run": DRY_RUN, **leg}
        if not send:
            doc.update({"status": "SIMULATED" if DRY_RUN else "REFUSED", "refused": refusals or None,
                        "fill": leg["ref_price"] if DRY_RUN else None, "slippage_bp": 0.0 if DRY_RUN else None})
        else:
            from app.services.angel_client import angel_client
            try:
                qty = int(leg["lots"]) * int(leg.get("angel_lotsize") or 1)
                r = await angel_client.place_order(tradingsymbol=leg["tradingsymbol"], symboltoken=leg["token"],
                                                   transactiontype=leg["side"], exchange="MCX",
                                                   quantity=qty, producttype="CARRYFORWARD")
                oid = (r.get("data") or {}).get("orderid")
                fill = await _fill_price(oid) if oid else None
                sign = 1 if leg["side"] == "BUY" else -1
                slip = sign * (fill - leg["ref_price"]) / leg["ref_price"] * 1e4 if fill else None
                doc.update({"status": "FILLED" if fill else "PLACED", "order_id": oid, "fill": fill,
                            "slippage_bp": slip, "quantity_sent": qty})
                await state.update_one({"_id": STATE_ID}, {"$set": {"consecutive_rejects": 0}}, upsert=True)
            except Exception as exc:  # noqa: BLE001 — a reject is recorded, counted, and may disarm
                doc.update({"status": "REJECTED", "error": str(exc)[:300]})
                st2 = await state.find_one_and_update({"_id": STATE_ID}, {"$inc": {"consecutive_rejects": 1}},
                                                      upsert=True, return_document=True)
                if (st2 or {}).get("consecutive_rejects", 0) >= MAX_CONSECUTIVE_REJECTS:
                    await disarm(f"auto-disarmed after {MAX_CONSECUTIVE_REJECTS} consecutive rejects")
        await orders.insert_one(dict(doc))
        results.append({k: v for k, v in doc.items() if k != "_id"})
    await _slippage_watch()
    return {"sent": send, "dry_run": DRY_RUN, "refused": refusals, "orders": results}


async def _slippage_watch() -> dict:
    xs = [o["slippage_bp"] async for o in orders.find({"status": "FILLED", "slippage_bp": {"$ne": None}},
                                                      {"slippage_bp": 1}).sort("at", -1).limit(20)]
    out = {"fills": len(xs), "mean_slippage_bp": round(statistics.mean(xs), 2) if xs else None,
           "alarm_at_bp": SLIPPAGE_ALARM_BP}
    if len(xs) >= 5 and statistics.mean(xs) > SLIPPAGE_ALARM_BP:
        out["alarm"] = True
        await disarm(f"slippage alarm: real fills {statistics.mean(xs):.1f} bp worse than the touch on average")
    return out


async def readiness() -> dict:
    from app.services.commodity_hypotheses import hypotheses

    rows = []
    async for h in hypotheses.find({}, {"status": 1, "name": 1}).sort("_id", 1):
        ok, why = await can_arm(h["_id"])
        rows.append({"strategy": h["_id"], "name": h.get("name"), "status": h.get("status"),
                     "can_arm": ok, "why_not": why})
    recent = []
    async for o in orders.find({}).sort("at", -1).limit(20):
        o.pop("_id", None)
        if isinstance(o.get("at"), datetime):
            o["at"] = o["at"].isoformat()
        recent.append(o)
    return {"state": await get_state(), "strategies": rows, "slippage": await _slippage_watch(),
            "recent_orders": recent, "confirm_phrase": CONFIRM_PHRASE,
            "checks": ["CONFIRMED verdict (forward record or Lab incubation)", "MCX_LIVE_ENABLED=1",
                       "MCX_LIVE_QTY_VERIFIED=1 after a real 1-lot round trip", "user arms with the phrase",
                       "MCX_LIVE_DRY_RUN=0 to send real orders", "whole lots only",
                       f"order notional <= Rs{MAX_ORDER_NOTIONAL:,.0f}", "never inside a delivery window",
                       "MCX in session (own calendar)", f"daily loss cap Rs{DAILY_LOSS_CAP:,.0f}",
                       "Angel cash covers SPAN-lite margin + charges", "kill switch off",
                       f"auto-disarm after {MAX_CONSECUTIVE_REJECTS} rejects",
                       f"slippage alarm at {SLIPPAGE_ALARM_BP} bp mean over 20 fills"]}
