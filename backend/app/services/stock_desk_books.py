"""Stock Pre-Live Paper Books - the buying desk's strategies on an account you could open.

The parent desk (`stock_desk`, buying side) gives each of its 220 strategies its own
Rs 10,00,000 and charges nothing to trade. That answers "did the signal work". It cannot
answer the question that decides whether any of this is worth real money:

    on ONE account of this size, paying what a broker actually charges, what is left?

So these books run the same strategies over the same fills, in TWO independent books that
differ only in capital - Rs 10,00,000 and Rs 2,00,000.

ONE SHARED BOOK, NOT A SLICE PER STRATEGY
-----------------------------------------
The parent hands every strategy its own Rs 10L, so 220 strategies imply Rs 22 crore of
notional that nobody has. A real account is one pot of money that every strategy competes
for, and it runs out. Here the book is shared: whoever signals first spends the cash, and
when it is gone the next signal is DECLINED and the decline is recorded. That is not a
failure mode, it is the measurement - "how many of these signals could a Rs 2 lakh account
actually have taken" is a number the parent desk structurally cannot produce.

A single position is capped at MAX_POSITION_PCT of the book so one contract cannot swallow
a small account, and a strategy holds at most one open position per book at a time.

WHOLE LOTS, WHICH IS WHERE A SMALL ACCOUNT ACTUALLY BREAKS
----------------------------------------------------------
An option trades in lots. You cannot buy 0.4 of one. A Rs 2 lakh book that can afford
Rs 18,000 of a contract priced at Rs 25,000 per lot does not take a smaller position - it
takes NOTHING, and the signal is lost entirely. Scaling one book's returns down would hide
that completely, which is why both books are run for real rather than divided.

FEES ARE CHARGED HERE, AND THEY ARE THE POINT
---------------------------------------------
The parent desk charges nothing anywhere - its P&L is gross. Options brokerage is a FLAT
Rs 20 per order regardless of size, so a Rs 3,000 position pays the same Rs 40 round trip as
a Rs 3,00,000 one. On the parent's numbers that is invisible; on a small book it is most of
the edge. Every close here is charged through `option_round_trip` on THIS book's own lots.

THE BOOKS MIRROR THE PARENT - THEY DO NOT RE-SCAN
--------------------------------------------------
A book opens when the parent opens, at the parent's entry premium, and closes when the
parent closes, at the parent's exit. Nothing here calls Angel at all. That is deliberate
twice over: a second scan would re-fetch the same candles and option chains that are already
this module's binding rate limit, and sharing the parent's signal means any difference
between the books is caused by SIZE AND COSTS and nothing else. If they re-derived their own
signals, a divergence could be a different entry rather than a different account, and the
comparison they exist for would be worthless.
"""

import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import (
    stock_book_equity_collection,
    stock_book_positions_collection,
    stock_book_scores_collection,
    stock_book_state_collection,
    stock_book_trades_collection,
    stock_desk_positions_collection,
)
from app.services.angel_fees import option_round_trip

logger = logging.getLogger("stock_books")

# The side of the parent desk these books follow. The buying desk is the one with a
# leaderboard worth mirroring; the selling desk is a different risk shape and would need its
# own margin model rather than a premium-paid one.
PARENT_SIDE = os.getenv("STOCK_BOOK_PARENT_SIDE", "buying")

BOOK_CAPITAL: dict[str, float] = {
    "10L": float(os.getenv("STOCK_BOOK_CAPITAL_10L", "1000000")),
    "2L": float(os.getenv("STOCK_BOOK_CAPITAL_2L", "200000")),
}
BOOKS = list(BOOK_CAPITAL)
DEFAULT_BOOK = "10L"
BOOK_LABEL = {"10L": "Paper Trade · ₹10 lakh", "2L": "Paper Trade · ₹2 lakh"}

# The most of the book one position may take. Without it a single expensive contract could
# consume a Rs 2 lakh account on the first signal of the day and the book would measure that
# one trade rather than the strategy set.
MAX_POSITION_PCT = float(os.getenv("STOCK_BOOK_MAX_POSITION_PCT", "0.10"))

