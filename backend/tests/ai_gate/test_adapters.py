"""The four module readers against in-memory MongoDB documents shaped like each engine's own (mongomock-motor).
Checks the queries, the aggregations, the normalised position and the outcome mapping; the stores that hold bars are
replaced by fakes. Skipped when mongomock-motor is not installed.
    cd backend && python -m pytest tests/ai_gate -q
"""
import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

mm = pytest.importorskip("mongomock_motor")

UTC = timezone.utc
NOW = datetime(2026, 11, 10, 5, 0, tzinfo=UTC)


def _naive(t):            # Mongo hands datetimes back without a zone, as the real driver does by default
    return t.replace(tzinfo=None)


@pytest.fixture()
def env(monkeypatch):
    client = mm.AsyncMongoMockClient()
    db = client["app"]
    pdb = client["alpha_engine_premium"]
    core_db = types.ModuleType("app.core.db")
    core_db.intraday_lab_positions_collection = db.intraday_lab_positions
    core_db.commodity_positions_collection = db.commodity_positions
    core_db.gold_positions_collection = db.gold_positions
    monkeypatch.setitem(sys.modules, "app.core.db", core_db)

    bars = types.SimpleNamespace(t=[int((NOW - timedelta(minutes=15 * (8 - i))).timestamp()) for i in range(8)],
                                 o=[100.0] * 8, h=[101.0] * 8, l=[99.0] * 8, c=[100.5] * 8, v=[1000] * 8)
    store_mod = types.ModuleType("app.services.intraday_store")
    store_mod.store = types.SimpleNamespace(get=lambda sym: bars)
    monkeypatch.setitem(sys.modules, "app.services.intraday_store", store_mod)

    ev = types.ModuleType("app.services.event_classifier")

    async def recent_high(symbol, minutes=120, now=None):
        return symbol == "TCS"
    ev.recent_high = recent_high
    monkeypatch.setitem(sys.modules, "app.services.event_classifier", ev)

    v2 = types.ModuleType("app.services.intraday_v2_strategies")
    v2.CATALOG = [types.SimpleNamespace(strategy_id="iv2_supertrend_1h", why="Supertrend(10,3) changing direction")]
    monkeypatch.setitem(sys.modules, "app.services.intraday_v2_strategies", v2)

    class Bar:
        def __init__(self, ts):
            self.ts, self.open, self.high, self.low, self.close, self.volume = ts, 1.0, 2.0, 0.5, 1.5, 3.0
    cb = types.ModuleType("app.services.commodity_bars")
    cb.TIMEFRAMES = {"15m": ("FIFTEEN_MINUTE", 15)}

    async def load_bars(symbol, timeframe, limit=400, closed_only=False, prefer_expiry=None):
        return [Bar(NOW - timedelta(minutes=15 * k)) for k in range(6, -1, -1)]      # the last one is still forming
    cb.load_bars = load_bars
    monkeypatch.setitem(sys.modules, "app.services.commodity_bars", cb)

    gd = types.ModuleType("app.services.gold_desk")
    gd.venue = lambda key: types.SimpleNamespace(key=key)
    gd.tf_minutes = lambda v, tf: 240

    async def gload(v, symbol, tf, limit, inst=None):
        return [Bar(NOW - timedelta(hours=4 * k)) for k in range(5, 0, -1)]
    gd.load_bars = gload
    monkeypatch.setitem(sys.modules, "app.services.gold_desk", gd)

    pp = types.ModuleType("app.api.routes.premium_paper")
    pp._database = lambda: pdb
    monkeypatch.setitem(sys.modules, "app.api.routes.premium_paper", pp)

    from app.services import ai_gate as G
    return types.SimpleNamespace(G=G, db=db, pdb=pdb)


def run(coro):
    return asyncio.run(coro)


