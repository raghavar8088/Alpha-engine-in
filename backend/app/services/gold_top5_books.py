"""Top-5 paper books on the Gold Desk (2026-11-12).

The owner asked for three paper accounts on the Gold Desk's top five strategies:

    top5_2L       one Rs 2 lakh account the five share      at most 5 positions, each up to Rs 40,000
    top5_10L      one Rs 10 lakh account the five share     at most 5 positions, each up to Rs 2,00,000
    each10L_1..5  five Rs 10 lakh accounts, one a strategy  one position at a time, sized on that
                                                            account's own balance (its profit stays in it)

THE FIVE are the top of the desk's Rank on its Delta board (strategy_rank, desk "gold", venue delta)
as read on 12 Nov 2026 at 22:54 IST, and they are FROZEN - not re-picked as ranks move, as for every
Top-10 book. That board is H1, the nine pre-registered 4h templates on XAUTUSD, so all five are H1
templates. They had 8 to 18 closed trades each and none a t-stat of 2; a Rank under 30 trades is
pulled toward the middle. The pick is the best of a short record, not evidence of an edge.

THEY COPY THE DESK'S OWN TRADES. A copy opens when H1 opens one of the five, at H1's entry price,
and closes when H1 closes it, at H1's exit price, so a copy differs from H1 only in SIZE. Nothing
here scans a bar, asks Delta for a price or writes to the desk's records: H1's pre-registered record
is read, never touched.

SIZE AND COST
- Whole contracts of 0.001 oz at 1x (no leverage): a position ties up its notional, as H1's do.
- A contract's rupee cost is H1's entry price x 0.001 x USD/INR. The rate (Yahoo's INR=X through
  gold_desk.usd_inr) is read when the copy is decided and kept on the copy; its profit and loss
  convert at that same rate. With no rate, no new copy is made (open ones still close).
- P&L is H1's own per-contract result at the book's quantity: the price move between its fills (the
  spread is inside them), its fees (0.01% + 18% GST a side) and the funding it paid or was paid.
  On Delta each of those is proportional to the number of contracts.
- H1 fills at the touch for about 280 contracts. A Rs 2 lakh book's position is smaller than that, a
  Rs 10 lakh book's about twice and a Rs 10 lakh account's about ten times; the extra depth the larger
  ones would eat is NOT modelled.

ONE POSITION PER STRATEGY, NOT PER CONTRACT. Every pick trades the same contract. The other Top-10
books allow one position per contract (one stock, one commodity); here that would let one strategy
at a time trade. Each copy is instead its own position, as each of H1's sleeves is (its "record"
mode does not net), so a long and a short can be held at once. One real Delta account would net them.

SLOTS AND CASH are live_intraday_mirror.plan_book's: entries are decided on the trades' own clock,
closes before opens at the same instant, cash = capital + realised - tied up, never below zero. A
Rs 10 lakh-each account sizes an entry on its realised equity at that instant. It does this without
plan_book's newer `compound` flag, which a server running an older copy of that shared file would
reject. Instead the account takes one new entry per round, and each round's capital is its equity
then. Its strategy holds one position at a time, so this is exact.

A book starts the first time it runs and never back-fills: a position H1 already held then is not
copied. A desk trade that ends VOID (no recorded price) voids its copy - no P&L, the money back.
Main Control's gold_desk switch gates new copies, as it gates the desk's own entries.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.core.db import db, gold_positions_collection
from app.services.book_reset import naive_utc
from app.services.live_intraday_mirror import pending_since, plan_book

logger = logging.getLogger("gold_top5_books")

PARENTS = gold_positions_collection          # the desk's own records: read, never written
POSITIONS = db["gold_top5_positions"]
STATE = db["gold_top5_state"]
SOURCE_TAG = "gold-top5"
VENUE = "delta"
SYMBOL = "XAUTUSD"
ENABLED = os.getenv("GOLD_TOP5_BOOKS", "1").lower() not in ("0", "false", "")
TICK_SECONDS = int(os.getenv("GOLD_TOP5_TICK_SECONDS", "120"))
# H1 holds a position at most 60 4h bars (10 days). A pass reads the desk's trades opened inside this
# window, plus any an open copy points at; every pass decides all it sees.
LOOKBACK = timedelta(days=int(os.getenv("GOLD_TOP5_LOOKBACK_DAYS", "14")))
PICKED_AT = "2026-11-12T22:54:00+05:30"
BOARD = "the Gold Desk's Rank on its Delta board: H1's nine 4h templates on XAUTUSD, 115 closed trades"


@dataclass(frozen=True)
class Pick:
    n: int              # its place in the five
    key: str            # the board's id: symbol-template-timeframe
    template: str
    timeframe: str
    name: str
    score: float        # its Rank score at the pick
    trades: int         # closed trades at the pick
    bp: float           # net return a trade at the pick, basis points
    net_usd: float      # its net P&L on the desk at the pick, one H1 sleeve ($10,000 / 9)
    t: float            # t-stat of its net return a trade


PICKS: tuple[Pick, ...] = (
    Pick(1, "XAUTUSD-ema_ribbon-4h", "ema_ribbon", "4h", "EMA Ribbon Compression · 4h", 69.1, 12, 48.45, 64.39, 1.31),
    Pick(2, "XAUTUSD-donchian_fast-4h", "donchian_fast", "4h", "Donchian Breakout (fast) · 4h", 67.6, 14, 42.68, 66.27, 1.17),
    Pick(3, "XAUTUSD-round_number_break-4h", "round_number_break", "4h", "Round Number Break · 4h", 64.1, 18, 12.53, 25.03, 0.66),
    Pick(4, "XAUTUSD-hh_hl_shift-4h", "hh_hl_shift", "4h", "HH/HL Structure Shift · 4h", 52.5, 8, 12.08, 10.73, 0.24),
    Pick(5, "XAUTUSD-pivot_break-4h", "pivot_break", "4h", "Pivot R1/S1 Break · 4h", 50.6, 18, 9.48, 18.86, 0.37),
)
PICK = {p.key: p for p in PICKS}
ROSTER = tuple(p.key for p in PICKS)


@dataclass(frozen=True)
class Book:
    id: str
    group: str                 # "2L" | "10L" | "each10L"
    label: str
    capital: float
    roster: tuple[str, ...]
    max_open: int
    compound: bool             # size each entry on realised equity (the each-strategy accounts)

    @property
    def position_cap(self) -> float | None:
        """The most one position may tie up; None where it is the account's own balance."""
        return None if self.compound else self.capital / max(self.max_open, 1)


