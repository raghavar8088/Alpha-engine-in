"""End-to-end check of NIFTY 50 Option Scalping's Rank-band accounts (20) and Paper-book top-4 accounts (8),
17 Nov 2026, in app.services.top10_books, with an in-memory Mongo. Needs `mongomock-motor` (pip --target is
fine); run from the repo root:
    python backend/tests/top10_books/verify_ns_accounts.py
Real: top10_books (picked books, the NIFTY scalp loader, sizing, groups/accounts), plan_book,
angel_fees.option_round_trip, the routes module. Stubbed: app.core.db (in-memory), intraday_v2_strategies, deps."""
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
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return DB[name]


dbmod = _DbModule("app.core.db")
dbmod.db = DB
sys.modules["app.core.db"] = dbmod
sys.modules["app.services.intraday_v2_strategies"] = types.ModuleType("app.services.intraday_v2_strategies")
deps = types.ModuleType("app.api.deps")


async def get_current_user():
    return {}


deps.get_current_user = get_current_user
sys.modules[deps.__name__] = deps

from app.services import top10_books as t10  # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
START = NOW - timedelta(hours=3)
LOT = 65
BANDS = [(lo, lo + 4) for lo in range(1, 51, 5)]
BAND_KEYS = [f"rank{lo}_{hi}_{s}" for lo, hi in BANDS for s in ("2L", "10L")]
PB_KEYS = [f"pb{n}_{s}" for n in range(1, 5) for s in ("2L", "10L")]
# the screenshot / live board of 17 Nov 2026 20:20 IST
TOP12 = ["ns_5m_38", "ns_5m_23", "ns_10m_48", "ns_10m_22", "ns_10m_31", "ns_10m_26", "ns_1d_46", "ns_1m_25",
         "ns_10m_40", "ns_1m_46", "ns_10m_38", "ns_5m_36"]
PAPER4 = ["ns_5m_46", "ns_4h_28", "ns_1h_13", "ns_1h_12"]


