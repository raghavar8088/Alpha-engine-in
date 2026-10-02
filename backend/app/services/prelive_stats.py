"""Honest per-strategy records for the Pre-Live buying tournament (U0 of the 2026-10-02 plan).

What the old leaderboard showed and why it misled:
  - it RANKED 148 strategies by net P&L after 45 sessions — with no strategy able to predict
    NIFTY's direction, that ranking is luck (the first half's top quarter did worse than
    average in the second half), and about 3 of 148 look "significant" by chance alone;
  - its top rows were ANTI-<name>: read-time sign flips of the worst records, never traded;
  - P&L was paper: filled at the option's last traded price, Dhan-style brokerage, no STT
    before 2026-10-02, 75 units to a lot when NIFTY's lot is 65.

This module computes, per strategy: trades, paper net, the t-stat of its per-trade P&L, how
often NIFTY actually moved the bought option's way between entry and exit (the direction
test — no option price needed), the mix of days to expiry it really traded (the instrument
master was stale, so many "weekly" buys were monthlies), and a REAL-MONEY estimate: today's
65 lot, bought at the ask and sold at the bid (measured from the order book on trades from
2026-10-05; an estimated half spread on older ones), Angel One's rate card. Nothing is ranked.
"""

from __future__ import annotations

import asyncio
import math
import os
import statistics
import time
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from app.core.db import db
from tradingai_shared.option_fees import option_round_trip

IST = timezone(timedelta(hours=5, minutes=30))
trades_coll = db["prelive_trades"]
LOT_NOW = int(os.getenv("NIFTY_LOT_SIZE", "65"))
EST_HALF_SPREAD_PCT = float(os.getenv("PRELIVE_EST_HALF_SPREAD_PCT", "0.0025"))
# The NIFTY expiries the instrument master held from July until the 2026-10-02 sync. The desk
# took the nearest one >= the session, so this list reconstructs every older trade's expiry
# (Dhan re-uses security ids, so the master itself can no longer answer for old contracts).
OLD_MASTER_EXPIRIES = ["2026-07-14", "2026-07-21", "2026-07-28", "2026-08-04", "2026-08-11", "2026-08-25",
                       "2026-09-29", "2026-12-29", "2027-03-30"]
LUCK_P = 0.02275          # P(t > 2) for a strategy with no edge
_cache: dict = {"at": 0.0, "data": None}


def _ist(v):
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            return None
    if v is None:
        return None
    return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(IST)


def true_expiry(t: dict) -> str | None:
    if t.get("expiry"):
        return t["expiry"]
    s = t.get("session")
    if not s or s > "2026-10-02":
        return None
    return next((e for e in OLD_MASTER_EXPIRIES if e >= s), None)


def real_money(t: dict) -> tuple[float, str]:
    """(real-money net of one trade — the lots it actually traded, at today's lot size — basis).
    Old trades carry no lot count: 75 units was one lot then, so qty/75 lots (the early basket
    mode traded 20 lots = 1,500 units)."""
    if t.get("real_pnl") is not None and t.get("lot_size") == LOT_NOW:
        return float(t["real_pnl"]), t.get("real_basis") or "book"
    lots = int(t.get("lots") or max(1, round(float(t.get("qty") or 75) / float(t.get("lot_size") or 75))))
    qty = lots * LOT_NOW
    e, x = float(t["entry_premium"]), float(t["exit_premium"])
    hs = lambda p: max(0.05, p * EST_HALF_SPREAD_PCT)  # noqa: E731
    re, rx = e + hs(e), max(0.05, x - hs(x))
    fees = option_round_trip(re, rx, qty, on=t.get("session"))["total"]
    return round((rx - re) * qty - fees, 2), "estimated"


def _nifty_5m():
    from app.services.intraday_store import read_file
    b = read_file("NIFTY", "5m")
    return list(b.t), list(b.c)


