"""Selling Paper Books - a picked roster from the NIFTY option-SELLING desk, on one account.

The Pre-Live SELLING desk gives every one of its 393 strategies its own Rs 10 lakh margin
account and charges nothing to trade. That answers "did this signal make money". A paper
book answers the question that comes before real money: on ONE account of this size,
paying what a broker charges, what would a hand-picked set of these strategies have done?

"Paper Trading 01" is the first such book: Rs 10,00,000 and the 16 strategies picked off
the desk's leaderboard. More books are one entry in BOOKS.

THE BOOK MIRRORS THE DESK - IT NEVER CALLS THE BROKER
------------------------------------------------------
The desk is a separate daemon (`prelive-service/main_selling.py`) that owns every write to
`prelive_selling_*`. This module only READS those collections: an open structure there is a
position the book may follow, and a trade row with the same `key` and `entry_ts` is its
close. Following the desk's own fills means any difference between desk and book is size,
cost and the three rules below, and nothing else.

Closed trades are read as well as open positions, because most of this roster's real trades
last minutes and the backend only looks every few minutes - a structure that opened and
closed between two looks is still found, from its trade row, and booked at its real prices.
Only entries at or after the book's start are followed; the book never adopts a position the
desk opened before it existed, at a premium that is long gone.

WHAT AN "ANTI-" PICK IS
-----------------------
The desk's leaderboard shows an `ANTI-<name>` row for EVERY strategy: the same trades with
the P&L sign flipped. It is computed when the page is read - no ANTI position has ever been
placed. So a losing strategy always produces a winning ANTI twin, which is why the top of
that leaderboard is full of them.

It can still be traded honestly, and here it is: an ANTI pick BUYS the exact structure the
original SELLS, at the same premium, and sells it back when the original buys it back.
Before costs that is precisely the negated P&L the leaderboard shows. After costs it is
worse, because both sides of a trade pay fees - the leaderboard's ANTI number never paid any.
A long structure ties up its debit, not SPAN margin, so that is what it costs the book.

THREE RULES A REAL ACCOUNT WOULD NEED, EACH RECORDED AS A DECLINED ROW
----------------------------------------------------------------------
1. **No entry on a structure's own expiry day.** On every NIFTY expiry day the desk opens
   structures expiring that same day; its expiry rule closes them seconds later at the price
   they opened at, and the strategy re-opens on the next bar. For this roster that was 879 of
   1,345 trades, 871 of them exactly Rs 0. Mirroring them would change nothing but fees.
2. **One copy of an identical position.** These 16 picks are far fewer ideas than names:
   207 of their 271 distinct trades were taken by two or more of them at once - one call
   spread opened by six "different" strategies in the same minute, 29 times. Holding it six
   times is not diversification, it is six lots on one idea. The first pick to signal holds
   it; the rest are declined with the name of the holder.
3. **Whole lots, and money the account has.** A position is capped at MAX_POSITION_PCT of the
   book, and when margin runs out the signal is declined.

Each rule is a per-book switch, because it is a choice about what the account should do.

FEES
----
Every leg is one buy and one sell over the life of the structure, whichever side it opened
on, so a structure's cost is `option_round_trip` summed over its legs. The flat Rs 20 per
order is exact. The desk records each leg's ENTRY premium but only the structure's net exit
cost, so the premium-based charges (STT, exchange, stamp, SEBI) use each leg's entry premium
for both sides - they are a few rupees against the brokerage on a NIFTY lot.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    db,
    selling_book_equity_collection,
    selling_book_positions_collection,
    selling_book_state_collection,
)
from app.services.angel_fees import option_round_trip
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger("selling_books")

IST = timezone(timedelta(hours=5, minutes=30))

# The desk's own collections. Read-only from here - the daemon owns every write.
PARENT_POSITIONS = db["prelive_selling_positions"]
PARENT_TRADES = db["prelive_selling_trades"]

MAX_POSITION_PCT = float(os.getenv("SELLING_BOOK_MAX_POSITION_PCT", "0.10"))
ENABLED = os.getenv("SELLING_BOOK_ENABLED", "1").lower() not in ("0", "false", "")


@dataclass(frozen=True)
class Pick:
    display: str          # the name as the desk's leaderboard shows it
    base: str             # the strategy that actually trades on the desk
    direction: str        # "SHORT" copies the sale; "LONG" buys the same structure (ANTI)


def _pick(display: str) -> Pick:
    if display.startswith("ANTI-"):
        return Pick(display=display, base=display[len("ANTI-"):], direction="LONG")
    return Pick(display=display, base=display, direction="SHORT")


@dataclass(frozen=True)
class BookSpec:
    key: str
    label: str
    capital: float
    picks: tuple[Pick, ...]
    skip_expiry_day_entries: bool = True
    one_copy_per_structure: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)


BOOKS: dict[str, BookSpec] = {
    "pt01": BookSpec(
        key="pt01",
        label="Paper Trading 01",
        capital=float(os.getenv("SELLING_BOOK_PT01_CAPITAL", "1000000")),
        # In the order the desk's leaderboard ranked them when they were picked.
        picks=tuple(_pick(n) for n in (
            "sell_sw_trend_down_call_spread",
            "mirror_pta_trap",
            "ANTI-sell_sw_narrow_fly",
            "ANTI-sell_sw_low_rv_fly",
            "mirror_sl_trap_trading",
            "sell_sw_three_green_call_spread",
            "ANTI-sell_sw_bb_inside_put_spread",
            "mirror_swing_aroon",
            "mirror_intra_aroon",
            "ANTI-sell_sw_vol_falling_fly",
            "mirror_intra_prev_day_hl",
            "mirror_scalp_prev_day_level",
            "mirror_sl_event_level_trading",
            "ANTI-sell_sw_quiet_open_fly",
            "ANTI-sell_sw_macd_flat_fly",
            "ANTI-sell_sw_three_red_put_spread",
        )),
    ),
}
DEFAULT_BOOK = "pt01"


def normalize_book(book: str | None) -> str:
    return book if book in BOOKS else DEFAULT_BOOK


def position_cap(spec: BookSpec) -> float:
    return spec.capital * MAX_POSITION_PCT


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(v) -> datetime | None:
    """The daemon writes ISO strings with a +05:30 offset; compare them as instants."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v))
        return d if d.tzinfo else d.replace(tzinfo=IST)
    except (TypeError, ValueError):
        return None


