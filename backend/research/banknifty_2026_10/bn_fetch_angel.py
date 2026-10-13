# Runs in a throwaway backend container: docker run --rm --network alpha-engine_default --env-file .env -v /tmp/bn_out:/out ... python bn_fetch_angel.py
"""READ-ONLY: Angel candles 2015-01 -> 2026-10-09 for NIFTY BANK, INDIA VIX, NIFTY (5m and daily).
Written to /out/<SYM>_<res>.json.gz as [[epoch, o, h, l, c], ...]."""
import asyncio, gzip, json
from datetime import date, datetime, timedelta, timezone
from app.services.angel_client import angel_client
from app.services.intraday_store import parse_stamp

TOK = {"NIFTYBANK": "99926009", "INDIAVIX": "99926017", "NIFTY": "99926000"}
START, END = date(2015, 1, 1), date(2026, 10, 9)


async def pull(sym, res, span):
    rows, d = {}, START
    while d <= END:
        e = min(END, d + timedelta(days=span - 1))
        for attempt in range(6):
            try:
                cs = await angel_client.candles("NSE", TOK[sym], res, f"{d} 09:00", f"{e} 15:35", bulk=True)
                break
            except Exception as ex:
                print(sym, res, d, "retry", attempt, str(ex)[:80], flush=True)
                await asyncio.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"{sym} {res} {d} failed")
        for c in cs or []:
            t = parse_stamp(c[0])
            if t is not None:
                rows[t] = [t, float(c[1]), float(c[2]), float(c[3]), float(c[4])]
        d = e + timedelta(days=1)
    out = [rows[k] for k in sorted(rows)]
    with gzip.open(f"/out/{sym}_{res}.json.gz", "wt") as g:
        json.dump(out, g, separators=(",", ":"))
    print(f"{sym} {res}: {len(out)} bars {datetime.fromtimestamp(out[0][0]).date()}..{datetime.fromtimestamp(out[-1][0]).date()}", flush=True)


async def main():
    for sym in ("NIFTYBANK", "INDIAVIX", "NIFTY"):
        await pull(sym, "D", 1900)
        await pull(sym, "5", 95)
    print("ALL DONE", flush=True)

asyncio.run(main())
