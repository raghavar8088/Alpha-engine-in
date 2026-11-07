"""The money layer, on hand-worked trades.   python -I test_ledger.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ledger as L  # noqa: E402


def t(i, mkt, entry, unit, r_net, entry_t, exit_t, date="2026-11-09", side=1, **kw):
    d = {"_id": f"x{i}", "mkt": mkt, "sym": mkt, "side": side, "date": date, "exit_date": kw.pop("exit_date", date), "entry_t": entry_t,
         "exit_t": exit_t, "entry": entry, "exit": kw.pop("exit", entry), "stop": entry - unit, "target": None, "unit": unit, "r_net": r_net,
         "last": entry, "setup": "t", "open": exit_t is None}
    d.update(kw)
    return d


def fields(res, i):
    return res["fields"][f"x{i}"]


ok = True


def check(name, cond, detail=""):
    global ok
    print(("ok  " if cond else "FAIL"), name, detail)
    ok = ok and bool(cond)


# Nifty: 1% of 10L = 10,000. A 50-point stop risks 50 x 65 = 3,250 a lot, so 3 lots. Margin 12% x 25,000 x 65 = 1.95L a lot.
res = L.walk([t(1, "NIFTY", 25000.0, 50.0, 2.0, 1000, 2000)], {}, "2026-11-09")
check("nifty lots from 1% risk", fields(res, 1)["qty"] == 195, fields(res, 1))
check("nifty pnl = qty x r x unit", fields(res, 1)["pnl"] == 195 * 2.0 * 50.0)
check("equity includes it", res["summary"]["equity"] == 1_000_000 + 19500.0)

# A very tight stop would want many lots: the margin caps it at 5 (5 x 1.95L = 9.75L of the 10L).
res = L.walk([t(1, "NIFTY", 25000.0, 2.0, -1.0, 1000, 2000)], {}, "2026-11-09")
check("nifty margin cap", fields(res, 1)["qty"] == 5 * 65, fields(res, 1))

# A 300-point stop: one lot risks 19,500 (1.95%), more than the 1% budget but under the 5% floor: one lot.
res = L.walk([t(1, "NIFTY", 25000.0, 300.0, -1.0, 1000, 2000)], {}, "2026-11-09")
check("one-lot floor", fields(res, 1)["qty"] == 65, fields(res, 1))
# A 900-point unit: one lot risks 58,500 (5.85%): skipped.
res = L.walk([t(1, "NIFTY", 25000.0, 900.0, -1.0, 1000, 2000)], {}, "2026-11-09")
check("too wide for one lot", fields(res, 1)["skip"] == "below one lot", fields(res, 1))

# Two positions at once share the margin; the second gets what is free.
res = L.walk([t(1, "NIFTY", 25000.0, 5.0, 0.0, 1000, 5000), t(2, "BANKNIFTY", 60000.0, 5.0, 0.0, 2000, 6000)], {}, "2026-11-09")
check("margin is shared", fields(res, 1)["qty"] == 5 * 65 and fields(res, 2)["qty"] == 0, (fields(res, 1), fields(res, 2)))

# Equity compounds: a closed win raises the next trade's budget; a position still open does not.
res = L.walk([t(1, "EURUSD", 1.08, 0.002, 5.0, 1000, 2000), t(2, "EURUSD", 1.08, 0.002, 0.0, 3000, 4000)], {"2026-11-09": 88.0}, "2026-11-09")
q1, q2 = fields(res, 1)["qty"], fields(res, 2)["qty"]
check("usd sized through the rate", q1 == 56000.0, q1)            # 10,000 / (0.002 x 88) = 56,818 -> 56,000
check("compounds on closed profit", q2 > q1, (q1, q2))
check("usd pnl in rupees", abs(fields(res, 1)["pnl"] - 56000 * 5 * 0.002 * 88) < 0.01, fields(res, 1))

# An open position is unrealised, and its margin stays held.
res = L.walk([t(1, "XAUUSD", 4000.0, 10.0, 1.0, 1000, None)], {"2026-11-09": 88.0}, "2026-11-09")
s = res["summary"]
check("open position counted as unrealised", s["open"] == 1 and s["closed"] == 0 and s["unrealised"] == s["equity"] - 1_000_000 and s["realised"] == 0, s)
check("position listed", res["positions"][0]["sym"] == "XAUUSD" and res["positions"][0]["pnl"] == s["unrealised"])

# VWAP: Rs 2,500 risk, Rs 2.5 lakh notional cap, 5% of the signal bar's volume, the study's own charges.
d = t(1, "VWAP", 1000.0, 5.0, None, 1000, 2000, exit=1010.0, slip=0.0005, vol_cap=10000.0, vwap_costs=True)
res = L.walk([d], {}, "2026-11-09")
check("vwap risk sizing", fields(res, 1)["qty"] == 250, fields(res, 1))         # min(500, 250, 10000)
qty = 250.0
expected = L.vwap_net(1, qty, 1000.0, 1010.0, 0.0005)
check("vwap net uses the study's costs", abs(fields(res, 1)["pnl"] - round(expected, 2)) < 0.01 and expected < qty * 10, expected)
d = t(1, "VWAP", 1000.0, 5.0, None, 1000, 2000, exit=1010.0, slip=0.0005, vol_cap=7.0, vwap_costs=True)
check("vwap volume cap", fields(L.walk([d], {}, "2026-11-09"), 1)["qty"] == 7)

# The cost formula, by hand: 100 shares long at 1000, out at 1010, no slippage.
bv, sv = 100_000.0, 101_000.0
brok = 20.0 + 20.0
stt, exch, sebi, stamp = 0.00025 * sv, 0.0000297 * (bv + sv), 1e-6 * (bv + sv), 3e-5 * bv
gst = 0.18 * (brok + exch + sebi)
check("vwap_net by hand", abs(L.vwap_net(1, 100, 1000.0, 1010.0, 0.0) - (1000.0 - (brok + stt + exch + sebi + stamp + gst))) < 1e-6)

# NSE daily pool: 10% notional cap in a cash account.
res = L.walk([t(1, "NSED", 500.0, 5.0, 1.0, 1000, 2000)], {}, "2026-11-09")
check("daily stock notional cap", fields(res, 1)["qty"] == 200, fields(res, 1))  # 10,000/5 = 2000, capped at 1L/500 = 200

# Replays agree: the same trades in any order give the same account.
a = [t(1, "NIFTY", 25000.0, 50.0, 1.0, 1000, 2000), t(2, "NIFTY", 25000.0, 50.0, -1.0, 3000, 4000), t(3, "NIFTY", 25000.0, 50.0, 2.0, 5000, 6000)]
check("deterministic", L.walk(a, {}, "x")["summary"] == L.walk(list(reversed(a)), {}, "x")["summary"])

sys.exit(0 if ok else 1)
