"""One history reader for every desk in the app.

Each desk stores positions in its own collection with its own capital, its own field for
"money at risk" and — sometimes — its own equity snapshots. What a user wants to know is
identical in all of them: when did this start, how many days has it run, what did each day
make, and what is that as a return. Writing that ten times would guarantee ten subtly
different definitions of "ROI", so it is written once here and each desk registers its
shape.

TWO ROI DENOMINATORS PER DAY, because they answer different questions and disagree wildly
on desks that deploy a fraction of their capital: ROI on the desk's own capital says what
the book returned, ROI on capital actually deployed says how the trades themselves went. A
desk holding Rs10 crore and risking Rs1.4 crore looks flat on the first and meaningful on
the second; both are true.

EQUITY CURVES come from snapshots where a desk records them, and are DERIVED by running
totals over closed trades where it does not (F&O accounts keep no snapshots). A derived
curve is marked as such in the payload, because it moves only when a trade closes and will
look like a staircase next to a sampled one — that is a real difference, not a glitch.

AVERAGE PER DAY is reported two ways for the same reason a batting average is not runs per
match: `avg_per_trading_day` divides by days that actually had closes, `avg_per_calendar_day`
by days since the desk started. A desk that traded twice in three months flatters itself
badly on the first.
"""

from datetime import date, datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection

from app.services.call_engine import IST


def _day(dt) -> str | None:
    if not dt:
        return None
    if isinstance(dt, str):
        return dt[:10]
    try:
        return dt.astimezone(IST).date().isoformat()
    except (ValueError, AttributeError):
        return None


async def history(
    positions: AsyncIOMotorCollection,
    capital: float,
    *,
    match: dict | None = None,
    equity: AsyncIOMotorCollection | None = None,
    equity_match: dict | None = None,
    deployed_field: str = "capital_deployed",
    days: int = 365,
    equity_points: int = 600,
) -> dict:
    """Start date, day count, per-day P&L/ROI, averages and an equity curve."""
    base = dict(match or {})
    closed_q = {**base, "status": {"$ne": "OPEN"}}

    buckets: dict[str, dict] = {}
    first_open: str | None = None
    total_fees = 0.0
    async for p in positions.find(
        closed_q,
        {"realized_pnl": 1, "fees": 1, "gross_pnl": 1, "closed_at": 1, "closed_on": 1,
         "opened_at": 1, deployed_field: 1},
    ):
        d = p.get("closed_on") or _day(p.get("closed_at"))
        o = _day(p.get("opened_at"))
        if o and (first_open is None or o < first_open):
            first_open = o
        if not d:
            continue
        b = buckets.setdefault(d, {"date": d, "trades": 0, "wins": 0, "realized_pnl": 0.0,
                                   "fees": 0.0, "deployed": 0.0})
        net = float(p.get("realized_pnl") or 0.0)
        fee = float(p.get("fees") or 0.0)
        b["trades"] += 1
        b["wins"] += 1 if net > 0 else 0
        b["realized_pnl"] += net
        b["fees"] += fee
        dep = float(p.get(deployed_field) or 0.0)
        b["deployed"] += dep
        b["with_deployed"] = b.get("with_deployed", 0) + (1 if dep else 0)
        total_fees += fee

    rows = sorted(buckets.values(), key=lambda r: r["date"])
    for r in rows:
        for k in ("realized_pnl", "fees", "deployed"):
            r[k] = round(r[k], 2)
        r["win_rate"] = round(r["wins"] / r["trades"], 4) if r["trades"] else 0.0
        r["roi_pct"] = round(r["realized_pnl"] / capital * 100, 4) if capital else 0.0
        # Only quote a deployed return when most of the day's trades actually recorded
        # what they had at risk. F&O releases margin on close and zeroes the field, so a
        # naive sum divides a full day's P&L by the handful of rows that kept a value and
        # invents a spectacular percentage. None means "not knowable", not "zero".
        covered = r.pop("with_deployed", 0)
        r["deployed_coverage"] = round(covered / r["trades"], 3) if r["trades"] else 0.0
        r["deployed_roi_pct"] = (round(r["realized_pnl"] / r["deployed"] * 100, 3)
                                 if r["deployed"] and r["deployed_coverage"] >= 0.8 else None)

    covered_rows = sum(1 for r in rows if (r.get("deployed_coverage") or 0) >= 0.8)
    deployed_known = covered_rows == len(rows) and bool(rows)
    realized = round(sum(r["realized_pnl"] for r in rows), 2)
    trades = sum(r["trades"] for r in rows)
    wins = sum(r["wins"] for r in rows)
    deployed_total = round(sum(r["deployed"] for r in rows), 2)

    started_on = rows[0]["date"] if rows else first_open
    today = datetime.now(IST).date()
    days_live = ((today - date.fromisoformat(started_on)).days + 1) if started_on else 0
    days_traded = len(rows)

    # open exposure, for the "still at risk" figure
    open_deployed = open_unreal = 0.0
    open_n = 0
    async for p in positions.find({**base, "status": "OPEN"},
                                  {deployed_field: 1, "unrealized_pnl": 1}):
        open_deployed += float(p.get(deployed_field) or 0.0)
        open_unreal += float(p.get("unrealized_pnl") or 0.0)
        open_n += 1

    curve: list[dict] = []
    derived = True
    if equity is not None:
        async for e in equity.find(equity_match or {}, {"ts": 1, "equity": 1}).sort("ts", -1).limit(equity_points):
            if e.get("equity") is not None and e.get("ts") is not None:
                curve.append({"ts": e["ts"].isoformat(), "value": round(float(e["equity"]), 2)})
        curve.reverse()
        derived = not curve
    if not curve:
        # No snapshots: rebuild the curve from closed trades. Steps on close, by design.
        run = capital
        for r in rows:
            run += r["realized_pnl"]
            curve.append({"ts": r["date"], "value": round(run, 2)})

    equity_now = round(capital + realized + open_unreal, 2)
    return {
        "started_on": started_on,
        "days_live": days_live,
        "days_traded": days_traded,
        "capital": round(capital, 2),
        "equity": equity_now,
        "realized_pnl": realized,
        "unrealized_pnl": round(open_unreal, 2),
        "total_fees": round(total_fees, 2),
        "trades": trades,
        "wins": wins,
        "win_rate": round(wins / trades, 4) if trades else 0.0,
        "roi_pct": round((realized + open_unreal) / capital * 100, 4) if capital else 0.0,
        "deployed_now": round(open_deployed, 2),
        "open_positions": open_n,
        # Same rule at desk level: an unknowable number is reported as unknown.
        "deployed_roi_pct": (round(realized / deployed_total * 100, 3)
                             if deployed_total and deployed_known else None),
        "deployed_total": deployed_total,
        "deployed_known": deployed_known,
        "deployed_note": None if deployed_known else
        "this desk clears its margin/size fields when a position closes, so return on "
        "capital-at-risk cannot be reconstructed for closed trades",
        # Two averages; see the module note on why one number would mislead.
        "avg_per_trading_day": round(realized / days_traded, 2) if days_traded else 0.0,
        "avg_per_calendar_day": round(realized / days_live, 2) if days_live else 0.0,
        "avg_roi_per_trading_day_pct": (round(realized / days_traded / capital * 100, 4)
                                        if days_traded and capital else 0.0),
        "daily": list(reversed(rows))[:days],
        "curve": curve[-equity_points:],
        "curve_is_derived": derived,
    }
