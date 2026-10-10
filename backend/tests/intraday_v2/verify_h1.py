"""H1: is the order-book measurement right, and is its rule really frozen?

Run:  python backend/tests/intraday_v2/verify_h1.py

No Mongo, no Angel, no network. What is tested:
- the book walk prices a Rs 10 lakh order the way a market order would actually fill;
- costs are signed so a cost is positive on both sides;
- the pre-registered rule decides GO / NO-GO / COLLECTING exactly as written;
- the rule is stored once, before the first sample, and a later code change cannot alter it;
- a measurement failure can never reach the trading engine.
"""

import asyncio
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "instrument_search"))
for p in ("broker-clients", "shared", "backtesting-service"):
    sys.path.insert(0, str(ROOT / p))
from _stub_infra import stub_infra  # noqa: E402

stub_infra()
for name in ("redis", "redis.asyncio"):
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            root = name.split(".")[0]
            mod = sys.modules.get(root) or types.ModuleType(root)
            sys.modules[root] = mod
            if "." in name:
                sub = types.ModuleType(name)
                setattr(mod, name.split(".")[1], sub)
                sys.modules[name] = sub

import app.services.angel_client as AC  # noqa: E402
import app.services.h1_slippage as H  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
FAILURES: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -- ' + str(detail)) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def section(t):
    print(f"\n{t}\n{'-' * len(t)}")


