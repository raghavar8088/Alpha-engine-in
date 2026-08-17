"""Live Intraday desks — small, curated paper books INSIDE the Intraday Stocks module,
separate from the 150-strategy tournament (intraday_lab_engine).

Unlike the tournament (every strategy, Rs10 lakh each), these are the hand-picked
shortlist the user selected to take toward real money. The SAME eight strategies run in
THREE independent books that differ only in capital — Rs80,000, Rs30,000 and Rs10,000 —
so the same signals can be judged at the size a real account would actually use.

WHY THREE SIZES AND NOT ONE SCALED NUMBER: position size is not a free parameter on a
small account. Sizing is whole shares, so a Rs1,250 slice simply cannot buy a Rs3,000
share and that signal is skipped, while the Rs10,000 slice takes it. Costs behave the
same way — a round trip costs roughly the same rupees whichever book takes it, so it is
a far larger share of a small book's P&L. Scaling one book's returns by 1/8 would hide
both effects; running the trades for real is the only way to see them.

Six of the eight picks are ANTI strategies. An ANTI is the REVERSE of its base strategy
— same entry, opposite side, with target/stop swapped — so when the base would lose,
this gains. The tournament shows ANTI only as a computed mirror; here it is a REAL
reverse trade the engine manages to the swapped levels.

COSTS ARE REAL. Every close is charged the actual Angel One schedule (see angel_fees) —
brokerage, STT, exchange and SEBI charges, stamp duty, GST, and a DP charge on delivery
exits. `gross_pnl` keeps the pre-cost number so the two are always separable and the
cost drag on each book is visible rather than assumed.

All three books share ONE market-data sweep per cycle: quotes and signals are computed
once and offered to each book in turn, so tripling the desks does not triple the load on
Angel's rate limiter.
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
from app.services.angel_fees import product_for, round_trip
from app.services.call_engine import IST, _scored_daily_symbols
from app.services.desk_totals import split as _totals_split
from app.services.dhan_client import DhanClient
from app.services.intraday_lab_engine import _equity_quote_map, _size
from app.services.intraday_strategies import STRATEGY_CATALOG, Signal, evaluate
from backtesting_service.service import load_bars
from tradingai_shared.domain import Timeframe

logger = logging.getLogger("live_intraday")

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

# The three books. Capital is the DESK total; each of the eight strategies gets an equal
# slice, and a position may use up to that slice. Rs80k/8 = Rs10,000, which is exactly
# what the original single desk used — so the 80k book's history carries over unchanged.
BOOK_CAPITAL: dict[str, float] = {
    "80k": float(os.getenv("LIVE_INTRADAY_CAPITAL_80K", "80000")),
    "30k": float(os.getenv("LIVE_INTRADAY_CAPITAL_30K", "30000")),
    "10k": float(os.getenv("LIVE_INTRADAY_CAPITAL_10K", "10000")),
}
BOOKS = list(BOOK_CAPITAL)
DEFAULT_BOOK = "80k"
STATE_ID = "engine"  # legacy id, kept for the 80k book so old state keeps resolving

MAX_SYMBOLS_PER_SCAN = int(os.getenv("LIVE_INTRADAY_MAX_SYMBOLS", "150"))
# Armed by default — the user explicitly wants these desks trading paper now.
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


def normalize_book(book: str | None) -> str:
    return book if book in BOOK_CAPITAL else DEFAULT_BOOK


def book_capital(book: str) -> float:
    return BOOK_CAPITAL[normalize_book(book)]


def per_strategy_allocation(book: str) -> float:
    """Equal slice of the desk. Also the per-position cap: on these books there is no
    reason to hold back cash a strategy is not using."""
    return book_capital(book) / max(len(SELECTED), 1)


# The REAL-MONEY desk (live_trading_engine) sizes off these and must not follow this
# module's book split: its Rs10,000-per-strategy cap is the user's standing instruction
# for actual capital, so it is pinned to the 80k book rather than left to track a default.
PER_STRATEGY_ALLOCATION = per_strategy_allocation(DEFAULT_BOOK)   # Rs10,000
POSITION_NOTIONAL = PER_STRATEGY_ALLOCATION
INITIAL_CAPITAL = BOOK_CAPITAL[DEFAULT_BOOK]                      # Rs80,000


def _state_id(book: str) -> str:
    return STATE_ID if book == DEFAULT_BOOK else f"{STATE_ID}:{book}"


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


# ---- capital / scoring, scoped to one book ------------------------------------


async def _deployed_capital(strategy_id: str, book: str) -> float:
    total = 0.0
    async for p in live_intraday_positions_collection.find(
        {"strategy_id": strategy_id, "book": book, "status": "OPEN"}, {"capital_deployed": 1}
    ):
        total += p.get("capital_deployed", 0.0)
    return total


async def _realized_pnl(strategy_id: str, book: str) -> float:
    total = 0.0
    async for p in live_intraday_positions_collection.find(
        {"strategy_id": strategy_id, "book": book, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    return total


async def _available_cash(strategy_id: str, book: str) -> float:
    return (per_strategy_allocation(book)
            + await _realized_pnl(strategy_id, book)
            - await _deployed_capital(strategy_id, book))


async def today_pnl(book: str) -> float:
    start = _session_start_utc()
    total = 0.0
    async for p in live_intraday_positions_collection.find(
        {"book": book, "status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    async for p in live_intraday_positions_collection.find(
        {"book": book, "status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}
    ):
        total += p.get("unrealized_pnl") or 0.0
    return total


async def breaker_state(book: str) -> dict:
    pnl = await today_pnl(book)
    capital = book_capital(book)
    limit = DAILY_LOSS_BREAKER_PCT * capital
    return {
        "breaker_tripped": pnl <= -limit,
        "today_pnl": round(pnl, 2),
        # Daily ROI: today's P&L against the desk's own capital, so the three books are
        # comparable even though their rupee P&L never will be.
        "today_roi_pct": round(pnl / capital * 100, 3) if capital else 0.0,
        "daily_loss_limit": round(limit, 2),
        "daily_loss_pct": DAILY_LOSS_BREAKER_PCT,
    }


async def _update_score(strategy_id: str, book: str) -> None:
    ls = SELECTED_BY_ID.get(strategy_id)
    if ls is None:
        return
    closed = [
        p async for p in live_intraday_positions_collection.find(
            {"strategy_id": strategy_id, "book": book, "status": {"$ne": "OPEN"}},
            {"realized_pnl": 1, "gross_pnl": 1, "fees": 1},
        )
    ]
    trades = len(closed)
    wins = sum(1 for p in closed if (p.get("realized_pnl") or 0) > 0)
    net_pnl = sum(p.get("realized_pnl") or 0 for p in closed)
    fees = sum(p.get("fees") or 0 for p in closed)
    alloc = per_strategy_allocation(book)
    await live_intraday_scores_collection.update_one(
        {"strategy_id": strategy_id, "book": book},
        {"$set": {
            "strategy_id": strategy_id, "book": book,
            "name": ls.name, "category": ls.category, "is_anti": ls.is_anti,
            "trades": trades, "wins": wins, "win_rate": round(wins / trades, 4) if trades else 0.0,
            "net_pnl": round(net_pnl, 2), "fees": round(fees, 2),
            "gross_pnl": round(net_pnl + fees, 2),
            "allocated_capital": round(alloc + net_pnl, 2),
            "roi_pct": round(net_pnl / alloc * 100, 2) if alloc else 0.0,
            "updated_at": _now(),
        }},
        upsert=True,
    )


async def _open_position(ls: LiveStrategy, book: str, symbol: str, inst: dict, signal, ltp_source: str) -> bool:
    if await live_intraday_positions_collection.find_one(
        {"strategy_id": ls.strategy_id, "book": book, "symbol": symbol, "status": "OPEN"}
    ):
        return False  # one open position per symbol per strategy per book
    notional = per_strategy_allocation(book)
    cash = await _available_cash(ls.strategy_id, book)
    qty = _size(signal.entry, notional, cash)
    if qty < 1:
        return False  # share costs more than this book's slice — an honest skip
    await live_intraday_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "book": book,
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
        "gross_pnl": None, "fees": None, "fee_breakdown": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "confidence": round(signal.confidence, 2), "rationale": signal.rationale,
        "max_hold_days": ls.max_hold_days,
        "opened_at": _now(), "opened_on": _today_ist().isoformat(),
        "updated_at": _now(), "closed_at": None, "closed_on": None,
    })
    return True


async def scan_cycle(dhan: DhanClient | None) -> dict:
    """One market sweep, offered to every book.

    Quotes and signals are identical across books — only sizing and available cash
    differ — so they are computed once here and each book decides independently whether
    it can afford the trade."""
    breakers = {b: await breaker_state(b) for b in BOOKS}
    live_books = [b for b in BOOKS if not breakers[b]["breaker_tripped"]]
    notes: list[str] = [
        f"{b} book: DAILY LOSS BREAKER TRIPPED — today's P&L Rs{breakers[b]['today_pnl']:,.0f} crossed the "
        f"Rs{breakers[b]['daily_loss_limit']:,.0f} limit. No new positions this session; open ones still managed."
        for b in BOOKS if breakers[b]["breaker_tripped"]
    ]
    opened_by_book = {b: 0 for b in BOOKS}
    if not live_books:
        return {"opened": 0, "opened_by_book": opened_by_book, "scanned_symbols": 0, "notes": notes}

    scored = await _scored_daily_symbols()
    if not scored:
        notes.append("No scored symbols — backfill daily bars first.")
        return {"opened": 0, "opened_by_book": opened_by_book, "scanned_symbols": 0, "notes": notes}
    scored = scored[:MAX_SYMBOLS_PER_SCAN]
    symbols = [s for s, *_ in scored]
    equities = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": symbols}}
    )}
    quotes, quote_source = await _equity_quote_map(dhan, list(equities.values()))

    if not quotes:
        notes.append("No live equity quotes this cycle — only daily-bar swing signals can fire.")
    intraday_entries_closed = datetime.now(IST).strftime("%H:%M") >= ENTRY_CUTOFF_HHMM
    if intraday_entries_closed:
        notes.append(f"Past the {ENTRY_CUTOFF_HHMM} IST entry cutoff — no new same-day entries; open positions still managed.")

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
            for book in live_books:
                if await _open_position(ls, book, symbol, inst, signal, ltp_source):
                    opened_by_book[book] += 1
    return {
        "opened": sum(opened_by_book.values()), "opened_by_book": opened_by_book,
        "scanned_symbols": len(scored), "notes": notes,
    }


async def manage_cycle(dhan: DhanClient | None) -> int:
    """Manage every book's open positions off a single quote sweep."""
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
    touched: set[tuple[str, str]] = set()
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
            book = normalize_book(pos.get("book"))
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
                # Charge the real Angel One cost of this round trip. `unrealized` is the
                # gross move; what the book actually keeps is gross minus costs.
                fb = round_trip(
                    entry_price=pos["entry_price"], exit_price=ltp, qty=pos["qty"],
                    side=pos["side"], product=product_for(category, days_held),
                )
                net = round(unrealized - fb.total, 2)
                changes.update({
                    "status": "CLOSED", "exit_price": round(ltp, 2), "exit_reason": reason,
                    "gross_pnl": unrealized, "fees": fb.total, "fee_breakdown": fb.as_dict(),
                    "realized_pnl": net, "unrealized_pnl": 0.0,
                    "closed_at": _now(), "closed_on": today_iso,
                })
                touched.add((pos["strategy_id"], book))
                await live_intraday_trades_collection.insert_one({
                    "trade_id": uuid4().hex[:12], "book": book,
                    "strategy_id": pos["strategy_id"], "strategy_name": pos["strategy_name"],
                    "symbol": symbol, "side": pos["side"], "entry_price": pos["entry_price"], "exit_price": round(ltp, 2),
                    "qty": pos["qty"], "gross_pnl": unrealized, "fees": fb.total, "realized_pnl": net,
                    "exit_reason": reason, "opened_at": pos["opened_at"], "closed_at": _now(),
                })
            await live_intraday_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
            updated += 1

    for strategy_id, book in touched:
        await _update_score(strategy_id, book)
    return updated


