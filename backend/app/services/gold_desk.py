"""Gold Desk — gold on two venues, rebuilt on its research (2026-10-11).

WHAT THE RESEARCH FOUND (GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md)
---------------------------------------------------------------
The desk's 353 pattern strategies were replayed on six gold histories with honest fills and
measured costs. Below 4h no strategy earns its fees on either venue; at 1d, 39 of 40 templates
lose to simply holding gold; no strategy survives deflation. Run with its old rules, each book
hit its 50% floor within weeks. One effect was consistent: the nine breakout / trend-structure
templates at 4h. So the desk now trades exactly what the evidence allows:

    DELTA   the pre-registered forward test H1 (gold_h1): those nine templates, 4h, XAUTUSD,
            each in its own sleeve of capital / 9 at 1x, recorded independently ("record" mode).
    MCX     nothing by default — every strategy was retired by the research. The venue keeps its
            corrected machinery ("account" mode: one book, real-account rules); `GOLD_MCX_STRATEGIES=h1`
            would run the same nine templates there as ordinary records — never part of H1.

WHAT WAS FIXED (the plan's C- and I-items)
-----------------------------------------
C1  signals on CLOSED bars only — the desk used to act on the half-formed candle. On Delta a bar
    is decided only once the store has re-read it after its close (gold_delta_feed.fetched_at),
    and a bar first seen more than 15 minutes after its close is skipped, never traded late.
C2  MCX positions are priced and closed on THEIR OWN contract; the roll window forces an exit;
    an expired contract settles at its last print.
C3  entries fill at the touch (the book walked if needed); exits are walked minute by minute
    (gold_fills) over FINAL minutes instead of filled at a polled price; market exits pay the
    measured half-spread; Delta funding is accrued at every exchange the walk has cleared, at the
    rate of the hour ending at it; a fee the venue does not publish refuses the trade.
C4  the hold limit counts bars (Delta: the 60th bar's close; MCX: trading time), not wall clock.
C5  account mode refuses an entry offsetting an open position on the same contract, caps net lots
    and keeps aggregate notional within the book; one Delta token; GOLD (1 kg) dropped.
C6  the daily breaker measures equity against the day's opening equity — every position counts.
C7  equity is sampled only while a book is on or has positions, and only when it changed (or
    every 30 minutes); the Delta feed is incremental (gold_delta_feed).
C8  strategies carry a RECORD, never a "READY"; the scheduler manages stops even when Main
    Control is off (entries need it on).
C9  session templates are not run on a market with no session.
I1  every timeframe below 4h is retired. I2 account mode refuses a lot whose stop risk exceeds its
    budget. I3 the MCX premium uses a live USD/INR. I5 measured costs are published (`costs`).

STILL PAPER. No order reaches a broker or an exchange from this module.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    commodity_bars_collection,
    gold_equity_collection,
    gold_positions_collection,
    gold_state_collection,
    gold_trades_collection,
)
from app.services import gold_delta_feed, gold_h1, mcx_market
from app.services.commodity_bars import IST, TIMEFRAMES as MCX_TIMEFRAMES, last_contract_price
from app.services.commodity_bars import load_bars as mcx_load_bars
from app.services.commodity_engine import _trade_stats, order_charges
from app.services.commodity_patterns import COMMODITY_CATALOG, FAMILY_LABELS, evaluate
from app.services.commodity_positions import multiplier
from app.services.commodity_prelive import margin_pct
from app.services.gold_fills import (
    funding_cost,
    funding_exchanges,
    market_exit_price,
    time_exit,
    walk_exit,
)

logger = logging.getLogger("gold_desk")

DELTA_GST = float(os.getenv("GOLD_DELTA_GST_PCT", "0.18"))
WINDOW_BARS = 250                 # the desk hands a pattern the last 250 closed bars
MIN_SERIES_BARS = 65              # and skips a series shorter than this
STALE_STORE_S = 600               # no 1m bars for this long while open: fall back to quotes
EQUITY_SAMPLE_EVERY_S = 1800      # an unchanged book is sampled at most this often
DATA_VERSION = 2

SESSION_TEMPLATES = frozenset({"opening_range", "gap_fade"})
RETIRED_TIMEFRAMES = frozenset(t.strip() for t in os.getenv(
    "GOLD_RETIRED_TIMEFRAMES", "1m,5m,15m,30m,45m,1h").split(",") if t.strip())
H1_PAIRS: tuple[tuple[str, str], ...] = tuple((t, gold_h1.H1_TIMEFRAME) for t in gold_h1.H1_TEMPLATES)


class GoldDeskError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _allowed(env: str, default: str) -> tuple[tuple[str, str], ...]:
    v = os.getenv(env, default).strip().lower()
    return H1_PAIRS if v == "h1" else ()


@dataclass(frozen=True)
class Venue:
    key: str
    label: str
    currency: str                  # INR | USD
    unit_label: str
    symbols: tuple[str, ...]
    capital: float
    mode: str                      # "record": each strategy its own sleeve | "account": one shared book
    allowed: tuple[tuple[str, str], ...]   # (template, timeframe) pairs this venue trades
    max_positions: int             # account mode: slots on the shared book
    max_hold_bars: int
    daily_loss_pct: float | None   # account mode breaker; None = off (it would censor a record)
    book_floor_pct: float          # entries stop below this share of capital — a ruin guard
    exit_slip_bp: float            # market exits pay this — the measured median half-spread
    max_net_units: int             # account mode: |net lots| per contract
    max_lot_risk_pct: float        # account mode: refuse a lot whose stop risk exceeds this share of equity
    session_templates_ok: bool     # False on a 24/7 venue (C9)
    funding: bool                  # perpetual funding is accrued
    quote_note: str
    retired: frozenset = field(default=RETIRED_TIMEFRAMES)
    max_entry_lag_s: int | None = None   # a bar first seen later than this after its close is skipped


VENUES: dict[str, Venue] = {
    "mcx": Venue(
        key="mcx", label="MCX Gold Futures", currency="INR", unit_label="lot",
        # GOLDM only: one GOLD (1 kg) lot is ~Rs 1.5 crore of notional and could never be sized on
        # this book — evaluating it every cycle bought nothing (D15).
        symbols=tuple(s.strip().upper() for s in os.getenv("GOLD_MCX_SYMBOLS", "GOLDM").split(",") if s.strip()),
        capital=float(os.getenv("GOLD_MCX_CAPITAL", "3000000")),
        mode="account",
        allowed=_allowed("GOLD_MCX_STRATEGIES", "none"),
        max_positions=int(os.getenv("GOLD_MCX_MAX_POSITIONS", "4")),
        max_hold_bars=60,
        daily_loss_pct=float(os.getenv("GOLD_MCX_DAILY_LOSS_PCT", "0.03")),
        book_floor_pct=float(os.getenv("GOLD_BOOK_FLOOR_PCT", "0.50")),
        exit_slip_bp=float(os.getenv("GOLD_MCX_EXIT_SLIP_BP", "0.64")),     # GOLDM median half-spread
        max_net_units=int(os.getenv("GOLD_MCX_MAX_NET_LOTS", "2")),
        max_lot_risk_pct=float(os.getenv("GOLD_MCX_MAX_LOT_RISK_PCT", "0.015")),
        session_templates_ok=True, funding=False,
        quote_note="₹ per 10 grams · whole GOLDM lots, broker-measured margin, fills at the bid / ask",
    ),
    "delta": Venue(
        key="delta", label="Delta Gold · H1 forward test", currency="USD", unit_label="contract",
        symbols=tuple(gold_delta_feed.SYMBOLS),
        capital=float(os.getenv("GOLD_DELTA_CAPITAL", "10000")),
        mode="record",
        allowed=_allowed("GOLD_DELTA_STRATEGIES", "h1"),
        max_positions=len(H1_PAIRS),
        max_hold_bars=60,
        daily_loss_pct=None,
        book_floor_pct=float(os.getenv("GOLD_BOOK_FLOOR_PCT", "0.50")),
        exit_slip_bp=float(os.getenv("GOLD_DELTA_EXIT_SLIP_BP", "0.04")),   # XAUT sleeve, measured
        max_net_units=0, max_lot_risk_pct=0.0,
        session_templates_ok=False, funding=True,
        quote_note="$ per troy ounce · one sleeve of capital / 9 per strategy at 1x, fills at the bid / ask",
        # The replay entered at the first minute after the close; a bar first seen long after it
        # closed (an outage, a fresh switch-on) is skipped rather than traded at a later price.
        max_entry_lag_s=int(os.getenv("GOLD_DELTA_MAX_ENTRY_LAG_S", "900")),
    ),
}
VENUE_KEYS = tuple(VENUES)


def venue(key: str) -> Venue:
    v = VENUES.get((key or "").lower())
    if v is None:
        raise KeyError(f"unknown gold venue {key!r} — expected one of {VENUE_KEYS}")
    return v


def specs_for(v: Venue) -> list:
    """The strategies this venue trades: its allow-list, minus retired timeframes, minus session
    templates where there is no session."""
    allowed = set(v.allowed)
    return [s for s in COMMODITY_CATALOG
            if (s.template, s.timeframe) in allowed
            and s.timeframe not in v.retired
            and (v.session_templates_ok or s.template not in SESSION_TEMPLATES)]


def timeframes_in_use(v: Venue) -> list[str]:
    order = list(MCX_TIMEFRAMES)
    return sorted({s.timeframe for s in specs_for(v)}, key=order.index)


def tf_minutes(v: Venue, tf: str) -> int:
    table = MCX_TIMEFRAMES if v.key == "mcx" else gold_delta_feed.TIMEFRAMES
    return table.get(tf, (None, 1440))[1]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(ts):
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _today_ist() -> date:
    return datetime.now(IST).date()


def _day_key(v: Venue) -> str:
    return (datetime.now(IST).date() if v.key == "mcx" else _now().date()).isoformat()


def is_open(v: Venue) -> bool:
    if v.key == "mcx":
        from app.services.commodity_bars import is_market_open
        return is_market_open(datetime.now(IST))
    return True


def _mcx_entries_known() -> bool:
    """New MCX exposure needs a holiday calendar that covers today. Older shared calendars do not
    carry the check; treat them as covered (the session gate still applies)."""
    from tradingai_shared import mcx_calendar as mcal
    known = getattr(mcal, "entry_calendar_known", None)
    return bool(known()) if callable(known) else True


async def load_bars(v: Venue, symbol: str, tf: str, limit: int, inst: dict | None = None):
    """CLOSED bars only (C1). MCX reads the position's own contract when one is given."""
    if v.key == "mcx":
        if inst and inst.get("expiry"):
            return await mcx_load_bars(symbol, tf, limit=limit, closed_only=True, prefer_expiry=inst.get("expiry"))
        return await mcx_load_bars(symbol, tf, limit=limit, closed_only=True)
    return await gold_delta_feed.load_bars(symbol, tf, limit=limit, closed_only=True)


