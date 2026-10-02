import json, math, statistics, sys
from datetime import date
sys.argv = sys.argv[:1]
import pl_h1b as B
H = B.H
from pl_replay import kdate
ex = lambda k: kdate(k) <= date(2025, 12, 31)
on = [d for d in H.ok if H.pred[d["k"]] >= H.thr]
h1 = {p: [d["h1_net"] for d in on if ex(d["k"]) == (p == "explore")] for p in ("explore", "confirm")}
fl = [r for r in B.res if r["flag"]]
h1b = {p: [r["net"] for r in fl if ex(r["k"]) == (p == "explore")] for p in ("explore", "confirm")}
def st(v):
    return {"n": len(v), "mean": round(statistics.mean(v), 2), "sd": round(statistics.stdev(v), 2)}
out = {"frozen_at": "2026-10-02", "signal": {"features": ["log VIX (09:45, 0-1 scale)", "VIX change vs previous session's last bar",
       "|gap| % (09:15 open vs previous close)", "first-30-minute range % (09:15-09:45 high-low over open)",
       "log(previous session RV / IV window)", "log(mean RV of last 5 sessions / IV window)", "expiry day (nearest weekly) 1/0", "constant"],
       "weights": [round(float(x), 6) for x in H.w], "threshold": round(H.thr, 6),
       "rv": "sum of squared 5-minute log returns of the session", "iv_window": "VIX^2 x 330/375 / 252 (VIX at 09:45)",
       "fit": "OLS on 2024-10-04..2025-12-31; threshold = 60th percentile of those predictions"},
       "pricing": {"clock": "trading minutes + 0.2 session per calendar night", "iv": "India VIX x 0.888", "spread_pts_per_leg_side": 0.5},
       "H1": {"rule": "09:45 ATM straddle of next week's expiry on flagged days, sold 15:15", "explore": st(h1["explore"]), "confirm": st(h1["confirm"])},
       "H1b": {"rule": "15:15 ATM straddle of next week's expiry on flagged days, sold 09:30 next session", "explore": st(h1b["explore"]), "confirm": st(h1b["confirm"])}}
json.dump(out, open("h1_frozen.json", "w"), indent=1)
print(json.dumps({k: out[k] for k in ("H1", "H1b")}, indent=1)); print(out["signal"]["weights"], out["signal"]["threshold"])
