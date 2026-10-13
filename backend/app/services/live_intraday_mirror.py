"""Live Intraday books on the TOURNAMENT's strategies (since 2026-10-13).

The three Live Intraday books (Rs 80,000 / 30,000 / 10,000) used to run their own shortlist:
eight daily-bar "swing" strategies from the catalog the tournament retired on 2 Oct. The owner
asked for them to trade the tournament's strategies instead - the 54 on the Tournament tab.

THEY COPY THE TOURNAMENT'S TRADES; THEY DO NOT RE-SCAN
------------------------------------------------------
The tournament (`intraday_v2_engine`) already decides every entry and exit on real 15m/45m/1h
bars and fills like a broker: entries and market exits pay slippage, stops and targets fill at
their level found by walking the minute bars. A book opens when the tournament opens, at the
tournament's entry price, and closes when the tournament closes, at its exit price - so any
difference between the tournament and a book is SIZE AND COST, never a different signal or a
different fill. Nothing here asks Angel for a price.

ONE SMALL ACCOUNT, NOT 54 SLICES
--------------------------------
The tournament gives each strategy Rs 50 lakh in five Rs 10 lakh slots and takes ~450 trades a
day. Splitting Rs 10,000 into 54 slices would give each strategy Rs 185 - not one share of the
median stock. A book is instead ONE account, as a real one would be:
  * at most MAX_OPEN positions at a time, each capped at capital / MAX_OPEN
    (Rs 16,000 / 6,000 / 2,000 at the default of five), whole shares only;
  * never two positions in the same stock (an account cannot be long and short one name, and
    two longs in it are one bigger bet, not two strategies);
  * cash = capital + everything realised - what is tied up in open positions, no leverage;
  * the book's own 3% daily loss breaker stops new entries.
Signals are taken in the order the tournament took them - in the morning most of the 54 cannot
get a slot. Every signal a book could not take is COUNTED per strategy and reason (breaker, full,
symbol held, share price above the cap, no cash) rather than written as a row: at ~450 signals a
day x 3 books, a row each would be ~1,350 writes a day to say "no".

COSTS ARE THE BOOK'S OWN. Gross P&L uses the tournament's prices (slippage already inside them);
fees are Angel's intraday rate card on the BOOK's quantity, not the tournament's.

TIME-ORDERED. The shared loop looks every ~3 minutes, and many tournament trades open and close
between two looks. Each look replays what happened since the last in timestamp order - closes
before opens at the same instant - so cash, open slots and held symbols are what they were at the
moment of each entry, not what they are when the look happens.

SQUARE-OFF. The close-out job calls the books' manage cycle every few seconds near 15:05/15:12 and
raises an alarm for any intraday position still open. `sync(entries=False)` runs inside that manage
cycle, so a copied position closes in the same pass its parent does.

RESETS. A reset deletes a book's rows; `book_reset.reset_at` then keeps the book from re-copying
anything the tournament opened before the reset, at a price that is long gone.

REAL MONEY IS UNTOUCHED. The real-money Live Trading desk imports `SELECTED` (the eight) and its
sizing constants from `live_intraday_engine`. None of them change; the books simply stop opening
new trades from that list. `LIVE_INTRADAY_SOURCE=legacy` puts the books back on it.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (intraday_lab_positions_collection, live_intraday_positions_collection,
                         live_intraday_scores_collection, live_intraday_state_collection,
                         live_intraday_trades_collection)
from app.services import intraday_v2_strategies as v2
from app.services.angel_fees import round_trip
from app.services.book_reset import naive_utc, reset_at
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger("live_intraday_mirror")

IST = timezone(timedelta(hours=5, minutes=30))
SOURCE_TAG = "tournament"
MAX_OPEN = int(os.getenv("LIVE_INTRADAY_MAX_OPEN", "5"))
SKIP_REASONS = ("breaker", "full", "symbol_held", "price_above_cap", "no_cash")
START_ID = "mirror_start"
RESET_DESK = "live-intraday"
# The close-out job (closes only) and the shared loop (entries) can both call `sync`; one at a
# time, so two passes can never copy the same tournament trade twice. The unique index in
# ensure_indexes is the second line of defence.
_sync_lock = asyncio.Lock()
_indexed = False

_PARENT_FIELDS = {
    "position_id": 1, "strategy_id": 1, "strategy_name": 1, "category": 1, "family": 1,
    "timeframe": 1, "symbol": 1, "instrument": 1, "side": 1, "entry_price": 1, "signal_price": 1,
    "target": 1, "stoploss": 1, "ltp": 1, "status": 1, "exit_price": 1, "exit_reason": 1,
    "rationale": 1, "opened_at": 1, "opened_on": 1, "closed_at": 1, "closed_on": 1, "cas": 1,
}


def position_cap(capital: float) -> float:
    return capital / max(MAX_OPEN, 1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _net(side: str, entry: float, exit_price: float, qty: int) -> tuple[float, float, object]:
    """(gross, net, fee breakdown) on the BOOK's quantity, Angel's intraday card."""
    sign = 1 if side == "BUY" else -1
    gross = round(sign * (exit_price - entry) * qty, 2)
    fb = round_trip(entry_price=entry, exit_price=exit_price, qty=qty, side=side, product="INTRADAY")
    return gross, round(gross - fb.total, 2), fb


def _closed(p: dict) -> bool:
    return p.get("status") == "CLOSED" and p.get("exit_price") is not None


# -- the decision, as a pure function ---------------------------------------------


def plan_book(*, capital: float, realized: float, deployed: float, open_rows: list[dict],
              parents: list[dict], decided: set[str], breaker_tripped: bool,
              entries: bool) -> dict:
    """Replay one book against the tournament, in time order. Pure - no I/O.

    open_rows: the book's OPEN positions from ANY source (they hold cash, slots, symbols).
    parents:   tournament positions in scope (opened on/after the book's floor), any status.
    decided:   parent ids this book has already taken or skipped.
    Returns {"opens": [...], "closes": [...], "skips": [...]}; an open may carry its own close
    when the parent opened and closed between two looks."""
    cash = capital + realized - deployed
    held: dict[str, int] = {}
    for r in open_rows:
        held[r["symbol"]] = held.get(r["symbol"], 0) + 1
    n_open = len(open_rows)
    by_id = {p["position_id"]: p for p in parents}
    cap = position_cap(capital)

    events: list[tuple] = []
    seq = 0

    def push(at, order: int, kind: str, payload) -> None:
        nonlocal seq
        seq += 1
        heapq.heappush(events, (at if at is not None else datetime.min, order, seq, kind, payload))

    mirrored_open = {r["parent_position_id"]: r for r in open_rows
                     if r.get("source") == SOURCE_TAG and r.get("parent_position_id")}
    for pid, row in mirrored_open.items():
        parent = by_id.get(pid)
        if parent is not None and _closed(parent):
            push(parent.get("closed_at"), 0, "close_existing", (row, parent))
    if entries:
        for p in parents:
            pid = p["position_id"]
            if pid not in decided and pid not in mirrored_open:
                push(p.get("opened_at"), 1, "open", p)

    out: dict = {"opens": [], "closes": [], "skips": []}
    while events:
        _at, _order, _seq, kind, payload = heapq.heappop(events)

        if kind in ("close_existing", "close_new"):
            row, parent = payload
            gross, net, fb = _net(row["side"], row["entry_price"], float(parent["exit_price"]),
                                  row["qty"])
            cash += row["capital_deployed"] + net
            n_open -= 1
            held[row["symbol"]] = held.get(row["symbol"], 1) - 1
            close = {"gross": gross, "net": net, "fb": fb}
            if kind == "close_existing":
                out["closes"].append({"row": row, "parent": parent, **close})
            else:
                row["_open"]["close"] = close
            continue

        p = payload                                         # kind == "open"
        price = float(p.get("entry_price") or 0.0)
        qty = int(min(cap, max(cash, 0.0)) // price) if price > 0 else 0
        if breaker_tripped:
            reason = "breaker"
        elif n_open >= MAX_OPEN:
            reason = "full"
        elif held.get(p["symbol"], 0) > 0:
            reason = "symbol_held"
        elif qty < 1:
            reason = "price_above_cap" if price > cap else "no_cash"
        else:
            reason = None
        if reason:
            out["skips"].append({"parent": p, "reason": reason})
            continue
        spend = round(price * qty, 2)
        cash -= spend
        n_open += 1
        held[p["symbol"]] = held.get(p["symbol"], 0) + 1
        opened = {"parent": p, "qty": qty, "spend": spend, "close": None}
        out["opens"].append(opened)
        if _closed(p):
            # Opened and closed between two looks. Its close is an event like any other, so an
            # entry that came AFTER it closed sees the cash and the symbol freed - and one that
            # came before does not.
            row = {"side": p["side"], "entry_price": price, "qty": qty, "capital_deployed": spend,
                   "symbol": p["symbol"], "_open": opened}
            push(p.get("closed_at"), 0, "close_new", (row, p))
    return out


# -- reading the world --------------------------------------------------------------


async def _mirror_start() -> datetime:
    """When the books began copying the tournament. Set once; nothing earlier is copied."""
    doc = await live_intraday_state_collection.find_one({"_id": START_ID})
    if doc and doc.get("started_at"):
        return naive_utc(doc["started_at"])
    now = _now()
    await live_intraday_state_collection.update_one(
        {"_id": START_ID}, {"$setOnInsert": {"started_at": now}}, upsert=True)
    doc = await live_intraday_state_collection.find_one({"_id": START_ID})
    return naive_utc(doc["started_at"])


async def _floor(book: str, start: datetime) -> datetime:
    """The earliest tournament entry this book may copy: the later of the copy start and its
    last reset."""
    r = await reset_at(RESET_DESK, book)
    return max(start, r) if r else start


async def _parents(since: datetime, extra_ids: list[str]) -> list[dict]:
    """Tournament positions opened since `since` (any status), plus any parent an open book
    row still points at."""
    out: dict[str, dict] = {}
    async for p in intraday_lab_positions_collection.find(
            {"engine": "v2", "opened_at": {"$gte": since}}, _PARENT_FIELDS):
        out[p["position_id"]] = p
    missing = [i for i in extra_ids if i not in out]
    if missing:
        async for p in intraday_lab_positions_collection.find(
                {"engine": "v2", "position_id": {"$in": missing}}, _PARENT_FIELDS):
            out[p["position_id"]] = p
    return sorted(out.values(), key=lambda p: (naive_utc(p.get("opened_at")) or datetime.min,
                                               p["position_id"]))


def _skip_doc_id(book: str, day: str) -> str:
    return f"mirror_skipped:{book}:{day}"


async def _decided(book: str, parents: list[dict]) -> set[str]:
    ids = [p["position_id"] for p in parents]
    decided: set[str] = set()
    async for r in live_intraday_positions_collection.find(
            {"book": book, "source": SOURCE_TAG, "parent_position_id": {"$in": ids}},
            {"parent_position_id": 1}):
        decided.add(r["parent_position_id"])
    days = sorted({p.get("opened_on") for p in parents if p.get("opened_on")})
    if days:
        async for d in live_intraday_state_collection.find(
                {"_id": {"$in": [_skip_doc_id(book, day) for day in days]}}, {"ids": 1}):
            decided.update(d.get("ids") or [])
    return decided


# -- writing it ---------------------------------------------------------------------


def _row(book: str, p: dict, qty: int, spend: float) -> dict:
    sig = float(p.get("signal_price") or p["entry_price"])
    return {
        "position_id": uuid4().hex[:12], "book": book,
        "source": SOURCE_TAG, "parent_position_id": p["position_id"],
        "strategy_id": p["strategy_id"], "strategy_name": p.get("strategy_name"),
        "category": p.get("category"), "is_anti": False,
        "family": p.get("family"), "timeframe": p.get("timeframe"),
        "symbol": p["symbol"], "display_name": p["symbol"],
        "instrument": p.get("instrument") or {"symbol": p["symbol"], "lot_size": 1},
        "side": p["side"], "entry_price": round(float(p["entry_price"]), 2), "qty": qty,
        "capital_deployed": spend,
        "target": p.get("target"), "stoploss": p.get("stoploss"),
        "ltp": p.get("ltp") or p["entry_price"], "ltp_source": "tournament",
        "signal_price": round(sig, 2),
        "signal_slippage_pct": round((float(p["entry_price"]) - sig) / sig * 100, 3) if sig else 0.0,
        "unrealized_pnl": 0.0, "pnl_pct": 0.0, "realized_pnl": None,
        "gross_pnl": None, "fees": None, "fee_breakdown": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "confidence": None, "rationale": p.get("rationale"), "max_hold_days": 0,
        "cas": bool(p.get("cas")),
        # The tournament's own times, so the book's day and its P&L land where the trade did.
        "opened_at": p.get("opened_at"), "opened_on": p.get("opened_on"),
        "updated_at": _now(), "closed_at": None, "closed_on": None,
    }


def _close_fields(p: dict, c: dict) -> dict:
    return {
        "status": "CLOSED", "exit_price": round(float(p["exit_price"]), 2),
        "exit_reason": p.get("exit_reason"), "gross_pnl": c["gross"], "fees": c["fb"].total,
        "fee_breakdown": c["fb"].as_dict(), "realized_pnl": c["net"], "unrealized_pnl": 0.0,
        "ltp": round(float(p["exit_price"]), 2),
        "closed_at": p.get("closed_at") or _now(), "closed_on": p.get("closed_on"),
        "updated_at": _now(),
    }


async def _trade(book: str, row: dict, p: dict, c: dict) -> None:
    await live_intraday_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "book": book, "source": SOURCE_TAG,
        "strategy_id": row["strategy_id"], "strategy_name": row.get("strategy_name"),
        "symbol": row["symbol"], "side": row["side"], "entry_price": row["entry_price"],
        "exit_price": round(float(p["exit_price"]), 2), "qty": row["qty"],
        "gross_pnl": c["gross"], "fees": c["fb"].total, "realized_pnl": c["net"],
        "exit_reason": p.get("exit_reason"), "opened_at": row.get("opened_at"),
        "closed_at": p.get("closed_at") or _now()})


async def _score(book: str, strategy_id: str, skips: dict[str, int]) -> None:
    """The book's record for one tournament strategy, plus what it could not take."""
    spec = v2.BY_ID.get(strategy_id)
    trades = wins = 0
    net = fees = 0.0
    async for r in live_intraday_positions_collection.find(
            {"book": book, "source": SOURCE_TAG, "strategy_id": strategy_id, "status": "CLOSED"},
            {"realized_pnl": 1, "fees": 1}):
        trades += 1
        wins += 1 if (r.get("realized_pnl") or 0) > 0 else 0
        net += r.get("realized_pnl") or 0.0
        fees += r.get("fees") or 0.0
    update: dict = {"$set": {
        "strategy_id": strategy_id, "book": book, "source": SOURCE_TAG,
        "name": spec.name if spec else strategy_id,
        "category": spec.category if spec else None, "is_anti": False,
        "trades": trades, "wins": wins, "win_rate": round(wins / trades, 4) if trades else 0.0,
        "net_pnl": round(net, 2), "fees": round(fees, 2), "gross_pnl": round(net + fees, 2),
        "updated_at": _now()}}
    if skips:
        update["$inc"] = {f"skipped.{k}": v for k, v in skips.items()}
    await live_intraday_scores_collection.update_one(
        {"strategy_id": strategy_id, "book": book}, update, upsert=True)


async def sync(*, entries: bool) -> dict:
    """Copy the tournament into every book once.

    entries=False (from the manage cycle and the close-out job): closes and marks only.
    entries=True  (from the shared loop): new entries too."""
    global _indexed
    if not _indexed:
        _indexed = True
        await ensure_indexes()
    async with _sync_lock:
        return await _sync(entries=entries)


async def _sync(*, entries: bool) -> dict:
    from app.services import live_intraday_engine as li   # late: that module imports this one

    start = await _mirror_start()
    total = {"opened": 0, "closed": 0, "skipped": 0, "marked": 0}
    if entries and li.PAUSE_NEW_ENTRIES:
        entries = False
    for book in li.BOOKS:
        floor = await _floor(book, start)
        capital = li.book_capital(book)
        open_rows = [r async for r in live_intraday_positions_collection.find(
            {"book": book, "status": "OPEN"})]
        pointed = [r["parent_position_id"] for r in open_rows
                   if r.get("source") == SOURCE_TAG and r.get("parent_position_id")]
        parents = await _parents(floor, pointed)
        op, cl = await li._totals_split(live_intraday_positions_collection, {"book": book})
        breaker = (await li.breaker_state(book))["breaker_tripped"] if entries else False
        plan = plan_book(capital=capital, realized=cl["realized"], deployed=op["deployed"],
                         open_rows=open_rows, parents=parents,
                         decided=await _decided(book, parents) if entries else set(),
                         breaker_tripped=breaker, entries=entries)

        touched: dict[str, dict[str, int]] = {}
        for c in plan["closes"]:
            row, p = c["row"], c["parent"]
            res = await live_intraday_positions_collection.update_one(
                {"_id": row["_id"], "status": "OPEN"}, {"$set": _close_fields(p, c)})
            if res.modified_count:
                await _trade(book, row, p, c)
                touched.setdefault(row["strategy_id"], {})
                total["closed"] += 1
        for o in plan["opens"]:
            p = o["parent"]
            doc = _row(book, p, o["qty"], o["spend"])
            if o["close"] is not None:
                doc.update(_close_fields(p, o["close"]))
            try:
                await live_intraday_positions_collection.insert_one(doc)
            except DuplicateKeyError:
                continue                          # already copied by an overlapping pass
            if o["close"] is not None:
                await _trade(book, doc, p, o["close"])
                total["closed"] += 1
            touched.setdefault(p["strategy_id"], {})
            total["opened"] += 1
        skipped_ids: dict[str, list[str]] = {}
        for s in plan["skips"]:
            p = s["parent"]
            per = touched.setdefault(p["strategy_id"], {})
            per[s["reason"]] = per.get(s["reason"], 0) + 1
            skipped_ids.setdefault(p.get("opened_on") or "", []).append(p["position_id"])
            total["skipped"] += 1
        for day, ids in skipped_ids.items():
            await live_intraday_state_collection.update_one(
                {"_id": _skip_doc_id(book, day)},
                {"$addToSet": {"ids": {"$each": ids}}, "$set": {"book": book, "day": day}},
                upsert=True)
        for sid, skips in touched.items():
            await _score(book, sid, skips)

        # Marks: an open copy shows its parent's latest price on its own quantity.
        by_id = {p["position_id"]: p for p in parents}
        closed_now = {c["row"]["_id"] for c in plan["closes"]}
        for r in open_rows:
            if r.get("source") != SOURCE_TAG or r["_id"] in closed_now:
                continue
            p = by_id.get(r.get("parent_position_id"))
            if not p or p.get("status") != "OPEN" or not p.get("ltp"):
                continue
            ltp = float(p["ltp"])
            sign = 1 if r["side"] == "BUY" else -1
            await live_intraday_positions_collection.update_one(
                {"_id": r["_id"], "status": "OPEN"}, {"$set": {
                    "ltp": round(ltp, 2), "ltp_source": "tournament",
                    "unrealized_pnl": round(sign * (ltp - r["entry_price"]) * r["qty"], 2),
                    "pnl_pct": round(sign * (ltp - r["entry_price"]) / r["entry_price"] * 100, 2),
                    "updated_at": _now()}})
            total["marked"] += 1
    return total


# -- read models used by live_intraday_engine ------------------------------------------


async def leaderboard_rows(book: str, capital: float) -> list[dict]:
    """One row per tournament strategy - including the ones this book never got a slot for,
    because how often a strategy was crowded out is part of what a small account learns."""
    scores = {s["strategy_id"]: s async for s in live_intraday_scores_collection.find(
        {"book": book, "source": SOURCE_TAG})}
    rows = []
    for spec in v2.CATALOG:
        sc = scores.get(spec.strategy_id) or {}
        net = sc.get("net_pnl", 0.0) or 0.0
        skipped = {k: int((sc.get("skipped") or {}).get(k, 0)) for k in SKIP_REASONS}
        rows.append({
            "strategy_id": spec.strategy_id, "name": spec.name, "category": spec.category,
            "is_anti": False, "trades": sc.get("trades", 0) or 0,
            "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "net_pnl": round(net, 2), "fees": round(sc.get("fees", 0.0) or 0.0, 2),
            "gross_pnl": round(sc.get("gross_pnl", net) or net, 2),
            # A shared account has no per-strategy capital; this is the strategy's share of
            # the BOOK's return.
            "allocated_capital": None,
            "roi_pct": round(net / capital * 100, 3) if capital else 0.0,
            "skipped": skipped, "skipped_total": sum(skipped.values()),
        })
    rows.sort(key=lambda r: (r["net_pnl"], r["trades"]), reverse=True)
    return rows


async def skipped_totals(book: str) -> dict[str, int]:
    out = {k: 0 for k in SKIP_REASONS}
    async for s in live_intraday_scores_collection.find(
            {"book": book, "source": SOURCE_TAG}, {"skipped": 1}):
        for k, v in (s.get("skipped") or {}).items():
            if k in out:
                out[k] += int(v or 0)
    return out


async def started_at() -> datetime | None:
    doc = await live_intraday_state_collection.find_one({"_id": START_ID})
    return doc.get("started_at") if doc else None


async def ensure_indexes() -> None:
    """Best effort: an index failure must never stop the books."""
    try:
        await intraday_lab_positions_collection.create_index(
            [("engine", 1), ("opened_at", 1)], name="v2_opened_at")
        await live_intraday_positions_collection.create_index(
            [("book", 1), ("parent_position_id", 1)], name="book_mirror_parent_unique",
            unique=True, partialFilterExpression={"source": SOURCE_TAG})
    except Exception:  # noqa: BLE001
        logger.warning("live_intraday_mirror: index creation skipped", exc_info=True)