def _structure_fees(legs: list[dict], lots: int, lot_size: int) -> float:
    total = 0.0
    for leg in legs or []:
        p = max(float(leg.get("entry_premium") or 0.0), 0.05)
        total += option_round_trip(p, p, lots, lot_size).total
    return round(total, 2)


def _lot_size(parent: dict) -> int:
    lots = int(parent.get("lots") or 1)
    qty = int(parent.get("qty") or 0)
    return qty // lots if lots > 0 and qty > 0 else 0


def _capital_per_lot(parent: dict, direction: str) -> float:
    """What one lot of this structure ties up in the book.

    SHORT: the desk's SPAN/defined-risk margin, per lot. LONG: the debit paid - a bought
    structure can lose its premium and nothing more, so the premium is all it reserves."""
    lots = int(parent.get("lots") or 1) or 1
    if direction == "SHORT":
        return float(parent.get("margin") or 0.0) / lots
    return float(parent.get("credit") or 0.0) * _lot_size(parent)


def _pnl(direction: str, credit: float, exit_cost: float, qty: int) -> float:
    per_unit = (credit - exit_cost) if direction == "SHORT" else (exit_cost - credit)
    return per_unit * qty


# -- book state ------------------------------------------------------------------


async def _started_at(spec: BookSpec) -> datetime:
    """When the book began following the desk. Set once, on the first run."""
    st = await selling_book_state_collection.find_one({"_id": spec.key})
    if st and st.get("started_at"):
        return _ts(st["started_at"])
    now = _now()
    await selling_book_state_collection.update_one(
        {"_id": spec.key}, {"$set": {"started_at": now}}, upsert=True)
    return now


