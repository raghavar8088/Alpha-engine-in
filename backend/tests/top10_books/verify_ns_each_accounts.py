"""End-to-end check of NIFTY 50 Option Scalping's "top 25, each on its own Rs 2 lakh" accounts and the two
"Prime Premium Strategies" accounts (18 Nov 2026) in
app.services.top10_books, with an in-memory Mongo. Needs `mongomock-motor` (pip --target is fine); run from the
repo root:
    python backend/tests/top10_books/verify_ns_each_accounts.py
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
EACH_KEYS = [f"each{r}_2L" for r in range(1, 26)]
# the owner's screenshot of 18 Nov 2026 (Strategy leaderboard · all 504), ranks 1-9
SHOT9 = ["ns_5m_23", "ns_10m_48", "ns_10m_31", "ns_5m_38", "ns_10m_26", "ns_1d_46", "ns_10m_22", "ns_10m_40",
         "ns_1m_25"]


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
    check("the 25 accounts come after the 32 earlier books, in Rank order, then prime2L and prime10L",
          keys[32:57] == EACH_KEYS and keys[57:] == ["prime2L", "prime10L"], str(keys[30:34]))
    check("the earlier 32 are untouched and in place", keys[:4] == ["top2L", "top10L", "prem2L", "prem50k"]
          and keys[4] == "rank1_5_2L" and keys[31] == "pb4_10L")
    g = t10.groups("nifty-scalp")
    check("groups(): top25-each = the 25 in order; rank-band and paper-top4 unchanged",
          g.get("top25-each") == EACH_KEYS and len(g.get("rank-band", [])) == 20 and len(g.get("paper-top4", [])) == 8)
    top = t10._NS_RANK_TOP25_1811
    check("the frozen board: ranks 1-25 once each, ids unique", [p.rank for p in top] == list(range(1, 26))
          and len({p.key for p in top}) == 25)
    check("...its ranks 1-9 are the owner's screenshot", [p.key for p in top[:9]] == SHOT9)
    check("...names match the screenshot", top[0].name == "Bollinger %B Extreme · 5 minutes"
          and top[1].name == "Fibonacci 61.8% Bounce · 10 minutes" and top[8].name == "Donchian Fast Break · 1 minute")
    check("the 17 Nov board is not changed by the new pick", [p.key for p in t10._NS_RANK_TOP50[:2]] == ["ns_5m_38", "ns_5m_23"])
    d = t10.DESKS["nifty-scalp"]
    bad = []
    for p in top:
        k = f"each{p.rank}_2L"
        pb = t10.picked_book("nifty-scalp", k)
        lo = (p.rank - 1) // 5 * 5 + 1
        ok = (pb is not None and pb.capital == 200_000 and pb.max_open == 1 and pb.picks == (p,)
              and pb.group == "top25-each" and pb.label == f"#{p.rank} {t10._ns_short(p.name)} · ₹2 lakh"
              and f"set Top {lo}-{lo + 4}" in pb.pick_rule and pb.picked_at == "2026-11-18T22:59:00+05:30"
              and t10.position_cap(d, k) == 200_000)
        if not ok:
            bad.append(k)
    check("every account: one strategy, one slot, Rs 2 lakh, its set in the rule, its label", not bad, str(bad))
    check("labels read like the board", t10.picked_book("nifty-scalp", "each1_2L").label == "#1 Bollinger %B Extreme 5m · ₹2 lakh"
          and t10.picked_book("nifty-scalp", "each6_2L").label == "#6 Round Number Break 1d · ₹2 lakh")
    p2, p10 = t10.picked_book("nifty-scalp", "prime2L"), t10.picked_book("nifty-scalp", "prime10L")
    check("Prime Premium Strategies: the Paper book's #1 and #2, in one account with a slot each",
          [p.key for p in p2.picks] == ["ns_5m_46", "ns_4h_28"] and p2.picks == p10.picks and p2.max_open == 2
          and p10.max_open == 2 and p2.capital == 200_000 and p10.capital == 1_000_000 and p2.group == ""
          and p2.label == "Prime Premium Strategies · ₹2 lakh" and p10.label == "Prime Premium Strategies · ₹10 lakh")
    check("...a slot is half the account: Rs 1,00,000 / Rs 5,00,000",
          t10.position_cap(d, "prime2L") == 100_000 and t10.position_cap(d, "prime10L") == 500_000)


async def trading():
    N = DB["nifty_scalp_positions"]
    for b in t10.book_keys("nifty-scalp"):
        await t10.STATE.insert_one({"_id": f"start:nifty-scalp:{b}", "started_at": START, "desk": "nifty-scalp", "book": b})
    await N.insert_one(npos("a1", "ns_5m_23", 100.0, NOW - timedelta(minutes=120), token="A1", ltp=110.0))   # #1
    await N.insert_one(npos("a1b", "ns_5m_23", 90.0, NOW - timedelta(minutes=100), token="A2", ltp=91.0))    # #1, slot full
    await N.insert_one(npos("a25", "ns_10m_24", 50.0, NOW - timedelta(minutes=90), token="A3", status="CLOSED",
                            exit_=60.0, t_close=NOW - timedelta(minutes=70)))                            # #25 closed
    await N.insert_one(npos("a19", "ns_5m_46", 120.0, NOW - timedelta(minutes=80), token="A4", ltp=125.0))   # #19 (+ pb1)
    await N.insert_one(npos("a26", "ns_1m_61", 70.0, NOW - timedelta(minutes=60), token="A5", ltp=71.0))     # #26: not picked
    await N.insert_one(npos("old", "ns_10m_48", 80.0, START - timedelta(minutes=30), token="A6", ltp=85.0))  # before start
    await N.insert_one(npos("t4", "ns_4h_28", 60.0, NOW - timedelta(minutes=75), token="A7", ltp=66.0))      # TTM 4h (prime #2)
    out = await t10.sync(entries=True, only="nifty-scalp")
    errs = {k: v for k, v in out.items() if "error" in v}
    check("one pass over all 59 books on the desk, no errors", len(out) == 59 and not errs, str(errs)[:300])
    await t10.sync(entries=True, only="nifty-scalp")

    rows = [r async for r in t10.POSITIONS.find({})]
    by = {(r["book"], r["parent_position_id"]): r for r in rows}
    held = lambda b: {pid for (bk, pid) in by if bk == b}   # noqa: E731
    check("#1's trade is copied into its own account only, among the 25",
          "a1" in held("each1_2L") and not any("a1" in held(k) for k in EACH_KEYS[1:]))
    r = by[("each1_2L", "a1")]
    check("all-in whole lots on Rs 2 lakh: 30 lots of a Rs 6,500 lot", r["qty"] == 200_000 // (100 * LOT) == 30, str(r["qty"]))
    check("one slot: while a1 is open, a1b is skipped", "a1b" not in held("each1_2L"))
    sk = {(s["book"], s["key"]): s.get("skipped", {}) async for s in t10.SCORES.find({"desk": "nifty-scalp"})}
    check("...and the skip is counted as full", sk.get(("each1_2L", "ns_5m_23"), {}).get("full") == 1,
          str(sk.get(("each1_2L", "ns_5m_23"))))
    c = by.get(("each25_2L", "a25"))
    check("#25's closed trade: 61 lots, closed at the desk's exit, net of charges below the gross",
          c is not None and c["qty"] == 200_000 // (50 * LOT) == 61 and c["status"] == "CLOSED"
          and 0 < c["realized_pnl"] < (60 - 50) * LOT * 61, str(c and (c["qty"], c["realized_pnl"])))
    check("#19 Round Number Break 5m is in its own account AND still in the 17 Nov Paper-book #1 accounts",
          "a19" in held("each19_2L") and "a19" in held("pb1_2L") and "a19" in held("pb1_10L"))
    check("#26 is in none of the 25", not any(pid == "a26" for (bk, pid) in by if bk.startswith("each")))
    check("no backfill: a trade opened before the start is not copied", "old" not in held("each2_2L"))
    q2, q10 = by.get(("prime2L", "a19")), by.get(("prime10L", "a19"))
    check("Prime: Round Number Break 5m in both, in whole lots up to half (12 / 64 lots of a Rs 7,800 lot)",
          q2 is not None and q10 is not None and q2["qty"] == 100_000 // (120 * LOT) == 12
          and q10["qty"] == 500_000 // (120 * LOT) == 64, str(q2 and q2["qty"]))
    t2 = by.get(("prime2L", "t4"))
    check("...and TTM Squeeze Release 4h beside it in the second slot (25 lots of a Rs 3,900 lot)",
          t2 is not None and t2["qty"] == 100_000 // (60 * LOT) == 25 and ("prime10L", "t4") in by)
    check("...nothing else enters the Prime accounts", held("prime2L") == {"a19", "t4"} and held("prime10L") == {"a19", "t4"})

    accts = await t10.accounts("nifty-scalp", "top25-each")
    check("accounts('top25-each'): 25 summaries in Rank order", [a["book"] for a in accts] == EACH_KEYS
          and all(a["group"] == "top25-each" and a["picked"] for a in accts))
    a1 = accts[0]
    check("...each with its capital, one slot, its one strategy and its name",
          a1["desk_capital"] == 200_000 and a1["max_open_positions"] == 1 and a1["roster"] == ["ns_5m_23"]
          and a1["pick_names"] == ["Bollinger %B Extreme · 5 minutes"] and a1["open_positions"] == 1
          and a1["copying_since"] is not None)
    check("...#25 shows its closed trade", accts[24]["closed_positions"] == 1 and accts[24]["realized_pnl"] > 0)
    check("...an untouched account sits at Rs 2 lakh", accts[2]["equity"] == 200_000 and accts[2]["open_positions"] == 0)


def routes():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import top10_books as r
    app = FastAPI()
    app.include_router(r.router)
    c = TestClient(app)
    a = c.get("/api/top10-books/nifty-scalp/accounts", params={"group": "top25-each"})
    check("GET /accounts?group=top25-each answers 25", a.status_code == 200 and a.json()["total"] == 25
          and a.json()["groups"]["top25-each"] == EACH_KEYS, str(a.status_code))
    s = c.get("/api/top10-books/nifty-scalp/summary", params={"book": "each25_2L"}).json()
    check("summary of an account answers for THAT book", s["book"] == "each25_2L"
          and s["label"] == "#25 Keltner Breakout 10m · ₹2 lakh")
    p = c.get("/api/top10-books/nifty-scalp/positions", params={"book": "each1_2L", "status": "OPEN"})
    check("its open positions answer", p.status_code == 200)
    s = c.get("/api/top10-books/nifty-scalp/summary", params={"book": "prime10L"}).json()
    check("summary of prime10L answers for itself, two strategies, two slots", s["book"] == "prime10L"
          and s["label"] == "Prime Premium Strategies · ₹10 lakh" and s["strategies"] == 2 and s["max_open_positions"] == 2
          and s["pick_names"] == ["Round Number Break · 5 minutes", "TTM Squeeze Release · 4 hours"] and s["picked"])


async def main():
    definitions()
    await trading()
    routes()
    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
