"""Gold Desk — the pattern library on gold, on two venues, one book each.

Ported from the antigravity app's Gold Desk, which ran every strategy that desk had on
Delta's gold-backed token perpetuals out of a single shared book. The idea is kept; three
things about it are not.

WHAT CAME ACROSS
----------------
The whole pattern catalogue (39 templates x 8 timeframes = 312 strategies, long and
short) evaluated on gold, with every fill charged the venue's real costs, out of ONE
shared balance per venue rather than one per strategy. A win here funds the next position,
exactly as a real account does — which is the property that makes a book's record mean
something a per-strategy leaderboard's does not.

TWO VENUES, NEVER NETTED
------------------------
    MCX     GOLD (1 kg) and GOLDM (100 g) futures, rupees per 10 grams, 09:00-23:30 IST,
            whole lots on SPAN-lite margin, real MCX brokerage/CTT/exchange/SEBI/stamp/GST.
    DELTA   XAUTUSD and PAXGUSD token perpetuals, dollars per ounce, 24/7, whole
            contracts at 1x notional, the venue's own taker fee both legs.

The same ounce of gold, priced by two markets that disagree — MCX carries Indian import
duty and GST, Delta carries a token's basis. Two books, two currencies, and no figure on
this desk ever adds them together.

THE THREE THINGS FIXED ON THE WAY OVER
--------------------------------------
1. THE FEE WAS WRONG BY 5.9x. The original charged one hardcoded crypto taker rate
   (0.059%) on every fill including gold. Delta's published taker on XAUTUSD and PAXGUSD
   is 0.01% — gold perps are a fifth of Bitcoin's 0.05% before GST. On a book whose only
   question is whether an edge survives its costs, a fee nearly six times too big does not
   make the test conservative, it makes it meaningless. The rate is now read from the
   venue's own product spec (`gold_delta_feed.product`) and never written down here.

2. A STRATEGY'S RECORD COULD VANISH. The original held per-strategy rows in memory and
   merged the saved ones back only for streams still on the watch list, so the day gold
   dropped out of that engine's resolved universe every row was silently discarded — the
   page showed "no gold streams registered" beside a live balance and 428 closed trades.
   Here a strategy's record IS its positions in Mongo, derived on read. Nothing to drop.

3. THE BOOK COULD RUN TO ZERO. The original had no breaker of any kind and went from $100
   to $0.05 — a 99.95% loss over 428 trades with nothing in the code able to notice. This
   one carries the desk breakers this app already uses (a daily loss limit) plus a book
   floor: entries stop if equity falls below a set fraction of capital. Both are visible
   on the page, and neither closes an open position — an open position keeps its stop.

STILL PAPER. No order reaches a broker or an exchange from this module.
"""

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    gold_equity_collection,
    gold_positions_collection,
    gold_state_collection,
    gold_trades_collection,
)
from app.services import gold_delta_feed
from app.services.broker_data import get_ltp
from app.services.commodity_bars import (
    IST,
    TIMEFRAMES as MCX_TIMEFRAMES,
    front_month_universe,
    is_market_open as mcx_open,
    load_bars as mcx_load_bars,
)
from app.services.commodity_engine import _trade_stats, _verdict, order_charges
from app.services.commodity_patterns import COMMODITY_CATALOG, FAMILY_LABELS, evaluate
from app.services.commodity_positions import multiplier
from app.services.commodity_prelive import margin_pct

logger = logging.getLogger("gold_desk")

# GST on the venue's commission. Delta India bills it separately at 18%, which is why the
# engine this was ported from carried 0.00059 for a 0.0005 product — the GST was baked in.
# Kept explicit here so the product rate stays the product rate and the tax stays a tax.
DELTA_GST = float(os.getenv("GOLD_DELTA_GST_PCT", "0.18"))


@dataclass(frozen=True)
class Venue:
    key: str
    label: str
    currency: str            # INR | USD
    unit_label: str          # what one position is counted in
    symbols: tuple[str, ...]
    capital: float
    max_positions: int
    slippage_bps: float
    max_hold_bars: int
    daily_loss_pct: float
    # Entries stop below this fraction of starting capital. The thing the original desk
    # had no version of.
    book_floor_pct: float
    quote_note: str


