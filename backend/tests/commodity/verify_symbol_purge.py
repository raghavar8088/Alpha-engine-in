"""Check backend/scripts/purge_commodity_symbols.py end to end, on in-memory Mongo (never the real cluster).

Run from the repo root (needs mongomock-motor; pip --target is fine):
    python backend/tests/commodity/verify_symbol_purge.py

Real: the script (plan, backup, delete, rebuild, restore), commodity_engine.rescore_all, top10_books and
rank_band_books' capitals. Stubbed: app.core.db (in-memory), the box-local AI database (a second one).
"""
import asyncio
import importlib.util
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200")
ROOT = Path(__file__).resolve().parents[3]
for p in ("backend", "shared", "broker-clients", "strategy-service", "risk-service", "backtesting-service",
          "options-service", "ai-service", "research-service", "vector-service"):
    sys.path.insert(0, str(ROOT / p))
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

DB = AsyncMongoMockClient()["main"]
FDB = AsyncMongoMockClient()["box_local"]


class _DbModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return DB[name.removesuffix("_collection")]


dbmod = _DbModule("app.core.db")
dbmod.db = DB
sys.modules["app.core.db"] = dbmod

spec = importlib.util.spec_from_file_location("purge", ROOT / "backend/scripts/purge_commodity_symbols.py")
purge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(purge)
from app.services.commodity_patterns import COMMODITY_CATALOG  # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


KEEP = {"NATGASMINI", "CRUDEOILM", "NATURALGAS", "CRUDEOIL"}     # natural gas + crude oil, both sizes
KNOWN = {"GOLD", "GOLDM", "SILVER", "SILVERM", "CRUDEOIL", "NATURALGAS", "COPPER", "ZINC", "CRUDEOILM", "NATGASMINI"}
T0 = datetime(2026, 11, 10, 4, 0, tzinfo=timezone.utc)
S1, S2 = COMMODITY_CATALOG[0].strategy_id, COMMODITY_CATALOG[1].strategy_id


def pos(pid, sym, sid, mins, pnl, *, closed_mins=None, status="CLOSED", deployed=10000.0):
    d = {"position_id": pid, "symbol": sym, "strategy_id": sid, "status": status, "honest": True,
         "opened_at": T0 + timedelta(minutes=mins), "capital_deployed": deployed,
         "realized_pnl": pnl if status != "OPEN" else None, "record_pnl": pnl if status != "OPEN" else None,
         "costs": 50.0, "unrealized_pnl": 0.0 if status != "OPEN" else 120.0}
    if status != "OPEN":
        d["closed_at"] = T0 + timedelta(minutes=closed_mins if closed_mins is not None else mins + 30)
    return d


async def seed():
    P = DB["commodity_positions"]
    await P.insert_many([
        pos("n1", "NATGASMINI", S1, 0, 1000.0), pos("c1", "CRUDEOILM", S2, 10, -400.0),
        pos("g1", "GOLD", S1, 20, 5000.0), pos("g2", "GOLDM", S2, 30, -2000.0),
        pos("z1", "ZINC", S1, 40, 700.0), pos("ng", "NATURALGAS", S1, 50, -300.0),   # full-size: KEPT
        pos("co", "CRUDEOIL", S2, 60, 900.0),                                          # full-size: KEPT
        pos("o_n", "NATGASMINI", S2, 70, 0, status="OPEN"), pos("o_g", "SILVER", S1, 80, 0, status="OPEN"),
        {"position_id": "nul", "symbol": None, "strategy_id": S1, "status": "CLOSED", "realized_pnl": 1.0,
         "opened_at": T0, "closed_at": T0 + timedelta(minutes=5)},
        {"position_id": "unk", "symbol": "LEAD", "strategy_id": S1, "status": "CLOSED", "realized_pnl": 2.0,
         "opened_at": T0, "closed_at": T0 + timedelta(minutes=5)},
    ])
    await DB["commodity_trades"].insert_many([{"trade_id": "t1", "symbol": "NATGASMINI"}, {"trade_id": "t2", "symbol": "GOLD"},
                                              {"trade_id": "t3", "symbol": "COPPER"}])
    await DB["commodity_scores"].insert_one({"strategy_id": S1, "trades": 99, "net_pnl": 123456.0})
    await DB["commodity_equity"].insert_many([{"ts": T0 + timedelta(minutes=m), "equity": 1.0, "realized": 1.0,
                                               "unrealized": 1.0, "deployed": 1.0, "open_positions": 9}
                                              for m in (25, 45, 75, 200)])
    await DB["top10_book_positions"].insert_many([
        {"desk": "commodity", "book": "top2L", "symbol": "CRUDEOILM", "status": "CLOSED", "realized_pnl": 50.0,
         "opened_at": T0, "closed_at": T0 + timedelta(minutes=40), "capital_deployed": 5000.0},
        {"desk": "commodity", "book": "top2L", "symbol": "GOLD", "status": "CLOSED", "realized_pnl": 900.0,
         "opened_at": T0, "closed_at": T0 + timedelta(minutes=40), "capital_deployed": 5000.0},
        {"desk": "zero-hero", "book": "top2L", "symbol": "GOLD", "status": "CLOSED"},          # another desk: untouched
    ])
    await DB["top10_book_scores"].insert_many([{"desk": "commodity", "book": "top2L", "key": S1, "skipped": {"full": 7}},
                                               {"desk": "nifty-scalp", "book": "top2L", "key": "x", "skipped": {"full": 3}}])
    await DB["top10_book_equity"].insert_one({"desk": "commodity", "book": "top2L", "ts": T0 + timedelta(minutes=60), "equity": 0})
    await DB["rank_band_positions"].insert_many([
        {"book": "top5", "symbol": "SILVERM", "status": "CLOSED", "realized_pnl": 10.0, "opened_at": T0, "closed_at": T0},
        {"book": "top5", "symbol": "NATGASMINI", "status": "OPEN", "opened_at": T0, "capital_deployed": 1.0}])
    await FDB["ai_positions"].insert_many([
        {"module": "commodity", "symbol": "NATGASMINI26NOVFUT"},         # a contract name: still the mini, kept
        {"module": "commodity", "symbol": "GOLD26DECFUT"},                # deleted
        {"module": "intraday", "symbol": "GOLD"}])                        # another module: untouched
    await FDB["ai_gate_decisions"].insert_many([{"module": "commodity", "symbol": "ZINC"},
                                                {"module": "commodity", "symbol": "CRUDEOILM"}])


