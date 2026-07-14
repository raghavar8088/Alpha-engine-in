"""Intraday Strategy Lab engine — auto-trading paper desk over the 50-strategy
catalog in `intraday_strategies.py`.

Capital model: a single ₹1,00,00,000 (1 crore) pool is split into 50 equal
per-strategy allocations (~₹2L each, see `PER_STRATEGY_ALLOCATION`). Each
strategy trades only its own slice — one open paper position per symbol per
strategy — sized by `allocated capital * spec.risk_pct`, with target/stop taken
directly from the strategy's own signal (already ATR-derived).

Lifecycle:
- scan: for every strategy, for every scored equity symbol without an open
  position under that strategy, evaluate the strategy's signal function; open a
  paper position when it fires.
- manage: refresh LTP for every open position (live Dhan quote, else last daily
  bar close — never fabricated), close on target/stop hit; scalping/momentum/
  mean_reversion positions are also force-closed at EOD 15:15 IST; swing
  positions may carry over up to `spec.max_hold_days` trading days.
- On every close, update that strategy's leaderboard doc (trades, win rate, net
  P&L, current allocated capital = its slice + its own realized P&L).

Paper only — no live broker orders. Honest about price sourcing exactly like
call_engine.py (`ltp_source`: dhan_quote / last_bar_close).
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from anyio import to_thread

from app.core.db import (
    instruments_collection,
    intraday_lab_positions_collection,
    intraday_lab_scores_collection,
    intraday_lab_state_collection,
    intraday_lab_trades_collection,
)
from app.services.call_engine import IST, _quote_batch, _scored_daily_symbols
from app.services.dhan_client import DhanClient
from app.services.intraday_strategies import STRATEGY_CATALOG, STRATEGY_BY_ID, evaluate
from backtesting_service.service import load_bars
from tradingai_shared.domain import Timeframe

logger = logging.getLogger("intraday_lab")

INTRADAY_LAB_INITIAL_CAPITAL = float(os.getenv("INTRADAY_LAB_INITIAL_CAPITAL", "10000000"))  # ₹1 crore
PER_STRATEGY_ALLOCATION = INTRADAY_LAB_INITIAL_CAPITAL / max(len(STRATEGY_CATALOG), 1)
MAX_SYMBOLS_PER_SCAN = int(os.getenv("INTRADAY_LAB_MAX_SYMBOLS", "150"))  # keeps one Dhan quote call bounded

EOD_SQUAREOFF_HHMM = "15:15"
INTRADAY_CATEGORIES = {"scalping", "momentum", "mean_reversion"}  # square off same day
SWING_CATEGORIES = {"swing"}  # may carry up to spec.max_hold_days trading days

STATE_ID = "intraday_lab"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist():
    return datetime.now(IST).date()


async def _open_positions_count(strategy_id: str) -> int:
    return await intraday_lab_positions_collection.count_documents({"strategy_id": strategy_id, "status": "OPEN"})


async def _deployed_capital(strategy_id: str) -> float:
    total = 0.0
    async for p in intraday_lab_positions_collection.find(
        {"strategy_id": strategy_id, "status": "OPEN"}, {"capital_deployed": 1}
    ):
        total += p.get("capital_deployed", 0.0)
    return total


async def _realized_pnl(strategy_id: str) -> float:
    total = 0.0
    async for p in intraday_lab_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    return total


async def _available_cash(strategy_id: str) -> float:
    deployed = await _deployed_capital(strategy_id)
    realized = await _realized_pnl(strategy_id)
    return PER_STRATEGY_ALLOCATION + realized - deployed


def _size(entry_price: float, budget: float, cash: float) -> int:
    """Whole shares only (equities, lot size 1) affordable within this
    strategy's remaining budget/cash, whichever is tighter."""
    if entry_price <= 0:
        return 0
    cap = min(budget, cash)
    qty = int(cap // entry_price)
    return max(qty, 0)


async def _update_score(strategy_id: str) -> None:
    spec = STRATEGY_BY_ID.get(strategy_id)
    if spec is None:
        return
    closed = [
        p async for p in intraday_lab_positions_collection.find(
            {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
        )
    ]
    trades = len(closed)
    wins = sum(1 for p in closed if (p.get("realized_pnl") or 0) > 0)
    net_pnl = sum(p.get("realized_pnl") or 0 for p in closed)
    win_rate = round(wins / trades, 4) if trades else 0.0
    allocated_capital = round(PER_STRATEGY_ALLOCATION + net_pnl, 2)
    await intraday_lab_scores_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {
            "strategy_id": strategy_id, "name": spec.name, "category": spec.category,
            "trades": trades, "wins": wins, "win_rate": win_rate,
            "net_pnl": round(net_pnl, 2), "allocated_capital": allocated_capital,
            "updated_at": _now(),
        }},
        upsert=True,
    )