VENUES: dict[str, Venue] = {
    "mcx": Venue(
        key="mcx", label="MCX Gold Futures", currency="INR", unit_label="lot",
        # GOLD and GOLDM only. The bar store polls exactly these two of the gold family
        # (GOLDTEN / GOLDGUINEA / GOLDPETAL are not in COMMODITY_UNDERLYINGS), and adding
        # symbols to that poller costs requests on an Angel endpoint that answered five
        # HTTP 403s to eight unpaced calls. A desk that cannot get candles is worse than a
        # desk with two contracts.
        symbols=("GOLDM", "GOLD"),
        # Rs 30 lakh, and the number is forced by the contract rather than chosen. One
        # GOLDM lot is 100 g x Rs ~1,46,800 per 10 g = ~Rs 14.7 LAKH of notional, and this
        # desk never takes a position whose notional exceeds the book. At Rs 15 lakh
        # exactly one lot could ever be open, so the first strategy to signal would block
        # all 311 others — the fill would be decided by which timeframe ticks fastest, not
        # by which strategy is any good. Rs 30 lakh buys a second slot, which is the
        # minimum at which the book is measuring strategies rather than clock speed.
        capital=float(os.getenv("GOLD_MCX_CAPITAL", "3000000")),
        max_positions=int(os.getenv("GOLD_MCX_MAX_POSITIONS", "4")),
        slippage_bps=float(os.getenv("GOLD_MCX_SLIPPAGE_BPS", "5")),
        max_hold_bars=int(os.getenv("GOLD_MCX_MAX_HOLD_BARS", "60")),
        daily_loss_pct=float(os.getenv("GOLD_MCX_DAILY_LOSS_PCT", "0.03")),
        book_floor_pct=float(os.getenv("GOLD_BOOK_FLOOR_PCT", "0.50")),
        quote_note="₹ per 10 grams · whole MCX lots on SPAN-lite margin",
    ),
    "delta": Venue(
        key="delta", label="Delta Gold Perpetuals", currency="USD", unit_label="contract",
        symbols=tuple(gold_delta_feed.SYMBOLS),
        capital=float(os.getenv("GOLD_DELTA_CAPITAL", "10000")),
        max_positions=int(os.getenv("GOLD_DELTA_MAX_POSITIONS", "6")),
        slippage_bps=float(os.getenv("GOLD_DELTA_SLIPPAGE_BPS", "5")),
        max_hold_bars=int(os.getenv("GOLD_DELTA_MAX_HOLD_BARS", "60")),
        daily_loss_pct=float(os.getenv("GOLD_DELTA_DAILY_LOSS_PCT", "0.03")),
        book_floor_pct=float(os.getenv("GOLD_BOOK_FLOOR_PCT", "0.50")),
        quote_note="$ per troy ounce · whole contracts at 1x notional, no leverage",
    ),
}

VENUE_KEYS = tuple(VENUES)


def venue(key: str) -> Venue:
    v = VENUES.get((key or "").lower())
    if v is None:
        raise KeyError(f"unknown gold venue {key!r} — expected one of {VENUE_KEYS}")
    return v


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist() -> date:
    return datetime.now(IST).date()


def _session_start(v: Venue) -> datetime:
    """Where "today" begins for the daily loss breaker.

    IST midnight for MCX, UTC midnight for the perpetuals. A 24/7 venue has no session, so
    the only defensible day is the one its candles are bucketed by — and that is the same
    UTC day `gold_delta_feed` anchors on, or the breaker would measure a different day
    from the bars that triggered the trades."""
    if v.key == "mcx":
        return datetime.now(IST).replace(hour=0, minute=0, second=0,
                                         microsecond=0).astimezone(timezone.utc)
    return _now().replace(hour=0, minute=0, second=0, microsecond=0)


def is_open(v: Venue) -> bool:
    return mcx_open(datetime.now(IST)) if v.key == "mcx" else True


def timeframes(v: Venue) -> dict:
    return MCX_TIMEFRAMES if v.key == "mcx" else gold_delta_feed.TIMEFRAMES


async def load_bars(v: Venue, symbol: str, tf: str, limit: int):
    if v.key == "mcx":
        return await mcx_load_bars(symbol, tf, limit=limit)
    return await gold_delta_feed.load_bars(symbol, tf, limit=limit)


# ── the tradable set ─────────────────────────────────────────────────────────────


async def universe(v: Venue) -> dict[str, dict]:
    """What each symbol needs to be traded and marked.

    MCX hands back the front-month contract (token, expiry, segment); Delta hands back the
    product spec (contract value, the venue's own fee). Same shape, so everything below
    this line stops caring which venue it is on."""
    if v.key == "mcx":
        uni = await front_month_universe()
        return {s: uni[s] for s in v.symbols if s in uni}
    out: dict[str, dict] = {}
    for s in v.symbols:
        try:
            out[s] = await gold_delta_feed.product(s)
        except Exception as exc:                        # noqa: BLE001
            logger.warning("gold desk: no Delta product for %s (%s)", s, exc)
    return out


async def mark(v: Venue, symbol: str, inst: dict) -> tuple[float | None, str]:
    """The live price a position is marked and filled against."""
    if v.key == "mcx":
        sec = str(inst.get("security_id") or "")
        if not sec:
            return None, "none"
        px, src = await get_ltp(None, sec, inst.get("exchange_segment"))
        return (float(px) if px else None), (src or "angel")
    px = await gold_delta_feed.mark_price(symbol)
    return px, "delta"


# ── contract mathematics ─────────────────────────────────────────────────────────


def _qty_per_unit(v: Venue, symbol: str, inst: dict) -> float:
    """How much metal one lot / one contract carries, in the units the price is quoted in.

    MCX: the published value multiplier (GOLD 100, GOLDM 10) — NOT the broker's `lotsize`
    field, which is the order-quantity unit and disagrees on exactly these two contracts.
    Delta: `contract_value`, 0.001 oz on both gold perps."""
    if v.key == "mcx":
        return float(multiplier(symbol))
    return float(inst.get("contract_value") or 0.001)


