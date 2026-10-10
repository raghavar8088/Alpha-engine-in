"""Are 504 strategies 504 bets, or the same bet many times? READ ONLY."""
import asyncio, sys
from collections import defaultdict, Counter
sys.path.insert(0, "/app/backend")
from app.core.db import db
async def main():
    for label, coll, keyf in (
        ("Patterns (504)", "pattern_positions",
         lambda x: (x.get("symbol"), x.get("side"), round(x.get("entry_price") or 0, 2),
                    str(x.get("opened_at"))[:16])),
        ("Tournament (54)", "intraday_lab_positions",
         lambda x: (x.get("symbol"), x.get("side"), round(x.get("entry_price") or 0, 2),
                    str(x.get("opened_at"))[:16])),
    ):
        rows = [x async for x in db[coll].find({"status": "CLOSED"})]
        g = defaultdict(list)
        for x in rows:
            g[keyf(x)].append(x)
        sizes = Counter(len(v) for v in g.values())
        dup_rows = sum(len(v) for v in g.values() if len(v) > 1)
        print(f"=== {label}: {len(rows):,} closed, {len(g):,} distinct (symbol, side, price, minute) ===")
        print(f"    rows that share a bet with another: {dup_rows:,} ({dup_rows/len(rows)*100:.0f}%)")
        print(f"    cluster sizes: {dict(sorted(sizes.items())[:12])}")
        big = sorted(g.items(), key=lambda kv: -len(kv[1]))[:3]
        for k, v in big:
            pnl = sum(x.get("realized_pnl") or 0 for x in v)
            cap = sum(x.get("capital_deployed") or 0 for x in v)
            print(f"      {k[0]} {k[1]} @{k[2]} x{len(v)} strategies -> "
                  f"Rs {cap:,.0f} deployed on ONE idea, P&L Rs {pnl:,.0f}")
        # concurrent exposure per day
        byday = defaultdict(float)
        for x in rows:
            d = str(x.get("opened_on") or str(x.get("opened_at"))[:10])
            byday[d] += x.get("capital_deployed") or 0
        print("    capital deployed per day (sum of opens):")
        for d in sorted(byday):
            print(f"      {d}  Rs {byday[d]:>16,.0f}")
        print()
asyncio.run(main())
