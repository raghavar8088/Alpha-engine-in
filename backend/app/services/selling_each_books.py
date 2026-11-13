"""Index Option Selling: two paper accounts with Rs 10 lakh for EACH strategy (13 Nov 2026).

The owner asked (screenshots of the two Rank boards on /prelive-selling, 12 Nov 2026 near midnight IST) for paper
trading accounts on this module with Rs 10 lakh per strategy:

    sf10    Top 10 of the 546    the top 10 of the "Strategy Factory · 546" tab's Rank: the Factory's own signals
                                 traded as NIFTY credit spreads (app.services.factory_desks, tab "index-selling")
    desk10  Top 10 of the desk   the top 10 of the desk's own "Strategy leaderboard" Rank: the selling daemon's
                                 strategies (prelive-service/main_selling.py)

WHAT AN ACCOUNT IS
- Ten strategies, each with its OWN Rs 10,00,000 (Rs 1 crore an account). One strategy's losses never touch another's
  money. Its profit stays in its own account: a position is sized on that strategy's equity when it opens (Rs 10 lakh
  plus its own realised P&L), so a winner's next position can grow and a loser's shrinks.
- One structure at a time for each strategy, as on both desks.

SIZE
- Whole lots. A position may tie up at most POSITION_SHARE (a fifth) of the strategy's equity in margin - Rs 2 lakh to
  start, the rule of every Top-10 book - and never more than MAX_LOTS (10), the selling desk's own cap on one structure
  (its PRELIVE_SELLING_MAX_LOTS: bigger orders eat through the quoted depth and worsen their own fill).
- Margin per lot is the parent's own: the desk's estimated margin for the structure, and on the Factory tab the
  spread's maximum loss, which is that tab's margin. Both trade defined-risk structures, so the margin is close to what
  a position can lose. A signal whose one lot needs more than the limit is skipped and counted.
- Both parents trade ONE lot, so a copy is usually 8 to 10 times its parent.

PRICES AND COSTS
- A copy opens when its parent opens, at the parent's entry credit, and closes when the parent closes, at the parent's
  exit: a copy differs from its parent only in size and charges. The parents price one lot off the quotes; the extra
  depth 8 to 10 lots would take is NOT modelled.
- Charges: Angel One's option rate card on every leg at the account's own lots (app.services.angel_fees). Factory
  copies are charged on each leg's real entry and exit premium. The desk records each leg's entry premium but only the
  structure's net exit cost, so desk copies charge each leg's entry premium for both sides, as the desk's Paper Trading
  books do; the flat Rs 20 an order is most of it either way.
- Open copies are marked at the parent's own mark (gross: before the exit's charges).

RULES - every entry not copied is recorded with its reason and counted, never dropped silently
- expiry_day (desk only): an entry opened on its own expiry day is skipped, the rule of the desk's Paper Trading books.
  The daemon still churns them: from 20 Oct to 12 Nov the ten's 192 entries on their own expiry day (27 Oct, 3 Nov,
  9 Nov) were each closed by its expiry rule within 2 minutes (median 15 s) at the price they opened at - P&L exactly
  0. Copied at 8-10 lots they would only pay charges. Factory copies take same-day expiries: on that tab the ten's 20
  such trades were real (held from 10 minutes to the 15:15 square-off, median 3.7 hours).
- held: the strategy already holds a copy at that moment (its parent holds one at a time, so this is a guard).
- margin: one lot needs more margin than the strategy may put on a position.
- off: Main Control's `selling_books` switch (the desk's Paper Trading books) was OFF when the entry was seen, so it is
  never copied late. Open copies are still closed when their parents close.
- data: the parent's record has no size, margin or credit to copy.
- A desk copy whose parent vanished without a trade row is voided (no P&L, its margin back) once that strategy opens
  its next structure: the desk holds one at a time, so the old one is gone.

STARTS on each account's first cycle and never back-fills: a position a parent already held then is not copied.

THE TWENTY ARE FROZEN as ranked when picked (PICKED_AT: the owner's screenshots; /api/strategy-rank returned the same
twenty, two tied pairs in the other order). They are not re-picked as ranks move. Two pairs have identical records -
SF0330 / SF0474, and mirror_nj_daily_bias / mirror_bb_daily_bias - so each pair takes the same trades, each with its
own money. None is validated: the Factory ten had 6 to 15 closed trades each, and a Rank under 30 trades is pulled
toward the middle. These accounts are the out-of-sample test of whether they keep leading.

Paper only: nothing here places an order or asks the broker for a price.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.core.db import db
from app.services.book_reset import naive_utc

logger = logging.getLogger("selling_each_books")

IST = timezone(timedelta(hours=5, minutes=30))
POSITIONS = db["selling_each_positions"]
STATE = db["selling_each_state"]
DESK_POSITIONS = db["prelive_selling_positions"]      # the selling daemon's own records: read, never written
DESK_TRADES = db["prelive_selling_trades"]
FACTORY_TAB = "index-selling"                         # factory_desks' tab of this module: read, never written

PER_STRATEGY = float(os.getenv("SELLING_EACH_PER_STRATEGY", "1000000"))     # Rs 10 lakh each
POSITION_SHARE = float(os.getenv("SELLING_EACH_POSITION_SHARE", "0.20"))    # a fifth of the strategy's equity
MAX_LOTS = int(os.getenv("SELLING_EACH_MAX_LOTS", "10"))                     # the selling desk's cap on one structure
ENABLED = os.getenv("SELLING_EACH_BOOKS", "1").lower() not in ("0", "false", "")
SWITCH = "selling_books"
PICKED_AT = "2026-11-12T23:40:00+05:30"
SKIP_REASONS = ("expiry_day", "held", "margin", "off", "data")


@dataclass(frozen=True)
class Pick:
    strategy_id: str
    rank: int            # on its board when picked
    score: float
    trades: int          # closed trades on its board then (1 lot)
    net_pnl: float       # its board's net P&L then (1 lot)
    name: str


@dataclass(frozen=True)
class Account:
    key: str
    label: str
    source: str          # "factory" | "desk"
    board: str
    instrument: str
    picks: tuple[Pick, ...]
    skip_expiry_day: bool
    notes: tuple[str, ...] = field(default_factory=tuple)


def _picks(rows) -> tuple[Pick, ...]:
    return tuple(Pick(*r) for r in rows)


ACCOUNTS: dict[str, Account] = {
    "sf10": Account(
        key="sf10", label="Top 10 of the 546 · ₹10 lakh each", source="factory",
        board="the Strategy Factory · 546 tab's Rank (146 strategies with closed trades)",
        instrument=("NIFTY credit spreads as the Strategy Factory · 546 tab trades them: a BUY signal sells an ATM put "
                    "spread, a SELL signal an ATM call spread, 200-point wing, the nearest listed weekly"),
        picks=_picks([
            ("SF0330", 1, 60.6, 8, 13970.82, "Trend Pullback to EMA · 30m"),
            ("SF0474", 2, 60.6, 8, 13970.82, "Pullback + EMA + RSI + VWAP · 30m"),
            ("SF0400", 3, 60.2, 15, 12107.60, "MACD Histogram Turn · 5m"),
            ("SF0229", 4, 58.1, 6, 14029.03, "Keltner Breakout · 45m"),
            ("SF0401", 5, 58.1, 8, 12997.62, "MACD Histogram Turn · 15m"),
            ("SF0107", 6, 58.0, 8, 10543.76, "Engulfing Candle · 15m"),
            ("SF0392", 7, 57.2, 9, 12569.89, "MACD Signal Cross · 5m"),
            ("SF0113", 8, 56.9, 9, 5924.52, "Hammer / Shooting Star · 1m"),
            ("SF0329", 9, 56.3, 11, 14369.16, "Trend Pullback to EMA · 15m"),
            ("SF0179", 10, 56.2, 11, 11936.60, "Three Soldiers / Crows · 15m"),
        ]),
        skip_expiry_day=False,
        notes=(
            "Ranks 1 and 2 (SF0330, SF0474) have identical records on the tab: they take the same trades, each with "
            "its own money.",
            "Each of the ten had 6 to 15 closed trades when picked, and the Rank pulls a record under 30 trades toward "
            "the middle.",
        ),
    ),
    "desk10": Account(
        key="desk10", label="Top 10 of the desk · ₹10 lakh each", source="desk",
        board="the desk's Strategy leaderboard Rank (363 strategies with closed trades)",
        instrument="the desk's own NIFTY structures (defined-risk spreads and flies), as the selling daemon trades them",
        picks=_picks([
            ("sell_pos_low_rv_fly", 1, 87.6, 32, 50415.0, "sell_pos_low_rv_fly"),
            ("mirror_intra_morning_momentum", 2, 87.3, 71, 19256.0, "mirror_intra_morning_momentum"),
            ("mirror_mr_event_volatility", 3, 87.0, 316, 39053.0, "mirror_mr_event_volatility"),
            ("mirror_swing_pullback_sma50", 4, 87.0, 49, 19804.0, "mirror_swing_pullback_sma50"),
            ("mirror_ema_200_trend", 5, 85.6, 90, 22643.0, "mirror_ema_200_trend"),
            ("sell_range_low_bull_put", 6, 85.6, 50, 10729.0, "sell_range_low_bull_put"),
            ("mirror_pta_breakout_direction", 7, 84.0, 90, 11059.0, "mirror_pta_breakout_direction"),
            ("mirror_nj_daily_bias", 8, 83.8, 161, 30173.0, "mirror_nj_daily_bias"),
            ("mirror_bb_daily_bias", 9, 83.8, 161, 30173.0, "mirror_bb_daily_bias"),
            ("mirror_raschke_holy_grail", 10, 83.7, 143, 20816.0, "mirror_raschke_holy_grail"),
        ]),
        skip_expiry_day=True,
        notes=(
            "Ranks 8 and 9 (mirror_nj_daily_bias, mirror_bb_daily_bias) have identical records on the desk: they take "
            "the same trades, each with its own money.",
            "The desk's board counts its expiry-day churn as trades: 192 of the ten's 345 trades from 20 Oct to 12 Nov "
            "were opened on their own expiry day and closed by the daemon within 2 minutes at the price they opened at "
            "(P&L exactly ₹0). This account skips those, so its trade counts will be lower than the board's, and the "
            "board's win rates understate these strategies' real ones.",
        ),
    ),
}
DEFAULT_ACCOUNT = "sf10"


def normalize_account(account: str | None) -> str:
    return account if account in ACCOUNTS else DEFAULT_ACCOUNT


# -- the parents ------------------------------------------------------------------------------------------------------


@dataclass
class Parent:
    """One parent position, in one shape for both desks. Prices are per unit; times naive UTC."""
    ref: str                       # the parent's own id: a factory position_id, or the desk's "<key>|<entry_ts>"
    strategy_id: str
    opened_at: datetime
    lots: int
    lot_size: int
    credit: float                  # the structure's net entry credit
    margin_per_lot: float
    structure: str
    expiry: str
    timeframe: str | None
    legs: list[dict]               # {"label", "side": SELL | BUY, "entry"}
    state: str                     # OPEN | CLOSED | VOID
    closed_at: datetime | None = None
    exit_cost: float | None = None           # what buying the structure back cost
    exit_legs: list[float] | None = None     # each leg's exit premium, where the parent records them
    exit_reason: str | None = None
    mark: float | None = None                # what buying it back would cost now (open parents)
    entry_spot: float | None = None
    exit_spot: float | None = None


def _ts(v) -> datetime | None:
    """Naive UTC from a datetime or the daemon's ISO strings (written +05:30; a bare one is IST)."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return naive_utc(v)
    try:
        d = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return naive_utc(d if d.tzinfo else d.replace(tzinfo=IST))