def close(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol


class Coll:
    def __init__(self):
        self.docs = []

    async def find_one(self, q):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    async def insert_one(self, d):
        if any(x.get("_id") == d.get("_id") for x in self.docs if "_id" in d):
            raise RuntimeError("duplicate _id")
        self.docs.append(dict(d))

    def find(self, q, projection=None):
        docs = [dict(d) for d in self.docs if all(d.get(k) == v for k, v in q.items())]

        class _C:
            def __aiter__(self_inner):
                async def gen():
                    for d in docs:
                        yield d
                return gen()
        return _C()

    async def count_documents(self, q):
        return sum(1 for d in self.docs if all(d.get(k) == v for k, v in q.items()))


def fresh():
    H.samples, H.meta = Coll(), Coll()
    H._registered = False


# ═════════════════════════════════════════════════════════════════════════════════
section("THE BOOK WALK")

asks = [[100.05, 2000], [100.10, 3000], [100.20, 10000]]
bids = [[99.95, 2500], [99.90, 4000], [99.80, 10000]]
vw, got = H.walk_book(asks, 4000)
check("a walk takes each level in turn", got == 4000 and close(vw, (2000 * 100.05 + 2000 * 100.10) / 4000), vw)
vw, got = H.walk_book(asks, 100)
check("a small order fills at the best level", close(vw, 100.05) and got == 100)

c = H.cost_of("BUY", 1_000_000, 100.0, bids, asks)
shares = 10000
exp_vwap = (2000 * 100.05 + 3000 * 100.10 + 5000 * 100.20) / shares
check("a Rs 10 lakh BUY sizes to notional / LTP", c["shares"] == shares, c["shares"])
check("…and walks the ASKS", close(c["vwap"], round(exp_vwap, 4), 1e-3), c["vwap"])
check("…its cost vs LTP is positive", c["cost_bp_vs_ltp"] > 0, c["cost_bp_vs_ltp"])
check("…and equals (vwap - ltp) / ltp in bp",
      close(c["cost_bp_vs_ltp"], round((exp_vwap - 100.0) / 100.0 * 1e4, 3), 1e-3))
s = H.cost_of("SELL", 1_000_000, 100.0, bids, asks)
check("a SELL walks the BIDS, and its cost is positive too", s["cost_bp_vs_ltp"] > 0, s["cost_bp_vs_ltp"])
check("the half-spread is measured off the best levels",
      close(c["half_spread_bp"], round((100.05 - 99.95) / 2 / 100.0 * 1e4, 3), 1e-3), c["half_spread_bp"])

thin = H.cost_of("BUY", 1_000_000, 100.0, bids, [[100.05, 1000], [100.10, 1000]])
check("a book too thin to fill is FLAGGED", thin["insufficient_depth"] is True and thin["depth_covered_pct"] == 20.0)
check("…and priced at its best case (the rest at the worst visible level)",
      close(thin["vwap"], round((1000 * 100.05 + 9000 * 100.10) / 10000, 4), 1e-3))
check("no book, no price", H.cost_of("BUY", 1_000_000, 100.0, bids, []) is None)
check("no LTP, no price", H.cost_of("BUY", 1_000_000, 0, bids, asks) is None)
# The last trade printed above where the book now sits (the price fell after it): the order
# fills BELOW that stale LTP, and the record shows a negative cost rather than hiding it.
stale = H.cost_of("BUY", 1_000_000, 100.30, bids, asks)
check("an LTP printed above the current book gives a negative cost — recorded, not hidden",
      stale["cost_bp_vs_ltp"] < 0 and stale["cost_bp_vs_mid"] > 0,
      f"{stale['cost_bp_vs_ltp']} vs LTP, {stale['cost_bp_vs_mid']} vs mid")

# ═════════════════════════════════════════════════════════════════════════════════
section("THE PRE-REGISTERED RULE")

rule = H.PREREGISTRATION
be = 1.50
check("below the minimum sample: COLLECTING, whatever the median",
      H.verdict([0.1] * 99, 0, rule, be)["status"] == "COLLECTING")
check("median at 80% of break-even: GO", H.verdict([1.20] * 100, 0, rule, be)["status"] == "GO")
check("median just above it: NO-GO", H.verdict([1.21] * 100, 0, rule, be)["status"] == "NO-GO")
check("a cheap median does not pass when >10% of the book was too thin",
      H.verdict([0.5] * 100, 11, rule, be)["status"] == "NO-GO")
check("…and 10% exactly is still allowed", H.verdict([0.5] * 100, 10, rule, be)["status"] == "GO")
v = H.verdict([1.0, 2.0, 3.0], 0, rule, be)
check("the median is the median", v["median_bp"] == 2.0 and v["progress_pct"] == 3.0, v)
check("the three strategies and their break-evens are the plan's",
      H.H1_STRATEGIES == {"iv2_donchian_45m": 1.80, "iv2_donchian_1h": 1.50, "iv2_vwap_trend_1h": 1.29})

# ═════════════════════════════════════════════════════════════════════════════════
section("STORED ONCE, BEFORE THE FIRST SAMPLE, NEVER EDITED")

fresh()
r1 = asyncio.run(H.ensure_preregistered())
check("the rule is stored with a fingerprint", r1["stored"] and r1["fingerprint"])
r2 = asyncio.run(H.ensure_preregistered())
check("a second call stores nothing", r2["stored"] is False and len(H.meta.docs) == 1)

H.meta.docs[0]["doc"] = {**H.PREREGISTRATION, "min_samples_per_strategy": 50,
                         "go_fraction_of_break_even": 0.5}
H.meta.docs[0]["fingerprint"] = "storedrule0000"
rep = asyncio.run(H.report())
check("if the code's rule drifts from the stored one, the report says so",
      rep["code_matches_stored"] is False)
check("…and the STORED rule governs the verdict",
      rep["strategies"]["iv2_donchian_1h"]["threshold_bp"] == 0.75, rep["strategies"]["iv2_donchian_1h"])


class FakeAngel:
    def __init__(self, book=None, fail=False):
        self.book, self.fail, self.calls = book or {}, fail, 0

    async def full_quote(self, payload):
        self.calls += 1
        if self.fail:
            raise RuntimeError("403 access rate")
        return self.book

    async def place_order(self, **kw):
        raise AssertionError("H1 must never place an order")


fresh()
AC.angel_client = FakeAngel({"11": {"ltp": 100.0, "depth_buy": bids, "depth_sell": asks}})
n = asyncio.run(H.capture([
    {"strategy_id": "iv2_donchian_1h", "symbol": "ABC", "token": "11", "side": "BUY",
     "phase": "entry", "ltp": 100.0, "signal_at": datetime.now(timezone.utc)},
    {"strategy_id": "iv2_rsi2_15m", "symbol": "ABC", "token": "11", "side": "BUY",
     "phase": "entry", "ltp": 100.0, "signal_at": datetime.now(timezone.utc)}]))
check("only the three pre-registered strategies are measured", n == 1 and len(H.samples.docs) == 1)
check("the rule was stored BEFORE that first sample", len(H.meta.docs) == 1)
smp = H.samples.docs[0]
check("the sample carries the walk, the side and the timing",
      smp["measurable"] and smp["side"] == "BUY" and smp["lag_s"] is not None and smp["shares"] == 10000)

fresh()
AC.angel_client = FakeAngel({"11": {"ltp": 100.0, "depth_buy": [], "depth_sell": []}})
asyncio.run(H.capture([{"strategy_id": "iv2_donchian_45m", "symbol": "ABC", "token": "11",
                        "side": "SELL", "phase": "entry", "ltp": 100.0}]))
check("an empty book is stored as unmeasurable, not skipped silently",
      H.samples.docs and H.samples.docs[0]["measurable"] is False)

fresh()
AC.angel_client = FakeAngel(fail=True)
try:
    n = asyncio.run(H.capture([{"strategy_id": "iv2_donchian_45m", "symbol": "ABC", "token": "11",
                                "side": "SELL", "phase": "entry", "ltp": 100.0}]))
    check("a failed book read never raises into the engine", n == 0)
except Exception as exc:  # noqa: BLE001
    check("a failed book read never raises into the engine", False, exc)

ran = []


async def _sched_probe():
    H.capture = lambda items: _rec(items)
    H.schedule([{"strategy_id": "iv2_rsi2_15m", "token": "1"}])
    H.schedule([{"strategy_id": "iv2_donchian_1h", "token": "1"}])
    await asyncio.sleep(0.01)


async def _rec(items):
    ran.append(items)


asyncio.run(_sched_probe())
check("schedule() ignores signals of untested strategies, and runs the rest off the engine's path",
      len(ran) == 1 and ran[0][0]["strategy_id"] == "iv2_donchian_1h")

src = (ROOT / "backend/app/services/intraday_v2_engine.py").read_text(encoding="utf-8")
check("the tournament measures every H1 signal at the decision, taken or not",
      "h1.schedule([{\"strategy_id\": spec.strategy_id" in src and "for _p, spec, sym, sig in cands" in src)
check("…and its market exits", "\"phase\": \"exit\"" in src)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    raise SystemExit(1)
print("all checks passed")
