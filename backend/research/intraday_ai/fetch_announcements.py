"""Corporate announcements history for the Phase 8 test (prereg/P8_event_proxy.json).

NSE's /api/corporate-announcements, one calendar day per request, primed and paced like the
app's nse_client (a session that has visited the site; 0.6 s between requests). Saved as
DATA/intraday/nse_events/ann/YYYY-MM-DD.json.gz — the same layout the box's nse_events
collector writes. Days already saved are skipped, so the run can be resumed.

    D:/intraday_ai_data/venv/Scripts/python.exe fetch_announcements.py 2025-11-04 2026-11-03
"""
from __future__ import annotations

import gzip
import json
import pathlib
import sys
import time
from datetime import date, datetime, timedelta, timezone

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stubpkg import DATA  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
HOME = "https://www.nseindia.com"
REFERER = "/companies-listing/corporate-filings-announcements"
API = HOME + "/api/corporate-announcements?index=equities&from_date={d}&to_date={d}"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
           "Accept-Language": "en-US,en;q=0.9"}
KEEP = ("symbol", "desc", "an_dt", "sort_date", "exchdisstime", "attchmntText", "smIndustry", "seq_id")
OUT = DATA / "intraday" / "nse_events" / "ann"


def when(s) -> str | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(str(s).strip(), fmt).replace(tzinfo=IST).isoformat()
        except ValueError:
            continue
    return None


def prime(c: httpx.Client) -> None:
    for url in (HOME, HOME + REFERER):
        try:
            c.get(url, headers={**HEADERS, "Accept": "text/html"})
        except httpx.HTTPError:
            pass


def fetch_day(c: httpx.Client, d: date) -> list | None:
    url = API.format(d=d.strftime("%d-%m-%Y"))
    for k in range(4):
        time.sleep(0.6 + k * 2.0)
        try:
            r = c.get(url, headers={**HEADERS, "Accept": "application/json, text/plain, */*",
                                    "Referer": HOME + REFERER})
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else (data.get("data") if isinstance(data, dict) else None)
            if r.status_code in (401, 403):
                prime(c)
        except (httpx.HTTPError, ValueError):
            prime(c)
    return None


def main() -> None:
    lo, hi = date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2])
    OUT.mkdir(parents=True, exist_ok=True)
    got = missing = 0
    with httpx.Client(timeout=45, follow_redirects=True, headers=HEADERS) as c:
        prime(c)
        d = hi
        while d >= lo:
            p = OUT / f"{d.isoformat()}.json.gz"
            if not p.exists():
                items = fetch_day(c, d)
                if items is None:
                    missing += 1
                    print("missing", d, flush=True)
                else:
                    rows = []
                    for it in items:
                        row = {k: it.get(k) for k in KEEP if it.get(k) not in (None, "")}
                        if isinstance(row.get("attchmntText"), str):
                            row["attchmntText"] = row["attchmntText"][:1000]
                        row["t"] = when(it.get("exchdisstime") or it.get("an_dt"))
                        rows.append(row)
                    with gzip.open(p, "wt", encoding="utf-8") as f:
                        json.dump({"d": d.isoformat(), "rows": rows, "n": len(rows)}, f, ensure_ascii=False)
                    got += 1
                    if got % 25 == 0:
                        print(f"{got} days saved (at {d})", flush=True)
            d -= timedelta(days=1)
    print(f"done: {got} saved, {missing} missing")


if __name__ == "__main__":
    main()