def _ist_date(t: datetime) -> date:
    return t.replace(tzinfo=timezone.utc).astimezone(IST).date()


def _num(v) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _desk_legs(legs) -> list[dict]:
    out = []
    for leg in legs or []:
        strike = _num(leg.get("strike"))
        label = f"{int(strike)}{leg.get('option_type') or ''}" if strike else str(leg.get("symbol") or "")
        out.append({"label": label, "side": "SELL" if leg.get("sold") else "BUY",
                    "entry": round(float(leg.get("entry_premium") or 0.0), 2)})
    return out


def desk_parent(doc: dict, closed: bool) -> Parent | None:
    """A selling-daemon structure: an open position (`prelive_selling_positions`) or a closed trade
    (`prelive_selling_trades`). The two share `key` + `entry_ts`, which is how a close finds its open."""
    opened = _ts(doc.get("entry_ts"))
    if opened is None:
        return None
    lots = int(doc.get("lots") or 0)
    qty = int(doc.get("qty") or 0)
    state = "OPEN"
    exit_cost = None
    if closed:
        exit_cost = _num(doc.get("exit_cost"))
        state = "CLOSED" if exit_cost is not None else "VOID"
    return Parent(
        ref=f"{doc.get('key')}|{doc.get('entry_ts')}", strategy_id=str(doc.get("strategy_id") or ""),
        opened_at=opened, lots=lots, lot_size=qty // lots if lots > 0 and qty > 0 else 0,
        credit=float(doc.get("credit") or 0.0),
        margin_per_lot=float(doc.get("margin") or 0.0) / lots if lots > 0 else 0.0,
        structure=str(doc.get("structure") or ""), expiry=str(doc.get("expiry") or "")[:10],
        timeframe=doc.get("timeframe"), legs=_desk_legs(doc.get("legs")), state=state,
        closed_at=_ts(doc.get("exit_ts")) if closed else None, exit_cost=exit_cost,
        exit_reason=doc.get("exit_reason") if closed else None,
        mark=None if closed else _num(doc.get("mark")),
        entry_spot=_num(doc.get("entry_spot")), exit_spot=_num(doc.get("exit_spot")) if closed else None)


