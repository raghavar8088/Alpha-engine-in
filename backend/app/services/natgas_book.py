"""Natural Gas Paper Trading — Rs 2,00,000 on two hand-picked NATGASMINI strategies.

WHAT THIS IS
The Pre-Live Commodity desk runs every admitted pattern on every mini contract, each
contract on its own Rs 2 lakh book. Two of its natural-gas strategies stood out on that
desk's own whole-lot record:

    Trend Pullback to EMA  · 1m   (ema_pullback)   21 trades  71% win  PF 7.86  +Rs13,808
    Hammer / Shooting Star · 5m   (hammer_star)    21 trades  57% win  PF 2.96  +Rs 6,037

This book gives exactly those two their OWN Rs 2,00,000 and nothing else, so what they do
next is measured on a book nobody else is drawing from.

IT EVALUATES ITS OWN SIGNALS, IT DOES NOT MIRROR THE DESK
The obvious build — copy every fill the Pre-Live desk makes on these two — would tie this
book to that desk's switches and admission gate. Switch the desk off, or let a strategy
drop out of admission on its next re-score, and this book would go silently quiet while
still claiming to be trading them. These two were picked by name; they trade here until
they are unpicked here. So the book runs the same `evaluate()` on the same shared bar store
and takes its own entries.

EVERYTHING ELSE IS THE DESK'S, IMPORTED NOT RESTATED
Whole MCX lots on SPAN-lite margin, one lot per trade, fills at the LIVE QUOTE with the
desk's slippage, real MCX brokerage/CTT/exchange/SEBI/stamp/GST on both legs, the same
max-hold rule, the same 3% daily loss breaker. The contract mathematics (`multiplier`,
`margin_pct`, `order_charges`) is imported from where it already lives, because a
multiplier restated by hand is how a lot gets understated by a factor of thousands.

SAME CADENCE AS THE RECORD
It runs on the Pre-Live desk's 180s tick. That means the 1-minute strategy is evaluated
roughly every third bar — and that is the cadence under which its +Rs13,808 was earned.
Running it faster would trade it differently from the record that justified picking it.

KEYED BY TEMPLATE + TIMEFRAME, NOT BY STRATEGY ID
`cmd_0038` and `cmd_0054` are positions in the catalog, not names. Re-order the catalog
and the same ids point at different strategies — this book would keep "trading
cmd_0038" while actually running something else. The roster is resolved from
(template, timeframe) against the catalog every cycle instead.

STILL PAPER. No order reaches a broker from this module.
"""

import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import (
    natgas_book_equity_collection,
    natgas_book_positions_collection,
    natgas_book_state_collection,
    natgas_book_trades_collection,
)
from app.services.broker_data import get_ltp
from app.services.commodity_bars import TIMEFRAMES, is_market_open, load_bars
from app.services.commodity_engine import _trade_stats, _verdict, order_charges
from app.services.commodity_patterns import COMMODITY_CATALOG, FAMILY_LABELS, evaluate
from app.services.commodity_positions import multiplier
from app.services.commodity_prelive import (
    DAILY_LOSS_BREAKER_PCT,
    MAX_HOLD_BARS,
    SLIPPAGE_BPS,
    _session_start_utc,
    _today_ist,
    margin_pct,
    prelive_universe,
)

logger = logging.getLogger("natgas_book")

BOOK_ID = "natgas"
LABEL = "Natural Gas Paper Trading"
SYMBOL = "NATGASMINI"
CAPITAL = float(os.getenv("NATGAS_BOOK_CAPITAL", "200000"))      # Rs 2 lakh
LOTS_PER_TRADE = 1

