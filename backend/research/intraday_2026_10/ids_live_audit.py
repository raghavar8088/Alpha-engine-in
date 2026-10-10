"""Intraday Stocks — what the live paper record actually says. READ ONLY."""
import asyncio
import math
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, "/app/backend")

from app.core.db import (                                              # noqa: E402
    intraday_lab_positions_collection as POS,
    intraday_lab_scores_collection as SCORES,
    intraday_lab_trades_collection as TR,
)

IST_OFFSET = 5.5 * 3600


def pf(wins, losses):
    L = abs(sum(losses))
    return (sum(wins) / L) if L else float("inf") if wins else 0.0


def tstat(xs):
    if len(xs) < 2:
        return 0.0
    sd = st.pstdev(xs)
    return (st.mean(xs) / (sd / math.sqrt(len(xs)))) if sd else 0.0


async def main():
    trades = [t async for t in TR.find({})]
    positions = {p["position_id"]: p async for p in POS.find({})}
    print(f"trades {len(trades):,}   positions {len(positions):,}\n")

    days = sorted({t["closed_at"].date().isoformat() for t in trades if t.get("closed_at")})
    print("=" * 100)
    print("1. HOW LONG IS THIS RECORD?")
    print("=" * 100)
    print(f"  distinct closing days : {len(days)}   {days[0]} .. {days[-1]}")
    per_day = defaultdict(list)
    for t in trades:
        per_day[t["closed_at"].date().isoformat()].append(t)
    print(f"\n  {'day':<12} {'trades':>7} {'gross':>13} {'fees':>12} {'net':>13}")
    for d in days:
        ts = per_day[d]
        g = sum(x.get("gross_pnl") or 0 for x in ts)
        f = sum(x.get("fees") or 0 for x in ts)
        print(f"  {d:<12} {len(ts):>7,} {g:>13,.0f} {f:>12,.0f} {g - f:>13,.0f}")

    g_all = sum(t.get("gross_pnl") or 0 for t in trades)
    f_all = sum(t.get("fees") or 0 for t in trades)
    print(f"\n  {'TOTAL':<12} {len(trades):>7,} {g_all:>13,.0f} {f_all:>12,.0f} {g_all - f_all:>13,.0f}")
    print(f"\n  fees / gross profit    : {f_all / g_all:.2f}x" if g_all > 0 else "")
    print(f"  gross per trade        : Rs {g_all / len(trades):>9,.0f}")
    print(f"  fees  per trade        : Rs {f_all / len(trades):>9,.0f}")
    print(f"  net   per trade        : Rs {(g_all - f_all) / len(trades):>9,.0f}")

    print("\n" + "=" * 100)
    print("2. IS THE GROSS EDGE EVEN THERE, BEFORE COSTS?")
    print("=" * 100)
    gross = [t.get("gross_pnl") or 0 for t in trades]
    net = [(t.get("gross_pnl") or 0) - (t.get("fees") or 0) for t in trades]
    gw = [x for x in gross if x > 0]
    gl = [x for x in gross if x <= 0]
    nw = [x for x in net if x > 0]
    nl = [x for x in net if x <= 0]
    print(f"  {'':<22} {'GROSS (no costs)':>20} {'NET (real)':>20}")
    print(f"  {'win rate':<22} {len(gw) / len(gross) * 100:>19.1f}% {len(nw) / len(net) * 100:>19.1f}%")
    print(f"  {'avg win':<22} {st.mean(gw) if gw else 0:>20,.0f} {st.mean(nw) if nw else 0:>20,.0f}")
    print(f"  {'avg loss':<22} {st.mean(gl) if gl else 0:>20,.0f} {st.mean(nl) if nl else 0:>20,.0f}")
    print(f"  {'profit factor':<22} {pf(gw, gl):>20.3f} {pf(nw, nl):>20.3f}")
    print(f"  {'expectancy / trade':<22} {st.mean(gross):>20,.0f} {st.mean(net):>20,.0f}")
    print(f"  {'t-stat of mean':<22} {tstat(gross):>20.2f} {tstat(net):>20.2f}")
    print("\n  A t-stat below ~2 means the mean is indistinguishable from zero at this sample size.")

    print("\n" + "=" * 100)
    print("3. WHAT DO THE COSTS CONSIST OF?")
    print("=" * 100)
    comp = defaultdict(float)
    turnover = 0.0
    n_fb = 0
    for p in positions.values():
        fb = p.get("fee_breakdown") or {}
        if fb:
            n_fb += 1
            for k, v in fb.items():
                if isinstance(v, (int, float)):
                    comp[k] += v
        ep, xp, q = p.get("entry_price") or 0, p.get("exit_price") or 0, p.get("qty") or 0
        turnover += (ep + xp) * q
    tot = sum(v for k, v in comp.items() if k != "total")
    print(f"  positions carrying a fee breakdown: {n_fb:,} of {len(positions):,}")
    print(f"\n  {'component':<20} {'Rs':>14} {'share':>8}  {'bp of turnover':>15}")
    for k, v in sorted(comp.items(), key=lambda kv: -kv[1]):
        if k == "total":
            continue
        print(f"  {k:<20} {v:>14,.0f} {v / tot * 100:>7.1f}% {v / turnover * 1e4:>15.2f}")
    print(f"  {'-' * 60}")
    print(f"  {'TOTAL':<20} {tot:>14,.0f} {100.0:>7.1f}% {tot / turnover * 1e4:>15.2f}")
    print(f"\n  round-trip turnover    : Rs {turnover:>16,.0f}")
    print(f"  all-in cost            : {tot / turnover * 1e4:.2f} bp of turnover "
          f"({tot / turnover * 1e4 / 2:.2f} bp a side)")
    print(f"  gross edge captured    : {g_all / turnover * 1e4:.2f} bp of turnover")
    print(f"  => the strategies must find {tot / turnover * 1e4:.1f} bp of edge per round trip "
          f"just to break even;\n     measured gross edge is {g_all / turnover * 1e4:.1f} bp.")

    print("\n" + "=" * 100)
    print("4. PER STRATEGY — sorted by NET")
    print("=" * 100)
    by_s = defaultdict(list)
    for t in trades:
        by_s[(t.get("strategy_id"), t.get("strategy_name"))].append(t)
    rows = []
    for (sid, sname), ts in by_s.items():
        g = [x.get("gross_pnl") or 0 for x in ts]
        n = [(x.get("gross_pnl") or 0) - (x.get("fees") or 0) for x in ts]
        f = sum(x.get("fees") or 0 for x in ts)
        rows.append({
            "id": sid, "name": sname or "", "n": len(ts),
            "gross": sum(g), "fees": f, "net": sum(n),
            "gwin": len([x for x in g if x > 0]) / len(g) * 100,
            "nwin": len([x for x in n if x > 0]) / len(n) * 100,
            "gpf": pf([x for x in g if x > 0], [x for x in g if x <= 0]),
            "npf": pf([x for x in n if x > 0], [x for x in n if x <= 0]),
            "t": tstat(n),
        })
    rows.sort(key=lambda r: -r["net"])
    print(f"  {'strategy':<34} {'n':>4} {'gross':>11} {'fees':>10} {'net':>11} "
          f"{'gWR%':>6} {'nWR%':>6} {'gPF':>6} {'nPF':>6} {'t':>6}")
    print("  " + "-" * 110)
    for r in rows:
        print(f"  {r['id'][:33]:<34} {r['n']:>4} {r['gross']:>11,.0f} {r['fees']:>10,.0f} "
              f"{r['net']:>11,.0f} {r['gwin']:>6.1f} {r['nwin']:>6.1f} "
              f"{min(r['gpf'], 99):>6.2f} {min(r['npf'], 99):>6.2f} {r['t']:>6.2f}")

    pos_net = [r for r in rows if r["net"] > 0]
    pos_gross = [r for r in rows if r["gross"] > 0]
    print(f"\n  strategies with ANY trades        : {len(rows)}")
    print(f"  positive GROSS (before costs)     : {len(pos_gross)}  ({len(pos_gross)/len(rows)*100:.0f}%)")
    print(f"  positive NET  (after costs)       : {len(pos_net)}  ({len(pos_net)/len(rows)*100:.0f}%)")
    print(f"  with >= 30 trades                 : {len([r for r in rows if r['n'] >= 30])}")
    print(f"  >= 30 trades AND net positive     : {len([r for r in rows if r['n'] >= 30 and r['net'] > 0])}")
    print(f"  >= 30 trades AND t >= 2           : {len([r for r in rows if r['n'] >= 30 and r['t'] >= 2])}")
    print(f"  >= 30 trades AND t >= 3.31 (gate) : {len([r for r in rows if r['n'] >= 30 and r['t'] >= 3.312])}")

    print("\n" + "=" * 100)
    print("5. WHY DO TRADES END?")
    print("=" * 100)
    by_r = defaultdict(list)
    for t in trades:
        by_r[t.get("exit_reason") or "?"].append(t)
    print(f"  {'exit reason':<16} {'n':>6} {'share':>7} {'gross':>13} {'fees':>12} {'net':>13} {'net/trade':>11}")
    for r, ts in sorted(by_r.items(), key=lambda kv: -len(kv[1])):
        g = sum(x.get("gross_pnl") or 0 for x in ts)
        f = sum(x.get("fees") or 0 for x in ts)
        print(f"  {r:<16} {len(ts):>6,} {len(ts)/len(trades)*100:>6.1f}% {g:>13,.0f} "
              f"{f:>12,.0f} {g-f:>13,.0f} {(g-f)/len(ts):>11,.0f}")

    print("\n" + "=" * 100)
    print("6. HOW LONG IS A TRADE HELD?")
    print("=" * 100)
    holds = []
    for t in trades:
        if t.get("opened_at") and t.get("closed_at"):
            holds.append(((t["closed_at"] - t["opened_at"]).total_seconds() / 60.0, t))
    holds.sort(key=lambda h: h[0])
    mins = [h[0] for h in holds]
    print(f"  median {st.median(mins):.1f} min   mean {st.mean(mins):.1f} min   "
          f"min {min(mins):.2f}   max {max(mins):.0f}")
    buckets = [(0, 1), (1, 5), (5, 15), (15, 60), (60, 180), (180, 10 ** 9)]
    print(f"\n  {'hold':<14} {'n':>6} {'share':>7} {'gross':>13} {'fees':>12} {'net':>13}")
    for lo, hi in buckets:
        sel = [t for m, t in holds if lo <= m < hi]
        if not sel:
            continue
        g = sum(x.get("gross_pnl") or 0 for x in sel)
        f = sum(x.get("fees") or 0 for x in sel)
        lbl = f"{lo}-{hi}m" if hi < 10 ** 9 else f"{lo}m+"
        print(f"  {lbl:<14} {len(sel):>6,} {len(sel)/len(holds)*100:>6.1f}% {g:>13,.0f} "
              f"{f:>12,.0f} {g-f:>13,.0f}")
    under1 = [t for m, t in holds if m < 1]
    if under1:
        print(f"\n  !! {len(under1):,} trades ({len(under1)/len(holds)*100:.0f}%) opened and closed "
              f"inside ONE MINUTE,\n     costing Rs {sum(x.get('fees') or 0 for x in under1):,.0f} in fees "
              f"for Rs {sum(x.get('gross_pnl') or 0 for x in under1):,.0f} gross.")

    print("\n" + "=" * 100)
    print("7. THE PROMOTION GATE'S OWN VERDICT")
    print("=" * 100)
    scores = [s async for s in SCORES.find({})]
    g_by = defaultdict(int)
    for s in scores:
        g_by[str(s.get("grade") or s.get("status") or "?")] += 1
    print(f"  scored strategies: {len(scores)}")
    for k, v in sorted(g_by.items(), key=lambda kv: -kv[1]):
        print(f"    {k:<24} {v}")
    keys = sorted({k for s in scores for k in s.keys()})
    print(f"\n  score fields: {keys}")


asyncio.run(main())