# ── the tradable set and prices ──────────────────────────────────────────────────


async def universe(v: Venue) -> dict[str, dict]:
    """MCX: the roll-aware tradable contract per symbol. Delta: the product spec per symbol."""
    if v.key == "mcx":
        uni = await mcx_market.tradable_universe(list(v.symbols))
        return {s: uni[s] for s in v.symbols if s in uni}
    out: dict[str, dict] = {}
    for s in v.symbols:
        try:
            out[s] = await gold_delta_feed.product(s)
        except Exception as exc:                        # noqa: BLE001
            logger.warning("gold desk: no Delta product for %s (%s)", s, exc)
    return out


async def mcx_quote(contract: dict) -> mcx_market.McxQuote | None:
    tok = str(contract.get("angel_token") or contract.get("security_id") or "")
    if not tok:
        return None
    return (await mcx_market.quotes([contract])).get(tok)


def _qty_per_unit(v: Venue, symbol: str, inst: dict) -> float:
    """MCX: the published value multiplier (GOLDM 10). Delta: contract value (0.001 oz)."""
    if v.key == "mcx":
        return float(multiplier(symbol))
    return float(inst.get("contract_value") or 0.001)


def _fee(v: Venue, inst: dict, price: float, qty: float, is_buy: bool) -> float | None:
    """One executed side's charges, or None when the venue publishes no fee (refuse, D7)."""
    if v.key == "mcx":
        return order_charges(price, qty, is_buy)
    rate = inst.get("taker_fee_rate")
    if not rate:
        return None
    return price * qty * float(rate) * (1 + DELTA_GST)


# ── switches and state ───────────────────────────────────────────────────────────


async def get_state(v: Venue) -> dict:
    doc = await gold_state_collection.find_one({"_id": v.key}) or {}
    return {"enabled": bool(doc.get("enabled", False)), "last_run_at": doc.get("last_run_at"),
            "last_opened": doc.get("last_opened", 0), "last_managed": doc.get("last_managed", 0),
            "last_evaluated": doc.get("last_evaluated", 0), "last_notes": doc.get("last_notes", [])}


async def set_enabled(v: Venue, enabled: bool) -> dict:
    if enabled:
        if not specs_for(v):
            raise GoldDeskError(
                f"{v.label} has no strategy to trade: the research retired every one on this venue "
                "(GOLD_DESK_RESEARCH_AND_UPGRADE_PLAN.md). Nothing would happen if it were on.")
        if v.mode == "record" and any(gold_h1.is_h1(t, tf, s) for (t, tf) in v.allowed for s in v.symbols):
            got = await gold_h1.ensure_preregistered()
            if got.get("error"):
                raise GoldDeskError("H1's pre-registration could not be stored; the test cannot start.")
    await gold_state_collection.update_one(
        {"_id": v.key}, {"$set": {"enabled": bool(enabled), "updated_at": _now()}}, upsert=True)
    return await summary(v)


async def open_count(v: Venue) -> int:
    return await gold_positions_collection.count_documents({"venue": v.key, "status": "OPEN"})


# ── the book ─────────────────────────────────────────────────────────────────────


