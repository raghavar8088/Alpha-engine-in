"""Fee-honest daily-bar backtest for the Intraday Stocks strategy catalog.

WHAT THIS CAN AND CANNOT MEASURE, AND WHY
-----------------------------------------
The 50 strategies in `intraday_strategies.py` split cleanly in two by what they read:

  * 34 of them (ORB, VWAP-reversion scalp, tick-momentum, gap-go, PDH breakout, volume
    surge, VWAP fade) need INTRADAY DAY-STATE — the day's open/high/low so far and
    volume so far — which they get live from `ctx["quote"]`. No equity intraday history
    is backfilled anywhere in this app (`market-data-service/collector/poller.py` gives
    equities `1d` only; 5m/15m backfill is NIFTY-only), so there is nothing to replay
    them against. They are reported as `not_backtestable` with that reason rather than
    as 34 strategies that "made no trades" — a zero-trade row and an unmeasurable
    strategy look identical on a leaderboard, and conflating them is how a desk talks
    itself into trusting an untested strategy.
  * 16 of them (RSI(2) extreme, Bollinger snap-back, and all 10 swing strategies) read
    only `ctx["bars"]`, so daily bars measure them honestly. Those are what this scores.

The strategies are driven through `evaluate()` UNCHANGED — the same function the live
desk calls — with `quote=None`. Nothing here re-implements a strategy, so a strategy
that scores well here is the same code that would trade.

MODELLING CHOICES, ALL PESSIMISTIC OR DECLARED
----------------------------------------------
  * Entry at the signal bar's close, the same bar the live engine would have acted on.
  * Exit scans forward: stop if `low <= stoploss`, target if `high >= target`. When a
    single daily bar contains BOTH, the STOP is assumed to have hit first. A daily bar
    cannot say which came first, and assuming the target would manufacture edge.
  * `max_hold_days == 0` strategies (RSI(2), Bollinger) square off intra-session live,
    which a daily bar cannot represent. They are held one day and exited at the next
    close if untouched — an approximation, and labelled as one in the result.
  * Costs use the real NSE rate card via `CostModel`: intraday rates for the same-day
    strategies, delivery rates for multi-day swings, plus slippage on both fills.
  * Sizing mirrors the live desk: `PER_STRATEGY_ALLOCATION * spec.risk_pct`, whole
    shares, one open position per (strategy, symbol).

PERFORMANCE
-----------
The family functions recompute their indicators from `ctx["bars"]` on every call, which
is free live (once per cycle) and quadratic in a replay. Bars are therefore fed as a
bounded trailing window (`WINDOW_BARS`) rather than the whole history — deep enough for
the longest lookback in the catalog (EMA200) that the seeding difference is immaterial.
"""

import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

from app.services.intraday_strategies import STRATEGY_CATALOG, evaluate
from backtesting_service.costs import DELIVERY, INTRADAY, CostModel
from strategy_service.indicators import atr

# Everything the REPLAY path touches is imported above and is pure — no Mongo, no broker,
# no FastAPI. The database/bar-loading imports are deliberately deferred into the two
# functions that do I/O, so the scoring logic can be exercised directly against a set of
# bars (a fixture, another data source, a notebook) without standing up the stack. A
# backtester you cannot run without production infrastructure is a backtester nobody runs.

logger = logging.getLogger("intraday_backtest")

# Mirrors intraday_lab_engine's pool split. Recomputed here from the same env var and the
# same catalog rather than imported, so this module stays free of the engine's DB imports;
# both derive from one formula, so they cannot drift without that formula changing.
INITIAL_CAPITAL = float(os.getenv("INTRADAY_LAB_INITIAL_CAPITAL", "10000000"))
PER_STRATEGY_ALLOCATION = INITIAL_CAPITAL / max(len(STRATEGY_CATALOG), 1)

# Families that read ctx["quote"] (intraday day-state) and so cannot be replayed on
# daily bars. Derived from the `_quote_ohlc` calls in intraday_strategies.py.
QUOTE_DEPENDENT_FAMILIES = {
    "orb", "vwap_reversion_scalp", "tick_momentum_scalp",
    "gap_go", "pdh_breakout", "volume_surge", "vwap_fade",
}

# Trailing window fed to each evaluate() call. The deepest lookback in the catalog is
# RSI(2)-extreme's EMA200 trend filter (needs 201+ bars); 400 keeps the EMA seed effect
# negligible while bounding the replay's cost per bar.
WINDOW_BARS = 400
ATR_PERIOD = 14

