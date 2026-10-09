"""Re-measure MCX margin against Angel's own calculator, contract by contract.

WHY IT IS A SCRIPT AND NOT A JOB
--------------------------------
`commodity_broker_margin.MEASURED_RATE` is the fallback used when the broker cannot be
asked. It is MEASURED, not modelled, which means it goes stale: SPAN files move with
volatility, and a rate measured in a quiet month under-charges a violent one. But it must
not update itself. A fallback that silently re-derives itself from the thing it is a
fallback FOR would adopt that thing's bad days — and two MCX futures (CRUDEOILM,
SILVER100) return about a seventh of their family's rate, every time, which is exactly
what the fallback exists to override. So re-measuring is deliberate, read-only, and
printed for a human to paste in.

WHAT IT DOES
------------
For every underlying with a live future it asks Angel what one lot costs, both as a future
and as a sold at-the-money call, and prints the answer as a fraction of that lot's
notional. Nothing is written anywhere.

It also flags two things worth knowing beyond the rates:

  * A VALUE MULTIPLIER THAT IS WRONG. Margin as a fraction of notional lands between 7%
    and 31% for every contract whose spec is right. A contract showing 1,328% is not a
    margin anomaly, it is `multiplier()` being wrong by a factor of a hundred-odd - which
    is how COTTONOIL and KAPAS were caught. The rate column is a spec check for free.

  * A BROKER FIGURE THAT CONTRADICTS ITSELF. A future whose rate is far below its own
    family's, while an OPTION on the same underlying sits at the family rate, is Angel's
    data being wrong rather than the contract being cheap to carry.

PACING. The margin endpoint answers reliably only when calls are spaced; unpaced bursts
come back Rs 0 for about a third of them. The shared `margin_pacer` handles that, so this
takes a couple of minutes for ~56 calls. That is the endpoint's speed, not the script's.

Run:  docker exec -e PYTHONPATH=/app/backend <container> python /tmp/measure_mcx_margin.py
"""

import asyncio
import sys
from datetime import date

sys.path.insert(0, "/app/backend")

from app.core.db import instruments_collection                          # noqa: E402
from app.services import commodity_positions as CP                      # noqa: E402
from app.services.angel_client import AngelAPIError, angel_client       # noqa: E402
from app.services.commodity_broker_margin import (                     # noqa: E402
    MEASURED_RATE, SHORT_OPTION_FACTOR,
)

TODAY = date.today().isoformat()
# The band every correctly-specced contract fell inside on 2026-10-09. Outside it, suspect
# the multiplier before the margin.
PLAUSIBLE = (0.03, 0.60)


async def ask(positions: list[dict]) -> float | None:
    try:
        return await angel_client.margin_batch(positions)
    except (AngelAPIError, OSError) as exc:
        print(f"      ! {str(exc)[:70]}")
        return None


def position(token, side: str, qty: int) -> dict:
    return {"exchange": "MCX", "qty": qty, "price": 0, "productType": "CARRYFORWARD",
            "token": str(token), "tradeType": side, "orderType": "MARKET"}


async def atm_call(sym: str, price: float) -> dict | None:
    expiries = sorted(await instruments_collection.distinct(
        "expiry", {"underlying_symbol": sym, "asset_class": "COMMODITY_OPTION",
                   "expiry": {"$gte": TODAY}}))
    if not expiries:
        return None
    strikes = await instruments_collection.distinct(
        "strike", {"underlying_symbol": sym, "asset_class": "COMMODITY_OPTION",
                   "expiry": expiries[0], "option_type": "CE"})
    if not strikes:
        return None
    return await instruments_collection.find_one(
        {"underlying_symbol": sym, "asset_class": "COMMODITY_OPTION",
         "expiry": expiries[0], "strike": min(strikes, key=lambda s: abs(s - price)),
         "option_type": "CE", "angel_token": {"$ne": None}})


