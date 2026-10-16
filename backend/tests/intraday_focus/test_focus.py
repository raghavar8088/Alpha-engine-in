"""Offline checks: python -m unittest discover -s backend/tests/intraday_focus -v

Uses the actual accounting/engine code with an in-memory DB and feed. Nothing connects
to Mongo, a broker, or production. These tests validate mechanics, not profitability.
"""
import ast
import asyncio
import copy
import importlib
import importlib.util
import sys
import types
import unittest
from unittest.mock import patch
from array import array
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "shared"))
from app.services import intraday_focus_rules as R


def matches(doc, query):
    for k, v in query.items():
        got = doc.get(k)
        if isinstance(v, dict):
            if "$in" in v and got not in v["$in"]:
                return False
        elif got != v:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)

    def sort(self, key, order):
        self.rows.sort(key=lambda x: x.get(key), reverse=order < 0)
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    async def to_list(self, n):
        return copy.deepcopy(self.rows[:n])

    def __aiter__(self):
        self.it = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self.it)
        except StopIteration:
            raise StopAsyncIteration


class Collection:
    def __init__(self):
        self.docs = {}
        self.writes = 0

    def find(self, query=None, projection=None):
        return Cursor([d for d in self.docs.values() if matches(d, query or {})])

    async def find_one(self, query):
        return next((copy.deepcopy(d) for d in self.docs.values() if matches(d, query)), None)

    async def replace_one(self, query, doc):
        if not any(matches(d, query) for d in self.docs.values()):
            return types.SimpleNamespace(modified_count=0)
        self.docs[doc["_id"]] = copy.deepcopy(doc)
        self.writes += 1
        return types.SimpleNamespace(modified_count=1)

    async def update_one(self, query, update, upsert=False):
        doc = next((d for d in self.docs.values() if matches(d, query)), None)
        if doc is None and upsert:
            doc = copy.deepcopy(query)
            doc.update(copy.deepcopy(update.get("$setOnInsert", {})))
            self.docs[doc["_id"]] = doc
        if doc is not None:
            doc.update(copy.deepcopy(update.get("$set", {})))
            for key, value in update.get("$inc", {}).items():
                doc[key] = doc.get(key, 0) + value
            if "$pull" in update:
                ids = update["$pull"]["outbox"]["position_id"]["$in"]
                doc["outbox"] = [x for x in doc["outbox"] if x["position_id"] not in ids]
            self.writes += 1
        return types.SimpleNamespace(modified_count=int(doc is not None))

    async def create_index(self, *args, **kwargs):
        return None


class DB(dict):
    def __missing__(self, key):
        self[key] = Collection()
        return self[key]


def stub(name, **values):
    mod = types.ModuleType(name)
    mod.__dict__.update(values)
    sys.modules[name] = mod
    return mod


async def on(_key):
    return True


async def noop():
    return None


test_db = DB()
stub("app.core.db", db=test_db)
stub("app.services.desk_switches", is_on=on)
stub("app.services.in_play")
stub("app.services.intraday_universe")
stub("app.services.market_calendar", in_session=lambda n, start, end: n.weekday() < 5 and start <= n.strftime("%H:%M") < end)
stub("app.services.intraday_session", ensure_cas=noop, squareoff_due=lambda s, now: now.astimezone(R.IST).strftime("%H:%M") >= "15:05")
stub("app.services.intraday_v2_strategies", in_entry_window=lambda now: "09:45" <= now.astimezone(R.IST).strftime("%H:%M") < "14:30")
test_stream = types.SimpleNamespace(states={}, connected=True)
stub("app.services.angel_stream", stream=test_stream)
stub("app.services.intraday_fills", slippage_bp=lambda t: 2.0, stream_minutes=lambda s, t: [])
stub("app.services.intraday_store", store=types.SimpleNamespace(), SESSION_OPEN_MIN=555)
E = importlib.import_module("app.services.intraday_focus")

NOW = datetime(2026, 10, 15, 10, 15, 25, tzinfo=R.IST)
BOUNDARY = NOW.replace(second=0)
SID = R.STRATEGIES[0][0]


def account(sid=SID):
    return R.new_account(sid, NOW - timedelta(minutes=30))


def candidate(symbol="ABC", side="BUY", **overrides):
    return {"strategy_id": SID, "symbol": symbol, "side": side, "price": 100.0,
            "quote_at": NOW.timestamp(), "priority": 1, "stop_dist": 2.0,
            "target_dist": 4.0, "slippage_pct": .02, "max_hold_seconds": 10800,
            **overrides}


