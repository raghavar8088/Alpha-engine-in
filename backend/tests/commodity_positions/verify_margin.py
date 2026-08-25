"""Margin must scale with the position. No Mongo, no Angel, no network.

Run:  python backend/tests/commodity_positions/verify_margin.py

THE BUG THIS PINS DOWN, found on a live book:

    a 38-lot NATGASMINI short strangle — Rs2.53 lakh of contract exposure on a Rs2 lakh
    account — was blocking Rs14,574 of margin. The correct portfolio figure was
    Rs2,59,314.

`margin_used` was written once when a position was created and never again. `_merge`,
which grows a position when you add to it, updated lots, quantity and the average entry
and left margin frozen. So the first lot paid margin and every lot after it was free, and
every later affordability check saw capital that did not exist.

The give-away in the data was that a 1-lot position and a 38-lot position on the same
strike recorded almost the same margin — Rs7,665 against Rs7,677. Margin that does not
move with size is margin that is not being computed.

Everything below runs against `fno_margin.portfolio_margin` directly, which is pure, so
the arithmetic is checked without a database or a broker.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "instrument_search"))
from _stub_infra import stub_infra  # noqa: E402

stub_infra()

from app.services.commodity_positions import (  # noqa: E402
    _leg_from, _margin_for, _merge, _pos_to_leg, _scan_pct, multiplier,
)

FAILURES: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


# The real contract, and the real futures price at the time of the incident.
SYM, STRIKE, REF, T = "NATGASMINI", 265.0, 267.1, 29 / 365
MULT = multiplier(SYM)
CE = {"option_type": "CE", "strike": STRIKE}
PE = {"option_type": "PE", "strike": STRIKE}


def margin(inst, side, lots, premium, legs_extra=None):
    legs = [_leg_from(inst, side, lots * MULT, premium, REF, T)]
    if legs_extra:
        legs += legs_extra
    return _margin_for(legs, SYM, REF, T)["total"]


print(f"\n== the contract ==")
check("NATGASMINI multiplier is 250", MULT == 250, str(MULT))
check("it scans at natural gas's 13%, not the default", abs(_scan_pct(SYM) - 0.13) < 1e-9,
      f"{_scan_pct(SYM):.0%}")

print("\n== margin scales with size ==")
one = margin(CE, "SELL", 1, 14.20)
ten = margin(CE, "SELL", 10, 14.20)
thirty8 = margin(CE, "SELL", 38, 14.20)
print(f"    1 lot  Rs{one:>12,.0f}")
print(f"   10 lots Rs{ten:>12,.0f}")
print(f"   38 lots Rs{thirty8:>12,.0f}")
check("10 lots costs ~10x one lot", abs(ten / one - 10) < 0.05, f"{ten/one:.2f}x")
check("38 lots costs ~38x one lot", abs(thirty8 / one - 38) < 0.05, f"{thirty8/one:.2f}x")
check("a 38-lot short strangle leg is NOT Rs7,677", thirty8 > 200000,
      f"Rs{thirty8:,.0f} (the book had recorded Rs7,677)")

print("\n== the strangle as a portfolio ==")
both = _margin_for(
    [_leg_from(CE, "SELL", 38 * MULT, 14.20, REF, T),
     _leg_from(PE, "SELL", 38 * MULT, 12.46, REF, T)], SYM, REF, T)["total"]
print(f"   short 38x265CE + 38x265PE  Rs{both:,.0f}")
check("a 38-lot short strangle needs six figures of margin", both > 200000, f"Rs{both:,.0f}")
check("it is not the sum of both legs — one side pays", both < thirty8 + margin(PE, "SELL", 38, 12.46),
      "a strangle cannot lose on both sides at once")

print("\n== a short is margined far above the premium it collects ==")
premium_in = (14.20 + 12.46) * 38 * MULT
print(f"   premium collected Rs{premium_in:,.0f} vs margin Rs{both:,.0f}")
check("margin exceeds the premium received", both > premium_in,
      f"{both/premium_in:.1f}x the credit")

print("\n== hedging reduces it, and being naked does not ==")
hedged = _margin_for(
    [_leg_from(CE, "SELL", 38 * MULT, 14.20, REF, T),
     _leg_from({"option_type": "CE", "strike": 275.0}, "BUY", 38 * MULT, 9.0, REF, T)],
    SYM, REF, T)["total"]
print(f"   38x 265/275 call spread    Rs{hedged:,.0f}")
check("a capped short costs far less than a naked one", hedged < thirty8 / 2,
      f"Rs{hedged:,.0f} vs Rs{thirty8:,.0f}")

print("\n== a long option can never cost more than it paid ==")
long_cost = margin(CE, "BUY", 38, 14.20)
paid = 14.20 * 38 * MULT
check("a long call's margin is bounded by its premium", long_cost <= paid * 1.02,
      f"Rs{long_cost:,.0f} against Rs{paid:,.0f} paid")

print("\n== _pos_to_leg reports the CURRENT size, not the opening size ==")
pos = {"instrument_kind": "OPTION", "side": "SELL", "quantity": 38 * MULT,
       "entry_price": 14.20, "ltp": 14.25,
       "instrument": {"option_type": "CE", "strike": STRIKE}}
leg = _pos_to_leg(pos, REF, T)
check("qty comes from the stored quantity", leg["qty"] == 38 * MULT, str(leg["qty"]))
check("it marks at the live price, not the entry", leg["premium"] == 14.25, str(leg["premium"]))
check("IV is solved against the FUTURE, not left blank", leg["iv"] is not None, str(leg["iv"]))
check("re-margining that leg gives the six-figure number",
      _margin_for([leg], SYM, REF, T)["total"] > 200000)

print("\n== _merge grows the position, so margin must be recomputed after it ==")
base = {"side": "SELL", "lots": 1, "quantity": MULT, "entry_price": 14.20, "realized_pnl": 0.0}
grown = _merge(base, "SELL", 37, 37 * MULT, 14.20)
check("adding 37 lots to 1 gives 38", grown["lots"] == 38 and grown["quantity"] == 38 * MULT,
      f"{grown['lots']} lots / {grown['quantity']} qty")
check("_merge does NOT carry a margin field — the caller must re-margin",
      "margin_used" not in grown,
      "if this ever starts returning margin_used, remargin_group is being bypassed")

print("\n== the reference price must be the FUTURE, never the premium ==")
# The old fallback used the option's own premium as the underlying when no future price
# was available. On this contract that turned a Rs2.98 lakh margin into Rs2,698.
wrong = _margin_for([_leg_from(CE, "SELL", 38 * MULT, 14.20, 14.20, T)], SYM, 14.20, T)["total"]
print(f"   ref = the future (267.10)  Rs{thirty8:>12,.0f}")
print(f"   ref = the premium (14.20)  Rs{wrong:>12,.0f}")
check("pricing the underlying as the premium understates margin catastrophically",
      wrong < thirty8 / 20, f"{thirty8/max(wrong,1):.0f}x too small")

print(f"\n{'ALL CHECKS PASSED' if not FAILURES else 'FAILURES: ' + '; '.join(FAILURES)}")
sys.exit(1 if FAILURES else 0)
