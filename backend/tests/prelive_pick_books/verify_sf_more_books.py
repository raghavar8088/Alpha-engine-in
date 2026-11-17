"""End-to-end check of the Strategy Factory Rank-band and all-546 paper accounts on Index Option Buying (17 Nov 2026,
app.services.prelive_pick_books) with an in-memory Mongo. Needs `pip install mongomock-motor motor fastapi httpx`;
run from the repo root:
    python backend/tests/prelive_pick_books/verify_sf_more_books.py
Real: prelive_pick_books, prelive_pick_roster, top10_books (_option_parent, _row, _close_fields), plan_book,
angel_fees.option_round_trip, the routes module. Stubbed: app.core.db (in-memory), factory_desks (only its POSITIONS
collection), intraday_v2_strategies, deps."""
import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "shared"))
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

DB = AsyncMongoMockClient()["test"]


class _DbModule(types.ModuleType):
    def __getattr__(self, name):          # any `*_collection` the imported modules ask for
        if name.startswith("__"):
            raise AttributeError(name)
        return DB[name]


dbmod = _DbModule("app.core.db")
dbmod.db = DB
sys.modules["app.core.db"] = dbmod
v2 = types.ModuleType("app.services.intraday_v2_strategies")
sys.modules[v2.__name__] = v2
fd = types.ModuleType("app.services.factory_desks")
fd.POSITIONS = DB["factory_desk_positions"]          # in production: the tab's own MongoDB
sys.modules[fd.__name__] = fd
deps = types.ModuleType("app.api.deps")


async def get_current_user():
    return {}


deps.get_current_user = get_current_user
sys.modules[deps.__name__] = deps

from app.services import prelive_pick_books as pb          # noqa: E402
from app.services.prelive_pick_roster import SF546, RANKED  # noqa: E402
from app.services.angel_fees import option_round_trip      # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def utc_naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


NOW = utc_naive(datetime.now(timezone.utc)).replace(microsecond=0)
START = NOW - timedelta(hours=3)
IST = timezone(timedelta(hours=5, minutes=30))
LOT = 65
BANDS = [f"sfb{lo}_{lo + 4}_{s}" for lo in range(1, 51, 5) for s in ("2L", "10L")]
ALL = ("sf_all_2L", "sf_all_10L")


