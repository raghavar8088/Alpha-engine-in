"""Paper desk for the Screener's own signals — which of them actually make money.

THE QUESTION. The Screener produces five different kinds of signal: intraday momentum, swing
trends, breakouts, raw momentum rank, and completed chart patterns. Every one of them looks
plausible on the page. This desk is the only thing that can say which of them is worth acting
on, because it takes every signal at the price it was published, manages it to the stop and
target that were published with it, and charges real Angel One costs on the way out.

FIVE INDEPENDENT BOOKS, NOT ONE. Each family gets its own capital pool and its own
leaderboard. Pooling them would make the whole desk's P&L a weighted average that hides the
answer — a strong breakout book could carry a losing intraday book for months and nobody
would know which was which. Separate books make the comparison the point.

COSTS ARE CHARGED, per family, on the schedule that family actually trades:
intraday squares off the same session (INTRADAY rates); swing, breakout, momentum and
chart-pattern positions sleep overnight (DELIVERY rates — 0.1% STT on BOTH legs plus a DP
charge on exit, roughly four times the drag). Charging one rate for all five would flatter the
overnight books by exactly the amount that matters.

FILLS ARE THE SIGNAL'S OWN PRICE, and exits are checked against the live quote each cycle.
Intraday positions are squared off at 15:10 whatever they are showing; swing and breakout
positions have a maximum holding period so a dead trade cannot sit open forever quietly
flattering the win rate by never being counted as a loss.

NO ORDERS REACH A BROKER. This is paper, on live Angel prices.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import (
    instruments_collection,
    screener_paper_equity_collection,
    screener_paper_positions_collection,
    screener_paper_state_collection,
    screener_paper_trades_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from app.services.angel_fees import round_trip
from app.services.screener.horizons import IST
from tradingai_broker_clients.angel.auth import batches

logger = logging.getLogger("screener.paper")

FAMILIES = ["intraday", "swing", "breakout", "momentum", "chart_pattern"]
FAMILY_LABELS = {
    "intraday": "Intraday", "swing": "Swing", "breakout": "Breakout",
    "momentum": "Momentum", "chart_pattern": "Chart Pattern",
}
# Which fee schedule each family actually pays. Intraday is the only one that closes
# the same session.
FAMILY_PRODUCT = {
    "intraday": "INTRADAY", "swing": "DELIVERY", "breakout": "DELIVERY",
    "momentum": "DELIVERY", "chart_pattern": "DELIVERY",
}
# Maximum holding period in sessions. Without it a losing trade never closes and the win
# rate is computed only over the trades that happened to resolve.
FAMILY_MAX_DAYS = {"intraday": 0, "swing": 15, "breakout": 10, "momentum": 21, "chart_pattern": 15}

CAPITAL_PER_FAMILY = float(os.getenv("SCREENER_PAPER_CAPITAL", "200000"))
PER_TRADE = float(os.getenv("SCREENER_PAPER_PER_TRADE", "25000"))
MAX_OPEN_PER_FAMILY = int(os.getenv("SCREENER_PAPER_MAX_OPEN", "8"))
SQUAREOFF_HHMM = os.getenv("SCREENER_PAPER_SQUAREOFF", "15:10")
ENABLED = os.getenv("SCREENER_PAPER_ENABLED", "1").lower() not in ("0", "false", "")

STATE_ID = "screener_paper"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _qty(entry: float) -> int:
    return int(PER_TRADE // entry) if entry > 0 else 0


# ── quotes ──────────────────────────────────────────────────────────────────────


async def _quotes(symbols: list[str]) -> dict[str, float]:
    """Live LTP per symbol. Never raises — a quote failure means positions are simply not
    managed this cycle, which is strictly better than closing them at a guessed price."""
    if not symbols or not angel_client.configured():
        return {}
    inst = {
        d["symbol"]: d async for d in instruments_collection.find(
            {"asset_class": "EQUITY", "symbol": {"$in": symbols}, "angel_token": {"$ne": None}},
            {"symbol": 1, "angel_token": 1, "angel_exchange": 1})
    }
    by_ex: dict[str, list[str]] = {}
    tok_sym: dict[str, str] = {}
    for sym, i in inst.items():
        tok = str(i["angel_token"])
        by_ex.setdefault(i.get("angel_exchange") or "NSE", []).append(tok)
        tok_sym[tok] = sym

    try:
        await angel_client._session()
    except AngelAPIError:
        pass

    out: dict[str, float] = {}
    for grouped in batches(by_ex):
        try:
            for tok, q in (await angel_client.full_quote(grouped)).items():
                if tok in tok_sym and q.get("ltp"):
                    out[tok_sym[tok]] = float(q["ltp"])
        except AngelAPIError:
            pass
        await asyncio.sleep(0.15)
    return out


# ── opening ─────────────────────────────────────────────────────────────────────


async def _open_position(family: str, sig: dict) -> dict | None:
    """Open one paper position from a signal. Idempotent per (family, symbol) while open."""
    symbol = sig["symbol"]
    if await screener_paper_positions_collection.find_one(
            {"family": family, "symbol": symbol, "status": "OPEN"}):
        return None

    entry, stop, target = sig["entry"], sig["stop"], sig["target"]
    if not (entry > 0 and stop > 0 and target > 0 and stop < entry < target):
        return None
    qty = _qty(entry)
    if qty <= 0:
        return None

    doc = {
        "position_id": str(uuid4()),
        "family": family,
        "symbol": symbol,
        "name": sig.get("name"),
        "sector": sig.get("sector"),
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "qty": qty,
        "capital": round(entry * qty, 2),
        "product": FAMILY_PRODUCT[family],
        "opened_at": _now(),
        "opened_on": _today(),
        "status": "OPEN",
        "signal_reason": sig.get("why_summary"),
        "signal_chips": sig.get("why", []),
        "pattern": sig.get("pattern"),
        "net_rr_at_entry": sig.get("net_rr"),
        "ts": _now(),
    }
    await screener_paper_positions_collection.insert_one(doc)
    logger.info("screener paper: opened %s %s @ %.2f (SL %.2f TP %.2f)",
                family, symbol, entry, stop, target)
    return doc


async def _signals_for(family: str, index: str) -> list[dict]:
    """Turn each family's board into a uniform signal shape."""
    from app.services.screener import engine as E
    from app.services.screener import momentum as M
    from app.services.screener import patterns as P
    from app.services.screener import plans as PL

    if family in ("intraday", "swing", "breakout"):
        board = await E.setups(family, index, limit=MAX_OPEN_PER_FAMILY * 3)
        return [{
            "symbol": r["symbol"], "name": r.get("name"), "sector": r.get("sector"),
            "entry": r["plan"]["entry"], "stop": r["plan"]["stop"], "target": r["plan"]["target"],
            "why_summary": r.get("why_summary"), "why": r.get("why", []),
            "net_rr": r["plan"].get("net_rr"),
            "_ok": r["plan"].get("worth_taking"),
        } for r in board["rows"] if r["plan"].get("worth_taking")]

    if family == "momentum":
        # The top of the 1-month board, gated the same way the swing desk is, so this book
        # tests RANK as a signal rather than re-testing the swing setup rules.
        board = await M.board(index, "1m", limit=MAX_OPEN_PER_FAMILY * 3)
        snap = await M.universe_snapshot(index)
        by_sym = {r["symbol"]: r for r in snap["rows"]}
        out = []
        for r in board["rows"]:
            row = by_sym.get(r["symbol"])
            if not row:
                continue
            passes, _ = PL.gate(row, "swing")
            if not passes:
                continue
            plan = PL.swing_plan(row)
            if not plan or not plan.get("net_rr") or plan["net_rr"] < PL.MIN_RR:
                continue
            out.append({
                "symbol": r["symbol"], "name": r.get("name"), "sector": r.get("sector"),
                "entry": plan["entry"], "stop": plan["stop"], "target": plan["target"],
                "why_summary": r.get("why_summary"), "why": r.get("why", []),
                "net_rr": plan.get("net_rr"),
            })
        return out

    if family == "chart_pattern":
        board = await P.board(index=index, state="TRIGGERED", direction="bullish", limit=60)
        return [{
            "symbol": r["symbol"], "name": None, "sector": r.get("sector"),
            "entry": r["entry"], "stop": r["stoploss"], "target": r["target"],
            "why_summary": r["rationale"], "why": [],
            "pattern": f"{r['pattern']} ({r['timeframe_label']})",
            "net_rr": r.get("reward_risk"),
        } for r in board["rows"]]

    return []


