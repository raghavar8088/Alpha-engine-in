"""Commodity Trading desk — the paper engine.

311 pattern strategies (39 templates x 8 timeframes, minus opening-range on daily), each
with its own ₹10,00,000 paper account, trading the 8 front-month MCX futures on live
Angel One prices. Paper only; the point is to find which patterns actually pay before any
real money is put behind them.

THREE THINGS THIS DESK DOES THAT THE PATTERN LITERATURE USUALLY DOESN'T
-----------------------------------------------------------------------
1. **Real MCX charges on every fill.** Commodities are not equities: there is no STT,
   there IS Commodity Transaction Tax (0.01%, sell side, non-agri), the exchange charge
   is different again, and the whole lot attracts GST. Charged here on both sides plus
   slippage, because a 2-ATR target on a 1-minute bar is small enough that costs decide
   whether the pattern is an edge or a subsidy to the broker.
2. **Shorts are real.** These are futures, so a head-and-shoulders SELLS rather than
   being skipped. Testing only the bullish half of a two-sided library would report on
   half the strategy.
3. **Bars come from the store, never inline.** Angel throttles the candle endpoint hard
   (measured: 5 of 8 unpaced requests returned 403), so `commodity_bars` polls on a paced
   background loop and the engine only ever reads what has already landed.

CONCENTRATION
-------------
The universe is 8 contracts and the catalog is 311 strategies, so without a cap a single
gold print could be held by dozens of strategies at once. `MAX_STRATEGIES_PER_SYMBOL`
bounds that, the same lesson the option and momentum desks each had to learn.
"""

import logging
import math
import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import (
    commodity_equity_collection,
    commodity_positions_collection,
    commodity_scores_collection,
    commodity_state_collection,
    commodity_trades_collection,
)
from app.services.broker_data import get_ltp
from app.services.commodity_bars import (
    IST,
    TIMEFRAMES,
    front_month_universe,
    is_market_open,
    load_bars,
)
from app.services.commodity_patterns import (
    COMMODITY_BY_ID,
    COMMODITY_CATALOG,
    FAMILY_LABELS,
    evaluate,
)

logger = logging.getLogger("commodity_engine")

STATE_ID = "commodity"

# ── capital ──────────────────────────────────────────────────────────────────────
PER_STRATEGY_ALLOCATION = float(os.getenv("COMMODITY_PER_STRATEGY_CAPITAL", "1000000"))  # ₹10 lakh
MAX_POSITIONS_PER_STRATEGY = int(os.getenv("COMMODITY_MAX_POSITIONS", "1"))
POSITION_NOTIONAL = PER_STRATEGY_ALLOCATION / max(MAX_POSITIONS_PER_STRATEGY, 1)
INITIAL_CAPITAL = PER_STRATEGY_ALLOCATION * max(len(COMMODITY_CATALOG), 1)

MAX_STRATEGIES_PER_SYMBOL = int(os.getenv("COMMODITY_MAX_PER_SYMBOL", "12"))
# Bars of a strategy's OWN timeframe after which an unresolved position is closed. Scaling
# the hold to the timeframe is the point: 60 bars is an hour on 1m and three months on 1d,
# which is what makes one number sane for a catalog spanning both.
MAX_HOLD_BARS = int(os.getenv("COMMODITY_MAX_HOLD_BARS", "60"))
DAILY_LOSS_BREAKER_PCT = float(os.getenv("COMMODITY_DAILY_LOSS_PCT", "0.03"))
PAUSE_NEW_ENTRIES = os.getenv("COMMODITY_PAUSE_ENTRIES", "0").lower() not in ("0", "false", "")
SLIPPAGE_BPS = float(os.getenv("COMMODITY_SLIPPAGE_BPS", "5"))

# ── MCX charges (non-agri futures) ───────────────────────────────────────────────
# Deliberately local rather than added to backtesting_service.costs: that CostModel is
# shared by six other desks and is built on the NSE rate card (STT, equity exchange
# rates). Commodities have a different tax entirely — CTT, not STT — so bending the
# shared model to fit would risk changing what every other desk charges.
BROKERAGE_FLAT = float(os.getenv("COMMODITY_BROKERAGE_FLAT", "20"))
BROKERAGE_PCT = float(os.getenv("COMMODITY_BROKERAGE_PCT", "0.0003"))
CTT_SELL_PCT = float(os.getenv("COMMODITY_CTT_PCT", "0.0001"))       # 0.01%, sell side
EXCH_PCT = float(os.getenv("COMMODITY_EXCH_PCT", "0.000026"))         # ~0.0026%
SEBI_PCT = 0.000001
STAMP_BUY_PCT = float(os.getenv("COMMODITY_STAMP_PCT", "0.00002"))    # 0.002%, buy side
GST_PCT = 0.18