CAPITAL_2L = float(os.getenv("GOLD_TOP5_CAPITAL_2L", "200000"))
CAPITAL_10L = float(os.getenv("GOLD_TOP5_CAPITAL_10L", "1000000"))
BOOKS: tuple[Book, ...] = (
    Book("top5_2L", "2L", "Top 5 · ₹2 lakh", CAPITAL_2L, ROSTER, 5, False),
    Book("top5_10L", "10L", "Top 5 · ₹10 lakh", CAPITAL_10L, ROSTER, 5, False),
    *(Book(f"each10L_{p.n}", "each10L", f"{p.name} · ₹10 lakh", CAPITAL_10L, (p.key,), 1, True) for p in PICKS),
)
BOOK = {b.id: b for b in BOOKS}
GROUPS = (
    {"group": "2L", "label": "Top 5 · ₹2 lakh", "about": "one ₹2 lakh account the five share: up to 5 positions of ₹40,000"},
    {"group": "10L", "label": "Top 5 · ₹10 lakh", "about": "one ₹10 lakh account the five share: up to 5 positions of ₹2,00,000"},
    {"group": "each10L", "label": "Top 5 · ₹10 lakh each",
     "about": "five ₹10 lakh accounts, one per strategy: each trade uses that account's own balance"},
)
NOTES = (
    "The five are the top of this desk's Rank on 12 Nov 2026 at 22:54 IST and stay fixed. They had 8 to 18 closed "
    "trades each and none a t-stat of 2; a Rank under 30 trades is pulled toward the middle. A short good record, "
    "not a proven edge.",
    "Each copy is H1's own trade - its entry, its exit, its fees, the spread inside its fills and the funding it paid "
    "or was paid - at the account's size, in whole 0.001 oz contracts at 1x (no leverage). Nothing is re-scanned "
    "and no order is sent.",
    "Rupees at USD/INR (Yahoo INR=X) read when the copy is made; its profit and loss convert at that same rate.",
    "Each strategy's copy is its own position, as on the desk, so two of them can be long and short XAUTUSD at once. "
    "One real Delta account would net them into one position.",
    "H1 fills at the touch for about 280 contracts. A ₹10 lakh book's position is about twice that and a ₹10 lakh "
    "account's about ten times; the extra depth they would eat is not modelled.",
    "The accounts started when they first ran and copy only trades H1 opens after that; nothing is back-filled. "
    "Main Control's Gold Desk switch stops new copies.",
)


