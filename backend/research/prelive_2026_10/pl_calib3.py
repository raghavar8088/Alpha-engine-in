"""Variance clock: trading minutes + W x a session per night ahead. Fit W (and the IV/VIX table
under that clock) so that re-pricing exits with VIX x ratio is unbiased across expiry buckets."""
import json
import math
import statistics
import sys
from datetime import date, datetime, timedelta, timezone

sys.argv = sys.argv[:1]
import pl_calib2 as C  # noqa: E402  (rows with true expiries, calendar-clock fields)

IST = C.IST
TDS = sorted({datetime.fromtimestamp(r[0], IST).date() for r in C.N5})
TDSET = set(TDS)


def is_td(d):
    return d in TDSET if d <= TDS[-1] else d.weekday() < 5


def T_clock(t0: datetime, exp: datetime, W: float) -> float:
    """Variance time in years: minutes of trading left (09:15-15:30 on trading days) plus W
    sessions per night before expiry, scaled so a full trading day = 1/252 year."""
    if exp <= t0:
        return 1e-6
    mins = 0.0
    d = t0.date()
    while d <= exp.date():
        if is_td(d):
            o = datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST)
            c = datetime(d.year, d.month, d.day, 15, 30, tzinfo=IST)
            a, b = max(o, t0), min(c, exp)
            if b > a:
                mins += (b - a).total_seconds() / 60
        if d < exp.date():
            mins += W * 375                       # every calendar night carries W sessions
        d += timedelta(days=1)
    # a year of this clock = 252 sessions + 365 nights x W
    return max(mins, 1.0) / ((252 + 365 * W) * 375)


trades = json.load(open("prelive_trades.json"))
base = []
for t in trades:
    if t["qty"] != 75 or not t.get("entry_ts") or not t.get("exit_ts") or t["session"] >= "2026-10-02":
        continue
    exp_d = next(e for e in C.OLD_MASTER if e >= t["session"])
    exp = datetime.fromisoformat(exp_d).replace(hour=15, minute=30, tzinfo=IST)
    e0 = datetime.fromisoformat(t["entry_ts"]).astimezone(IST)
    e1 = datetime.fromisoformat(t["exit_ts"]).astimezone(IST)
    s0, s1, v0, v1 = C.spot_at(e0), C.spot_at(e1), C.vix_at(e0), C.vix_at(e1)
    if not (s0 and s1 and v0 and v1):
        continue
    dte = (date.fromisoformat(exp_d) - date.fromisoformat(t["session"])).days
    base.append((t, exp, e0, e1, s0, s1, v0, v1, dte))


def run(W):
    rows = []
    for t, exp, e0, e1, s0, s1, v0, v1, dte in base:
        call = t["option_type"] == "CE"
        T0, T1 = T_clock(e0, exp, W), T_clock(e1, exp, W)
        iv = C.implied(t["entry_premium"], s0, t["strike"], T0, call)
        if iv is None:
            continue
        rows.append((C.bucket(dte), e0.hour, e1.hour, iv / v0, v1, s1, t["strike"], call, T1, t["entry_premium"], t["exit_premium"]))
    table = {}
    for b in ("0", "1", "2-6", "7-20", "21-40", "80+"):
        xs = [r for r in rows if r[0] == b]
        e = {"n": len(xs), "ratio": round(statistics.median(r[3] for r in xs), 3)}
        if b == "0":
            byh = {}
            for r in xs:
                byh.setdefault(r[1], []).append(r[3])
            e["by_hour"] = {h: round(statistics.median(v), 3) for h, v in sorted(byh.items())}
        table[b] = e
    errs = {}
    for b in table:
        xs = [r for r in rows if r[0] == b]
        def ratio(h):
            return table[b]["by_hour"].get(h, table[b]["ratio"]) if b == "0" else table[b]["ratio"]
        er = [(C.bs(r[5], r[6], r[8], r[4] * ratio(r[2]), r[7]) - r[10]) / r[9] * 100 for r in xs]
        errs[b] = (round(statistics.median(er), 2), round(statistics.mean(abs(x) for x in er), 2))
    return table, errs


best = None
for W in (0.0, 0.1, 0.2, 0.3, 0.45, 0.6, 0.8, 1.0):
    table, errs = run(W)
    score = sum(abs(errs[b][0]) * table[b]["n"] for b in errs) / sum(table[b]["n"] for b in errs)
    print(f"W={W:4.2f}: weighted |median exit error| {score:5.2f}% | " +
          " ".join(f"{b}:{errs[b][0]:+.1f}%/MAE{errs[b][1]:.0f}" for b in errs))
    if best is None or score < best[0]:
        best = (score, W, table, errs)
print("best W", best[1], json.dumps(best[2]))
json.dump({"clock": "trading minutes + W sessions per night", "W": best[1], "table": best[2], "exit_error_pct": best[3]},
          open("calib_clock.json", "w"), indent=1)
