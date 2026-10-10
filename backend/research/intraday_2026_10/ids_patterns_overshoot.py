"""How much of the Patterns book's P&L is overshoot past its own target/stop? READ ONLY."""
import asyncio, sys
from collections import defaultdict
sys.path.insert(0, "/app/backend")
from app.core.db import db
P = db["pattern_positions"]

async def main():
    closed = [x async for x in P.find({"status": "CLOSED"})]
    buckets = defaultdict(lambda: {"n":0,"booked":0.0,"atlevel":0.0,"over":0.0})
    worst = []
    for x in closed:
        side = 1 if x.get("side") == "BUY" else -1
        ep = x.get("entry_price") or 0; xp = x.get("exit_price") or 0
        q = x.get("qty") or 0; r = str(x.get("exit_reason"))
        tgt, stp = x.get("target"), x.get("stoploss")
        booked = side * (xp - ep) * q
        lvl = tgt if r == "target" else stp if r == "stoploss" else None
        b = buckets[r]; b["n"] += 1; b["booked"] += booked
        if lvl is None:
            b["atlevel"] += booked
            continue
        at = side * (lvl - ep) * q
        b["atlevel"] += at
        b["over"] += booked - at
        if r == "target" and ep:
            worst.append((booked - at, x, (xp - lvl) / lvl * 100 * side))
    print(f"{'exit reason':<13}{'n':>7}{'booked gross':>16}{'if filled AT the level':>24}{'overshoot':>15}")
    print("-" * 76)
    tb = ta = to = 0
    for r, b in sorted(buckets.items(), key=lambda kv: -kv[1]["over"]):
        tb += b["booked"]; ta += b["atlevel"]; to += b["over"]
        print(f"{r:<13}{b['n']:>7,}{b['booked']:>16,.0f}{b['atlevel']:>24,.0f}{b['over']:>15,.0f}")
    print("-" * 76)
    print(f"{'TOTAL':<13}{sum(b['n'] for b in buckets.values()):>7,}{tb:>16,.0f}{ta:>24,.0f}{to:>15,.0f}")
    fees = sum((x.get("fee_breakdown") or {}).get("total") or x.get("fees") or 0 for x in closed)
    print(f"\n  fees charged            Rs {fees:>14,.0f}")
    print(f"  net as reported         Rs {tb - fees:>14,.0f}")
    print(f"  net if filled AT levels Rs {ta - fees:>14,.0f}")
    print(f"  => Rs {to:,.0f} of the reported P&L is price that ran PAST the strategy's own")
    print("     exit level before a polling cycle noticed. A real limit order fills at the")
    print("     level; a real stop fills at or through it, never better.")
    # slippage that is never charged
    notion = sum((x.get('entry_price') or 0)*(x.get('qty') or 0) for x in closed)
    for bp in (2, 3, 5):
        print(f"  plus un-charged slippage at {bp} bp/side: Rs {notion*2*bp/1e4:,.0f}")
    print("\n  largest single overshoots on a 'target' exit:")
    worst.sort(key=lambda t: -t[0])
    for over, x, pct in worst[:8]:
        print(f"    {str(x.get('symbol')):<11} {str(x.get('side')):<4} {str(x.get('timeframe')):<4} "
              f"entry {x.get('entry_price'):>9.2f} target {x.get('target'):>9.2f} "
              f"exit {x.get('exit_price'):>9.2f}  ({pct:+.1f}% past target)  "
              f"+Rs {over:>9,.0f} manufactured")
asyncio.run(main())