def _signed(legs: list[dict], prices) -> float:
    """Cost of buying a structure back at these per-leg prices: its short legs bought, its long legs sold."""
    return round(sum(float(x) * (1 if leg["side"] == "SELL" else -1) for leg, x in zip(legs, prices)), 4)


def factory_parent(doc: dict) -> Parent | None:
    """A row of the Strategy Factory · 546 tab (factory_desk_positions, desk "index-selling"): a short leg sold at
    the bid and its wing bought at the ask, `capital_deployed` = the spread's maximum loss for its lots."""
    raw = doc.get("legs") or []
    opened = _ts(doc.get("opened_at"))
    if opened is None or not raw:
        return None
    legs = [{"label": f"{int(float(leg.get('strike') or 0))}{leg.get('option_type') or ''}",
             "side": "SELL" if leg.get("side") == "SELL" else "BUY",
             "entry": round(float(leg.get("entry") or 0.0), 2)} for leg in raw]
    lots = int(doc.get("lots") or 0)
    status = str(doc.get("status") or "")
    state = "OPEN" if status == "OPEN" else "CLOSED" if status == "CLOSED" else "VOID"
    exits = doc.get("exit_legs")
    if state == "CLOSED" and (not exits or len(exits) != len(legs)):
        state = "VOID"
    marks = doc.get("mark_legs")
    return Parent(
        ref=str(doc.get("position_id") or ""), strategy_id=str(doc.get("strategy_id") or ""), opened_at=opened,
        lots=lots, lot_size=int(doc.get("lot_size") or 0), credit=float(doc.get("credit") or 0.0),
        margin_per_lot=float(doc.get("capital_deployed") or 0.0) / lots if lots > 0 else 0.0,
        structure=" / ".join(f"{leg['side']} {leg['label']}" for leg in legs),
        expiry=str(raw[0].get("expiry") or "")[:10], timeframe=doc.get("timeframe"), legs=legs, state=state,
        closed_at=_ts(doc.get("closed_at")) if state != "OPEN" else None,
        exit_cost=_signed(legs, exits) if state == "CLOSED" else None,
        exit_legs=[float(x) for x in exits] if state == "CLOSED" else None,
        exit_reason=doc.get("exit_reason") if state != "OPEN" else None,
        mark=_signed(legs, marks) if state == "OPEN" and marks and len(marks) == len(legs) else None,
        entry_spot=_num(doc.get("under_entry")))


