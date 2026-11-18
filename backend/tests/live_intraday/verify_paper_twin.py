"""End-to-end check of the Live Trading paper twin (book "ltpaper", 18 Nov 2026), with an in-memory Mongo.

Run from the repo root (needs mongomock-motor; pip --target is fine):
    python backend/tests/live_intraday/verify_paper_twin.py

Real: live_intraday_engine (the twin's book, roster, rules, summary), live_intraday_mirror (plan_book, the
twin's offer filter, fixed start), live_trading_twin (the side-by-side), angel_fees. Stubbed: app.core.db
(in-memory), the REAL-money desk (a stand-in with its constants and five strategies - this test must never
import the real engine), the broker route helper.
"""
import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "shared"))
for _pkg in ("broker-clients", "strategy-service", "risk-service", "backtesting-service", "options-service",
             "ai-service", "research-service", "vector-service"):
    sys.path.insert(0, str(ROOT / _pkg))          # the backend image installs these (requirements -e)
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

DB = AsyncMongoMockClient()["twin"]


class _DbModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return DB[name.removesuffix("_collection")] if name.endswith("_collection") else DB[name]


dbmod = _DbModule("app.core.db")
dbmod.db = DB
dbmod.client = None
sys.modules["app.core.db"] = dbmod


class CS:
    def __init__(self, sid, name, default_enabled=True):
        self.strategy_id, self.name, self.default_enabled = sid, name, default_enabled


lt = types.ModuleType("app.services.live_trading_engine")
lt.SELECTED = [CS("iv2_orb_sel15", "Selected ORB 15-min"), CS("iv2_gap_go", "Gap and Go", False),
               CS("iv2_rsi2_15m", "RSI(2) Extreme · 15 min", False), CS("iv2_supertrend_45m", "Supertrend 45m", False),
               CS("iv2_supertrend_1h", "Supertrend 1h", False)]
lt.COPY_SOURCES = tuple(s.strategy_id for s in lt.SELECTED)
lt.COPY_NOTIONAL, lt.MAX_OPEN_POSITIONS, lt.MIS_LEVERAGE, lt.DAILY_LOSS_BREAKER_PCT = 30000.0, 5, 5.0, 0.03
lt.ENTRY_CUTOFF_HHMM = "14:30"
sys.modules[lt.__name__] = lt

from app.services import live_intraday_engine as li  # noqa: E402
from app.services import live_intraday_mirror as mirror  # noqa: E402
from app.services import live_trading_twin as twin  # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
li.TWIN_START = NOW - timedelta(hours=6)          # the twin's first session, moved to "this morning" for the test
B = li.TWIN_BOOK
P = DB["intraday_lab_positions"]