async def book(v: Venue) -> dict:
    """Balance, exposure and the realised / unrealised split, summed in Mongo."""
    agg = {"deployed": 0.0, "unreal": 0.0, "open": 0, "notional": 0.0}
    async for r in gold_positions_collection.aggregate([
            {"$match": {"venue": v.key, "status": "OPEN"}},
            {"$group": {"_id": None, "deployed": {"$sum": "$margin_used"}, "unreal": {"$sum": "$unrealized_pnl"},
                        "notional": {"$sum": "$notional"}, "n": {"$sum": 1}}}]):
        agg = {"deployed": r.get("deployed") or 0.0, "unreal": r.get("unreal") or 0.0,
               "open": r.get("n") or 0, "notional": r.get("notional") or 0.0}
    realized = costs = funding = 0.0
    closed = wins = 0
    async for r in gold_positions_collection.aggregate([
            {"$match": {"venue": v.key, "status": {"$ne": "OPEN"}, "void": {"$ne": True}}},
            {"$group": {"_id": None, "realized": {"$sum": "$realized_pnl"}, "costs": {"$sum": "$costs"},
                        "funding": {"$sum": "$funding_paid"}, "n": {"$sum": 1},
                        "wins": {"$sum": {"$cond": [{"$gt": ["$realized_pnl", 0]}, 1, 0]}}}}]):
        realized, costs = r.get("realized") or 0.0, r.get("costs") or 0.0
        funding, closed, wins = r.get("funding") or 0.0, r.get("n") or 0, r.get("wins") or 0
    unreal, deployed = agg["unreal"], agg["deployed"]
    total = realized + unreal
    return {
        "capital": v.capital,
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unreal, 2), "total_pnl": round(total, 2),
        "realized_pct": round(realized / v.capital * 100, 2), "unrealized_pct": round(unreal / v.capital * 100, 2),
        "total_pct": round(total / v.capital * 100, 2),
        "margin_deployed": round(deployed, 2), "open_notional": round(agg["notional"], 2),
        "available_margin": round(v.capital + realized - deployed, 2),
        "equity": round(v.capital + total, 2), "total_costs": round(costs, 2), "funding_paid": round(funding, 2),
        "open_positions": agg["open"], "closed_positions": closed,
        "win_rate": round(wins / closed * 100, 1) if closed else 0.0,
    }


async def day_open_equity(v: Venue, equity_now: float) -> float:
    """The equity at this venue's first cycle of the day (C6). IST day for MCX, UTC for Delta."""
    day = _day_key(v)
    st = await gold_state_collection.find_one({"_id": f"{v.key}:day"}) or {}
    if st.get("day") != day:
        await gold_state_collection.update_one({"_id": f"{v.key}:day"},
                                               {"$set": {"day": day, "open_equity": float(equity_now), "at": _now()}},
                                               upsert=True)
        return float(equity_now)
    return float(st.get("open_equity", equity_now))


# ── position lifecycle ───────────────────────────────────────────────────────────


async def _open(v: Venue, spec, symbol: str, inst: dict, sig, bar, tf_min: int, equity: float,
                prereg_fp: str | None) -> tuple[bool, str | None]:
    """Open one position at the market — or say why not. Never invents a price."""
    if await gold_positions_collection.find_one({"venue": v.key, "symbol": symbol, "strategy_template": spec.template,
                                                  "timeframe": spec.timeframe, "status": "OPEN"}):
        return False, None
    if not sig.entry:
        return False, None
    side = 1 if sig.side == "BUY" else -1
    per_unit = _qty_per_unit(v, symbol, inst)
    h1 = gold_h1.is_h1(spec.template, spec.timeframe, symbol) and v.mode == "record"
    if h1 and not prereg_fp:
        return False, "H1 is not pre-registered yet — no H1 position opens before its rule is stored."

    if v.key == "delta":
        if not inst.get("taker_fee_rate"):
            return False, f"{symbol}: the venue publishes no taker fee — refusing rather than charging zero."
        t = await gold_delta_feed.ticker(symbol)
        if not t or not t.get("mid"):
            return False, f"{symbol}: no two-sided market this cycle."
        sleeve = v.capital / max(len(specs_for(v)), 1)
        units = int(sleeve // (t["mid"] * per_unit))
        if units < 1:
            return False, f"{symbol}: one contract exceeds the {sleeve:,.2f} sleeve."
        f = await gold_delta_feed.fill_price(symbol, sig.side, units)
        if not f:
            return False, f"{symbol}: the visible book cannot fill {units} contracts."
        fill, basis, spread_bp, quote_doc = float(f["price"]), f["basis"], f["spread_bp"], f
        margin = notional = fill * units * per_unit
    else:
        q = await mcx_quote(inst)
        if q is None or not q.fresh or not q.ltp:
            return False, f"{symbol}: no live quote ({q.why if q else 'none'}) — no fill on a frozen price."
        touch = q.touch(sig.side)
        if not touch:
            return False, f"{symbol}: one-sided book."
        fill, basis, spread_bp, quote_doc = float(touch), "touch", q.spread_bp, q.as_doc()
        units = 1
        notional = fill * per_unit * units
        margin = margin_pct(symbol) * notional
        # C5: a real account nets a contract — refuse an entry that would offset an open position,
        # cap net lots, and never hold more notional than the book.
        same = [p async for p in gold_positions_collection.find(
            {"venue": v.key, "symbol": symbol, "status": "OPEN"}, {"side": 1, "units": 1, "notional": 1})]
        if any((p.get("side") == "BUY") != (side > 0) for p in same):
            return False, f"{symbol}: an open position on the other side — a real account would net it."
        if sum(int(p.get("units") or 1) for p in same) + units > v.max_net_units:
            return False, f"{symbol}: net {v.max_net_units} lots already held."
        b = await book(v)
        if b["open_notional"] + notional > v.capital:
            return False, f"{symbol}: another lot would hold more gold than the book can pay for."
        if b["available_margin"] < margin:
            return False, f"{symbol}: margin {margin:,.0f} exceeds the {b['available_margin']:,.0f} free."
        risk = abs(fill - float(sig.stoploss) * fill / float(sig.entry)) * per_unit * units
        if risk > v.max_lot_risk_pct * equity:
            return False, (f"{symbol}: one lot risks {risk:,.0f} to its stop, over the "
                           f"{v.max_lot_risk_pct:.1%} budget ({v.max_lot_risk_pct * equity:,.0f}).")

    ratio = fill / float(sig.entry)
    target, stop = float(sig.target) * ratio, float(sig.stoploss) * ratio
    qty = units * per_unit
    entry_costs = _fee(v, inst, fill, qty, side > 0)
    if entry_costs is None:
        return False, f"{symbol}: no fee published — refused."
    now = _now()
    bar_start = _aware(bar.ts)
    bar_close = bar_start + timedelta(minutes=tf_min)
    hold_until = (bar_close + timedelta(minutes=tf_min * v.max_hold_bars)) if v.key == "delta" else None
    next_minute = (int(now.timestamp()) // 60 + 1) * 60          # exits are walked from the next full minute
    await gold_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "venue": v.key, "currency": v.currency, "mode": v.mode,
        "strategy_id": spec.strategy_id, "strategy_template": spec.template, "strategy_name": spec.name,
        "family": spec.family, "family_label": FAMILY_LABELS.get(spec.family, spec.family),
        "timeframe": spec.timeframe, "pattern": sig.pattern, "symbol": symbol,
        "display_name": inst.get("symbol") or inst.get("description") or symbol,
        "instrument": {"symbol": inst.get("symbol") or symbol, "security_id": str(inst.get("security_id") or ""),
                       "angel_token": str(inst.get("angel_token") or inst.get("security_id") or ""),
                       "exchange_segment": inst.get("exchange_segment") or ("DELTA" if v.key == "delta" else "MCX"),
                       "expiry": inst.get("expiry"), "contract_value": inst.get("contract_value"),
                       "underlying_symbol": symbol},
        "side": sig.side, "signal_price": round(float(sig.entry), 4),
        "signal_bar_ts": bar_start, "signal_bar_close": bar_close,
        "entry_price": round(fill, 4), "entry_basis": basis,
        "entry_spread_bp": round(spread_bp, 4) if spread_bp is not None else None, "entry_quote": quote_doc,
        "units": units, "unit_label": v.unit_label, "lots": units, "multiplier": per_unit, "qty": qty,
        "notional": round(notional, 2), "margin_used": round(margin, 2), "capital_deployed": round(margin, 2),
        "fee_rate": inst.get("taker_fee_rate") if v.key == "delta" else None,
        "entry_costs": round(entry_costs, 4), "target": round(target, 4), "stoploss": round(stop, 4),
        "ltp": round(fill, 4), "unrealized_pnl": round(-entry_costs, 2), "return_on_margin_pct": 0.0,
        "funding_paid": 0.0, "funding_through": int(now.timestamp()), "funding_events": 0,
        "checked_through": next_minute, "hold_until": hold_until, "max_hold_bars": v.max_hold_bars,
        "bars_held": 0, "realized_pnl": None, "costs": None, "fees": None, "exit_price": None,
        "exit_reason": None, "status": "OPEN", "rationale": sig.rationale, "h1": h1,
        "prereg_fingerprint": prereg_fp if h1 else None, "data_version": DATA_VERSION,
        "opened_at": now, "opened_on": _today_ist().isoformat(), "updated_at": now, "closed_at": None,
    })
    return True, None


