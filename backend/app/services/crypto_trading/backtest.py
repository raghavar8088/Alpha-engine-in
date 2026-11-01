"""One strategy-cryptocurrency pair's backtest, on the strategy's own definition.

  Factory strategies       the Factory's own `signals.evaluate` (setup, regime gate, confirmations,
                           levels) on the latest 600 bars - what the live desk passes it - in the
                           replay below, with the Factory's sizing, the Delta fee card and the
                           coin's slippage.
  Strategies module        backtesting_service.engine.BacktestEngine - the module's own replay
                           (next-bar fills, intrabar stops, the stop first on a tie) - with
                           a Delta CostModel and, for NSE-clock strategies, the crypto session.

WHY NOT strategy_factory.backtest.backtest() ITSELF. Read line by line (2026-11-01) it has four
habits a live account cannot share, every one of them in the strategy's favour:
  1. look-ahead on the higher timeframe: its HTF slice is every HTF bar that OPENED by the signal
     bar's open, so the HTF bar still forming is handed over with its FINAL close (a 15m signal sees
     up to 45 minutes of the 1h bar's future);
  2. the entry bar is never checked: management starts on the bar after the fill, so a stop the
     entry bar itself ran through is ignored;
  3. overlapping re-entry: after an exit on bar t+1 it decides on bar t - a bar it was still in the
     position at - and fills at bar t+1's OPEN, before that exit happened, and the new position then
     skips bar t+1 too (see 2) - it survives the very bar that stopped the old one;
  4. a bar that opens through the stop fills at the stop, not at the worse open.
This replay is that one with the four corrected: only HTF bars that had CLOSED by the signal bar's
close; stops and targets from the entry bar on; a decision only on a bar the account was flat at;
a gap through a level fills at the open. Everything else is the Factory's - next-bar-open entry,
levels re-anchored to the fill, the stop first on a bar touching both, DEFAULT_MAX_HOLD, the 1%
risk sizing and its cash cap. A position still open at the end is closed at the last close, as the
Strategies module's replay closes it. The shared Factory replay is left as it is - the other desks'
grades come from it - and its four habits are reported, not silently inherited here.

Data quality comes first: a series with more than MAX_NO_TRADE_BAR_PCT of no-trade bars (see
config) is "insufficient data" before either replay runs.

Both then go through the same three steps, so the two libraries are judged identically:
  1. funding charged on every trade from the venue's own funding history;
  2. metrics by the Factory's `_metrics` on the funded trades, the out-of-sample set being the
     LAST 30% of trades in time (chronological, never shuffled);
  3. the grade by the Factory's own `_grade`; grade >= 3 is eligible to paper trade.

Status, kept distinct:
  unsupported         the strategy (or this pair) cannot run on this venue's data
  insufficient_data   too few bars, or fewer than 20 trades - not enough evidence to grade
  failed_validation   enough trades, graded below 3 on crypto results
  eligible            graded 3 or better on crypto results
"""

from __future__ import annotations

import os
import platform
import time
from bisect import bisect_right
from datetime import datetime, timedelta

from . import library as lib
from .adapters import (
    Contract, FBar, factory_bars, real_ts, register_factory_cost_model, sm_bars, sm_cost_model, sm_unit, trade_funding,
)
from .config import (
    ACCOUNT_CAPITAL_USD, BENCHMARK_SYMBOL, EVAL_WINDOW, HTF_WINDOW, MAX_NO_TRADE_BAR_PCT, MAX_NOTIONAL_PCT,
    MIN_GRADE_TO_TRADE, MIN_TRADES_FOR_GRADE, NSE_CLOCK_STRATEGIES, OOS_FRACTION, RISK_PCT, TF_SECONDS, UTC,
)

CODE_VERSION = os.getenv("CRYPTO_TRADING_CODE_VERSION", "")


def pair_id(strategy_id: str, symbol: str) -> str:
    return f"{strategy_id}|{symbol}"


def no_trade_pct(rows: list[list]) -> float:
    """Share of bars (percent) with no trade in them - the last trade carried forward."""
    return round(sum(1 for r in rows if not r[5]) / len(rows) * 100, 2) if rows else 100.0


