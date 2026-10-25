"""A multi-factor RANK for a strategy leaderboard - an ordering, never a verdict.

Sorting a board by net P&L ranks on one number, and the number most moved by luck: a single
big day puts a strategy on top. This rank blends seven factors instead, each scored as a
PERCENTILE among the strategies on the board (0 = worst there, 100 = best there), so no
factor's units can swamp another's:

    t-stat of net P&L per trade      25   is the per-trade mean distinguishable from noise?
    net return per trade (bp)        20   after costs, as a share of the position - size-free
    profit factor                    15   rupees won per rupee lost
    max drawdown (lower is better)   15   the worst peak-to-trough fall on its allocation
    positive days                    10   share of its sessions that closed up
    last 5 sessions' net P&L         10   recent form, so a strategy that has stopped working
                                          sinks even while its older record carries it
    win rate                          5   kept small - a high win rate with bigger losses loses

SHORT RECORDS ARE PULLED TO THE MIDDLE. Under `min_trades` the score is shrunk toward 50 in
proportion to how far short the record is: five lucky trades must not outrank a hundred.

WHAT IT IS NOT. A percentile is relative: on a board where every strategy loses, #1 is the
least bad loser. Whether anything has an EDGE is the promotion gate's verdict
(`promotion_gate`), which this does not replace or weaken.

Pure: rows in, rows out. No I/O, so the same rank can serve any desk's leaderboard.
"""

from __future__ import annotations

import math

# (key, label, weight, higher_is_better). Weights sum to 100.
FACTORS: tuple[tuple[str, str, float, bool], ...] = (
    ("t_stat", "t-stat", 25.0, True),
    ("net_bp_per_trade", "Net return per trade", 20.0, True),
    ("profit_factor", "Profit factor", 15.0, True),
    ("max_drawdown_pct", "Max drawdown", 15.0, False),
    ("positive_days_pct", "Positive days", 10.0, True),
    ("recent_pnl", "Last 5 sessions", 10.0, True),
    ("win_rate", "Win rate", 5.0, True),
)
NEUTRAL = 50.0
RECENT_SESSIONS = 5


def _percentiles(values: list[float | None], higher_is_better: bool) -> list[float | None]:
    """Average-rank percentile of each value among the non-missing ones; ties share a rank."""
    present = sorted((v if higher_is_better else -v, i) for i, v in enumerate(values) if v is not None)
    out: list[float | None] = [None] * len(values)
    n = len(present)
    if n == 0:
        return out
    if n == 1:
        out[present[0][1]] = 100.0
        return out
    j = 0
    while j < n:
        k = j
        while k + 1 < n and present[k + 1][0] == present[j][0]:
            k += 1
        pct = ((j + k) / 2) / (n - 1) * 100.0
        for m in range(j, k + 1):
            out[present[m][1]] = pct
        j = k + 1
    return out


def _factor_value(row: dict, key: str) -> float | None:
    v = row.get(key)
    if key == "profit_factor" and v is None:
        # No losing trade at all: the best possible profit factor, not a missing one.
        if (row.get("gross_loss") or 0) == 0 and (row.get("gross_profit") or 0) > 0:
            return math.inf
        return None
    if v is None:
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def rank_rows(rows: list[dict], *, min_trades: int = 30) -> list[dict]:
    """Add `rank`, `rank_score` (0-100) and `rank_factors` to every row; return them sorted
    by rank. A row with no closed trades gets no score and sorts last."""
    scored = [r for r in rows if (r.get("trades") or 0) > 0]
    for r in rows:
        r["rank"], r["rank_score"], r["rank_factors"] = None, None, []

    pct_by_factor = {key: _percentiles([_factor_value(r, key) for r in scored], hib)
                     for key, _label, _w, hib in FACTORS}
    for i, r in enumerate(scored):
        total = 0.0
        factors = []
        for key, label, weight, hib in FACTORS:
            pct = pct_by_factor[key][i]
            used = NEUTRAL if pct is None else pct
            total += weight * used
            value = r.get(key)
            factors.append({"key": key, "label": label, "weight": weight,
                            "higher_is_better": hib, "value": value,
                            "percentile": None if pct is None else round(pct, 1)})
        raw = total / sum(w for _k, _l, w, _h in FACTORS)
        trust = min(1.0, (r.get("trades") or 0) / max(min_trades, 1))
        r["rank_score"] = round(NEUTRAL + (raw - NEUTRAL) * trust, 1)
        r["rank_factors"] = factors
        r["rank_shrunk"] = trust < 1.0

    ordered = sorted(scored, key=lambda r: (-r["rank_score"], -(r.get("net_pnl") or 0.0)))
    for n, r in enumerate(ordered, start=1):
        r["rank"] = n
    unscored = [r for r in rows if (r.get("trades") or 0) <= 0]
    return ordered + unscored


def day_factors(daily_net: dict[str, float], desk_sessions: list[str],
                recent: int = RECENT_SESSIONS) -> dict:
    """Positive-day share over the strategy's own sessions, and its net P&L over the DESK's
    last `recent` sessions (a strategy that did not trade in them scores 0 there, not missing:
    it made nothing)."""
    days = [d for d in daily_net if d]
    last = set(sorted(desk_sessions)[-recent:])
    return {
        "positive_days_pct": round(sum(1 for d in days if daily_net[d] > 0) / len(days) * 100.0, 1)
        if days else None,
        "recent_pnl": round(sum(v for d, v in daily_net.items() if d in last), 2) if days else None,
        "sessions_traded": len(days),
    }