async def _close(v: Venue, pos: dict, fill: float, reason: str, basis: str, when: datetime,
                 inst: dict | None = None, quote: dict | None = None) -> float:
    """Close at `fill` (already the price the order got) and book costs, funding and net."""
    side = 1 if pos["side"] == "BUY" else -1
    qty = float(pos["qty"])
    gross = (fill - float(pos["entry_price"])) * qty * side
    inst = inst or {"taker_fee_rate": pos.get("fee_rate")}
    if v.key == "delta" and not inst.get("taker_fee_rate"):
        inst = {**inst, "taker_fee_rate": pos.get("fee_rate")}
    exit_fee = _fee(v, inst, fill, qty, side < 0) or 0.0
    funding = float(pos.get("funding_paid") or 0.0)
    costs = float(pos.get("entry_costs") or 0.0) + exit_fee + funding
    net = gross - costs
    notional = float(pos.get("notional") or 0.0)
    margin = float(pos.get("margin_used") or 0.0)
    fields = {"status": "CLOSED", "exit_price": round(fill, 4), "exit_reason": reason, "exit_basis": basis,
              "exit_quote": quote, "gross_pnl": round(gross, 2), "exit_costs": round(exit_fee, 4),
              "costs": round(costs, 4), "fees": round(costs, 4), "realized_pnl": round(net, 2),
              "funding_paid": round(funding, 6), "funding_through": pos.get("funding_through"),
              "funding_events": pos.get("funding_events", 0),
              "net_bp": round(net / notional * 1e4, 3) if notional else None,
              "return_on_margin_pct": round(net / margin * 100, 2) if margin else 0.0,
              "unrealized_pnl": 0.0, "closed_at": when,
              "closed_on": when.astimezone(IST).date().isoformat(), "updated_at": _now(), "ltp": round(fill, 4)}
    await gold_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "venue": v.key, "currency": v.currency, "position_id": pos.get("position_id"),
        "strategy_template": pos.get("strategy_template"), "strategy_name": pos.get("strategy_name"),
        "timeframe": pos.get("timeframe"), "pattern": pos.get("pattern"), "symbol": pos["symbol"],
        "side": pos["side"], "entry_price": pos["entry_price"], "units": pos.get("units"), "lots": pos.get("lots"),
        "qty": qty, "margin_used": round(margin, 2), "notional": round(notional, 2), "h1": bool(pos.get("h1")),
        "opened_at": pos["opened_at"], **fields})
    await gold_positions_collection.update_one({"_id": pos["_id"]}, {"$set": fields})
    return net


async def _accrue_funding(v: Venue, pos: dict, until_ts: int, inst: dict) -> dict:
    """Funding at every exchange the position was open across (C3). Positive = paid."""
    if not v.funding:
        return {}
    interval = int(inst.get("funding_interval_s") or 14400)
    since = int(pos.get("funding_through") or until_ts)
    times = funding_exchanges(since, until_ts, interval)
    if not times:
        return {}
    series = await gold_delta_feed.funding_series(pos["symbol"])
    side = 1 if pos["side"] == "BUY" else -1
    px = float(pos.get("ltp") or pos["entry_price"])
    paid, bases = 0.0, set()
    for t in times:
        rate, basis = gold_delta_feed.rate_at(series, t)
        if rate is None:
            rate, basis = 0.0, "unknown"
        bases.add(basis)
        paid += funding_cost(side, float(pos["qty"]) * px, rate)
    return {"funding_paid": round(float(pos.get("funding_paid") or 0.0) + paid, 6),
            "funding_through": times[-1], "funding_events": int(pos.get("funding_events") or 0) + len(times),
            "funding_basis": sorted(bases)}


async def _mcx_minutes(symbol: str, expiry: str | None, since_ts: int, until_ts: int) -> list[tuple]:
    """Completed 1m bars of ONE contract (the position's own) — the path its exit is walked over."""
    now = int(time.time())
    hi = min(int(until_ts), now - 59)
    if hi <= since_ts or not expiry:
        return []
    out = []
    async for d in commodity_bars_collection.find(
            {"symbol": symbol, "timeframe": "1m", "expiry": expiry,
             "ts": {"$gte": datetime.fromtimestamp(int(since_ts), timezone.utc),
                    "$lt": datetime.fromtimestamp(hi, timezone.utc)}},
            {"_id": 0, "ts": 1, "open": 1, "high": 1, "low": 1, "close": 1}).sort("ts", 1):
        ts = _aware(d["ts"])
        out.append((int(ts.timestamp()), float(d["open"]), float(d["high"]), float(d["low"]), float(d["close"])))
    return out


def _unrealized(v: Venue, pos: dict, mark: float, inst: dict) -> float:
    side = 1 if pos["side"] == "BUY" else -1
    qty = float(pos["qty"])
    gross = (mark - float(pos["entry_price"])) * qty * side
    if v.key == "delta" and not inst.get("taker_fee_rate"):
        inst = {**inst, "taker_fee_rate": pos.get("fee_rate")}
    exit_fee = _fee(v, inst, mark, qty, side < 0) or 0.0
    return gross - float(pos.get("entry_costs") or 0.0) - exit_fee - float(pos.get("funding_paid") or 0.0)


