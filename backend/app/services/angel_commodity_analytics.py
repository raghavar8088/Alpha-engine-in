"""Analytics for Angel One Commodity Live Trading Data (2026-10-20).

Everything here is computed from what `angel_commodity_ledger` keeps of the owner's REAL Angel
One MCX account - nothing is invented, and nothing here can place an order.

  round trips     every closing order matched first-in-first-out against the open quantity of
                  the same contract: entry and exit prices, holding time, gross P&L in rupees
                  (x the contract's value factor), the charges of the units involved (each
                  order's charges spread over its fills by value) and the net
  trade stats     win rate, average win / loss, payoff, profit factor, expectancy, streaks
  breakdowns      by style (bought / sold calls and puts, futures), commodity, entry hour,
                  weekday, holding period and days to expiry at entry
  performance     over the daily records: drawdown, Sharpe and Sortino on daily ROI (x sqrt 250),
                  profit factor of days, streaks, the ROI distribution
  periods         weekly and monthly totals and ROI on the period's average capital
  risk            the open positions, re-quoted now: implied volatility and Greeks (Black-76 -
                  MCX options are options on FUTURES), days to expiry, moneyness, breakeven,
                  the margin Angel's own calculator gives each position, and what the book
                  gains or loses if the underlying moves, a day passes or volatility shifts

Round-trip P&L is realised first-in-first-out P&L. On a day Angel's API was polled, the daily
table instead shows Angel's own day P&L (marked to market), so the two can differ while a
position is carried overnight - they agree once it is closed.
"""

from __future__ import annotations

import logging
import math
import statistics
import time as _time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from app.services import angel_commodity_ledger as L

logger = logging.getLogger("angel_commodity_analytics")

IST = timezone(timedelta(hours=5, minutes=30))
ANNUAL = 250
R_RATE = 0.065
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_cache: dict[str, tuple[float, dict]] = {}


# ── helpers ─────────────────────────────────────────────────────────────────────


def _mins(t: str | None) -> int | None:
    try:
        h, m, *rest = (t or "").strip().split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _style(kind: str, long: bool) -> str:
    if kind in ("CE", "PE"):
        return f"{'Bought' if long else 'Sold'} {kind}"
    return "Long future" if long else "Short future"


def _hold_bucket(minutes: float | None, days: int) -> str:
    if days >= 1:
        return "Overnight (1 day)" if days == 1 else "2-5 days" if days <= 5 else "More than 5 days"
    if minutes is None:
        return "Same day (time unknown)"
    if minutes < 5:
        return "Under 5 min"
    if minutes < 15:
        return "5-15 min"
    if minutes < 60:
        return "15-60 min"
    if minutes < 180:
        return "1-3 hours"
    return "Over 3 hours, same day"


def _dte_bucket(dte: int | None) -> str:
    if dte is None:
        return "Future / unknown"
    if dte <= 0:
        return "Expiry day"
    if dte <= 3:
        return "1-3 days to expiry"
    if dte <= 7:
        return "4-7 days"
    if dte <= 15:
        return "8-15 days"
    return "More than 15 days"


# ── round trips ─────────────────────────────────────────────────────────────────


