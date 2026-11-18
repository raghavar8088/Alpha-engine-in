"""Gold Desk: a Rs 2 lakh paper account for each of the Strategy Factory tab's top 25 (18 Nov 2026).

The owner asked, on the Gold Desk's "Strategy Factory · 546" tab (the board "The 546 strategies - the ones that have
traded"), for a Rs 2 lakh paper account for each strategy, in sets for the board's top 1-5, 5-10, 10-15, 15-20 and
20-25. Read as Rank 1-5, 6-10, 11-15, 16-20 and 21-25 (the page labels them as the owner did, with the ranks under
them): 25 accounts, one strategy each, Rs 2,00,000 each - Rs 10 lakh a set, Rs 50 lakh in all.

THE 25 are the tab's Rank (strategy_rank, source "factory-desks", desk "gold") as read at 22:21 IST on 18 Nov 2026, and
they are FROZEN - not re-picked as the board moves, as for every picked book. 415 strategies had closed trades then
(51,857 trades in all); these 25 had 17 to 75 each and t-stats of 0.82 to 2.64. A Rank under 30 trades is pulled toward
the middle, but the best 25 of 415 still collect luck at the top, and the tab as a whole had lost money. The board says
it itself: a rank is relative, not proof of an edge. Never re-pick them without the owner; a new roster is a new set.

THEY COPY THE TAB'S OWN TRADES (factory_desk_positions, desk "gold", in the tab's own MongoDB). A copy opens when the tab
opens a trade for its strategy, at the tab's entry price, and closes when the tab closes it, at the tab's exit price, so
a copy differs from the tab only in SIZE. Nothing here scans a bar, asks Delta for a price or writes to the tab's records.

SIZE AND COST
- Whole contracts of 0.001 oz of Delta's XAUTUSD perpetual at 1x (no leverage): a position ties up its notional.
- A contract's rupee cost is the tab's entry price x 0.001 x USD/INR. The rate (Yahoo INR=X through gold_desk.usd_inr)
  is read when the copy is decided and kept on the copy; its profit and loss convert at that same rate. With no rate,
  no new copy is made (open ones still close).
- Each entry is sized on the account's realised equity then (Rs 2 lakh + its realised P&L): a strategy's profit stays
  in its own account and a loss shrinks only its own next position. It takes one new entry per round, each round's
  capital being its equity then - exact, because a strategy holds one position at a time on the tab. (This avoids
  plan_book's newer `compound` flag, which a server running an older copy of that shared file would reject.)
- P&L is the tab's own result at the account's size: the price move between its fills (the spread is inside them),
  its fees (Delta's taker rate + 18% GST, both sides) and the funding it paid or was paid - each proportional to the
  position's size on Delta.
- The tab trades a $1,111 sleeve (about 270 contracts); a Rs 2 lakh account's position is about twice that. The extra
  depth that would take is NOT modelled.

ONE POSITION PER ACCOUNT, NEVER NETTED. Each copy is its own position, as on the tab, so some of the 25 can be long and
others short XAUTUSD at the same time. One real Delta account would net them into one position.

An account starts the first time a pass sees it and never back-fills: a position the tab already held then is not
copied, so each account's first trade is its strategy's next entry on the tab. Main Control's Gold Desk switch stops
new copies (open ones still close with the tab), as it stops the tab's own entries. The accounts live in the tab's
MongoDB beside the trades they copy (gold_sf_positions, gold_sf_state). Paper only: nothing here places an order.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.services import factory_desks as fd
from app.services.book_reset import naive_utc
from app.services.live_intraday_mirror import pending_since, plan_book

logger = logging.getLogger("gold_sf_books")

IST = timezone(timedelta(hours=5, minutes=30))
TAB = "gold"                                  # factory_desks.TABS key of the Gold Desk's Strategy Factory tab
SYMBOL = "XAUTUSD"
CONTRACT_VALUE = 0.001                        # troy ounces in one Delta XAUTUSD contract
SOURCE_TAG = "gold-sf"
ENABLED = os.getenv("GOLD_SF_BOOKS", "1").lower() not in ("0", "false", "")
TICK_SECONDS = int(os.getenv("GOLD_SF_TICK_SECONDS", "120"))
# The 25 trade 5m-1h bars and the tab holds a trade at most 60 of its bars (2.5 days at 1h). A pass reads the tab's
# trades of the 25 opened inside this window, plus any an open copy points at; every pass decides all it sees.
LOOKBACK = timedelta(days=int(os.getenv("GOLD_SF_LOOKBACK_DAYS", "14")))
CAPITAL = float(os.getenv("GOLD_SF_CAPITAL", "200000"))
PICKED_AT = "2026-11-18T22:21:00+05:30"
BOARD = ("the Gold Desk's Strategy Factory tab, ranked by its Rank (7 factors): 415 strategies with closed trades, "
         "51,857 trades, as read at 22:21 IST on 18 Nov 2026")

PARENTS = fd.POSITIONS                        # the tab's own records: read, never written
POSITIONS = fd.STORE["gold_sf_positions"]
STATE = fd.STORE["gold_sf_state"]


@dataclass(frozen=True)
class Pick:
    rank: int               # its place on the board at the pick
    strategy_id: str
    name: str
    timeframe: str
    family: str
    score: float            # its Rank score at the pick
    trades: int             # closed trades on the tab at the pick
    win_rate: float         # 0-1
    profit_factor: float | None
    net_usd: float          # its net P&L on the tab at the pick, one $1,111 sleeve
    t: float | None         # t-stat of its net P&L a trade
    bp: float | None        # its mean net return a trade, basis points


# /api/strategy-rank/factory-desks?desk=gold + /api/factory-desks/gold/leaderboard at 22:21 IST on 18 Nov 2026.
PICKS: tuple[Pick, ...] = (
    Pick(1, "SF0181", "Three Soldiers / Crows · 45m", "45m", "candlestick", 82.7, 41, 0.4634, 2.341, 112.06, 2.396, 24.62),
    Pick(2, "SF0020", "Triple Top / Bottom · 30m", "30m", "chart", 81.8, 41, 0.4146, 2.759, 131.40, 2.570, 28.84),
    Pick(3, "SF0182", "Three Soldiers / Crows · 1h", "1h", "candlestick", 79.9, 33, 0.4242, 1.781, 69.73, 1.457, 19.09),
    Pick(4, "SF0219", "Donchian Breakout (slow) · 15m", "15m", "structure", 79.6, 39, 0.4103, 1.948, 78.32, 1.617, 18.13),
    Pick(5, "SF0013", "Double Top / Bottom · 45m", "45m", "chart", 79.3, 38, 0.4474, 2.042, 97.61, 1.873, 23.14),
    Pick(6, "SF0346", "Rectangle / Trading Range Break · 30m", "30m", "structure", 78.7, 23, 0.6522, 4.121, 116.33,
         2.637, 45.52),
    Pick(7, "SF0331", "Trend Pullback to EMA · 45m", "45m", "structure", 76.1, 30, 0.4000, 1.770, 73.13, 1.318, 21.98),
    Pick(8, "SF0245", "Prior Session High/Low Break · 45m", "45m", "structure", 75.8, 28, 0.5000, 2.379, 91.94, 1.962,
         29.55),
    Pick(9, "SF0021", "Triple Top / Bottom · 45m", "45m", "chart", 75.8, 26, 0.4615, 2.468, 88.87, 1.903, 30.76),
    Pick(10, "SF0324", "Opening Range Breakout · 45m", "45m", "structure", 75.4, 46, 0.4348, 1.704, 62.94, 1.554, 12.32),
    Pick(11, "SF0213", "Donchian Breakout (fast) · 45m", "45m", "structure", 74.8, 23, 0.4783, 2.490, 73.82, 1.827, 28.90),
    Pick(12, "SF0022", "Triple Top / Bottom · 1h", "1h", "chart", 73.4, 27, 0.3704, 2.073, 79.89, 1.466, 26.68),
    Pick(13, "SF0206", "Heikin Ashi Flip · 1h", "1h", "candlestick", 72.8, 32, 0.3438, 1.541, 44.66, 0.997, 12.63),
    Pick(14, "SF0090", "Diamond · 5m", "5m", "chart", 72.6, 36, 0.3889, 1.505, 24.78, 0.993, 6.22),
    Pick(15, "SF0251", "Round Number Break · 30m", "30m", "structure", 71.7, 18, 0.6111, 3.780, 41.28, 2.431, 20.64),
    Pick(16, "SF0370", "RSI Trend Regime (40/60) · 30m", "30m", "indicator", 71.0, 18, 0.6111, 3.096, 99.31, 1.751, 49.90),
    Pick(17, "SF0347", "Rectangle / Trading Range Break · 45m", "45m", "structure", 70.8, 17, 0.7647, 3.757, 108.05,
         2.337, 57.20),
    Pick(18, "SF0243", "Prior Session High/Low Break · 15m", "15m", "structure", 69.9, 75, 0.4000, 1.448, 60.93, 1.341,
         7.33),
    Pick(19, "SF0282", "ATR Expansion Thrust · 15m", "15m", "structure", 69.3, 51, 0.4118, 1.314, 20.37, 0.824, 3.60),
    Pick(20, "SF0542", "Rectangle + Volume + ATR · 30m", "30m", "hybrid", 69.2, 18, 0.6667, 3.526, 85.29, 2.091, 42.65),
    Pick(21, "SF0466", "Breakout + Volume + HTF Trend · 30m", "30m", "hybrid", 68.2, 25, 0.3600, 1.684, 41.98, 1.062,
         15.14),
    Pick(22, "SF0426", "Parabolic SAR Flip · 30m", "30m", "indicator", 67.8, 23, 0.5217, 2.208, 72.42, 1.483, 28.34),
    Pick(23, "SF0205", "Heikin Ashi Flip · 45m", "45m", "candlestick", 67.8, 31, 0.3871, 1.465, 34.15, 0.882, 9.95),
    Pick(24, "SF0476", "Pullback + EMA + RSI + VWAP · 1h", "1h", "hybrid", 67.7, 19, 0.4211, 2.451, 85.42, 1.618, 40.51),
    Pick(25, "SF0332", "Trend Pullback to EMA · 1h", "1h", "structure", 67.7, 19, 0.4211, 2.324, 77.47, 1.514, 36.77),
)
PICK = {p.strategy_id: p for p in PICKS}


@dataclass(frozen=True)
class Band:
    lo: int
    hi: int

    @property
    def key(self) -> str:
        return f"{self.lo}-{self.hi}"

    @property
    def label(self) -> str:
        """As the owner named it: Top 1-5, Top 5-10 ... Top 20-25 (the ranks are under it on the page)."""
        return f"Top {self.lo if self.lo == 1 else self.lo - 1}-{self.hi}"


BANDS: tuple[Band, ...] = tuple(Band(lo, lo + 4) for lo in range(1, len(PICKS) + 1, 5))


@dataclass(frozen=True)
class Account:
    id: str
    pick: Pick
    capital: float

    @property
    def band(self) -> Band:
        return BANDS[(self.pick.rank - 1) // 5]

    @property
    def label(self) -> str:
        return f"#{self.pick.rank} {self.pick.name} · ₹2 lakh"


ACCOUNTS: tuple[Account, ...] = tuple(Account(f"sf2L_{p.rank:02d}", p, CAPITAL) for p in PICKS)
ACCOUNT = {a.id: a for a in ACCOUNTS}
BY_STRATEGY = {a.pick.strategy_id: a for a in ACCOUNTS}

NOTES = (
    "Rank 1-25 of this tab's board at 22:21 IST on 18 Nov 2026, frozen. 415 strategies had closed trades then; these "
    "had 17 to 75 each and t-stats of 0.82 to 2.64. Picked after the fact from a board where the 546 together had lost "
    "money: the best of many short records, not a proven edge.",
    "Each strategy has its own ₹2,00,000 and holds one position at a time, as on the tab. Each entry is sized on that "
    "account's realised equity then, so one strategy's losses never reduce another's money.",
    "Each copy is the tab's own trade - its entry, its exit, its fees and the funding it paid or was paid - at the "
    "account's size, in whole 0.001 oz contracts at 1x (no leverage). Nothing is re-scanned and no order is sent.",
    "Rupees at USD/INR (Yahoo INR=X) read when the copy is made; its profit and loss convert at that same rate.",
    "The tab trades a $1,111 sleeve (about 270 contracts); a ₹2 lakh account's position is about twice that. The extra "
    "depth it would take is not modelled.",
    "Several of the 25 are the same pattern on another timeframe (Triple Top / Bottom 30m, 45m and 1h; Three Soldiers / "
    "Crows 45m and 1h; Rectangle / Trading Range Break 30m and 45m) and often trade together, so the accounts move "
    "together. Each copy is its own position; one real Delta account would net them.",
    "The accounts started empty when they first ran and copy only trades the tab opens after that; nothing is "
    "back-filled. Main Control's Gold Desk switch stops new copies.",
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


def _ist_day(v) -> str | None:
    d = _dt(v)
    return d.replace(tzinfo=timezone.utc).astimezone(IST).date().isoformat() if d else None


def _iso(v) -> str | None:
    d = _dt(v)
    return d.replace(tzinfo=timezone.utc).isoformat() if d else None


# -- the tab's trades as parents ----------------------------------------------------------------------


def parent_of(doc: dict, fx: float | None) -> dict | None:
    """One of the tab's gold positions as a parent to copy; None when it is not one of the 25 or cannot be.

    `entry_price` is what one contract ties up, in rupees at `fx` (plan_book sizes on it); with no rate it is 0, which
    only a pass that makes no new copy is ever given. The tab books a position by its dollar notional
    (`capital_deployed`): its gross is side x the move / entry x notional, its fees are the taker rate + GST on that
    notional at entry and at exit, and its funding is charged on it - so every figure scales with a copy's size."""
    sid = doc.get("strategy_id")
    pick = PICK.get(sid)
    entry = _f(doc.get("entry_px"))
    notional = _f(doc.get("capital_deployed"))
    side = doc.get("signal_side") or doc.get("side")
    if (pick is None or doc.get("desk", TAB) != TAB or doc.get("kind", "perp") != "perp" or entry <= 0
            or notional <= 0 or side not in ("BUY", "SELL") or not doc.get("position_id")):
        return None
    closed = (doc.get("status") == "CLOSED" and doc.get("exit_px") is not None
              and doc.get("realized_pnl") is not None)
    opened_at = _dt(doc.get("opened_at"))
    closed_at = _dt(doc.get("closed_at")) if closed else None
    funding = _f(doc.get("funding")) if closed else 0.0
    return {
        "position_id": doc["position_id"], "key": sid, "strategy_id": sid, "strategy_name": pick.name,
        "timeframe": doc.get("timeframe") or pick.timeframe,
        "symbol": sid,                    # one position per STRATEGY: see the module notes
        "instrument": SYMBOL, "side": side,
        "opened_at": opened_at,
        "opened_on": doc.get("opened_on") or _ist_day(opened_at),
        "closed_at": closed_at,
        "closed_on": (doc.get("closed_on") or _ist_day(closed_at)) if closed else None,
        "status": "CLOSED" if closed else "OPEN",
        "entry_price": round(entry * CONTRACT_VALUE * fx, 4) if fx else 0.0,
        "exit_price": _f(doc.get("exit_px")) if closed else None,
        "px_entry": entry, "px_exit": _f(doc.get("exit_px")) if closed else None,
        "px_ltp": None if doc.get("under_ltp") is None else _f(doc.get("under_ltp")),
        "notional_usd": notional, "usd_inr": fx,
        # the tab's costs for ITS notional: fees both sides once closed (entry only while open) and the funding
        "fees_usd": (_f(doc.get("fees")) - funding) if closed else _f(doc.get("entry_costs")),
        "funding_usd": funding,
        "unrealized_usd": None if doc.get("unrealized_pnl") is None else _f(doc.get("unrealized_pnl")),
        "exit_reason": doc.get("exit_reason"), "exit_basis": doc.get("exit_basis"),
        "target": doc.get("target"), "stoploss": doc.get("stop"),
    }


