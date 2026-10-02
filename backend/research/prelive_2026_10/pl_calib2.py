"""Premium-model calibration on the desk's real trades, with each contract's TRUE expiry.

The desk took "the nearest expiry >= today" from an instrument master frozen in July, so its
contracts were: July/Aug weeklies, then the 25 Aug and 29 Sep monthlies, then 29 Dec. Each
trade's expiry is therefore reconstructed from that list. Calendar-time Black-Scholes; the
fitted quantity is the real IV / India VIX ratio, by days to expiry and (on expiry day) hour.
Output: calib.json, the table every later model reads (U3 engine, H1 pricing)."""
import json
import math
import statistics
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
R = 0.065
OLD_MASTER = ["2026-07-14", "2026-07-21", "2026-07-28", "2026-08-04", "2026-08-11", "2026-08-25",
              "2026-09-29", "2026-12-29", "2027-03-30"]
D = json.load(open("nifty_bars.json"))
N5, V15 = D["NIFTY_5m"], D["INDIAVIX_15m"]
nt, vt = [r[0] for r in N5], [r[0] for r in V15]


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, sig, call):
    if T <= 0 or sig <= 0:
        return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + (R + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    return S * ncdf(d1) - K * math.exp(-R * T) * ncdf(d2) if call else K * math.exp(-R * T) * ncdf(-d2) - S * ncdf(-d1)


def implied(price, S, K, T, call):
    lo, hi = 0.005, 4.0
    if bs(S, K, T, hi, call) < price or bs(S, K, T, lo, call) > price:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if bs(S, K, T, mid, call) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def spot_at(ts):
    e = int(ts.timestamp())
    i = bisect_right(nt, e - 300) - 1
    return N5[i][4] if i >= 0 and e - nt[i] < 1800 else None


def vix_at(ts):
    e = int(ts.timestamp())
    i = bisect_right(vt, e - 900) - 1
    return V15[i][4] / 100 if i >= 0 and e - vt[i] < 86400 * 5 else None


def T_cal(t, exp):
    return max((exp - t).total_seconds(), 60) / (365 * 86400)


def bucket(dte):
    return "0" if dte == 0 else "1" if dte == 1 else "2-6" if dte <= 6 else "7-20" if dte <= 20 else "21-40" if dte <= 40 else "80+"


trades = json.load(open("prelive_trades.json"))
rows = []
for t in trades:
    if t["qty"] != 75 or not t.get("entry_ts") or not t.get("exit_ts") or t["session"] >= "2026-10-02":
        continue
    exp_d = next(e for e in OLD_MASTER if e >= t["session"])
    exp = datetime.fromisoformat(exp_d).replace(hour=15, minute=30, tzinfo=IST)
    e0 = datetime.fromisoformat(t["entry_ts"]).astimezone(IST)
    e1 = datetime.fromisoformat(t["exit_ts"]).astimezone(IST)
    s0, s1, v0, v1 = spot_at(e0), spot_at(e1), vix_at(e0), vix_at(e1)
    if not (s0 and s1 and v0 and v1):
        continue
    call = t["option_type"] == "CE"
    iv = implied(t["entry_premium"], s0, t["strike"], T_cal(e0, exp), call)
    if iv is None:
        continue
    dte = (date.fromisoformat(exp_d) - date.fromisoformat(t["session"])).days
    rows.append({"b": bucket(dte), "dte": dte, "h0": e0.hour, "h1": e1.hour, "ratio": iv / v0, "v0": v0, "v1": v1,
                 "s1": s1, "K": t["strike"], "call": call, "T1": T_cal(e1, exp), "p0": t["entry_premium"],
                 "p1": t["exit_premium"], "iv": iv, "pnl": t["pnl"]})
print(f"{len(rows)} trades priced with their true expiry")
table = {}
for b in ("0", "1", "2-6", "7-20", "21-40", "80+"):
    xs = [r for r in rows if r["b"] == b]
    if not xs:
        continue
    rat = sorted(r["ratio"] for r in xs)
    entry = {"n": len(xs), "ratio": round(statistics.median(rat), 3), "p25": round(rat[len(rat) // 4], 3),
             "p75": round(rat[len(rat) * 3 // 4], 3)}
    if b == "0":
        byh = defaultdict(list)
        for r in xs:
            byh[r["h0"]].append(r["ratio"])
        entry["by_hour"] = {h: round(statistics.median(v), 3) for h, v in sorted(byh.items())}
    table[b] = entry
print("IV / VIX by days to expiry:", json.dumps(table))


def model_ratio(b, hour):
    e = table[b]
    if b == "0":
        return e["by_hour"].get(hour, e["ratio"])
    return e["ratio"]


# how well does the MODEL (VIX x table ratio at entry AND exit) reproduce real exits?
for b in table:
    xs = [r for r in rows if r["b"] == b]
    err_entry_iv = [(bs(r["s1"], r["K"], r["T1"], r["iv"], r["call"]) - r["p1"]) / r["p0"] * 100 for r in xs]
    err_model = [(bs(r["s1"], r["K"], r["T1"], r["v1"] * model_ratio(b, r["h1"]), r["call"]) - r["p1"]) / r["p0"] * 100 for r in xs]
    print(f"  {b:>5s} DTE: n {len(xs):4d} | exit at entry IV: median err {statistics.median(err_entry_iv):+5.2f}% MAE "
          f"{statistics.mean(abs(e) for e in err_entry_iv):5.2f}% | full model (VIX x ratio): median {statistics.median(err_model):+5.2f}% "
          f"MAE {statistics.mean(abs(e) for e in err_model):5.2f}%")
# P&L by TRUE days to expiry
print("net per trade by true days to expiry:", {b: (len([r for r in rows if r['b'] == b]),
                                                    round(statistics.mean(r['pnl'] for r in rows if r['b'] == b)))
                                                for b in table})
json.dump(table, open("calib.json", "w"), indent=1)