def round_trips(all_fills: list[dict]) -> tuple[list[dict], list[dict]]:
    """Closed trades (one per closing order) and what is still open, first-in-first-out."""
    # charges per unit of each fill: its order's charges, spread over the order's fills by value
    by_day: dict[str, list] = defaultdict(list)
    for x in all_fills:
        if x.get("source") != "carried-in":
            by_day[x["date"]].append(x)
    cpu: dict[tuple, float] = {}
    for d, fs in by_day.items():
        _, by_order, _ = L.day_charges(fs, date.fromisoformat(d))
        for x in fs:
            o = by_order.get(str(x.get("orderid") or x.get("fillid")))
            share = (x["value"] / o["turnover"]) if o and o["turnover"] else 0.0
            cpu[(d, x.get("orderid"), x.get("fillid"))] = (o["charges"] * share / x["qty"]) if o and x["qty"] else 0.0

    book: dict[str, list[dict]] = defaultdict(list)
    trips: dict[tuple, dict] = {}
    order_seq: list[tuple] = []
    for x in sorted(all_fills, key=lambda r: (r["date"], r.get("time") or "", r.get("seq", 0))):
        sym = x["tradingsymbol"]
        factor = L.fill_factor(x)
        c = cpu.get((x["date"], x.get("orderid"), x.get("fillid")), 0.0)
        remaining = x["qty"] if x["side"] == "BUY" else -x["qty"]
        lots = book[sym]
        while remaining and lots and (lots[0]["qty"] > 0) != (remaining > 0):
            lot = lots[0]
            take = min(abs(lot["qty"]), abs(remaining))
            long = lot["qty"] > 0
            key = (sym, x["date"], str(x.get("orderid") or x.get("fillid")), long)
            t = trips.get(key)
            if t is None:
                t = trips[key] = {"tradingsymbol": sym, "underlying": x.get("underlying"), "kind": x.get("kind"),
                                  "strike": x.get("strike"), "expiry": x.get("expiry"), "long": long,
                                  "style": _style(x.get("kind") or "FUT", long), "qty": 0.0, "entry_value": 0.0,
                                  "exit_value": 0.0, "gross": 0.0, "charges": 0.0, "factor": factor,
                                  "entry_date": lot["date"], "entry_time": lot["time"], "exit_date": x["date"],
                                  "exit_time": x.get("time"), "lot_units": x.get("lot_units") or lot.get("lot_units"),
                                  "order": str(x.get("orderid") or ""), "source": x.get("source"),
                                  "carried_in": False}
                order_seq.append(key)
            t["qty"] += take
            t["carried_in"] = t["carried_in"] or bool(lot.get("carried"))
            t["entry_value"] += lot["price"] * take
            t["exit_value"] += x["price"] * take
            t["gross"] += (x["price"] - lot["price"]) * take * factor * (1 if long else -1)
            t["charges"] += take * (lot["cpu"] + c)
            if (lot["date"], lot["time"] or "") < (t["entry_date"], t["entry_time"] or ""):
                t["entry_date"], t["entry_time"] = lot["date"], lot["time"]
            if (x.get("time") or "") > (t["exit_time"] or ""):
                t["exit_time"] = x.get("time")
            lot["qty"] += -take if long else take
            remaining += take if remaining < 0 else -take
            if lot["qty"] == 0:
                lots.pop(0)
        if remaining:
            lots.append({"qty": remaining, "price": x["price"], "date": x["date"], "time": x.get("time"), "cpu": c,
                         "lot_units": x.get("lot_units"), "carried": x.get("source") == "carried-in"})
    out = []
    for key in order_seq:
        t = trips[key]
        q = t["qty"]
        t["entry_avg"] = round(t["entry_value"] / q, 4) if q else None
        t["exit_avg"] = round(t["exit_value"] / q, 4) if q else None
        t["gross"] = round(t["gross"], 2)
        t["charges"] = round(t["charges"], 2)
        t["net"] = round(t["gross"] - t["charges"], 2)
        t["lots"] = round(q / t["lot_units"], 2) if t.get("lot_units") else None
        ed, xd = date.fromisoformat(t["entry_date"]), date.fromisoformat(t["exit_date"])
        t["hold_days"] = (xd - ed).days
        a, b = _mins(t["entry_time"]), _mins(t["exit_time"])
        t["hold_minutes"] = (b - a) if (t["hold_days"] == 0 and a is not None and b is not None) else None
        t["hold_bucket"] = _hold_bucket(t["hold_minutes"], t["hold_days"])
        t["entry_hour"] = (a // 60) if a is not None else None
        t["weekday"] = WEEKDAYS[xd.weekday()]
        t["dte_at_entry"] = (date.fromisoformat(t["expiry"]) - ed).days if t.get("expiry") else None
        t["dte_bucket"] = _dte_bucket(t["dte_at_entry"]) if t.get("kind") in ("CE", "PE") else "Future / unknown"
        premium = t["entry_value"] * t["factor"]
        if t["long"] and t["kind"] in ("CE", "PE") and premium:
            t["return_on_premium"] = round(t["net"] / premium, 4)
        for k in ("entry_value", "exit_value"):
            t.pop(k, None)
        out.append(t)
    open_lots = []
    for sym, lots in book.items():
        q = sum(l["qty"] for l in lots)
        if q:
            open_lots.append({"tradingsymbol": sym, "qty": q, "avg": round(sum(l["qty"] * l["price"] for l in lots) / q, 4),
                              "since": min((l["date"], l["time"] or "") for l in lots)[0]})
    return out, open_lots


def trade_stats(trips: list[dict]) -> dict:
    n = len(trips)
    if not n:
        return {"trades": 0}
    nets = [t["net"] for t in trips]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    streak_w = streak_l = best_w = best_l = 0
    for x in nets:
        if x > 0:
            streak_w, streak_l = streak_w + 1, 0
        elif x < 0:
            streak_l, streak_w = streak_l + 1, 0
        best_w, best_l = max(best_w, streak_w), max(best_l, streak_l)
    holds = [t["hold_minutes"] for t in trips if t.get("hold_minutes") is not None]
    gross = sum(t["gross"] for t in trips)
    charges = sum(t["charges"] for t in trips)
    return {
        "trades": n, "wins": len(wins), "losses": len(losses), "win_rate": len(wins) / n,
        "avg_win": statistics.mean(wins) if wins else None, "avg_loss": statistics.mean(losses) if losses else None,
        "payoff": (statistics.mean(wins) / abs(statistics.mean(losses))) if wins and losses else None,
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses else None,
        "expectancy": statistics.mean(nets), "median": statistics.median(nets),
        "largest_win": max(nets), "largest_loss": min(nets),
        "gross": round(gross, 2), "charges": round(charges, 2), "net": round(sum(nets), 2),
        "charges_share_of_gross": (charges / gross) if gross > 0 else None,
        "max_win_streak": best_w, "max_loss_streak": best_l,
        "current_streak": (streak_w if streak_w else -streak_l),
        "avg_hold_minutes": statistics.mean(holds) if holds else None,
        "median_hold_minutes": statistics.median(holds) if holds else None,
        "overnight_trades": sum(1 for t in trips if t["hold_days"] > 0),
    }


def breakdown(trips: list[dict], key: str, order: list[str] | None = None) -> list[dict]:
    groups: dict = defaultdict(list)
    for t in trips:
        groups[t.get(key)].append(t)
    rows = []
    for k, ts in groups.items():
        nets = [t["net"] for t in ts]
        rows.append({"key": str(k), "trades": len(ts), "wins": sum(1 for x in nets if x > 0),
                     "win_rate": sum(1 for x in nets if x > 0) / len(ts), "gross": round(sum(t["gross"] for t in ts), 2),
                     "charges": round(sum(t["charges"] for t in ts), 2), "net": round(sum(nets), 2),
                     "avg_net": round(statistics.mean(nets), 2)})
    if order:
        rank = {k: i for i, k in enumerate(order)}
        rows.sort(key=lambda r: rank.get(r["key"], 999))
    else:
        rows.sort(key=lambda r: -r["net"])
    return rows


# ── performance over the daily records ──────────────────────────────────────────


def performance(days: list[dict]) -> dict:
    ds = sorted((d for d in days if d.get("capital") and d.get("net_pnl") is not None), key=lambda d: d["date"])
    if not ds:
        return {"days": 0}
    nets = [d["net_pnl"] for d in ds]
    rois = [d["roi"] for d in ds if d.get("roi") is not None]
    cum, peak, series = 0.0, 0.0, []
    max_dd, dd_from, dd_to, cur_start, longest, run = 0.0, None, None, None, 0, 0
    peak_date = ds[0]["date"]
    for d in ds:
        cum += d["net_pnl"]
        if cum >= peak:
            peak, peak_date, run = cum, d["date"], 0
        else:
            run += 1
            longest = max(longest, run)
        dd = cum - peak
        if dd < max_dd:
            max_dd, dd_from, dd_to = dd, peak_date, d["date"]
        series.append({"date": d["date"], "cum": round(cum, 2), "drawdown": round(dd, 2)})
    avg_cap = statistics.mean(d["capital"] for d in ds)
    mean_r = statistics.mean(rois) if rois else None
    sd_r = statistics.stdev(rois) if len(rois) > 1 else None
    down = math.sqrt(statistics.mean([min(r, 0.0) ** 2 for r in rois])) if rois else None
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    streak = 0
    for x in reversed(nets):
        if x > 0 and streak >= 0:
            streak += 1
        elif x < 0 and streak <= 0:
            streak -= 1
        else:
            break
    best = max(ds, key=lambda d: d["net_pnl"])
    worst = min(ds, key=lambda d: d["net_pnl"])
    max_dd_pct = (max_dd / avg_cap) if avg_cap else None
    return {
        "days": len(ds), "series": series, "max_drawdown": round(max_dd, 2), "max_drawdown_pct_avg_capital": max_dd_pct,
        "drawdown_from": dd_from, "drawdown_to": dd_to, "current_drawdown": series[-1]["drawdown"],
        "longest_drawdown_days": longest, "peak": round(peak, 2),
        "mean_roi": mean_r, "median_roi": statistics.median(rois) if rois else None, "sd_roi": sd_r,
        "sharpe": (mean_r / sd_r * math.sqrt(ANNUAL)) if (mean_r is not None and sd_r) else None,
        "sortino": (mean_r / down * math.sqrt(ANNUAL)) if (mean_r is not None and down) else None,
        "calmar": ((mean_r * ANNUAL) / abs(max_dd_pct)) if (mean_r is not None and max_dd_pct) else None,
        "green_days": len(wins), "red_days": len(losses), "avg_green": statistics.mean(wins) if wins else None,
        "avg_red": statistics.mean(losses) if losses else None,
        "profit_factor_days": (sum(wins) / abs(sum(losses))) if losses else None,
        "best": {"date": best["date"], "net": best["net_pnl"], "roi": best.get("roi")},
        "worst": {"date": worst["date"], "net": worst["net_pnl"], "roi": worst.get("roi")},
        "current_streak": streak, "histogram": histogram([r * 100 for r in rois], 10),
    }


def histogram(values: list[float], bins: int) -> list[dict]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [{"from": lo, "to": hi, "count": len(values)}]
    w = (hi - lo) / bins
    out = [{"from": round(lo + i * w, 4), "to": round(lo + (i + 1) * w, 4), "count": 0} for i in range(bins)]
    for v in values:
        out[min(bins - 1, int((v - lo) / w))]["count"] += 1
    return out


def periods(days: list[dict]) -> dict:
    def agg(keyfn) -> list[dict]:
        g: dict[str, list] = defaultdict(list)
        for d in days:
            if d.get("capital") and d.get("net_pnl") is not None:
                g[keyfn(date.fromisoformat(d["date"]))].append(d)
        rows = []
        for k, ds in sorted(g.items(), reverse=True):
            net = sum(d["net_pnl"] for d in ds)
            cap = statistics.mean(d["capital"] for d in ds)
            rows.append({"period": k, "days": len(ds), "net": round(net, 2), "charges": round(sum(d.get("charges") or 0 for d in ds), 2),
                         "avg_capital": round(cap, 2), "roi": (net / cap) if cap else None,
                         "green_days": sum(1 for d in ds if d["net_pnl"] > 0),
                         "best": max(d["net_pnl"] for d in ds), "worst": min(d["net_pnl"] for d in ds),
                         "turnover": round(sum(d.get("turnover") or 0 for d in ds), 2)})
        return rows

    weeks = agg(lambda d: f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}")
    months = agg(lambda d: d.strftime("%Y-%m"))
    heat = [{"year": int(m["period"][:4]), "month": int(m["period"][5:7]), "return_pct": round((m["roi"] or 0) * 100, 3)}
            for m in months]
    return {"weeks": weeks, "months": months, "heatmap": heat}


def charges_summary(days: list[dict], trips: list[dict]) -> dict:
    parts = {k: 0.0 for k in L.COMPONENTS}
    total = turnover = gross_pos = 0.0
    orders = 0
    rows = []
    for d in sorted(days, key=lambda d: d["date"], reverse=True):
        b = d.get("charges_breakdown") or {}
        for k in L.COMPONENTS:
            parts[k] += b.get(k, 0.0)
        total += d.get("charges") or 0.0
        turnover += d.get("turnover") or 0.0
        orders += d.get("orders") or 0
        g = d.get("gross_pnl") if d.get("basis") == "angel-api" else d.get("realised_fifo")
        gross_pos += max(g or 0.0, 0.0)
        rows.append({"date": d["date"], "charges": d.get("charges"), "breakdown": b, "orders": d.get("orders"),
                     "turnover": d.get("turnover"), "gross": g})
    return {"total": round(total, 2), "by_component": {k: round(v, 2) for k, v in parts.items()},
            "turnover": round(turnover, 2), "orders": orders,
            "per_order": (total / orders) if orders else None, "per_trade": (total / len(trips)) if trips else None,
            "pct_of_turnover": (total / turnover) if turnover else None,
            "pct_of_gross_profit_days": (total / gross_pos) if gross_pos else None, "days": rows}


def orders_summary(orders: list[dict]) -> dict:
    by_status: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    reasons: dict[str, int] = defaultdict(int)
    slip = []
    for o in orders:
        st = (o.get("status") or "unknown").lower()
        by_status[st] += 1
        by_type[(o.get("ordertype") or "?").upper()] += 1
        if st == "rejected" and o.get("text"):
            reasons[o["text"][:140]] += 1
        if (o.get("ordertype") or "").upper() == "LIMIT" and o.get("price") and o.get("avg_price") and o.get("filled"):
            sign = 1 if (o.get("side") or "").upper() == "BUY" else -1
            slip.append(sign * (o["avg_price"] - o["price"]))
    return {"orders": len(orders), "by_status": dict(by_status), "by_type": dict(by_type),
            "rejections": sorted(({"reason": k, "count": v} for k, v in reasons.items()), key=lambda r: -r["count"])[:10],
            "limit_fill_vs_limit_price": (statistics.mean(slip) if slip else None), "limit_fills": len(slip)}


def coverage(days: list[dict]) -> dict:
    if not days:
        return {"days": 0}
    ds = sorted(d["date"] for d in days)
    have = set(ds)
    first, last = date.fromisoformat(ds[0]), date.fromisoformat(ds[-1])
    gaps, d = [], first
    while d <= last:
        if d.weekday() < 5 and d.isoformat() not in have:
            gaps.append(d.isoformat())
        d += timedelta(days=1)
    return {"days": len(ds), "first": ds[0], "last": ds[-1],
            "live": sum(1 for x in days if x.get("basis") == "angel-api"),
            "imported": sum(1 for x in days if x.get("basis") == "imported"),
            "weekdays_without_a_record": gaps[-60:]}


async def openings() -> list[dict]:
    """Positions that were ALREADY open when this module first saw the account: Angel's own
    carry-forward quantity and price on the earliest polled day, as opening lots dated the
    day before. Without them a buy that closes an older short reads as a new long. Skipped
    when imported history reaches back before that day (it carries the inventory itself)."""
    first = await L.days.find_one({"basis": "angel-api"}, sort=[("_id", 1)])
    if not first:
        return []
    d0 = first["_id"]
    if await L.fills.find_one({"date": {"$lt": d0}}):
        return []
    eve = (date.fromisoformat(d0) - timedelta(days=1)).isoformat()
    out = []
    for p in first.get("positions") or []:
        q = p.get("cf_qty") or 0.0
        price = (p.get("cf_buyavg") if q > 0 else p.get("cf_sellavg")) or 0.0
        if not q or not price:
            continue
        sym = L.parse_symbol(p["tradingsymbol"])
        factor = L.spec_factor(p.get("underlying") or sym["underlying"], p.get("lot_units")) or 1.0
        out.append({"date": eve, "time": "00:00:00", "seq": -1, "tradingsymbol": p["tradingsymbol"],
                    "underlying": p.get("underlying") or sym["underlying"], "expiry": p.get("expiry") or sym["expiry"],
                    "strike": p.get("strike") or sym["strike"], "kind": sym["kind"], "side": "BUY" if q > 0 else "SELL",
                    "qty": abs(q), "price": price, "value": round(price * abs(q) * factor, 2), "value_factor": factor,
                    "lot_units": p.get("lot_units"), "orderid": f"carry-{p['tradingsymbol']}", "fillid": "carry",
                    "source": "carried-in"})
    return out


async def analytics() -> dict:
    hit = _cache.get("analytics")
    if hit and _time.monotonic() - hit[0] < 45:
        return hit[1]
    fills = [x async for x in L.fills.find({}, {"_id": 0})] + await openings()
    days = [{**d, "date": d["_id"]} async for d in L.days.find({"active": True}, {"positions": 0})]
    orders = [o async for o in L.orders.find({}, {"_id": 0})]
    trips, open_lots = round_trips(fills)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trips": list(reversed(trips))[:600], "trip_count": len(trips), "open_fifo": open_lots,
        "stats": trade_stats(trips),
        "by_style": breakdown(trips, "style", ["Bought CE", "Sold CE", "Bought PE", "Sold PE", "Long future", "Short future"]),
        "by_underlying": breakdown(trips, "underlying"),
        "by_hour": breakdown(trips, "entry_hour", [str(h) for h in range(8, 24)] + ["None"]),
        "by_weekday": breakdown(trips, "weekday", WEEKDAYS),
        "by_hold": breakdown(trips, "hold_bucket", ["Under 5 min", "5-15 min", "15-60 min", "1-3 hours",
                                                   "Over 3 hours, same day", "Same day (time unknown)",
                                                   "Overnight (1 day)", "2-5 days", "More than 5 days"]),
        "by_dte": breakdown(trips, "dte_bucket", ["Expiry day", "1-3 days to expiry", "4-7 days", "8-15 days",
                                                  "More than 15 days", "Future / unknown"]),
        "performance": performance(days), "periods": periods(days), "charges": charges_summary(days, trips),
        "orders": orders_summary(orders), "coverage": coverage(days),
    }
    _cache["analytics"] = (_time.monotonic(), out)
    return out