def _scale(qty: int, parent: dict) -> float:
    """A copy of `qty` contracts as a share of the tab's own position (its notional at the tab's entry price)."""
    return parent["px_entry"] * CONTRACT_VALUE * qty / parent["notional_usd"]


def pnl(row: dict, parent: dict) -> tuple[float, float, Costs]:
    """(gross, net, costs) in rupees: the tab's own result at the copy's contracts.

    plan_book calls it with a stored row (which carries the rate it was opened at) or, for a trade that opened and
    closed between two passes, with its own draft row (the parent carries the rate)."""
    q = int(row["qty"])
    fx = float(row.get("usd_inr") or parent["usd_inr"])
    sign = 1 if parent["side"] == "BUY" else -1
    k = _scale(q, parent)
    gross = round(sign * (parent["px_exit"] - parent["px_entry"]) * CONTRACT_VALUE * q * fx, 2)
    fees = round(parent["fees_usd"] * k * fx, 2)
    funding = round(parent["funding_usd"] * k * fx, 2)
    costs = Costs(round(fees + funding, 2), {"fees": fees, "funding": funding})
    return gross, round(gross - costs.total, 2), costs


def mark(row: dict, parent: dict) -> float | None:
    """An open copy's P&L: the tab's own mark (the move less its entry fee) at the copy's size and rate."""
    u = parent.get("unrealized_usd")
    fx = _f(row.get("usd_inr") or parent.get("usd_inr"))
    if u is None or fx <= 0:
        return None
    return round(u * _scale(int(row["qty"]), parent) * fx, 2)


