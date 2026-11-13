"""Index Option Buying: three picked-strategy paper accounts (12 Nov 2026).

The owner asked, on the Index Option Buying page, for:

  best2L       "Best Strategies of Top 10" - Rs 2,00,000 on the two strategies that made the most in BOTH
               of this page's Top 10 paper accounts (top10_books, desk "prelive") from 27 Oct to 12 Nov
               2026: intra_ha_reversal · 15m and it_fake_breakout · 15m. ONE shared account with a slot
               for each: at most two positions at once, each up to Rs 1,00,000.
  sf_top10     "Top 10 Performing Strategies" - the Strategy Factory tab's Rank 1-10 on Index Option
               Buying (factory_desks, tab "index-buying"), Rs 10,00,000 for EACH strategy.
  sf_top10_20  "Top 10-20 Performing Strategies" - the same board's Rank 11-20, Rs 10,00,000 for each.

WHAT THEY COPY. Each book copies its desk's own trades of its picks - entry and exit at the desk's own
prices - and never re-scans or calls a broker:
  - best2L: the NIFTY 50 tournament (prelive_positions / prelive_trades), priced as its Top 10 books are:
    bought at the ask, sold at the bid (the tournament's real-money estimate);
  - the Factory books: the Strategy Factory tab's NIFTY option buys (factory_desk_positions, in that
    tab's own MongoDB): its ATM option bought at the ask and sold at the bid from Angel's quote, an
    unquoted expired option at intrinsic, as the tab itself books them.
Whole lots; never two positions in one contract inside one account; Angel One's option charges on the
book's own lots. A book starts at its first cycle and never backfills. The replay - slots, cash, one
contract, and the rewind that keeps them honest on the trades' own clock - is plan_book's
(live_intraday_mirror), as for the Top-10 and the rank-band books.

THE SHAPES. best2L is ONE account, as the Top 10 books are. The Factory books give every strategy its
OWN Rs 10 lakh (a book is Rs 1 crore), as the Commodity rank-band books do: one position at a time, as on
the desk, in whole lots up to that strategy's free cash, so a strategy's losses never shrink another's
money. The tab buys 1 lot a signal; at Rs 1,900-16,400 a lot these accounts buy roughly 60-520, priced
at the tab's 1-lot fill - an upper bound on what an order that size would have got.

THE PICKS ARE FROZEN as they stood at PICKED_AT; they are not re-picked as the boards move. Never re-pick
them without the owner: a changed roster is a new book.

Paper only: nothing here places an order.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.core.db import db
from app.services import top10_books as t10
from app.services.book_reset import naive_utc
from app.services.live_intraday_mirror import pending_since, plan_book

logger = logging.getLogger("prelive_pick_books")

POSITIONS = db["pick_book_positions"]
SCORES = db["pick_book_scores"]
STATE = db["pick_book_state"]
EQUITY = db["pick_book_equity"]
SOURCE_TAG = "pick"
ENABLED = os.getenv("PRELIVE_PICK_BOOKS_ENABLED", "1").lower() not in ("0", "false", "")
LOOKBACK = t10.LOOKBACK
SKIP_REASONS = ("full", "symbol_held", "price_above_cap", "no_cash")
SHARED = "book"                       # the account id of a book that is one account
FACTORY_TAB = "index-buying"          # factory_desks.TABS key of Index Option Buying's Strategy Factory tab
SNAPSHOT_EVERY = timedelta(minutes=15)
PICKED_AT = "2026-11-12T23:14:00+05:30"
MODULE = "Index Option Buying"


# -- the Strategy Factory tab's trades as parents --------------------------------------------------


def _factory_parent(p: dict) -> dict | None:
    """One Strategy Factory tab position (a single bought NIFTY option) as a parent the copy replays."""
    legs = p.get("legs") or []
    if p.get("kind") != "option_buy" or len(legs) != 1 or not p.get("lot_size") or not legs[0].get("entry"):
        return None
    leg = legs[0]
    closed = p.get("status") == "CLOSED"
    exits = p.get("exit_legs") or []
    marks = p.get("mark_legs") or []
    strike = t10._f(leg.get("strike"))
    return t10._option_parent(
        pid=str(p["position_id"]), key=p["strategy_id"], name=p.get("strategy_name") or p["strategy_id"],
        symbol=str(leg.get("token") or leg.get("tradingsymbol")),
        label=f"NIFTY {int(strike)} {leg.get('option_type') or ''} {leg.get('expiry') or ''}".strip(),
        lot_size=int(p["lot_size"]), entry=t10._f(leg["entry"]),
        exit_px=t10._f(exits[0]) if closed and exits else None,
        ltp=t10._f(marks[0]) if marks else None,
        opened_at=p.get("opened_at"), closed_at=p.get("closed_at"), status="CLOSED" if closed else "OPEN",
        expiry=leg.get("expiry"), opened_on=p.get("opened_on"), closed_on=p.get("closed_on"),
        exit_reason=p.get("exit_reason"))


async def _load_factory(since: datetime, keys: set, pointed: list) -> list[dict]:
    """The tab's positions of these strategies opened since `since`, plus any an open copy points at."""
    from app.services import factory_desks as fd       # its store: the tab's own MongoDB in production
    q = {"desk": FACTORY_TAB, "strategy_id": {"$in": list(keys)},
         "$or": [{"opened_at": {"$gte": since}}, {"position_id": {"$in": list(pointed)}}]}
    out = []
    async for p in fd.POSITIONS.find(q):
        x = _factory_parent(p)
        if x is not None:
            out.append(x)
    return out