async def _manage_delta(v: Venue, pos: dict, inst: dict) -> str | None:
    """Walk the position's minutes since its last check; exit at a level, at the hold limit, or —
    when the bar store has gone stale — on the live book, never beyond a level."""
    side = 1 if pos["side"] == "BUY" else -1
    now = int(time.time())
    hold = _aware(pos.get("hold_until"))
    hold_ts = int(hold.timestamp()) if hold else None
    since = int(pos.get("checked_through") or now)
    until = min(now, hold_ts) if hold_ts else now
    mins = await gold_delta_feed.minutes(pos["symbol"], since, until)
    ex = walk_exit(side, mins, float(pos["target"]), float(pos["stoploss"]))
    if ex:
        fill = ex.price if ex.reason == "target" else market_exit_price(ex.price, side, v.exit_slip_bp)
        # Open across an exchange at the exit minute's open; gone before one at its end.
        fund = await _accrue_funding(v, pos, ex.ts, inst)
        await _close(v, {**pos, **fund}, fill, ex.reason, f"minute_{ex.basis}",
                     datetime.fromtimestamp(ex.ts + 60, timezone.utc), inst)
        return ex.reason
    if hold_ts and now >= hold_ts:
        done = await gold_delta_feed.fetched_at(pos["symbol"], "1m")
        if done is not None and done >= hold_ts + gold_delta_feed.FINAL_MARGIN_S:
            # Every minute up to the hold limit is final and none reached a level: a market order
            # at the hold limit, at the last minute's close — out before that moment's exchange.
            te = time_exit(mins, hold_ts) if mins else None
            if te is None:
                tail = await gold_delta_feed.minutes(pos["symbol"], hold_ts - 1800, hold_ts)
                te = time_exit(tail, hold_ts)
            if te:
                fund = await _accrue_funding(v, pos, hold_ts - 1, inst)
                await _close(v, {**pos, **fund}, market_exit_price(te[1], side, v.exit_slip_bp), "max_hold",
                             "minute_close", datetime.fromtimestamp(hold_ts, timezone.utc), inst)
                return "max_hold"
        if now - hold_ts > STALE_STORE_S:
            # The store has not reached the hold limit in ten minutes: leave on the live book, and
            # pay for what was really held.
            f = await gold_delta_feed.fill_price(pos["symbol"], "SELL" if side > 0 else "BUY", int(pos["units"]))
            if f:
                fund = await _accrue_funding(v, pos, now, inst)
                await _close(v, {**pos, **fund}, float(f["price"]), "max_hold", "quote_fallback", _now(), inst, f)
                return "max_hold"
        # Otherwise wait for the store to reach the hold limit; the walk so far is kept below.
    changes: dict = {"updated_at": _now()}
    if mins:
        changes["checked_through"] = mins[-1][0] + 60
        changes["store_stale"] = False
    elif now - since > STALE_STORE_S:
        # The store has stopped advancing: judge the levels on the live book, never beyond them.
        t = await gold_delta_feed.ticker(pos["symbol"])
        if t and t.get("bid") and t.get("ask"):
            px = t["bid"] if side > 0 else t["ask"]
            hit_t = px >= pos["target"] if side > 0 else px <= pos["target"]
            hit_s = px <= pos["stoploss"] if side > 0 else px >= pos["stoploss"]
            if hit_t or hit_s:
                fund = await _accrue_funding(v, pos, now, inst)
                fill = float(pos["target"]) if hit_t else float(px)
                await _close(v, {**pos, **fund}, fill, "target" if hit_t else "stoploss", "quote_fallback",
                             _now(), inst, t)
                return "target" if hit_t else "stoploss"
        changes["store_stale"] = True
    # Funding only over the stretch the walk has cleared: a later walk can still find an exit
    # before an exchange that has passed on the clock, and the position must not have paid it.
    covered = int(changes.get("checked_through") or since)
    changes.update(await _accrue_funding(v, pos, min(covered, hold_ts - 1) if hold_ts else covered, inst))
    if hold_ts:
        changes["bars_held"] = max(0, int((now - int(_aware(pos["signal_bar_close"]).timestamp())) //
                                          (tf_minutes(v, pos["timeframe"]) * 60)))
    mark = await gold_delta_feed.mark_price(pos["symbol"])
    if mark:
        unreal = _unrealized(v, {**pos, **changes}, mark, inst)
        changes.update(ltp=round(mark, 4), unrealized_pnl=round(unreal, 2),
                       return_on_margin_pct=round(unreal / float(pos["margin_used"]) * 100, 2) if pos.get("margin_used") else 0.0)
    await gold_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
    return None


async def _manage_mcx(v: Venue, pos: dict) -> str | None:
    """Own contract (C2): settle an expired one, force out of the roll window, walk the minutes."""
    from tradingai_shared import mcx_calendar as mcal

    contract = mcx_market.position_contract(pos)
    inst = {**contract}
    side = 1 if pos["side"] == "BUY" else -1
    forced = mcx_market.forced_exit(pos)
    if forced == "contract_expired":
        got = await last_contract_price(pos["symbol"], contract.get("expiry"))
        if got:
            await _close(v, pos, float(got[0]), "contract_expired", "contract_last_bar", _now(), inst)
            return "contract_expired"
        if pos.get("ltp"):
            await _close(v, pos, float(pos["ltp"]), "contract_expired", "last_mark", _now(), inst)
            return "contract_expired"
        await gold_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
            "status": "VOID", "void": True, "void_reason": "expired with no recorded price", "updated_at": _now()}})
        return "void"
    q = await mcx_quote(contract)
    exit_side = "SELL" if side > 0 else "BUY"
    if forced == "roll_exit":
        if q is not None and q.fresh and q.touch(exit_side):
            await _close(v, pos, float(q.touch(exit_side)), "roll_exit", "touch", _now(), inst, q.as_doc())
            return "roll_exit"
        await gold_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
            "quote_status": "roll window: waiting for a live quote on its own contract", "updated_at": _now()}})
        return None
    now = int(time.time())
    since = int(pos.get("checked_through") or now)
    mins = await _mcx_minutes(pos["symbol"], contract.get("expiry"), since, now)
    ex = walk_exit(side, mins, float(pos["target"]), float(pos["stoploss"]))
    if ex:
        fill = ex.price if ex.reason == "target" else market_exit_price(ex.price, side, v.exit_slip_bp)
        await _close(v, pos, fill, ex.reason, f"minute_{ex.basis}", datetime.fromtimestamp(ex.ts + 60, timezone.utc), inst)
        return ex.reason
    bars_held = mcal.bars_elapsed(_aware(pos["signal_bar_ts"]), tf_minutes(v, pos["timeframe"]))
    changes: dict = {"updated_at": _now(), "bars_held": bars_held}
    if mins:
        changes["checked_through"] = mins[-1][0] + 60
    fresh = q is not None and q.fresh and q.ltp
    # The signal bar is bar 0 and entry is in bar 1, so the 60th bar after it has closed when
    # 61 bars have elapsed since the signal bar opened.
    if bars_held >= int(pos.get("max_hold_bars") or v.max_hold_bars) + 1 and fresh and q.touch(exit_side):
        await _close(v, pos, float(q.touch(exit_side)), "max_hold", "touch", _now(), inst, q.as_doc())
        return "max_hold"
    if not mins and now - since > STALE_STORE_S and fresh:
        px = q.touch(exit_side)
        if px:
            hit_t = px >= pos["target"] if side > 0 else px <= pos["target"]
            hit_s = px <= pos["stoploss"] if side > 0 else px >= pos["stoploss"]
            if hit_t or hit_s:
                await _close(v, pos, float(pos["target"]) if hit_t else float(px),
                             "target" if hit_t else "stoploss", "quote_fallback", _now(), inst, q.as_doc())
                return "target" if hit_t else "stoploss"
    if q is not None and q.ltp:
        unreal = _unrealized(v, pos, float(q.ltp), inst)
        changes.update(ltp=round(float(q.ltp), 4), unrealized_pnl=round(unreal, 2),
                       quote_status="live" if q.fresh else (q.why or "stale"),
                       return_on_margin_pct=round(unreal / float(pos["margin_used"]) * 100, 2) if pos.get("margin_used") else 0.0)
    await gold_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
    return None


