"""Phase 0 (PLAN.md): 5-minute bars, Oct 2021 -> 23 Oct 2026, for every stock that was in NIFTY 50
at any time in the period, plus NIFTY, India VIX and the sector indices - from Angel One through the
app's own client and shared candle pacer (a BULK caller, so it yields to any live desk).

READ-ONLY on the database (it reads stock_universe and instruments, never writes). It writes only
gzip CSV files under /out. Resumable: an existing window file is never fetched again.

Run in a throwaway, memory-capped container on the server, off market hours:
  docker run -d --name n50fetch --memory 300m --memory-swap 300m --network alpha-engine_default \
    --env-file /home/ubuntu/alpha-engine/.env -e PYTHONPATH=/app/backend -v /home/ubuntu/n50data:/out \
    --entrypoint python alpha-engine-backend /out/n50_fetch.py [probe]
"""
import asyncio
import csv
import gzip
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

OUT = "/out"
START = date(2021, 10, 1)
END = date(2026, 10, 23)
WINDOW = 99                        # Angel serves FIVE_MINUTE 100 calendar days per request

# NIFTY 50 at the start of the period (Oct 2021), then the additions announced since; today's list
# (stock_universe) is added on top, so every member of the period is fetched. Effective dates are
# recorded separately (universe.json) and verified in the data checks.
OCT2021 = ["ADANIPORTS", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BHARTIARTL",
           "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY", "EICHERMOT", "GRASIM", "HCLTECH",
           "HDFC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
           "INFY", "IOC", "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
           "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHREECEM", "SUNPHARMA", "TATACONSUM", "TATAMOTORS",
           "TATASTEEL", "TCS", "TECHM", "TITAN", "ULTRACEMCO", "UPL", "WIPRO"]
ADDED = ["APOLLOHOSP", "ADANIENT", "LTIM", "SHRIRAMFIN", "TRENT", "BEL", "ETERNAL", "JIOFIN", "INDIGO", "MAXHEALTH"]
ALIASES = {"ETERNAL": ["ETERNAL", "ZOMATO"], "TATAMOTORS": ["TATAMOTORS", "TMPV"], "LTIM": ["LTIM", "LTI"]}


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(os.path.join(OUT, "fetch.log"), "a") as fh:
        fh.write(line + "\n")


async def universe():
    from app.core.db import instruments_collection, stock_universe_collection
    from app.services.intraday_universe import INDEX_TOKENS, SECTOR_INDEX
    current = {d["symbol"]: d async for d in stock_universe_collection.find(
        {"indices": "nifty50"}, {"_id": 0, "symbol": 1, "name": 1, "sector": 1})}
    wanted = list(dict.fromkeys(OCT2021 + ADDED + sorted(current)))
    names = sorted({a for s in wanted for a in ALIASES.get(s, [s])})
    inst = {}
    async for d in instruments_collection.find(
            {"symbol": {"$in": names}, "angel_token": {"$ne": None}, "series": {"$nin": ["BE", "SM"]}},
            {"_id": 0, "symbol": 1, "angel_token": 1, "angel_exchange": 1, "series": 1, "exchange": 1}):
        if (d.get("angel_exchange") or d.get("exchange") or "NSE") == "NSE":
            inst.setdefault(d["symbol"], d)
    secs = {d["symbol"]: d.get("sector") async for d in stock_universe_collection.find(
        {"symbol": {"$in": names}}, {"_id": 0, "symbol": 1, "sector": 1})}
    stocks, missing = {}, []
    for s in wanted:
        hit = next((a for a in ALIASES.get(s, [s]) if a in inst), None)
        if hit is None:
            missing.append(s)
            continue
        stocks[s] = {"angel_symbol": hit, "token": str(inst[hit]["angel_token"]), "sector": secs.get(hit) or secs.get(s),
                     "current_member": s in current or hit in current, "in_oct2021": s in OCT2021}
    indices = {k: {"token": v} for k, v in INDEX_TOKENS.items()}
    u = {"stocks": stocks, "missing_token": missing, "indices": indices, "sector_index": SECTOR_INDEX,
         "current_nifty50": sorted(current), "built_at": datetime.now().isoformat()}
    json.dump(u, open(os.path.join(OUT, "universe.json"), "w"), indent=1)
    log(f"universe: {len(stocks)} stocks with tokens, {len(missing)} without ({missing}), {len(indices)} indices; "
        f"current NIFTY 50 = {len(current)}")
    return u


def windows():
    out, end = [], END
    while end >= START:
        frm = max(START, end - timedelta(days=WINDOW - 1))
        out.append((frm, end))
        end = frm - timedelta(days=1)
    return out                     # newest first


async def fetch_one(name, token, frm, to):
    from app.services.angel_client import AngelAPIError, angel_client
    for attempt in (1, 2, 3, 4):
        try:
            return await angel_client.candles("NSE", token, "5", f"{frm} 09:00", f"{to} 15:35", bulk=True)
        except AngelAPIError as exc:
            if attempt == 4:
                log(f"FAILED {name} {frm}..{to}: {str(exc)[:120]}")
                return None
            await asyncio.sleep(5 * attempt)


async def run(probe=False):
    os.makedirs(OUT, exist_ok=True)
    u = await universe()
    jobs = [(s, v["token"]) for s, v in u["stocks"].items()] + [(k, v["token"]) for k, v in u["indices"].items()]
    if probe:
        jobs = [("RELIANCE", u["stocks"]["RELIANCE"]["token"])]
    wins = windows()
    if probe:
        wins = [wins[0], wins[-1]]
    t0, reqs, rows_total = time.time(), 0, 0
    for name, token in jobs:
        d = os.path.join(OUT, "5m", name)
        os.makedirs(d, exist_ok=True)
        empties = 0
        for frm, to in wins:
            f = os.path.join(d, f"{frm}_{to}.csv.gz")
            e = os.path.join(d, f"{frm}_{to}.empty")
            if os.path.exists(f) or os.path.exists(e):
                continue
            rows = await fetch_one(name, token, frm, to)
            reqs += 1
            if rows is None:
                continue
            if not rows:
                open(e, "w").close()
                empties += 1
                if empties >= 2 and not probe:
                    log(f"{name}: nothing older than {frm} (two empty windows) - stopping this symbol")
                    break
                continue
            empties = 0
            with gzip.open(f + ".tmp", "wt", newline="") as fh:
                w = csv.writer(fh)
                for r in rows:
                    w.writerow(r[:6])
            os.replace(f + ".tmp", f)
            rows_total += len(rows)
        log(f"{name}: done ({reqs} requests so far, {rows_total:,} rows, {time.time() - t0:.0f}s)")
    log(f"FINISHED: {reqs} requests, {rows_total:,} rows, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(run(probe=len(sys.argv) > 1 and sys.argv[1] == "probe"))