async def day_detail(day: str) -> dict:
    d = await L.days.find_one({"_id": day})
    if not d:
        return {"date": day, "found": False}
    d = L._clean(d) | {"date": day, "found": True}
    fs = [L._clean(x) async for x in L.fills.find({"date": day}).sort([("time", 1), ("seq", 1)])]
    os_ = [L._clean(x) async for x in L.orders.find({"date": day}).sort("time", 1)]
    pts = [L._clean(x) async for x in L.points.find({"date": day}).sort("slot", 1)]
    all_fills = [x async for x in L.fills.find({"date": {"$lte": day}}, {"_id": 0})] + await openings()
    trips, _ = round_trips(all_fills)
    _, by_order, _ = L.day_charges([x async for x in L.fills.find({"date": day}, {"_id": 0})], date.fromisoformat(day))
    return {"day": d, "fills": fs, "orders": os_, "points": pts,
            "trips": [t for t in trips if t["exit_date"] == day],
            "order_charges": [{"order": k, "turnover": round(v["turnover"], 2), "charges": v["charges"],
                               "breakdown": v.get("breakdown")} for k, v in by_order.items()]}


# ── risk: the open positions, re-quoted now ─────────────────────────────────────


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def b76(F: float, K: float, T: float, sig: float, call: bool) -> float:
    D = math.exp(-R_RATE * T)
    if T <= 0 or sig <= 0:
        return D * max(0.0, (F - K) if call else (K - F))
    v = sig * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    return D * (F * _ncdf(d1) - K * _ncdf(d2)) if call else D * (K * _ncdf(-d2) - F * _ncdf(-d1))


