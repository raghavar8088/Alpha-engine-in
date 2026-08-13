"""Momentum Trading — intraday cash-equity momentum on the F&O stock universe.

THE RULE, as specified:
  At 09:20, 09:40 and 10:00 IST on every active trading day, check every F&O stock against
  its previous close:
      up   2% or more  ->  BUY  the stock (long)
      down 2% or more  ->  SELL the stock (short)
  Target +2% and stop -2% from the entry price, in the direction of the trade. Anything
  still open at 15:00 is squared off.

  Later checkpoints only add NEW names — a stock already holding an open position is not
  entered again, so a name that stays up 2% all morning is one position, not three.

THIS TRADES THE SHARES, NOT OPTIONS. That is the difference from the F&O morning-momentum
desk: here a 2% adverse move is a 2% loss on the position, with no premium cap underneath
it. The short side is only possible intraday (cash equities cannot be held short
overnight), which is exactly why everything squares off the same session.

SIZING, since the brief did not state capital: Rs5,00,000 desk, Rs25,000 per position, so
up to 20 concurrent names. When more stocks qualify than the desk can fund — 30 crossed 2%
on a recent session — the STRONGEST movers are taken first and the rest are logged as
skipped, rather than silently dropping whichever the scan happened to reach last.

Prices are live Angel One, and the scan is ONE batched sweep for all 208 stocks.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    instruments_collection,
    momentum_trading_equity_collection,
    momentum_trading_positions_collection,
    momentum_trading_state_collection,
    momentum_trading_trades_collection,
)
from app.services.buy_low_options import scan_falls
from app.services.stock_options import batched_ltp

logger = logging.getLogger("momentum_trading")

IST = timezone(timedelta(hours=5, minutes=30))
STATE_ID = "engine"

ENABLED = os.getenv("MT_ENABLED", "1").lower() not in ("0", "false", "")
CHECKPOINTS = [c.strip() for c in os.getenv("MT_CHECKPOINTS", "09:20,09:40,10:00").split(",") if c.strip()]
GRACE_MIN = int(os.getenv("MT_GRACE_MINUTES", "6"))
MOVE_PCT = float(os.getenv("MT_MOVE_PCT", "2.0"))
TARGET_PCT = float(os.getenv("MT_TARGET_PCT", "2.0"))
STOP_PCT = float(os.getenv("MT_STOP_PCT", "2.0"))
SQUAREOFF = os.getenv("MT_SQUAREOFF", "15:00")
TOTAL_CAPITAL = float(os.getenv("MT_CAPITAL", "500000"))
POSITION_SIZE = float(os.getenv("MT_POSITION_SIZE", "25000"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return date.today().isoformat()


def _hhmm() -> str:
    return datetime.now(IST).strftime("%H:%M")


def _trading_day() -> bool:
    return datetime.now(IST).weekday() < 5


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def due_checkpoint(done: list[str]) -> str | None:
    now = _mins(_hhmm())
    for cp in CHECKPOINTS:
        if cp in done:
            continue
        if _mins(cp) <= now <= _mins(cp) + GRACE_MIN:
            return cp
    return None


# ── capital ──────────────────────────────────────────────────────────────────────


async def _deployed() -> float:
    total = 0.0
    async for p in momentum_trading_positions_collection.find({"status": "OPEN"}, {"cost": 1}):
        total += p.get("cost") or 0.0
    return total


async def _realized() -> float:
    total = 0.0
    async for p in momentum_trading_positions_collection.find(
            {"status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    return total


async def _open_symbols() -> set[str]:
    return set(await momentum_trading_positions_collection.distinct("symbol", {"status": "OPEN"}))


# ── checkpoint ───────────────────────────────────────────────────────────────────


async def run_checkpoint(checkpoint: str) -> dict:
    rows = await scan_falls()                       # one batched sweep, all 208 stocks
    if not rows:
        return {"checkpoint": checkpoint, "opened": 0, "candidates": 0,
                "notes": ["no live quotes this cycle"]}

    held = await _open_symbols()
    # Strongest movers first, so a capital-constrained desk funds the best signals rather
    # than whichever names the scan happened to reach first.
    cands = sorted(
        (r for r in rows if abs(r["change_pct"]) >= MOVE_PCT and r["symbol"] not in held),
        key=lambda r: abs(r["change_pct"]), reverse=True)

    free = TOTAL_CAPITAL + await _realized() - await _deployed()
    opened = skipped = 0
    picks: list[dict] = []
    notes: list[str] = []

    for r in cands:
        if free < POSITION_SIZE:
            skipped += 1
            continue
        price = r["ltp"]
        qty = int(POSITION_SIZE // price) if price > 0 else 0
        if qty < 1:
            skipped += 1
            if len(notes) < 4:
                notes.append(f"{r['symbol']}: one share costs more than the "
                             f"Rs{POSITION_SIZE:,.0f} position size")
            continue
        side = "BUY" if r["change_pct"] > 0 else "SELL"
        sign = 1 if side == "BUY" else -1
        cost = price * qty
        await momentum_trading_positions_collection.insert_one({
            "position_id": uuid4().hex[:12], "session": _today(), "checkpoint": checkpoint,
            "symbol": r["symbol"], "side": side,
            "change_pct_at_entry": r["change_pct"], "prev_close": r["prev_close"],
            "entry_price": round(price, 2), "qty": qty, "cost": round(cost, 2),
            "ltp": round(price, 2),
            # Target and stop always move WITH the trade: a long profits as price rises,
            # a short profits as it falls, so the signs flip with `sign`.
            "target_price": round(price * (1 + sign * TARGET_PCT / 100), 2),
            "stop_price": round(price * (1 - sign * STOP_PCT / 100), 2),
            "unrealized_pnl": 0.0, "realized_pnl": None, "exit_price": None,
            "exit_reason": None, "status": "OPEN",
            "opened_at": _now(), "updated_at": _now(), "closed_at": None,
        })
        free -= cost
        opened += 1
        picks.append({"symbol": r["symbol"], "side": side, "change_pct": r["change_pct"],
                      "price": round(price, 2), "qty": qty, "cost": round(cost, 2)})

    if skipped:
        notes.append(f"{skipped} qualifying stock(s) skipped — desk capital fully deployed.")
    ups = sum(1 for r in rows if r["change_pct"] >= MOVE_PCT)
    downs = sum(1 for r in rows if r["change_pct"] <= -MOVE_PCT)
    return {"checkpoint": checkpoint, "scanned": len(rows), "up": ups, "down": downs,
            "candidates": len(cands), "opened": opened, "skipped": skipped,
            "picks": picks, "notes": notes}


# ── manage ───────────────────────────────────────────────────────────────────────


async def manage() -> dict:
    pos = [p async for p in momentum_trading_positions_collection.find({"status": "OPEN"})]
    if not pos:
        return {"managed": 0, "closed": 0}

    syms = list({p["symbol"] for p in pos})
    eq = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": syms}, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1})}
    prices = await batched_ltp({"NSE": [str(d["angel_token"]) for d in eq.values()]})
    tok2sym = {str(d["angel_token"]): s for s, d in eq.items()}
    ltp_by = {tok2sym[t]: v for t, v in prices.items() if t in tok2sym}

    eod = _hhmm() >= SQUAREOFF
    today = _today()
    closed = 0
    for p in pos:
        ltp = ltp_by.get(p["symbol"])
        stale = p.get("session", today) < today     # never carry a cash short overnight
        if ltp is None:
            if not (eod or stale):
                continue
            ltp = p.get("ltp") or p["entry_price"]
        sign = 1 if p["side"] == "BUY" else -1
        pnl = round(sign * (ltp - p["entry_price"]) * p["qty"], 2)

        hit_t = ltp >= p["target_price"] if sign > 0 else ltp <= p["target_price"]
        hit_s = ltp <= p["stop_price"] if sign > 0 else ltp >= p["stop_price"]
        reason = "target" if hit_t else "stoploss" if hit_s else ("eod" if (eod or stale) else None)

        changes = {"ltp": round(ltp, 2), "unrealized_pnl": pnl, "updated_at": _now(),
                   "pnl_pct": round(sign * (ltp / p["entry_price"] - 1) * 100, 2) if p["entry_price"] else 0.0}
        if reason:
            changes.update({"status": "CLOSED", "exit_price": round(ltp, 2), "exit_reason": reason,
                            "realized_pnl": pnl, "unrealized_pnl": 0.0, "closed_at": _now()})
            await momentum_trading_trades_collection.insert_one({
                "trade_id": uuid4().hex[:12], "session": p.get("session"),
                "checkpoint": p.get("checkpoint"), "symbol": p["symbol"], "side": p["side"],
                "change_pct_at_entry": p.get("change_pct_at_entry"),
                "entry_price": p["entry_price"], "exit_price": round(ltp, 2), "qty": p["qty"],
                "cost": p.get("cost"), "realized_pnl": pnl, "exit_reason": reason,
                "opened_at": p["opened_at"], "closed_at": _now(),
            })
            closed += 1
        await momentum_trading_positions_collection.update_one({"_id": p["_id"]}, {"$set": changes})
    return {"managed": len(pos), "closed": closed}


# ── cycle ────────────────────────────────────────────────────────────────────────


async def run_cycle(force_checkpoint: str | None = None) -> dict:
    if not ENABLED:
        return {"ran": False, "reason": "disabled"}
    session = _today()
    st = await momentum_trading_state_collection.find_one({"_id": STATE_ID}) or {}
    done = st.get("done", []) if st.get("session") == session else []

    managed = await manage()
    cp = force_checkpoint or (due_checkpoint(done) if _trading_day() else None)
    if not cp:
        await momentum_trading_state_collection.update_one(
            {"_id": STATE_ID},
            {"$set": {"session": session, "done": done, "last_run_at": _now(),
                      "last_managed": managed}}, upsert=True)
        return {"ran": False, "reason": f"no checkpoint due (now {_hhmm()} IST; done {done})",
                "managed": managed}

    result = await run_checkpoint(cp)
    done = sorted(set(done + [cp]))
    await momentum_trading_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {"session": session, "done": done, "last_run_at": _now(),
                  "last_checkpoint": result, "last_managed": managed}}, upsert=True)
    snap = await summary()
    await momentum_trading_equity_collection.insert_one({
        "ts": _now(), "session": session, "equity": snap["equity"],
        "realized": snap["realized_pnl"], "unrealized": snap["unrealized_pnl"],
        "open_positions": snap["open_positions"]})
    logger.warning("[momentum_trading] %s: opened %s of %s candidates",
                   cp, result["opened"], result["candidates"])
    return {"ran": True, "managed": managed, **result}


# ── read models ──────────────────────────────────────────────────────────────────


async def summary() -> dict:
    deployed = unreal = 0.0
    async for p in momentum_trading_positions_collection.find(
            {"status": "OPEN"}, {"cost": 1, "unrealized_pnl": 1}):
        deployed += p.get("cost") or 0.0
        unreal += p.get("unrealized_pnl") or 0.0
    realized = await _realized()
    closed = await momentum_trading_positions_collection.count_documents({"status": {"$ne": "OPEN"}})
    wins = await momentum_trading_positions_collection.count_documents(
        {"status": {"$ne": "OPEN"}, "realized_pnl": {"$gt": 0}})
    st = await momentum_trading_state_collection.find_one({"_id": STATE_ID}) or {}
    session = _today()
    done = st.get("done", []) if st.get("session") == session else []
    longs = await momentum_trading_positions_collection.count_documents({"status": "OPEN", "side": "BUY"})
    shorts = await momentum_trading_positions_collection.count_documents({"status": "OPEN", "side": "SELL"})
    return {
        "mode": "paper", "enabled": ENABLED,
        "total_capital": TOTAL_CAPITAL, "position_size": POSITION_SIZE,
        "max_concurrent": int(TOTAL_CAPITAL // POSITION_SIZE),
        "move_pct": MOVE_PCT, "target_pct": TARGET_PCT, "stop_pct": STOP_PCT,
        "checkpoints": CHECKPOINTS, "done_today": done, "squareoff": SQUAREOFF,
        "now_ist": _hhmm(), "next_due": due_checkpoint(done),
        "deployed_capital": round(deployed, 2),
        "free_capital": round(TOTAL_CAPITAL + realized - deployed, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unreal, 2),
        "equity": round(TOTAL_CAPITAL + realized + unreal, 2),
        "open_positions": longs + shorts, "longs": longs, "shorts": shorts,
        "closed_positions": closed, "wins": wins,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "last_run_at": st.get("last_run_at").isoformat() if st.get("last_run_at") else None,
        "last_checkpoint": st.get("last_checkpoint"),
    }


def _ser(d: dict, ts: tuple[str, ...]) -> dict:
    d.pop("_id", None)
    for k in ts:
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


async def positions(status: str = "OPEN", limit: int = 300) -> list[dict]:
    q = {"status": status.upper()} if status else {}
    return [_ser(p, ("opened_at", "updated_at", "closed_at"))
            async for p in momentum_trading_positions_collection.find(q)
            .sort("opened_at", -1).limit(limit)]


async def trades(limit: int = 300) -> list[dict]:
    return [_ser(t, ("opened_at", "closed_at"))
            async for t in momentum_trading_trades_collection.find({})
            .sort("closed_at", -1).limit(limit)]


async def daily_pnl(limit: int = 60) -> list[dict]:
    rows = []
    async for r in momentum_trading_trades_collection.aggregate([
        {"$group": {"_id": "$session", "net_pnl": {"$sum": "$realized_pnl"},
                    "trades": {"$sum": 1},
                    "wins": {"$sum": {"$cond": [{"$gt": ["$realized_pnl", 0]}, 1, 0]}}}},
        {"$sort": {"_id": -1}}, {"$limit": limit},
    ]):
        rows.append({"session": r["_id"], "net_pnl": round(r["net_pnl"] or 0, 2),
                     "trades": r["trades"], "wins": r["wins"],
                     "win_rate": round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0})
    return rows


async def preview() -> dict:
    """Who would be taken right now, without opening anything."""
    rows = await scan_falls()
    held = await _open_symbols()
    cands = sorted((r for r in rows if abs(r["change_pct"]) >= MOVE_PCT),
                   key=lambda r: abs(r["change_pct"]), reverse=True)
    out = []
    for r in cands[:30]:
        qty = int(POSITION_SIZE // r["ltp"]) if r["ltp"] > 0 else 0
        out.append({"symbol": r["symbol"], "change_pct": r["change_pct"], "ltp": r["ltp"],
                    "side": "BUY" if r["change_pct"] > 0 else "SELL", "qty": qty,
                    "cost": round(r["ltp"] * qty, 2), "already_open": r["symbol"] in held})
    return {"scanned": len(rows), "candidates": len(cands),
            "up": sum(1 for r in rows if r["change_pct"] >= MOVE_PCT),
            "down": sum(1 for r in rows if r["change_pct"] <= -MOVE_PCT),
            "rows": out}
