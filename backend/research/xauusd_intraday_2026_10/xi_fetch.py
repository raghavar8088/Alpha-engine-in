"""Download XAUUSD one-minute bars from HistData.com (free) into ./data/raw/histdata/ (not committed).

HistData serves one zip a year for finished years and one a month for the current year, through a
form: GET the download page (it carries a one-time token `tk`), then POST it to get.php with the
page as referer. Each zip holds DAT_ASCII_XAUUSD_M1_<period>.csv: "YYYYMMDD HHMMSS;open;high;low;close;volume",
timestamps in New York STANDARD time all year (UTC-5, no daylight saving), plus a gap report.

    python xi_fetch.py
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw" / "histdata"
FIRST_YEAR = 2009
PAGE = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/xauusd/{period}"
GET = "https://www.histdata.com/get.php"


def fetch(period: str, date: str, datemonth: str, s: requests.Session) -> bytes | None:
    for attempt in range(1, 6):
        try:
            page = s.get(PAGE.format(period=period), timeout=60)
            m = re.search(r'id="tk" value="([^"]+)"', page.text)
            if not m:
                return None                      # no such period
            r = s.post(GET, data={"tk": m.group(1), "date": date, "datemonth": datemonth, "platform": "ASCII",
                                  "timeframe": "M1", "fxpair": "XAUUSD"},
                       headers={"Referer": PAGE.format(period=period)}, timeout=180)
            if r.status_code == 200 and r.content[:2] == b"PK":
                return r.content
            reason = f"HTTP {r.status_code}, {len(r.content)} bytes"
        except requests.RequestException as exc:
            reason = type(exc).__name__
        print(f"  {period}: {reason} (try {attempt}); waiting", flush=True)
        time.sleep(10 * attempt)
    return None


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (research download)"})
    now = datetime.now(timezone.utc)
    jobs = [(str(y), str(y), str(y)) for y in range(FIRST_YEAR, now.year)]
    jobs += [(f"{now.year}/{mth}", str(now.year), f"{now.year}{mth:02d}") for mth in range(1, now.month + 1)]
    got, missing = 0, []
    for period, date, dm in jobs:
        out = RAW / f"XAUUSD_M1_{dm}.zip"
        current = dm == f"{now.year}{now.month:02d}"
        if out.exists() and out.stat().st_size > 1000 and not current:
            got += 1
            continue
        body = fetch(period, date, dm, s)
        if body:
            out.write_bytes(body)
            got += 1
            print(f"  {dm}: {len(body):,} bytes", flush=True)
        else:
            missing.append(dm)
        time.sleep(2)
    print(f"done: {got} files; not available: {missing}")