# (template, timeframe) — see the module docstring on why not strategy ids.
ROSTER: list[tuple[str, str]] = [
    ("ema_pullback", "1m"),
    ("hammer_star", "5m"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def roster_specs() -> list:
    """The two picked strategies, resolved from the catalog as it stands right now."""
    wanted = set(ROSTER)
    return [s for s in COMMODITY_CATALOG if (s.template, s.timeframe) in wanted]


# ── switch ───────────────────────────────────────────────────────────────────────


async def get_state() -> dict:
    doc = await natgas_book_state_collection.find_one({"_id": BOOK_ID}) or {}
    return {
        # Ships ON: this book exists because it was asked for by name, to trade.
        "enabled": doc.get("enabled", True),
        "last_run_at": doc.get("last_run_at"),
        "last_opened": doc.get("last_opened", 0),
        "last_managed": doc.get("last_managed", 0),
        "last_notes": doc.get("last_notes", []),
    }


async def set_enabled(enabled: bool) -> dict:
    await natgas_book_state_collection.update_one(
        {"_id": BOOK_ID}, {"$set": {"enabled": bool(enabled), "updated_at": _now()}},
        upsert=True)
    return await get_state()


# ── the book ─────────────────────────────────────────────────────────────────────


async def book() -> dict:
    deployed = unreal = 0.0
    opens = 0
    async for p in natgas_book_positions_collection.find(
            {"status": "OPEN"}, {"margin_used": 1, "unrealized_pnl": 1}):
        deployed += p.get("margin_used") or 0.0
        unreal += p.get("unrealized_pnl") or 0.0
        opens += 1
    realized = costs = 0.0
    closed = wins = 0
    async for p in natgas_book_positions_collection.find(
            {"status": {"$ne": "OPEN"}}, {"realized_pnl": 1, "costs": 1}):
        net = p.get("realized_pnl") or 0.0
        realized += net
        costs += p.get("costs") or 0.0
        closed += 1
        wins += 1 if net > 0 else 0
    total = realized + unreal
    return {
        "capital": CAPITAL,
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unreal, 2),
        "total_pnl": round(total, 2),
        "realized_pct": round(realized / CAPITAL * 100, 2),
        "unrealized_pct": round(unreal / CAPITAL * 100, 2),
        "total_pct": round(total / CAPITAL * 100, 2),
        "margin_deployed": round(deployed, 2),
        "available_margin": round(CAPITAL + realized - deployed, 2),
        "equity": round(CAPITAL + total, 2),
        "total_costs": round(costs, 2),
        "open_positions": opens, "closed_positions": closed,
        "win_rate": round(wins / closed * 100, 1) if closed else 0.0,
    }


async def today_pnl() -> float:
    start = _session_start_utc()
    total = 0.0
    async for p in natgas_book_positions_collection.find(
            {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    async for p in natgas_book_positions_collection.find(
            {"status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}):
        total += p.get("unrealized_pnl") or 0.0
    return total


# ── position lifecycle (the desk's rules, this book's collections) ───────────────


async def _open(spec, inst: dict, sig, bar_ts, free: float, market: float) -> tuple[bool, str | None, float]:
    if await natgas_book_positions_collection.find_one(
            {"strategy_template": spec.template, "timeframe": spec.timeframe, "status": "OPEN"}):
        return False, None, 0.0
    if not market or market <= 0 or not sig.entry:
        return False, None, 0.0

    slip = SLIPPAGE_BPS / 10000.0
    ratio = market / float(sig.entry)
    tgt, stp = float(sig.target) * ratio, float(sig.stoploss) * ratio
    fill = market * (1 + slip) if sig.side == "BUY" else market * (1 - slip)
    mult = multiplier(SYMBOL)
    lot_notional = fill * mult
    lot_margin = margin_pct(SYMBOL) * lot_notional
    if lot_margin <= 0:
        return False, None, 0.0
    lots = min(LOTS_PER_TRADE, int(free // lot_margin), int(CAPITAL // lot_notional))
    if lots < 1:
        return False, (f"{spec.name} · {spec.timeframe}: one {SYMBOL} lot needs "
                       f"~Rs{lot_margin:,.0f} of margin against Rs{free:,.0f} free — skipped, "
                       "no fraction of a lot invented."), 0.0

    qty = lots * mult
    margin_used = lots * lot_margin
    entry_costs = order_charges(fill, qty, sig.side == "BUY")
    await natgas_book_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "book": BOOK_ID,
        "strategy_id": spec.strategy_id, "strategy_template": spec.template,
        "strategy_name": spec.name, "family": spec.family,
        "family_label": FAMILY_LABELS.get(spec.family, spec.family),
        "timeframe": spec.timeframe, "pattern": sig.pattern,
        "symbol": SYMBOL, "display_name": inst.get("symbol"),
        "instrument": {"symbol": inst.get("symbol"), "security_id": str(inst.get("security_id")),
                       "exchange_segment": inst.get("exchange_segment"),
                       "expiry": inst.get("expiry")},
        "side": sig.side, "signal_price": round(sig.entry, 4), "entry_price": round(fill, 4),
        "lots": lots, "multiplier": mult, "qty": qty,
        "notional": round(fill * qty, 2), "margin_used": round(margin_used, 2),
        # desk_history reads capital_deployed / fees; set both names so History works.
        "capital_deployed": round(margin_used, 2),
        "entry_costs": round(entry_costs, 2),
        "target": round(tgt, 4), "stoploss": round(stp, 4),
        "ltp": round(fill, 4), "unrealized_pnl": 0.0, "return_on_margin_pct": 0.0,
        "realized_pnl": None, "costs": None, "fees": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "rationale": sig.rationale, "entry_bar_ts": bar_ts, "bars_held": 0,
        "max_hold_bars": MAX_HOLD_BARS,
        "opened_at": _now(), "opened_on": _today_ist().isoformat(),
        "updated_at": _now(), "closed_at": None,
    })
    return True, None, margin_used


async def _close(pos: dict, ltp: float, reason: str) -> float:
    slip = SLIPPAGE_BPS / 10000.0
    is_long = pos["side"] == "BUY"
    fill = ltp * (1 - slip) if is_long else ltp * (1 + slip)
    qty = pos["qty"]
    gross = (fill - pos["entry_price"]) * qty * (1 if is_long else -1)
    costs = (pos.get("entry_costs") or 0.0) + order_charges(fill, qty, not is_long)
    net = gross - costs
    margin = pos.get("margin_used") or 0.0
    closed_at = _now()
    await natgas_book_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "book": BOOK_ID,
        "strategy_template": pos.get("strategy_template"), "strategy_name": pos["strategy_name"],
        "timeframe": pos.get("timeframe"), "pattern": pos.get("pattern"),
        "symbol": pos["symbol"], "side": pos["side"],
        "entry_price": pos["entry_price"], "exit_price": round(fill, 4),
        "lots": pos.get("lots"), "qty": qty, "margin_used": round(margin, 2),
        "gross_pnl": round(gross, 2), "costs": round(costs, 2), "realized_pnl": round(net, 2),
        "return_on_margin_pct": round(net / margin * 100, 2) if margin else 0.0,
        "exit_reason": reason, "opened_at": pos["opened_at"], "closed_at": closed_at,
    })
    await natgas_book_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "status": "CLOSED", "exit_price": round(fill, 4), "exit_reason": reason,
        "gross_pnl": round(gross, 2), "costs": round(costs, 2), "fees": round(costs, 2),
        "realized_pnl": round(net, 2),
        "return_on_margin_pct": round(net / margin * 100, 2) if margin else 0.0,
        "unrealized_pnl": 0.0, "closed_at": closed_at,
        "closed_on": _today_ist().isoformat(), "updated_at": closed_at, "ltp": round(ltp, 4),
    }})
    return net