def day(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone(IST).date().isoformat()


def par(pid, sid, sym, entry, mins_ago, *, side="BUY", stop=None, exit_=None, close_mins_ago=None, ltp=None):
    t = NOW - timedelta(minutes=mins_ago)
    d = {"position_id": pid, "engine": "v2", "strategy_id": sid, "strategy_name": sid, "symbol": sym,
         "instrument": {"exchange_segment": "NSE_EQ", "security_id": sym}, "side": side, "entry_price": entry,
         "signal_price": entry, "stoploss": stop or round(entry * 0.97, 2), "target": None, "ltp": ltp or entry,
         "status": "OPEN", "exit_price": None, "exit_reason": None, "opened_at": t, "opened_on": day(t),
         "closed_at": None, "closed_on": None}
    if exit_ is not None:
        tc = NOW - timedelta(minutes=close_mins_ago)
        d.update({"status": "CLOSED", "exit_price": exit_, "exit_reason": "target", "closed_at": tc, "closed_on": day(tc)})
    return d


async def main():
    # ── the book itself ──────────────────────────────────────────────────────────────────────
    check("the twin is a Live Intraday book with the real Angel balance as its money",
          B in li.BOOKS and li.book_capital(B) == 33882.16)
    check("its roster is the real desk's five strategies", li.book_roster(B) == lt.COPY_SOURCES)
    rules = mirror.book_rules(B)
    check("its rules are the real desk's: 5 slots, Rs 30,000 a position, 3% breaker, 5x",
          rules.get("max_open") == 5 and rules.get("position_value_cap") == 30000.0
          and abs(rules["loss_limit"] - 0.03 * 33882.16) < 1e-6 and rules["leverage_fn"]({"instrument": {"exchange_segment": "NSE_EQ"}}) == 5.0)
    check("no other book gains a rule", all(li.book_extra_rules(b) == {} for b in li.BOOKS if b != B)
          and "position_value_cap" not in mirror.book_rules("2L") and li.book_roster("top2L") == li.TOP10_ROSTER)
    check("...and only the twin has a fixed start", li.book_fixed_start(B) == li.TWIN_START
          and all(li.book_fixed_start(b) is None for b in li.BOOKS if b != B))

    # ── the real desk's switches ──────────────────────────────────────────────────────────────
    F = DB["live_trading_flags"]
    await F.insert_one({"strategy_id": "iv2_gap_go", "enabled": True, "updated_at": NOW - timedelta(minutes=60)})
    await F.insert_one({"strategy_id": "iv2_rsi2_15m", "enabled": True, "updated_at": NOW - timedelta(hours=5)})
    await F.insert_one({"strategy_id": "iv2_supertrend_45m", "enabled": False, "updated_at": NOW - timedelta(hours=5)})
    # ORB: no flag -> its default (ON). Supertrend 1h: no flag -> default OFF.

    # Production's copy start is 13 Oct and the 2L book's 13 Oct too; a fresh database would set both to now.
    ST = DB["live_intraday_state"]
    await ST.insert_one({"_id": mirror.START_ID, "started_at": NOW - timedelta(days=2)})
    await ST.insert_one({"_id": f"{mirror.START_ID}:2L", "started_at": NOW - timedelta(days=2), "book": "2L"})

    rows = [
        par("p1", "iv2_orb_sel15", "TATASTEEL", 100.0, 200, ltp=101.0),                       # copied: 300 sh
        par("pre", "iv2_orb_sel15", "OLD", 100.0, 7 * 60),                                    # before the start
        par("g_early", "iv2_gap_go", "INFY", 1500.0, 90),                                      # before its switch
        par("g_late", "iv2_gap_go", "HDFCBANK", 1600.0, 50, exit_=1650.0, close_mins_ago=40), # after it: copied
        par("st45", "iv2_supertrend_45m", "SBIN", 800.0, 45),                                  # switched OFF
        par("st1h", "iv2_supertrend_1h", "ITC", 400.0, 44),                                    # default OFF
        par("r_held", "iv2_rsi2_15m", "TATASTEEL", 102.0, 43),                                 # stock held: skip
        par("big", "iv2_orb_sel15", "MRF", 36000.0, 42),                                       # one share > Rs 30k
        par("o2", "iv2_orb_sel15", "AAA", 50.0, 41), par("o3", "iv2_orb_sel15", "BBB", 2000.0, 40),
        par("o4", "iv2_orb_sel15", "CCC", 250.0, 39), par("o5", "iv2_orb_sel15", "DDD", 300.0, 38),
        par("o6", "iv2_orb_sel15", "EEE", 75.0, 37),                                          # sixth at once: full
    ]
    await P.insert_many(rows)
    out = await mirror.sync(entries=True)
    await mirror.sync(entries=True)
    check("a pass over every book runs without an error", isinstance(out, dict) and "opened" in out, str(out))
    tw = {r["parent_position_id"]: r async for r in DB["live_intraday_positions"].find({"book": B})}
    check("Rs 30,000 a position, not capital / slots x 5 (Rs 33,882): 300 shares of a Rs 100 stock",
          tw.get("p1", {}).get("qty") == 300 and abs(tw["p1"]["notional"] - 30000) < 0.01
          and abs(tw["p1"]["capital_deployed"] - 6000) < 0.01, str({k: tw.get("p1", {}).get(k) for k in ("qty", "notional", "capital_deployed")}))
    check("nothing from before the twin's first session", "pre" not in tw)
    check("a strategy's trades only from the moment its real switch went on",
          "g_early" not in tw and "g_late" in tw and tw["g_late"]["status"] == "CLOSED")
    check("a strategy switched off on the real desk, or never on, is not offered", "st45" not in tw and "st1h" not in tw)
    check("one position per stock, as the real desk", "r_held" not in tw)
    check("a share costing more than Rs 30,000 cannot be bought", "big" not in tw)
    check("five open at once is the most; the sixth is skipped", all(k in tw for k in ("o2", "o3", "o4")) and "o6" not in tw,
          str(sorted(tw)))
    check("Rs 2,000 stock: 15 shares (Rs 30,000)", tw.get("o3", {}).get("qty") == 15)
    sk = {s["strategy_id"]: s.get("skipped", {}) async for s in DB["live_intraday_scores"].find({"book": B})}
    orb = sk.get("iv2_orb_sel15", {})
    check("skips counted by reason (price above cap, full), none for strategies never offered",
          orb.get("price_above_cap") == 1 and orb.get("full", 0) >= 1 and "iv2_supertrend_45m" not in sk
          and sk.get("iv2_rsi2_15m", {}).get("symbol_held") == 1, str(sk))
    taken = {r["parent_position_id"] async for r in DB["live_intraday_positions"].find(
        {"book": "2L", "parent_position_id": {"$in": ["st45", "st1h"]}})}
    skipped = set()
    async for d in DB["live_intraday_state"].find({"_id": {"$regex": "^mirror_skipped:2L:"}}):
        skipped.update(d.get("ids") or [])
    check("the other books are still offered every tournament strategy (copied or counted as skipped)",
          {"st45", "st1h"} <= (taken | skipped), f"taken {taken} skipped {skipped & {'st45', 'st1h'}}")

    # Real switch goes OFF while the twin holds TATASTEEL: the open copy must still close with its parent.
    await F.insert_one({"strategy_id": "iv2_orb_sel15", "enabled": False, "updated_at": NOW})
    await P.update_one({"position_id": "p1"}, {"$set": {"status": "CLOSED", "exit_price": 103.0, "exit_reason": "target",
                                                        "closed_at": NOW - timedelta(minutes=1), "closed_on": day(NOW)}})
    await mirror.sync(entries=True)
    p1 = await DB["live_intraday_positions"].find_one({"book": B, "parent_position_id": "p1"})
    gross = round((103.0 - 100.0) * 300, 2)
    check("switched off later, a held copy still closes at its parent's exit, on its own quantity",
          p1["status"] == "CLOSED" and p1["gross_pnl"] == gross and p1["realized_pnl"] < gross, str({k: p1.get(k) for k in ("status", "gross_pnl", "realized_pnl")}))

    s = await li.summary(B)
    check("summary: the twin's money, Rs 30,000 cap, 5 slots, its twin block and start",
          s["initial_capital"] == 33882.16 and abs(s["position_cap"] - 30000) < 0.01 and s["max_open_positions"] == 5
          and s.get("twin", {}).get("of") == "live-trading" and s.get("roster") == list(lt.COPY_SOURCES)
          and s.get("copying_since") is not None, str({k: s.get(k) for k in ("initial_capital", "position_cap", "max_open_positions")}))
    lb = await li.leaderboard(B)
    check("leaderboard lists the real desk's strategies only", {r["strategy_id"] for r in lb} <= set(lt.COPY_SOURCES) and lb)

    # ── beside the real desk ──────────────────────────────────────────────────────────────────
    S, R = DB["live_trading_state"], DB["live_trading_positions"]
    await S.insert_one({"_id": "copy|p1", "decision": "opened", "strategy_id": "iv2_orb_sel15"})
    await R.insert_one({"position_id": "r1", "parent_id": "p1", "symbol": "TATASTEEL", "side": "BUY", "qty": 298,
                        "entry_price": 100.2, "entry_fill_price": 100.2, "exit_price": 102.9, "status": "CLOSED",
                        "realized_pnl": 740.0, "strategy_id": "iv2_orb_sel15", "strategy_name": "Selected ORB 15-min",
                        "opened_at": NOW - timedelta(minutes=199), "closed_at": NOW - timedelta(minutes=1)})
    await S.insert_one({"_id": "copy|g_late", "decision": "Angel refused: the exchange has this stock on its caution "
                                                          "(surveillance) list"})
    await S.insert_one({"_id": "copy|o2", "decision": "desk disarmed"})
    await S.insert_one({"_id": "copy|o6", "decision": "opened"})
    await R.insert_one({"position_id": "r6", "parent_id": "o6", "symbol": "EEE", "side": "BUY", "qty": 400,
                        "entry_price": 75.0, "status": "OPEN", "unrealized_pnl": 12.0, "strategy_id": "iv2_orb_sel15",
                        "strategy_name": "Selected ORB 15-min", "opened_at": NOW - timedelta(minutes=37)})
    cmp = await twin.compare()
    by = {r["parent_id"]: r for r in cmp["rows"]}
    check("a trade both took sits on one row, paper beside real",
          by["p1"]["real_outcome"] == "taken" and by["p1"]["paper"]["qty"] == 300 and by["p1"]["real"]["qty"] == 298
          and by["p1"]["real"]["net"] == 740.0)
    check("refused by Angel / disarmed / never tried are told apart",
          by["g_late"]["real_outcome"] == "refused" and by["o2"]["real_outcome"] == "disarmed"
          and by["o3"]["real_outcome"] == "not_seen", str({k: by[k]["real_outcome"] for k in ("g_late", "o2", "o3")}))
    check("a real trade the twin could not take (its slots were full) is listed as real-only",
          by["o6"]["paper"] is None and by["o6"]["real"]["qty"] == 400)
    t = cmp["totals"]
    check("totals: both 1, real-only 1, paper-only by reason",
          t["both"] == 1 and t["real_only"] == 1 and t["paper_only_by_reason"].get("refused") == 1
          and t["paper_only_by_reason"].get("disarmed") == 1 and t["both_real_net"] == 740.0, str(t))
    check("the real desk's switches are reported with when they changed",
          [x["enabled"] for x in cmp["real_desk"]["strategies"]] == [False, True, True, False, False]
          and cmp["real_desk"]["copy_notional"] == 30000.0)

    # ── the route ─────────────────────────────────────────────────────────────────────────────
    broker = types.ModuleType("app.api.routes.broker")

    async def _get_dhan_client(_uid):
        return None
    broker._get_dhan_client = _get_dhan_client
    sys.modules["app.api.routes.broker"] = broker
    deps = types.ModuleType("app.api.deps")

    async def get_current_user():
        return {"_id": "u"}
    deps.get_current_user = get_current_user
    sys.modules["app.api.deps"] = deps
    import httpx
    from fastapi import FastAPI
    from app.api.routes import live_intraday as routes
    app = FastAPI()
    app.include_router(routes.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/live-intraday/twin")
        sm = await c.get("/api/live-intraday/summary", params={"book": B})
    check("GET /api/live-intraday/twin answers with the side-by-side", r.status_code == 200 and r.json()["book"] == B
          and r.json()["totals"]["both"] == 1, str(r.status_code))
    check("GET /api/live-intraday/summary?book=ltpaper is the twin's own account", sm.status_code == 200
          and sm.json()["initial_capital"] == 33882.16 and sm.json()["book"] == B)

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
