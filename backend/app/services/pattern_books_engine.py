"""Pattern Paper Books — a shortlist of the pattern desk, at a size a real account uses.

The 548-strategy pattern desk (`intraday_pattern_engine`) gives every strategy its own
Rs 10,00,000 and asks one question: does this template have an edge on this candle? These
books ask the next one: does that edge survive on a small account, where whole-share
rounding and a roughly fixed round-trip fee are no longer rounding errors?

So a SHORTLIST of that desk's best strategies runs in TWO independent books that differ
only in capital — Rs 50,000 and Rs 2,00,000.

WHY TWO SIZES RATHER THAN ONE SCALED NUMBER
-------------------------------------------
Scaling one book's returns would hide the two things that actually decide whether a small
account works, because neither is linear in capital:

  * **Whole shares.** Rs 50,000 across eight strategies is Rs 6,250 each, which cannot buy
    a single Rs 7,000 share — that signal is simply skipped, while the Rs 25,000 slice in
    the larger book takes 3. The parent desk, on Rs 10 lakh, took 142 and never noticed.
  * **Fees are near-fixed per round trip.** The same trade costs roughly the same rupees in
    both books, so it is four times the drag on the smaller one.

Running both for real is the only way to see either, which is exactly why `live_intraday`
runs its shortlist at three sizes rather than dividing one.

THE BOOKS MIRROR THE PARENT'S FILLS — THEY DO NOT RE-SCAN
----------------------------------------------------------
A book opens when the pattern desk opens a shortlisted strategy, at the parent's entry
price, and closes when the parent closes, at the parent's exit price. Nothing here calls
Angel at all.

That is deliberate on two counts. First, cost: a second scan would refetch the same
candles for the same 25 symbols, and Angel's candle endpoint is the binding constraint on
this whole module — the parent desk already caps its universe at 25 symbols for exactly
this reason. Second, honesty: sharing the parent's signal and fill means any difference in
the books' results is caused by SIZE and nothing else, which is the only question they
exist to answer. If they re-derived their own signals, a divergence could be a different
entry rather than a different account, and the comparison would be worthless.

What is NOT shared is the part that matters: sizing, cash, fees and P&L are computed per
book, against that book's own capital.
"""

import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import (
    pattern_book_equity_collection,
    pattern_book_positions_collection,
    pattern_book_scores_collection,
    pattern_book_state_collection,
    pattern_book_trades_collection,
    pattern_positions_collection,
)
from app.services.angel_fees import product_for, round_trip
from app.services.intraday_pattern_engine import CATALOG

logger = logging.getLogger("pattern_books")

# ── the shortlist ────────────────────────────────────────────────────────────────
# Picked off the pattern desk's own leaderboard by ROI. Stored as (template, timeframe)
# rather than strategy_id because the id encodes the template's INDEX in the catalog
# (`pat_30m_15`), so inserting a template upstream would silently repoint every id — the
# names are what a person actually chose.
SELECTED_SPECS: list[tuple[str, str]] = [
    ("Williams %R Reversal",   "30m"),
    ("Bollinger %B Extreme",   "30m"),
    ("Bollinger Mean Revert",  "30m"),
    ("Pivot R1/S1 Break",      "1m"),
    ("Three Soldiers / Crows", "1h"),
    ("CCI Zero Cross",         "1h"),
    ("EMA Fast Cross",         "30m"),
    ("MACD Zero Line",         "30m"),
]


def _resolve() -> list:
    """Shortlist specs -> catalog strategies, skipping any that no longer exist.

    A name that has been renamed or dropped upstream is logged and left out rather than
    raising: this module is imported at startup, and a missing template must not be able to
    take the whole backend down over a shortlist entry."""
    by_key = {(s.template, s.timeframe): s for s in CATALOG}
    out, missing = [], []
    for template, tf in SELECTED_SPECS:
        st = by_key.get((template, tf))
        if st is None:
            missing.append(f"{template} · {tf}")
            continue
        out.append(st)
    if missing:
        logger.warning("[pattern_books] %d shortlisted strategies not in the catalog: %s",
                       len(missing), ", ".join(missing))
    return out


SELECTED = _resolve()
SELECTED_BY_ID = {s.strategy_id: s for s in SELECTED}