async def manage_cycle(v: Venue) -> int:
    """Every open position, on its own contract and its own minutes. Runs whether or not the
    book may add positions — an open position is exposure with a stop."""
    open_pos = [p async for p in gold_positions_collection.find({"venue": v.key, "status": "OPEN"})]
    if not open_pos:
        return 0
    uni = await universe(v) if v.key == "delta" else {}
    n = 0
    for pos in open_pos:
        try:
            if v.key == "delta":
                inst = uni.get(pos["symbol"]) or {"taker_fee_rate": pos.get("fee_rate"), "funding_interval_s": 14400}
                await _manage_delta(v, pos, inst)
            else:
                await _manage_mcx(v, pos)
            n += 1
        except Exception:  # noqa: BLE001 - one position's failure must not strand the others
            logger.exception("[gold %s] managing %s failed", v.key, pos.get("position_id"))
    return n


async def scan_cycle(v: Venue, entries_allowed: bool = True) -> dict:
    """Evaluate the venue's strategies on each newly CLOSED bar and open what signals."""
    specs = specs_for(v)
    if not specs:
        return {"opened": 0, "evaluated": 0, "notes": [
            f"{v.label}: no strategy is enabled — the research retired every one on this venue."]}
    state = await get_state(v)
    if not state["enabled"]:
        return {"opened": 0, "evaluated": 0, "notes": ["Switched OFF — no new entries; open positions are still managed."]}
    if not entries_allowed:
        return {"opened": 0, "evaluated": 0, "notes": ["Main Control has the Gold Desk off — no new entries; stops are still managed."]}
    if v.key == "mcx" and not _mcx_entries_known():
        return {"opened": 0, "evaluated": 0, "notes": ["New entries blocked: the MCX holiday calendar does not cover today."]}
    b = await book(v)
    if b["equity"] <= v.capital * v.book_floor_pct:
        return {"opened": 0, "evaluated": 0, "notes": [
            f"Book floor reached: equity {b['equity']:,.2f} is at or below {v.book_floor_pct:.0%} of capital."]}
    if v.daily_loss_pct:
        start = await day_open_equity(v, b["equity"])
        if b["equity"] - start <= -v.daily_loss_pct * v.capital:
            return {"opened": 0, "evaluated": 0, "notes": [
                f"Daily loss breaker: {b['equity'] - start:,.2f} since the day opened at {start:,.2f}."]}
    uni = await universe(v)
    if not uni:
        return {"opened": 0, "evaluated": 0, "notes": [f"No tradable {v.label} contract resolved."]}
    prereg = await gold_h1.stored() if v.mode == "record" else None
    prereg_fp = prereg.get("fingerprint") if prereg else None
    guard = await gold_state_collection.find_one({"_id": f"{v.key}:entry_bars"}) or {}
    last = guard.get("last", {})
    fresh: dict[str, str] = {}
    notes: set[str] = set()
    opened = evaluated = 0
    open_now = b["open_positions"]
    now = _now()
    for symbol, inst in uni.items():
        for tf in timeframes_in_use(v):
            tfm = tf_minutes(v, tf)
            bars = await load_bars(v, symbol, tf, WINDOW_BARS, inst)
            if len(bars) < MIN_SERIES_BARS:
                notes.add(f"{symbol} {tf}: only {len(bars)} closed bars in the store.")
                continue
            bar = bars[-1]
            bar_close = _aware(bar.ts) + timedelta(minutes=tfm)
            age = (now - bar_close).total_seconds()
            if age > tfm * 60:
                notes.add(f"{symbol} {tf}: the newest closed bar is stale — no decision on an old bar.")
                continue
            if v.key == "delta":
                # Closed by the clock is not enough: the store must have re-read the bar after its
                # close, or its last seconds — where a breakout can form — are missing.
                done = await gold_delta_feed.fetched_at(symbol, tf)
                if done is None or done < bar_close.timestamp() + gold_delta_feed.FINAL_MARGIN_S:
                    notes.add(f"{symbol} {tf}: the bar that closed at {bar_close:%H:%M} UTC has not been "
                              "re-read since its close — decided on the next cycle.")
                    continue
            late = v.max_entry_lag_s is not None and age > v.max_entry_lag_s
            for spec in (s for s in specs if s.timeframe == tf):
                key = f"{symbol}:{spec.template}:{tf}"
                if last.get(key) == str(bar.ts):
                    continue               # one decision per closed bar — it cannot change
                fresh[key] = str(bar.ts)
                if late:
                    notes.add(f"{symbol} {tf}: the bar that closed at {bar_close:%H:%M} UTC was first seen "
                              f"{age / 60:.0f} min after its close — skipped, never traded late.")
                    continue
                if len(bars) < spec.min_bars + 5:
                    continue
                evaluated += 1
                sig = evaluate(spec, bars)
                if sig is None:
                    continue
                if v.mode == "account" and open_now >= v.max_positions:
                    notes.add(f"All {v.max_positions} slots in use.")
                    continue
                ok, why = await _open(v, spec, symbol, inst, sig, bar, tfm, b["equity"], prereg_fp)
                if ok:
                    opened += 1
                    open_now += 1
                elif why:
                    notes.add(why)
    if fresh:
        await gold_state_collection.update_one({"_id": f"{v.key}:entry_bars"},
                                               {"$set": {f"last.{k}": val for k, val in fresh.items()}}, upsert=True)
    return {"opened": opened, "evaluated": evaluated, "notes": sorted(notes)[:12]}


async def run_cycle(v: Venue, entries_allowed: bool = True) -> dict:
    managed = await manage_cycle(v)
    scan = await scan_cycle(v, entries_allowed)
    if v.mode == "record":
        await gold_h1.snapshot_boundaries()      # XAUT at each H1 week boundary, as it passes
    b = await book(v)
    state = await get_state(v)
    if state["enabled"] or b["open_positions"] > 0:
        last = await gold_state_collection.find_one({"_id": f"{v.key}:equity_last"}) or {}
        at = _aware(last.get("at"))
        changed = (round(float(last.get("equity", -1)), 2) != b["equity"]
                   or int(last.get("open", -1)) != b["open_positions"])
        if changed or at is None or (_now() - at).total_seconds() >= EQUITY_SAMPLE_EVERY_S:
            await gold_equity_collection.insert_one({
                "ts": _now(), "venue": v.key, "equity": b["equity"], "realized": b["realized_pnl"],
                "unrealized": b["unrealized_pnl"], "margin_deployed": b["margin_deployed"],
                "open_positions": b["open_positions"]})
            await gold_state_collection.update_one({"_id": f"{v.key}:equity_last"}, {"$set": {
                "equity": b["equity"], "open": b["open_positions"], "at": _now()}}, upsert=True)
    await gold_state_collection.update_one({"_id": v.key}, {"$set": {
        "last_run_at": _now(), "last_opened": scan["opened"], "last_managed": managed,
        "last_evaluated": scan["evaluated"], "last_notes": scan["notes"], "market_open": is_open(v)}}, upsert=True)
    return {"venue": v.key, "opened": scan["opened"], "managed": managed, "evaluated": scan["evaluated"],
            "notes": scan["notes"]}


