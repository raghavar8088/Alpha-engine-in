"""All Time High Trading — buy every ₹1,00,000 of a stock the day it prints a new all-time
high, then hold it to +20% or -20% and nothing else.

THE RULE, exactly as specified:
  universe   Indian equities with a market capitalisation above ₹1,000 crore
  signal     the stock trades at or through its ALL-TIME high
  entry      ₹1,00,000 of it, whole shares, at the live price
  exit       +20% target or -20% stop. Nothing else closes a position — no time limit, no
             end-of-day square-off, no trailing stop.

WHAT "NOTHING ELSE" COSTS, because it is the most consequential part of the brief. A
position that goes nowhere is held forever; one that halves is held all the way down to the
stop and one that doubles was sold at +20% long before. That is a deliberate choice and the
desk implements it faithfully, but it means the equity curve here answers "does buying
all-time highs work" and not "is this a good way to run money". Both stop and target are
20%, so the strategy needs better than a 50% hit rate merely to cover its costs.

────────────────────────────────────────────────────────────────────────────────────────
NSE ONLY, AND WHY THAT IS NOT THE LIMITATION IT SOUNDS LIKE
────────────────────────────────────────────────────────────────────────────────────────
The brief says NSE and BSE. This app's instrument master holds 2,069 NSE equities and ZERO
BSE ones — Angel's BSE feed has never been loaded here, so a BSE-listed price cannot be
fetched, an order cannot be priced, and a BSE-only stock cannot honestly be traded.

That matters less than it reads. Essentially every Indian company above ₹1,000 crore is
listed on BOTH exchanges; BSE-exclusive names are overwhelmingly small, illiquid scrips
that the market-cap floor in this very brief would reject anyway. So the tradable universe
is the same universe either way, and the module says NSE rather than pretending to a
coverage it does not have. Loading Angel's BSE segment would be the fix if a genuinely
BSE-only name ever mattered.

────────────────────────────────────────────────────────────────────────────────────────
AN ALL-TIME HIGH IS NOT A 52-WEEK HIGH, AND THE DIFFERENCE IS THE WHOLE MODULE
────────────────────────────────────────────────────────────────────────────────────────
`stock_highs` walks each symbol's history back to its listing date and stores the real peak.
This desk uses that and nothing else — a windowed high would fire on stocks that are 40%
below their actual record, which is a completely different strategy wearing the same name.

Two guards follow from that:

  * NO STORED HIGH MEANS NOT ELIGIBLE. A missing high is never treated as "the current
    price is the high". That single substitution would make every unseeded stock a
    permanent buy signal.
  * A MINIMUM HISTORY IS REQUIRED. A stock listed six weeks ago is at its all-time high
    almost by definition, and there is no information in that. `MIN_SESSIONS` keeps recent
    listings out until they have a record worth breaking.

PAPER, on live Angel One prices, with the real Angel DELIVERY cost schedule charged on
exit — these positions sleep overnight, so intraday rates would understate every trade.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    ath_equity_collection,
    ath_positions_collection,
    ath_signals_collection,
    ath_state_collection,
    ath_trades_collection,
    instruments_collection,
    stock_fundamentals_collection,
    stock_highs_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from app.services.angel_fees import round_trip
from tradingai_broker_clients.angel.auth import batches

logger = logging.getLogger("ath_trading")

IST = timezone(timedelta(hours=5, minutes=30))
STATE_ID = "ath_trading"

# ── the rule ────────────────────────────────────────────────────────────────────
PER_POSITION = float(os.getenv("ATH_PER_POSITION", "100000"))        # ₹1 lakh
STOP_PCT = float(os.getenv("ATH_STOP_PCT", "20"))                    # -20%
TARGET_PCT = float(os.getenv("ATH_TARGET_PCT", "20"))                # +20%
MIN_MARKET_CAP = float(os.getenv("ATH_MIN_MARKET_CAP", "10000000000"))   # ₹1,000 crore

# A stock needs a record worth breaking. Roughly one trading year.
MIN_SESSIONS = int(os.getenv("ATH_MIN_SESSIONS", "250"))
# How close to the stored high counts as "at" it. 0 means it must actually trade through.
TOUCH_TOLERANCE_PCT = float(os.getenv("ATH_TOUCH_TOLERANCE_PCT", "0"))
# Desk size. The rule names a position size but not a book; this bounds the experiment.
DESK_CAPITAL = float(os.getenv("ATH_DESK_CAPITAL", "50000000"))      # ₹5 crore
# Days to wait before the same symbol can be bought again after an exit. 0 allows an
# immediate re-entry, which is what the rule literally implies: a stock that just hit +20%
# is, by construction, at a new all-time high.
REENTRY_COOLDOWN_DAYS = int(os.getenv("ATH_REENTRY_COOLDOWN_DAYS", "0"))

ENABLED = os.getenv("ATH_ENABLED", "1").lower() not in ("0", "false", "")
QUOTE_PACE = 0.15
MARKET_OPEN, MARKET_CLOSE = "09:15", "15:30"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def market_is_open(when: datetime | None = None) -> bool:
    now = when or datetime.now(IST)
    return now.weekday() < 5 and MARKET_OPEN <= now.strftime("%H:%M") <= MARKET_CLOSE


# ── universe ────────────────────────────────────────────────────────────────────


async def universe() -> list[dict]:
    """Every Angel-quotable NSE equity above the market-cap floor that has a real
    all-time high on file and enough history for it to mean something.

    Each exclusion is counted rather than silently dropped — the coverage report is what
    tells you whether "no signals today" means the market was quiet or the data is thin.
    """
    caps = {
        d["symbol"]: d["market_cap"]
        async for d in stock_fundamentals_collection.find(
            {"market_cap": {"$gte": MIN_MARKET_CAP}}, {"_id": 0, "symbol": 1, "market_cap": 1})
    }
    if not caps:
        return []

    highs = {
        d["symbol"]: d
        async for d in stock_highs_collection.find(
            {"symbol": {"$in": list(caps)}},
            {"_id": 0, "symbol": 1, "all_time_high": 1, "all_time_high_date": 1, "sessions": 1})
    }

    out = []
    async for i in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": list(caps)}, "angel_token": {"$ne": None}},
        {"_id": 0, "symbol": 1, "name": 1, "angel_token": 1, "angel_exchange": 1},
    ):
        sym = i["symbol"]
        h = highs.get(sym)
        if not h or not h.get("all_time_high"):
            continue
        if int(h.get("sessions") or 0) < MIN_SESSIONS:
            continue
        out.append({
            "symbol": sym,
            "name": i.get("name") or sym,
            "token": str(i["angel_token"]),
            "exchange": i.get("angel_exchange") or "NSE",
            "market_cap": caps[sym],
            "market_cap_cr": round(caps[sym] / 1e7, 0),
            "all_time_high": float(h["all_time_high"]),
            "ath_date": h.get("all_time_high_date"),
            "sessions": int(h.get("sessions") or 0),
        })
    return out


async def coverage() -> dict:
    """How much of the intended universe the desk can actually see.

    Surfaced because the honest answer to "why so few signals" is usually this, not the
    market: all-time highs are seeded per symbol by a slow historical walk, and until that
    walk reaches a stock the desk is blind to it.
    """
    above_cap = await stock_fundamentals_collection.count_documents(
        {"market_cap": {"$gte": MIN_MARKET_CAP}})
    caps = [d["symbol"] async for d in stock_fundamentals_collection.find(
        {"market_cap": {"$gte": MIN_MARKET_CAP}}, {"_id": 0, "symbol": 1})]
    quotable = await instruments_collection.count_documents(
        {"asset_class": "EQUITY", "symbol": {"$in": caps}, "angel_token": {"$ne": None}})
    with_high = await stock_highs_collection.count_documents({"symbol": {"$in": caps}})
    tradable = len(await universe())
    return {
        "market_cap_floor_cr": round(MIN_MARKET_CAP / 1e7),
        "above_market_cap": above_cap,
        "angel_quotable": quotable,
        "with_all_time_high": with_high,
        "tradable": tradable,
        "missing_highs": max(0, quotable - with_high),
        "min_sessions": MIN_SESSIONS,
        "note": (
            f"{tradable} stocks are tradable right now. A name is excluded when it has no "
            f"stored all-time high yet ({max(0, quotable - with_high)} such) or has fewer "
            f"than {MIN_SESSIONS} sessions of history — a stock listed weeks ago is at its "
            f"all-time high by definition and that is not a signal. Highs are seeded by a "
            f"paced historical walk, so coverage grows over the first few days."),
        "exchange_note": (
            "NSE only. This app's instrument master holds no BSE equities, so a BSE price "
            "cannot be fetched. Virtually every company above ₹1,000 crore is listed on "
            "both exchanges, so the tradable set is unchanged in practice."),
    }


# ── quotes ──────────────────────────────────────────────────────────────────────


async def _quotes(rows: list[dict]) -> dict[str, float]:
    """Batched Angel LTPs keyed by token. Never raises; a missing quote means the symbol is
    simply not evaluated this cycle, which is safer than acting on a stale price."""
    if not rows or not angel_client.configured():
        return {}
    by_ex: dict[str, list[str]] = {}
    for r in rows:
        by_ex.setdefault(r.get("exchange") or "NSE", []).append(str(r["token"]))

    for attempt in range(2):
        try:
            await angel_client._session()
            break
        except AngelAPIError:
            if attempt == 0:
                await asyncio.sleep(0.7)

    out: dict[str, float] = {}
    for grouped in batches(by_ex):
        try:
            out.update({str(k): float(v) for k, v in (await angel_client.ltp(grouped)).items()})
        except AngelAPIError:
            pass
        await asyncio.sleep(QUOTE_PACE)
    return out


# ── capital ─────────────────────────────────────────────────────────────────────


async def _deployed() -> float:
    total = 0.0
    async for p in ath_positions_collection.find({"status": "OPEN"}, {"cost": 1}):
        total += float(p.get("cost") or 0)
    return total


async def _realised() -> tuple[float, float]:
    net = fees = 0.0
    async for t in ath_trades_collection.find({}, {"net_pnl": 1, "fees": 1}):
        net += float(t.get("net_pnl") or 0)
        fees += float(t.get("fees") or 0)
    return net, fees


async def available_capital() -> float:
    net, _ = await _realised()
    return DESK_CAPITAL + net - await _deployed()


# ── the cycle ───────────────────────────────────────────────────────────────────


async def run_cycle() -> dict:
    """Manage open positions first, then look for new all-time highs.

    Managing first matters: an exit frees capital that a new signal in the same cycle can
    use, and doing it the other way round would reject entries the desk could afford.
    """
    rows = await universe()
    if not rows:
        return {"scanned": 0, "opened": 0, "closed": 0, "reason": "universe empty"}

    open_positions = [p async for p in ath_positions_collection.find({"status": "OPEN"})]
    # One quote sweep covers both jobs.
    watch = {r["token"]: r for r in rows}
    for p in open_positions:
        watch.setdefault(str(p["token"]), {"token": str(p["token"]),
                                           "exchange": p.get("exchange", "NSE")})
    prices = await _quotes(list(watch.values()))

    closed = await _manage(open_positions, prices)
    opened, skipped = await _scan(rows, prices)

    await _write_equity(prices)
    await ath_state_collection.replace_one(
        {"_id": STATE_ID},
        {"_id": STATE_ID, "last_cycle": _now(), "last_cycle_on": _today(),
         "scanned": len(rows), "opened": opened, "closed": closed,
         "skipped_no_capital": skipped, "ts": _now()},
        upsert=True)
    return {"scanned": len(rows), "opened": opened, "closed": closed,
            "skipped_no_capital": skipped, "priced": len(prices)}


async def _manage(open_positions: list[dict], prices: dict[str, float]) -> int:
    """Close positions that have reached their stop or their target. Nothing else exits."""
    closed = 0
    for pos in open_positions:
        ltp = prices.get(str(pos["token"]))
        if ltp is None:
            continue
        reason = None
        if ltp >= float(pos["target"]):
            reason = "TARGET"
        elif ltp <= float(pos["stop"]):
            reason = "STOP"
        if not reason:
            # Mark to market and move on. There is deliberately no third exit branch.
            await ath_positions_collection.update_one(
                {"_id": pos["_id"]},
                {"$set": {"ltp": round(ltp, 2),
                          "unrealised_pnl": round((ltp - float(pos["entry"])) * int(pos["quantity"]), 2),
                          "updated_at": _now()}})
            continue
        await _close(pos, ltp, reason)
        closed += 1
    return closed


async def _close(pos: dict, ltp: float, reason: str) -> dict:
    qty, entry = int(pos["quantity"]), float(pos["entry"])
    gross = (ltp - entry) * qty
    # DELIVERY, not intraday: these positions sleep overnight, often for months.
    fees = round_trip(entry, ltp, qty, "BUY", "DELIVERY")
    net = gross - fees.total
    held = (datetime.now(IST).date() - datetime.fromisoformat(pos["opened_on"]).date()).days

    trade = {
        **{k: v for k, v in pos.items() if k != "_id"},
        "exit": round(ltp, 2),
        "exit_reason": reason,
        "closed_at": _now(),
        "closed_on": _today(),
        "days_held": held,
        "gross_pnl": round(gross, 2),
        "fees": fees.total,
        "fee_breakdown": fees.as_dict(),
        "net_pnl": round(net, 2),
        "return_pct": round((ltp / entry - 1) * 100, 2),
        "status": "CLOSED",
        "ts": _now(),
    }
    await ath_trades_collection.insert_one(trade)
    await ath_positions_collection.delete_one({"_id": pos["_id"]})
    logger.info("ath: closed %s at %s (%s) after %sd — net %.2f",
                pos["symbol"], ltp, reason, held, net)
    return trade


async def _scan(rows: list[dict], prices: dict[str, float]) -> tuple[int, int]:
    """Buy anything printing a new all-time high."""
    held = {p["symbol"] async for p in ath_positions_collection.find(
        {"status": "OPEN"}, {"symbol": 1})}
    cash = await available_capital()
    opened = skipped = 0

    for r in rows:
        sym = r["symbol"]
        if sym in held:
            continue
        ltp = prices.get(r["token"])
        if ltp is None or ltp <= 0:
            continue

        ath = float(r["all_time_high"])
        threshold = ath * (1 - TOUCH_TOLERANCE_PCT / 100)
        if ltp < threshold:
            continue

        if REENTRY_COOLDOWN_DAYS:
            recent = await ath_trades_collection.find_one(
                {"symbol": sym}, sort=[("closed_at", -1)])
            if recent and recent.get("closed_on"):
                gap = (datetime.now(IST).date()
                       - datetime.fromisoformat(recent["closed_on"]).date()).days
                if gap < REENTRY_COOLDOWN_DAYS:
                    continue

        qty = int(PER_POSITION // ltp)
        if qty < 1:
            # A single share costs more than the position size. Recorded rather than
            # dropped — silently skipping a signal makes the desk look like it never fired.
            await _record_signal(r, ltp, taken=False,
                                 why=f"One share costs {ltp:,.2f}, above the "
                                     f"{PER_POSITION:,.0f} position size")
            continue

        cost = qty * ltp
        if cost > cash:
            skipped += 1
            await _record_signal(r, ltp, taken=False,
                                 why=f"Desk has {cash:,.0f} free, needs {cost:,.0f}")
            continue

        await _open(r, ltp, qty, cost)
        # The stored high moves up with the price, so tomorrow's signal is measured against
        # today's peak rather than a record the stock has already beaten.
        await stock_highs_collection.update_one(
            {"symbol": sym},
            {"$set": {"all_time_high": round(ltp, 2), "all_time_high_date": _today()}})
        cash -= cost
        opened += 1
    return opened, skipped


async def _open(r: dict, ltp: float, qty: int, cost: float) -> dict:
    doc = {
        "position_id": f"ATH-{uuid4().hex[:12]}",
        "symbol": r["symbol"],
        "name": r.get("name"),
        "token": r["token"],
        "exchange": r.get("exchange", "NSE"),
        "entry": round(ltp, 2),
        "quantity": qty,
        "cost": round(cost, 2),
        "stop": round(ltp * (1 - STOP_PCT / 100), 2),
        "target": round(ltp * (1 + TARGET_PCT / 100), 2),
        "ltp": round(ltp, 2),
        "unrealised_pnl": 0.0,
        "market_cap": r.get("market_cap"),
        "market_cap_cr": r.get("market_cap_cr"),
        "ath_broken": r.get("all_time_high"),
        "previous_ath_date": r.get("ath_date"),
        "sessions": r.get("sessions"),
        "status": "OPEN",
        "opened_at": _now(),
        "opened_on": _today(),
        "updated_at": _now(),
        "ts": _now(),
    }
    await ath_positions_collection.insert_one(dict(doc))
    doc.pop("_id", None)
    await _record_signal(r, ltp, taken=True,
                         why=f"New all-time high — took out {r['all_time_high']:,.2f} "
                             f"set on {r.get('ath_date')}")
    logger.info("ath: bought %s x%s @ %.2f (prev ATH %.2f, mcap %s cr)",
                r["symbol"], qty, ltp, r["all_time_high"], r.get("market_cap_cr"))
    return doc


async def _record_signal(r: dict, ltp: float, taken: bool, why: str) -> None:
    await ath_signals_collection.insert_one({
        "signal_id": f"S-{uuid4().hex[:10]}",
        "symbol": r["symbol"],
        "ltp": round(ltp, 2),
        "all_time_high": r.get("all_time_high"),
        "previous_ath_date": r.get("ath_date"),
        "market_cap_cr": r.get("market_cap_cr"),
        "taken": taken,
        "why": why,
        "date": _today(),
        "ts": _now(),
    })


async def _write_equity(prices: dict[str, float]) -> None:
    s = await summary(prices)
    await ath_equity_collection.insert_one({
        "equity": s["equity"], "realised": s["realised_pnl"],
        "unrealised": s["unrealised_pnl"], "open_positions": s["open_positions"],
        "ts": _now(),
    })


# ── reporting ───────────────────────────────────────────────────────────────────


async def summary(prices: dict[str, float] | None = None) -> dict:
    positions = [p async for p in ath_positions_collection.find({"status": "OPEN"}, {"_id": 0})]
    unrealised = sum(float(p.get("unrealised_pnl") or 0) for p in positions)
    net, fees = await _realised()
    deployed = sum(float(p.get("cost") or 0) for p in positions)
    trades = await ath_trades_collection.count_documents({})
    wins = await ath_trades_collection.count_documents({"net_pnl": {"$gt": 0}})
    hits = await ath_trades_collection.count_documents({"exit_reason": "TARGET"})
    stops = await ath_trades_collection.count_documents({"exit_reason": "STOP"})
    state = await ath_state_collection.find_one({"_id": STATE_ID}) or {}

    return {
        "mode": "paper",
        "enabled": ENABLED,
        "desk_capital": DESK_CAPITAL,
        "per_position": PER_POSITION,
        "stop_pct": STOP_PCT,
        "target_pct": TARGET_PCT,
        "market_cap_floor_cr": round(MIN_MARKET_CAP / 1e7),
        "deployed": round(deployed, 2),
        "available": round(DESK_CAPITAL + net - deployed, 2),
        "realised_pnl": round(net, 2),
        "fees_paid": round(fees, 2),
        "unrealised_pnl": round(unrealised, 2),
        "equity": round(DESK_CAPITAL + net + unrealised, 2),
        "roi_pct": round((net + unrealised) / DESK_CAPITAL * 100, 3) if DESK_CAPITAL else 0.0,
        "open_positions": len(positions),
        "max_positions": int(DESK_CAPITAL // PER_POSITION),
        "closed_trades": trades,
        "wins": wins,
        "win_rate": round(wins / trades * 100, 1) if trades else None,
        "target_hits": hits,
        "stop_hits": stops,
        "last_cycle": state.get("last_cycle").isoformat() if state.get("last_cycle") else None,
        "last_scanned": state.get("scanned"),
        "market_open": market_is_open(),
        "exit_note": (
            f"A position closes at +{TARGET_PCT:g}% or -{STOP_PCT:g}% and at nothing else — "
            f"no time limit, no square-off, no trailing stop. With the stop and target equal, "
            f"the strategy needs better than a 50% hit rate just to pay its costs."),
    }


async def positions(limit: int = 500) -> dict:
    rows = [p async for p in ath_positions_collection.find({"status": "OPEN"}, {"_id": 0})
            .sort("opened_at", -1).limit(limit)]
    if rows:
        prices = await _quotes([{"token": r["token"], "exchange": r.get("exchange", "NSE")}
                                for r in rows])
        for r in rows:
            ltp = prices.get(str(r["token"]))
            if ltp:
                r["ltp"] = round(ltp, 2)
                r["unrealised_pnl"] = round((ltp - float(r["entry"])) * int(r["quantity"]), 2)
                r["return_pct"] = round((ltp / float(r["entry"]) - 1) * 100, 2)
                r["to_target_pct"] = round((float(r["target"]) / ltp - 1) * 100, 2)
                r["to_stop_pct"] = round((float(r["stop"]) / ltp - 1) * 100, 2)
            r["days_held"] = (datetime.now(IST).date()
                              - datetime.fromisoformat(r["opened_on"]).date()).days
            for k in ("opened_at", "updated_at", "ts"):
                if hasattr(r.get(k), "isoformat"):
                    r[k] = r[k].isoformat()
    rows.sort(key=lambda r: -(r.get("unrealised_pnl") or 0))
    return {"count": len(rows), "rows": rows,
            "unrealised_pnl": round(sum(r.get("unrealised_pnl") or 0 for r in rows), 2)}


async def trades(limit: int = 300) -> dict:
    rows = [t async for t in ath_trades_collection.find({}, {"_id": 0})
            .sort("closed_at", -1).limit(limit)]
    for r in rows:
        for k in ("opened_at", "closed_at", "ts"):
            if hasattr(r.get(k), "isoformat"):
                r[k] = r[k].isoformat()
    return {
        "count": len(rows), "rows": rows,
        "net_pnl": round(sum(float(r.get("net_pnl") or 0) for r in rows), 2),
        "fees": round(sum(float(r.get("fees") or 0) for r in rows), 2),
        "avg_days_held": round(sum(int(r.get("days_held") or 0) for r in rows) / len(rows), 1)
                          if rows else None,
    }


async def signals(limit: int = 200, taken: bool | None = None) -> dict:
    q: dict = {}
    if taken is not None:
        q["taken"] = taken
    rows = [s async for s in ath_signals_collection.find(q, {"_id": 0})
            .sort("ts", -1).limit(limit)]
    for r in rows:
        if hasattr(r.get("ts"), "isoformat"):
            r["ts"] = r["ts"].isoformat()
    return {"count": len(rows), "rows": rows}


async def near_highs(limit: int = 50) -> dict:
    """Stocks closest to their all-time high without having broken it — the watchlist.

    The desk only acts on a break, but knowing what is one percent away is the difference
    between a screen that looks dead and one you can see coming.
    """
    rows = await universe()
    if not rows:
        return {"count": 0, "rows": []}
    prices = await _quotes(rows)
    out = []
    for r in rows:
        ltp = prices.get(r["token"])
        if not ltp:
            continue
        gap = (ltp / float(r["all_time_high"]) - 1) * 100
        if gap >= 0:
            continue          # already through it — that is a signal, not a watch
        out.append({**{k: v for k, v in r.items() if k != "token"},
                    "ltp": round(ltp, 2), "pct_from_ath": round(gap, 2)})
    out.sort(key=lambda r: -r["pct_from_ath"])
    return {"count": len(out), "rows": out[:limit],
            "universe": len(rows), "priced": len(prices)}


async def equity_curve(limit: int = 500) -> dict:
    rows = [e async for e in ath_equity_collection.find({}, {"_id": 0})
            .sort("ts", -1).limit(limit)]
    rows.reverse()
    for r in rows:
        if hasattr(r.get("ts"), "isoformat"):
            r["ts"] = r["ts"].isoformat()
    return {"count": len(rows), "rows": rows}


async def seed_highs(limit: int = 120) -> dict:
    """Walk history for universe stocks that have no all-time high yet.

    Paced and capped: each symbol costs several calls to Angel's rate-limited historical
    endpoint, so the ~600 missing names are filled in over several runs rather than one.
    """
    from app.services.stock_highs import backfill_all_time_highs

    caps = [d["symbol"] async for d in stock_fundamentals_collection.find(
        {"market_cap": {"$gte": MIN_MARKET_CAP}}, {"_id": 0, "symbol": 1})]
    have = set(await stock_highs_collection.distinct("symbol"))
    quotable = [d["symbol"] async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": caps}, "angel_token": {"$ne": None}},
        {"_id": 0, "symbol": 1})]
    missing = [s for s in quotable if s not in have]
    if not missing:
        return {"seeded": 0, "remaining": 0, "complete": True}

    result = await backfill_all_time_highs(only_missing=True, symbols=missing, limit=limit)
    return {**result, "remaining": max(0, len(missing) - int(result.get("ok", 0))),
            "complete": False}


async def reset() -> dict:
    p = await ath_positions_collection.delete_many({})
    t = await ath_trades_collection.delete_many({})
    s = await ath_signals_collection.delete_many({})
    e = await ath_equity_collection.delete_many({})
    await ath_state_collection.delete_many({"_id": STATE_ID})
    return {"positions_cleared": p.deleted_count, "trades_cleared": t.deleted_count,
            "signals_cleared": s.deleted_count, "equity_points_cleared": e.deleted_count}
