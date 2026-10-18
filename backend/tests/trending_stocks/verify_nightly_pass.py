"""Verify the Trending Stocks nightly pass completes, and runs once a day — without Mongo or Angel.

Run:  python backend/tests/trending_stocks/verify_nightly_pass.py

What this pins down (both found in production on 2026-10-18):

  * The end-of-sweep state write encodes as BSON. Its grade histogram was keyed by the grade
    INTEGER, and Mongo refuses non-string keys: the write raised "documents must have only
    string keys" every trading night since the module shipped (2026-08-21). The pass then
    re-ran every 20 minutes until one found nothing left to sweep — an EMPTY histogram encodes
    — so each night paid two or three full passes and recorded an empty grade histogram.
  * A pass that fails is retried TOMORROW, as its log line says. The date was only recorded on
    success, so a failure re-ran the whole pass (a candle refresh of the basket from Angel, then
    the sweep) every 20 minutes until midnight.
"""

import asyncio
import os
import sys
import types
from pathlib import Path

# Never the real cluster: the local settings point at PRODUCTION Atlas. Any collection this
# test forgets to fake fails fast against a dead port instead of writing to it.
os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "shared"))      # the repo's shared package, not a stale install
sys.path.insert(0, str(ROOT))

import bson  # noqa: E402

from app.services.trending_stocks import bars as BARS  # noqa: E402
from app.services.trending_stocks import basket as BASKET  # noqa: E402
from app.services.trending_stocks import engine as E  # noqa: E402
from app.services.trending_stocks import scheduler as S  # noqa: E402

FAILURES: list[str] = []


def check(label: str, ok: bool, detail="") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -- ' + str(detail)) if detail not in ('', None) else ''}")
    if not ok:
        FAILURES.append(label)


class FakeColl:
    """Encodes every $set the way the driver would, so a non-string key fails HERE."""

    def __init__(self) -> None:
        self.updates: list[tuple[dict, dict]] = []

    def find(self, *a, **k):
        class _Cursor:
            def __aiter__(self):
                async def gen():
                    return
                    yield                                   # an empty async generator
                return gen()
        return _Cursor()

    async def update_one(self, q, upd, upsert=False):
        bson.encode(upd.get("$set") or {})
        self.updates.append((q, upd))
        return types.SimpleNamespace(modified_count=1)


print("\nNIGHTLY PASS — the sweep's state write is valid BSON")
print("-" * 60)

METRIC_KEYS = ("trades", "wins", "win_rate", "net_pnl", "gross_profit", "gross_loss", "total_costs",
               "profit_factor", "expectancy", "avg_r", "max_drawdown_pct", "return_pct", "cagr_pct",
               "sharpe", "sortino", "largest_win", "largest_loss", "max_consecutive_wins",
               "max_consecutive_losses", "exposure_pct")
metrics = types.SimpleNamespace(**dict.fromkeys(METRIC_KEYS, 0))
strategies = [types.SimpleNamespace(strategy_id=f"s{k}", name=f"S{k}", family="f", sub_family="sf",
                                    timeframe="1d", htf=None, style="swing", hypothesis="h", detector="d",
                                    target_r=2.0, regimes={"bull"}, min_bars=10) for k in (1, 2, 3)]
result = types.SimpleNamespace(rejections={"rr": 1}, overall=metrics, in_sample=metrics, out_of_sample=metrics,
                               grade=3, grade_reasons=[], bars_tested=100, span_days=200, equity_curve=[1.0, 2.0])


async def _basket():
    return {"TITAN": {}, "VEDL": {}}


async def _bars(sym, tf, limit):
    return list(range(100))


async def _noop(*a, **k):
    return None


E.basket = types.SimpleNamespace(active=_basket)
E.bar_store = types.SimpleNamespace(load_bars=_bars, load_benchmark=_bars)
E.LONG_CATALOG = strategies
E.needs_benchmark = lambda s: False
E.cost_model_for = lambda s: "equity_delivery"
E.run_backtest = lambda *a, **k: result
grades = iter([3, 1, 3, 4, 1, 3])
E.extended_grade = lambda *a: (next(grades), [], "graded")
E._refresh_scores = _noop
E.ts_backtests_collection = FakeColl()
E.ts_state_collection = FakeColl()

try:
    out = asyncio.run(E.run_backtests())
    err = None
except Exception as exc:  # noqa: BLE001
    out, err = None, exc
check("a sweep over 2 symbols x 3 strategies completes (the state write no longer raises)", err is None, err)
state = E.ts_state_collection.updates[-1][1]["$set"] if E.ts_state_collection.updates else {}
check("the stored grade histogram is keyed by strings: {'1': 2, '3': 3, '4': 1}",
      state.get("grade_histogram") == {"1": 2, "3": 3, "4": 1}, state.get("grade_histogram"))
check("every backtest row was written (6)", len(E.ts_backtests_collection.updates) == 6,
      len(E.ts_backtests_collection.updates))

print("\nNIGHTLY LOOP — a failed pass is retried tomorrow, not every 20 minutes")
print("-" * 60)

runs: list[int] = []


async def failing_sweep(*a, **k):
    runs.append(1)
    raise RuntimeError("boom")


async def _on(key):
    return True


async def _refresh(*a, **k):
    return {"symbols": {}}


class Stop(Exception):
    pass


sleeps = {"n": 0}


async def fake_sleep(seconds):
    sleeps["n"] += 1
    if sleeps["n"] >= 4:
        raise Stop


from app.services import desk_switches as DS  # noqa: E402

real = (E.run_backtests, DS.is_on, BASKET.active, BARS.refresh_many, S._due, S.asyncio)
E.run_backtests = failing_sweep
DS.is_on = _on
BASKET.active = _basket
BARS.refresh_many = _refresh
S._due = lambda now, last: last != now.date()           # due whenever it has not run today
S.asyncio = types.SimpleNamespace(sleep=fake_sleep)
try:
    asyncio.run(S.trending_eod_loop())
except Stop:
    pass
finally:
    E.run_backtests, DS.is_on, BASKET.active, BARS.refresh_many, S._due, S.asyncio = real
check("four checks of the clock, one failed pass: it waits for tomorrow", runs == [1], runs)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("all checks passed")