# -- the books and their frozen picks ---------------------------------------------------------------


@dataclass(frozen=True)
class Book:
    key: str
    label: str
    desk: t10.Desk            # the copied desk's adapters, with this book's picks as its roster
    capital: float            # each strategy's own when per_strategy, else the one account's
    slots: int                # positions at once: in each strategy's account, or in the one account
    per_strategy: bool
    pick_rule: str            # how the picks were chosen

    @property
    def picks(self) -> tuple[t10.Pick, ...]:
        return self.desk.picks

    @property
    def total_capital(self) -> float:
        return self.capital * (len(self.picks) if self.per_strategy else 1)

    def accounts(self) -> list[tuple[str, set[str]]]:
        """(account id, the strategies it trades): one per strategy, or the one shared account."""
        if self.per_strategy:
            return [(p.key, {p.key}) for p in self.picks]
        return [(SHARED, {p.key for p in self.picks})]


_BEST_NOTES = (
    "Picked on 12 Nov 2026 as the two that made the most in BOTH of this page's Top 10 paper accounts since "
    "27 Oct: in the ₹2 lakh one, intra_ha_reversal · 15m made +₹79,871 on 9 trades and it_fake_breakout · 15m "
    "+₹59,580 on 7 (+₹4,22,549 and +₹3,12,818 in the ₹10 lakh one, the same trades at a bigger size).",
    "Chosen after the fact, on 9 and 7 trades. When the Top 10 was picked on 27 Oct, intra_ha_reversal stood #9 "
    "on the tournament with a loss of 128 bp a trade over 37 trades. On this desk a month's top 20 option-buying "
    "strategies lost the next month 11 times in 12 (Option Buying Top 20 study, Oct 2026).",
    "Priced as the Top 10 books are: bought at the ask, sold at the bid (the tournament's real-money estimate), "
    "not at the option's last traded price. Both trade ATM NIFTY options, so when they want the same contract at "
    "the same time the second is skipped and counted.",
)
_FACTORY_NOTES = (
    "Each strategy has its own ₹10,00,000 and holds one position at a time, as on the Strategy Factory tab; one "
    "strategy's losses never reduce another's money.",
    "The tab buys 1 lot a signal. These accounts buy whole lots up to the strategy's free cash - roughly 60 to "
    "520 lots at the premiums these strategies have paid (₹1,900-16,400 a lot) - priced at the tab's own 1-lot "
    "fill (the ask in, the bid out). A real order that size would pay more to get in and out, so read the "
    "rupee P&L as an upper bound.",
    "Ranked on 4-15 closed trades each since 28 Oct; the board itself says a rank is relative, not proof of an "
    "edge. On this desk a month's top 20 option-buying strategies lost the next month 11 times in 12 (Option "
    "Buying Top 20 study, Oct 2026).",
)

