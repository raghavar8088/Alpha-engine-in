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
    intraday_lab_equity_collection,
    intraday_lab_positions_collection,
    intraday_lab_scores_collection,
    intraday_lab_state_collection,
    intraday_lab_trades_collection,
)
from app.services.angel_client import angel_client
from app.services.angel_equity_feed import equity_quotes
from app.services.call_engine import IST, _quote_batch, _scored_daily_symbols
from app.services.dhan_client import DhanClient
from app.services.intraday_strategies import STRATEGY_CATALOG, STRATEGY_BY_ID, evaluate
from backtesting_service.service import load_bars
from tradingai_shared.domain import Timeframe

logger = logging.getLogger("intraday_lab")

# Tournament capital, matching the buying/selling desks. Each strategy trades its OWN
# independent account (₹10 lakh by default), never a shared pool — one strategy can never
# starve another and each is judged against its own capital. The desk total is that times
# the catalog size (50 × ₹10L = ₹5 crore).
PER_STRATEGY_ALLOCATION = float(os.getenv("INTRADAY_LAB_PER_STRATEGY_CAPITAL", "1000000"))  # ₹10 lakh each
INTRADAY_LAB_INITIAL_CAPITAL = PER_STRATEGY_ALLOCATION * max(len(STRATEGY_CATALOG), 1)
# Every position is a uniform ₹1 lakh notional — the equity analog of the option desks'
# "1 lot everywhere". The leaderboard then ranks a strategy on WHICH stocks it picks and
# WHEN, not on how much it deployed: spec.risk_pct varies per strategy and is deliberately
# bypassed for this uniform size. Capped by the strategy's own remaining ₹10L, so a strategy
# can run up to ~10 concurrent names.
POSITION_NOTIONAL = float(os.getenv("INTRADAY_LAB_POSITION_NOTIONAL", "100000"))  # ₹1 lakh/position
MAX_SYMBOLS_PER_SCAN = int(os.getenv("INTRADAY_LAB_MAX_SYMBOLS", "150"))  # keeps one Dhan quote call bounded

# Kill switch for NEW entries only. Set once the fee-honest daily-bar backtest
# (intraday_backtest.py) showed this catalog losing 16/16 measurable strategies to real
# NSE costs, and live trading then reproduced the same loss even BEFORE costs (this
# engine charges none) — plus visible correlated triples firing on one symbol at once
# (e.g. three "VWAP Fade" parameter variants all buying the same LT print). Paused rather
# than stopped: `manage_cycle` keeps running regardless, so every already-open paper
# position is still marked, stopped, targeted and EOD-squared-off normally. Only the
# opening of new ones is gated — a paused desk that stopped MANAGING its book would leave
# open risk untracked, which is worse than leaving it running.
#
# Defaults to PAUSED (fail-safe), not trading: on 2026-07-24 this var was found reset to
# "0" in production with no record of who/what did it, and because the old default was
# "trade unless told otherwise", the desk silently resumed opening new positions on a
# catalog already proven to lose net of costs and kept losing for days before anyone
# noticed. A proven-unprofitable strategy set must now be explicitly re-armed
# (INTRADAY_LAB_PAUSE_ENTRIES=0) to trade; losing the env var, a fresh deploy without it,
# or any other accidental reset now fails toward safe, not toward loss.
PAUSE_NEW_ENTRIES = os.getenv("INTRADAY_LAB_PAUSE_ENTRIES", "1").lower() not in ("0", "false", "")

EOD_SQUAREOFF_HHMM = "15:15"
INTRADAY_CATEGORIES = {"scalping", "momentum", "mean_reversion"}  # square off same day
SWING_CATEGORIES = {"swing"}  # may carry up to spec.max_hold_days trading days

# Categories barred from NEW entries. Swing is removed by default because the live record
# is unambiguous: of the desk's -Rs756k, swing was -Rs728k — 96% of the entire loss —
# while the three genuine intraday categories together were roughly breakeven before costs
# (scalping -Rs37k, momentum -Rs32k, mean_reversion +Rs41k). Swing carries positions
# overnight with wide ATR stops on a desk built for same-day square-off, so when it is
# wrong (it wins ~38% of the time) it loses far bigger than the intraday book. This is a
# structural mismatch, not a parameter to tune, so it is cut rather than fitted. Existing
# swing positions still close out normally through manage_cycle; only new swing entries are
# gated. Env-tunable so the exclusion can be widened or cleared without a code change.
EXCLUDED_CATEGORIES = {
    c.strip().lower() for c in os.getenv("INTRADAY_LAB_EXCLUDE_CATEGORIES", "swing").split(",")
    if c.strip()
}