# ── managing ────────────────────────────────────────────────────────────────────


def _exit_reason(pos: dict, ltp: float, force_squareoff: bool, aged_out: bool) -> str | None:
    if ltp <= pos["stop"]:
        return "STOP"
    if ltp >= pos["target"]:
        return "TARGET"
    if force_squareoff and pos["family"] == "intraday":
        return "SQUAREOFF"
    if aged_out:
        return "TIME"
    return None


async def _close(pos: dict, ltp: float, reason: str) -> dict:
    fees = round_trip(pos["entry"], ltp, pos["qty"], "BUY", pos["product"])
    gross = (ltp - pos["entry"]) * pos["qty"]
    net = gross - fees.total
    trade = {
        **{k: v for k, v in pos.items() if k != "_id"},
        "exit": round(ltp, 2),
        "exit_reason": reason,
        "closed_at": _now(),
        "closed_on": _today(),
        "gross_pnl": round(gross, 2),
        "fees": fees.total,
        "fee_breakdown": fees.as_dict(),
        "net_pnl": round(net, 2),
        "return_pct": round((ltp / pos["entry"] - 1) * 100, 2),
        "r_multiple": round(net / max(1e-9, (pos["entry"] - pos["stop"]) * pos["qty"]), 2),
        "status": "CLOSED",
        "ts": _now(),
    }
    await screener_paper_trades_collection.insert_one(trade)
    await screener_paper_positions_collection.delete_one({"position_id": pos["position_id"]})
    logger.info("screener paper: closed %s %s @ %.2f (%s) net %.2f",
                pos["family"], pos["symbol"], ltp, reason, net)
    return trade


