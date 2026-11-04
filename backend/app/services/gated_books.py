"""Gated paper accounts — Phase 4 of INTRADAY_STOCKS_AI_UPGRADE_PLAN.md.

Two paper books copy the tournament's positions through the gates a careful real account would
apply, beside the existing ungated copy books, so the gates' effect is measured on live data:
  A   every tournament position — the gates' effect alone (compare with the ungated Rs 10 lakh book)
  B   only the six rules with a real edge before costs — the future real-money candidate
Rs 10 lakh each. EVENT-DRIVEN: the engine calls on_open / on_close as it opens and closes its own
positions (fire-and-forget, in order, never raising into the engine); a reconcile pass every five
minutes closes any copy whose parent closed while the backend was down.

THE GATES (CONFIG, fixed and fingerprinted for the comparison month)
  5  size by risk: shares = floor(min(risk budget / (stop distance + costs a share),
                                      free cash / entry)), risk budget = 0.5% of equity
  6  reward >= 1.0 x risk after costs where the rule has a target; at most 10 open positions;
     at most 3% of equity at risk in total; one position per stock; at most 3 per NSE industry
  7  no new entries after a 3% loss on the day, or while equity is 8% or more below its peak
  8  the parent's fill is the live price seconds after the bar close (the tournament checks the
     quote's age); spread and visible depth will join once the depth recorder covers a rule
Every decision — opened or the reason it was refused — is written to gated_decisions.

PRICES. A copy enters and exits at the PARENT's fills (slippage included); charges are Angel's
round trip on the book's own quantity. Records live in the box's local MongoDB beside the
decision ledger (alpha_engine_intraday), never Atlas; off when the ledger is off.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import time
from datetime import datetime, timezone

from app.services import intraday_signal_ledger as ledger
from app.services.angel_fees import round_trip

logger = logging.getLogger("gated_books")

IST = ledger.IST
SIX = ("iv2_donchian_45m", "iv2_donchian_1h", "iv2_vwap_trend_1h", "iv2_macd_trend_1h",
       "iv2_rsi_momentum_45m", "iv2_bollinger_snap_1h")
BOOKS = {
    "A": {"label": "Gated A · all tournament signals", "capital": 1_000_000.0, "rules": None},
    "B": {"label": "Gated B · six edge rules", "capital": 1_000_000.0, "rules": SIX},
}
CONFIG = {"risk_per_trade_pct": 0.5, "min_reward_to_risk": 1.0, "max_open": 10, "max_open_risk_pct": 3.0,
          "max_per_stock": 1, "max_per_sector": 3, "daily_loss_stop_pct": 3.0, "drawdown_pause_pct": 8.0,
          "est_charges_bp": 6.0,
          # Phase 8: refuse a stock with a high-materiality announcement in the last N minutes
          # (event_classifier). OFF until a pre-registered test shows it cuts losses.
          "event_gate": os.getenv("GATED_EVENT_GATE", "off").strip().lower() in ("1", "on", "true", "yes"),
          "event_gate_minutes": 120,
          # Phase 9: automatic demotion — after this many closed copies of one rule in a book, a
          # mean net per trade with t <= demote_t pauses that rule in that book (owner resumes it).
          "demote_min_trades": 30, "demote_t": -2.0}
CONFIG_VERSION = hashlib.sha256(json.dumps(CONFIG, sort_keys=True).encode()).hexdigest()[:12]
ENABLED = ledger.ENABLED and os.getenv("GATED_BOOKS", "1").strip().lower() not in ("0", "false", "no", "off")
RECONCILE_EVERY_S = 300

POS, DEC, STATE = "gated_positions", "gated_decisions", "gated_state"
_lock = asyncio.Lock()
_loaded = False
_state: dict[str, dict] = {}
_sectors: dict = {"day": None, "map": {}}
_last_reconcile = 0.0
_tasks: set = set()
stats: dict = {"events": 0, "errors": 0, "last_error": None}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _spawn(coro) -> None:
    try:
        t = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()
        return
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def _load() -> None:
    """State from the database once per process: realised P&L, peak, day, and open copies."""
    global _loaded
    if _loaded:
        return
    db = ledger._db()
    await db[POS].create_index([("book", 1), ("status", 1)], name="book_status")
    await db[POS].create_index("parent_id", name="parent")
    await db[DEC].create_index([("d", 1), ("book", 1)], name="d_book")
    for book, cfg in BOOKS.items():
        doc = await db[STATE].find_one({"_id": book}) or {}
        _state[book] = {"realized": float(doc.get("realized", 0.0)), "peak": float(doc.get("peak", cfg["capital"])),
                        "day": doc.get("day"), "day_pnl": float(doc.get("day_pnl", 0.0)),
                        "rules": doc.get("rules") or {}, "paused": doc.get("paused") or {},
                        "open": {p["parent_id"]: p async for p in db[POS].find({"book": book, "status": "OPEN"})}}
    _loaded = True


async def _save_state(book: str) -> None:
    s = _state[book]
    await ledger._db()[STATE].replace_one({"_id": book}, {
        "_id": book, "realized": round(s["realized"], 2), "peak": round(s["peak"], 2), "day": s["day"],
        "day_pnl": round(s["day_pnl"], 2), "rules": s.get("rules", {}), "paused": s.get("paused", {}),
        "config_version": CONFIG_VERSION, "updated_at": _now()}, upsert=True)


def _record_rule(book: str, sid: str, net_bp: float) -> dict | None:
    """Running per-rule record in a book; returns the demotion evidence when it trips."""
    s = _state[book]
    r = s.setdefault("rules", {}).setdefault(sid, {"n": 0, "s": 0.0, "ss": 0.0})
    r["n"] += 1
    r["s"] += net_bp
    r["ss"] += net_bp * net_bp
    n = r["n"]
    if sid in s.setdefault("paused", {}) or n < CONFIG["demote_min_trades"]:
        return None
    mean = r["s"] / n
    var = max((r["ss"] - n * mean * mean) / (n - 1), 0.0)
    t = mean / math.sqrt(var / n) if var > 0 else 0.0
    if t > CONFIG["demote_t"]:
        return None
    ev = {"at": _now().isoformat(), "trades": n, "mean_net_bp": round(mean, 2), "t": round(t, 2),
          "config_version": CONFIG_VERSION}
    s["paused"][sid] = ev
    return ev


async def _sector(sym: str) -> str:
    if _sectors["day"] != _today():
        try:
            from app.core.db import fundamental_universe_symbols_collection as fu
            _sectors["map"] = {d["_id"]: (d.get("sector") or "Unclassified")
                               async for d in fu.find({}, {"sector": 1})}
        except Exception:  # noqa: BLE001 - a missing map only disables the sector cap's precision
            logger.warning("[gated] sector map unavailable today")
        _sectors["day"] = _today()
    return _sectors["map"].get(sym, "Unclassified")


def _roll(book: str) -> dict:
    s = _state[book]
    if s["day"] != _today():
        s["day"], s["day_pnl"] = _today(), 0.0
    return s


def _risk_ps(p: dict) -> tuple[float, float]:
    """(stop distance, costs) per share for a parent position."""
    entry = float(p["entry_price"])
    stop_dist = abs(entry - float(p.get("stoploss") or entry))
    costs = entry * ((p.get("slippage_bp") or 0.0) + CONFIG["est_charges_bp"]) / 1e4
    return stop_dist, costs


async def _decide(book: str, p: dict) -> tuple[str | None, int, dict]:
    """(refusal reason or None, quantity, detail) for copying parent `p` into `book`."""
    cfg, s = BOOKS[book], _roll(book)
    capital = cfg["capital"]
    equity = capital + s["realized"]
    s["peak"] = max(s["peak"], equity)
    detail = {"equity": round(equity, 2)}
    if p["strategy_id"] in s.get("paused", {}):
        return "strategy paused (demoted)", 0, detail
    if equity < s["peak"] * (1 - CONFIG["drawdown_pause_pct"] / 100):
        return "drawdown pause", 0, detail
    if s["day_pnl"] <= -CONFIG["daily_loss_stop_pct"] / 100 * capital:
        return "daily loss stop", 0, detail
    if len(s["open"]) >= CONFIG["max_open"]:
        return "max open positions", 0, detail
    if any(c["symbol"] == p["symbol"] for c in s["open"].values()):
        return "already holding the stock", 0, detail
    sector = await _sector(p["symbol"])
    detail["sector"] = sector
    if sum(1 for c in s["open"].values() if c.get("sector") == sector) >= CONFIG["max_per_sector"]:
        return "sector limit", 0, detail
    if CONFIG["event_gate"]:
        from app.services import event_classifier
        if await event_classifier.recent_high(p["symbol"], CONFIG["event_gate_minutes"]):
            return "event risk", 0, detail
    entry = float(p["entry_price"])
    stop_dist, costs = _risk_ps(p)
    if stop_dist <= 0:
        return "no stop", 0, detail
    risk_ps = stop_dist + costs
    detail.update({"risk_ps": round(risk_ps, 4)})
    if p.get("target"):
        reward_ps = abs(float(p["target"]) - entry) - costs
        rr = reward_ps / risk_ps
        detail["rr"] = round(rr, 3)
        if rr < CONFIG["min_reward_to_risk"]:
            return "reward below risk after costs", 0, detail
    deployed = sum(c["entry_price"] * c["qty"] for c in s["open"].values())
    cash = equity - deployed
    qty = int(min(CONFIG["risk_per_trade_pct"] / 100 * equity / risk_ps, cash / entry))
    open_risk = sum(c.get("risk", 0.0) for c in s["open"].values())
    room = CONFIG["max_open_risk_pct"] / 100 * equity - open_risk
    qty = min(qty, int(room / risk_ps)) if room > 0 else 0
    if qty < 1:
        return ("total risk limit" if room <= risk_ps else "size below one share"), 0, detail
    detail["risk"] = round(qty * risk_ps, 2)
    return None, qty, detail


async def _open(p: dict) -> None:
    async with _lock:
        await _load()
        db = ledger._db()
        for book, cfg in BOOKS.items():
            if cfg["rules"] is not None and p["strategy_id"] not in cfg["rules"]:
                continue
            why, qty, detail = await _decide(book, p)
            await db[DEC].insert_one({
                "book": book, "d": _today(), "t": _now(), "parent_id": p["position_id"],
                "strategy_id": p["strategy_id"], "symbol": p["symbol"], "side": p["side"],
                "decision": "opened" if why is None else "refused", "why": why, "qty": qty,
                "config_version": CONFIG_VERSION, **detail})
            if why is not None:
                continue
            copy = {"book": book, "parent_id": p["position_id"], "strategy_id": p["strategy_id"],
                    "symbol": p["symbol"], "side": p["side"], "entry_price": float(p["entry_price"]),
                    "stoploss": p.get("stoploss"), "target": p.get("target"), "qty": qty,
                    "risk": detail.get("risk"), "sector": detail.get("sector"),
                    "opened_at": _now(), "opened_on": _today(), "status": "OPEN",
                    "rule_version": p.get("rule_version"), "config_version": CONFIG_VERSION}
            await db[POS].insert_one(copy)
            _state[book]["open"][p["position_id"]] = copy


async def _close(parent_id: str, exit_price: float, reason: str) -> None:
    async with _lock:
        await _load()
        db = ledger._db()
        for book in BOOKS:
            c = _state[book]["open"].pop(parent_id, None)
            if c is None:
                continue
            sign = 1 if c["side"] == "BUY" else -1
            gross = round(sign * (exit_price - c["entry_price"]) * c["qty"], 2)
            fees = round_trip(entry_price=c["entry_price"], exit_price=exit_price, qty=c["qty"],
                              side=c["side"], product="INTRADAY").total
            net = round(gross - fees, 2)
            s = _roll(book)
            s["realized"] += net
            s["day_pnl"] += net
            s["peak"] = max(s["peak"], BOOKS[book]["capital"] + s["realized"])
            await db[POS].update_one({"_id": c["_id"], "status": "OPEN"}, {"$set": {
                "status": "CLOSED", "exit_price": exit_price, "exit_reason": reason, "gross_pnl": gross,
                "fees": round(fees, 2), "realized_pnl": net, "closed_at": _now(), "closed_on": _today()}})
            notional = c["entry_price"] * c["qty"]
            demoted = _record_rule(book, c["strategy_id"], net / notional * 1e4) if notional else None
            if demoted:
                await db[DEC].insert_one({"book": book, "d": _today(), "t": _now(), "parent_id": parent_id,
                                          "strategy_id": c["strategy_id"], "symbol": c["symbol"], "side": c["side"],
                                          "decision": "demoted", "why": "rule paused: forward record significantly negative",
                                          "qty": 0, "config_version": CONFIG_VERSION, **demoted})
                logger.warning("[gated] %s paused in book %s: %s", c["strategy_id"], book, demoted)
            await _save_state(book)


def on_open(parent: dict) -> None:
    """The tournament opened `parent` (its position document). Fire-and-forget."""
    if not ENABLED:
        return
    stats["events"] += 1
    _spawn(_guard(_open(dict(parent))))


def on_close(parent_id: str, exit_price: float, reason: str) -> None:
    """The tournament closed `parent_id` at `exit_price` (its own fill, slippage included)."""
    if not ENABLED:
        return
    stats["events"] += 1
    _spawn(_guard(_close(parent_id, float(exit_price), reason)))


async def _guard(coro) -> None:
    try:
        await coro
    except Exception as exc:  # noqa: BLE001 - never into the engine
        stats["errors"] += 1
        stats["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
        logger.exception("[gated] event failed")


async def _reconcile() -> None:
    """Close copies whose parent is already closed (a close event lost to a restart)."""
    async with _lock:
        await _load()
    open_ids = {pid for s in _state.values() for pid in s["open"]}
    if not open_ids:
        return
    from app.core.db import intraday_lab_positions_collection as parents
    done = [p async for p in parents.find({"position_id": {"$in": sorted(open_ids)}, "status": {"$ne": "OPEN"}},
                                          {"position_id": 1, "exit_price": 1, "exit_reason": 1})]
    for p in done:
        if p.get("exit_price") is not None:
            await _close(p["position_id"], float(p["exit_price"]), f"{p.get('exit_reason')} (reconciled)")


def maybe_reconcile() -> None:
    """Called from the engine's tick; runs at most every RECONCILE_EVERY_S, in the background."""
    global _last_reconcile
    if not ENABLED or time.monotonic() - _last_reconcile < RECONCILE_EVERY_S:
        return
    _last_reconcile = time.monotonic()
    _spawn(_guard(_reconcile()))


