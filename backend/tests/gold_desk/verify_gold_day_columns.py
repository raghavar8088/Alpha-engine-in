"""Verify the trading-day figures behind the Gold Desk's strategy tables (2026-11-18). No real Mongo, no network.

Run:  python backend/tests/gold_desk/verify_gold_day_columns.py
Needs mongomock-motor (`pip install mongomock-motor`) for the two grouped aggregations (the Strategy Factory board and
the Gold Lab); the other two use the gold harness's in-memory collection.

Every table on /gold-desk shows, per strategy: the days it traded, the days since it started, its total return and that
return per day traded. The page computes the return and the days since the start; these modules supply the rest:
  * factory_desks.leaderboard: `days_traded` = the IST days a strategy closed a trade on (its `closed_on`);
    factory_desks.summary: `started_at` = the tab's first position.
  * gold_desk.strategies: `days_traded` (the IST day of each close), `started_at` (the venue's first position) and
    `capital` (a strategy's sleeve in record mode, the whole book in account mode).
  * gold_lab.summary: per strategy the New York sessions it had a fill in, and `sessions_since_start` - the NYSE
    sessions since the lab's pre-registration.
  * gold_top5_books.summary: `days_traded` per account, and per pick inside a shared book.
"""

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import Coll, check, finish, section  # noqa: E402

try:
    from mongomock_motor import AsyncMongoMockClient  # noqa: E402
except ImportError:                                    # pragma: no cover - a missing test dependency, said plainly
    print("mongomock-motor is needed: pip install mongomock-motor")
    raise SystemExit(2)

from app.services import factory_desks as fd  # noqa: E402
from app.services import gold_desk as gd  # noqa: E402
from app.services import gold_lab as gl  # noqa: E402
from app.services import gold_top5_books as t5  # noqa: E402
from app.services.gold_lab_rules import nyse_days  # noqa: E402

MDB = AsyncMongoMockClient()["test"]
IST = timezone(timedelta(hours=5, minutes=30))


def n(y, mo, d, h=0, mi=0):
    """A naive UTC time, as Mongo hands them back."""
    return datetime(y, mo, d, h, mi)


def ist_day(t):
    return t.replace(tzinfo=timezone.utc).astimezone(IST).date().isoformat()