ENABLED = os.getenv("STOCK_BOOK_ENABLED", "1").lower() not in ("0", "false", "")


def normalize_book(book: str | None) -> str:
    return book if book in BOOK_CAPITAL else DEFAULT_BOOK


def book_capital(book: str) -> float:
    return BOOK_CAPITAL[normalize_book(book)]


def position_cap(book: str) -> float:
    return book_capital(book) * MAX_POSITION_PCT


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lots_affordable(premium: float, lot_size: int, budget: float) -> int:
    """Whole lots only - the constraint these books exist to measure."""
    per_lot = premium * lot_size
    if per_lot <= 0:
        return 0
    return max(int(budget // per_lot), 0)


# -- cash ------------------------------------------------------------------------
# One pot per book. Cash is what the account would actually have: what it started with, plus
# everything it has realised (net of fees, since fees are charged into realized_pnl), minus
# what is currently tied up in open positions.


async def _deployed(book: str) -> float:
    total = 0.0
    async for p in stock_book_positions_collection.find(
            {"book": book, "status": "OPEN"}, {"capital_deployed": 1}):
        total += p.get("capital_deployed") or 0.0
    return total


async def _realized(book: str) -> float:
    total = 0.0
    async for p in stock_book_positions_collection.find(
            {"book": book, "status": "CLOSED"}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    return total


async def _cash(book: str) -> float:
    return book_capital(book) + await _realized(book) - await _deployed(book)


# -- mirroring the parent's fills ------------------------------------------------


async def _open_mirror(book: str, parent: dict, cash: float) -> float:
    """Take the parent's fill at this book's size, or decline it and say why.

    Returns the cash spent (0.0 when declined), so the caller can keep one running balance
    across a cycle instead of re-querying the book for every signal."""
    pid = parent.get("position_id")
    if await stock_book_positions_collection.find_one(
            {"book": book, "parent_position_id": pid}):
        return 0.0                                    # already seen this fill
    sid = parent.get("strategy_id")
    if await stock_book_positions_collection.find_one(
            {"book": book, "strategy_id": sid, "status": "OPEN"}):
        return 0.0                                    # one open position per strategy

    premium = float(parent.get("entry_premium") or 0.0)
    lot_size = int(parent.get("lot_size") or 0)
    parent_lots = int(parent.get("lots") or 1)
    budget = min(position_cap(book), cash)
    lots = min(_lots_affordable(premium, lot_size, budget), parent_lots)

    common = {
        "book": book, "parent_position_id": pid,
        "strategy_id": sid, "strategy_name": parent.get("strategy_name"),
        "is_anti": bool(parent.get("is_anti")),
        "symbol": parent.get("symbol"), "option_type": parent.get("option_type"),
        "strike": parent.get("strike"), "expiry": parent.get("expiry"),
        "structure": parent.get("structure"), "lot_size": lot_size,
        "entry_premium": round(premium, 2),
        "opened_at": _now(), "opened_on": parent.get("opened_on"), "updated_at": _now(),
    }

    if lots < 1:
        # Recorded as a ROW, not a tally. A row is auditable - which signals this account
        # could not take, in what, and for what reason - and because the duplicate check
        # above matches the parent id at ANY status, the same missed signal is not counted
        # again on every cycle for as long as the parent holds it.
        per_lot = premium * lot_size
        reason = (f"₹{per_lot:,.0f} per lot of {parent.get('symbol')} "
                  f"{parent.get('strike')} {parent.get('option_type')} at "
                  f"₹{premium:,.2f} × {lot_size}")
        reason += (f" exceeds the ₹{position_cap(book):,.0f} per-position cap"
                   if per_lot > position_cap(book)
                   else f", and only ₹{max(cash, 0):,.0f} cash is left in the book")
        await stock_book_positions_collection.insert_one({
            **common, "position_id": uuid4().hex[:12],
            "lots": 0, "qty": 0, "capital_deployed": 0.0,
            "status": "DECLINED", "decline_reason": reason,
            "ltp": round(premium, 2), "unrealized_pnl": 0.0,
            "realized_pnl": None, "gross_pnl": None, "fees": None,
            "exit_premium": None, "exit_reason": None, "closed_at": None,
        })
        return 0.0

    qty = lots * lot_size
    spend = round(premium * qty, 2)
    await stock_book_positions_collection.insert_one({
        **common, "position_id": uuid4().hex[:12],
        "lots": lots, "qty": qty, "capital_deployed": spend,
        "parent_lots": parent_lots,
        "target_premium": parent.get("target_premium"),
        "stop_premium": parent.get("stop_premium"),
        "ltp": round(premium, 2), "unrealized_pnl": 0.0,
        "realized_pnl": None, "gross_pnl": None, "fees": None, "fee_breakdown": None,
        "exit_premium": None, "exit_reason": None, "status": "OPEN", "closed_at": None,
    })
    return spend


async def _close_mirror(pos: dict, parent: dict) -> float:
    """Close at the parent's exit, charging this book's own fees on its own lots."""
    exit_px = float(parent.get("exit_premium") if parent.get("exit_premium") is not None
                    else pos.get("ltp") or pos["entry_premium"])
    lots, lot_size = int(pos["lots"]), int(pos["lot_size"])
    gross = (exit_px - pos["entry_premium"]) * lots * lot_size

    # The flat Rs20-per-order leg is why these books exist. It does not shrink with the
    # position, so the same trade that is a rounding error on the parent's Rs 10L slice can
    # be most of the move on a small book.
    fb = option_round_trip(pos["entry_premium"], exit_px, lots, lot_size)
    net = gross - fb.total

    await stock_book_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "book": pos["book"],
        "strategy_id": pos["strategy_id"], "strategy_name": pos.get("strategy_name"),
        "is_anti": bool(pos.get("is_anti")),
        "symbol": pos.get("symbol"), "option_type": pos.get("option_type"),
        "strike": pos.get("strike"), "structure": pos.get("structure"),
        "lots": lots, "lot_size": lot_size, "qty": lots * lot_size,
        "entry_premium": pos["entry_premium"], "exit_premium": round(exit_px, 2),
        "gross_pnl": round(gross, 2), "fees": round(fb.total, 2),
        "realized_pnl": round(net, 2),
        "exit_reason": parent.get("exit_reason"), "exit_basis": parent.get("exit_basis"),
        "opened_at": pos["opened_at"], "closed_at": _now(),
    })
    await stock_book_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "status": "CLOSED", "exit_premium": round(exit_px, 2),
        "exit_reason": parent.get("exit_reason"), "exit_basis": parent.get("exit_basis"),
        "gross_pnl": round(gross, 2), "fees": round(fb.total, 2),
        "fee_breakdown": fb.as_dict(),
        "realized_pnl": round(net, 2), "unrealized_pnl": 0.0,
        "ltp": round(exit_px, 2), "closed_at": _now(), "updated_at": _now(),
    }})
    return net