# -- reads -------------------------------------------------------------------------------------------


async def _starts() -> dict[str, datetime]:
    """When each account began copying: the first time a pass saw it. Set once; nothing earlier is copied."""
    have: dict[str, datetime] = {}
    async for d in STATE.find({"kind": "start"}):
        if d.get("account") and d.get("started_at"):
            have[d["account"]] = naive_utc(d["started_at"])
    missing = [a.id for a in ACCOUNTS if a.id not in have]
    if missing:
        now = _now()
        for acct in missing:
            await STATE.update_one({"_id": f"start:{acct}"}, {"$setOnInsert": {
                "kind": "start", "account": acct, "started_at": now}}, upsert=True)
        async for d in STATE.find({"kind": "start", "account": {"$in": missing}}):
            have[d["account"]] = naive_utc(d["started_at"])
    return have


async def _load(since: datetime, pointed: list[str]) -> list[dict]:
    """The tab's gold positions of the 25 opened since `since`, and any an open copy points at."""
    q = {"desk": TAB, "strategy_id": {"$in": sorted(PICK)},
         "$or": [{"opened_at": {"$gte": since}}, {"position_id": {"$in": pointed}}]}
    return [d async for d in PARENTS.find(q)]


async def _decided(acct: str, parents: list[dict]) -> set[str]:
    """The tab's trades this account has already copied or skipped."""
    ids = [p["position_id"] for p in parents]
    out: set[str] = set()
    async for r in POSITIONS.find({"account": acct, "parent_position_id": {"$in": ids}}, {"parent_position_id": 1}):
        out.add(r["parent_position_id"])
    async for s in STATE.find({"kind": "skip", "account": acct, "parent_position_id": {"$in": ids}},
                              {"parent_position_id": 1}):
        out.add(s["parent_position_id"])
    return out