async def _desk_parents(acc: Account, start: datetime) -> list[Parent]:
    ids = [p.strategy_id for p in acc.picks]
    out: dict[str, Parent] = {}
    async for d in DESK_POSITIONS.find({"strategy_id": {"$in": ids}}):
        p = desk_parent(d, closed=False)
        if p and p.opened_at >= start:
            out[p.ref] = p
    # The daemon writes entry_ts as an ISO string with a fixed +05:30 offset, so a string bound in that form lets Mongo
    # skip history (a minute early, for format slack); the instant comparison is the real test.
    since = (start - timedelta(minutes=1)).replace(tzinfo=timezone.utc).astimezone(IST).isoformat()
    async for t in DESK_TRADES.find({"strategy_id": {"$in": ids}, "entry_ts": {"$gte": since}}):
        p = desk_parent(t, closed=True)
        if p and p.opened_at >= start:
            out[p.ref] = p                 # the closed record wins over a not-yet-removed open one
    return list(out.values())


async def _factory_parents(acc: Account, start: datetime) -> list[Parent]:
    from app.services import factory_desks as fdk
    ids = [p.strategy_id for p in acc.picks]
    out = []
    async for d in fdk.POSITIONS.find({"desk": FACTORY_TAB, "strategy_id": {"$in": ids}, "opened_at": {"$gte": start}}):
        p = factory_parent(d)
        if p and p.opened_at >= start:
            out.append(p)
    return out