# ── cycles ───────────────────────────────────────────────────────────────────────


async def manage_cycle() -> int:
    """Always runs, switch on or off — an open position still has a stop."""
    open_pos = [p async for p in natgas_book_positions_collection.find({"status": "OPEN"})]
    if not open_pos:
        return 0
    universe = await prelive_universe()
    inst = universe.get(SYMBOL) or open_pos[0].get("instrument") or {}
    if not inst.get("security_id"):
        return 0
    price, src = await get_ltp(None, str(inst.get("security_id")), inst.get("exchange_segment"))
    if not price:
        return 0
    ltp = float(price)
    updated = 0
    for pos in open_pos:
        is_long = pos["side"] == "BUY"
        qty = pos["qty"]
        gross = (ltp - pos["entry_price"]) * qty * (1 if is_long else -1)
        unrealized = gross - ((pos.get("entry_costs") or 0.0) + order_charges(ltp, qty, not is_long))
        tf_minutes = TIMEFRAMES.get(pos.get("timeframe", "1d"), (None, 1440))[1]
        entry_ts = pos.get("entry_bar_ts")
        if entry_ts is not None and entry_ts.tzinfo is None:
            entry_ts = entry_ts.replace(tzinfo=timezone.utc)
        bars_held = (int((_now() - entry_ts).total_seconds() // 60 // max(tf_minutes, 1))
                     if entry_ts else 0)
        margin = pos.get("margin_used") or 0.0
        changes = {"ltp": round(ltp, 4), "ltp_source": src,
                   "unrealized_pnl": round(unrealized, 2),
                   "return_on_margin_pct": round(unrealized / margin * 100, 2) if margin else 0.0,
                   "bars_held": bars_held, "updated_at": _now()}
        hit_t = ltp >= pos["target"] if is_long else ltp <= pos["target"]
        hit_s = ltp <= pos["stoploss"] if is_long else ltp >= pos["stoploss"]
        expired = bars_held >= pos.get("max_hold_bars", MAX_HOLD_BARS)
        reason = "target" if hit_t else "stoploss" if hit_s else "max_hold_expired" if expired else None
        await natgas_book_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
        if reason:
            await _close({**pos, **changes}, ltp, reason)
        updated += 1
    return updated


async def scan_cycle() -> dict:
    state = await get_state()
    if not state["enabled"]:
        return {"opened": 0, "notes": ["Book switched OFF — no new entries; open positions "
                                       "are still managed to their target or stop."]}
    limit = DAILY_LOSS_BREAKER_PCT * CAPITAL
    pnl = await today_pnl()
    if pnl <= -limit:
        return {"opened": 0, "notes": [f"Daily loss breaker tripped: today Rs{pnl:,.0f} crossed "
                                       f"-Rs{limit:,.0f}. No new entries today."]}

    universe = await prelive_universe()
    inst = universe.get(SYMBOL)
    if not inst:
        return {"opened": 0, "notes": [f"No unexpired {SYMBOL} front month with an Angel token."]}
    specs = roster_specs()
    if len(specs) < len(ROSTER):
        found = {(s.template, s.timeframe) for s in specs}
        missing = [f"{t}·{tf}" for t, tf in ROSTER if (t, tf) not in found]
        logger.warning("natgas book: roster entries not in catalog: %s", missing)

    b = await book()
    free = b["available_margin"]
    px, _src = await get_ltp(None, str(inst.get("security_id")), inst.get("exchange_segment"))
    market = float(px) if px else 0.0

    guard_doc = await natgas_book_state_collection.find_one({"_id": "entry_bars"}) or {}
    last_bar = guard_doc.get("last", {})
    fresh: dict[str, str] = {}
    opened, notes = 0, []
    for spec in specs:
        bars = await load_bars(SYMBOL, spec.timeframe, limit=max(spec.min_bars + 5, 250))
        if len(bars) < spec.min_bars + 5:
            notes.append(f"{spec.name} · {spec.timeframe}: only {len(bars)} bars in the store.")
            continue
        bar_ts = bars[-1].ts
        key = f"{spec.template}:{spec.timeframe}"
        if last_bar.get(key) == str(bar_ts):          # one decision per bar per strategy
            continue
        sig = evaluate(spec, bars)
        if sig is None:
            continue
        fresh[key] = str(bar_ts)
        ok, why, used = await _open(spec, inst, sig, bar_ts, free, market)
        if ok:
            opened += 1
            free -= used
        elif why:
            notes.append(why)
    if fresh:
        await natgas_book_state_collection.update_one(
            {"_id": "entry_bars"}, {"$set": {f"last.{k}": v for k, v in fresh.items()}},
            upsert=True)
    return {"opened": opened, "notes": notes}


async def run_cycle() -> dict:
    managed = await manage_cycle()
    scan = await scan_cycle()
    b = await book()
    await natgas_book_equity_collection.insert_one({
        "ts": _now(), "equity": b["equity"], "realized": b["realized_pnl"],
        "unrealized": b["unrealized_pnl"], "margin_deployed": b["margin_deployed"],
        "open_positions": b["open_positions"]})
    await natgas_book_state_collection.update_one({"_id": BOOK_ID}, {"$set": {
        "last_run_at": _now(), "last_opened": scan["opened"], "last_managed": managed,
        "last_notes": scan["notes"], "market_open": is_market_open()}}, upsert=True)
    return {"opened": scan["opened"], "managed": managed, "notes": scan["notes"]}


async def close_all(reason: str = "manual_close_all") -> dict:
    open_pos = [p async for p in natgas_book_positions_collection.find({"status": "OPEN"})]
    if not open_pos:
        return {"closed": 0, "net_pnl": 0.0}
    universe = await prelive_universe()
    inst = universe.get(SYMBOL) or open_pos[0].get("instrument") or {}
    price = None
    if inst.get("security_id"):
        price, _ = await get_ltp(None, str(inst["security_id"]), inst.get("exchange_segment"))
    net = 0.0
    closed = 0
    for pos in open_pos:
        ltp = float(price) if price else float(pos.get("ltp") or 0.0)
        if ltp <= 0:
            continue
        net += await _close(pos, ltp, reason)
        closed += 1
    return {"closed": closed, "net_pnl": round(net, 2)}


# ── read models ──────────────────────────────────────────────────────────────────


async def summary() -> dict:
    state = await get_state()
    b = await book()
    limit = DAILY_LOSS_BREAKER_PCT * CAPITAL
    tp = await today_pnl()
    return {
        "book": BOOK_ID, "label": LABEL, "symbol": SYMBOL, **state, **b,
        "today_pnl": round(tp, 2), "today_pct": round(tp / CAPITAL * 100, 2),
        "daily_loss_limit": round(limit, 2), "breaker_tripped": tp <= -limit,
        "market_open": is_market_open(), "mode": "paper",
        "lots_per_trade": LOTS_PER_TRADE, "slippage_bps": SLIPPAGE_BPS,
        "roster": [{"template": t, "timeframe": tf} for t, tf in ROSTER],
    }


async def strategies() -> list[dict]:
    """One row per picked strategy: its record IN THIS BOOK, not on the Pre-Live desk."""
    out = []
    for spec in roster_specs():
        closed = [p async for p in natgas_book_positions_collection.find(
            {"strategy_template": spec.template, "timeframe": spec.timeframe,
             "status": {"$ne": "OPEN"}},
            {"realized_pnl": 1, "costs": 1, "closed_at": 1}).sort("closed_at", 1)]
        stats = _trade_stats(closed, base=CAPITAL)
        verdict, reasons = _verdict(stats)
        unreal = 0.0
        opens = 0
        async for p in natgas_book_positions_collection.find(
                {"strategy_template": spec.template, "timeframe": spec.timeframe,
                 "status": "OPEN"}, {"unrealized_pnl": 1}):
            unreal += p.get("unrealized_pnl") or 0.0
            opens += 1
        out.append({
            "template": spec.template, "name": spec.name, "timeframe": spec.timeframe,
            "family": spec.family, "family_label": FAMILY_LABELS.get(spec.family, spec.family),
            # _trade_stats reports win_rate as a fraction; this book reports percent
            # everywhere so the page never has to know which it was handed.
            "trades": stats.get("trades", 0),
            "win_rate": round((stats.get("win_rate") or 0.0) * 100, 1),
            "profit_factor": stats.get("profit_factor"), "expectancy": stats.get("expectancy", 0.0),
            "max_drawdown_pct": stats.get("max_drawdown_pct", 0.0), "t_stat": stats.get("t_stat"),
            "total_costs": stats.get("total_costs", 0.0),
            "realized_pnl": stats.get("net_pnl", 0.0), "unrealized_pnl": round(unreal, 2),
            "open_positions": opens, "verdict": verdict, "verdict_reasons": reasons,
        })
    return out


async def positions(status: str = "OPEN", limit: int = 200) -> list[dict]:
    q = {"status": "OPEN"} if status == "OPEN" else {"status": {"$ne": "OPEN"}}
    sort_key = "opened_at" if status == "OPEN" else "closed_at"
    rows = []
    async for p in natgas_book_positions_collection.find(q).sort(sort_key, -1).limit(limit):
        p.pop("_id", None)
        for k in ("opened_at", "closed_at", "updated_at", "entry_bar_ts"):
            if isinstance(p.get(k), datetime):
                p[k] = p[k].isoformat()
        rows.append(p)
    return rows
