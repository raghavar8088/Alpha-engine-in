"""Gold Desk audit — READ-ONLY. What has the desk actually done, and on what data?

Run inside the backend image (it reads the production cluster; it writes nothing to it):

    docker cp gd_audit.py alpha-engine-backend-1:/tmp/
    docker exec -e PYTHONPATH=/app/backend alpha-engine-backend-1 python /tmp/gd_audit.py

Prints the desk's switches, record, bar coverage and the MCX spreads logged for gold, and
exports every position, trade and equity sample to /tmp/gd_export.json for offline analysis.
"""

import asyncio
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

from bson import ObjectId

from app.core.db import (
    commodity_bars_collection as CB,
    db,
    desk_switches_collection as SW,
    gold_bars_collection as B,
    gold_equity_collection as E,
    gold_positions_collection as P,
    gold_state_collection as S,
    gold_trades_collection as T,
)


def ser(o):
    if isinstance(o, datetime):
        return (o if o.tzinfo else o.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(o, ObjectId):
        return str(o)
    if isinstance(o, dict):
        return {k: ser(v) for k, v in o.items()}
    if isinstance(o, list):
        return [ser(v) for v in o]
    return o


def q(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(len(xs) * p))]


async def main():
    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat()}

    print("=== SWITCHES ===")
    sw = await SW.find_one({"_id": "gold_desk"})
    print("main control gold_desk:", ser(sw))
    states = [ser(d) async for d in S.find({})]
    for d in states:
        if d.get("_id") == "mcx:entry_bars" or d.get("_id") == "delta:entry_bars":
            print(d["_id"], "keys:", len(d.get("last", {})))
        else:
            dd = dict(d)
            dd.pop("detail", None)
            print(json.dumps(dd, default=str)[:900])
    out["main_control"] = ser(sw)
    out["state"] = states

    print("\n=== POSITIONS ===")
    pos = [ser(p) async for p in P.find({})]
    out["positions"] = pos
    by = Counter((p.get("venue"), p.get("status")) for p in pos)
    print("count by (venue,status):", dict(by))
    for v in ("mcx", "delta"):
        vp = [p for p in pos if p.get("venue") == v]
        if not vp:
            print(f"[{v}] no positions")
            continue
        closed = [p for p in vp if p.get("status") != "OPEN"]
        opened = sorted(p.get("opened_at") or "" for p in vp)
        print(f"[{v}] {len(vp)} positions, {len(closed)} closed; first open {opened[0]}, last open {opened[-1]}")
        net = sum(p.get("realized_pnl") or 0 for p in closed)
        gross = sum(p.get("gross_pnl") or 0 for p in closed)
        costs = sum(p.get("costs") or 0 for p in closed)
        print(f"[{v}] realised net {net:,.2f}  gross {gross:,.2f}  costs {costs:,.2f}")
        print(f"[{v}] exit reasons:", dict(Counter(p.get("exit_reason") for p in closed)))
        print(f"[{v}] by timeframe:", dict(Counter(p.get("timeframe") for p in vp)))
        print(f"[{v}] by symbol:", dict(Counter(p.get("symbol") for p in vp)))
        print(f"[{v}] by side:", dict(Counter(p.get("side") for p in vp)))
        print(f"[{v}] by family:", dict(Counter(p.get("family") for p in vp)))
        expiries = Counter((p.get("instrument") or {}).get("expiry") for p in vp)
        print(f"[{v}] contract expiries held:", dict(expiries))
        opn = [p for p in vp if p.get("status") == "OPEN"]
        for p in opn[:20]:
            print(f"   OPEN {p.get('symbol')} {p.get('side')} {p.get('strategy_template')}/{p.get('timeframe')} "
                  f"entry {p.get('entry_price')} ltp {p.get('ltp')} unreal {p.get('unrealized_pnl')} "
                  f"opened {p.get('opened_at')} exp {(p.get('instrument') or {}).get('expiry')}")

    print("\n=== TRADES ===")
    tr = [ser(t) async for t in T.find({})]
    out["trades"] = tr
    print("trades:", Counter(t.get("venue") for t in tr))

    print("\n=== EQUITY SAMPLES ===")
    for v in ("mcx", "delta"):
        n = await E.count_documents({"venue": v})
        first = await E.find_one({"venue": v}, sort=[("ts", 1)])
        last = await E.find_one({"venue": v}, sort=[("ts", -1)])
        print(f"[{v}] {n} samples; first {ser(first) if first else None}")
        print(f"[{v}] last {ser(last) if last else None}")
    eq = [ser(e) async for e in E.find({}, {"_id": 0}).sort("ts", 1)]
    out["equity_n"] = len(eq)
    # thin the equity curve for export
    out["equity"] = eq[:: max(1, len(eq) // 4000)]

    print("\n=== DELTA BAR STORE (gold_delta_bars) ===")
    async for r in B.aggregate([{"$group": {"_id": {"s": "$symbol", "t": "$timeframe"}, "n": {"$sum": 1},
                                            "first": {"$min": "$ts"}, "last": {"$max": "$ts"}}},
                                {"$sort": {"_id.s": 1, "_id.t": 1}}]):
        print(f"  {r['_id']['s']:8} {r['_id']['t']:4} n={r['n']:5}  {ser(r['first'])} .. {ser(r['last'])}")

    print("\n=== MCX BAR STORE (commodity_bars) for GOLD / GOLDM ===")
    async for r in CB.aggregate([{"$match": {"symbol": {"$in": ["GOLD", "GOLDM"]}}},
                                 {"$group": {"_id": {"s": "$symbol", "t": "$timeframe", "e": "$expiry"},
                                             "n": {"$sum": 1}, "first": {"$min": "$ts"}, "last": {"$max": "$ts"}}},
                                 {"$sort": {"_id.s": 1, "_id.t": 1, "_id.e": 1}}]):
        print(f"  {r['_id']['s']:6} {r['_id']['t']:4} exp={str(r['_id']['e']):10} n={r['n']:5}  "
              f"{ser(r['first'])} .. {ser(r['last'])}")

    print("\n=== MCX QUOTE LOG (logged spreads) for gold ===")
    ql = db["mcx_quote_log"]
    rows = [r async for r in ql.find({"underlying": {"$in": ["GOLD", "GOLDM", "GOLDPETAL", "GOLDTEN", "GOLDGUINEA"]}},
                                     {"_id": 0})]
    out["quote_log"] = [ser(r) for r in rows]
    g = defaultdict(list)
    for r in rows:
        if r.get("spread_bp") is not None:
            g[(r.get("underlying"), r.get("expiry"))].append(r)
    for k, rs in sorted(g.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
        sp = [float(r["spread_bp"]) for r in rs]
        bq = [r.get("bid_qty") or 0 for r in rs]
        aq = [r.get("ask_qty") or 0 for r in rs]
        ts = sorted(r["ts"] for r in rs)
        print(f"  {k[0]:9} {k[1]}  n={len(rs):5}  spread bp med {statistics.median(sp):.3f} p90 {q(sp, .9):.3f} "
              f"max {max(sp):.3f} | top qty bid med {statistics.median(bq)} ask med {statistics.median(aq)} "
              f"| {ser(ts[0])} .. {ser(ts[-1])}")

    print("\n=== MCX CURVE (gold rows) ===")
    cv = db["mcx_curve"]
    ncv = await cv.count_documents({"underlying": {"$in": ["GOLD", "GOLDM"]}})
    sample = await cv.find_one({"underlying": "GOLDM"}, {"_id": 0}, sort=[("date", -1)])
    print("rows", ncv, "latest GOLDM:", json.dumps(ser(sample), default=str)[:1200] if sample else None)

    with open("/tmp/gd_export.json", "w") as f:
        json.dump(out, f, default=str)
    print("\nexported /tmp/gd_export.json")


asyncio.run(main())