# How many DIFFERENT strategies may hold the same symbol at once.
#
# The per-strategy guard below already stops one strategy doubling up on a symbol, but
# nothing stopped N strategies each taking their own position in it — which is how this
# desk ended up holding SUNPHARMA across four strategies and TCS across three on the same
# read. That is the same concentration the buying desk's `in_basket` de-dup exists to
# prevent, where six near-identical strategies bought one strike and turned a single wrong
# call into a -29% day (2026-07-20).
#
# Near-identical variants are the common case here (three "VWAP Fade" parameter sets
# firing on one print), so the cap counts DISTINCT strategies, not positions. Set to 1 to
# forbid overlap entirely; raise it to allow genuinely different reads (a swing and a
# scalp on one name) to coexist.
MAX_STRATEGIES_PER_SYMBOL = int(os.getenv("INTRADAY_LAB_MAX_STRATEGIES_PER_SYMBOL", "2"))

# Daily loss circuit breaker, as a fraction of starting capital. Once the day's P&L is
# worse than this, the desk stops OPENING for the rest of the session; manage_cycle keeps
# running, so open positions are still marked, stopped, targeted and squared off — a
# breaker that stopped managing open risk would be worse than no breaker.
#
# The selling desk has had one of these since it was built and the buying desk gained one
# after its -29% day; this desk had none, which mattered because its measured live edge is
# negative (Rs16,497 lost over 500 trades at 39% before any costs). A bad day here had
# nothing to stop it compounding.
DAILY_LOSS_BREAKER_PCT = float(os.getenv("INTRADAY_LAB_DAILY_LOSS_PCT", "0.03"))
IST = timezone(timedelta(hours=5, minutes=30))

STATE_ID = "intraday_lab"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist():
    return datetime.now(IST).date()


async def _equity_quote_map(
    dhan: DhanClient | None, insts: list[dict]
) -> tuple[dict[tuple[str, str], dict], dict[tuple[str, str], str]]:
    """Live quotes for the given equity instrument docs — Angel One first, Dhan for
    whatever Angel could not price. Returns (quotes_by_key, source_by_key) keyed by
    (exchange_segment, security_id); source is "angel_quote" or "dhan_quote" so the desk
    can record which broker actually answered, exactly like broker_data.py's ltp_source.

    Angel is the desk's primary equity feed (this is a cash-equity desk and Angel is our
    equity broker); Dhan covers the tail Angel does not list or an off-whitelist host that
    cannot reach Angel at all. Anything neither can price is simply absent, and the caller
    falls back to the last daily-bar close — never a fabricated intraday print."""
    quotes: dict[tuple[str, str], dict] = {}
    source: dict[tuple[str, str], str] = {}

    for key, q in (await equity_quotes(insts)).items():
        quotes[key] = q
        source[key] = "angel_quote"

    wanted: dict[str, list[int]] = {}
    for inst in insts:
        key = (inst["exchange_segment"], str(inst["security_id"]))
        if key in quotes:
            continue
        wanted.setdefault(inst["exchange_segment"], []).append(int(inst["security_id"]))
    for key, q in (await _quote_batch(dhan, wanted)).items():
        quotes[key] = q
        source[key] = "dhan_quote"
    return quotes, source


async def _open_positions_count(strategy_id: str) -> int:
    return await intraday_lab_positions_collection.count_documents({"strategy_id": strategy_id, "status": "OPEN"})


def _session_start_utc() -> datetime:
    """Midnight IST today, as UTC — the boundary for 'this session'."""
    now_ist = datetime.now(IST)
    return now_ist.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