async def run_cycle(index: str | None = None) -> dict:
    """One manage-then-scan cycle. Manage first, so freed slots can be refilled."""
    from app.services.screener.momentum import DEFAULT_INDEX

    index = index or DEFAULT_INDEX
    now_ist = datetime.now(IST)
    force_squareoff = now_ist.strftime("%H:%M") >= SQUAREOFF_HHMM

    # ── manage ──
    open_pos = [p async for p in screener_paper_positions_collection.find({"status": "OPEN"})]
    quotes = await _quotes(sorted({p["symbol"] for p in open_pos}))
    closed = 0
    for p in open_pos:
        ltp = quotes.get(p["symbol"])
        if ltp is None:
            continue
        age = (now_ist.date() - datetime.fromisoformat(p["opened_on"]).date()).days
        aged_out = age >= FAMILY_MAX_DAYS.get(p["family"], 15) > 0
        reason = _exit_reason(p, ltp, force_squareoff, aged_out)
        if reason:
            await _close(p, ltp, reason)
            closed += 1

    # ── scan ──
    opened = 0
    for family in FAMILIES:
        held = await screener_paper_positions_collection.count_documents(
            {"family": family, "status": "OPEN"})
        room = MAX_OPEN_PER_FAMILY - held
        if room <= 0:
            continue
        # Intraday never opens after the square-off time — a position that would be closed
        # on the same cycle it opened is not a trade, it is a fee.
        if family == "intraday" and force_squareoff:
            continue
        try:
            signals = await _signals_for(family, index)
        except Exception:
            logger.exception("screener paper: signal build failed for %s", family)
            continue
        for sig in signals[:room]:
            if await _open_position(family, sig):
                opened += 1

    await _write_equity()
    await screener_paper_state_collection.replace_one(
        {"_id": STATE_ID},
        {"_id": STATE_ID, "last_cycle": _now(), "last_cycle_on": _today(),
         "opened": opened, "closed": closed, "ts": _now()},
        upsert=True)
    return {"opened": opened, "closed": closed, "managed": len(open_pos), "index": index}


async def _write_equity() -> None:
    """One equity point per family per cycle. TTL'd — this is for charting, not a record."""
    summary_rows = await leaderboard()
    ts = _now()
    for row in summary_rows["families"]:
        await screener_paper_equity_collection.insert_one({
            "family": row["family"], "equity": row["equity"],
            "realised": row["net_pnl"], "open_positions": row["open_positions"], "ts": ts,
        })


# ── reporting ───────────────────────────────────────────────────────────────────