_BEST_DESK = dataclasses.replace(
    t10.DESKS["prelive"],
    board="net P&L in this page's two Top 10 paper accounts (₹2 lakh and ₹10 lakh), 27 Oct - 12 Nov 2026",
    picks=t10._picks([
        # (key, rank in the Top 10 books by net P&L, no Rank score, trades, mean net bp a trade, name, net
        #  P&L in the Rs 2 lakh Top 10 book) - both books' leaderboards at the 12 Nov close
        ("intra_ha_reversal@15m", 1, None, 9, 2390.5, "intra_ha_reversal · 15m", 79870.79),
        ("it_fake_breakout@15m", 2, None, 7, 2235.1, "it_fake_breakout · 15m", 59579.89),
    ]),
    max_open=2,
    notes=_BEST_NOTES,
)

_FACTORY_DESK = t10.Desk(
    key="factory:index-buying", label="Index Option Buying · Strategy Factory", route="/prelive",
    instrument="NIFTY options bought: the ATM CE on a BUY signal, the ATM PE on a SELL (the Strategy Factory "
               "tab's own trades)",
    cost_basis="the premium paid at the ask (premium x lot size a lot)",
    board="the Strategy Factory tab's Rank on Index Option Buying (146 strategies with closed trades, 28 Oct - "
          "12 Nov 2026)",
    picks=(), load=_load_factory, pnl=t10._bought_option_pnl, mark=t10._bought_option_mark, max_open=1,
)

# /api/strategy-rank/factory-desks?desk=index-buying at PICKED_AT: (strategy id, rank, score, closed trades,
# net bp a trade, name, net P&L of the tab's own 1-lot trades). Ranks 1-20 as on the owner's screenshot.
_SF_TOP10 = t10._picks([
    ("SF0400", 1, 60.8, 15, 2023.18, "MACD Histogram Turn · 5m", 24147.70),
    ("SF0107", 2, 60.7, 8, 4338.73, "Engulfing Candle · 15m", 26578.54),
    ("SF0474", 3, 59.2, 8, 4966.10, "Pullback + EMA + RSI + VWAP · 30m", 37694.77),
    ("SF0330", 4, 59.2, 8, 4966.10, "Trend Pullback to EMA · 30m", 37694.77),
    ("SF0329", 5, 59.0, 11, 3273.70, "Trend Pullback to EMA · 15m", 34481.93),
    ("SF0401", 6, 58.0, 8, 3916.64, "MACD Histogram Turn · 15m", 29356.84),
    ("SF0113", 7, 57.9, 10, 1964.19, "Hammer / Shooting Star · 1m", 11895.35),
    ("SF0473", 8, 57.1, 10, 3250.00, "Pullback + EMA + RSI + VWAP · 15m", 28084.21),
    ("SF0367", 9, 56.9, 6, 4172.12, "RSI Trend Regime (40/60) · 1m", 17763.29),
    ("SF0179", 10, 56.8, 11, 2434.42, "Three Soldiers / Crows · 15m", 21172.03),
])
_SF_TOP10_20 = t10._picks([
    ("SF0116", 11, 56.2, 8, 3797.42, "Hammer / Shooting Star · 30m", 18162.39),
    ("SF0416", 12, 56.1, 10, 2743.75, "Supertrend Flip · 5m", 32691.84),
    ("SF0392", 13, 56.1, 9, 3340.42, "MACD Signal Cross · 5m", 29542.72),
    ("SF0229", 14, 55.9, 6, 5220.25, "Keltner Breakout · 45m", 24717.48),
    ("SF0108", 15, 55.4, 4, 6621.32, "Engulfing Candle · 30m", 22904.01),
    ("SF0230", 16, 54.5, 4, 7678.34, "Keltner Breakout · 1h", 27125.52),
    ("SF0533", 17, 54.5, 5, 3326.88, "Fib 61.8% + RSI + HTF Trend · 15m", 10915.92),
    ("SF0226", 18, 54.1, 11, 2376.87, "Keltner Breakout · 5m", 15410.48),
    ("SF0369", 19, 54.0, 5, 3309.59, "RSI Trend Regime (40/60) · 15m", 13828.23),
    ("SF0109", 20, 53.8, 4, 5751.71, "Engulfing Candle · 45m", 19524.14),
])

