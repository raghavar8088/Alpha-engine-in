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
for c in ["bars_collection", "instruments_collection", "stock_universe_collection"]:
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
spec = importlib.util.spec_from_file_location(
    "bs", r"d:/INDIAN MARKET/backend/app/services/bullish_stocks.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)

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

print("\n" + ("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
