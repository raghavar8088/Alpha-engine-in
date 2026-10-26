"""A multi-factor RANK for a strategy leaderboard - an ordering, never a verdict.

Sorting a board by net P&L ranks on one number, and the number most moved by luck: a single
big day puts a strategy on top. This rank blends seven factors instead, each scored as a
PERCENTILE among the strategies on the board (0 = worst there, 100 = best there), so no
factor's units can swamp another's:

    t-stat of net P&L per trade      25   is the per-trade mean distinguishable from noise?
    net return per trade (bp)        20   after costs, as a share of the position - size-free
    profit factor                    15   rupees won per rupee lost
    max drawdown (lower is better)   15   the worst peak-to-trough fall
    positive days                    10   share of its sessions that closed up
    last 5 sessions' net P&L         10   recent form, so a strategy that has stopped working
                                          sinks even while its older record carries it
    win rate                          5   kept small - a high win rate with bigger losses loses

Every PAPER/LIVE desk's board is ranked on these seven, computed from that desk's own closed
trades (`position_stats`). A BACKTEST board (a sweep, a factory catalog) has no trade record to
compute them from, so it is ranked on the metrics it reports instead, with its own factor list
- the page names the factors each board uses.

A factor no strategy on the board has is dropped and the other weights scale up; a factor one
strategy lacks counts as the middle (50) for that strategy, never as the worst.

SHORT RECORDS ARE PULLED TO THE MIDDLE. Under `min_trades` the score is shrunk toward 50 in
proportion to how far short the record is: five lucky trades must not outrank a hundred.

WHAT IT IS NOT. A percentile is relative: on a board where every strategy loses, #1 is the
least bad loser. Whether anything has an EDGE is the promotion gate's verdict
(`promotion_gate`), which this does not replace or weaken.
"""

from __future__ import annotations

import math

# (key, label, weight, higher_is_better, unit). Weights sum to 100. `unit` tells the page how
# to print the value: t (a t-statistic), bp, ratio, pct (already in percent), fraction (0-1),
# inr (rupees), r (multiples of the risk taken).
Factor = tuple[str, str, float, bool, str]
FACTORS: tuple[Factor, ...] = (
    ("t_stat", "t-stat", 25.0, True, "t"),
    ("net_bp_per_trade", "Net return per trade", 20.0, True, "bp"),
    ("profit_factor", "Profit factor", 15.0, True, "ratio"),
    ("max_drawdown_pct", "Max drawdown", 15.0, False, "pct"),
    ("positive_days_pct", "Positive days", 10.0, True, "pct"),
    ("recent_pnl", "Last 5 sessions", 10.0, True, "inr"),
    ("win_rate", "Win rate", 5.0, True, "fraction"),
)
# The same seven from a desk's trade record. Drawdown is in rupees there: every strategy on a
# desk has the same allocation (or shares one book), so rupees order them as percent would.
POSITION_FACTORS: tuple[Factor, ...] = tuple(
    ("max_drawdown", "Max drawdown", w, hib, "inr") if key == "max_drawdown_pct" else (key, label, w, hib, unit)
    for key, label, w, hib, unit in FACTORS)
NEUTRAL = 50.0
RECENT_SESSIONS = 5
MIN_TRADES = 30


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
    if v is None or isinstance(v, bool):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def active_factors(rows: list[dict], factors: tuple[Factor, ...] = FACTORS) -> tuple[Factor, ...]:
    """The factors at least one traded row has a value for."""
    scored = [r for r in rows if (r.get("trades") or 0) > 0]
    return tuple(f for f in factors if any(_factor_value(r, f[0]) is not None for r in scored))


def rank_rows(rows: list[dict], *, min_trades: int = MIN_TRADES,
              factors: tuple[Factor, ...] = FACTORS) -> list[dict]:
    """Add `rank`, `rank_score` (0-100), `rank_shrunk` and `rank_factors` to every row; return
    them sorted by rank. A row with no closed trades gets no score and sorts last."""
    scored = [r for r in rows if (r.get("trades") or 0) > 0]
    for r in rows:
        r["rank"], r["rank_score"], r["rank_factors"], r["rank_shrunk"] = None, None, [], False

    used = active_factors(rows, factors)
    total_weight = sum(f[2] for f in used)
    pct_by_factor = {f[0]: _percentiles([_factor_value(r, f[0]) for r in scored], f[3]) for f in used}
    for i, r in enumerate(scored):
        total = 0.0
        out = []
        for key, label, weight, hib, unit in used:
            pct = pct_by_factor[key][i]
            total += weight * (NEUTRAL if pct is None else pct)
            out.append({"key": key, "label": label, "weight": round(weight / total_weight * 100.0, 1),
                        "higher_is_better": hib, "unit": unit, "value": r.get(key),
                        "percentile": None if pct is None else round(pct, 1)})
        raw = total / total_weight if total_weight else NEUTRAL
        trust = min(1.0, (r.get("trades") or 0) / max(min_trades, 1))
        r["rank_score"] = round(NEUTRAL + (raw - NEUTRAL) * trust, 1)
        r["rank_factors"] = out
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