async def _charges(v: Venue, symbol: str, inst: dict, price: float, qty: float,
                   is_buy: bool) -> float:
    """What one executed side costs, in the venue's currency."""
    if v.key == "mcx":
        return order_charges(price, qty, is_buy)
    rate = float(inst.get("taker_fee_rate") or 0.0)
    return price * qty * rate * (1 + DELTA_GST)


def _sizing(v: Venue, symbol: str, inst: dict, price: float, free: float
            ) -> tuple[int, float, float, str | None]:
    """(units, notional, capital committed, refusal reason).

    Whole lots and whole contracts only. No fraction of a lot is ever invented — a paper
    desk that can hold 0.3 of a GOLD lot is measuring an instrument that does not exist."""
    per_unit = _qty_per_unit(v, symbol, inst)
    unit_notional = price * per_unit
    if unit_notional <= 0:
        return 0, 0.0, 0.0, None

    if v.key == "mcx":
        unit_margin = margin_pct(symbol) * unit_notional
        if unit_margin <= 0:
            return 0, 0.0, 0.0, None
        # Capped by the book's own notional, not only by free margin. Margin would let
        # Rs 30 lakh carry Rs 4 crore of gold; the book refuses to hold more gold than it
        # has money, which is what keeps a paper record transferable to a real account.
        units = min(1, int(free // unit_margin), int(v.capital // unit_notional))
        if units < 1:
            why = (f"{symbol}: one lot is {unit_notional:,.0f} of notional and "
                   f"~{unit_margin:,.0f} of margin against {free:,.0f} free on a "
                   f"{v.capital:,.0f} book — skipped, no fraction of a lot invented.")
            return 0, 0.0, 0.0, why
        return units, units * unit_notional, units * unit_margin, None

    # Delta: an equal share of the book per slot, at 1x. The venue offers 100x on these
    # products and the desk takes none of it: leverage would multiply a pattern library's
    # results without telling anyone anything new about the patterns.
    budget = min(v.capital / max(v.max_positions, 1), free)
    units = int(budget // unit_notional)
    if units < 1:
        why = (f"{symbol}: one contract is {unit_notional:,.2f} of notional against a "
               f"{budget:,.2f} slot budget — skipped.")
        return 0, 0.0, 0.0, why
    notional = units * unit_notional
    return units, notional, notional, None


# ── switches ─────────────────────────────────────────────────────────────────────


async def get_state(v: Venue) -> dict:
    doc = await gold_state_collection.find_one({"_id": v.key}) or {}
    return {
        # Ships OFF, like every desk in this app that spends a book. The antigravity desk
        # it came from had no switch at all.
        "enabled": doc.get("enabled", False),
        "last_run_at": doc.get("last_run_at"),
        "last_opened": doc.get("last_opened", 0),
        "last_managed": doc.get("last_managed", 0),
        "last_evaluated": doc.get("last_evaluated", 0),
        "last_notes": doc.get("last_notes", []),
    }


async def set_enabled(v: Venue, enabled: bool) -> dict:
    await gold_state_collection.update_one(
        {"_id": v.key}, {"$set": {"enabled": bool(enabled), "updated_at": _now()}}, upsert=True)
    return await summary(v)


# ── the book ─────────────────────────────────────────────────────────────────────


async def book(v: Venue) -> dict:
    """Balance, exposure and the realised/unrealised split — summed in Mongo.

    Aggregated rather than streamed: 312 strategies x 2 symbols produces a lot of closed
    rows, and pulling them into Python to add up four numbers is how a summary endpoint
    starts taking seconds on a shared cluster."""
    agg = {"deployed": 0.0, "unreal": 0.0, "open": 0}
    async for r in gold_positions_collection.aggregate([
            {"$match": {"venue": v.key, "status": "OPEN"}},
            {"$group": {"_id": None, "deployed": {"$sum": "$margin_used"},
                        "unreal": {"$sum": "$unrealized_pnl"}, "n": {"$sum": 1}}}]):
        agg = {"deployed": r.get("deployed") or 0.0, "unreal": r.get("unreal") or 0.0,
               "open": r.get("n") or 0}

    realized = costs = 0.0
    closed = wins = 0
    async for r in gold_positions_collection.aggregate([
            {"$match": {"venue": v.key, "status": {"$ne": "OPEN"}}},
            {"$group": {"_id": None, "realized": {"$sum": "$realized_pnl"},
                        "costs": {"$sum": "$costs"}, "n": {"$sum": 1},
                        "wins": {"$sum": {"$cond": [{"$gt": ["$realized_pnl", 0]}, 1, 0]}}}}]):
        realized = r.get("realized") or 0.0
        costs = r.get("costs") or 0.0
        closed = r.get("n") or 0
        wins = r.get("wins") or 0

    unreal, deployed = agg["unreal"], agg["deployed"]
    total = realized + unreal
    dp = 2
    return {
        "capital": v.capital,
        "realized_pnl": round(realized, dp), "unrealized_pnl": round(unreal, dp),
        "total_pnl": round(total, dp),
        "realized_pct": round(realized / v.capital * 100, 2),
        "unrealized_pct": round(unreal / v.capital * 100, 2),
        "total_pct": round(total / v.capital * 100, 2),
        "margin_deployed": round(deployed, dp),
        "available_margin": round(v.capital + realized - deployed, dp),
        "equity": round(v.capital + total, dp),
        "total_costs": round(costs, dp),
        "open_positions": agg["open"], "closed_positions": closed,
        "win_rate": round(wins / closed * 100, 1) if closed else 0.0,
    }


async def today_pnl(v: Venue) -> float:
    start = _session_start(v)
    total = 0.0
    async for r in gold_positions_collection.aggregate([
            {"$match": {"venue": v.key, "status": {"$ne": "OPEN"},
                        "closed_at": {"$gte": start}}},
            {"$group": {"_id": None, "s": {"$sum": "$realized_pnl"}}}]):
        total += r.get("s") or 0.0
    async for r in gold_positions_collection.aggregate([
            {"$match": {"venue": v.key, "status": "OPEN", "opened_at": {"$gte": start}}},
            {"$group": {"_id": None, "s": {"$sum": "$unrealized_pnl"}}}]):
        total += r.get("s") or 0.0
    return total


# ── position lifecycle ───────────────────────────────────────────────────────────


async def _open(v: Venue, spec, symbol: str, inst: dict, sig, bar_ts, free: float,
                market: float) -> tuple[bool, str | None, float]:
    if await gold_positions_collection.find_one({
            "venue": v.key, "symbol": symbol, "strategy_template": spec.template,
            "timeframe": spec.timeframe, "status": "OPEN"}):
        return False, None, 0.0
    if not market or market <= 0 or not sig.entry:
        return False, None, 0.0

    units, notional, committed, why = _sizing(v, symbol, inst, market, free)
    if units < 1:
        return False, why, 0.0

    slip = v.slippage_bps / 10000.0
    # The signal's levels were computed on the last CLOSE; the fill happens at the live
    # price. Scaling target and stop by the same ratio keeps the trade's shape — its
    # reward:risk — rather than silently widening one side by however far price moved
    # between the bar closing and the desk looking at it.
    ratio = market / float(sig.entry)
    tgt, stp = float(sig.target) * ratio, float(sig.stoploss) * ratio
    fill = market * (1 + slip) if sig.side == "BUY" else market * (1 - slip)
    per_unit = _qty_per_unit(v, symbol, inst)
    qty = units * per_unit
    entry_costs = await _charges(v, symbol, inst, fill, qty, sig.side == "BUY")

    await gold_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "venue": v.key, "currency": v.currency,
        "strategy_id": spec.strategy_id, "strategy_template": spec.template,
        "strategy_name": spec.name, "family": spec.family,
        "family_label": FAMILY_LABELS.get(spec.family, spec.family),
        "timeframe": spec.timeframe, "pattern": sig.pattern,
        "symbol": symbol,
        "display_name": inst.get("symbol") or inst.get("description") or symbol,
        "instrument": {
            "symbol": inst.get("symbol") or symbol,
            "security_id": str(inst.get("security_id") or ""),
            "exchange_segment": inst.get("exchange_segment") or ("DELTA" if v.key == "delta" else None),
            "expiry": inst.get("expiry"),
            "contract_value": inst.get("contract_value"),
        },
        "side": sig.side, "signal_price": round(float(sig.entry), 4),
        "entry_price": round(fill, 4),
        "units": units, "unit_label": v.unit_label,
        # `lots` as well as `units`, because desk_history and the shared position readers
        # in this app all speak lots. One name for the page, one for the plumbing.
        "lots": units, "multiplier": per_unit, "qty": qty,
        "notional": round(notional, 2), "margin_used": round(committed, 2),
        "capital_deployed": round(committed, 2),
        "entry_costs": round(entry_costs, 4),
        "target": round(tgt, 4), "stoploss": round(stp, 4),
        "ltp": round(fill, 4), "unrealized_pnl": 0.0, "return_on_margin_pct": 0.0,
        "realized_pnl": None, "costs": None, "fees": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "rationale": sig.rationale, "entry_bar_ts": bar_ts, "bars_held": 0,
        "max_hold_bars": v.max_hold_bars,
        "opened_at": _now(), "opened_on": _today_ist().isoformat(),
        "updated_at": _now(), "closed_at": None,
    })
    return True, None, committed


async def _close(v: Venue, pos: dict, inst: dict, ltp: float, reason: str) -> float:
    slip = v.slippage_bps / 10000.0
    is_long = pos["side"] == "BUY"
    fill = ltp * (1 - slip) if is_long else ltp * (1 + slip)
    qty = pos["qty"]
    gross = (fill - pos["entry_price"]) * qty * (1 if is_long else -1)
    costs = (pos.get("entry_costs") or 0.0) + \
        await _charges(v, pos["symbol"], inst, fill, qty, not is_long)
    net = gross - costs
    margin = pos.get("margin_used") or 0.0
    closed_at = _now()

    await gold_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "venue": v.key, "currency": v.currency,
        "strategy_template": pos.get("strategy_template"),
        "strategy_name": pos.get("strategy_name"), "timeframe": pos.get("timeframe"),
        "pattern": pos.get("pattern"), "symbol": pos["symbol"], "side": pos["side"],
        "entry_price": pos["entry_price"], "exit_price": round(fill, 4),
        "units": pos.get("units"), "lots": pos.get("lots"), "qty": qty,
        "margin_used": round(margin, 2),
        "gross_pnl": round(gross, 2), "costs": round(costs, 4), "realized_pnl": round(net, 2),
        "return_on_margin_pct": round(net / margin * 100, 2) if margin else 0.0,
        "exit_reason": reason, "opened_at": pos["opened_at"], "closed_at": closed_at,
    })
    await gold_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "status": "CLOSED", "exit_price": round(fill, 4), "exit_reason": reason,
        "gross_pnl": round(gross, 2), "costs": round(costs, 4), "fees": round(costs, 4),
        "realized_pnl": round(net, 2),
        "return_on_margin_pct": round(net / margin * 100, 2) if margin else 0.0,
        "unrealized_pnl": 0.0, "closed_at": closed_at,
        "closed_on": _today_ist().isoformat(), "updated_at": closed_at,
        "ltp": round(ltp, 4)}})
    return net


