"""Per-strategy out-of-sample stats from the 2-year walk-forward backtest. READ ONLY.

Record layout (positional, from intraday_v2_backtest):
  0 strategy_id  1 symbol  2 entry_ts  3 exit_ts  4 side  5 entry  6 exit
  7 qty  8 gross  9 fees  10 net  11 exit_reason  12 (extra)
"""
import gzip
import json
import math
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

PATH = sys.argv[1] if len(sys.argv) > 1 else \
    "/data/intraday/backtests/v2-20261010-0605-trades.jsonl.gz"
HOLDOUT_FROM = "2026-05-13"
IST = timezone(timedelta(hours=5, minutes=30))

TREND = {"donchian", "macd_trend", "supertrend", "keltner", "ema_pullback", "pdh_pdl",
         "adx_dmi", "vwap_trend", "orb_inplay", "orb_sel15", "orb_sel30", "gap_go",
         "gap_fade", "or_close_break"}
REVERT = {"rsi2", "bollinger_snap", "cci_extreme", "stoch_range", "zscore",
          "vwap_reversion", "rsi_momentum"}


def parse(sid):
    s = (sid or "").replace("iv2_", "")
    for tf in ("_15m", "_45m", "_1h"):
        if s.endswith(tf):
            return s[: -len(tf)], tf[1:]
    return s, "day"


def pf(xs):
    w = sum(x for x in xs if x > 0)
    L = abs(sum(x for x in xs if x <= 0))
    return (w / L) if L else (float("inf") if w else 0.0)


def tstat(xs):
    if len(xs) < 2:
        return 0.0
    sd = st.pstdev(xs)
    return (st.mean(xs) / (sd / math.sqrt(len(xs)))) if sd else 0.0


def sharpe_daily(daily):
    if len(daily) < 2:
        return 0.0
    sd = st.pstdev(daily)
    return (st.mean(daily) / sd * math.sqrt(252)) if sd else 0.0


rows = []
with gzip.open(PATH, "rt") as fh:
    for line in fh:
        r = json.loads(line)
        day = datetime.fromtimestamp(r[3], IST).date().isoformat()
        rows.append((r[0], r[1], day, r[8], r[9], r[10], r[11]))

print(f"file   : {PATH}")
print(f"trades : {len(rows):,}")
days = sorted({r[2] for r in rows})
print(f"days   : {len(days)}   {days[0]} .. {days[-1]}")
print(f"holdout: from {HOLDOUT_FROM} "
      f"({len([d for d in days if d >= HOLDOUT_FROM])} sessions)\n")

gross = sum(r[3] for r in rows)
fees = sum(r[4] for r in rows)
net = sum(r[5] for r in rows)
print("=" * 104)
print("A. THE WHOLE TOURNAMENT OVER 2 YEARS")
print("=" * 104)
print(f"  gross  Rs {gross:>16,.0f}")
print(f"  fees   Rs {fees:>16,.0f}   ({fees / gross:.2f}x gross)" if gross > 0
      else f"  fees   Rs {fees:>16,.0f}")
print(f"  net    Rs {net:>16,.0f}")
print(f"  per trade: gross Rs {gross/len(rows):,.0f}  fees Rs {fees/len(rows):,.0f}  "
      f"net Rs {net/len(rows):,.0f}")

print("\n" + "=" * 104)
print("B. DOES THE TREND vs MEAN-REVERSION SPLIT HOLD OVER 2 YEARS?")
print("=" * 104)
for label, keyfn in (("kind", lambda s: "trend/breakout" if parse(s)[0] in TREND
                      else "mean-reversion" if parse(s)[0] in REVERT else "other"),
                     ("timeframe", lambda s: parse(s)[1])):
    buckets = defaultdict(list)
    for sid, _sym, day, g, f, n, _x in rows:
        buckets[keyfn(sid)].append((day, g, f, n))
    print(f"\n  {label:<16} {'trades':>8} {'gross':>14} {'fees':>13} {'net':>14} "
          f"{'nPF':>6} {'net/trade':>10} {'t':>7} {'Sharpe':>7}")
    print("  " + "-" * 100)
    for k, v in sorted(buckets.items(), key=lambda kv: -sum(x[3] for x in kv[1])):
        ns = [x[3] for x in v]
        dd = defaultdict(float)
        for day, _g, _f, n in v:
            dd[day] += n
        daily = [dd[d] for d in sorted(dd)]
        print(f"  {k:<16} {len(v):>8,} {sum(x[1] for x in v):>14,.0f} "
              f"{sum(x[2] for x in v):>13,.0f} {sum(ns):>14,.0f} "
              f"{min(pf(ns), 99):>6.2f} {st.mean(ns):>10,.0f} {tstat(ns):>7.2f} "
              f"{sharpe_daily(daily):>7.2f}")

print("\n" + "=" * 104)
print("C. PER STRATEGY — full 2 years, split at the holdout")
print("=" * 104)
by_s = defaultdict(list)
for sid, _sym, day, g, f, n, _x in rows:
    by_s[sid].append((day, g, f, n))