async def leaderboard() -> dict:
    """Per-family performance. This is the answer the desk exists to produce."""
    out = []
    for family in FAMILIES:
        trades = [t async for t in screener_paper_trades_collection.find({"family": family})]
        open_n = await screener_paper_positions_collection.count_documents(
            {"family": family, "status": "OPEN"})

        wins = [t for t in trades if t["net_pnl"] > 0]
        losses = [t for t in trades if t["net_pnl"] <= 0]
        net = sum(t["net_pnl"] for t in trades)
        gross_win = sum(t["net_pnl"] for t in wins)
        gross_loss = abs(sum(t["net_pnl"] for t in losses))
        fees = sum(t.get("fees", 0) for t in trades)

        out.append({
            "family": family,
            "label": FAMILY_LABELS[family],
            "product": FAMILY_PRODUCT[family],
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
            "net_pnl": round(net, 2),
            "gross_pnl": round(sum(t.get("gross_pnl", 0) for t in trades), 2),
            "fees": round(fees, 2),
            # Profit factor and expectancy are the two that actually rank a strategy; win
            # rate alone ranks a martingale first.
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
            "expectancy": round(net / len(trades), 2) if trades else None,
            "avg_r": round(sum(t.get("r_multiple", 0) for t in trades) / len(trades), 2)
                     if trades else None,
            "best": round(max((t["net_pnl"] for t in trades), default=0), 2),
            "worst": round(min((t["net_pnl"] for t in trades), default=0), 2),
            "open_positions": open_n,
            "capital": CAPITAL_PER_FAMILY,
            "equity": round(CAPITAL_PER_FAMILY + net, 2),
            "roi_pct": round(net / CAPITAL_PER_FAMILY * 100, 2),
        })

    ranked = sorted(out, key=lambda r: (-(r["net_pnl"])))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    total_net = sum(r["net_pnl"] for r in out)
    total_trades = sum(r["trades"] for r in out)
    return {
        "families": out,
        "ranked": [r["family"] for r in ranked],
        "total_capital": CAPITAL_PER_FAMILY * len(FAMILIES),
        "total_net_pnl": round(total_net, 2),
        "total_trades": total_trades,
        "total_fees": round(sum(r["fees"] for r in out), 2),
        "per_trade_capital": PER_TRADE,
        "max_open_per_family": MAX_OPEN_PER_FAMILY,
        "note": ("Each family runs its own book so they can be compared. Costs are charged "
                 "on the schedule that family actually trades — intraday pays intraday "
                 "rates, everything else pays delivery rates on both legs."),
    }


async def positions(status: str = "OPEN", family: str | None = None, limit: int = 200) -> dict:
    """Open positions marked to the live quote, or the closed trade log."""
    q: dict = {}
    if family:
        q["family"] = family

    if status.upper() == "OPEN":
        rows = [p async for p in screener_paper_positions_collection.find(
            {**q, "status": "OPEN"}, {"_id": 0}).limit(limit)]
        quotes = await _quotes(sorted({r["symbol"] for r in rows}))
        for r in rows:
            ltp = quotes.get(r["symbol"])
            r["ltp"] = ltp
            if ltp:
                gross = (ltp - r["entry"]) * r["qty"]
                fees = round_trip(r["entry"], ltp, r["qty"], "BUY", r["product"])
                r["unrealised_gross"] = round(gross, 2)
                r["unrealised_net"] = round(gross - fees.total, 2)
                r["return_pct"] = round((ltp / r["entry"] - 1) * 100, 2)
                r["to_target_pct"] = round((r["target"] / ltp - 1) * 100, 2)
                r["to_stop_pct"] = round((r["stop"] / ltp - 1) * 100, 2)
            r.pop("ts", None)
            if r.get("opened_at"):
                r["opened_at"] = r["opened_at"].isoformat()
        rows.sort(key=lambda r: -(r.get("unrealised_net") or 0))
        return {"status": "OPEN", "count": len(rows), "rows": rows}

    rows = [t async for t in screener_paper_trades_collection.find(
        q, {"_id": 0}).sort("closed_at", -1).limit(limit)]
    for r in rows:
        for k in ("opened_at", "closed_at", "ts"):
            if r.get(k) and hasattr(r[k], "isoformat"):
                r[k] = r[k].isoformat()
    return {"status": "CLOSED", "count": len(rows), "rows": rows}


async def summary() -> dict:
    lb = await leaderboard()
    state = await screener_paper_state_collection.find_one({"_id": STATE_ID}) or {}
    return {
        **lb,
        "enabled": ENABLED,
        "squareoff": SQUAREOFF_HHMM,
        "families": lb["families"],
        "last_cycle": state.get("last_cycle").isoformat() if state.get("last_cycle") else None,
        "last_opened": state.get("opened"),
        "last_closed": state.get("closed"),
        "max_hold_days": FAMILY_MAX_DAYS,
    }


async def reset() -> dict:
    """Wipe the desk. Used when the signal rules change enough that old trades would be
    comparing two different strategies under one name."""
    p = await screener_paper_positions_collection.delete_many({})
    t = await screener_paper_trades_collection.delete_many({})
    e = await screener_paper_equity_collection.delete_many({})
    await screener_paper_state_collection.delete_many({"_id": STATE_ID})
    return {"positions_cleared": p.deleted_count, "trades_cleared": t.deleted_count,
            "equity_points_cleared": e.deleted_count}
