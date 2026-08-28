"""Does "Re-add ATM" close the right leg and put the right one back?

Runs on a scratch account it creates and deletes. Cleanup is in a finally block: an
exception between the close and the re-open would otherwise leave a scratch book holding
live positions on the shared cluster.

What has to hold:
  * the old position is CLOSED, not left open alongside the new one
  * the new position is the SAME underlying, expiry, option type, side and lots
  * only the STRIKE moved, and it moved to the listed strike nearest the future
  * the book ends with the same number of open legs it started with
  * a futures position is refused rather than rolled into a nonsense strike

Run: python -m tests.commodity_positions.verify_reopen_atm
"""
import asyncio
import sys
import traceback

from app.services.commodity_positions import (
    OrderError, atm_strike, available_cash, create_account, delete_account, execute_basket,
    exit_position, future_expiries, option_chain, option_expiries, prime_lotsizes,
    reopen_at_the_money, summary,
)

SYMBOL = "CRUDEOILM"
LOTS = 2
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


async def go() -> None:
    await prime_lotsizes()
    expiry = (await option_expiries(SYMBOL))[0]
    chain = await option_chain(SYMBOL, expiry)
    spot = float(chain["spot"])
    strikes = sorted(float(r["strike"]) for r in chain["strikes"])
    atm = min(strikes, key=lambda k: abs(k - spot))

    # Deliberately open AWAY from the money, so the roll has somewhere to move to. Rolling
    # a leg that is already at the money proves nothing about whether the strike changed.
    off = [k for k in strikes if k > atm]
    away = off[min(4, len(off) - 1)] if off else atm
    print(f"{SYMBOL} {expiry}: future {spot}, ATM {atm:g}, opening away at {away:g}\n")

    acc = await create_account("SCRATCH reopen-atm probe", 2000000.0)
    aid = acc["account_id"]
    try:
        await execute_basket(aid, [{
            "instrument_kind": "OPTION", "symbol": SYMBOL, "expiry": expiry,
            "strike": away, "option_type": "CE", "transaction_type": "SELL",
            "lots": LOTS}])
        before = await summary(aid)
        old = before["open_positions"][0]
        print(f"opened  {old['display_name']} {old['side']} {old['lots']} lots")

        want_strike, ref = await atm_strike(SYMBOL, expiry, "CE")
        r = await reopen_at_the_money(aid, old["position_id"])
        print(f"rolled  {r['note']}")
        print(f"        closed at {r['closed']['exit_price']}, "
              f"re-opened at {r['opened']['entry_price']}, "
              f"margin delta Rs{r['margin_delta']:,.0f}")

        after = await summary(aid)
        openp = after["open_positions"]
        check("the book still holds exactly one leg", len(openp) == 1,
              f"{len(openp)} open")
        if not openp:
            return
        new = openp[0]
        ni = new["instrument"]

        check("the old strike is gone", float(ni["strike"]) != away,
              f"was {away:g}, now {float(ni['strike']):g}")
        check("the new strike is the one nearest the future",
              float(ni["strike"]) == want_strike,
              f"{float(ni['strike']):g} vs expected {want_strike:g} (future {ref})")
        check("same underlying", new["underlying_symbol"] == SYMBOL)
        check("same expiry", ni["expiry"] == expiry)
        check("same option type", ni["option_type"] == "CE")
        check("same side", new["side"] == old["side"], f"{new['side']}")
        check("same lots", new["lots"] == LOTS, f"{new['lots']}")
        check("the closed leg is recorded as closed",
              any(float((p["instrument"] or {}).get("strike") or 0) == away
                  for p in after["closed_positions"]),
              f"{len(after['closed_positions'])} closed row(s)")

        # A future has no at-the-money strike; rolling one must be refused, not invented.
        # Its own expiry, not the option's: MCX options expire BEFORE the future they are
        # written on, so reusing the option expiry here just fails to find a contract and
        # skips the check that matters.
        fut_expiry = (await future_expiries(SYMBOL))[0]
        try:
            await execute_basket(aid, [{
                "instrument_kind": "FUTURE", "symbol": SYMBOL, "expiry": fut_expiry,
                "transaction_type": "BUY", "lots": 1}])
            s2 = await summary(aid)
            fut = next(p for p in s2["open_positions"]
                       if p["instrument_kind"] == "FUTURE")
            try:
                await reopen_at_the_money(aid, fut["position_id"])
                check("a future is refused, not rolled", False, "it was allowed")
            except OrderError as exc:
                check("a future is refused, not rolled", True, exc.detail[:70])
        except OrderError as exc:
            print(f"  (futures leg not opened, skipped that check: {exc.detail[:60]})")

    except Exception:
        traceback.print_exc()
        FAILURES.append("unexpected exception")
    finally:
        print("\ncleanup:")
        try:
            s = await summary(aid)
            for p in s["open_positions"]:
                await exit_position(aid, p["position_id"])
                print(f"  closed {p['display_name']}")
            await delete_account(aid)
            print("  scratch account deleted")
        except Exception as exc:
            print(f"  CLEANUP FAILED — remove {aid} by hand: {exc}")
            FAILURES.append("cleanup")


async def main() -> None:
    await go()
    print("\n" + "=" * 64)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("re-add ATM holds")


asyncio.run(main())
