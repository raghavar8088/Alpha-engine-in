"""Download NSE's daily price files and index closes for the forecast validation.

Usage:  python fetch_history.py <out_dir> [start YYYY-MM-DD] [end YYYY-MM-DD]

For every weekday in the range, fetches:
  sec_bhavdata_full_DDMMYYYY.csv  -> <out>/prices/YYYY-MM-DD.json.gz
      {symbol: [close, prev_close, traded_qty, turnover_lacs, trades, delivery_pct]}
      EQ, BE and BZ series only (mainboard equities).
  ind_close_all_DDMMYYYY.csv      -> <out>/indices/YYYY-MM-DD.json.gz
      {index name: close}
A 404 is a holiday and is remembered in <out>/missing.json, so a re-run skips it. The
script resumes: files already on disk are not fetched again. It asks for one file at a
time with a pause in between, and keeps Windows awake while it runs.
"""

import csv
import ctypes
import gzip
import io
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

import httpx

OUT = sys.argv[1]
START = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2021, 10, 1)
END = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date.today()
HOME = "https://www.nseindia.com"
BHAV = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
INDEX = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d}.csv"
GAP = 0.45
KEEP = {"EQ", "BE", "BZ"}

if os.name == "nt":                       # a sleeping PC freezes the job silently
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)

H = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
     "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": f"{HOME}/all-reports"}
client = httpx.Client(timeout=45, follow_redirects=True, headers=H)
try:
    client.get(HOME, headers={**H, "Accept": "text/html"})
except httpx.HTTPError:
    pass

os.makedirs(os.path.join(OUT, "prices"), exist_ok=True)
os.makedirs(os.path.join(OUT, "indices"), exist_ok=True)
miss_path = os.path.join(OUT, "missing.json")
missing = set(json.load(open(miss_path))) if os.path.exists(miss_path) else set()


def num(v):
    try:
        s = str(v).strip().replace(",", "")
        return None if s in ("", "-", "nan") else float(s)
    except ValueError:
        return None


def get(url):
    for k in range(4):
        try:
            r = client.get(url)
            if r.status_code in (200, 404):
                return r
        except httpx.HTTPError:
            pass
        time.sleep(2 + 3 * k)
    return None


def save(path, obj):
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, path)


d, n_ok, n_hol, t0 = START, 0, 0, time.time()
while d <= END:
    if d.weekday() >= 5 or d.isoformat() in missing:
        d += timedelta(days=1)
        continue
    pp = os.path.join(OUT, "prices", f"{d.isoformat()}.json.gz")
    ip = os.path.join(OUT, "indices", f"{d.isoformat()}.json.gz")
    if not os.path.exists(pp):
        r = get(BHAV.format(d=d.strftime("%d%m%Y")))
        time.sleep(GAP)
        if r is None:
            print("gave up", d, flush=True)
        elif r.status_code == 404:
            missing.add(d.isoformat())
            n_hol += 1
            json.dump(sorted(missing), open(miss_path, "w"))
        else:
            rec = {}
            day_seen = None
            try:
                if r.content[:2] == b"PK":
                    # 8 Aug 2022 is served as an Excel workbook, not a CSV. One missing day
                    # in five years is a smaller error than guessing at its contents.
                    raise csv.Error("an xlsx workbook, not a csv")
                # newline="" lets csv handle the stray \r NSE leaves in some files.
                for raw in csv.DictReader(io.StringIO(r.text, newline="")):
                    x = {(k or "").strip(): (v.strip() if isinstance(v, str) else "")
                         for k, v in raw.items() if isinstance(k, str)}
                    if day_seen is None and x.get("DATE1"):
                        try:
                            day_seen = datetime.strptime(x["DATE1"], "%d-%b-%Y").date()
                        except ValueError:
                            day_seen = None
                    if x.get("SERIES") in KEEP and x.get("SYMBOL"):
                        rec[x["SYMBOL"].upper()] = [num(x.get("CLOSE_PRICE")), num(x.get("PREV_CLOSE")),
                                                    num(x.get("TTL_TRD_QNTY")), num(x.get("TURNOVER_LACS")),
                                                    num(x.get("NO_OF_TRADES")), num(x.get("DELIV_PER"))]
            except csv.Error as exc:
                print("unreadable", d, exc, flush=True)
                rec = {}
            if day_seen is not None and day_seen != d:
                # On a holiday NSE serves the previous session's file under the holiday's
                # date (26 Jan 2022 is 25 Jan's, close for close). It is not a session.
                rec = {}
            if len(rec) > 500:
                save(pp, rec)
                n_ok += 1
            elif not rec:
                missing.add(d.isoformat())          # a non-CSV answer: not a trading file
                json.dump(sorted(missing), open(miss_path, "w"))
    if os.path.exists(pp) and not os.path.exists(ip):
        r = get(INDEX.format(d=d.strftime("%d%m%Y")))
        time.sleep(GAP)
        if r is not None and r.status_code == 200:
            idx = {}
            try:
                for raw in csv.DictReader(io.StringIO(r.text, newline="")):
                    x = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                    if x.get("Index Name"):
                        idx[x["Index Name"]] = num(x.get("Closing Index Value"))
            except csv.Error as exc:
                print("unreadable index file", d, exc, flush=True)
            if idx:
                save(ip, idx)
    if n_ok and n_ok % 50 == 0:
        print(f"{d} files {n_ok} holidays {n_hol} elapsed {time.time() - t0:.0f}s", flush=True)
    d += timedelta(days=1)

print(f"done {START}..{END}: {n_ok} new price files, {n_hol} holidays, {time.time() - t0:.0f}s", flush=True)