DEFAULT_GATE = {
    "min_trades": 30,
    "min_profit_factor": 1.2,
    "min_expectancy": 0.0,
    "max_drawdown_pct": 25.0,
}

DEFAULT_SLIPPAGE_BPS = 5.0  # each side, applied against us


def _daily_capable(spec) -> bool:
    return spec.family not in QUOTE_DEPENDENT_FAMILIES


def qualify_intraday(metrics: dict, gate: dict | None = None) -> dict:
    """Judge one strategy's backtest against the gate.

    Returns {"qualified", "reasons"} where `reasons` names every rule it FAILED in plain
    language — the same convention as the options sweep's `qualify()`: a qualification a
    reader cannot audit is not a qualification.
    """
    g = {**DEFAULT_GATE, **(gate or {})}
    reasons: list[str] = []

    trades = metrics.get("trades") or 0
    pf = metrics.get("profit_factor")
    expectancy = metrics.get("expectancy")
    max_dd = metrics.get("max_drawdown_pct")

    if trades < g["min_trades"]:
        reasons.append(f"only {trades} trades (need {g['min_trades']})")
    if pf is None:
        # No losing trade at all is almost always a tiny sample, not an edge that cannot
        # lose. Treat it as unproven rather than perfect.
        reasons.append("no profit factor (no losing trades yet — unproven, not perfect)")
    elif pf < g["min_profit_factor"]:
        reasons.append(f"profit factor {pf:.2f} below {g['min_profit_factor']}")
    if expectancy is None or expectancy <= g["min_expectancy"]:
        reasons.append(
            f"expectancy Rs{(expectancy or 0):,.0f}/trade is not above "
            f"Rs{g['min_expectancy']:,.0f}"
        )
    if max_dd is not None and max_dd > g["max_drawdown_pct"]:
        reasons.append(f"max drawdown {max_dd:.1f}% above {g['max_drawdown_pct']}%")

    return {"qualified": not reasons, "reasons": reasons}


def _metrics_from_trades(trades: list[dict]) -> dict:
    """Per-strategy scorecard from its closed trades. All P&L is NET of costs."""
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0, "win_rate": None, "net_pnl": 0.0,
            "gross_win": 0.0, "gross_loss": 0.0, "profit_factor": None,
            "expectancy": None, "max_drawdown_pct": None,
            "max_drawdown_pct_of_allocation": None, "avg_hold_days": None,
            "best_trade": None, "worst_trade": None, "total_costs": 0.0,
        }
    ordered = sorted(trades, key=lambda t: t["exit_date"])
    wins = [t for t in ordered if t["net_pnl"] > 0]
    losses = [t for t in ordered if t["net_pnl"] <= 0]
    gross_win = sum(t["net_pnl"] for t in wins)
    gross_loss = -sum(t["net_pnl"] for t in losses)
    net = sum(t["net_pnl"] for t in ordered)

    # Drawdown on the strategy's own cumulative P&L curve, walked from a base of the
    # capital it is allocated (not from zero) so a strategy still comfortably in profit
    # cannot report a swing below its own starting line as a drawdown past 100%.
    #
    # It is measured two ways, because they answer different questions and conflating
    # them once produced a wrong verdict here: a long-hold momentum strategy sitting on
    # +Rs300k that gave back Rs94k was gated as "47% drawdown" against the ORIGINAL
    # allocation, when the peak it actually fell from was allocation+300k — it was never
    # worse than +Rs200k. That is not how any real tearsheet reports drawdown.
    #   * pct_of_peak    — the STANDARD definition (Calmar-style): the swing as a % of
    #     the highest equity actually reached. This is what the gate uses.
    #   * pct_of_allocation — the swing as a % of the ORIGINAL fixed allocation only,
    #     kept for anyone who wants the more conservative "could this wipe out the
    #     capital it started with" reading.
    peak = PER_STRATEGY_ALLOCATION
    equity = PER_STRATEGY_ALLOCATION
    max_dd = 0.0
    max_dd_vs_peak = 0.0
    for t in ordered:
        equity += t["net_pnl"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if peak > 0:
            max_dd_vs_peak = max(max_dd_vs_peak, (peak - equity) / peak)

    return {
        "trades": len(ordered),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(ordered), 4),
        "net_pnl": round(net, 2),
        "gross_win": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "expectancy": round(net / len(ordered), 2),
        "max_drawdown_pct": round(max_dd_vs_peak * 100, 3),
        "max_drawdown_pct_of_allocation": round(max_dd / PER_STRATEGY_ALLOCATION * 100, 3),
        "avg_hold_days": round(sum(t["hold_days"] for t in ordered) / len(ordered), 2),
        "best_trade": round(max(t["net_pnl"] for t in ordered), 2),
        "worst_trade": round(min(t["net_pnl"] for t in ordered), 2),
        "total_costs": round(sum(t["costs"] for t in ordered), 2),
    }