def closed_htf(htf: list, htf_close: list, signal_close) -> list | None:
    """The higher-timeframe bars that had CLOSED by the time the signal bar closed (the latest
    HTF_WINDOW of them). `htf_close[k]` is bar k's close time. The bar still forming is never in it."""
    cut = bisect_right(htf_close, signal_close)
    return htf[max(0, cut - HTF_WINDOW):cut] or None


def exit_on_bar(side: str, stop: float, target: float, bar, slippage_bps: float) -> tuple[float, str] | None:
    """A stop or target on one bar - the rule the replay and the live desk share. The stop is taken
    first when the bar holds both (bar data cannot say which came first); a bar that opens through
    a level fills at that open, not at a level price had already passed; slippage on every fill."""
    from app.services.strategy_factory.primitives import slippage_price
    if side == "BUY":
        if bar.low <= stop:
            return slippage_price(min(stop, bar.open), slippage_bps, adverse_for_buy=False), "stoploss"
        if bar.high >= target:
            return slippage_price(max(target, bar.open), slippage_bps, adverse_for_buy=False), "target"
    else:
        if bar.high >= stop:
            return slippage_price(max(stop, bar.open), slippage_bps, adverse_for_buy=True), "stoploss"
        if bar.low <= target:
            return slippage_price(min(target, bar.open), slippage_bps, adverse_for_buy=True), "target"
    return None


def _metrics_doc(m) -> dict:
    return {k: getattr(m, k) for k in (
        "trades", "wins", "win_rate", "net_pnl", "gross_profit", "gross_loss", "total_costs", "profit_factor",
        "expectancy", "avg_r", "max_drawdown_pct", "return_pct", "cagr_pct", "sharpe", "sortino", "largest_win",
        "largest_loss", "max_consecutive_wins", "max_consecutive_losses", "exposure_pct")}


def _downsample(points: list, n: int = 200) -> list:
    if len(points) <= n:
        return points
    step = len(points) / n
    return [points[int(i * step)] for i in range(n - 1)] + [points[-1]]


def _base(row: dict, contract: Contract, status: str, reason: str, **extra) -> dict:
    return {"pair_id": pair_id(row["strategy_id"], contract.symbol), "strategy_id": row["strategy_id"],
            "library": row["library"], "base_id": row["base_id"], "name": row["name"], "family": row["family"],
            "timeframe": row["timeframe"], "symbol": contract.symbol, "coin": contract.coin, "status": status,
            "status_reason": reason, "grade": None, "fingerprint": row["fingerprint"],
            "run_at": datetime.now(UTC).isoformat(), "run_on": platform.node(), "code_version": CODE_VERSION, **extra}


