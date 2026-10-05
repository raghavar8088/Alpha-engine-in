"""HC1 paper book — the pre-registered 5-commodity 12-month trend rule, in whole MCX lots.

THE FROZEN RULE (commodity_hypotheses.HC1; nothing here may be tuned once forward data exists)
  * Commodities: gold, silver, copper, crude oil, natural gas.
  * Signal per commodity: the sign of its 12-month (252 trading-day) rupee return on the
    Commodity Lab's daily series (international future x USD/INR), at the last completed
    daily close.
  * Size: min(10% / 60-day realised vol, 3) x capital / 5 of rupee notional per commodity,
    rounded to WHOLE lots of the smallest liquid MCX contract — GOLDPETAL, SILVERMIC,
    COPPER (no mini exists), CRUDEOILM, NATGASMINI. A leg that rounds to 0 lots is not
    held (copper at Rs 50 lakh: one lot is ~Rs 35 lakh of metal).
  * When: opens on the first session after registration (2026-10-05), then rebalances on
    the FIRST MCX TRADING DAY of each month, from 11:00 IST.
  * Fills at the touch (the ask to buy, the bid to sell) on a live quote; Angel's charges.
  * Rolls out of a contract before its exit window (delivery tender days for bullion and
    copper, last two sessions for energy) into the next month, both legs charged.
  * A worst-day stress check (every leg's worst single day at once) caps the book at
    MCX_MAX_STRESS_PCT of capital; if exceeded, every leg is scaled down.

Every rebalance order is also handed to the MCX real-money executor, which is LOCKED
(dry run, no CONFIRMED verdict) — so the orders are recorded, never sent.
"""

from __future__ import annotations

import logging
import math
import os
import statistics
from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

from tradingai_shared import mcx_calendar as mcal
from tradingai_shared.mcx_fees import mcx_leg

from app.core.db import db
from app.services import mcx_market
from app.services.commodity_positions import multiplier

logger = logging.getLogger("commodity_trend_book")

BOOK_ID = "HC1"
CAPITAL = float(os.getenv("COMMODITY_TREND_BOOK_CAPITAL", "5000000"))
VOL_TARGET = 0.10
LOOKBACK = 252
VOL_WINDOW = 60
REBALANCE_FROM = time(11, 0)
START_DATE = "2026-10-05"
LEGS = {"GOLD": "GOLDPETAL", "SILVER": "SILVERMIC", "COPPER": "COPPER", "CRUDE": "CRUDEOILM", "NATGAS": "NATGASMINI"}
FAMILY = {"GOLD": "GOLD", "SILVER": "SILVER", "COPPER": "COPPER", "CRUDE": "CRUDEOIL", "NATGAS": "NATURALGAS"}

state_collection = db["commodity_trend_state"]
legs_collection = db["commodity_trend_legs"]
trades_collection = db["commodity_trend_trades"]
equity_collection = db["commodity_trend_equity"]
IST = mcal.IST


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_state() -> dict:
    st = await state_collection.find_one({"_id": BOOK_ID}) or {}
    st.pop("_id", None)
    return st


# ── the signal ───────────────────────────────────────────────────────────────────