async def main():
    # ── 1. the Strategy Factory board ─────────────────────────────────────────────────
    section("1. Strategy Factory board: days traded per strategy, the tab's start")
    fd.POSITIONS, fd.STATE, fd.EQUITY = MDB["fdp"], MDB["fds"], MDB["fde"]
    base = {"desk": "gold", "kind": "perp", "capital_deployed": 1111.11, "fees": 0.26, "gross_pnl": 1.0}
    docs = [
        # SF0181: three closes on two IST days (one just after IST midnight is the NEXT IST day), one open
        {**base, "strategy_id": "SF0181", "status": "CLOSED", "realized_pnl": 5.0, "opened_at": n(2026, 10, 28, 3),
         "closed_at": n(2026, 10, 28, 9), "closed_on": "2026-10-28"},
        {**base, "strategy_id": "SF0181", "status": "CLOSED", "realized_pnl": -2.0, "opened_at": n(2026, 10, 28, 10),
         "closed_at": n(2026, 10, 28, 17), "closed_on": "2026-10-28"},
        {**base, "strategy_id": "SF0181", "status": "CLOSED", "realized_pnl": 3.0, "opened_at": n(2026, 10, 28, 18),
         "closed_at": n(2026, 10, 28, 19), "closed_on": "2026-10-29"},
        {**base, "strategy_id": "SF0181", "status": "OPEN", "realized_pnl": None, "unrealized_pnl": 1.5,
         "opened_at": n(2026, 11, 18, 9), "closed_at": None, "closed_on": None},
        # SF0020: one close; the tab's very first position is its
        {**base, "strategy_id": "SF0020", "status": "CLOSED", "realized_pnl": 7.0, "opened_at": n(2026, 10, 27, 23, 5),
         "closed_at": n(2026, 10, 30, 4), "closed_on": "2026-10-30"},
        # SF0182: open only - it has not traded a day yet
        {**base, "strategy_id": "SF0182", "status": "OPEN", "realized_pnl": None, "unrealized_pnl": -0.5,
         "opened_at": n(2026, 11, 18, 11), "closed_at": None, "closed_on": None},
        # another tab's trade counts for neither
        {**base, "desk": "index-buying", "strategy_id": "SF0181", "status": "CLOSED", "realized_pnl": 9.0,
         "opened_at": n(2026, 10, 20, 4), "closed_at": n(2026, 10, 20, 6), "closed_on": "2026-10-20"},
    ]
    await fd.POSITIONS.insert_many([dict(d) for d in docs])
    lb = {r["strategy_id"]: r for r in await fd.leaderboard("gold")}
    check("days traded = distinct IST close days (2 for three closes on 28-29 Oct IST)", lb["SF0181"]["days_traded"] == 2,
          lb["SF0181"]["days_traded"])
    check("one close is one day; an open-only strategy and an untraded one have 0",
          lb["SF0020"]["days_traded"] == 1 and lb["SF0182"]["days_traded"] == 0 and lb["SF0400"]["days_traded"] == 0)
    check("the other fields are as before (trades, net, open, roi on the $1,111 sleeve)",
          lb["SF0181"]["trades"] == 3 and lb["SF0181"]["net_pnl"] == 6.0 and lb["SF0181"]["open_positions"] == 1
          and abs(lb["SF0181"]["roi_pct"] - 6.0 / (10_000 / 9) * 100) < 1e-3)
    s = await fd.summary("gold")
    check("the tab's start = its first position, another tab's trades not counted",
          s["started_at"] is not None and s["started_at"].startswith("2026-10-27T23:05"), s["started_at"])
    empty = await fd.summary("momentum")
    check("a tab with no position has no start", empty["started_at"] is None)

    # ── 2. the Delta / MCX strategy records ─────────────────────────────────────────────
    section("2. Delta board (H1): days traded, the venue's start, a strategy's capital")
    gd.gold_positions_collection = Coll("gold_positions")
    v = gd.VENUES["delta"]
    spec = gd.specs_for(v)[0]
    sym = v.symbols[0]
    pos = lambda **k: {"venue": "delta", "strategy_template": spec.template, "timeframe": spec.timeframe,  # noqa: E731
                       "symbol": sym, "realized_pnl": 2.0, "costs": 0.3, "net_bp": 18.0, **k}
    gd.gold_positions_collection.docs.extend([
        pos(status="CLOSED", opened_at=n(2026, 10, 11, 12), closed_at=n(2026, 10, 12, 4), closed_on="2026-10-12"),
        pos(status="CLOSED", opened_at=n(2026, 10, 12, 8), closed_at=n(2026, 10, 12, 20)),     # no closed_on: 13 Oct IST
        pos(status="CLOSED", opened_at=n(2026, 10, 13, 0), closed_at=n(2026, 10, 13, 2), closed_on="2026-10-13"),
        pos(status="OPEN", opened_at=n(2026, 11, 18, 8), closed_at=None, unrealized_pnl=4.0),
        pos(status="CLOSED", opened_at=n(2026, 10, 10, 1), closed_at=n(2026, 10, 10, 3), closed_on="2026-10-10",
            void=True),                                                                         # VOID: never counted
    ])
    rows = await gd.strategies(v)
    r = next(x for x in rows if x["template"] == spec.template and x["timeframe"] == spec.timeframe)
    check("days traded = distinct IST close days, a close with no closed_on dated by its IST time",
          r["days_traded"] == 2 and ist_day(n(2026, 10, 12, 20)) == "2026-10-13", r["days_traded"])
    check("the venue's start is its first non-void position", (r["started_at"] or "").startswith("2026-10-11T12:00"),
          r["started_at"])
    check("record mode: a strategy's capital is its sleeve, capital / the strategies it runs",
          abs(r["capital"] - round(v.capital / len(gd.specs_for(v)), 2)) < 1e-9, r["capital"])
    other = [x for x in rows if x is not r]
    check("strategies that never traded: 0 days, the same venue start", all(x["days_traded"] == 0 for x in other)
          and all(x["started_at"] == r["started_at"] for x in other))
    check("the record itself is unchanged (trades, realised, open)",
          r["trades"] == 3 and abs(r["realized_pnl"] - 6.0) < 1e-9 and r["open_positions"] == 1)

    # ── 3. the Gold Lab ───────────────────────────────────────────────────────────────────
    section("3. Gold Lab: New York sessions with a fill, NYSE sessions since it began")
    gl.state_coll, gl.holdings_coll, gl.fills_coll = MDB["gls"], MDB["glh"], MDB["glf"]
    await gl.state_coll.insert_one({"_id": gl.PREREG_ID, "fingerprint": "f", "stored_at": n(2026, 10, 11, 13, 5)})
    await gl.state_coll.insert_one({"_id": "lab", "enabled": True})
    await gl.fills_coll.insert_many([
        {"sid": "gl1", "session": "2026-10-29", "contracts": 177, "at": n(2026, 10, 29, 13, 35)},
        {"sid": "gl1", "session": "2026-10-30", "contracts": 4, "at": n(2026, 10, 30, 13, 35)},
        {"sid": "gl6", "session": "2026-11-02", "contracts": -361, "at": n(2026, 11, 2, 14, 35)},
        {"sid": "gl6", "session": "2026-11-02", "contracts": 1, "at": n(2026, 11, 2, 14, 36)},     # same session
        # a manual close-all has no session: its New York date counts (03:00 UTC on 5 Nov = 4 Nov in New York)
        {"sid": "gl6", "session": None, "reason": "manual_close_all", "contracts": 360, "at": n(2026, 11, 5, 3)},
    ])
    lab = await gl.summary()
    by = {x["id"]: x for x in lab["strategies"]}
    check("gl1: two sessions; gl6: two (two fills in one session count once, the close-all on its NY date)",
          by["gl1"]["days_traded"] == 2 and by["gl6"]["days_traded"] == 2, {k: x["days_traded"] for k, x in by.items()})
    check("a strategy with no fill has 0 days", by["gl2"]["days_traded"] == 0 and by["gl2"]["fills"] == 0)
    today_ny = datetime.now(timezone.utc).astimezone(gl.NY).date()
    want = len(nyse_days(date(2026, 10, 11), today_ny))
    check("sessions since start = NYSE sessions from the pre-registration's New York date to today",
          lab["sessions_since_start"] == want and want >= 28, f"{lab['sessions_since_start']} vs {want}")
    check("the fills count is unchanged", by["gl6"]["fills"] == 3 and by["gl1"]["fills"] == 2)
    await gl.state_coll.delete_one({"_id": gl.PREREG_ID})
    lab2 = await gl.summary()
    check("not pre-registered yet: no session count, the days still there",
          lab2["sessions_since_start"] is None and {x["id"]: x["days_traded"] for x in lab2["strategies"]}["gl1"] == 2)

    # ── 4. the Top-5 accounts ─────────────────────────────────────────────────────────────
    section("4. Top-5 accounts: days traded per account and per pick")
    t5.POSITIONS, t5.STATE = Coll("t5p"), Coll("t5s")
    k1, k2 = t5.PICKS[0].key, t5.PICKS[1].key
    t5.POSITIONS.docs.extend([
        {"book": "top5_2L", "key": k1, "status": "CLOSED", "realized_pnl": 100.0, "fees": 5.0, "gross_pnl": 105.0,
         "closed_at": n(2026, 11, 15, 4), "closed_on": "2026-11-15"},
        {"book": "top5_2L", "key": k1, "status": "CLOSED", "realized_pnl": -40.0, "fees": 5.0, "gross_pnl": -35.0,
         "closed_at": n(2026, 11, 15, 20)},                                    # no closed_on: 16 Nov IST
        {"book": "top5_2L", "key": k2, "status": "CLOSED", "realized_pnl": 30.0, "fees": 5.0, "gross_pnl": 35.0,
         "closed_at": n(2026, 11, 15, 6), "closed_on": "2026-11-15"},
        {"book": "top5_2L", "key": k2, "status": "OPEN", "unrealized_pnl": 12.0, "capital_deployed": 39000.0},
        {"book": "top5_2L", "key": k2, "status": "VOID", "realized_pnl": 0.0, "closed_at": n(2026, 11, 17, 4)},
    ])
    s = await t5.summary(t5.BOOK["top5_2L"])
    per = {x["key"]: x for x in s["strategies"]}
    check("the book: 2 IST days (15 and 16 Nov); a void copy is no day", s["days_traded"] == 2, s["days_traded"])
    check("per pick: 2 days and 1 day; a pick with no close 0",
          per[k1]["days_traded"] == 2 and per[k2]["days_traded"] == 1
          and all(x["days_traded"] == 0 for k, x in per.items() if k not in (k1, k2)))
    check("the book's money is unchanged (realised, open, trades)",
          s["realized_pnl"] == 90.0 and s["unrealized_pnl"] == 12.0 and s["closed_positions"] == 3)


asyncio.run(main())
finish()
