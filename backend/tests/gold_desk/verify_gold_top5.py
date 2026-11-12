"""Verify the Gold Desk's Top-5 paper books (app.services.gold_top5_books). No Mongo, no Delta, no network.

Run:  python backend/tests/gold_desk/verify_gold_top5.py

The desk trades are REAL: 24 H1 positions read from production on 12 Nov 2026 (gold_top5_fixtures.json),
the five picks' 20 trades since 4 Nov, two trades of other templates and two picks' open positions.

What this pins down:
  * A copy earns the desk's own result per contract: at the desk's size and a rate of 1 it reproduces
    every closed trade's gross and net (fees both sides and funding included).
  * The shared Rs 2 lakh / Rs 10 lakh books: every pick trade copied, each position up to capital / 5,
    on the trades' own clock never more than five open, one per strategy, cash never below zero.
  * The Rs 10 lakh-each accounts: one per strategy, each entry sized on that account's realised equity.
  * Open copies are marked at the desk's mark; they close when the desk closes, at the rate they opened at.
  * VOID desk trades void their copies; no USD/INR rate or Main Control off means no NEW copy; a book
    never back-fills; a second pass changes nothing; the desk's records are never written.
"""

import asyncio
import copy
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import Coll, check, finish, section  # noqa: E402

from app.services import gold_top5_books as M  # noqa: E402

UTC = timezone.utc
FX = 88.5
FIX = json.loads((Path(__file__).resolve().parent / "gold_top5_fixtures.json").read_text(encoding="utf-8"))
DOCS = []
for _r in FIX["rows"]:
    _d = dict(zip(FIX["fields"], _r))
    for _k in ("opened_at", "closed_at"):
        if _d.get(_k):
            _d[_k] = datetime.fromisoformat(_d[_k])        # Mongo hands back dates, not strings
    _d["instrument"] = {"contract_value": _d["multiplier"]}
    DOCS.append(_d)
PICKED = {p.template for p in M.PICKS}
CLOSED = [d for d in DOCS if d["status"] == "CLOSED"]
OPEN = [d for d in DOCS if d["status"] == "OPEN"]
CLOSED_PICKS = [d for d in CLOSED if d["strategy_template"] in PICKED]


def fresh(start=datetime(2026, 11, 1, tzinfo=UTC), fx=FX, docs=()):
    """Empty books (started `start`; None = they start on the first pass), the given desk trades, a rate."""
    M.PARENTS, M.POSITIONS, M.STATE = Coll("parents"), Coll("positions"), Coll("state")
    M.LOOKBACK = timedelta(days=3650)
    set_fx(fx)
    M.PARENTS.docs.extend(copy.deepcopy(list(docs)))
    if start is not None:
        for b in M.BOOKS:
            M.STATE.docs.append({"_id": f"start:{b.id}", "kind": "start", "book": b.id, "started_at": start})


def set_fx(fx):
    async def _fx():
        return (fx, "test rate") if fx else (None, None)
    M._fx = _fx


def rows(book_id, status=None):
    return [r for r in M.POSITIONS.docs if r["book"] == book_id and (status is None or r["status"] == status)]


def expected_net(d, q, fx):
    """The desk's per-contract result at q contracts, worked out here from the desk's own fields."""
    sign = 1 if d["side"] == "BUY" else -1
    gross = sign * (d["exit_price"] - d["entry_price"]) * d["multiplier"] * q * fx
    costs = (d["entry_costs"] + d["exit_costs"] + d["funding_paid"]) * q / d["units"] * fx
    return gross - costs