def day(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone(IST).date().isoformat()


def npos(pid, sid, entry, t_open, *, token, status="OPEN", exit_=None, t_close=None, ltp=None):
    d = {"position_id": pid, "strategy_id": sid, "strategy_name": sid, "angel_token": token,
         "symbol": f"NIFTY17NOV26{token}CE", "lot_size": LOT, "lots": 1, "entry_premium": entry,
         "exit_premium": None, "ltp": ltp, "status": status, "expiry": "2026-11-17",
         "opened_at": t_open, "opened_on": day(t_open), "closed_at": None, "closed_on": None, "exit_reason": None}
    if status == "CLOSED":
        d.update({"exit_premium": exit_, "closed_at": t_close, "closed_on": day(t_close), "exit_reason": "target"})
    return d


def definitions():
    keys = t10.book_keys("nifty-scalp")
    check("the desk carries its 4 earlier books, then the 20 Rank-band and 8 Paper-book accounts in order",
          keys[:4] == ["top2L", "top10L", "prem2L", "prem50k"] and keys[4:] == BAND_KEYS + PB_KEYS, str(keys[4:8]))
    check("no other desk gains a book", all(t10.book_keys(k) == ["top2L", "top10L"] for k in t10.DESKS if k != "nifty-scalp"))
    g = t10.groups("nifty-scalp")
    check("groups(): rank-band = 20 in band order, paper-top4 = 8", g.get("rank-band") == BAND_KEYS
          and g.get("paper-top4") == PB_KEYS and set(g) == {"rank-band", "paper-top4"}, str(list(g)))
    top50 = t10._NS_RANK_TOP50
    check("the frozen board: ranks 1-50 once each, ids unique", [p.rank for p in top50] == list(range(1, 51))
          and len({p.key for p in top50}) == 50)
    check("...its top 12 are the board on the owner's screenshot", [p.key for p in top50[:12]] == TOP12)
    for lo, hi in BANDS:
        for s, cap in (("2L", 200_000), ("10L", 1_000_000)):
            pb = t10.picked_book("nifty-scalp", f"rank{lo}_{hi}_{s}")
            ok = (pb is not None and pb.capital == cap and pb.max_open == 5 and [p.rank for p in pb.picks] == list(range(lo, hi + 1))
                  and pb.label == f"Rank {lo}-{hi} · ₹{'2' if s == '2L' else '10'} lakh" and pb.group == "rank-band")
            if not ok:
                check(f"band {lo}-{hi} {s}", False, str(pb))
    check("every band account holds its five ranks, five slots, its capital and label", not [f for f in fails if f.startswith("band ")])
    p4 = t10._NS_PAPER_TOP4
    check("Paper-book top 4 = the roster's ranks 1-4", [p.key for p in p4] == PAPER4 and [p.rank for p in p4] == [1, 2, 3, 4])
    pb1 = t10.picked_book("nifty-scalp", "pb1_2L")
    pb4 = t10.picked_book("nifty-scalp", "pb4_10L")
    check("a Paper-book account is one strategy, one slot, the whole capital a position",
          pb1.picks[0].key == "ns_5m_46" and pb1.max_open == 1 and pb1.capital == 200_000
          and pb1.label == "Paper book #1 Round Number Break 5m · ₹2 lakh"
          and pb4.picks[0].key == "ns_1h_12" and pb4.capital == 1_000_000 and pb4.label == "Paper book #4 RSI Divergence 1h · ₹10 lakh")
    d = t10.DESKS["nifty-scalp"]
    check("position caps: Rs 40,000 / Rs 2,00,000 in a band, Rs 2 / 10 lakh in a Paper-book account",
          t10.position_cap(d, "rank1_5_2L") == 40_000 and t10.position_cap(d, "rank46_50_10L") == 200_000
          and t10.position_cap(d, "pb2_2L") == 200_000 and t10.position_cap(d, "pb3_10L") == 1_000_000)
    check("the earlier books are unchanged", t10.position_cap(d, "top2L") == 40_000
          and abs(t10.position_cap(d, "prem2L") - 66_666.67) < 0.01 and t10.picked_book("nifty-scalp", "prem2L").group == "")


async def trading():
    N = DB["nifty_scalp_positions"]
    for b in t10.book_keys("nifty-scalp"):
        await t10.STATE.insert_one({"_id": f"start:nifty-scalp:{b}", "started_at": START, "desk": "nifty-scalp", "book": b})
    await N.insert_one(npos("r1", "ns_5m_38", 100.0, NOW - timedelta(minutes=120), token="A1", ltp=110.0))   # rank 1
    await N.insert_one(npos("r7", "ns_1d_46", 200.0, NOW - timedelta(minutes=110), token="A2", ltp=205.0))   # rank 7
    await N.insert_one(npos("r50", "ns_15m_24", 50.0, NOW - timedelta(minutes=100), token="A3", ltp=52.0))   # rank 50
    await N.insert_one(npos("p1", "ns_5m_46", 120.0, NOW - timedelta(minutes=90), token="B1", status="CLOSED",
                            exit_=130.0, t_close=NOW - timedelta(minutes=80)))                             # paper #1, rank 24
    await N.insert_one(npos("p1b", "ns_5m_46", 90.0, NOW - timedelta(minutes=70), token="B2", ltp=95.0))     # paper #1 again
    await N.insert_one(npos("p1c", "ns_5m_46", 80.0, NOW - timedelta(minutes=60), token="B3", ltp=81.0))     # while p1b is open
    await N.insert_one(npos("x", "ns_5m_13", 70.0, NOW - timedelta(minutes=50), token="C1", ltp=71.0))       # in no new book
    out = await t10.sync(entries=True, only="nifty-scalp")
    errs = {k: v for k, v in out.items() if "error" in v}
    check("one pass over all 32 books on the desk, no errors", len(out) == 32 and not errs, str(errs)[:300])
    await t10.sync(entries=True, only="nifty-scalp")

    rows = [r async for r in t10.POSITIONS.find({})]
    by = {(r["book"], r["parent_position_id"]): r for r in rows}
    held = lambda b: {pid for (bk, pid) in by if bk == b}   # noqa: E731
    check("rank 1 is copied into band 1-5 only (both sizes), not 6-10",
          "r1" in held("rank1_5_2L") and "r1" in held("rank1_5_10L") and "r1" not in held("rank6_10_2L"))
    check("rank 7 into band 6-10, rank 50 into band 46-50",
          "r7" in held("rank6_10_2L") and "r7" not in held("rank1_5_2L") and "r50" in held("rank46_50_10L"))
    r1s, r1l = by[("rank1_5_2L", "r1")], by[("rank1_5_10L", "r1")]
    check("band sizing: whole lots up to Rs 40,000 / Rs 2,00,000 (6 / 30 lots of a Rs 6,500 lot)",
          r1s["qty"] == 40_000 // (100 * LOT) == 6 and r1l["qty"] == 200_000 // (100 * LOT) == 30, f"{r1s['qty']} {r1l['qty']}")
    check("rank 24 (Round Number Break 5m) is in band 21-25", "p1" in held("rank21_25_2L"))
    p2, p10 = by[("pb1_2L", "p1")], by[("pb1_10L", "p1")]
    check("Paper-book #1 accounts: all-in whole lots (25 / 128 lots of a Rs 7,800 lot), closed at the desk's exit",
          p2["qty"] == 200_000 // (120 * LOT) == 25 and p10["qty"] == 1_000_000 // (120 * LOT) == 128
          and p2["status"] == "CLOSED" and p2["realized_pnl"] < (130 - 120) * LOT * 25, f"{p2['qty']} {p10['qty']}")
    check("one slot: while p1b is open, p1c is skipped as full",
          "p1b" in held("pb1_2L") and "p1c" not in held("pb1_2L") and "p1c" not in held("pb1_10L"))
    sk = {(s["book"], s["key"]): s.get("skipped", {}) async for s in t10.SCORES.find({"desk": "nifty-scalp"})}
    check("...and the skip is counted", sk.get(("pb1_2L", "ns_5m_46"), {}).get("full") == 1, str(sk.get(("pb1_2L", "ns_5m_46"))))
    check("a strategy in none of the 28 is never copied into them",
          not any(pid == "x" for (bk, pid) in by if bk.startswith(("rank", "pb"))))
    check("Paper-book #2-#4 accounts copy only their own strategy", not held("pb2_2L") and not held("pb4_10L"))

    accts = await t10.accounts("nifty-scalp", "rank-band")
    check("accounts('rank-band'): 20 summaries in band order, each its own book",
          [a["book"] for a in accts] == BAND_KEYS and all(a["group"] == "rank-band" and a["picked"] for a in accts))
    a1 = accts[0]
    check("...with capital, roster, slots and copying_since", a1["desk_capital"] == 200_000 and a1["max_open_positions"] == 5
          and a1["roster"] == TOP12[:5] and a1["copying_since"] is not None and a1["open_positions"] == 1)
    pb = await t10.accounts("nifty-scalp", "paper-top4")
    check("accounts('paper-top4'): 8 summaries", [a["book"] for a in pb] == PB_KEYS and pb[0]["closed_positions"] == 1)
    check("an unknown group, or another desk, has none", await t10.accounts("nifty-scalp", "nope") == []
          and await t10.accounts("zero-hero", "rank-band") == [])
    s = await t10.summary("nifty-scalp", "top2L")
    check("a Top-10 book's summary has no group", s["group"] is None and s["picked"] is False)


def routes():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import top10_books as r
    app = FastAPI()
    app.include_router(r.router)
    c = TestClient(app)
    a = c.get("/api/top10-books/nifty-scalp/accounts", params={"group": "rank-band"})
    check("GET /accounts?group=rank-band answers 20", a.status_code == 200 and a.json()["total"] == 20
          and a.json()["groups"]["paper-top4"] == PB_KEYS, str(a.status_code))
    b = c.get("/api/top10-books/nifty-scalp/accounts", params={"group": "paper-top4"})
    check("GET /accounts?group=paper-top4 answers 8", b.status_code == 200 and b.json()["total"] == 8)
    check("an unknown group is a 404, so a page can tell 'not there' from 'empty'",
          c.get("/api/top10-books/nifty-scalp/accounts", params={"group": "nope"}).status_code == 404
          and c.get("/api/top10-books/zero-hero/accounts", params={"group": "rank-band"}).status_code == 404)
    s = c.get("/api/top10-books/nifty-scalp/summary", params={"book": "rank46_50_10L"}).json()
    check("summary of a band account answers for THAT book", s["book"] == "rank46_50_10L" and s["label"] == "Rank 46-50 · ₹10 lakh")


async def main():
    definitions()
    await trading()
    routes()
    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