out = []
for sid, v in by_s.items():
    ns = [x[3] for x in v]
    dd = defaultdict(float)
    for day, _g, _f, n in v:
        dd[day] += n
    daily = [dd[d] for d in sorted(dd)]
    sel = [x[3] for x in v if x[0] < HOLDOUT_FROM]
    hold = [x[3] for x in v if x[0] >= HOLDOUT_FROM]
    months = defaultdict(float)
    for day, _g, _f, n in v:
        months[day[:7]] += n
    pos_m = len([m for m in months.values() if m > 0]) / len(months) if months else 0
    out.append({
        "id": sid, "n": len(v), "gross": sum(x[1] for x in v), "fees": sum(x[2] for x in v),
        "net": sum(ns), "pf": pf(ns), "t": tstat(ns), "sharpe": sharpe_daily(daily),
        "sel": sum(sel), "seln": len(sel), "hold": sum(hold), "holdn": len(hold),
        "posm": pos_m * 100,
    })
out.sort(key=lambda r: -r["net"])
print(f"  {'strategy':<30} {'n':>6} {'gross':>13} {'net':>13} {'nPF':>5} {'t':>6} "
      f"{'Sharpe':>7} {'selection':>12} {'HOLDOUT':>12} {'+mo%':>6}")
print("  " + "-" * 118)
for r in out:
    print(f"  {r['id'][:29]:<30} {r['n']:>6,} {r['gross']:>13,.0f} {r['net']:>13,.0f} "
          f"{min(r['pf'],99):>5.2f} {r['t']:>6.2f} {r['sharpe']:>7.2f} "
          f"{r['sel']:>12,.0f} {r['hold']:>12,.0f} {r['posm']:>6.0f}")

print("\n" + "=" * 104)
print("D. HOW MANY SURVIVE EACH BAR?")
print("=" * 104)
n_all = len(out)
checks = [
    ("any trades", lambda r: True),
    ("positive GROSS", lambda r: r["gross"] > 0),
    ("positive NET", lambda r: r["net"] > 0),
    (">=100 trades", lambda r: r["n"] >= 100),
    ("net>0 AND >=100 trades", lambda r: r["net"] > 0 and r["n"] >= 100),
    ("+ PF>=1.1", lambda r: r["net"] > 0 and r["n"] >= 100 and r["pf"] >= 1.1),
    ("+ holdout positive", lambda r: r["net"] > 0 and r["n"] >= 100 and r["pf"] >= 1.1
     and r["hold"] > 0),
    ("+ >=55% months positive", lambda r: r["net"] > 0 and r["n"] >= 100 and r["pf"] >= 1.1
     and r["hold"] > 0 and r["posm"] >= 55),
    ("+ t>=2", lambda r: r["net"] > 0 and r["n"] >= 100 and r["pf"] >= 1.1
     and r["hold"] > 0 and r["posm"] >= 55 and r["t"] >= 2),
    ("+ t>=3.31 (Bonferroni)", lambda r: r["net"] > 0 and r["n"] >= 100 and r["pf"] >= 1.1
     and r["hold"] > 0 and r["posm"] >= 55 and r["t"] >= 3.312),
]
for label, fn in checks:
    k = [r for r in out if fn(r)]
    print(f"  {label:<28} {len(k):>3} / {n_all}   "
          + (", ".join(r["id"].replace("iv2_", "") for r in k[:6]) if 0 < len(k) <= 6 else ""))

print("\n" + "=" * 104)
print("E. SELECTION vs HOLDOUT — does the in-sample winner keep winning?")
print("=" * 104)
ranked_sel = sorted(out, key=lambda r: -r["sel"])
top10 = ranked_sel[:10]
bot10 = ranked_sel[-10:]
print(f"  top 10 by SELECTION net  -> their HOLDOUT net: "
      f"Rs {sum(r['hold'] for r in top10):,.0f}")
print(f"  bottom 10 by SELECTION   -> their HOLDOUT net: "
      f"Rs {sum(r['hold'] for r in bot10):,.0f}")
kept = len([r for r in top10 if r["hold"] > 0])
print(f"  of the top 10 in selection, {kept} were still positive in the holdout")
print(f"\n  {'strategy':<30} {'selection':>13} {'HOLDOUT':>13}  kept?")
for r in top10:
    print(f"  {r['id'][:29]:<30} {r['sel']:>13,.0f} {r['hold']:>13,.0f}  "
          f"{'yes' if r['hold'] > 0 else 'NO'}")

print("\n" + "=" * 104)
print("F. EXIT REASONS OVER 2 YEARS")
print("=" * 104)
by_r = defaultdict(list)
for _sid, _sym, _day, g, f, n, reason in rows:
    by_r[reason].append((g, f, n))
print(f"  {'reason':<14} {'n':>8} {'share':>7} {'gross':>14} {'net':>14} {'net/trade':>11}")
for k, v in sorted(by_r.items(), key=lambda kv: -len(kv[1])):
    print(f"  {k:<14} {len(v):>8,} {len(v)/len(rows)*100:>6.1f}% "
          f"{sum(x[0] for x in v):>14,.0f} {sum(x[2] for x in v):>14,.0f} "
          f"{sum(x[2] for x in v)/len(v):>11,.0f}")