async def summary(book: str = DEFAULT_BOOK) -> dict:
    book = normalize_book(book)
    capital = book_capital(book)
    op, cl = await _totals_split(live_intraday_positions_collection, {"book": book})
    deployed, unrealized = op["deployed"], op["unrealized"]
    realized, fees = cl["realized"], cl["fees"]
    open_count, closed_count = op["n"], cl["n"]
    equity = capital + realized + unrealized
    alloc = per_strategy_allocation(book)
    return {
        "book": book, "books": BOOKS,
        "book_capitals": {b: BOOK_CAPITAL[b] for b in BOOKS},
        "initial_capital": capital,
        "per_strategy_allocation": round(alloc, 2),
        "position_notional": round(alloc, 2),
        "available_cash": round(capital + realized - deployed, 2),
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2),
        "gross_realized_pnl": round(realized + fees, 2),
        "total_fees": round(fees, 2),
        "unrealized_pnl": round(unrealized, 2),
        "equity": round(equity, 2),
        # ROI on the desk's OWN capital — the only figure that compares across books.
        "roi_pct": round((equity - capital) / capital * 100, 2) if capital else 0.0,
        "open_positions": open_count,
        "closed_positions": closed_count,
        "strategy_count": len(SELECTED),
        "paused": PAUSE_NEW_ENTRIES,
        "mode": "paper",
        **(await breaker_state(book)),
    }


