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
  * The 18 Nov accounts (own2L_n / own10L_n): each of that day's top 5 alone on Rs 2 lakh and on Rs 10 lakh,
    sized the same way; Keltner Breakout trades only there, HH/HL Structure Shift only in the 12 Nov books.
  * The 19 Nov H1-nine accounts, on all 130 real H1 trades to 19 Nov (gold_h1_fixtures.json): the shared Rs 2 lakh /
    Rs 10 lakh accounts copy every trade of the nine, each position up to capital / 9, never more than nine open, one
    per strategy, cash never below zero; each of the nine alone on Rs 2 lakh and on Rs 10 lakh, sized on its equity.
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

from app.services import gold_h1  # noqa: E402
from app.services import gold_top5_books as M  # noqa: E402

UTC = timezone.utc
FX = 88.5
def _docs(name):
    fix = json.loads((Path(__file__).resolve().parent / name).read_text(encoding="utf-8"))
    out = []
    for r in fix["rows"]:
        d = dict(zip(fix["fields"], r))
        for k in ("opened_at", "closed_at"):
            if d.get(k):
                d[k] = datetime.fromisoformat(d[k])        # Mongo hands back dates, not strings
        d["instrument"] = {"contract_value": d["multiplier"]}
        out.append(d)
    return out


DOCS = _docs("gold_top5_fixtures.json")
H1_DOCS = _docs("gold_h1_fixtures.json")                  # every H1 trade to 19 Nov 2026, all nine templates
PICKED = {p.template for p in M.PICKS}                   # the 12 Nov five (the shared books' roster)
PICKED_ANY = {p.template for p in M.ALL_PICKS}           # any set: 12 Nov, 18 Nov or the 19 Nov nine
# A desk trade of a template outside every set: a real H1 row relabelled, so only its template differs
OUTSIDER = {**copy.deepcopy(DOCS[0]), "position_id": "not-a-pick-0001", "strategy_template": "rsi_reversal"}
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