async def _totals(acct: str) -> tuple[float, float]:
    realized = deployed = 0.0
    async for r in POSITIONS.find({"account": acct}, {"status": 1, "realized_pnl": 1, "capital_deployed": 1}):
        if r.get("status") == "OPEN":
            deployed += _f(r.get("capital_deployed"))
        else:
            realized += _f(r.get("realized_pnl"))
    return realized, deployed


async def _closed_after(acct: str, t0: datetime | None) -> list[dict]:
    """The account's copies closed after t0: they still held their slot and cash when later entries happened."""
    if t0 is None:
        return []
    return [r async for r in POSITIONS.find(
        {"account": acct, "status": "CLOSED", "closed_at": {"$gt": t0}},
        {"symbol": 1, "capital_deployed": 1, "realized_pnl": 1, "opened_at": 1, "closed_at": 1})]


async def _fx() -> tuple[float | None, str | None]:
    """USD/INR now (Yahoo INR=X, cached ten minutes by the desk; GOLD_USD_INR as its fallback)."""
    try:
        from app.services import gold_desk
        rate, asof = await gold_desk.usd_inr()
    except Exception:  # noqa: BLE001 - no rate means no new copy, never a guessed one
        logger.warning("[gold sf] USD/INR read failed", exc_info=True)
        return None, None
    return (float(rate), asof) if rate and float(rate) > 0 else (None, None)