# -- the plan: pure, so it can be tested without a database ------------------------------------------------------------


def leg_fees(legs: list[dict], lots: int, lot_size: int, exit_legs: list[float] | None, on: date) -> float:
    """Angel One's option card on every leg at the account's lots: each leg's opening side and its close. The card
    is written buy-then-sell, so a short leg passes its buy-back as the buy (floored at a tick, so a leg bought back
    for nothing is still charged) and its sale as the sell. No per-leg exits (the desk): each leg's entry premium."""
    from app.services.angel_fees import option_round_trip
    total = 0.0
    for i, leg in enumerate(legs):
        entry = max(float(leg.get("entry") or 0.0), 0.05)
        x = float(exit_legs[i]) if exit_legs else entry
        if leg.get("side") == "BUY":
            total += option_round_trip(entry, max(x, 0.0), lots, lot_size, on=on).total
        else:
            total += option_round_trip(max(x, 0.05), entry, lots, lot_size, on=on).total
    return round(total, 2)


def ledger(copies: list[dict], t: datetime) -> tuple[float, float, bool]:
    """A strategy's realised P&L before `t`, the margin its copies tie up at `t`, and whether it holds one then."""
    realized = deployed = 0.0
    held = False
    for r in copies:
        st = r.get("status")
        if st not in ("OPEN", "CLOSED"):
            continue
        o, c = r.get("opened_at"), r.get("closed_at")
        if st == "CLOSED" and c is not None and c <= t:
            realized += float(r.get("realized_pnl") or 0.0)
        elif o is not None and o <= t and (c is None or c > t):
            deployed += float(r.get("capital_deployed") or 0.0)
            held = True
    return realized, deployed, held


