"""Full performance-metric set derived from a BacktestRun (trades + equity curve).

All ratios are annualized from the bar cadence: 252 trading days/year, 375 trading
minutes/day for intraday timeframes, 52 weeks/year. No-trade runs return a zeroed
summary instead of raising."""

import math
from collections import defaultdict

from backtesting_service.engine import BacktestRun
from tradingai_shared.domain import Timeframe

BARS_PER_YEAR = {
    Timeframe.M1: 252 * 375,
    Timeframe.M5: 252 * 75,
    Timeframe.M15: 252 * 25,
    Timeframe.H1: 252 * 7,  # 375min/60 ~ 6.25, but Dhan hourly cuts 7 candles/session
    Timeframe.D1: 252,
    Timeframe.W1: 52,
}


def compute_metrics(run: BacktestRun) -> dict:
    equity = run.equity
    trades = run.trades
    cfg = run.config
    initial = cfg.initial_capital
    final = equity[-1] if equity else initial

    years = _years_spanned(run)
    net_profit = final - initial
    total_return_pct = net_profit / initial * 100

    wins = [t.pnl for t in trades if t.pnl is not None and t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl is not None and t.pnl <= 0]
    gross_win, gross_loss = sum(wins), -sum(losses)

    returns = _bar_returns(equity)
    max_dd_pct, max_dd_value = _max_drawdown(equity)
    cagr = ((final / initial) ** (1 / years) - 1) * 100 if years > 0 and final > 0 else None
    sharpe = _annualized_ratio(returns, cfg.timeframe, downside_only=False)
    sortino = _annualized_ratio(returns, cfg.timeframe, downside_only=True)

    return {
        "net_profit": round(net_profit, 2),
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr, 2) if cagr is not None else None,
        "annual_return_pct": round(cagr, 2) if cagr is not None else None,
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 4) if trades else None,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "expectancy": round((gross_win - gross_loss) / len(trades), 2) if trades else None,
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "sortino": round(sortino, 3) if sortino is not None else None,
        "calmar": round(cagr / max_dd_pct, 3) if cagr is not None and max_dd_pct > 0 else None,
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_value": round(max_dd_value, 2),
        "recovery_factor": round(net_profit / max_dd_value, 3) if max_dd_value > 0 else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "avg_holding_bars": _avg_holding_bars(run),
        "max_win_streak": _streak(trades, winning=True),
        "max_loss_streak": _streak(trades, winning=False),
        "exposure_pct": round(run.bars_in_market / run.total_bars * 100, 2) if run.total_bars else 0.0,
        "total_charges": run.total_charges,
        "initial_capital": initial,
        "final_equity": round(final, 2),
        "monthly_returns": _period_returns(run, monthly=True),
        "yearly_returns": _period_returns(run, monthly=False),
    }


def _years_spanned(run: BacktestRun) -> float:
    if len(run.equity_ts) < 2:
        return 0.0
    return max((run.equity_ts[-1] - run.equity_ts[0]).days / 365.25, 1 / 365.25)


def _bar_returns(equity: list[float]) -> list[float]:
    return [
        (equity[i] - equity[i - 1]) / equity[i - 1]
        for i in range(1, len(equity))
        if equity[i - 1] > 0
    ]


def _annualized_ratio(returns: list[float], timeframe: Timeframe, downside_only: bool) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    pool = [r for r in returns if r < 0] if downside_only else returns
    if len(pool) < 2:
        return None
    ref = 0.0 if downside_only else mean
    var = sum((r - ref) ** 2 for r in pool) / (len(pool) - 1)
    std = math.sqrt(var)
    if std == 0:
        return None
    periods = BARS_PER_YEAR[timeframe]
    return mean / std * math.sqrt(periods)


def _max_drawdown(equity: list[float]) -> tuple[float, float]:
    peak = float("-inf")
    max_dd_pct = max_dd_value = 0.0
    for value in equity:
        peak = max(peak, value)
        dd_value = peak - value
        dd_pct = dd_value / peak * 100 if peak > 0 else 0.0
        max_dd_pct = max(max_dd_pct, dd_pct)
        max_dd_value = max(max_dd_value, dd_value)
    return max_dd_pct, max_dd_value


def _avg_holding_bars(run: BacktestRun) -> float | None:
    """Holding time in bars, derived from time-in-market over trade count (cheap and
    cadence-independent; wall-clock holding time = bars x bar duration)."""
    closed = [t for t in run.trades if t.exit_ts is not None]
    if not closed:
        return None
    return round(run.bars_in_market / len(closed), 1)


def _streak(trades: list, winning: bool) -> int:
    best = current = 0
    for t in trades:
        if t.pnl is None:
            continue
        if (t.pnl > 0) == winning:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _period_returns(run: BacktestRun, monthly: bool) -> list[dict]:
    """Equity return per calendar month/year, from the last equity mark of each period."""
    if not run.equity:
        return []
    last_in_period: dict = {}
    for ts, value in zip(run.equity_ts, run.equity):
        key = (ts.year, ts.month) if monthly else ts.year
        last_in_period[key] = value  # ordered bars -> ends as period-final equity

    out = []
    prev = run.config.initial_capital
    for key in sorted(last_in_period):
        value = last_in_period[key]
        ret = (value - prev) / prev * 100 if prev > 0 else 0.0
        entry = {"year": key[0], "month": key[1]} if monthly else {"year": key}
        out.append({**entry, "return_pct": round(ret, 2)})
        prev = value
    return out