async def close_all(v: Venue, reason: str = "manual_close_all") -> dict:
    """Square off at the market — the touch of each position's own instrument. A position with no
    live price is left open and named, never closed at a stale one."""
    open_pos = [p async for p in gold_positions_collection.find({"venue": v.key, "status": "OPEN"})]
    closed, net, left = 0, 0.0, []
    uni = await universe(v) if v.key == "delta" else {}
    for pos in open_pos:
        side = 1 if pos["side"] == "BUY" else -1
        exit_side = "SELL" if side > 0 else "BUY"
        if v.key == "delta":
            inst = uni.get(pos["symbol"]) or {"taker_fee_rate": pos.get("fee_rate"), "funding_interval_s": 14400}
            f = await gold_delta_feed.fill_price(pos["symbol"], exit_side, int(pos["units"]))
            if not f:
                left.append(pos["position_id"])
                continue
            fund = await _accrue_funding(v, pos, int(time.time()), inst)
            net += await _close(v, {**pos, **fund}, float(f["price"]), reason, f["basis"], _now(), inst, f)
        else:
            contract = mcx_market.position_contract(pos)
            q = await mcx_quote(contract)
            if q is None or not q.fresh or not q.touch(exit_side):
                left.append(pos["position_id"])
                continue
            net += await _close(v, pos, float(q.touch(exit_side)), reason, "touch", _now(), contract, q.as_doc())
        closed += 1
    return {"closed": closed, "net_pnl": round(net, 2), "left_open_no_live_price": left}


# ── read models ──────────────────────────────────────────────────────────────────


async def summary(v: Venue) -> dict:
    state = await get_state(v)
    b = await book(v)
    specs = specs_for(v)
    day = await gold_state_collection.find_one({"_id": f"{v.key}:day"}) or {}
    today = (b["equity"] - float(day["open_equity"])) if day.get("day") == _day_key(v) else 0.0
    limit = (v.daily_loss_pct or 0.0) * v.capital
    floor = v.capital * v.book_floor_pct
    out = {
        "venue": v.key, "label": v.label, "currency": v.currency, "unit_label": v.unit_label,
        "quote_note": v.quote_note, "mode": v.mode, "symbols": list(v.symbols), "tradable_symbols": list(v.symbols),
        **state, **b,
        "today_pnl": round(today, 2), "today_pct": round(today / v.capital * 100, 2),
        "daily_loss_limit": round(limit, 2) if v.daily_loss_pct else None,
        "breaker_tripped": bool(v.daily_loss_pct) and today <= -limit,
        "book_floor": round(floor, 2), "book_floor_pct": v.book_floor_pct, "floor_reached": b["equity"] <= floor,
        "market_open": is_open(v), "max_positions": v.max_positions if v.mode == "account" else len(specs),
        "exit_slip_bp": v.exit_slip_bp, "slippage_bps": v.exit_slip_bp, "max_hold_bars": v.max_hold_bars,
        "max_entry_lag_s": v.max_entry_lag_s,
        "strategy_count": len(specs), "stream_count": len(specs) * len(v.symbols),
        "strategies_enabled": [s.name for s in specs], "retired_timeframes": sorted(v.retired),
        "can_enable": bool(specs),
        "why_off": None if specs else "The research retired every strategy on this venue — nothing earned its costs.",
        "funding": v.funding,
        "fee_note": ("Angel MCX charges on both legs (Rs 305 a GOLDM round trip ≈ 2.03 bp); entries at the bid / ask; "
                     f"market exits {v.exit_slip_bp} bp (the measured median half-spread)." if v.key == "mcx" else
                     "Delta's own taker rate (product spec) + 18% GST on both legs; entries at the bid / ask; market "
                     f"exits {v.exit_slip_bp} bp; funding at every 4-hourly exchange."),
    }
    if v.mode == "record":
        st = await gold_h1.stored()
        out["h1"] = {"preregistered": bool(st), "fingerprint": st.get("fingerprint") if st else None,
                     "stored_at": _aware(st["stored_at"]).isoformat() if st else None}
    return out


def _bp_stats(rows: list[dict]) -> tuple[float | None, float | None]:
    xs = [float(r["net_bp"]) for r in rows if r.get("net_bp") is not None]
    if not xs:
        return None, None
    m = sum(xs) / len(xs)
    if len(xs) < 3:
        return round(m, 3), None
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return round(m, 3), (round(m / (sd / math.sqrt(len(xs))), 3) if sd > 0 else None)


async def strategies(v: Venue, limit: int = 400) -> list[dict]:
    """One row per strategy that is enabled or has traded: its RECORD (C8). A record states what
    happened on honest fills; promotion is the Commodity Lab's job, and H1's verdict its own."""
    rows: dict[tuple, dict] = {}
    for s in specs_for(v):
        for sym in v.symbols:
            rows[(s.template, s.timeframe, sym)] = {"closed": [], "unreal": 0.0, "open": 0}
    async for p in gold_positions_collection.find(
            {"venue": v.key, "void": {"$ne": True}},
            {"strategy_template": 1, "timeframe": 1, "symbol": 1, "status": 1, "realized_pnl": 1,
             "costs": 1, "net_bp": 1, "unrealized_pnl": 1, "closed_at": 1}).sort("closed_at", 1):
        k = (p.get("strategy_template"), p.get("timeframe"), p.get("symbol"))
        r = rows.setdefault(k, {"closed": [], "unreal": 0.0, "open": 0})
        if p.get("status") == "OPEN":
            r["open"] += 1
            r["unreal"] += float(p.get("unrealized_pnl") or 0.0)
        else:
            r["closed"].append(p)
    by = {(s.template, s.timeframe): s for s in COMMODITY_CATALOG}
    enabled = {(s.template, s.timeframe) for s in specs_for(v)}
    out = []
    for (template, tf, symbol), agg in rows.items():
        spec = by.get((template, tf))
        stats = _trade_stats([{"realized_pnl": p.get("realized_pnl"), "costs": p.get("costs")} for p in agg["closed"]],
                             base=v.capital / max(len(enabled), 1) if v.mode == "record" else v.capital)
        mean_bp, t_bp = _bp_stats(agg["closed"])
        n = stats.get("trades", 0)
        reason = (f"{n} trades on honest fills — too few for a t-statistic to mean anything." if n < 20 else
                  f"{n} trades, mean {mean_bp:+.2f} bp net, t {t_bp if t_bp is not None else 'n/a'}. A record, "
                  "not a verdict.")
        h1 = gold_h1.is_h1(template, tf, symbol) and v.mode == "record"
        if h1:
            reason += " Part of H1 — judged only by its pre-registered rule."
        out.append({
            "template": template, "timeframe": tf, "symbol": symbol,
            "name": spec.name if spec else f"{template} · {tf}", "family": spec.family if spec else "",
            "family_label": FAMILY_LABELS.get(spec.family, spec.family) if spec else "",
            "enabled": (template, tf) in enabled, "h1": h1,
            "trades": n, "win_rate": round((stats.get("win_rate") or 0.0) * 100, 1),
            "profit_factor": stats.get("profit_factor"), "expectancy": stats.get("expectancy", 0.0),
            "net_bp_mean": mean_bp, "net_bp_t": t_bp, "max_drawdown_pct": stats.get("max_drawdown_pct", 0.0),
            "t_stat": stats.get("t_stat"),
            "total_costs": round(sum(float(p.get("costs") or 0) for p in agg["closed"]), 2),
            "realized_pnl": stats.get("net_pnl", 0.0), "unrealized_pnl": round(agg["unreal"], 2),
            "open_positions": agg["open"], "verdict": "RECORD", "verdict_reasons": [reason],
        })
    out.sort(key=lambda r: (not r["enabled"], -(r["realized_pnl"] + r["unrealized_pnl"]), -r["trades"]))
    return out[:limit]


def _jsonable(x):
    if isinstance(x, datetime):
        return _aware(x).isoformat()
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_jsonable(v) for v in x]
    return x