def opened(side="BUY", rows=None):
    return R.plan_entries(account(), rows or [candidate(side=side)], BOUNDARY, NOW, E.fee_model)


class AccountingTests(unittest.TestCase):
    def test_exact_five_and_fixed_allocation(self):
        self.assertEqual(set(R.BY_ID), {"iv2_macd_trend_1h", "iv2_donchian_1h", "iv2_ema_pullback_45m", "iv2_supertrend_1h", "iv2_keltner_1h"})
        self.assertEqual(sum(account(s)["initial_capital"] for s in R.BY_ID), 5_000_000)
        self.assertEqual(R.SLOT_CAPITAL, 200_000)

    def test_fresh_quotes_reject_stale_future_nan_zero(self):
        for price, when in [(0, NOW.timestamp()), (float("nan"), NOW.timestamp()), (100, NOW.timestamp()-31), (100, NOW.timestamp()+1), (None, 0)]:
            self.assertFalse(R.fresh_quote(price, when, NOW))
        self.assertTrue(R.fresh_quote(100, NOW.timestamp()-30, NOW))

    def test_five_slots_and_fees_fit_capital(self):
        a = opened(rows=[candidate(str(i)) for i in range(12)])
        self.assertEqual(len(a["positions"]), 5)
        self.assertGreaterEqual(R.available_cash(a), 0)
        for p in a["positions"]:
            self.assertLessEqual(p["capital_deployed"] + p["fee_reserve"], 200000)
            self.assertEqual(p["qty"], int(p["qty"]))
            self.assertLess(p["unrealized_pnl"], 0)

    def test_no_cross_strategy_capital(self):
        a = account()
        a["realized_pnl"] = -999990
        other = account(R.STRATEGIES[1][0])
        self.assertEqual(R.plan_entries(a, [candidate()], BOUNDARY, NOW, E.fee_model)["positions"], [])
        self.assertEqual(R.available_cash(other), 1_000_000)

    def test_no_duplicate_symbol_or_signal(self):
        a = opened(rows=[candidate(), candidate()])
        self.assertEqual(len(a["positions"]), 1)
        self.assertEqual(R.plan_entries(a, [candidate()], BOUNDARY, NOW, E.fee_model), a)

    def test_wrong_strategy_not_admitted(self):
        self.assertFalse(opened(rows=[candidate(strategy_id="some_other_rule")])["positions"])

    def test_no_backfill_or_future_signal(self):
        for b in (BOUNDARY-timedelta(minutes=15), NOW+timedelta(seconds=1)):
            self.assertFalse(R.plan_entries(account(), [candidate()], b, NOW, E.fee_model)["positions"])
        a = R.new_account(SID, NOW)
        self.assertFalse(R.plan_entries(a, [candidate()], BOUNDARY, NOW, E.fee_model)["positions"])

    def test_entry_cutoff_and_opening_restriction(self):
        for hour, minute in ((9, 30), (14, 30), (15, 0)):
            n = NOW.replace(hour=hour, minute=minute)
            self.assertFalse(R.plan_entries(account(), [candidate(quote_at=n.timestamp())], n.replace(second=0), n, E.fee_model)["positions"])

    def test_stale_entry_quote_blocks(self):
        self.assertFalse(opened(rows=[candidate(quote_at=NOW.timestamp()-60)])["positions"])

    def test_stale_held_position_blocks_more_risk(self):
        a = opened()
        a["positions"][0]["price_status"] = "STALE"
        n = NOW + timedelta(hours=1)
        out = R.plan_entries(a, [candidate("DEF", quote_at=n.timestamp())], n.replace(second=0), n, E.fee_model)
        self.assertEqual(len(out["positions"]), 1)
        self.assertIn("stale", out["last_skip"])

    def test_daily_loss_breaker_is_per_account(self):
        a = account()
        a["daily"][R.day(NOW)] = {"realized_pnl": -30000}
        out = R.plan_entries(a, [candidate()], BOUNDARY, NOW, E.fee_model)
        self.assertFalse(out["positions"])
        self.assertIn("loss limit", out["last_skip"])
        self.assertTrue(opened()["positions"])

    def test_archive_backlog_blocks_entries(self):
        a = account()
        a["outbox"] = [{}] * 100
        self.assertFalse(R.plan_entries(a, [candidate()], BOUNDARY, NOW, E.fee_model)["positions"])

    def test_price_above_slot_skips(self):
        self.assertFalse(opened(rows=[candidate(price=250000)])["positions"])

    def test_invalid_stop_and_targets_rejected(self):
        for args in ({"stop_dist": 0}, {"stop_dist": float("nan")}, {"target_dist": -2}, {"slippage_pct": float("nan")}, {"side": "X"}):
            self.assertFalse(opened(rows=[candidate(**args)])["positions"])

    def test_long_and_short_fills_adverse(self):
        self.assertGreater(opened()["positions"][0]["entry_price"], 100)
        self.assertLess(opened("SELL")["positions"][0]["entry_price"], 100)

    def test_entry_minute_extremes_cannot_exit_position(self):
        p = opened()["positions"][0]
        t = int(NOW.timestamp()) // 60 * 60
        self.assertIsNone(R.exit_decision(p, [(t, 100, 200, 1, 100)], 100, NOW, False))
        self.assertEqual(R.exit_decision(p, [], 90, NOW, False)[0], "stoploss")

    def test_long_short_both_hit_stop_first(self):
        for side in ("BUY", "SELL"):
            p = opened(side)["positions"][0]
            ts = p["checked_through"]
            result = R.exit_decision(p, [(ts, 100, 110, 90, 100)], None, NOW+timedelta(minutes=1), False)
            self.assertEqual(result, ("stoploss", p["stoploss"], True))

    def test_gap_stop_and_limit_target(self):
        for side, gap in (("BUY", 90), ("SELL", 110)):
            p = opened(side)["positions"][0]
            ts = p["checked_through"]
            result = R.exit_decision(p, [(ts, gap, gap, gap, gap)], None, NOW+timedelta(minutes=1), False)
            self.assertEqual(result, ("stoploss", gap, True))
            px = 120 if side == "BUY" else 80
            self.assertEqual(R.exit_decision(p, [], px, NOW, False), ("target", p["target"], False))

    def test_time_eod_and_no_fake_exit(self):
        p = opened()["positions"][0]
        self.assertEqual(R.exit_decision(p, [], 100, NOW+timedelta(hours=3), False)[0], "time")
        self.assertEqual(R.exit_decision(p, [], 100, NOW, True)[0], "eod")
        self.assertIsNone(R.exit_decision(p, [], None, NOW+timedelta(hours=5), True))
        self.assertEqual(R.exit_decision(p, [], 100, NOW+timedelta(days=1), False)[0], "missed_eod_recovery")

    def test_close_once_and_capital_released(self):
        a = opened()
        p = a["positions"][0]
        b = R.close_position(a, p["position_id"], ("target", p["target"], False), NOW+timedelta(minutes=2), E.fee_model)
        c = R.close_position(b, p["position_id"], ("target", p["target"], False), NOW+timedelta(minutes=3), E.fee_model)
        self.assertEqual(b, c)
        self.assertEqual(b["trades"], 1)
        self.assertEqual(R.available_cash(b), R.CAPITAL+b["realized_pnl"])
        self.assertEqual(len(b["outbox"]), 1)
        self.assertEqual(len(a["positions"]), 1, "pure function must not mutate original")

    def test_returns_use_strategy_and_trade_denominators(self):
        a = opened()
        p = a["positions"][0]
        b = R.close_position(a, p["position_id"], ("target", p["target"], False), NOW, E.fee_model)
        self.assertEqual(R.account_summary(b)["return_pct"], round(b["realized_pnl"] / 1_000_000 * 100, 4))
        self.assertEqual(b["outbox"][0]["return_pct"], round(b["realized_pnl"] / p["capital_deployed"] * 100, 4))

    def test_brokerage_minimum_cap_and_short_stt(self):
        _, small = E.fee_model(10, 10, 1, "BUY")
        self.assertEqual(small["brokerage"], 10)
        fees, large = E.fee_model(100, 100, 2000, "BUY")
        self.assertEqual(large["brokerage"], 40)
        self.assertEqual(fees, round(sum(v for k, v in large.items() if k not in ("total", "product")), 2))
        _, short = E.fee_model(100, 90, 100, "SELL")
        self.assertEqual(short["stt"], 2.5)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for coll in test_db.values():
            coll.docs.clear(); coll.writes = 0
        E._cache = []; E._cache_at = 0; E._initialized = False
        E._last_mark = 0; E._note = None
        E._now = lambda: R.utc(NOW)
        E.ENABLED = True
        E.desk_switches.is_on = on
        test_stream.states = {}; test_stream.connected = True

    def live_quote(self, symbol="ABC", price=100, delay=0):
        test_stream.states[symbol] = types.SimpleNamespace(day=NOW.date(), last_ltp=price,
            last_price_received_at=NOW.timestamp()-delay, last_price_exchange_at=NOW.timestamp()-delay)

    async def test_snapshot_read_only_and_no_seeded_profit(self):
        snap = await E.snapshot()
        self.assertEqual(len(snap["strategies"]), 5)
        self.assertEqual(snap["initial_capital"], 5_000_000)
        self.assertEqual(snap["total_pnl"], 0)
        self.assertIsNone(snap["started_at"])
        self.assertFalse(snap["real_orders_enabled"])
        self.assertEqual(sum(c.writes for c in test_db.values()), 0)

    async def test_initialize_preserves_existing_accounts(self):
        await E.initialize()
        a = E.accounts.docs[SID]
        a["realized_pnl"] = 500
        E._initialized = False
        await E.initialize()
        self.assertEqual(E.accounts.docs[SID]["realized_pnl"], 500)
        self.assertEqual(len(E.accounts.docs), 5)

    async def test_cas_loser_cannot_duplicate_financial_writes(self):
        old = account()
        E.accounts.docs[SID] = copy.deepcopy(old)
        first, second = opened(), opened()
        self.assertTrue(await E._commit(old, first))
        self.assertFalse(await E._commit(old, second))
        self.assertEqual(len(E.accounts.docs[SID]["positions"]), 1)

    async def test_quote_requires_connection_both_timestamps_and_current_day(self):
        self.live_quote()
        self.assertEqual(E.quote("ABC", NOW)[0], 100)
        st = test_stream.states["ABC"]
        st.last_price_exchange_at -= 31
        self.assertIsNone(E.quote("ABC", NOW)[0])
        self.live_quote(); test_stream.connected = False
        self.assertIsNone(E.quote("ABC", NOW)[0])
        test_stream.connected = True; test_stream.states["ABC"].day -= timedelta(days=1)
        self.assertIsNone(E.quote("ABC", NOW)[0])

    async def test_switch_off_does_not_block_exits(self):
        a = opened()
        E.accounts.docs[SID] = a
        E.ENABLED = False
        self.live_quote(price=90)
        self.assertEqual(await E.manage(), 1)
        self.assertFalse(E.accounts.docs[SID]["positions"])

    async def test_stale_quote_does_not_manufacture_eod_exit(self):
        E.accounts.docs[SID] = opened()
        later = R.utc(NOW.replace(hour=15, minute=6))
        E._now = lambda: later
        self.live_quote()
        self.assertEqual(await E.manage(), 0)
        self.assertEqual(E.accounts.docs[SID]["positions"][0]["price_status"], "STALE · EXIT PENDING")

    async def test_closing_first_position_does_not_lose_second_mark(self):
        E.accounts.docs[SID] = opened(rows=[candidate("ABC"), candidate("DEF")])
        self.live_quote("ABC", 90); self.live_quote("DEF", 101)
        self.assertEqual(await E.manage(), 1)
        self.assertEqual(E.accounts.docs[SID]["positions"][0]["ltp"], 101)

    async def test_archive_idempotence_and_pending_trades_visible(self):
        a = opened(); p = a["positions"][0]
        a = R.close_position(a, p["position_id"], ("target", p["target"], False), NOW, E.fee_model)
        E.accounts.docs[SID] = a
        before = await E.snapshot()
        self.assertEqual(len(before["trades"]), 1)
        await E.archive_closed(); E._cache_at = 0
        await E.archive_closed()
        self.assertEqual(len(E.trades.docs), 1)
        self.assertEqual(E.accounts.docs[SID]["outbox"], [])
        after = await E.snapshot()
        self.assertEqual(after["realized_pnl"], before["realized_pnl"])
        self.assertEqual(after["daily"][0]["return_pct"], round(a["realized_pnl"] / 5_000_000 * 100, 4))

    async def test_closed_market_is_not_live(self):
        E._now = lambda: R.utc(NOW.replace(hour=18))
        self.live_quote()
        snap = await E.snapshot()
        self.assertEqual(snap["feed"]["status"], "MARKET_CLOSED")
        self.assertFalse(snap["engine"]["entries_enabled"])

    async def test_config_mismatch_fails_not_resets(self):
        a = account(); a["initial_capital"] = 99
        E.accounts.docs[SID] = a
        with self.assertRaises(RuntimeError):
            await E.snapshot()
        self.assertEqual(E.accounts.docs[SID]["initial_capital"], 99)

    async def run_evaluation(self, complete=True, enabled=True, now=NOW):
        async def members():
            return [{"symbol": "ABC", "turnover_cr": 500}]
        async def ranked(**kwargs):
            return {"top": [{"symbol": "ABC", "rvol_raw": 2}]}
        specs = {sid: types.SimpleNamespace(strategy_id=sid, tf=tf) for sid, _, tf, _ in R.STRATEGIES}
        series = types.SimpleNamespace(ts=[], o=[], c=[])
        fake_store = types.SimpleNamespace(count_between=lambda *a: 4 if complete else 0,
                                          series=lambda *a, **k: series)
        signal = types.SimpleNamespace(side="BUY", entry=50, stop_dist=2, target_dist=4,
                    priority=2, max_bars=3, rationale="test", trigger=None, oco=None)
        E.ENABLED = enabled
        with patch.object(E, "_now", return_value=R.utc(now)), \
                patch.object(E, "store", fake_store), \
                patch.object(E.intraday_universe, "members", members, create=True), \
                patch.object(E.in_play, "ranked", ranked, create=True), \
                patch.object(E.v2, "BY_ID", specs, create=True), \
                patch.object(E.v2, "TF_SECONDS", {"1h": 3600, "45m": 2700}, create=True), \
                patch.object(E.v2, "build_ctx", lambda *a: object(), create=True), \
                patch.object(E.v2, "evaluate", lambda *a: signal, create=True):
            await E.evaluate_boundary(BOUNDARY)

    async def test_boundary_uses_real_quote_not_signal_close_and_is_deduped(self):
        for sid in R.BY_ID:
            E.accounts.docs[sid] = account(sid)
        self.live_quote(price=100)
        await self.run_evaluation()
        self.assertEqual(sum(len(a["positions"]) for a in E.accounts.docs.values()), 4)  # 1-hour rules only
        self.assertEqual(E.accounts.docs[SID]["positions"][0]["entry_price"], 100.02)
        self.assertEqual(E.accounts.docs[SID]["positions"][0]["signal_price"], 50)
        E._last_evaluation = 0  # simulate restart
        await self.run_evaluation()
        self.assertEqual(sum(len(a["positions"]) for a in E.accounts.docs.values()), 4)

    async def test_incomplete_bars_block_evaluation_entries(self):
        for sid in R.BY_ID:
            E.accounts.docs[sid] = account(sid)
        self.live_quote()
        await self.run_evaluation(complete=False)
        self.assertEqual(sum(len(a["positions"]) for a in E.accounts.docs.values()), 0)

    async def test_disabled_and_old_boundary_do_not_trade(self):
        for sid in R.BY_ID:
            E.accounts.docs[sid] = account(sid)
        self.live_quote()
        await self.run_evaluation(enabled=False)
        await self.run_evaluation(now=NOW+timedelta(minutes=3))
        self.assertEqual(sum(len(a["positions"]) for a in E.accounts.docs.values()), 0)

    async def test_missing_live_quotes_cannot_open(self):
        for sid in R.BY_ID:
            E.accounts.docs[sid] = account(sid)
        await self.run_evaluation()
        self.assertEqual(sum(len(a["positions"]) for a in E.accounts.docs.values()), 0)


