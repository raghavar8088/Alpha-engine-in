"""Two-year walk-forward record, cut every way the brief asks. READ ONLY.

Excludes the two `~opt` shadow records (an optimistic UPPER BOUND on ambiguous ORB bars,
stored for reference, not a strategy). Uses the catalog's own kind/category labels.
"""
import asyncio
import gzip
import json
import math
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")

from app.core.db import db                                                  # noqa: E402
from app.services.intraday_v2_strategies import CATALOG                    # noqa: E402

PATH = "/data/intraday/backtests/v2-20261010-0605-trades.jsonl.gz"
IST = timezone(timedelta(hours=5, minutes=30))
HOLDOUT_FROM = "2026-05-13"
BOOK = 54 * 5_000_000.0          # Rs 27 crore, as the live desk is capitalised

SPEC = {s.strategy_id: s for s in CATALOG}


def pf(xs):
    w = sum(x for x in xs if x > 0)
    L = abs(sum(x for x in xs if x <= 0))
    return (w / L) if L else (float("inf") if w else 0.0)


def tstat(xs):
    if len(xs) < 2:
        return 0.0
    sd = st.pstdev(xs)
    return (st.mean(xs) / (sd / math.sqrt(len(xs)))) if sd else 0.0


def line(label, v, total_n=None):
    g = sum(x["g"] for x in v)
    n = sum(x["n"] for x in v)
    notl = sum(x["notl"] for x in v)
    nets = [x["n"] for x in v]
    share = f"{len(v)/total_n*100:>5.1f}%" if total_n else ""
    return (f"  {label:<26} {len(v):>8,} {share:>6} {g:>13,.0f} {n:>14,.0f} "
            f"{g/notl*1e4 if notl else 0:>7.2f} {n/notl*1e4 if notl else 0:>7.2f} "
            f"{min(pf(nets),99):>5.2f} {tstat(nets):>7.2f}")


HDR = (f"  {'':<26} {'trades':>8} {'share':>6} {'gross':>13} {'net':>14} "
       f"{'g bp':>7} {'n bp':>7} {'nPF':>5} {'t':>7}")


