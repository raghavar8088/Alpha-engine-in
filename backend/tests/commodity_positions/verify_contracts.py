"""Verify the MCX contract mathematics. No Mongo, no Angel, no network.

Run:  python backend/tests/commodity_positions/verify_contracts.py

Everything here decides money. An MCX lot is not one unit — a ZINC lot is 5 tonnes and a
GOLD lot is a kilogram — so a wrong multiplier does not produce a wrong-looking number, it
produces a plausible one that is out by a factor of 100 or 5,000. The fixtures below are
real rows from the broker's scrip master and real prices read from production on
2026-08-22, so the assertions are checks against reality rather than against themselves.

The three that matter most, because the broker's own `lotsize` field disagrees with the
published contract specification for exactly these:

    GOLD    lotsize 1    -> Rs 1.6 lakh    but a 1 kg gold lot is Rs 1.63 crore
    GOLDM   lotsize 100  -> Rs 1.6 crore   but a 100 g lot is Rs 16.2 lakh
    ZINC    lotsize 5    -> Rs 2,088       but 5 tonnes of zinc is Rs 20.9 lakh
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "instrument_search"))
from _stub_infra import stub_infra  # noqa: E402

stub_infra()

from app.services.commodity_instruments import build_rows, _parse_expiry  # noqa: E402
from app.services.commodity_positions import (  # noqa: E402
    CONTRACT_SPEC, _merge, check_specs, contract_value, multiplier, spec_doc, tick_rupees,
)

FAILURES: list[str] = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


# Live futures prices read from production on 2026-08-22.
LIVE = {
    "GOLD": 162101.0, "GOLDM": 160955.0, "GOLDTEN": 160900.0, "GOLDGUINEA": 129070.0,
    "GOLDPETAL": 16132.0, "SILVER": 241241.0, "SILVERM": 242400.0, "SILVERMIC": 242275.0,
    "SILVER100": 2421.0, "CRUDEOIL": 7885.0, "CRUDEOILM": 7881.0, "NATURALGAS": 259.6,
    "NATGASMINI": 259.5, "COPPER": 1384.2, "ZINC": 418.85, "ZINCMINI": 417.25,
    "ALUMINIUM": 346.15, "ALUMINI": 347.55, "LEAD": 196.45, "LEADMINI": 197.4,
    "NICKEL": 1629.0,
}

print("\n== the three the broker's lotsize gets wrong ==")
check("a GOLD lot is a kilo, not 10 grams",
      abs(contract_value("GOLD", LIVE["GOLD"]) - 1.62e7) < 3e5,
      f"₹{contract_value('GOLD', LIVE['GOLD']):,.0f} (broker lotsize 1 would say ₹1.6 lakh)")
check("a GOLDM lot is 100 g — a tenth of GOLD, not the same size",
      abs(contract_value("GOLDM", LIVE["GOLDM"]) / contract_value("GOLD", LIVE["GOLD"]) - 0.1) < 0.02,
      f"₹{contract_value('GOLDM', LIVE['GOLDM']):,.0f}")
check("a ZINC lot is 5 tonnes, not 5 kilos",
      abs(contract_value("ZINC", LIVE["ZINC"]) - 2.09e6) < 1e5,
      f"₹{contract_value('ZINC', LIVE['ZINC']):,.0f} (broker lotsize 5 would say ₹2,088)")

print("\n== every specified contract lands in a plausible band ==")
rows = check_specs(LIVE)
bad = [r for r in rows if not r["plausible"]]
check("all priced underlyings are plausible", not bad,
      "; ".join(f"{r['underlying']} ₹{r['contract_value']:,.0f}" for r in bad))
check("check_specs prices everything it was given", len(rows) == len(LIVE))

print("\n== mini contracts are a fraction of their parent, by the right factor ==")
for mini, parent, ratio in (("CRUDEOILM", "CRUDEOIL", 0.1), ("NATGASMINI", "NATURALGAS", 0.2),
                            ("ZINCMINI", "ZINC", 0.2), ("ALUMINI", "ALUMINIUM", 0.2),
                            ("LEADMINI", "LEAD", 0.2), ("GOLDM", "GOLD", 0.1)):
    got = contract_value(mini, LIVE[mini]) / contract_value(parent, LIVE[parent])
    check(f"{mini} is {ratio:.0%} of {parent}", abs(got - ratio) < 0.03, f"{got:.3f}")

print("\n== silver family is internally consistent ==")
# SILVERMIC is 1 kg. SILVERM is 5 kg, SILVER is 30 kg — so the ratios must hold exactly.
mic = contract_value("SILVERMIC", LIVE["SILVERMIC"])
check("SILVERM is ~5x SILVERMIC",
      abs(contract_value("SILVERM", LIVE["SILVERM"]) / mic - 5) < 0.2)
check("SILVER is ~30x SILVERMIC",
      abs(contract_value("SILVER", LIVE["SILVER"]) / mic - 30) < 1.0)
check("SILVER100 is quoted per 10g, so its value matches a 1 kg lot",
      abs(contract_value("SILVER100", LIVE["SILVER100"]) / mic - 1) < 0.05,
      f"₹{contract_value('SILVER100', LIVE['SILVER100']):,.0f} vs SILVERMIC ₹{mic:,.0f}")

print("\n== unspecified underlyings degrade honestly ==")
doc = spec_doc("KAPAS")
check("an underlying with no published spec reports verified:false", doc["verified"] is False)
check("...and says where its number came from", "broker" in doc["spec_source"].lower(), doc["spec_source"])
check("...and never claims a price unit it does not know", doc["price_unit"] == "unknown")
check("a specified one reports verified:true", spec_doc("CRUDEOIL")["verified"] is True)
check("multiplier never silently returns 1 for a known underlying",
      all(multiplier(s) > 1 for s in ("GOLD", "ZINC", "COPPER", "NATURALGAS", "CRUDEOIL")))

print("\n== ticks are converted out of paise ==")
check("a NATURALGAS future ticks at ₹0.10", tick_rupees({"tick_size": 10.0}) == 0.10)
check("a GOLD future ticks at ₹1", tick_rupees({"tick_size": 100.0}) == 1.0)
check("a missing tick falls back rather than crashing", tick_rupees({}) == 0.05)

print("\n== scrip-master parsing ==")
SCRIP = [
    {"token": "561496", "symbol": "NATURALGAS26AUG26FUT", "name": "NATURALGAS",
     "expiry": "26AUG2026", "strike": "0.000000", "lotsize": "1250",
     "instrumenttype": "FUTCOM", "exch_seg": "MCX", "tick_size": "10.000000"},
    {"token": "511016", "symbol": "SILVER28AUG26272000CE", "name": "SILVER",
     "expiry": "28AUG2026", "strike": "27200000.000000", "lotsize": "30",
     "instrumenttype": "OPTFUT", "exch_seg": "MCX", "tick_size": "50.000000"},
    {"token": "999", "symbol": "RELIANCE", "name": "RELIANCE", "expiry": "",
     "strike": "0", "lotsize": "1", "instrumenttype": "", "exch_seg": "NSE",
     "tick_size": "5"},
    {"token": "888", "symbol": "GOLDSPOT", "name": "GOLD", "expiry": "05OCT2026",
     "strike": "0", "lotsize": "1", "instrumenttype": "COMDTY", "exch_seg": "MCX",
     "tick_size": "100"},
]
built = build_rows(SCRIP)
by_class = {r["asset_class"] for r in built}
check("only MCX futures and options are taken", by_class == {"COMMODITY_FUTURE", "COMMODITY_OPTION"},
      str(sorted(by_class)))
check("NSE rows are ignored", not any(r["underlying_symbol"] == "RELIANCE" for r in built))
check("MCX spot (COMDTY) is ignored", len(built) == 2, f"{len(built)} rows")

fut = next(r for r in built if r["asset_class"] == "COMMODITY_FUTURE")
opt = next(r for r in built if r["asset_class"] == "COMMODITY_OPTION")
check("futures symbol matches the app's naming",
      fut["symbol"] == "NATURALGAS-26Aug2026-FUT", fut["symbol"])
check("option symbol matches the app's naming",
      opt["symbol"] == "SILVER-28Aug2026-272000-CE", opt["symbol"])
check("strikes are converted out of paise", opt["strike"] == 272000.0, str(opt["strike"]))
check("the real lot size is stamped, not 1", fut["lot_size"] == 1250 and opt["lot_size"] == 30,
      f"fut {fut['lot_size']}, opt {opt['lot_size']}")
check("the broker's own value is kept verbatim too", fut["angel_lotsize"] == 1250)
check("option type is read off the trading symbol", opt["option_type"] == "CE")
check("futures carry no strike or option type",
      fut["strike"] is None and fut["option_type"] is None)
check("angel routing fields are set", fut["angel_exchange"] == "MCX" and fut["angel_token"] == "561496")

check("expiry parses to ISO", _parse_expiry("26AUG2026") == "2026-08-26")
check("a malformed expiry is rejected, not guessed", _parse_expiry("NOTADATE") is None)
check("an empty expiry is rejected", _parse_expiry("") is None)

print("\n== position merge: add, reduce, flip ==")
base = {"side": "BUY", "lots": 2, "quantity": 2500, "entry_price": 260.0, "realized_pnl": 0.0}
add = _merge(base, "BUY", 2, 2500, 280.0)
check("adding averages the entry", add["entry_price"] == 270.0, str(add["entry_price"]))
check("adding sums the lots", add["lots"] == 4 and add["quantity"] == 5000)

red = _merge(base, "SELL", 1, 1250, 280.0)
check("reducing books realised P&L on the closed part",
      red["realized_pnl"] == 25000.0, str(red["realized_pnl"]))
check("reducing leaves the rest open", red["lots"] == 1 and red["quantity"] == 1250)

flat = _merge(base, "SELL", 2, 2500, 280.0)
check("closing exactly flattens the position", flat["status"] == "CLOSED" and flat["lots"] == 0)
check("closing books the whole gain", flat["realized_pnl"] == 50000.0, str(flat["realized_pnl"]))

flip = _merge(base, "SELL", 3, 3750, 280.0)
check("over-selling flips the side", flip["side"] == "SELL", flip["side"])
check("the flipped position is the excess only", flip["lots"] == 1 and flip["quantity"] == 1250)
check("the flip re-bases the entry at the new fill", flip["entry_price"] == 280.0)
check("the closed part is still booked", flip["realized_pnl"] == 50000.0, str(flip["realized_pnl"]))

short = {"side": "SELL", "lots": 1, "quantity": 1250, "entry_price": 280.0, "realized_pnl": 0.0}
cov = _merge(short, "BUY", 1, 1250, 260.0)
check("a short that buys back profits when price falls",
      cov["realized_pnl"] == 25000.0, str(cov["realized_pnl"]))

print("\n== the spec table covers what MCX actually lists options on ==")
WITH_OPTIONS = {"COPPER", "CRUDEOIL", "CRUDEOILM", "GOLD", "GOLDM", "NATGASMINI",
                "NATURALGAS", "SILVER", "SILVERM", "ZINC"}
missing = sorted(WITH_OPTIONS - set(CONTRACT_SPEC))
check("every options-bearing underlying has a published spec", not missing, str(missing))
check("mini contracts are covered",
      {"CRUDEOILM", "NATGASMINI", "ZINCMINI", "ALUMINI", "LEADMINI", "SILVERMIC",
       "GOLDM", "GOLDTEN", "GOLDPETAL"} <= set(CONTRACT_SPEC))

print(f"\n{'ALL CHECKS PASSED' if not FAILURES else 'FAILURES: ' + '; '.join(FAILURES)}")
sys.exit(1 if FAILURES else 0)
