"""Paper Trade books (Rs 50k / Rs 2 lakh / Rs 10 lakh) on ALL of the Patterns desk (2026-10-15).

Until today these books copied an 11-strategy shortlist of the 548-strategy Patterns desk, on
an equal slice each (Rs 4,545 on the Rs 50k book). The owner asked for them to take the
Patterns tab's strategies - all 548 - and for a third, Rs 10 lakh, book: the same treatment the
Live Intraday books got from the tournament two days earlier, by the same rules and the same
code (`live_intraday_mirror.plan_book`).

THEY COPY THE DESK'S TRADES; THEY DO NOT RE-SCAN. A book opens when the Patterns desk opens, at
its entry price, and closes when it closes, at its exit price (both corrected 10 Oct: a target
fills at the target, market fills pay slippage). Fees are Angel's card on the BOOK's quantity -
DELIVERY when the copy was held overnight, intraday otherwise, the same `product_for` rule the
desk and the old shortlist books use. Nothing here calls Angel.

ONE ACCOUNT PER BOOK. 548 slices of Rs 50,000 would be Rs 91 each. So a book is one account:
at most MAX_OPEN positions (default 5), each up to capital / MAX_OPEN - Rs 10,000 / 40,000 /
2,00,000 - whole shares, never two positions in one stock, no leverage. Signals are taken in the
order the desk took them; the ones a book cannot take are COUNTED per strategy and reason.

WHY THIS FITS NOW. Before 10 Oct the desk took ~900-1,250 trades a day; capped at two strategies
per stock and a 3% loss limit it takes ~20, over ~33 stocks (median price Rs 871). A five-slot
book can now copy a real share of what the desk does, rather than a sliver.

TIME-ORDERED (closes before opens at the same instant), INCLUDING trades that opened and closed
between two looks - the old shortlist copy only ever saw positions still open when it looked.

OVERNIGHT. The desk's 4h and daily strategies hold for days, and so do their copies. The
close-out job's alarm for these books is limited to intraday styles (intraday_session), as it
already is for the desk itself.

PATBOOK_SOURCE=shortlist puts the books back on the eleven.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.core.db import (pattern_book_positions_collection, pattern_book_scores_collection,
                         pattern_book_state_collection, pattern_book_trades_collection,
                         pattern_positions_collection)
from app.services.angel_fees import product_for, round_trip
from app.services.book_reset import naive_utc, reset_at
from app.services.intraday_pattern_engine import CATALOG
from app.services.live_intraday_mirror import plan_book

logger = logging.getLogger("pattern_books_copy")

IST = timezone(timedelta(hours=5, minutes=30))
SOURCE_TAG = "desk"
MAX_OPEN = int(os.getenv("PATBOOK_MAX_OPEN", "5"))
SKIP_REASONS = ("breaker", "full", "symbol_held", "price_above_cap", "no_cash")
START_ID = "copy_start"
RESET_DESK = "pattern-books"
BY_ID = {s.strategy_id: s for s in CATALOG}

_PARENT_FIELDS = {
    "position_id": 1, "strategy_id": 1, "strategy_name": 1, "template": 1, "family": 1,
    "timeframe": 1, "style": 1, "symbol": 1, "side": 1, "entry_price": 1, "target": 1,
    "stoploss": 1, "ltp": 1, "status": 1, "exit_price": 1, "exit_reason": 1, "exit_basis": 1,
    "opened_at": 1, "opened_on": 1, "closed_at": 1, "closed_on": 1,
}

_sync_lock = asyncio.Lock()
_indexed = False


def position_cap(capital: float) -> float:
    return capital / max(MAX_OPEN, 1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_held(parent: dict) -> int:
    try:
        return (datetime.fromisoformat(str(parent["closed_on"])).date()
                - datetime.fromisoformat(str(parent["opened_on"])).date()).days
    except (KeyError, TypeError, ValueError):
        return 0


def _net(row: dict, parent: dict) -> tuple[float, float, object]:
    """(gross, net, fees) on the BOOK's qty - delivery if the copy slept overnight."""
    exit_price = float(parent["exit_price"])
    side = row.get("side") or "BUY"
    sign = 1 if side == "BUY" else -1
    gross = round(sign * (exit_price - row["entry_price"]) * row["qty"], 2)
    fb = round_trip(row["entry_price"], exit_price, row["qty"], side=side,
                    product=product_for(None, _days_held(parent)))
    return gross, round(gross - fb.total, 2), fb


# -- reading the world -------------------------------------------------------------


