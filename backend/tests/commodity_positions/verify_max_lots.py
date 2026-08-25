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
    rows = [r for r in chain["rows"] if r.get("atm")] or chain["rows"]
    if not rows:
        return None
    strike = float(rows[0]["strike"])
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
    account = accounts[0]
    aid = account["account_id"]
    cash = await available_cash(aid)
    print(f"account: {account['name']}  free cash Rs{cash:,.0f}\n")

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

        if n < 500:
            over, _p = await basket_margin_delta(
                aid, await _price_basket([{**leg, "lots": n + 1} for leg in legs]))
            check(f"{symbol}: {n + 1} lots does NOT fit",
                  over > res["available_cash"] + 0.01,
                  f"Rs{over:,.0f} > Rs{res['available_cash']:,.0f}")

        # 3. a straddle must not be margined as both sides added together
        naive = res["margin_per_lot"] * n
        check(f"{symbol}: margin is netted, not multiplied out",
              res["margin"] <= naive * 1.05,
              f"Rs{res['margin']:,.0f} vs Rs{naive:,.0f} if scaled linearly")
        print()

    print("=" * 62)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("all auto-sizing checks passed")


asyncio.run(go())
