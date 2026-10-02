"""H1 (volatility-timed long straddle) under the corrected premium model, and its frozen rule.

Signal (known at 09:45; same features as the research): log VIX, VIX change since yesterday's
close, |gap| %, first-30-minute range %, log(prev-day RV / IV window), log(5-day RV / IV window),
expiry-day flag -> predicted log(realized / implied variance, 09:45-15:15). Weights fitted on
EXPLORE (to 2025-12-31) only; the trade threshold = the 60th percentile of the explore
predictions (top 40% of days). Frozen here for pre-registration.

Trade: ATM straddle of NEXT WEEK's expiry (the weekly after the current one), bought 09:45 at
the ask, sold 15:15 at the bid, 1 lot (65) per leg.
Pricing: variance clock = trading minutes + 0.2 session per calendar night (fitted on the
desk's real trades); IV = India VIX at the time x 0.888 (the fitted 7-20 day ratio), the same
ratio at entry and exit (IV moves only with VIX - hourly ratio noise would swamp a straddle).
Costs: fees on both legs, spread SPREAD_PTS per leg per side.
"""
import json
import math
import statistics
import sys
from datetime import date, datetime, timedelta

sys.argv = sys.argv[:1]
import pl_vol as V  # noqa: E402  days table + features (pl_vol's own explore fit is ignored)
from pl_replay import LOT, IST, bs, expiry_key, fees, kdate  # noqa: E402

import numpy as np  # noqa: E402

W = 0.2
RATIO = 0.888
SPREAD_PTS = 0.5
TDS = sorted({kdate(d["k"]) for d in V.days})
TDSET = set(TDS)


def T_clock(t0, exp):
    if exp <= t0:
        return 1e-6
    mins = 0.0
    d = t0.date()
    while d <= exp.date():
        if (d in TDSET) if d <= TDS[-1] else d.weekday() < 5:
            o = datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST)
            c = datetime(d.year, d.month, d.day, 15, 30, tzinfo=IST)
            a, b = max(o, t0), min(c, exp)
            if b > a:
                mins += (b - a).total_seconds() / 60
        if d < exp.date():
            mins += W * 375
        d += timedelta(days=1)
    return max(mins, 1.0) / ((252 + 365 * W) * 375)


def straddle(d):
    k = d["k"]
    xk = expiry_key(k, plus_week=True)
    exp = datetime.combine(kdate(xk), datetime.min.time()).replace(hour=15, minute=30, tzinfo=IST)
    t0 = datetime.combine(kdate(k), datetime.min.time()).replace(hour=9, minute=45, tzinfo=IST)
    t1 = t0.replace(hour=15, minute=15)
    S0, S1 = d["s945"], d["s1515"]
    K = round(S0 / 50) * 50
    v0 = d["vix"]
    v1 = V.vix_at(int(t1.timestamp())) or v0
    T0, T1 = T_clock(t0, exp), T_clock(t1, exp)
    c0, p0 = bs(S0, K, T0, v0 * RATIO, True), bs(S0, K, T0, v0 * RATIO, False)
    c1, p1 = bs(S1, K, T1, v1 * RATIO, True), bs(S1, K, T1, v1 * RATIO, False)
    net = (c1 + p1 - c0 - p0 - 4 * SPREAD_PTS) * LOT - fees(c0 + SPREAD_PTS, c1 - SPREAD_PTS) - fees(p0 + SPREAD_PTS, p1 - SPREAD_PTS)
    return net, c0 + p0, (xk - k)


ok = [d for d in V.days if d["rv_prev"] and d["rv5"]]
for d in ok:
    d["h1_net"], d["h1_prem"], d["h1_dte"] = straddle(d)
ex = [d for d in ok if kdate(d["k"]) <= date(2025, 12, 31)]
cf = [d for d in ok if kdate(d["k"]) > date(2025, 12, 31)]
X = np.array([V.feats(d) for d in ex])
y = np.array([math.log(d["ratio"]) for d in ex])
w = np.linalg.lstsq(X, y, rcond=None)[0]
pred = {d["k"]: float(np.dot(V.feats(d), w)) for d in ok}
thr = float(np.quantile([pred[d["k"]] for d in ex], 0.6))
print("frozen weights:", [round(float(x), 4) for x in w], "threshold (60th pct of explore):", round(thr, 4))
for lab, xs in (("explore", ex), ("confirm", cf)):
    on = [d for d in xs if pred[d["k"]] >= thr]
    off = [d for d in xs if pred[d["k"]] < thr]
    corr = float(np.corrcoef([pred[d["k"]] for d in xs], [math.log(d["ratio"]) for d in xs])[0, 1])
    t_on = statistics.mean(d["h1_net"] for d in on) / (statistics.stdev(d["h1_net"] for d in on) / math.sqrt(len(on)))
    print(f"{lab}: corr(pred, actual log RV/IV) {corr:+.3f}; TRADED days {len(on)}: net/day {statistics.mean(d['h1_net'] for d in on):+.0f} "
          f"(sd {statistics.stdev(d['h1_net'] for d in on):.0f}, t {t_on:+.2f}, win {sum(1 for d in on if d['h1_net'] > 0) / len(on):.2f}); "
          f"SKIPPED days {len(off)}: {statistics.mean(d['h1_net'] for d in off):+.0f}; straddle cost median Rs{statistics.median(d['h1_prem'] for d in on) * LOT:,.0f}")
allon = [d for d in ok if pred[d["k"]] >= thr]
json.dump({"features": ["log VIX", "VIX change since previous close", "|gap| %", "first-30-minute range %",
                        "log(prev-day RV / IV window)", "log(5-day RV / IV window)", "expiry day"],
           "weights": [float(x) for x in w], "threshold": thr,
           "explore": {"traded": len([d for d in ex if pred[d['k']] >= thr]),
                       "net_mean": statistics.mean(d["h1_net"] for d in ex if pred[d["k"]] >= thr)},
           "confirm": {"traded": len([d for d in cf if pred[d['k']] >= thr]),
                       "net_mean": statistics.mean(d["h1_net"] for d in cf if pred[d["k"]] >= thr)},
           "sd": statistics.stdev(d["h1_net"] for d in allon)}, open("h1_frozen.json", "w"), indent=1)
