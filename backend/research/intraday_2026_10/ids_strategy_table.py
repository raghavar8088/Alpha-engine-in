"""Per-strategy assessment rows, generated rather than transcribed. READ ONLY.

Prints markdown tables ready to paste into the report:
  1. every v2 tournament strategy: 2-year record, raw edge, break-even slippage, live 4 days
  2. the Patterns desk by timeframe and family, with targets filled AT the target and
     3 bp a side of slippage (the tournament's own mean is 2.76)
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
SLIP = 2.76
HOLD = "2026-05-13"
IST = timezone(timedelta(hours=5, minutes=30))
SPEC = {s.strategy_id: s for s in CATALOG}


def tstat(xs):
    if len(xs) < 2:
        return 0.0
    sd = st.pstdev(xs)
    return st.mean(xs) / (sd / math.sqrt(len(xs))) if sd else 0.0


async def main():
    by = defaultdict(list)
    with gzip.open(PATH, "rt") as fh:
        for raw in fh:
            r = json.loads(raw)
            if r[0].endswith("~opt"):
                continue
            notl = abs(r[5] * r[7])
            slip = notl * SLIP / 1e4 * (2 if r[11] != "target" else 1)
            day = datetime.fromtimestamp(r[3], IST).date().isoformat()
            by[r[0]].append((notl, r[8], r[9], r[10], slip, day))

    live = defaultdict(lambda: [0, 0.0])
    async for t in db["intraday_lab_trades"].find({}, {"strategy_id": 1, "gross_pnl": 1,
                                                       "fees": 1}):
        live[t["strategy_id"]][0] += 1
        live[t["strategy_id"]][1] += (t.get("gross_pnl") or 0) - (t.get("fees") or 0)

    rows = []
    for spec in CATALOG:
        v = by.get(spec.strategy_id, [])
        lv = live.get(spec.strategy_id, [0, 0.0])
        if not v:
            rows.append((spec, None, lv))
            continue
        notl = sum(x[0] for x in v)
        raw_trades = [(x[1] + x[4]) / x[0] * 1e4 for x in v]
        rawbp = sum(x[1] + x[4] for x in v) / notl * 1e4
        feebp = sum(x[2] for x in v) / notl * 1e4
        slipbp = sum(x[4] for x in v) / notl * 1e4
        share = slipbp / SLIP
        be = (rawbp - feebp) / share if share else 0
        hold = sum(x[3] for x in v if x[5] >= HOLD)
        rows.append((spec, {
            "n": len(v), "net": sum(x[3] for x in v), "netbp": sum(x[3] for x in v) / notl * 1e4,
            "raw": rawbp, "t": tstat(raw_trades), "be": be, "hold": hold}, lv))

    def decide(m):
        if m is None:
            return "INCUBATE (pre-registered; S4 study)"
        if m["raw"] <= 0:
            return "DISABLE — no edge even before costs"
        if m["t"] >= 3.312 and m["be"] >= 1.2:
            return "OPTIMIZE — measure real slippage (H1)"
        if m["be"] > 0:
            return "RESEARCH ONLY — edge < friction"
        return "DISABLE — fees alone exceed edge"

    print("| # | Strategy | Kind / TF | 2y trades | Raw edge bp | Raw t | Net bp | 2y net ₹ | "
          "Holdout ₹ | Break-even slip (bp/side) | Live 4d net ₹ | Decision |")
    print("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    order = sorted(rows, key=lambda r: -(r[1]["raw"] if r[1] else 99))
    for k, (spec, m, lv) in enumerate(order, 1):
        live_s = f"{lv[1]:,.0f} ({lv[0]})" if lv[0] else "—"
        if m is None:
            print(f"| {k} | `{spec.strategy_id}` | {spec.kind} / {spec.tf} | — | — | — | — | — | "
                  f"— | — | {live_s} | {decide(m)} |")
            continue
        be = f"{m['be']:.2f}" if m["be"] > 0 else "never"
        print(f"| {k} | `{spec.strategy_id}` | {spec.kind} / {spec.tf} | {m['n']:,} | "
              f"{m['raw']:+.2f} | {m['t']:.2f} | {m['netbp']:+.2f} | {m['net']:,.0f} | "
              f"{m['hold']:,.0f} | {be} | {live_s} | {decide(m)} |")
    counts = defaultdict(int)
    for _s, m, _l in rows:
        counts[decide(m).split(" —")[0].split(" (")[0]] += 1
    print("\nDECISION COUNTS:", dict(counts))

    # ---- Patterns, corrected ---------------------------------------------------------
    print("\n\nPATTERNS DESK, corrected (targets AT the target; stops as booked; 3 bp/side)")
    pats = [x async for x in db["pattern_positions"].find({"status": "CLOSED"})]
    agg = {"tf": defaultdict(lambda: [0, 0.0, 0.0]), "fam": defaultdict(lambda: [0, 0.0, 0.0])}
    for x in pats:
        side = 1 if x.get("side") == "BUY" else -1
        ep, xp, q = x.get("entry_price") or 0, x.get("exit_price") or 0, x.get("qty") or 0
        fee = (x.get("fee_breakdown") or {}).get("total") or x.get("fees") or 0
        px = x.get("target") if x.get("exit_reason") == "target" and x.get("target") else xp
        corrected = side * (px - ep) * q - fee - ep * q * 3 / 1e4 * 2
        reported = x.get("realized_pnl") or 0
        for key, val in (("tf", str(x.get("timeframe"))), ("fam", str(x.get("family")))):
            a = agg[key][val]
            a[0] += 1; a[1] += reported; a[2] += corrected
    for key, title in (("tf", "timeframe"), ("fam", "family")):
        print(f"\n| {title} | trades | reported net ₹ | corrected net ₹ |")
        print("|---|---:|---:|---:|")
        tot = [0, 0.0, 0.0]
        for k, a in sorted(agg[key].items(), key=lambda kv: kv[1][2]):
            print(f"| {k} | {a[0]:,} | {a[1]:,.0f} | {a[2]:,.0f} |")
            tot = [tot[0] + a[0], tot[1] + a[1], tot[2] + a[2]]
        print(f"| **total** | {tot[0]:,} | {tot[1]:,.0f} | {tot[2]:,.0f} |")


asyncio.run(main())