def implied_vol(price: float, F: float, K: float, T: float, call: bool) -> float | None:
    if price <= 0 or T <= 0:
        return None
    intrinsic = math.exp(-R_RATE * T) * max(0.0, (F - K) if call else (K - F))
    if price <= intrinsic + 1e-6:
        return None
    lo, hi = 0.005, 5.0
    if b76(F, K, T, hi, call) < price:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if b76(F, K, T, mid, call) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def greeks(F: float, K: float, T: float, sig: float, call: bool) -> dict:
    """Per unit of the underlying: delta, gamma, theta per calendar day, vega per vol point."""
    D = math.exp(-R_RATE * T)
    v = sig * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    price = b76(F, K, T, sig, call)
    delta = D * _ncdf(d1) if call else -D * _ncdf(-d1)
    gamma = D * _npdf(d1) / (F * v)
    vega = D * F * _npdf(d1) * math.sqrt(T) / 100.0
    theta_year = -(D * F * _npdf(d1) * sig) / (2.0 * math.sqrt(T)) + R_RATE * price
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta_year / 365.0}


def _years_to(expiry: str | None, now: datetime) -> float:
    if not expiry:
        return 0.0
    end = datetime.fromisoformat(expiry).replace(hour=23, minute=30, tzinfo=IST)   # MCX settles at the session's end
    return max((end - now).total_seconds(), 60.0) / (365.0 * 86400.0)


