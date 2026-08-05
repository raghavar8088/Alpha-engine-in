"""Live Intraday desk — a small, curated paper-trading desk INSIDE the Intraday
Stocks module, separate from the 150-strategy tournament (intraday_lab_engine).

Unlike the tournament (every strategy, ₹10 lakh each), this is the hand-picked
shortlist the user selected to take toward real money: a fixed set of strategies,
each on its own ₹10,000 paper account (₹80,000 desk total), trading on the SAME
live Angel-One equity feed. Paper today; the plan is to route these same signals
to a real broker once the shortlist proves out.

Six of the eight picks are ANTI strategies. An ANTI is the REVERSE of its base
strategy — same entry, opposite side, with target/stop swapped — so when the base
would lose, this gains. The tournament shows ANTI only as a computed mirror; here
it is a REAL reverse trade: the engine flips the base signal to the opposite side
(the intraday engine already supports shorts) with SL<->TP swapped, and manages it
to those levels. So the ANTI rows on this desk are genuine positions, not a mirror.

Everything else mirrors intraday_lab_engine: Angel-first quotes, honest last-bar
fallback, per-strategy independent account, EOD square-off for same-day categories,
swing carry to max_hold_days, a daily-loss breaker scaled to this desk.
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from anyio import to_thread

from app.core.db import (
    instruments_collection,
    live_intraday_equity_collection,
    live_intraday_positions_collection,
    live_intraday_scores_collection,
    live_intraday_state_collection,
    live_intraday_trades_collection,
)
from app.services.angel_client import angel_client
from app.services.call_engine import IST, _scored_daily_symbols
from app.services.dhan_client import DhanClient
from app.services.intraday_lab_engine import _equity_quote_map, _size
from app.services.intraday_strategies import STRATEGY_CATALOG, Signal, evaluate
from backtesting_service.service import load_bars
from tradingai_shared.domain import Timeframe

logger = logging.getLogger("live_intraday")

STATE_ID = "engine"

# Curated shortlist the user picked to trade with real money (paper for now). Names are
# the leaderboard display names; an "ANTI " prefix means trade the REVERSE of that base
# strategy. Edit this list (env LIVE_INTRADAY_STRATEGIES, "|"-separated) to re-pick.
_DEFAULT_SELECTION = [
    "ANTI EMA20 Pullback Swing 2.0%",
    "ANTI EMA20 Pullback Swing 2.5%",
    "ANTI EMA20 Pullback Swing 1.5%",
    "ANTI EMA20 Pullback Swing 1.0%",
    "ANTI Breakout Retest (10d) Swing",
    "ANTI Breakout Retest (30d) Swing",
    "Aroon25 Trend Up80",
    "ANTI Momentum Swing ROC20",
]
SELECTED_NAMES = [n.strip() for n in os.getenv("LIVE_INTRADAY_STRATEGIES", "|".join(_DEFAULT_SELECTION)).split("|") if n.strip()]

# ₹10,000 per strategy, ₹10,000 uniform per position → ₹80,000 across the 8-name desk.
PER_STRATEGY_ALLOCATION = float(os.getenv("LIVE_INTRADAY_PER_STRATEGY_CAPITAL", "10000"))
POSITION_NOTIONAL = float(os.getenv("LIVE_INTRADAY_POSITION_NOTIONAL", "10000"))
MAX_SYMBOLS_PER_SCAN = int(os.getenv("LIVE_INTRADAY_MAX_SYMBOLS", "150"))
# Armed by default — the user explicitly wants this desk trading paper now.
PAUSE_NEW_ENTRIES = os.getenv("LIVE_INTRADAY_PAUSE_ENTRIES", "0").lower() not in ("0", "false", "")

EOD_SQUAREOFF_HHMM = "15:15"
ENTRY_CUTOFF_HHMM = os.getenv("LIVE_INTRADAY_ENTRY_CUTOFF", "15:00")
INTRADAY_CATEGORIES = {"scalping", "momentum", "mean_reversion"}
SWING_CATEGORIES = {"swing"}
DAILY_LOSS_BREAKER_PCT = float(os.getenv("LIVE_INTRADAY_DAILY_LOSS_PCT", "0.03"))


@dataclass
class LiveStrategy:
    strategy_id: str          # "anti_intraday_042" for an anti, else the base id
    name: str                 # leaderboard display name (with "ANTI " if reversed)
    category: str
    is_anti: bool
    max_hold_days: int
    spec: object              # the base StrategySpec whose signal we evaluate


def _resolve_selection() -> list[LiveStrategy]:
    by_name = {s.name: s for s in STRATEGY_CATALOG}
    out: list[LiveStrategy] = []
    for disp in SELECTED_NAMES:
        is_anti = disp.startswith("ANTI ")
        base_name = disp[5:] if is_anti else disp
        spec = by_name.get(base_name)
        if spec is None:
            logger.warning("[live_intraday] selected strategy not found in catalog: %r", disp)
            continue
        out.append(LiveStrategy(
            strategy_id=f"anti_{spec.strategy_id}" if is_anti else spec.strategy_id,
            name=disp, category=spec.category, is_anti=is_anti,
            max_hold_days=spec.max_hold_days, spec=spec,
        ))
    return out


SELECTED: list[LiveStrategy] = _resolve_selection()
SELECTED_BY_ID: dict[str, LiveStrategy] = {ls.strategy_id: ls for ls in SELECTED}
INITIAL_CAPITAL = PER_STRATEGY_ALLOCATION * max(len(SELECTED), 1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist():
    return datetime.now(IST).date()


def _session_start_utc() -> datetime:
    return datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _live_signal(ls: LiveStrategy, symbol: str, ctx: dict):
    """The base strategy's signal, REVERSED for an ANTI (opposite side, SL<->TP
    swapped) so its P&L is the inverse of the base — a real reverse trade the engine
    then manages to the swapped levels."""
    sig = evaluate(ls.spec, symbol, ctx)
    if sig is None:
        return None
    if not ls.is_anti:
        return sig
    if sig.target <= sig.stoploss and sig.side == "BUY":
        return None  # malformed base — don't build a degenerate reverse
    return Signal(
        side="SELL" if sig.side == "BUY" else "BUY",
        entry=sig.entry,
        target=sig.stoploss,   # base stop becomes the reverse target
        stoploss=sig.target,   # base target becomes the reverse stop
        confidence=sig.confidence,
        rationale=f"ANTI (reverse of base): {sig.rationale}",
    )


# ---- capital / scoring, scoped to this desk's own collections ------------------


async def _deployed_capital(strategy_id: str) -> float:
    total = 0.0
    async for p in live_intraday_positions_collection.find(
        {"strategy_id": strategy_id, "status": "OPEN"}, {"capital_deployed": 1}
    ):
        total += p.get("capital_deployed", 0.0)
    return total


async def _realized_pnl(strategy_id: str) -> float:
    total = 0.0
    async for p in live_intraday_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    return total


async def _available_cash(strategy_id: str) -> float:
    return PER_STRATEGY_ALLOCATION + await _realized_pnl(strategy_id) - await _deployed_capital(strategy_id)


async def today_pnl() -> float:
    start = _session_start_utc()
    total = 0.0
    async for p in live_intraday_positions_collection.find(
        {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    async for p in live_intraday_positions_collection.find(
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
        p async for p in live_intraday_positions_collection.find(
            {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
        )
    ]
    trades = len(closed)
    wins = sum(1 for p in closed if (p.get("realized_pnl") or 0) > 0)
    net_pnl = sum(p.get("realized_pnl") or 0 for p in closed)
    await live_intraday_scores_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {
            "strategy_id": strategy_id, "name": ls.name, "category": ls.category, "is_anti": ls.is_anti,
            "trades": trades, "wins": wins, "win_rate": round(wins / trades, 4) if trades else 0.0,
            "net_pnl": round(net_pnl, 2), "allocated_capital": round(PER_STRATEGY_ALLOCATION + net_pnl, 2),
            "updated_at": _now(),
        }},
        upsert=True,
    )


async def _open_position(ls: LiveStrategy, symbol: str, inst: dict, signal, ltp_source: str) -> bool:
    if await live_intraday_positions_collection.find_one(
        {"strategy_id": ls.strategy_id, "symbol": symbol, "status": "OPEN"}
    ):
        return False  # one open position per symbol per strategy
    cash = await _available_cash(ls.strategy_id)
    qty = _size(signal.entry, POSITION_NOTIONAL, cash)
    if qty < 1:
        return False
    await live_intraday_positions_collection.insert_one({
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
        "max_hold_days": ls.max_hold_days,
        "opened_at": _now(), "opened_on": _today_ist().isoformat(), "updated_at": _now(), "closed_at": None,
    })
    return True


async def scan_cycle(dhan: DhanClient | None) -> dict:
    breaker = await breaker_state()
    if breaker["breaker_tripped"]:
        return {"opened": 0, "scanned_symbols": 0, "notes": [
            f"DAILY LOSS BREAKER TRIPPED — today's P&L Rs{breaker['today_pnl']:,.0f} crossed the "
            f"Rs{breaker['daily_loss_limit']:,.0f} limit. No new positions this session; open ones still managed."
        ]}
    scored = await _scored_daily_symbols()
    if not scored:
        return {"opened": 0, "scanned_symbols": 0, "notes": ["No scored symbols — backfill daily bars first."]}
    scored = scored[:MAX_SYMBOLS_PER_SCAN]
    symbols = [s for s, *_ in scored]
    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": symbols}}
    )}
    quotes, quote_source = await _equity_quote_map(dhan, list(equities.values()))

    notes: list[str] = []
    if not quotes:
        notes.append("No live equity quotes this cycle — only daily-bar swing signals can fire.")
    intraday_entries_closed = datetime.now(IST).strftime("%H:%M") >= ENTRY_CUTOFF_HHMM
    if intraday_entries_closed:
        notes.append(f"Past the {ENTRY_CUTOFF_HHMM} IST entry cutoff — no new same-day entries; open positions still managed.")

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
            if ls.category in INTRADAY_CATEGORIES and intraday_entries_closed:
                continue
            if ls.category != "swing" and quote is None:
                continue  # no live intraday context available
            signal = _live_signal(ls, symbol, ctx)
            if signal is None:
                continue
            if await _open_position(ls, symbol, inst, signal, ltp_source):
                opened += 1
    return {"opened": opened, "scanned_symbols": len(scored), "notes": notes}


async def manage_cycle(dhan: DhanClient | None) -> int:
    open_positions = [p async for p in live_intraday_positions_collection.find({"status": "OPEN"})]
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
    today_iso = _today_ist().isoformat()

    updated = 0
    touched: set[str] = set()
    for symbol, positions in by_symbol.items():
        inst = equities.get(symbol)
        ltp, ltp_source = None, None
        if inst:
            q = quotes.get((inst["exchange_segment"], str(inst["security_id"])))
            if q:
                ltp, ltp_source = float(q["last_price"]), quote_source[(inst["exchange_segment"], str(inst["security_id"]))]
        if ltp is None:
            bars = await to_thread.run_sync(load_bars, symbol, Timeframe.D1, 0.1)
            if bars:
                ltp, ltp_source = bars[-1].close, "last_bar_close"
        if ltp is None:
            continue

        for pos in positions:
            sign = 1 if pos["side"] == "BUY" else -1
            unrealized = round(sign * (ltp - pos["entry_price"]) * pos["qty"], 2)
            changes: dict = {
                "ltp": round(ltp, 2), "ltp_source": ltp_source, "unrealized_pnl": unrealized,
                "pnl_pct": round(sign * (ltp - pos["entry_price"]) / pos["entry_price"] * 100, 2) if pos["entry_price"] else 0.0,
                "updated_at": _now(),
            }
            hit_target = ltp >= pos["target"] if sign > 0 else ltp <= pos["target"]
            hit_stop = ltp <= pos["stoploss"] if sign > 0 else ltp >= pos["stoploss"]
            category = pos.get("category")
            days_held = (datetime.fromisoformat(today_iso).date() - datetime.fromisoformat(pos["opened_on"]).date()).days
            eod_close = category in INTRADAY_CATEGORIES and (is_eod or days_held >= 1)
            swing_expired = category in SWING_CATEGORIES and days_held >= pos.get("max_hold_days", 5)

            reason = "target" if hit_target else "stoploss" if hit_stop else "eod" if eod_close else "max_hold_expired" if swing_expired else None
            if reason:
                changes.update({
                    "status": "CLOSED", "exit_price": round(ltp, 2), "exit_reason": reason,
                    "realized_pnl": unrealized, "unrealized_pnl": 0.0, "closed_at": _now(),
                })
                touched.add(pos["strategy_id"])
                await live_intraday_trades_collection.insert_one({
                    "trade_id": uuid4().hex[:12], "strategy_id": pos["strategy_id"], "strategy_name": pos["strategy_name"],
                    "symbol": symbol, "side": pos["side"], "entry_price": pos["entry_price"], "exit_price": round(ltp, 2),
                    "qty": pos["qty"], "realized_pnl": unrealized, "exit_reason": reason,
                    "opened_at": pos["opened_at"], "closed_at": _now(),
                })
            await live_intraday_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
            updated += 1

    for strategy_id in touched:
        await _update_score(strategy_id)
    return updated


async def summary() -> dict:
    deployed = realized = unrealized = 0.0
    async for p in live_intraday_positions_collection.find({"status": "OPEN"}, {"capital_deployed": 1, "unrealized_pnl": 1}):
        deployed += p.get("capital_deployed", 0.0)
        unrealized += p.get("unrealized_pnl") or 0.0
    async for p in live_intraday_positions_collection.find({"status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        realized += p.get("realized_pnl") or 0.0
    open_count = await live_intraday_positions_collection.count_documents({"status": "OPEN"})
    closed_count = await live_intraday_positions_collection.count_documents({"status": {"$ne": "OPEN"}})
    return {
        "initial_capital": INITIAL_CAPITAL,
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
        "paused": PAUSE_NEW_ENTRIES,
        "mode": "paper",
        **(await breaker_state()),
    }


async def leaderboard() -> list[dict]:
    scores = {s["strategy_id"]: s async for s in live_intraday_scores_collection.find({})}
    rows = []
    for ls in SELECTED:
        sc = scores.get(ls.strategy_id) or {}
        net_pnl = sc.get("net_pnl", 0.0) or 0.0
        rows.append({
            "strategy_id": ls.strategy_id, "name": ls.name, "category": ls.category, "is_anti": ls.is_anti,
            "trades": sc.get("trades", 0) or 0, "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "net_pnl": round(net_pnl, 2),
            "allocated_capital": round(PER_STRATEGY_ALLOCATION + net_pnl, 2),
        })
    rows.sort(key=lambda r: r["net_pnl"], reverse=True)
    return rows


async def run_cycle(dhan: DhanClient | None) -> dict:
    managed = await manage_cycle(dhan)
    if PAUSE_NEW_ENTRIES:
        scan_result = {"opened": 0, "scanned_symbols": 0, "notes": ["Live Intraday entries are paused; open positions still managed."]}
    else:
        scan_result = await scan_cycle(dhan)
    snap = await summary()
    await live_intraday_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "deployed": snap["deployed_capital"], "open_positions": snap["open_positions"],
    })
    await live_intraday_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {
            "last_run_at": _now(), "last_opened": scan_result["opened"], "last_managed": managed,
            "last_notes": scan_result["notes"], "broker_connected": dhan is not None,
            "angel_configured": angel_client.configured(), "paused": PAUSE_NEW_ENTRIES,
        }},
        upsert=True,
    )
    return {"opened": scan_result["opened"], "managed": managed, "scanned_symbols": scan_result["scanned_symbols"], "notes": scan_result["notes"]}