async def _mark_open(book_positions: list[dict], parents: dict) -> None:
    """Mark open books to the parent's current premium. No quote call of our own."""
    for pos in book_positions:
        parent = parents.get(pos.get("parent_position_id"))
        if not parent:
            continue
        ltp = parent.get("ltp")
        if ltp is None:
            continue
        unreal = round((float(ltp) - pos["entry_premium"]) * pos["lots"] * pos["lot_size"], 2)
        await stock_book_positions_collection.update_one(
            {"_id": pos["_id"]},
            {"$set": {"ltp": round(float(ltp), 2), "unrealized_pnl": unreal,
                      "updated_at": _now()}})


async def _update_scores(pairs: set) -> None:
    """Recompute the leaderboard row for each (book, strategy) that just changed."""
    for book, sid in pairs:
        trades = [t async for t in stock_book_trades_collection.find(
            {"book": book, "strategy_id": sid})]
        n = len(trades)
        net = sum(t.get("realized_pnl") or 0.0 for t in trades)
        gross = sum(t.get("gross_pnl") or 0.0 for t in trades)
        fees = sum(t.get("fees") or 0.0 for t in trades)
        wins = [t for t in trades if (t.get("realized_pnl") or 0) > 0]
        losses = [t for t in trades if (t.get("realized_pnl") or 0) < 0]
        gp = sum(t["realized_pnl"] for t in wins)
        gl = abs(sum(t["realized_pnl"] for t in losses))
        declined = await stock_book_positions_collection.count_documents(
            {"book": book, "strategy_id": sid, "status": "DECLINED"})
        name = trades[-1].get("strategy_name") if trades else sid
        await stock_book_scores_collection.update_one(
            {"_id": f"{book}:{sid}"},
            {"$set": {
                "book": book, "strategy_id": sid, "strategy_name": name,
                "is_anti": bool(trades[-1].get("is_anti")) if trades else False,
                "trades": n, "wins": len(wins),
                "win_rate": round(len(wins) / n, 4) if n else 0.0,
                "net_pnl": round(net, 2), "gross_pnl": round(gross, 2),
                "fees": round(fees, 2),
                "profit_factor": round(gp / gl, 3) if gl > 0 else None,
                "declined": declined,
                "updated_at": _now(),
            }}, upsert=True)