@dataclass
class Costs:
    total: float
    parts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {**self.parts, "total": self.total}


# -- small helpers ---------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(v) -> datetime | None:
    """Naive UTC from a datetime (naive = UTC, as Mongo returns them) or an ISO string."""
    if v is None:
        return None
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return naive_utc(v)


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _key(doc: dict) -> str:
    return f"{doc.get('symbol')}-{doc.get('strategy_template')}-{doc.get('timeframe')}"


# -- the desk's trades as parents ---------------------------------------------------------------------


def parent_of(doc: dict, fx: float | None) -> dict | None:
    """One of the desk's positions as a parent to copy; None when it is not one of the five or cannot be.

    `entry_price` is what one contract ties up, in rupees at `fx`: plan_book sizes on it. With no rate
    it is 0, which only a pass that makes no new copy is ever given."""
    key = _key(doc)
    pick = PICK.get(key)
    entry = _f(doc.get("entry_price"))
    units = int(_f(doc.get("units")))
    side = doc.get("side")
    if pick is None or entry <= 0 or units <= 0 or side not in ("BUY", "SELL") or not doc.get("position_id"):
        return None
    cv = _f(doc.get("multiplier")) or _f((doc.get("instrument") or {}).get("contract_value")) or 0.001
    status = doc.get("status") or "OPEN"
    void = status == "VOID" or bool(doc.get("void"))
    closed = not void and status == "CLOSED" and doc.get("exit_price") is not None
    opened_at = _dt(doc.get("opened_at"))
    exit_px = _f(doc.get("exit_price")) if closed else None
    return {
        "position_id": doc["position_id"], "key": key, "strategy_id": key, "strategy_name": pick.name,
        "symbol": key,                    # one position per STRATEGY: see the module notes
        "instrument": doc.get("symbol") or SYMBOL, "side": side,
        "opened_at": opened_at,
        "opened_on": doc.get("opened_on") or (opened_at.date().isoformat() if opened_at else None),
        "closed_at": _dt(doc.get("closed_at")) if closed else None,
        "closed_on": doc.get("closed_on") if closed else None,
        "status": "VOID" if void else ("CLOSED" if closed else "OPEN"),
        "entry_price": round(entry * cv * fx, 4) if fx else 0.0,
        "exit_price": exit_px,
        "px_entry": entry, "px_exit": exit_px,
        "px_ltp": None if doc.get("ltp") is None else _f(doc.get("ltp")),
        "units": units, "contract_value": cv, "usd_inr": fx,
        # the desk's costs for ITS units: fees both sides (entry only while open) and funding so far
        "fees_usd": _f(doc.get("entry_costs")) + (_f(doc.get("exit_costs")) if closed else 0.0),
        "funding_usd": _f(doc.get("funding_paid")),
        "unrealized_usd": None if doc.get("unrealized_pnl") is None else _f(doc.get("unrealized_pnl")),
        "exit_reason": doc.get("exit_reason"), "exit_basis": doc.get("exit_basis"),
        "target": doc.get("target"), "stoploss": doc.get("stoploss"),
    }


