"""No-look-ahead replay for Strategy Factory strategies.

THREE DECISIONS THAT DECIDE WHETHER THE NUMBERS MEAN ANYTHING
-------------------------------------------------------------
1. **Entry fills on the NEXT bar's open, never the signal bar's close.** The signal is
   only known once its bar has completed, so filling at that close buys at a price that
   was already history when the decision existed. This single shortcut is the most common
   reason a backtest looks good and a live desk does not.

2. **Intrabar ambiguity resolves against the trade.** When a bar's range contains both the
   stop and the target, the replay assumes the STOP was hit first. Bar data cannot say
   which came first, and the optimistic assumption manufactures winners out of exactly the
   volatile bars where real fills are worst.

3. **Costs and slippage on both sides.** Charged from the same rate cards the live desks
   use, so a strategy whose edge is smaller than its friction is reported as the loser it
   is rather than as a modest winner.

The replay only ever hands `evaluate()` the slice `bars[:i+1]`, so a strategy physically
cannot read a bar that had not happened yet — look-ahead is prevented by construction
rather than by discipline.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Callable, Optional

from .catalog import Strategy
from .primitives import (
    DEFAULT_CAPITAL, DEFAULT_RISK_PCT, classify_regime_series, position_size,
    round_trip_cost, slippage_price,
)
from .signals import evaluate

# Bars a position may live for, per timeframe, before it is closed as unresolved. Scaled
# so "held too long" means a comparable amount of market time on every chart.
DEFAULT_MAX_HOLD = {"1m": 120, "5m": 96, "15m": 80, "30m": 64,
                    "45m": 64, "1h": 60, "4h": 45, "1d": 40}

BARS_PER_YEAR = {"1m": 375 * 250, "5m": 75 * 250, "15m": 25 * 250, "30m": 13 * 250,
                 "45m": 9 * 250, "1h": 7 * 250, "4h": 2 * 250, "1d": 250}


@dataclass
class Trade:
    entry_ts: object
    exit_ts: object
    side: str
    entry: float
    exit: float
    qty: int
    gross: float
    costs: float
    net: float
    r_realised: float
    reason: str
    pattern: str
    bars_held: int


@dataclass
class Metrics:
    trades: int = 0
    wins: int = 0
    win_rate: float = 0.0
    net_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_costs: float = 0.0
    profit_factor: Optional[float] = None
    expectancy: float = 0.0
    avg_r: float = 0.0
    max_drawdown_pct: float = 0.0
    return_pct: float = 0.0
    cagr_pct: Optional[float] = None
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    largest_win: float = 0.0
    largest_loss: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    exposure_pct: float = 0.0


@dataclass
class BacktestResult:
    strategy_id: str
    symbol: str
    timeframe: str
    bars_tested: int
    span_days: float
    overall: Metrics
    in_sample: Metrics
    out_of_sample: Metrics
    grade: int
    grade_reasons: list[str]
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    rejections: dict = field(default_factory=dict)


def _metrics(trades: list[Trade], capital: float, timeframe: str,
             span_days: float, bars_in_market: int, bars_total: int) -> Metrics:
    m = Metrics()
    if not trades:
        return m
    pnls = [t.net for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    m.trades = len(trades)
    m.wins = len(wins)
    m.win_rate = round(len(wins) / len(trades), 4)
    m.net_pnl = round(sum(pnls), 2)
    m.gross_profit = round(sum(wins), 2)
    m.gross_loss = round(abs(sum(losses)), 2)
    m.total_costs = round(sum(t.costs for t in trades), 2)
    m.profit_factor = round(m.gross_profit / m.gross_loss, 3) if m.gross_loss > 0 else None
    m.expectancy = round(m.net_pnl / m.trades, 2)
    m.avg_r = round(sum(t.r_realised for t in trades) / m.trades, 3)
    m.largest_win = round(max(pnls), 2)
    m.largest_loss = round(min(pnls), 2)
    m.return_pct = round(m.net_pnl / capital * 100, 3)
    m.exposure_pct = round(bars_in_market / bars_total * 100, 2) if bars_total else 0.0

    # Drawdown against the running PEAK, not the starting stake.
    eq = peak = capital
    dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        if peak > 0:
            dd = max(dd, (peak - eq) / peak * 100)
    m.max_drawdown_pct = round(dd, 3)

    run_w = run_l = 0
    for p in pnls:
        if p > 0:
            run_w, run_l = run_w + 1, 0
        elif p < 0:
            run_l, run_w = run_l + 1, 0
        m.max_consecutive_wins = max(m.max_consecutive_wins, run_w)
        m.max_consecutive_losses = max(m.max_consecutive_losses, run_l)

    if span_days > 30 and capital > 0:
        years = span_days / 365.25
        ending = capital + m.net_pnl
        if ending > 0 and years > 0:
            m.cagr_pct = round(((ending / capital) ** (1 / years) - 1) * 100, 3)

    # Sharpe/Sortino on per-trade returns, annualised by the observed trade rate rather
    # than an assumed one — a 1-minute strategy and a daily strategy trade at wildly
    # different frequencies and must not be scaled by the same constant.
    rets = [p / capital for p in pnls]
    if len(rets) >= 3:
        mean = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
        per_year = (len(trades) / (span_days / 365.25)) if span_days > 0 else 0
        if sd > 0 and per_year > 0:
            m.sharpe = round(mean / sd * math.sqrt(per_year), 3)
        downside = [r for r in rets if r < 0]
        if downside and per_year > 0:
            dsd = math.sqrt(sum(r * r for r in downside) / len(downside))
            if dsd > 0:
                m.sortino = round(mean / dsd * math.sqrt(per_year), 3)
    return m


def _grade(overall: Metrics, oos: Metrics, min_trades: int) -> tuple[int, list[str]]:
    """Grade 1-5 on multiple axes, never on win rate alone.

    The binding tests are out-of-sample survival and drawdown. A strategy that only works
    in-sample is an overfit, and the grade says so rather than averaging it away."""
    reasons: list[str] = []
    if overall.trades < min_trades:
        return 1, [f"only {overall.trades} trades (needs {min_trades}) — not enough evidence"]

    pf = overall.profit_factor
    if overall.net_pnl <= 0:
        return 1, [f"net P&L {overall.net_pnl:,.0f} after costs"]
    if pf is None or pf <= 1.0:
        return 1, [f"profit factor {pf} is not above 1.0"]

    oos_ok = oos.trades >= max(5, min_trades // 4) and oos.net_pnl > 0
    if not oos_ok:
        reasons.append(f"out-of-sample not profitable ({oos.trades} trades, "
                       f"net {oos.net_pnl:,.0f}) — likely overfit")
        return 2, reasons

    reasons.append(f"in-sample PF {pf:.2f}, out-of-sample net {oos.net_pnl:,.0f} "
                   f"over {oos.trades} trades")
    if pf >= 1.6 and overall.max_drawdown_pct <= 15 and overall.trades >= min_trades * 2 \
            and (overall.sharpe or 0) >= 1.0:
        reasons.append("strong profit factor, contained drawdown, deep sample")
        return 5, reasons
    if pf >= 1.4 and overall.max_drawdown_pct <= 25:
        return 4, reasons
    if pf >= 1.15:
        return 3, reasons
    return 2, reasons + ["edge too thin once costs are charged"]


def backtest(strategy: Strategy, bars, symbol: str, exchange: str = "MCX",
             htf_bars=None, capital: float = DEFAULT_CAPITAL,
             cost_model: str = "commodity", slippage_bps: float = 5.0,
             risk_pct: float = DEFAULT_RISK_PCT, lot_size: int = 1,
             max_hold: int | None = None, oos_fraction: float = 0.3,
             min_trades_for_grade: int = 20,
             evaluate_fn: Callable | None = None) -> BacktestResult:
    """Replay `strategy` over `bars`. See the module docstring for the realism rules.

    `evaluate_fn` lets a desk with its own decision rules — the long-only Trending
    Stocks library, whose signals must clear a 1:6 feasibility gate — reuse THIS
    replay rather than forking it. It must have `evaluate()`'s exact signature and
    return shape. Default is `evaluate` itself, so factory behaviour is unchanged;
    the point of the hook is that there stays exactly one no-look-ahead replay in the
    app, and every desk's numbers come out of it."""
    _eval = evaluate_fn or evaluate
    tf = strategy.timeframe
    max_hold = max_hold or DEFAULT_MAX_HOLD.get(tf, 60)
    htf_ts = [b.ts for b in htf_bars] if htf_bars else []

    # Regime for every bar in ONE pass. Recomputing it per bar made the replay O(n^2)
    # and was measured at 65% of total backtest time (a full 546-strategy sweep projected
    # to 10 hours). The series is provably identical to the per-bar function — every
    # indicator involved is causal — so this is speed, not a shortcut.
    regimes = classify_regime_series(bars)

    trades: list[Trade] = []
    equity = [capital]
    rejections: dict[str, int] = {}
    bars_in_market = 0

    pos: dict | None = None
    start = max(strategy.min_bars, 2)

    for i in range(start, len(bars) - 1):
        nxt = bars[i + 1]

        # ---- manage an open position on the NEXT bar ---------------------------
        if pos is not None:
            pos["bars_held"] += 1
            long = pos["side"] == "BUY"
            hit_stop = nxt.low <= pos["stop"] if long else nxt.high >= pos["stop"]
            hit_target = nxt.high >= pos["target"] if long else nxt.low <= pos["target"]
            reason = None
            if hit_stop and hit_target:
                # Ambiguous bar: assume the stop came first. See docstring.
                exit_px, reason = pos["stop"], "stoploss"
            elif hit_stop:
                exit_px, reason = pos["stop"], "stoploss"
            elif hit_target:
                exit_px, reason = pos["target"], "target"
            elif pos["bars_held"] >= max_hold:
                exit_px, reason = nxt.close, "max_hold"

            if reason:
                fill = slippage_price(exit_px, slippage_bps, adverse_for_buy=not long)
                qty = pos["qty"]
                gross = (fill - pos["entry"]) * qty * (1 if long else -1)
                costs = round_trip_cost(cost_model, pos["entry"], fill, qty, long)
                net = gross - costs
                risk_amount = pos["risk"] * qty
                trades.append(Trade(
                    entry_ts=pos["entry_ts"], exit_ts=nxt.ts, side=pos["side"],
                    entry=round(pos["entry"], 4), exit=round(fill, 4), qty=qty,
                    gross=round(gross, 2), costs=round(costs, 2), net=round(net, 2),
                    r_realised=round(net / risk_amount, 3) if risk_amount else 0.0,
                    reason=reason, pattern=pos["pattern"], bars_held=pos["bars_held"],
                ))
                equity.append(equity[-1] + net)
                bars_in_market += pos["bars_held"]
                pos = None

        if pos is not None:
            continue

        # ---- look for a new signal on the COMPLETED bar i ------------------------
        htf_slice = None
        if htf_ts:
            cut = bisect_right(htf_ts, bars[i].ts)
            htf_slice = htf_bars[:cut] if cut else None

        sig, rej = _eval(strategy, bars[:i + 1], symbol, exchange, htf_slice,
                         regime=regimes[i])
        if sig is None:
            if rej is not None:
                rejections[rej.stage] = rejections.get(rej.stage, 0) + 1
            continue

        # ---- fill on the NEXT bar's open ----------------------------------------
        long = sig.side == "BUY"
        fill = slippage_price(nxt.open, slippage_bps, adverse_for_buy=long)
        # Re-anchor the levels to the actual fill so the risk really is the risk taken.
        shift = fill - sig.entry
        stop, target = sig.stop + shift, sig.target + shift
        risk = abs(fill - stop)
        if risk <= 0:
            continue

        from .primitives import Levels
        qty = position_size(capital, equity[-1], Levels(fill, stop, target, risk,
                                                        abs(target - fill),
                                                        abs(target - fill) / risk,
                                                        sig.stop_basis, sig.target_basis),
                            risk_pct=risk_pct, lot_size=lot_size)
        if qty < 1:
            rejections["sizing"] = rejections.get("sizing", 0) + 1
            continue

        pos = {"side": sig.side, "entry": fill, "stop": stop, "target": target,
               "risk": risk, "qty": qty, "entry_ts": nxt.ts, "bars_held": 0,
               "pattern": sig.pattern}

    span_days = 0.0
    if len(bars) >= 2:
        span_days = (bars[-1].ts - bars[0].ts).total_seconds() / 86400.0

    overall = _metrics(trades, capital, tf, span_days, bars_in_market, len(bars))

    # Chronological split — never random. Shuffling a time series before splitting leaks
    # the future into the training half.
    cut_idx = int(len(trades) * (1 - oos_fraction))
    is_trades, oos_trades = trades[:cut_idx], trades[cut_idx:]
    is_span = oos_span = span_days / 2 if span_days else 0
    in_sample = _metrics(is_trades, capital, tf, is_span, 0, len(bars))
    out_sample = _metrics(oos_trades, capital, tf, oos_span, 0, len(bars))

    grade, reasons = _grade(overall, out_sample, min_trades_for_grade)

    return BacktestResult(
        strategy_id=strategy.strategy_id, symbol=symbol, timeframe=tf,
        bars_tested=len(bars), span_days=round(span_days, 2),
        overall=overall, in_sample=in_sample, out_of_sample=out_sample,
        grade=grade, grade_reasons=reasons, trades=trades, equity_curve=equity,
        rejections=rejections,
    )


__all__ = ["backtest", "BacktestResult", "Metrics", "Trade", "DEFAULT_MAX_HOLD"]