async def _cash(spec: BookSpec) -> float:
    deployed = realized = 0.0
    async for p in selling_book_positions_collection.find(
            {"book": spec.key, "status": {"$in": ["OPEN", "CLOSED"]}},
            {"status": 1, "capital": 1, "realized_pnl": 1}):
        if p["status"] == "OPEN":
            deployed += p.get("capital") or 0.0
        else:
            realized += p.get("realized_pnl") or 0.0
    return spec.capital + realized - deployed


# -- following the desk ------------------------------------------------------------


def _base_row(spec: BookSpec, pick: Pick, parent: dict) -> dict:
    return {
        "book": spec.key, "pick": pick.display, "base_strategy_id": pick.base,
        "direction": pick.direction,
        "parent_key": parent.get("key"), "parent_entry_ts": str(parent.get("entry_ts")),
        "timeframe": parent.get("timeframe"),
        "structure": parent.get("structure"), "legs": parent.get("legs") or [],
        "expiry": parent.get("expiry"), "credit": float(parent.get("credit") or 0.0),
        "entry_spot": parent.get("entry_spot"),
        "opened_at": _ts(parent.get("entry_ts")), "updated_at": _now(),
    }


async def _decline(spec: BookSpec, pick: Pick, parent: dict, reason: str) -> None:
    try:
        await _insert_decline(spec, pick, parent, reason)
    except DuplicateKeyError:
        pass                        # a concurrent run recorded this same decision first


async def _insert_decline(spec: BookSpec, pick: Pick, parent: dict, reason: str) -> None:
    await selling_book_positions_collection.insert_one({
        **_base_row(spec, pick, parent), "position_id": uuid4().hex[:12],
        "status": "DECLINED", "decline_reason": reason,
        "lots": 0, "lot_size": _lot_size(parent), "qty": 0, "capital": 0.0,
        "mark": None, "unrealized_pnl": 0.0, "realized_pnl": None,
        "gross_pnl": None, "fees": None, "exit_cost": None, "exit_reason": None,
        "closed_at": None,
    })