# ── the books ────────────────────────────────────────────────────────────────────
# Capital is the DESK total; each shortlisted strategy gets an equal slice of it, which is
# also its per-position cap — there is no pyramiding on a book this size.
BOOK_CAPITAL: dict[str, float] = {
    "50k": float(os.getenv("PATBOOK_CAPITAL_50K", "50000")),
    "2L": float(os.getenv("PATBOOK_CAPITAL_2L", "200000")),
}
BOOKS = list(BOOK_CAPITAL)
DEFAULT_BOOK = "50k"
BOOK_LABEL = {"50k": "Paper Trade · ₹50k", "2L": "Paper Trade · ₹2 lakh"}

ENABLED = os.getenv("PATBOOK_ENABLED", "1").lower() not in ("0", "false", "")


def normalize_book(book: str | None) -> str:
    return book if book in BOOK_CAPITAL else DEFAULT_BOOK


def book_capital(book: str) -> float:
    return BOOK_CAPITAL[normalize_book(book)]


def per_strategy_allocation(book: str) -> float:
    """Equal slice of the desk, and the per-position cap."""
    return book_capital(book) / max(len(SELECTED), 1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _size(entry_price: float, budget: float, cash: float) -> int:
    """Whole shares only — the constraint these books exist to measure."""
    if entry_price <= 0:
        return 0
    return max(int(min(budget, cash) // entry_price), 0)


# ── cash ─────────────────────────────────────────────────────────────────────────


async def _deployed(book: str, strategy_id: str) -> float:
    total = 0.0
    async for p in pattern_book_positions_collection.find(
        {"book": book, "strategy_id": strategy_id, "status": "OPEN"}, {"capital_deployed": 1}
    ):
        total += p.get("capital_deployed", 0.0) or 0.0
    return total


async def _realized(book: str, strategy_id: str) -> float:
    total = 0.0
    async for p in pattern_book_positions_collection.find(
        {"book": book, "strategy_id": strategy_id, "status": "CLOSED"},
        {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    return total


async def _cash(book: str, strategy_id: str) -> float:
    alloc = per_strategy_allocation(book)
    return alloc + await _realized(book, strategy_id) - await _deployed(book, strategy_id)


# ── mirroring the parent's fills ─────────────────────────────────────────────────


async def _open_mirror(book: str, parent: dict) -> bool:
    """Take the parent's signal at this book's size, or decline it and say why."""
    sid = parent["strategy_id"]
    if await pattern_book_positions_collection.find_one(
        {"book": book, "parent_position_id": parent["position_id"]}
    ):
        return False                                   # already mirrored
    if await pattern_book_positions_collection.find_one(
        {"book": book, "strategy_id": sid, "status": "OPEN"}
    ):
        return False                                   # one position per strategy per book

    price = float(parent.get("entry_price") or 0.0)
    cash = await _cash(book, sid)
    qty = _size(price, per_strategy_allocation(book), cash)
    if qty < 1:
        # Not an error — this IS the finding the small book exists to produce, so it is
        # recorded as a row rather than a tally. A row is auditable ("which signals could
        # this account not take, and in what") and, because the duplicate check above
        # matches on parent_position_id at ANY status, it also stops the same missed signal
        # being counted again on every cycle for as long as the parent holds the position.
        await pattern_book_positions_collection.insert_one({
            "position_id": uuid4().hex[:12], "book": book,
            "parent_position_id": parent["position_id"],
            "strategy_id": sid, "strategy_name": parent.get("strategy_name"),
            "template": parent.get("template"), "family": parent.get("family"),
            "timeframe": parent.get("timeframe"), "style": parent.get("style"),
            "symbol": parent.get("symbol"), "side": parent.get("side"),
            "entry_price": round(price, 2), "qty": 0, "capital_deployed": 0.0,
            "allocation": round(per_strategy_allocation(book), 2),
            "status": "DECLINED",
            "decline_reason": (
                f"₹{per_strategy_allocation(book):,.0f} slice buys 0 shares of "
                f"{parent.get('symbol')} at ₹{price:,.2f}"),
            "realized_pnl": None, "unrealized_pnl": 0.0, "gross_pnl": None, "fees": None,
            "opened_at": _now(), "opened_on": parent.get("opened_on"),
            "closed_at": None, "updated_at": _now(),
        })
        return False

    await pattern_book_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "book": book,
        "parent_position_id": parent["position_id"],
        "strategy_id": sid, "strategy_name": parent.get("strategy_name"),
        "template": parent.get("template"), "family": parent.get("family"),
        "timeframe": parent.get("timeframe"), "style": parent.get("style"),
        "symbol": parent.get("symbol"), "side": parent.get("side"),
        "entry_price": round(price, 2), "qty": qty,
        "capital_deployed": round(price * qty, 2),
        "allocation": round(per_strategy_allocation(book), 2),
        "target": parent.get("target"), "stoploss": parent.get("stoploss"),
        "ltp": round(price, 2), "unrealized_pnl": 0.0,
        "realized_pnl": None, "gross_pnl": None, "fees": None, "fee_breakdown": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "opened_at": _now(), "opened_on": parent.get("opened_on"),
        "closed_at": None, "updated_at": _now(),
    })
    return True


async def _close_mirror(pos: dict, parent: dict) -> float:
    """Close at the parent's exit, charging this book's own fees on its own quantity."""
    exit_price = float(parent.get("exit_price") or pos.get("ltp") or pos["entry_price"])
    qty = int(pos["qty"])
    side = pos.get("side") or "BUY"
    sign = 1 if side == "BUY" else -1
    gross = (exit_price - pos["entry_price"]) * qty * sign

    # Same fee call the parent desk makes, on THIS book's quantity. `product_for(None,
    # days)` mirrors `intraday_pattern_engine.manage` exactly — DELIVERY only when the
    # position actually slept overnight — so the two desks can never charge a different
    # schedule for the same trade and make a size comparison meaningless.
    days = 0
    if parent.get("opened_on") and parent.get("closed_on"):
        try:
            days = (datetime.fromisoformat(str(parent["closed_on"])).date()
                    - datetime.fromisoformat(str(parent["opened_on"])).date()).days
        except (TypeError, ValueError):
            days = 0
    fb = round_trip(pos["entry_price"], exit_price, qty, side=side,
                    product=product_for(None, days))
    fees = fb.total
    net = gross - fees

    await pattern_book_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "book": pos["book"],
        "strategy_id": pos["strategy_id"], "strategy_name": pos.get("strategy_name"),
        "template": pos.get("template"), "family": pos.get("family"),
        "timeframe": pos.get("timeframe"), "symbol": pos.get("symbol"), "side": side,
        "entry_price": pos["entry_price"], "exit_price": round(exit_price, 2), "qty": qty,
        "gross_pnl": round(gross, 2), "fees": round(fees, 2), "realized_pnl": round(net, 2),
        "exit_reason": parent.get("exit_reason"),
        "opened_at": pos["opened_at"], "closed_at": _now(),
    })
    await pattern_book_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "status": "CLOSED", "exit_price": round(exit_price, 2),
        "exit_reason": parent.get("exit_reason"),
        "gross_pnl": round(gross, 2), "fees": round(fees, 2),
        "fee_breakdown": fb.as_dict(),
        "realized_pnl": round(net, 2), "unrealized_pnl": 0.0,
        "ltp": round(exit_price, 2), "closed_at": _now(), "updated_at": _now(),
    }})
    return net


