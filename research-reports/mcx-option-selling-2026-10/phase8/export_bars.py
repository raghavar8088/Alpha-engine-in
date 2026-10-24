"""READ-ONLY export of the app's recorded MCX crude / natural-gas intraday bars (commodity_bars).
Runs in a throwaway, memory-capped container; never writes to the database.
Output: /out/coverage.csv and /out/bars.csv.gz"""
import csv
import gzip
import os

from pymongo import MongoClient

SYMS = ["CRUDEOIL", "NATURALGAS", "CRUDEOILM", "NATGASMINI"]
TFS = ["1m", "5m", "15m", "1h"]

client = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=30000)
col = client[os.environ.get("MONGO_DB_NAME", "tradingai")]["commodity_bars"]
match = {"symbol": {"$in": SYMS}, "timeframe": {"$in": TFS}}

cov = col.aggregate([
    {"$match": match},
    {"$group": {"_id": {"s": "$symbol", "t": "$timeframe", "e": "$expiry"},
                "n": {"$sum": 1}, "first": {"$min": "$ts"}, "last": {"$max": "$ts"}}},
])
with open("/out/coverage.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["symbol", "timeframe", "expiry", "n", "first", "last"])
    for r in cov:
        w.writerow([r["_id"]["s"], r["_id"]["t"], r["_id"].get("e"), r["n"], r["first"], r["last"]])

n = 0
proj = {"_id": 0, "symbol": 1, "timeframe": 1, "expiry": 1, "ts": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
with gzip.open("/out/bars.csv.gz", "wt", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["symbol", "timeframe", "expiry", "ts", "open", "high", "low", "close", "volume"])
    for d in col.find(match, proj, batch_size=2000):
        w.writerow([d.get("symbol"), d.get("timeframe"), d.get("expiry"), d.get("ts"), d.get("open"), d.get("high"),
                    d.get("low"), d.get("close"), d.get("volume")])
        n += 1
print("exported", n, "bars")