def order_charges(price: float, qty: float, is_buy: bool) -> float:
    """Total MCX charges for one executed side."""
    turnover = price * qty
    if turnover <= 0:
        return 0.0
    brokerage = min(BROKERAGE_FLAT, turnover * BROKERAGE_PCT)
    ctt = 0.0 if is_buy else turnover * CTT_SELL_PCT
    exch = turnover * EXCH_PCT
    sebi = turnover * SEBI_PCT
    stamp = turnover * STAMP_BUY_PCT if is_buy else 0.0
    gst = GST_PCT * (brokerage + exch + sebi)
    return brokerage + ctt + exch + sebi + stamp + gst


# ── promotion gate (same shape as the Momentum desk's) ───────────────────────────
MIN_TRADES_FOR_VERDICT = int(os.getenv("COMMODITY_MIN_TRADES", "30"))
MIN_PROFIT_FACTOR = float(os.getenv("COMMODITY_MIN_PF", "1.2"))
MIN_WIN_RATE = float(os.getenv("COMMODITY_MIN_WIN_RATE", "0.30"))
MAX_DRAWDOWN_PCT = float(os.getenv("COMMODITY_MAX_DD_PCT", "20"))
MIN_T_STAT = float(os.getenv("COMMODITY_MIN_T_STAT", "1.5"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_ist() -> date:
    return datetime.now(IST).date()


def _session_start_utc() -> datetime:
    return datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _size(price: float, budget: float, cash: float) -> int:
    if price <= 0:
        return 0
    return max(int(min(budget, cash) // price), 0)


# ── capital helpers ──────────────────────────────────────────────────────────────


async def _deployed(strategy_id: str) -> float:
    total = 0.0
    async for p in commodity_positions_collection.find(
        {"strategy_id": strategy_id, "status": "OPEN"}, {"capital_deployed": 1}
    ):
        total += p.get("capital_deployed", 0.0)
    return total


async def _realized(strategy_id: str) -> float:
    total = 0.0
    async for p in commodity_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    return total


async def _available_cash(strategy_id: str) -> float:
    return PER_STRATEGY_ALLOCATION + await _realized(strategy_id) - await _deployed(strategy_id)


async def today_pnl() -> float:
    start = _session_start_utc()
    total = 0.0
    async for p in commodity_positions_collection.find(
        {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}
    ):
        total += p.get("realized_pnl") or 0.0
    async for p in commodity_positions_collection.find(
        {"status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}
    ):
        total += p.get("unrealized_pnl") or 0.0
    return total


async def breaker_state() -> dict:
    pnl = await today_pnl()
    limit = DAILY_LOSS_BREAKER_PCT * INITIAL_CAPITAL
    return {"breaker_tripped": pnl <= -limit, "today_pnl": round(pnl, 2),
            "daily_loss_limit": round(limit, 2), "daily_loss_pct": DAILY_LOSS_BREAKER_PCT}


# ── scoring / verdict ────────────────────────────────────────────────────────────


def _trade_stats(closed: list[dict]) -> dict:
    trades = len(closed)
    pnls = [t.get("realized_pnl") or 0.0 for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net, gp, gl = sum(pnls), sum(wins), abs(sum(losses))
    equity = peak = PER_STRATEGY_ALLOCATION
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)
    t_stat = sd = None
    if trades >= 2:
        mean = net / trades
        sd = math.sqrt(sum((p - mean) ** 2 for p in pnls) / (trades - 1))
        if sd > 0:
            t_stat = round(mean / (sd / math.sqrt(trades)), 3)
    return {
        "trades": trades, "wins": len(wins),
        "win_rate": round(len(wins) / trades, 4) if trades else 0.0,
        "net_pnl": round(net, 2), "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
        "total_costs": round(sum(t.get("costs") or 0.0 for t in closed), 2),
        "profit_factor": round(gp / gl, 3) if gl > 0 else None,
        "expectancy": round(net / trades, 2) if trades else 0.0,
        "max_drawdown_pct": round(max_dd, 2), "t_stat": t_stat,
        "pnl_stdev": round(sd, 2) if sd is not None else None,
        "return_pct": round(net / PER_STRATEGY_ALLOCATION * 100, 2),
    }


def _verdict(s: dict) -> tuple[str, list[str]]:
    if s["trades"] < MIN_TRADES_FOR_VERDICT:
        return "PENDING", [f"{s['trades']}/{MIN_TRADES_FOR_VERDICT} closed trades — not enough evidence yet."]
    fails = []
    if s["net_pnl"] <= 0:
        fails.append(f"Net P&L ₹{s['net_pnl']:,.0f} is not positive after real MCX charges.")
    pf = s["profit_factor"]
    if pf is None and s["gross_loss"] == 0 and s["gross_profit"] > 0:
        pass
    elif pf is None or pf <= MIN_PROFIT_FACTOR:
        fails.append(f"Profit factor {'undefined (no winning trades)' if pf is None else round(pf, 2)} "
                     f"is not above {MIN_PROFIT_FACTOR}.")
    if s["expectancy"] <= 0:
        fails.append(f"Expectancy ₹{s['expectancy']:,.0f} per trade is not positive.")
    if s["win_rate"] < MIN_WIN_RATE:
        fails.append(f"Win rate {s['win_rate']*100:.0f}% is below the {MIN_WIN_RATE*100:.0f}% floor.")
    if s["max_drawdown_pct"] > MAX_DRAWDOWN_PCT:
        fails.append(f"Peak-to-trough drawdown {s['max_drawdown_pct']:.1f}% exceeds {MAX_DRAWDOWN_PCT:.0f}%.")
    t = s["t_stat"]
    if t is None and s.get("pnl_stdev") == 0 and s["net_pnl"] > 0:
        pass
    elif t is None or t < MIN_T_STAT:
        fails.append(f"t-statistic {'undefined' if t is None else round(t, 2)} is below {MIN_T_STAT} — "
                     "this record is not separable from luck yet.")
    if fails:
        return "REJECTED", fails
    return "READY", [
        f"{s['trades']} trades, profit factor {'no losing trades' if pf is None else format(pf, '.2f')}, "
        f"expectancy ₹{s['expectancy']:,.0f}/trade, max drawdown {s['max_drawdown_pct']:.1f}%, "
        f"t-stat {'n/a' if t is None else format(t, '.2f')} — clears the gate net of MCX charges."
    ]


async def _update_score(strategy_id: str) -> None:
    spec = COMMODITY_BY_ID.get(strategy_id)
    if spec is None:
        return
    closed = [p async for p in commodity_positions_collection.find(
        {"strategy_id": strategy_id, "status": {"$ne": "OPEN"}},
        {"realized_pnl": 1, "costs": 1, "closed_at": 1}).sort("closed_at", 1)]
    stats = _trade_stats(closed)
    verdict, reasons = _verdict(stats)
    await commodity_scores_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {"strategy_id": strategy_id, "name": spec.name, "family": spec.family,
                  "family_label": FAMILY_LABELS.get(spec.family, spec.family),
                  "template": spec.template, "timeframe": spec.timeframe, **stats,
                  "allocated_capital": round(PER_STRATEGY_ALLOCATION + stats["net_pnl"], 2),
                  "verdict": verdict, "verdict_reasons": reasons, "updated_at": _now()}},
        upsert=True,
    )


# ── position lifecycle ───────────────────────────────────────────────────────────


async def _open_position(spec, symbol: str, inst: dict, sig, bar_ts: datetime) -> bool:
    if await commodity_positions_collection.count_documents(
        {"strategy_id": spec.strategy_id, "status": "OPEN"}
    ) >= MAX_POSITIONS_PER_STRATEGY:
        return False
    if await commodity_positions_collection.find_one(
        {"strategy_id": spec.strategy_id, "symbol": symbol, "status": "OPEN"}
    ):
        return False
    slip = SLIPPAGE_BPS / 10000.0
    fill = sig.entry * (1 + slip) if sig.side == "BUY" else sig.entry * (1 - slip)
    cash = await _available_cash(spec.strategy_id)
    qty = _size(fill, POSITION_NOTIONAL, cash)
    if qty < 1:
        return False
    entry_costs = order_charges(fill, qty, sig.side == "BUY")
    await commodity_positions_collection.insert_one({
        "position_id": uuid4().hex[:12], "strategy_id": spec.strategy_id, "strategy_name": spec.name,
        "family": spec.family, "family_label": FAMILY_LABELS.get(spec.family, spec.family),
        "template": spec.template, "timeframe": spec.timeframe, "pattern": sig.pattern,
        "symbol": symbol, "display_name": inst.get("symbol"),
        "instrument": {"symbol": inst.get("symbol"), "security_id": str(inst.get("security_id")),
                       "exchange_segment": inst.get("exchange_segment"), "expiry": inst.get("expiry"),
                       "lot_size": inst.get("lot_size", 1)},
        "side": sig.side, "signal_price": round(sig.entry, 4), "entry_price": round(fill, 4),
        "qty": qty, "capital_deployed": round(fill * qty, 2), "entry_costs": round(entry_costs, 2),
        "target": round(sig.target, 4), "stoploss": round(sig.stoploss, 4),
        "ltp": round(fill, 4), "ltp_source": "signal_bar",
        "unrealized_pnl": 0.0, "pnl_pct": 0.0, "realized_pnl": None, "costs": None,
        "exit_price": None, "exit_reason": None, "status": "OPEN",
        "confidence": round(sig.confidence, 2), "rationale": sig.rationale,
        "entry_bar_ts": bar_ts, "bars_held": 0, "max_hold_bars": MAX_HOLD_BARS,
        "opened_at": _now(), "opened_on": _today_ist().isoformat(),
        "updated_at": _now(), "closed_at": None,
    })
    return True


async def _close(pos: dict, ltp: float, reason: str) -> float:
    slip = SLIPPAGE_BPS / 10000.0
    is_long = pos["side"] == "BUY"
    fill = ltp * (1 - slip) if is_long else ltp * (1 + slip)
    qty = pos["qty"]
    gross = (fill - pos["entry_price"]) * qty * (1 if is_long else -1)
    costs = (pos.get("entry_costs") or 0.0) + order_charges(fill, qty, not is_long)
    net = gross - costs
    await commodity_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "strategy_id": pos["strategy_id"],
        "strategy_name": pos["strategy_name"], "family": pos.get("family"),
        "template": pos.get("template"), "timeframe": pos.get("timeframe"),
        "pattern": pos.get("pattern"), "symbol": pos["symbol"], "side": pos["side"],
        "entry_price": pos["entry_price"], "exit_price": round(fill, 4), "qty": qty,
        "gross_pnl": round(gross, 2), "costs": round(costs, 2), "realized_pnl": round(net, 2),
        "exit_reason": reason, "rationale": pos.get("rationale"),
        "opened_at": pos["opened_at"], "closed_at": _now(),
    })
    await commodity_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
        "status": "CLOSED", "exit_price": round(fill, 4), "exit_reason": reason,
        "gross_pnl": round(gross, 2), "costs": round(costs, 2), "realized_pnl": round(net, 2),
        "unrealized_pnl": 0.0, "closed_at": _now(), "updated_at": _now(), "ltp": round(ltp, 4),
    }})
    return net


