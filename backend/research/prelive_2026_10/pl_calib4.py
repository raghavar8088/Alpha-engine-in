"""IV surface vs India VIX on the W=0.2 clock: median real-IV/VIX by (expiry bucket, hour),
from BOTH entry and exit premiums of the desk's real trades; then out-of-sample check
(fit on trades before 2026-09-01, test exits after)."""
import json, statistics, sys
from datetime import date, datetime
sys.argv = sys.argv[:1]
import pl_calib3 as K
C = K.C
W = 0.2
obs = []
for t, exp, e0, e1, s0, s1, v0, v1, dte in K.base:
    call = t["option_type"] == "CE"
    b = C.bucket(dte)
    for ts, s, v, p in ((e0, s0, v0, t["entry_premium"]), (e1, s1, v1, t["exit_premium"])):
        if p < 0.5:
            continue
        T = K.T_clock(ts, exp, W)
        iv = C.implied(p, s, t["strike"], T, call)
        if iv:
            obs.append((t["session"], b, ts.hour, iv / v, s, t["strike"], call, T, p, v, ts is e1))


def table_from(xs):
    tab = {}
    for o in xs:
        tab.setdefault(o[1], {}).setdefault(o[2], []).append(o[3])
    return {b: {h: statistics.median(v) for h, v in hs.items() if len(v) >= 15} for b, hs in tab.items()}


def ratio(tab, b, h):
    hs = tab.get(b, {})
    if h in hs:
        return hs[h]
    near = sorted(hs, key=lambda x: abs(x - h))
    return hs[near[0]] if near else 0.9


train = [o for o in obs if o[0] < "2026-09-01"]
test = [o for o in obs if o[0] >= "2026-09-01" and o[10]]
tab = table_from(train)
for b in ("0", "1", "2-6", "7-20", "21-40", "80+"):
    xs = [o for o in test if o[1] == b]
    if not xs:
        print(b, "no test exits"); continue
    er = [(C.bs(o[4], o[5], o[7], o[9] * ratio(tab, b, o[2]), o[6]) - o[8]) / o[8] * 100 for o in xs]
    print(f"{b:>5s}: test exits {len(xs):4d}, model error median {statistics.median(er):+5.1f}% of the real price, MAE {statistics.mean(abs(e) for e in er):5.1f}%")
full = table_from(obs)
print(json.dumps({b: {h: round(v, 3) for h, v in sorted(hs.items())} for b, hs in full.items()}))
json.dump({"clock": "trading minutes + 0.2 session per calendar night; year = (252 + 365*0.2) sessions",
           "W": W, "iv_over_vix": {b: {str(h): round(v, 4) for h, v in sorted(hs.items())} for b, hs in full.items()},
           "source": "5,800 real NIFTY option trades of the Pre-Live desk, 2026-07-20..10-01, entry and exit premiums"},
          open("calib_surface.json", "w"), indent=1)