def test_intraday(env):
    G, db = env.G, env.db
    sig = NOW - timedelta(seconds=40)
    run(db.intraday_lab_positions.insert_many([
        {"position_id": "old1", "engine": "v2", "strategy_id": "iv2_supertrend_1h", "status": "CLOSED", "realized_pnl": 1200.0,
         "opened_at": _naive(NOW - timedelta(days=2)), "closed_at": _naive(NOW - timedelta(days=2) + timedelta(hours=1))},
        {"position_id": "old2", "engine": "v2", "strategy_id": "iv2_supertrend_1h", "status": "CLOSED", "realized_pnl": -800.0,
         "opened_at": _naive(NOW - timedelta(days=1)), "closed_at": _naive(NOW - timedelta(days=1) + timedelta(hours=1))},
        {"position_id": "p1", "engine": "v2", "strategy_id": "iv2_supertrend_1h", "strategy_name": "Supertrend Flip · 1 hour",
         "symbol": "TCS", "side": "BUY", "entry_price": 3500.5, "signal_price": 3499.0, "slippage_bp": 1.5, "qty": 285,
         "target": 3540.0, "stoploss": 3470.0, "max_bars": 3, "timeframe": "1h", "status": "OPEN", "realized_pnl": None,
         "signal_bar_close": _naive(sig), "opened_at": _naive(NOW - timedelta(seconds=30))},
        {"position_id": "x1", "engine": "v1", "opened_at": _naive(NOW)},
    ]))
    a = G.IntradayAdapter()
    ps = run(a.new_parents(NOW - timedelta(minutes=10)))
    assert [p["parent_id"] for p in ps] == ["p1"]
    p = ps[0]
    assert p["side"] == "BUY" and p["entry"] == 3500.5 and p["stop"] == 3470.0 and p["rule"].startswith("Supertrend")
    assert p["signal_time"] == sig and "4.0 bp" not in p["cost_note"] and "7.0 bp" in p["cost_note"]
    ctx = run(a.context(p))
    assert ctx["record"]["n"] == 2 and ctx["record"]["wins"] == 1 and ctx["record"]["net"] == 400.0
    assert any("Event risk" in n for n in ctx["notes"]) and ctx["bars"]
    assert all(r[0] + 900 <= int(sig.timestamp()) for r in ctx["bars"])
    text = G.build_prompt("intraday", p, ctx)
    assert "2 closed trades, 50% won" in text
    run(db.intraday_lab_positions.update_one({"position_id": "p1"}, {"$set": {
        "status": "CLOSED", "exit_price": 3540.0, "exit_reason": "target", "realized_pnl": 10800.0,
        "closed_at": _naive(NOW + timedelta(hours=1))}}))
    o = run(a.outcomes(["p1", "old1"]))
    assert o["p1"]["status"] == "CLOSED" and o["p1"]["pnl"] == 10800.0 and o["p1"]["closed_at"].tzinfo is not None
    ctl = run(a.control(NOW - timedelta(days=3)))
    assert ctl["INR"]["n"] == 3


def test_commodity_bars_stop_before_the_open(env):
    G, db = env.G, env.db
    run(db.commodity_positions.insert_one({
        "position_id": "c1", "strategy_id": "cp_hs_15m", "strategy_name": "Head and shoulders · 15m", "family_label": "Reversal",
        "pattern": "head_and_shoulders", "symbol": "CRUDEOILM", "side": "SELL", "entry_price": 5800.0, "signal_price": 5810.0,
        "qty": 10, "capital_deployed": 58000.0, "entry_costs": 25.0, "target": 5740.0, "stoploss": 5840.0,
        "timeframe": "15m", "max_hold_bars": 40, "status": "OPEN", "opened_at": _naive(NOW)}))
    a = G.CommodityAdapter()
    p = run(a.new_parents(NOW - timedelta(minutes=15)))[0]
    assert p["side"] == "SELL" and p["market"] == "MCX futures" and "0.086%" in p["cost_note"]
    ctx = run(a.context(p))
    assert ctx["bars"] and all(r[0] + 900 <= int(NOW.timestamp()) for r in ctx["bars"])
    assert len(ctx["bars"]) == 6                          # the forming bar is left out


def test_gold_currency_and_void(env):
    G, db = env.G, env.db
    run(db.gold_positions.insert_many([
        {"position_id": "g1", "venue": "delta", "currency": "USD", "strategy_id": "gd_brk_4h", "strategy_name": "Breakout · 4h",
         "strategy_template": "breakout", "symbol": "XAUTUSD", "side": "BUY", "entry_price": 2650.0, "signal_price": 2648.0,
         "qty": 0.5, "notional": 1325.0, "entry_costs": 0.66, "target": 2690.0, "stoploss": 2630.0, "timeframe": "4h", "h1": True,
         "status": "OPEN", "signal_bar_close": _naive(NOW - timedelta(minutes=1)), "opened_at": _naive(NOW)},
        {"position_id": "g2", "venue": "delta", "currency": "USD", "status": "CLOSED", "void": True, "opened_at": _naive(NOW)}]))
    a = G.GoldAdapter()
    ps = run(a.new_parents(NOW - timedelta(minutes=20)))
    p = next(x for x in ps if x["parent_id"] == "g1")
    assert p["currency"] == "USD" and "H1" in p["rule"]
    ctx = run(a.context(p))
    assert ctx["bars"] and all(r[0] + 4 * 3600 <= int(p["signal_time"].timestamp()) for r in ctx["bars"])
    o = run(a.outcomes(["g1", "g2"]))
    assert o["g1"]["status"] == "OPEN" and o["g2"]["status"] == "VOID"