async def _open_position(spec, symbol: str, inst: dict, signal, ltp_source: str) -> bool:
    if await _open_positions_count(spec.strategy_id) >= 200:  # sane per-strategy cap
        return False
    existing = await intraday_lab_positions_collection.find_one(
        {"strategy_id": spec.strategy_id, "symbol": symbol, "status": "OPEN"}
    )
    if existing is not None:
        return False

    cash = await _available_cash(spec.strategy_id)
    budget = PER_STRATEGY_ALLOCATION * spec.risk_pct
    qty = _size(signal.entry, budget, cash)
    if qty < 1:
        return False

    doc = {
        "position_id": uuid4().hex[:12],
        "strategy_id": spec.strategy_id,
        "strategy_name": spec.name,
        "category": spec.category,
        "symbol": symbol,
        "display_name": symbol,
        "instrument": {
            "symbol": inst["symbol"], "security_id": inst["security_id"],
            "exchange_segment": inst["exchange_segment"], "lot_size": inst.get("lot_size", 1),
        },
        "side": signal.side,
        "entry_price": round(signal.entry, 2),
        "qty": qty,
        "capital_deployed": round(signal.entry * qty, 2),
        "target": round(signal.target, 2),
        "stoploss": round(signal.stoploss, 2),
        "ltp": round(signal.entry, 2),
        "ltp_source": ltp_source,
        "unrealized_pnl": 0.0,
        "pnl_pct": 0.0,
        "realized_pnl": None,
        "exit_price": None,
        "exit_reason": None,
        "status": "OPEN",
        "confidence": round(signal.confidence, 2),
        "rationale": signal.rationale,
        "max_hold_days": spec.max_hold_days,
        "opened_at": _now(),
        "opened_on": _today_ist().isoformat(),
        "updated_at": _now(),
        "closed_at": None,
    }
    await intraday_lab_positions_collection.insert_one(doc)
    return True


async def scan_cycle(dhan: DhanClient | None) -> dict:
    """One scan pass across every strategy x scored symbol. Returns a summary
    dict {opened, scanned_symbols, notes}."""
    scored = await _scored_daily_symbols()
    if not scored:
        return {"opened": 0, "scanned_symbols": 0, "notes": ["No scored symbols — backfill daily bars first."]}
    scored = scored[:MAX_SYMBOLS_PER_SCAN]

    symbols = [s for s, *_ in scored]
    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": symbols}}
    )}
    wanted: dict[str, list[int]] = {}
    for symbol in symbols:
        inst = equities.get(symbol)
        if inst:
            wanted.setdefault(inst["exchange_segment"], []).append(int(inst["security_id"]))
    quotes = await _quote_batch(dhan, wanted)

    notes = []
    if dhan is None:
        notes.append("No Dhan connection — intraday-context strategies (scalping/momentum/mean_reversion) skipped this cycle; only daily-bar swing signals can fire.")

    opened = 0
    for symbol, score, reasons, atr14, bars in scored:
        inst = equities.get(symbol)
        if inst is None or atr14 <= 0 or len(bars) < 2:
            continue
        key = (inst["exchange_segment"], str(inst["security_id"]))
        quote = quotes.get(key)
        ltp_source = "dhan_quote" if quote else "last_bar_close"
        ctx = {"bars": bars, "atr14": atr14, "quote": quote, "prev_bar": bars[-2]}
        for spec in STRATEGY_CATALOG:
            if spec.category != "swing" and quote is None:
                continue  # honest skip — no live intraday context available
            signal = evaluate(spec, symbol, ctx)
            if signal is None:
                continue
            if await _open_position(spec, symbol, inst, signal, ltp_source):
                opened += 1
    return {"opened": opened, "scanned_symbols": len(scored), "notes": notes}