async def leaderboard(book: str = DEFAULT_BOOK) -> list[dict]:
    book = normalize_book(book)
    alloc = per_strategy_allocation(book)
    scores = {s["strategy_id"]: s async for s in live_intraday_scores_collection.find({"book": book})}
    rows = []
    for ls in SELECTED:
        sc = scores.get(ls.strategy_id) or {}
        net_pnl = sc.get("net_pnl", 0.0) or 0.0
        rows.append({
            "strategy_id": ls.strategy_id, "name": ls.name, "category": ls.category, "is_anti": ls.is_anti,
            "trades": sc.get("trades", 0) or 0, "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "net_pnl": round(net_pnl, 2),
            "fees": round(sc.get("fees", 0.0) or 0.0, 2),
            "gross_pnl": round(sc.get("gross_pnl", net_pnl) or net_pnl, 2),
            "allocated_capital": round(alloc + net_pnl, 2),
            "roi_pct": round(net_pnl / alloc * 100, 2) if alloc else 0.0,
        })
    rows.sort(key=lambda r: r["net_pnl"], reverse=True)
    return rows


async def daily(book: str = DEFAULT_BOOK, limit: int = 60) -> list[dict]:
    """Realised P&L and ROI per trading day, newest first.

    Grouped on the IST calendar date the position CLOSED, since that is the day the
    money actually moved."""
    book = normalize_book(book)
    capital = book_capital(book)
    buckets: dict[str, dict] = {}
    async for p in live_intraday_positions_collection.find(
        {"book": book, "status": {"$ne": "OPEN"}},
        {"realized_pnl": 1, "gross_pnl": 1, "fees": 1, "closed_at": 1, "closed_on": 1},
    ):
        closed_at = p.get("closed_at")
        day = p.get("closed_on") or (closed_at.astimezone(IST).date().isoformat() if closed_at else None)
        if not day:
            continue
        b = buckets.setdefault(day, {"date": day, "trades": 0, "wins": 0, "realized_pnl": 0.0, "fees": 0.0, "gross_pnl": 0.0})
        net = p.get("realized_pnl") or 0.0
        fee = p.get("fees") or 0.0
        b["trades"] += 1
        b["wins"] += 1 if net > 0 else 0
        b["realized_pnl"] += net
        b["fees"] += fee
        b["gross_pnl"] += p.get("gross_pnl") if p.get("gross_pnl") is not None else net + fee
    rows = sorted(buckets.values(), key=lambda r: r["date"], reverse=True)[:limit]
    for r in rows:
        r["realized_pnl"] = round(r["realized_pnl"], 2)
        r["fees"] = round(r["fees"], 2)
        r["gross_pnl"] = round(r["gross_pnl"], 2)
        r["win_rate"] = round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0
        r["roi_pct"] = round(r["realized_pnl"] / capital * 100, 3) if capital else 0.0
    return rows


