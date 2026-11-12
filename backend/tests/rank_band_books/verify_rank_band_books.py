"""End-to-end check of app.services.rank_band_books (the Commodity Trading rank-band paper accounts) with an in-memory
Mongo. Needs `pip install mongomock-motor motor fastapi httpx`; run: python backend/tests/rank_band_books/verify_rank_band_books.py. Real: rank_band_books, top10_books (its commodity adapter, _row, _close_fields), plan_book.
Stubbed (heavy imports with broker clients): margin specs, MCX trade pricing, fee schedules, intraday strategies."""
import asyncio, sys, types
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mongomock_motor import AsyncMongoMockClient

DB = AsyncMongoMockClient()["test"]


class _DbModule(types.ModuleType):
    def __getattr__(self, name):          # any `*_collection` the imported modules ask for
        if name.startswith("__"):
            raise AttributeError(name)
        return DB[name]


dbmod = _DbModule("app.core.db"); dbmod.db = DB
sys.modules["app.core.db"] = dbmod
v2 = types.ModuleType("app.services.intraday_v2_strategies"); sys.modules[v2.__name__] = v2
af = types.ModuleType("app.services.angel_fees"); af.round_trip = lambda *a, **k: None; sys.modules[af.__name__] = af
SPECS = {"CRUDEOIL": (100, 0.10), "NATURALGAS": (1250, 0.15), "GOLD": (100, 0.10), "GOLDM": (10, 0.10)}
cp = types.ModuleType("app.services.commodity_positions")
cp.multiplier = lambda s: SPECS[s][0]
cp.margin_pct_for = lambda s: SPECS[s][1]
sys.modules[cp.__name__] = cp
mr = types.ModuleType("app.services.mcx_risk")
FEE_PER_LOT = 60.0


def real_trade(sym, side, entry, exit_, on=None, lots=1):
    sign = 1 if side == "BUY" else -1
    return {"gross": round(sign * (exit_ - entry) * SPECS[sym][0] * lots, 2), "fees": FEE_PER_LOT * lots}


mr.real_trade = real_trade
sys.modules[mr.__name__] = mr
deps = types.ModuleType("app.api.deps")
async def get_current_user():
    return {}
deps.get_current_user = get_current_user
sys.modules[deps.__name__] = deps

from app.services import rank_band_books as rb     # noqa: E402
from app.services import top10_books as t10        # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def utc_naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


NOW = utc_naive(datetime.now(timezone.utc))
START = NOW - timedelta(hours=3)
IST = timezone(timedelta(hours=5, minutes=30))


