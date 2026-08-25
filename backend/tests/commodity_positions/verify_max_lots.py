"""Does auto-sizing return a size the account can actually carry?

Read-only: `max_lots` never writes, so this runs against the live paper book safely.

Two things must hold, and the first is the one that matters:

  1. The fast search agrees with the REAL margin path. `max_lots` hoists the reference
     price and open legs out of the loop and scales quantities locally, so it no longer
     goes through `basket_margin_delta`. If the two ever disagree, the sizer is quoting a
     number the order gate will not honour, and the "Max" button becomes a trap.

  2. The answer is the true boundary: N fits, N+1 does not.

Run: python -m tests.commodity_positions.verify_max_lots
"""
import asyncio
import sys

from app.services.commodity_positions import (
    _price_basket,
    available_cash,
    basket_margin_delta,
    list_accounts,
    max_lots,
    option_chain,
    option_expiries,
    prime_lotsizes,
)

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


async def straddle_legs(symbol: str) -> tuple[list[dict], str, float] | None:
    """The ATM strike of the nearest expiry, as a short straddle."""
    expiries = await option_expiries(symbol)
    if not expiries:
        return None
    expiry = expiries[0]
    chain = await option_chain(symbol, expiry)
    rows = chain.get("strikes") or []
    if not rows:
        return None
    # The ATM strike, chosen the same way the page does: nearest the underlying FUTURE,
    # which is what the chain is priced against. MCX does not quote a spot intraday.
    spot = float(chain["spot"])
    strike = float(min(rows, key=lambda r: abs(float(r["strike"]) - spot))["strike"])
    legs = [{"instrument_kind": "OPTION", "symbol": symbol, "expiry": expiry,
             "strike": strike, "option_type": ot, "transaction_type": "SELL", "lots": 1}
            for ot in ("CE", "PE")]
    return legs, expiry, strike


async def go() -> None:
    await prime_lotsizes()
    accounts = await list_accounts()
    if not accounts:
        print("no paper accounts; nothing to verify")
        return
    # Both ends of the range. The tightest book exercises the refusal boundary — the
    # largest size that still fits, and the honest zero when nothing does. The roomiest
    # exercises the search itself: it has to walk down from the cap and land on a real
    # number, which a book that cannot afford one lot never tests.
    by_cash = sorted([(await available_cash(a["account_id"]), a) for a in accounts],
                     key=lambda t: t[0])
    picks = [("tightest", *next(((c, a) for c, a in by_cash if c > 0), by_cash[-1]))]
    if by_cash[-1][1] is not picks[0][2]:
        picks.append(("roomiest", by_cash[-1][0], by_cash[-1][1]))

    for role, cash, account in picks:
        print("=" * 64)
        print(f"{role}: {account['name']}  free cash Rs{cash:,.0f}")
        print()
        await run_book(account["account_id"])


async def run_book(aid: str) -> None:
    for symbol in ("CRUDEOILM", "NATGASMINI", "GOLDM"):
        built = await straddle_legs(symbol)
        if not built:
            print(f"{symbol}: no option chain, skipped\n")
            continue
        legs, expiry, strike = built
        print(f"{symbol} {expiry} {strike:g} short straddle")

        res = await max_lots(aid, legs)
        n = res["max_lots"]
        print(f"  max_lots -> {n} lots, margin Rs{res['margin']:,.0f} "
              f"of Rs{res['available_cash']:,.0f}")
        print(f"  reason: {res['reason']}")

        if n == 0:
            check(f"{symbol}: zero is honest", res["margin"] > res["available_cash"],
                  f"one lot Rs{res['margin']:,.0f} > cash Rs{res['available_cash']:,.0f}")
            print()
            continue

        # 1. the fast local search must match the real gate, at the size it returns
        real, _prem = await basket_margin_delta(
            aid, await _price_basket([{**leg, "lots": n} for leg in legs]))
        drift = abs(real - res["margin"])
        check(f"{symbol}: sizer agrees with the real margin path at {n} lots",
              drift <= max(1.0, real * 0.005),
              f"sizer Rs{res['margin']:,.0f} vs gate Rs{real:,.0f} (drift Rs{drift:,.2f})")

        # 2. N must fit and N+1 must not — the true boundary, not a safe under-estimate
        check(f"{symbol}: {n} lots fits", real <= res["available_cash"] + 0.01,
              f"Rs{real:,.0f} <= Rs{res['available_cash']:,.0f}")

        # N+1 must fail — judged at the prices the sizer itself used. Re-fetching quotes
        # to test this compares two snapshots: the natural gas straddle sizes to within
        # Rs545 of a Rs30L book, which is 0.018%, so a tick between the two calls flips the
        # answer and the test fails on market noise rather than on a defect.
        nxt = res.get("margin_at_next")
        if nxt is not None:
            check(f"{symbol}: {n + 1} lots does NOT fit",
                  nxt > res["available_cash"] + 0.01,
                  f"Rs{nxt:,.0f} > Rs{res['available_cash']:,.0f}")

        # 3. a straddle must not be margined as both sides added together
        naive = res["margin_per_lot"] * n
        check(f"{symbol}: margin is netted, not multiplied out",
              res["margin"] <= naive * 1.05,
              f"Rs{res['margin']:,.0f} vs Rs{naive:,.0f} if scaled linearly")
        print()


async def main() -> None:
    await go()
    print("=" * 64)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("all auto-sizing checks passed")


asyncio.run(main())