def test_premium_sized_trades_only_and_missing(env):
    G, pdb = env.G, env.pdb
    t = int(NOW.timestamp()) - 300
    run(pdb.premium_accounts.insert_one({"_id": "YT-08", "name": "Inside candle (15m)", "channel": "Power of Stocks"}))
    run(pdb.premium_trades.insert_many([
        {"_id": f"YT-08|NSE15|SBIN|{t}|1", "acct": "YT-08", "mkt": "NSE15", "sym": "SBIN", "side": 1, "setup": "IC",
         "variant": "V0", "entry_t": t, "entry": 812.0, "stop": 806.0, "target": 824.0, "cost_r": 0.12, "qty": 300,
         "pnl": 0.0, "open": True, "exit_t": None},
        {"_id": f"YT-08|NSE15|ITC|{t}|-1", "acct": "YT-08", "mkt": "NSE15", "sym": "ITC", "side": -1, "entry_t": t,
         "entry": 410.0, "stop": 414.0, "target": None, "qty": 0, "skip": "margin"},
        {"_id": "YT-08|NSE15|INFY|1|1", "acct": "YT-08", "mkt": "NSE15", "sym": "INFY", "side": 1, "entry_t": t - 86400,
         "exit_t": t - 80000, "open": False, "qty": 100, "pnl": -1500.0}]))
    a = G.PremiumAdapter()
    ps = run(a.new_parents(NOW - timedelta(minutes=40)))
    assert [p["symbol"] for p in ps] == ["SBIN"]                    # the unsized ITC trade is not a position
    p = ps[0]
    assert p["side"] == "BUY" and p["strategy_name"] == "Inside candle (15m)" and "0.12R" in p["cost_note"]
    ctx = run(a.context(p))
    assert ctx["record"]["n"] == 1 and ctx["record"]["net"] == -1500.0 and ctx["bars"]
    o = run(a.outcomes([p["parent_id"], "YT-08|gone|X|1|1"]))
    assert o[p["parent_id"]]["status"] == "OPEN" and o["YT-08|gone|X|1|1"]["status"] == "MISSING"


def test_mongo_repo_and_summary(env, monkeypatch):
    G = env.G
    client = mm.AsyncMongoMockClient()
    rp = G.MongoRepo(client["alpha_engine_intraday"])
    monkeypatch.setattr(G, "_repo", rp)

    class Fake:
        module = "intraday"

        async def context(self, p):
            return {"bars": [], "record": {"n": 0, "wins": 0, "net": 0.0}}

        async def outcomes(self, ids):
            return {i: ({"status": "CLOSED", "exit_price": 101.0, "exit_reason": "stop", "closed_at": NOW, "pnl": -500.0,
                         "currency": "INR"} if i.startswith("s") else {"status": "OPEN"}) for i in ids}

        async def control(self, since):
            return {"INR": {"n": 3, "wins": 1, "net": 700.0}}
    fake = Fake()
    monkeypatch.setitem(G.ADAPTERS, "intraday", fake)

    def par(pid):
        return {"parent_id": pid, "strategy_id": "s", "symbol": "SBIN", "side": "BUY", "entry": 100.0, "stop": 99.0,
                "target": 102.0, "currency": "INR", "signal_time": NOW, "opened_at": NOW - timedelta(seconds=10)}

    async def take(prompt):
        return ({"decision": "take", "p_profit": 0.6, "confidence": "high", "reasons": ["r"], "main_risk": "m"},
                {"input_tokens": 1000, "output_tokens": 200}, G.MODEL)

    async def skip(prompt):
        return ({"decision": "skip", "p_profit": 0.3, "confidence": "low", "reasons": ["r"], "main_risk": "m"},
                {"input_tokens": 1000, "output_tokens": 200}, G.MODEL)
    run(rp.ensure())
    d1 = run(G.review("intraday", par("t1"), rp, fake, take, NOW))
    d2 = run(G.review("intraday", par("s1"), rp, fake, skip, NOW))
    assert d1["ai_position_id"] == "AI-INT-20261110-0001" and d2["decision"] == "skip"
    assert run(rp.decided(["intraday|t1", "intraday|s1", "intraday|zz"])) == {"intraday|t1", "intraday|s1"}
    assert run(rp.called_today("intraday", "2026-11-10")) == 2
    run(rp.update_position("AI-INT-20261110-0001", {"status": "CLOSED", "pnl": 1500.0, "currency": "INR"}))
    s = run(G.summary("intraday"))
    assert s["decisions"] == {"take": 1, "skip": 1} and s["today"] == {"take": 1, "skip": 1}
    assert s["approved"]["INR"] == {"trades": 1, "wins": 1, "win_rate": 100.0, "net": 1500.0, "avg": 1500.0}
    assert s["skipped"]["INR"]["net"] == -500.0 and s["control"]["INR"]["trades"] == 3
    assert s["cost_usd"] == round(2 * (1000 * 2 + 200 * 10) / 1e6, 4)
    pos = run(G.positions("intraday"))
    assert pos[0]["ai_position_id"] == "AI-INT-20261110-0001" and isinstance(pos[0]["approved_at"], str)
    decs = run(G.decisions("intraday", 10, "skip"))
    assert [d["parent_id"] for d in decs] == ["s1"] and "usage" not in decs[0]
    run(rp.claim({"_id": "intraday|p9", "module": "intraday", "decision": "pending", "seen_at": NOW - timedelta(hours=1),
                  "d": "2026-11-10"}))
    assert run(rp.expire_pending(NOW)) == 1