def compact(rows: list[dict], factors: tuple[Factor, ...], *, id_key: str = "strategy_id") -> dict:
    """A ranked board as the page needs it: the factor list once, then per strategy its rank,
    score and each factor's value and percentile in that order - not seven dicts a row."""
    used = active_factors(rows, factors)
    total = sum(f[2] for f in used) or 1.0
    ranks = {}
    for r in rows:
        if r.get("rank") is None:
            continue
        by_key = {f["key"]: f for f in r["rank_factors"]}
        ranks[str(r[id_key])] = {
            "rank": r["rank"], "score": r["rank_score"], "shrunk": r["rank_shrunk"],
            "trades": r.get("trades") or 0,
            "values": [by_key.get(f[0], {}).get("value") for f in used],
            "pct": [by_key.get(f[0], {}).get("percentile") for f in used],
        }
    return {
        "factors": [{"key": k, "label": label, "weight": round(w / total * 100.0, 1),
                     "higher_is_better": hib, "unit": unit} for k, label, w, hib, unit in used],
        "ranked": len(ranks), "ranks": ranks,
    }


# -- a desk's trade record -> the seven factors ----------------------------------------------


def stats_from_trades(items, recent: int = RECENT_SESSIONS) -> dict[str, dict]:
    """The same per-strategy figures as `position_stats`, for a desk whose honest P&L is only
    computed in Python (the NIFTY option-buying tournament's real-money estimate). `items`:
    one dict per closed trade with key, pnl, deployed, day and ts (any orderable close time)."""
    by: dict[str, list[dict]] = {}
    for it in items:
        if it.get("key") is not None:
            by.setdefault(str(it["key"]), []).append(it)
    sessions: set[str] = set()
    out: dict[str, dict] = {}
    for key, xs in by.items():
        xs.sort(key=lambda x: (x.get("ts") is None, x.get("ts") or 0))
        pnls = [float(x.get("pnl") or 0.0) for x in xs]
        n, s = len(pnls), sum(pnls)
        mean = s / n
        t = None
        if n >= 2:
            sd = math.sqrt(sum((p - mean) ** 2 for p in pnls) / (n - 1))
            if sd > 0:
                t = round(mean / (sd / math.sqrt(n)), 3)
        gp = sum(p for p in pnls if p > 0)
        gl = -sum(p for p in pnls if p < 0)
        cum = peak = dd = 0.0
        for p in pnls:
            cum += p
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        bps = [float(x.get("pnl") or 0.0) / x["deployed"] for x in xs if (x.get("deployed") or 0) > 0]
        daily: dict[str, float] = {}
        for x in xs:
            day = str(x.get("day") or "")[:10]
            if day:
                daily[day] = daily.get(day, 0.0) + float(x.get("pnl") or 0.0)
                sessions.add(day)
        wins = sum(1 for p in pnls if p > 0)
        out[key] = {
            "trades": n, "wins": wins, "win_rate": round(wins / n, 4), "net_pnl": round(s, 2),
            "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
            "profit_factor": round(gp / gl, 3) if gl > 0 else None, "t_stat": t,
            "net_bp_per_trade": round(sum(bps) / len(bps) * 1e4, 2) if bps else None,
            "max_drawdown": round(dd, 2), "daily": daily,
        }
    ordered_sessions = sorted(sessions)
    for st in out.values():
        st.update(day_factors(st.pop("daily"), ordered_sessions, recent))
    return out


# -- ... or computed inside Mongo, for the desks that store their P&L --------------------------


def _field(expr):
    return f"${expr}" if isinstance(expr, str) else expr