def day(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone(IST).date().isoformat()


def fpos(pid, sid, entry, t_open, *, token="45396", status="OPEN", exit_=None, t_close=None, mark=None):
    """A Strategy Factory tab position, as factory_desks writes it."""
    d = {"position_id": pid, "desk": "index-buying", "strategy_id": sid, "strategy_name": sid, "kind": "option_buy",
         "timeframe": "15m", "symbol": "NIFTY", "signal_side": "BUY", "side": "BUY",
         "legs": [{"token": token, "tradingsymbol": f"NIFTY17NOV26{token}CE", "strike": 25250.0, "option_type": "CE",
                   "expiry": "2026-11-24", "side": "BUY", "entry": entry}],
         "lots": 1, "lot_size": LOT, "entry_px": entry, "capital_deployed": round(entry * LOT, 2), "status": status,
         "opened_at": t_open, "opened_on": day(t_open), "closed_at": None, "closed_on": None, "exit_reason": None}
    if mark is not None:
        d["mark_legs"] = [mark]
    if status == "CLOSED":
        d.update({"exit_legs": [exit_], "closed_at": t_close, "closed_on": day(t_close), "exit_reason": "target"})
    return d


def option_net(entry, exit_, lots, on):
    gross = (exit_ - entry) * LOT * lots
    fb = option_round_trip(entry, max(exit_, 0.0), lots, LOT, on=datetime.fromisoformat(on).date())
    return round(gross, 2), round(gross - fb.total, 2)


def roster():
    ids = [r[0] for r in SF546]
    ranked = [r for r in SF546 if r[1] is not None]
    check("roster: 546 distinct strategies, SF0001-SF0546", len(ids) == 546 and len(set(ids)) == 546
          and sorted(ids) == [f"SF{i:04d}" for i in range(1, 547)])
    check("roster: 161 ranked first, in Rank order 1..161, then the unranked by id",
          RANKED == 161 and [r[1] for r in ranked] == list(range(1, 162)) and SF546[:161] == tuple(ranked)
          and [r[0] for r in SF546[161:]] == sorted(r[0] for r in SF546[161:]))
    check("roster: the board's top 5 as read at 20:35 IST", [r[0] for r in SF546[:5]]
          == ["SF0107", "SF0327", "SF0400", "SF0329", "SF0471"])

    check("22 new books: 20 bands then the two all-546 books, after the six earlier ones",
          pb.BOOK_KEYS[6:] == BANDS + list(ALL) and len(pb.BOOKS) == 28, str(pb.BOOK_KEYS[6:9]))
    ok = True
    for lo in range(1, 51, 5):
        for s, cap in (("2L", 200_000), ("10L", 1_000_000)):
            b = pb.BOOKS[f"sfb{lo}_{lo + 4}_{s}"]
            ok &= ([p.rank for p in b.picks] == list(range(lo, lo + 5)) and b.capital == cap and b.slots == 5
                   and not b.per_strategy and b.group == "sf-bands" and b.accounts() == [("book", {p.key for p in b.picks})]
                   and b.picked_at == "2026-11-17T20:35:00+05:30" and b.total_capital == cap)
    check("every band: its five ranks, one shared account of Rs 2 lakh / Rs 10 lakh, five slots, group sf-bands", ok)
    b2, b10 = pb.BOOKS["sf_all_2L"], pb.BOOKS["sf_all_10L"]
    check("all-546 books: each strategy its own Rs 2 lakh / Rs 10 lakh, one position at a time",
          len(b2.picks) == 546 and b2.per_strategy and b2.slots == 1 and b2.capital == 200_000
          and b2.total_capital == 109_200_000 and b10.total_capital == 546_000_000 and len(b10.accounts()) == 546
          and b2.group == "" and b10.capital == 1_000_000)
    check("labels", pb.BOOK_LABEL["sfb1_5_2L"] == "Strategy Factory Rank 1-5 · ₹2 lakh"
          and pb.BOOK_LABEL["sfb46_50_10L"] == "Strategy Factory Rank 46-50 · ₹10 lakh"
          and pb.BOOK_LABEL["sf_all_10L"] == "All 546 Factory Strategies · ₹10 lakh each", str(pb.BOOK_LABEL["sfb1_5_2L"]))
    twins = [n for n in pb.BOOKS["sfb11_15_2L"].desk.notes if "same record" in n]
    check("band 11-15 notes the pair with the same trades (SF0330 / SF0474)", len(twins) == 1
          and "#12 Trend Pullback to EMA · 30m" in twins[0] and "#13 Pullback + EMA + RSI + VWAP · 30m" in twins[0], str(twins))
    check("band 16-20 notes its pair too (SF0475 / SF0331), band 1-5 has none",
          sum("same record" in n for n in pb.BOOKS["sfb16_20_10L"].desk.notes) == 1
          and not any("same record" in n for n in pb.BOOKS["sfb1_5_2L"].desk.notes))
    check("a band's slot is a fifth of it in its notes", "₹40,000" in pb.BOOKS["sfb1_5_2L"].desk.notes[0]
          and "₹2,00,000" in pb.BOOKS["sfb1_5_10L"].desk.notes[0])


async def copies():
    F = DB["factory_desk_positions"]
    for b in pb.BOOKS:
        await pb.STATE.insert_one({"_id": f"start:{b}", "started_at": START, "book": b})
    t = NOW - timedelta(minutes=120)
    await F.insert_many([
        fpos("old", "SF0107", 150.0, START - timedelta(minutes=5)),                        # before the start
        fpos("a1", "SF0107", 150.0, t, mark=160.0),                                        # #1, open
        fpos("a2", "SF0327", 700.0, t + timedelta(minutes=1), token="45401", mark=705.0),  # #2: a lot is Rs 45,500
        fpos("t1", "SF0330", 110.0, t + timedelta(minutes=2), token="45402", mark=111.0),  # #12 and #13, the same
        fpos("t2", "SF0474", 110.0, t + timedelta(minutes=2), token="45402", mark=111.0),  #   contract at once
        fpos("u1", "SF0001", 90.0, t + timedelta(minutes=3), token="45403", status="CLOSED", exit_=120.0,
             t_close=t + timedelta(minutes=30)),                                           # unranked: all-546 only
        fpos("r51", "SF0421", 200.0, t + timedelta(minutes=4), token="45404", mark=190.0), # #51: all-546 only
        fpos("x", "SF9999", 100.0, t + timedelta(minutes=5), token="45405"),               # not on the tab's roster
    ])
    out = await pb.sync(entries=True)
    check("first pass: every book ran, no account failed",
          len(out) == 28 and all("error" not in v and not v["errors"] for v in out.values()), str(out)[:300])
    check("all-546: one pass touches only the accounts with work (6 of 546), not all of them",
          out["sf_all_2L"]["accounts"] == 546 and out["sf_all_2L"]["active"] == 6, str(out["sf_all_2L"]))
    out2 = await pb.sync(entries=True)
    check("second pass: an all-546 book replays only the accounts holding a position",
          out2["sf_all_2L"]["active"] == 5 and out2["sf_all_2L"]["opened"] == 0 and out2["sfb1_5_2L"]["opened"] == 0,
          str(out2["sf_all_2L"]))
    rows = [r async for r in pb.POSITIONS.find({})]
    by = {(r["book"], r["parent_position_id"]): r for r in rows}
    check("nothing before the start and nothing off the roster is copied",
          not [k for k in by if k[1] in ("old", "x")])

    a = by.get(("sfb1_5_2L", "a1"))
    lots = int(40_000 // (150.0 * LOT))
    check("band Rs 2 lakh: a position is up to its Rs 40,000 slot, one shared account", a is not None
          and a["qty"] == lots and a["account"] == "book" and a["allocation"] is None
          and abs(a["unrealized_pnl"] - (160.0 - 150.0) * LOT * lots) < 0.01, str(a and a.get("qty")))
    a10 = by.get(("sfb1_5_10L", "a1"))
    check("band Rs 10 lakh: the same trade up to its Rs 2,00,000 slot",
          a10 is not None and a10["qty"] == int(200_000 // (150.0 * LOT)))
    check("band Rs 2 lakh: a lot above the slot is skipped (price above cap); the Rs 10 lakh band takes it",
          ("sfb1_5_2L", "a2") not in by and ("sfb1_5_10L", "a2") in by
          and by[("sfb1_5_10L", "a2")]["qty"] == int(200_000 // (700.0 * LOT)))
    sc = await pb.SCORES.find_one({"book": "sfb1_5_2L", "key": "SF0327"})
    check("that skip is counted by reason", sc is not None and sc["skipped"].get("price_above_cap") == 1, str(sc))
    check("band 11-15: two of its five on one contract at once - the first is held, the second skipped",
          ("sfb11_15_2L", "t1") in by and ("sfb11_15_2L", "t2") not in by)
    sc2 = await pb.SCORES.find_one({"book": "sfb11_15_2L", "key": "SF0474"})
    check("... counted as symbol_held", sc2 is not None and sc2["skipped"].get("symbol_held") == 1, str(sc2))
    check("a trade lands in its own band only", not [k for k in by if k[1] == "a1" and k[0].startswith("sfb")
                                                     and k[0] not in ("sfb1_5_2L", "sfb1_5_10L")])

    s1 = by.get(("sf_all_2L", "a1"))
    check("all-546 Rs 2 lakh: the strategy's own account, whole lots up to its Rs 2 lakh", s1 is not None
          and s1["account"] == "SF0107" and s1["qty"] == int(200_000 // (150.0 * LOT)) and s1["allocation"] == 200_000
          and s1["strategy_name"] == "Engulfing Candle · 15m")
    check("all-546: the two strategies on one contract each trade in their own account",
          by.get(("sf_all_10L", "t1"), {}).get("account") == "SF0330"
          and by.get(("sf_all_10L", "t2"), {}).get("account") == "SF0474")
    u = by.get(("sf_all_10L", "u1"))
    lu = int(1_000_000 // (90.0 * LOT))
    g, n = option_net(90.0, 120.0, lu, day(t + timedelta(minutes=30)))
    check("an unranked strategy trades in the all-546 books, opened and closed between looks, at the tab's prices",
          u is not None and u["status"] == "CLOSED" and u["qty"] == lu and abs(u["realized_pnl"] - n) < 0.01
          and abs(u["gross_pnl"] - g) < 0.01, str(u and (u.get("qty"), u.get("realized_pnl"), n)))
    check("... and in no band; neither does Rank 51",
          not [k for k in by if k[1] in ("u1", "r51") and k[0].startswith("sfb")] and ("sf_all_2L", "r51") in by)

    # The tab closes a1 at 170: every copy closes at the same price, each at its own lots.
    await F.update_one({"position_id": "a1"}, {"$set": {"status": "CLOSED", "exit_legs": [170.0],
                                                        "closed_at": NOW - timedelta(minutes=5),
                                                        "closed_on": day(NOW - timedelta(minutes=5)), "exit_reason": "eod"}})
    await pb.sync(entries=True)
    closed = {r["book"]: r async for r in pb.POSITIONS.find({"parent_position_id": "a1"})}
    want = {b: option_net(150.0, 170.0, closed[b]["qty"], day(NOW - timedelta(minutes=5)))[1] for b in closed}
    check("the tab's close closes the copy in each of its books at the tab's exit (SF0107 was also #2 on 12 Nov)",
          sorted(closed) == ["sf_all_10L", "sf_all_2L", "sf_top10", "sfb1_5_10L", "sfb1_5_2L"]
          and all(r["status"] == "CLOSED" and abs(r["realized_pnl"] - want[b]) < 0.01 for b, r in closed.items()),
          str({b: (r["status"], r.get("realized_pnl"), want[b]) for b, r in closed.items()}))
    n_before = await pb.POSITIONS.count_documents({})
    await pb.sync(entries=True)
    check("passes are idempotent", await pb.POSITIONS.count_documents({}) == n_before)

    s = await pb.summary("sfb1_5_2L")
    check("band summary: Rs 2 lakh, five slots of Rs 40,000, its five ranks and names, group sf-bands",
          s["desk_capital"] == 200_000 and s["max_open_positions"] == 5 and s["position_cap"] == 40_000
          and s["per_strategy"] is False and s["board_ranks"] == [1, 2, 3, 4, 5] and s["group"] == "sf-bands"
          and s["pick_names"][0] == "Engulfing Candle · 15m" and s["picked_at"] == "2026-11-17T20:35:00+05:30"
          and s["source_label"] == "the tab" and s["closed_positions"] == 1)
    sa = await pb.summary("sf_all_2L")
    check("all-546 summary: Rs 10.92 crore over 546 accounts, its roster left to the leaderboard",
          sa["desk_capital"] == 109_200_000 and sa["strategies"] == 546 and sa["per_strategy_capital"] == 200_000
          and sa["roster"] is None and sa["board_ranks"] is None and sa["group"] is None
          and sa["strategies_traded"] == 6 and sa["max_open_positions"] == 546, str({k: sa[k] for k in ("strategies_traded",)}))
    lb = await pb.leaderboard("sf_all_2L")
    check("all-546 leaderboard: 546 rows, ranked first in Rank order, the unranked after with no rank",
          len(lb) == 546 and [r["picked_rank"] for r in lb[:161]] == list(range(1, 162))
          and all(r["picked_rank"] is None for r in lb[161:]) and lb[0]["key"] == "SF0107"
          and lb[0]["allocation"] == 200_000 and lb[0]["trades"] == 1)
    acc = await pb.accounts("sf-bands")
    check("accounts(sf-bands): the 20 band summaries, in band order", [x["book"] for x in acc] == BANDS)
    check("groups(): only the bands are grouped", pb.groups() == {"sf-bands": BANDS})
    books = pb.books()
    check("books(): an all-546 book gives its count, not 546 picks", books[-1]["picks"] is None
          and books[-1]["strategies"] == 546 and len(books[6]["picks"]) == 5)


def routes():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import prelive_pick_books as r
    app = FastAPI()
    app.include_router(r.router)
    c = TestClient(app)
    a = c.get("/api/prelive-pick-books/accounts", params={"group": "sf-bands"})
    check("GET /accounts?group=sf-bands: 20 accounts", a.status_code == 200 and a.json()["total"] == 20
          and a.json()["accounts"][0]["book"] == "sfb1_5_2L", str(a.status_code))
    nope = c.get("/api/prelive-pick-books/accounts", params={"group": "nope"})
    check("GET /accounts of an unknown group: 404 (a page never shows another book under these names)",
          nope.status_code == 404)
    lb = c.get("/api/prelive-pick-books/leaderboard", params={"book": "sf_all_10L"})
    check("GET leaderboard of an all-546 book over HTTP", lb.status_code == 200 and lb.json()["total"] == 546)


async def main():
    roster()
    await copies()
    routes()
    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
