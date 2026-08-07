"""Verify the Bullish Stocks screener's indicator math without touching Mongo or Angel.

Every signal this screen trades on is computed here from plain lists, so the maths can be
checked against series whose answer is known by construction: a pure uptrend, a pure
downtrend, a flat range, an accelerating breakout and a rollover.

Run:  python backend/tests/bullish_stocks/verify_indicators.py

Two things this file exists to pin down, both of which bit during development:

  * The higher-high/higher-low test must not use fractal +/-k swing pivots. On a stock
    trending hard with shallow pullbacks — exactly what this screen looks for — no bar is
    ever the extreme of its own window, so the pivot version found ZERO swings and
    silently rejected every candidate.
  * MACD only sits above its signal line when momentum is ACCELERATING. On a perfectly
    linear ramp the MACD converges to a constant and its own EMA settles just above it;
    that is correct maths, not a crossover, so synthetic test data has to curve.
"""

import sys, types

# Stub the heavy module-level imports so the service can be imported standalone.
for name in ["app", "app.core", "app.core.db", "app.services", "app.services.angel_client",
             "app.services.stocks_range", "tradingai_broker_clients",
             "tradingai_broker_clients.angel", "tradingai_broker_clients.angel.auth"]:
    sys.modules.setdefault(name, types.ModuleType(name))

db = sys.modules["app.core.db"]
for c in ["bars_collection", "instruments_collection", "stock_universe_collection",
          "stock_highs_collection", "stock_fundamentals_collection"]:
    setattr(db, c, object())
ac = sys.modules["app.services.angel_client"]
ac.AngelAPIError = type("AngelAPIError", (Exception,), {})
ac.angel_client = object()
sr = sys.modules["app.services.stocks_range"]
sr.INDEX_LABELS = {"nifty50": "Nifty 50"}
sr.QUOTE_PACE_SECONDS = 0.15
auth = sys.modules["tradingai_broker_clients.angel.auth"]
auth.batches = lambda x: []

sys.path.insert(0, r"d:/INDIAN MARKET/backend")
import importlib.util

SERVICES = r"d:/INDIAN MARKET/backend/app/services"