# -- the copy ----------------------------------------------------------------------------------------


def _row(acct: Account, p: dict, qty: int, spend: float, fx_asof: str | None) -> dict:
    return {
        "position_id": uuid4().hex[:12], "account": acct.id, "rank": acct.pick.rank, "band": acct.band.key,
        "source": SOURCE_TAG, "parent_position_id": p["position_id"], "key": p["key"], "strategy_id": p["key"],
        "strategy_name": p["strategy_name"], "timeframe": p["timeframe"], "symbol": p["symbol"],
        "instrument": p["instrument"], "side": p["side"], "qty": qty, "contract_value": CONTRACT_VALUE,
        "ounces": round(qty * CONTRACT_VALUE, 4), "entry_px": p["px_entry"], "entry_price": p["entry_price"],
        "usd_inr": p["usd_inr"], "usd_inr_asof": fx_asof,
        "notional_usd": round(p["px_entry"] * CONTRACT_VALUE * qty, 2), "parent_notional_usd": p["notional_usd"],
        "capital_deployed": spend, "target": p.get("target"), "stoploss": p.get("stoploss"),
        "ltp": p.get("px_ltp"), "unrealized_pnl": 0.0,
        "realized_pnl": None, "gross_pnl": None, "fees": None, "fee_breakdown": None,
        "exit_px": None, "exit_reason": None, "exit_basis": None, "status": "OPEN",
        "opened_at": p["opened_at"], "opened_on": p.get("opened_on"), "closed_at": None, "closed_on": None,
        "updated_at": _now(),
    }