async def _mark_open(book_positions: list[dict], parents: dict) -> None:
    """Mark open books to the parent's current LTP. No quote call of our own."""
    for pos in book_positions:
        parent = parents.get(pos["parent_position_id"])
        if not parent:
            continue
        ltp = float(parent.get("ltp") or pos.get("ltp") or pos["entry_price"])
        sign = 1 if (pos.get("side") or "BUY") == "BUY" else -1
        unreal = (ltp - pos["entry_price"]) * int(pos["qty"]) * sign
        await pattern_book_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
            "ltp": round(ltp, 2), "unrealized_pnl": round(unreal, 2), "updated_at": _now(),
        }})


# ── scoring ──────────────────────────────────────────────────────────────────────


async def _update_scores(pairs: set) -> None:
    for book, sid in pairs:
        st = SELECTED_BY_ID.get(sid)
        trades = wins = 0
        net = gross = fees = 0.0
        async for p in pattern_book_positions_collection.find(
            {"book": book, "strategy_id": sid, "status": "CLOSED"},
            {"realized_pnl": 1, "gross_pnl": 1, "fees": 1}
        ):
            trades += 1
            r = p.get("realized_pnl") or 0.0
            net += r
            gross += p.get("gross_pnl") or 0.0
            fees += p.get("fees") or 0.0
            if r > 0:
                wins += 1
        alloc = per_strategy_allocation(book)
        await pattern_book_scores_collection.update_one(
            {"book": book, "strategy_id": sid},
            {"$set": {
                "book": book, "strategy_id": sid,
                "name": st.name if st else sid,
                "template": st.template if st else None,
                "family": st.family if st else None,
                "timeframe": st.timeframe if st else None,
                "style": st.style if st else None,
                "trades": trades, "wins": wins,
                "win_rate": round(wins / trades, 4) if trades else 0.0,
                "net_pnl": round(net, 2), "gross_pnl": round(gross, 2),
                "fees": round(fees, 2),
                "allocation": round(alloc, 2),
                # ROI on the slice this strategy actually runs, not on the whole desk —
                # otherwise eight strategies each "returning" desk-level percentages would
                # sum to eight times the book's real return.
                "roi_pct": round(net / alloc * 100, 4) if alloc else 0.0,
                "updated_at": _now(),
            }}, upsert=True)


