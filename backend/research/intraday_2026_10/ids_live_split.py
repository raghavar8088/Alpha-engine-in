"""Intraday Stocks live record: family/timeframe split, the honest sample size, cost per
trade, fill realism, liquidity, and the gate's stored verdicts. READ ONLY.

The split by category uses the CATALOG's own labels. A first draft grouped families by hand
and filed `rsi_momentum` (a momentum rule) under mean reversion.

Four sessions cannot speak to edge (section B makes that explicit); the two-year verdict is
in ids_walkforward*.py."""
import asyncio
import math
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, "/app/backend")

from app.services.intraday_v2_strategies import CATALOG                    # noqa: E402
from app.core.db import (                                              # noqa: E402
    intraday_lab_positions_collection as POS,
    intraday_lab_scores_collection as SCORES,
    intraday_lab_trades_collection as TR,
)

SPEC = {sp.strategy_id: sp for sp in CATALOG}


def tstat(xs):
    if len(xs) < 2:
        return 0.0
    sd = st.pstdev(xs)
    return (st.mean(xs) / (sd / math.sqrt(len(xs)))) if sd else 0.0


def pf(xs):
    w = sum(x for x in xs if x > 0)
    L = abs(sum(x for x in xs if x <= 0))
    return (w / L) if L else float("inf") if w else 0.0


def parse(sid):
    """iv2_<family>_<tf>  ->  (family, timeframe)."""
    s = (sid or "").replace("iv2_", "")
    for tf in ("_15m", "_45m", "_1h"):
        if s.endswith(tf):
            return s[: -len(tf)], tf[1:]
    return s, "day/other"


