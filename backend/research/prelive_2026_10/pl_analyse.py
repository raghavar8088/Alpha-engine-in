import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import NormalDist

IST = timezone(timedelta(hours=5, minutes=30))
R = json.load(open("pl_replay_trades.json"))
real = json.load(open("prelive_trades.json"))


def kdate(k):
    return date(1970, 1, 1) + timedelta(days=k)


def period(k):
    d = kdate(k)
    return "explore" if d <= date(2025, 12, 31) else "confirm" if d < date(2026, 7, 20) else "live"


def t(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 3:
        return None
    sd = statistics.stdev(xs)
    return statistics.mean(xs) / (sd / math.sqrt(len(xs))) if sd else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def spearman(a, b):
    def rk(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0] * len(v)
        for i, j in enumerate(o):
            r[j] = i
        return r
    ra, rb = rk(a), rk(b); n = len(a)
    return 1 - 6 * sum((x - y) ** 2 for x, y in zip(ra, rb)) / (n * (n * n - 1))


# ── 1. validation: replay vs the real trades, same strategies, same window ──
real_by = defaultdict(list)
for x in real:
    if x["qty"] == 75 and "2026-07-30" <= x["session"] < "2026-10-02":
        real_by[x["key"]].append(x)
rep_by = {k: [x for x in v if "2026-07-30" <= str(kdate(x["k"])) < "2026-10-02"] for k, v in R.items()}
keys = [k for k in R if k in real_by or rep_by[k]]
cnt_r = [len(real_by.get(k, [])) for k in keys]
cnt_m = [len(rep_by[k]) for k in keys]
print(f"VALIDATION (2026-07-30..10-01, {len(keys)} strategies):")
print(f"  trades real {sum(cnt_r)} vs replay {sum(cnt_m)}; per-strategy count Spearman {spearman(cnt_r, cnt_m):.2f}")
both = [k for k in keys if len(real_by.get(k, [])) >= 10 and len(rep_by[k]) >= 10]
mr = [statistics.mean(x["pnl"] * 65 / 75 for x in real_by[k]) for k in both]
mm = [statistics.mean(x["net"] for x in rep_by[k]) for k in both]
print(f"  net per trade (lot 65): real {statistics.mean(x['pnl'] * 65 / 75 for k in both for x in real_by[k]):.0f} "
      f"vs replay {statistics.mean(x['net'] for k in both for x in rep_by[k]):.0f}; per-strategy Spearman {spearman(mr, mm):.2f}")
# trade-level match: same strategy, same day, same option side, entry within 10 minutes
match = tot = 0
for k in both:
    rr = defaultdict(list)
    for x in rep_by[k]:
        rr[str(kdate(x["k"]))].append(x)
    for x in real_by[k]:
        tot += 1
        e = datetime.fromisoformat(x["entry_ts"]).timestamp()
        side = 1 if x["option_type"] == "CE" else -1
        if any(abs(y["e"] - e) <= 600 and y["side"] == side for y in rr.get(x["session"], [])):
            match += 1
print(f"  real trades with a replay twin (same day, side, entry within 10 min): {match}/{tot} = {match / tot:.2f}")

# ── 2. two years, by period ──
print("\nALL SIGNALS, per trade (Rs, lot 65, after fees and spread):")
for per in ("explore", "confirm", "live"):
    xs = [x for v in R.values() for x in v if period(x["k"]) == per]
    days = len({x["k"] for x in xs})
    print(f"  {per:8s}: {len(xs):6d} trades over {days} days | ATM weekly {mean([x['net'] for x in xs]):+6.0f} "
          f"| next-week {mean([x['net_nextwk'] for x in xs]):+6.0f} | 60-min hold {mean([x['net_60m'] for x in xs]):+6.0f} "
          f"| futures to 15:15 {mean([x['net_fut'] for x in xs]):+6.0f} | NIFTY moved signal's way by 15:15 "
          f"{sum(1 for x in xs if (x['fav_eod_bp'] or 0) > 0) / len(xs):.3f}, mean {mean([x['fav_eod_bp'] for x in xs]):+.2f} bp")
alln = [x for v in R.values() for x in v]
print("  exits:", Counter(x["why"] for x in alln), "| DTE:", Counter(min(x["dte"], 6) for x in alln))
for d in (0, 1):
    xs = [x for x in alln if x["dte"] == d]
    print(f"  dte {d}: {len(xs)} trades, net/trade {mean([x['net'] for x in xs]):+.0f}")
xs = [x for x in alln if x["dte"] >= 2]
print(f"  dte 2+: {len(xs)} trades, net/trade {mean([x['net'] for x in xs]):+.0f}")
hr = defaultdict(list)
for x in alln:
    hr[datetime.fromtimestamp(x["e"], IST).hour].append(x["net"])
print("  by entry hour:", {h: (len(v), round(statistics.mean(v))) for h, v in sorted(hr.items())})
first_bar = sum(1 for x in alln if datetime.fromtimestamp(x["e"], IST).strftime("%H:%M") in ("09:20", "09:30", "10:15"))
print(f"  trades entered on the day's FIRST bar close (fresh strategy each morning): {first_bar / len(alln):.2f}")

# ── 3. per strategy: edge, persistence, deflated Sharpe ──
rows = []
for k, v in R.items():
    e = [x for x in v if period(x["k"]) == "explore"]
    c = [x for x in v if period(x["k"]) == "confirm"]
    l = [x for x in v if period(x["k"]) == "live"]
    rows.append({"key": k, "n": len(v), "e_n": len(e), "c_n": len(c),
                 "e": mean([x["net"] for x in e]), "c": mean([x["net"] for x in c]), "l": mean([x["net"] for x in l]),
                 "e_t": t([x["net"] for x in e]), "c_t": t([x["net"] for x in c]),
                 "all": mean([x["net"] for x in v]), "all_t": t([x["net"] for x in v]),
                 "dir_e": mean([x["fav_eod_bp"] for x in e]), "dir_c": mean([x["fav_eod_bp"] for x in c]),
                 "dir_t": t([x["fav_eod_bp"] for x in v]),
                 "fut_e": mean([x["net_fut"] for x in e]), "fut_c": mean([x["net_fut"] for x in c]),
                 "nw_e": mean([x["net_nextwk"] for x in e]), "nw_c": mean([x["net_nextwk"] for x in c])})
rows = [r for r in rows if r["e_n"] >= 30 and r["c_n"] >= 15]
print(f"\nPER STRATEGY ({len(rows)} with 30+ explore and 15+ confirm trades):")
for lab, f in (("ATM weekly (the desk)", "e"), ("futures, same signal", "fut_e"), ("next-week option", "nw_e")):
    fc = {"e": "c", "fut_e": "fut_c", "nw_e": "nw_c"}[f]
    pe = sum(1 for r in rows if (r[f] or 0) > 0)
    pc = sum(1 for r in rows if (r[fc] or 0) > 0)
    both = sum(1 for r in rows if (r[f] or 0) > 0 and (r[fc] or 0) > 0)
    rho = spearman([r[f] or 0 for r in rows], [r[fc] or 0 for r in rows])
    top = sorted(rows, key=lambda r: -(r[f] or -1e9))[:max(1, len(rows) // 10)]
    print(f"  {lab:24s}: positive explore {pe}, confirm {pc}, both {both}; explore->confirm Spearman {rho:+.3f}; "
          f"explore top-10% -> confirm {statistics.mean(r[fc] or 0 for r in top):+.0f}/trade (all {statistics.mean(r[fc] or 0 for r in rows):+.0f})")
print(f"  explore t>2 (ATM): {sum(1 for r in rows if (r['e_t'] or 0) > 2)}; of those, confirm > 0: "
      f"{sum(1 for r in rows if (r['e_t'] or 0) > 2 and (r['c'] or 0) > 0)}")
dsig = sum(1 for r in rows if (r["dir_t"] or 0) > 2)
dneg = sum(1 for r in rows if (r["dir_t"] or 0) < -2)
print(f"  DIRECTION to 15:15 (model-free): t>2 {dsig}, t<-2 {dneg} of {len(rows)} (chance ~{0.023 * len(rows):.1f} each side); "
      f"explore->confirm Spearman of mean move {spearman([r['dir_e'] or 0 for r in rows], [r['dir_c'] or 0 for r in rows]):+.3f}")


# deflated Sharpe on daily P&L over the whole two years, n_trials = all strategies
def daily(v):
    d = defaultdict(float)
    for x in v:
        d[x["k"]] += x["net"]
    return d
alldays = sorted({x["k"] for v in R.values() for x in v})
srs = {}
for k, v in R.items():
    d = daily(v)
    ser = [d.get(x, 0.0) for x in alldays]
    m, sd = statistics.mean(ser), statistics.pstdev(ser)
    srs[k] = (m / sd if sd else 0.0, ser)
sr_var = statistics.pvariance([s[0] for s in srs.values()])
N = len(srs)
nd = NormalDist()
EUL = 0.5772156649
sr0 = math.sqrt(sr_var) * ((1 - EUL) * nd.inv_cdf(1 - 1 / N) + EUL * nd.inv_cdf(1 - 1 / (N * math.e)))
best = sorted(srs.items(), key=lambda kv: -kv[1][0])[:8]
print(f"\nDEFLATED SHARPE ({N} trials, {len(alldays)} days): the best daily Sharpe expected by luck alone = {sr0:.4f}")
for k, (sr, ser) in best:
    n = len(ser)
    m = statistics.mean(ser); sd = statistics.pstdev(ser)
    g3 = sum(((x - m) / sd) ** 3 for x in ser) / n if sd else 0
    g4 = sum(((x - m) / sd) ** 4 for x in ser) / n if sd else 3
    den = 1 - g3 * sr + (g4 - 1) / 4 * sr * sr
    dsr = nd.cdf((sr - sr0) * math.sqrt(n - 1) / math.sqrt(den)) if den > 0 else None
    r = next((r for r in rows if r["key"] == k), None)
    print(f"  {k:40s} daily SR {sr:+.4f} (annual {sr * math.sqrt(250):+.2f}) DSR {dsr:.3f}" +
          (f" | per trade explore {r['e']:+.0f} confirm {r['c']:+.0f} live {r['l'] if r['l'] is not None else float('nan'):+.0f}" if r else ""))
json.dump(rows, open("pl_rows.json", "w"))
