"""End-to-end check of the "Premium Strategy" picked books on NIFTY 50 Option Scalping (prem2L / prem50k, 16 Nov
2026) in app.services.top10_books, with an in-memory Mongo. Needs `pip install mongomock-motor motor fastapi httpx`;
run from the repo root:
    python backend/tests/top10_books/verify_premium_books.py
Real: top10_books (its NIFTY scalp loader, _option_parent, _row, _close_fields, the picked books), plan_book,
angel_fees.option_round_trip (Angel's option card from the repo's shared/), the routes module.
Stubbed: app.core.db (in-memory), intraday_v2_strategies, deps."""
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
deps = types.ModuleType("app.api.deps")


async def get_current_user():
    return {}


deps.get_current_user = get_current_user
sys.modules[deps.__name__] = deps

from app.services import top10_books as t10                # noqa: E402
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
PREM = ["ns_10m_44", "ns_5m_46", "ns_1h_12"]
ALL_BOOKS = ["top2L", "top10L", "prem2L", "prem50k"]
CAP2L, CAP50K = 200_000 / 3, 50_000 / 3


def day(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone(IST).date().isoformat()


def npos(pid, sid, entry, t_open, *, token, status="OPEN", exit_=None, t_close=None, ltp=None):
    """A NIFTY 50 Option Scalping desk position, as nifty_scalp_engine writes it."""
    d = {"position_id": pid, "strategy_id": sid, "strategy_name": sid, "angel_token": token,
         "symbol": f"NIFTY17NOV26{token}CE", "lot_size": LOT, "lots": 1, "entry_premium": entry,
         "exit_premium": None, "ltp": ltp, "status": status, "expiry": "2026-11-17",
         "opened_at": t_open, "opened_on": day(t_open), "closed_at": None, "closed_on": None, "exit_reason": None}
    if status == "CLOSED":
        d.update({"exit_premium": exit_, "closed_at": t_close, "closed_on": day(t_close), "exit_reason": "target"})
    return d


def option_net(entry, exit_, lots, on):
    gross = (exit_ - entry) * LOT * lots
    fb = option_round_trip(entry, max(exit_, 0.0), lots, LOT, on=datetime.fromisoformat(on).date())
    return round(gross, 2), round(gross - fb.total, 2), fb.total


def lots_for(cap, prem):
    return int(cap // (prem * LOT))


async def books():
    N = DB["nifty_scalp_positions"]
    for b in ALL_BOOKS:
        await t10.STATE.insert_one({"_id": f"start:nifty-scalp:{b}", "started_at": START, "desk": "nifty-scalp", "book": b})
    await N.insert_one(npos("old", "ns_10m_44", 150.0, START - timedelta(hours=1), token="T0"))          # before the start
    await N.insert_one(npos("a1", "ns_10m_44", 150.0, NOW - timedelta(minutes=120), token="T1", ltp=160.0))  # Prior Extreme
    await N.insert_one(npos("b1", "ns_5m_46", 120.0, NOW - timedelta(minutes=110), token="T2", status="CLOSED",
                            exit_=132.0, t_close=NOW - timedelta(minutes=100)))                        # Round Number, closed
    await N.insert_one(npos("c1", "ns_1h_12", 300.0, NOW - timedelta(minutes=90), token="T3", ltp=310.0))  # RSI Div, Rs 19,500 a lot
    await N.insert_one(npos("d1", "ns_1m_03", 90.0, NOW - timedelta(minutes=85), token="T6", ltp=91.0))    # a Top-10 pick only
    await N.insert_one(npos("e1", "ns_5m_46", 152.0, NOW - timedelta(minutes=80), token="T1", ltp=160.0))  # the contract a1 holds
    await N.insert_one(npos("g1", "ns_5m_46", 100.0, NOW - timedelta(minutes=70), token="T4", ltp=104.0))  # third slot
    await N.insert_one(npos("h1", "ns_10m_44", 80.0, NOW - timedelta(minutes=60), token="T5", ltp=82.0))   # a fourth at once
    await N.insert_one(npos("z1", "ns_15m_20", 70.0, NOW - timedelta(minutes=55), token="T7", ltp=71.0))    # in no book

    out = await t10.sync(entries=True, only="nifty-scalp")
    errs = {k: v for k, v in out.items() if "error" in v}
    # Since 17 Nov the desk also carries 28 Rank-band / Paper-book top-4 accounts (verify_ns_accounts.py).
    check("first pass: every book on the desk ran without an error, the Premium two among them",
          sorted(out) == sorted(f"nifty-scalp:{b}" for b in t10.book_keys("nifty-scalp"))
          and {f"nifty-scalp:{b}" for b in ALL_BOOKS} <= set(out) and not errs, str(errs or sorted(out)))
    out2 = await t10.sync(entries=True, only="nifty-scalp")      # a copy opened in a pass is marked on the next
    check("second pass is clean", not [k for k, v in out2.items() if "error" in v])

    rows = [r async for r in t10.POSITIONS.find({})]
    by = {(r["book"], r["parent_position_id"]): r for r in rows}
    in_book = lambda b: {pid for (bk, pid) in by if bk == b}   # noqa: E731
    p2, p5 = in_book("prem2L"), in_book("prem50k")

    check("nothing opened before the book's start is copied", not any(pid == "old" for (_, pid) in by))
    check("a strategy in no book is never copied", not any(pid == "z1" for (_, pid) in by))
    check("a Top-10 pick that is not one of the three never enters the Premium books",
          "d1" not in p2 and "d1" not in p5 and "d1" in in_book("top2L") and "d1" in in_book("top10L"))
    check("Round Number Break 5m (not a Top-10 pick) is copied only into the Premium books",
          "b1" in p2 and "b1" in p5 and "b1" not in in_book("top2L") and "b1" not in in_book("top10L"))
    a2, a5 = by.get(("prem2L", "a1")), by.get(("prem50k", "a1"))
    check("Rs 2 lakh: a position is whole lots up to a third of the account (Rs 66,667)",
          a2 is not None and a2["qty"] == lots_for(CAP2L, 150.0) == 6 and abs(a2["capital_deployed"] - 6 * 150.0 * LOT) < 0.01,
          str(a2 and a2.get("qty")))
    check("Rs 50k: a position is whole lots up to a third of the account (Rs 16,667)",
          a5 is not None and a5["qty"] == lots_for(CAP50K, 150.0) == 1 and abs(a5["capital_deployed"] - 150.0 * LOT) < 0.01,
          str(a5 and a5.get("qty")))
    check("each copy carries its book, the owner's name for the strategy and the contract",
          a2 is not None and a2["book"] == "prem2L" and a2["desk"] == "nifty-scalp" and a2["source"] == "top10"
          and a2["strategy_name"] == "Prior Extreme Breakout · 10 minutes" and a2["label"] == "NIFTY17NOV26T1CE")
    check("an open copy is marked at the desk's LTP", a2 is not None
          and abs(a2["unrealized_pnl"] - (160.0 - 150.0) * LOT * 6) < 0.01, str(a2 and a2.get("unrealized_pnl")))
    b2 = by.get(("prem2L", "b1"))
    lb2 = lots_for(CAP2L, 120.0)
    g, n, fee = option_net(120.0, 132.0, lb2, day(NOW - timedelta(minutes=100)))
    check("opened-and-closed between looks: booked closed at the desk's exit, Angel's option card on the book's lots",
          b2 is not None and b2["status"] == "CLOSED" and b2["qty"] == lb2 and abs(b2["gross_pnl"] - g) < 0.01
          and abs(b2["realized_pnl"] - n) < 0.01 and abs(b2["fees"] - round(fee, 2)) < 0.01,
          f"{b2 and (b2.get('qty'), b2.get('gross_pnl'), b2.get('realized_pnl'))} vs {(lb2, g, n)}")
    c2 = by.get(("prem2L", "c1"))
    check("a Rs 300 option (Rs 19,500 a lot): the Rs 2 lakh account buys 3 lots",
          c2 is not None and c2["qty"] == lots_for(CAP2L, 300.0) == 3, str(c2 and c2.get("qty")))
    check("...the Rs 50k account cannot afford one lot within its Rs 16,667 slot: skipped", "c1" not in p5)
    check("the same contract twice at once is never held: the second strategy's entry is skipped",
          "e1" not in p2 and "e1" not in p5)
    check("three positions at once is the most: with three open, a fourth is skipped in the Rs 2 lakh account",
          "g1" in p2 and "h1" not in p2)
    check("...while the Rs 50k account, which skipped the Rs 300 option, still had a slot for it",
          "g1" in p5 and "h1" in p5 and by[("prem50k", "h1")]["qty"] == lots_for(CAP50K, 80.0))

    sk = {(s["book"], s["key"]): s.get("skipped", {}) async for s in t10.SCORES.find({"desk": "nifty-scalp"})}
    check("skips are counted by reason: one lot above the slot",
          sk.get(("prem50k", "ns_1h_12"), {}).get("price_above_cap") == 1, str(sk.get(("prem50k", "ns_1h_12"))))
    check("...the contract already held", sk.get(("prem2L", "ns_5m_46"), {}).get("symbol_held") == 1
          and sk.get(("prem50k", "ns_5m_46"), {}).get("symbol_held") == 1, str(sk.get(("prem2L", "ns_5m_46"))))
    check("...and the slots full", sk.get(("prem2L", "ns_10m_44"), {}).get("full") == 1, str(sk.get(("prem2L", "ns_10m_44"))))

    # The desk closes a1 at 170: the Premium copies close at the same price.
    await N.update_one({"position_id": "a1"}, {"$set": {"status": "CLOSED", "exit_premium": 170.0,
                                                        "closed_at": NOW - timedelta(minutes=5),
                                                        "closed_on": day(NOW - timedelta(minutes=5)),
                                                        "exit_reason": "target"}})
    await t10.sync(entries=True, only="nifty-scalp")
    a2b = await t10.POSITIONS.find_one({"book": "prem2L", "parent_position_id": "a1"})
    a5b = await t10.POSITIONS.find_one({"book": "prem50k", "parent_position_id": "a1"})
    _, n2, _ = option_net(150.0, 170.0, 6, day(NOW - timedelta(minutes=5)))
    _, n5, _ = option_net(150.0, 170.0, 1, day(NOW - timedelta(minutes=5)))
    check("when the desk closes, both Premium copies close at its exit, each on its own lots",
          a2b["status"] == "CLOSED" and abs(a2b["realized_pnl"] - n2) < 0.01
          and a5b["status"] == "CLOSED" and abs(a5b["realized_pnl"] - n5) < 0.01,
          f"{a2b.get('realized_pnl')} vs {n2}; {a5b.get('realized_pnl')} vs {n5}")
    n_before = await t10.POSITIONS.count_documents({})
    await t10.sync(entries=True, only="nifty-scalp")
    check("passes are idempotent: no duplicate copies", await t10.POSITIONS.count_documents({}) == n_before)

    s2 = await t10.summary("nifty-scalp", "prem2L")
    s5 = await t10.summary("nifty-scalp", "prem50k")
    check("Premium Strategy · ₹2 lakh: Rs 2 lakh, three slots of Rs 66,667, the three picks, a picked book",
          s2["label"] == "Premium Strategy · ₹2 lakh" and s2["desk_capital"] == 200_000 and s2["max_open_positions"] == 3
          and abs(s2["position_cap"] - 66_666.67) < 0.01 and s2["roster"] == PREM and s2["strategies"] == 3
          and s2["picked"] is True and "Prior Extreme Breakout" in (s2["pick_rule"] or "")
          and s2["picked_at"].startswith("2026-11-16"), str({k: s2.get(k) for k in ("label", "desk_capital", "position_cap")}))
    check("Premium Strategy · ₹50k: Rs 50,000, three slots of Rs 16,667",
          s5["label"] == "Premium Strategy · ₹50k" and s5["desk_capital"] == 50_000 and abs(s5["position_cap"] - 16_666.67) < 0.01
          and s5["max_open_positions"] == 3 and s5["roster"] == PREM)
    realized = sum([r["realized_pnl"] async for r in t10.POSITIONS.find({"book": "prem2L", "status": "CLOSED"})])
    check("the summary adds up its own rows only", abs(s2["realized_pnl"] - realized) < 0.05
          and s2["books"][:4] == ALL_BOOKS and s2["book_labels"]["prem50k"] == "Premium Strategy · ₹50k",
          f"{s2['realized_pnl']} vs {realized}")
    check("the Premium notes travel with the book", any("slot for each of the three" in x for x in s2["notes"]))
    st = await t10.summary("nifty-scalp", "top2L")
    check("the desk's Top 10 books are unchanged: ten picks, five slots of Rs 40,000, not a picked book",
          st["label"] == "Top 10 Paper Trade · ₹2 lakh" and st["strategies"] == 10 and st["max_open_positions"] == 5
          and st["position_cap"] == 40_000 and st["picked"] is False and st["pick_rule"] is None
          and st["picked_at"] == t10.PICKED_AT)
    at = await t10.POSITIONS.find_one({"book": "top2L", "parent_position_id": "a1"})
    check("...and size their own copies as before (Rs 40,000 a position)", at is not None and at["qty"] == lots_for(40_000, 150.0))

    lb = await t10.leaderboard("nifty-scalp", "prem50k")
    check("Premium leaderboard: the three in pick order, where each stood when picked",
          [r["key"] for r in lb] == PREM and [r["picked_rank"] for r in lb] == [1, 1, 2]
          and [r["picked_score"] for r in lb] == [60.7, 99.1, 65.0], str([(r["key"], r["picked_rank"]) for r in lb]))
    check("...each with its share of this account", abs(lb[0]["roi_pct"] - lb[0]["net_pnl"] / 50_000 * 100) < 1e-3)
    pos = await t10.positions("nifty-scalp", "prem2L", "ALL")
    check("positions() lists only this book's rows", pos and all(r["book"] == "prem2L" for r in pos))


async def other_desks():
    check("only NIFTY 50 Option Scalping carries the Premium books", t10.book_keys("nifty-scalp")[:4] == ALL_BOOKS
          and all(t10.book_keys(k) == ["top2L", "top10L"] for k in t10.DESKS if k != "nifty-scalp"))
    check("a Premium key on another desk falls back to its first Top-10 book",
          t10.normalize_book("prem2L", "zero-hero") == "top2L" and t10.normalize_book("prem50k", "nifty-scalp") == "prem50k"
          and t10.normalize_book("prem2L") == "top2L" and t10.normalize_book("nope", "nifty-scalp") == "top2L")
    out = await t10.sync(entries=True, only="zero-hero")
    check("another desk still runs exactly its two books", sorted(out) == ["zero-hero:top10L", "zero-hero:top2L"], str(sorted(out)))


def routes():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import top10_books as r
    app = FastAPI()
    app.include_router(r.router)
    c = TestClient(app)
    s = c.get("/api/top10-books/nifty-scalp/summary", params={"book": "prem50k"})
    lb = c.get("/api/top10-books/nifty-scalp/leaderboard", params={"book": "prem2L"})
    pos = c.get("/api/top10-books/nifty-scalp/positions", params={"book": "prem2L", "status": "ALL"})
    check("GET summary / leaderboard / positions answer for the Premium books",
          s.status_code == 200 and s.json()["label"] == "Premium Strategy · ₹50k" and lb.status_code == 200
          and lb.json()["book"] == "prem2L" and lb.json()["total"] == 3 and pos.status_code == 200
          and pos.json()["book"] == "prem2L" and all(p["book"] == "prem2L" for p in pos.json()["positions"]),
          f"{s.status_code} {lb.status_code} {pos.status_code}")
    z = c.get("/api/top10-books/zero-hero/summary", params={"book": "prem2L"})
    check("another desk asked for a Premium book answers with its own Top 10 · ₹2 lakh",
          z.status_code == 200 and z.json()["book"] == "top2L")
    d = c.get("/api/top10-books/desks").json()
    ns = next(x for x in d["desks"] if x["desk"] == "nifty-scalp")
    check("/desks names every book on each desk", [b["book"] for b in ns["desk_books"]][:4] == ALL_BOOKS
          and ns["desk_books"][2]["capital"] == 200_000 and ns["desk_books"][3]["picks"] == PREM
          and all(len(x["desk_books"]) == 2 for x in d["desks"] if x["desk"] != "nifty-scalp"))


async def main():
    await books()
    await other_desks()
    routes()
    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