class WiringTests(unittest.TestCase):
    def test_route_has_auth_and_no_write_endpoints(self):
        code = (ROOT / "backend/app/api/routes/intraday_focus.py").read_text(encoding="utf-8")
        self.assertIn("Depends(get_current_user)", code)
        self.assertIn('@router.get("/snapshot")', code)
        for write in ("post", "put", "patch", "delete"):
            self.assertNotIn(f"@router.{write}", code)

    def test_no_broker_order_calls_or_tournament_ledger(self):
        code = (ROOT / "backend/app/services/intraday_focus.py").read_text(encoding="utf-8")
        for forbidden in ("place_order", "submit_order", "intraday_lab_positions", "intraday_lab_scores", "live_trading_engine"):
            self.assertNotIn(forbidden, code)

    def test_stream_valid_price_clock_does_not_advance_on_invalid_price(self):
        tree = ast.parse((ROOT / "backend/app/services/angel_stream.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TokenState")
        ns = {"datetime": datetime, "IST": R.IST, "array": array, "SESSION_OPEN_MIN": 555,
              "SESSION_CLOSE_MIN": 930, "time": types.SimpleNamespace(time=lambda: NOW.timestamp()),
              "_minute_start": lambda x: int(x)//60*60}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "angel_stream.py", "exec"), ns)
        s = ns["TokenState"]("ABC", "1")
        s.on_tick({"exch_ms": int(NOW.timestamp()*1000), "ltp": 100})
        saved = s.last_price_exchange_at
        s.on_tick({"exch_ms": int((NOW.timestamp()+5)*1000), "ltp": 0})
        self.assertEqual(s.last_price_exchange_at, saved)
        self.assertEqual(s.last_ltp, 100)


if __name__ == "__main__":
    unittest.main()
