"""Verify the Gold Desk's Strategy Factory top-25 accounts (app.services.gold_sf_books). No Mongo, no Delta, no network.

Run:  python backend/tests/gold_desk/verify_gold_sf_books.py

The tab's trades are REAL: 49 Strategy Factory gold positions read from production at 22:30 IST on 18 Nov 2026
(gold_sf_fixtures.json) - the 25 picks' 26 closed and 19 open trades in that window, and four trades of strategies
outside the 25.

What this pins down:
  * A copy earns the tab's own result at its size: the price move between the tab's fills, its fees both sides and the
    funding it paid or was paid (which can be negative), scaled from the tab's $1,111 sleeve to the copy's contracts.
  * 25 accounts, one per pick, Rs 2 lakh each, in five sets labelled as the owner asked (Top 1-5 ... Top 20-25, Rank
    1-5 ... 21-25); a strategy's trades go to its own account only, each entry sized on that account's realised equity.
  * Open copies are marked at the tab's mark and close when the tab closes, at the rate they opened at.
  * No USD/INR rate or Main Control off means no NEW copy; an account never back-fills; a second pass changes nothing,
    and a pass with nothing to do replays no account; the tab's records are never written.
  * The read model: per account its equity, total return and the IST days it closed a copy on; per set and overall the
    sums; positions by account, by set or all.
"""

import asyncio
import copy
import json
import math
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import Coll, check, finish, section  # noqa: E402

# The tab's module is stubbed to what this module uses of it: its positions and its store.
_fd = types.ModuleType("app.services.factory_desks")
_fd.POSITIONS = Coll("parents")
_fd.STORE = {"gold_sf_positions": Coll("positions"), "gold_sf_state": Coll("state")}
sys.modules[_fd.__name__] = _fd

from app.services import gold_sf_books as M  # noqa: E402

UTC = timezone.utc
FX = 94.24
FIX = json.loads((Path(__file__).resolve().parent / "gold_sf_fixtures.json").read_text(encoding="utf-8"))
DOCS = []
for _r in FIX["rows"]:
    _d = dict(zip(FIX["fields"], _r))
    for _k in ("opened_at", "closed_at"):
        if _d.get(_k):
            _d[_k] = datetime.fromisoformat(_d[_k]).astimezone(UTC).replace(tzinfo=None)   # Mongo hands back naive UTC
    DOCS.append(_d)
PICKED = {p.strategy_id for p in M.PICKS}
CLOSED = [d for d in DOCS if d["status"] == "CLOSED"]
OPEN = [d for d in DOCS if d["status"] == "OPEN"]
CLOSED_PICKS = [d for d in CLOSED if d["strategy_id"] in PICKED]
OPEN_PICKS = [d for d in OPEN if d["strategy_id"] in PICKED]
START = datetime(2026, 11, 17)            # the accounts' start in most scenarios: before every fixture trade


def fresh(start=START, fx=FX, docs=()):
    """Empty accounts (started `start`; None = they start on the first pass), the given tab trades, a rate."""
    M.PARENTS, M.POSITIONS, M.STATE = Coll("parents"), Coll("positions"), Coll("state")
    M.LOOKBACK = timedelta(days=3650)
    set_fx(fx)
    M.PARENTS.docs.extend(copy.deepcopy(list(docs)))
    if start is not None:
        for a in M.ACCOUNTS:
            M.STATE.docs.append({"_id": f"start:{a.id}", "kind": "start", "account": a.id, "started_at": start})


def set_fx(fx):
    async def _fx():
        return (fx, "test rate") if fx else (None, None)
    M._fx = _fx


def rows(account=None, status=None):
    return [r for r in M.POSITIONS.docs
            if (account is None or r["account"] == account) and (status is None or r["status"] == status)]


