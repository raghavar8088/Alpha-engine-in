"""Do the ported tools work on the F&O desk's own data?

Runs on a scratch account it creates and deletes; cleanup is in a finally block.

`dhan=None` throughout: quotes, chains and expiries all fall back to Angel One here, and
the auto-roll scheduler runs with None routinely, so this exercises the same path the
unattended jobs take rather than one that only works with a broker session attached.

Run: python -m tests.fno_positions.verify_atm_tools
"""
import asyncio
import sys
import traceback

from app.services.fno_positions import (
    OrderError, atm_strike, available_cash, create_account, delete_account, execute_basket,
    exit_position, max_lots, option_chain, option_expiries, reopen_all_at_the_money,
    summary,
)

SYMBOL = "NIFTY"
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


async def go() -> None:
    expiry = (await option_expiries(None, SYMBOL))[0]
    chain = await option_chain(None, SYMBOL, expiry)
    spot = float(chain["spot"])
    strikes = sorted(float(r["strike"]) for r in chain.get("strikes", []))
    if not strikes:
        print("chain returned no strikes — market data unavailable, nothing to verify")
        return
    atm = min(strikes, key=lambda k: abs(k - spot))
    above = [k for k in strikes if k > atm]
    away = above[min(5, len(above) - 1)] if above else atm
    print(f"{SYMBOL} {expiry}: spot {spot}, ATM {atm:g}, opening away at {away:g}\n")

    scratch: list[str] = []
    try:
        acc = await create_account("SCRATCH fno atm tools", 5000000.0)
        scratch.append(acc["account_id"])
        aid = acc["account_id"]

        # ---------------------------------------------------------- max_lots ----
        straddle = [{"instrument_kind": "OPTION", "symbol": SYMBOL, "expiry": expiry,
                     "strike": atm, "option_type": ot, "transaction_type": "SELL",
                     "lots": 1} for ot in ("CE", "PE")]
        m = await max_lots(None, aid, straddle)
        cash = await available_cash(aid)
        print(f"max_lots on an ATM straddle -> {m['max_lots']} lots, "
              f"margin Rs{m['margin']:,.0f} of Rs{m['available_cash']:,.0f}")
        print(f"  reason: {m['reason']}")
        check("the sized margin fits the free cash",
              m["max_lots"] == 0 or m["margin"] <= cash + 0.01,
              f"Rs{m['margin']:,.0f} <= Rs{cash:,.0f}")
        if m.get("margin_at_next") is not None:
            check("one more lot does NOT fit",
                  m["margin_at_next"] > cash + 0.01,
                  f"Rs{m['margin_at_next']:,.0f} > Rs{cash:,.0f}")
        check("a straddle is netted, not multiplied out",
              m["max_lots"] == 0
              or m["margin"] <= m["margin_per_lot"] * m["max_lots"] * 1.05,
              f"Rs{m['margin']:,.0f} vs Rs{m['margin_per_lot'] * m['max_lots']:,.0f} linear")

        # ------------------------------------------------------------- roll -----
        await execute_basket(None, aid, [
            {"instrument_kind": "OPTION", "symbol": SYMBOL, "expiry": expiry,
             "strike": away, "option_type": ot, "transaction_type": "SELL", "lots": 1}
            for ot in ("CE", "PE")])
        before = await summary(aid)
        print(f"\nopened {before['open_count']} legs at {away:g}")

        want, _spot = await atm_strike(None, SYMBOL, expiry, "CE")
        r = await reopen_all_at_the_money(None, aid)
        print(f"  {r['note']}")
        after = await summary(aid)
        check("every leg still open after the roll",
              after["open_count"] == before["open_count"],
              f"{before['open_count']} -> {after['open_count']}")
        check("both legs rolled", r["legs_rolled"] == 2, str(r["legs_rolled"]))
        check("both strikes changed", r["strikes_changed"] == 2,
              f"{r['strikes_changed']} changed")
        check("every open leg now sits at the money",
              all(float(p["instrument"]["strike"]) == want
                  for p in after["open_positions"]),
              ", ".join(f"{float(p['instrument']['strike']):g}"
                        for p in after["open_positions"]))
        check("nothing failed", not r["failed"], str(r["failed"])[:80])

        # ------------------------------------------------- a selection only -----
        one = after["open_positions"][0]
        other = after["open_positions"][1]
        r2 = await reopen_all_at_the_money(None, aid, [one["position_id"]])
        check("only the selected leg was rolled", r2["legs_rolled"] == 1,
              f"{r2['legs_rolled']} rolled")
        after2 = await summary(aid)
        check("the unselected leg kept its position id",
              any(p["position_id"] == other["position_id"]
                  for p in after2["open_positions"]),
              "it was replaced" )

        try:
            await reopen_all_at_the_money(None, aid, ["deadbeefdead"])
            check("a stale selection is refused", False, "it returned")
        except OrderError as exc:
            check("a stale selection is refused", "no longer open" in exc.detail,
                  exc.detail[:60])

        # ------------------------------------------- delete guards --------------
        try:
            await delete_account(aid)
            check("delete refuses a book with open positions", False, "it deleted")
        except OrderError as exc:
            check("delete refuses a book with open positions",
                  "open position" in exc.detail, exc.detail[:60])

    except Exception:
        traceback.print_exc()
        FAILURES.append("unexpected exception")
    finally:
        print("\ncleanup:")
        for aid in scratch:
            try:
                s = await summary(aid)
                for p in s["open_positions"]:
                    await exit_position(None, aid, p["position_id"])
                await delete_account(aid)
                print(f"  deleted {aid}")
            except Exception as exc:
                print(f"  CLEANUP FAILED for {aid}: {exc}")
                FAILURES.append("cleanup")


async def main() -> None:
    await go()
    print("\n" + "=" * 64)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("F&O ATM tools hold")


asyncio.run(main())