# ── cycles ───────────────────────────────────────────────────────────────────────


async def scan_cycle() -> dict:
    notes: list[str] = []
    breaker = await breaker_state()
    if breaker["breaker_tripped"]:
        return {"opened": 0, "evaluated": 0, "notes": [
            f"DAILY LOSS BREAKER TRIPPED — today's P&L ₹{breaker['today_pnl']:,.0f} crossed the "
            f"₹{breaker['daily_loss_limit']:,.0f} limit. No new positions; open ones still managed."]}

    universe = await front_month_universe()
    if not universe:
        return {"opened": 0, "evaluated": 0,
                "notes": ["No unexpired MCX front-month futures with an Angel token on file."]}

    holders: dict[str, int] = {}
    async for p in commodity_positions_collection.find({"status": "OPEN"}, {"symbol": 1}):
        holders[p["symbol"]] = holders.get(p["symbol"], 0) + 1

    by_tf: dict[str, list] = {}
    for spec in COMMODITY_CATALOG:
        by_tf.setdefault(spec.timeframe, []).append(spec)

    opened = evaluated = capped = 0
    thin: list[str] = []
    for tf, specs in by_tf.items():
        need = max(s.min_bars for s in specs) + 5
        for symbol, inst in universe.items():
            bars = await load_bars(symbol, tf, limit=max(need, 250))
            if len(bars) < need:
                thin.append(f"{symbol}/{tf}({len(bars)})")
                continue
            bar_ts = bars[-1].ts
            for spec in specs:
                if holders.get(symbol, 0) >= MAX_STRATEGIES_PER_SYMBOL:
                    capped += 1
                    break
                evaluated += 1
                sig = evaluate(spec, bars)
                if sig is None:
                    continue
                if await _open_position(spec, symbol, inst, sig, bar_ts):
                    opened += 1
                    holders[symbol] = holders.get(symbol, 0) + 1

    if thin:
        notes.append(f"{len(thin)} (symbol, timeframe) series had too few bars to evaluate — "
                     f"the store is still filling: {', '.join(thin[:8])}"
                     f"{'…' if len(thin) > 8 else ''}")
    if capped:
        notes.append(f"{capped} signals were withheld because their contract already had "
                     f"{MAX_STRATEGIES_PER_SYMBOL} strategies in it — an 8-contract universe "
                     "against 311 strategies concentrates fast without this cap.")
    return {"opened": opened, "evaluated": evaluated, "notes": notes}