BOOKS: dict[str, Book] = {
    "best2L": Book(
        key="best2L", label="Best Strategies of Top 10 · ₹2 lakh", desk=_BEST_DESK,
        capital=200000.0, slots=2, per_strategy=False,
        pick_rule="the two that made the most in both of this page's Top 10 Paper Trade accounts (₹2 lakh and ₹10 "
                  "lakh) from 27 Oct to 12 Nov 2026"),
    "sf_top10": Book(
        key="sf_top10", label="Top 10 Performing Strategies · ₹10 lakh each",
        desk=dataclasses.replace(_FACTORY_DESK, picks=_SF_TOP10, notes=_FACTORY_NOTES + (
            "SF0474 and SF0330 have taken the same 8 trades so far, and SF0329 and SF0473 share 8 of theirs, so "
            "this book often holds one trade twice.",
            "SF0113 and SF0367 are 1-minute strategies. The tab took no 1-minute entries on 12 Nov (it reported "
            "its 1-minute NIFTY bars behind), and they trade only while that feed is current.")),
        capital=1000000.0, slots=1, per_strategy=True,
        pick_rule="ranks 1-10 on the Strategy Factory tab's Rank (146 strategies with closed trades, 28 Oct - 12 Nov "
                  "2026)"),
    "sf_top10_20": Book(
        key="sf_top10_20", label="Top 10-20 Performing Strategies · ₹10 lakh each",
        desk=dataclasses.replace(_FACTORY_DESK, picks=_SF_TOP10_20, notes=_FACTORY_NOTES),
        capital=1000000.0, slots=1, per_strategy=True,
        pick_rule="ranks 11-20 on the Strategy Factory tab's Rank (146 strategies with closed trades, 28 Oct - 12 Nov "
                  "2026)"),
}
BOOK_KEYS = list(BOOKS)
BOOK_LABEL = {k: b.label for k, b in BOOKS.items()}


def normalize_book(book: str | None) -> str:
    return book if book in BOOKS else BOOK_KEYS[0]


# -- state ------------------------------------------------------------------------------------------


async def _start(book: str) -> datetime:
    """When the book began copying: set once, on its first cycle. Nothing earlier is copied."""
    key = f"start:{book}"
    doc = await STATE.find_one({"_id": key})
    if doc and doc.get("started_at"):
        return naive_utc(doc["started_at"])
    await STATE.update_one({"_id": key}, {"$setOnInsert": {"started_at": t10._now(), "book": book}}, upsert=True)
    doc = await STATE.find_one({"_id": key})
    return naive_utc(doc["started_at"])


def _skip_doc(book: str, acct: str, day: str) -> str:
    return f"skipped:{book}:{acct}:{day}"


async def _decided(book: str, acct: str, parents: list[dict]) -> set[str]:
    """Parents this account has already taken or skipped."""
    ids = [p["position_id"] for p in parents]
    out: set[str] = set()
    async for r in POSITIONS.find({"book": book, "parent_position_id": {"$in": ids}}, {"parent_position_id": 1}):
        out.add(r["parent_position_id"])
    days = sorted({p.get("opened_on") for p in parents if p.get("opened_on")})
    if days:
        async for s in STATE.find({"_id": {"$in": [_skip_doc(book, acct, day) for day in days]}}, {"ids": 1}):
            out.update(s.get("ids") or [])
    return out


async def _totals(book: str, acct: str) -> tuple[float, float]:
    """The account's realised P&L and the capital its open positions tie up."""
    realized = deployed = 0.0
    async for r in POSITIONS.find({"book": book, "account": acct},
                                  {"status": 1, "realized_pnl": 1, "capital_deployed": 1}):
        if r.get("status") == "OPEN":
            deployed += r.get("capital_deployed") or 0.0
        else:
            realized += r.get("realized_pnl") or 0.0
    return realized, deployed


async def _closed_after(book: str, acct: str, t0: datetime | None) -> list[dict]:
    if t0 is None:
        return []
    return [r async for r in POSITIONS.find(
        {"book": book, "account": acct, "status": "CLOSED", "closed_at": {"$gt": t0}},
        {"symbol": 1, "capital_deployed": 1, "realized_pnl": 1, "opened_at": 1, "closed_at": 1})]


# -- the copy ---------------------------------------------------------------------------------------


