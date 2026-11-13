"""End-to-end check of app.services.prelive_pick_books (Index Option Buying's three picked-strategy paper accounts)
with an in-memory Mongo. Needs `pip install mongomock-motor motor fastapi httpx`; run from the repo root:
    python backend/tests/prelive_pick_books/verify_prelive_pick_books.py
Real: prelive_pick_books, top10_books (its prelive loader, _option_parent, _row, _close_fields), plan_book,
angel_fees.option_round_trip (Angel's option card from the repo's shared/), the routes module.
Stubbed: app.core.db (in-memory), factory_desks (only its POSITIONS collection), intraday_v2_strategies, deps."""
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


def day(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone(IST).date().isoformat()


def fpos(pid, sid, entry, t_open, *, token="45396", status="OPEN", exit_=None, t_close=None, mark=None,
         desk="index-buying", kind="option_buy"):
    """A Strategy Factory tab position, as factory_desks writes it."""
    d = {"position_id": pid, "desk": desk, "strategy_id": sid, "strategy_name": sid, "kind": kind,
         "timeframe": "15m", "symbol": "NIFTY", "signal_side": "BUY", "side": "BUY",
         "legs": [{"token": token, "tradingsymbol": f"NIFTY17NOV26{token}CE", "strike": 25250.0, "option_type": "CE",
                   "expiry": "2026-11-17", "side": "BUY", "entry": entry}],
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
    return round(gross, 2), round(gross - fb.total, 2), fb.total


async def factory_books():
    F = DB["factory_desk_positions"]
    for b in pb.BOOKS:
        await pb.STATE.insert_one({"_id": f"start:{b}", "started_at": START, "book": b})
    await F.insert_one(fpos("old", "SF0400", 150.0, START - timedelta(hours=2)))            # before the start
    await F.insert_one(fpos("f1", "SF0400", 150.0, NOW - timedelta(hours=2), mark=160.0))   # Top 10 #1, open
    await F.insert_one(fpos("f2", "SF0400", 120.0, NOW - timedelta(hours=1, minutes=30), token="45400"))  # while held
    await F.insert_one(fpos("f3", "SF0107", 100.0, NOW - timedelta(minutes=80), token="45401", status="CLOSED",
                            exit_=130.0, t_close=NOW - timedelta(minutes=20)))              # opened + closed between looks
    await F.insert_one(fpos("f4", "SF0116", 90.0, NOW - timedelta(minutes=70), token="45402", mark=95.0))  # #11
    await F.insert_one(fpos("f5", "SF9999", 90.0, NOW - timedelta(minutes=60), token="45403"))  # in no book
    await F.insert_one(fpos("f6a", "SF0474", 110.0, NOW - timedelta(minutes=50), token="45404", mark=111.0))
    await F.insert_one(fpos("f6b", "SF0330", 110.0, NOW - timedelta(minutes=50), token="45404", mark=111.0))
    await F.insert_one(fpos("f7", "SF0400", 80.0, NOW - timedelta(minutes=45), token="45405",
                            desk="index-selling", kind="credit_spread"))                     # another tab
    # SF0401 (#6) loses nearly all of its Rs 10 lakh, then signals again: no cash. Its neighbours are untouched.
    await F.insert_one(fpos("g1", "SF0401", 100.0, NOW - timedelta(minutes=40), token="45406", status="CLOSED",
                            exit_=2.0, t_close=NOW - timedelta(minutes=35)))
    # About Rs 25,000 is left; one lot at 500 costs Rs 32,500.
    await F.insert_one(fpos("g2", "SF0401", 500.0, NOW - timedelta(minutes=30), token="45407"))

    out = await pb.sync(entries=True)
    errs = {k: v for k, v in out.items() if "error" in v}
    check("first pass: every account of the three books ran without an error",
          len(out) == 1 + 10 + 10 and not errs, str(errs or len(out)))
    out2 = await pb.sync(entries=True)                     # a copy opened in a pass is marked on the next
    check("second pass is clean", not [k for k, v in out2.items() if "error" in v])
    rows = [r async for r in pb.POSITIONS.find({})]
    by = {r["parent_position_id"]: r for r in rows}

    check("nothing opened before the book's start is copied", "old" not in by)
    check("a strategy in no book is never copied", "f5" not in by)
    check("another Strategy Factory tab's trade is never copied", "f7" not in by)
    f1 = by.get("f1")
    lots = int(1_000_000 // (150.0 * LOT))
    check("open copy: whole lots up to the strategy's own Rs 10 lakh", f1 is not None and f1["qty"] == lots
          and f1["status"] == "OPEN" and abs(f1["capital_deployed"] - lots * 150.0 * LOT) < 0.01,
          f"{f1 and f1.get('qty')} vs {lots}")
    check("open copy is marked at the tab's own mark (its bid)", f1 is not None
          and abs(f1["unrealized_pnl"] - (160.0 - 150.0) * LOT * lots) < 0.01, str(f1 and f1.get("unrealized_pnl")))
    check("open copy carries book, account, source, allocation, name and contract", f1 is not None
          and f1["book"] == "sf_top10" and f1["account"] == "SF0400" and f1["source"] == "pick"
          and f1["allocation"] == 1_000_000 and f1["strategy_name"] == "MACD Histogram Turn · 5m"
          and f1["label"] == "NIFTY 25250 CE 2026-11-17" and f1["expiry"] == "2026-11-17")
    check("a second signal while the strategy holds a position is skipped (one at a time)", "f2" not in by)
    f3 = by.get("f3")
    l3 = int(1_000_000 // (100.0 * LOT))
    g3, n3, fee3 = option_net(100.0, 130.0, l3, day(NOW - timedelta(minutes=20)))
    check("opened-and-closed copy: booked closed at the tab's exit, Angel's option card on its own lots",
          f3 is not None and f3["status"] == "CLOSED" and f3["qty"] == l3 and abs(f3["gross_pnl"] - g3) < 0.01
          and abs(f3["realized_pnl"] - n3) < 0.01 and abs(f3["fees"] - round(fee3, 2)) < 0.01,
          f"{f3 and (f3.get('qty'), f3.get('gross_pnl'), f3.get('realized_pnl'))} vs {(l3, g3, n3)}")
    f4 = by.get("f4")
    check("a Rank 11-20 strategy lands only in Top 10-20", f4 is not None and f4["book"] == "sf_top10_20"
          and f4["account"] == "SF0116" and len([r for r in rows if r["parent_position_id"] == "f4"]) == 1)
    check("two strategies on the same contract at once: each copied into its own account",
          "f6a" in by and "f6b" in by and by["f6a"]["account"] == "SF0474" and by["f6b"]["account"] == "SF0330")
    check("a strategy that lost its money cannot take the next trade (no cash)", "g1" in by and "g2" not in by)
    sc = await pb.SCORES.find_one({"book": "sf_top10", "key": "SF0401"})
    check("that skip is counted as no_cash", sc is not None and sc["skipped"].get("no_cash") == 1, str(sc))
    sc0 = await pb.SCORES.find_one({"book": "sf_top10", "key": "SF0400"})
    check("the held-position skip is counted as full", sc0 is not None and sc0["skipped"].get("full") == 1, str(sc0))

    # The tab closes f1 at 170: the copy closes at the same price.
    await F.update_one({"position_id": "f1"}, {"$set": {"status": "CLOSED", "exit_legs": [170.0],
                                                        "closed_at": NOW - timedelta(minutes=5),
                                                        "closed_on": day(NOW - timedelta(minutes=5)),
                                                        "exit_reason": "eod"}})
    await pb.sync(entries=True)
    f1b = await pb.POSITIONS.find_one({"parent_position_id": "f1"})
    g1_, n1_, _ = option_net(150.0, 170.0, lots, day(NOW - timedelta(minutes=5)))
    check("when the tab closes, the copy closes at the tab's exit", f1b["status"] == "CLOSED"
          and abs(f1b["realized_pnl"] - n1_) < 0.01 and f1b["exit_reason"] == "eod", str(f1b.get("realized_pnl")))
    n_before = await pb.POSITIONS.count_documents({})
    await pb.sync(entries=True)
    check("passes are idempotent: no duplicate copies", await pb.POSITIONS.count_documents({}) == n_before)

    s = await pb.summary("sf_top10")
    realized = sum(r["realized_pnl"] for r in rows if r["book"] == "sf_top10" and r["status"] == "CLOSED"
                   and r["parent_position_id"] != "f1") + f1b["realized_pnl"]
    check("Top 10 summary: Rs 10 lakh a strategy, Rs 1 crore in all, one position each",
          s["desk_capital"] == 10_000_000 and s["per_strategy_capital"] == 1_000_000 and s["position_cap"] == 1_000_000
          and s["max_open_positions"] == 10 and s["strategies"] == 10 and s["board_ranks"] == list(range(1, 11)))
    check("Top 10 summary adds up its accounts", abs(s["realized_pnl"] - realized) < 0.05,
          f"{s['realized_pnl']} vs {realized}")
    lb = await pb.leaderboard("sf_top10")
    r401 = next(r for r in lb if r["key"] == "SF0401")
    check("leaderboard: ten rows in rank order, each on its own Rs 10 lakh", [r["picked_rank"] for r in lb] == list(range(1, 11))
          and all(r["allocation"] == 1_000_000 for r in lb))
    check("leaderboard: the losing strategy's equity is its own Rs 10 lakh less its loss",
          abs(r401["equity"] - (1_000_000 + r401["net_pnl"])) < 0.01 and r401["net_pnl"] < -900_000, str(r401["equity"]))
    s2 = await pb.summary("sf_top10_20")
    check("Top 10-20 summary: ranks 11-20", s2["board_ranks"] == list(range(11, 21)) and s2["open_positions"] == 1)


async def best_book():
    P, T = DB["prelive_positions"], DB["prelive_trades"]
    t_a = NOW - timedelta(minutes=100)
    iso = lambda t: t.replace(tzinfo=timezone.utc).isoformat()   # noqa: E731 - the daemon's open rows keep an ISO string
    # intra_ha_reversal: an open position (ask 151, mark 160).
    await P.insert_one({"key": "intra_ha_reversal@15m", "entry_ts": iso(t_a), "entry_premium": 150.0, "entry_ask": 151.0,
                        "mark": 160.0, "security_id": "50001", "strike": 25300, "option_type": "PE",
                        "expiry": "2026-11-17", "lot_size": LOT})
    # it_fake_breakout wants the SAME contract a minute later: one contract per account -> skipped.
    await P.insert_one({"key": "it_fake_breakout@15m", "entry_ts": iso(t_a + timedelta(minutes=1)), "entry_premium": 150.5,
                        "entry_ask": 151.5, "mark": 160.0, "security_id": "50001", "strike": 25300,
                        "option_type": "PE", "expiry": "2026-11-17", "lot_size": LOT})
    # it_fake_breakout, a different contract: takes the second slot.
    await P.insert_one({"key": "it_fake_breakout@15m", "entry_ts": iso(t_a + timedelta(minutes=5)), "entry_premium": 90.0,
                        "entry_ask": 90.5, "mark": 92.0, "security_id": "50002", "strike": 25400,
                        "option_type": "CE", "expiry": "2026-11-17", "lot_size": LOT})
    # intra_ha_reversal again while both slots are used -> full.
    await P.insert_one({"key": "intra_ha_reversal@15m", "entry_ts": iso(t_a + timedelta(minutes=10)), "entry_premium": 70.0,
                        "entry_ask": 70.4, "mark": 71.0, "security_id": "50003", "strike": 25500,
                        "option_type": "CE", "expiry": "2026-11-17", "lot_size": LOT})
    # A Top 10 strategy that is not one of the two: never copied.
    await P.insert_one({"key": "ema_200_trend@15m", "entry_ts": iso(t_a), "entry_premium": 80.0, "entry_ask": 80.4,
                        "mark": 81.0, "security_id": "50004", "strike": 25200, "option_type": "CE",
                        "expiry": "2026-11-17", "lot_size": LOT})
    await pb.sync(entries=True, only="best2L")
    await pb.sync(entries=True, only="best2L")
    rows = [r async for r in pb.POSITIONS.find({"book": "best2L"})]
    keys = sorted((r["key"], r["symbol"]) for r in rows)
    check("best2L: two positions, one per slot, the second contract taken and the shared one skipped",
          keys == [("intra_ha_reversal@15m", "50001"), ("it_fake_breakout@15m", "50002")], str(keys))
    a = next(r for r in rows if r["key"] == "intra_ha_reversal@15m")
    lots_a = int(100_000 // (151.0 * LOT))
    check("best2L: a position is up to Rs 1 lakh (Rs 2 lakh over two slots), bought at the ask",
          a["qty"] == lots_a and a["entry_px"] == 151.0 and a["account"] == "book" and a["allocation"] is None,
          f"{a['qty']} vs {lots_a}")
    check("best2L: marked at the tournament's mark", abs(a["unrealized_pnl"] - (160.0 - 151.0) * LOT * lots_a) < 0.01)
    sc = {s["key"]: s["skipped"] async for s in pb.SCORES.find({"book": "best2L"})}
    check("best2L: the shared contract counted as symbol_held, the third position as full",
          sc.get("it_fake_breakout@15m", {}).get("symbol_held") == 1 and sc.get("intra_ha_reversal@15m", {}).get("full") == 1,
          str(sc))
    # The daemon closes intra_ha_reversal's first trade: the open row leaves prelive_positions and a closed row lands
    # in prelive_trades with the same key and entry time (a Mongo date, milliseconds) and the bid it sold at.
    await P.delete_one({"key": "intra_ha_reversal@15m", "security_id": "50001"})
    t_x = NOW - timedelta(minutes=10)
    await T.insert_one({"key": "intra_ha_reversal@15m", "entry_ts": t_a, "entry_premium": 150.0, "entry_ask": 151.0,
                        "exit_premium": 171.0, "exit_bid": 170.5, "exit_ts": t_x, "security_id": "50001",
                        "strike": 25300, "option_type": "PE", "expiry": "2026-11-17", "lot_size": LOT,
                        "session": day(t_a), "exit_reason": "target"})
    await pb.sync(entries=True, only="best2L")
    a2 = await pb.POSITIONS.find_one({"book": "best2L", "key": "intra_ha_reversal@15m", "symbol": "50001"})
    g, n, _ = option_net(151.0, 170.5, lots_a, day(t_x))
    check("best2L: the copy closes at the tournament's exit bid", a2["status"] == "CLOSED"
          and abs(a2["realized_pnl"] - n) < 0.01, f"{a2.get('realized_pnl')} vs {n}")
    s = await pb.summary("best2L")
    check("best2L summary: Rs 2 lakh, two slots, cap Rs 1 lakh, one account",
          s["desk_capital"] == 200_000 and s["max_open_positions"] == 2 and s["position_cap"] == 100_000
          and s["per_strategy"] is False and s["per_strategy_capital"] is None and s["strategies"] == 2)
    lb = await pb.leaderboard("best2L")
    check("best2L leaderboard: the two, with their share of the book", [r["key"] for r in lb]
          == ["intra_ha_reversal@15m", "it_fake_breakout@15m"] and lb[0]["allocation"] is None
          and abs(lb[0]["roi_pct"] - (lb[0]["net_pnl"] + lb[0]["unrealized_pnl"]) / 200_000 * 100) < 1e-3)


def routes():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import prelive_pick_books as r
    app = FastAPI()
    app.include_router(r.router)
    check("the router hands its startup loop to the app", r._start_loop in app.router.on_startup)
    paths = {getattr(x, "path", "") for x in r.router.routes}
    check("four read-only routes, no write route", paths == {
        "/api/prelive-pick-books/books", "/api/prelive-pick-books/summary",
        "/api/prelive-pick-books/leaderboard", "/api/prelive-pick-books/positions"}
        and all(x.methods == {"GET"} for x in r.router.routes), str(paths))
    c = TestClient(app)                                    # no `with`: the startup loop is not started
    s = c.get("/api/prelive-pick-books/summary", params={"book": "sf_top10"})
    lb = c.get("/api/prelive-pick-books/leaderboard", params={"book": "sf_top10_20"})
    pos = c.get("/api/prelive-pick-books/positions", params={"book": "sf_top10", "status": "CLOSED"})
    check("GET summary / leaderboard / positions answer over HTTP", s.status_code == 200 and lb.status_code == 200
          and pos.status_code == 200 and s.json()["label"] == "Top 10 Performing Strategies · ₹10 lakh each"
          and lb.json()["total"] == 10 and len(pos.json()["positions"]) >= 2,
          f"{s.status_code} {lb.status_code} {pos.status_code}")
    books = pb.books()
    check("books(): three, with the owner's names", [b["label"] for b in books] == [
        "Best Strategies of Top 10 · ₹2 lakh", "Top 10 Performing Strategies · ₹10 lakh each",
        "Top 10-20 Performing Strategies · ₹10 lakh each"] and [b["capital"] for b in books] == [200_000, 10_000_000, 10_000_000])
    check("unknown book names fall back to the first", pb.normalize_book("nope") == "best2L")


async def main():
    await factory_books()
    await best_book()
    routes()
    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