async def main():
    # ── pure parts ────────────────────────────────────────────────────────────────────────
    u = purge.underlying
    check("underlying: contract names, minis and blanks",
          u("NATGASMINI26NOVFUT") == "NATGASMINI" and u("CRUDEOILM") == "CRUDEOILM" and u("CRUDEOIL26NOVFUT") == "CRUDEOIL"
          and u("GOLDM") == "GOLDM" and u(None) is None and u("") is None)
    pts = purge.replay_curve([T0 + timedelta(minutes=m) for m in (5, 35, 100)],
                             [pos("a", "X", S1, 0, 100.0, closed_mins=30), pos("b", "X", S1, 20, 0, status="OPEN", deployed=7.0)],
                             1000.0)
    check("replay_curve: realised by time, open count and margin",
          [(p["equity"], p["open_positions"], p["deployed"]) for p in pts] == [(1000.0, 1, 10000.0), (1100.0, 1, 7.0), (1100.0, 1, 7.0)],
          str([(p["equity"], p["open_positions"], p["deployed"]) for p in pts]))

    await seed()
    before = {n: await DB[n].count_documents({}) for n in ("commodity_positions", "commodity_trades", "top10_book_positions",
                                                          "rank_band_positions", "commodity_equity", "commodity_scores")}
    # ── dry run ───────────────────────────────────────────────────────────────────────────
    plan = await purge.plan_purge(DB, FDB, KEEP, KNOWN)
    s = plan["stores"]
    check("dry run: the six (gold, silver, copper, zinc), never natural gas or crude oil",
          s["commodity_positions"]["delete"] == 4
          and s["commodity_positions"]["by_symbol"] == {"GOLD": 1, "GOLDM": 1, "ZINC": 1, "SILVER": 1},
          str(s["commodity_positions"]["by_symbol"]))
    check("...the full-size natural gas and crude oil are KEPT beside the minis",
          s["commodity_positions"]["kept"] == {"NATGASMINI": 2, "CRUDEOILM": 1, "NATURALGAS": 1, "CRUDEOIL": 1},
          str(s["commodity_positions"]["kept"]))
    check("...a row with no symbol or an unknown one is kept and reported, never deleted",
          s["commodity_positions"]["kept_unknown"] == {"None": 1, "LEAD": 1})
    check("...a contract-named mini is kept; another module's rows are not even looked at",
          s["ai_positions"]["delete"] == 1 and s["ai_positions"]["kept"] == {"NATGASMINI": 1}
          and s["top10_book_positions"]["delete"] == 1)
    check("...nothing written by a dry run", await DB["commodity_positions"].count_documents({}) == before["commodity_positions"])
    phrase = purge.confirm_phrase(plan)
    check("the confirmation carries the exact count", phrase == f"DELETE {plan['total']} ROWS" and plan["total"] == 10, phrase)

    with tempfile.TemporaryDirectory() as tmp:
        try:
            await purge.apply_purge(DB, FDB, KEEP, KNOWN, confirm="DELETE 1 ROWS", backup_dir=Path(tmp), force_hours=True)
            refused = False
        except SystemExit:
            refused = True
        check("a wrong confirmation is refused, and nothing is written",
              refused and await DB["commodity_positions"].count_documents({}) == before["commodity_positions"])

        out = await purge.apply_purge(DB, FDB, KEEP, KNOWN, confirm=phrase, backup_dir=Path(tmp), force_hours=True)
        bk = Path(out["backup"])
        check("apply: a verified backup file first", bk.exists() and bk.stat().st_size > 0)
        syms = sorted([d.get("symbol") async for d in DB["commodity_positions"].find({})], key=str)
        check("only natural gas and crude oil (and the unrecognised rows) remain on the desk",
              syms == sorted(["NATGASMINI", "NATGASMINI", "CRUDEOILM", "NATURALGAS", "CRUDEOIL", None, "LEAD"], key=str), str(syms))
        check("trades, paper-book copies and AI rows of the six are gone; others untouched",
              [d["symbol"] async for d in DB["commodity_trades"].find({})] == ["NATGASMINI"]
              and await DB["top10_book_positions"].count_documents({"desk": "zero-hero"}) == 1
              and await DB["top10_book_positions"].count_documents({"desk": "commodity"}) == 1
              and await DB["rank_band_positions"].count_documents({}) == 1
              and await FDB["ai_positions"].count_documents({}) == 2
              and await FDB["ai_gate_decisions"].count_documents({}) == 1)
        check("nothing of the six is left anywhere", out["left_to_delete"] == 0)
        sc = {d["strategy_id"]: d async for d in DB["commodity_scores"].find({})}
        check("scores recomputed from what remains (S1: NATGASMINI +1,000 and NATURALGAS -300)",
              sc[S1]["trades"] == 2 and abs(sc[S1]["net_pnl"] - 700.0) < 0.01, str({k: sc[S1].get(k) for k in ("trades", "net_pnl")}))
        from app.services import commodity_engine as ce
        eq = [d async for d in DB["commodity_equity"].find({}).sort("ts", 1)]
        # Remaining closes: the two kept unrecognised rows (+1, +2) at 0:05, NATGASMINI +1,000 at 0:30, CRUDEOILM -400
        # at 0:40, NATURALGAS -300 at 1:20, CRUDEOIL +900 at 1:30.
        check("desk equity replayed at the same times: capital + remaining realised (+3, +603, +603, +1,203)",
              [round(d["equity"] - ce.INITIAL_CAPITAL, 2) for d in eq] == [3.0, 603.0, 603.0, 1203.0]
              and all("rebuilt" in d for d in eq), str([round(d["equity"] - ce.INITIAL_CAPITAL, 2) for d in eq]))
        from app.services import top10_books as t10
        teq = await DB["top10_book_equity"].find_one({"desk": "commodity"})
        check("Top 10 book equity replayed from its remaining copy", teq["equity"] == t10.book_capital("commodity", "top2L") + 50.0)
        check("skip counters of the commodity books restart; other desks' untouched",
              (await DB["top10_book_scores"].find_one({"desk": "commodity"}))["skipped"] == {}
              and (await DB["top10_book_scores"].find_one({"desk": "nifty-scalp"}))["skipped"] == {"full": 3})

        # ── restore ───────────────────────────────────────────────────────────────────────
        r = await purge.restore(bk, DB, FDB)
        after = {n: await DB[n].count_documents({}) for n in before}
        check("restore: every deleted row is back", after == before, f"{after} vs {before}")
        check("...the rebuilt scopes are back exactly",
              (await DB["commodity_scores"].find_one({"strategy_id": S1}))["trades"] == 99
              and [d["equity"] async for d in DB["commodity_equity"].find({})] == [1.0, 1.0, 1.0, 1.0]
              and (await DB["top10_book_scores"].find_one({"desk": "commodity"}))["skipped"] == {"full": 7})
        check("...including the box-local AI rows", await FDB["ai_positions"].count_documents({}) == 3
              and await FDB["ai_gate_decisions"].count_documents({}) == 2, str(r))

    # ── the desk trades natural gas and crude oil only, both sizes ────────────────────────────
    from app.services import commodity_engine as ce
    check("the desk's contracts: natural gas and crude oil, both sizes",
          ce.DESK_UNDERLYINGS == ("NATGASMINI", "CRUDEOILM", "NATURALGAS", "CRUDEOIL"))
    check("the script keeps exactly what the desk trades, by default", set(purge.KEEP_DEFAULT) == set(ce.DESK_UNDERLYINGS))
    asked: list = []

    async def fake_universe():
        return {u: {"symbol": f"{u}26NOVFUT", "angel_token": u} for u in sorted(KNOWN)}

    async def fake_quotes(contracts):
        asked.extend(c["symbol"] for c in contracts)
        return {}
    ce.front_month_universe, ce.mcx_market.quotes = fake_universe, fake_quotes
    await ce.scan_cycle()
    check("a scan quotes only the four natural gas and crude oil contracts out of all ten",
          sorted(asked) == ["CRUDEOIL26NOVFUT", "CRUDEOILM26NOVFUT", "NATGASMINI26NOVFUT", "NATURALGAS26NOVFUT"], str(asked))

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
