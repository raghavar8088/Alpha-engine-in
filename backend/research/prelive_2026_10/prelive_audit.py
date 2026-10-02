"""READ ONLY audit of the Pre-Live (NIFTY option BUYING) paper desk: what really happened."""
import asyncio
import json
import math
import statistics
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
OUT = {}


def p(*a):
    print(*a, flush=True)


def tstat(xs):
    if len(xs) < 3:
        return None
    sd = statistics.stdev(xs)
    return statistics.mean(xs) / (sd / math.sqrt(len(xs))) if sd else None


async def main():
    from app.core.db import db
    from app.services.intraday_store import read_file

    names = sorted(await db.list_collection_names())
    rel = [n for n in names if "prelive" in n or "live_paper" in n or "paper_book" in n]
    p("collections:", {n: await db[n].estimated_document_count() for n in rel})

    tr = db["prelive_trades"]
    sample = await tr.find_one({}, sort=[("exit_ts", -1)])
    p("sample trade keys:", sorted(sample.keys()) if sample else None)
    trades = [t async for t in tr.find({})]
    p("trades:", len(trades))
    for t in trades:
        for k in ("entry_ts", "exit_ts"):
            v = t.get(k)
            if isinstance(v, str):
                try:
                    v = datetime.fromisoformat(v)
                except ValueError:
                    v = None
            if v is not None and v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            t[k] = v.astimezone(IST) if v else None
    sessions = sorted({t["session"] for t in trades})
    p("sessions:", len(sessions), sessions[0], "..", sessions[-1])
    by_sess = defaultdict(list)
    for t in trades:
        by_sess[t["session"]].append(t)
    p("per session (n, net):", [(s, len(by_sess[s]), round(sum(x["pnl"] for x in by_sess[s]))) for s in sessions])

    # ── overall economics ──
    gross = [ (t["exit_premium"] - t["entry_premium"]) * t["qty"] for t in trades]
    net = [t["pnl"] for t in trades]
    fees = [t.get("charges") or 0 for t in trades]
    qty = Counter(t["qty"] for t in trades)
    prem = [t["entry_premium"] for t in trades]
    hold = [(t["exit_ts"] - t["entry_ts"]).total_seconds() / 60 for t in trades if t["entry_ts"] and t["exit_ts"]]
    p("\nOVERALL: trades", len(trades), "gross", round(sum(gross)), "fees", round(sum(fees)), "net", round(sum(net)),
      "| win rate", round(sum(1 for x in net if x > 0) / len(net), 3), "| qty", dict(qty))
    p("  entry premium median", round(statistics.median(prem), 1), "p10", round(sorted(prem)[len(prem)//10], 1),
      "p90", round(sorted(prem)[len(prem)*9//10], 1))
    p("  hold minutes median", round(statistics.median(hold), 1), "mean", round(statistics.mean(hold), 1))
    p("  exit reasons", Counter(t["exit_reason"] for t in trades), "pricing", Counter(t.get("pricing") for t in trades))
    p("  premium return per trade (gross %): mean", round(statistics.mean((t["exit_premium"] / t["entry_premium"] - 1) * 100 for t in trades), 2),
      "median", round(statistics.median((t["exit_premium"] / t["entry_premium"] - 1) * 100 for t in trades), 2))
    by_reason = defaultdict(list)
    for t in trades:
        by_reason[t["exit_reason"]].append((t["exit_premium"] / t["entry_premium"] - 1) * 100)
    p("  premium % by exit reason:", {k: (len(v), round(statistics.mean(v), 1)) for k, v in by_reason.items()})
    p("  by option type:", {k: (len(v), round(sum(v))) for k, v in
                            {ot: [t["pnl"] for t in trades if t["option_type"] == ot] for ot in ("CE", "PE")}.items()})
    # STT: trades before the 2026-10-02 fee fix never paid it — what would they have paid?
    stt_missing = sum(t["exit_premium"] * t["qty"] * (0.0015 if t["session"] >= "2026-04-01" else 0.001)
                      for t in trades if t["session"] < "2026-10-02")
    p("  STT never charged before 2026-10-02:", round(stt_missing))

    # ── by expiry distance (NIFTY weekly expiry = Tuesday since 2025-09; Monday if Tuesday is a holiday) ──
    from tradingai_shared import nse_calendar as cal

    def expiry_for(d):
        x = d
        while x.weekday() != 1:
            x += timedelta(days=1)
        while not cal.is_listed_trading_day(x):
            x -= timedelta(days=1)
        return x
    dte_bins = defaultdict(list)
    for t in trades:
        d = date.fromisoformat(t["session"])
        dte = (expiry_for(d) - d).days
        t["dte"] = dte
        dte_bins[min(dte, 4)].append(t)
    p("\nBY DAYS TO EXPIRY (0 = expiry day):")
    for k in sorted(dte_bins):
        xs = dte_bins[k]
        p(f"  dte {k}: n {len(xs)}, net {round(sum(x['pnl'] for x in xs))}, per trade {round(statistics.mean(x['pnl'] for x in xs))}, "
          f"premium median {round(statistics.median(x['entry_premium'] for x in xs), 1)}, "
          f"win {round(sum(1 for x in xs if x['pnl'] > 0) / len(xs), 3)}")
    # by entry hour
    hrs = defaultdict(list)
    for t in trades:
        if t["entry_ts"]:
            hrs[t["entry_ts"].hour].append(t["pnl"])
    p("BY ENTRY HOUR:", {h: (len(v), round(statistics.mean(v))) for h, v in sorted(hrs.items())})

    # ── per strategy ──
    per = defaultdict(list)
    for t in sorted(trades, key=lambda x: x["exit_ts"] or datetime.min.replace(tzinfo=IST)):
        per[t["key"]].append(t)
    rows = []
    for k, xs in per.items():
        nets = [x["pnl"] for x in xs]
        rows.append((k, len(nets), sum(nets), statistics.mean(nets), tstat(nets)))
    rows.sort(key=lambda r: -r[2])
    pos = sum(1 for r in rows if r[2] > 0)
    p(f"\nPER STRATEGY: {len(rows)} strategies traded; {pos} net positive; "
      f"t>2: {sum(1 for r in rows if (r[4] or 0) > 2)}, t<-2: {sum(1 for r in rows if (r[4] or 0) < -2)}")
    p("  top 10:", [(r[0], r[1], round(r[2]), round(r[4], 2) if r[4] else None) for r in rows[:10]])
    p("  bottom 10:", [(r[0], r[1], round(r[2]), round(r[4], 2) if r[4] else None) for r in rows[-10:]])
    p("  trades per strategy: median", statistics.median(r[1] for r in rows), "max", max(r[1] for r in rows))
    # persistence: first half vs second half of sessions
    mid = sessions[len(sessions) // 2]
    a, b = [], []
    for k, xs in per.items():
        h1 = [x["pnl"] for x in xs if x["session"] < mid]
        h2 = [x["pnl"] for x in xs if x["session"] >= mid]
        if len(h1) >= 5 and len(h2) >= 5:
            a.append(statistics.mean(h1)); b.append(statistics.mean(h2))

    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
        for i, j in enumerate(o):
            r[j] = i
        return r
    if len(a) > 10:
        ra, rb = rank(a), rank(b)
        n = len(a)
        rho = 1 - 6 * sum((x - y) ** 2 for x, y in zip(ra, rb)) / (n * (n * n - 1))
        top_q = [i for i in range(n) if ra[i] >= n * 3 // 4]
        p(f"  PERSISTENCE (split at {mid}): {n} strategies with 5+ trades in both halves; Spearman {rho:.3f}; "
          f"first-half top quartile -> second-half mean per trade {statistics.mean(b[i] for i in top_q):.0f} "
          f"(all: {statistics.mean(b):.0f}); first-half positive {sum(1 for x in a if x > 0)}, second-half positive {sum(1 for x in b if x > 0)}")
    # how many 'significant' winners would luck produce?
    p(f"  luck check: with {len(rows)} strategies, ~{len(rows) * 0.023:.1f} reach t>2 by chance even if none has an edge")

    # ── what NIFTY did during each trade ──
    nb = read_file("NIFTY", "5m")
    nt = list(nb.t)

    def spot_at(ts):
        e = int(ts.timestamp())
        i = bisect_right(nt, e - 300) - 1          # last 5m bar closed by ts
        return nb.c[i] if i >= 0 and e - nt[i] < 1800 else None
    dirn = []
    for t in trades:
        if not t["entry_ts"] or not t["exit_ts"]:
            continue
        s0, s1 = spot_at(t["entry_ts"]), spot_at(t["exit_ts"])
        if not s0 or not s1:
            continue
        mv = (s1 / s0 - 1) * 1e4                      # bp
        signed = mv if t["option_type"] == "CE" else -mv
        dirn.append((signed, (t["exit_premium"] / t["entry_premium"] - 1) * 100, t["pnl"], t))
    p(f"\nDIRECTION: {len(dirn)} trades with NIFTY 5m spot at entry and exit")
    right = [d for d in dirn if d[0] > 0]
    p(f"  NIFTY moved the bought option's way on {len(right) / len(dirn):.3f} of trades; mean favourable move {statistics.mean(d[0] for d in dirn):.1f} bp")
    for lo, hi in ((-1e9, -30), (-30, -10), (-10, 0), (0, 10), (10, 30), (30, 1e9)):
        xs = [d for d in dirn if lo <= d[0] < hi]
        if xs:
            p(f"  NIFTY move in option's favour {lo:>6} .. {hi:<6} bp: n {len(xs):4d}, premium {statistics.mean(d[1] for d in xs):+6.1f}%, "
              f"net/trade {statistics.mean(d[2] for d in xs):+8.0f}")
    # premium change when NIFTY did not move: the cost of holding (theta + spread-free decay)
    flat = [d for d in dirn if abs(d[0]) < 5]
    if flat:
        p(f"  flat NIFTY (|move| < 5 bp): n {len(flat)}, premium {statistics.mean(d[1] for d in flat):+.1f}%, "
          f"hold {statistics.median((d[3]['exit_ts'] - d[3]['entry_ts']).total_seconds() / 60 for d in flat):.0f} min")
    # per-strategy direction hit rate vs 50%
    hit = defaultdict(list)
    for d in dirn:
        hit[d[3]["key"]].append(1 if d[0] > 0 else 0)
    hr = [(k, len(v), sum(v) / len(v)) for k, v in hit.items() if len(v) >= 20]
    zs = [(h - 0.5) / math.sqrt(0.25 / n) for _k, n, h in hr]
    p(f"  per-strategy direction hit rate (20+ trades, {len(hr)} strategies): mean {statistics.mean(h for _k, _n, h in hr):.3f}, "
      f"best {max(h for _k, _n, h in hr):.3f}, z>2: {sum(1 for z in zs if z > 2)}, z<-2: {sum(1 for z in zs if z < -2)}")

    # ── the scoreboard and the ANTI rows ──
    sc = [s async for s in db["prelive_strategy_scores"].find({})]
    traded = [s for s in sc if s.get("trades")]
    p(f"\nSCOREBOARD: {len(sc)} rows, {len(traded)} traded, positive {sum(1 for s in traded if s['net_pnl'] > 0)}, "
      f"sum net {round(sum(s['net_pnl'] for s in traded))}")
    anti_fee_gift = sum(t.get("charges") or 0 for t in trades)
    p(f"  ANTI rows negate net P&L, so they count the buyer's Rs{round(anti_fee_gift):,} of fees as INCOME; a real seller "
      f"would also pay ~the same again")
    st = await db["prelive_state"].find_one({"_id": "engine"})
    if st:
        p("  engine state:", {k: st.get(k) for k in ("initial_capital", "balance", "equity", "realized_all_time", "universe_size", "universe_source")})
    dp = [d async for d in db["prelive_daily_pnl"].find({}).sort("session", 1)]
    p("  daily docs:", len(dp), "sum net", round(sum(d.get("net_pnl") or 0 for d in dp)), "green", sum(1 for d in dp if (d.get("net_pnl") or 0) > 0))
    inst = await db["instruments"].find_one({"asset_class": "INDEX_OPTION", "symbol": {"$regex": "^NIFTY-"}},
                                            {"lot_size": 1, "symbol": 1, "expiry": 1})
    p("  instrument master lot size for NIFTY options:", inst)
    json.dump({"rows": [(r[0], r[1], r[2], r[3], r[4]) for r in rows]}, open("/out/prelive_strats.json", "w"))


asyncio.run(main())