async def run_cycle(dhan: DhanClient | None) -> dict:
    """One tick for ALL books: manage first, then scan, then snapshot each book."""
    managed = await manage_cycle(dhan)
    if PAUSE_NEW_ENTRIES:
        scan_result = {"opened": 0, "opened_by_book": {b: 0 for b in BOOKS}, "scanned_symbols": 0,
                       "notes": ["Live Intraday entries are paused; open positions still managed."]}
    else:
        scan_result = await scan_cycle(dhan)

    snaps: dict[str, dict] = {}
    for book in BOOKS:
        snap = await summary(book)
        snaps[book] = snap
        await live_intraday_equity_collection.insert_one({
            "ts": _now(), "book": book, "equity": snap["equity"], "realized": snap["realized_pnl"],
            "unrealized": snap["unrealized_pnl"], "fees": snap["total_fees"],
            "roi_pct": snap["roi_pct"], "deployed": snap["deployed_capital"],
            "open_positions": snap["open_positions"],
        })
        await live_intraday_state_collection.update_one(
            {"_id": _state_id(book)},
            {"$set": {
                "book": book, "last_run_at": _now(),
                "last_opened": scan_result["opened_by_book"].get(book, 0), "last_managed": managed,
                "last_notes": scan_result["notes"], "broker_connected": dhan is not None,
                "angel_configured": angel_client.configured(), "paused": PAUSE_NEW_ENTRIES,
            }},
            upsert=True,
        )
    return {
        "opened": scan_result["opened"], "opened_by_book": scan_result["opened_by_book"],
        "managed": managed, "scanned_symbols": scan_result["scanned_symbols"],
        "notes": scan_result["notes"],
        "equity": {b: snaps[b]["equity"] for b in BOOKS},
    }