async def position_stats(coll, match: dict, *, key="strategy_id", pnl: str = "realized_pnl",
                         deployed=None, day=None, ts: str = "closed_at",
                         recent: int = RECENT_SESSIONS) -> dict[str, dict]:
    """Per strategy, from its CLOSED trades: trades, wins, net, profit factor, t-stat of the
    per-trade P&L, mean net return per trade in bp of the position, max drawdown in rupees
    (trade by trade, in close order - the same walk as promotion_gate), positive-day share and
    the net over the desk's last `recent` sessions.

    Three aggregations that return about one row per strategy (per strategy-day for the
    second); no trade is shipped to Python. `key`/`deployed`/`day` take a field name or a Mongo
    expression; `day` defaults to `closed_on`, else the IST date of `ts`."""
    k = _field(key)
    p = {"$ifNull": [_field(pnl), 0]}
    d = _field(deployed) if deployed is not None else None
    if day is None:
        day = {"$ifNull": ["$closed_on", {"$dateToString": {
            "format": "%Y-%m-%d", "date": _field(ts), "timezone": "Asia/Kolkata"}}]}
    day_expr = _field(day)

    stats: dict[str, dict] = {}
    async for g in coll.aggregate([
            {"$match": match},
            {"$project": {"_id": 0, "k": k, "p": p, "d": d if d is not None else {"$literal": None}}},
            {"$group": {"_id": "$k", "n": {"$sum": 1}, "s": {"$sum": "$p"},
                        "ss": {"$sum": {"$multiply": ["$p", "$p"]}},
                        "gp": {"$sum": {"$cond": [{"$gt": ["$p", 0]}, "$p", 0]}},
                        "gl": {"$sum": {"$cond": [{"$lt": ["$p", 0]}, {"$subtract": [0, "$p"]}, 0]}},
                        "w": {"$sum": {"$cond": [{"$gt": ["$p", 0]}, 1, 0]}},
                        "bp": {"$avg": {"$cond": [{"$gt": ["$d", 0]}, {"$divide": ["$p", "$d"]}, None]}}}}]):
        if g["_id"] is None:
            continue
        n, s, ss = int(g["n"]), float(g["s"]), float(g["ss"])
        mean = s / n if n else 0.0
        t = None
        if n >= 2:
            var = max((ss - n * mean * mean) / (n - 1), 0.0)
            if var > 0:
                t = round(mean / math.sqrt(var / n), 3)
        gp, gl = float(g["gp"]), float(g["gl"])
        stats[str(g["_id"])] = {
            "trades": n, "wins": int(g["w"]), "win_rate": round(g["w"] / n, 4) if n else 0.0,
            "net_pnl": round(s, 2), "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
            "profit_factor": round(gp / gl, 3) if gl > 0 else None, "t_stat": t,
            "net_bp_per_trade": round(g["bp"] * 1e4, 2) if g.get("bp") is not None else None,
            "max_drawdown": None, "daily": {},
        }

    sessions: set[str] = set()
    async for g in coll.aggregate([
            {"$match": match},
            {"$project": {"_id": 0, "k": k, "p": p, "day": day_expr}},
            {"$group": {"_id": {"k": "$k", "day": "$day"}, "net": {"$sum": "$p"}}}]):
        sid, dd = g["_id"].get("k"), g["_id"].get("day")
        if sid is None or not dd:
            continue
        st = stats.get(str(sid))
        if st is not None:
            st["daily"][str(dd)[:10]] = float(g["net"] or 0.0)
            sessions.add(str(dd)[:10])

    async for g in coll.aggregate([
            {"$match": match},
            {"$project": {"k": k, "p": p, "t": _field(ts)}},
            {"$setWindowFields": {"partitionBy": "$k", "sortBy": {"t": 1, "_id": 1}, "output": {
                "cum": {"$sum": "$p", "window": {"documents": ["unbounded", "current"]}}}}},
            {"$setWindowFields": {"partitionBy": "$k", "sortBy": {"t": 1, "_id": 1}, "output": {
                "peak": {"$max": "$cum", "window": {"documents": ["unbounded", "current"]}}}}},
            {"$group": {"_id": "$k", "dd": {"$max": {"$subtract": [{"$max": ["$peak", 0]}, "$cum"]}}}}]):
        st = stats.get(str(g["_id"]))
        if st is not None:
            st["max_drawdown"] = round(float(g["dd"] or 0.0), 2)

    ordered_sessions = sorted(sessions)
    for st in stats.values():
        st.update(day_factors(st.pop("daily"), ordered_sessions, recent))
    return stats
