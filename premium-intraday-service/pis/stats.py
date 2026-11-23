"""Performance numbers for a list of closed positions (Position.public()-style dicts or Position objects).

t is DAY-CLUSTERED: trades on the same day move together, so each day's summed R is one observation. A
trade-count t overstates certainty about two-fold on this app's books (INTRADAY_STOCKS_54_STRATEGY_AUDIT.md)."""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import NormalDist, mean, pstdev


def _g(p, k):
    return p[k] if isinstance(p, dict) else getattr(p, k)


def day_of(p) -> str:
    v = _g(p, "t_entry")
    from .timeutil import day_of as d_
    return str(d_(v))


def summarize(trades: list, capital: float = 1_000_000.0, sessions: int | None = None) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    nets = [_g(p, "net") for p in trades]
    rs = [_g(p, "r_net") or 0.0 for p in trades]
    gross = [_g(p, "gross") for p in trades]
    fees = [(_g(p, "fees") or {}).get("total", 0.0) for p in trades]
    notion = [_g(p, "notional") for p in trades]
    slip = [abs(_g(p, "entry") - _g(p, "ref")) * _g(p, "qty") + abs((_g(p, "exit") or 0) - (_g(p, "exit_ref") or 0)) * _g(p, "qty")
            for p in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    by_day = defaultdict(float)
    by_day_r = defaultdict(float)
    for p in trades:
        by_day[day_of(p)] += _g(p, "net")
        by_day_r[day_of(p)] += _g(p, "r_net") or 0.0
    days = sorted(by_day)
    eq, peak, dd = capital, capital, 0.0
    for d in days:
        eq += by_day[d]
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
    dr = list(by_day_r.values())
    t_day = _t(dr)
    months = defaultdict(float)
    for d in days:
        months[d[:7]] += by_day[d]
    bp = [10_000 * x / y for x, y in zip(nets, notion) if y]
    exits = defaultdict(int)
    for p in trades:
        r = (_g(p, "reason") or "").split(" (")[0]
        r = "time exit" if r.startswith("time exit") else ("square-off" if r.startswith("square-off") else r)
        exits["failed exit" if r.startswith("FAILED") else r] += 1
    out = {
        "trades": n, "days_traded": len(days), "sessions": sessions,
        "net": sum(nets), "gross": sum(gross), "fees": sum(fees), "slippage": sum(slip),
        "costs": sum(fees) + sum(slip), "return_pct": sum(nets) / capital * 100,
        "mean_R": mean(rs), "median_R": sorted(rs)[n // 2], "mean_net_bp": mean(bp) if bp else None,
        "win_pct": len(wins) / n * 100, "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
        "avg_win": mean(wins) if wins else 0.0, "avg_loss": mean(losses) if losses else 0.0,
        "max_dd_pct": dd * 100, "t_day": t_day, "avg_daily_net": sum(nets) / len(days),
        "avg_daily_net_sessions": (sum(nets) / sessions) if sessions else None,
        "months": len(months), "months_up": sum(1 for v in months.values() if v > 0),
        "avg_notional": mean(notion), "exits": dict(exits),
        "long": _side(trades, 1), "short": _side(trades, -1),
        "failed_exits": sum(1 for p in trades if _g(p, "failed_exit")),
        "partials": sum(1 for p in trades if _g(p, "partial")),
    }
    # robustness: without the best 5% of days; largest single-stock share of net
    if len(days) >= 20:
        cut = max(1, int(len(days) * 0.05))
        best = set(sorted(days, key=lambda d: -by_day[d])[:cut])
        out["net_ex_best5pct_days"] = sum(v for d, v in by_day.items() if d not in best)
    by_sym = defaultdict(float)
    for p in trades:
        by_sym[_g(p, "symbol")] += _g(p, "net")
    pos = sum(v for v in by_sym.values() if v > 0)
    out["top_symbol_share"] = (max(by_sym.values()) / pos) if pos > 0 else None
    return out


def _side(trades: list, side: int) -> dict:
    xs = [p for p in trades if (_g(p, "side") in (side, "LONG" if side > 0 else "SHORT"))]
    if not xs:
        return {"trades": 0}
    rs = [_g(p, "r_net") or 0.0 for p in xs]
    nets = [_g(p, "net") for p in xs]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    by_day = defaultdict(float)
    for p in xs:
        by_day[day_of(p)] += _g(p, "r_net") or 0.0
    dr = list(by_day.values())
    t_day = _t(dr)
    return {"trades": len(xs), "net": sum(nets), "mean_R": mean(rs), "win_pct": len(wins) / len(xs) * 100,
            "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None, "t_day": t_day}


MIN_T_DAYS = 10


def _t(day_values: list) -> float | None:
    """Day-clustered t; None below MIN_T_DAYS trading days (two days with similar R gave t = -897)."""
    if len(day_values) < MIN_T_DAYS:
        return None
    sd = pstdev(day_values)
    return mean(day_values) / (sd / math.sqrt(len(day_values))) if sd > 0 else None


def t_crit(k_trials: int, alpha: float = 0.05) -> float:
    """One-sided Bonferroni critical value."""
    return NormalDist().inv_cdf(1 - alpha / max(1, k_trials))
