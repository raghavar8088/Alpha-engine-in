"""Import the whole desk with a stubbed Mongo driver, to catch wiring mistakes.

Run:  python backend/tests/trending_stocks/verify_wiring.py

The other three verification scripts exercise pure logic — catalog, detectors, the 1:6
gate — none of which touch the database. This one covers the opposite risk: a collection
name that does not exist, a helper imported under the wrong name, a scheduler that
references a config constant nobody defined. Those all import fine in isolation and fail
at 09:15 on a Monday.

`motor` is not installed in every environment this repo is checked out into, so the driver
is stubbed with something that records which collection names were asked for. That is
enough to prove every `db[...]` this module reaches for is one `app.core.db` actually
declares, and that the engine, evidence layer and scheduler all import cleanly together.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FAILURES: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


# ---- stub the driver ------------------------------------------------------------
ASKED: list[str] = []


class _Coll:
    def __init__(self, name):
        self.name = name

    def __getattr__(self, _item):
        raise AssertionError("this stub is for import-time wiring only, not for queries")


class _DB:
    def __getitem__(self, name):
        ASKED.append(name)
        return _Coll(name)


class _Client:
    def __init__(self, *a, **k):
        pass

    def __getitem__(self, _name):
        return _DB()


# `pydantic_settings` ships with the backend's requirements but not with the bare
# interpreter this repo is often checked out into. `Settings` only ever reads env vars
# with defaults, so a plain pydantic BaseModel is a faithful stand-in for the purpose of
# an import-wiring test.
if "pydantic_settings" not in sys.modules:
    try:
        import pydantic_settings  # noqa: F401
    except ImportError:
        from pydantic import BaseModel

        ps = types.ModuleType("pydantic_settings")

        class _BaseSettings(BaseModel):
            model_config = {"extra": "ignore"}

        ps.BaseSettings = _BaseSettings
        ps.SettingsConfigDict = dict
        sys.modules["pydantic_settings"] = ps

if "motor" not in sys.modules:
    motor = types.ModuleType("motor")
    motor_async = types.ModuleType("motor.motor_asyncio")
    motor_async.AsyncIOMotorClient = _Client
    motor_async.AsyncIOMotorCollection = _Coll
    motor.motor_asyncio = motor_async
    sys.modules["motor"] = motor
    sys.modules["motor.motor_asyncio"] = motor_async

# ---- import the desk ------------------------------------------------------------
print("\n== the module imports as a whole ==")
try:
    from app.services.trending_stocks import basket, bars, engine, evidence, scheduler
    from app.services.trending_stocks import signals, validation
    check("engine, evidence, bars, basket, signals, validation and scheduler all import", True)
except Exception as exc:  # noqa: BLE001
    check("engine, evidence, bars, basket, signals, validation and scheduler all import",
          False, f"{type(exc).__name__}: {exc}")
    print(f"\nFAILURES: {'; '.join(FAILURES)}")
    sys.exit(1)

print("\n== every collection it reaches for is declared ==")
expected = {"ts_basket", "ts_backtests", "ts_validation", "ts_scores", "ts_positions",
            "ts_trades", "ts_signals", "ts_rejections", "ts_evidence", "ts_equity",
            "ts_state"}
missing = sorted(expected - set(ASKED))
check("all eleven ts_* collections exist in app.core.db", not missing, str(missing))
check("bars go to the SHARED collection, not a private one",
      "bars" in ASKED and not any(a.startswith("ts_bars") for a in ASKED),
      "a private bar store would hide the deeper history from every other module")

print("\n== capital and gate configuration ==")
check("Rs10,00,000 per strategy", engine.PER_STRATEGY_CAPITAL == 1_000_000,
      f"{engine.PER_STRATEGY_CAPITAL:,.0f}")
check("the book is 10L x the whole library",
      engine.INITIAL_CAPITAL == engine.PER_STRATEGY_CAPITAL * len(engine.LONG_CATALOG),
      f"Rs{engine.INITIAL_CAPITAL:,.0f} over {len(engine.LONG_CATALOG)} strategies")
check("1% risk per trade", engine.RISK_PCT == 0.01)
check("paper trading is earned, not granted", engine.REQUIRE_GRADE
      and engine.MIN_GRADE_TO_TRADE >= 3, f"min grade {engine.MIN_GRADE_TO_TRADE}")
check("a cap on how many strategies may hold one symbol",
      1 <= engine.MAX_STRATEGIES_PER_SYMBOL <= 20, str(engine.MAX_STRATEGIES_PER_SYMBOL))
check("five of seven pillars required", evidence.MIN_PILLARS == 5)
check("seven pillars are declared", len(evidence.PILLARS) == 7, str(evidence.PILLARS))

print("\n== costs are charged, and by holding style ==")
check("intraday styles pay intraday rates",
      engine.STYLE_COST_MODEL["scalp"] == "equity_intraday"
      and engine.STYLE_COST_MODEL["intraday"] == "equity_intraday")
check("swing and positional pay DELIVERY rates (STT both sides)",
      engine.STYLE_COST_MODEL["swing"] == "equity_delivery"
      and engine.STYLE_COST_MODEL["positional"] == "equity_delivery")
check("every style in the catalog has a cost model",
      all(s.style in engine.STYLE_COST_MODEL for s in engine.LONG_CATALOG))
check("slippage is charged", engine.SLIPPAGE_BPS > 0, f"{engine.SLIPPAGE_BPS} bps")

print("\n== the backtest and the paper desk share one decision function ==")
import inspect

src = inspect.getsource(validation.run_backtest)
check("the replay is driven by THIS desk's evaluator", "evaluate_fn=make_evaluator" in src)
check("the paper scan calls the same evaluate_long",
      "evaluate_long(" in inspect.getsource(engine._scan))
check("the entry gate rule exists in exactly one place",
      "ev.assemble(" in inspect.getsource(engine._scan)
      and "def assemble(" in inspect.getsource(evidence))

print("\n== risk controls are real ==")
for name in ("DAILY_LOSS_PCT", "WEEKLY_LOSS_PCT", "MAX_DRAWDOWN_PCT",
             "MAX_CONSECUTIVE_LOSSES", "MAX_POSITIONS_PER_STRATEGY"):
    check(f"{name} configured", getattr(engine, name) > 0, str(getattr(engine, name)))
check("breakers are checked before entries, not after",
      inspect.getsource(engine.run_paper_cycle).index("breaker_state")
      < inspect.getsource(engine.run_paper_cycle).index("_scan(cycle)"))
check("managing happens before scanning",
      inspect.getsource(engine.run_paper_cycle).index("_manage(cycle)")
      < inspect.getsource(engine.run_paper_cycle).index("_scan(cycle)"))

print("\n== the scheduler ==")
for name in ("TICK_SECONDS", "EOD_HHMM", "NEWS_INTERVAL_SECONDS"):
    check(f"scheduler.{name} defined", hasattr(scheduler, name), str(getattr(scheduler, name, None)))
check("three loops exist",
      all(callable(getattr(scheduler, n, None)) for n in
          ("trending_session_loop", "trending_eod_loop", "news_ingest_loop")))

print("\n== bar pipeline ==")
check("only the five intervals Angel actually serves are fetched",
      set(bars.NATIVE) == {"1m", "5m", "15m", "1h", "1d"}, str(sorted(bars.NATIVE)))
check("30m / 45m / 4h are derived, never stored",
      set(bars.DERIVED_FROM) == {"30m", "45m", "4h"}, str(bars.DERIVED_FROM))
check("candle requests are paced", bars.CANDLE_MIN_INTERVAL_S >= 1.0,
      f"{bars.CANDLE_MIN_INTERVAL_S}s between requests")
check("a deviant quote quarantines the symbol",
      bars.MAX_QUOTE_DEVIATION_PCT > 0 and hasattr(basket, "quarantine"))

print("\n== long only, end to end ==")
check("the signal wrapper rejects SELL setups",
      'setup.side != "BUY"' in inspect.getsource(signals.evaluate_long))
check("and records it as its own rejection stage",
      "STAGE_DIRECTION" in inspect.getsource(signals.evaluate_long))
check("positions are opened long", '"side": "BUY"' in inspect.getsource(engine._open)
      and '"direction": "LONG"' in inspect.getsource(engine._open))

print(f"\n{'ALL CHECKS PASSED' if not FAILURES else 'FAILURES: ' + '; '.join(FAILURES)}")
sys.exit(1 if FAILURES else 0)