async def today_pnl() -> float:
    """This session's P&L: realized on positions closed today plus unrealized on
    positions opened today. Positions carried in from earlier sessions are excluded —
    a swing trade drifting since Monday is not this session's decision to keep trading,
    and counting it would trip the breaker on history rather than on today."""
    start = _session_start_utc()
    total = 0.0
    async for p in intraday_lab_positions_collection.find(
        {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    async for p in intraday_lab_positions_collection.find(
        {"status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}
    ):
        total += p.get("unrealized_pnl") or 0.0
    return total


async def breaker_state() -> dict:
    """Whether the daily loss breaker has tripped, and the numbers behind it."""
    pnl = await today_pnl()
    limit = DAILY_LOSS_BREAKER_PCT * INTRADAY_LAB_INITIAL_CAPITAL
    return {
        "breaker_tripped": pnl <= -limit,
        "today_pnl": round(pnl, 2),
        "daily_loss_limit": round(limit, 2),
        "daily_loss_pct": DAILY_LOSS_BREAKER_PCT,
    }


async def _strategies_holding(symbol: str) -> int:
    """How many DISTINCT strategies currently hold this symbol. Distinct rather than a
    raw position count, because the concentration that matters is how many independent
    reads are riding on one name, not how many rows exist."""
    return len(await intraday_lab_positions_collection.distinct(
        "strategy_id", {"symbol": symbol, "status": "OPEN"}
    ))


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

    # Desk-wide concentration guard: the check above is per-strategy, so without this a
    # symbol can be taken independently by as many strategies as happen to signal on it.
    if await _strategies_holding(symbol) >= MAX_STRATEGIES_PER_SYMBOL:
        return False

    cash = await _available_cash(spec.strategy_id)
    budget = POSITION_NOTIONAL  # uniform size for every strategy — see POSITION_NOTIONAL note
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
    # Checked before any scanning work: once the day's loss limit is hit there is no
    # point pricing symbols we have already decided not to trade.
    breaker = await breaker_state()
    if breaker["breaker_tripped"]:
        return {
            "opened": 0,
            "scanned_symbols": 0,
            "notes": [
                f"DAILY LOSS BREAKER TRIPPED — today's P&L Rs{breaker['today_pnl']:,.0f} crossed the "
                f"Rs{breaker['daily_loss_limit']:,.0f} limit ({DAILY_LOSS_BREAKER_PCT:.1%} of capital). "
                f"No new positions for the rest of the session; open positions are still managed."
            ],
        }

    scored = await _scored_daily_symbols()
    if not scored:
        return {"opened": 0, "scanned_symbols": 0, "notes": ["No scored symbols — backfill daily bars first."]}
    scored = scored[:MAX_SYMBOLS_PER_SCAN]

    symbols = [s for s, *_ in scored]
    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": symbols}}
    )}
    quotes, quote_source = await _equity_quote_map(dhan, list(equities.values()))

    notes = []
    if not quotes:
        # Say WHICH feed came up empty. "No signals today" and "the desk was blind today"
        # look identical on the page otherwise, and that ambiguity has already cost the
        # option desks whole sessions of misdiagnosis.
        angel_on = angel_client.configured()
        if not angel_on and dhan is None:
            notes.append("No Angel One or Dhan feed configured — intraday-context strategies (scalping/momentum/mean_reversion) skipped this cycle; only daily-bar swing signals can fire.")
        else:
            notes.append(
                f"No live equity quotes this cycle (Angel One: {'returned none' if angel_on else 'not configured'}; "
                f"Dhan: {'returned none' if dhan is not None else 'not connected'}) — "
                "only daily-bar swing signals can fire."
            )

    opened = 0
    for symbol, score, reasons, atr14, bars in scored:
        inst = equities.get(symbol)
        if inst is None or atr14 <= 0 or len(bars) < 2:
            continue
        key = (inst["exchange_segment"], str(inst["security_id"]))
        quote = quotes.get(key)
        ltp_source = quote_source.get(key, "last_bar_close")
        ctx = {"bars": bars, "atr14": atr14, "quote": quote, "prev_bar": bars[-2]}
        for spec in STRATEGY_CATALOG:
            if spec.category in EXCLUDED_CATEGORIES:
                continue  # structurally barred (swing by default — 96% of the desk's losses)
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
    quotes, quote_source = await _equity_quote_map(dhan, list(equities.values()))

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
                ltp, ltp_source = float(q["last_price"]), quote_source[key]
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


async def _snapshot_equity() -> dict:
    """Append one point to the equity curve and return the pool summary. Mirrors the
    selling desk's `snapshot_equity` so the Intraday Stocks page can chart an equity line
    the same way. Written once per cycle (~every 3 min in market hours)."""
    snap = await summary()
    await intraday_lab_equity_collection.insert_one({
        "ts": _now(),
        "equity": snap["equity"],
        "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"],
        "deployed": snap["deployed_capital"],
        "open_positions": snap["open_positions"],
    })
    return snap


async def run_cycle(dhan: DhanClient | None) -> dict:
    """One full scan+manage pass — used by both the background loop and the
    manual 'Run now' endpoint."""
    managed = await manage_cycle(dhan)
    if PAUSE_NEW_ENTRIES:
        # Every open position is still managed above; only new entries are withheld.
        scan_result = {"opened": 0, "scanned_symbols": 0,
                       "notes": ["INTRADAY_LAB_PAUSE_ENTRIES is set — no new positions are "
                                 "being opened. Existing positions are still managed normally."]}
    else:
        scan_result = await scan_cycle(dhan)
    await _snapshot_equity()
    await intraday_lab_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {
            "last_run_at": _now(), "last_opened": scan_result["opened"],
            "last_managed": managed, "last_notes": scan_result["notes"],
            "broker_connected": dhan is not None,
            "angel_configured": angel_client.configured(),
            "paused": PAUSE_NEW_ENTRIES,
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
        **(await breaker_state()),
        "max_strategies_per_symbol": MAX_STRATEGIES_PER_SYMBOL,
        "excluded_categories": sorted(EXCLUDED_CATEGORIES),
    }