async def _start(key: str) -> datetime:
    doc = await pattern_book_state_collection.find_one({"_id": key})
    if doc and doc.get("started_at"):
        return naive_utc(doc["started_at"])
    await pattern_book_state_collection.update_one(
        {"_id": key}, {"$setOnInsert": {"started_at": _now()}}, upsert=True)
    doc = await pattern_book_state_collection.find_one({"_id": key})
    return naive_utc(doc["started_at"])


async def _floor(book: str) -> datetime:
    """Latest of: when copying began, when THIS book first did (a book added later never
    backfills), and its last reset."""
    floor = max(await _start(START_ID), await _start(f"{START_ID}:{book}"))
    r = await reset_at(RESET_DESK, book)
    return max(floor, r) if r else floor


async def _parents(since: datetime, extra_ids: list[str]) -> list[dict]:
    out: dict[str, dict] = {}
    async for p in pattern_positions_collection.find({"opened_at": {"$gte": since}},
                                                     _PARENT_FIELDS):
        out[p["position_id"]] = p
    missing = [i for i in extra_ids if i not in out]
    if missing:
        async for p in pattern_positions_collection.find({"position_id": {"$in": missing}},
                                                         _PARENT_FIELDS):
            out[p["position_id"]] = p
    return sorted(out.values(), key=lambda p: (naive_utc(p.get("opened_at")) or datetime.min,
                                               p["position_id"]))


def _skip_doc(book: str, day: str) -> str:
    return f"copy_skipped:{book}:{day}"


async def _decided(book: str, parents: list[dict]) -> set[str]:
    ids = [p["position_id"] for p in parents]
    decided: set[str] = set()
    async for r in pattern_book_positions_collection.find(
            {"book": book, "source": SOURCE_TAG, "parent_position_id": {"$in": ids}},
            {"parent_position_id": 1}):
        decided.add(r["parent_position_id"])
    days = sorted({p.get("opened_on") for p in parents if p.get("opened_on")})
    if days:
        async for d in pattern_book_state_collection.find(
                {"_id": {"$in": [_skip_doc(book, day) for day in days]}}, {"ids": 1}):
            decided.update(d.get("ids") or [])
    return decided


async def _totals(book: str) -> tuple[float, float]:
    """(realised on every closed row, capital deployed in every open row) - any source."""
    realized = deployed = 0.0
    async for p in pattern_book_positions_collection.find(
            {"book": book, "status": {"$in": ["OPEN", "CLOSED"]}},
            {"status": 1, "realized_pnl": 1, "capital_deployed": 1}):
        if p["status"] == "OPEN":
            deployed += p.get("capital_deployed") or 0.0
        else:
            realized += p.get("realized_pnl") or 0.0
    return realized, deployed


# -- writing it ---------------------------------------------------------------------


def _row(book: str, p: dict, qty: int, spend: float, capital: float) -> dict:
    return {
        "position_id": uuid4().hex[:12], "book": book,
        "source": SOURCE_TAG, "parent_position_id": p["position_id"],
        "strategy_id": p["strategy_id"], "strategy_name": p.get("strategy_name"),
        "template": p.get("template"), "family": p.get("family"),
        "timeframe": p.get("timeframe"), "style": p.get("style"),
        "symbol": p["symbol"], "side": p.get("side") or "BUY",
        "entry_price": round(float(p["entry_price"]), 2), "qty": qty,
        "capital_deployed": spend, "allocation": round(position_cap(capital), 2),
        "target": p.get("target"), "stoploss": p.get("stoploss"),
        "ltp": p.get("ltp") or p["entry_price"], "unrealized_pnl": 0.0,
        "realized_pnl": None, "gross_pnl": None, "fees": None, "fee_breakdown": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        # The desk's own times, so the book's days and P&L land where the trade did.
        "opened_at": p.get("opened_at"), "opened_on": p.get("opened_on"),
        "closed_at": None, "closed_on": None, "updated_at": _now(),
    }


def _close_fields(p: dict, c: dict) -> dict:
    return {
        "status": "CLOSED", "exit_price": round(float(p["exit_price"]), 2),
        "exit_reason": p.get("exit_reason"), "exit_basis": p.get("exit_basis"),
        "gross_pnl": c["gross"], "fees": round(c["fb"].total, 2),
        "fee_breakdown": c["fb"].as_dict(), "realized_pnl": c["net"], "unrealized_pnl": 0.0,
        "ltp": round(float(p["exit_price"]), 2),
        "closed_at": p.get("closed_at") or _now(),
        "closed_on": p.get("closed_on") or datetime.now(IST).date().isoformat(),
        "updated_at": _now(),
    }


