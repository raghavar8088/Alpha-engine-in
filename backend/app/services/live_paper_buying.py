"""Live Paper Buying — the 5 leaderboard winners, on ₹50,000, on live Angel One data.

WHAT THIS IS
The Pre-Live tournament runs the whole option-buying library to find out which strategies
actually work forward. These five came out on top of that leaderboard:

    ANTI intra_macd_hist_turn   ANTI mt_breakout_buying   ANTI intra_rsi_divergence
    ANTI intra_rsi_regime       ANTI intra_ema_stack

This desk trades ONLY those five, on a realistic ₹50,000 book (₹10,000 each) rather than
the tournament's ₹10 lakh-per-strategy accounts, so the P&L is what a real ₹50k account
would have done. Still paper, but on live Angel One prices and REAL option premiums.

ANTI = the reverse of the base strategy. Where the base reads bullish and would buy a CE,
the ANTI buys the PE, and vice versa. The mirror inherits the base's whole state machine
(it subclasses it and negates the direction read), so the two can never drift apart.

MECHANICS
  * NIFTY 15m bars from Angel candles drive the signals; one candle call per cycle, shared
    across all five strategies, so the cost is one request rather than five.
  * A signal buys the ATM CE or PE of the nearest weekly expiry at its live premium.
  * Managed to a premium stop/target and squared off at 15:15 — these are intraday
    strategies, and carrying a 0-DTE option overnight is a different bet than the one the
    leaderboard measured.
  * ₹10,000 per strategy is a hard budget: a position is only opened if a whole lot fits.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    instruments_collection,
    live_paper_equity_collection,
    live_paper_positions_collection,
    live_paper_scores_collection,
    live_paper_state_collection,
    live_paper_trades_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from app.services.anti_strategies import register_anti_buying
from app.services.stock_options import batched_ltp
from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
from tradingai_shared.domain import Bar, SignalAction, Timeframe

logger = logging.getLogger("live_paper_buying")

IST = timezone(timedelta(hours=5, minutes=30))
STATE_ID = "engine"

UNDERLYING = os.getenv("LIVE_PAPER_UNDERLYING", "NIFTY")
TIMEFRAME = "15m"
TOTAL_CAPITAL = float(os.getenv("LIVE_PAPER_CAPITAL", "50000"))
PER_STRATEGY = TOTAL_CAPITAL / 5
STOP_PCT = float(os.getenv("LIVE_PAPER_STOP_PCT", "0.35"))
TARGET_PCT = float(os.getenv("LIVE_PAPER_TARGET_PCT", "0.60"))
ENTRY_CUTOFF = os.getenv("LIVE_PAPER_ENTRY_CUTOFF", "15:00")
SQUAREOFF = os.getenv("LIVE_PAPER_SQUAREOFF", "15:15")
MARKET_OPEN = "09:15"
BARS_DAYS = int(os.getenv("LIVE_PAPER_BARS_DAYS", "10"))

# The five that topped the Pre-Live tournament. Base ids; each is traded as its ANTI.
SELECTED_BASES = [s.strip() for s in os.getenv(
    "LIVE_PAPER_STRATEGIES",
    "intra_macd_hist_turn,mt_breakout_buying,intra_rsi_divergence,intra_rsi_regime,intra_ema_stack"
).split(",") if s.strip()]


class LivePaperError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return date.today().isoformat()


def _hhmm() -> str:
    return datetime.now(IST).strftime("%H:%M")


def _market_open() -> bool:
    return datetime.now(IST).weekday() < 5 and MARKET_OPEN <= _hhmm() <= "15:30"


# ── strategies ───────────────────────────────────────────────────────────────────

_ctx: StrategyContext | None = None
_insts: dict[str, object] = {}


def selected() -> list[dict]:
    """The five ANTI strategies, resolved against the registry."""
    register_anti_buying()
    out = []
    for base in SELECTED_BASES:
        aid = f"anti_{base}"
        cls = STRATEGY_REGISTRY.get(aid)
        if cls is None:
            logger.warning("live_paper: %s not registered", aid)
            continue
        out.append({"strategy_id": aid, "base_id": base,
                    "name": getattr(cls.metadata, "name", aid)})
    return out


def _instance(sid: str):
    inst = _insts.get(sid)
    if inst is None:
        cls = STRATEGY_REGISTRY.get(sid)
        if cls is None:
            return None
        try:
            inst = cls(params={})
        except Exception:
            return None
        _insts[sid] = inst
    return inst


# ── market data ──────────────────────────────────────────────────────────────────


async def _underlying_token() -> tuple[str, str] | None:
    d = await instruments_collection.find_one(
        {"asset_class": "INDEX", "symbol": UNDERLYING, "angel_token": {"$ne": None}},
        {"angel_token": 1, "angel_exchange": 1})
    if not d:
        return None
    return str(d["angel_token"]), d.get("angel_exchange") or "NSE"


async def _bars() -> list[Bar]:
    ref = await _underlying_token()
    if not ref:
        return []
    token, ex = ref
    now = datetime.now(IST)
    frm = (now - timedelta(days=BARS_DAYS)).strftime("%Y-%m-%d 09:15")
    to = now.strftime("%Y-%m-%d %H:%M")
    try:
        rows = await angel_client.candles(ex, token, "15", frm, to)
    except Exception as exc:
        logger.debug("live_paper: candles failed (%s)", exc)
        return []
    out = []
    for r in rows or []:
        try:
            out.append(Bar(symbol=UNDERLYING, timeframe=Timeframe.M15,
                           ts=datetime.fromisoformat(r[0]), open=float(r[1]), high=float(r[2]),
                           low=float(r[3]), close=float(r[4]), volume=float(r[5]), oi=None))
        except (ValueError, TypeError, IndexError):
            continue
    return out


async def _weekly_expiry() -> str | None:
    today = _today()
    exps = [e for e in await instruments_collection.distinct(
        "expiry", {"asset_class": "INDEX_OPTION", "underlying_symbol": UNDERLYING}) if e and e >= today]
    return min(exps) if exps else None


async def _atm(kind: str, spot: float, expiry: str) -> dict | None:
    rows = [d async for d in instruments_collection.find(
        {"asset_class": "INDEX_OPTION", "underlying_symbol": UNDERLYING, "expiry": expiry,
         "option_type": kind, "angel_token": {"$ne": None}},
        {"symbol": 1, "strike": 1, "lot_size": 1, "angel_token": 1, "angel_tradingsymbol": 1})]
    if not rows:
        return None
    return min(rows, key=lambda r: abs(r["strike"] - spot))


# ── capital ──────────────────────────────────────────────────────────────────────


async def _realized(sid: str) -> float:
    t = 0.0
    async for p in live_paper_positions_collection.find(
            {"strategy_id": sid, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        t += p.get("realized_pnl") or 0.0
    return t


async def _deployed(sid: str) -> float:
    t = 0.0
    async for p in live_paper_positions_collection.find(
            {"strategy_id": sid, "status": "OPEN"}, {"cost": 1}):
        t += p.get("cost") or 0.0
    return t


async def _update_score(sid: str) -> None:
    closed = [p async for p in live_paper_positions_collection.find(
        {"strategy_id": sid, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1})]
    n = len(closed)
    wins = sum(1 for p in closed if (p.get("realized_pnl") or 0) > 0)
    net = sum(p.get("realized_pnl") or 0 for p in closed)
    gw = sum(p["realized_pnl"] for p in closed if (p.get("realized_pnl") or 0) > 0)
    gl = -sum(p["realized_pnl"] for p in closed if (p.get("realized_pnl") or 0) < 0)
    meta = next((s for s in selected() if s["strategy_id"] == sid), None)
    await live_paper_scores_collection.update_one(
        {"strategy_id": sid},
        {"$set": {"strategy_id": sid, "name": meta["name"] if meta else sid,
                  "base_id": meta["base_id"] if meta else None,
                  "trades": n, "wins": wins, "win_rate": round(wins / n, 4) if n else 0.0,
                  "net_pnl": round(net, 2),
                  "profit_factor": round(gw / gl, 2) if gl > 0 else None,
                  "expectancy": round(net / n, 2) if n else 0.0,
                  "allocated": round(PER_STRATEGY + net, 2), "updated_at": _now()}},
        upsert=True,
    )


# ── cycle ────────────────────────────────────────────────────────────────────────


async def run_cycle(force: bool = False) -> dict:
    global _ctx
    notes: list[str] = []
    managed = await _manage()

    if not force and not _market_open():
        notes.append(f"Market closed (now {_hhmm()} IST) — open positions still managed.")
        await _persist(0, managed, notes)
        return {"opened": 0, "managed": managed, "signals": 0, "notes": notes}

    bars = await _bars()
    if len(bars) < 60:
        notes.append(f"Only {len(bars)} 15m bars available — not enough history to signal.")
        await _persist(0, managed, notes)
        return {"opened": 0, "managed": managed, "signals": 0, "notes": notes}

    if _ctx is None:
        _ctx = StrategyContext(max_bars=500)
    last = _ctx.bars[-1].ts if _ctx.bars else None
    for b in bars:
        if last is None or b.ts > last:
            _ctx.push(b)

    spot = bars[-1].close
    expiry = await _weekly_expiry()
    if not expiry:
        notes.append("No live NIFTY expiry found.")
        await _persist(0, managed, notes)
        return {"opened": 0, "managed": managed, "signals": 0, "notes": notes}

    past_cutoff = _hhmm() >= ENTRY_CUTOFF
    if past_cutoff:
        notes.append(f"Past the {ENTRY_CUTOFF} entry cutoff — no new entries.")

    wants: list[tuple[dict, str]] = []
    for s in selected():
        inst = _instance(s["strategy_id"])
        if inst is None or len(_ctx.bars) < getattr(inst, "warmup", 30):
            continue
        try:
            sig = inst.on_bar(_ctx)
        except Exception:
            continue
        if sig is None or sig.signal not in (SignalAction.BUY, SignalAction.SELL):
            continue
        # An option-BUYING strategy expresses bullish as a long CE and bearish as a long PE.
        wants.append((s, "CE" if sig.signal == SignalAction.BUY else "PE"))

    if past_cutoff or not wants:
        await _persist(0, managed, notes)
        return {"opened": 0, "managed": managed, "signals": len(wants), "notes": notes}

    # resolve contracts, price them in one batch
    plans, tokens = [], []
    for s, kind in wants:
        if await live_paper_positions_collection.find_one(
                {"strategy_id": s["strategy_id"], "status": "OPEN"}):
            continue          # one open position per strategy
        c = await _atm(kind, spot, expiry)
        if not c:
            continue
        plans.append({"s": s, "kind": kind, "c": c, "spot": spot, "expiry": expiry})
        tokens.append(str(c["angel_token"]))
    prices = await batched_ltp({"NFO": tokens}) if tokens else {}

    opened = 0
    for p in plans:
        if await _open(p, prices):
            opened += 1
    await _persist(opened, managed, notes)
    return {"opened": opened, "managed": managed, "signals": len(wants), "notes": notes}


async def _open(plan: dict, prices: dict[str, float]) -> bool:
    s, c = plan["s"], plan["c"]
    prem = prices.get(str(c["angel_token"]))
    lot = int(c.get("lot_size") or 0)
    if not prem or prem <= 0 or lot <= 0:
        return False
    sid = s["strategy_id"]
    cash = PER_STRATEGY + await _realized(sid) - await _deployed(sid)
    lots = int(min(PER_STRATEGY, cash) // (prem * lot))
    if lots < 1:
        return False                    # a whole lot must fit the ₹10,000 budget
    qty = lots * lot
    await live_paper_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "strategy_id": sid, "strategy_name": s["name"],
        "base_id": s["base_id"], "underlying": UNDERLYING,
        "option_type": plan["kind"], "strike": c["strike"], "expiry": plan["expiry"],
        "angel_tradingsymbol": c.get("angel_tradingsymbol"), "token": str(c["angel_token"]),
        "lot_size": lot, "lots": lots, "qty": qty,
        "spot_at_entry": round(plan["spot"], 2),
        "entry_premium": round(prem, 2), "ltp": round(prem, 2),
        "cost": round(prem * qty, 2),
        "target_premium": round(prem * (1 + TARGET_PCT), 2),
        "stop_premium": round(prem * (1 - STOP_PCT), 2),
        "unrealized_pnl": 0.0, "realized_pnl": None, "exit_premium": None,
        "exit_reason": None, "status": "OPEN",
        "session": _today(), "opened_at": _now(), "updated_at": _now(), "closed_at": None,
    })
    return True


async def _manage() -> int:
    pos = [p async for p in live_paper_positions_collection.find({"status": "OPEN"})]
    if not pos:
        return 0
    prices = await batched_ltp({"NFO": [p["token"] for p in pos]})
    hhmm = _hhmm()
    today = _today()
    eod = hhmm >= SQUAREOFF
    touched: set[str] = set()
    updated = 0
    for p in pos:
        cur = prices.get(p["token"])
        stale = p.get("session", today) < today          # left over from a previous session
        if cur is None:
            if not (eod or stale):
                continue
            cur = 0.0
        pnl = round((cur - p["entry_premium"]) * p["qty"], 2)
        reason = None
        if cur >= p["target_premium"]:
            reason = "target"
        elif cur <= p["stop_premium"]:
            reason = "stoploss"
        elif eod or stale:
            reason = "eod"
        changes = {"ltp": round(cur, 2), "unrealized_pnl": pnl, "updated_at": _now()}
        if reason:
            changes.update({"status": "CLOSED", "exit_premium": round(cur, 2),
                            "exit_reason": reason, "realized_pnl": pnl,
                            "unrealized_pnl": 0.0, "closed_at": _now()})
            await live_paper_trades_collection.insert_one({
                "trade_id": uuid4().hex[:12], "strategy_id": p["strategy_id"],
                "strategy_name": p.get("strategy_name"), "underlying": p.get("underlying"),
                "option_type": p["option_type"], "strike": p["strike"],
                "qty": p["qty"], "lots": p.get("lots"),
                "entry_premium": p["entry_premium"], "exit_premium": round(cur, 2),
                "cost": p.get("cost"), "realized_pnl": pnl, "exit_reason": reason,
                "session": p.get("session"), "opened_at": p["opened_at"], "closed_at": _now(),
            })
            touched.add(p["strategy_id"])
        await live_paper_positions_collection.update_one({"_id": p["_id"]}, {"$set": changes})
        updated += 1
    for sid in touched:
        await _update_score(sid)
    return updated


async def _persist(opened: int, managed: int, notes: list[str]) -> None:
    snap = await summary()
    await live_paper_equity_collection.insert_one({
        "ts": _now(), "session": _today(), "equity": snap["equity"],
        "realized": snap["realized_pnl"], "unrealized": snap["unrealized_pnl"],
        "open_positions": snap["open_positions"],
    })
    await live_paper_state_collection.update_one(
        {"_id": STATE_ID},
        {"$set": {"last_run_at": _now(), "last_opened": opened, "last_managed": managed,
                  "last_notes": notes}}, upsert=True)


# ── read models ──────────────────────────────────────────────────────────────────


async def summary() -> dict:
    deployed = realized = unreal = 0.0
    async for p in live_paper_positions_collection.find({"status": "OPEN"}, {"cost": 1, "unrealized_pnl": 1}):
        deployed += p.get("cost") or 0.0
        unreal += p.get("unrealized_pnl") or 0.0
    async for p in live_paper_positions_collection.find({"status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        realized += p.get("realized_pnl") or 0.0
    closed = await live_paper_positions_collection.count_documents({"status": {"$ne": "OPEN"}})
    wins = await live_paper_positions_collection.count_documents(
        {"status": {"$ne": "OPEN"}, "realized_pnl": {"$gt": 0}})
    st = await live_paper_state_collection.find_one({"_id": STATE_ID}) or {}
    return {
        "mode": "paper", "underlying": UNDERLYING, "timeframe": TIMEFRAME,
        "total_capital": TOTAL_CAPITAL, "per_strategy": round(PER_STRATEGY, 2),
        "strategy_count": len(selected()),
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unreal, 2),
        "equity": round(TOTAL_CAPITAL + realized + unreal, 2),
        "open_positions": await live_paper_positions_collection.count_documents({"status": "OPEN"}),
        "closed_positions": closed, "wins": wins,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "market_open": _market_open(),
        "entry_cutoff": ENTRY_CUTOFF, "squareoff": SQUAREOFF,
        "last_run_at": st.get("last_run_at").isoformat() if st.get("last_run_at") else None,
        "last_notes": st.get("last_notes", []),
    }


async def leaderboard() -> list[dict]:
    scores = {s["strategy_id"]: s async for s in live_paper_scores_collection.find({})}
    rows = []
    for s in selected():
        sc = scores.get(s["strategy_id"]) or {}
        rows.append({**s,
                     "trades": sc.get("trades", 0) or 0,
                     "wins": sc.get("wins", 0) or 0,
                     "win_rate": sc.get("win_rate", 0.0) or 0.0,
                     "net_pnl": round(sc.get("net_pnl", 0.0) or 0.0, 2),
                     "profit_factor": sc.get("profit_factor"),
                     "expectancy": sc.get("expectancy", 0.0) or 0.0,
                     "allocated": round(sc.get("allocated", PER_STRATEGY) or PER_STRATEGY, 2)})
    rows.sort(key=lambda r: r["net_pnl"], reverse=True)
    return rows


def _ser(d: dict, ts: tuple[str, ...]) -> dict:
    d.pop("_id", None)
    for k in ts:
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


async def positions(status: str = "OPEN", limit: int = 300) -> list[dict]:
    q = {"status": status.upper()} if status else {}
    return [_ser(p, ("opened_at", "updated_at", "closed_at"))
            async for p in live_paper_positions_collection.find(q).sort("opened_at", -1).limit(limit)]


async def trades(limit: int = 300) -> list[dict]:
    return [_ser(t, ("opened_at", "closed_at"))
            async for t in live_paper_trades_collection.find({}).sort("closed_at", -1).limit(limit)]


async def daily_pnl(limit: int = 60) -> list[dict]:
    rows = []
    async for r in live_paper_trades_collection.aggregate([
        {"$group": {"_id": "$session", "net_pnl": {"$sum": "$realized_pnl"},
                    "trades": {"$sum": 1},
                    "wins": {"$sum": {"$cond": [{"$gt": ["$realized_pnl", 0]}, 1, 0]}}}},
        {"$sort": {"_id": -1}}, {"$limit": limit},
    ]):
        rows.append({"session": r["_id"], "net_pnl": round(r["net_pnl"] or 0, 2),
                     "trades": r["trades"], "wins": r["wins"],
                     "win_rate": round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0})
    return rows