# ── cycles ───────────────────────────────────────────────────────────────────────


async def manage_cycle(v: Venue) -> int:
    """Mark and exit open positions. Runs whether the desk is switched on or off — a
    position taken before the switch flipped is still exposure and still has a stop."""
    open_pos = [p async for p in gold_positions_collection.find({"venue": v.key, "status": "OPEN"})]
    if not open_pos:
        return 0
    uni = await universe(v)
    tfs = timeframes(v)
    marks: dict[str, float] = {}
    updated = 0

    for pos in open_pos:
        symbol = pos["symbol"]
        inst = uni.get(symbol) or pos.get("instrument") or {}
        if symbol not in marks:
            px, _src = await mark(v, symbol, inst)
            if not px:
                continue
            marks[symbol] = float(px)
        ltp = marks[symbol]

        is_long = pos["side"] == "BUY"
        qty = pos["qty"]
        gross = (ltp - pos["entry_price"]) * qty * (1 if is_long else -1)
        exit_cost = await _charges(v, symbol, inst, ltp, qty, not is_long)
        unreal = gross - ((pos.get("entry_costs") or 0.0) + exit_cost)

        tf_minutes = tfs.get(pos.get("timeframe", "1d"), (None, 1440))[1]
        entry_ts = pos.get("entry_bar_ts")
        if isinstance(entry_ts, datetime) and entry_ts.tzinfo is None:
            entry_ts = entry_ts.replace(tzinfo=timezone.utc)
        bars_held = (int((_now() - entry_ts).total_seconds() // 60 // max(tf_minutes, 1))
                     if isinstance(entry_ts, datetime) else 0)
        margin = pos.get("margin_used") or 0.0
        changes = {"ltp": round(ltp, 4), "unrealized_pnl": round(unreal, 2),
                   "return_on_margin_pct": round(unreal / margin * 100, 2) if margin else 0.0,
                   "bars_held": bars_held, "updated_at": _now()}

        hit_t = ltp >= pos["target"] if is_long else ltp <= pos["target"]
        hit_s = ltp <= pos["stoploss"] if is_long else ltp >= pos["stoploss"]
        expired = bars_held >= pos.get("max_hold_bars", v.max_hold_bars)
        reason = "target" if hit_t else "stoploss" if hit_s else "max_hold_expired" if expired else None

        await gold_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
        if reason:
            await _close(v, {**pos, **changes}, inst, ltp, reason)
        updated += 1
    return updated


async def scan_cycle(v: Venue) -> dict:
    """Evaluate the whole catalogue on both of the venue's gold symbols."""
    state = await get_state(v)
    notes: list[str] = []
    if not state["enabled"]:
        return {"opened": 0, "evaluated": 0,
                "notes": ["Desk switched OFF — no new entries. Open positions are still "
                          "managed to their target or stop."]}

    b = await book(v)
    floor = v.capital * v.book_floor_pct
    if b["equity"] <= floor:
        return {"opened": 0, "evaluated": 0,
                "notes": [f"Book floor reached: equity {b['equity']:,.2f} is at or below "
                          f"{v.book_floor_pct:.0%} of the {v.capital:,.0f} book. No new "
                          f"entries. The desk this was ported from had no floor and ran "
                          f"its book down to 0.05% of capital."]}
    limit = v.daily_loss_pct * v.capital
    tp = await today_pnl(v)
    if tp <= -limit:
        return {"opened": 0, "evaluated": 0,
                "notes": [f"Daily loss breaker tripped: today {tp:,.2f} crossed "
                          f"-{limit:,.2f}. No new entries today."]}

    uni = await universe(v)
    if not uni:
        return {"opened": 0, "evaluated": 0,
                "notes": [f"No tradable {v.label} contracts resolved — nothing to scan."]}

    open_now = await gold_positions_collection.count_documents({"venue": v.key, "status": "OPEN"})
    if open_now >= v.max_positions:
        return {"opened": 0, "evaluated": 0,
                "notes": [f"All {v.max_positions} position slots are in use."]}

    free = b["available_margin"]
    guard = await gold_state_collection.find_one({"_id": f"{v.key}:entry_bars"}) or {}
    last_bar = guard.get("last", {})
    fresh: dict[str, str] = {}
    opened = evaluated = 0
    skipped: set[str] = set()

    # Bars are loaded once per (symbol, timeframe) and every strategy on that timeframe is
    # evaluated against the same list. Loading per strategy would be 312 reads a symbol
    # for 8 distinct series — the desk would spend its cycle in Mongo rather than in the
    # pattern library.
    for symbol, inst in uni.items():
        market, _src = await mark(v, symbol, inst)
        if not market:
            notes.append(f"{symbol}: no live price — skipped this cycle.")
            continue
        for tf in timeframes(v):
            specs = [s for s in COMMODITY_CATALOG if s.timeframe == tf]
            if not specs:
                continue
            need = max((s.min_bars for s in specs), default=60) + 5
            bars = await load_bars(v, symbol, tf, limit=max(need, 250))
            if len(bars) < 65:
                notes.append(f"{symbol} {tf}: only {len(bars)} bars in the store.")
                continue
            bar_ts = bars[-1].ts
            for spec in specs:
                if len(bars) < spec.min_bars + 5:
                    continue
                key = f"{symbol}:{spec.template}:{spec.timeframe}"
                # One decision per strategy per bar. Without it a 3-minute loop would
                # re-enter the same 1-hour signal twenty times.
                if last_bar.get(key) == str(bar_ts):
                    continue
                evaluated += 1
                sig = evaluate(spec, bars)
                if sig is None:
                    continue
                fresh[key] = str(bar_ts)
                if open_now >= v.max_positions:
                    skipped.add(f"{v.max_positions} slots full")
                    continue
                ok, why, used = await _open(v, spec, symbol, inst, sig, bar_ts, free, market)
                if ok:
                    opened += 1
                    open_now += 1
                    free -= used
                elif why:
                    # Deduplicated: 312 strategies hitting the same unaffordable contract
                    # would otherwise write 312 identical lines onto the page.
                    skipped.add(why)

    if fresh:
        await gold_state_collection.update_one(
            {"_id": f"{v.key}:entry_bars"},
            {"$set": {f"last.{k}": val for k, val in fresh.items()}}, upsert=True)
    notes.extend(sorted(skipped))
    return {"opened": opened, "evaluated": evaluated, "notes": notes[:12]}


async def run_cycle(v: Venue) -> dict:
    managed = await manage_cycle(v)
    scan = await scan_cycle(v)
    b = await book(v)
    await gold_equity_collection.insert_one({
        "ts": _now(), "venue": v.key, "equity": b["equity"], "realized": b["realized_pnl"],
        "unrealized": b["unrealized_pnl"], "margin_deployed": b["margin_deployed"],
        "open_positions": b["open_positions"]})
    await gold_state_collection.update_one({"_id": v.key}, {"$set": {
        "last_run_at": _now(), "last_opened": scan["opened"], "last_managed": managed,
        "last_evaluated": scan["evaluated"], "last_notes": scan["notes"],
        "market_open": is_open(v)}}, upsert=True)
    return {"venue": v.key, "opened": scan["opened"], "managed": managed,
            "evaluated": scan["evaluated"], "notes": scan["notes"]}


async def close_all(v: Venue, reason: str = "manual_close_all") -> dict:
    open_pos = [p async for p in gold_positions_collection.find({"venue": v.key, "status": "OPEN"})]
    if not open_pos:
        return {"closed": 0, "net_pnl": 0.0}
    uni = await universe(v)
    marks: dict[str, float] = {}
    net = 0.0
    closed = 0
    for pos in open_pos:
        symbol = pos["symbol"]
        inst = uni.get(symbol) or pos.get("instrument") or {}
        if symbol not in marks:
            px, _src = await mark(v, symbol, inst)
            marks[symbol] = float(px) if px else float(pos.get("ltp") or 0.0)
        ltp = marks[symbol]
        if ltp <= 0:
            continue
        net += await _close(v, pos, inst, ltp, reason)
        closed += 1
    return {"closed": closed, "net_pnl": round(net, 2)}


# ── read models ──────────────────────────────────────────────────────────────────


async def summary(v: Venue) -> dict:
    state = await get_state(v)
    b = await book(v)
    limit = v.daily_loss_pct * v.capital
    tp = await today_pnl(v)
    floor = v.capital * v.book_floor_pct
    uni = await universe(v)
    return {
        "venue": v.key, "label": v.label, "currency": v.currency,
        "unit_label": v.unit_label, "quote_note": v.quote_note,
        "symbols": list(v.symbols), "tradable_symbols": sorted(uni),
        **state, **b,
        "today_pnl": round(tp, 2), "today_pct": round(tp / v.capital * 100, 2),
        "daily_loss_limit": round(limit, 2), "breaker_tripped": tp <= -limit,
        "book_floor": round(floor, 2), "book_floor_pct": v.book_floor_pct,
        "floor_reached": b["equity"] <= floor,
        "market_open": is_open(v), "mode": "paper",
        "max_positions": v.max_positions, "slippage_bps": v.slippage_bps,
        "max_hold_bars": v.max_hold_bars,
        "strategy_count": len(COMMODITY_CATALOG),
        "stream_count": len(COMMODITY_CATALOG) * max(len(uni), 1),
        "fee_note": _fee_note(v, uni),
    }


def _fee_note(v: Venue, uni: dict) -> str:
    if v.key == "mcx":
        return ("Real MCX brokerage, CTT, exchange, SEBI, stamp duty and GST on both legs.")
    rates = sorted({float(i.get("taker_fee_rate") or 0.0) for i in uni.values()})
    if not rates or not any(rates):
        return "Delta taker fee, read from the venue's product spec, on both legs."
    pct = ", ".join(f"{r * 100:.3f}%" for r in rates)
    return (f"Delta's own taker rate ({pct} a side) plus {DELTA_GST:.0%} GST, both legs — "
            f"read from the venue, not assumed. The desk this was ported from charged "
            f"0.059%, a crypto rate, which is 5.9x what gold actually costs here.")


async def strategies(v: Venue, limit: int = 400) -> list[dict]:
    """One row per (strategy, symbol) that has traded in this book.

    Aggregated in Mongo and joined to the catalogue in Python. The alternative — a query
    per strategy — is 312 round trips a symbol on a shared cluster, which is the shape
    that has already made a summary endpoint on this app take seconds."""
    by_spec = {s.strategy_id: s for s in COMMODITY_CATALOG}
    tmpl_tf = {(s.template, s.timeframe): s for s in COMMODITY_CATALOG}

    rows: dict[tuple, dict] = {}
    async for r in gold_positions_collection.aggregate([
            {"$match": {"venue": v.key, "status": {"$ne": "OPEN"}}},
            {"$sort": {"closed_at": 1}},
            {"$group": {
                "_id": {"t": "$strategy_template", "tf": "$timeframe", "s": "$symbol"},
                "pnl": {"$push": "$realized_pnl"}, "costs": {"$sum": "$costs"},
                "n": {"$sum": 1}}}]):
        k = (r["_id"]["t"], r["_id"]["tf"], r["_id"]["s"])
        rows[k] = {"pnl": r.get("pnl") or [], "costs": r.get("costs") or 0.0,
                   "trades": r.get("n") or 0, "unreal": 0.0, "open": 0}

    async for r in gold_positions_collection.aggregate([
            {"$match": {"venue": v.key, "status": "OPEN"}},
            {"$group": {
                "_id": {"t": "$strategy_template", "tf": "$timeframe", "s": "$symbol"},
                "unreal": {"$sum": "$unrealized_pnl"}, "n": {"$sum": 1}}}]):
        k = (r["_id"]["t"], r["_id"]["tf"], r["_id"]["s"])
        row = rows.setdefault(k, {"pnl": [], "costs": 0.0, "trades": 0, "unreal": 0.0, "open": 0})
        row["unreal"] = r.get("unreal") or 0.0
        row["open"] = r.get("n") or 0

    out = []
    for (template, tf, symbol), agg in rows.items():
        spec = tmpl_tf.get((template, tf)) or by_spec.get(template)
        # `_trade_stats` wants documents, and it is imported rather than reimplemented so
        # this desk's verdict means exactly what every other desk's verdict means.
        docs = [{"realized_pnl": p} for p in agg["pnl"]]
        stats = _trade_stats(docs, base=v.capital)
        verdict, reasons = _verdict(stats)
        if v.currency != "INR":
            # The shared gate writes its reasons with a rupee sign because every desk that
            # used it until now was a rupee desk. Its TESTS are currency-free — a sign
            # test on net and expectancy, ratios everywhere else — so the same verdict is
            # correct here and only the symbol is wrong. Swapped rather than forked: a
            # second copy of the gate is how two desks start disagreeing about what
            # "passing" means.
            reasons = [r.replace("₹", "$") for r in reasons]
        out.append({
            "template": template, "timeframe": tf, "symbol": symbol,
            "name": spec.name if spec else f"{template} · {tf}",
            "family": spec.family if spec else "",
            "family_label": FAMILY_LABELS.get(spec.family, spec.family) if spec else "",
            "trades": stats.get("trades", 0),
            "win_rate": round((stats.get("win_rate") or 0.0) * 100, 1),
            "profit_factor": stats.get("profit_factor"),
            "expectancy": stats.get("expectancy", 0.0),
            "max_drawdown_pct": stats.get("max_drawdown_pct", 0.0),
            "t_stat": stats.get("t_stat"),
            "total_costs": round(agg["costs"], 2),
            "realized_pnl": stats.get("net_pnl", 0.0),
            "unrealized_pnl": round(agg["unreal"], 2),
            "open_positions": agg["open"],
            "verdict": verdict, "verdict_reasons": reasons,
        })
    out.sort(key=lambda r: (-(r["realized_pnl"] + r["unrealized_pnl"]), -r["trades"]))
    return out[:limit]


async def positions(v: Venue, status: str = "OPEN", limit: int = 200) -> list[dict]:
    q = {"venue": v.key, "status": "OPEN"} if status == "OPEN" else \
        {"venue": v.key, "status": {"$ne": "OPEN"}}
    sort_key = "opened_at" if status == "OPEN" else "closed_at"
    rows = []
    async for p in gold_positions_collection.find(q).sort(sort_key, -1).limit(limit):
        p.pop("_id", None)
        for k in ("opened_at", "closed_at", "updated_at", "entry_bar_ts"):
            if isinstance(p.get(k), datetime):
                p[k] = p[k].isoformat()
        rows.append(p)
    return rows


async def basis() -> dict:
    """What the two venues say the same ounce of gold is worth, right now.

    The one number neither tab can show on its own, and the reason this desk has two tabs
    rather than two pages: MCX quotes rupees per 10 grams with Indian import duty and GST
    inside the price, Delta quotes dollars per troy ounce for a token. Converted here to a
    common unit so the gap is visible — but reported as a comparison, never netted into a
    position, because nothing on this desk can trade one against the other."""
    GRAMS_PER_OZ = 31.1034768
    out: dict[str, dict] = {}

    mcx_uni = await universe(VENUES["mcx"])
    for sym in ("GOLDM", "GOLD"):
        inst = mcx_uni.get(sym)
        if not inst:
            continue
        px, src = await mark(VENUES["mcx"], sym, inst)
        if px:
            out["mcx"] = {"symbol": sym, "price": round(px, 2), "source": src,
                          "quote": "₹ per 10 grams",
                          "per_gram_inr": round(px / 10.0, 2),
                          "per_oz_inr": round(px / 10.0 * GRAMS_PER_OZ, 2)}
            break

    delta_uni = await universe(VENUES["delta"])
    legs = {}
    for sym, inst in delta_uni.items():
        px, _src = await mark(VENUES["delta"], sym, inst)
        if px:
            legs[sym] = round(px, 2)
    if legs:
        out["delta"] = {"prices": legs, "quote": "$ per troy ounce", "source": "delta",
                        # The two tokens are nominally the same ounce. They are not the
                        # same price, and the gap is the token basis rather than a data
                        # error — the desk this came from has seen them $15 apart.
                        "token_basis_usd": round(max(legs.values()) - min(legs.values()), 2)}

    if "mcx" in out and "delta" in out:
        usd_inr = float(os.getenv("GOLD_USD_INR", "0") or 0)
        if usd_inr > 0:
            d = sum(out["delta"]["prices"].values()) / len(out["delta"]["prices"])
            out["implied"] = {
                "usd_inr_used": usd_inr,
                "delta_per_oz_inr": round(d * usd_inr, 2),
                "mcx_per_oz_inr": out["mcx"]["per_oz_inr"],
                "premium_pct": round(
                    (out["mcx"]["per_oz_inr"] / (d * usd_inr) - 1) * 100, 2),
                "note": ("MCX carries import duty and GST inside the price, so a premium "
                         "here is expected rather than an arbitrage."),
            }
        else:
            out["implied"] = {
                "note": ("Set GOLD_USD_INR to compare the two in one currency. No rate is "
                         "assumed: a hardcoded one silently goes stale and would turn a "
                         "currency move into a fake gold premium."),
            }
    return out


async def ensure_indexes() -> None:
    """Index what this desk actually queries by.

    Every read here filters on `venue` first and then on `status`, and the bar store reads
    (symbol, timeframe, ts). Unindexed, those are collection scans that grow with the
    record — which is exactly how the commodity positions collection reached 29,192 rows
    and made a bare count take 21 seconds, taking its page down with it."""
    await gold_positions_collection.create_index([("venue", 1), ("status", 1)])
    await gold_positions_collection.create_index([("venue", 1), ("status", 1), ("closed_at", -1)])
    await gold_positions_collection.create_index(
        [("venue", 1), ("strategy_template", 1), ("timeframe", 1), ("symbol", 1), ("status", 1)])
    await gold_trades_collection.create_index([("venue", 1), ("closed_at", -1)])
    await gold_equity_collection.create_index([("venue", 1), ("ts", -1)])
    from app.core.db import gold_bars_collection
    await gold_bars_collection.create_index(
        [("symbol", 1), ("timeframe", 1), ("ts", -1)], unique=True)


async def coverage(v: Venue) -> dict:
    """Is there data under this tab at all — the diagnostic that separates a quiet market
    from a starved store."""
    if v.key == "delta":
        return await gold_delta_feed.coverage()
    from app.services.commodity_bars import coverage as mcx_coverage
    cov = await mcx_coverage()
    bars = cov.get("bars") if isinstance(cov, dict) else None
    if isinstance(bars, dict):
        cov = {**cov, "bars": {s: n for s, n in bars.items() if s in v.symbols}}
    return {"venue": "MCX", "symbols": list(v.symbols), **(cov if isinstance(cov, dict) else {})}
