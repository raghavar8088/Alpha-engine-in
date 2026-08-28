"""Does the book-level roll move every leg, and survive the state a loop would strand?

Runs on scratch accounts it creates and deletes; cleanup is in a finally block.

The case that justifies this existing as its own operation rather than a loop over the
per-row button: a short straddle rolled ONE LEG AT A TIME is, in between, a naked leg —
and a naked leg costs more margin than the pair did, because the leg that was offsetting
it is gone. On a book with little free cash that intermediate state can refuse the second
roll and leave the position half-rolled: one leg at the money, one stranded far from it,
and the account worse off than before it was touched.

So this test builds a tight book, measures whether a leg-at-a-time roll would be refused
there, and checks the real operation completes either way. Whether that refusal actually
occurs depends on live prices - an inverted intermediate is not always dearer than the
pair - so the run PRINTS which case it demonstrated rather than letting a pass imply the
harder one.

Run: python -m tests.commodity_positions.verify_reopen_atm_all
"""
import asyncio
import sys
import traceback

from app.services.commodity_positions import (
    OrderError, atm_strike, available_cash, basket_allowed, create_account, delete_account,
    execute_basket, exit_position, _leg_from, _margin_for, _open_group, _pos_to_leg,
    _price_basket, _years_to_expiry, option_chain, option_expiries, prime_lotsizes,
    reopen_all_at_the_money, summary,
)

SYMBOL = "CRUDEOILM"
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


async def build(aid: str, expiry: str, away: float, lots: int) -> None:
    """A short strangle sitting away from the money, so the roll has work to do."""
    await execute_basket(aid, [
        {"instrument_kind": "OPTION", "symbol": SYMBOL, "expiry": expiry,
         "strike": away, "option_type": ot, "transaction_type": "SELL", "lots": lots}
        for ot in ("CE", "PE")])


async def would_a_single_leg_roll_be_refused(aid: str, expiry: str) -> bool:
    """Project rolling just the CE, the way the per-row button gates it."""
    s = await summary(aid)
    ce = next(p for p in s["open_positions"]
              if (p["instrument"] or {}).get("option_type") == "CE")
    inst = ce["instrument"]
    strike, ref = await atm_strike(SYMBOL, expiry, "CE")
    t = _years_to_expiry(expiry)
    priced = await _price_basket([{
        "instrument_kind": "OPTION", "symbol": SYMBOL, "expiry": expiry,
        "strike": strike, "option_type": "CE", "transaction_type": ce["side"],
        "lots": int(ce["lots"])}])
    group = await _open_group(aid, SYMBOL, expiry)
    survivors = [q for q in group if q["position_id"] != ce["position_id"]]
    before = _margin_for([_pos_to_leg(q, ref, t) for q in group], SYMBOL, ref, t)["total"]
    after = _margin_for(
        [_pos_to_leg(q, ref, t) for q in survivors]
        + [_leg_from(x["inst"], x["side"], x["qty"], x["ltp"], ref, t) for x in priced],
        SYMBOL, ref, t)["total"]
    delta = round(after - before, 2)
    cash = await available_cash(aid)
    print(f"    one-leg-at-a-time delta Rs{delta:,.0f} against Rs{cash:,.0f} free")
    return not basket_allowed(delta, cash)