# ── cycle ────────────────────────────────────────────────────────────────────────


async def run_cycle() -> dict:
    """Mirror the parent desk: close what it closed, open what it opened.

    Ordering matters — closes first. A strategy holds at most one position per book, so
    releasing the closed one before mirroring the next entry is what lets a book take a
    signal on the same strategy in the same cycle."""
    if not ENABLED:
        return {"opened": 0, "closed": 0, "notes": ["pattern books disabled"]}
    if not SELECTED:
        return {"opened": 0, "closed": 0,
                "notes": ["No shortlisted strategies resolved against the pattern catalog."]}

    sids = list(SELECTED_BY_ID)
    parents = {p["position_id"]: p async for p in pattern_positions_collection.find(
        {"strategy_id": {"$in": sids}})}

    opened = closed = 0
    touched = set()

    # 1. Close any book position whose parent has closed.
    open_books = [p async for p in pattern_book_positions_collection.find({"status": "OPEN"})]
    for pos in open_books:
        parent = parents.get(pos["parent_position_id"])
        if parent is None:
            continue
        if parent.get("status") == "OPEN":
            continue
        await _close_mirror(pos, parent)
        touched.add((pos["book"], pos["strategy_id"]))
        closed += 1

    # 2. Mirror parent positions that are open and not yet in each book.
    for parent in parents.values():
        if parent.get("status") != "OPEN":
            continue
        for book in BOOKS:
            if await _open_mirror(book, parent):
                opened += 1
                touched.add((book, parent["strategy_id"]))

    # 3. Mark the survivors to the parent's LTP.
    still_open = [p async for p in pattern_book_positions_collection.find({"status": "OPEN"})]
    await _mark_open(still_open, parents)

    await _update_scores(touched)

    for book in BOOKS:
        snap = await summary(book)
        await pattern_book_equity_collection.insert_one({
            "ts": _now(), "book": book, "equity": snap["equity"],
            "realized": snap["realized_pnl"], "unrealized": snap["unrealized_pnl"],
            "open_positions": snap["open_positions"],
        })
    await pattern_book_state_collection.update_one({"_id": "engine"}, {"$set": {
        "last_run_at": _now(), "last_opened": opened, "last_closed": closed,
        "selected": len(SELECTED),
    }}, upsert=True)
    return {"opened": opened, "closed": closed, "books": BOOKS, "notes": []}


# ── read models ──────────────────────────────────────────────────────────────────


