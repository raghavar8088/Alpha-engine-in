"""Top-10 paper books on six more desks (2026-10-27).

The owner asked for Rs 2 lakh and Rs 10 lakh paper accounts on the top 10 of each strategy desk's
leaderboard, as was done for Intraday Stocks the day before (live_intraday_engine.TOP10_PICKS for the
Tournament, pattern_books_engine.TOP10_PICKS for Patterns). Those live in their own desks' modules.
These six share one engine:

    zero-hero      Zero Hero Trades                         expiry-day deep-OTM index options, bought
    nifty-scalp    NIFTY 50 Option Scalping                 near-expiry NIFTY options, bought
    prelive        Index Option Buying (NIFTY 50 tournament) ATM NIFTY options, bought
    stock-buying   Stock Pre-Live · Buying                  stock options, bought
    stock-selling  Stock Pre-Live · Selling                 stock option credit spreads, sold
    commodity      Commodity Trading                        MCX futures, both sides

Index Option Selling's two are books in selling_paper_books, whose structure and margin rules they
need. Gold Desk and Indian Index Intraday have none: Gold's board is its nine-template pre-registered
forward test (H1), and Index Intraday has no strategy running to copy.

THE SAME RULES AS THE INTRADAY STOCKS TOP-10 BOOKS
- The ten are FROZEN as ranked when picked (strategy_rank, the board the owner looked at); they are
  not re-picked as ranks move. Each keeps its rank, score, trades and net return a trade at the pick.
- The books COPY the desk's own trades of those ten - its entry and exit, at its prices - and never
  re-scan or call a broker. Signals from the desk's other strategies are not offered.
- One account per book: at most `max_open` positions (5; Zero Hero 10, its desk's own 10%-a-trade
  cap), each up to capital / max_open; WHOLE lots; never two positions in one contract (one stock /
  one commodity on the stock and MCX desks); a position ties up what a real account would: the
  premium for a bought option, the spread's maximum loss for a sold spread, the broker's measured
  margin for an MCX future.
- Costs are charged on the BOOK's quantity at Angel One's rate card (options; MCX).
- A book starts when it first runs and never backfills. Replay, sizing, slots and the rewind that
  keeps slots, cash and one-contract honest on the trades' own clock are live_intraday_mirror.plan_book.

The stock desks' books skip an entry made on its own contract's expiry day: the Stock Pre-Live audit
(2026-10-07) found the buying desk's record was mostly contracts bought and closed minutes apart on
their expiry day, and the selling books skip the same. Zero Hero is the opposite - it trades only on
expiry day, so nothing is skipped there.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.core.db import db
from app.services.book_reset import naive_utc
from app.services.live_intraday_mirror import pending_since, plan_book

logger = logging.getLogger("top10_books")

IST = timezone(timedelta(hours=5, minutes=30))
POSITIONS = db["top10_book_positions"]
SCORES = db["top10_book_scores"]
STATE = db["top10_book_state"]
EQUITY = db["top10_book_equity"]
SOURCE_TAG = "top10"
BOOK_CAPITAL: dict[str, float] = {
    "top2L": float(os.getenv("TOP10_CAPITAL_2L", "200000")),
    "top10L": float(os.getenv("TOP10_CAPITAL_10L", "1000000")),
}
BOOKS = list(BOOK_CAPITAL)
BOOK_LABEL = {"top2L": "Top 10 Paper Trade · ₹2 lakh", "top10L": "Top 10 Paper Trade · ₹10 lakh"}
SKIP_REASONS = ("full", "symbol_held", "price_above_cap", "no_cash", "expiry_day")
ENABLED = os.getenv("TOP10_BOOKS_ENABLED", "1").lower() not in ("0", "false", "")
# How far back a pass reads the desk. Every pass decides all it sees, so only a backend that was
# down this long could miss a trade; the window keeps a pass from re-reading weeks of trades.
LOOKBACK = timedelta(days=int(os.getenv("TOP10_LOOKBACK_DAYS", "10")))
PICKED_AT = "2026-10-27T00:10:00+05:30"      # every board read after the 26 Oct close


@dataclass
class Fees:
    total: float
    parts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {**{k: round(v, 2) for k, v in self.parts.items()}, "total": round(self.total, 2)}


def _fees_of(fb) -> Fees:
    """angel_fees.FeeBreakdown or an option_fees dict -> Fees."""
    if isinstance(fb, dict):
        return Fees(float(fb.get("total") or 0.0), {k: float(v) for k, v in fb.items()
                                                    if k != "total" and isinstance(v, (int, float))})
    d = fb.as_dict() if hasattr(fb, "as_dict") else {}
    return Fees(float(getattr(fb, "total", d.get("total", 0.0)) or 0.0),
                {k: float(v) for k, v in d.items() if k not in ("total", "product") and isinstance(v, (int, float))})


@dataclass(frozen=True)
class Pick:
    key: str
    rank: int
    score: float | None       # its Rank score at the pick; None where the pick was not by Rank
    trades: int
    bp: float | None          # net return a trade, basis points of what it deployed
    name: str
    net: float | None = None  # its net P&L on the desk at the pick, in the desk's own sizing


@dataclass
class Desk:
    key: str
    label: str
    route: str
    instrument: str
    cost_basis: str
    picks: tuple[Pick, ...]
    load: Callable[[datetime, set, list], Awaitable[list[dict]]]
    pnl: Callable[[dict, int], tuple[float, Fees]]
    mark: Callable[[dict, int], float | None]
    max_open: int = 5
    skip_expiry_day: bool = False
    board: str = ""               # what the picks were ranked on
    notes: tuple[str, ...] = ()

    @property
    def roster(self) -> tuple[str, ...]:
        return tuple(p.key for p in self.picks)


# -- time ---------------------------------------------------------------------------


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


def _ist_day(v) -> str | None:
    d = _dt(v)
    return (d + timedelta(hours=5, minutes=30)).date().isoformat() if d else None


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


# -- bought options (Zero Hero, NIFTY scalp, the NIFTY tournament, stock buying) ----------


def _option_parent(*, pid: str, key: str, name: str, symbol: str, label: str, lot_size: int,
                   entry: float, exit_px: float | None, ltp: float | None, opened_at, closed_at,
                   status: str, expiry: str | None, opened_on: str | None = None,
                   closed_on: str | None = None, exit_reason: str | None = None) -> dict:
    closed = status == "CLOSED" and exit_px is not None
    return {
        "position_id": pid, "key": key, "strategy_id": key, "strategy_name": name,
        "symbol": symbol, "label": label, "side": "BUY", "lot_size": int(lot_size or 1),
        "opened_at": _dt(opened_at), "closed_at": _dt(closed_at) if closed else None,
        "opened_on": opened_on or _ist_day(opened_at),
        "closed_on": (closed_on or _ist_day(closed_at)) if closed else None,
        "status": "CLOSED" if closed else "OPEN",
        "entry_price": round(entry * int(lot_size or 1), 4),     # what one lot costs the book
        "exit_price": exit_px if closed else None,
        "px_entry": entry, "px_exit": exit_px if closed else None, "px_ltp": ltp,
        "expiry": expiry, "exit_reason": exit_reason,
    }


def _on(day):
    """A stored ISO day as the date Angel's rate schedules take (None: today's rates)."""
    try:
        return datetime.fromisoformat(str(day)[:10]).date() if day else None
    except ValueError:
        return None


def _bought_option_pnl(p: dict, lots: int) -> tuple[float, Fees]:
    from app.services.angel_fees import option_round_trip
    gross = (p["px_exit"] - p["px_entry"]) * p["lot_size"] * lots
    fb = option_round_trip(p["px_entry"], max(p["px_exit"], 0.0), lots, p["lot_size"], on=_on(p.get("closed_on")))
    return round(gross, 2), _fees_of(fb)


def _bought_option_mark(p: dict, lots: int) -> float | None:
    if p.get("px_ltp") is None:
        return None
    return round((_f(p["px_ltp"]) - p["px_entry"]) * p["lot_size"] * lots, 2)


def _zero_hero_parent(p: dict) -> dict | None:
    if not p.get("entry_premium") or not p.get("lot_size"):
        return None
    return _option_parent(
            pid=p["position_id"], key=p["strategy_id"], name=p.get("strategy_name") or p["strategy_id"],
            symbol=str(p.get("token") or p.get("angel_tradingsymbol")), label=p.get("angel_tradingsymbol") or "",
            lot_size=int(p["lot_size"]), entry=_f(p["entry_premium"]),
            exit_px=None if p.get("exit_premium") is None else _f(p["exit_premium"]),
            ltp=p.get("ltp"), opened_at=p.get("opened_at"), closed_at=p.get("closed_at"),
            status=p.get("status") or "OPEN", expiry=p.get("expiry"), opened_on=p.get("session"),
            exit_reason=p.get("exit_reason"))


def _nifty_scalp_parent(p: dict) -> dict | None:
    if not p.get("entry_premium") or not p.get("lot_size"):
        return None
    return _option_parent(
            pid=p["position_id"], key=p["strategy_id"], name=p.get("strategy_name") or p["strategy_id"],
            symbol=str(p.get("angel_token") or p.get("symbol")), label=p.get("symbol") or "",
            lot_size=int(p["lot_size"]), entry=_f(p["entry_premium"]),
            exit_px=None if p.get("exit_premium") is None else _f(p["exit_premium"]),
            ltp=p.get("ltp"), opened_at=p.get("opened_at"), closed_at=p.get("closed_at"),
            status=p.get("status") or "OPEN", expiry=p.get("expiry"), opened_on=p.get("opened_on"),
            closed_on=p.get("closed_on"), exit_reason=p.get("exit_reason"))


def _by_strategy(coll_name: str, normalize):
    """A loader for a desk with one positions collection keyed by strategy_id."""
    async def load(since: datetime, keys: set, pointed: list) -> list[dict]:
        q = {"strategy_id": {"$in": list(keys)}, "$or": [{"opened_at": {"$gte": since}},
                                                           {"position_id": {"$in": pointed}}]}
        out = []
        async for p in db[coll_name].find(q):
            x = normalize(p)
            if x is not None:
                out.append(x)
        return out
    return load


def _prelive_prices(t: dict) -> tuple[float, float | None]:
    """The tournament's REAL-MONEY prices - what its Rank is computed on: bought at the ask, sold
    at the bid (from the order book; an estimated half-spread where the book was not recorded)."""
    from app.services import prelive_stats as ps
    hs = lambda p: max(0.05, p * ps.EST_HALF_SPREAD_PCT)  # noqa: E731
    e = _f(t.get("real_entry")) or _f(t.get("entry_ask")) or (_f(t.get("entry_premium")) + hs(_f(t.get("entry_premium"))))
    x = None
    if t.get("exit_premium") is not None or t.get("real_exit") is not None:
        x = _f(t.get("real_exit")) or _f(t.get("exit_bid")) or max(0.05, _f(t.get("exit_premium")) - hs(_f(t.get("exit_premium"))))
    return e, x


async def _load_prelive(since: datetime, keys: set, pointed: list) -> list[dict]:
    """Open positions from prelive_positions, closed ones from prelive_trades (one row per closed
    trade, written by the prelive-service daemon). The two are the same trade when key and entry
    time agree, so that pair is the parent's id."""
    from app.services import prelive_stats as ps
    out: dict[str, dict] = {}
    since_iso = since.replace(tzinfo=timezone.utc).isoformat()

    def build(t: dict, closed: bool) -> dict | None:
        key, ets = t.get("key"), _dt(t.get("entry_ts") or t.get("opened_at"))
        if not key or ets is None or not t.get("entry_premium"):
            return None
        # An open position keeps its entry time as an ISO string (microseconds), the closed trade as a
        # Mongo date (milliseconds): the id that pairs them is cut to the millisecond.
        ets = ets.replace(microsecond=(ets.microsecond // 1000) * 1000)
        e, x = _prelive_prices(t)
        lot = int(t.get("lot_size") or ps.LOT_NOW)
        ltp = t.get("mark") if t.get("mark") is not None else t.get("ltp")
        return _option_parent(
            pid=f"{key}|{ets.isoformat()}", key=key, name=key,
            symbol=str(t.get("security_id") or f"{t.get('strike')}{t.get('option_type')}"),
            label=f"NIFTY {int(_f(t.get('strike')))} {t.get('option_type') or ''} {t.get('expiry') or ''}".strip(),
            lot_size=lot, entry=e, exit_px=x if closed else None,
            ltp=None if ltp is None else _f(ltp), opened_at=ets,
            closed_at=t.get("exit_ts") if closed else None,
            status="CLOSED" if closed else "OPEN", expiry=t.get("expiry"),
            opened_on=t.get("session") or _ist_day(ets), exit_reason=t.get("exit_reason"))

    for coll, closed in ((db["prelive_trades"], True), (db["prelive_positions"], False)):
        q = {"key": {"$in": list(keys)}, "$or": [{"entry_ts": {"$gte": since}}, {"entry_ts": {"$gte": since_iso}}]}
        async for t in coll.find(q):
            p = build(t, closed)
            if p is not None and (closed or p["position_id"] not in out):
                out[p["position_id"]] = p
    if pointed:                                  # an open book row whose parent fell out of the window
        missing = [i for i in pointed if i not in out]
        for pid in missing:
            key, _, ets = pid.partition("|")
            t0 = _dt(ets)
            t = None
            if t0 is not None:
                t = await db["prelive_trades"].find_one(
                    {"key": key, "entry_ts": {"$gte": t0, "$lt": t0 + timedelta(milliseconds=1)}})
            t = t or await db["prelive_positions"].find_one({"key": key})
            if t:
                p = build(t, t.get("exit_ts") is not None)
                if p:
                    out[pid] = p
    return list(out.values())


def _stock_parent(p: dict) -> dict | None:
    side = p.get("side")
    if side not in ("buying", "selling"):
        return None
    lots, lot_size = int(p.get("lots") or 1), int(p.get("lot_size") or 0)
    if not lot_size or not p.get("entry_premium"):
        return None
    status = p.get("status") or "OPEN"
    x = None if p.get("exit_premium") is None else _f(p["exit_premium"])
    base = _option_parent(
        pid=p["position_id"], key=p["strategy_id"], name=p.get("strategy_name") or p["strategy_id"],
        # one stock at a time, as the Intraday Stocks books
        symbol=p.get("symbol") or str(p.get("short_token")), label=p.get("angel_tradingsymbol") or "",
        lot_size=lot_size, entry=_f(p["entry_premium"]), exit_px=x, ltp=p.get("ltp"),
        opened_at=p.get("opened_at"), closed_at=p.get("closed_at"), status=status,
        expiry=p.get("expiry"), opened_on=p.get("opened_on"), exit_reason=p.get("exit_reason"))
    if side == "selling":
        base["side"] = "SELL"
        base["label"] = f"{p.get('angel_tradingsymbol') or ''} · {p.get('structure') or ''}".strip(" ·")
        base["max_loss_per_lot"] = _f(p.get("capital_deployed")) / max(lots, 1)
        base["entry_price"] = round(base["max_loss_per_lot"], 4)      # the margin one lot reserves
        base["px_wing"] = _f(p.get("entry_wing_premium"))
    return base


def _stock_loader(side: str):
    async def load(since: datetime, keys: set, pointed: list) -> list[dict]:
        q = {"side": side, "strategy_id": {"$in": list(keys)},
             "$or": [{"opened_at": {"$gte": since}}, {"position_id": {"$in": pointed}}]}
        out = []
        async for p in db["stock_desk_positions"].find(q):
            x = _stock_parent(p)
            if x is not None:
                out.append(x)
        return out
    return load


def _sold_spread_pnl(p: dict, lots: int) -> tuple[float, Fees]:
    """The desk's own record counts only the SOLD leg's premium (it does not record the protective
    wing's exit), so the books do too; the wing's buy and its sale at zero are charged.

    Angel's option card is written buy-then-sell, so the short leg passes its buy-back as the buy
    and its sale as the sell (STT on the sale, stamp duty on the buy-back); a buy-back of nothing
    is floored at one tick so the leg is still charged."""
    from app.services.angel_fees import option_round_trip
    gross = (p["px_entry"] - p["px_exit"]) * p["lot_size"] * lots
    short = _fees_of(option_round_trip(max(p["px_exit"], 0.05), p["px_entry"], lots, p["lot_size"],
                                       on=_on(p.get("closed_on"))))
    wing = _fees_of(option_round_trip(p.get("px_wing") or 0.05, 0.0, lots, p["lot_size"],
                                      on=_on(p.get("closed_on")))) if (p.get("px_wing") or 0) > 0 else Fees(0.0)
    parts = {k: short.parts.get(k, 0.0) + wing.parts.get(k, 0.0) for k in set(short.parts) | set(wing.parts)}
    return round(gross, 2), Fees(short.total + wing.total, parts)


def _sold_spread_mark(p: dict, lots: int) -> float | None:
    if p.get("px_ltp") is None:
        return None
    return round((p["px_entry"] - _f(p["px_ltp"])) * p["lot_size"] * lots, 2)


# -- MCX futures (Commodity Trading) --------------------------------------------------------


def _commodity_parent(p: dict) -> dict | None:
    from app.services.commodity_positions import margin_pct_for, multiplier
    sym = p.get("symbol")
    entry = _f(p.get("entry_touch")) or _f(p.get("entry_price"))
    if not sym or entry <= 0:
        return None
    try:
        mult = int(multiplier(sym) or 0)
        margin_rate = float(margin_pct_for(sym))
    except Exception:  # noqa: BLE001 - a contract the shared specs do not know is skipped
        return None
    if mult <= 0 or margin_rate <= 0:
        return None
    real = p.get("real") or {}
    status = p.get("status") or "OPEN"
    x = _f(real.get("exit")) or (None if p.get("exit_price") is None else _f(p["exit_price"]))
    closed = status == "CLOSED" and x is not None
    inst = p.get("instrument") or {}
    return {
        "position_id": p["position_id"], "key": p["strategy_id"], "strategy_id": p["strategy_id"],
        "strategy_name": p.get("strategy_name") or p["strategy_id"],
        "symbol": sym,                              # one commodity at a time
        "label": inst.get("symbol") or p.get("display_name") or sym,
        "side": p.get("side") or "BUY", "lot_size": mult, "multiplier": mult,
        "opened_at": _dt(p.get("opened_at")), "closed_at": _dt(p.get("closed_at")) if closed else None,
        "opened_on": p.get("opened_on") or _ist_day(p.get("opened_at")),
        "closed_on": (p.get("closed_on") or _ist_day(p.get("closed_at"))) if closed else None,
        "status": "CLOSED" if closed else "OPEN",
        "entry_price": round(margin_rate * entry * mult, 2),   # the broker's margin for one lot
        "exit_price": x if closed else None,
        "px_entry": entry, "px_exit": x if closed else None, "px_ltp": p.get("ltp"),
        "expiry": inst.get("expiry"), "exit_reason": p.get("exit_reason"),
        "honest": p.get("honest"),
    }


def _futures_pnl(p: dict, lots: int) -> tuple[float, Fees]:
    """N lots of the trade's own contract, in at the touch, out at the desk's exit, Angel's MCX card."""
    from app.services.mcx_risk import real_trade
    on = None
    try:
        on = datetime.fromisoformat(p["closed_on"]).date() if p.get("closed_on") else None
    except ValueError:
        on = None
    r = real_trade(p["symbol"], p["side"], p["px_entry"], p["px_exit"], on=on, lots=lots)
    if not r:
        sign = 1 if p["side"] == "BUY" else -1
        return round(sign * (p["px_exit"] - p["px_entry"]) * p["multiplier"] * lots, 2), Fees(0.0)
    return float(r["gross"]), Fees(float(r["fees"]), {"mcx_charges": float(r["fees"])})


def _futures_mark(p: dict, lots: int) -> float | None:
    if p.get("px_ltp") is None:
        return None
    sign = 1 if p["side"] == "BUY" else -1
    return round(sign * (_f(p["px_ltp"]) - p["px_entry"]) * p["multiplier"] * lots, 2)


# -- Strategy Factory: its trades come from its own forward replay -----------------------------
# The Factory has no running paper engine, so app.services.strategy_factory.top10_replay runs its
# ten forward by the backtest's own rules; these adapt that replay's trades to a book.


async def _sf_load(since: datetime, keys: set, pointed: list) -> list[dict]:
    from app.services.strategy_factory import top10_replay as sft
    return await sft.load_parents(since, keys, pointed)


def _sf_pnl(p: dict, lots: int) -> tuple[float, Fees]:
    from app.services.strategy_factory import top10_replay as sft
    gross, fees, parts = sft.parent_pnl(p, lots)
    return gross, Fees(fees, parts)


def _sf_mark(p: dict, lots: int) -> float | None:
    from app.services.strategy_factory import top10_replay as sft
    return sft.parent_mark(p, lots)


# -- the desks and their frozen picks ---------------------------------------------------------


def _picks(rows: list[tuple]) -> tuple[Pick, ...]:
    return tuple(Pick(key=k, rank=r, score=s, trades=n, bp=bp, name=nm, net=net)
                 for k, r, s, n, bp, nm, net in rows)


DESKS: dict[str, Desk] = {
    "zero-hero": Desk(
        key="zero-hero", label="Zero Hero Trades", route="/zero-hero",
        instrument="expiry-day deep-OTM index options, bought",
        cost_basis="the premium paid (premium x lot size a lot)",
        board="the Zero Hero Rank (26 strategies with closed trades)",
        max_open=10,   # its desk caps one ticket at 10% of an account
        load=_by_strategy("zero_hero_positions", _zero_hero_parent), pnl=_bought_option_pnl, mark=_bought_option_mark,
        picks=_picks([
            ("zh_007", 1, 63.0, 12, 11776.54, "NIFTY 0.75% OTM ≤₹8 final momentum 4x", 140858.25),
            ("zh_003", 2, 62.2, 9, 24652.42, "NIFTY 1% OTM ≤₹5 late momentum 5x", 221617.50),
            ("zh_008", 3, 61.6, 8, 24571.87, "NIFTY 1% OTM ≤₹5 final momentum 5x", 195760.50),
            ("zh_006", 4, 61.6, 13, 7150.90, "NIFTY 0.5% OTM ≤₹10 final momentum 3x", 92602.25),
            ("zh_011", 5, 59.6, 9, 11025.07, "NIFTY 0.75% OTM ≤₹8 mid momentum 4x", 98143.50),
            ("zh_002", 6, 58.9, 10, 9918.47, "NIFTY 0.75% OTM ≤₹8 late momentum 4x", 97370.00),
            ("zh_001", 7, 56.8, 7, 6112.96, "NIFTY 0.5% OTM ≤₹10 late momentum 3x", 41795.00),
            ("zh_017", 8, 55.3, 12, 7448.53, "NIFTY 1% OTM ≤₹6 late both 5x", 89963.25),
            ("zh_009", 9, 55.1, 8, 3005.95, "NIFTY 1.5% OTM ≤₹3 final momentum 8x", 24063.00),
            ("zh_014", 10, 53.9, 6, 5601.19, "NIFTY 1.5% OTM ≤₹3 final breakout 8x", 33614.75),
        ]),
        notes=("Lottery tickets: most expire at zero. The ten led on 6-13 expiry-day trades each.",
               "Its desk charges no costs; these books pay Angel One's option charges on every round trip."),
    ),
    "nifty-scalp": Desk(
        key="nifty-scalp", label="NIFTY 50 Option Scalping", route="/nifty-scalp",
        instrument="near-expiry NIFTY options, bought",
        cost_basis="the premium paid (premium x lot size a lot)",
        board="the NIFTY 50 Option Scalping Rank (446 strategies with closed trades)",
        load=_by_strategy("nifty_scalp_positions", _nifty_scalp_parent), pnl=_bought_option_pnl, mark=_bought_option_mark,
        picks=_picks([
            ("ns_1m_03", 1, 81.8, 31, 987.84, "SMA Cross · 1 minute", 582019.42),
            ("ns_1h_14", 2, 79.9, 24, 1397.52, "CCI Zero Cross · 1 hour", 619681.58),
            ("ns_5m_38", 3, 78.1, 21, 1325.32, "Outside Bar Reversal · 5 minutes", 537857.63),
            ("ns_1h_12", 4, 77.8, 37, 807.61, "RSI Divergence · 1 hour", 570890.15),
            ("ns_10m_44", 5, 77.8, 25, 1202.08, "Prior Extreme Breakout · 10 minutes", 343871.75),
            ("ns_1h_40", 6, 77.7, 19, 2562.94, "Morning / Evening Star · 1 hour", 850777.44),
            ("ns_10m_31", 7, 76.6, 24, 1613.45, "Parabolic SAR Flip · 10 minutes", 743823.51),
            ("ns_5m_33", 8, 76.2, 39, 919.25, "Engulfing Candle · 5 minutes", 713694.15),
            ("ns_1d_46", 9, 75.7, 21, 2321.82, "Round Number Break · 1 day", 975190.60),
            ("ns_1h_38", 10, 75.7, 21, 1733.23, "Outside Bar Reversal · 1 hour", 479400.24),
        ]),
        notes=("Separate from the desk's existing Paper book · ₹2L, which runs its own hand-picked roster.",),
    ),
    "prelive": Desk(
        key="prelive", label="Index Option Buying · NIFTY 50", route="/prelive",
        instrument="ATM NIFTY options, bought",
        cost_basis="the premium paid at the ask (premium x lot size a lot)",
        board="the NIFTY 50 tournament's Rank on each trade's REAL-MONEY estimate (152 strategies)",
        load=_load_prelive, pnl=_bought_option_pnl, mark=_bought_option_mark,
        picks=_picks([
            ("ema_200_trend@15m", 1, 97.6, 30, 810.99, "ema_200_trend · 15m", None),
            ("intra_orb30@15m", 2, 91.6, 68, 747.44, "intra_orb30 · 15m", None),
            ("intra_adx_di@15m", 3, 89.9, 69, 443.23, "intra_adx_di · 15m", None),
            ("prt_directional_mirror@15m", 4, 89.7, 69, 442.06, "prt_directional_mirror · 15m", None),
            ("pta_trap@15m", 5, 89.7, 63, 725.84, "pta_trap · 15m", None),
            ("sl_trap_trading@15m", 6, 86.9, 60, 285.47, "sl_trap_trading · 15m", None),
            ("intra_pivot_break@15m", 7, 86.3, 50, 479.70, "intra_pivot_break · 15m", None),
            ("it_fake_breakout@15m", 8, 84.4, 56, 372.36, "it_fake_breakout · 15m", None),
            ("intra_ha_reversal@15m", 9, 84.1, 37, -127.79, "intra_ha_reversal · 15m", None),
            ("scalp_zscore_snap@5m", 10, 84.0, 96, 298.42, "scalp_zscore_snap · 5m", None),
        ]),
        notes=("Priced as the tournament's Rank is: bought at the ask, sold at the bid (its real-money "
               "estimate), not at the option LTP.",
               "The NIFTY BANK tab is a separate study with its own ten picks, already paper-traded there."),
    ),
    "stock-buying": Desk(
        key="stock-buying", label="Stock Pre-Live · Buying", route="/stock-prelive-buying",
        instrument="stock options, bought",
        cost_basis="the premium paid (premium x lot size a lot)",
        board="the stock buying desk's Rank (187 strategies with closed trades)",
        skip_expiry_day=True,
        load=_stock_loader("buying"), pnl=_bought_option_pnl, mark=_bought_option_mark,
        picks=_picks([
            ("intra_ma_envelope", 1, 83.1, 37, 1744.18, "Intraday: MA Envelope Break", 31836.25),
            ("anti_bb_volume_profile_poc", 2, 80.2, 29, 881.89, "ANTI Booming Bulls: Volume Profile / POC (D4)", 45153.75),
            ("intra_aroon", 3, 78.2, 32, 2594.97, "Intraday: Aroon Trend", 26775.00),
            ("intra_macd_trend", 4, 75.0, 60, -17.84, "Intraday: MACD Trend", 43882.50),
            ("intra_cpr_break", 5, 74.0, 55, 1461.37, "Intraday: CPR Break", 33685.00),
            ("intra_dema_cross", 6, 73.7, 57, 426.00, "Intraday: DEMA 10/30 Cross", 42992.50),
            ("anti_intra_rsi_regime", 7, 73.5, 36, 1379.29, "ANTI Intraday: RSI 55/45 Regime", 20013.75),
            ("intra_prev_day_hl", 8, 73.3, 32, 499.62, "Intraday: Prior-Day H/L Break", 26111.25),
            ("bb_ultimate_confluence", 9, 72.9, 19, 701.22, "Booming Bulls: Ultimate Nifty & Stock Strategy (D1)", 27937.50),
            ("anti_intra_first_hour_range", 10, 72.2, 43, 966.43, "ANTI Intraday: First-Hour Range Break", 35542.50),
        ]),
        notes=("The desk's own paper books are paused until the Stock Buying Lab admits a strategy; these "
               "two are not, but skip any entry on its contract's expiry day - the churn that made up most "
               "of the desk's record.",),
    ),
    "stock-selling": Desk(
        key="stock-selling", label="Stock Pre-Live · Selling", route="/stock-prelive-selling",
        instrument="stock option credit spreads, sold",
        cost_basis="the spread's maximum loss a lot (what the desk reserves for it)",
        board="the stock selling desk's Rank (279 strategies with closed trades; win rate left out, as for every selling desk)",
        skip_expiry_day=True,
        load=_stock_loader("selling"), pnl=_sold_spread_pnl, mark=_sold_spread_mark,
        picks=_picks([
            ("mirror_scalp_inside_break", 1, 89.9, 29, 1224.58, "Mirror: Scalp: Inside-Bar Break", 16920.00),
            ("mirror_swing_heikin", 2, 83.4, 37, 828.46, "Mirror: Swing: Heikin-Ashi Regime", 20921.25),
            ("mirror_swing_ibs", 3, 81.2, 29, 1045.25, "Mirror: Swing: Internal Bar Strength", 13436.25),
            ("mirror_intra_vwap_reject", 4, 77.1, 24, 541.94, "Mirror: Intraday: VWAP Rejection Wick", 14731.25),
            ("mirror_swing_ichimoku_kumo", 5, 76.0, 37, 719.08, "Mirror: Swing: Kumo Breakout", 17626.25),
            ("mirror_wt_btst", 6, 74.5, 61, 669.24, "Mirror: Wizard Trader: BTST Trade (H5)", 14326.25),
            ("mirror_scalp_vwap_band", 7, 73.9, 18, 867.42, "Mirror: Scalp: VWAP Band Fade", 13448.75),
            ("mirror_swing_fractal", 8, 73.1, 18, 807.15, "Mirror: Swing: Fractal Break", 15517.50),
            ("mirror_warrior_micro_pullback", 9, 73.0, 16, 1123.97, "Mirror: Ross Cameron (Warrior Trading): Micro Pullback", 12393.75),
            ("mirror_tfs_level_reversal", 10, 71.5, 21, 611.57, "Mirror: Trade For Sure: Level Reversal", 12090.00),
        ]),
        notes=("Like the desk, these books count only the SOLD leg's premium: the desk does not record the "
               "protective wing's exit, so its value is not marked; its buy and its sale are charged.",
               "Entries on the contract's own expiry day are skipped, as in the selling books."),
    ),
    "commodity": Desk(
        key="commodity", label="Commodity Trading", route="/commodity",
        instrument="MCX futures, both sides",
        cost_basis="the broker's margin for one lot (its measured rate x price x multiplier)",
        board="the Commodity Trading Rank on its honest record (300 strategies with closed trades)",
        load=_by_strategy("commodity_positions", _commodity_parent), pnl=_futures_pnl, mark=_futures_mark,
        picks=_picks([
            ("cmd_0149", 1, 88.7, 30, 42.69, "Inside Bar Breakout · 30m", 122004.36),
            ("cmd_0246", 2, 78.5, 25, 26.15, "Heikin Ashi Flip · 1h", 20848.38),
            ("cmd_0205", 3, 78.2, 32, 12.11, "Prior Session High/Low Break · 45m", 22100.76),
            ("cmd_0206", 4, 77.9, 41, 13.24, "Round Number Break · 45m", 52169.07),
            ("cmd_0195", 5, 77.8, 28, 18.61, "Inside Bar Breakout · 45m", 48634.12),
            ("cmd_0123", 6, 77.6, 58, 11.70, "Trend Pullback to EMA · 15m", 40603.68),
            ("cmd_0238", 7, 76.0, 29, 19.33, "Hammer / Shooting Star · 1h", 17796.14),
            ("cmd_0132", 8, 75.8, 27, 13.30, "Head & Shoulders · 30m", 22257.08),
            ("cmd_0022", 9, 75.1, 27, 25.48, "Pin Bar at Extreme · 1m", 69692.03),
            ("cmd_0016", 10, 74.8, 37, 17.21, "Doji Reversal · 1m", 37968.55),
        ]),
        notes=("Whole lots on margin: a ₹2 lakh book's ₹40,000 position cannot carry one lot of the big "
               "contracts (GOLD, SILVER, COPPER, ZINC); those signals are skipped and counted.",
               "Each copy is priced on its own contract, in at the touch and out at the desk's exit, with "
               "Angel One's MCX charges."),
    ),
    # The Factory's leaderboard grades a strategy on its best single symbol; across all their symbols
    # six of its top ten lost. These ten are the best COMBINED backtests over every stock and MCX
    # contract each was tested on (net P&L, >= 100 trades) - no Rank score, hence score None. Ids,
    # numbers and the reasoning: strategy_factory/top10_replay.py (PICKS), picked 27 Oct 23:35 IST.
    "strategy-factory": Desk(
        key="strategy-factory", label="Strategy Factory", route="/strategy-factory",
        instrument="NSE stocks (long only) and MCX futures (minis), both sides on MCX",
        cost_basis="a stock's price, whole shares; the broker's measured margin for one MCX lot",
        board=("the combined backtest over every stock and MCX contract each strategy was tested on "
               "(net P&L, at least 100 trades)"),
        load=_sf_load, pnl=_sf_pnl, mark=_sf_mark,
        picks=_picks([
            ("SF0006", 1, None, 187, None, "Head & Shoulders · 1h", 352997.0),
            ("SF0119", 2, None, 236, None, "Hammer / Shooting Star · 4h", 322344.0),
            ("SF0277", 3, None, 258, None, "EMA Ribbon Compression · 1h", 240029.0),
            ("SF0410", 4, None, 142, None, "ADX / DI Cross · 30m", 227103.0),
            ("SF0230", 5, None, 411, None, "Keltner Breakout · 1h", 220529.0),
            ("SF0420", 6, None, 123, None, "Supertrend Flip · 1h", 197268.0),
            ("SF0183", 7, None, 183, None, "Three Soldiers / Crows · 4h", 133901.0),
            ("SF0200", 8, None, 266, None, "Pin Bar at Extreme · 1d", 133455.0),
            ("SF0022", 9, None, 400, None, "Triple Top / Bottom · 1h", 112348.0),
            ("SF0298", 10, None, 192, None, "Break of Structure · 15m", 105556.0),
        ]),
        notes=("The Strategy Factory has no running paper engine, so these ten are run forward on every "
               "closed bar by the backtest's own rules - signal on the completed bar, fill at the next "
               "bar's open plus 5 bp, stop first, the backtest's maximum hold - checked trade for trade "
               "against the backtest on 20 series.",
               "Picked on all their symbols, not the leaderboard's best one: six of the board's top ten lost "
               "across all of theirs. Two that qualified were left out - in the backtest their "
               "higher-timeframe filter read a 4h bar before it had finished.",
               "Stocks: long only (a cash account cannot hold a short overnight), whole shares. Stock bars "
               "arrive once a day after the close, so stock trades appear after about 16:45 IST.",
               "MCX: through the mini where there is one (GOLDM, SILVERM, CRUDEOILM, NATGASMINI), whole "
               "lots on the broker's margin, one position per commodity, closed the day before its "
               "contract's exit window. COPPER and ZINC have no mini and their lots need more margin than "
               "a position here may use, so those signals are skipped and counted.",
               "Part of the MCX backtest evidence ran across contract joins the commodity store now "
               "refuses for decisions; weigh the MCX half of the pick with that in mind."),
    ),
}


def desk(key: str) -> Desk | None:
    return DESKS.get(key)


def normalize_book(book: str | None) -> str:
    return book if book in BOOK_CAPITAL else BOOKS[0]


def position_cap(d: Desk, book: str) -> float:
    return BOOK_CAPITAL[book] / max(d.max_open, 1)


# -- state ------------------------------------------------------------------------------------


async def _start(d: str, book: str) -> datetime:
    key = f"start:{d}:{book}"
    doc = await STATE.find_one({"_id": key})
    if doc and doc.get("started_at"):
        return naive_utc(doc["started_at"])
    await STATE.update_one({"_id": key}, {"$setOnInsert": {"started_at": _now(), "desk": d, "book": book}},
                           upsert=True)
    doc = await STATE.find_one({"_id": key})
    return naive_utc(doc["started_at"])


def _skip_doc(d: str, book: str, day: str) -> str:
    return f"skipped:{d}:{book}:{day}"


async def _decided(d: str, book: str, parents: list[dict]) -> set[str]:
    ids = [p["position_id"] for p in parents]
    out: set[str] = set()
    async for r in POSITIONS.find({"desk": d, "book": book, "parent_position_id": {"$in": ids}},
                                  {"parent_position_id": 1}):
        out.add(r["parent_position_id"])
    days = sorted({p.get("opened_on") for p in parents if p.get("opened_on")})
    if days:
        async for s in STATE.find({"_id": {"$in": [_skip_doc(d, book, day) for day in days]}}, {"ids": 1}):
            out.update(s.get("ids") or [])
    return out


async def _totals(d: str, book: str) -> tuple[float, float]:
    realized = deployed = 0.0
    async for r in POSITIONS.find({"desk": d, "book": book}, {"status": 1, "realized_pnl": 1, "capital_deployed": 1}):
        if r.get("status") == "OPEN":
            deployed += r.get("capital_deployed") or 0.0
        else:
            realized += r.get("realized_pnl") or 0.0
    return realized, deployed


async def _closed_after(d: str, book: str, t0: datetime | None) -> list[dict]:
    if t0 is None:
        return []
    return [r async for r in POSITIONS.find(
        {"desk": d, "book": book, "status": "CLOSED", "closed_at": {"$gt": t0}},
        {"symbol": 1, "capital_deployed": 1, "realized_pnl": 1, "opened_at": 1, "closed_at": 1})]


# -- the copy ------------------------------------------------------------------------------------


def _row(d: Desk, book: str, p: dict, lots: int, spend: float) -> dict:
    pick = next((x for x in d.picks if x.key == p["key"]), None)
    return {
        "position_id": uuid4().hex[:12], "desk": d.key, "book": book, "source": SOURCE_TAG,
        "parent_position_id": p["position_id"], "key": p["key"], "strategy_id": p["strategy_id"],
        "strategy_name": pick.name if pick else p.get("strategy_name"),
        "symbol": p["symbol"], "label": p.get("label"), "side": p["side"],
        "lots": lots, "qty": lots, "lot_size": p.get("lot_size"), "units": lots * int(p.get("lot_size") or 1),
        "entry_px": p["px_entry"], "cost_per_lot": p["entry_price"], "entry_price": p["entry_price"],
        "capital_deployed": spend, "allocation": None, "ltp": p.get("px_ltp"), "unrealized_pnl": 0.0,
        "realized_pnl": None, "gross_pnl": None, "fees": None, "fee_breakdown": None,
        "exit_px": None, "exit_reason": None, "status": "OPEN", "expiry": p.get("expiry"),
        "opened_at": p["opened_at"], "opened_on": p.get("opened_on"),
        "closed_at": None, "closed_on": None, "updated_at": _now(),
    }


def _close_fields(p: dict, c: dict) -> dict:
    return {
        "status": "CLOSED", "exit_px": p["px_exit"], "exit_reason": p.get("exit_reason"),
        "gross_pnl": c["gross"], "fees": round(c["fb"].total, 2), "fee_breakdown": c["fb"].as_dict(),
        "realized_pnl": c["net"], "unrealized_pnl": 0.0, "ltp": p["px_exit"],
        "closed_at": p.get("closed_at") or naive_utc(_now()), "closed_on": p.get("closed_on"),
        "updated_at": _now(),
    }


def _net_fn(d: Desk):
    def net(row: dict, parent: dict):
        gross, fb = d.pnl(parent, int(row["qty"]))
        return gross, round(gross - fb.total, 2), fb
    return net


async def _sync_book(d: Desk, book: str, entries: bool) -> dict:
    capital = BOOK_CAPITAL[book]
    floor = max(await _start(d.key, book), naive_utc(_now()) - LOOKBACK)
    open_rows = [r async for r in POSITIONS.find({"desk": d.key, "book": book, "status": "OPEN"})]
    pointed = [r["parent_position_id"] for r in open_rows if r.get("parent_position_id")]
    parents = [p for p in await d.load(floor, set(d.roster), pointed)
               if p.get("opened_at") is not None and (p["opened_at"] >= floor or p["position_id"] in pointed)]
    parents.sort(key=lambda p: (p["opened_at"], p["position_id"]))
    realized, deployed = await _totals(d.key, book)
    decided = await _decided(d.key, book, parents) if entries else set()

    rule_skips = []
    if entries and d.skip_expiry_day:
        held = set(pointed)
        keep = []
        for p in parents:
            if (p["position_id"] not in decided and p["position_id"] not in held and p.get("expiry")
                    and p.get("opened_on") == p["expiry"]):
                rule_skips.append({"parent": p, "reason": "expiry_day"})
            else:
                keep.append(p)
        parents = keep

    t0 = pending_since(parents, decided, open_rows, SOURCE_TAG) if entries else None
    closed_rows = await _closed_after(d.key, book, t0) if entries else []
    plan = plan_book(capital=capital, realized=realized, deployed=deployed, open_rows=open_rows,
                     parents=parents, decided=decided, breaker_tripped=False, entries=entries,
                     max_open=d.max_open, net_fn=_net_fn(d), source_tag=SOURCE_TAG,
                     closed_rows=closed_rows)

    n = {"opened": 0, "closed": 0, "skipped": 0, "marked": 0}
    for c in plan["closes"]:
        res = await POSITIONS.update_one({"_id": c["row"]["_id"], "status": "OPEN"},
                                         {"$set": _close_fields(c["parent"], c)})
        n["closed"] += res.modified_count
    for o in plan["opens"]:
        p = o["parent"]
        doc = _row(d, book, p, o["qty"], o["spend"])
        if o["close"] is not None:
            doc.update(_close_fields(p, o["close"]))
        try:
            await POSITIONS.insert_one(doc)
        except DuplicateKeyError:
            continue
        n["opened"] += 1
        n["closed"] += 1 if o["close"] is not None else 0
    skips: dict[str, dict[str, int]] = {}
    ids_by_day: dict[str, list[str]] = {}
    for s in plan["skips"] + rule_skips:
        p = s["parent"]
        per = skips.setdefault(p["key"], {})
        per[s["reason"]] = per.get(s["reason"], 0) + 1
        ids_by_day.setdefault(p.get("opened_on") or "", []).append(p["position_id"])
        n["skipped"] += 1
    for day, ids in ids_by_day.items():
        await STATE.update_one({"_id": _skip_doc(d.key, book, day)},
                               {"$addToSet": {"ids": {"$each": ids}},
                                "$set": {"desk": d.key, "book": book, "day": day}}, upsert=True)
    for key, per in skips.items():
        await SCORES.update_one({"desk": d.key, "book": book, "key": key},
                                {"$inc": {f"skipped.{k}": v for k, v in per.items()},
                                 "$set": {"updated_at": _now()}}, upsert=True)

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
                                   {"$set": {"ltp": p.get("px_ltp"), "unrealized_pnl": u, "updated_at": _now()}})
        n["marked"] += 1
    return n


_lock = asyncio.Lock()
_indexed = False


async def sync(entries: bool = True, only: str | None = None) -> dict:
    """Copy every desk into both books once."""
    global _indexed
    if not _indexed:
        _indexed = True
        await ensure_indexes()
    out: dict = {}
    async with _lock:
        for key, d in DESKS.items():
            if only and key != only:
                continue
            for book in BOOKS:
                try:
                    out[f"{key}:{book}"] = await _sync_book(d, book, entries)
                except Exception as exc:  # noqa: BLE001 - one desk's bad row must not stop the rest
                    logger.warning("[top10_books] %s %s failed: %s", key, book, exc, exc_info=True)
                    out[f"{key}:{book}"] = {"error": str(exc)[:200]}
            for book in BOOKS:
                try:
                    await _snapshot(d, book)
                except Exception:  # noqa: BLE001
                    logger.warning("[top10_books] snapshot %s %s failed", key, book, exc_info=True)
    return out


async def _snapshot(d: Desk, book: str) -> None:
    s = await summary(d.key, book)
    last = await EQUITY.find_one({"desk": d.key, "book": book}, sort=[("ts", -1)])
    stale = last is None or (naive_utc(_now()) - naive_utc(last["ts"])) > timedelta(minutes=30)
    if stale or abs((last or {}).get("equity", 0.0) - s["equity"]) > 0.005:
        await EQUITY.insert_one({"ts": _now(), "desk": d.key, "book": book, "equity": s["equity"],
                                 "realized": s["realized_pnl"], "unrealized": s["unrealized_pnl"],
                                 "open_positions": s["open_positions"]})


def _market_minutes() -> bool:
    t = datetime.now(IST)
    if t.weekday() >= 5:
        return False
    hm = t.hour * 60 + t.minute
    return 9 * 60 <= hm <= 23 * 60 + 59          # NSE day + MCX evening


async def loop() -> None:
    """Every minute in market hours (NSE, then MCX's evening), every ten minutes otherwise."""
    await asyncio.sleep(20)
    while True:
        if ENABLED:
            try:
                await sync(entries=True)
            except Exception:  # noqa: BLE001
                logger.warning("[top10_books] cycle failed", exc_info=True)
        await asyncio.sleep(60 if _market_minutes() else 600)


# -- read models ---------------------------------------------------------------------------------


async def summary(desk_key: str, book: str) -> dict:
    d = DESKS[desk_key]
    book = normalize_book(book)
    cap = BOOK_CAPITAL[book]
    realized = unrealized = deployed = fees = gross = 0.0
    open_n = closed_n = wins = 0
    async for r in POSITIONS.find({"desk": d.key, "book": book}):
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
    async for s in SCORES.find({"desk": d.key, "book": book}, {"skipped": 1}):
        for k, v in (s.get("skipped") or {}).items():
            if k in skipped:
                skipped[k] += int(v or 0)
    start = await STATE.find_one({"_id": f"start:{d.key}:{book}"})
    started = start.get("started_at") if start else None
    equity = cap + realized + unrealized
    return {
        "desk": d.key, "desk_label": d.label, "book": book, "books": BOOKS, "label": BOOK_LABEL[book],
        "book_labels": BOOK_LABEL, "mode": "paper", "enabled": ENABLED,
        "instrument": d.instrument, "cost_basis": d.cost_basis, "board": d.board, "notes": list(d.notes),
        "picked_at": PICKED_AT, "roster": list(d.roster), "strategies": len(d.picks),
        "max_open_positions": d.max_open, "position_cap": round(position_cap(d, book), 2),
        "skip_expiry_day": d.skip_expiry_day,
        "desk_capital": cap, "equity": round(equity, 2), "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2), "gross_pnl": round(gross, 2), "fees": round(fees, 2),
        "deployed": round(deployed, 2), "available_cash": round(cap + realized - deployed, 2),
        "open_positions": open_n, "closed_positions": closed_n, "wins": wins,
        "roi_pct": round((equity - cap) / cap * 100, 4) if cap else 0.0, "skipped": skipped,
        "copying_since": (naive_utc(started).replace(tzinfo=timezone.utc).isoformat() if started else None),
    }


async def leaderboard(desk_key: str, book: str) -> list[dict]:
    """The ten, in pick order, each with its record in this book and where it stood when picked."""
    d = DESKS[desk_key]
    book = normalize_book(book)
    cap = BOOK_CAPITAL[book]
    rec: dict[str, dict] = {p.key: {"trades": 0, "wins": 0, "net": 0.0, "gross": 0.0, "fees": 0.0, "open": 0}
                            for p in d.picks}
    async for r in POSITIONS.find({"desk": d.key, "book": book}):
        x = rec.get(r.get("key"))
        if x is None:
            continue
        if r.get("status") == "OPEN":
            x["open"] += 1
            continue
        v = r.get("realized_pnl") or 0.0
        x["trades"] += 1
        x["wins"] += 1 if v > 0 else 0
        x["net"] += v
        x["gross"] += r.get("gross_pnl") or 0.0
        x["fees"] += r.get("fees") or 0.0
    sk: dict[str, dict] = {}
    async for s in SCORES.find({"desk": d.key, "book": book}, {"key": 1, "skipped": 1}):
        sk[s["key"]] = {k: int((s.get("skipped") or {}).get(k, 0)) for k in SKIP_REASONS}
    rows = []
    for p in d.picks:
        x = rec[p.key]
        skipped = sk.get(p.key) or {k: 0 for k in SKIP_REASONS}
        rows.append({
            "key": p.key, "strategy_id": p.key, "name": p.name,
            "picked_rank": p.rank, "picked_score": p.score, "picked_trades": p.trades,
            "picked_bp": p.bp, "picked_net_pnl": p.net,
            "trades": x["trades"], "wins": x["wins"], "win_rate": round(x["wins"] / x["trades"], 4) if x["trades"] else 0.0,
            "net_pnl": round(x["net"], 2), "gross_pnl": round(x["gross"], 2), "fees": round(x["fees"], 2),
            "roi_pct": round(x["net"] / cap * 100, 4) if cap else 0.0, "open_positions": x["open"],
            "skipped": skipped, "skipped_total": sum(skipped.values()),
        })
    return rows


def _jsonable(doc: dict) -> dict:
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = naive_utc(v).replace(tzinfo=timezone.utc).isoformat()
    return doc


async def positions(desk_key: str, book: str, status: str = "OPEN", limit: int = 200) -> list[dict]:
    book = normalize_book(book)
    q: dict = {"desk": desk_key, "book": book}
    if status.upper() != "ALL":
        q["status"] = status.upper()
    sort_key = "opened_at" if status.upper() == "OPEN" else "closed_at"
    return [_jsonable(r) async for r in POSITIONS.find(q).sort(sort_key, -1).limit(limit)]


async def ensure_indexes() -> None:
    """Best effort: an index failure must never stop the books."""
    try:
        await POSITIONS.create_index([("desk", 1), ("book", 1), ("parent_position_id", 1)],
                                     name="t10_parent_unique", unique=True)
        await POSITIONS.create_index([("desk", 1), ("book", 1), ("status", 1)], name="t10_desk_book_status")
        await SCORES.create_index([("desk", 1), ("book", 1), ("key", 1)], name="t10_score_key", unique=True)
        await EQUITY.create_index([("desk", 1), ("book", 1), ("ts", -1)], name="t10_equity_ts")
    except Exception:  # noqa: BLE001
        logger.warning("[top10_books] index creation skipped", exc_info=True)
