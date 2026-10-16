"""Focus Five: real NSE data, simulated execution, five isolated Rs 10 lakh books.

No broker order client is imported. Signals use the existing v2 rules and closed-bar
store, but positions/capital never come from the tournament or its trade history.
Atomic versioned account documents prevent overspending and duplicate closes across
workers. A durable outbox archives trades without a multi-document transaction.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from app.core.db import db
from app.services import desk_switches, in_play, intraday_universe, market_calendar
from app.services import intraday_session as session
from app.services import intraday_v2_strategies as v2
from app.services import intraday_focus_rules as rules
from app.services.angel_fees import round_trip, GST_RATE
from app.services.angel_stream import stream
from app.services.intraday_fills import slippage_bp, stream_minutes
from app.services.intraday_store import store, SESSION_OPEN_MIN

logger = logging.getLogger("intraday_focus")
ENABLED = os.getenv("INTRADAY_FOCUS_ENABLED", "1").lower() not in ("0", "false", "no")
accounts = db["intraday_focus_accounts"]
trades = db["intraday_focus_trades"]
state = db["intraday_focus_state"]
_lock = asyncio.Lock()
_cache: list[dict] = []
_cache_at = 0.0
_initialized = False
_last_evaluation = 0
_last_mark = 0.0
_last_heartbeat = 0.0
_last_archive = 0.0
_note: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def fee_model(entry: float, exit_price: float, qty: int, side: str) -> tuple[float, dict]:
    """NSE cash intraday estimate, not a broker contract note.

    Current brokerage verified 2026-10-15 at
    https://www.angelone.in/support/charges-and-cashbacks/brokerage-charges
    0.1% per order, minimum Rs5, maximum Rs20. Keep the older desks untouched.
    """
    fb = round_trip(entry, exit_price, qty, side=side, product="INTRADAY")
    fb.brokerage = sum(min(20.0, max(5.0, price * qty * 0.001)) for price in (entry, exit_price)) if qty > 0 else 0
    fb.gst = GST_RATE * (fb.brokerage + fb.exchange_txn + fb.sebi + fb.ipft)
    return round(fb.total, 2), fb.as_dict()


def quote(symbol: str, now: datetime) -> tuple[float | None, float | None]:
    """Both valid-price receipt AND exchange timestamps must be at most 30s old."""
    st = stream.states.get(symbol)
    if st is None or not stream.connected or st.day != now.astimezone(rules.IST).date():
        return None, None
    received = getattr(st, "last_price_received_at", 0)
    exchange = getattr(st, "last_price_exchange_at", 0)
    if not (rules.fresh_quote(st.last_ltp, received, now) and rules.fresh_quote(st.last_ltp, exchange, now)):
        return None, None
    return float(st.last_ltp), float(exchange)


async def initialize() -> None:
    global _initialized
    if _initialized:
        return
    await state.update_one({"_id": "desk"}, {"$setOnInsert": {
        "started_at": _now(), "mode": "PAPER", "model_version": rules.MODEL_VERSION}}, upsert=True)
    meta = await state.find_one({"_id": "desk"})
    for sid in rules.BY_ID:
        doc = rules.new_account(sid, meta["started_at"])
        await accounts.update_one({"_id": sid}, {"$setOnInsert": doc}, upsert=True)
    await trades.create_index([("closed_at", -1)])
    await trades.create_index([("strategy_id", 1), ("closed_at", -1)])
    _initialized = True


async def _load(fresh: bool = False) -> list[dict]:
    global _cache, _cache_at
    if fresh or time.monotonic() - _cache_at > 30 or not _cache:
        _cache = await accounts.find({"_id": {"$in": list(rules.BY_ID)}}).to_list(5)
        _cache_at = time.monotonic()
    return copy.deepcopy(_cache)


async def _commit(old: dict, new: dict) -> bool:
    """One CAS commits positions, costs and cash together. No partial money writes."""
    global _cache_at
    if old == new:
        return True
    new["version"] = old["version"] + 1
    new["updated_at"] = _now()
    result = await accounts.replace_one({"_id": old["_id"], "version": old["version"]}, new)
    _cache_at = 0.0
    return result.modified_count == 1


async def archive_closed() -> None:
    global _cache_at
    for account in await _load():
        archived = []
        for trade in account.get("outbox", []):
            pid = trade["position_id"]
            await trades.update_one({"_id": pid}, {"$setOnInsert": trade}, upsert=True)
            archived.append(pid)
        if archived:
            # Only remove confirmed archive writes. A concurrent close remains in the outbox.
            await accounts.update_one({"_id": account["_id"]}, {
                "$pull": {"outbox": {"position_id": {"$in": archived}}}, "$inc": {"version": 1}})
            _cache_at = 0.0


async def _switches_on() -> bool:
    return ENABLED and await desk_switches.is_on("intraday_focus") and await desk_switches.is_on("intraday_lab")


def _in_session(now: datetime) -> bool:
    return market_calendar.in_session(now.astimezone(rules.IST), "09:15", "15:30")


async def manage() -> int:
    """Manage existing positions even when entries are disabled. Never fabricate a price."""
    global _last_mark
    async with _lock:
        now = _now()
        if not _in_session(now):
            return 0
        await session.ensure_cas()
        closed = 0
        mark_due = time.monotonic() - _last_mark >= 15
        for old in await _load():
            if not rules.valid_account(old):
                raise RuntimeError("Focus Five account configuration mismatch; entries halted")
            new = copy.deepcopy(old)
            for pid in [p["position_id"] for p in old["positions"]]:
                p = next(p for p in new["positions"] if p["position_id"] == pid)
                price, quote_at = quote(p["symbol"], now)
                decision = rules.exit_decision(p, stream_minutes(p["symbol"], p["checked_through"]),
                                               price, now, session.squareoff_due(p["symbol"], now))
                if decision:
                    new = rules.close_position(new, p["position_id"], decision, now, fee_model)
                elif mark_due:
                    if price is not None:
                        p["ltp"], p["quote_at"], p["price_status"] = price, quote_at, "LIVE"
                        p["unrealized_pnl"], p["return_pct"] = rules.mark_position(p, price, fee_model)
                        # Recheck the current forming minute until it is complete.
                        p["checked_through"] = max(p["checked_through"], int(now.timestamp()) // 60 * 60)
                    else:
                        p["price_status"] = "STALE · EXIT PENDING" if session.squareoff_due(p["symbol"], now) else "STALE"
            if await _commit(old, new):
                closed += len(old["positions"]) - len(new["positions"])
        if mark_due:
            _last_mark = time.monotonic()
        return closed


async def evaluate_boundary(boundary: datetime) -> None:
    """Independent capital decisions on exactly the same five indicator rule functions."""
    global _note
    now = _now()
    if not (_in_session(now) and v2.in_entry_window(now) and await _switches_on()):
        return
    if not 20 <= (rules.utc(now) - rules.utc(boundary)).total_seconds() < 120:
        return
    minute = boundary.hour * 60 + boundary.minute - SESSION_OPEN_MIN
    specs = [v2.BY_ID[sid] for sid, _, tf, _ in rules.STRATEGIES
             if minute % (45 if tf == "45m" else 60) == 0]
    if not specs:
        return
    member_list = await intraday_universe.members()
    ranked = await in_play.ranked(top=len(member_list), now=boundary + timedelta(seconds=1))
    rv = {r["symbol"]: (r.get("rvol_raw"), i + 1) for i, r in enumerate(ranked["top"])}
    nifty = store.series("NIFTY", "15m", n=40, now=boundary + timedelta(seconds=1))
    today = [i for i, t in enumerate(nifty.ts) if datetime.fromisoformat(t).date() == boundary.date()]
    nifty_ret = ((nifty.c[today[-1]] / nifty.o[today[0]] - 1) * 100
                 if today and nifty.o[today[0]] > 0 else None)
    candidates = {spec.strategy_id: [] for spec in specs}
    incomplete = stale = 0
    for member in member_list:
        sym = member["symbol"]
        end = int(boundary.timestamp())
        count = minute // 15
        if store.count_between(sym, end - count * 900, end - 900) < count:
            incomplete += 1
            continue
        price, quote_at = quote(sym, _now())
        if price is None:
            stale += 1
            continue
        s15 = store.series(sym, "15m", n=420, now=boundary + timedelta(seconds=1))
        rvol, rank = rv.get(sym, (None, None))
        contexts = {}
        for spec in specs:
            if spec.tf not in contexts:
                series = store.series(sym, spec.tf, n=220, now=boundary + timedelta(seconds=1))
                contexts[spec.tf] = v2.build_ctx(sym, spec.tf, boundary, series, s15, rvol, rank, nifty_ret)
            ctx = contexts[spec.tf]
            sig = v2.evaluate(spec, ctx) if ctx else None
            if sig is None or sig.oco or sig.trigger is not None:
                continue
            candidates[spec.strategy_id].append({"strategy_id": spec.strategy_id, "symbol": sym,
                "side": sig.side, "price": price, "quote_at": quote_at, "priority": sig.priority,
                "signal_price": sig.entry, "stop_dist": sig.stop_dist, "target_dist": sig.target_dist,
                "slippage_pct": slippage_bp(member.get("turnover_cr")) / 100,
                "max_hold_seconds": sig.max_bars * v2.TF_SECONDS[spec.tf], "rationale": sig.rationale})
        await asyncio.sleep(0)
    opened = 0
    async with _lock:
        for sid, rows in candidates.items():
            if not await _switches_on():
                break
            for _attempt in range(3):
                old = await accounts.find_one({"_id": sid})
                if old is None:
                    raise RuntimeError("Focus Five account not initialized")
                current = _now()
                if not _in_session(current):
                    break
                # Scoring can take time; renew each quote before reserving any cash.
                for c in rows:
                    c["price"], c["quote_at"] = quote(c["symbol"], current)
                marked = copy.deepcopy(old)
                for p in marked["positions"]:
                    px, qt = quote(p["symbol"], current)
                    p["price_status"] = "LIVE" if px is not None else "STALE"
                    if px is not None:
                        p["ltp"], p["quote_at"] = px, qt
                        p["unrealized_pnl"], p["return_pct"] = rules.mark_position(p, px, fee_model)
                new = rules.plan_entries(marked, rows, boundary, current, fee_model)
                if await _commit(old, new):
                    opened += len(new["positions"]) - len(old["positions"])
                    break
    _note = f"Last scan: {opened} entries; {incomplete} stocks missing bars; {stale} without fresh quotes."
    await state.update_one({"_id": "desk"}, {"$set": {"last_evaluation": _now(),
        "last_boundary": boundary, "note": _note}})


async def tick() -> None:
    global _last_evaluation, _last_heartbeat, _last_archive, _note
    await initialize()
    await manage()
    now = _now()
    local = now.astimezone(rules.IST)
    if _in_session(now) and await _switches_on() and v2.in_entry_window(local):
        minute = local.hour * 60 + local.minute
        k = (minute - SESSION_OPEN_MIN) // 15
        boundary = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=SESSION_OPEN_MIN + k * 15)
        stamp = int(boundary.timestamp())
        if stamp > _last_evaluation and (local - boundary).total_seconds() >= 20:
            await evaluate_boundary(boundary)
            _last_evaluation = stamp
    if time.monotonic() - _last_archive >= 30:
        await archive_closed()
        _last_archive = time.monotonic()
    if time.monotonic() - _last_heartbeat >= 30:
        await state.update_one({"_id": "desk"}, {"$set": {"last_tick": now,
            "enabled": ENABLED, "note": _note}})
        _last_heartbeat = time.monotonic()


async def focus_loop() -> None:
    global _note
    while True:
        try:
            await tick()
        except Exception as exc:
            _note = f"Engine error ({type(exc).__name__}); no fabricated fills. Check server logs."
            logger.exception("Focus Five tick failed")
        await asyncio.sleep(3 if _in_session(_now()) else 30)


async def snapshot() -> dict:
    """Read only. Opening the page never starts an account or submits an order."""
    now = _now()
    meta = await state.find_one({"_id": "desk"}) or {}
    docs = {d["_id"]: d for d in await accounts.find({"_id": {"$in": list(rules.BY_ID)}}).to_list(5)}
    books = [docs.get(sid) or rules.new_account(sid, now) for sid in rules.BY_ID]
    if any(not rules.valid_account(a) for a in books):
        raise RuntimeError("Focus Five ledger configuration mismatch")
    active = _in_session(now)
    fresh = [(sym, quote(sym, now)[1]) for sym in list(stream.states)] if active else []
    fresh = [(sym, ts) for sym, ts in fresh if ts is not None]
    feed_status = "LIVE" if fresh else ("STALE" if active else "MARKET_CLOSED")
    positions = []
    for a in books:
        for p in a["positions"]:
            px, at = quote(p["symbol"], now) if active else (None, None)
            if px is not None:
                p["ltp"], p["quote_at"], p["price_status"] = px, at, "LIVE"
                p["unrealized_pnl"], p["return_pct"] = rules.mark_position(p, px, fee_model)
            else:
                p["price_status"] = "STALE" if active else "MARKET_CLOSED"
            positions.append(p)
    rows = [rules.account_summary(a) for a in books]
    recent = await trades.find({}, {"_id": 0}).sort("closed_at", -1).limit(100).to_list(100)
    by_id = {t["position_id"]: t for t in recent}
    for a in books:
        for t in a["outbox"]:
            by_id[t["position_id"]] = t
    recent = sorted(by_id.values(), key=lambda t: rules.utc(t["closed_at"]), reverse=True)[:100]
    daily: dict[str, dict] = {}
    for a in books:
        for date, values in a["daily"].items():
            row = daily.setdefault(date, {"date": date, "trades": 0, "gross_pnl": 0.0, "fees": 0.0, "realized_pnl": 0.0})
            for key in ("trades", "gross_pnl", "fees", "realized_pnl"):
                row[key] += values[key]
    for row in daily.values():
        row["return_pct"] = round(row["realized_pnl"] / (rules.CAPITAL * 5) * 100, 4)
    on = await _switches_on()
    last_tick = meta.get("last_tick")
    healthy = bool(last_tick and 0 <= (now - rules.utc(last_tick)).total_seconds() <= 90)
    note = _note or meta.get("note")
    if not meta.get("started_at"):
        note = "Waiting for engine startup. Allocations below are configured; no history has been imported."
    elif not healthy:
        note = "Engine heartbeat is stale. Stored results are not evidence of active trading."
    elif not on:
        note = "New entries paused by configuration or Main Control. Existing exits continue."
    totals = {key: round(sum(row[key] for row in rows), 2) for key in (
        "equity", "available_cash", "deployed_capital", "fee_reserve", "realized_pnl", "unrealized_pnl", "total_pnl")}
    return {"mode": "PAPER", "real_orders_enabled": False, "initial_capital": rules.CAPITAL * 5,
        "per_strategy_capital": rules.CAPITAL, "slot_notional": rules.SLOT_CAPITAL, "slots_per_strategy": rules.SLOTS,
        "started_at": meta.get("started_at"), "updated_at": now, **totals,
        "return_pct": round(totals["total_pnl"] / (rules.CAPITAL * 5) * 100, 4),
        "open_positions": len(positions), "closed_trades": sum(a["trades"] for a in books),
        "feed": {"source": "Angel One NSE live stream", "status": feed_status,
                 "last_quote_at": datetime.fromtimestamp(max(ts for _, ts in fresh), timezone.utc) if fresh else None,
                 "reason": None if fresh else "No fresh session quotes. New entries require valid prices received and exchanged within 30 seconds."},
        "engine": {"enabled": ENABLED, "entries_enabled": bool(on and healthy and fresh and v2.in_entry_window(now)),
                   "last_tick": last_tick, "last_evaluation": meta.get("last_evaluation"), "note": note},
        "strategies": rows, "positions": positions, "trades": recent,
        "daily": sorted(daily.values(), key=lambda x: x["date"], reverse=True)[:90],
        "cost_note": "Estimated Angel One charges and liquidity-based slippage; simulated fills, not broker executions.",
        "validation_note": "These five strategies are research candidates, not validated real-money strategies. No prior tournament returns are included."}