async def _trade(book: str, row: dict, p: dict, c: dict) -> None:
    await pattern_book_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "book": book, "source": SOURCE_TAG,
        "strategy_id": row["strategy_id"], "strategy_name": row.get("strategy_name"),
        "template": row.get("template"), "family": row.get("family"),
        "timeframe": row.get("timeframe"), "symbol": row["symbol"], "side": row["side"],
        "entry_price": row["entry_price"], "exit_price": round(float(p["exit_price"]), 2),
        "qty": row["qty"], "gross_pnl": c["gross"], "fees": round(c["fb"].total, 2),
        "realized_pnl": c["net"], "exit_reason": p.get("exit_reason"),
        "exit_basis": p.get("exit_basis"), "opened_at": row.get("opened_at"),
        "closed_at": p.get("closed_at") or _now(),
        "closed_on": p.get("closed_on") or datetime.now(IST).date().isoformat()})


async def _score(book: str, strategy_id: str, skips: dict[str, int], capital: float) -> None:
    st = BY_ID.get(strategy_id)
    trades = wins = 0
    net = gross = fees = 0.0
    async for r in pattern_book_positions_collection.find(
            {"book": book, "source": SOURCE_TAG, "strategy_id": strategy_id, "status": "CLOSED"},
            {"realized_pnl": 1, "gross_pnl": 1, "fees": 1}):
        trades += 1
        v = r.get("realized_pnl") or 0.0
        wins += 1 if v > 0 else 0
        net += v
        gross += r.get("gross_pnl") or 0.0
        fees += r.get("fees") or 0.0
    update: dict = {"$set": {
        "book": book, "strategy_id": strategy_id, "source": SOURCE_TAG,
        "name": st.name if st else strategy_id,
        "template": st.template if st else None, "family": st.family if st else None,
        "timeframe": st.timeframe if st else None, "style": st.style if st else None,
        "trades": trades, "wins": wins, "win_rate": round(wins / trades, 4) if trades else 0.0,
        "net_pnl": round(net, 2), "gross_pnl": round(gross, 2), "fees": round(fees, 2),
        "allocation": round(position_cap(capital), 2),
        # A shared account has no per-strategy capital: this is the strategy's share of the
        # BOOK's return, so the column sums to the book's own ROI.
        "roi_pct": round(net / capital * 100, 4) if capital else 0.0,
        "updated_at": _now()}}
    if skips:
        update["$inc"] = {f"skipped.{k}": v for k, v in skips.items()}
    await pattern_book_scores_collection.update_one(
        {"book": book, "strategy_id": strategy_id}, update, upsert=True)


async def sync(*, entries: bool) -> dict:
    """Copy the Patterns desk into every book once. entries=False: closes and marks only."""
    global _indexed
    if not _indexed:
        _indexed = True
        await ensure_indexes()
    async with _sync_lock:
        return await _sync(entries=entries)


async def _sync(*, entries: bool) -> dict:
    from app.services import pattern_books_engine as pbe   # late: that module imports this one

    total = {"opened": 0, "closed": 0, "skipped": 0, "marked": 0}
    for book in pbe.BOOKS:
        capital = pbe.book_capital(book)
        floor = await _floor(book)
        open_rows = [r async for r in pattern_book_positions_collection.find(
            {"book": book, "status": "OPEN"})]
        pointed = [r["parent_position_id"] for r in open_rows
                   if r.get("source") == SOURCE_TAG and r.get("parent_position_id")]
        parents = await _parents(floor, pointed)
        realized, deployed = await _totals(book)
        plan = plan_book(capital=capital, realized=realized, deployed=deployed,
                         open_rows=open_rows, parents=parents,
                         decided=await _decided(book, parents) if entries else set(),
                         breaker_tripped=False, entries=entries,
                         max_open=MAX_OPEN, net_fn=_net)

        touched: dict[str, dict[str, int]] = {}
        for c in plan["closes"]:
            row, p = c["row"], c["parent"]
            res = await pattern_book_positions_collection.update_one(
                {"_id": row["_id"], "status": "OPEN"}, {"$set": _close_fields(p, c)})
            if res.modified_count:
                await _trade(book, row, p, c)
                touched.setdefault(row["strategy_id"], {})
                total["closed"] += 1
        for o in plan["opens"]:
            p = o["parent"]
            doc = _row(book, p, o["qty"], o["spend"], capital)
            if o["close"] is not None:
                doc.update(_close_fields(p, o["close"]))
            try:
                await pattern_book_positions_collection.insert_one(doc)
            except DuplicateKeyError:
                continue                      # an overlapping pass copied it first
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
            await pattern_book_state_collection.update_one(
                {"_id": _skip_doc(book, day)},
                {"$addToSet": {"ids": {"$each": ids}}, "$set": {"book": book, "day": day}},
                upsert=True)
        for sid, skips in touched.items():
            await _score(book, sid, skips, capital)

        by_id = {p["position_id"]: p for p in parents}
        closed_now = {c["row"]["_id"] for c in plan["closes"]}
        for r in open_rows:
            if r.get("source") != SOURCE_TAG or r["_id"] in closed_now:
                continue
            p = by_id.get(r.get("parent_position_id"))
            if not p or p.get("status") != "OPEN" or not p.get("ltp"):
                continue
            ltp = float(p["ltp"])
            sign = 1 if (r.get("side") or "BUY") == "BUY" else -1
            await pattern_book_positions_collection.update_one(
                {"_id": r["_id"], "status": "OPEN"}, {"$set": {
                    "ltp": round(ltp, 2),
                    "unrealized_pnl": round(sign * (ltp - r["entry_price"]) * r["qty"], 2),
                    "updated_at": _now()}})
            total["marked"] += 1
    return total


