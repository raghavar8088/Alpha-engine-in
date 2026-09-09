"""The ₹1 crore paper desk that takes every signal this module publishes.

One rule, deliberately rigid: **₹1,00,000 per signal**, one position per symbol, whole
shares only. Not 1% of a floating equity, not a volatility-scaled size — a fixed notional,
because the point of this desk is to measure whether the RESEARCH picks winners, and a
sizing rule that varies with conviction mixes two questions into one P&L curve.

Real NSE delivery costs are charged on both legs through the shared `equity_delivery`
schedule (brokerage, STT, exchange, SEBI, stamp, GST), and both fills take slippage. A
paper desk that fills at the mid and charges nothing produces a curve that cannot happen.

Exits are checked against DAILY BARS, in the order a real day would resolve them:

  * stop first. When a bar's low breaches the stop and its high reaches a target, the
    honest assumption is the loss, because from a daily bar alone there is no way to know
    which came first, and assuming the win is how a backtest flatters itself.
  * then T2, then T1 — T1 exits the whole position here rather than scaling, so the
    recorded result is unambiguous.
  * then time. At the horizon's working-day count the position closes at the market,
    win or lose, because the signal made a claim about a window and the desk has to
    honour it.

Nothing is marked to a price the position could not have got: exits use the bar's own
levels, and the time exit uses that day's close.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.db import swing_signal_positions_collection as POS
from app.core.db import swing_signal_trades_collection as TRADES
from app.services.screener.horizons import Bar
from app.services.strategy_factory.primitives import round_trip_cost, slippage_price

CAPITAL = 1_00_00_000.0        # ₹1 crore
PER_SIGNAL = 1_00_000.0        # ₹1 lakh per signal
SLIPPAGE_BPS = float(8)        # 8 bps each way on a liquid mid/large cap
COST_MODEL = "equity_delivery"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def open_count() -> int:
    return await POS.count_documents({"status": "OPEN"})


async def deployed() -> float:
    total = 0.0
    async for p in POS.find({"status": "OPEN"}, {"cost_basis": 1}):
        total += float(p.get("cost_basis") or 0.0)
    return round(total, 2)


async def realised() -> float:
    total = 0.0
    async for t in TRADES.find({}, {"net_pnl": 1}):
        total += float(t.get("net_pnl") or 0.0)
    return round(total, 2)


async def available() -> float:
    return round(CAPITAL + await realised() - await deployed(), 2)


async def take(sig: dict) -> dict | None:
    """Open a ₹1 lakh position on a signal. Returns None when the desk declines it.

    Declining is a real outcome and is recorded on the signal, not swallowed: a desk that
    silently skips signals reports a P&L for a strategy nobody could have traded."""
    symbol = sig["symbol"]
    if await POS.find_one({"symbol": symbol, "status": "OPEN"}):
        return None

    entry = slippage_price(float(sig["price"]), SLIPPAGE_BPS, adverse_for_buy=True)
    qty = int(PER_SIGNAL // entry)
    if qty < 1:
        return None
    cost_basis = round(entry * qty, 2)
    if cost_basis > await available():
        return None

    doc = {
        "symbol": symbol,
        "name": sig.get("name"),
        "sector": sig.get("sector"),
        "status": "OPEN",
        "opened_on": sig["generated_on"],
        "opened_at": _now(),
        "entry": round(entry, 2),
        "signal_price": float(sig["price"]),
        "qty": qty,
        "cost_basis": cost_basis,
        "stop": float(sig["stop"]),
        "target1": float(sig["target1"]),
        "target2": float(sig["target2"]),
        "horizon": sig["horizon"],
        "horizon_days": int(sig["horizon_days"]),
        "conviction": sig["conviction"],
        "score": float(sig["score"]),
        "reasons": sig.get("reasons") or [],
        "ltp": float(sig["price"]),
        "unrealised": 0.0,
        "bars_held": 0,
    }
    await POS.insert_one(doc)
    doc.pop("_id", None)
    return doc


def _resolve(pos: dict, bar: Bar) -> tuple[str, float] | None:
    """(reason, exit price) if this bar closes the position, else None."""
    if bar.low <= pos["stop"]:
        return "STOP", float(pos["stop"])
    if bar.high >= pos["target2"]:
        return "TARGET2", float(pos["target2"])
    if bar.high >= pos["target1"]:
        return "TARGET1", float(pos["target1"])
    return None


async def mark_and_exit(bars_by_sym: dict[str, list[Bar]], today: str) -> dict:
    """Walk every open position forward over the bars it has not yet seen.

    Replaying bars rather than reading a live quote is what makes the exits honest: a stop
    that was breached intraday three days ago has to count as a stop, not as whatever the
    price happens to be when someone opens the page."""
    closed = marked = 0
    async for pos in POS.find({"status": "OPEN"}):
        bars = bars_by_sym.get(pos["symbol"]) or []
        if not bars:
            continue
        after = [b for b in bars if b.ts.date().isoformat() > str(pos["opened_on"])]
        if not after:
            continue

        held, exit_hit = 0, None
        for bar in after:
            held += 1
            hit = _resolve(pos, bar)
            if hit:
                exit_hit = hit
                break
            if held >= int(pos["horizon_days"]):
                exit_hit = ("TIME", float(bar.close))
                break

        last = after[-1]
        if exit_hit is None:
            await POS.update_one(
                {"_id": pos["_id"]},
                {"$set": {"ltp": round(last.close, 2), "bars_held": held,
                          "unrealised": round((last.close - pos["entry"]) * pos["qty"], 2),
                          "updated_at": _now()}})
            marked += 1
            continue

        reason, raw = exit_hit
        exit_px = slippage_price(raw, SLIPPAGE_BPS, adverse_for_buy=False)
        gross = (exit_px - pos["entry"]) * pos["qty"]
        costs = round_trip_cost(COST_MODEL, pos["entry"], exit_px, pos["qty"], True)
        net = gross - costs
        await TRADES.insert_one({
            "symbol": pos["symbol"], "name": pos.get("name"), "sector": pos.get("sector"),
            "opened_on": pos["opened_on"], "closed_on": today,
            "entry": pos["entry"], "exit": round(exit_px, 2), "qty": pos["qty"],
            "reason": reason, "bars_held": held,
            "gross_pnl": round(gross, 2), "costs": round(costs, 2),
            "net_pnl": round(net, 2),
            "return_pct": round(net / pos["cost_basis"] * 100, 2),
            "horizon": pos["horizon"], "conviction": pos["conviction"],
            "score": pos["score"], "closed_at": _now(),
        })
        await POS.update_one({"_id": pos["_id"]},
                             {"$set": {"status": "CLOSED", "closed_on": today,
                                       "exit_reason": reason, "closed_at": _now()}})
        closed += 1
    return {"marked": marked, "closed": closed}


async def summary() -> dict:
    open_rows = [p async for p in POS.find({"status": "OPEN"}, {"_id": 0})]
    trades = [t async for t in TRADES.find({}, {"_id": 0})]
    real = round(sum(float(t.get("net_pnl") or 0.0) for t in trades), 2)
    unreal = round(sum(float(p.get("unrealised") or 0.0) for p in open_rows), 2)
    dep = round(sum(float(p.get("cost_basis") or 0.0) for p in open_rows), 2)
    wins = [t for t in trades if (t.get("net_pnl") or 0) > 0]
    gross_win = sum(t["net_pnl"] for t in wins)
    gross_loss = -sum(t["net_pnl"] for t in trades if (t.get("net_pnl") or 0) <= 0)
    by_reason: dict[str, int] = {}
    for t in trades:
        by_reason[t.get("reason", "?")] = by_reason.get(t.get("reason", "?"), 0) + 1
    return {
        "capital": CAPITAL,
        "per_signal": PER_SIGNAL,
        "deployed": dep,
        "available": round(CAPITAL + real - dep, 2),
        "equity": round(CAPITAL + real + unreal, 2),
        "realised": real,
        "unrealised": unreal,
        "open_count": len(open_rows),
        "closed_count": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "avg_win": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss": (round(-gross_loss / (len(trades) - len(wins)), 2)
                     if len(trades) > len(wins) else None),
        "exits": by_reason,
        "open_positions": sorted(open_rows, key=lambda p: p.get("opened_on") or "",
                                 reverse=True),
        "recent_trades": sorted(trades, key=lambda t: t.get("closed_on") or "",
                                reverse=True)[:60],
        "costs_note": ("Real NSE delivery costs on both legs plus 8 bps of slippage each "
                       "way. Win rate is reported but never used to rank a signal."),
    }