def _load(name: str, path: str):
    """Load a real service module by path and register it under its dotted name, so the
    modules that import it resolve against the real thing rather than the stub package."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# fundamentals and highs first — bullish_stocks imports both at module scope
sf = _load("app.services.stock_fundamentals", f"{SERVICES}/stock_fundamentals.py")
_load("app.services.stock_highs", f"{SERVICES}/stock_highs.py")
bs = _load("app.services.bullish_stocks", f"{SERVICES}/bullish_stocks.py")

fails = []
def check(label, cond, extra=""):
    print(f"{'PASS' if cond else 'FAIL'}  {label} {extra}")
    if not cond:
        fails.append(label)

# ---- EMA alignment -------------------------------------------------------------
vals = [float(i) for i in range(1, 31)]
e = bs._ema_series(vals, 9)
check("EMA series length aligns to vals[period-1:]", len(e) == len(vals) - 9 + 1,
      f"(got {len(e)}, want {len(vals)-8})")
check("EMA seed is the first-9 SMA", abs(e[0] - sum(vals[:9]) / 9) < 1e-9)
check("EMA of a rising series trails price", e[-1] < vals[-1])

# ---- RSI bounds ----------------------------------------------------------------
check("RSI of a pure uptrend is 100", bs._rsi([float(i) for i in range(1, 40)]) == 100.0)
check("RSI of a pure downtrend is ~0", bs._rsi([float(i) for i in range(40, 1, -1)]) < 1e-6)
flat = bs._rsi([10.0 + (1 if i % 2 else -1) for i in range(40)])
check("RSI of a chop oscillates near 50", flat is not None and 30 < flat < 70, f"(got {flat:.1f})")

# ---- MACD alignment (the fast-series trim is easy to get wrong) -----------------
closes = [float(i) for i in range(1, 120)]
line, sig = bs._macd(closes)
fast = bs._ema_series(closes, bs.MACD_FAST)[bs.MACD_SLOW - bs.MACD_FAST:]
slow = bs._ema_series(closes, bs.MACD_SLOW)
check("MACD fast/slow trimmed to equal length", len(fast) == len(slow),
      f"({len(fast)} vs {len(slow)})")
check("MACD line positive in an uptrend", line is not None and line > 0, f"(got {line:.3f})")
# the last MACD value must equal ema12 - ema26 on the SAME final bar
check("MACD equals ema12-ema26 on the last bar", abs(line - (fast[-1] - slow[-1])) < 1e-9)
# On a PERFECTLY linear ramp the MACD converges down to a constant, so its own EMA
# legitimately sits just above it — that is correct maths, not a crossover. Momentum has
# to be ACCELERATING for macd > signal, so test that instead.
accel = []
p = 100.0
for i in range(120):
    p += 1 + i * 0.05
    accel.append(p)
aline, asig = bs._macd(accel)
check("MACD above signal when momentum accelerates", aline > asig, f"({aline:.2f} > {asig:.2f})")
# Decisive check: the signal line must literally BE the 9-EMA of the MACD line.
# Rebuild the whole MACD line independently and take its EMA9.
_f = bs._ema_series(closes, bs.MACD_FAST)[bs.MACD_SLOW - bs.MACD_FAST:]
_s = bs._ema_series(closes, bs.MACD_SLOW)
_line_full = [a - b for a, b in zip(_f, _s)]
_sig_full = bs._ema_series(_line_full, bs.MACD_SIGNAL)
check("signal line is exactly EMA9(macd line)", abs(sig - _sig_full[-1]) < 1e-9)

# A series that rises then rolls over must lose the crossover.
rollover = []
p = 100.0
for i in range(90):
    p += 2.0
    rollover.append(p)
for i in range(25):
    p -= 3.0
    rollover.append(p)
rline, rsig = bs._macd(rollover)
check("MACD drops below signal after a rollover", rline < rsig, f"({rline:.2f} < {rsig:.2f})")

# ---- 9 EMA streak --------------------------------------------------------------
up = [float(i) for i in range(1, 60)]
check("EMA9 streak counts a full uptrend", bs._ema9_streak(up) == len(up) - 8,
      f"(got {bs._ema9_streak(up)})")
broken = up[:-1] + [1.0]  # last bar crashes below the EMA
check("EMA9 streak resets on a break below", bs._ema9_streak(broken) == 0)

# ---- swing structure -----------------------------------------------------------
check("_ascending true for rising pivots", bs._ascending([1.0, 2.0, 3.0]))
check("_ascending false for a lower high", not bs._ascending([1.0, 3.0, 2.0]))
check("_ascending false with <2 points", not bs._ascending([5.0]))

# a zig-zag uptrend: each leg higher than the last
h, l, c, v = [], [], [], []
base = 100.0
for leg in range(8):
    for step in range(6):       # up leg
        base += 2.0
        h.append(base + 1); l.append(base - 1); c.append(base); v.append(1000.0)
    for step in range(3):       # shallow pullback (holds above the prior low)
        base -= 1.0
        h.append(base + 1); l.append(base - 1); c.append(base); v.append(900.0)
check("zig-zag uptrend reads as higher highs + higher lows", bs._higher_structure(h, l),
      f"(bars={len(h)})")
# a flat range and a downtrend must NOT read as higher highs / higher lows
flat_h = [101.0 + (i % 5) for i in range(80)]
flat_l = [99.0 - (i % 5) for i in range(80)]
check("flat range fails the structure test", not bs._higher_structure(flat_h, flat_l))
down_h = [200.0 - i for i in range(80)]
down_l = [198.0 - i for i in range(80)]
check("downtrend fails the structure test", not bs._higher_structure(down_h, down_l))
check("structure test needs enough history", not bs._higher_structure(h[:20], l[:20]))

# ---- _evaluate end-to-end on a long synthetic uptrend ---------------------------
# A realistic breakout profile: the up-legs get progressively stronger (momentum
# ACCELERATING into the highs), which is what actually produces a MACD crossover. A
# perfectly uniform ramp makes MACD converge to a constant and its own EMA sit just
# above it — correct maths, but a shape no real breakout has.
h, l, c, v = [], [], [], []
base = 100.0
for leg in range(40):
    step = 1.0 + leg * 0.06
    for _ in range(6):
        base += step
        h.append(base + 0.8); l.append(base - 0.8); c.append(base); v.append(1000.0)
    for _ in range(3):
        base -= step * 0.45
        h.append(base + 0.8); l.append(base - 0.8); c.append(base); v.append(900.0)
# finish on a fresh up-leg, so the series ends AT its highs like a real breakout
# (ending mid-pullback legitimately costs the MACD crossover)
for _ in range(6):
    base += 3.4
    h.append(base + 0.8); l.append(base - 0.8); c.append(base); v.append(1200.0)
v[-1] = 5000.0  # volume breakout on the last bar
ltp = c[-1]
ev = bs._evaluate(c, h, l, v, ltp)
check("_evaluate returns a result with enough history", ev is not None, f"(bars={len(c)})")
if ev:
    check("  sig_ema9 (month above 9 EMA)", ev["sig_ema9"], f"(streak={ev['ema9_days']})")
    check("  sig_ma_stack (50>200, price above both)", ev["sig_ma_stack"])
    check("  sig_near_high", ev["sig_near_high"], f"({ev['pct_from_52w_high']}% from 52W high)")
    check("  sig_structure (HH/HL)", ev["sig_structure"])
    check("  sig_rsi", ev["sig_rsi"], f"(rsi={ev['rsi']})")
    check("  sig_macd", ev["sig_macd"], f"(macd={ev['macd']} sig={ev['macd_signal']})")
    check("  sig_volume", ev["sig_volume"], f"(x{ev['vol_x_avg']})")

# short history must be rejected, not crash
check("_evaluate rejects short history", bs._evaluate(c[-50:], h[-50:], l[-50:], v[-50:], ltp) is None)
check("_evaluate rejects a missing ltp", bs._evaluate(c, h, l, v, None) is None)

# ---- a downtrend must NOT qualify ----------------------------------------------
h2, l2, c2, v2 = [], [], [], []
base = 300.0
for _ in range(300):
    base -= 0.5
    h2.append(base + 0.8); l2.append(base - 0.8); c2.append(base); v2.append(1000.0)
ev2 = bs._evaluate(c2, h2, l2, v2, c2[-1])
check("downtrend fails ema9", ev2 and not ev2["sig_ema9"])
check("downtrend fails MA stack", ev2 and not ev2["sig_ma_stack"])
check("downtrend fails near-high", ev2 and not ev2["sig_near_high"])
check("downtrend fails RSI", ev2 and not ev2["sig_rsi"])

# ---- trade plan arithmetic ------------------------------------------------------
ltp = 250.0
check("stop is 10% below entry", abs(round(ltp * (1 - bs.STOP_PCT), 2) - 225.0) < 1e-9)
check("target is 10% above entry", abs(round(ltp * (1 + bs.TARGET_PCT), 2) - 275.0) < 1e-9)
check("trail is 10% below the running high", abs(round(300.0 * (1 - bs.TRAIL_PCT), 2) - 270.0) < 1e-9)

# ---- all-time-high signal -------------------------------------------------------
ev_ath = bs._evaluate(c, h, l, v, ltp, all_time_high=ltp * 0.99)   # price ABOVE the old ATH
check("at an all-time high fires the ATH signal", ev_ath and ev_ath["sig_all_time_high"])
check("ATH distance is positive when price is above it",
      ev_ath and ev_ath["pct_from_ath"] > 0, f"({ev_ath['pct_from_ath']}%)")
ev_far = bs._evaluate(c, h, l, v, ltp, all_time_high=ltp * 2.0)    # far below the old ATH
check("far below the ATH does not fire", ev_far and not ev_far["sig_all_time_high"])
check("ATH distance is negative when price is below it",
      ev_far and ev_far["pct_from_ath"] < 0, f"({ev_far['pct_from_ath']}%)")
ev_none = bs._evaluate(c, h, l, v, ltp, all_time_high=None)
check("a missing ATH never fires the signal", ev_none and not ev_none["sig_all_time_high"])
check("a missing ATH reports no distance rather than guessing",
      ev_none and ev_none["pct_from_ath"] is None and ev_none["all_time_high"] is None)
# the 52-week signal must be independent of the all-time one
check("52-week signal unaffected by the ATH input",
      ev_ath["sig_near_high"] == ev_far["sig_near_high"] == ev_none["sig_near_high"])

# ---- fundamental grading (pure function, no network) ----------------------------
strong = sf.grade({"revenue_growth": 0.22, "earnings_growth": 0.30, "profit_margin": 0.18,
                   "debt_to_equity": 20.0, "roe": 0.25, "held_institutions": 0.30,
                   "analyst_rec": "buy"})
check("a strong business scores 6/6", strong["fundamental_score"] == 6, f"(got {strong['fundamental_score']})")
check("strong business is flagged analyst-bullish", strong["analyst_bullish"])

weak = sf.grade({"revenue_growth": -0.10, "earnings_growth": -0.20, "profit_margin": 0.01,
                 "debt_to_equity": 400.0, "roe": 0.02, "held_institutions": 0.001,
                 "analyst_rec": "sell"})
check("a weak business scores 0/6", weak["fundamental_score"] == 0, f"(got {weak['fundamental_score']})")
check("weak business is not analyst-bullish", not weak["analyst_bullish"])

missing = sf.grade(None)
check("no fundamentals => ungraded, not failed", missing["fundamental_score"] is None
      and missing["fundamentals_known"] is False)
partial = sf.grade({"revenue_growth": 0.20})
check("partial data grades only what exists", partial["fundamental_score"] == 1
      and partial["fundamentals_known"] is True, f"(got {partial['fundamental_score']})")
check("None fields never crash the grader", sf.grade({"revenue_growth": None, "roe": None})
      ["fundamental_score"] == 0)
# debt is the one "lower is better" check — make sure the comparison isn't inverted
check("low debt passes, high debt fails",
      sf.grade({"debt_to_equity": 10.0})["fund_debt"] is True
      and sf.grade({"debt_to_equity": 900.0})["fund_debt"] is False)

# ---- NaN guard (yfinance hands back NaN for missing numerics) --------------------
check("_num rejects NaN", sf._num(float("nan")) is None)
check("_num rejects junk", sf._num("n/a") is None and sf._num(None) is None)
check("_num accepts real numbers", sf._num("12.5") == 12.5)

print("\n" + ("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