def pnl(row: dict, parent: dict) -> tuple[float, float, Costs]:
    """(gross, net, costs) in rupees: H1's own result per contract at the book's contracts.

    plan_book calls it with a stored row (which carries the rate it was opened at) or, for a trade
    that opened and closed between two passes, with its own draft row (the parent carries the rate)."""
    q = int(row["qty"])
    k = q / parent["units"]
    fx = float(row.get("usd_inr") or parent["usd_inr"])
    sign = 1 if parent["side"] == "BUY" else -1
    gross_usd = sign * (parent["px_exit"] - parent["px_entry"]) * parent["contract_value"] * q
    fees_usd = parent["fees_usd"] * k
    funding_usd = parent["funding_usd"] * k
    gross = round(gross_usd * fx, 2)
    fees = round(fees_usd * fx, 2)
    funding = round(funding_usd * fx, 2)
    costs = Costs(round(fees + funding, 2), {"fees": fees, "funding": funding})
    return gross, round(gross - costs.total, 2), costs


def mark(row: dict, parent: dict) -> float | None:
    """An open copy's P&L: the desk's own mark (it counts the costs so far) at the copy's size and rate."""
    u = parent.get("unrealized_usd")
    fx = _f(row.get("usd_inr") or parent.get("usd_inr"))
    if u is None or fx <= 0:
        return None
    return round(u * int(row["qty"]) / parent["units"] * fx, 2)


# -- state -------------------------------------------------------------------------------------------


async def _start(book_id: str) -> datetime:
    """When this book began copying: the first time a pass saw it. Set once; nothing earlier is copied."""
    key = f"start:{book_id}"
    doc = await STATE.find_one({"_id": key})
    if doc and doc.get("started_at"):
        return naive_utc(doc["started_at"])
    await STATE.update_one({"_id": key}, {"$setOnInsert": {"kind": "start", "book": book_id, "started_at": _now()}},
                           upsert=True)
    doc = await STATE.find_one({"_id": key})
    return naive_utc(doc["started_at"])


async def _decided(book_id: str, parents: list[dict]) -> set[str]:
    """The desk trades this book has already copied or skipped."""
    ids = [p["position_id"] for p in parents]
    out: set[str] = set()
    async for r in POSITIONS.find({"book": book_id, "parent_position_id": {"$in": ids}}, {"parent_position_id": 1}):
        out.add(r["parent_position_id"])
    async for s in STATE.find({"kind": "skip", "book": book_id, "parent_position_id": {"$in": ids}},
                              {"parent_position_id": 1}):
        out.add(s["parent_position_id"])
    return out


async def _totals(book_id: str) -> tuple[float, float]:
    realized = deployed = 0.0
    async for r in POSITIONS.find({"book": book_id}, {"status": 1, "realized_pnl": 1, "capital_deployed": 1}):
        if r.get("status") == "OPEN":
            deployed += r.get("capital_deployed") or 0.0
        else:
            realized += r.get("realized_pnl") or 0.0
    return realized, deployed


async def _closed_after(book_id: str, t0: datetime | None) -> list[dict]:
    """The book's copies closed after t0: they still held their slot and cash when later entries happened."""
    if t0 is None:
        return []
    return [r async for r in POSITIONS.find(
        {"book": book_id, "status": "CLOSED", "closed_at": {"$gt": t0}},
        {"symbol": 1, "capital_deployed": 1, "realized_pnl": 1, "opened_at": 1, "closed_at": 1})]