async def targets(capital: float = CAPITAL) -> dict:
    """{commodity: {signal, vol, notional, contract, lots, side, price}} by the frozen rule."""
    from app.services import commodity_lab_data as data
    from app.services.mcx_risk import stress_check, whole_lots

    await data.ensure_fresh()
    hist = await data.load()
    uni = await mcx_market.tradable_universe(list(LEGS.values()))
    quotes = await mcx_market.quotes(list(uni.values()))
    out = {}
    for k, vehicle in LEGS.items():
        closes = hist.closes.get(k) or []
        if len(closes) < LOOKBACK + VOL_WINDOW + 2:
            out[k] = {"error": "not enough history"}
            continue
        signal = 1 if closes[-1][1] > closes[-1 - LOOKBACK][1] else -1
        rets = [closes[i][1] / closes[i - 1][1] - 1 for i in range(len(closes) - VOL_WINDOW, len(closes))]
        vol = statistics.pstdev(rets) * math.sqrt(252)
        notional = capital * min(VOL_TARGET / vol, 3.0) / len(LEGS) if vol > 0 else 0.0
        inst = uni.get(vehicle)
        q = quotes.get(str((inst or {}).get("angel_token") or (inst or {}).get("security_id"))) if inst else None
        price = q.ltp if q and q.ltp else None
        lots = whole_lots(vehicle, price, notional) if price else 0
        out[k] = {"signal": signal, "side": "BUY" if signal > 0 else "SELL", "vol_60d": round(vol, 4),
                  "notional": round(notional, 2), "contract": vehicle, "expiry": (inst or {}).get("expiry"),
                  "price": price, "lots": lots, "series_last": closes[-1][0].isoformat(),
                  "ret_12m": round(closes[-1][1] / closes[-1 - LOOKBACK][1] - 1, 4),
                  "not_held_reason": None if lots else (
                      f"one {vehicle} lot is Rs{(price or 0) * multiplier(vehicle):,.0f} against a "
                      f"Rs{notional:,.0f} target" if price else "no MCX price")}
    held = [{"symbol": v["contract"], "price": v["price"], "lots": v["lots"]} for v in out.values()
            if v.get("lots") and v.get("price")]
    stress = stress_check(held, capital)
    scale = 1.0
    if not stress["ok"] and stress["worst_day_loss"] > 0:
        from app.services.mcx_risk import MAX_STRESS_PCT
        scale = MAX_STRESS_PCT * capital / stress["worst_day_loss"]
        for v in out.values():
            if v.get("lots"):
                v["lots"] = int(v["lots"] * scale)
    return {"legs": out, "stress": stress, "scaled_by": round(scale, 3), "capital": capital,
            "computed_at": _now().isoformat()}


# ── execution (paper, at the touch) ──────────────────────────────────────────────


async def _trade(commodity: str, inst: dict, side: str, lots: int, q: mcx_market.McxQuote, purpose: str) -> dict | None:
    """One paper order of `lots` at the touch. Returns the fill record or None."""
    px = q.touch(side) if q else None
    if not px or lots <= 0:
        return None
    mult = multiplier(inst.get("underlying_symbol") or LEGS[commodity])
    qty = lots * mult
    fee = mcx_leg(px, qty, side == "BUY")
    rec = {"trade_id": uuid4().hex[:12], "book": BOOK_ID, "commodity": commodity,
           "contract": inst.get("symbol"), "underlying": inst.get("underlying_symbol"), "expiry": inst.get("expiry"),
           "token": str(inst.get("angel_token") or inst.get("security_id")), "side": side, "lots": lots,
           "multiplier": mult, "price": px, "ltp": q.ltp, "spread_bp": q.spread_bp, "fees": fee,
           "purpose": purpose, "at": _now()}
    await trades_collection.insert_one(dict(rec))
    try:   # mirror to the real-money executor — LOCKED, so it only records what it would do
        from app.services import mcx_live_executor
        await mcx_live_executor.execute(BOOK_ID, "close" if purpose.startswith("close") else "open", [{
            "tradingsymbol": inst.get("angel_tradingsymbol"), "token": rec["token"], "exchange": "MCX",
            "side": side, "lots": lots, "angel_lotsize": inst.get("angel_lotsize"), "underlying": rec["underlying"],
            "expiry": rec["expiry"], "ref_price": px, "multiplier": mult}])
    except Exception as exc:  # noqa: BLE001 — the paper book never depends on the executor
        logger.info("[trend_book] executor mirror skipped: %s", exc)
    return rec


