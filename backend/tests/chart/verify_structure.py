"""Exercises the Phase 6 structural analysis by exec-ing the real function
definitions out of chart_data.py (which can't be imported directly here because
its module-level imports need motor/redis)."""

import ast
import math

SRC = r"d:\INDIAN MARKET\backend\app\services\chart_data.py"
WANTED_FUNCS = {"_swing_indices", "_cluster_zones", "_fit_line", "_describe_structure", "analyze_structure"}
WANTED_CONSTS = {"_SWING_WINDOW"}

tree = ast.parse(open(SRC, encoding="utf-8").read())
picked = []
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in WANTED_FUNCS:
        picked.append(node)
    elif isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in WANTED_CONSTS for t in node.targets
    ):
        picked.append(node)

missing = WANTED_FUNCS - {n.name for n in picked if isinstance(n, ast.FunctionDef)}
assert not missing, f"could not find in source: {missing}"

ns: dict = {}
exec(compile(ast.Module(body=picked, type_ignores=[]), SRC, "exec"), ns)

analyze_structure = ns["analyze_structure"]
_cluster_zones = ns["_cluster_zones"]
_fit_line = ns["_fit_line"]
_describe_structure = ns["_describe_structure"]
_swing_indices = ns["_swing_indices"]

failures = 0


def check(name, got, want):
    global failures
    ok = got == want
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got={got!r} want={want!r}")