async def _load(since: datetime, pointed: list[str]) -> list[dict]:
    """The desk's Delta positions of the five's templates opened since `since`, and any an open copy points at."""
    q = {"venue": VENUE, "symbol": SYMBOL,
         "strategy_template": {"$in": sorted({p.template for p in PICKS})},
         "timeframe": {"$in": sorted({p.timeframe for p in PICKS})},
         "$or": [{"opened_at": {"$gte": since}}, {"position_id": {"$in": pointed}}]}
    return [d async for d in PARENTS.find(q)]


async def _fx() -> tuple[float | None, str | None]:
    """USD/INR now (Yahoo INR=X, cached ten minutes by the desk; GOLD_USD_INR as its fallback)."""
    try:
        from app.services import gold_desk
        rate, asof = await gold_desk.usd_inr()
    except Exception:  # noqa: BLE001 - no rate means no new copy, never a guessed one
        logger.warning("[gold top5] USD/INR read failed", exc_info=True)
        return None, None
    return (float(rate), asof) if rate and float(rate) > 0 else (None, None)


# -- the copy --------------------------------------------------------------------------------------


def _row(book: Book, p: dict, qty: int, spend: float, fx_asof: str | None) -> dict:
    return {
        "position_id": uuid4().hex[:12], "book": book.id, "group": book.group, "source": SOURCE_TAG,
        "parent_position_id": p["position_id"], "key": p["key"], "strategy_id": p["key"],
        "strategy_name": p["strategy_name"], "symbol": p["symbol"], "instrument": p["instrument"],
        "side": p["side"], "qty": qty, "contract_value": p["contract_value"],
        "ounces": round(qty * p["contract_value"], 4), "parent_units": p["units"],
        "entry_px": p["px_entry"], "entry_price": p["entry_price"],
        "usd_inr": p["usd_inr"], "usd_inr_asof": fx_asof,
        "notional_usd": round(p["px_entry"] * p["contract_value"] * qty, 2), "capital_deployed": spend,
        "target": p.get("target"), "stoploss": p.get("stoploss"),
        "ltp": p.get("px_ltp"), "unrealized_pnl": 0.0,
        "realized_pnl": None, "gross_pnl": None, "fees": None, "fee_breakdown": None,
        "exit_px": None, "exit_reason": None, "exit_basis": None, "status": "OPEN",
        "opened_at": p["opened_at"], "opened_on": p.get("opened_on"), "closed_at": None, "closed_on": None,
        "updated_at": _now(),
    }


def _close_fields(p: dict, c: dict) -> dict:
    return {
        "status": "CLOSED", "exit_px": p["px_exit"], "exit_reason": p.get("exit_reason"),
        "exit_basis": p.get("exit_basis"), "gross_pnl": c["gross"], "fees": c["fb"].total,
        "fee_breakdown": c["fb"].as_dict(), "realized_pnl": c["net"], "unrealized_pnl": 0.0, "ltp": p["px_exit"],
        "closed_at": p.get("closed_at") or naive_utc(_now()), "closed_on": p.get("closed_on"), "updated_at": _now(),
    }