async def _sync_account(b: Book, acct: str, keys: set[str], entries: bool) -> dict:
    """One account of the book: the desk's trades of its strategies, replayed in time order."""
    d = b.desk
    floor = max(await _start(b.key), naive_utc(t10._now()) - LOOKBACK)
    open_rows = [r async for r in POSITIONS.find({"book": b.key, "account": acct, "status": "OPEN"})]
    pointed = [r["parent_position_id"] for r in open_rows if r.get("parent_position_id")]
    parents = [p for p in await d.load(floor, keys, pointed)
               if p.get("opened_at") is not None and (p["opened_at"] >= floor or p["position_id"] in pointed)]
    parents.sort(key=lambda p: (p["opened_at"], p["position_id"]))
    realized, deployed = await _totals(b.key, acct)
    decided = await _decided(b.key, acct, parents) if entries else set()
    t0 = pending_since(parents, decided, open_rows, SOURCE_TAG) if entries else None
    closed_rows = await _closed_after(b.key, acct, t0) if entries else []
    plan = plan_book(capital=b.capital, realized=realized, deployed=deployed, open_rows=open_rows,
                     parents=parents, decided=decided, breaker_tripped=False, entries=entries,
                     max_open=b.slots, net_fn=t10._net_fn(d), source_tag=SOURCE_TAG, closed_rows=closed_rows)

    n = {"opened": 0, "closed": 0, "skipped": 0, "marked": 0}
    for c in plan["closes"]:
        res = await POSITIONS.update_one({"_id": c["row"]["_id"], "status": "OPEN"},
                                         {"$set": t10._close_fields(c["parent"], c)})
        n["closed"] += res.modified_count
    for o in plan["opens"]:
        p = o["parent"]
        doc = t10._row(d, b.key, p, o["qty"], o["spend"])
        doc.update({"source": SOURCE_TAG, "account": acct,
                    "allocation": b.capital if b.per_strategy else None})
        if o["close"] is not None:
            doc.update(t10._close_fields(p, o["close"]))
        try:
            await POSITIONS.insert_one(doc)
        except DuplicateKeyError:
            continue
        n["opened"] += 1
        n["closed"] += 1 if o["close"] is not None else 0
    per: dict[str, dict[str, int]] = {}
    ids_by_day: dict[str, list[str]] = {}
    for s in plan["skips"]:
        p = s["parent"]
        k = per.setdefault(p["key"], {})
        k[s["reason"]] = k.get(s["reason"], 0) + 1
        ids_by_day.setdefault(p.get("opened_on") or "", []).append(p["position_id"])
        n["skipped"] += 1
    for day, ids in ids_by_day.items():
        await STATE.update_one({"_id": _skip_doc(b.key, acct, day)},
                               {"$addToSet": {"ids": {"$each": ids}},
                                "$set": {"book": b.key, "account": acct, "day": day}}, upsert=True)
    for key, counts in per.items():
        await SCORES.update_one({"book": b.key, "key": key},
                                {"$inc": {f"skipped.{r}": v for r, v in counts.items()},
                                 "$set": {"updated_at": t10._now()}}, upsert=True)

    by_id = {p["position_id"]: p for p in parents}
    closed_now = {c["row"]["_id"] for c in plan["closes"]}
    for r in open_rows:
        if r["_id"] in closed_now:
            continue
        p = by_id.get(r.get("parent_position_id"))
        if not p or p.get("status") != "OPEN":
            continue
        u = d.mark(p, int(r["qty"]))
        if u is None:
            continue
        await POSITIONS.update_one({"_id": r["_id"], "status": "OPEN"},
                                   {"$set": {"ltp": p.get("px_ltp"), "unrealized_pnl": u, "updated_at": t10._now()}})
        n["marked"] += 1
    return n


_lock = asyncio.Lock()
_indexed = False


async def sync(entries: bool = True, only: str | None = None) -> dict:
    """Copy every book's desk once."""
    global _indexed
    if not _indexed:
        _indexed = True
        await ensure_indexes()
    out: dict = {}
    async with _lock:
        for key, b in BOOKS.items():
            if only and key != only:
                continue
            for acct, keys in b.accounts():
                try:
                    out[f"{key}:{acct}"] = await _sync_account(b, acct, keys, entries)
                except Exception as exc:  # noqa: BLE001 - one account's bad row must not stop the rest
                    logger.warning("[prelive_pick_books] %s %s failed: %s", key, acct, exc, exc_info=True)
                    out[f"{key}:{acct}"] = {"error": str(exc)[:200]}
            try:
                await _snapshot(b)
            except Exception:  # noqa: BLE001
                logger.warning("[prelive_pick_books] snapshot %s failed", key, exc_info=True)
    return out


