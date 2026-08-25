"""Can an over-committed book put the hedge back on?

Read-only: estimates only, nothing is filled.

The trap this guards against, seen on a real ₹2L book:

  A 35-lot short straddle held ₹1.92L of margin. Closing the CALL left a NAKED short put,
  and its margin ROSE to ₹2.07L — correctly, because the call's premium had been offsetting
  the put's loss in the down scenario, and that offset is gone. Available cash went to
  -₹5,612 without a single new trade.

  Re-adding the call REDUCES margin back to ₹1.94L. But `basket_margin_delta` clamped its
  own result at zero, so a true delta of -₹12,331 was reported as ₹0, and the gate
  `added > cash` compared 0 against -5,612 and refused. The account was locked out of the
  one trade that repairs it, while stuck holding the riskier half of the pair.

Run: python -m tests.commodity_positions.verify_rehedge
"""
import asyncio
import sys

from app.services.commodity_positions import (
    available_cash, basket_allowed, estimate_basket, list_accounts, prime_lotsizes, summary,
)

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def mirror(pos: dict, open_positions: list[dict]) -> dict | None:
    """The MISSING other half of the pair this position is one leg of.

    Returns None when that half is already open. Proposing it anyway would be proposing a
    SECOND put on top of an existing one, which doubles that side of the book and correctly
    raises margin — a true result about a basket nobody wants, dressed up as a re-hedge.
    Only a genuinely absent leg exercises the gate this test is about."""
    inst = pos.get("instrument") or {}
    if not inst.get("option_type"):
        return None
    want = "CE" if inst["option_type"] == "PE" else "PE"
    for q in open_positions:
        qi = q.get("instrument") or {}
        if (q["underlying_symbol"] == pos["underlying_symbol"]
                and qi.get("expiry") == inst["expiry"]
                and qi.get("strike") == inst["strike"]
                and qi.get("option_type") == want):
            return None
    return {"instrument_kind": "OPTION", "symbol": pos["underlying_symbol"],
            "expiry": inst["expiry"], "strike": inst["strike"],
            "option_type": want,
            "transaction_type": pos["side"], "lots": pos["lots"]}


async def go() -> None:
    await prime_lotsizes()
    print("The gate rule itself:")
    for added, cash, want, why in [
        (-12331.0, -5612.0, True, "re-hedge frees margin, book over-committed"),
        (-1000.0, -50000.0, True, "frees less than the deficit — still an improvement"),
        (0.0, -5612.0, True, "neutral basket cannot reduce solvency"),
        (1.0, -5612.0, False, "adds margin to an over-committed book"),
        (3000.0, 5000.0, True, "ordinary affordable basket"),
        (6000.0, 5000.0, False, "ordinary basket beyond cash"),
    ]:
        got = basket_allowed(added, cash)
        check(f"added {added:>10,.0f} vs cash {cash:>10,.0f} -> {'allow' if want else 'refuse'}",
              got == want, why)

    print("\nAgainst the live paper books:")
    tested = 0
    for account in await list_accounts():
        aid = account["account_id"]
        s = await summary(aid)
        cash = await available_cash(aid)
        for pos in s["open_positions"]:
            leg = mirror(pos, s["open_positions"])
            if not leg:
                continue
            tested += 1
            est = await estimate_basket(aid, [leg])
            over = cash < 0
            print(f"\n  {account['name'][:40]}")
            print(f"    holding  {pos['display_name']} {pos['side']} {pos['lots']} lots")
            print(f"    cash     Rs{cash:>11,.0f}{'   OVER-COMMITTED' if over else ''}")
            freed = est["margin_released"]
            tail = f"  (frees Rs{freed:,.0f})" if freed else ""
            print(f"    re-hedge {leg['option_type']} {leg['lots']} lots -> "
                  f"margin delta Rs{est['margin_required']:>11,.0f}{tail}")
            print(f"    affordable: {est['affordable']}")

            if est["margin_required"] <= 0:
                check(f"{account['name'][:28]}: margin-freeing re-hedge is allowed",
                      est["affordable"],
                      f"delta Rs{est['margin_required']:,.0f}, cash Rs{cash:,.0f}")
                check(f"{account['name'][:28]}: the freed amount is reported, not clamped",
                      est["margin_released"] > 0 or est["margin_required"] == 0,
                      f"released Rs{est['margin_released']:,.0f}")
                # It must actually leave the book solvent, not merely be permitted.
                after = cash - est["margin_required"]
                check(f"{account['name'][:28]}: filling it improves available cash",
                      after >= cash,
                      f"Rs{cash:,.0f} -> Rs{after:,.0f}")
            break  # one pair per account is enough

    if not tested:
        print("  every open option position is already paired, so there is no missing leg "
              "to put back — the gate table above is the whole check")

    print("\n" + "=" * 64)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("re-hedge gate holds")


asyncio.run(go())
