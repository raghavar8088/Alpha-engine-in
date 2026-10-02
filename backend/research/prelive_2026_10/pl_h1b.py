"""Overnight variant: ATM next-week straddle bought 15:15, sold next session 09:30 (W=0.2 clock,
IV = VIX x 0.888 at each time). Unconditional, and on days the 09:45 model flagged high."""
import math, statistics, sys
from bisect import bisect_right
from datetime import date, datetime, timedelta
sys.argv = sys.argv[:1]
import pl_h1 as H
from pl_replay import LOT, IST, bs, expiry_key, fees, kdate, N5, n5t
ok = H.ok
nxt = {ok[i]["k"]: ok[i + 1] for i in range(len(ok) - 1) if ok[i + 1]["k"] - ok[i]["k"] <= 4}
def spot(e):
    i = bisect_right(n5t, e - 300) - 1
    return N5[i][4]
res = []
for d in ok:
    n = nxt.get(d["k"])
    if not n:
        continue
    k = d["k"]
    xk = expiry_key(k, plus_week=True)
    exp = datetime.combine(kdate(xk), datetime.min.time()).replace(hour=15, minute=30, tzinfo=IST)
    t0 = datetime.combine(kdate(k), datetime.min.time()).replace(hour=15, minute=15, tzinfo=IST)
    t1 = datetime.combine(kdate(n["k"]), datetime.min.time()).replace(hour=9, minute=30, tzinfo=IST)
    S0, S1 = spot(int(t0.timestamp())), spot(int(t1.timestamp()))
    v0 = H.V.vix_at(int(t0.timestamp())); v1 = H.V.vix_at(int(t1.timestamp()))
    if not (v0 and v1):
        continue
    K = round(S0 / 50) * 50
    T0, T1 = H.T_clock(t0, exp), H.T_clock(t1, exp)
    c0, p0 = bs(S0, K, T0, v0 * H.RATIO, True), bs(S0, K, T0, v0 * H.RATIO, False)
    c1, p1 = bs(S1, K, T1, v1 * H.RATIO, True), bs(S1, K, T1, v1 * H.RATIO, False)
    gross = (c1 + p1 - c0 - p0) * LOT
    net = gross - 4 * H.SPREAD_PTS * LOT - fees(c0, c1) - fees(p0, p1)
    res.append({"k": k, "net": net, "gross": gross, "flag": H.pred[k] >= H.thr, "gap_bp": abs(S1 / S0 - 1) * 1e4,
                "vixchg": v1 / v0 - 1})
for lab, f in (("explore", lambda r: kdate(r["k"]) <= date(2025, 12, 31)), ("confirm", lambda r: kdate(r["k"]) > date(2025, 12, 31))):
    xs = [r for r in res if f(r)]
    for sub, ys in (("all nights", xs), ("flagged days", [r for r in xs if r["flag"]])):
        m = statistics.mean(r["net"] for r in ys); sd = statistics.stdev(r["net"] for r in ys)
        print(f"{lab} {sub}: n {len(ys)}, net/night {m:+.0f} (gross {statistics.mean(r['gross'] for r in ys):+.0f}, t {m / (sd / math.sqrt(len(ys))):+.2f}, "
              f"win {sum(1 for r in ys if r['net'] > 0) / len(ys):.2f}); |15:15->09:30 move| median {statistics.median(r['gap_bp'] for r in ys):.0f} bp; "
              f"VIX change median {statistics.median(r['vixchg'] for r in ys) * 100:+.1f}%")