# -- read models used by pattern_books_engine ------------------------------------------


async def leaderboard_rows(book: str, capital: float) -> list[dict]:
    """Every Patterns strategy with this book's record and what it could not take. The page
    shows the ones that have signalled; 548 rows of zeros would bury them."""
    scores = {s["strategy_id"]: s async for s in pattern_book_scores_collection.find(
        {"book": book, "source": SOURCE_TAG})}
    open_counts: dict[str, int] = {}
    async for p in pattern_book_positions_collection.find(
            {"book": book, "status": "OPEN", "source": SOURCE_TAG}, {"strategy_id": 1}):
        open_counts[p["strategy_id"]] = open_counts.get(p["strategy_id"], 0) + 1
    cap = position_cap(capital)
    rows = []
    for st in CATALOG:
        sc = scores.get(st.strategy_id) or {}
        skipped = {k: int((sc.get("skipped") or {}).get(k, 0)) for k in SKIP_REASONS}
        rows.append({
            "strategy_id": st.strategy_id, "name": st.name, "template": st.template,
            "family": st.family, "timeframe": st.timeframe, "style": st.style,
            "allocation": round(cap, 2),
            "trades": sc.get("trades", 0) or 0, "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "gross_pnl": round(sc.get("gross_pnl", 0.0) or 0.0, 2),
            "fees": round(sc.get("fees", 0.0) or 0.0, 2),
            "net_pnl": round(sc.get("net_pnl", 0.0) or 0.0, 2),
            "roi_pct": round(sc.get("roi_pct", 0.0) or 0.0, 4),
            "open_positions": open_counts.get(st.strategy_id, 0),
            "skipped": skipped, "skipped_total": sum(skipped.values()),
        })
    rows.sort(key=lambda r: (-r["net_pnl"], -r["trades"], -r["skipped_total"], r["name"]))
    return rows


async def skipped_totals(book: str) -> dict[str, int]:
    out = {k: 0 for k in SKIP_REASONS}
    async for s in pattern_book_scores_collection.find(
            {"book": book, "source": SOURCE_TAG}, {"skipped": 1}):
        for k, v in (s.get("skipped") or {}).items():
            if k in out:
                out[k] += int(v or 0)
    return out


async def started_at(book: str) -> datetime | None:
    desk = await pattern_book_state_collection.find_one({"_id": START_ID})
    own = await pattern_book_state_collection.find_one({"_id": f"{START_ID}:{book}"})
    a = desk.get("started_at") if desk else None
    b = own.get("started_at") if own else None
    if a and b:
        return max(naive_utc(a), naive_utc(b))
    return b or a


async def ensure_indexes() -> None:
    """Best effort: an index failure must never stop the books."""
    try:
        await pattern_positions_collection.create_index([("opened_at", 1)],
                                                        name="pat_opened_at")
        await pattern_book_positions_collection.create_index(
            [("book", 1), ("parent_position_id", 1)], name="pb_copy_parent_unique",
            unique=True, partialFilterExpression={"source": SOURCE_TAG})
    except Exception:  # noqa: BLE001
        logger.warning("pattern_books_copy: index creation skipped", exc_info=True)
