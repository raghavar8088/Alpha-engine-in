# Runs in a throwaway backend container (as bn_fetch_angel.py). Output: /out/bn_optcandles.json.gz
"""READ-ONLY: Angel 5m candles for live BANKNIFTY monthly options (Oct + Nov 2026), ATM band."""
import asyncio, gzip, json
from app.core.db import instruments_collection
from app.services.angel_client import angel_client
from app.services.intraday_store import parse_stamp


async def main():
    out = {}
    q = {"asset_class": "INDEX_OPTION", "underlying_symbol": "BANKNIFTY", "expiry": {"$in": ["2026-10-27", "2026-11-23"]},
         "strike": {"$gte": 53500.0, "$lte": 57000.0}, "angel_token": {"$ne": None}}
    docs = [d async for d in instruments_collection.find(q, {"expiry": 1, "strike": 1, "option_type": 1, "angel_token": 1})]
    print(len(docs), "contracts", flush=True)
    for d in sorted(docs, key=lambda d: (d["expiry"], d["strike"], d["option_type"])):
        if d["strike"] % 100:
            continue
        try:
            rows = await angel_client.candles("NFO", str(d["angel_token"]), "5", "2026-08-01 09:15", "2026-10-09 15:30", bulk=True)
        except Exception as ex:
            print("ERR", d["expiry"], d["strike"], d["option_type"], str(ex)[:80], flush=True)
            continue
        key = f"{d['expiry']}|{int(d['strike'])}|{d['option_type']}"
        out[key] = [[parse_stamp(r[0]), r[1], r[2], r[3], r[4], r[5]] for r in rows]
        print(key, len(rows), rows[0][0] if rows else "-", flush=True)
    with gzip.open("/out/bn_optcandles.json.gz", "wt") as g:
        json.dump(out, g)
    print("DONE", flush=True)

asyncio.run(main())