# -- the cycle -------------------------------------------------------------------


async def run_cycle() -> dict:
    """Follow the parent desk once: close what it closed, open what it opened, mark the rest."""
    if not ENABLED:
        return {"opened": 0, "closed": 0, "declined": 0, "marked": 0,
                "notes": ["books disabled"]}

    opened = closed = declined = marked = 0
    touched: set = set()

    # Everything the parent has ever held that a book might still be following. Keyed by
    # position_id so both the close pass and the mark pass can look a parent up directly.
    parents: dict[str, dict] = {}
    async for p in stock_desk_positions_collection.find({"side": PARENT_SIDE}):
        parents[p.get("position_id")] = p

    for book in BOOKS:
        # 1) close first, so the cash a close frees is available to the same cycle's opens.
        open_rows = [p async for p in stock_book_positions_collection.find(
            {"book": book, "status": "OPEN"})]
        still_open: list[dict] = []
        for pos in open_rows:
            parent = parents.get(pos.get("parent_position_id"))
            if parent and parent.get("status") == "VOIDED":
                # The parent's fill was struck out as one that could never have happened (an
                # entry outside market hours, say). A mirror of an impossible fill is just as
                # impossible, so it is voided too - cash released, no P&L either way - rather
                # than being left OPEN forever waiting for a close that will never come.
                await stock_book_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
                    "status": "VOIDED", "void_reason": parent.get("void_reason"),
                    "unrealized_pnl": 0.0, "updated_at": _now()}})
                continue
            if parent and parent.get("status") == "CLOSED":
                await _close_mirror(pos, parent)
                closed += 1
                touched.add((book, pos["strategy_id"]))
            else:
                still_open.append(pos)

        # 2) mark what is still open to the parent's latest premium.
        await _mark_open(still_open, parents)
        marked += len(still_open)

        # 3) take what the parent is holding that this book has not seen yet, oldest first
        #    so the book spends its cash in the order the signals actually arrived rather
        #    than in whatever order Mongo returns them.
        cash = await _cash(book)
        candidates = sorted(
            (p for p in parents.values() if p.get("status") == "OPEN"),
            key=lambda p: str(p.get("opened_at") or ""))
        for parent in candidates:
            before = await stock_book_positions_collection.count_documents(
                {"book": book, "parent_position_id": parent.get("position_id")})
            if before:
                continue
            spent = await _open_mirror(book, parent, cash)
            if spent > 0:
                cash -= spent
                opened += 1
                touched.add((book, parent["strategy_id"]))
            else:
                # Either declined (a row was written) or skipped for an open position of the
                # same strategy. Only the former is a finding, so count rows not calls.
                if await stock_book_positions_collection.find_one(
                        {"book": book, "parent_position_id": parent.get("position_id"),
                         "status": "DECLINED"}):
                    declined += 1

        await stock_book_equity_collection.insert_one({
            "book": book, "ts": _now(), **(await summary(book))})

    await _update_scores(touched)
    await stock_book_state_collection.update_one(
        {"_id": "state"},
        {"$set": {"last_run_at": _now(), "last_opened": opened, "last_closed": closed,
                  "last_declined": declined, "parent_side": PARENT_SIDE}},
        upsert=True)
    return {"opened": opened, "closed": closed, "declined": declined,
            "marked": marked, "notes": []}