async def _apply(commodity: str, inst: dict, side: str, lots: int, q, purpose: str) -> bool:
    """Move the leg for `commodity` by an order of `lots` on `side`, realising P&L on any
    reduction. One leg document per commodity."""
    rec = await _trade(commodity, inst, side, lots, q, purpose)
    if rec is None:
        return False
    leg = await legs_collection.find_one({"_id": commodity}) or {"_id": commodity, "lots": 0, "side": None,
                                                                   "avg_price": 0.0, "realized_pnl": 0.0, "fees": 0.0}
    signed_now = leg["lots"] * (1 if leg.get("side") == "BUY" else -1)
    delta = lots * (1 if side == "BUY" else -1)
    new = signed_now + delta
    realized = 0.0
    if signed_now and (signed_now > 0) != (delta > 0):          # reducing or flipping
        closed = min(abs(signed_now), abs(delta))
        sign = 1 if signed_now > 0 else -1
        realized = (rec["price"] - leg["avg_price"]) * closed * rec["multiplier"] * sign
    if new == 0:
        avg = 0.0
    elif signed_now == 0 or (signed_now > 0) != (new > 0):
        avg = rec["price"]                                       # fresh or flipped
    elif abs(new) > abs(signed_now):
        avg = (leg["avg_price"] * abs(signed_now) + rec["price"] * abs(delta)) / abs(new)
    else:
        avg = leg["avg_price"]
    await legs_collection.update_one({"_id": commodity}, {"$set": {
        "lots": abs(new), "side": ("BUY" if new > 0 else "SELL") if new else None, "avg_price": avg,
        "contract": inst.get("symbol"), "underlying": inst.get("underlying_symbol"), "expiry": inst.get("expiry"),
        "token": rec["token"], "multiplier": rec["multiplier"], "angel_tradingsymbol": inst.get("angel_tradingsymbol"),
        "angel_lotsize": inst.get("angel_lotsize"), "updated_at": _now()},
        "$inc": {"realized_pnl": realized, "fees": rec["fees"]}}, upsert=True)
    await trades_collection.update_one({"trade_id": rec["trade_id"]}, {"$set": {"realized_pnl": round(realized, 2)}})
    return True


async def rebalance() -> dict:
    tg = await targets()
    notes, done = [], 0
    for k, t in tg["legs"].items():
        if t.get("error"):
            notes.append(f"{k}: {t['error']}")
            continue
        leg = await legs_collection.find_one({"_id": k}) or {}
        held = leg.get("lots", 0) * (1 if leg.get("side") == "BUY" else -1) if leg.get("lots") else 0
        want = t["lots"] * (1 if t["side"] == "BUY" else -1)
        # a held leg on an older contract is moved to the tradable one first (roll)
        if held and leg.get("expiry") != t["expiry"]:
            r = await _roll(k, leg)
            if not r:
                notes.append(f"{k}: roll pending (no live quote)")
                continue
            leg = await legs_collection.find_one({"_id": k}) or {}
        diff = want - held
        if diff == 0:
            done += 1
            continue
        inst = (await mcx_market.tradable_universe([t["contract"]])).get(t["contract"])
        q = (await mcx_market.quotes([inst])).get(str(inst.get("angel_token") or inst.get("security_id"))) if inst else None
        if not inst or q is None or not q.fresh:
            notes.append(f"{k}: no live quote for {t['contract']} ({q.why if q else 'no contract'}) — retried next tick")
            continue
        ok = await _apply(k, inst, "BUY" if diff > 0 else "SELL", abs(diff), q, "rebalance")
        done += 1 if ok else 0
    month = datetime.now(IST).strftime("%Y-%m")
    complete = done == len(tg["legs"])
    await state_collection.update_one({"_id": BOOK_ID}, {"$set": {
        "last_targets": tg, "last_rebalance_try": _now(), "last_notes": notes,
        **({"rebalanced_month": month, "rebalanced_at": _now()} if complete else {})}}, upsert=True)
    return {"complete": complete, "notes": notes, "targets": tg}


async def _roll(commodity: str, leg: dict) -> bool:
    """Close the leg on its old contract and reopen the same lots on the tradable one."""
    old = {"symbol": leg.get("contract"), "underlying_symbol": leg.get("underlying"), "expiry": leg.get("expiry"),
           "angel_token": leg.get("token"), "angel_tradingsymbol": leg.get("angel_tradingsymbol"),
           "angel_lotsize": leg.get("angel_lotsize")}
    new = (await mcx_market.tradable_universe([leg.get("underlying")])).get(leg.get("underlying"))
    if not new or new.get("expiry") == leg.get("expiry"):
        return True
    qs = await mcx_market.quotes([old, new])
    q_old, q_new = qs.get(str(old["angel_token"])), qs.get(str(new.get("angel_token") or new.get("security_id")))
    if not (q_old and q_old.fresh and q_new and q_new.fresh):
        return False
    lots, side = leg["lots"], leg["side"]
    back = "SELL" if side == "BUY" else "BUY"
    await _apply(commodity, old, back, lots, q_old, "close_roll")
    await _apply(commodity, new, side, lots, q_new, "open_roll")
    return True


