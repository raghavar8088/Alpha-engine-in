"""Live Trading desk — the REAL-MONEY twin of the Live Intraday shortlist.

Same eight strategies, same ₹10,000-per-strategy / ₹10,000-per-position structure as the
paper Live Intraday desk (it imports that desk's exact selection and signal logic, so the
two can never drift apart). The difference is execution: when this desk is ARMED it routes
REAL orders to Dhan, the app's live execution broker. Angel One remains the price/signal
feed — it has no order path here by design.

Safety model (mirrors the Antigravity Live Engine the user already runs):
  * ARMED flag — ships OFF. Nothing is ordered until the desk is armed. Disarming stops
    NEW entries but open positions keep being managed to their target/stop/EOD.
  * KILL SWITCH — halts all new orders instantly, independent of the armed flag.
  * Per-strategy ENABLE — a toggle per strategy; a disabled strategy takes no new entries.
  * ₹10k per-strategy cap AND an ₹80k desk-wide ceiling, both server-enforced.
  * Auto-disarm after MAX_CONSECUTIVE_REJECTS failed orders in a row (a crash loop can
    never keep firing rejected orders unattended).
  * PANIC close-all — squares off every open position, disarms, and trips the kill switch.

Real cash-equity reality: you cannot carry a short position overnight, and a losing intraday
short must be covered same day. So every real order here is INTRADAY (MIS) and ALL positions
square off at EOD — the swing/intraday distinction the paper desk carries does not survive
contact with a real broker for shorts, so this desk is honest about being same-day.
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from anyio import to_thread

from app.core.db import (
    instruments_collection,
    live_trading_equity_collection,
    live_trading_flags_collection,
    live_trading_positions_collection,
    live_trading_scores_collection,
    live_trading_state_collection,
    live_trading_trades_collection,
)
from app.services.angel_client import angel_client
from app.services.call_engine import IST, _scored_daily_symbols
from app.services.dhan_client import DhanClient
from app.services.intraday_lab_engine import _equity_quote_map, _size
from app.services.live_intraday_engine import (
    ENTRY_CUTOFF_HHMM,
    EOD_SQUAREOFF_HHMM,
    INTRADAY_CATEGORIES,
    MAX_SYMBOLS_PER_SCAN,
    PER_STRATEGY_ALLOCATION,
    POSITION_NOTIONAL,
    SELECTED,
    SELECTED_BY_ID,
    _live_signal,
)
from backtesting_service.service import load_bars
from tradingai_shared.domain import Timeframe

logger = logging.getLogger("live_trading")

STATE_ID = "engine"
DESK_CEILING = PER_STRATEGY_ALLOCATION * max(len(SELECTED), 1)  # ₹80k across the 8 names
MAX_CONSECUTIVE_REJECTS = 3        # auto-disarm after this many failed real orders in a row
PRODUCT_TYPE = "INTRADAY"          # MIS: intraday shorts allowed, everything squares off EOD
DAILY_LOSS_BREAKER_PCT = 0.03      # same 3% desk breaker as the paper desk
INITIAL_CAPITAL = PER_STRATEGY_ALLOCATION * max(len(SELECTED), 1)


class LiveTradingError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist():
    return datetime.now(IST).date()


def _session_start_utc() -> datetime:
    return datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


# ── engine state: armed / kill switch / reject streak ───────────────────────────


async def get_state() -> dict:
    st = await live_trading_state_collection.find_one({"_id": STATE_ID}) or {}
    return {
        "armed": bool(st.get("armed", False)),
        "kill_switch": bool(st.get("kill_switch", False)),
        "consecutive_rejects": int(st.get("consecutive_rejects", 0)),
        "max_consecutive_rejects": MAX_CONSECUTIVE_REJECTS,
        "armed_at": st.get("armed_at").isoformat() if st.get("armed_at") else None,
        "last_run_at": st.get("last_run_at").isoformat() if st.get("last_run_at") else None,
        "last_opened": int(st.get("last_opened", 0)),
        "last_managed": int(st.get("last_managed", 0)),
        "last_notes": st.get("last_notes", []),
        "disarmed_reason": st.get("disarmed_reason"),
        "broker_connected": bool(st.get("broker_connected", False)),
    }


async def set_armed(armed: bool, reason: str | None = None) -> dict:
    upd: dict = {"armed": bool(armed), "updated_at": _now()}
    if armed:
        upd.update({"armed_at": _now(), "consecutive_rejects": 0, "disarmed_reason": None})
    else:
        upd["disarmed_reason"] = reason
    await live_trading_state_collection.update_one({"_id": STATE_ID}, {"$set": upd}, upsert=True)
    logger.warning("[live_trading] ARMED=%s (%s)", armed, reason or "manual")
    return await get_state()


async def set_kill_switch(active: bool) -> dict:
    await live_trading_state_collection.update_one(
        {"_id": STATE_ID}, {"$set": {"kill_switch": bool(active), "updated_at": _now()}}, upsert=True
    )
    logger.warning("[live_trading] KILL SWITCH=%s", active)
    return await get_state()


async def _register_reject() -> None:
    st = await get_state()
    n = st["consecutive_rejects"] + 1
    await live_trading_state_collection.update_one(
        {"_id": STATE_ID}, {"$set": {"consecutive_rejects": n}}, upsert=True
    )
    if n >= MAX_CONSECUTIVE_REJECTS:
        await set_armed(False, reason=f"auto-disarmed after {n} consecutive order rejects")


async def _clear_rejects() -> None:
    await live_trading_state_collection.update_one(
        {"_id": STATE_ID}, {"$set": {"consecutive_rejects": 0}}, upsert=True
    )


# ── per-strategy enable flags ────────────────────────────────────────────────────


async def _enabled_map() -> dict[str, bool]:
    flags = {f["strategy_id"]: bool(f.get("enabled", True)) async for f in live_trading_flags_collection.find({})}
    return {ls.strategy_id: flags.get(ls.strategy_id, True) for ls in SELECTED}


async def set_strategy_enabled(strategy_id: str, enabled: bool) -> dict:
    if strategy_id not in SELECTED_BY_ID:
        raise LiveTradingError(f"Unknown strategy '{strategy_id}'")
    await live_trading_flags_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {"strategy_id": strategy_id, "enabled": bool(enabled), "updated_at": _now()}},
        upsert=True,
    )
    return {"strategy_id": strategy_id, "enabled": bool(enabled)}


# ── capital, scoped to this desk's own collections ──────────────────────────────


async def _deployed_capital(strategy_id: str) -> float:
    total = 0.0
    async for p in live_trading_positions_collection.find(
        {"strategy_id": strategy_id, "status": "OPEN"}, {"capital_deployed": 1}
    ):
        total += p.get("capital_deployed", 0.0)
    return total


async def _desk_deployed() -> float:
    total = 0.0
    async for p in live_trading_positions_collection.find({"status": "OPEN"}, {"capital_deployed": 1}):
        total += p.get("capital_deployed", 0.0)
    return total


async def _realized_pnl(strategy_id: str) -> float:
    total = 0.0
    async for p in live_trading_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    return total


async def _available_cash(strategy_id: str) -> float:
    return PER_STRATEGY_ALLOCATION + await _realized_pnl(strategy_id) - await _deployed_capital(strategy_id)


async def today_pnl() -> float:
    start = _session_start_utc()
    total = 0.0
    async for p in live_trading_positions_collection.find(
        {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    async for p in live_trading_positions_collection.find(
        {"status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}
    ):
        total += p.get("unrealized_pnl") or 0.0
    return total


async def breaker_state() -> dict:
    pnl = await today_pnl()
    limit = DAILY_LOSS_BREAKER_PCT * INITIAL_CAPITAL
    return {
        "breaker_tripped": pnl <= -limit,
        "today_pnl": round(pnl, 2),
        "daily_loss_limit": round(limit, 2),
        "daily_loss_pct": DAILY_LOSS_BREAKER_PCT,
    }


async def _update_score(strategy_id: str) -> None:
    ls = SELECTED_BY_ID.get(strategy_id)
    if ls is None:
        return
    closed = [
        p async for p in live_trading_positions_collection.find(
            {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
        )
    ]
    trades = len(closed)
    wins = sum(1 for p in closed if (p.get("realized_pnl") or 0) > 0)
    net_pnl = sum(p.get("realized_pnl") or 0 for p in closed)
    await live_trading_scores_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {
            "strategy_id": strategy_id, "name": ls.name, "category": ls.category, "is_anti": ls.is_anti,
            "trades": trades, "wins": wins, "win_rate": round(wins / trades, 4) if trades else 0.0,
            "net_pnl": round(net_pnl, 2), "allocated_capital": round(PER_STRATEGY_ALLOCATION + net_pnl, 2),
            "updated_at": _now(),
        }},
        upsert=True,
    )


# ── real Dhan order placement ────────────────────────────────────────────────────


async def _place_dhan_order(dhan: DhanClient, inst: dict, side: str, qty: int) -> str | None:
    """Place a REAL market INTRADAY order. Returns the Dhan orderId, or None on any
    failure (so the caller can refuse to record a position that never actually opened)."""
    try:
        result = await dhan.place_order(
            security_id=str(inst["security_id"]),
            exchange_segment=inst["exchange_segment"],
            transaction_type=side,
            quantity=int(qty),
            order_type="MARKET",
            product_type=PRODUCT_TYPE,
            price=0,
        )
    except Exception:
        logger.exception("[live_trading] Dhan order FAILED: %s %s x%s", side, inst.get("symbol"), qty)
        return None
    oid = None
    if isinstance(result, dict):
        oid = (result.get("data") or {}).get("orderId") or result.get("orderId")
    if not oid:
        logger.error("[live_trading] Dhan order returned no orderId: %s", result)
        return None
    return str(oid)


async def _open_position(ls, symbol: str, inst: dict, signal, ltp_source: str, dhan: DhanClient) -> bool:
    if await live_trading_positions_collection.find_one(
        {"strategy_id": ls.strategy_id, "symbol": symbol, "status": "OPEN"}
    ):
        return False  # one open position per symbol per strategy
    cash = await _available_cash(ls.strategy_id)
    qty = _size(signal.entry, POSITION_NOTIONAL, cash)
    if qty < 1:
        return False
    new_notional = signal.entry * qty
    # ₹80k desk-wide ceiling (the per-strategy ₹10k cap is already in `cash` above)
    if await _desk_deployed() + new_notional > DESK_CEILING + 1:
        return False

    # REAL order — only record the position if the broker accepted it
    order_id = await _place_dhan_order(dhan, inst, signal.side, qty)
    if not order_id:
        await _register_reject()
        return False
    await _clear_rejects()

    await live_trading_positions_collection.insert_one({
        "position_id": uuid4().hex[:12],
        "strategy_id": ls.strategy_id, "strategy_name": ls.name, "category": ls.category, "is_anti": ls.is_anti,
        "symbol": symbol, "display_name": symbol,
        "instrument": {
            "symbol": inst["symbol"], "security_id": inst["security_id"],
            "exchange_segment": inst["exchange_segment"], "lot_size": inst.get("lot_size", 1),
        },
        "side": signal.side, "entry_price": round(signal.entry, 2), "qty": qty,
        "capital_deployed": round(signal.entry * qty, 2),
        "target": round(signal.target, 2), "stoploss": round(signal.stoploss, 2),
        "ltp": round(signal.entry, 2), "ltp_source": ltp_source,
        "unrealized_pnl": 0.0, "pnl_pct": 0.0, "realized_pnl": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "confidence": round(signal.confidence, 2), "rationale": signal.rationale,
        "product_type": PRODUCT_TYPE, "mode": "real",
        "entry_order_id": order_id, "exit_order_id": None,
        # entry_price is the reference/signal price; the true fill price comes from Dhan and
        # is not reconciled into this ledger in v1 (matches the app's existing LiveExecutor).
        "opened_at": _now(), "opened_on": _today_ist().isoformat(), "updated_at": _now(), "closed_at": None,
    })
    logger.warning("[live_trading] REAL ENTRY %s %s x%s @~%.2f (order %s)",
                   signal.side, symbol, qty, signal.entry, order_id)
    return True


# ── scan (gated) ─────────────────────────────────────────────────────────────────


async def scan_cycle(dhan: DhanClient | None) -> dict:
    state = await get_state()
    if not state["armed"]:
        return {"opened": 0, "scanned_symbols": 0, "notes": [
            "Live Trading is DISARMED — no real orders are placed. Arm the desk to trade with real money."]}
    if state["kill_switch"]:
        return {"opened": 0, "scanned_symbols": 0, "notes": [
            "KILL SWITCH is ON — new orders halted. Open positions are still managed."]}
    if dhan is None:
        return {"opened": 0, "scanned_symbols": 0, "notes": [
            "Broker not connected — cannot place real orders. Connect Dhan in Broker Settings."]}
    breaker = await breaker_state()
    if breaker["breaker_tripped"]:
        return {"opened": 0, "scanned_symbols": 0, "notes": [
            f"DAILY LOSS BREAKER TRIPPED — today's P&L Rs{breaker['today_pnl']:,.0f} crossed the "
            f"Rs{breaker['daily_loss_limit']:,.0f} limit. No new positions this session; open ones still managed."]}

    scored = await _scored_daily_symbols()
    if not scored:
        return {"opened": 0, "scanned_symbols": 0, "notes": ["No scored symbols — backfill daily bars first."]}
    scored = scored[:MAX_SYMBOLS_PER_SCAN]
    symbols = [s for s, *_ in scored]
    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": symbols}}
    )}
    quotes, quote_source = await _equity_quote_map(dhan, list(equities.values()))
    enabled = await _enabled_map()

    notes: list[str] = []
    if not quotes:
        notes.append("No live equity quotes this cycle — only daily-bar swing signals can fire.")
    intraday_entries_closed = datetime.now(IST).strftime("%H:%M") >= ENTRY_CUTOFF_HHMM
    if intraday_entries_closed:
        notes.append(f"Past the {ENTRY_CUTOFF_HHMM} IST entry cutoff — no new entries; open positions still managed.")

    opened = 0
    for symbol, score, reasons, atr14, bars in scored:
        inst = equities.get(symbol)
        if inst is None or atr14 <= 0 or len(bars) < 2:
            continue
        key = (inst["exchange_segment"], str(inst["security_id"]))
        quote = quotes.get(key)
        ltp_source = quote_source.get(key, "last_bar_close")
        ctx = {"bars": bars, "atr14": atr14, "quote": quote, "prev_bar": bars[-2]}
        for ls in SELECTED:
            if not enabled.get(ls.strategy_id, True):
                continue  # this strategy is disabled for real trading
            if intraday_entries_closed:
                continue
            if quote is None:
                continue  # a real MARKET order needs a live quote to size and to be fillable
            signal = _live_signal(ls, symbol, ctx)
            if signal is None:
                continue
            # re-check the gate right before each order — arm/kill can flip mid-cycle
            live = await get_state()
            if not live["armed"] or live["kill_switch"]:
                notes.append("Desk was disarmed / kill-switched mid-scan — stopped placing new orders.")
                return {"opened": opened, "scanned_symbols": len(scored), "notes": notes}
            if await _open_position(ls, symbol, inst, signal, ltp_source, dhan):
                opened += 1
    return {"opened": opened, "scanned_symbols": len(scored), "notes": notes}


# ── manage (always runs, even disarmed — open real positions must be exited) ─────


async def _close_real(pos: dict, ltp: float, reason: str, dhan: DhanClient | None) -> bool:
    """Square off a real position with an opposite-side market order. Returns True only if
    the exit order was accepted (or there is nothing to send). If it fails we leave the
    position OPEN so the next cycle retries — we never mark a broker position closed on a
    failed exit."""
    exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
    if dhan is None:
        return False
    oid = await _place_dhan_order(dhan, pos["instrument"], exit_side, pos["qty"])
    if not oid:
        await _register_reject()
        return False
    await _clear_rejects()
    sign = 1 if pos["side"] == "BUY" else -1
    realized = round(sign * (ltp - pos["entry_price"]) * pos["qty"], 2)
    await live_trading_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "status": "CLOSED", "exit_price": round(ltp, 2), "exit_reason": reason,
        "realized_pnl": realized, "unrealized_pnl": 0.0, "exit_order_id": oid,
        "ltp": round(ltp, 2), "updated_at": _now(), "closed_at": _now(),
    }})
    await live_trading_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "strategy_id": pos["strategy_id"], "strategy_name": pos["strategy_name"],
        "symbol": pos["symbol"], "side": pos["side"], "entry_price": pos["entry_price"], "exit_price": round(ltp, 2),
        "qty": pos["qty"], "realized_pnl": realized, "exit_reason": reason,
        "entry_order_id": pos.get("entry_order_id"), "exit_order_id": oid,
        "opened_at": pos["opened_at"], "closed_at": _now(),
    })
    logger.warning("[live_trading] REAL EXIT %s %s x%s @~%.2f (%s, pnl %.2f, order %s)",
                   exit_side, pos["symbol"], pos["qty"], ltp, reason, realized, oid)
    return True


async def manage_cycle(dhan: DhanClient | None) -> int:
    open_positions = [p async for p in live_trading_positions_collection.find({"status": "OPEN"})]
    if not open_positions:
        return 0
    by_symbol: dict[str, list[dict]] = {}
    for p in open_positions:
        by_symbol.setdefault(p["symbol"], []).append(p)
    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": list(by_symbol.keys())}}
    )}
    quotes, quote_source = await _equity_quote_map(dhan, list(equities.values()))

    now_ist = datetime.now(IST)
    is_eod = now_ist.strftime("%H:%M") >= EOD_SQUAREOFF_HHMM

    updated = 0
    touched: set[str] = set()
    for symbol, positions in by_symbol.items():
        inst = equities.get(symbol)
        ltp, ltp_source = None, None
        if inst:
            q = quotes.get((inst["exchange_segment"], str(inst["security_id"])))
            if q:
                ltp = float(q["last_price"])
                ltp_source = quote_source[(inst["exchange_segment"], str(inst["security_id"]))]
        if ltp is None:
            bars = await to_thread.run_sync(load_bars, symbol, Timeframe.D1, 0.1)
            if bars:
                ltp, ltp_source = bars[-1].close, "last_bar_close"
        if ltp is None:
            continue

        for pos in positions:
            sign = 1 if pos["side"] == "BUY" else -1
            unrealized = round(sign * (ltp - pos["entry_price"]) * pos["qty"], 2)
            await live_trading_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
                "ltp": round(ltp, 2), "ltp_source": ltp_source, "unrealized_pnl": unrealized,
                "pnl_pct": round(sign * (ltp - pos["entry_price"]) / pos["entry_price"] * 100, 2) if pos["entry_price"] else 0.0,
                "updated_at": _now(),
            }})
            updated += 1

            hit_target = ltp >= pos["target"] if sign > 0 else ltp <= pos["target"]
            hit_stop = ltp <= pos["stoploss"] if sign > 0 else ltp >= pos["stoploss"]
            # INTRADAY product: every position squares off same day, so EOD closes everything.
            reason = "target" if hit_target else "stoploss" if hit_stop else "eod" if is_eod else None
            if reason and await _close_real(pos, ltp, reason, dhan):
                touched.add(pos["strategy_id"])

    for strategy_id in touched:
        await _update_score(strategy_id)
    return updated


async def panic_close_all(dhan: DhanClient | None) -> dict:
    """Square off every open position immediately, then disarm and trip the kill switch."""
    open_positions = [p async for p in live_trading_positions_collection.find({"status": "OPEN"})]
    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": [p["symbol"] for p in open_positions]}}
    )} if open_positions else {}
    quotes, _ = await _equity_quote_map(dhan, list(equities.values())) if equities else ({}, {})

    closed = failed = 0
    touched: set[str] = set()
    for pos in open_positions:
        inst = equities.get(pos["symbol"])
        ltp = pos.get("ltp") or pos["entry_price"]
        if inst:
            q = quotes.get((inst["exchange_segment"], str(inst["security_id"])))
            if q:
                ltp = float(q["last_price"])
        if await _close_real(pos, ltp, "panic", dhan):
            closed += 1
            touched.add(pos["strategy_id"])
        else:
            failed += 1
    for strategy_id in touched:
        await _update_score(strategy_id)
    await set_kill_switch(True)
    await set_armed(False, reason="panic close-all")
    return {"closed": closed, "failed": failed, "armed": False, "kill_switch": True}


# ── read models ──────────────────────────────────────────────────────────────────


async def summary() -> dict:
    deployed = realized = unrealized = 0.0
    async for p in live_trading_positions_collection.find({"status": "OPEN"}, {"capital_deployed": 1, "unrealized_pnl": 1}):
        deployed += p.get("capital_deployed", 0.0)
        unrealized += p.get("unrealized_pnl") or 0.0
    async for p in live_trading_positions_collection.find({"status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        realized += p.get("realized_pnl") or 0.0
    open_count = await live_trading_positions_collection.count_documents({"status": "OPEN"})
    closed_count = await live_trading_positions_collection.count_documents({"status": {"$ne": "OPEN"}})
    state = await get_state()
    return {
        "mode": "real",
        "armed": state["armed"],
        "kill_switch": state["kill_switch"],
        "consecutive_rejects": state["consecutive_rejects"],
        "max_consecutive_rejects": MAX_CONSECUTIVE_REJECTS,
        "disarmed_reason": state["disarmed_reason"],
        "broker_connected": state["broker_connected"],
        "last_run_at": state["last_run_at"],
        "last_notes": state["last_notes"],
        "initial_capital": INITIAL_CAPITAL,
        "desk_ceiling": DESK_CEILING,
        "per_strategy_allocation": round(PER_STRATEGY_ALLOCATION, 2),
        "position_notional": round(POSITION_NOTIONAL, 2),
        "available_cash": round(INITIAL_CAPITAL + realized - deployed, 2),
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "equity": round(INITIAL_CAPITAL + realized + unrealized, 2),
        "open_positions": open_count,
        "closed_positions": closed_count,
        "strategy_count": len(SELECTED),
        **(await breaker_state()),
    }


async def leaderboard() -> list[dict]:
    scores = {s["strategy_id"]: s async for s in live_trading_scores_collection.find({})}
    enabled = await _enabled_map()
    rows = []
    for ls in SELECTED:
        sc = scores.get(ls.strategy_id) or {}
        net_pnl = sc.get("net_pnl", 0.0) or 0.0
        rows.append({
            "strategy_id": ls.strategy_id, "name": ls.name, "category": ls.category, "is_anti": ls.is_anti,
            "trades": sc.get("trades", 0) or 0, "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "net_pnl": round(net_pnl, 2),
            "allocated_capital": round(PER_STRATEGY_ALLOCATION + net_pnl, 2),
            "enabled": enabled.get(ls.strategy_id, True),
        })
    rows.sort(key=lambda r: r["net_pnl"], reverse=True)
    return rows


async def open_positions() -> list[dict]:
    rows = []
    async for p in live_trading_positions_collection.find({"status": "OPEN"}).sort("opened_at", -1):
        rows.append({
            "position_id": p.get("position_id"), "symbol": p["symbol"], "strategy_name": p.get("strategy_name"),
            "is_anti": p.get("is_anti", False), "side": p["side"], "qty": p["qty"],
            "entry_price": p["entry_price"], "ltp": p.get("ltp"), "ltp_source": p.get("ltp_source"),
            "target": p["target"], "stoploss": p["stoploss"],
            "unrealized_pnl": p.get("unrealized_pnl") or 0.0, "pnl_pct": p.get("pnl_pct") or 0.0,
            "entry_order_id": p.get("entry_order_id"),
        })
    return rows


# ── the tick ─────────────────────────────────────────────────────────────────────


async def run_cycle(dhan: DhanClient | None) -> dict:
    managed = await manage_cycle(dhan)   # ALWAYS manage open real positions
    scan_result = await scan_cycle(dhan)  # gated by armed / kill / breaker / broker
    snap = await summary()
    await live_trading_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "deployed": snap["deployed_capital"], "open_positions": snap["open_positions"],
    })
    await live_trading_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {
            "last_run_at": _now(), "last_opened": scan_result["opened"], "last_managed": managed,
            "last_notes": scan_result["notes"], "broker_connected": dhan is not None,
            "angel_configured": angel_client.configured(),
        }},
        upsert=True,
    )
    return {"opened": scan_result["opened"], "managed": managed,
            "scanned_symbols": scan_result["scanned_symbols"], "notes": scan_result["notes"]}