def _replay_symbol(spec, symbol: str, bars: list, cost_model: CostModel,
                   slippage_bps: float) -> list[dict]:
    """Replay one strategy over one symbol's daily bars. Returns closed trades."""
    trades: list[dict] = []
    # max_hold_days == 0 means "square off the same session" live; on daily bars the
    # tightest honest equivalent is a one-day hold.
    max_hold = spec.max_hold_days or 1
    product = INTRADAY if spec.max_hold_days == 0 else DELIVERY
    budget = PER_STRATEGY_ALLOCATION * spec.risk_pct
    slip = slippage_bps / 10000.0

    atr_series = atr(bars, ATR_PERIOD)
    i = WINDOW_BARS if len(bars) > WINDOW_BARS else ATR_PERIOD + 2

    while i < len(bars):
        atr14 = atr_series[i] if i < len(atr_series) else 0.0
        if not atr14 or atr14 <= 0:
            i += 1
            continue
        window = bars[max(0, i - WINDOW_BARS + 1): i + 1]
        if len(window) < 3:
            i += 1
            continue
        ctx = {"bars": window, "atr14": atr14, "quote": None, "prev_bar": window[-2]}
        signal = evaluate(spec, symbol, ctx)
        if signal is None:
            i += 1
            continue

        entry = signal.entry * (1 + slip)  # pay up on entry
        qty = int(min(budget, PER_STRATEGY_ALLOCATION) // entry) if entry > 0 else 0
        if qty < 1:
            i += 1
            continue

        # --- walk forward to the exit ---------------------------------------
        exit_price = exit_reason = None
        exit_idx = min(i + max_hold, len(bars) - 1)
        for j in range(i + 1, min(i + max_hold + 1, len(bars))):
            bar = bars[j]
            if bar.low <= signal.stoploss:
                # Both touched inside one daily bar => assume the stop first. A daily
                # bar cannot order intrabar events, and assuming the target invents edge.
                exit_price, exit_reason, exit_idx = signal.stoploss, "stoploss", j
                break
            if bar.high >= signal.target:
                exit_price, exit_reason, exit_idx = signal.target, "target", j
                break
        if exit_price is None:
            if i + 1 >= len(bars):
                break  # signal on the last bar — no forward data to exit against
            exit_price, exit_reason = bars[exit_idx].close, "max_hold"

        fill = exit_price * (1 - slip)  # and give up slippage on the way out
        gross = (fill - entry) * qty
        costs = (cost_model.order_charges(product, entry, qty, is_buy=True)
                 + cost_model.order_charges(product, fill, qty, is_buy=False))
        trades.append({
            "symbol": symbol,
            "entry_date": bars[i].ts.date().isoformat(),
            "exit_date": bars[exit_idx].ts.date().isoformat(),
            "entry_price": round(entry, 2),
            "exit_price": round(fill, 2),
            "qty": qty,
            "gross_pnl": round(gross, 2),
            "costs": round(costs, 2),
            "net_pnl": round(gross - costs, 2),
            "exit_reason": exit_reason,
            "hold_days": exit_idx - i,
        })
        i = exit_idx + 1  # one open position per (strategy, symbol) at a time
    return trades


def _replay_all(bars_by_symbol: dict[str, list], gate: dict,
                slippage_bps: float = DEFAULT_SLIPPAGE_BPS) -> dict:
    """Score the whole catalog against preloaded daily bars. Pure and synchronous —
    give it `{symbol: [Bar, ...]}` from anywhere and it returns the leaderboard."""
    cost_model = CostModel()
    results = []
    for spec in STRATEGY_CATALOG:
        if not _daily_capable(spec):
            results.append({
                "strategy_id": spec.strategy_id, "name": spec.name,
                "category": spec.category, "family": spec.family,
                "backtestable": False,
                "reason": (
                    "needs intraday day-state (day open/high/low + volume so far) from a "
                    "live quote; no equity intraday history is backfilled, so this cannot "
                    "be measured on daily bars"
                ),
                "metrics": _metrics_from_trades([]), "qualified": False,
                "gate_failures": ["not backtestable on daily bars"],
            })
            continue

        trades: list[dict] = []
        for symbol, bars in bars_by_symbol.items():
            trades.extend(_replay_symbol(spec, symbol, bars, cost_model, slippage_bps))
        metrics = _metrics_from_trades(trades)
        verdict = qualify_intraday(metrics, gate)
        results.append({
            "strategy_id": spec.strategy_id, "name": spec.name,
            "category": spec.category, "family": spec.family,
            "backtestable": True,
            "approximation": (
                "held 1 day and exited at the next close if untouched — this strategy "
                "squares off intra-session live, which a daily bar cannot represent"
                if spec.max_hold_days == 0 else None
            ),
            "max_hold_days": spec.max_hold_days,
            "metrics": metrics,
            "qualified": verdict["qualified"],
            "gate_failures": verdict["reasons"],
            "symbols_traded": len({t["symbol"] for t in trades}),
        })

    testable = [r for r in results if r["backtestable"]]
    results.sort(key=lambda r: (
        r["qualified"],
        (r["metrics"].get("profit_factor") or -1),
        r["metrics"].get("net_pnl") or 0,
    ), reverse=True)

    return {
        "results": results,
        "strategy_count": len(results),
        "backtestable_count": len(testable),
        "not_backtestable_count": len(results) - len(testable),
        "qualified_count": sum(1 for r in results if r["qualified"]),
        "symbols": len(bars_by_symbol),
        "total_trades": sum(r["metrics"]["trades"] for r in results),
    }


async def _universe(max_symbols: int) -> list[str]:
    """Every non-index symbol with local daily bars — the scan universe is exactly what
    has been backfilled, never invented."""
    from app.core.db import bars_collection
    from app.services.call_engine import INDICES

    symbols = await bars_collection.distinct("symbol", {"timeframe": "1d"})
    return sorted(s for s in symbols if s not in INDICES)[:max_symbols]


def _load_bars_for(symbols: list[str], years: float) -> dict[str, list]:
    """Daily bars per symbol from the local store, skipping anything too short to score."""
    from backtesting_service.service import load_bars
    from tradingai_shared.domain import Timeframe

    out: dict[str, list] = {}
    for symbol in symbols:
        try:
            bars = load_bars(symbol, Timeframe.D1, years)
        except Exception:
            continue
        if len(bars) >= ATR_PERIOD + 5:
            out[symbol] = bars
    return out


async def run_intraday_backtest(
    years: float = 3.0,
    max_symbols: int = 50,
    gate: dict | None = None,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    persist: bool = True,
) -> dict:
    """Replay the catalog on daily bars, score it fee-honestly, and gate it."""
    symbols = await _universe(max_symbols)
    if not symbols:
        return {
            "error": "No symbols with local daily bars — backfill daily bars first.",
            "results": [], "strategy_count": 0, "backtestable_count": 0,
            "not_backtestable_count": 0, "qualified_count": 0, "symbols": 0,
            "total_trades": 0,
        }
    from anyio import to_thread

    effective_gate = {**DEFAULT_GATE, **(gate or {})}
    payload = await to_thread.run_sync(
        lambda: _replay_all(_load_bars_for(symbols, years), effective_gate, slippage_bps)
    )
    doc = {
        "backtest_id": uuid4().hex[:12],
        "created_at": datetime.now(timezone.utc),
        "years": years,
        "max_symbols": max_symbols,
        "timeframe": "1d",
        "gate": effective_gate,
        "slippage_bps": slippage_bps,
        "cost_model": "NSE rate card (CostModel): intraday rates for same-day strategies, delivery for swings",
        "intrabar_rule": "stop assumed to hit before target when one daily bar contains both",
        **payload,
    }
    if persist:
        from app.core.db import intraday_lab_backtests_collection

        await intraday_lab_backtests_collection.insert_one(dict(doc))
    doc.pop("_id", None)
    doc["created_at"] = doc["created_at"].isoformat()
    return doc