async def _sync_book(book: Book, parents_all: list[dict], entries: bool, fx_asof: str | None,
                     first_pending_only: bool = False) -> dict:
    n = {"opened": 0, "closed": 0, "skipped": 0, "marked": 0, "voided": 0, "pending": 0}
    by_id = {p["position_id"]: p for p in parents_all}
    floor = max(await _start(book.id), naive_utc(_now()) - LOOKBACK)
    open_rows = []
    async for r in POSITIONS.find({"book": book.id, "status": "OPEN"}):
        p = by_id.get(r.get("parent_position_id"))
        if p is not None and p["status"] == "VOID":
            # the desk's trade ended with no recorded price: so does the copy - no P&L, its money back
            res = await POSITIONS.update_one({"_id": r["_id"], "status": "OPEN"}, {"$set": {
                "status": "VOID", "void": True, "realized_pnl": 0.0, "gross_pnl": 0.0, "fees": 0.0,
                "unrealized_pnl": 0.0, "exit_reason": "void", "closed_at": naive_utc(_now()), "updated_at": _now()}})
            n["voided"] += res.modified_count
            continue
        open_rows.append(r)
    pointed = {r.get("parent_position_id") for r in open_rows}
    parents = [p for p in parents_all
               if p["key"] in book.roster and p["status"] != "VOID" and p["opened_at"] is not None
               and (p["opened_at"] >= floor or p["position_id"] in pointed)]
    parents.sort(key=lambda p: (p["opened_at"], p["position_id"]))
    realized, deployed = await _totals(book.id)
    decided = await _decided(book.id, parents) if entries else set()
    if first_pending_only and entries:
        # One new entry per round (sync runs rounds until none waits), so each is sized on the equity the
        # ones before it left.
        waiting = [p for p in parents if p["position_id"] not in decided and p["position_id"] not in pointed]
        later = {p["position_id"] for p in waiting[1:]}
        parents = [p for p in parents if p["position_id"] not in later]
        n["pending"] = len(later)
    t0 = pending_since(parents, decided, open_rows, SOURCE_TAG) if entries else None
    closed_rows = await _closed_after(book.id, t0) if entries else []
    # An each-strategy account's capital is its realised equity now: its one position may use all of it.
    capital, realized_in = (book.capital + realized, 0.0) if book.compound else (book.capital, realized)
    plan = plan_book(capital=capital, realized=realized_in, deployed=deployed, open_rows=open_rows,
                     parents=parents, decided=decided, breaker_tripped=False, entries=entries,
                     max_open=book.max_open, net_fn=pnl, source_tag=SOURCE_TAG, closed_rows=closed_rows)

    for c in plan["closes"]:
        res = await POSITIONS.update_one({"_id": c["row"]["_id"], "status": "OPEN"},
                                         {"$set": _close_fields(c["parent"], c)})
        n["closed"] += res.modified_count
    for o in plan["opens"]:
        p = o["parent"]
        doc = _row(book, p, o["qty"], o["spend"], fx_asof)
        if o["close"] is not None:
            doc.update(_close_fields(p, o["close"]))
        elif (u := mark(doc, p)) is not None:
            doc["unrealized_pnl"] = u          # marked now, not one pass later
        try:
            await POSITIONS.insert_one(doc)
        except DuplicateKeyError:
            continue
        n["opened"] += 1
        n["closed"] += 1 if o["close"] is not None else 0
    for s in plan["skips"]:
        p = s["parent"]
        await STATE.update_one({"_id": f"skip:{book.id}:{p['position_id']}"}, {"$setOnInsert": {
            "kind": "skip", "book": book.id, "key": p["key"], "parent_position_id": p["position_id"],
            "reason": s["reason"], "day": p.get("opened_on"), "at": _now()}}, upsert=True)
        n["skipped"] += 1

    closed_now = {c["row"]["_id"] for c in plan["closes"]}
    for r in open_rows:
        if r["_id"] in closed_now:
            continue
        p = by_id.get(r.get("parent_position_id"))
        if p is None or p["status"] != "OPEN":
            continue
        u = mark(r, p)
        if u is None:
            continue
        await POSITIONS.update_one({"_id": r["_id"], "status": "OPEN"},
                                   {"$set": {"ltp": p.get("px_ltp"), "unrealized_pnl": u, "updated_at": _now()}})
        n["marked"] += 1
    return n


_lock = asyncio.Lock()
_indexed = False