async def summary(book: str = DEFAULT_BOOK) -> dict:
    book = normalize_book(book)
    cap = book_capital(book)
    realized = unrealized = deployed = fees = gross = 0.0
    open_n = closed_n = 0
    async for p in pattern_book_positions_collection.find(
        {"book": book, "status": "OPEN"},
        {"capital_deployed": 1, "unrealized_pnl": 1}
    ):
        open_n += 1
        deployed += p.get("capital_deployed", 0.0) or 0.0
        unrealized += p.get("unrealized_pnl") or 0.0
    async for p in pattern_book_positions_collection.find(
        {"book": book, "status": "CLOSED"},
        {"realized_pnl": 1, "fees": 1, "gross_pnl": 1}
    ):
        closed_n += 1
        realized += p.get("realized_pnl") or 0.0
        fees += p.get("fees") or 0.0
        gross += p.get("gross_pnl") or 0.0

    declined = await pattern_book_positions_collection.count_documents(
        {"book": book, "status": "DECLINED"})
    last_decline = None
    async for d in pattern_book_positions_collection.find(
            {"book": book, "status": "DECLINED"}).sort("opened_at", -1).limit(1):
        last_decline = d.get("decline_reason")
    state = await pattern_book_state_collection.find_one({"_id": "engine"}) or {}
    equity = cap + realized + unrealized
    return {
        "book": book, "books": BOOKS, "label": BOOK_LABEL.get(book, book),
        "book_capitals": {b: BOOK_CAPITAL[b] for b in BOOKS},
        "book_labels": BOOK_LABEL,
        "mode": "paper", "enabled": ENABLED,
        "desk_capital": cap,
        "strategies": len(SELECTED),
        "per_strategy_allocation": round(per_strategy_allocation(book), 2),
        "equity": round(equity, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "gross_pnl": round(gross, 2), "fees": round(fees, 2),
        "deployed": round(deployed, 2),
        "available_cash": round(cap + realized - deployed, 2),
        "open_positions": open_n, "closed_positions": closed_n,
        "roi_pct": round((equity - cap) / cap * 100, 4) if cap else 0.0,
        # How often this book's slice could not buy a single share. The whole point of
        # running the small book, so it is a headline number rather than a log line.
        "skipped_unaffordable": declined,
        "last_skip": last_decline,
        "last_run_at": state["last_run_at"].isoformat() if state.get("last_run_at") else None,
        "source": "mirrors the 548-strategy pattern desk's fills for the shortlist",
    }


async def leaderboard(book: str = DEFAULT_BOOK) -> list[dict]:
    book = normalize_book(book)
    scores = {s["strategy_id"]: s async for s in
              pattern_book_scores_collection.find({"book": book})}
    open_counts: dict = {}
    async for p in pattern_book_positions_collection.find(
        {"book": book, "status": "OPEN"}, {"strategy_id": 1}
    ):
        open_counts[p["strategy_id"]] = open_counts.get(p["strategy_id"], 0) + 1

    alloc = per_strategy_allocation(book)
    rows = []
    for st in SELECTED:
        sc = scores.get(st.strategy_id) or {}
        rows.append({
            "strategy_id": st.strategy_id, "name": st.name, "template": st.template,
            "family": st.family, "timeframe": st.timeframe, "style": st.style,
            "allocation": round(alloc, 2),
            "trades": sc.get("trades", 0) or 0,
            "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "gross_pnl": round(sc.get("gross_pnl", 0.0) or 0.0, 2),
            "fees": round(sc.get("fees", 0.0) or 0.0, 2),
            "net_pnl": round(sc.get("net_pnl", 0.0) or 0.0, 2),
            "roi_pct": round(sc.get("roi_pct", 0.0) or 0.0, 4),
            "open_positions": open_counts.get(st.strategy_id, 0),
        })
    rows.sort(key=lambda r: (-r["net_pnl"], r["name"]))
    return rows


async def positions(book: str = DEFAULT_BOOK, status: str = "OPEN",
                    limit: int = 300) -> list[dict]:
    book = normalize_book(book)
    q: dict = {"book": book}
    if status.upper() != "ALL":
        q["status"] = status.upper()
    out = []
    async for d in pattern_book_positions_collection.find(q).sort("opened_at", -1).limit(limit):
        d.pop("_id", None)
        for k in ("opened_at", "closed_at", "updated_at"):
            if d.get(k) is not None and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        out.append(d)
    return out


async def trades(book: str = DEFAULT_BOOK, limit: int = 200) -> list[dict]:
    book = normalize_book(book)
    out = []
    async for d in pattern_book_trades_collection.find({"book": book}).sort(
            "closed_at", -1).limit(limit):
        d.pop("_id", None)
        for k in ("opened_at", "closed_at"):
            if d.get(k) is not None and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        out.append(d)
    return out


async def ensure_indexes() -> None:
    """Best-effort; an index is a speed-up, never a precondition for the desk to load."""
    specs = [
        (pattern_book_positions_collection, [("book", 1), ("status", 1)], "pb_pos_book_status", False),
        (pattern_book_positions_collection, [("book", 1), ("parent_position_id", 1)],
         "pb_pos_parent", False),
        (pattern_book_positions_collection, [("book", 1), ("strategy_id", 1), ("status", 1)],
         "pb_pos_strategy", False),
        (pattern_book_trades_collection, [("book", 1), ("closed_at", -1)], "pb_trade_book", False),
        (pattern_book_scores_collection, [("book", 1), ("strategy_id", 1)], "pb_score_key", True),
        (pattern_book_equity_collection, [("book", 1), ("ts", -1)], "pb_equity_ts", False),
    ]
    made = skipped = 0
    for coll, keys, name, unique in specs:
        try:
            await coll.create_index(keys, name=name, unique=unique, background=True)
            made += 1
        except Exception as exc:  # noqa: BLE001 — one failure must not skip the rest
            skipped += 1
            logger.warning("[pattern_books] index %s skipped: %s", name, exc)
    logger.info("[pattern_books] indexes ensured (%d present, %d skipped)", made, skipped)