def describe() -> dict:
    return {"enabled": ENABLED, "config_version": CONFIG_VERSION, "pending": len(_tasks), **stats}


async def summary() -> dict:
    """Both books: equity, P&L, open positions, today's decisions by reason, the config."""
    out = {"enabled": ENABLED, "config": CONFIG, "config_version": CONFIG_VERSION, "books": []}
    if not ENABLED:
        out["why_off"] = "the decision ledger's local database is not configured"
        return out
    async with _lock:
        await _load()
    db = ledger._db()
    today = _today()
    for book, cfg in BOOKS.items():
        s = _state[book]
        closed = [p async for p in db[POS].find({"book": book, "status": "CLOSED"}, {"realized_pnl": 1, "closed_on": 1})]
        wins = sum(1 for p in closed if (p.get("realized_pnl") or 0) > 0)
        reasons: dict = {}
        async for r in db[DEC].aggregate([{"$match": {"book": book, "d": today}},
                                          {"$group": {"_id": {"dec": "$decision", "why": "$why"}, "n": {"$sum": 1}}}]):
            k = r["_id"]
            reasons[k.get("why") or k.get("dec")] = r["n"]
        equity = cfg["capital"] + s["realized"]
        out["books"].append({
            "book": book, "label": cfg["label"], "capital": cfg["capital"], "equity": round(equity, 2),
            "realized": round(s["realized"], 2), "return_pct": round(s["realized"] / cfg["capital"] * 100, 3),
            "peak": round(s["peak"], 2), "drawdown_pct": round((s["peak"] - equity) / s["peak"] * 100, 3) if s["peak"] else 0.0,
            "today_pnl": round(s["day_pnl"], 2) if s["day"] == today else 0.0,
            "trades": len(closed), "win_rate": round(wins / len(closed), 3) if closed else None,
            "open": [{k: v for k, v in c.items() if k != "_id"} | {"opened_at": c["opened_at"].isoformat()
                     if isinstance(c.get("opened_at"), datetime) else c.get("opened_at")} for c in s["open"].values()],
            "today_decisions": reasons, "rules": list(cfg["rules"]) if cfg["rules"] else "all",
            "paused_rules": s.get("paused", {}),
            "rule_records": {sid: {"trades": r["n"], "mean_net_bp": round(r["s"] / r["n"], 2)}
                             for sid, r in s.get("rules", {}).items() if r.get("n")}})
    return out


async def positions(book: str, status: str = "CLOSED", limit: int = 200) -> list[dict]:
    if not ENABLED or book not in BOOKS:
        return []
    out = []
    async for p in ledger._db()[POS].find({"book": book, "status": status.upper()}, {"_id": 0}).sort(
            "opened_at", -1).limit(max(1, min(limit, 1000))):
        for k in ("opened_at", "closed_at"):
            if isinstance(p.get(k), datetime):
                p[k] = p[k].isoformat()
        out.append(p)
    return out
