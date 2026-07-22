"""Out-of-sample sweep for the long-horizon factor catalog (`intraday_research_strategies`).

WHY THIS DESK EXISTS, AND WHY IT LOOKS NOTHING LIKE THE INTRADAY-LAB SWEEP
---------------------------------------------------------------------------
The Intraday Stocks desk's 50 short-hold strategies were backtested fee-honest on 5y of
NSE history and lost 16/16 — the post-mortem was ~Rs11/trade of gross edge against
~Rs132/trade of real charges. Published evidence on Indian equities says the same thing
in general: momentum profitability "disappears for shorter horizons but remains for
longer horizons... beyond 6 months", as turnover falls. This module is the response:
every strategy here holds for MONTHS, not days, so cost drag stops dominating the edge.

THE SECOND THING THAT HAD TO CHANGE: CROSS-SECTIONAL, NOT PER-SYMBOL
----------------------------------------------------------------------
A first pass measured every strategy ONE STOCK AT A TIME and found real, out-of-sample
profit factor (1.3-2.5) but 40-70% drawdowns — dominated by the Mar-2020 crash hitting one
concentrated name alone. That is not how these factors are actually deployed (NSE's own
Nifty500 Momentum 50 buys a ranked BASKET, not one name), and it is not how the drawdown
gate should be judged. Re-testing as a top-K cross-sectional basket (rank the whole
universe each rebalance, hold the top K equal-weighted) cut drawdowns roughly in half and
produced real survivors. `rebalance()` in this module implements exactly that.

METHODOLOGY, CARRIED OVER FROM THE VERIFIED RESEARCH PASS
-----------------------------------------------------------
  * Chronological train/test split (`train_fraction`), same convention as the options-
    selling sweep — a strategy must clear the gate on BOTH halves independently.
  * Drawdown is measured on a DAILY mark-to-market portfolio curve (every held name
    priced at every day's close), not stitched from non-overlapping per-symbol trades —
    that is what actually captures simultaneous multi-name exposure.
  * Two survivors holding near-identical baskets are one idea wearing two names: an
    overlap pass (Jaccard similarity of (symbol, entry_date) pairs during TEST) keeps the
    higher-PF one and records what the other duplicates — the same principle as the
    selling sweep's `overlap_groups()`.
  * `MIN_HISTORY` gates universe INCLUSION (a symbol needs ~9y of bars to enter), kept
    deliberately separate from `REBALANCE_START_IDX` (when the loop may first fire) —
    conflating the two once left almost no rebalance points at all, caught by direct
    verification against a real download before this was trusted.

DATA SOURCE HONESTY
--------------------
The research pass that found these parameters used yfinance (unadjusted OHLC) because
Mongo was unreachable in that environment. THIS module reads the app's own `bars`
collection via `load_bars` — the same Dhan-backfilled daily bars every other desk in this
app uses. That means the first real sweep run here may report different numbers than the
research pass (different date range, different corporate-action/adjustment handling) even
though the replay logic itself is unchanged and was verified. Re-run the sweep against
this app's own data before trusting a specific number; trust the METHOD, verify the DATA.
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.services.intraday_research_strategies import (
    RESEARCH_CATALOG, PORTFOLIO_SCORE_FUNCS, relative_strength_score,
)
from backtesting_service.costs import DELIVERY, CostModel

logger = logging.getLogger("long_horizon_backtest")

PORTFOLIO_FAMILIES = set(PORTFOLIO_SCORE_FUNCS) | {"relative_strength"}

# Own paper pool for this desk, mirroring the option desks' "never share a capital pool"
# rule (see db_selling.py) — a long-horizon desk's track record must never be diluted by,
# or blamed on, the intraday desk's.
LONG_HORIZON_INITIAL_CAPITAL = 10_000_000.0  # Rs 1 crore
LONG_HORIZON_ALLOCATION_PER_STRATEGY = LONG_HORIZON_INITIAL_CAPITAL / max(len(RESEARCH_CATALOG), 1)

DEFAULT_TOP_K = 10
DEFAULT_TRAIN_FRACTION = 0.70
DEFAULT_SLIPPAGE_BPS = 5.0
MIN_HISTORY_BARS = 2300  # ~9y of daily bars — see module docstring on why this is NOT the rebalance start index
REBALANCE_START_IDX = 300
BENCHMARK_SYMBOL = "NIFTY"

DEFAULT_GATE = {"min_trades": 8, "min_profit_factor": 1.3, "min_expectancy": 0.0, "max_drawdown_pct": 30.0}
DEFAULT_OVERLAP_THRESHOLD = 0.6


def qualify_long_horizon(metrics: dict, gate: dict | None = None) -> dict:
    """Same shape and philosophy as `intraday_backtest.qualify_intraday`: reasons, not a
    bare boolean — a qualification a reader cannot audit is not a qualification."""
    g = {**DEFAULT_GATE, **(gate or {})}
    reasons: list[str] = []
    trades = metrics.get("trades") or 0
    pf = metrics.get("profit_factor")
    expectancy = metrics.get("expectancy")
    max_dd = metrics.get("max_drawdown_pct")

    if trades < g["min_trades"]:
        reasons.append(f"only {trades} trades (need {g['min_trades']})")
    if pf is None:
        reasons.append("no profit factor (no losing trades yet — unproven, not perfect)")
    elif pf < g["min_profit_factor"]:
        reasons.append(f"profit factor {pf:.2f} below {g['min_profit_factor']}")
    if expectancy is None or expectancy <= g["min_expectancy"]:
        reasons.append(f"expectancy Rs{(expectancy or 0):,.0f}/trade is not above Rs{g['min_expectancy']:,.0f}")
    if max_dd is not None and max_dd > g["max_drawdown_pct"]:
        reasons.append(f"max drawdown {max_dd:.1f}% above {g['max_drawdown_pct']}%")
    return {"qualified": not reasons, "reasons": reasons}


def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0, "profit_factor": None, "expectancy": None, "net_pnl": 0.0,
                "max_drawdown_pct": None, "win_rate": None}
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    gross_win = sum(t["net_pnl"] for t in wins)
    gross_loss = -sum(t["net_pnl"] for t in losses)
    net = sum(t["net_pnl"] for t in trades)
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 4),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "expectancy": round(net / len(trades), 2),
        "net_pnl": round(net, 2),
    }


def _drawdown_pct(daily_equity: list[tuple], window: tuple) -> float | None:
    start, end = window
    curve = [e for d, e in daily_equity if start <= d < end]
    if not curve:
        return None
    peak = curve[0]
    max_dd = 0.0
    for e in curve:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)
    return round(max_dd * 100, 3)


def _common_dates(bars_by_symbol: dict[str, list]) -> list:
    date_sets = [set(b.ts.date() for b in bars) for bars in bars_by_symbol.values()]
    return sorted(set.intersection(*date_sets)) if date_sets else []


def _replay_one(spec, bars_by_symbol: dict[str, list], dates: list, cost_model: CostModel,
                bench_close_by_date: dict, top_k: int, slippage_bps: float) -> tuple[list, list]:
    """One cross-sectional top-K walk for a single strategy spec. Returns
    (trades, daily_equity[(date, mtm)]) — see module docstring for why drawdown is
    measured off the daily curve rather than the trade list."""
    idx_by_symbol = {s: {d: i for i, d in enumerate(bd.ts.date() for bd in bars)}
                     for s, bars in bars_by_symbol.items()}
    close_by_symbol = {s: {b.ts.date(): b.close for b in bars} for s, bars in bars_by_symbol.items()}
    score_fn = PORTFOLIO_SCORE_FUNCS.get(spec.family)
    rebalance_days = spec.max_hold_days or 63
    slip = slippage_bps / 10000.0

    trades: list[dict] = []
    daily_equity: list[tuple] = []
    held: dict[str, dict] = {}
    cash = LONG_HORIZON_ALLOCATION_PER_STRATEGY

    i = REBALANCE_START_IDX
    next_rebalance = i
    while i < len(dates):
        today = dates[i]
        if i >= next_rebalance:
            for sym, pos in list(held.items()):
                px = close_by_symbol[sym].get(today)
                if px is None:
                    continue
                fill = px * (1 - slip)
                gross = (fill - pos["entry_price"]) * pos["qty"]
                costs = (cost_model.order_charges(DELIVERY, pos["entry_price"], pos["qty"], True)
                        + cost_model.order_charges(DELIVERY, fill, pos["qty"], False))
                net = gross - costs
                cash += pos["entry_price"] * pos["qty"] + net
                trades.append({"symbol": sym, "entry_date": pos["entry_date"],
                               "exit_date": today.isoformat(), "net_pnl": net, "costs": costs,
                               "hold_days": i - pos["entry_idx"]})
                del held[sym]

            scored = []
            for sym, bars in bars_by_symbol.items():
                pos_idx = idx_by_symbol[sym].get(today)
                if pos_idx is None or pos_idx < 60:
                    continue
                window = bars[: pos_idx + 1]
                if spec.family == "relative_strength":
                    tail_n = max(spec.params["lookback"] + spec.params["skip"] + 2, spec.params["ma_period"] + 5)
                    tail = window[-tail_n:]
                    bench_tail = [bench_close_by_date.get(b.ts.date()) for b in tail]
                    if any(v is None for v in bench_tail):
                        continue
                    score = relative_strength_score(tail, spec.params, bench_tail)
                elif score_fn is not None:
                    score = score_fn(window, spec.params)
                else:
                    score = None
                if score is not None:
                    scored.append((score, sym))
            scored.sort(reverse=True)
            picks = [sym for _, sym in scored[:top_k]]

            if picks:
                budget_each = cash / len(picks)
                for sym in picks:
                    px = close_by_symbol[sym].get(today)
                    if px is None or px <= 0:
                        continue
                    entry = px * (1 + slip)
                    qty = int(budget_each // entry)
                    if qty < 1:
                        continue
                    cash -= entry * qty
                    held[sym] = {"qty": qty, "entry_price": entry, "entry_idx": i,
                                "entry_date": today.isoformat()}
            next_rebalance = i + rebalance_days

        mtm = cash
        for sym, pos in held.items():
            px = close_by_symbol[sym].get(today)
            if px is not None:
                mtm += px * pos["qty"]
        daily_equity.append((today, mtm))
        i += 1

    return trades, daily_equity


async def _universe() -> tuple[dict[str, list], dict]:
    """This app's own equity bars — the universe is exactly what has been backfilled,
    never invented (same rule `_scored_daily_symbols` in call_engine.py follows)."""
    from app.core.db import bars_collection
    from anyio import to_thread
    from backtesting_service.service import load_bars
    from tradingai_shared.domain import Timeframe

    symbols = await bars_collection.distinct("symbol", {"timeframe": "1d"})
    symbols = [s for s in symbols if s != BENCHMARK_SYMBOL]

    def _load_all():
        out = {}
        for sym in symbols:
            try:
                bars = load_bars(sym, Timeframe.D1, 10.0)
            except Exception:
                continue
            if len(bars) >= MIN_HISTORY_BARS:
                out[sym] = bars
        return out

    bars_by_symbol = await to_thread.run_sync(_load_all)
    bench_bars = await to_thread.run_sync(lambda: load_bars(BENCHMARK_SYMBOL, Timeframe.D1, 10.0))
    bench_close_by_date = {b.ts.date(): b.close for b in bench_bars}
    return bars_by_symbol, bench_close_by_date


async def run_long_horizon_sweep(
    top_k: int = DEFAULT_TOP_K,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    gate: dict | None = None,
    overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
    persist: bool = True,
) -> dict:
    bars_by_symbol, bench_close_by_date = await _universe()
    if not bars_by_symbol:
        return {"error": "No symbols with >=9y of local daily bars — backfill more history first.",
                "results": [], "strategy_count": 0, "basket_count": 0, "symbols": 0}

    dates = _common_dates(bars_by_symbol)
    cut_idx = int(len(dates) * train_fraction)
    cut_date = dates[cut_idx] if dates else None
    effective_gate = {**DEFAULT_GATE, **(gate or {})}
    cost_model = CostModel()

    def _run_all():
        rows = []
        for spec in RESEARCH_CATALOG:
            if spec.family not in PORTFOLIO_FAMILIES:
                continue
            trades, daily_eq = _replay_one(spec, bars_by_symbol, dates, cost_model,
                                           bench_close_by_date, top_k, slippage_bps)
            train_t = [t for t in trades if t["entry_date"] < cut_date.isoformat()]
            test_t = [t for t in trades if t["entry_date"] >= cut_date.isoformat()]
            train_m = _metrics(train_t)
            test_m = _metrics(test_t)
            train_m["max_drawdown_pct"] = _drawdown_pct(daily_eq, (dates[0], cut_date))
            test_m["max_drawdown_pct"] = _drawdown_pct(daily_eq, (cut_date, dates[-1]))
            train_v = qualify_long_horizon(train_m, effective_gate)
            test_v = qualify_long_horizon(test_m, effective_gate)
            test_holdings = frozenset((t["symbol"], t["entry_date"]) for t in test_t)
            rows.append({
                "strategy_id": spec.strategy_id, "name": spec.name, "category": spec.category,
                "family": spec.family, "max_hold_days": spec.max_hold_days,
                "train_metrics": train_m, "test_metrics": test_m,
                "qualified": train_v["qualified"], "gate_failures": train_v["reasons"],
                "test_qualified": test_v["qualified"], "test_failures": test_v["reasons"],
                "_test_holdings": test_holdings,
            })
        return rows

    from anyio import to_thread
    results = await to_thread.run_sync(_run_all)

    # --- overlap de-dup: keep the higher test-PF of any pair sharing >= threshold of its
    # TEST-period (symbol, entry_date) holdings; the same principle as the selling sweep's
    # overlap_groups(), applied to baskets instead of option entry-days.
    survivors = [r for r in results if r["qualified"] and r["test_qualified"]]
    survivors.sort(key=lambda r: r["test_metrics"]["profit_factor"] or 0, reverse=True)
    kept: list = []
    for r in survivors:
        dup_of = None
        for k in kept:
            a, b = r["_test_holdings"], k["_test_holdings"]
            if a and b and len(a & b) / len(a | b) >= overlap_threshold:
                dup_of = k["strategy_id"]
                break
        if dup_of:
            r["duplicate_of"] = dup_of
        else:
            kept.append(r)
    kept_ids = {r["strategy_id"] for r in kept}
    for r in results:
        r["independent"] = r["strategy_id"] in kept_ids
        r["in_basket"] = bool(r["qualified"] and r["test_qualified"] and r["independent"])
        r.pop("_test_holdings", None)

    results.sort(key=lambda r: (r["in_basket"], r["qualified"],
                                r["test_metrics"]["profit_factor"] or 0), reverse=True)

    doc = {
        "sweep_id": uuid4().hex[:12],
        "created_at": datetime.now(timezone.utc),
        "desk": "long_horizon",
        "top_k": top_k,
        "universe_size": len(bars_by_symbol),
        "train_fraction": train_fraction,
        "overlap_threshold": overlap_threshold,
        "gate": effective_gate,
        "data_from": dates[0].isoformat() if dates else None,
        "data_to": dates[-1].isoformat() if dates else None,
        "cost_model": "NSE rate card (CostModel, delivery rates)",
        "data_source": "app bars collection (load_bars) — Dhan-backfilled daily bars",
        "strategy_count": len(results),
        "qualified_count": sum(1 for r in results if r["qualified"]),
        "robust_count": sum(1 for r in results if r["qualified"] and r["test_qualified"]),
        "basket_count": sum(1 for r in results if r["in_basket"]),
        "results": results,
    }
    if persist:
        from app.core.db import long_horizon_sweeps_collection

        await long_horizon_sweeps_collection.insert_one(dict(doc))
    doc.pop("_id", None)
    doc["created_at"] = doc["created_at"].isoformat()
    return doc
