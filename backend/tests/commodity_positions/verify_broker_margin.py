"""Does the margin path charge what the broker charges, and refuse what it should?

Run:  python backend/tests/commodity_positions/verify_broker_margin.py

No Mongo, no Angel, no network. The broker call is stubbed so the DECISIONS can be tested
— which answers are believed, which are refused, and what is used instead — without
depending on a live endpoint that is rate-limited and that this test must not spend.

WHY THIS EXISTS
---------------
Measured on production 2026-10-09, a Rs 66,000 account sizing a 1-lot CRUDEOILM 8750
short straddle was told it could carry 8 lots. The broker allows 1.

    local SPAN-lite   Rs  7,347 a lot
    Angel One app     Rs 60,603 a lot      8.2x

The model was wrong twice over: price-scan bands calibrated on NIFTY and never re-measured
against MCX, and a "hedge benefit" on a short straddle that SPAN does not give. Both of
those were invisible on the screen, which is why `margin_source` is now part of every
payload and why the numbers below are real measurements rather than round figures.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "instrument_search"))
from _stub_infra import stub_infra  # noqa: E402

stub_infra()


def _stub_missing(*names: str) -> None:
    """Neutralise import-time third-party deps this test never exercises."""
    import types
    for name in names:
        if name in sys.modules:
            continue
        try:
            __import__(name)
        except ImportError:
            root = name.split(".")[0]
            mod = sys.modules.get(root) or types.ModuleType(root)
            sys.modules[root] = mod
            cur = mod
            for part in name.split(".")[1:]:
                sub = types.ModuleType(f"{cur.__name__}.{part}")
                setattr(cur, part, sub)
                sys.modules[sub.__name__] = sub
                cur = sub


_stub_missing("redis", "redis.asyncio", "fastapi", "httpx")
if not hasattr(sys.modules["redis.asyncio"], "Redis"):
    sys.modules["redis.asyncio"].Redis = type("Redis", (), {})
    sys.modules["redis.asyncio"].from_url = lambda *a, **k: None

import asyncio  # noqa: E402

from app.services import commodity_broker_margin as BM  # noqa: E402

FAILURES: list[str] = []

# Real figures, CRUDEOILM 8750 strike, 2026-10-09.
STRIKE_NOTIONAL = 87_500.0          # 8750 x 10 barrels
BROKER_STRADDLE = 60_499.0          # Angel's calculator; the app showed 60,603
BROKER_ONE_SHORT = 30_805.0
OLD_MODEL_STRADDLE = 7_347.0        # what SPAN-lite charged


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def section(title):
    print(f"\n{title}\n{'-' * len(title)}")


def leg(kind="OPTION", side="SELL", lots=1, notional=STRIKE_NOTIONAL,
        token="580776", order_qty=10, family="CRUDEOIL", product="MARGIN"):
    return {"symbol": "CRUDEOILM", "family": family, "kind": kind, "side": side,
            "lots": lots, "notional": notional, "token": token,
            "order_qty": order_qty, "product": product}


# ── the measured table ───────────────────────────────────────────────────────────
section("MEASURED RATES — all in the band the broker was actually seen to charge")

for fam, rate in sorted(BM.MEASURED_RATE.items()):
    check(f"{fam} at {rate:.1%} is between 5% and 35%", 0.05 <= rate <= 0.35)
check("a sold option costs MORE than a future, never less",
      BM.SHORT_OPTION_FACTOR > 1.0, f"x{BM.SHORT_OPTION_FACTOR}")
check("the short-option factor is past the top of the measured 1.13-1.19 range",
      BM.SHORT_OPTION_FACTOR >= 1.19,
      f"x{BM.SHORT_OPTION_FACTOR} — a fallback must err expensive")
check("an unmeasured contract costs more than most measured ones, not less",
      BM.DEFAULT_RATE >= sorted(BM.MEASURED_RATE.values())[len(BM.MEASURED_RATE) // 2],
      f"{BM.DEFAULT_RATE:.1%} default")

# ── the fallback's shape must match the broker's ─────────────────────────────────
section("THE FALLBACK HAS THE SAME SHAPE AS THE BROKER")

one = BM.fallback_margin([leg()])
check("linear in lots: 9 lots costs 9x one lot",
      abs(BM.fallback_margin([leg()], 9) - 9 * one) < 0.01,
      f"Rs {one:,.0f} -> Rs {BM.fallback_margin([leg()], 9):,.0f}")
check("linear whether size is in `lots` or the multiplier argument",
      abs(BM.fallback_margin([leg(lots=4)]) - BM.fallback_margin([leg()], 4)) < 0.01)

straddle = [leg(side="SELL"), leg(side="SELL")]
check("additive across legs — a straddle gets NO netting benefit",
      abs(BM.fallback_margin(straddle) - 2 * one) < 0.01,
      "the broker charged 30,805 + 29,694 = 60,499 exactly")
check("a straddle is not cheaper than one leg, as the old model claimed",
      BM.fallback_margin(straddle) > one,
      f"Rs {BM.fallback_margin(straddle):,.0f} vs Rs {one:,.0f}")

check("a BOUGHT option costs no margin at all",
      BM.fallback_margin([leg(side="BUY")]) == 0.0,
      "the premium is paid up front")
check("a bought leg does not discount a sold one in the same basket",
      BM.fallback_margin([leg(side="SELL"), leg(side="BUY")]) == BM.fallback_margin([leg()]),
      "the broker's vertical-spread benefit was 1.8%, which is not credited here")
check("a LONG future still costs margin",
      BM.fallback_margin([leg(kind="FUTURE", side="BUY")]) > 0)

# ── and it must land near the broker, erring expensive ───────────────────────────
section("THE FALLBACK IS CLOSE TO THE BROKER, ON THE SAFE SIDE")

fb = BM.fallback_margin(straddle)
print(f"  broker Rs {BROKER_STRADDLE:,.0f}   fallback Rs {fb:,.0f}   "
      f"old model Rs {OLD_MODEL_STRADDLE:,.0f}")
check("within 15% of the broker's own figure",
      abs(fb - BROKER_STRADDLE) / BROKER_STRADDLE < 0.15,
      f"{(fb - BROKER_STRADDLE) / BROKER_STRADDLE * +100:+.1f}%")
check("and on the EXPENSIVE side of it", fb >= BROKER_STRADDLE,
      "a cheap fallback lets through an order the account cannot carry")
check("nowhere near the 8.2x-light model it replaced",
      fb > OLD_MODEL_STRADDLE * 7, f"{fb / OLD_MODEL_STRADDLE:.1f}x the old figure")

# ── the broker's QUANTITY is the lotsize, not the multiplier ─────────────────────
section("THE REQUEST COUNTS IN THE BROKER'S OWN UNITS")

pos = BM._angel_positions([leg(order_qty=1, notional=15_082_500.0)], 1)   # a GOLD lot
check("qty is the broker's order unit, not the value multiplier",
      pos[0]["qty"] == 1,
      "GOLD trades in lots of 1 though a lot is worth 100x the quoted 10g price")
check("lots multiply the order quantity",
      BM._angel_positions([leg(order_qty=10, lots=3)], 1)[0]["qty"] == 30)
check("the outer `lots` argument multiplies it too",
      BM._angel_positions([leg(order_qty=10)], 5)[0]["qty"] == 50)
check("orderType is always sent — without it the call is rejected outright",
      pos[0]["orderType"] == "MARKET")
check("MARGIN maps to the broker's CARRYFORWARD",
      BM._angel_positions([leg(product="MARGIN")], 1)[0]["productType"] == "CARRYFORWARD")
check("INTRADAY stays INTRADAY",
      BM._angel_positions([leg(product="INTRADAY")], 1)[0]["productType"] == "INTRADAY")
check("a leg with no token makes the WHOLE basket decline, not part of it",
      BM._angel_positions([leg(), leg(token=None)], 1) is None,
      "a basket half-priced from the broker is neither source")
check("so does a leg with no lotsize",
      BM._angel_positions([leg(order_qty=None)], 1) is None)

# ── which answers are believed ───────────────────────────────────────────────────
section("WHAT THE BROKER SAYS IS NOT ALWAYS BELIEVED")

check("a basket of bought options alone could legitimately need nothing",
      not BM._needs_margin([leg(side="BUY"), leg(side="BUY")]))
check("but one sold option means it must cost something",
      BM._needs_margin([leg(side="BUY"), leg(side="SELL")]))
check("and so does a future, bought or sold",
      BM._needs_margin([leg(kind="FUTURE", side="BUY")])
      and BM._needs_margin([leg(kind="FUTURE", side="SELL")]))

zero = BM._implausible(0.0, straddle, fb)
check("zero on a basket that must cost something is refused as a throttle",
      zero is not None and zero[0] == "throttled",
      "Angel answers 200 OK with 0 when rate-limited")

futs = [leg(kind="FUTURE", side="BUY", notional=87_550.0)]
local_fut = BM.fallback_margin(futs)
low = BM._implausible(1_105.0, futs, local_fut)
check("the CRUDEOILM futures figure (1.3% of notional) is refused",
      low is not None and low[0] == "below-floor",
      f"Rs 1,105 against a measured Rs {local_fut:,.0f}")
check("a plausible futures figure is believed",
      BM._implausible(27_000.0, futs, local_fut) is None,
      f"Rs 27,000 against a measured Rs {local_fut:,.0f}")

check("a CHEAP OPTION figure is NOT floored — a far OTM short really is cheap",
      BM._implausible(900.0, straddle, fb) is None,
      "only the broker's option figures reproduced the app exactly, so they are trusted")
check("an EXPENSIVE figure is always passed through",
      BM._implausible(fb * 5, straddle, fb) is None,
      "too much margin is conservative, never dangerous")

# ── the whole path, with the broker stubbed ──────────────────────────────────────
section("END TO END, WITH THE BROKER STUBBED")


class Stub:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    async def margin_batch(self, positions):
        self.calls.append(positions)
        got = self.answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got


def run(answers, legs, lots=1):
    BM.invalidate_margin_cache()
    stub = Stub(answers)
    real, BM.angel_client = BM.angel_client, stub
    try:
        return asyncio.run(BM.basket_margin(legs, lots)), stub
    finally:
        BM.angel_client = real


(m, src, _n), stub = run([BROKER_STRADDLE], straddle)
check("the broker's figure is used and labelled as the broker's",
      m == BROKER_STRADDLE and src == "angel", f"Rs {m:,.0f} source={src}")
check("one call for the whole basket, not one per leg", len(stub.calls) == 1,
      f"{len(stub.calls)} call(s) for {len(straddle)} legs")
check("both legs were in that one call", len(stub.calls[0]) == 2)

(m, src, _n), stub = run([], [leg(side="BUY"), leg(side="BUY")])
check("an all-bought basket answers 0 without asking",
      m == 0.0 and src == "angel" and not stub.calls,
      "a long option is genuinely free, and needs no round trip")

(m, src, note), stub = run([0.0], straddle)
check("a throttled zero falls back to the measured rate",
      m == fb and src == "measured:throttled", f"Rs {m:,.0f} source={src}")

(m, src, note), stub = run([RuntimeError("boom")], straddle)
check("ANY broker exception falls back rather than failing the order gate",
      m == fb and src == "measured:broker-unavailable", f"source={src}")

(m, src, note), stub = run([1_105.0], futs)
check("an unbelievable futures figure falls back, and says why",
      m == local_fut and src == "measured:below-floor" and "CRUDEOILM" in note,
      f"source={src}")

(m, src, note), stub = run([], [leg(), leg(token=None)])
check("an unmapped leg falls back without calling",
      src == "measured:unmapped" and not stub.calls, f"source={src}")

BM.invalidate_margin_cache()
stub = Stub([BROKER_STRADDLE])
real, BM.angel_client = BM.angel_client, stub
try:
    first = asyncio.run(BM.basket_margin(straddle, 1))
    second = asyncio.run(BM.basket_margin(straddle, 1))
finally:
    BM.angel_client = real
check("the same question twice costs one call",
      first[0] == second[0] and len(stub.calls) == 1,
      f"{len(stub.calls)} call(s) — the endpoint's budget is tiny")
check("a DIFFERENT size is a different question",
      BM._cache_key(straddle, 1) != BM._cache_key(straddle, 2))
check("a different SIDE is a different question",
      BM._cache_key([leg(side="SELL")], 1) != BM._cache_key([leg(side="BUY")], 1))
check("leg order does not change the question",
      BM._cache_key([leg(token="a"), leg(token="b")], 1)
      == BM._cache_key([leg(token="b"), leg(token="a")], 1))

# ── sizing arithmetic ────────────────────────────────────────────────────────────
section("WHAT THIS MEANS FOR max_lots ON THE Rs 66,000 ACCOUNT")

cash = 66_000.0
old_n = int(cash // OLD_MODEL_STRADDLE)
new_n = int(cash // BROKER_STRADDLE)
print(f"  old model: floor({cash:,.0f} / {OLD_MODEL_STRADDLE:,.0f}) = {old_n} lots")
print(f"  broker   : floor({cash:,.0f} / {BROKER_STRADDLE:,.0f}) = {new_n} lot")
check("the broker's figure gives 1 lot", new_n == 1)
check("the old model gave the 8 that was reported", old_n == 8,
      "which is the number on the screen the user queried")
check("one lot of this straddle is most of a Rs 66,000 book",
      BROKER_STRADDLE / cash > 0.9, f"{BROKER_STRADDLE / cash:.0%} of it")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    raise SystemExit(1)
print("all checks passed")