async def sync(entries: bool = True) -> dict:
    """Copy the desk into every book once: close what the desk closed, open what it opened, mark the rest."""
    global _indexed
    if not _indexed:
        _indexed = True
        await ensure_indexes()
    async with _lock:
        fx, asof = await _fx()
        if fx is not None:
            await STATE.update_one({"_id": "fx"}, {"$set": {"kind": "fx", "rate": fx, "asof": asof, "at": _now()}},
                                   upsert=True)
        allow = bool(entries and fx is not None)
        pointed = [r["parent_position_id"] async for r in POSITIONS.find({"status": "OPEN"}, {"parent_position_id": 1})
                   if r.get("parent_position_id")]
        docs = await _load(naive_utc(_now()) - LOOKBACK, pointed)
        parents = [p for p in (parent_of(d, fx) for d in docs) if p is not None]
        out: dict = {"entries": allow, "usd_inr": fx, "parents": len(parents), "books": {}}
        if entries and fx is None:
            out["note"] = "No USD/INR rate this pass: open copies were managed and no new copy was made."
        for b in BOOKS:
            try:
                if not b.compound:
                    out["books"][b.id] = await _sync_book(b, parents, allow, asof)
                    continue
                tot = {"opened": 0, "closed": 0, "skipped": 0, "marked": 0, "voided": 0}
                for _round in range(200):           # a strategy takes a few trades a week; 200 is a guard
                    r = await _sync_book(b, parents, allow, asof, first_pending_only=True)
                    for k in tot:
                        tot[k] += r.get(k, 0)
                    if not r.get("pending"):
                        break
                out["books"][b.id] = tot
            except Exception as exc:  # noqa: BLE001 - one book's bad row must not stop the others
                logger.warning("[gold top5] %s failed: %s", b.id, exc, exc_info=True)
                out["books"][b.id] = {"error": str(exc)[:200]}
        return out


async def loop() -> None:
    """Every TICK_SECONDS, around the clock (Delta trades 24/7). Started by gold_scheduler.gold_delta_loop."""
    from app.services.desk_switches import is_on

    await asyncio.sleep(45)
    while True:
        if ENABLED:
            try:
                r = await sync(entries=await is_on("gold_desk"))
                moved = {k: v for k, v in (r.get("books") or {}).items()
                         if any(v.get(x) for x in ("opened", "closed", "voided", "error"))}
                if moved:
                    logger.info("[gold top5] %s", moved)
            except Exception:  # noqa: BLE001
                logger.warning("[gold top5] cycle failed", exc_info=True)
        await asyncio.sleep(TICK_SECONDS)


# -- read models --------------------------------------------------------------------------------------


def _iso(v) -> str | None:
    d = _dt(v)
    return d.replace(tzinfo=timezone.utc).isoformat() if d else None


async def summary(book: Book) -> dict:
    realized = unrealized = deployed = fees = gross = 0.0
    open_n = closed_n = wins = voided = 0
    per = {k: {"key": k, "name": PICK[k].name, "trades": 0, "wins": 0, "net": 0.0, "open": 0, "unrealized": 0.0}
           for k in book.roster}
    async for r in POSITIONS.find({"book": book.id}):
        x = per.get(r.get("key"))
        status = r.get("status")
        if status == "OPEN":
            u = r.get("unrealized_pnl") or 0.0
            open_n += 1
            deployed += r.get("capital_deployed") or 0.0
            unrealized += u
            if x:
                x["open"] += 1
                x["unrealized"] += u
        elif status == "VOID":
            voided += 1
        else:
            v = r.get("realized_pnl") or 0.0
            closed_n += 1
            realized += v
            wins += 1 if v > 0 else 0
            fees += r.get("fees") or 0.0
            gross += r.get("gross_pnl") or 0.0
            if x:
                x["trades"] += 1
                x["wins"] += 1 if v > 0 else 0
                x["net"] += v
    skipped: dict[str, int] = {}
    async for s in STATE.find({"kind": "skip", "book": book.id}, {"reason": 1}):
        skipped[s.get("reason") or "?"] = skipped.get(s.get("reason") or "?", 0) + 1
    start = await STATE.find_one({"_id": f"start:{book.id}"})
    equity = book.capital + realized + unrealized
    return {
        "id": book.id, "group": book.group, "label": book.label, "capital": book.capital,
        "roster": list(book.roster), "max_open": book.max_open, "position_cap": book.position_cap,
        "compound": book.compound,
        "equity": round(equity, 2), "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "deployed": round(deployed, 2), "available_cash": round(book.capital + realized - deployed, 2),
        "open_positions": open_n, "closed_positions": closed_n, "wins": wins,
        "win_rate": round(wins / closed_n * 100, 1) if closed_n else None,
        "fees": round(fees, 2), "gross_pnl": round(gross, 2),
        "roi_pct": round((equity - book.capital) / book.capital * 100, 4) if book.capital else 0.0,
        "skipped": skipped, "voided": voided,
        "started_at": _iso(start.get("started_at")) if start else None,
        "strategies": [{**x, "net": round(x["net"], 2), "unrealized": round(x["unrealized"], 2)} for x in per.values()],
    }