def gt_ok(ov, group, accounts, capital):
    """A one-account-a-strategy group's total line: its account count, its capital and the sum of its equities."""
    t = ov["group_totals"].get(group) or {}
    eq = sum(b["equity"] for b in ov["books"] if b["group"] == group)
    return t.get("accounts") == accounts and t.get("capital") == capital and abs(t.get("equity", 0) - eq) < 0.01


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
    check("the 19 Nov set is exactly H1's nine templates, so every H1 trade is now a pick's",
          {p.template for p in M.PICKS_H1} == set(gold_h1.H1_TEMPLATES) and len(M.PICKS_H1) == 9
          and all(M.parent_of(x, FX) is not None for x in H1_DOCS))
    check("a trade of a template in no pick set is never copied",
          OUTSIDER["strategy_template"] not in PICKED_ANY and M.parent_of(OUTSIDER, FX) is None)
    check("each strategy holds its own position: its 'symbol' is its board id", p["symbol"] == p["key"] != "XAUTUSD")

    # ── 2. a week of real trades ────────────────────────────────────────────────────────
    section("2. A week of the desk's real trades through every book (on an engine without `compound`)")
    real_plan = M.plan_book

    def older_engine(*, capital, realized, deployed, open_rows, parents, decided, breaker_tripped, entries,
                     max_open=None, net_fn=None, source_tag=None, closed_rows=None):
        """plan_book as a server whose shared engine predates 11 Nov has it: no `compound` flag at all."""
        return real_plan(capital=capital, realized=realized, deployed=deployed, open_rows=open_rows, parents=parents,
                         decided=decided, breaker_tripped=breaker_tripped, entries=entries, max_open=max_open,
                         net_fn=net_fn, source_tag=source_tag, closed_rows=closed_rows)

    M.plan_book = older_engine
    fresh(docs=CLOSED + [OUTSIDER])
    out = await M.sync(entries=True)
    check("the outsider's trade is in no book", not [r for r in M.POSITIONS.docs if r["parent_position_id"] == OUTSIDER["position_id"]])
    check("every book ran on the older engine (nothing passed it a flag it does not have)",
          not any("error" in v for v in out["books"].values()), {k: v for k, v in out["books"].items() if "error" in v})
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
    for p in M.PICKS_1811:
        mine = [x for x in CLOSED if x["strategy_template"] == p.template]
        for kind, cap in (("own2L", 200000.0), ("own10L", 1000000.0)):
            bid = f"{kind}_{p.n}"
            rs = sorted(rows(bid), key=lambda r: r["opened_at"])
            ok = len(rs) == len(mine) and all(r["key"] == p.key for r in rs) and M.BOOK[bid].capital == cap
            eq, sized = cap, True
            for r in rs:
                if r["qty"] != math.floor(eq / r["entry_price"]):
                    sized = False
                eq += r["realized_pnl"]
            check(f"{bid} ({p.name}): only its own {len(mine)} trades on its own Rs {cap:,.0f}, each sized on its "
                  "equity then", ok and sized and len(rs) > 0, f"{len(rs)} copies, equity now Rs {eq:,.0f}")
    kel = [x["position_id"] for x in CLOSED if x["strategy_template"] == "keltner_break"]
    hh = [x["position_id"] for x in CLOSED if x["strategy_template"] == "hh_hl_shift"]
    in_books = lambda pid: {r["book"] for r in M.POSITIONS.docs if r["parent_position_id"] == pid}  # noqa: E731
    nine = {"h1_2L", "h1_10L"}
    check("Keltner Breakout (18 Nov, not 12 Nov) is in its own two 18 Nov accounts and the H1-nine ones, nowhere else",
          kel and all(in_books(k) == {"own2L_5", "own10L_5", "h1own2L_6", "h1own10L_6"} | nine for k in kel),
          str([in_books(k) for k in kel]))
    check("HH/HL Structure Shift (12 Nov, not 18 Nov) is in the 12 Nov books and the H1-nine ones, not the 18 Nov accounts",
          hh and all(in_books(k) == {"top5_2L", "top5_10L", "each10L_4", "h1own2L_7", "h1own10L_7"} | nine for k in hh),
          str([in_books(k) for k in hh]))
    pri = [x["position_id"] for x in CLOSED if x["strategy_template"] == "prior_session_break"]
    check("Prior Session High/Low Break (in no top 5) trades only in the H1-nine accounts",
          pri and all(in_books(k) == {"h1own2L_9", "h1own10L_9"} | nine for k in pri), str([in_books(k) for k in pri]))
    f2 = sorted(rows("own2L_1"), key=lambda r: r["opened_at"])[0]
    f10 = sorted(rows("own10L_1"), key=lambda r: r["opened_at"])[0]
    check("an own Rs 10 lakh account's first trade is about five times its Rs 2 lakh twin's",
          abs(f10["qty"] - 5 * f2["qty"]) <= 5, f"{f2['qty']} vs {f10['qty']}")
    snap = copy.deepcopy(M.POSITIONS.docs)
    await M.sync(entries=True)
    check("a second pass changes nothing", M.POSITIONS.docs == snap)
    check("the desk's records were never written", M.PARENTS.writes == 0)
    M.plan_book = real_plan

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
    check("three 12 Nov account types (two shared books, five Rs 10 lakh accounts), the 18 Nov ten and the 19 Nov twenty",
          [g["group"] for g in ov["groups"]] == ["2L", "10L", "each10L", "own2L", "own10L",
                                                 "h1_2L", "h1_10L", "h1own2L", "h1own10L"] and len(books) == 37
          and ov["each_total"]["capital"] == 5_000_000 and ov["each_total"]["accounts"] == 5)
    check("19 Nov: two shared accounts on all nine and nine accounts each on Rs 2 lakh and Rs 10 lakh",
          books["h1_2L"]["capital"] == 200_000 and books["h1_10L"]["capital"] == 1_000_000
          and books["h1_2L"]["max_open"] == 9 and abs(books["h1_2L"]["position_cap"] - 200_000 / 9) < 0.01
          and abs(books["h1_10L"]["position_cap"] - 1_000_000 / 9) < 0.01
          and len(books["h1_10L"]["roster"]) == 9
          and gt_ok(ov, "h1own2L", 9, 1_800_000) and gt_ok(ov, "h1own10L", 9, 9_000_000)
          and books["h1own2L_9"]["roster"] == ["XAUTUSD-prior_session_break-4h"] and books["h1own10L_1"]["position_cap"] is None
          and ov["h1_groups"] == ["h1_2L", "h1_10L", "h1own2L", "h1own10L"]
          and len(ov["notes_h1"]) == 6 and all(isinstance(n, str) and n for n in ov["notes_h1"]))
    check("19 Nov: the nine as picked, in board order, with when",
          [p["template"] for p in ov["picks_h1"]] == ["ema_ribbon", "round_number_break", "donchian_fast", "pivot_break",
                                                      "donchian_slow", "keltner_break", "hh_hl_shift", "atr_thrust",
                                                      "prior_session_break"]
          and ov["picked_at_h1"] == "2026-11-19T20:15:00+05:30" and [p["n"] for p in ov["picks_h1"]] == list(range(1, 10)))
    gt = ov["group_totals"]
    check("18 Nov: five Rs 2 lakh and five Rs 10 lakh accounts, each total the sum of its five",
          gt["own2L"]["capital"] == 1_000_000 and gt["own10L"]["capital"] == 5_000_000
          and gt["own2L"]["accounts"] == 5 and gt["own10L"]["accounts"] == 5
          and abs(gt["own2L"]["equity"] - sum(books[f"own2L_{p.n}"]["equity"] for p in M.PICKS_1811)) < 0.01
          and books["own2L_1"]["position_cap"] is None and books["own10L_5"]["roster"] == ["XAUTUSD-keltner_break-4h"])
    check("18 Nov: the five as picked, in board order, with when",
          [p["template"] for p in ov["picks_1811"]] == ["round_number_break", "ema_ribbon", "donchian_fast",
                                                         "pivot_break", "keltner_break"]
          and ov["picked_at_1811"] == "2026-11-18T07:53:00+05:30")
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

    # ── 6. the 19 Nov H1-nine accounts on every real H1 trade ────────────────────────────────
    h1_closed = [d for d in H1_DOCS if d["status"] == "CLOSED"]
    section(f"6. The H1-nine accounts: all {len(h1_closed)} real H1 trades to 19 Nov (on an engine without `compound`)")
    M.plan_book = older_engine
    fresh(start=datetime(2026, 10, 1, tzinfo=UTC), docs=h1_closed)
    out = await M.sync(entries=True)
    check("every book ran on the older engine", not any("error" in v for v in out["books"].values()),
          {k: v for k, v in out["books"].items() if "error" in v})
    by_parent = {x["position_id"]: x for x in h1_closed}
    for bid, cap in (("h1_2L", 200000.0 / 9), ("h1_10L", 1000000.0 / 9)):
        rs = rows(bid)
        b = M.BOOK[bid]
        check(f"{bid}: every one of the {len(h1_closed)} H1 trades copied (nine slots never turn one away)",
              {r["parent_position_id"] for r in rs} == set(by_parent) and len(rs) == len(h1_closed), f"{len(rs)} copies")
        check(f"{bid}: no position above capital / 9 (Rs {cap:,.0f})", all(r["capital_deployed"] <= cap + 1e-6 for r in rs))
        most, worst_cash, most_per, sized, full = clock_check(rs, b.capital, cap)
        check(f"{bid}: on the trades' own clock at most 9 open, one per strategy, cash never below zero",
              most <= 9 and most_per == 1 and worst_cash >= -1e-6, f"max open {most}, lowest cash Rs {worst_cash:,.0f}")
        check(f"{bid}: every entry is the whole slot in whole contracts, or what cash was left", sized,
              f"{full} of {len(rs)} had the full slot")
        worst = max(abs(r["realized_pnl"] - expected_net(by_parent[r["parent_position_id"]], r["qty"], FX)) for r in rs)
        check(f"{bid}: every copy's net = H1's per-contract result x its contracts x the rate", worst <= 0.03,
              f"worst gap Rs {worst:.3f}")
    q2 = {r["parent_position_id"]: r["qty"] for r in rows("h1_2L")}
    q10 = {r["parent_position_id"]: r["qty"] for r in rows("h1_10L")}
    check("the shared Rs 10 lakh account holds about five times the Rs 2 lakh one's contracts",
          all(abs(q10[k] - 5 * q2[k]) <= 5 for k in q2))
    for p in M.PICKS_H1:
        mine = [x for x in h1_closed if x["strategy_template"] == p.template]
        for kind, cap in (("h1own2L", 200000.0), ("h1own10L", 1000000.0)):
            bid = f"{kind}_{p.n}"
            rs = sorted(rows(bid), key=lambda r: r["opened_at"])
            eq, sized = cap, True
            for r in rs:
                if r["qty"] != math.floor(eq / r["entry_price"]):
                    sized = False
                eq += r["realized_pnl"]
            check(f"{bid} ({p.name}): its own {len(mine)} trades only, on its own Rs {cap:,.0f}, each sized on its "
                  "equity then", len(rs) == len(mine) > 0 and all(r["key"] == p.key for r in rs) and sized
                  and M.BOOK[bid].capital == cap, f"{len(rs)} copies, equity now Rs {eq:,.0f}")
    snap = copy.deepcopy(M.POSITIONS.docs)
    await M.sync(entries=True)
    check("a second pass changes nothing", M.POSITIONS.docs == snap)
    check("the desk's records were never written", M.PARENTS.writes == 0)
    ov = await M.overview()
    books = {b["id"]: b for b in ov["books"]}
    per = {x["key"]: x for x in books["h1_2L"]["strategies"]}
    check("the shared account shows each of the nine's own record in it",
          len(per) == 9 and sum(x["trades"] for x in per.values()) == books["h1_2L"]["closed_positions"]
          and abs(sum(x["net"] for x in per.values()) - books["h1_2L"]["realized_pnl"]) < 0.05)
    M.plan_book = real_plan
    print(f"\n  (all {len(h1_closed)} H1 trades since 11 Oct through the accounts - in-sample, not evidence: "
          f"H1 nine Rs 2 lakh {books['h1_2L']['realized_pnl']:+,.2f}, Rs 10 lakh {books['h1_10L']['realized_pnl']:+,.2f}; "
          f"Rs 2 lakh each {ov['group_totals']['h1own2L']['realized_pnl']:+,.2f} on Rs 18 lakh)")


asyncio.run(main())
finish()