def expected_net(d, q, fx):
    """The tab's result at q contracts, worked out here from the tab's own fields."""
    sign = 1 if d["signal_side"] == "BUY" else -1
    gross = sign * (d["exit_px"] - d["entry_px"]) * 0.001 * q * fx
    share = d["entry_px"] * 0.001 * q / d["capital_deployed"]
    return gross - d["fees"] * share * fx          # the tab's `fees` = both sides' fees + the funding


async def main():
    # ── 1. arithmetic ─────────────────────────────────────────────────────────────────
    section("1. A copy's arithmetic is the tab's, scaled to its contracts")
    gap = 0.0
    for d in CLOSED_PICKS:
        p = M.parent_of(d, 1.0)
        q = round(d["capital_deployed"] / (d["entry_px"] * 0.001))       # about the tab's own size
        gross, net, costs = M.pnl({"qty": q, "usd_inr": 1.0}, p)
        k = d["entry_px"] * 0.001 * q / d["capital_deployed"]
        gap = max(gap, abs(net - d["realized_pnl"] * k), abs(gross - d["gross_pnl"] * k))
    check(f"at the tab's size and a rate of 1, all {len(CLOSED_PICKS)} closed pick trades come out at the tab's own "
          "gross and net (fees both sides + funding)", gap <= 0.03, f"worst gap ${gap:.4f}")
    neg = [d for d in CLOSED_PICKS if (d.get("funding") or 0) < 0]
    if neg:
        d = neg[0]
        p = M.parent_of(d, 1.0)
        _g, _n, c = M.pnl({"qty": 270, "usd_inr": 1.0}, p)
        check("funding the tab was PAID lowers the copy's costs (a short paid by longs)",
              c.parts["funding"] < 0 and c.total < c.parts["fees"], c.as_dict())
    d = CLOSED_PICKS[0]
    p = M.parent_of(d, FX)
    check("one contract ties up entry x 0.001 oz x USD/INR in rupees",
          abs(p["entry_price"] - d["entry_px"] * 0.001 * FX) < 1e-3, f"Rs {p['entry_price']}")
    g1, n1, _ = M.pnl({"qty": 100}, p)
    g2, n2, _ = M.pnl({"qty": 200}, p)
    check("P&L is proportional to contracts", abs(2 * n1 - n2) <= 0.03 and abs(2 * g1 - g2) <= 0.02, f"{n1} / {n2}")
    check("a stored copy keeps its own rate (the row's rate wins over today's)",
          abs(M.pnl({"qty": 100, "usd_inr": 80.0}, p)[1] - expected_net(d, 100, 80.0)) <= 0.03)
    others = [x for x in DOCS if x["strategy_id"] not in PICKED]
    check("trades of strategies outside the 25 are never copied",
          others and all(M.parent_of(x, FX) is None for x in others))
    check("another tab's trade (an Index Option Buying option) is never copied",
          M.parent_of({**d, "desk": "index-buying", "kind": "option_buy"}, FX) is None)
    check("each strategy holds its own position: its 'symbol' is its strategy id", p["symbol"] == p["key"] == d["strategy_id"])

    # ── 2. the roster ─────────────────────────────────────────────────────────────────
    section("2. Twenty-five accounts in five sets, as asked")
    check("25 accounts, one per pick, Rs 2 lakh each, ranks 1-25 in board order",
          len(M.ACCOUNTS) == 25 and [a.pick.rank for a in M.ACCOUNTS] == list(range(1, 26))
          and all(a.capital == 200000 for a in M.ACCOUNTS) and len(PICKED) == 25)
    check("five sets labelled as the owner asked, each with its ranks",
          [b.label for b in M.BANDS] == ["Top 1-5", "Top 5-10", "Top 10-15", "Top 15-20", "Top 20-25"]
          and [b.key for b in M.BANDS] == ["1-5", "6-10", "11-15", "16-20", "21-25"])
    check("each set holds its five ranks",
          all(sum(1 for a in M.ACCOUNTS if a.band.key == b.key) == 5 for b in M.BANDS)
          and M.ACCOUNT["sf2L_06"].band.key == "6-10" and M.ACCOUNT["sf2L_05"].band.key == "1-5")
    check("the 18 Nov board's top 3: Three Soldiers / Crows 45m, Triple Top / Bottom 30m, Three Soldiers / Crows 1h",
          [a.pick.strategy_id for a in M.ACCOUNTS[:3]] == ["SF0181", "SF0020", "SF0182"])

    # ── 3. the real trades through every account ────────────────────────────────────────
    section("3. The tab's real trades through all 25 accounts (on an engine without `compound`)")
    real_plan = M.plan_book

    def older_engine(*, capital, realized, deployed, open_rows, parents, decided, breaker_tripped, entries,
                     max_open=None, net_fn=None, source_tag=None, closed_rows=None):
        """plan_book as a server whose shared engine predates 11 Nov has it: no `compound` flag at all."""
        return real_plan(capital=capital, realized=realized, deployed=deployed, open_rows=open_rows, parents=parents,
                         decided=decided, breaker_tripped=breaker_tripped, entries=entries, max_open=max_open,
                         net_fn=net_fn, source_tag=source_tag, closed_rows=closed_rows)

    M.plan_book = older_engine
    fresh(docs=CLOSED)
    out = await M.sync(entries=True)
    check("every account ran on the older engine (nothing passed it a flag it does not have)",
          not any("error" in v for v in out["accounts"].values()),
          {k: v for k, v in out["accounts"].items() if "error" in v})
    check("the pass made new copies with a rate", out["entries"] is True and out["usd_inr"] == FX, out.get("note", ""))
    copied = rows()
    check(f"every one of the {len(CLOSED_PICKS)} closed pick trades copied once, nothing else",
          len(copied) == len(CLOSED_PICKS)
          and {r["parent_position_id"] for r in copied} == {x["position_id"] for x in CLOSED_PICKS},
          f"{len(copied)} copies")
    check("each copy is in its own strategy's account, and only there",
          all(M.ACCOUNT[r["account"]].pick.strategy_id == r["strategy_id"] for r in copied))
    by_parent = {x["position_id"]: x for x in CLOSED_PICKS}
    worst = max(abs(r["realized_pnl"] - expected_net(by_parent[r["parent_position_id"]], r["qty"], FX)) for r in copied)
    check("every copy's net = the tab's result x (its contracts / the tab's size) x the rate", worst <= 0.05,
          f"worst gap Rs {worst:.3f}")
    sized_all, most_open = True, 0
    for a in M.ACCOUNTS:
        rs = sorted(rows(a.id), key=lambda r: r["opened_at"])
        eq = a.capital
        for r in rs:
            if r["qty"] != math.floor(eq / r["entry_price"]):
                sized_all = False
            eq += r["realized_pnl"]
        ev = sorted([(r["opened_at"], 1) for r in rs] + [(r["closed_at"], -1) for r in rs], key=lambda e: (e[0], e[1]))
        n = 0
        for _t, step in ev:
            n += step
            most_open = max(most_open, n)
    check("each entry is sized on its account's realised equity then, in whole contracts", sized_all)
    check("no account ever holds two positions at once", most_open <= 1, f"most open {most_open}")
    f = sorted(copied, key=lambda r: r["opened_at"])[0]
    check("a Rs 2 lakh copy is about twice the tab's $1,111 sleeve",
          1.7 <= f["notional_usd"] / f["parent_notional_usd"] <= 2.0,
          f"{f['qty']} contracts, ${f['notional_usd']:,.0f} vs ${f['parent_notional_usd']:,.0f}")
    snap = copy.deepcopy(M.POSITIONS.docs)
    out2 = await M.sync(entries=True)
    check("a second pass changes nothing", M.POSITIONS.docs == snap)
    check("a pass with nothing to do replays no account", out2["accounts"] == {}, out2["accounts"])
    check("the tab's records were never written", M.PARENTS.writes == 0)
    M.plan_book = real_plan

    # ── 4. an open trade, then its close ────────────────────────────────────────────────
    section("4. An open tab trade: copied, marked, closed when the tab closes it")
    fresh(docs=OPEN_PICKS)
    await M.sync(entries=True)
    ok = True
    for d in OPEN_PICKS:
        r = next(x for x in rows() if x["parent_position_id"] == d["position_id"])
        k = d["entry_px"] * 0.001 * r["qty"] / d["capital_deployed"]
        want = round(d["unrealized_pnl"] * k * FX, 2)
        ok = ok and r["status"] == "OPEN" and abs(r["unrealized_pnl"] - want) <= 0.01
    check(f"all {len(OPEN_PICKS)} open pick trades copied OPEN and marked at the tab's mark x size x rate", ok)
    d = M.PARENTS.docs[0]
    up = 12.0 if d["signal_side"] == "BUY" else -12.0
    d.update(status="CLOSED", exit_px=d["entry_px"] + up, exit_reason="target", exit_basis="strategy level",
             gross_pnl=round(abs(up) / d["entry_px"] * d["capital_deployed"], 2), funding=0.0412,
             fees=round(2 * d["entry_costs"] + 0.0412, 4), closed_at=d["opened_at"] + timedelta(hours=3),
             closed_on=(d["opened_at"] + timedelta(hours=3)).date().isoformat())
    d["realized_pnl"] = round(d["gross_pnl"] - d["fees"], 2)
    set_fx(91.0)                                              # the rate has moved since the copy opened
    await M.sync(entries=True)
    r = next(x for x in rows() if x["parent_position_id"] == d["position_id"])
    check("the copy closed with the tab, at the rate it opened at (not today's)",
          r["status"] == "CLOSED" and abs(r["realized_pnl"] - expected_net(d, r["qty"], FX)) <= 0.05,
          f"Rs {r['realized_pnl']} vs {expected_net(d, r['qty'], FX):.2f}")
    acct = M.ACCOUNT[r["account"]]
    ov = await M.overview()
    s = next(x for x in ov["accounts"] if x["id"] == acct.id)
    check("its account: equity = capital + realised + open, its money free again, one day traded",
          abs(s["equity"] - (s["capital"] + s["realized_pnl"] + s["unrealized_pnl"])) < 0.01
          and abs(s["available_cash"] - (s["capital"] + s["realized_pnl"] - s["deployed"])) < 0.01
          and s["open_positions"] == 0 and s["closed_positions"] == 1 and s["days_traded"] == 1,
          f"cash Rs {s['available_cash']:,.0f}")

    # ── 5. no rate, Main Control off, no back-fill ───────────────────────────────────────
    section("5. No USD/INR rate, Main Control off, no back-fill")
    fresh(docs=OPEN_PICKS[:1], fx=None)
    out = await M.sync(entries=True)
    check("with no USD/INR rate nothing new is copied, and the pass says why",
          not M.POSITIONS.docs and out["entries"] is False and "USD/INR" in out.get("note", ""))
    set_fx(FX)
    await M.sync(entries=True)
    d = M.PARENTS.docs[0]
    d.update(status="CLOSED", exit_px=d["entry_px"], exit_reason="max_hold", gross_pnl=0.0, funding=0.0,
             fees=round(2 * d["entry_costs"], 4), closed_at=d["opened_at"] + timedelta(hours=4), closed_on=d["opened_on"])
    d["realized_pnl"] = round(-d["fees"], 2)
    set_fx(None)
    await M.sync(entries=True)
    check("with no rate an open copy still closes, at its own stored rate",
          rows()[0]["status"] == "CLOSED" and abs(rows()[0]["realized_pnl"] - expected_net(d, rows()[0]["qty"], FX)) <= 0.05)

    fresh(docs=OPEN_PICKS[:1])
    await M.sync(entries=False)
    check("Main Control off (entries=False): no new copy", not M.POSITIONS.docs)

    fresh(start=None, docs=CLOSED + OPEN)
    await M.sync(entries=True)
    check("accounts that start now copy nothing the tab opened before (no back-fill)", not M.POSITIONS.docs)
    starts = [x for x in M.STATE.docs if x.get("kind") == "start"]
    check("every account's start is set once, on its first pass", len(starts) == 25)
    await M.sync(entries=True)
    check("a later pass keeps the same starts", [x for x in M.STATE.docs if x.get("kind") == "start"] == starts)

    # ── 6. the read model ────────────────────────────────────────────────────────────────
    section("6. What the page reads")
    fresh(docs=CLOSED + OPEN)
    await M.sync(entries=True)
    ov = await M.overview()
    accts = {x["id"]: x for x in ov["accounts"]}
    check("25 accounts and 5 sets of five, Rs 10 lakh a set, Rs 50 lakh in all",
          len(accts) == 25 and len(ov["bands"]) == 5 and all(len(b["accounts"]) == 5 for b in ov["bands"])
          and all(b["total"]["capital"] == 1_000_000 for b in ov["bands"]) and ov["total"]["capital"] == 5_000_000)
    check("set labels and ranks as the page shows them",
          [(b["label"], b["ranks"]) for b in ov["bands"]][:2] == [("Top 1-5", "Rank 1-5"), ("Top 5-10", "Rank 6-10")])
    check("every account: equity = capital + realised + open, total return on its Rs 2 lakh",
          all(abs(x["equity"] - (x["capital"] + x["realized_pnl"] + x["unrealized_pnl"])) < 0.01
              and abs(x["roi_pct"] - (x["equity"] - 200000) / 2000) < 1e-3 for x in ov["accounts"]))
    check("a set's total is the sum of its five accounts",
          all(abs(b["total"]["equity"] - sum(accts[i]["equity"] for i in b["accounts"])) < 0.05 for b in ov["bands"]))
    by_sid: dict[str, set] = {}
    for x in CLOSED_PICKS:
        by_sid.setdefault(x["strategy_id"], set()).add(x["closed_on"])
    check("days traded = the IST days the account closed a copy on",
          all(x["days_traded"] == len(by_sid.get(x["strategy_id"], ())) for x in ov["accounts"]),
          {x["id"]: x["days_traded"] for x in ov["accounts"] if x["days_traded"]})
    check("each account says when it started and what it was picked on",
          all(x["started_at"] and x["started_at"].startswith("2026-11-17") for x in ov["accounts"])
          and accts["sf2L_01"]["pick"]["score"] == 82.7 and accts["sf2L_01"]["strategy_id"] == "SF0181")
    one = await M.positions(M.accounts_in(account="sf2L_04"), "CLOSED", 500)
    band = await M.positions(M.accounts_in(band="1-5"), "ALL", 500)
    every = await M.positions(M.accounts_in(), "CLOSED", 500)
    check("positions by account, by set and all: right accounts, latest close first, ISO dates, no Mongo ids",
          all(r["account"] == "sf2L_04" for r in one)
          and {r["account"] for r in band} <= {"sf2L_01", "sf2L_02", "sf2L_03", "sf2L_04", "sf2L_05"}
          and every == sorted(every, key=lambda r: r["closed_at"], reverse=True)
          and all(isinstance(r["opened_at"], str) and "_id" not in r for r in every) and len(every) == len(CLOSED_PICKS))
    check("an unknown account or set is refused (the route answers 404)",
          M.accounts_in(account="sf2L_99") is None and M.accounts_in(band="26-30") is None)
    check("the rate and the notes are on the page", ov["usd_inr"]["rate"] == FX and len(ov["notes"]) >= 5)
    t = ov["total"]
    print(f"\n  (the 18 Nov window through the 25: {t['closed_positions']} copies closed, Rs {t['realized_pnl']:,.2f} "
          f"realised, Rs {t['unrealized_pnl']:,.2f} open - in-sample, not evidence)")


asyncio.run(main())
finish()
