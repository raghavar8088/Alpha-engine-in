"""Does a leg report what it CONTROLS, or what it cost? No Mongo, no Angel, no network.

Run:  python backend/tests/commodity_positions/verify_notional.py

WHY THIS EXISTS
---------------
Measured on production 2026-10-08: a 9-lot CRUDEOILM 9000 straddle reported

    Contract exposure  Rs 47,920   "full notional controlled"
    Net premium        Rs 47,920   "received"

— the same number twice, because both were premium x quantity. It controlled
Rs 16,20,000. Understating exposure 34x is bad anywhere; it is worse on the one screen
where someone decides whether a short straddle is safe, and worst on a Rs 66,000 account
where the true leverage was 24.5x.

The fault was that `contract_value(symbol, price, lots)` is only a notional when `price`
IS the underlying's price. For a future it is. For an option the price is the premium.

The numbers below are real: CRUDEOILM at Rs 8,998 and its 9000 strike, read from
production on 2026-10-08.
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


_stub_missing("redis", "redis.asyncio", "fastapi")
if not hasattr(sys.modules["redis.asyncio"], "Redis"):
    sys.modules["redis.asyncio"].Redis = type("Redis", (), {})
    sys.modules["redis.asyncio"].from_url = lambda *a, **k: None

from app.services.commodity_positions import (  # noqa: E402
    SPEC_VALUE_MAX, SPEC_VALUE_MIN, contract_value, multiplier, notional_value,
)

FAILURES: list[str] = []

FUT_PX = 8998.0      # CRUDEOILM future, 2026-10-08
STRIKE = 9000.0
CE_PREM = 264.75
LOTS = 9
MULT = 10            # 10 barrels


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def section(title):
    print(f"\n{title}\n{'-' * len(title)}")


# ── a FUTURE: price IS the underlying, so nothing changes ────────────────────────
section("FUTURE — notional is the quoted price")

fut_notional = notional_value("CRUDEOILM", "FUTURE", FUT_PX, LOTS)
check("a future's notional is price x multiplier x lots",
      fut_notional == FUT_PX * MULT * LOTS, f"Rs {fut_notional:,.0f}")
check("a future is unchanged from contract_value",
      fut_notional == contract_value("CRUDEOILM", FUT_PX, LOTS),
      "the fix must not touch futures")

# ── an OPTION: the premium is the cost, the strike is the obligation ─────────────
section("OPTION — notional is the strike, not the premium")

opt_notional = notional_value("CRUDEOILM", "OPTION", CE_PREM, LOTS, STRIKE)
premium_value = CE_PREM * MULT * LOTS

check("an option's notional is strike x multiplier x lots",
      opt_notional == STRIKE * MULT * LOTS, f"Rs {opt_notional:,.0f}")
check("an option's notional is NOT its premium value",
      opt_notional != premium_value,
      f"notional Rs {opt_notional:,.0f} vs premium Rs {premium_value:,.0f}")
check("the premium understates the notional by more than 10x",
      opt_notional / premium_value > 10, f"{opt_notional / premium_value:.1f}x")
check("the old formula is what premium_value still reports",
      premium_value == contract_value("CRUDEOILM", CE_PREM, LOTS),
      "the useful number is kept, under a name that says which it is")

# A straddle: the exposure the page reports must exceed the margin it reports, which is
# the claim the module's own note makes and which used to be false for options.
section("THE STRADDLE FROM THE SCREENSHOT")

exposure = (notional_value("CRUDEOILM", "OPTION", CE_PREM, LOTS, STRIKE)
            + notional_value("CRUDEOILM", "OPTION", 259.75, LOTS, STRIKE))
net_premium = (CE_PREM + 259.75) * MULT * LOTS
margin_quoted = 65738.0        # measured on production the same day

check("exposure is no longer equal to net premium",
      abs(exposure - net_premium) > 1,
      f"Rs {exposure:,.0f} vs Rs {net_premium:,.0f}")
check("exposure is 'many times the margin', as the module claims",
      exposure > margin_quoted * 10, f"{exposure / margin_quoted:.1f}x")
check("the account's real leverage is visible",
      exposure / 66000 > 20, f"{exposure / 66000:.1f}x on a Rs 66,000 book")

# ── the spec plausibility band ───────────────────────────────────────────────────
section("SPEC BAND — what the gate refuses")

check("COTTONOIL's derived lot value falls outside the band",
      not (SPEC_VALUE_MIN <= 1530.0 * 5 <= SPEC_VALUE_MAX),
      f"Rs {1530.0 * 5:,.0f} against a floor of Rs {SPEC_VALUE_MIN:,.0f}")
check("KAPAS's derived lot value falls outside the band",
      not (SPEC_VALUE_MIN <= 1800.0 * 4 <= SPEC_VALUE_MAX),
      f"Rs {1800.0 * 4:,.0f}")
check("a GOLDPETAL lot stays inside the band",
      SPEC_VALUE_MIN <= 14896.0 * multiplier("GOLDPETAL") <= SPEC_VALUE_MAX,
      "the smallest real MCX contract must not be blocked")
check("a GOLD kilo bar stays inside the band",
      SPEC_VALUE_MIN <= 149170.0 * multiplier("GOLD") <= SPEC_VALUE_MAX,
      f"Rs {149170.0 * multiplier('GOLD'):,.0f} — the largest must not be blocked either")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    raise SystemExit(1)
print("all checks passed")