async def main():
    trades = [t async for t in TR.find({})]
    pos = {p["position_id"]: p async for p in POS.find({})}
    net = {t["trade_id"]: (t.get("gross_pnl") or 0) - (t.get("fees") or 0) for t in trades}

    print("=" * 96)
    print("A. BY FAMILY — is the winner a family or a timeframe?")
    print("=" * 96)
    by_fam, by_tf, by_kind = defaultdict(list), defaultdict(list), defaultdict(list)
    for t in trades:
        fam, tf = parse(t.get("strategy_id"))
        g = t.get("gross_pnl") or 0
        n = net[t["trade_id"]]
        by_fam[fam].append((g, n))
        by_tf[tf].append((g, n))
        spec = SPEC.get(t.get("strategy_id"))
        by_kind[spec.category if spec else "other"].append((g, n))

    def block(title, d, label):
        print(f"\n  {label:<20} {'n':>5} {'gross':>12} {'net':>12} {'gPF':>6} {'nPF':>6} "
              f"{'net/trade':>10} {'t(net)':>7}")
        print("  " + "-" * 86)
        for k, v in sorted(d.items(), key=lambda kv: -sum(x[1] for x in kv[1])):
            gs = [x[0] for x in v]
            ns = [x[1] for x in v]
            print(f"  {k:<20} {len(v):>5} {sum(gs):>12,.0f} {sum(ns):>12,.0f} "
                  f"{min(pf(gs),99):>6.2f} {min(pf(ns),99):>6.2f} "
                  f"{st.mean(ns):>10,.0f} {tstat(ns):>7.2f}")

    block("family", by_fam, "family")
    block("timeframe", by_tf, "timeframe")
    block("kind", by_kind, "kind")

    print("\n" + "=" * 96)
    print("B. THE REAL SAMPLE SIZE — trades are not independent observations")
    print("=" * 96)
    by_day = defaultdict(float)
    for t in trades:
        by_day[t["closed_at"].date().isoformat()] += net[t["trade_id"]]
    daily = [by_day[d] for d in sorted(by_day)]
    allnet = [net[t["trade_id"]] for t in trades]
    print(f"  treating each TRADE as independent : n={len(allnet):,}  "
          f"mean Rs {st.mean(allnet):,.0f}  t={tstat(allnet):.2f}")
    print(f"  treating each DAY  as independent  : n={len(daily)}      "
          f"mean Rs {st.mean(daily):,.0f}  t={tstat(daily):.2f}")
    print("\n  daily net: " + "  ".join(f"{d:,.0f}" for d in daily))
    print("\n  Four days is the whole record. Hundreds of trades inside one day share that")
    print("  day's market, so the per-trade t-stat FLATTERS the evidence; the honest unit")
    print("  here is the day, and four of them can establish nothing about edge either way.")

    # how many strategy-days would be needed
    sd = st.pstdev(daily) if len(daily) > 1 else 0
    if sd:
        need = (2.0 * sd / abs(st.mean(daily))) ** 2 if st.mean(daily) else 0
        print(f"\n  daily sd Rs {sd:,.0f}. To show a mean of this size differs from zero at t=2")
        print(f"  would need about {need:,.0f} trading days (~{need/21:,.0f} months) at this variance.")

    print("\n" + "=" * 96)
    print("C. COST PER TRADE vs THE EDGE IT HAS TO BEAT")
    print("=" * 96)
    rows = []
    for p in pos.values():
        ep, xp, q = p.get("entry_price") or 0, p.get("exit_price") or 0, p.get("qty") or 0
        notion = ep * q
        fb = p.get("fee_breakdown") or {}
        fee = fb.get("total") or sum(v for k, v in fb.items()
                                     if k != "total" and isinstance(v, (int, float)))
        if notion:
            rows.append((notion, fee, abs(xp - ep) / ep * 1e4 if ep else 0))
    notions = [r[0] for r in rows]
    fees = [r[1] for r in rows]
    moves = [r[2] for r in rows]
    print(f"  median position size      Rs {st.median(notions):>12,.0f}")
    print(f"  median round-trip cost    Rs {st.median(fees):>12,.0f}")
    print(f"  cost as % of position     {st.median(fees)/st.median(notions)*100:>12.3f}%  "
          f"({st.median(fees)/st.median(notions)*1e4:.1f} bp)")
    print(f"  median |price move|       {st.median(moves):>12.1f} bp")
    print(f"\n  So the median trade must capture {st.median(fees)/st.median(notions)*1e4:.0f} bp "
          f"to break even and actually moves {st.median(moves):.0f} bp.")

    print("\n" + "=" * 96)
    print("D. SLIPPAGE AND FILL REALISM — what the desk assumed")
    print("=" * 96)
    slip = defaultdict(int)
    basis = defaultdict(int)
    src = defaultdict(int)
    for p in pos.values():
        slip[p.get("slippage_bp")] += 1
        b = (p.get("fill_basis") or "?").split("@")[0].strip()
        basis[b] += 1
        src[p.get("ltp_source") or "?"] += 1
    print("  slippage_bp applied :", dict(sorted(slip.items(), key=lambda kv: -kv[1])))
    print("  ltp_source          :", dict(sorted(src.items(), key=lambda kv: -kv[1])))
    print("  entry fill basis    :")
    for k, v in sorted(basis.items(), key=lambda kv: -kv[1])[:8]:
        print(f"      {v:>5}  {k}")

    print("\n" + "=" * 96)
    print("E. LIQUIDITY — is a position big enough to move the stock?")
    print("=" * 96)
    tc = [(p.get("turnover_cr") or 0, (p.get("entry_price") or 0) * (p.get("qty") or 0), p)
          for p in pos.values()]
    have = [x for x in tc if x[0] > 0]
    print(f"  positions with turnover_cr recorded: {len(have):,} of {len(tc):,}")
    if have:
        ratio = sorted(((pos_val / (t_cr * 1e7) * 100, t_cr, pos_val, p)
                        for t_cr, pos_val, p in have), key=lambda x: x[0])
        print("  position as % of that stock's DAILY TRADED VALUE:")
        for q, lbl in ((0.5, "median"), (0.9, "90th pct"), (0.99, "99th pct"), (1.0, "worst")):
            i = min(int(q * len(ratio)), len(ratio) - 1)
            r = ratio[i]
            print(f"      {lbl:<10} {r[0]:>7.3f}%   (Rs {r[2]:>12,.0f} in a stock doing "
                  f"Rs {r[1]:,.0f} cr/day — {r[3].get('symbol')})")

    print("\n" + "=" * 96)
    print("F. THE GATE'S STORED VERDICTS")
    print("=" * 96)
    scores = [s async for s in SCORES.find({})]
    vd = defaultdict(list)
    for s in scores:
        vd[str(s.get("verdict"))].append(s)
    for k, v in sorted(vd.items(), key=lambda kv: -len(kv[1])):
        print(f"  {k:<14} {len(v):>3}")
    rs = defaultdict(int)
    for s in scores:
        for r in (s.get("verdict_reasons") or []):
            rs[str(r)[:78]] += 1
    print("\n  reasons given:")
    for k, v in sorted(rs.items(), key=lambda kv: -kv[1])[:12]:
        print(f"    {v:>3}x  {k}")
    best = sorted(scores, key=lambda s: -(s.get("t_stat") or -99))[:5]
    print(f"\n  best 5 by stored t_stat (threshold {scores[0].get('t_threshold') if scores else '?'}):")
    for s in best:
        print(f"    {str(s.get('strategy_id'))[:30]:<32} t={s.get('t_stat')} "
              f"trades={s.get('trades')} pf={s.get('profit_factor')} "
              f"dd={s.get('max_drawdown_pct')} verdict={s.get('verdict')}")


asyncio.run(main())