async def manage_cycle(dhan: DhanClient | None) -> int:
    """Refresh LTP/PnL for every open position; close on target/stop, EOD
    square-off (scalping/momentum/mean_reversion at 15:15 IST), or swing
    max-hold-days expiry. Returns count of positions updated (incl. closed)."""
    open_positions = [p async for p in intraday_lab_positions_collection.find({"status": "OPEN"})]
    if not open_positions:
        return 0

    by_symbol: dict[str, list[dict]] = {}
    for p in open_positions:
        by_symbol.setdefault(p["symbol"], []).append(p)

    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": list(by_symbol.keys())}}
    )}
    wanted: dict[str, list[int]] = {}
    for symbol, inst in equities.items():
        wanted.setdefault(inst["exchange_segment"], []).append(int(inst["security_id"]))
    quotes = await _quote_batch(dhan, wanted)

    now_ist = datetime.now(IST)
    is_eod = now_ist.strftime("%H:%M") >= EOD_SQUAREOFF_HHMM
    today_iso = _today_ist().isoformat()

    updated = 0
    touched_strategies: set[str] = set()
    for symbol, positions in by_symbol.items():
        inst = equities.get(symbol)
        ltp, ltp_source = None, None
        if inst:
            key = (inst["exchange_segment"], str(inst["security_id"]))
            q = quotes.get(key)
            if q:
                ltp, ltp_source = float(q["last_price"]), "dhan_quote"
        if ltp is None:
            bars = await to_thread.run_sync(load_bars, symbol, Timeframe.D1, 0.1)
            if bars:
                ltp, ltp_source = bars[-1].close, "last_bar_close"
        if ltp is None:
            continue  # honest skip — no price available at all

        for pos in positions:
            sign = 1 if pos["side"] == "BUY" else -1
            unrealized = round(sign * (ltp - pos["entry_price"]) * pos["qty"], 2)
            changes: dict = {
                "ltp": round(ltp, 2), "ltp_source": ltp_source,
                "unrealized_pnl": unrealized,
                "pnl_pct": round(sign * (ltp - pos["entry_price"]) / pos["entry_price"] * 100, 2) if pos["entry_price"] else 0.0,
                "updated_at": _now(),
            }

            hit_target = ltp >= pos["target"] if sign > 0 else ltp <= pos["target"]
            hit_stop = ltp <= pos["stoploss"] if sign > 0 else ltp >= pos["stoploss"]
            category = pos.get("category")
            eod_close = category in INTRADAY_CATEGORIES and is_eod
            days_held = (datetime.fromisoformat(today_iso).date() - datetime.fromisoformat(pos["opened_on"]).date()).days
            swing_expired = category in SWING_CATEGORIES and days_held >= pos.get("max_hold_days", 5)

            reason = None
            if hit_target:
                reason = "target"
            elif hit_stop:
                reason = "stoploss"
            elif eod_close:
                reason = "eod"
            elif swing_expired:
                reason = "max_hold_expired"

            if reason:
                changes["status"] = "CLOSED"
                changes["exit_price"] = round(ltp, 2)
                changes["exit_reason"] = reason
                changes["realized_pnl"] = unrealized
                changes["unrealized_pnl"] = 0.0
                changes["closed_at"] = _now()
                touched_strategies.add(pos["strategy_id"])
                await intraday_lab_trades_collection.insert_one({
                    "trade_id": uuid4().hex[:12],
                    "strategy_id": pos["strategy_id"], "strategy_name": pos["strategy_name"],
                    "symbol": symbol, "side": pos["side"], "entry_price": pos["entry_price"],
                    "exit_price": round(ltp, 2), "qty": pos["qty"], "realized_pnl": unrealized,
                    "exit_reason": reason, "opened_at": pos["opened_at"], "closed_at": _now(),
                })

            await intraday_lab_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
            updated += 1

    for strategy_id in touched_strategies:
        await _update_score(strategy_id)
    return updated


async def run_cycle(dhan: DhanClient | None) -> dict:
    """One full scan+manage pass — used by both the background loop and the
    manual 'Run now' endpoint."""
    managed = await manage_cycle(dhan)
    scan_result = await scan_cycle(dhan)
    await intraday_lab_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {
            "last_run_at": _now(), "last_opened": scan_result["opened"],
            "last_managed": managed, "last_notes": scan_result["notes"],
            "broker_connected": dhan is not None,
        }},
        upsert=True,
    )
    return {"opened": scan_result["opened"], "managed": managed, "scanned_symbols": scan_result["scanned_symbols"], "notes": scan_result["notes"]}


async def summary() -> dict:
    deployed = 0.0
    async for p in intraday_lab_positions_collection.find({"status": "OPEN"}, {"capital_deployed": 1}):
        deployed += p.get("capital_deployed", 0.0)
    realized = 0.0
    async for p in intraday_lab_positions_collection.find({"status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        realized += p.get("realized_pnl") or 0.0
    unrealized = 0.0
    async for p in intraday_lab_positions_collection.find({"status": "OPEN"}, {"unrealized_pnl": 1}):
        unrealized += p.get("unrealized_pnl") or 0.0
    equity = INTRADAY_LAB_INITIAL_CAPITAL + realized + unrealized
    open_count = await intraday_lab_positions_collection.count_documents({"status": "OPEN"})
    closed_count = await intraday_lab_positions_collection.count_documents({"status": {"$ne": "OPEN"}})
    return {
        "initial_capital": INTRADAY_LAB_INITIAL_CAPITAL,
        "per_strategy_allocation": round(PER_STRATEGY_ALLOCATION, 2),
        "available_cash": round(INTRADAY_LAB_INITIAL_CAPITAL + realized - deployed, 2),
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "equity": round(equity, 2),
        "open_positions": open_count,
        "closed_positions": closed_count,
        "strategy_count": len(STRATEGY_CATALOG),
    }
