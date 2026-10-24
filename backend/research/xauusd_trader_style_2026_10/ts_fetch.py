"""One-minute bars for the cross-market check: XAGUSD, EURUSD, GBPUSD from HistData.com (free),
into ./data/raw/<symbol>/ (not committed). Gold's minutes come from ../xauusd_intraday_2026_10.
Same form flow as ../xauusd_intraday_2026_10/xi_fetch.py.

    python ts_fetch.py
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
SYMBOLS = ["xagusd", "eurusd", "gbpusd"]
FIRST_YEAR = 2009
PAGE = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{sym}/{period}"
GET = "https://www.histdata.com/get.php"


def fetch(s: requests.Session, sym: str, period: str, date: str, dm: str) -> bytes | None:
    for attempt in range(1, 6):
        try:
            page = s.get(PAGE.format(sym=sym, period=period), timeout=60)
            m = re.search(r'id="tk" value="([^"]+)"', page.text)
            if not m:
                return None
            r = s.post(GET, data={"tk": m.group(1), "date": date, "datemonth": dm, "platform": "ASCII", "timeframe": "M1",
                                  "fxpair": sym.upper()}, headers={"Referer": PAGE.format(sym=sym, period=period)}, timeout=180)
            if r.status_code == 200 and r.content[:2] == b"PK":
                return r.content
            why = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            why = type(exc).__name__
        print(f"  {sym} {period}: {why} (try {attempt})", flush=True)
        time.sleep(10 * attempt)
    return None


if __name__ == "__main__":
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (research download)"})
    now = datetime.now(timezone.utc)
    for sym in SYMBOLS:
        out_dir = ROOT / "data" / "raw" / sym
        out_dir.mkdir(parents=True, exist_ok=True)
        jobs = [(str(y), str(y), str(y)) for y in range(FIRST_YEAR, now.year)]
        jobs += [(f"{now.year}/{m}", str(now.year), f"{now.year}{m:02d}") for m in range(1, now.month + 1)]
        got, missing = 0, []
        for period, date, dm in jobs:
            out = out_dir / f"{sym.upper()}_M1_{dm}.zip"
            if out.exists() and out.stat().st_size > 1000 and dm != f"{now.year}{now.month:02d}":
                got += 1
                continue
            body = fetch(s, sym, period, date, dm)
            if body:
                out.write_bytes(body)
                got += 1
            else:
                missing.append(dm)
            time.sleep(1.5)
        print(f"{sym}: {got} files; not available: {missing}", flush=True)
