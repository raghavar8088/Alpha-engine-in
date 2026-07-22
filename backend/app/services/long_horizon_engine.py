"""Long-Horizon factor desk — paper engine.

Trades the qualified basket from `long_horizon_backtest.run_long_horizon_sweep()`: for
each strategy that passed BOTH the train and test gate and survived the overlap de-dup,
rank the current equity universe by that strategy's own score function and hold the
top-K names equal-weighted, rebalancing on that strategy's own holding-period cadence
(3, 6 or 12 months). This is a cross-sectional / basket desk, not a per-symbol one — see
`long_horizon_backtest.py`'s module docstring for why that distinction is the whole point.

WHY THIS ENGINE IS SIMPLER THAN THE INTRADAY-LAB / SELLING-DESK ENGINES
------------------------------------------------------------------------
Those desks price open risk on every tick because an option or an intraday position can
move enough in minutes to matter. A rebalance that fires once a quarter does not have
that problem: real momentum funds transact at a rebalance date's CLOSE, not a mid-session
tick, so this engine only ever needs the latest daily bar — no live broker feed, no Angel/
Dhan failover. `rebalance()` is meant to be called once per trading day; on days nothing
is due it is a no-op.

CADENCE UNIT: TRADING-DAY INVOCATIONS, NOT CALENDAR DAYS
------------------------------------------------------------
The backtest counts a strategy's `max_hold_days` in TRADING days (bar count). This engine
tracks the same unit by incrementing a per-strategy counter once per call, and calling it
is expected to happen once per trading day (see the scheduler in main.py) — so the
cadence matches the backtest's semantics rather than calendar months, which would drift
against weekends/holidays.

Paper only — no real orders. Own capital pool (LONG_HORIZON_INITIAL_CAPITAL), separate
from every other desk's, for the same reason the option desks never share one (a bad
quarter here must never be blamed on, or hidden by, another desk's book).
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from anyio import to_thread

from app.core.db import (
    long_horizon_equity_collection,
    long_horizon_positions_collection,
    long_horizon_scores_collection,
    long_horizon_state_collection,
    long_horizon_sweeps_collection,
    long_horizon_trades_collection,
)
from app.services.intraday_research_strategies import (
    RESEARCH_BY_ID, PORTFOLIO_SCORE_FUNCS, relative_strength_score,
)
from app.services.long_horizon_backtest import (
    BENCHMARK_SYMBOL, DEFAULT_TOP_K, LONG_HORIZON_ALLOCATION_PER_STRATEGY,
    LONG_HORIZON_INITIAL_CAPITAL,
)
from backtesting_service.costs import DELIVERY, CostModel
from backtesting_service.service import load_bars
from tradingai_shared.domain import Timeframe

logger = logging.getLogger("long_horizon_engine")

SLIPPAGE_BPS = 5.0


def _now():
    return datetime.now(timezone.utc)


async def load_qualified_basket() -> list[dict]:
    """The qualified basket from the latest sweep — same "absence of a verdict is
    absence of approval" rule the selling desk's `load_qualified_basket` follows: a
    strategy trades only if the sweep marked it `in_basket`."""
    doc = await long_horizon_sweeps_collection.find_one({}, sort=[("created_at", -1)])
    if doc is None:
        return []
    out = []
    for entry in doc.get("results", []):
        if not entry.get("in_basket"):
            continue
        spec = RESEARCH_BY_ID.get(entry["strategy_id"])
        if spec is None:
            continue
        out.append({"spec": spec, "sweep_id": doc.get("sweep_id")})
    return out


async def _universe_bars() -> dict[str, list]:
    from app.core.db import bars_collection

    symbols = await bars_collection.distinct("symbol", {"timeframe": "1d"})
    symbols = [s for s in symbols if s != BENCHMARK_SYMBOL]

    def _load():
        out = {}
        for sym in symbols:
            try:
                bars = load_bars(sym, Timeframe.D1, 2.0)  # 2y is plenty for any lookback used to SCORE
            except Exception:
                continue
            if len(bars) > 260:
                out[sym] = bars
        return out

    return await to_thread.run_sync(_load)


async def _score_universe(spec, bars_by_symbol: dict[str, list], bench_bars: list) -> list[tuple[float, str]]:
    bench_by_date = {b.ts.date(): b.close for b in bench_bars}
    score_fn = PORTFOLIO_SCORE_FUNCS.get(spec.family)
    scored = []
    for sym, bars in bars_by_symbol.items():
        if spec.family == "relative_strength":
            tail_n = max(spec.params["lookback"] + spec.params["skip"] + 2, spec.params["ma_period"] + 5)
            tail = bars[-tail_n:]
            bench_tail = [bench_by_date.get(b.ts.date()) for b in tail]
            if any(v is None for v in bench_tail):
                continue
            score = relative_strength_score(tail, spec.params, bench_tail)
        elif score_fn is not None:
            score = score_fn(bars, spec.params)
        else:
            score = None
        if score is not None:
            scored.append((score, sym))
    scored.sort(reverse=True)
    return scored


async def _close_position(pos: dict, price: float, reason: str, cost_model: CostModel) -> float:
    fill = price * (1 - SLIPPAGE_BPS / 10000.0)
    gross = (fill - pos["entry_price"]) * pos["qty"]
    costs = (cost_model.order_charges(DELIVERY, pos["entry_price"], pos["qty"], True)
            + cost_model.order_charges(DELIVERY, fill, pos["qty"], False))
    net = gross - costs
    await long_horizon_trades_collection.insert_one({
        "trade_id": uuid4().hex[:12], "strategy_id": pos["strategy_id"],
        "strategy_name": pos["strategy_name"], "symbol": pos["symbol"],
        "entry_price": pos["entry_price"], "exit_price": round(fill, 2), "qty": pos["qty"],
        "net_pnl": round(net, 2), "costs": round(costs, 2), "exit_reason": reason,
        "opened_at": pos["opened_at"], "closed_at": _now(),
    })
    await long_horizon_positions_collection.delete_one({"_id": pos["_id"]})
    return net


async def _update_score(strategy_id: str, strategy_name: str, category: str) -> None:
    closed = [t async for t in long_horizon_trades_collection.find(
        {"strategy_id": strategy_id}, {"net_pnl": 1})]
    trades = len(closed)
    wins = sum(1 for t in closed if (t.get("net_pnl") or 0) > 0)
    net_pnl = sum(t.get("net_pnl") or 0 for t in closed)
    await long_horizon_scores_collection.update_one(
        {"strategy_id": strategy_id},
        {"$set": {"strategy_id": strategy_id, "name": strategy_name, "category": category,
                  "trades": trades, "wins": wins,
                  "win_rate": round(wins / trades, 4) if trades else 0.0,
                  "net_pnl": round(net_pnl, 2),
                  "allocated_capital": round(LONG_HORIZON_ALLOCATION_PER_STRATEGY + net_pnl, 2),
                  "updated_at": _now()}},
        upsert=True,
    )


async def rebalance() -> dict:
    """One pass over the qualified basket: close out any strategy whose holding period
    has elapsed, re-rank, re-enter. A no-op for strategies not yet due. Meant to be
    called once per trading day (see `long_horizon_scheduler.py`)."""
    basket = await load_qualified_basket()
    if not basket:
        await long_horizon_state_collection.update_one(
            {"_id": "long_horizon"},
            {"$set": {"heartbeat": _now(), "basket_size": 0,
                      "note": "no qualified basket — run the sweep first"}},
            upsert=True,
        )
        return {"basket_size": 0, "rebalanced": 0, "note": "no qualified basket"}

    bars_by_symbol = await _universe_bars()
    bench_bars = await to_thread.run_sync(lambda: load_bars(BENCHMARK_SYMBOL, Timeframe.D1, 2.0))
    cost_model = CostModel()
    rebalanced = 0

    for entry in basket:
        spec = entry["spec"]
        state = await long_horizon_state_collection.find_one({"_id": f"strategy:{spec.strategy_id}"}) or {}
        bars_elapsed = state.get("bars_since_rebalance", 0) + 1
        due = bars_elapsed >= spec.max_hold_days or not state.get("initialized")

        if not due:
            await long_horizon_state_collection.update_one(
                {"_id": f"strategy:{spec.strategy_id}"},
                {"$set": {"bars_since_rebalance": bars_elapsed}}, upsert=True,
            )
            continue

        # --- close out whatever this strategy currently holds ---
        open_positions = [p async for p in long_horizon_positions_collection.find(
            {"strategy_id": spec.strategy_id})]
        cash = LONG_HORIZON_ALLOCATION_PER_STRATEGY
        realized_this_cycle = 0.0
        for pos in open_positions:
            bars = bars_by_symbol.get(pos["symbol"])
            price = bars[-1].close if bars else pos["entry_price"]  # honest fallback, never fabricated beyond last mark
            net = await _close_position(pos, price, "rebalance", cost_model)
            realized_this_cycle += net
            cash += pos["entry_price"] * pos["qty"] + net

        # cash carries forward: original allocation + everything realized by this
        # strategy across its history (never blended with another strategy's book)
        past_realized = 0.0
        async for t in long_horizon_trades_collection.find({"strategy_id": spec.strategy_id}, {"net_pnl": 1}):
            past_realized += t.get("net_pnl") or 0.0
        cash = LONG_HORIZON_ALLOCATION_PER_STRATEGY + past_realized

        # --- rank the universe, pick the new top-K ---
        scored = await _score_universe(spec, bars_by_symbol, bench_bars)
        picks = [sym for _, sym in scored[:DEFAULT_TOP_K]]
        opened = 0
        if picks and cash > 0:
            budget_each = cash / len(picks)
            for sym in picks:
                bars = bars_by_symbol.get(sym)
                if not bars:
                    continue
                entry_px = bars[-1].close * (1 + SLIPPAGE_BPS / 10000.0)
                qty = int(budget_each // entry_px) if entry_px > 0 else 0
                if qty < 1:
                    continue
                await long_horizon_positions_collection.insert_one({
                    "strategy_id": spec.strategy_id, "strategy_name": spec.name,
                    "category": spec.category, "symbol": sym,
                    "entry_price": round(entry_px, 2), "qty": qty,
                    "ltp": round(entry_px, 2), "unrealized_pnl": 0.0,
                    "opened_at": _now(), "max_hold_days": spec.max_hold_days,
                    "rationale": f"top-{DEFAULT_TOP_K} pick, family={spec.family}",
                })
                opened += 1

        await _update_score(spec.strategy_id, spec.name, spec.category)
        await long_horizon_state_collection.update_one(
            {"_id": f"strategy:{spec.strategy_id}"},
            {"$set": {"bars_since_rebalance": 0, "initialized": True,
                      "last_rebalance_at": _now(), "last_opened": opened,
                      "last_closed": len(open_positions)}},
            upsert=True,
        )
        rebalanced += 1

    await snapshot_equity()
    await long_horizon_state_collection.update_one(
        {"_id": "long_horizon"},
        {"$set": {"heartbeat": _now(), "basket_size": len(basket), "rebalanced_this_pass": rebalanced}},
        upsert=True,
    )
    return {"basket_size": len(basket), "rebalanced": rebalanced}


async def mark_open_positions() -> None:
    """Refresh `ltp`/`unrealized_pnl` on every open position from the latest bar close —
    for display only; exits happen at `rebalance()`, not here (there is no target/stop on
    a factor position, its exit IS the next rebalance)."""
    positions = [p async for p in long_horizon_positions_collection.find({})]
    if not positions:
        return
    bars_by_symbol = await _universe_bars()
    for pos in positions:
        bars = bars_by_symbol.get(pos["symbol"])
        if not bars:
            continue
        ltp = bars[-1].close
        unrealized = (ltp - pos["entry_price"]) * pos["qty"]
        await long_horizon_positions_collection.update_one(
            {"_id": pos["_id"]},
            {"$set": {"ltp": round(ltp, 2), "unrealized_pnl": round(unrealized, 2)}},
        )


async def balance() -> dict:
    realized = 0.0
    async for t in long_horizon_trades_collection.find({}, {"net_pnl": 1}):
        realized += t.get("net_pnl") or 0.0
    unrealized = 0.0
    deployed = 0.0
    async for p in long_horizon_positions_collection.find({}, {"unrealized_pnl": 1, "entry_price": 1, "qty": 1}):
        unrealized += p.get("unrealized_pnl") or 0.0
        deployed += (p.get("entry_price") or 0.0) * (p.get("qty") or 0)
    equity = LONG_HORIZON_INITIAL_CAPITAL + realized + unrealized
    return {
        "initial_capital": LONG_HORIZON_INITIAL_CAPITAL, "realized": round(realized, 2),
        "unrealized": round(unrealized, 2), "equity": round(equity, 2),
        "deployed": round(deployed, 2),
    }


async def snapshot_equity() -> None:
    await mark_open_positions()
    bal = await balance()
    open_count = await long_horizon_positions_collection.count_documents({})
    await long_horizon_equity_collection.insert_one({
        "ts": _now(), "equity": bal["equity"], "realized": bal["realized"],
        "unrealized": bal["unrealized"], "deployed": bal["deployed"], "open_positions": open_count,
    })