def clock_check(book_rows, capital, slot_cap):
    """Replay a book's copies on their own clock, closes before opens at one instant:
    (max open, lowest cash, max open per strategy, entries sized as the whole slot or the cash left, full slots)."""
    ev = []
    for r in book_rows:
        ev.append((r["opened_at"], 1, r))
        if r["status"] == "CLOSED":
            ev.append((r["closed_at"], 0, r))
    ev.sort(key=lambda e: (e[0], e[1]))
    cash, n, worst_cash, most, per, most_per, sized, full = capital, 0, capital, 0, {}, 0, True, 0
    for _t, kind, r in ev:
        if kind == 1:
            want = math.floor(min(slot_cap, cash) / r["entry_price"])
            sized = sized and r["qty"] == want
            full += 1 if cash >= slot_cap else 0
            cash -= r["capital_deployed"]
            n += 1
            per[r["key"]] = per.get(r["key"], 0) + 1
        else:
            cash += r["capital_deployed"] + r["realized_pnl"]
            n -= 1
            per[r["key"]] -= 1
        worst_cash = min(worst_cash, cash)
        most = max(most, n)
        most_per = max(most_per, max(per.values()))
    return most, worst_cash, most_per, sized, full


async def main():
    # ── 1. arithmetic ─────────────────────────────────────────────────────────────────
    section("1. A copy's arithmetic is the desk's, per contract")
    gap = 0.0
    for d in CLOSED_PICKS:
        p = M.parent_of(d, 1.0)
        gross, net, costs = M.pnl({"qty": d["units"], "usd_inr": 1.0}, p)
        gap = max(gap, abs(net - d["realized_pnl"]), abs(gross - d["gross_pnl"]))
    check(f"at the desk's size and a rate of 1, all {len(CLOSED_PICKS)} closed pick trades come out at the desk's "
          "own gross and net (fees both sides + funding)", gap <= 0.021, f"worst gap ${gap:.4f}")
    d = CLOSED_PICKS[0]
    p = M.parent_of(d, FX)
    check("one contract ties up entry x 0.001 oz x USD/INR in rupees",
          abs(p["entry_price"] - d["entry_price"] * 0.001 * FX) < 1e-3, f"Rs {p['entry_price']}")
    g1, n1, _ = M.pnl({"qty": 100}, p)
    g2, n2, _ = M.pnl({"qty": 200}, p)
    check("P&L is proportional to contracts", abs(2 * n1 - n2) <= 0.03 and abs(2 * g1 - g2) <= 0.02, f"{n1} / {n2}")
    check("a stored copy keeps its own rate (the row's rate wins over today's)",
          abs(M.pnl({"qty": 100, "usd_inr": 80.0}, p)[1] - expected_net(d, 100, 80.0)) <= 0.02)
    check("trades of other templates are never copied",
          all(M.parent_of(x, FX) is None for x in DOCS if x["strategy_template"] not in PICKED))
    check("each strategy holds its own position: its 'symbol' is its board id", p["symbol"] == p["key"] != "XAUTUSD")

    # ── 2. a week of real trades ────────────────────────────────────────────────────────
    section("2. A week of the desk's real trades through every book")
    fresh(docs=CLOSED)
    out = await M.sync(entries=True)
    check("the pass made new copies with a rate", out["entries"] is True and out["usd_inr"] == FX, out.get("note", ""))
    n_picks = len(CLOSED_PICKS)
    for bid, cap in (("top5_2L", 40000.0), ("top5_10L", 200000.0)):
        rs = rows(bid)
        b = M.BOOK[bid]
        check(f"{bid}: every one of the {n_picks} pick trades copied, nothing else",
              len(rs) == n_picks and {r["parent_position_id"] for r in rs} == {x["position_id"] for x in CLOSED_PICKS},
              f"{len(rs)} copies")
        check(f"{bid}: no position above capital / 5 (Rs {cap:,.0f})", all(r["capital_deployed"] <= cap + 1e-6 for r in rs))
        most, worst_cash, most_per, sized, full = clock_check(rs, b.capital, cap)
        check(f"{bid}: on the trades' own clock at most 5 open, one per strategy, cash never below zero",
              most <= 5 and most_per == 1 and worst_cash >= -1e-6, f"max open {most}, lowest cash Rs {worst_cash:,.0f}")
        check(f"{bid}: every entry is the whole slot in whole contracts, or what cash was left",
              sized, f"{full} of {len(rs)} had the full slot")
        by_parent = {x["position_id"]: x for x in CLOSED_PICKS}
        worst = max(abs(r["realized_pnl"] - expected_net(by_parent[r["parent_position_id"]], r["qty"], FX)) for r in rs)
        check(f"{bid}: every copy's net = the desk's per-contract result x its contracts x the rate", worst <= 0.03,
              f"worst gap Rs {worst:.3f}")
    q2 = {r["parent_position_id"]: r["qty"] for r in rows("top5_2L")}
    q10 = {r["parent_position_id"]: r["qty"] for r in rows("top5_10L")}
    check("the Rs 10 lakh book holds about five times the Rs 2 lakh book's contracts",
          all(abs(q10[k] - 5 * q2[k]) <= 5 for k in q2), f"e.g. {next(iter(q2.values()))} vs {next(iter(q10.values()))}")
    for p in M.PICKS:
        bid = f"each10L_{p.n}"
        rs = sorted(rows(bid), key=lambda r: r["opened_at"])
        mine = [x for x in CLOSED_PICKS if x["strategy_template"] == p.template]
        ok = len(rs) == len(mine) and all(r["key"] == p.key for r in rs)
        eq, sized = M.BOOK[bid].capital, True
        for r in rs:
            if r["qty"] != math.floor(eq / r["entry_price"]):
                sized = False
            eq += r["realized_pnl"]
        check(f"{bid} ({p.name}): only its own {len(mine)} trades, each sized on the account's equity then",
              ok and sized, f"{len(rs)} copies, equity now Rs {eq:,.0f}")
    snap = copy.deepcopy(M.POSITIONS.docs)
    await M.sync(entries=True)
    check("a second pass changes nothing", M.POSITIONS.docs == snap)
    check("the desk's records were never written", M.PARENTS.writes == 0)

    # ── 3. an open trade, then its close ────────────────────────────────────────────────
    section("3. An open desk trade: copied, marked, closed when the desk closes it")
    fresh(docs=OPEN)
    await M.sync(entries=True)
    for d in OPEN:
        r = next(x for x in rows("top5_2L") if x["parent_position_id"] == d["position_id"])
        want = round(d["unrealized_pnl"] * r["qty"] / d["units"] * FX, 2)
        check(f"{d['strategy_template']}: copied OPEN and marked at the desk's mark x size x rate",
              r["status"] == "OPEN" and abs(r["unrealized_pnl"] - want) <= 0.01, f"Rs {r['unrealized_pnl']} vs {want}")
    d = M.PARENTS.docs[0]
    d.update(status="CLOSED", exit_price=d["entry_price"] + (12.0 if d["side"] == "BUY" else -12.0),
             exit_costs=d["entry_costs"], funding_paid=0.0412, exit_reason="target",
             closed_at=d["opened_at"] + timedelta(hours=8), closed_on=(d["opened_at"] + timedelta(hours=8)).date().isoformat())
    set_fx(91.0)                                              # the rate has moved since the copy opened
    await M.sync(entries=True)
    r = next(x for x in rows("top5_2L") if x["parent_position_id"] == d["position_id"])
    check("the copy closed with the desk, at the rate it opened at (not today's)",
          r["status"] == "CLOSED" and abs(r["realized_pnl"] - expected_net(d, r["qty"], FX)) <= 0.03,
          f"Rs {r['realized_pnl']}")
    s = await M.summary(M.BOOK["top5_2L"])
    check("equity = capital + realised + open P&L, and the closed copy's money is free again",
          abs(s["equity"] - (s["capital"] + s["realized_pnl"] + s["unrealized_pnl"])) < 0.01
          and abs(s["available_cash"] - (s["capital"] + s["realized_pnl"] - s["deployed"])) < 0.01
          and s["open_positions"] == len(OPEN) - 1, f"cash Rs {s['available_cash']:,.0f}")

    # ── 4. void, no rate, Main Control off, no back-fill ──────────────────────────────────
    section("4. VOID trades, no USD/INR rate, Main Control off, no back-fill")
    fresh(docs=OPEN[:1])
    await M.sync(entries=True)
    M.PARENTS.docs[0].update(status="VOID", void=True)
    await M.sync(entries=True)
    v = rows("top5_2L")[0]
    s = await M.summary(M.BOOK["top5_2L"])
    check("a desk trade that ends VOID voids its copy: no P&L, the money back",
          v["status"] == "VOID" and v["realized_pnl"] == 0.0 and s["available_cash"] == s["capital"] and s["voided"] == 1)

    fresh(docs=OPEN[:1], fx=None)
    out = await M.sync(entries=True)
    check("with no USD/INR rate nothing new is copied, and the pass says why",
          not M.POSITIONS.docs and out["entries"] is False and "USD/INR" in out.get("note", ""))
    set_fx(FX)
    await M.sync(entries=True)
    d = M.PARENTS.docs[0]
    d.update(status="CLOSED", exit_price=d["entry_price"], exit_costs=d["entry_costs"], funding_paid=0.0,
             exit_reason="time", closed_at=d["opened_at"] + timedelta(hours=4), closed_on=d["opened_on"])
    set_fx(None)
    await M.sync(entries=True)
    check("with no rate an open copy still closes, at its own stored rate",
          rows("top5_2L")[0]["status"] == "CLOSED"
          and abs(rows("top5_2L")[0]["realized_pnl"] - expected_net(d, rows("top5_2L")[0]["qty"], FX)) <= 0.03)

    fresh(docs=OPEN[:1])
    await M.sync(entries=False)
    check("Main Control off (entries=False): no new copy", not M.POSITIONS.docs)

    fresh(start=None, docs=CLOSED)
    await M.sync(entries=True)
    check("books that start now copy nothing the desk opened before (no back-fill)", not M.POSITIONS.docs)

    # ── 5. the read model ────────────────────────────────────────────────────────────────
    section("5. What the page reads")
    fresh(docs=CLOSED + OPEN)
    await M.sync(entries=True)
    ov = await M.overview()
    books = {b["id"]: b for b in ov["books"]}
    check("three account types: two shared books and five Rs 10 lakh accounts",
          [g["group"] for g in ov["groups"]] == ["2L", "10L", "each10L"] and len(books) == 7
          and ov["each_total"]["capital"] == 5_000_000 and ov["each_total"]["accounts"] == 5)
    check("position caps: Rs 40,000 / Rs 2,00,000 / the account's own balance",
          books["top5_2L"]["position_cap"] == 40000 and books["top5_10L"]["position_cap"] == 200000
          and books["each10L_1"]["position_cap"] is None)
    check("every book: equity = capital + realised + open P&L",
          all(abs(b["equity"] - (b["capital"] + b["realized_pnl"] + b["unrealized_pnl"])) < 0.01 for b in ov["books"]))
    tot = ov["each_total"]
    check("the each-strategy total is the sum of its five accounts",
          abs(tot["equity"] - sum(books[f"each10L_{p.n}"]["equity"] for p in M.PICKS)) < 0.01)
    per = {x["key"]: x for x in books["top5_2L"]["strategies"]}
    check("a shared book shows each pick's own record in it",
          sum(x["trades"] for x in per.values()) == books["top5_2L"]["closed_positions"]
          and abs(sum(x["net"] for x in per.values()) - books["top5_2L"]["realized_pnl"]) < 0.05)
    closed = await M.positions("top5_2L", "CLOSED", 500)
    check("closed copies come back latest close first, dates as ISO text, no Mongo ids",
          closed == sorted(closed, key=lambda r: r["closed_at"], reverse=True)
          and all(isinstance(r["opened_at"], str) and "_id" not in r for r in closed))
    check("the five picks and the rate are on the page", len(ov["picks"]) == 5 and ov["usd_inr"]["rate"] == FX)
    print(f"\n  (the week through the Rs 2 lakh book: {books['top5_2L']['closed_positions']} trades, "
          f"Rs {books['top5_2L']['realized_pnl']:,.2f} realised; Rs 10 lakh each: Rs {tot['realized_pnl']:,.2f})")


asyncio.run(main())
finish()
