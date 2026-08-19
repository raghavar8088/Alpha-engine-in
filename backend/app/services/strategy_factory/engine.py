"""Strategy Factory desk: batch backtesting and Rs10L-per-strategy paper trading.

Both halves call the SAME `signals.evaluate()`. The backtester feeds it a historical
slice, the paper desk feeds it the live slice, and neither has its own copy of the
decision logic — so a backtest number describes what the desk will actually do.

BAR SOURCE
----------
The factory is instrument-agnostic; it needs only something that can answer
"give me the last N bars of SYMBOL on TIMEFRAME". Today that is the commodity store
(`commodity_bars`), which is the only source in this app carrying all eight timeframes
with real data. `BAR_SOURCES` is where an equity or index store plugs in later without
touching a single strategy.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from app.core.db import (
    sf_backtests_collection,
    sf_equity_collection,
    sf_positions_collection,
    sf_scores_collection,
    sf_signals_collection,
    sf_state_collection,
    sf_trades_collection,
)

from .backtest import DEFAULT_MAX_HOLD, backtest
from .catalog import FACTORY_BY_ID, FACTORY_CATALOG, HTF_OF, family_counts
from .primitives import (
    DEFAULT_CAPITAL, DEFAULT_RISK_PCT, Levels, classify_regime, position_size,
    round_trip_cost, slippage_price,
)
from .signals import evaluate

logger = logging.getLogger("strategy_factory")

STATE_ID = "strategy_factory"

PER_STRATEGY_CAPITAL = DEFAULT_CAPITAL
INITIAL_CAPITAL = PER_STRATEGY_CAPITAL * len(FACTORY_CATALOG)
MAX_POSITIONS_PER_STRATEGY = int(os.getenv("SF_MAX_POSITIONS", "1"))
MAX_STRATEGIES_PER_SYMBOL = int(os.getenv("SF_MAX_PER_SYMBOL", "40"))
SLIPPAGE_BPS = float(os.getenv("SF_SLIPPAGE_BPS", "5"))
PAUSE_NEW_ENTRIES = os.getenv("SF_PAUSE_ENTRIES", "0").lower() not in ("0", "false", "")
DAILY_LOSS_BREAKER_PCT = float(os.getenv("SF_DAILY_LOSS_PCT", "0.03"))
# Only strategies graded at least this well are allowed to trade paper. Ungraded
# strategies (no backtest yet) are held back rather than let loose: the brief's whole
# point is that paper trading is EARNED by evidence, not granted by existing.
MIN_GRADE_TO_TRADE = int(os.getenv("SF_MIN_GRADE", "3"))
REQUIRE_GRADE = os.getenv("SF_REQUIRE_GRADE", "1").lower() not in ("0", "false", "")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------------
# Bar sources
# --------------------------------------------------------------------------------


async def _commodity_bars(symbol: str, timeframe: str, limit: int):
    from app.services.commodity_bars import load_bars
    return await load_bars(symbol, timeframe, limit)


async def _commodity_universe() -> dict[str, dict]:
    from app.services.commodity_bars import front_month_universe
    return await front_month_universe()


BAR_SOURCES = {
    "commodity": {"bars": _commodity_bars, "universe": _commodity_universe,
                  "cost_model": "commodity", "exchange": "MCX"},
}
DEFAULT_SOURCE = os.getenv("SF_BAR_SOURCE", "commodity")


# --------------------------------------------------------------------------------
# Backtesting (batch)
# --------------------------------------------------------------------------------


def _metrics_doc(m) -> dict:
    return {k: getattr(m, k) for k in (
        "trades", "wins", "win_rate", "net_pnl", "gross_profit", "gross_loss",
        "total_costs", "profit_factor", "expectancy", "avg_r", "max_drawdown_pct",
        "return_pct", "cagr_pct", "sharpe", "sortino", "largest_win", "largest_loss",
        "max_consecutive_wins", "max_consecutive_losses", "exposure_pct")}


async def run_backtests(source: str = DEFAULT_SOURCE, symbols: list[str] | None = None,
                        strategy_ids: list[str] | None = None,
                        bar_limit: int = 1500) -> dict:
    """Backtest strategies over every symbol in the source and persist one row each.

    Results are stored per (strategy, symbol) rather than averaged: a pattern that works
    on crude and fails on gold is useful information, and blending them into one number
    destroys exactly the answer the brief asks for."""
    src = BAR_SOURCES.get(source)
    if src is None:
        return {"error": f"unknown bar source {source!r}"}
    universe = await src["universe"]()
    names = [s for s in (symbols or sorted(universe)) if s in universe]
    if not names:
        return {"error": "no symbols available from this source", "source": source}

    strategies = [FACTORY_BY_ID[i] for i in strategy_ids if i in FACTORY_BY_ID] \
        if strategy_ids else FACTORY_CATALOG

    # Cache bars per (symbol, timeframe): 546 strategies share only 8 timeframes, so
    # loading per strategy would be ~68x more database work for identical data.
    cache: dict[tuple[str, str], list] = {}

    async def bars_for(sym: str, tf: str):
        key = (sym, tf)
        if key not in cache:
            cache[key] = await src["bars"](sym, tf, bar_limit)
        return cache[key]

    written = skipped = 0
    graded: dict[int, int] = {}
    for sym in names:
        inst = universe[sym]
        lot = int(inst.get("lot_size") or 1)
        for strat in strategies:
            bars = await bars_for(sym, strat.timeframe)
            if len(bars) < strat.min_bars + 30:
                skipped += 1
                continue
            htf = await bars_for(sym, strat.htf) if strat.htf else None
            res = backtest(strat, bars, sym, src["exchange"], htf_bars=htf,
                           capital=PER_STRATEGY_CAPITAL, cost_model=src["cost_model"],
                           slippage_bps=SLIPPAGE_BPS, lot_size=lot)
            graded[res.grade] = graded.get(res.grade, 0) + 1
            await sf_backtests_collection.update_one(
                {"strategy_id": strat.strategy_id, "symbol": sym, "source": source},
                {"$set": {
                    "strategy_id": strat.strategy_id, "name": strat.name,
                    "family": strat.family, "sub_family": strat.sub_family,
                    "timeframe": strat.timeframe, "htf": strat.htf, "style": strat.style,
                    "hypothesis": strat.hypothesis, "detector": strat.detector,
                    "target_r": strat.target_r, "regimes": sorted(strat.regimes),
                    "symbol": sym, "source": source, "exchange": src["exchange"],
                    "bars_tested": res.bars_tested, "span_days": res.span_days,
                    "overall": _metrics_doc(res.overall),
                    "in_sample": _metrics_doc(res.in_sample),
                    "out_of_sample": _metrics_doc(res.out_of_sample),
                    "grade": res.grade, "grade_reasons": res.grade_reasons,
                    "rejections": res.rejections,
                    "equity_curve": [round(v, 2) for v in res.equity_curve[-400:]],
                    "updated_at": _now(),
                }}, upsert=True)
            written += 1

    await _refresh_scores()
    await sf_state_collection.update_one({"_id": STATE_ID}, {"$set": {
        "last_backtest_at": _now(), "backtests_written": written,
        "backtests_skipped": skipped, "grade_histogram": graded, "source": source,
    }}, upsert=True)
    return {"written": written, "skipped": skipped, "symbols": names,
            "grade_histogram": graded, "strategies": len(strategies)}


async def _refresh_scores() -> None:
    """Roll per-(strategy, symbol) backtests into one row per strategy.

    The strategy's grade is its BEST grade on any symbol, and the row records which
    symbol earned it — because "this works on crude" is the actionable answer, whereas an
    average across eight unrelated contracts is not."""
    best: dict[str, dict] = {}
    async for d in sf_backtests_collection.find({}):
        sid = d["strategy_id"]
        cur = best.get(sid)
        key = (d.get("grade", 1), (d.get("overall") or {}).get("net_pnl", 0))
        if cur is None or key > cur["_key"]:
            best[sid] = {"_key": key, "doc": d}
    for sid, entry in best.items():
        d = entry["doc"]
        o = d.get("overall") or {}
        await sf_scores_collection.update_one({"strategy_id": sid}, {"$set": {
            "strategy_id": sid, "name": d.get("name"), "family": d.get("family"),
            "sub_family": d.get("sub_family"), "timeframe": d.get("timeframe"),
            "style": d.get("style"), "hypothesis": d.get("hypothesis"),
            "best_symbol": d.get("symbol"), "grade": d.get("grade", 1),
            "grade_reasons": d.get("grade_reasons", []),
            "bt_trades": o.get("trades", 0), "bt_win_rate": o.get("win_rate", 0.0),
            "bt_profit_factor": o.get("profit_factor"), "bt_expectancy": o.get("expectancy", 0.0),
            "bt_avg_r": o.get("avg_r", 0.0), "bt_net_pnl": o.get("net_pnl", 0.0),
            "bt_max_dd_pct": o.get("max_drawdown_pct", 0.0), "bt_cagr_pct": o.get("cagr_pct"),
            "bt_sharpe": o.get("sharpe"), "bt_sortino": o.get("sortino"),
            "oos_net_pnl": (d.get("out_of_sample") or {}).get("net_pnl", 0.0),
            "oos_trades": (d.get("out_of_sample") or {}).get("trades", 0),
            "updated_at": _now(),
        }}, upsert=True)


# --------------------------------------------------------------------------------
# Paper trading
# --------------------------------------------------------------------------------


async def _tradable_ids() -> set[str]:
    if not REQUIRE_GRADE:
        return {s.strategy_id for s in FACTORY_CATALOG}
    out = set()
    async for d in sf_scores_collection.find({"grade": {"$gte": MIN_GRADE_TO_TRADE}},
                                             {"strategy_id": 1}):
        out.add(d["strategy_id"])
    return out


async def _realized(sid: str) -> float:
    total = 0.0
    async for p in sf_positions_collection.find(
            {"strategy_id": sid, "status": {"$ne": "OPEN"}}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    return total


async def _deployed(sid: str) -> float:
    total = 0.0
    async for p in sf_positions_collection.find(
            {"strategy_id": sid, "status": "OPEN"}, {"capital_deployed": 1}):
        total += p.get("capital_deployed", 0.0)
    return total


async def _cash(sid: str) -> float:
    return PER_STRATEGY_CAPITAL + await _realized(sid) - await _deployed(sid)


async def today_pnl() -> float:
    from app.services.commodity_bars import IST
    start = datetime.now(IST).replace(hour=0, minute=0, second=0,
                                      microsecond=0).astimezone(timezone.utc)
    total = 0.0
    async for p in sf_positions_collection.find(
            {"status": {"$ne": "OPEN"}, "closed_at": {"$gte": start}}, {"realized_pnl": 1}):
        total += p.get("realized_pnl") or 0.0
    async for p in sf_positions_collection.find(
            {"status": "OPEN", "opened_at": {"$gte": start}}, {"unrealized_pnl": 1}):
        total += p.get("unrealized_pnl") or 0.0
    return total


async def breaker_state() -> dict:
    pnl = await today_pnl()
    limit = DAILY_LOSS_BREAKER_PCT * INITIAL_CAPITAL
    return {"breaker_tripped": pnl <= -limit, "today_pnl": round(pnl, 2),
            "daily_loss_limit": round(limit, 2)}


async def run_paper_cycle(source: str = DEFAULT_SOURCE) -> dict:
    """One scan+manage pass over the live bar store."""
    src = BAR_SOURCES.get(source)
    if src is None:
        return {"error": f"unknown bar source {source!r}"}

    managed = await _manage(src)
    notes: list[str] = []
    opened = 0
    breaker = await breaker_state()

    if PAUSE_NEW_ENTRIES:
        notes.append("Entries paused (SF_PAUSE_ENTRIES=1); open positions still managed.")
    elif breaker["breaker_tripped"]:
        notes.append(f"Daily loss breaker tripped at {breaker['today_pnl']:,.0f}; "
                     "no new entries, open positions still managed.")
    else:
        opened, scan_notes = await _scan(src, source)
        notes += scan_notes

    snap = await summary()
    await sf_equity_collection.insert_one({
        "ts": _now(), "equity": snap["equity"], "realized": snap["realized_pnl"],
        "unrealized": snap["unrealized_pnl"], "open_positions": snap["open_positions"]})
    await sf_state_collection.update_one({"_id": STATE_ID}, {"$set": {
        "last_run_at": _now(), "last_opened": opened, "last_managed": managed,
        "last_notes": notes}}, upsert=True)
    return {"opened": opened, "managed": managed, "notes": notes}


async def _scan(src: dict, source: str) -> tuple[int, list[str]]:
    notes: list[str] = []
    tradable = await _tradable_ids()
    if not tradable:
        return 0, ["No strategy has earned a paper allocation yet — run the backtest "
                   f"first; only grade >= {MIN_GRADE_TO_TRADE} strategies trade."]

    universe = await src["universe"]()
    if not universe:
        return 0, ["Bar source has no tradable symbols."]

    holders: dict[str, int] = {}
    async for p in sf_positions_collection.find({"status": "OPEN"}, {"symbol": 1}):
        holders[p["symbol"]] = holders.get(p["symbol"], 0) + 1

    strategies = [s for s in FACTORY_CATALOG if s.strategy_id in tradable]
    cache: dict[tuple[str, str], list] = {}
    opened = capped = thin = 0

    for sym, inst in universe.items():
        lot = int(inst.get("lot_size") or 1)
        for strat in strategies:
            if holders.get(sym, 0) >= MAX_STRATEGIES_PER_SYMBOL:
                capped += 1
                continue
            key = (sym, strat.timeframe)
            if key not in cache:
                cache[key] = await src["bars"](sym, strat.timeframe, 600)
            bars = cache[key]
            if len(bars) < strat.min_bars:
                thin += 1
                continue
            htf = None
            if strat.htf:
                hk = (sym, strat.htf)
                if hk not in cache:
                    cache[hk] = await src["bars"](sym, strat.htf, 400)
                htf = cache[hk]

            sig, rej = evaluate(strat, bars, sym, src["exchange"], htf)
            if sig is None:
                continue
            if await _open(strat, sig, inst, lot, src, source):
                opened += 1
                holders[sym] = holders.get(sym, 0) + 1

    if thin:
        notes.append(f"{thin} (symbol, timeframe) series were too short to evaluate — "
                     "the bar store is still filling.")
    if capped:
        notes.append(f"{capped} evaluations skipped: symbol already held by "
                     f"{MAX_STRATEGIES_PER_SYMBOL} strategies.")
    notes.append(f"{len(strategies)} of {len(FACTORY_CATALOG)} strategies are graded "
                 f">= {MIN_GRADE_TO_TRADE} and eligible to trade.")
    return opened, notes


async def _open(strat, sig, inst: dict, lot: int, src: dict, source: str) -> bool:
    if await sf_positions_collection.count_documents(
            {"strategy_id": strat.strategy_id, "status": "OPEN"}) >= MAX_POSITIONS_PER_STRATEGY:
        return False
    if await sf_positions_collection.find_one(
            {"strategy_id": strat.strategy_id, "symbol": sig.symbol, "status": "OPEN"}):
        return False

    long = sig.side == "BUY"
    fill = slippage_price(sig.entry, SLIPPAGE_BPS, adverse_for_buy=long)
    shift = fill - sig.entry
    stop, target = sig.stop + shift, sig.target + shift
    risk = abs(fill - stop)
    if risk <= 0:
        return False
    cash = await _cash(strat.strategy_id)
    levels = Levels(fill, stop, target, risk, abs(target - fill),
                    abs(target - fill) / risk, sig.stop_basis, sig.target_basis)
    qty = position_size(PER_STRATEGY_CAPITAL, cash, levels,
                        risk_pct=DEFAULT_RISK_PCT, lot_size=lot)
    if qty < 1:
        return False

    doc = {
        "position_id": uuid4().hex[:12], "strategy_id": strat.strategy_id,
        "strategy_name": strat.name, "family": strat.family, "sub_family": strat.sub_family,
        "timeframe": strat.timeframe, "htf": strat.htf, "style": strat.style,
        "symbol": sig.symbol, "exchange": sig.exchange, "source": source,
        "instrument": {"symbol": inst.get("symbol"), "security_id": str(inst.get("security_id")),
                       "exchange_segment": inst.get("exchange_segment"), "lot_size": lot},
        "side": sig.side, "signal_price": round(sig.entry, 4), "entry_price": round(fill, 4),
        "stoploss": round(stop, 4), "target": round(target, 4), "qty": qty,
        "risk_per_unit": round(risk, 4), "risk_amount": round(risk * qty, 2),
        "reward_amount": round(abs(target - fill) * qty, 2),
        "r_multiple": round(abs(target - fill) / risk, 3),
        "capital_deployed": round(fill * qty, 2), "capital_allocated": PER_STRATEGY_CAPITAL,
        "pattern": sig.pattern, "detail": sig.detail, "confirmations": sig.confirmations,
        "regime_primary": sig.regime_primary, "regime_tags": sig.regime_tags,
        "confidence": sig.confidence, "hypothesis": sig.hypothesis,
        "cost_model": src["cost_model"],
        "ltp": round(fill, 4), "unrealized_pnl": 0.0, "pnl_pct": 0.0,
        "realized_pnl": None, "costs": None, "exit_price": None, "exit_reason": None,
        "status": "OPEN", "bars_held": 0,
        "max_hold_bars": DEFAULT_MAX_HOLD.get(strat.timeframe, 60),
        "entry_bar_ts": sig.bar_ts, "opened_at": _now(), "updated_at": _now(), "closed_at": None,
    }
    await sf_positions_collection.insert_one(doc)
    await sf_signals_collection.insert_one({
        "signal_id": uuid4().hex[:12], "strategy_id": strat.strategy_id,
        "strategy_name": strat.name, "symbol": sig.symbol, "exchange": sig.exchange,
        "timeframe": strat.timeframe, "side": sig.side, "entry": round(fill, 4),
        "stop": round(stop, 4), "target": round(target, 4),
        "risk": round(risk * qty, 2), "reward": round(abs(target - fill) * qty, 2),
        "r_multiple": round(abs(target - fill) / risk, 3), "qty": qty,
        "pattern": sig.pattern, "confirmations": sig.confirmations,
        "regime": sig.regime_primary, "confidence": sig.confidence,
        "taken": True, "created_at": _now(),
    })
    return True


async def _manage(src: dict) -> int:
    open_positions = [p async for p in sf_positions_collection.find({"status": "OPEN"})]
    if not open_positions:
        return 0
    cache: dict[tuple[str, str], list] = {}
    updated = 0
    touched: set[str] = set()

    for pos in open_positions:
        key = (pos["symbol"], pos["timeframe"])
        if key not in cache:
            cache[key] = await src["bars"](pos["symbol"], pos["timeframe"], 5)
        bars = cache[key]
        if not bars:
            continue
        bar = bars[-1]
        long = pos["side"] == "BUY"
        qty = pos["qty"]

        hit_stop = bar.low <= pos["stoploss"] if long else bar.high >= pos["stoploss"]
        hit_target = bar.high >= pos["target"] if long else bar.low <= pos["target"]
        entry_ts = pos.get("entry_bar_ts")
        held = pos.get("bars_held", 0) + 1
        expired = held >= pos.get("max_hold_bars", 60)

        # Same pessimistic rule as the backtest: an ambiguous bar resolves to the stop.
        reason = ("stoploss" if hit_stop else "target" if hit_target
                  else "max_hold" if expired else None)
        exit_px = (pos["stoploss"] if reason == "stoploss" else
                   pos["target"] if reason == "target" else bar.close)

        gross = (bar.close - pos["entry_price"]) * qty * (1 if long else -1)
        projected = round_trip_cost(pos.get("cost_model", "commodity"),
                                    pos["entry_price"], bar.close, qty, long)
        changes = {"ltp": round(bar.close, 4), "bars_held": held,
                   "unrealized_pnl": round(gross - projected, 2),
                   "pnl_pct": round((bar.close - pos["entry_price"]) / pos["entry_price"]
                                    * 100 * (1 if long else -1), 3),
                   "updated_at": _now()}
        await sf_positions_collection.update_one({"_id": pos["_id"]}, {"$set": changes})
        updated += 1

        if reason:
            fill = slippage_price(exit_px, SLIPPAGE_BPS, adverse_for_buy=not long)
            g = (fill - pos["entry_price"]) * qty * (1 if long else -1)
            costs = round_trip_cost(pos.get("cost_model", "commodity"),
                                    pos["entry_price"], fill, qty, long)
            net = g - costs
            risk_amount = pos.get("risk_amount") or 0
            await sf_trades_collection.insert_one({
                "trade_id": uuid4().hex[:12], "strategy_id": pos["strategy_id"],
                "strategy_name": pos["strategy_name"], "family": pos.get("family"),
                "timeframe": pos.get("timeframe"), "symbol": pos["symbol"],
                "side": pos["side"], "entry_price": pos["entry_price"],
                "exit_price": round(fill, 4), "qty": qty, "gross_pnl": round(g, 2),
                "costs": round(costs, 2), "realized_pnl": round(net, 2),
                "r_realised": round(net / risk_amount, 3) if risk_amount else 0.0,
                "exit_reason": reason, "pattern": pos.get("pattern"),
                "opened_at": pos["opened_at"], "closed_at": _now()})
            await sf_positions_collection.update_one({"_id": pos["_id"]}, {"$set": {
                "status": "CLOSED", "exit_price": round(fill, 4), "exit_reason": reason,
                "gross_pnl": round(g, 2), "costs": round(costs, 2),
                "realized_pnl": round(net, 2), "unrealized_pnl": 0.0,
                "closed_at": _now(), "updated_at": _now()}})
            touched.add(pos["strategy_id"])

    for sid in touched:
        await _update_paper_score(sid)
    return updated


async def _update_paper_score(sid: str) -> None:
    closed = [p async for p in sf_positions_collection.find(
        {"strategy_id": sid, "status": {"$ne": "OPEN"}},
        {"realized_pnl": 1, "costs": 1})]
    pnls = [p.get("realized_pnl") or 0.0 for p in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gl = abs(sum(losses))
    await sf_scores_collection.update_one({"strategy_id": sid}, {"$set": {
        "paper_trades": len(pnls),
        "paper_win_rate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
        "paper_net_pnl": round(sum(pnls), 2),
        "paper_profit_factor": round(sum(wins) / gl, 3) if gl > 0 else None,
        "paper_costs": round(sum(p.get("costs") or 0.0 for p in closed), 2),
        "paper_updated_at": _now(),
    }}, upsert=True)


# --------------------------------------------------------------------------------
# Read models
# --------------------------------------------------------------------------------


async def summary() -> dict:
    deployed = realized = unrealized = costs = 0.0
    async for p in sf_positions_collection.find({"status": "OPEN"},
                                                {"capital_deployed": 1, "unrealized_pnl": 1}):
        deployed += p.get("capital_deployed", 0.0)
        unrealized += p.get("unrealized_pnl") or 0.0
    async for p in sf_positions_collection.find({"status": {"$ne": "OPEN"}},
                                                {"realized_pnl": 1, "costs": 1}):
        realized += p.get("realized_pnl") or 0.0
        costs += p.get("costs") or 0.0

    grades: dict[str, int] = {}
    async for d in sf_scores_collection.find({}, {"grade": 1}):
        g = str(d.get("grade", 0))
        grades[g] = grades.get(g, 0) + 1
    backtested = await sf_backtests_collection.count_documents({})
    state = await sf_state_collection.find_one({"_id": STATE_ID}) or {}

    return {
        "strategy_count": len(FACTORY_CATALOG),
        "family_counts": family_counts(),
        "per_strategy_capital": PER_STRATEGY_CAPITAL,
        "initial_capital": INITIAL_CAPITAL,
        "deployed_capital": round(deployed, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "total_costs": round(costs, 2),
        "equity": round(INITIAL_CAPITAL + realized + unrealized, 2),
        "open_positions": await sf_positions_collection.count_documents({"status": "OPEN"}),
        "closed_positions": await sf_positions_collection.count_documents({"status": {"$ne": "OPEN"}}),
        "backtest_rows": backtested,
        "grade_counts": grades,
        "min_grade_to_trade": MIN_GRADE_TO_TRADE,
        "require_grade": REQUIRE_GRADE,
        "paused": PAUSE_NEW_ENTRIES, "mode": "paper", "costs_charged": True,
        "slippage_bps": SLIPPAGE_BPS,
        "last_run_at": state["last_run_at"].isoformat() if state.get("last_run_at") else None,
        "last_backtest_at": state["last_backtest_at"].isoformat() if state.get("last_backtest_at") else None,
        "last_notes": state.get("last_notes", []),
        **(await breaker_state()),
    }


async def leaderboard(family: str | None = None, timeframe: str | None = None,
                      grade: int | None = None, limit: int = 600) -> list[dict]:
    scores = {d["strategy_id"]: d async for d in sf_scores_collection.find({})}
    open_counts: dict[str, int] = {}
    async for p in sf_positions_collection.find({"status": "OPEN"}, {"strategy_id": 1}):
        open_counts[p["strategy_id"]] = open_counts.get(p["strategy_id"], 0) + 1

    rows = []
    for s in FACTORY_CATALOG:
        if family and s.family != family:
            continue
        if timeframe and s.timeframe != timeframe:
            continue
        sc = scores.get(s.strategy_id) or {}
        g = sc.get("grade", 0)
        if grade is not None and g != grade:
            continue
        rows.append({
            "strategy_id": s.strategy_id, "name": s.name, "family": s.family,
            "sub_family": s.sub_family, "timeframe": s.timeframe, "htf": s.htf,
            "style": s.style, "target_r": s.target_r, "hypothesis": s.hypothesis,
            "regimes": sorted(s.regimes), "detector": s.detector,
            "grade": g, "grade_reasons": sc.get("grade_reasons", []),
            "best_symbol": sc.get("best_symbol"),
            "bt_trades": sc.get("bt_trades", 0), "bt_win_rate": sc.get("bt_win_rate", 0.0),
            "bt_profit_factor": sc.get("bt_profit_factor"),
            "bt_expectancy": sc.get("bt_expectancy", 0.0), "bt_avg_r": sc.get("bt_avg_r", 0.0),
            "bt_net_pnl": sc.get("bt_net_pnl", 0.0), "bt_max_dd_pct": sc.get("bt_max_dd_pct", 0.0),
            "bt_cagr_pct": sc.get("bt_cagr_pct"), "bt_sharpe": sc.get("bt_sharpe"),
            "oos_net_pnl": sc.get("oos_net_pnl", 0.0), "oos_trades": sc.get("oos_trades", 0),
            "paper_trades": sc.get("paper_trades", 0),
            "paper_net_pnl": sc.get("paper_net_pnl", 0.0),
            "paper_win_rate": sc.get("paper_win_rate", 0.0),
            "open_positions": open_counts.get(s.strategy_id, 0),
            "eligible": (not REQUIRE_GRADE) or g >= MIN_GRADE_TO_TRADE,
        })
    rows.sort(key=lambda r: (-r["grade"], -(r["bt_profit_factor"] or 0), -r["bt_net_pnl"]))
    return rows[:limit]


__all__ = ["run_backtests", "run_paper_cycle", "summary", "leaderboard",
           "PER_STRATEGY_CAPITAL", "INITIAL_CAPITAL", "STATE_ID", "BAR_SOURCES"]
