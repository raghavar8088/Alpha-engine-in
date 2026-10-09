"""Audit EVERY MCX contract's lot maths, two independent ways. READ-ONLY.

CHECK 1 - INTERNAL. The multiplier must equal lot_quantity / quote_quantity. A GOLD lot
is 1 kg and the price is quoted per 10 grams, so one lot is 100 quote-units and the
multiplier must be 100. This catches a multiplier that disagrees with the module's own
stated lot size and quote unit.

CHECK 2 - AGAINST THE MARKET. Every contract in a family is the same metal, so once each
is converted to rupees per BASE unit (a gram of gold, a kilo of silver) they must all
agree. GOLD, GOLDM, GOLDTEN, GOLDGUINEA and GOLDPETAL quote five different ways; if the
multiplier or the quote unit is wrong on any of them, that one falls out of line with the
other four. This catches an error that is self-consistent on paper but wrong in reality.
"""
import asyncio, re
from app.services import commodity_positions as C

# unit -> (canonical base, how many base units)
UNITS = {
    "gram": ("g", 1), "grams": ("g", 1), "g": ("g", 1),
    "kg": ("g", 1000), "kgs": ("g", 1000),
    "tonne": ("g", 1_000_000), "tonnes": ("g", 1_000_000), "mt": ("g", 1_000_000),
    "barrel": ("bbl", 1), "barrels": ("bbl", 1),
    "mmbtu": ("mmBtu", 1),
}
FAMILY = {
    "GOLD": "gold", "GOLDM": "gold", "GOLDTEN": "gold", "GOLDGUINEA": "gold",
    "GOLDPETAL": "gold",
    "SILVER": "silver", "SILVERM": "silver", "SILVERMIC": "silver", "SILVER100": "silver",
    "CRUDEOIL": "crude", "CRUDEOILM": "crude",
    "NATURALGAS": "gas", "NATGASMINI": "gas",
    "ZINC": "zinc", "ZINCMINI": "zinc",
    "ALUMINIUM": "aluminium", "ALUMINI": "aluminium",
    "LEAD": "lead", "LEADMINI": "lead",
    "COPPER": "copper", "NICKEL": "nickel",
}


def parse_qty(text: str):
    """'100 grams' -> ('g', 100).  '₹ per kg' -> ('g', 1000).  '₹ per 10 grams' -> ('g', 10)."""
    t = (text or "").lower().replace("₹", " ").replace("per", " ")
    m = re.search(r"([\d,]*\.?\d*)\s*([a-z]+)", t)
    if not m:
        return None, None
    num = m.group(1).replace(",", "")
    qty = float(num) if num else 1.0
    unit = m.group(2)
    if unit not in UNITS:
        return None, None
    base, scale = UNITS[unit]
    return base, qty * scale


async def main():
    await C.prime_lotsizes()
    board = await C.futures_board()
    price = {}
    for c in board.get("contracts") or []:
        u = ((c.get("underlying") or "")).upper()
        if c.get("ltp") and u and u not in price:
            price[u] = c["ltp"]

    print("CHECK 1 — multiplier must equal lot ÷ quote unit")
    print(f"  {'UNDERLYING':<13}{'LOT':>14}{'QUOTED PER':>14}{'MULT':>8}{'EXPECTED':>10}  VERDICT")
    bad1 = []
    rows = {}
    for sym in sorted(C.CONTRACT_SPEC):
        lot_s, quote_s, mult = C.CONTRACT_SPEC[sym]
        lb, lq = parse_qty(lot_s)
        qb, qq = parse_qty(quote_s)
        if not lb or not qb or lb != qb or not qq:
            print(f"  {sym:<13}{lot_s:>14}{quote_s:>14}{mult:>8}{'?':>10}  cannot parse")
            continue
        expect = lq / qq
        ok = abs(expect - mult) < 1e-9
        if not ok:
            bad1.append((sym, mult, expect))
        rows[sym] = (lb, lq, qb, qq, mult)
        print(f"  {sym:<13}{lot_s:>14}{quote_s:>14}{mult:>8}{expect:>10,.0f}  "
              f"{'ok' if ok else '*** WRONG ***'}")
    print(f"\n  multiplier disagreements: {bad1 or 'NONE'}")

    print("\n\nCHECK 2 — family members must agree on the price of one base unit")
    fams = {}
    for sym, (lb, lq, qb, qq, mult) in rows.items():
        fam = FAMILY.get(sym)
        if not fam or sym not in price:
            continue
        per_base = price[sym] / qq          # rupees per gram / kg-of-base / barrel / mmBtu
        fams.setdefault((fam, lb), []).append((sym, price[sym], per_base, lq * price[sym] / qq))
    bad2 = []
    for (fam, base), members in sorted(fams.items()):
        vals = [m[2] for m in members]
        lo, hi = min(vals), max(vals)
        spread = (hi - lo) / lo * 100 if lo else 0
        flag = "ok" if spread < 2.0 else "*** DISAGREE ***"
        if spread >= 2.0:
            bad2.append((fam, round(spread, 1)))
        print(f"\n  {fam.upper()} — rupees per {base}   spread {spread:.2f}%  {flag}")
        for sym, px, per_base, lot_value in sorted(members):
            print(f"      {sym:<12} price {px:>12,.2f}  = {per_base:>12,.2f} /{base}"
                  f"   1 lot = Rs {lot_value:>14,.0f}")
    print(f"\n  family disagreements: {bad2 or 'NONE'}")

    print("\n\nCONTRACTS WITH NO PUBLISHED SPEC (lot value is the broker's order unit)")
    for r in board.get("spec_check") or []:
        if not r["verified"]:
            gate = "BLOCKED from new orders" if not r["plausible"] else "tradable, UNVERIFIED"
            print(f"  {r['underlying']:<12} mult {r['multiplier']:<6} "
                  f"1 lot = Rs {r['contract_value']:>12,.0f}   {gate}")

asyncio.run(main())