async def go() -> None:
    await prime_lotsizes()
    expiry = (await option_expiries(SYMBOL))[0]
    chain = await option_chain(SYMBOL, expiry)
    spot = float(chain["spot"])
    strikes = sorted(float(r["strike"]) for r in chain["strikes"])
    atm = min(strikes, key=lambda k: abs(k - spot))
    above = [k for k in strikes if k > atm]
    away = above[min(5, len(above) - 1)] if above else atm
    print(f"{SYMBOL} {expiry}: future {spot}, ATM {atm:g}, strangle at {away:g}\n")

    scratch: list[str] = []
    try:
        # ---------------------------------------------------- 1. a roomy book ----
        acc = await create_account("SCRATCH roll-all roomy", 3000000.0)
        scratch.append(acc["account_id"])
        aid = acc["account_id"]
        await build(aid, expiry, away, 3)
        before = await summary(aid)
        print(f"roomy book: {before['open_count']} legs at {away:g}")

        r = await reopen_all_at_the_money(aid)
        print(f"  {r['note']}")
        after = await summary(aid)
        check("every leg still open after the roll",
              after["open_count"] == before["open_count"],
              f"{before['open_count']} -> {after['open_count']}")
        check("both legs rolled", r["legs_rolled"] == 2, f"{r['legs_rolled']}")
        check("both strikes actually changed", r["strikes_changed"] == 2,
              f"{r['strikes_changed']} changed")
        want, _ref = await atm_strike(SYMBOL, expiry, "CE")
        check("every open leg now sits at the money",
              all(float(p["instrument"]["strike"]) == want
                  for p in after["open_positions"]),
              ", ".join(f"{float(p['instrument']['strike']):g}"
                        for p in after["open_positions"]))
        check("nothing failed", not r["failed"], str(r["failed"])[:80])

        # ------------------------------------------- 2. the tight book that
        #    a leg-at-a-time roll would strand ------------------------------------
        acc2 = await create_account("SCRATCH roll-all tight", 100000.0)
        scratch.append(acc2["account_id"])
        bid = acc2["account_id"]
        await build(bid, expiry, away, 1)
        cash = await available_cash(bid)
        s = await summary(bid)
        print(f"\ntight book: {s['open_count']} legs, only Rs{cash:,.0f} free")

        refused = await would_a_single_leg_roll_be_refused(bid, expiry)
        print(f"    -> rolling one leg alone would be "
              f"{'REFUSED' if refused else 'allowed'}")

        r2 = await reopen_all_at_the_money(bid)
        print(f"  {r2['note']}")
        after2 = await summary(bid)
        check("the tight book rolled as one group",
              r2["legs_rolled"] == 2 and not r2["failed"],
              f"{r2['legs_rolled']} legs, {len(r2['failed'])} failed")
        check("the tight book is not left half-rolled",
              len({float(p["instrument"]["strike"]) for p in after2["open_positions"]}) == 1,
              ", ".join(f"{float(p['instrument']['strike']):g}"
                        for p in after2["open_positions"]))
        # Be explicit about which of the two this run actually demonstrated. The grouped
        # design prevents stranding by construction, but whether a leg-at-a-time roll
        # WOULD have stranded depends on live prices, and on many days it would not.
        # Reporting a pass as proof of the harder case when the condition never arose
        # would make this test a worse witness than saying so.
        print("    NOTE: rolling one leg alone would have been "
              + ("REFUSED here — this run does demonstrate the case a loop strands."
                 if refused else
                 "allowed here, so this run does NOT demonstrate stranding. What it "
                 "shows is that the grouped path reaches the same end state."))

        # ------------------------------------ 3. rolling only a SELECTION --------
        acc4 = await create_account("SCRATCH roll-all selection", 3000000.0)
        scratch.append(acc4["account_id"])
        did = acc4["account_id"]
        await build(did, expiry, away, 1)
        s4 = await summary(did)
        one = next(p for p in s4["open_positions"]
                   if (p["instrument"] or {}).get("option_type") == "CE")
        other = next(p for p in s4["open_positions"]
                     if p["position_id"] != one["position_id"])
        print("")
        print(f"selection: rolling ONLY {one['display_name']}, "
              f"leaving {other['display_name']} alone")

        r4 = await reopen_all_at_the_money(did, [one["position_id"]])
        print(f"  {r4['note']}")
        after4 = await summary(did)
        check("only the selected leg was rolled", r4["legs_rolled"] == 1,
              f"{r4['legs_rolled']} rolled")
        want_ce, _r = await atm_strike(SYMBOL, expiry, "CE")
        moved = [q for q in after4["open_positions"]
                 if (q["instrument"] or {}).get("option_type") == "CE"]
        stayed = [q for q in after4["open_positions"]
                  if (q["instrument"] or {}).get("option_type") == "PE"]
        check("the selected leg is now at the money",
              len(moved) == 1 and float(moved[0]["instrument"]["strike"]) == want_ce,
              str([float(q["instrument"]["strike"]) for q in moved]))
        check("the UNSELECTED leg was left exactly where it was",
              len(stayed) == 1
              and float(stayed[0]["instrument"]["strike"]) == away
              and stayed[0]["position_id"] == other["position_id"],
              f"{[float(q['instrument']['strike']) for q in stayed]} vs {away:g}")

        # A selection that has gone stale must be refused, not silently reduced to the
        # rows that still exist — the button would then do less than it said it would.
        try:
            await reopen_all_at_the_money(did, [one["position_id"], "deadbeefdead"])
            check("a stale selection is refused, not partly rolled", False, "it returned")
        except OrderError as exc:
            check("a stale selection is refused, not partly rolled",
                  "no longer open" in exc.detail, exc.detail[:70])
        after5 = await summary(did)
        check("the refused stale roll closed nothing",
              after5["open_count"] == after4["open_count"],
              f"{after4['open_count']} -> {after5['open_count']}")

        # ------------------------------------------------ 4. an empty book -------
        acc3 = await create_account("SCRATCH roll-all empty", 100000.0)
        scratch.append(acc3["account_id"])
        try:
            await reopen_all_at_the_money(acc3["account_id"])
            check("an empty book is refused, not silently 'rolled'", False, "it returned")
        except OrderError as exc:
            check("an empty book is refused, not silently 'rolled'", True, exc.detail[:60])

    except Exception:
        traceback.print_exc()
        FAILURES.append("unexpected exception")
    finally:
        print("\ncleanup:")
        for aid in scratch:
            try:
                s = await summary(aid)
                for p in s["open_positions"]:
                    await exit_position(aid, p["position_id"])
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
    print("book-level roll holds")


asyncio.run(main())