def _sum_books(rows: list[dict]) -> dict:
    """The five each-strategy accounts as one line: the money the third account type puts to work."""
    cap = sum(r["capital"] for r in rows)
    keys = ("equity", "realized_pnl", "unrealized_pnl", "deployed", "available_cash", "fees", "gross_pnl")
    out = {k: round(sum(r[k] for r in rows), 2) for k in keys}
    closed = sum(r["closed_positions"] for r in rows)
    wins = sum(r["wins"] for r in rows)
    out.update(capital=cap, accounts=len(rows), open_positions=sum(r["open_positions"] for r in rows),
               closed_positions=closed, wins=wins, win_rate=round(wins / closed * 100, 1) if closed else None,
               roi_pct=round((out["equity"] - cap) / cap * 100, 4) if cap else 0.0)
    return out


async def overview() -> dict:
    books = [await summary(b) for b in BOOKS]
    fx = await STATE.find_one({"_id": "fx"})
    return {
        "mode": "paper", "enabled": ENABLED, "tick_seconds": TICK_SECONDS,
        "picked_at": PICKED_AT, "board": BOARD, "venue": VENUE, "instrument": SYMBOL,
        "picks": [asdict(p) for p in PICKS], "groups": list(GROUPS), "books": books,
        "each_total": _sum_books([b for b in books if b["group"] == "each10L"]),
        "usd_inr": {"rate": fx.get("rate"), "asof": fx.get("asof"), "at": _iso(fx.get("at"))} if fx else None,
        "notes": list(NOTES),
    }


def _jsonable(doc: dict) -> dict:
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = naive_utc(v).replace(tzinfo=timezone.utc).isoformat()
    return doc


async def positions(book_id: str, status: str = "OPEN", limit: int = 200) -> list[dict]:
    """A book's copies: OPEN (newest first), CLOSED (closed or void, latest close first) or ALL."""
    s = status.upper()
    q: dict = {"book": book_id}
    if s == "OPEN":
        q["status"] = "OPEN"
    elif s == "CLOSED":
        q["status"] = {"$in": ["CLOSED", "VOID"]}
    sort_key = "opened_at" if s == "OPEN" else "closed_at"
    return [_jsonable(r) async for r in POSITIONS.find(q).sort(sort_key, -1).limit(limit)]


async def ensure_indexes() -> None:
    """Best effort: an index failure must never stop the books."""
    try:
        await POSITIONS.create_index([("book", 1), ("parent_position_id", 1)], name="gt5_parent_unique", unique=True)
        await POSITIONS.create_index([("book", 1), ("status", 1)], name="gt5_book_status")
        await STATE.create_index([("kind", 1), ("book", 1), ("parent_position_id", 1)], name="gt5_state_kind")
    except Exception:  # noqa: BLE001
        logger.warning("[gold top5] index creation skipped", exc_info=True)