def day(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone(IST).date().isoformat()


def parent(pid, sid, sym, side, entry, t_open, status="OPEN", exit_=None, t_close=None, ltp=None):
    d = {"position_id": pid, "strategy_id": sid, "strategy_name": sid, "symbol": sym, "side": side,
         "entry_touch": entry, "entry_price": entry, "status": status, "opened_at": t_open, "opened_on": day(t_open),
         "instrument": {"symbol": f"{sym}25DECFUT", "expiry": "2026-12-19"}, "ltp": ltp, "honest": True}
    if status == "CLOSED":
        d.update({"exit_price": exit_, "real": {"exit": exit_}, "closed_at": t_close, "closed_on": day(t_close),
                  "exit_reason": "target"})
    return d


async def main():
    P = DB["commodity_positions"]
    # The book started 3 h ago: anything the desk opened before that is never copied.
    for b in rb.BOOKS:
        await rb.STATE.insert_one({"_id": f"start:{b}", "started_at": START, "book": b})
    await P.insert_one(parent("old1", "cmd_0246", "CRUDEOIL", "BUY", 5800.0, START - timedelta(hours=5)))
    # cmd_0246 (Top 5 #1): CRUDEOIL long opened 2 h ago, still open; then a NATURALGAS signal while it is held.
    await P.insert_one(parent("a1", "cmd_0246", "CRUDEOIL", "BUY", 5800.0, NOW - timedelta(hours=2), ltp=5850.0))
    await P.insert_one(parent("a2", "cmd_0246", "NATURALGAS", "SELL", 300.0, NOW - timedelta(hours=1, minutes=30)))
    # cmd_0238 (Top 5 #2): a GOLD lot needs Rs 13 lakh of margin - more than its Rs 10 lakh.
    await P.insert_one(parent("b1", "cmd_0238", "GOLD", "BUY", 130000.0, NOW - timedelta(hours=1)))
    # cmd_0201 (Top 5 #3): opened AND closed between two looks - a short that made money.
    await P.insert_one(parent("c1", "cmd_0201", "CRUDEOIL", "SELL", 5900.0, NOW - timedelta(minutes=50),
                              status="CLOSED", exit_=5880.0, t_close=NOW - timedelta(minutes=20)))
    # A strategy of another band (Top 5-10 #6) - must land only in that band.
    await P.insert_one(parent("d1", "cmd_0226", "GOLDM", "BUY", 13000.0, NOW - timedelta(minutes=40), ltp=13010.0))
    # A strategy in no band at all - never copied.
    await P.insert_one(parent("z1", "cmd_9999", "CRUDEOIL", "BUY", 5800.0, NOW - timedelta(minutes=30)))

    out = await rb.sync(entries=True)
    check("sync ran for all 20 strategy accounts without an error", len(out) == 20 and not [k for k, v in out.items() if "error" in v],
          str({k: v for k, v in out.items() if "error" in v}))

    # As in top10_books, a copy opened during a pass is marked on the NEXT pass (the live loop runs every minute).
    out_b = await rb.sync(entries=True)
    check("a second pass is clean", not [k for k, v in out_b.items() if "error" in v])
    rows = [r async for r in rb.POSITIONS.find({})]
    by = {r["parent_position_id"]: r for r in rows}
    check("nothing from before the book's start is copied", "old1" not in by)
    check("a strategy outside every band is never copied", "z1" not in by)
    a1 = by.get("a1")
    lots_a1 = int(1_000_000 // (0.10 * 5800.0 * 100))
    check("open copy: whole lots on margin within its Rs 10 lakh", a1 is not None and a1["qty"] == lots_a1 and a1["status"] == "OPEN",
          f"{a1 and a1.get('qty')} vs {lots_a1}")
    check("open copy is marked to the desk's last price", a1 is not None and abs(a1["unrealized_pnl"] - (5850 - 5800) * 100 * lots_a1) < 1e-6,
          str(a1 and a1.get("unrealized_pnl")))
    check("open copy carries its band, source and allocation", a1 is not None and a1["book"] == "top5" and a1["source"] == "rank_band"
          and a1["allocation"] == 1_000_000 and a1["strategy_name"] == "Heikin Ashi Flip · 1h")
    check("second signal while the strategy holds a position: skipped (one at a time)", "a2" not in by)
    check("GOLD lot above the strategy's Rs 10 lakh: skipped", "b1" not in by)
    c1 = by.get("c1")
    lots_c1 = int(1_000_000 // (0.10 * 5900.0 * 100))
    exp_c1 = round((5900 - 5880) * 100 * lots_c1 - FEE_PER_LOT * lots_c1, 2)
    check("opened and closed between looks: copied closed, net of MCX charges", c1 is not None and c1["status"] == "CLOSED"
          and abs(c1["realized_pnl"] - exp_c1) < 1e-6, f"{c1 and c1.get('realized_pnl')} vs {exp_c1}")
    d1 = by.get("d1")
    check("another band's strategy goes only to its own band", d1 is not None and d1["book"] == "top5_10"
          and not [r for r in rows if r["parent_position_id"] == "d1" and r["book"] != "top5_10"])

    s = await rb.summary("top5")
    check("Top 5: Rs 50 lakh = five strategies x Rs 10 lakh", s["desk_capital"] == 5_000_000 and s["per_strategy_capital"] == 1_000_000)
    check("Top 5: counts and skips", s["open_positions"] == 1 and s["closed_positions"] == 1
          and s["skipped"]["full"] == 1 and s["skipped"]["price_above_cap"] == 1, str({k: s[k] for k in ("open_positions", "closed_positions", "skipped")}))
    check("Top 5: equity = capital + realised + unrealised",
          abs(s["equity"] - (5_000_000 + exp_c1 + (5850 - 5800) * 100 * lots_a1)) < 1e-6, str(s["equity"]))
    lb = {r["key"]: r for r in await rb.leaderboard("top5")}
    check("leaderboard: the five in pick order with their board ranks",
          [r["picked_rank"] for r in await rb.leaderboard("top5")] == [1, 2, 3, 4, 5])
    check("ring-fenced: cmd_0201's profit is its own account's", abs(lb["cmd_0201"]["equity"] - (1_000_000 + exp_c1)) < 1e-6
          and lb["cmd_0149"]["equity"] == 1_000_000 and lb["cmd_0238"]["skipped_total"] == 1)
    check("other bands untouched but for their own strategy", (await rb.summary("top10_15"))["open_positions"] == 0
          and (await rb.summary("top5_10"))["open_positions"] == 1)

    # The desk closes a1; the NATURALGAS signal stays skipped (decided), and a re-run adds nothing twice.
    await P.update_one({"position_id": "a1"}, {"$set": {"status": "CLOSED", "exit_price": 5830.0, "real": {"exit": 5830.0},
                                                     "closed_at": NOW - timedelta(minutes=5), "closed_on": day(NOW), "exit_reason": "stop"}})
    await rb.sync(entries=False)            # the manage pass writes the close
    out2 = await rb.sync(entries=True)
    rows2 = [r async for r in rb.POSITIONS.find({})]
    a1b = next(r for r in rows2 if r["parent_position_id"] == "a1")
    exp_a1 = round((5830 - 5800) * 100 * lots_a1 - FEE_PER_LOT * lots_a1, 2)
    check("the desk's close is copied at its exit, net of charges", a1b["status"] == "CLOSED" and abs(a1b["realized_pnl"] - exp_a1) < 1e-6,
          str(a1b.get("realized_pnl")))
    check("re-running adds no duplicate and re-skips nothing", len(rows2) == len(rows) and
          (await rb.summary("top5"))["skipped"]["full"] == 1, f"{len(rows2)} vs {len(rows)}")
    check("second pass clean", not [k for k, v in out2.items() if "error" in v])

    # The API, through FastAPI.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import rank_band_books as routes
    app = FastAPI(); app.include_router(routes.router)
    c = TestClient(app)
    r = c.get("/api/rank-band-books/books").json()
    check("GET /books: four books, five picks each, Rs 50 lakh", [b["book"] for b in r["books"]] == ["top5", "top5_10", "top10_15", "top15_20"]
          and all(len(b["picks"]) == 5 and b["capital"] == 5_000_000 for b in r["books"]))
    r = c.get("/api/rank-band-books/summary?book=top5").json()
    check("GET /summary", r["label"] == "Top 5 Paper Trading" and r["closed_positions"] == 2)
    r = c.get("/api/rank-band-books/leaderboard?book=top15_20").json()
    check("GET /leaderboard", r["book"] == "top15_20" and [x["picked_rank"] for x in r["rows"]] == [18, 19, 20, 21, 22])
    r = c.get("/api/rank-band-books/positions?book=top5&status=CLOSED").json()
    check("GET /positions serialises dates", len(r["positions"]) == 2 and isinstance(r["positions"][0]["opened_at"], str))
    r = c.get("/api/rank-band-books/summary?book=nonsense").json()
    check("an unknown book falls back to Top 5", r["book"] == "top5")
    print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}")


asyncio.run(main())