async def _try_open(spec: BookSpec, pick: Pick, parent: dict, cash: float) -> float:
    """Follow one entry of the desk, or decline it and say why. Returns capital used."""
    expiry = str(parent.get("expiry") or "")[:10]
    entered = _ts(parent.get("entry_ts"))
    entry_day = entered.astimezone(IST).date().isoformat() if entered else ""

    if spec.skip_expiry_day_entries and expiry and expiry == entry_day:
        await _decline(spec, pick, parent, (
            f"Opened on its own expiry day ({expiry}). The desk's expiry rule closes these "
            "within seconds at the price they opened at, so the only thing that would change "
            "hands is fees."))
        return 0.0

    if spec.one_copy_per_structure:
        # "Held at the moment this entry happened", not "open right now": a twin that opened
        # and closed between two of our looks is booked open-then-closed in one go, so by the
        # time its twins seconds later are processed it is already CLOSED - and an OPEN-only
        # check would wave every one of them through.
        twin = await selling_book_positions_collection.find_one({
            "book": spec.key, "status": {"$in": ["OPEN", "CLOSED"]},
            "direction": pick.direction,
            "structure": parent.get("structure"), "expiry": parent.get("expiry"),
            "opened_at": {"$lte": entered},
            "$or": [{"closed_at": None}, {"closed_at": {"$gt": entered}}]})
        if twin:
            await _decline(spec, pick, parent, (
                f"Identical position held at that moment via {twin['pick']} - the same "
                f"{parent.get('structure')} expiring {expiry}. A second copy would be a "
                "second lot on the same idea, not a second strategy."))
            return 0.0

    per_lot = _capital_per_lot(parent, pick.direction)
    lot_size = _lot_size(parent)
    parent_lots = int(parent.get("lots") or 1)
    budget = min(position_cap(spec), max(cash, 0.0))
    lots = min(parent_lots, int(budget // per_lot)) if per_lot > 0 else 0
    if lots < 1 or lot_size < 1:
        what = "margin" if pick.direction == "SHORT" else "debit"
        reason = (f"Needs ₹{per_lot:,.0f} of {what} per lot"
                  + (f", above the ₹{position_cap(spec):,.0f} per-position cap"
                     if per_lot > position_cap(spec)
                     else f", and only ₹{max(cash, 0):,.0f} is free in the book"))
        await _decline(spec, pick, parent, reason)
        return 0.0

    qty = lots * lot_size
    capital = round(per_lot * lots, 2)
    try:
        await _insert_open(spec, pick, parent, lots, lot_size, qty, parent_lots, capital)
    except DuplicateKeyError:
        # The scheduler and a manual Run can overlap. The unique index makes the second one
        # lose cleanly instead of holding the same fill twice; it spent nothing.
        return 0.0
    return capital


async def _insert_open(spec: BookSpec, pick: Pick, parent: dict, lots: int, lot_size: int,
                       qty: int, parent_lots: int, capital: float) -> None:
    await selling_book_positions_collection.insert_one({
        **_base_row(spec, pick, parent), "position_id": uuid4().hex[:12],
        "status": "OPEN", "decline_reason": None,
        "lots": lots, "lot_size": lot_size, "qty": qty, "parent_lots": parent_lots,
        "capital": capital,
        "mark": parent.get("mark"), "unrealized_pnl": 0.0, "realized_pnl": None,
        "gross_pnl": None, "fees": None, "exit_cost": None, "exit_reason": None,
        "closed_at": None,
    })


async def _close(pos: dict, trade: dict) -> float:
    exit_cost = float(trade.get("exit_cost") or 0.0)
    gross = _pnl(pos["direction"], pos["credit"], exit_cost, pos["qty"])
    fees = _structure_fees(pos.get("legs") or [], pos["lots"], pos["lot_size"])
    net = round(gross - fees, 2)
    await selling_book_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "status": "CLOSED", "exit_cost": round(exit_cost, 2),
        "exit_reason": trade.get("exit_reason"), "exit_spot": trade.get("exit_spot"),
        "gross_pnl": round(gross, 2), "fees": fees, "realized_pnl": net,
        "unrealized_pnl": 0.0, "mark": round(exit_cost, 2),
        "closed_at": _ts(trade.get("exit_ts")) or _now(), "updated_at": _now()}})
    return net