SCENARIOS = [-0.05, -0.03, -0.02, -0.01, -0.005, 0.0, 0.005, 0.01, 0.02, 0.03, 0.05]


async def risk() -> dict:
    hit = _cache.get("risk")
    if hit and _time.monotonic() - hit[0] < 30:
        return hit[1]
    from app.services import commodity_positions as CP
    from app.services.commodity_broker_margin import basket_margin
    now = datetime.now(IST)
    today = now.date().isoformat()
    doc = await L.days.find_one({"_id": today}) or await L.days.find_one({"basis": "angel-api"}, sort=[("_id", -1)])
    positions = []
    for p in (doc or {}).get("positions") or []:
        if not p.get("netqty"):
            continue
        # snapshots written before 2026-10-20 carry no kind / expiry / strike / token: derive
        # them from the trading symbol and the instrument master rather than fail on them
        sym = L.parse_symbol(p["tradingsymbol"])
        p = {**p, "underlying": sym["underlying"] or p.get("underlying"), "kind": p.get("kind") or sym["kind"],
             "expiry": p.get("expiry") or sym["expiry"], "strike": p.get("strike") or sym["strike"]}
        if not p.get("token"):
            from app.core.db import instruments_collection
            inst = await instruments_collection.find_one({"angel_tradingsymbol": p["tradingsymbol"]}, {"angel_token": 1})
            p["token"] = str(inst["angel_token"]) if inst and inst.get("angel_token") else None
        positions.append(p)
    if not positions:
        out = {"as_of": (doc or {}).get("updated_at"), "positions": [], "note": "No open MCX positions in the latest snapshot."}
        _cache["risk"] = (_time.monotonic(), out)
        return out
    # the future each option is written on, and fresh prices for everything
    fut_of: dict[str, dict | None] = {}
    for p in positions:
        if p["kind"] in ("CE", "PE"):
            k = f"{p['underlying']}|{p.get('expiry')}"
            if k not in fut_of:
                fut_of[k] = await CP.underlying_future(p["underlying"], p.get("expiry"))
    tokens = [p["token"] for p in positions if p.get("token")] + [str(f["angel_token"]) for f in fut_of.values() if f]
    try:
        px = await CP._quote_tokens(tokens)
    except Exception:  # noqa: BLE001 - the page still shows the snapshot prices
        px = {}
    rows, legs_all = [], []
    totals: dict[str, dict] = defaultdict(lambda: {"delta_rupees_1pct": 0.0, "theta_day": 0.0, "vega_point": 0.0,
                                                   "gamma_rupees_1pct": 0.0, "value": 0.0, "positions": 0})
    grid = {m: 0.0 for m in SCENARIOS}
    tomorrow = 0.0
    iv_down = iv_up = 0.0
    for p in positions:
        qty = p["netqty"]
        lot = p.get("lot_units") or 1.0
        factor = L.spec_factor(p["underlying"], lot) or 1.0
        ltp = float(px.get(p.get("token") or "", 0.0) or p.get("ltp") or 0.0)
        row = {"tradingsymbol": p["tradingsymbol"], "underlying": p["underlying"], "kind": p["kind"],
               "strike": p.get("strike"), "expiry": p.get("expiry"), "product": p.get("product"), "qty": qty,
               "lots": round(qty / lot, 2), "ltp": ltp, "factor": factor,
               "avg": p.get("netavg") or (p.get("buyavg") if qty > 0 else p.get("sellavg")),
               "dte": (date.fromisoformat(p["expiry"]) - now.date()).days if p.get("expiry") else None}
        family = CP.family_of(p["underlying"])
        mult = CP.multiplier(p["underlying"])
        if p["kind"] in ("CE", "PE"):
            fut = fut_of.get(f"{p['underlying']}|{p.get('expiry')}")
            F = float(px.get(str((fut or {}).get("angel_token") or ""), 0.0) or 0.0)
            K = float(p.get("strike") or 0.0)
            call = p["kind"] == "CE"
            T = _years_to(p.get("expiry"), now)
            row.update({"future": (fut or {}).get("symbol") or (fut or {}).get("angel_tradingsymbol"), "future_price": F or None})
            if F > 0 and K > 0 and ltp > 0:
                iv = implied_vol(ltp, F, K, T, call)
                row["iv"] = iv
                sig = iv or 0.30
                g = greeks(F, K, T, sig, call)
                units = qty * factor
                row.update({"delta": g["delta"], "theta_day": g["theta"] * units, "vega_point": g["vega"] * units,
                            "delta_rupees_1pct": g["delta"] * units * F * 0.01,
                            "gamma_rupees_1pct": 0.5 * g["gamma"] * (F * 0.01) ** 2 * units,
                            "iv_assumed": iv is None})
                intrinsic = max(0.0, (F - K) if call else (K - F))
                row.update({"intrinsic": intrinsic, "time_value": max(0.0, ltp - intrinsic),
                            "moneyness_pct": ((F - K) / K) if call else ((K - F) / K)})
                row["moneyness"] = "ATM" if abs(F - K) / K < 0.005 else ("ITM" if row["moneyness_pct"] > 0 else "OTM")
                avg = row["avg"] or 0.0
                row["breakeven"] = (K + avg) if call else (K - avg)
                base = b76(F, K, T, sig, call)
                for m in SCENARIOS:
                    grid[m] += (b76(F * (1 + m), K, T, sig, call) - base) * units
                tomorrow += (b76(F, K, max(T - 1 / 365, 1e-6), sig, call) - base) * units
                iv_down += (b76(F, K, T, sig * 0.8, call) - base) * units
                iv_up += (b76(F, K, T, sig * 1.2, call) - base) * units
                t = totals[p["underlying"]]
                for k in ("delta_rupees_1pct", "theta_day", "vega_point", "gamma_rupees_1pct"):
                    t[k] += row[k]
            notional = K * mult
        else:
            F = ltp
            units = qty * factor
            row.update({"delta": 1.0, "delta_rupees_1pct": units * F * 0.01, "theta_day": 0.0, "vega_point": 0.0})
            for m in SCENARIOS:
                grid[m] += F * m * units
            totals[p["underlying"]]["delta_rupees_1pct"] += row["delta_rupees_1pct"]
            notional = F * mult
        totals[p["underlying"]]["value"] += ltp * qty * factor
        totals[p["underlying"]]["positions"] += 1
        leg = {"symbol": p["underlying"], "family": family, "kind": "OPTION" if p["kind"] in ("CE", "PE") else "FUTURE",
               "side": "BUY" if qty > 0 else "SELL", "lots": max(1, int(round(abs(qty) / lot))), "notional": notional,
               "token": p.get("token"), "order_qty": int(lot), "product": "INTRADAY" if p.get("product") == "INTRADAY" else "MARGIN"}
        legs_all.append(leg)
        try:
            m_, src, _note = await basket_margin([leg], 1)
            row.update({"margin": m_, "margin_source": src})
        except Exception:  # noqa: BLE001
            row.update({"margin": None, "margin_source": "unavailable"})
        if qty > 0 and p["kind"] in ("CE", "PE"):
            row["capital"] = ltp * qty * factor        # a bought option ties up its premium
        else:
            row["capital"] = row.get("margin")
        rows.append(row)
    try:
        basket, bsrc, bnote = await basket_margin(legs_all, 1)
    except Exception:  # noqa: BLE001
        basket, bsrc, bnote = None, "unavailable", ""
    out = {
        "as_of": now.isoformat(), "positions": rows,
        "by_underlying": [{"underlying": k, **{kk: round(vv, 2) for kk, vv in v.items()}} for k, v in totals.items()],
        "scenarios": [{"move_pct": m * 100, "pnl": round(v, 2)} for m, v in grid.items()],
        "one_day_no_move": round(tomorrow, 2), "iv_minus_20pct": round(iv_down, 2), "iv_plus_20pct": round(iv_up, 2),
        "basket_margin": basket, "basket_margin_source": bsrc, "basket_margin_note": bnote,
        "angel_in_use": (doc or {}).get("capital_now"),
        "note": ("Greeks by Black-76 on the underlying future, at the option's implied volatility from its last price; "
                 "scenarios re-price every option at the moved future with that volatility held. Margin per position is "
                 "Angel's own calculator where it answers, else its measured rate."),
    }
    _cache["risk"] = (_time.monotonic(), out)
    return out