def size(margin_per_lot: float, equity: float, deployed: float) -> tuple[int, float]:
    """Whole lots for a new position: at most a fifth of the strategy's equity in margin (never more than its free
    cash), and never more than MAX_LOTS. Returns (lots, the margin the position may use)."""
    limit = max(min(equity * POSITION_SHARE, equity - deployed), 0.0)
    if margin_per_lot <= 0:
        return 0, limit
    return min(MAX_LOTS, int(limit // margin_per_lot)), limit


def _void(row: dict, now: datetime, why: str) -> tuple[str, dict]:
    upd = {"status": "VOID", "void_reason": why, "unrealized_pnl": 0.0, "realized_pnl": 0.0, "gross_pnl": 0.0,
           "fees": 0.0, "closed_at": now, "updated_at": now}
    row.update(upd)
    return "update", {"position_id": row["position_id"], "set": upd}


def _settle(row: dict, p: Parent, now: datetime) -> tuple[str, dict] | None:
    """Bring an OPEN copy up to its parent: mark it, close it at the parent's exit, or void it."""
    if p.state == "OPEN":
        if p.mark is None or row.get("mark") == round(p.mark, 2):
            return None
        upd = {"mark": round(p.mark, 2), "unrealized_pnl": round((row["credit"] - p.mark) * row["qty"], 2),
               "updated_at": now}
        row.update(upd)
        return "update", {"position_id": row["position_id"], "set": upd}
    if p.state == "VOID":
        return _void(row, now, "the parent's record has no exit price")
    closed_at = p.closed_at or now
    gross = round((row["credit"] - p.exit_cost) * row["qty"], 2)
    fees = leg_fees(row["legs"], row["lots"], row["lot_size"], p.exit_legs, _ist_date(closed_at))
    upd = {"status": "CLOSED", "exit_cost": round(p.exit_cost, 2), "exit_legs": p.exit_legs,
           "exit_reason": p.exit_reason, "exit_spot": p.exit_spot, "gross_pnl": gross, "fees": fees,
           "realized_pnl": round(gross - fees, 2), "unrealized_pnl": 0.0, "mark": round(p.exit_cost, 2),
           "closed_at": closed_at, "updated_at": now}
    row.update(upd)
    return "update", {"position_id": row["position_id"], "set": upd}


def _decide(acc: Account, pick: Pick, p: Parent, copies: list[dict], entries: bool, now: datetime) -> dict:
    """A new entry of the parent's: the copy it gets (OPEN), or the recorded reason it gets none (SKIPPED)."""
    row = {"position_id": uuid4().hex[:12], "account": acc.key, "source": acc.source,
           "strategy_id": pick.strategy_id, "name": pick.name, "pick_rank": pick.rank, "parent_ref": p.ref,
           "structure": p.structure, "expiry": p.expiry, "timeframe": p.timeframe, "legs": p.legs,
           "credit": round(p.credit, 2), "parent_lots": p.lots, "lot_size": p.lot_size,
           "margin_per_lot": round(p.margin_per_lot, 2), "opened_at": p.opened_at, "entry_spot": p.entry_spot,
           "lots": 0, "qty": 0, "capital_deployed": 0.0, "equity_at_entry": None, "mark": None,
           "unrealized_pnl": 0.0, "exit_cost": None, "exit_legs": None, "exit_reason": None, "exit_spot": None,
           "gross_pnl": None, "fees": None, "realized_pnl": None, "closed_at": None,
           "skip_reason": None, "skip_note": None, "created_at": now, "updated_at": now}

    def skip(reason: str, note: str) -> dict:
        row.update({"status": "SKIPPED", "skip_reason": reason, "skip_note": note})
        return row

    if not entries:
        return skip("off", "Main Control had the Index Option Selling paper books switched off when this entry came.")
    if p.lots < 1 or p.lot_size < 1 or p.margin_per_lot <= 0 or p.credit <= 0 or not p.legs:
        return skip("data", "The parent's record has no size, margin or credit to copy.")
    if acc.skip_expiry_day and p.expiry and p.expiry == _ist_date(p.opened_at).isoformat():
        return skip("expiry_day", f"Opened on its own expiry day ({p.expiry}); the desk's Paper Trading books skip "
                                  "these (the daemon used to close them seconds later at nothing).")
    realized, deployed, held = ledger(copies, p.opened_at)
    if held:
        return skip("held", "The strategy already held a position at that moment (one at a time).")
    equity = PER_STRATEGY + realized
    lots, limit = size(p.margin_per_lot, equity, deployed)
    if lots < 1:
        return skip("margin", f"One lot needs ₹{p.margin_per_lot:,.0f} of margin; the strategy may put ₹{limit:,.0f} "
                              f"on a position (a fifth of its ₹{equity:,.0f}).")
    row.update({"status": "OPEN", "lots": lots, "qty": lots * p.lot_size,
                "capital_deployed": round(p.margin_per_lot * lots, 2), "equity_at_entry": round(equity, 2)})
    return row


def plan_strategy(acc: Account, pick: Pick, parents: list[Parent], copies: list[dict], entries: bool,
                  now: datetime) -> list[tuple[str, dict]]:
    """One strategy's account, brought up to its parent: ("insert", row) and ("update", {"position_id", "set"})
    operations, in order. `copies` (its rows so far, times naive UTC) is updated in place as the plan goes."""
    ops: list[tuple[str, dict]] = []
    by_ref = {r["parent_ref"]: r for r in copies}
    refs = {p.ref for p in parents}
    for p in sorted(parents, key=lambda q: (q.opened_at, q.ref)):
        row = by_ref.get(p.ref)
        if row is not None:
            if row.get("status") == "OPEN":
                op = _settle(row, p, now)
                if op:
                    ops.append(op)
            continue
        # A new entry. A copy whose parent vanished without a closing record is voided first: the parent holds one
        # structure at a time per strategy, so a newer entry means the old one is gone.
        for r in copies:
            if r.get("status") == "OPEN" and r["parent_ref"] not in refs and r["opened_at"] <= p.opened_at:
                ops.append(_void(r, now, "the parent closed without a recorded trade"))
        row = _decide(acc, pick, p, copies, entries, now)
        copies.append(row)
        by_ref[p.ref] = row
        ops.append(("insert", row))
        if row["status"] == "OPEN" and p.state != "OPEN":
            op = _settle(row, p, now)       # it opened and closed between two looks: book the close now
            if op:
                ops.append(op)
    return ops


# -- running ----------------------------------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _norm(row: dict) -> dict:
    for k in ("opened_at", "closed_at", "created_at", "updated_at"):
        if isinstance(row.get(k), datetime):
            row[k] = naive_utc(row[k])
    return row


async def _start(key: str, now: datetime) -> datetime:
    """When an account began copying: set once, on its first cycle."""
    doc = await STATE.find_one({"_id": f"start:{key}"})
    if not (doc and doc.get("started_at")):
        await STATE.update_one({"_id": f"start:{key}"}, {"$setOnInsert": {"started_at": now, "account": key}},
                               upsert=True)
        doc = await STATE.find_one({"_id": f"start:{key}"})
    return naive_utc(doc["started_at"])


async def _apply(ops: list[tuple[str, dict]]) -> Counter:
    n: Counter = Counter()
    for kind, body in ops:
        if kind == "insert":
            try:
                await POSITIONS.insert_one(dict(body))
            except DuplicateKeyError:
                continue                    # another run decided this entry first
            n["opened" if body["status"] == "OPEN" else "skipped"] += 1
        else:
            await POSITIONS.update_one({"position_id": body["position_id"]}, {"$set": body["set"]})
            st = body["set"].get("status")
            if st in ("CLOSED", "VOID"):
                n[st.lower()] += 1
    return n


async def _entries_on() -> bool:
    from app.services.desk_switches import is_on
    return await is_on(SWITCH)


_lock = asyncio.Lock()
_indexed = False


async def ensure_indexes() -> None:
    await POSITIONS.create_index([("account", 1), ("strategy_id", 1), ("parent_ref", 1)], unique=True,
                                 name="selling_each_copy_once")
    await POSITIONS.create_index([("account", 1), ("status", 1)])


async def run_cycle() -> dict:
    """Bring both accounts up to their parents once: closes and marks, then new entries in the order they came."""
    global _indexed
    if not ENABLED:
        return {"enabled": False}
    async with _lock:
        if not _indexed:
            try:
                await ensure_indexes()
                _indexed = True
            except Exception:  # noqa: BLE001 - a missing index must never stop the copies
                logger.warning("[selling_each] could not create indexes", exc_info=True)
        entries = await _entries_on()
        out: dict = {"entries": entries}
        for acc in ACCOUNTS.values():
            try:
                now = _now()
                start = await _start(acc.key, now)
                parents = await (_factory_parents(acc, start) if acc.source == "factory" else _desk_parents(acc, start))
                total: Counter = Counter()
                for pick in acc.picks:
                    mine = [p for p in parents if p.strategy_id == pick.strategy_id]
                    copies = [_norm(r) async for r in POSITIONS.find({"account": acc.key,
                                                                      "strategy_id": pick.strategy_id})]
                    total.update(await _apply(plan_strategy(acc, pick, mine, copies, entries, now)))
                await STATE.update_one({"_id": f"run:{acc.key}"},
                                       {"$set": {"last_run_at": now, "parents_seen": len(parents), **total}},
                                       upsert=True)
                out[acc.key] = dict(total)
            except Exception:  # noqa: BLE001 - one account's fault never stops the other
                logger.warning("[selling_each] %s cycle failed", acc.key, exc_info=True)
                out[acc.key] = {"error": True}
        return out


def _nse_minutes() -> bool:
    t = datetime.now(IST)
    return t.weekday() < 5 and 9 * 60 <= t.hour * 60 + t.minute <= 15 * 60 + 45


async def loop() -> None:
    """Every minute in NSE hours, every ten minutes otherwise (a parent can close after the bell)."""
    await asyncio.sleep(45)
    while True:
        try:
            await run_cycle()
        except Exception:  # noqa: BLE001
            logger.warning("[selling_each] cycle failed", exc_info=True)
        await asyncio.sleep(60 if _nse_minutes() else 600)


# -- read models ------------------------------------------------------------------------------------------------------


def _iso(v):
    return v.replace(tzinfo=timezone.utc).isoformat() if isinstance(v, datetime) else v


def _out(row: dict) -> dict:
    row = dict(row)
    row.pop("_id", None)
    for k in ("opened_at", "closed_at", "created_at", "updated_at"):
        row[k] = _iso(row.get(k))
    return row


async def _rows(acc: Account) -> list[dict]:
    return [_norm(r) async for r in POSITIONS.find({"account": acc.key})]


def _strategy_rows(acc: Account, rows: list[dict]) -> list[dict]:
    out = []
    for pick in acc.picks:
        mine = [r for r in rows if r.get("strategy_id") == pick.strategy_id]
        closed = [r for r in mine if r.get("status") == "CLOSED"]
        held = [r for r in mine if r.get("status") == "OPEN"]
        net = sum(float(r.get("realized_pnl") or 0.0) for r in closed)
        unreal = sum(float(r.get("unrealized_pnl") or 0.0) for r in held)
        deployed = sum(float(r.get("capital_deployed") or 0.0) for r in held)
        wins = sum(1 for r in closed if (r.get("realized_pnl") or 0.0) > 0)
        skipped = Counter(r.get("skip_reason") for r in mine if r.get("status") == "SKIPPED")
        equity = PER_STRATEGY + net + unreal
        _, limit = size(1.0, PER_STRATEGY + net, deployed)
        out.append({
            "strategy_id": pick.strategy_id, "name": pick.name, "picked_rank": pick.rank,
            "picked_score": pick.score, "picked_trades": pick.trades, "picked_net_pnl": pick.net_pnl,
            "capital": PER_STRATEGY, "trades": len(closed), "wins": wins,
            "win_rate": round(wins / len(closed), 4) if closed else None,
            "gross_pnl": round(sum(float(r.get("gross_pnl") or 0.0) for r in closed), 2),
            "fees": round(sum(float(r.get("fees") or 0.0) for r in closed), 2),
            "net_pnl": round(net, 2), "unrealized_pnl": round(unreal, 2), "deployed": round(deployed, 2),
            "equity": round(equity, 2), "roi_pct": round((net + unreal) / PER_STRATEGY * 100, 3),
            "open_positions": len(held), "position_limit": round(limit, 2),
            "lots_last": (max(held or closed, key=lambda r: r.get("opened_at") or datetime.min).get("lots")
                          if (held or closed) else None),
            "skipped": {k: int(skipped.get(k, 0)) for k in SKIP_REASONS}, "skipped_total": sum(skipped.values()),
            "voided": sum(1 for r in mine if r.get("status") == "VOID"),
        })
    return out


async def summary(account: str | None = None) -> dict:
    acc = ACCOUNTS[normalize_account(account)]
    rows = await _rows(acc)
    strat = _strategy_rows(acc, rows)
    capital = PER_STRATEGY * len(acc.picks)
    realized = sum(s["net_pnl"] for s in strat)
    unreal = sum(s["unrealized_pnl"] for s in strat)
    deployed = sum(s["deployed"] for s in strat)
    skipped = {k: sum(s["skipped"][k] for s in strat) for k in SKIP_REASONS}
    start = await STATE.find_one({"_id": f"start:{acc.key}"}) or {}
    run = await STATE.find_one({"_id": f"run:{acc.key}"}) or {}
    try:
        switch_on = await _entries_on()
    except Exception:  # noqa: BLE001
        switch_on = True
    return {
        "account": acc.key, "accounts": [{"key": a.key, "label": a.label} for a in ACCOUNTS.values()],
        "label": acc.label, "source": acc.source, "board": acc.board, "instrument": acc.instrument,
        "notes": list(acc.notes), "picked_at": PICKED_AT, "mode": "PAPER", "enabled": ENABLED,
        "entries_on": switch_on, "switch": SWITCH,
        "strategies": len(acc.picks), "per_strategy_capital": PER_STRATEGY, "account_capital": capital,
        "position_share": POSITION_SHARE, "max_lots": MAX_LOTS, "skip_expiry_day": acc.skip_expiry_day,
        "equity": round(capital + realized + unreal, 2), "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unreal, 2),
        "gross_pnl": round(sum(s["gross_pnl"] for s in strat), 2), "fees": round(sum(s["fees"] for s in strat), 2),
        "deployed": round(deployed, 2), "available_cash": round(capital + realized - deployed, 2),
        "open_positions": sum(s["open_positions"] for s in strat), "closed_positions": sum(s["trades"] for s in strat),
        "wins": sum(s["wins"] for s in strat),
        "roi_pct": round((realized + unreal) / capital * 100, 3) if capital else 0.0,
        "skipped": skipped, "voided": sum(s["voided"] for s in strat),
        "copying_since": _iso(naive_utc(start["started_at"])) if start.get("started_at") else None,
        "last_run_at": _iso(naive_utc(run["last_run_at"])) if run.get("last_run_at") else None,
    }


async def strategies(account: str | None = None) -> list[dict]:
    acc = ACCOUNTS[normalize_account(account)]
    return _strategy_rows(acc, await _rows(acc))


async def positions(account: str | None = None, status: str = "OPEN", limit: int = 300) -> list[dict]:
    acc = ACCOUNTS[normalize_account(account)]
    q: dict = {"account": acc.key}
    st = (status or "OPEN").upper()
    if st != "ALL":
        q["status"] = st
    field_ = "closed_at" if st in ("CLOSED", "VOID") else "opened_at"
    return [_out(_norm(r)) async for r in POSITIONS.find(q).sort(field_, -1).limit(limit)]
