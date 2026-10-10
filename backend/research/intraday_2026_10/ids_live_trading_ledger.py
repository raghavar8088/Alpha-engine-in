"""Live Trading (REAL money): state, arming, the 78 real trades, and the ledger gaps —
no charges recorded, and 49 closes by broker auto-square-off booked at the next
session's price. READ ONLY."""
import asyncio, sys, json
from collections import Counter, defaultdict
sys.path.insert(0, "/app/backend")
from bson import json_util
from app.core.db import db
def show(d, n=1400):
    d = dict(d); d.pop("_id", None)
    print(json.dumps(json.loads(json_util.dumps(d)), indent=1)[:n])
async def main():
    st = await db["live_trading_state"].find_one({})
    print("=== live_trading_state ==="); show(st or {}, 1500)
    print("\n=== live_trading_flags ===")
    async for f in db["live_trading_flags"].find({}):
        f.pop("_id", None); print("  ", json.loads(json_util.dumps(f)))
    trades = [t async for t in db["live_trading_trades"].find({}).sort("closed_at", 1)]
    print(f"\n=== live_trading_trades: {len(trades)} ===")
    if trades:
        show(trades[0], 1300)
        keys = Counter(k for t in trades for k in t.keys())
        print("\n  fields present:", sorted(keys))
        real_markers = ("broker_order_id", "order_id", "angel_order_id", "exchange_order_id",
                        "entry_order_id", "exit_order_id", "orderid")
        for m in real_markers:
            n = sum(1 for t in trades if t.get(m))
            if n: print(f"  {m:<18} present on {n} trades")
        mode = Counter(str(t.get("mode") or t.get("execution") or t.get("paper")) for t in trades)
        print("  mode/execution:", dict(mode))
        days = sorted({str(t.get("closed_at"))[:10] for t in trades})
        print(f"  span: {days[0]} .. {days[-1]}  ({len(days)} days)")
        net = sum(t.get("realized_pnl") or t.get("net_pnl") or 0 for t in trades)
        fees = sum(t.get("fees") or 0 for t in trades)
        print(f"  net Rs {net:,.2f}   fees Rs {fees:,.2f}")
async def ledger_gaps():
    trades = [t async for t in db["live_trading_trades"].find({})]
    with_x = [t for t in trades if t.get("exit_order_id")]
    no_x = [t for t in trades if not t.get("exit_order_id")]
    print(f"with exit order id : {len(with_x)}   exit reasons {dict(Counter(t.get('exit_reason') for t in with_x))}")
    print(f"WITHOUT exit id    : {len(no_x)}   exit reasons {dict(Counter(t.get('exit_reason') for t in no_x))}")
    byday = defaultdict(lambda: [0, 0])
    for t in trades:
        d = str(t.get("closed_at"))[:10]
        byday[d][0 if t.get("exit_order_id") else 1] += 1
    print("\n  day          with-id  no-id")
    for d in sorted(byday):
        print(f"  {d}   {byday[d][0]:>6} {byday[d][1]:>6}")
    pos = [p async for p in db["live_trading_positions"].find({})]
    print(f"\nlive_trading_positions: {len(pos)}; status {dict(Counter(p.get('status') for p in pos))}")
    keys = sorted({k for p in pos for k in p.keys()})
    print(f"  fields: {keys}")
    for k in ("exit_basis", "close_basis", "closed_by", "squared_off_by", "exit_note"):
        c = Counter(str(p.get(k))[:60] for p in pos if p.get(k))
        if c: print(f"  {k}: {dict(c.most_common(5))}")
    notional = sum((t.get("entry_price") or 0) * (t.get("qty") or 0) for t in trades)
    print(f"\n  real notional traded: Rs {notional:,.0f} over {len(trades)} round trips "
          f"(avg Rs {notional/len(trades):,.0f})")



async def both():
    await main()
    print()
    await ledger_gaps()

asyncio.run(both())