async def run_cycle() -> dict:
    """Follow the desk once for every book: close, mark, then take new entries in order."""
    if not ENABLED:
        return {"opened": 0, "closed": 0, "declined": 0, "notes": ["books disabled"]}

    opened = closed = declined = 0
    for spec in BOOKS.values():
        started = await _started_at(spec)
        bases = sorted({p.base for p in spec.picks})

        open_parents = {}
        async for p in PARENT_POSITIONS.find({"strategy_id": {"$in": bases}}):
            open_parents[(p.get("key"), str(p.get("entry_ts")))] = p
        closed_parents = {}
        # The daemon writes entry_ts as an ISO string with a fixed +05:30 offset, so a string
        # bound in the same form lets Mongo skip the history the book will never read. The
        # instant comparison below stays as the real test.
        since = started.astimezone(IST).isoformat()
        async for t in PARENT_TRADES.find({"strategy_id": {"$in": bases},
                                           "entry_ts": {"$gte": since}}):
            et = _ts(t.get("entry_ts"))
            if et and et >= started:
                closed_parents[(t.get("key"), str(t.get("entry_ts")))] = t

        # 1) close what the desk closed; mark what it still holds.
        async for pos in selling_book_positions_collection.find(
                {"book": spec.key, "status": "OPEN"}):
            ref = (pos.get("parent_key"), pos.get("parent_entry_ts"))
            if ref in closed_parents:
                await _close(pos, closed_parents[ref])
                closed += 1
            elif ref in open_parents and open_parents[ref].get("mark") is not None:
                mark = float(open_parents[ref]["mark"])
                unreal = _pnl(pos["direction"], pos["credit"], mark, pos["qty"])
                await selling_book_positions_collection.update_one(
                    {"_id": pos["_id"]},
                    {"$set": {"mark": round(mark, 2), "unrealized_pnl": round(unreal, 2),
                              "updated_at": _now()}})

        # 2) new entries since the book started, oldest first, so the book spends its money
        #    in the order the signals actually came - including ones that already closed.
        events = []
        for ref, p in open_parents.items():
            et = _ts(p.get("entry_ts"))
            if et and et >= started:
                events.append((et, p, None))
        for ref, t in closed_parents.items():
            if ref not in open_parents:
                events.append((_ts(t.get("entry_ts")), t, t))
        events.sort(key=lambda e: e[0])

        cash = await _cash(spec)
        for _, parent, trade in events:
            for pick in spec.picks:
                if pick.base != parent.get("strategy_id"):
                    continue
                seen = await selling_book_positions_collection.find_one({
                    "book": spec.key, "pick": pick.display,
                    "parent_key": parent.get("key"),
                    "parent_entry_ts": str(parent.get("entry_ts"))})
                if seen:
                    continue
                used = await _try_open(spec, pick, parent, cash)
                if used <= 0:
                    declined += 1
                    continue
                cash -= used
                opened += 1
                if trade is not None:
                    # It opened and closed between two looks: book the close now, at the
                    # desk's real exit, and hand the money straight back.
                    row = await selling_book_positions_collection.find_one({
                        "book": spec.key, "pick": pick.display,
                        "parent_key": parent.get("key"),
                        "parent_entry_ts": str(parent.get("entry_ts")), "status": "OPEN"})
                    if row:
                        net = await _close(row, trade)
                        cash += used + net
                        closed += 1

        s = await summary(spec.key)
        await selling_book_equity_collection.insert_one({
            "book": spec.key, "ts": _now(), "equity": s["equity"],
            "realized": s["realized_pnl"], "unrealized": s["unrealized_pnl"],
            "deployed": s["deployed"], "open_positions": s["open_positions"]})
        await selling_book_state_collection.update_one(
            {"_id": spec.key},
            {"$set": {"last_run_at": _now(), "last_opened": opened,
                      "last_closed": closed, "last_declined": declined}},
            upsert=True)

    return {"opened": opened, "closed": closed, "declined": declined, "notes": []}


# -- read models -----------------------------------------------------------------