async def mark() -> dict:
    """Mark every leg at the side it would exit on (bid for a long, ask for a short)."""
    legs = [l async for l in legs_collection.find({})]
    open_legs = [l for l in legs if l.get("lots")]
    qs = await mcx_market.quotes([{"angel_token": l["token"]} for l in open_legs]) if open_legs else {}
    unreal, realized, fees = 0.0, 0.0, 0.0
    for l in legs:
        realized += l.get("realized_pnl") or 0.0
        fees += l.get("fees") or 0.0
        if not l.get("lots"):
            continue
        q = qs.get(str(l["token"]))
        px = (q.touch("SELL" if l["side"] == "BUY" else "BUY") if q and q.fresh else None) or l.get("mark")
        if px:
            sign = 1 if l["side"] == "BUY" else -1
            u = (px - l["avg_price"]) * l["lots"] * l["multiplier"] * sign
            unreal += u
            await legs_collection.update_one({"_id": l["_id"]}, {"$set": {"mark": px, "unrealized_pnl": round(u, 2)}})
    equity = CAPITAL + realized - fees + unreal
    today = mcal.as_date(None).isoformat()
    await equity_collection.update_one({"_id": today}, {"$set": {
        "date": today, "equity": round(equity, 2), "realized": round(realized, 2), "fees": round(fees, 2),
        "unrealized": round(unreal, 2), "ts": _now()}}, upsert=True)
    return {"equity": round(equity, 2), "realized": round(realized, 2), "fees": round(fees, 2),
            "unrealized": round(unreal, 2), "capital": CAPITAL}


def first_trading_day_of_month(d) -> bool:
    x = d.replace(day=1)
    while not mcal.is_trading_day(x):
        x += timedelta(days=1)
    return x == d


async def cycle() -> dict:
    """One tick: rolls, the rebalance when due, the mark."""
    now = datetime.now(IST)
    if mcal.session_at(now) is None:
        return {"skipped": "MCX closed"}
    st = await get_state()
    notes = []
    async for leg in legs_collection.find({"lots": {"$gt": 0}}):
        if mcx_market.in_exit_window(leg.get("underlying") or "", leg.get("expiry")):
            if not await _roll(leg["_id"], leg):
                notes.append(f"{leg['_id']}: roll due, waiting for live quotes")
    due = (now.date().isoformat() >= START_DATE and now.time() >= REBALANCE_FROM
           and (not st.get("rebalanced_month")
                or (st["rebalanced_month"] != now.strftime("%Y-%m") and _month_due(now))))
    reb = None
    if due:
        reb = await rebalance()
    m = await mark()
    await state_collection.update_one({"_id": BOOK_ID}, {"$set": {"last_cycle_at": _now(), "last_mark": m,
                                                                   "last_cycle_notes": notes}}, upsert=True)
    return {"rebalance": reb, "mark": m, "notes": notes}


def _month_due(now: datetime) -> bool:
    """Due from the first trading day of the month onward (a missed day retries the next)."""
    d = now.date()
    x = d.replace(day=1)
    while not mcal.is_trading_day(x):
        x += timedelta(days=1)
    return d >= x


async def summary() -> dict:
    st = await get_state()
    legs = []
    async for l in legs_collection.find({}):
        l["commodity"] = l.pop("_id")
        l.pop("updated_at", None)
        legs.append(l)
    eq = [e async for e in equity_collection.find({}, {"_id": 0}).sort("date", 1)]
    for e in eq:
        e.pop("ts", None)
    trades = [t async for t in trades_collection.find({}, {"_id": 0}).sort("at", -1).limit(50)]
    for t in trades:
        t["at"] = t["at"].isoformat() if isinstance(t.get("at"), datetime) else t.get("at")
    for k in ("last_rebalance_try", "rebalanced_at", "last_cycle_at"):
        if isinstance(st.get(k), datetime):
            st[k] = st[k].isoformat()
    return {"book": BOOK_ID, "capital": CAPITAL, "start_date": START_DATE, "legs": legs, "equity": eq,
            "trades": trades, "state": st, "vehicles": LEGS}