async def positions(v: Venue, status: str = "OPEN", limit: int = 200) -> list[dict]:
    q = {"venue": v.key, "status": "OPEN"} if status == "OPEN" else {"venue": v.key, "status": {"$ne": "OPEN"}}
    sort_key = "opened_at" if status == "OPEN" else "closed_at"
    rows = []
    async for p in gold_positions_collection.find(q).sort(sort_key, -1).limit(limit):
        p.pop("_id", None)
        rows.append(_jsonable(p))
    return rows


_USDINR: dict = {"rate": None, "at": 0.0, "asof": None}


async def usd_inr() -> tuple[float | None, str | None]:
    """A live USD/INR (I3), cached ten minutes: Yahoo's INR=X via the global-cues reader."""
    if _USDINR["rate"] and time.monotonic() - _USDINR["at"] < 600:
        return _USDINR["rate"], _USDINR.get("asof")
    try:
        import httpx

        from app.services.global_cues import HEADERS, _chart
        async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as c:
            ch = await _chart(c, "INR=X", "5d")
        price = ((ch or {}).get("meta") or {}).get("regularMarketPrice")
        if price:
            _USDINR.update(rate=float(price), at=time.monotonic(), asof=_now().isoformat())
            return float(price), _USDINR["asof"]
    except Exception:  # noqa: BLE001
        logger.info("gold desk: USD/INR unavailable", exc_info=True)
    env = float(os.getenv("GOLD_USD_INR", "0") or 0)
    return (env, "GOLD_USD_INR") if env > 0 else (None, None)


async def basis() -> dict:
    """What MCX and Delta say the same ounce is worth — compared, never netted."""
    GRAMS_PER_OZ = 31.1034768
    out: dict[str, dict] = {}
    mcx_uni = await universe(VENUES["mcx"])
    inst = mcx_uni.get("GOLDM")
    if inst:
        q = await mcx_quote(inst)
        if q is not None and q.ltp:
            px = float(q.ltp)
            out["mcx"] = {"symbol": "GOLDM", "price": round(px, 2), "source": "angel", "fresh": bool(q.fresh),
                          "quote": "₹ per 10 grams", "per_gram_inr": round(px / 10.0, 2),
                          "per_oz_inr": round(px / 10.0 * GRAMS_PER_OZ, 2)}
    legs = {}
    for sym in gold_delta_feed.BASIS_SYMBOLS:
        m = await gold_delta_feed.mark_price(sym)
        if m:
            legs[sym] = round(m, 2)
    if legs:
        out["delta"] = {"prices": legs, "quote": "$ per troy ounce", "source": "delta",
                        "token_basis_usd": round(max(legs.values()) - min(legs.values()), 2)}
    if "mcx" in out and "delta" in out:
        rate, asof = await usd_inr()
        d = legs.get("XAUTUSD") or sum(legs.values()) / len(legs)
        if rate:
            out["implied"] = {"usd_inr_used": round(rate, 4), "usd_inr_asof": asof,
                              "delta_per_oz_inr": round(d * rate, 2), "mcx_per_oz_inr": out["mcx"]["per_oz_inr"],
                              "premium_pct": round((out["mcx"]["per_oz_inr"] / (d * rate) - 1) * 100, 2),
                              "note": "MCX carries import duty and a local premium inside the price — "
                                      "a premium here is expected, not an arbitrage."}
        else:
            out["implied"] = {"note": "USD/INR unavailable right now, so the two are not compared."}
    return out


async def costs() -> dict:
    """The measured cost of trading here (I5): fees from the venue, spreads from the books."""
    out: dict = {}
    try:
        spec = await gold_delta_feed.product("XAUTUSD")
        series = await gold_delta_feed.funding_series("XAUTUSD")
        recent = [r for t, r in series if t >= int(time.time()) - 7 * 86400]
        interval = spec.get("funding_interval_s", 14400) or 14400
        mean = (sum(recent) / len(recent)) if recent else None
        out["delta"] = {
            "symbol": "XAUTUSD", "taker_fee_pct": (spec.get("taker_fee_rate") or 0) * 100,
            "maker_fee_pct": (spec.get("maker_fee_rate") or 0) * 100, "gst_pct": DELTA_GST * 100,
            "round_trip_fee_bp": round(2 * (spec.get("taker_fee_rate") or 0) * (1 + DELTA_GST) * 1e4, 3),
            "exit_slip_bp": VENUES["delta"].exit_slip_bp,
            "funding_interval_h": round(interval / 3600, 2),
            "funding_rate_pct_last": recent[-1] if recent else None,
            "funding_rate_pct_mean_7d": round(mean, 6) if mean is not None else None,
            # % per exchange x exchanges a day x 100 bp per % — what a long pays a day
            "funding_bp_per_day_long": round(mean * 86400 / interval * 100, 3) if mean is not None else None,
            "spreads": await gold_delta_feed.cost_stats("XAUTUSD"),
        }
    except Exception as exc:  # noqa: BLE001
        out["delta"] = {"error": str(exc)[:160]}
    try:
        stats = [s for s in await mcx_market.spread_stats(30) if s.get("underlying") == "GOLDM"]
        from tradingai_shared.mcx_fees import mcx_round_trip
        px, q = 150000.0, None
        uni = await universe(VENUES["mcx"])
        if uni.get("GOLDM"):
            q = await mcx_quote(uni["GOLDM"])
            if q is not None and q.ltp:
                px = float(q.ltp)
        rt = mcx_round_trip(px, px, 10.0, "BUY")
        out["mcx"] = {"symbol": "GOLDM", "lot_notional_inr": round(px * 10, 0), "round_trip_fee_inr": rt,
                      "round_trip_fee_bp": round(rt / (px * 10) * 1e4, 3), "exit_slip_bp": VENUES["mcx"].exit_slip_bp,
                      "spreads": stats[0] if stats else None,
                      "live_spread_bp": round(q.spread_bp, 3) if q is not None and q.spread_bp is not None else None}
    except Exception as exc:  # noqa: BLE001
        out["mcx"] = {"error": str(exc)[:160]}
    return out


async def ensure_indexes() -> None:
    """Never raises — a raising startup hook once took the whole backend down."""
    try:
        await gold_positions_collection.create_index([("venue", 1), ("status", 1)])
        await gold_positions_collection.create_index([("venue", 1), ("status", 1), ("closed_at", -1)])
        await gold_positions_collection.create_index(
            [("venue", 1), ("strategy_template", 1), ("timeframe", 1), ("symbol", 1), ("status", 1)])
        await gold_positions_collection.create_index([("venue", 1), ("h1", 1), ("status", 1)])
        await gold_trades_collection.create_index([("venue", 1), ("closed_at", -1)])
        await gold_equity_collection.create_index([("venue", 1), ("ts", -1)])
    except Exception as exc:  # noqa: BLE001
        logger.warning("gold desk indexes skipped: %s", exc)
    await gold_delta_feed.ensure_indexes()


async def coverage(v: Venue) -> dict:
    if v.key == "delta":
        return await gold_delta_feed.coverage()
    from app.services.commodity_bars import coverage as mcx_coverage
    cov = await mcx_coverage()
    bars = cov.get("bars") if isinstance(cov, dict) else None
    if isinstance(bars, dict):
        cov = {**cov, "bars": {s: n for s, n in bars.items() if s in v.symbols}}
    return {"venue": "MCX", "symbols": list(v.symbols), **(cov if isinstance(cov, dict) else {})}