def _factory_trades(row: dict, contract: Contract, bars: list[FBar], htf: list[FBar] | None):
    """The Factory's replay with its four habits corrected (module docstring)."""
    from app.services.strategy_factory.backtest import DEFAULT_MAX_HOLD, Trade
    from app.services.strategy_factory.catalog import FACTORY_BY_ID
    from app.services.strategy_factory.primitives import (
        Levels, classify_regime_series, position_size, round_trip_cost, slippage_price,
    )
    from app.services.strategy_factory.signals import evaluate
    s = FACTORY_BY_ID[row["strategy_id"]]
    cost_model = register_factory_cost_model(contract)
    slip = contract.slippage_bps
    max_hold = DEFAULT_MAX_HOLD.get(s.timeframe, 60)
    tf_len = timedelta(seconds=TF_SECONDS[s.timeframe])
    htf_close = [b.ts + timedelta(seconds=TF_SECONDS[s.htf]) for b in htf] if (htf and s.htf) else []
    regimes = classify_regime_series(bars)      # causal, one pass - the Factory's own speed-up
    trades: list[Trade] = []
    rejections: dict[str, int] = {}
    equity = ACCOUNT_CAPITAL_USD
    pos: dict | None = None

    def close(px: float, ts, reason: str, i: int) -> None:
        nonlocal equity, pos
        long = pos["side"] == "BUY"
        gross = (px - pos["entry"]) * pos["qty"] * (1 if long else -1)
        costs = round_trip_cost(cost_model, pos["entry"], px, pos["qty"], long)
        net = gross - costs
        risk_amount = pos["risk"] * pos["qty"]
        trades.append(Trade(
            entry_ts=pos["entry_ts"], exit_ts=ts, side=pos["side"], entry=round(pos["entry"], 4),
            exit=round(px, 4), qty=pos["qty"], gross=round(gross, 2), costs=round(costs, 2), net=round(net, 2),
            r_realised=round(net / risk_amount, 3) if risk_amount else 0.0, reason=reason,
            pattern=pos["pattern"], bars_held=i - pos["i"] + 1))
        equity += net
        pos = None

    for i in range(max(s.min_bars, 2), len(bars)):
        bar = bars[i]
        # ---- an open position, from its entry bar on (the fill was at that bar's open) ----------
        if pos is not None:
            hit = exit_on_bar(pos["side"], pos["stop"], pos["target"], bar, slip)
            if hit:
                close(hit[0], bar.ts, hit[1], i)
            elif i - pos["i"] >= max_hold:          # the Factory's count: bars after the entry bar
                close(slippage_price(bar.close, slip, adverse_for_buy=pos["side"] != "BUY"),
                      bar.ts + tf_len, "max_hold", i)
        if pos is not None or i + 1 >= len(bars):
            continue

        # ---- flat at bar i's close: decide on it, fill at bar i+1's open --------------------------
        htf_slice = closed_htf(htf, htf_close, bar.ts + tf_len) if htf_close else None
        sig, rej = evaluate(s, bars[max(0, i + 1 - EVAL_WINDOW):i + 1], contract.symbol, "DELTA", htf_slice,
                            regime=regimes[i])
        if sig is None:
            if rej is not None:
                rejections[rej.stage] = rejections.get(rej.stage, 0) + 1
            continue
        nxt = bars[i + 1]
        long = sig.side == "BUY"
        fill = slippage_price(nxt.open, slip, adverse_for_buy=long)
        shift = fill - sig.entry                    # levels re-anchored to the fill, as the Factory does
        stop, target = sig.stop + shift, sig.target + shift
        risk = abs(fill - stop)
        if risk <= 0:
            continue
        qty = position_size(ACCOUNT_CAPITAL_USD, equity,
                            Levels(fill, stop, target, risk, abs(target - fill), abs(target - fill) / risk,
                                   sig.stop_basis, sig.target_basis),
                            risk_pct=RISK_PCT, max_notional_pct=MAX_NOTIONAL_PCT, lot_size=1)
        if qty < 1:
            rejections["sizing"] = rejections.get("sizing", 0) + 1
            continue
        pos = {"side": sig.side, "entry": fill, "stop": stop, "target": target, "risk": risk, "qty": qty,
               "entry_ts": nxt.ts, "i": i + 1, "pattern": sig.pattern}

    if pos is not None:
        last = bars[-1]
        close(slippage_price(last.close, slip, adverse_for_buy=pos["side"] != "BUY"), last.ts + tf_len, "end",
              len(bars) - 1)
    return trades, rejections, {"unit_contracts": 1}