def _close_fields(p: dict, c: dict) -> dict:
    closed_at = p.get("closed_at") or naive_utc(_now())
    return {
        "status": "CLOSED", "exit_px": p["px_exit"], "exit_reason": p.get("exit_reason"),
        "exit_basis": p.get("exit_basis"), "gross_pnl": c["gross"], "fees": c["fb"].total,
        "fee_breakdown": c["fb"].as_dict(), "realized_pnl": c["net"], "unrealized_pnl": 0.0, "ltp": p["px_exit"],
        "closed_at": closed_at, "closed_on": p.get("closed_on") or _ist_day(closed_at), "updated_at": _now(),
    }


async def _sync_account(acct: Account, parents_all: list[dict], start: datetime, entries: bool,
                        fx_asof: str | None, first_pending_only: bool) -> dict:
    """One round for one account: close what the tab closed, take (at most) its earliest pending entry, mark the rest."""
    n = {"opened": 0, "closed": 0, "skipped": 0, "marked": 0, "pending": 0}
    by_id = {p["position_id"]: p for p in parents_all}
    floor = max(start, naive_utc(_now()) - LOOKBACK)
    open_rows = [r async for r in POSITIONS.find({"account": acct.id, "status": "OPEN"})]
    pointed = {r.get("parent_position_id") for r in open_rows}
    sid = acct.pick.strategy_id
    parents = [p for p in parents_all
               if p["key"] == sid and p["opened_at"] is not None
               and (p["opened_at"] >= floor or p["position_id"] in pointed)]
    parents.sort(key=lambda p: (p["opened_at"], p["position_id"]))
    realized, deployed = await _totals(acct.id)
    decided = await _decided(acct.id, parents) if entries else set()
    if first_pending_only and entries:
        # One new entry per round (sync runs rounds until none waits), so each is sized on the equity the ones before
        # it left.
        waiting = [p for p in parents if p["position_id"] not in decided and p["position_id"] not in pointed]
        later = {p["position_id"] for p in waiting[1:]}
        parents = [p for p in parents if p["position_id"] not in later]
        n["pending"] = len(later)
    t0 = pending_since(parents, decided, open_rows, SOURCE_TAG) if entries else None
    closed_rows = await _closed_after(acct.id, t0) if entries else []
    # The account's capital is its realised equity now: its one position may use all of it.
    plan = plan_book(capital=acct.capital + realized, realized=0.0, deployed=deployed, open_rows=open_rows,
                     parents=parents, decided=decided, breaker_tripped=False, entries=entries,
                     max_open=1, net_fn=pnl, source_tag=SOURCE_TAG, closed_rows=closed_rows)

    for c in plan["closes"]:
        res = await POSITIONS.update_one({"_id": c["row"]["_id"], "status": "OPEN"},
                                         {"$set": _close_fields(c["parent"], c)})
        n["closed"] += res.modified_count
    for o in plan["opens"]:
        p = o["parent"]
        doc = _row(acct, p, o["qty"], o["spend"], fx_asof)
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
        await STATE.update_one({"_id": f"skip:{acct.id}:{p['position_id']}"}, {"$setOnInsert": {
            "kind": "skip", "account": acct.id, "key": p["key"], "parent_position_id": p["position_id"],
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
        if u is None or (u == r.get("unrealized_pnl") and p.get("px_ltp") == r.get("ltp")):
            continue                           # nothing moved: no write
        await POSITIONS.update_one({"_id": r["_id"], "status": "OPEN"},
                                   {"$set": {"ltp": p.get("px_ltp"), "unrealized_pnl": u, "updated_at": _now()}})
        n["marked"] += 1
    return n


def _has_work(acct: Account, parents: list[dict], start: datetime, open_ids: set[str], decided: set[str],
              entries: bool) -> bool:
    """Whether a pass needs this account at all: an open copy to close or mark, or a trade of its strategy to decide."""
    if any(p["position_id"] in open_ids for p in parents if p["key"] == acct.pick.strategy_id):
        return True
    if not entries:
        return False
    floor = max(start, naive_utc(_now()) - LOOKBACK)
    return any(p["key"] == acct.pick.strategy_id and p["opened_at"] is not None and p["opened_at"] >= floor
               and p["position_id"] not in decided for p in parents)


_lock = asyncio.Lock()
_indexed = False


async def sync(entries: bool = True) -> dict:
    """Copy the tab into every account once: close what the tab closed, open what it opened, mark the rest.

    One read of each collection decides which accounts have anything to do; only those are replayed."""
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
        starts = await _starts()
        open_rows = [r async for r in POSITIONS.find({"status": "OPEN"}, {"account": 1, "parent_position_id": 1})]
        open_ids = {r.get("parent_position_id") for r in open_rows if r.get("parent_position_id")}
        docs = await _load(naive_utc(_now()) - LOOKBACK, sorted(open_ids))
        parents = [p for p in (parent_of(d, fx) for d in docs) if p is not None]
        decided: set[str] = set()
        if allow and parents:
            ids = [p["position_id"] for p in parents]
            async for r in POSITIONS.find({"parent_position_id": {"$in": ids}}, {"parent_position_id": 1}):
                decided.add(r["parent_position_id"])
            async for s in STATE.find({"kind": "skip", "parent_position_id": {"$in": ids}}, {"parent_position_id": 1}):
                decided.add(s["parent_position_id"])
        out: dict = {"entries": allow, "usd_inr": fx, "parents": len(parents), "accounts": {}}
        if entries and fx is None:
            out["note"] = "No USD/INR rate this pass: open copies were managed and no new copy was made."
        for acct in ACCOUNTS:
            # each strategy has its own account, so a trade copied (or skipped) anywhere is decided for its account
            if not _has_work(acct, parents, starts[acct.id], open_ids, decided, allow):
                continue
            try:
                tot = {"opened": 0, "closed": 0, "skipped": 0, "marked": 0}
                for _round in range(200):           # a strategy takes a few trades a day; 200 is a guard
                    r = await _sync_account(acct, parents, starts[acct.id], allow, asof, first_pending_only=True)
                    for k in tot:
                        tot[k] += r.get(k, 0)
                    if not r.get("pending"):
                        break
                out["accounts"][acct.id] = tot
            except Exception as exc:  # noqa: BLE001 - one account's bad row must not stop the others
                logger.warning("[gold sf] %s failed: %s", acct.id, exc, exc_info=True)
                out["accounts"][acct.id] = {"error": str(exc)[:200]}
        return out


async def loop() -> None:
    """Every TICK_SECONDS, around the clock (Delta trades 24/7). Started by gold_scheduler.gold_delta_loop."""
    from app.services.desk_switches import is_on

    await asyncio.sleep(60)
    while True:
        if ENABLED:
            try:
                r = await sync(entries=await is_on("gold_desk"))
                moved = {k: v for k, v in (r.get("accounts") or {}).items()
                         if any(v.get(x) for x in ("opened", "closed", "error"))}
                if moved:
                    logger.info("[gold sf] %s", moved)
            except Exception:  # noqa: BLE001
                logger.warning("[gold sf] cycle failed", exc_info=True)
        await asyncio.sleep(TICK_SECONDS)


# -- read models --------------------------------------------------------------------------------------


def _summary(acct: Account, rows: list[dict], skipped: dict[str, int], started_at) -> dict:
    realized = unrealized = deployed = fees = gross = 0.0
    open_n = closed_n = wins = voided = 0
    days: set[str] = set()
    last_close = None
    for r in rows:
        status = r.get("status")
        if status == "OPEN":
            open_n += 1
            deployed += _f(r.get("capital_deployed"))
            unrealized += _f(r.get("unrealized_pnl"))
        elif status == "VOID":
            voided += 1
        else:
            v = _f(r.get("realized_pnl"))
            closed_n += 1
            realized += v
            wins += 1 if v > 0 else 0
            fees += _f(r.get("fees"))
            gross += _f(r.get("gross_pnl"))
            d = r.get("closed_on") or _ist_day(r.get("closed_at"))
            if d:
                days.add(str(d)[:10])
            ca = _dt(r.get("closed_at"))
            if ca and (last_close is None or ca > last_close):
                last_close = ca
    equity = acct.capital + realized + unrealized
    p = acct.pick
    return {
        "id": acct.id, "label": acct.label, "rank": p.rank, "band": acct.band.key, "strategy_id": p.strategy_id,
        "name": p.name, "timeframe": p.timeframe, "family": p.family, "pick": asdict(p),
        "capital": acct.capital, "equity": round(equity, 2), "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2), "deployed": round(deployed, 2),
        "available_cash": round(acct.capital + realized - deployed, 2),
        "open_positions": open_n, "closed_positions": closed_n, "wins": wins,
        "win_rate": round(wins / closed_n * 100, 1) if closed_n else None,
        "fees": round(fees, 2), "gross_pnl": round(gross, 2),
        # total return: realised + open P&L on the account's own Rs 2 lakh
        "roi_pct": round((equity - acct.capital) / acct.capital * 100, 4) if acct.capital else 0.0,
        # IST days on which it closed at least one copy (the same rule as the desk's history card)
        "days_traded": len(days),
        "started_at": _iso(started_at), "last_close_at": _iso(last_close),
        "skipped": skipped, "voided": voided,
    }


def _sum(rows: list[dict]) -> dict:
    """Accounts as one line: what a set (or all 25) puts to work."""
    cap = sum(r["capital"] for r in rows)
    keys = ("equity", "realized_pnl", "unrealized_pnl", "deployed", "available_cash", "fees", "gross_pnl")
    out = {k: round(sum(r[k] for r in rows), 2) for k in keys}
    closed = sum(r["closed_positions"] for r in rows)
    wins = sum(r["wins"] for r in rows)
    out.update(capital=cap, accounts=len(rows), open_positions=sum(r["open_positions"] for r in rows),
               closed_positions=closed, wins=wins, win_rate=round(wins / closed * 100, 1) if closed else None,
               roi_pct=round((out["equity"] - cap) / cap * 100, 4) if cap else 0.0,
               traded=sum(1 for r in rows if r["closed_positions"]))
    return out


async def overview() -> dict:
    rows: dict[str, list[dict]] = {}
    async for r in POSITIONS.find({}, {"account": 1, "status": 1, "realized_pnl": 1, "unrealized_pnl": 1,
                                       "capital_deployed": 1, "fees": 1, "gross_pnl": 1, "closed_on": 1,
                                       "closed_at": 1}):
        rows.setdefault(r.get("account"), []).append(r)
    skipped: dict[str, dict[str, int]] = {}
    async for s in STATE.find({"kind": "skip"}, {"account": 1, "reason": 1}):
        by = skipped.setdefault(s.get("account"), {})
        by[s.get("reason") or "?"] = by.get(s.get("reason") or "?", 0) + 1
    starts: dict[str, datetime] = {}
    async for d in STATE.find({"kind": "start"}, {"account": 1, "started_at": 1}):
        if d.get("account"):
            starts[d["account"]] = d.get("started_at")
    accounts = [_summary(a, rows.get(a.id, []), skipped.get(a.id, {}), starts.get(a.id)) for a in ACCOUNTS]
    by_band: dict[str, list[dict]] = {}
    for x in accounts:
        by_band.setdefault(x["band"], []).append(x)
    fx = await STATE.find_one({"_id": "fx"})
    return {
        "mode": "paper", "enabled": ENABLED, "tick_seconds": TICK_SECONDS, "tab": TAB, "instrument": SYMBOL,
        "picked_at": PICKED_AT, "board": BOARD, "capital_each": CAPITAL,
        "bands": [{"band": b.key, "lo": b.lo, "hi": b.hi, "label": b.label, "ranks": f"Rank {b.lo}-{b.hi}",
                   "accounts": [x["id"] for x in by_band.get(b.key, [])], "total": _sum(by_band.get(b.key, []))}
                  for b in BANDS],
        "total": _sum(accounts),
        "accounts": accounts,
        "usd_inr": {"rate": fx.get("rate"), "asof": fx.get("asof"), "at": _iso(fx.get("at"))} if fx else None,
        "notes": list(NOTES),
    }


def _jsonable(doc: dict) -> dict:
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = naive_utc(v).replace(tzinfo=timezone.utc).isoformat()
    return doc


def accounts_in(band: str | None = None, account: str | None = None) -> list[str] | None:
    """The account ids a positions read covers: one account, a set's five, or all 25 (None: unknown)."""
    if account:
        return [account] if account in ACCOUNT else None
    if band:
        ids = [a.id for a in ACCOUNTS if a.band.key == band]
        return ids or None
    return [a.id for a in ACCOUNTS]


async def positions(ids: list[str], status: str = "OPEN", limit: int = 200) -> list[dict]:
    """Copies of the given accounts: OPEN (newest first), CLOSED (closed or void, latest close first) or ALL."""
    s = status.upper()
    q: dict = {"account": {"$in": ids}}
    if s == "OPEN":
        q["status"] = "OPEN"
    elif s == "CLOSED":
        q["status"] = {"$in": ["CLOSED", "VOID"]}
    sort_key = "opened_at" if s == "OPEN" else "closed_at"
    return [_jsonable(r) async for r in POSITIONS.find(q).sort(sort_key, -1).limit(limit)]


async def ensure_indexes() -> None:
    """Best effort: an index failure must never stop the accounts."""
    try:
        await POSITIONS.create_index([("account", 1), ("parent_position_id", 1)], name="gsf_parent_unique",
                                     unique=True)
        await POSITIONS.create_index([("account", 1), ("status", 1)], name="gsf_account_status")
        await STATE.create_index([("kind", 1), ("account", 1), ("parent_position_id", 1)], name="gsf_state_kind")
    except Exception:  # noqa: BLE001
        logger.warning("[gold sf] index creation skipped", exc_info=True)