async def _snapshot(b: Book) -> None:
    """An equity point at most every 15 minutes, or when realised P&L moves."""
    s = await summary(b.key)
    last = await EQUITY.find_one({"book": b.key}, sort=[("ts", -1)])
    stale = last is None or (naive_utc(t10._now()) - naive_utc(last["ts"])) > SNAPSHOT_EVERY
    if stale or abs((last or {}).get("realized", 0.0) - s["realized_pnl"]) > 0.005:
        await EQUITY.insert_one({"ts": t10._now(), "book": b.key, "equity": s["equity"],
                                 "realized": s["realized_pnl"], "unrealized": s["unrealized_pnl"],
                                 "open_positions": s["open_positions"]})


def _nse_minutes() -> bool:
    t = datetime.now(t10.IST)
    if t.weekday() >= 5:
        return False
    hm = t.hour * 60 + t.minute
    return 9 * 60 + 10 <= hm <= 15 * 60 + 45


async def loop() -> None:
    """Every minute through the NSE session, every ten minutes otherwise (late closes still land)."""
    await asyncio.sleep(45)
    while True:
        if ENABLED:
            try:
                await sync(entries=True)
            except Exception:  # noqa: BLE001
                logger.warning("[prelive_pick_books] cycle failed", exc_info=True)
        await asyncio.sleep(60 if _nse_minutes() else 600)


# -- read models: the Top-10 / rank-band shapes ------------------------------------------------------


async def summary(book: str) -> dict:
    b = BOOKS[normalize_book(book)]
    d = b.desk
    cap = b.total_capital
    realized = unrealized = deployed = fees = gross = 0.0
    open_n = closed_n = wins = 0
    async for r in POSITIONS.find({"book": b.key}, {"status": 1, "capital_deployed": 1, "unrealized_pnl": 1,
                                                    "realized_pnl": 1, "fees": 1, "gross_pnl": 1}):
        if r.get("status") == "OPEN":
            open_n += 1
            deployed += r.get("capital_deployed") or 0.0
            unrealized += r.get("unrealized_pnl") or 0.0
        else:
            closed_n += 1
            v = r.get("realized_pnl") or 0.0
            realized += v
            wins += 1 if v > 0 else 0
            fees += r.get("fees") or 0.0
            gross += r.get("gross_pnl") or 0.0
    skipped = {k: 0 for k in SKIP_REASONS}
    async for s in SCORES.find({"book": b.key}, {"skipped": 1}):
        for k, v in (s.get("skipped") or {}).items():
            if k in skipped:
                skipped[k] += int(v or 0)
    start = await STATE.find_one({"_id": f"start:{b.key}"})
    started = start.get("started_at") if start else None
    equity = cap + realized + unrealized
    n = len(b.picks)
    return {
        "book": b.key, "books": BOOK_KEYS, "label": b.label, "book_labels": BOOK_LABEL, "module": MODULE,
        "desk": d.key, "desk_label": d.label, "mode": "paper", "enabled": ENABLED,
        "instrument": d.instrument, "cost_basis": d.cost_basis, "board": d.board, "pick_rule": b.pick_rule,
        "notes": list(d.notes), "picked_at": PICKED_AT, "roster": list(d.roster), "strategies": n,
        "board_ranks": [p.rank for p in b.picks], "per_strategy": b.per_strategy,
        "per_strategy_capital": b.capital if b.per_strategy else None,
        "positions_per_strategy": b.slots if b.per_strategy else None,
        "max_open_positions": b.slots * (n if b.per_strategy else 1),
        "position_cap": round(b.capital / max(b.slots, 1), 2),
        "desk_capital": cap, "equity": round(equity, 2), "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2), "gross_pnl": round(gross, 2), "fees": round(fees, 2),
        "deployed": round(deployed, 2), "available_cash": round(cap + realized - deployed, 2),
        "open_positions": open_n, "closed_positions": closed_n, "wins": wins,
        "roi_pct": round((equity - cap) / cap * 100, 4) if cap else 0.0, "skipped": skipped,
        "copying_since": (naive_utc(started).replace(tzinfo=timezone.utc).isoformat() if started else None),
    }