async def manage_cycle() -> int:
    open_positions = [p async for p in commodity_positions_collection.find({"status": "OPEN"})]
    if not open_positions:
        return 0
    universe = await front_month_universe()
    prices: dict[str, tuple[float, str]] = {}
    for symbol, inst in universe.items():
        price, src = await get_ltp(None, str(inst.get("security_id")), inst.get("exchange_segment"))
        if price:
            prices[symbol] = (float(price), src)

    updated = 0
    touched: set[str] = set()
    for pos in open_positions:
        got = prices.get(pos["symbol"])
        if not got:
            continue
        ltp, src = got
        is_long = pos["side"] == "BUY"
        qty = pos["qty"]
        gross = (ltp - pos["entry_price"]) * qty * (1 if is_long else -1)
        projected = (pos.get("entry_costs") or 0.0) + order_charges(ltp, qty, not is_long)
        unrealized = gross - projected

        # Bars elapsed on this position's OWN timeframe.
        tf_minutes = TIMEFRAMES.get(pos.get("timeframe", "1d"), (None, 1440))[1]
        entry_ts = pos.get("entry_bar_ts")
        if entry_ts is not None and entry_ts.tzinfo is None:
            entry_ts = entry_ts.replace(tzinfo=timezone.utc)
        bars_held = 0
        if entry_ts is not None:
            bars_held = int((datetime.now(timezone.utc) - entry_ts).total_seconds() // 60 // max(tf_minutes, 1))

        changes = {"ltp": round(ltp, 4), "ltp_source": src, "unrealized_pnl": round(unrealized, 2),
                   "pnl_pct": round((ltp - pos["entry_price"]) / pos["entry_price"] * 100 * (1 if is_long else -1), 3)
                   if pos["entry_price"] else 0.0,
                   "bars_held": bars_held, "updated_at": _now()}

        hit_target = ltp >= pos["target"] if is_long else ltp <= pos["target"]
        hit_stop = ltp <= pos["stoploss"] if is_long else ltp >= pos["stoploss"]
        expired = bars_held >= pos.get("max_hold_bars", MAX_HOLD_BARS)
        reason = "target" if hit_target else "stoploss" if hit_stop else "max_hold_expired" if expired else None

        await commodity_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
        if reason:
            await _close({**pos, **changes}, ltp, reason)
            touched.add(pos["strategy_id"])
        updated += 1

    for sid in touched:
        await _update_score(sid)
    return updated


# ── read models ──────────────────────────────────────────────────────────────────


async def summary() -> dict:
    deployed = realized = unrealized = costs = 0.0
    async for p in commodity_positions_collection.find(
        {"status": "OPEN"}, {"capital_deployed": 1, "unrealized_pnl": 1, "entry_costs": 1}
    ):
        deployed += p.get("capital_deployed", 0.0)
        unrealized += p.get("unrealized_pnl") or 0.0
        costs += p.get("entry_costs") or 0.0
    async for p in commodity_positions_collection.find(
        {"status": {"$ne": "OPEN"}}, {"realized_pnl": 1, "costs": 1}
    ):
        realized += p.get("realized_pnl") or 0.0
        costs += p.get("costs") or 0.0

    verdicts = {"READY": 0, "REJECTED": 0, "PENDING": 0}
    async for s in commodity_scores_collection.find({}, {"verdict": 1}):
        v = s.get("verdict", "PENDING")
        verdicts[v] = verdicts.get(v, 0) + 1
    verdicts["PENDING"] += len(COMMODITY_CATALOG) - sum(verdicts.values())

    return {
        "initial_capital": INITIAL_CAPITAL,
        "per_strategy_allocation": round(PER_STRATEGY_ALLOCATION, 2),
        "position_notional": round(POSITION_NOTIONAL, 2),
        "strategy_count": len(COMMODITY_CATALOG),
        "available_cash": round(INITIAL_CAPITAL + realized - deployed, 2),
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "total_costs": round(costs, 2),
        "equity": round(INITIAL_CAPITAL + realized + unrealized, 2),
        "open_positions": await commodity_positions_collection.count_documents({"status": "OPEN"}),
        "closed_positions": await commodity_positions_collection.count_documents({"status": {"$ne": "OPEN"}}),
        "ready_count": verdicts.get("READY", 0), "rejected_count": verdicts.get("REJECTED", 0),
        "pending_count": verdicts.get("PENDING", 0),
        "paused": PAUSE_NEW_ENTRIES, "mode": "paper", "costs_charged": True,
        "slippage_bps": SLIPPAGE_BPS, "market_open": is_market_open(),
        "max_strategies_per_symbol": MAX_STRATEGIES_PER_SYMBOL,
        "promotion_gate": {"min_trades": MIN_TRADES_FOR_VERDICT, "min_profit_factor": MIN_PROFIT_FACTOR,
                           "min_win_rate": MIN_WIN_RATE, "max_drawdown_pct": MAX_DRAWDOWN_PCT,
                           "min_t_stat": MIN_T_STAT},
        **(await breaker_state()),
    }


async def leaderboard() -> list[dict]:
    scores = {s["strategy_id"]: s async for s in commodity_scores_collection.find({})}
    open_counts: dict[str, int] = {}
    async for p in commodity_positions_collection.find({"status": "OPEN"}, {"strategy_id": 1}):
        open_counts[p["strategy_id"]] = open_counts.get(p["strategy_id"], 0) + 1
    rows = []
    for spec in COMMODITY_CATALOG:
        sc = scores.get(spec.strategy_id) or {}
        net = sc.get("net_pnl", 0.0) or 0.0
        rows.append({
            "strategy_id": spec.strategy_id, "name": spec.name, "family": spec.family,
            "family_label": FAMILY_LABELS.get(spec.family, spec.family),
            "template": spec.template, "timeframe": spec.timeframe,
            "trades": sc.get("trades", 0) or 0, "win_rate": sc.get("win_rate", 0.0) or 0.0,
            "net_pnl": round(net, 2), "total_costs": sc.get("total_costs", 0.0) or 0.0,
            "profit_factor": sc.get("profit_factor"), "expectancy": sc.get("expectancy", 0.0) or 0.0,
            "max_drawdown_pct": sc.get("max_drawdown_pct", 0.0) or 0.0, "t_stat": sc.get("t_stat"),
            "return_pct": sc.get("return_pct", 0.0) or 0.0,
            "allocated_capital": round(PER_STRATEGY_ALLOCATION + net, 2),
            "open_positions": open_counts.get(spec.strategy_id, 0),
            "verdict": sc.get("verdict", "PENDING"),
            "verdict_reasons": sc.get("verdict_reasons",
                                      [f"0/{MIN_TRADES_FOR_VERDICT} closed trades — not enough evidence yet."]),
        })
    rows.sort(key=lambda r: (r["verdict"] != "READY", -r["net_pnl"]))
    return rows


async def run_cycle() -> dict:
    managed = await manage_cycle()
    if PAUSE_NEW_ENTRIES:
        scan = {"opened": 0, "evaluated": 0,
                "notes": ["Commodity entries are paused (COMMODITY_PAUSE_ENTRIES=1); open positions still managed."]}
    else:
        scan = await scan_cycle()
    snap = await summary()
    await commodity_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "deployed": snap["deployed_capital"],
        "open_positions": snap["open_positions"],
    })
    await commodity_state_collection.update_one({"_id": STATE_ID}, {"$set": {
        "last_run_at": _now(), "last_opened": scan["opened"], "last_managed": managed,
        "last_evaluated": scan["evaluated"], "last_notes": scan["notes"],
        "market_open": is_market_open(), "paused": PAUSE_NEW_ENTRIES,
    }}, upsert=True)
    return {"opened": scan["opened"], "managed": managed, "evaluated": scan["evaluated"],
            "notes": scan["notes"]}
