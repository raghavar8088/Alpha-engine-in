"""Two questions an option BUYER must answer, on two years of NIFTY 5m bars and India VIX:

A. Volatility. With no direction edge, a bought option is a bet that NIFTY moves MORE than its
   price implies. Is realized intraday variance (09:45->15:15) above the variance India VIX
   implies, on average or on predictable days? Features known at 09:45: VIX level and change,
   gap, the first-30-minute range, recent realized variance, days to expiry, weekday.
   Economic test: an ATM straddle (nearest weekly and next week's) bought 09:45, sold 15:15,
   priced with the model calibrated on the desk's real trades, after fees and spread.
B. Direction from price: NIFTY's own two-sided opening-range break (the one rule that held up
   for stocks), through futures and options.
"""
import json
import math
import statistics
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, timedelta

sys.argv = sys.argv[:1]
from pl_replay import (IST, LOT, N5, SPREAD, TD, T_years, bs, expiry_key, fees, fut_cost, ist, ivx, kdate,  # noqa: E402
                       mins, n5t, vix_at)

import numpy as np  # noqa: E402


def day_rows(k):
    a = bisect_left(n5t, k * 86400 - 19800)
    b = bisect_left(n5t, (k + 1) * 86400 - 19800)
    return N5[a:b]


def period(k):
    d = kdate(k)
    return "explore" if d <= date(2025, 12, 31) else "confirm"


days = []
prev_close = None
rv_hist = []
for k in TD:
    rows = day_rows(k)
    if len(rows) < 70 or mins(rows[0][0]) != 555:
        prev_close = rows[-1][4] if rows else prev_close
        continue
    by = {mins(r[0]): r for r in rows}
    if 580 not in by or 910 not in by or prev_close is None:
        prev_close = rows[-1][4]
        continue
    o = rows[0][1]
    first = [r for r in rows if mins(r[0]) < 585]
    hi30, lo30 = max(r[2] for r in first), min(r[3] for r in first)
    s945 = by[580][4]
    e945 = k * 86400 - 19800 + 585 * 60
    e1515 = k * 86400 - 19800 + 915 * 60
    rest = [r for r in rows if 585 <= mins(r[0]) < 915]
    rets = [math.log(rest[i][4] / rest[i - 1][4]) for i in range(1, len(rest))]
    if rest:
        rets.insert(0, math.log(rest[0][4] / s945))
    rv = sum(x * x for x in rets)
    full = [math.log(rows[i][4] / rows[i - 1][4]) for i in range(1, len(rows))]
    rv_day = sum(x * x for x in full)
    v = vix_at(e945)
    vprev = vix_at(k * 86400 - 19800 + 555 * 60)       # last VIX bar before today's open
    s1515 = next((r[4] for r in reversed(rows) if mins(r[0]) < 915), None)
    if not v or not vprev or not s1515:
        prev_close = rows[-1][4]
        continue
    xk = expiry_key(k)
    # implied variance of the 09:45-15:15 window, trading-time convention (330 of 375 minutes)
    iv_win = (v ** 2) * (330 / 375) / 252
    # the straddle, both expiries
    st = {}
    for lab, x in (("wk", xk), ("nw", expiry_key(k, plus_week=True))):
        K = round(s945 / 50) * 50
        dte = x - k
        sg0, sg1 = v * ivx(dte, 9), v * ivx(dte, 15)
        c0, p0 = bs(s945, K, T_years(e945, x), sg0, True), bs(s945, K, T_years(e945, x), sg0, False)
        v1 = vix_at(e1515) or v
        sg1 = v1 * ivx(dte, 15)
        c1, p1 = bs(s1515, K, T_years(e1515, x), sg1, True), bs(s1515, K, T_years(e1515, x), sg1, False)
        st[lab] = (c1 + p1 - c0 - p0 - 4 * SPREAD) * LOT - fees(c0, c1) - fees(p0, p1)
        st[lab + "_prem"] = c0 + p0
    days.append({"k": k, "vix": v, "dvix": v / vprev - 1, "gap": abs(o / prev_close - 1), "r30": (hi30 - lo30) / o,
                 "rv": rv, "iv": iv_win, "ratio": rv / iv_win, "rv_prev": rv_hist[-1] if rv_hist else None,
                 "rv5": statistics.mean(rv_hist[-5:]) if len(rv_hist) >= 5 else None, "dte": xk - k,
                 "wd": kdate(k).weekday(), "st_wk": st["wk"], "st_nw": st["nw"], "prem_wk": st["wk_prem"],
                 "o": o, "hi30": hi30, "lo30": lo30, "s945": s945, "s1515": s1515, "rows": rest})
    rv_hist.append(rv_day)
    prev_close = rows[-1][4]