async def leaderboard(book: str) -> list[dict]:
    """The picks in rank order: each one's record in this book (and its own account where it has one)."""
    b = BOOKS[normalize_book(book)]
    rec: dict[str, dict] = {p.key: {"trades": 0, "wins": 0, "net": 0.0, "gross": 0.0, "fees": 0.0, "open": 0,
                                    "unrealized": 0.0, "deployed": 0.0} for p in b.picks}
    async for r in POSITIONS.find({"book": b.key}, {"key": 1, "status": 1, "unrealized_pnl": 1, "capital_deployed": 1,
                                                    "realized_pnl": 1, "gross_pnl": 1, "fees": 1}):
        x = rec.get(r.get("key"))
        if x is None:
            continue
        if r.get("status") == "OPEN":
            x["open"] += 1
            x["unrealized"] += r.get("unrealized_pnl") or 0.0
            x["deployed"] += r.get("capital_deployed") or 0.0
            continue
        v = r.get("realized_pnl") or 0.0
        x["trades"] += 1
        x["wins"] += 1 if v > 0 else 0
        x["net"] += v
        x["gross"] += r.get("gross_pnl") or 0.0
        x["fees"] += r.get("fees") or 0.0
    sk: dict[str, dict] = {}
    async for s in SCORES.find({"book": b.key}, {"key": 1, "skipped": 1}):
        sk[s["key"]] = {k: int((s.get("skipped") or {}).get(k, 0)) for k in SKIP_REASONS}
    base = b.capital if b.per_strategy else b.total_capital
    rows = []
    for p in b.picks:
        x = rec[p.key]
        skipped = sk.get(p.key) or {k: 0 for k in SKIP_REASONS}
        rows.append({
            "key": p.key, "strategy_id": p.key, "name": p.name,
            "picked_rank": p.rank, "picked_score": p.score, "picked_trades": p.trades,
            "picked_bp": p.bp, "picked_net_pnl": p.net,
            "trades": x["trades"], "wins": x["wins"],
            "win_rate": round(x["wins"] / x["trades"], 4) if x["trades"] else 0.0,
            "net_pnl": round(x["net"], 2), "gross_pnl": round(x["gross"], 2), "fees": round(x["fees"], 2),
            "unrealized_pnl": round(x["unrealized"], 2), "deployed": round(x["deployed"], 2),
            "allocation": b.capital if b.per_strategy else None,
            "equity": round(b.capital + x["net"] + x["unrealized"], 2) if b.per_strategy else None,
            # its own account's return, or (one shared account) its share of the book
            "roi_pct": round((x["net"] + x["unrealized"]) / base * 100, 4) if base else 0.0,
            "open_positions": x["open"], "skipped": skipped, "skipped_total": sum(skipped.values()),
        })
    return rows


async def positions(book: str, status: str = "OPEN", limit: int = 200) -> list[dict]:
    b = normalize_book(book)
    q: dict = {"book": b}
    if status.upper() != "ALL":
        q["status"] = status.upper()
    sort_key = "opened_at" if status.upper() == "OPEN" else "closed_at"
    return [t10._jsonable(r) async for r in POSITIONS.find(q).sort(sort_key, -1).limit(limit)]


def books() -> list[dict]:
    return [{"book": b.key, "label": b.label, "capital": b.total_capital, "per_strategy": b.per_strategy,
             "per_strategy_capital": b.capital if b.per_strategy else None, "slots": b.slots,
             "desk": b.desk.key, "pick_rule": b.pick_rule, "picked_at": PICKED_AT,
             "picks": [{"key": p.key, "rank": p.rank, "score": p.score, "trades": p.trades, "bp": p.bp,
                        "name": p.name, "net": p.net} for p in b.picks]} for b in BOOKS.values()]


async def ensure_indexes() -> None:
    """Best effort: an index failure must never stop the books."""
    try:
        await POSITIONS.create_index([("book", 1), ("parent_position_id", 1)], name="pb_parent_unique", unique=True)
        await POSITIONS.create_index([("book", 1), ("account", 1), ("status", 1)], name="pb_book_account_status")
        await SCORES.create_index([("book", 1), ("key", 1)], name="pb_score_key", unique=True)
        await EQUITY.create_index([("book", 1), ("ts", -1)], name="pb_equity_ts")
    except Exception:  # noqa: BLE001
        logger.warning("[prelive_pick_books] index creation skipped", exc_info=True)
