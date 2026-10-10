"""Separate slippage from edge, test the mirror, audit the Live Intraday picks. READ ONLY.

Slippage is inside the backtest's fill prices, so `gross` is already after slippage. The
file does not carry each trade's bp, so it is approximated with the live desk's measured
mean (2.76 bp a side) on the entry and on every market exit (stop/time/eod). That is an
ASSUMPTION, stated as one; targets are limit orders and pay none.
"""
import asyncio
import gzip
import json
import math
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, "/app/backend")
from app.core.db import db                                                  # noqa: E402

PATH = "/data/intraday/backtests/v2-20261010-0605-trades.jsonl.gz"
SLIP = 2.76            # bp a side, mean of the live desk's 1,596 positions
COST_BP = 4.02         # Angel intraday card, measured


def tstat(xs):
    if len(xs) < 2:
        return 0.0
    sd = st.pstdev(xs)
    return st.mean(xs) / (sd / math.sqrt(len(xs))) if sd else 0.0


by = defaultdict(list)
with gzip.open(PATH, "rt") as fh:
    for raw in fh:
        r = json.loads(raw)
        if r[0].endswith("~opt"):
            continue
        notl = abs(r[5] * r[7])
        market_exit = r[11] != "target"
        slip_rs = notl * SLIP / 1e4 * (1 + (1 if market_exit else 0))
        by[r[0]].append({"notl": notl, "g": r[8], "f": r[9], "slip": slip_rs})

print("=" * 108)
print("A. HOW MUCH OF THE 'GROSS' LOSS IS MODELLED SLIPPAGE?")
print("=" * 108)
allr = [x for v in by.values() for x in v]
NOTL = sum(x["notl"] for x in allr)
g = sum(x["g"] for x in allr); f = sum(x["f"] for x in allr); s = sum(x["slip"] for x in allr)
print(f"  gross as booked (after slippage)   {g/NOTL*1e4:+7.2f} bp a trade")
print(f"  modelled slippage (approx.)        {s/NOTL*1e4:+7.2f} bp")
print(f"  => frictionless edge               {(g+s)/NOTL*1e4:+7.2f} bp")
print(f"  fees                               {f/NOTL*1e4:+7.2f} bp")
print(f"  total friction to overcome         {(s+f)/NOTL*1e4:+7.2f} bp "
      f"= {(s+f)/(g+s):.1f}x the frictionless edge" if g + s > 0 else "")

print("\n" + "=" * 108)
print("B. SLIPPAGE SCENARIOS for every strategy whose FRICTIONLESS edge is positive")
print("=" * 108)
print(f"  {'strategy':<24} {'n':>6} {'raw bp':>7} | {'net bp at slippage:':>19} "
      f"{'modelled':>9} {'half':>7} {'zero':>7} | {'t(raw)':>7}  needs slip <= ")
rows = []
for sid, v in by.items():
    notl = sum(x["notl"] for x in v)
    raw = [(x["g"] + x["slip"]) / x["notl"] * 1e4 for x in v]
    rawbp = sum(x["g"] + x["slip"] for x in v) / notl * 1e4
    if rawbp <= 0:
        continue
    slipbp = sum(x["slip"] for x in v) / notl * 1e4
    feebp = sum(x["f"] for x in v) / notl * 1e4
    # per-side slippage at which net = 0: raw - fee - k*slip_share = 0
    share = slipbp / SLIP if SLIP else 0          # (1 + market-exit share)
    be = (rawbp - feebp) / share if share else 0
    rows.append((sid, len(v), rawbp, rawbp - feebp - slipbp, rawbp - feebp - slipbp / 2,
                 rawbp - feebp, tstat(raw), be))
for r in sorted(rows, key=lambda r: -r[2]):
    print(f"  {r[0]:<24} {r[1]:>6,} {r[2]:>7.2f} | {'':>19} {r[3]:>9.2f} {r[4]:>7.2f} "
          f"{r[5]:>7.2f} | {r[6]:>7.2f}  "
          + (f"{r[7]:.2f} bp a side" if r[7] > 0 else "never (fees alone exceed it)"))
print(f"\n  {len(rows)} of {len(by)} strategies have a positive frictionless edge.")

print("\n" + "=" * 108)
print("C. THE MIRROR — would trading every signal BACKWARDS make money?")
print("=" * 108)
print("  The mirror's gross is the negative of the original's FRICTIONLESS P&L, and it pays")
print("  its own fees and slippage. (Approximation: the original's stop exits become the")
print("  mirror's targets and vice versa, so the slippage pattern is not a perfect swap.)")
mir = []
for sid, v in by.items():
    notl = sum(x["notl"] for x in v)
    rawbp = sum(x["g"] + x["slip"] for x in v) / notl * 1e4
    feebp = sum(x["f"] for x in v) / notl * 1e4
    slipbp = sum(x["slip"] for x in v) / notl * 1e4
    mir.append((sid, len(v), -rawbp, -rawbp - feebp - slipbp))
whole = -((g + s) / NOTL * 1e4) - f / NOTL * 1e4 - s / NOTL * 1e4
print(f"\n  the whole book, mirrored: {whole:+.2f} bp a trade net")
print(f"\n  {'strategy':<24} {'n':>6} {'mirror raw bp':>14} {'mirror net bp':>14}")
for r in sorted(mir, key=lambda r: -r[3])[:8]:
    print(f"  {r[0]:<24} {r[1]:>6,} {r[2]:>14.2f} {r[3]:>14.2f}")
print(f"\n  mirrors with positive net: {len([r for r in mir if r[3] > 0])} of {len(mir)}")
print("  (Picking the worst of 52 and inverting it is selection on an extreme, exactly as")
print("   picking the best is. Any mirror is a NEW hypothesis needing its own pre-registered")
print("   out-of-sample test, not a finding.)")


async def live_intraday():
    print("\n" + "=" * 108)
    print("D. LIVE INTRADAY — the 8 curated picks, as they stand")
    print("=" * 108)
    from app.services import live_intraday_engine as L
    picks = getattr(L, "SHORTLIST", None) or getattr(L, "CURATED", None) or \
        getattr(L, "PICKS", None)
    print(f"  shortlist constant: {picks!r}"[:900])
    rows = [d async for d in db["live_intraday_trades"].find({})]
    by_s = defaultdict(list)
    for d in rows:
        by_s[(d.get("book"), d.get("strategy_id"))].append(d)
    print(f"\n  {'book':<6} {'strategy':<40} {'n':>4} {'gross':>9} {'fees':>8} {'net':>9}")
    for (bk, sid), v in sorted(by_s.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        gg = sum(x.get("gross_pnl") or 0 for x in v)
        ff = sum(x.get("fees") or 0 for x in v)
        print(f"  {str(bk):<6} {str(sid)[:39]:<40} {len(v):>4} {gg:>9,.0f} {ff:>8,.0f} "
              f"{gg-ff:>9,.0f}")
    days = sorted({str(d.get("closed_at"))[:10] for d in rows})
    print(f"\n  record spans {len(days)} days: {days[:1]} .. {days[-1:]}")

asyncio.run(live_intraday())
