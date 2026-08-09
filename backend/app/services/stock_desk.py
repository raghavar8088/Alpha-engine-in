"""Stock-option Pre-Live desks — paper desks for BUYING and SELLING options on single
stocks, the stock twins of the NIFTY Pre-Live desks.

Same idea as the NIFTY desks: consume REAL market data, execute on PAPER, and keep a
per-strategy forward scoreboard so any later promotion rests on forward evidence rather
than a backtest. What differs is the underlying — stocks, not an index — and that changes
three things the NIFTY desks hardcode:

  * lot size is PER STOCK (RELIANCE 500, TCS 225, ITC 1725), read from the contract;
  * the strike ladder is per stock, so ATM is the nearest LISTED strike, never computed
    from a fixed step;
  * stock options expire MONTHLY, so positions are carried, not squared off weekly.

BOTH SIDES SHARE THIS ENGINE. `side="buying"` pays a debit for the ATM option and manages
premium stop/target. `side="selling"` sells the ATM and BUYS a further-out wing — a defined
-risk credit spread, never a naked short, for the same reason the NIFTY selling desk is
built that way: these signals are noisy, and a noisy signal expressed as a naked short is
how a book takes a tail loss.

RATE LIMITS ARE A DESIGN CONSTRAINT, NOT AN AFTERTHOUGHT
Angel prices at most 50 tokens per quote request and throttles history calls. So:
  * bars come from ONE candle call per symbol per cycle, paced (not per strategy);
  * every premium lookup in a cycle — signals and open positions alike — is collected and
    sent as a handful of 50-token batches, not one call per leg;
  * ONE StrategyContext is shared per symbol across all strategies, so 400+ strategies on
    a dozen stocks cost a dozen bar histories, not 5,000.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    instruments_collection,
    stock_desk_equity_collection,
    stock_desk_positions_collection,
    stock_desk_scores_collection,
    stock_desk_state_collection,
    stock_desk_trades_collection,
)
from app.services.angel_client import AngelAPIError, angel_client
from app.services.anti_strategies import register_anti_buying
from app.services.stock_options import atm_contracts, batched_ltp, current_expiry
from tradingai_shared.contracts import STRATEGY_REGISTRY, StrategyContext
from tradingai_shared.domain import Bar, SignalAction, Timeframe

logger = logging.getLogger("stock_desk")

IST = timezone(timedelta(hours=5, minutes=30))
BUYING, SELLING = "buying", "selling"

# Default universe: liquid, high-turnover F&O names spanning several sectors so the desk
# is not a single-sector bet. Env-overridable — widen it once the box is proven to keep up.
DEFAULT_UNIVERSE = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
    "ITC", "AXISBANK", "LT", "BHARTIARTL", "MARUTI", "TATAMOTORS",
]
UNIVERSE = [s.strip().upper() for s in os.getenv("STOCK_DESK_UNIVERSE", ",".join(DEFAULT_UNIVERSE)).split(",") if s.strip()]

TIMEFRAME = os.getenv("STOCK_DESK_TIMEFRAME", "15m")
PER_STRATEGY_CAPITAL = float(os.getenv("STOCK_DESK_PER_STRATEGY_CAPITAL", "1000000"))  # ₹10L each
MAX_OPEN_PER_STRATEGY = int(os.getenv("STOCK_DESK_MAX_OPEN_PER_STRATEGY", "2"))
MAX_OPEN_TOTAL = int(os.getenv("STOCK_DESK_MAX_OPEN_TOTAL", "120"))
LOTS = int(os.getenv("STOCK_DESK_LOTS", "1"))
STOP_PCT = float(os.getenv("STOCK_DESK_STOP_PCT", "0.35"))     # premium stop, buying
TARGET_PCT = float(os.getenv("STOCK_DESK_TARGET_PCT", "0.60"))  # premium target, buying
CREDIT_STOP_MULT = float(os.getenv("STOCK_DESK_CREDIT_STOP_MULT", "2.0"))   # selling: exit at 2x credit
CREDIT_TARGET_PCT = float(os.getenv("STOCK_DESK_CREDIT_TARGET_PCT", "0.55"))  # selling: keep 55% of credit
CANDLE_PACE_SECONDS = float(os.getenv("STOCK_DESK_CANDLE_PACE", "0.4"))
BARS_LOOKBACK_DAYS = int(os.getenv("STOCK_DESK_BARS_DAYS", "12"))
DAILY_LOSS_BREAKER_PCT = float(os.getenv("STOCK_DESK_DAILY_LOSS_PCT", "0.04"))

_TF_MAP = {"5m": Timeframe.M5, "15m": Timeframe.M15, "1h": Timeframe.H1}
_ANGEL_RES = {"5m": "5", "15m": "15", "1h": "60"}


class StockDeskError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist() -> str:
    return datetime.now(IST).date().isoformat()


# ── strategy library per side ────────────────────────────────────────────────────

_libraries: dict[str, list[str]] = {}


def strategy_ids(side: str) -> list[str]:
    """The tradable library for this desk. Buying = the option-buying library PLUS its
    ANTI mirrors; selling = the option-selling library. Computed once."""
    if side in _libraries:
        return _libraries[side]
    try:
        import strategy_service.strategies.options_buying  # noqa: F401
        import strategy_service.strategies.options_selling  # noqa: F401
    except Exception as exc:
        logger.warning("stock_desk: strategy import failed (%s)", exc)
    register_anti_buying()

    want = "options_buying" if side == BUYING else "options_selling"
    ids = []
    for sid, cls in STRATEGY_REGISTRY.items():
        mod = getattr(cls, "__module__", "") or ""
        # An ANTI subclasses its base, so its own __module__ is this package; walk the MRO.
        if want not in mod:
            base = cls.__mro__[1] if len(cls.__mro__) > 1 else None
            mod = getattr(base, "__module__", "") or ""
            if want not in mod:
                continue
        tfs = [getattr(t, "value", str(t)) for t in (getattr(cls.metadata, "timeframes", []) or [])]
        if TIMEFRAME in tfs:
            ids.append(sid)
    ids.sort()
    _libraries[side] = ids
    logger.info("stock_desk[%s]: %s strategies on %s", side, len(ids), TIMEFRAME)
    return ids


# ── in-process state (one context per SYMBOL, shared by every strategy) ──────────

_ctx: dict[str, StrategyContext] = {}
_strats: dict[tuple[str, str, str], object] = {}   # (side, sid, symbol) -> instance


def _instance(side: str, sid: str, symbol: str):
    key = (side, sid, symbol)
    inst = _strats.get(key)
    if inst is None:
        cls = STRATEGY_REGISTRY.get(sid)
        if cls is None:
            return None
        try:
            inst = cls(params={})
        except Exception:
            return None
        _strats[key] = inst
    return inst


# ── bars from Angel candles ──────────────────────────────────────────────────────


async def _load_bars(symbol: str, token: str) -> list[Bar]:
    """One paced Angel candle call per symbol per cycle."""
    now = datetime.now(IST)
    frm = (now - timedelta(days=BARS_LOOKBACK_DAYS)).strftime("%Y-%m-%d 09:15")
    to = now.strftime("%Y-%m-%d %H:%M")
    try:
        rows = await angel_client.candles("NSE", token, _ANGEL_RES.get(TIMEFRAME, "15"), frm, to)
    except (AngelAPIError, Exception) as exc:
        logger.debug("stock_desk: candles failed for %s (%s)", symbol, exc)
        return []
    tf = _TF_MAP.get(TIMEFRAME, Timeframe.M15)
    out: list[Bar] = []
    for r in rows or []:
        try:
            out.append(Bar(symbol=symbol, timeframe=tf, ts=datetime.fromisoformat(r[0]),
                           open=float(r[1]), high=float(r[2]), low=float(r[3]),
                           close=float(r[4]), volume=float(r[5]), oi=None))
        except (ValueError, TypeError, IndexError):
            continue
    return out


# ── capital / scoring ────────────────────────────────────────────────────────────


async def _open_count(side: str, sid: str | None = None) -> int:
    q: dict = {"side": side, "status": "OPEN"}
    if sid:
        q["strategy_id"] = sid
    return await stock_desk_positions_collection.count_documents(q)


async def _realized(side: str, sid: str) -> float:
    total = 0.0
    async for p in stock_desk_positions_collection.find(
        {"side": side, "strategy_id": sid, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    return total


async def _update_score(side: str, sid: str) -> None:
    closed = [p async for p in stock_desk_positions_collection.find(
        {"side": side, "strategy_id": sid, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1})]
    trades = len(closed)
    wins = sum(1 for p in closed if (p.get("realized_pnl") or 0) > 0)
    net = sum(p.get("realized_pnl") or 0 for p in closed)
    gw = sum(p["realized_pnl"] for p in closed if (p.get("realized_pnl") or 0) > 0)
    gl = -sum(p["realized_pnl"] for p in closed if (p.get("realized_pnl") or 0) < 0)
    cls = STRATEGY_REGISTRY.get(sid)
    await stock_desk_scores_collection.update_one(
        {"side": side, "strategy_id": sid},
        {"$set": {
            "side": side, "strategy_id": sid,
            "name": getattr(getattr(cls, "metadata", None), "name", None) or sid,
            "is_anti": sid.startswith("anti_"),
            "trades": trades, "wins": wins,
            "win_rate": round(wins / trades, 4) if trades else 0.0,
            "net_pnl": round(net, 2),
            "profit_factor": round(gw / gl, 2) if gl > 0 else None,
            "allocated_capital": round(PER_STRATEGY_CAPITAL + net, 2),
            "updated_at": _now(),
        }},
        upsert=True,
    )


async def today_pnl(side: str) -> float:
    start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    total = 0.0
    async for p in stock_desk_positions_collection.find(
        {"side": side, "status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    async for p in stock_desk_positions_collection.find(
        {"side": side, "status": "OPEN"}, {"unrealized_pnl": 1}):
        total += p.get("unrealized_pnl") or 0.0
    return total


async def breaker_state(side: str) -> dict:
    pnl = await today_pnl(side)
    n = max(len(strategy_ids(side)), 1)
    limit = DAILY_LOSS_BREAKER_PCT * PER_STRATEGY_CAPITAL * n
    return {"breaker_tripped": pnl <= -limit, "today_pnl": round(pnl, 2),
            "daily_loss_limit": round(limit, 2)}


# ── the cycle ────────────────────────────────────────────────────────────────────


async def run_cycle(side: str) -> dict:
    if side not in (BUYING, SELLING):
        raise StockDeskError(f"side must be '{BUYING}' or '{SELLING}'")
    notes: list[str] = []
    ids = strategy_ids(side)
    if not ids:
        return {"side": side, "opened": 0, "managed": 0, "notes": ["No strategies for this timeframe."]}

    eq = {d["symbol"]: d async for d in instruments_collection.find(
        {"asset_class": "EQUITY", "symbol": {"$in": UNIVERSE}, "angel_token": {"$ne": None}},
        {"symbol": 1, "angel_token": 1})}
    if not eq:
        return {"side": side, "opened": 0, "managed": 0, "notes": ["No universe instruments with Angel tokens."]}

    managed = await _manage(side)

    breaker = await breaker_state(side)
    if breaker["breaker_tripped"]:
        notes.append(f"Daily loss breaker tripped (Rs{breaker['today_pnl']:,.0f}) — no new positions; open ones still managed.")
        await _persist_state(side, 0, managed, notes)
        return {"side": side, "opened": 0, "managed": managed, "notes": notes}
    if await _open_count(side) >= MAX_OPEN_TOTAL:
        notes.append(f"At the {MAX_OPEN_TOTAL}-position desk cap — no new entries.")
        await _persist_state(side, 0, managed, notes)
        return {"side": side, "opened": 0, "managed": managed, "notes": notes}

    # 1) bars: one paced candle call per symbol
    spot: dict[str, float] = {}
    for sym, d in eq.items():
        bars = await _load_bars(sym, str(d["angel_token"]))
        await asyncio.sleep(CANDLE_PACE_SECONDS)
        if not bars:
            continue
        ctx = _ctx.get(sym)
        if ctx is None:
            ctx = _ctx[sym] = StrategyContext(max_bars=500)
        # replay only bars newer than what the context already holds. NOTE: ctx.current
        # RAISES on an empty context rather than returning None, so test ctx.bars.
        last_ts = ctx.bars[-1].ts if ctx.bars else None
        for b in bars:
            if last_ts is None or b.ts > last_ts:
                ctx.push(b)
        spot[sym] = bars[-1].close
    if not spot:
        notes.append("No candles this cycle — nothing evaluated.")
        await _persist_state(side, 0, managed, notes)
        return {"side": side, "opened": 0, "managed": managed, "notes": notes}

    # 2) collect signals (no network here)
    wanted: list[tuple[str, str, str]] = []  # (sid, symbol, option_type)
    for sym in spot:
        ctx = _ctx.get(sym)
        if ctx is None or not ctx.bars:
            continue
        for sid in ids:
            inst = _instance(side, sid, sym)
            if inst is None or len(ctx.bars) < getattr(inst, "warmup", 20):
                continue
            try:
                sig = inst.on_bar(ctx)
            except Exception:
                continue
            if sig is None or sig.signal not in (SignalAction.BUY, SignalAction.SELL):
                continue
            wanted.append((sid, sym, "CE" if sig.signal == SignalAction.BUY else "PE"))

    if not wanted:
        await _persist_state(side, 0, managed, notes)
        return {"side": side, "opened": 0, "managed": managed, "scanned": len(spot), "notes": notes}

    # 3) resolve contracts, then price EVERY leg in batched 50-token requests.
    # Caps are enforced against LIVE counters that this cycle increments as it opens —
    # reading them only from the DB up front let one cycle open a position per (strategy,
    # symbol) before any write landed, which is how 220 strategies put 646 positions on a
    # 120-position desk and 11 on a 2-per-strategy limit.
    open_total = await _open_count(side)
    per_strat: dict[str, int] = {}
    async for row in stock_desk_positions_collection.aggregate([
        {"$match": {"side": side, "status": "OPEN"}},
        {"$group": {"_id": "$strategy_id", "n": {"$sum": 1}}},
    ]):
        per_strat[row["_id"]] = row["n"]

    plans: list[dict] = []
    tokens: list[str] = []
    planned: dict[str, int] = dict(per_strat)
    planned_total = open_total
    for sid, sym, kind in wanted:
        if planned_total >= MAX_OPEN_TOTAL:
            break
        if planned.get(sid, 0) >= MAX_OPEN_PER_STRATEGY:
            continue
        if await stock_desk_positions_collection.find_one(
                {"side": side, "strategy_id": sid, "symbol": sym, "status": "OPEN"}):
            continue
        chain = await atm_contracts(sym, spot[sym])
        leg = chain.get(kind)
        if not leg:
            continue
        plan = {"sid": sid, "symbol": sym, "kind": kind, "short": leg, "wing": None,
                "expiry": await current_expiry(sym), "spot": spot[sym]}
        tokens.append(str(leg["angel_token"]))
        if side == SELLING:
            wing = await _wing(sym, plan["expiry"], leg["strike"], kind)
            if wing is None:
                continue
            plan["wing"] = wing
            tokens.append(str(wing["angel_token"]))
        plans.append(plan)
        planned[sid] = planned.get(sid, 0) + 1
        planned_total += 1

    prices = await batched_ltp({"NFO": tokens}) if tokens else {}

    opened = 0
    for plan in plans:
        # Re-check against the live counters: a plan may have been built before an earlier
        # plan in this same loop filled the strategy's or the desk's last slot.
        if open_total >= MAX_OPEN_TOTAL:
            notes.append(f"Reached the {MAX_OPEN_TOTAL}-position desk cap mid-cycle.")
            break
        sid = plan["sid"]
        if per_strat.get(sid, 0) >= MAX_OPEN_PER_STRATEGY:
            continue
        if await _open_position(side, plan, prices):
            opened += 1
            open_total += 1
            per_strat[sid] = per_strat.get(sid, 0) + 1

    await _persist_state(side, opened, managed, notes)
    return {"side": side, "opened": opened, "managed": managed, "scanned": len(spot),
            "signals": len(wanted), "notes": notes}


async def _wing(symbol: str, expiry: str | None, short_strike: float, kind: str) -> dict | None:
    """The next listed strike further OTM — the long leg that caps the loss."""
    if not expiry:
        return None
    q = {"asset_class": "EQUITY_OPTION", "underlying_symbol": symbol,
         "expiry": expiry, "option_type": kind}
    q["strike"] = {"$gt": short_strike} if kind == "CE" else {"$lt": short_strike}
    order = 1 if kind == "CE" else -1
    async for d in instruments_collection.find(q).sort("strike", order).limit(1):
        return d
    return None


async def _open_position(side: str, plan: dict, prices: dict[str, float]) -> bool:
    short = plan["short"]
    lot = int(short.get("lot_size") or 0)
    if lot <= 0:
        return False
    p_short = prices.get(str(short["angel_token"]))
    if not p_short or p_short <= 0:
        return False
    qty = lot * LOTS
    cls = STRATEGY_REGISTRY.get(plan["sid"])
    doc = {
        "position_id": uuid4().hex[:12], "side": side,
        "strategy_id": plan["sid"],
        "strategy_name": getattr(getattr(cls, "metadata", None), "name", None) or plan["sid"],
        "is_anti": plan["sid"].startswith("anti_"),
        "symbol": plan["symbol"], "option_type": plan["kind"], "expiry": plan["expiry"],
        "strike": short["strike"], "lot_size": lot, "lots": LOTS, "qty": qty,
        "spot_at_entry": round(plan["spot"], 2),
        "angel_tradingsymbol": short.get("angel_tradingsymbol"),
        "short_token": str(short["angel_token"]),
        "entry_premium": round(p_short, 2),
        "ltp": round(p_short, 2), "unrealized_pnl": 0.0, "realized_pnl": None,
        "exit_premium": None, "exit_reason": None, "status": "OPEN",
        "opened_at": _now(), "opened_on": _today_ist(), "updated_at": _now(), "closed_at": None,
    }
    if side == BUYING:
        doc.update({
            "structure": f"LONG {plan['kind']}",
            "capital_deployed": round(p_short * qty, 2),
            "stop_premium": round(p_short * (1 - STOP_PCT), 2),
            "target_premium": round(p_short * (1 + TARGET_PCT), 2),
        })
    else:
        wing = plan["wing"]
        p_wing = prices.get(str(wing["angel_token"])) or 0.0
        credit = p_short - p_wing
        if credit <= 0:
            return False
        width = abs(wing["strike"] - short["strike"])
        doc.update({
            "structure": f"SHORT {plan['kind']} spread {short['strike']:g}/{wing['strike']:g}",
            "wing_token": str(wing["angel_token"]), "wing_strike": wing["strike"],
            "wing_tradingsymbol": wing.get("angel_tradingsymbol"),
            "entry_wing_premium": round(p_wing, 2),
            "credit": round(credit, 2),
            # Defined risk: the most this spread can lose is (width - credit) per unit.
            "max_loss": round((width - credit) * qty, 2),
            "capital_deployed": round((width - credit) * qty, 2),
            "stop_premium": round(credit * CREDIT_STOP_MULT, 2),
            "target_premium": round(credit * (1 - CREDIT_TARGET_PCT), 2),
            "entry_premium": round(credit, 2), "ltp": round(credit, 2),
        })
    await stock_desk_positions_collection.insert_one(doc)
    return True


async def _manage(side: str) -> int:
    """Mark open positions to live premiums and close on stop/target/expiry — every leg in
    one batched, paced set of quote requests."""
    pos = [p async for p in stock_desk_positions_collection.find({"side": side, "status": "OPEN"})]
    if not pos:
        return 0
    tokens: list[str] = []
    for p in pos:
        tokens.append(p["short_token"])
        if p.get("wing_token"):
            tokens.append(p["wing_token"])
    prices = await batched_ltp({"NFO": tokens})

    today = _today_ist()
    updated = 0
    touched: set[str] = set()
    for p in pos:
        ps = prices.get(p["short_token"])
        if ps is None:
            continue
        if side == BUYING:
            cur = ps
            unreal = round((cur - p["entry_premium"]) * p["qty"], 2)
            hit_t = cur >= p["target_premium"]
            hit_s = cur <= p["stop_premium"]
        else:
            pw = prices.get(p.get("wing_token") or "") or 0.0
            cur = ps - pw                      # cost to close the spread
            unreal = round((p["entry_premium"] - cur) * p["qty"], 2)  # credit received minus cost now
            hit_t = cur <= p["target_premium"]
            hit_s = cur >= p["stop_premium"]
        expired = bool(p.get("expiry")) and p["expiry"] <= today
        reason = "target" if hit_t else "stoploss" if hit_s else "expiry" if expired else None

        changes = {"ltp": round(cur, 2), "unrealized_pnl": unreal, "updated_at": _now()}
        if reason:
            changes.update({"status": "CLOSED", "exit_premium": round(cur, 2),
                            "exit_reason": reason, "realized_pnl": unreal,
                            "unrealized_pnl": 0.0, "closed_at": _now()})
            await stock_desk_trades_collection.insert_one({
                "trade_id": uuid4().hex[:12], "side": side, "strategy_id": p["strategy_id"],
                "strategy_name": p.get("strategy_name"), "symbol": p["symbol"],
                "structure": p.get("structure"), "strike": p.get("strike"),
                "option_type": p.get("option_type"), "qty": p["qty"],
                "entry_premium": p["entry_premium"], "exit_premium": round(cur, 2),
                "realized_pnl": unreal, "exit_reason": reason,
                "opened_at": p["opened_at"], "closed_at": _now(),
            })
            touched.add(p["strategy_id"])
        await stock_desk_positions_collection.update_one({"_id": p["_id"]}, {"$set": changes})
        updated += 1

    for sid in touched:
        await _update_score(side, sid)
    return updated


async def _persist_state(side: str, opened: int, managed: int, notes: list[str]) -> None:
    snap = await summary(side)
    await stock_desk_equity_collection.insert_one({
        "side": side, "ts": _now(), "equity": snap["equity"],
        "realized": snap["realized_pnl"], "unrealized": snap["unrealized_pnl"],
        "open_positions": snap["open_positions"],
    })
    await stock_desk_state_collection.update_one(
        {"_id": side},
        {"$set": {"side": side, "last_run_at": _now(), "last_opened": opened,
                  "last_managed": managed, "last_notes": notes,
                  "universe": UNIVERSE, "timeframe": TIMEFRAME,
                  "strategy_count": len(strategy_ids(side))}},
        upsert=True,
    )


# ── read models ──────────────────────────────────────────────────────────────────


async def summary(side: str) -> dict:
    deployed = realized = unrealized = 0.0
    async for p in stock_desk_positions_collection.find(
            {"side": side, "status": "OPEN"}, {"capital_deployed": 1, "unrealized_pnl": 1}):
        deployed += p.get("capital_deployed") or 0.0
        unrealized += p.get("unrealized_pnl") or 0.0
    async for p in stock_desk_positions_collection.find(
            {"side": side, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        realized += p.get("realized_pnl") or 0.0
    n = len(strategy_ids(side))
    initial = PER_STRATEGY_CAPITAL * max(n, 1)
    st = await stock_desk_state_collection.find_one({"_id": side}) or {}
    return {
        "side": side, "mode": "paper",
        "strategy_count": n, "universe": UNIVERSE, "timeframe": TIMEFRAME,
        "per_strategy_capital": PER_STRATEGY_CAPITAL,
        "initial_capital": initial,
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "equity": round(initial + realized + unrealized, 2),
        "open_positions": await _open_count(side),
        "closed_positions": await stock_desk_positions_collection.count_documents(
            {"side": side, "status": {"$ne": "OPEN"}}),
        "last_run_at": st.get("last_run_at").isoformat() if st.get("last_run_at") else None,
        "last_notes": st.get("last_notes", []),
        **(await breaker_state(side)),
    }


async def leaderboard(side: str, limit: int = 300) -> list[dict]:
    rows = []
    async for s in stock_desk_scores_collection.find({"side": side}).sort("net_pnl", -1).limit(limit):
        s.pop("_id", None)
        if s.get("updated_at"):
            s["updated_at"] = s["updated_at"].isoformat()
        rows.append(s)
    return rows


async def positions(side: str, status: str = "OPEN", limit: int = 300) -> list[dict]:
    q = {"side": side}
    if status:
        q["status"] = status.upper()
    rows = []
    async for p in stock_desk_positions_collection.find(q).sort("opened_at", -1).limit(limit):
        p.pop("_id", None)
        for k in ("opened_at", "updated_at", "closed_at"):
            if p.get(k):
                p[k] = p[k].isoformat()
        rows.append(p)
    return rows