async def main():
    # ---- NIFTY daily, for regimes ------------------------------------------------
    nifty = {}
    async for b in db["bars"].find({"symbol": "NIFTY", "timeframe": "1d"},
                                   {"ts": 1, "close": 1}):
        d = (b["ts"].replace(tzinfo=timezone.utc) + timedelta(hours=5, minutes=30)).date()
        nifty[d.isoformat()] = float(b["close"])
    nd = sorted(nifty)
    ret = {nd[k]: nifty[nd[k]] / nifty[nd[k - 1]] - 1 for k in range(1, len(nd))}
    prior20, vol20 = {}, {}
    for k in range(21, len(nd)):
        d = nd[k]
        prior20[d] = nifty[nd[k - 1]] / nifty[nd[k - 21]] - 1          # ex-ante
        rr = [ret[nd[m]] for m in range(k - 20, k)]
        vol20[d] = st.pstdev(rr) * math.sqrt(252)                       # ex-ante
    print(f"NIFTY daily closes: {len(nd):,} ({nd[0]} .. {nd[-1]})")

    # ---- trades ------------------------------------------------------------------
    T = []
    with gzip.open(PATH, "rt") as fh:
        for raw in fh:
            r = json.loads(raw)
            if r[0].endswith("~opt"):
                continue
            ent = datetime.fromtimestamp(r[2], IST)
            ext = datetime.fromtimestamp(r[3], IST)
            sp = SPEC.get(r[0])
            T.append({
                "sid": r[0], "sym": r[1], "day": ext.date().isoformat(),
                "hhmm": ent.strftime("%H:%M"), "hold": (r[3] - r[2]) / 60.0,
                "side": r[4], "notl": abs(r[5] * r[7]), "g": r[8], "f": r[9], "n": r[10],
                "why": r[11], "kind": sp.kind if sp else "?",
                "cat": sp.category if sp else "?", "tf": sp.tf if sp else "?",
            })
    N = len(T)
    days = sorted({t["day"] for t in T})
    print(f"trades {N:,} (shadow records excluded)   sessions {len(days)}   "
          f"{days[0]} .. {days[-1]}\n")

    G = sum(t["g"] for t in T); F = sum(t["f"] for t in T); NN = sum(t["n"] for t in T)
    NOTL = sum(t["notl"] for t in T)
    print("=" * 104)
    print("0. HEADLINE")
    print("=" * 104)
    print(f"  gross Rs {G:>16,.0f}   ({G/NOTL*1e4:+.2f} bp of notional per trade)")
    print(f"  fees  Rs {F:>16,.0f}   ({F/NOTL*1e4:.2f} bp)")
    print(f"  net   Rs {NN:>16,.0f}   ({NN/NOTL*1e4:+.2f} bp)   on a Rs {BOOK/1e7:.0f} crore book")

    def cut(title, keyfn, order=None):
        print("\n" + "=" * 104)
        print(title)
        print("=" * 104)
        print(HDR)
        print("  " + "-" * 100)
        b = defaultdict(list)
        for t in T:
            k = keyfn(t)
            if k is not None:
                b[k].append(t)
        keys = order if order else sorted(b, key=lambda k: -sum(x["n"] for x in b[k]))
        for k in keys:
            if k in b:
                print(line(str(k), b[k], N))
        return b

    cut("1. BY CATALOG CATEGORY", lambda t: t["cat"])
    cut("2. BY KIND", lambda t: t["kind"])
    cut("3. BY TIMEFRAME", lambda t: t["tf"], ["15m", "45m", "1h", "day"])
    cut("4. BY SIDE", lambda t: t["side"])

    def regime_trend(t):
        p = prior20.get(t["day"])
        return None if p is None else ("bull  (prior 20d > +3%)" if p > 0.03 else
                                       "bear  (prior 20d < -3%)" if p < -0.03 else
                                       "sideways (within +-3%)")
    cut("5. MARKET REGIME, EX-ANTE — NIFTY's prior 20-session return", regime_trend)

    vols = sorted(vol20[d] for d in days if d in vol20)
    vmed = vols[len(vols) // 2] if vols else 0

    def regime_vol(t):
        v = vol20.get(t["day"])
        return None if v is None else (f"high vol (>{vmed:.0%} ann.)" if v > vmed
                                       else f"low vol (<={vmed:.0%} ann.)")
    cut("6. VOLATILITY REGIME, EX-ANTE — NIFTY's prior 20-session realised vol", regime_vol)

    def daytype(t):
        r = ret.get(t["day"])
        return None if r is None else ("NIFTY big up   (> +1%)" if r > 0.01 else
                                       "NIFTY up       (0..+1%)" if r > 0 else
                                       "NIFTY down     (-1%..0)" if r > -0.01 else
                                       "NIFTY big down (< -1%)")
    cut("7. DAY TYPE, EX-POST — what NIFTY did that session (descriptive only)", daytype,
        ["NIFTY big up   (> +1%)", "NIFTY up       (0..+1%)", "NIFTY down     (-1%..0)",
         "NIFTY big down (< -1%)"])

    def tod(t):
        h = t["hhmm"]
        return ("09:15-09:45" if h < "09:45" else "09:45-10:30" if h < "10:30" else
                "10:30-11:30" if h < "11:30" else "11:30-12:30" if h < "12:30" else
                "12:30-13:30" if h < "13:30" else "13:30-14:30" if h < "14:30" else "14:30+")
    cut("8. TIME OF DAY OF ENTRY", tod,
        ["09:15-09:45", "09:45-10:30", "10:30-11:30", "11:30-12:30", "12:30-13:30",
         "13:30-14:30", "14:30+"])

    def hold(t):
        m = t["hold"]
        return ("< 15 min" if m < 15 else "15-60 min" if m < 60 else "1-2 h" if m < 120
                else "2-4 h" if m < 240 else "4 h +")
    cut("9. HOLDING TIME", hold, ["< 15 min", "15-60 min", "1-2 h", "2-4 h", "4 h +"])
    cut("10. EXIT REASON", lambda t: t["why"])

    # ---- cost sensitivity --------------------------------------------------------
    print("\n" + "=" * 104)
    print("11. COST SENSITIVITY — what if costs were a fraction of Angel's real card?")
    print("=" * 104)
    print(f"  {'cost multiple':<16} {'whole book net':>16} {'momentum net':>15} "
          f"{'reversion net':>15} {'strategies net>0':>18}")
    by_s = defaultdict(list)
    for t in T:
        by_s[t["sid"]].append(t)
    for m in (0.0, 0.25, 0.5, 0.75, 1.0, 1.25):
        whole = G - m * F
        mom = sum(t["g"] - m * t["f"] for t in T if t["cat"] == "momentum")
        rev = sum(t["g"] - m * t["f"] for t in T if t["cat"] == "mean_reversion")
        pos = len([s for s, v in by_s.items() if sum(x["g"] - m * x["f"] for x in v) > 0])
        print(f"  {m:<16.2f} {whole:>16,.0f} {mom:>15,.0f} {rev:>15,.0f} "
              f"{pos:>12} / {len(by_s)}")
    print("\n  break-even cost multiple per gross-positive strategy (1.0 = today's real costs):")
    for s, v in sorted(by_s.items(), key=lambda kv: -sum(x["g"] for x in kv[1])):
        g = sum(x["g"] for x in v); f = sum(x["f"] for x in v)
        if g <= 0:
            continue
        notl = sum(x["notl"] for x in v)
        print(f"    {s:<26} gross {g:>11,.0f}  fees {f:>11,.0f}  breaks even at "
              f"{g/f:.2f}x costs   gross edge {g/notl*1e4:.2f} bp vs cost {f/notl*1e4:.2f} bp")

    # ---- drawdown ------------------------------------------------------------------
    print("\n" + "=" * 104)
    print("12. DRAWDOWN AND CONSISTENCY — whole Rs 27 crore book, daily")
    print("=" * 104)
    dn = defaultdict(float)
    for t in T:
        dn[t["day"]] += t["n"]
    eq, peak, mdd, under, longest = 0.0, 0.0, 0.0, 0, 0
    for d in days:
        eq += dn[d]
        if eq > peak:
            peak, under = eq, 0
        else:
            under += 1
            longest = max(longest, under)
        mdd = min(mdd, eq - peak)
    daily = [dn[d] for d in days]
    sd = st.pstdev(daily)
    neg = [x for x in daily if x < 0]
    dsd = math.sqrt(sum(x * x for x in neg) / len(daily)) if daily else 0
    print(f"  cumulative net          Rs {eq:>14,.0f}  ({eq/BOOK*100:+.2f}% of book)")
    print(f"  max drawdown            Rs {mdd:>14,.0f}  ({mdd/BOOK*100:.2f}% of book)")
    print(f"  longest time underwater {longest} sessions (of {len(days)})")
    print(f"  daily Sharpe (ann.)     {st.mean(daily)/sd*math.sqrt(252) if sd else 0:.2f}")
    print(f"  daily Sortino (ann.)    {st.mean(daily)/dsd*math.sqrt(252) if dsd else 0:.2f}")
    print(f"  positive sessions       {len([x for x in daily if x > 0])} / {len(daily)}")
    mo = defaultdict(float)
    for d in days:
        mo[d[:7]] += dn[d]
    print(f"  positive months         {len([v for v in mo.values() if v > 0])} / {len(mo)}")
    print("\n  month       net (Rs)")
    for k in sorted(mo):
        bar = "#" * min(40, int(abs(mo[k]) / 250_000))
        print(f"  {k}  {mo[k]:>13,.0f}  {'-' if mo[k] < 0 else '+'}{bar}")

    # ---- symbols -------------------------------------------------------------------
    print("\n" + "=" * 104)
    print("13. SYMBOLS — is the loss concentrated or everywhere?")
    print("=" * 104)
    sy = defaultdict(list)
    for t in T:
        sy[t["sym"]].append(t)
    ranked = sorted(sy.items(), key=lambda kv: -sum(x["n"] for x in kv[1]))
    pos_sy = [k for k, v in ranked if sum(x["n"] for x in v) > 0]
    print(f"  symbols traded {len(sy)}; net positive in {len(pos_sy)}; "
          f"gross positive in {len([1 for k, v in ranked if sum(x['g'] for x in v) > 0])}")
    print("  best 5 :", ", ".join(f"{k} {sum(x['n'] for x in v):,.0f}" for k, v in ranked[:5]))
    print("  worst 5:", ", ".join(f"{k} {sum(x['n'] for x in v):,.0f}" for k, v in ranked[-5:]))
    worst20 = sum(sum(x["n"] for x in v) for k, v in ranked[-20:])
    print(f"  the 20 worst symbols account for Rs {worst20:,.0f} of Rs {NN:,.0f} "
          f"({worst20/NN*100:.0f}%) — the loss is "
          f"{'concentrated' if worst20/NN > 0.6 else 'spread across the universe'}")


asyncio.run(main())