async def main() -> None:
    await CP.prime_lotsizes()
    symbols = sorted(await instruments_collection.distinct(
        "underlying_symbol", {"asset_class": "COMMODITY_FUTURE",
                              "expiry": {"$gte": TODAY}}))
    print(f"Measured {TODAY} against Angel's margin calculator, front-month, 1 lot.\n")
    print(f"{'underlying':<12} {'family':<11} {'1-lot notional':>15} {'FUT':>11} {'rate':>7}"
          f" {'short ATM CE':>13} {'rate':>7} {'in use':>7}  flag")
    print("-" * 104)

    rows: list[tuple] = []
    for sym in symbols:
        fut = await instruments_collection.find_one(
            {"underlying_symbol": sym, "asset_class": "COMMODITY_FUTURE",
             "expiry": {"$gte": TODAY}, "angel_token": {"$ne": None}},
            sort=[("expiry", 1)])
        price, _f = await CP.future_price(sym)
        order_qty = CP.broker_order_qty(sym)
        if not (fut and price and order_qty):
            print(f"{sym:<12} no live future, price or lotsize — skipped")
            continue
        notional = price * CP.multiplier(sym)
        fam = CP.family_of(sym)

        fut_margin = await ask([position(fut["angel_token"], "BUY", order_qty)])
        fut_rate = (fut_margin / notional) if (fut_margin and notional) else None

        opt = await atm_call(sym, price)
        opt_rate = opt_margin = None
        if opt:
            opt_margin = await ask([position(opt["angel_token"], "SELL", order_qty)])
            strike_notional = float(opt.get("strike") or 0) * CP.multiplier(sym)
            if opt_margin and strike_notional:
                opt_rate = opt_margin / strike_notional

        flags = []
        if fut_rate is not None and not PLAUSIBLE[0] <= fut_rate <= PLAUSIBLE[1]:
            flags.append("MULTIPLIER?" if fut_rate > PLAUSIBLE[1] else "BROKER-LOW")
        if fut_rate is not None and opt_rate is not None and opt_rate > fut_rate * 3:
            # The option is charged at the family rate while the future is not: Angel's
            # own two answers disagree about the same underlying.
            flags.append("FUT CONTRADICTS ITS OWN OPTION")
        in_use = MEASURED_RATE.get(fam)

        print(f"{sym:<12} {fam:<11} {notional:>15,.0f} "
              f"{(f'{fut_margin:>11,.0f}' if fut_margin else '          -')} "
              f"{(f'{fut_rate:>6.1%}' if fut_rate is not None else '      -')} "
              f"{(f'{opt_margin:>13,.0f}' if opt_margin else '            -')} "
              f"{(f'{opt_rate:>6.1%}' if opt_rate is not None else '      -')} "
              f"{(f'{in_use:>6.1%}' if in_use else '     -')}  {' · '.join(flags)}")
        rows.append((sym, fam, fut_rate, opt_rate, in_use, flags))

    # ---- what to paste into MEASURED_RATE -------------------------------------------
    print("\n\nPER FAMILY, from the contracts whose rate is plausible")
    print("(a family's members should agree; a spread means one of their multipliers is "
          "wrong)")
    by_family: dict[str, list[tuple[str, float]]] = {}
    for sym, fam, fut_rate, _o, _u, flags in rows:
        if fut_rate is not None and PLAUSIBLE[0] <= fut_rate <= PLAUSIBLE[1] \
                and "BROKER-LOW" not in flags:
            by_family.setdefault(fam, []).append((sym, fut_rate))

    print(f"\n{'family':<12} {'members used':<34} {'rate':>7} {'in use':>7}  change")
    print("-" * 80)
    suggestion = {}
    for fam in sorted(by_family):
        members = by_family[fam]
        rate = max(r for _s, r in members)      # the dearest member, not the average
        suggestion[fam] = rate
        in_use = MEASURED_RATE.get(fam)
        delta = (f"{(rate - in_use) * 100:+.1f} pts" if in_use is not None else "NEW")
        names = ", ".join(s for s, _r in members)
        print(f"{fam:<12} {names[:33]:<34} {rate:>6.1%} "
              f"{(f'{in_use:>6.1%}' if in_use else '     -')}  {delta}")

    print("\n\nMEASURED_RATE: dict[str, float] = {")
    for fam in sorted(suggestion):
        print(f'    "{fam}": {suggestion[fam]:.3f},')
    print("}")

    ratios = [o / f for _s, _fa, f, o, _u, fl in rows
              if f and o and PLAUSIBLE[0] <= f <= PLAUSIBLE[1] and "BROKER-LOW" not in fl]
    if ratios:
        print(f"\nSHORT_OPTION_FACTOR currently {SHORT_OPTION_FACTOR}; measured "
              f"{min(ratios):.2f}-{max(ratios):.2f} (use the top of the range, rounded up: "
              f"a fallback should err expensive)")

    flagged = [(s, fl) for s, _f, _fr, _o, _u, fl in rows if fl]
    if flagged:
        print("\n\nFLAGGED")
        for sym, fl in flagged:
            print(f"  {sym:<12} {' · '.join(fl)}")
        print("\n  MULTIPLIER?  margin is an implausible share of notional — the lot VALUE "
              "is wrong,\n               not the margin. Check the exchange's contract spec "
              "before trading it.")
        print("  BROKER-LOW / CONTRADICTS  Angel's futures figure is far under its own "
              "family's and\n               under its own option on the same underlying. "
              "The floor in\n               commodity_broker_margin overrides it; this is "
              "that override earning its keep.")


asyncio.run(main())
