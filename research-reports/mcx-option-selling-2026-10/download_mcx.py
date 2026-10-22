"""Download MCX bhavcopy history (official, mcxindia.com) for the energy option research.

One request per CONTRACT (symbol + expiry) over its listed life, via the bhavcopy page's own
commodity-wise endpoint. Sequential and paced; every response cached gzipped; re-runs skip
what is already on disk.

    python download_mcx.py <data_dir>
"""
import gzip
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta

from curl_cffi import requests

DATA = sys.argv[1]
TODAY = datetime(2026, 10, 22)
BASE = "https://www.mcxindia.com/market-data/bhavcopy"
HDR = {"Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest",
       "Referer": BASE, "Content-Type": "application/json"}
KEEP = ("Date", "Symbol", "ExpiryDate", "Open", "High", "Low", "Close", "PreviousClose", "Volume", "Value",
        "OpenInterest", "StrikePrice", "OptionType", "InstrumentName")
# options: every listed expiry; futures: only those that underlie an option month (2018+ crude,
# 2022+ natgas, minis since relaunch)
FUT_FROM = {"CRUDEOIL": datetime(2018, 5, 1), "NATURALGAS": datetime(2021, 12, 1),
            "CRUDEOILM": datetime(2024, 5, 1), "NATGASMINI": datetime(2024, 4, 1)}
LIFE_DAYS = {"OPTFUT": 110, "FUTCOM": 120}


def log(msg):
    line = f"{datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    with open(os.path.join(DATA, "download.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def session():
    s = requests.Session(impersonate="chrome")
    r = s.get(BASE, timeout=90)
    if r.status_code != 200:
        raise RuntimeError(f"warm-up {r.status_code}")
    return s


def fetch(s, inst, sym, expiry):
    ed = datetime.strptime(expiry, "%d%b%Y")
    frm = ed - timedelta(days=LIFE_DAYS[inst])
    to = min(ed, TODAY)
    r = s.get(f"{BASE}/GetCommoditywiseBhavCopy", headers=HDR, timeout=240,
              params={"InstrumentName": inst, "Symbol": sym, "Expiry": expiry,
                      "fromDate": frm.strftime("%d/%m/%Y"), "toDate": to.strftime("%d/%m/%Y")})
    if r.status_code != 200 or "json" not in (r.headers.get("content-type") or ""):
        raise RuntimeError(f"HTTP {r.status_code} {r.headers.get('content-type')}")
    d = r.json() or {}
    if "successful" not in str(d.get("Message", "")).lower():
        raise RuntimeError(f"message {d.get('Message')!r}")
    return [{k: x.get(k) for k in KEEP} for x in d.get("Data") or []]


def main():
    os.makedirs(DATA, exist_ok=True)
    ex = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "expiries.json")))
    tasks = []
    for sym in ("CRUDEOILM", "NATGASMINI", "NATURALGAS", "CRUDEOIL"):
        for e in ex[f"OPTFUT:{sym}"]:
            if datetime.strptime(e, "%d%b%Y") - timedelta(days=LIFE_DAYS["OPTFUT"]) <= TODAY:
                tasks.append(("OPTFUT", sym, e))
        for e in ex[f"FUTCOM:{sym}"]:
            ed = datetime.strptime(e, "%d%b%Y")
            if FUT_FROM[sym] <= ed and ed - timedelta(days=LIFE_DAYS["FUTCOM"]) <= TODAY:
                tasks.append(("FUTCOM", sym, e))
    log(f"{len(tasks)} contracts to fetch")
    s, done, fails = session(), 0, 0
    for inst, sym, e in tasks:
        path = os.path.join(DATA, inst, sym, f"{e}.json.gz")
        if os.path.exists(path):
            done += 1
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        for attempt in range(4):
            try:
                rows = fetch(s, inst, sym, e)
                with gzip.open(path + ".tmp", "wt", encoding="utf-8") as fh:
                    json.dump(rows, fh, separators=(",", ":"))
                os.replace(path + ".tmp", path)
                done += 1
                log(f"ok {inst} {sym} {e}: {len(rows)} rows ({done}/{len(tasks)})")
                break
            except Exception as exc:  # noqa: BLE001
                fails += 1
                log(f"retry {attempt + 1} {inst} {sym} {e}: {exc}")
                time.sleep(15 * (attempt + 1))
                try:
                    s = session()
                except Exception as exc2:  # noqa: BLE001
                    log(f"re-warm failed: {exc2}")
        time.sleep(1.5 + random.random())
    log(f"finished: {done}/{len(tasks)} on disk, {fails} retries")


if __name__ == "__main__":
    main()