print(f"{len(days)} sessions {kdate(days[0]['k'])}..{kdate(days[-1]['k'])}")
# ── A. realized vs implied ──
for per in ("explore", "confirm"):
    xs = [d for d in days if period(d["k"]) == per]
    print(f"\n{per}: realized/implied variance 09:45-15:15: median {statistics.median(d['ratio'] for d in xs):.2f}, "
          f"mean {statistics.mean(d['ratio'] for d in xs):.2f}; days realized > implied {sum(1 for d in xs if d['ratio'] > 1) / len(xs):.2f}")
    print(f"   ATM straddle 09:45->15:15 per lot: weekly {statistics.mean(d['st_wk'] for d in xs):+.0f} "
          f"(win {sum(1 for d in xs if d['st_wk'] > 0) / len(xs):.2f}), next week {statistics.mean(d['st_nw'] for d in xs):+.0f} "
          f"(win {sum(1 for d in xs if d['st_nw'] > 0) / len(xs):.2f})")
    for dte in sorted({min(d['dte'], 4) for d in xs}):
        ys = [d for d in xs if min(d["dte"], 4) == dte]
        print(f"     dte {dte}{'+' if dte == 4 else ''}: n {len(ys)}, ratio median {statistics.median(d['ratio'] for d in ys):.2f}, "
              f"weekly straddle {statistics.mean(d['st_wk'] for d in ys):+.0f}")


# features -> log(ratio): does anything known at 09:45 predict a big rest-of-day relative to the price?
def feats(d):
    return [math.log(d["vix"]), d["dvix"], d["gap"] * 100, d["r30"] * 100, math.log(d["rv_prev"] / d["iv"]),
            math.log(d["rv5"] / d["iv"]), 1.0 if d["dte"] == 0 else 0.0, 1.0]
names = ["log VIX", "VIX change", "|gap| %", "first-30 range %", "log prev-day RV/IV", "log 5-day RV/IV", "expiry day"]
ok = [d for d in days if d["rv_prev"] and d["rv5"]]
ex = [d for d in ok if period(d["k"]) == "explore"]
cf = [d for d in ok if period(d["k"]) == "confirm"]
X = np.array([feats(d) for d in ex])
y = np.array([math.log(d["ratio"]) for d in ex])
w = np.linalg.lstsq(X, y, rcond=None)[0]
print("\nlog(realized/implied) on 09:45 features, fitted on explore:", {n: round(float(c), 3) for n, c in zip(names + ['const'], w)})
for lab, xs in (("explore", ex), ("confirm", cf)):
    pr = np.array([float(np.dot(feats(d), w)) for d in xs])
    act = np.array([math.log(d["ratio"]) for d in xs])
    corr = float(np.corrcoef(pr, act)[0, 1])
    order = np.argsort(pr)
    q = len(xs) // 5
    print(f"  {lab}: corr(predicted, actual) {corr:+.3f}")
    for qi in range(5):
        sel = [xs[i] for i in order[qi * q:(qi + 1) * q if qi < 4 else len(xs)]]
        print(f"     quintile {qi + 1} of predicted RV/IV: actual ratio median {statistics.median(d['ratio'] for d in sel):.2f}, "
              f"weekly straddle {statistics.mean(d['st_wk'] for d in sel):+6.0f} (win {sum(1 for d in sel if d['st_wk'] > 0) / len(sel):.2f}), "
              f"next-week {statistics.mean(d['st_nw'] for d in sel):+6.0f}")

# ── B. NIFTY's own opening-range break ──
print("\nNIFTY OPENING-RANGE BREAK (09:15-09:45), first touch after 09:45, stop at the other edge, exit 15:15:")
res = defaultdict(list)
for d in days:
    hi, lo = d["hi30"], d["lo30"]
    side = entry = None
    for r in d["rows"]:
        up, dn = r[2] > hi, r[3] < lo
        if up and dn:
            break
        if up or dn:
            side = 1 if up else -1
            entry = (max(hi, r[1]) if up else min(lo, r[1]))
            et = r[0]
            break
    if side is None:
        continue
    stop = lo if side > 0 else hi
    exitp = None
    for r in d["rows"]:
        if r[0] <= et:
            continue
        if (side > 0 and r[3] <= stop) or (side < 0 and r[2] >= stop):
            exitp = stop
            break
    stopped = exitp is not None
    exitp = exitp if stopped else d["s1515"]
    pts = side * (exitp - entry) - 1.0                      # 0.5 pt slippage each side
    res[period(d["k"])].append({"pts": pts, "bp": pts / entry * 1e4, "fut": pts * LOT - fut_cost(entry, exitp) + 0.5 * LOT * 2,
                                "stopped": stopped, "vix": d["vix"], "r30": d["r30"]})
for per, xs in res.items():
    print(f"  {per}: {len(xs)} trades, {statistics.mean(x['bp'] for x in xs):+.2f} bp/trade gross of fees, futures net "
          f"{statistics.mean(x['fut'] for x in xs):+.0f}/lot, stopped {sum(1 for x in xs if x['stopped']) / len(xs):.2f}")
    for lab, f in (("first-30 range above median", lambda x, m: x["r30"] > m), ("VIX above median", lambda x, m: x["vix"] > m)):
        key = "r30" if "range" in lab else "vix"
        m = statistics.median(x[key] for x in xs)
        a = [x for x in xs if f(x, m)]
        b = [x for x in xs if not f(x, m)]
        print(f"     {lab}: {statistics.mean(x['bp'] for x in a):+.2f} bp vs {statistics.mean(x['bp'] for x in b):+.2f} bp")
