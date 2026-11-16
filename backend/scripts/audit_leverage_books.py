"""Read-only audit of the Intraday Stocks paper accounts after the 5x leverage replay (2026-11-16).

Checks the ROWS themselves, on the trades' own clock, without the replay's code: entry/exit = the parent's,
gross = price move x qty, net = gross - fees, margin = value / leverage, leverage by eligibility, at most 5
open, one stock once, margin <= money, exposure <= 5 x money, no entry after the day's breaker, trades and
scores = rows, and no parent in the next pass's window left undecided. Run like rebuild_leverage_books.py:
  python scripts/audit_leverage_books.py
"""
import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, "/app/backend")


def naive(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


async def audit(desk_key):
    from app.core import db as D
    if desk_key == "live-intraday":
        from app.services import live_intraday_engine as li
        from app.services import live_intraday_mirror as m
        books, tag, pos, trades, scores = li.BOOKS, m.SOURCE_TAG, D.live_intraday_positions_collection, \
            D.live_intraday_trades_collection, D.live_intraday_scores_collection
        parents_coll, capital = D.intraday_lab_positions_collection, li.book_capital
        start = await m._mirror_start()
        floor = lambda b: m._floor(b, start)
        decided = m._decided
        parents = m._parents
        roster = li.book_roster
        lim = lambda b: li.DAILY_LOSS_BREAKER_PCT * li.book_capital(b)
    else:
        from app.services import pattern_books_copy as c
        from app.services import pattern_books_engine as pbe
        books, tag, pos, trades, scores = pbe.COPY_BOOKS, c.SOURCE_TAG, D.pattern_book_positions_collection, \
            D.pattern_book_trades_collection, D.pattern_book_scores_collection
        parents_coll, capital = D.pattern_positions_collection, pbe.book_capital
        floor, decided, parents, roster = c._floor, c._decided, c._parents, pbe.book_roster
        lim = lambda b: None
    out = {}
    for book in books:
        cap = capital(book)
        rows = [r async for r in pos.find({"book": book, "source": tag})]
        issues = defaultdict(int)
        pids = [r["parent_position_id"] for r in rows]
        if len(pids) != len(set(pids)):
            issues["duplicate_parent"] += 1
        par = {p["position_id"]: p async for p in parents_coll.find({"position_id": {"$in": pids}})}
        for r in rows:
            p = par.get(r["parent_position_id"])
            if p is None:
                issues["parent_missing"] += 1
                continue
            if abs(round(float(p["entry_price"]), 2) - r["entry_price"]) > 0.005:
                issues["entry_not_parent"] += 1
            lev = float(r.get("leverage") or 1.0)
            val = round(r["entry_price"] * r["qty"], 2)
            if abs(val - float(r.get("notional") or 0)) > 0.011:
                issues["notional_wrong"] += 1
            if abs(float(r["capital_deployed"]) - val / lev) > 0.011:
                issues["margin_not_value_over_lev"] += 1
            if desk_key == "pattern-books":
                want = 5.0 if p.get("style") in ("intraday", "scalping") else 1.0
                if lev != want:
                    issues["leverage_not_by_style"] += 1
            elif lev != 5.0:
                issues["leverage_not_5"] += 1
            if r["status"] == "CLOSED":
                if abs(round(float(p["exit_price"]), 2) - r["exit_price"]) > 0.005:
                    issues["exit_not_parent"] += 1
                sign = 1 if r["side"] == "BUY" else -1
                g = round(sign * (r["exit_price"] - r["entry_price"]) * r["qty"], 2)
                if abs(g - r["gross_pnl"]) > 0.02:
                    issues["gross_not_price_move_x_qty"] += 1
                if abs(r["gross_pnl"] - r["fees"] - r["realized_pnl"]) > 0.02:
                    issues["net_not_gross_minus_fees"] += 1
        # The timeline: slots, one stock once, margin <= money, value <= 5 x money.
        ev = []
        for r in rows:
            ev.append((naive(r["opened_at"]), 1, r))
            if r["status"] == "CLOSED":
                ev.append((naive(r["closed_at"]), 0, r))
        ev.sort(key=lambda e: (e[0] or datetime.min, e[1]))
        money, margin, value, held, n = cap, 0.0, 0.0, defaultdict(int), 0
        peak = {"open": 0, "margin": 0.0, "value": 0.0, "min_free_margin": cap}
        day_net = defaultdict(float)
        for t, kind, r in ev:
            if kind == 1:
                n += 1
                margin += r["capital_deployed"]
                value += r["notional"]
                held[r["symbol"]] += 1
                if held[r["symbol"]] > 1:
                    issues["stock_twice"] += 1
                if n > 5:
                    issues["over_slots"] += 1
                if margin > money + 0.05:
                    issues["margin_over_money"] += 1
                if value > 5 * max(money, cap) + 0.05:
                    issues["exposure_over_5x"] += 1
                L = lim(book)
                day = r.get("opened_on")
                if L is not None and day_net[day] <= -L:
                    issues["entry_after_breaker"] += 1
                peak["open"] = max(peak["open"], n)
                peak["margin"] = round(max(peak["margin"], margin), 2)
                peak["value"] = round(max(peak["value"], value), 2)
                peak["min_free_margin"] = round(min(peak["min_free_margin"], money - margin), 2)
            else:
                n -= 1
                margin -= r["capital_deployed"]
                value -= r["notional"]
                held[r["symbol"]] -= 1
                money += r["realized_pnl"]
                day_net[r.get("closed_on")] += r["realized_pnl"]
        closed = [r for r in rows if r["status"] == "CLOSED"]
        nt = await trades.count_documents({"book": book, "source": tag})
        if nt != len(closed):
            issues["trades_ne_closed_rows"] += 1
        s_net = 0.0
        async for s in scores.find({"book": book, "source": tag}, {"net_pnl": 1}):
            s_net += s.get("net_pnl") or 0.0
        r_net = round(sum(r["realized_pnl"] for r in closed), 2)
        if abs(round(s_net, 2) - r_net) > 0.05:
            issues["scores_ne_rows"] += 1
        # Tomorrow's pass must not back-fill: every parent in its window is decided.
        fl = await floor(book)
        from app.services.live_intraday_mirror import window_start
        ps = await parents(window_start(fl), [])
        ro = roster(book)
        if ro is not None:
            ps = [p for p in ps if p["strategy_id"] in set(ro)]
        dec = await decided(book, ps)
        undecided = [p["position_id"] for p in ps if p["position_id"] not in dec]
        if undecided:
            issues["undecided_parents_in_window"] = len(undecided)
        out[book] = {"rows": len(rows), "closed": len(closed), "net": r_net, "peaks": peak,
                     "issues": dict(issues)}
    return out


async def main():
    res = {k: await audit(k) for k in ("live-intraday", "pattern-books")}
    bad = {d: {b: v["issues"] for b, v in r.items() if v["issues"]} for d, r in res.items()}
    for d, r in res.items():
        for b, v in r.items():
            print(d, b, v["rows"], v["closed"], v["net"], v["peaks"], v["issues"] or "OK")
    print("ISSUES:", json.dumps(bad))


asyncio.run(main())