def check_true(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")


# --- _swing_indices: a clean single peak -----------------------------------
vals = [1, 2, 3, 9, 3, 2, 1, 2, 3, 4]
highs = _swing_indices(vals, 0, len(vals), want_high=True)
check("swing high found at the peak", highs, [3])

lows_vals = [9, 8, 7, 1, 7, 8, 9, 8, 7, 6]
lows = _swing_indices(lows_vals, 0, len(lows_vals), want_high=False)
check("swing low found at the trough", lows, [3])

# --- _cluster_zones: three touches of ~100, two of ~120, one stray ---------
prices = [100.0, 100.4, 99.8, 120.0, 120.3, 141.0]
times = [10, 20, 30, 40, 50, 60]
zones = _cluster_zones(prices, times, tolerance=1.0, min_touches=2)
check("two zones survive the min-touch filter", len(zones), 2)
check("strongest zone is the 3-touch one", zones[0]["touches"], 3)
check_true("strongest zone price is the ~100 cluster mean",
           abs(zones[0]["price"] - 100.0667) < 0.01, f"got {zones[0]['price']}")
check("strongest zone carries its latest touch time", zones[0]["last_touch_time"], 30)
check("second zone has 2 touches", zones[1]["touches"], 2)
check_true("a single stray pivot forms no zone",
           all(abs(z["price"] - 141.0) > 1 for z in zones))

# tolerance actually widens clusters
wide = _cluster_zones(prices, times, tolerance=50.0, min_touches=2)
check("a huge tolerance collapses everything into one zone", len(wide), 1)

# --- _fit_line: exact fit on a perfectly linear ramp -----------------------
# values[i] = 2i + 5 at pivots 0,2,4  ->  endpoints must be exact
ramp = [2 * i + 5 for i in range(10)]
times10 = [1000 + 60 * i for i in range(10)]
line = _fit_line([0, 2, 4], ramp, times10)
check_true("fitted slope is exactly 2", abs(line["slope_per_bar"] - 2) < 1e-9, str(line["slope_per_bar"]))
check_true("fitted p1 price is exact", abs(line["p1"]["price"] - 5) < 1e-9, str(line["p1"]["price"]))
check_true("fitted p2 price is exact", abs(line["p2"]["price"] - 13) < 1e-9, str(line["p2"]["price"]))
check("fitted p1 time is the first pivot's", line["p1"]["time"], 1000)
check("fitted p2 time is the last pivot's", line["p2"]["time"], 1240)
check("fewer than two pivots yields no line", _fit_line([3], ramp, times10), None)

# an outlier must not swing the fit as far as a first-and-last join would
noisy = list(ramp)
noisy[2] = 100  # big outlier at an interior pivot
noisy_line = _fit_line([0, 2, 4, 6, 8], noisy, times10)
check_true("least squares dampens an interior outlier",
           noisy_line["slope_per_bar"] < 6, f"slope {noisy_line['slope_per_bar']}")

# --- _describe_structure ---------------------------------------------------
check("HH+HL reads as uptrend", _describe_structure([10, 12], [5, 7])["bias"], "uptrend")
check("LH+LL reads as downtrend", _describe_structure([12, 10], [7, 5])["bias"], "downtrend")
check("HL under a flat ceiling is compression", _describe_structure([12, 12], [5, 7])["bias"], "compression")
check("LH over a flat floor is compression", _describe_structure([12, 10], [5, 5])["bias"], "compression")
check("HH over a flat floor is compression", _describe_structure([10, 12], [5, 5])["bias"], "compression")
check("flat both sides is sideways", _describe_structure([10, 10], [5, 5])["bias"], "sideways")
check("HH+LL is expansion", _describe_structure([10, 12], [5, 3])["bias"], "expansion")
check("LH+HL is compression", _describe_structure([12, 10], [3, 5])["bias"], "compression")
check("flat ceiling with lower lows is downtrend", _describe_structure([10, 10], [5, 3])["bias"], "downtrend")
check("too few swings is unclear", _describe_structure([10], [5])["bias"], "unclear")

# --- analyze_structure: end to end ----------------------------------------
check_true("short series is refused",
           analyze_structure([1] * 5, [1] * 5, [1] * 5, list(range(5)))["available"] is False)

# Build a clean rising zig-zag: each leg higher than the last.
h, lo, c, t = [], [], [], []
price = 100.0
for leg in range(8):
    base = 100 + leg * 10
    for step in [0, 4, 8, 4, 0]:  # up then back down, forming pivots
        price = base + step
        h.append(price + 1)
        lo.append(price - 1)
        c.append(price)
        t.append(1_700_000_000 + 60 * len(t))

result = analyze_structure(h, lo, c, t, lookback=120)
check_true("rising zig-zag analyses", result["available"] is True)
check("structure reads as an uptrend", result["structure"]["bias"], "uptrend")
check_true("channel was fitted", result["channel"] is not None)
check_true("channel slopes upward",
           result["channel"]["upper"]["slope_per_bar"] > 0,
           str(result["channel"]["upper"]["slope_per_bar"]))
check_true("swing highs are reported", len(result["swing_highs"]) > 0)
check_true("swing lows are reported", len(result["swing_lows"]) > 0)
check("last_close is passed through", result["last_close"], c[-1])
check_true("zone lists are capped at 4",
           len(result["support_zones"]) <= 4 and len(result["resistance_zones"]) <= 4)

# A flat, repeatedly-tested level should produce a high-touch zone.
fh = [101 if i % 2 == 0 else 100 for i in range(60)]
fl = [99 if i % 2 == 0 else 100 for i in range(60)]
fc = [100] * 60
ft = [1_700_000_000 + 60 * i for i in range(60)]
flat = analyze_structure(fh, fl, fc, ft, lookback=60)
check_true("a repeatedly-tested flat level yields a multi-touch zone",
           bool(flat["resistance_zones"]) and flat["resistance_zones"][0]["touches"] >= 3,
           str(flat["resistance_zones"][:1]))

# Downtrend must read as one.
dh, dl, dc, dt = [], [], [], []
for leg in range(8):
    base = 200 - leg * 10
    for step in [0, 4, 8, 4, 0]:
        p = base - step
        dh.append(p + 1)
        dl.append(p - 1)
        dc.append(p)
        dt.append(1_700_000_000 + 60 * len(dt))
down = analyze_structure(dh, dl, dc, dt, lookback=120)
check("falling zig-zag reads as a downtrend", down["structure"]["bias"], "downtrend")
check_true("downtrend channel slopes down",
           down["channel"]["lower"]["slope_per_bar"] < 0,
           str(down["channel"]["lower"]["slope_per_bar"]))

# Tolerance scales with price magnitude, not absolute rupees: the same shape at
# option-premium scale must still cluster.
sh = [x / 100 for x in fh]
sl = [x / 100 for x in fl]
sc = [x / 100 for x in fc]
small = analyze_structure(sh, sl, sc, ft, lookback=60)
check_true("clustering still works at sub-rupee premium scale",
           bool(small["resistance_zones"]),
           str(small["resistance_zones"][:1]))

print()
print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
raise SystemExit(0 if failures == 0 else 1)