def _sm_trades(row: dict, contract: Contract, rows: list[list], tf: str, bench_rows: list[list] | None):
    from backtesting_service.engine import BacktestConfig, BacktestEngine
    from app.services.strategy_factory.backtest import Trade
    from tradingai_shared.contracts import STRATEGY_REGISTRY
    from tradingai_shared.domain import AssetClass, Timeframe
    cls = STRATEGY_REGISTRY[row["base_id"]]
    nse_clock = row["base_id"] in NSE_CLOCK_STRATEGIES
    unit = sm_unit(contract, rows[0][4])        # from the first bar: a replay never reads its own last price
    bars = sm_bars(rows, contract, tf, unit, nse_clock)
    bench = None
    if bench_rows is not None:
        bench_contract = Contract(BENCHMARK_SYMBOL, "BTC", 1.0, contract.taker_fee, contract.funding_interval_s, 0.0)
        bench = sm_bars(bench_rows, bench_contract, tf, 1, nse_clock)
    # max_volume_participation off: the engine caps an entry at 10% of the FILL bar's volume, read at
    # that bar's open - a volume known only once the bar has closed. A $10,000 order's book impact
    # is in the coin's slippage instead (measured on the live book, universe.slippage_bps).
    cfg = BacktestConfig(strategy_id=row["base_id"], symbol=contract.symbol, timeframe=Timeframe(tf),
                         initial_capital=ACCOUNT_CAPITAL_USD, slippage_bps=contract.slippage_bps, allow_short=True,
                         asset_class=AssetClass.INDEX_FUTURE, lot_size=1, costs=sm_cost_model(contract),
                         max_volume_participation=0.0)
    run = BacktestEngine(cls(), cfg).run(bars, benchmark_bars=bench)
    sec = TF_SECONDS[tf]
    out = []
    for t in run.trades:
        if t.exit_price is None or t.exit_ts is None:
            continue
        side = "BUY" if t.direction.value == "BUY" else "SELL"
        sign = 1 if side == "BUY" else -1
        gross = (t.exit_price - t.entry_price) * t.quantity * sign
        risk = abs(t.entry_price - t.stop_loss) * t.quantity if t.stop_loss else ACCOUNT_CAPITAL_USD * RISK_PCT
        e_ts, x_ts = real_ts(t.entry_ts, nse_clock), real_ts(t.exit_ts, nse_clock)
        out.append(Trade(entry_ts=e_ts, exit_ts=x_ts, side=side, entry=t.entry_price, exit=t.exit_price,
                         qty=t.quantity, gross=round(gross, 2), costs=round(t.charges, 2), net=round(t.pnl, 2),
                         r_realised=round(t.pnl / risk, 3) if risk else 0.0, reason=t.exit_reason or "signal",
                         pattern=row["base_id"], bars_held=max(1, int((x_ts - e_ts).total_seconds() // sec))))
    rejections = {r: 1 for r in run.risk_rejections}
    return out, rejections, {"unit_contracts": unit, "nse_clock": nse_clock}


def run_pair(row: dict, contract: Contract, data: dict[str, list[list]], funding: list[tuple[int, float]],
             bench: dict[str, list[list]] | None = None) -> dict:
    """`data`: timeframe -> [ts, o, h, l, c, v] rows in coin prices (oldest first); `funding`: the
    venue's hourly series; `bench`: the benchmark's rows by timeframe (benchmark strategies only)."""
    t0 = time.time()
    if row["support"] == "unsupported":
        return _base(row, contract, "unsupported", row["unsupported_reason"])
    why = lib.pair_unsupported(row, contract.symbol)
    if why:
        return _base(row, contract, "unsupported", why)
    tf = row["timeframe"]
    rows = data.get(tf) or []
    need = (row["min_bars"] or 0) + 50 if row["library"] == "factory" else 250
    if len(rows) < need:
        return _base(row, contract, "insufficient_data", f"only {len(rows)} {tf} bars on the venue (needs {need}+)")
    thin = no_trade_pct(rows)
    if thin > MAX_NO_TRADE_BAR_PCT:
        return _base(row, contract, "insufficient_data",
                     f"{thin:.1f}% of the venue's {tf} bars for {contract.symbol} have no trade in them (the last "
                     f"trade carried forward, not a tradeable price); the limit is {MAX_NO_TRADE_BAR_PCT:g}%",
                     no_trade_bar_pct=thin, bars_tested=len(rows))
    if row["library"] == "factory":
        bars = factory_bars(rows, contract)
        htf = factory_bars(data.get(row["htf"]) or [], contract) if row["htf"] else None
        trades, rejections, meta = _factory_trades(row, contract, bars, htf)
        closes_t = [int(b.ts.timestamp()) for b in bars]
        closes = [b.close for b in bars]
        span_days = (bars[-1].ts - bars[0].ts).total_seconds() / 86400
        n_bars = len(bars)
    else:
        b_rows = (bench or {}).get(tf) if row["base_id"] in ("relative_strength", "sector_rotation") else None
        if row["base_id"] in ("relative_strength", "sector_rotation") and not b_rows:
            return _base(row, contract, "insufficient_data", f"no {BENCHMARK_SYMBOL} {tf} bars for the benchmark")
        trades, rejections, meta = _sm_trades(row, contract, rows, tf, b_rows)
        unit_k = contract.contract_value * meta["unit_contracts"]
        closes_t = [r[0] for r in rows]
        closes = [r[4] * unit_k for r in rows]
        span_days = (rows[-1][0] - rows[0][0]) / 86400
        n_bars = len(rows)

    # 1. funding, per trade, from the venue's history
    f_times = [t for t, _ in funding]
    f_rates = [r for _, r in funding]
    funding_total, exchanges = 0.0, 0
    for t in trades:
        f, n = trade_funding(t.entry_ts, t.exit_ts, 1 if t.side == "BUY" else -1, t.qty, contract.funding_interval_s,
                             closes_t, closes, f_times, f_rates, TF_SECONDS[tf])
        if f:
            t.costs = round(t.costs + f, 2)
            t.net = round(t.net - f, 2)
        funding_total += f
        exchanges += n

    # 2. metrics and 3. the grade - the Factory's own functions, on crypto trades
    from app.services.strategy_factory.backtest import _grade, _metrics
    bars_in_market = sum(t.bars_held for t in trades)
    overall = _metrics(trades, ACCOUNT_CAPITAL_USD, tf, span_days, bars_in_market, n_bars)
    cut = int(len(trades) * (1 - OOS_FRACTION))
    is_m = _metrics(trades[:cut], ACCOUNT_CAPITAL_USD, tf, span_days / 2, 0, n_bars)
    oos_m = _metrics(trades[cut:], ACCOUNT_CAPITAL_USD, tf, span_days / 2, 0, n_bars)
    grade, reasons = _grade(overall, oos_m, MIN_TRADES_FOR_GRADE)

    if overall.trades < MIN_TRADES_FOR_GRADE:
        status, reason = "insufficient_data", f"only {overall.trades} trades in {span_days:.0f} days (needs {MIN_TRADES_FOR_GRADE})"
    elif grade >= MIN_GRADE_TO_TRADE:
        status, reason = "eligible", "; ".join(reasons)
    else:
        status, reason = "failed_validation", "; ".join(reasons)

    eq, pts = ACCOUNT_CAPITAL_USD, [[closes_t[0], ACCOUNT_CAPITAL_USD]]
    for t in trades:
        eq += t.net
        pts.append([int(t.exit_ts.timestamp()), round(eq, 2)])
    sample = [{"entry_ts": t.entry_ts.isoformat(), "exit_ts": t.exit_ts.isoformat(), "side": t.side,
               "entry": round(t.entry, 6), "exit": round(t.exit, 6), "qty": t.qty, "net": t.net, "costs": t.costs,
               "r": t.r_realised, "reason": t.reason, "bars_held": t.bars_held} for t in trades[-60:]]
    return _base(row, contract, status, reason, grade=grade, grade_reasons=reasons,
                 overall=_metrics_doc(overall), in_sample=_metrics_doc(is_m), out_of_sample=_metrics_doc(oos_m),
                 funding_total=round(funding_total, 2), funding_exchanges=exchanges,
                 slippage_bps=contract.slippage_bps, taker_fee=contract.taker_fee, no_trade_bar_pct=thin,
                 bars_tested=n_bars, window_start=datetime.fromtimestamp(closes_t[0], UTC).isoformat(),
                 window_end=datetime.fromtimestamp(closes_t[-1], UTC).isoformat(), span_days=round(span_days, 1),
                 equity_curve=_downsample(pts), trades_sample=sample, rejections=rejections,
                 engine=("Factory evaluate, corrected replay" if row["library"] == "factory"
                         else "Strategies-module BacktestEngine"),
                 duration_s=round(time.time() - t0, 2), **meta)


__all__ = ["run_pair", "pair_id"]