# -- read models -----------------------------------------------------------------


async def summary(book: str = DEFAULT_BOOK) -> dict:
    book = normalize_book(book)
    capital = book_capital(book)
    realized = unrealized = deployed = gross = fees = 0.0
    n_open = n_closed = n_declined = 0
    async for p in stock_book_positions_collection.find({"book": book}):
        st = p.get("status")
        if st == "OPEN":
            n_open += 1
            deployed += p.get("capital_deployed") or 0.0
            unrealized += p.get("unrealized_pnl") or 0.0
        elif st == "CLOSED":
            n_closed += 1
            realized += p.get("realized_pnl") or 0.0
            gross += p.get("gross_pnl") or 0.0
            fees += p.get("fees") or 0.0
        elif st == "DECLINED":
            n_declined += 1
    strategies = len(await stock_book_scores_collection.distinct("strategy_id", {"book": book}))
    return {
        "book": book, "books": BOOKS, "label": BOOK_LABEL[book],
        "book_labels": BOOK_LABEL, "book_capitals": BOOK_CAPITAL,
        "mode": "PAPER", "enabled": ENABLED, "parent_side": PARENT_SIDE,
        "capital": capital,
        "position_cap": round(position_cap(book), 2),
        "cash": round(capital + realized - deployed, 2),
        "deployed": round(deployed, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "gross_pnl": round(gross, 2),
        "fees": round(fees, 2),
        "equity": round(capital + realized + unrealized, 2),
        "roi_pct": round((realized + unrealized) / capital * 100, 4) if capital else 0.0,
        "open_positions": n_open, "closed_positions": n_closed,
        "declined": n_declined,
        "strategies": strategies,
    }


async def leaderboard(book: str = DEFAULT_BOOK) -> list[dict]:
    book = normalize_book(book)
    rows = [r async for r in stock_book_scores_collection.find({"book": book})]
    rows.sort(key=lambda r: -(r.get("net_pnl") or 0.0))
    for r in rows:
        r.pop("_id", None)
    return rows


async def positions(book: str = DEFAULT_BOOK, status: str = "OPEN",
                    limit: int = 400) -> list[dict]:
    book = normalize_book(book)
    q: dict = {"book": book}
    if status and status.upper() != "ALL":
        q["status"] = status.upper()
    out = []
    async for p in stock_book_positions_collection.find(q).sort("opened_at", -1).limit(limit):
        p.pop("_id", None)
        out.append(p)
    return out


async def trades(book: str = DEFAULT_BOOK, limit: int = 200) -> list[dict]:
    book = normalize_book(book)
    out = []
    async for t in stock_book_trades_collection.find({"book": book}).sort(
            "closed_at", -1).limit(limit):
        t.pop("_id", None)
        out.append(t)
    return out


async def ensure_indexes() -> None:
    # Every write here is wrapped by main.py's _try; an index failure must never be able to
    # stop the backend starting.
    await stock_book_positions_collection.create_index([("book", 1), ("status", 1)])
    await stock_book_positions_collection.create_index([("book", 1),
                                                        ("parent_position_id", 1)])
    await stock_book_positions_collection.create_index([("book", 1), ("strategy_id", 1),
                                                        ("status", 1)])
    await stock_book_trades_collection.create_index([("book", 1), ("strategy_id", 1)])
    await stock_book_trades_collection.create_index([("book", 1), ("closed_at", -1)])
    await stock_book_scores_collection.create_index([("book", 1)])