def _compute(trades: list[dict]) -> dict:
    nt, nc = _nifty_5m()

    def spot_at(ts):
        if ts is None:
            return None
        e = int(ts.timestamp())
        i = bisect_right(nt, e - 300) - 1
        return nc[i] if i >= 0 and e - nt[i] < 1800 else None

    per: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        per[t["key"]].append(t)
    rows = []
    dte_all = defaultdict(lambda: [0, 0.0])
    for key, xs in per.items():
        nets = [float(x["pnl"]) for x in xs]
        reals, bases = [], set()
        hits = hits_n = 0
        dte_mix = defaultdict(int)
        for x in xs:
            r, b = real_money(x)
            reals.append(r)
            bases.add(b)
            s0 = x.get("spot_entry") or spot_at(_ist(x.get("entry_ts")))
            s1 = x.get("spot_exit") or spot_at(_ist(x.get("exit_ts")))
            if s0 and s1 and s0 != s1:
                hits_n += 1
                up = s1 > s0
                hits += 1 if (up and x["option_type"] == "CE") or (not up and x["option_type"] == "PE") else 0
            ex = true_expiry(x)
            if ex:
                d = (date.fromisoformat(ex) - date.fromisoformat(x["session"])).days
                bucket = "0" if d == 0 else "1" if d == 1 else "2-6" if d <= 6 else "7-35" if d <= 35 else "36+"
                dte_mix[bucket] += 1
                dte_all[bucket][0] += 1
                dte_all[bucket][1] += r
        n = len(nets)
        sd = statistics.stdev(nets) if n > 1 else 0.0
        t_stat = statistics.mean(nets) / (sd / math.sqrt(n)) if n > 2 and sd else None
        wins = sum(1 for v in nets if v > 0)
        gw = sum(v for v in nets if v > 0)
        gl = -sum(v for v in nets if v < 0)
        hz = (hits / hits_n - 0.5) / math.sqrt(0.25 / hits_n) if hits_n >= 10 else None
        rows.append({
            "key": key, "strategy_id": xs[0]["strategy_id"], "timeframe": xs[0].get("timeframe"),
            "trades": n, "net_pnl": round(sum(nets), 2), "per_trade": round(sum(nets) / n, 2),
            "win_rate": round(wins / n, 4), "profit_factor": round(gw / gl, 3) if gl > 0 else None,
            "t_stat": round(t_stat, 2) if t_stat is not None else None,
            "direction_hit": round(hits / hits_n, 3) if hits_n else None, "direction_n": hits_n,
            "direction_z": round(hz, 2) if hz is not None else None,
            "real_net": round(sum(reals), 2), "real_per_trade": round(sum(reals) / n, 2),
            "real_basis": "book" if bases == {"book"} else "estimated" if bases == {"estimated"} else "mixed",
            "dte_mix": dict(dte_mix),
        })
    rows.sort(key=lambda r: r["key"])
    eligible = [r for r in rows if r["trades"] >= 20]
    all_nets = [float(t["pnl"]) for t in trades]
    all_real = [real_money(t)[0] for t in trades]
    return {
        "rows": rows,
        "luck": {"strategies_with_20_trades": len(eligible),
                 "expected_t_above_2_by_chance": round(len(eligible) * LUCK_P, 1),
                 "observed_t_above_2": sum(1 for r in eligible if (r["t_stat"] or 0) > 2),
                 "observed_t_below_minus_2": sum(1 for r in eligible if (r["t_stat"] or 0) < -2),
                 "direction_z_above_2": sum(1 for r in eligible if (r["direction_z"] or 0) > 2),
                 "reading": "With no edge anywhere, about 1 strategy in 44 still shows t > 2. A count near the "
                            "expected number means the 'winners' are what luck produces."},
        "desk": {"trades": len(trades), "paper_net": round(sum(all_nets), 2), "real_net_estimate": round(sum(all_real), 2),
                 "direction_hit": round(sum(r["direction_hit"] * r["direction_n"] for r in rows if r["direction_hit"] is not None)
                                        / max(1, sum(r["direction_n"] for r in rows)), 4),
                 "by_days_to_expiry": {k: {"trades": v[0], "real_per_trade": round(v[1] / v[0], 2)}
                                       for k, v in sorted(dte_all.items())}},
        "real_money_basis": f"lot {LOT_NOW}, ask/bid from the order book where recorded, else LTP +/- "
                            f"{EST_HALF_SPREAD_PCT:.2%} (min Rs0.05) a side; Angel One rate card",
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


async def strategy_records(force: bool = False) -> dict:
    if not force and _cache["data"] and time.monotonic() - _cache["at"] < 300:
        return _cache["data"]
    trades = [t async for t in trades_coll.find({}, {"_id": 0})]
    data = await asyncio.to_thread(_compute, trades)
    _cache.update({"at": time.monotonic(), "data": data})
    return data


async def daily_from_trades() -> list[dict]:
    """One row per session, computed from the TRADES (the daily documents missed six
    September sessions worth -Rs6.4 lakh, so the page's track record understated the loss)."""
    by: dict[str, dict] = {}
    async for t in trades_coll.find({}, {"session": 1, "pnl": 1, "real_pnl": 1, "lot_size": 1, "entry_premium": 1,
                                          "exit_premium": 1, "qty": 1}):
        d = by.setdefault(t["session"], {"session": t["session"], "trades": 0, "net_pnl": 0.0, "wins": 0, "real_net": 0.0})
        d["trades"] += 1
        d["net_pnl"] += float(t["pnl"])
        d["wins"] += 1 if t["pnl"] > 0 else 0
        d["real_net"] += real_money(t)[0]
    docs = {d["session"]: d async for d in db["prelive_daily_pnl"].find({}, {"_id": 0})}
    out = []
    for s in sorted(set(by) | set(docs)):
        t = by.get(s) or {"session": s, "trades": 0, "net_pnl": 0.0, "wins": 0, "real_net": 0.0}
        doc = docs.get(s) or {}
        peak = doc.get("peak_capital")
        out.append({**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in t.items()},
                    "peak_capital": peak, "roi_pct": round(t["net_pnl"] / peak * 100, 2) if peak else None,
                    "daily_doc": bool(doc)})
    return out


async def repair_missing_daily_docs() -> list[str]:
    """Write the daily document for every session that has trades but none (from the trades)."""
    fixed = []
    for d in await daily_from_trades():
        if d["daily_doc"] or not d["trades"]:
            continue
        pts = [p async for p in db["prelive_equity"].find({"session": d["session"]}, {"capital_locked": 1})]
        peak = round(max((p.get("capital_locked", 0) for p in pts), default=0.0), 2)
        await db["prelive_daily_pnl"].update_one({"session": d["session"]}, {"$setOnInsert": {
            "session": d["session"], "trades": d["trades"], "net_pnl": d["net_pnl"], "wins": d["wins"],
            "peak_capital": peak, "roi_pct": round(d["net_pnl"] / peak * 100, 2) if peak else None,
            "rebuilt_from_trades": True, "rebuilt_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
        fixed.append(d["session"])
    return fixed