async def summary(book: str = DEFAULT_BOOK) -> dict:
    spec = BOOKS[normalize_book(book)]
    realized = unrealized = deployed = gross = fees = 0.0
    n_open = n_closed = n_declined = 0
    declined_by_reason = {"expiry_day": 0, "duplicate": 0, "money": 0}
    async for p in selling_book_positions_collection.find({"book": spec.key}):
        st = p.get("status")
        if st == "OPEN":
            n_open += 1
            deployed += p.get("capital") or 0.0
            unrealized += p.get("unrealized_pnl") or 0.0
        elif st == "CLOSED":
            n_closed += 1
            realized += p.get("realized_pnl") or 0.0
            gross += p.get("gross_pnl") or 0.0
            fees += p.get("fees") or 0.0
        elif st == "DECLINED":
            n_declined += 1
            r = p.get("decline_reason") or ""
            key = ("expiry_day" if r.startswith("Opened on its own expiry day")
                   else "duplicate" if r.startswith("Identical position")
                   else "money")
            declined_by_reason[key] += 1
    st = await selling_book_state_collection.find_one({"_id": spec.key}) or {}
    return {
        "book": spec.key, "books": list(BOOKS),
        "book_labels": {k: v.label for k, v in BOOKS.items()},
        "label": spec.label, "mode": "PAPER", "enabled": ENABLED,
        "capital": spec.capital, "position_cap": round(position_cap(spec), 2),
        "cash": round(spec.capital + realized - deployed, 2),
        "deployed": round(deployed, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "gross_pnl": round(gross, 2), "fees": round(fees, 2),
        "equity": round(spec.capital + realized + unrealized, 2),
        "roi_pct": round((realized + unrealized) / spec.capital * 100, 2) if spec.capital else 0.0,
        "open_positions": n_open, "closed_positions": n_closed, "declined": n_declined,
        "declined_by_reason": declined_by_reason,
        "rules": {"skip_expiry_day_entries": spec.skip_expiry_day_entries,
                  "one_copy_per_structure": spec.one_copy_per_structure},
        "started_at": st.get("started_at"), "last_run_at": st.get("last_run_at"),
        "roster": [{"pick": p.display, "base_strategy_id": p.base, "direction": p.direction}
                   for p in spec.picks],
    }


async def leaderboard(book: str = DEFAULT_BOOK) -> list[dict]:
    """One row per pick, built from the book's own rows - including picks that never traded,
    because 'held nothing, declined as a duplicate every time' is itself the finding."""
    spec = BOOKS[normalize_book(book)]
    rows = {p.display: {"pick": p.display, "base_strategy_id": p.base,
                        "direction": p.direction, "trades": 0, "wins": 0,
                        "gross_pnl": 0.0, "fees": 0.0, "net_pnl": 0.0,
                        "gross_win": 0.0, "gross_loss": 0.0, "open": 0,
                        "unrealized_pnl": 0.0,
                        "declined_expiry_day": 0, "declined_duplicate": 0,
                        "declined_money": 0}
            for p in spec.picks}
    async for p in selling_book_positions_collection.find({"book": spec.key}):
        r = rows.get(p.get("pick"))
        if r is None:
            continue
        st = p.get("status")
        if st == "CLOSED":
            net = p.get("realized_pnl") or 0.0
            r["trades"] += 1
            r["wins"] += 1 if net > 0 else 0
            r["gross_pnl"] += p.get("gross_pnl") or 0.0
            r["fees"] += p.get("fees") or 0.0
            r["net_pnl"] += net
            if net > 0:
                r["gross_win"] += net
            elif net < 0:
                r["gross_loss"] += -net
        elif st == "OPEN":
            r["open"] += 1
            r["unrealized_pnl"] += p.get("unrealized_pnl") or 0.0
        elif st == "DECLINED":
            reason = p.get("decline_reason") or ""
            if reason.startswith("Opened on its own expiry day"):
                r["declined_expiry_day"] += 1
            elif reason.startswith("Identical position"):
                r["declined_duplicate"] += 1
            else:
                r["declined_money"] += 1
    out = []
    for r in rows.values():
        n = r["trades"]
        r["win_rate"] = round(r["wins"] / n, 4) if n else None
        r["profit_factor"] = round(r["gross_win"] / r["gross_loss"], 3) if r["gross_loss"] > 0 else None
        for k in ("gross_pnl", "fees", "net_pnl", "unrealized_pnl"):
            r[k] = round(r[k], 2)
        r.pop("gross_win")
        r.pop("gross_loss")
        out.append(r)
    out.sort(key=lambda r: -(r["net_pnl"] + r["unrealized_pnl"]))
    return out


async def positions(book: str = DEFAULT_BOOK, status: str = "OPEN",
                    limit: int = 400) -> list[dict]:
    spec = BOOKS[normalize_book(book)]
    q: dict = {"book": spec.key}
    if status and status.upper() != "ALL":
        q["status"] = status.upper()
    sort_field = "closed_at" if (status or "").upper() == "CLOSED" else "opened_at"
    out = []
    async for p in selling_book_positions_collection.find(q).sort(sort_field, -1).limit(limit):
        p.pop("_id", None)
        out.append(p)
    return out


async def ensure_indexes() -> None:
    await selling_book_positions_collection.create_index(
        [("book", 1), ("pick", 1), ("parent_key", 1), ("parent_entry_ts", 1)],
        unique=True, name="selling_book_mirror_once")
    await selling_book_positions_collection.create_index([("book", 1), ("status", 1)])
