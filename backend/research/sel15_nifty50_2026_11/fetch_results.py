"""Results calendar for 15 Sep - 5 Nov 2026 from NSE's public endpoints — the same two the live
results_calendar.refresh() reads: corporates-financial-results (filed, with dissemination time)
and corporate-board-meetings (scheduled 'Financial Results' meetings). Saved to scratchpad/d/exports."""
import json
import os
import pathlib
import sys
import time
from datetime import date, timedelta

import httpx
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "intraday_ai"))
from fetch_announcements import HEADERS, HOME, prime  # noqa: E402

OUT = Path(os.environ.get("INTRADAY_AI_DATA", r"D:/intraday_ai_data")) / "exports"
EPS = {
    "filed": ("/api/corporates-financial-results?index=equities&period=Quarterly&from_date={a}&to_date={b}",
              "/companies-listing/corporate-filings-financial-results"),
    "scheduled": ("/api/corporate-board-meetings?index=equities&from_date={a}&to_date={b}",
                  "/companies-listing/corporate-filings-board-meetings"),
}


def get(c, path, referer):
    for k in range(4):
        time.sleep(0.8 + k * 2.0)
        try:
            r = c.get(HOME + path, headers={**HEADERS, "Accept": "application/json, text/plain, */*",
                                            "Referer": HOME + referer})
            if r.status_code == 200:
                d = r.json()
                return d if isinstance(d, list) else (d or {}).get("data", [])
            print("status", r.status_code, path, flush=True)
            prime(c)
        except (httpx.HTTPError, ValueError) as e:
            print("error", e, flush=True)
            prime(c)
    return None


out = {"filed": [], "scheduled": []}
with httpx.Client(timeout=45, follow_redirects=True, headers=HEADERS) as c:
    prime(c)
    d = date(2026, 9, 15)
    while d <= date(2026, 11, 5):
        e = min(d + timedelta(days=6), date(2026, 11, 5))
        for kind, (path, ref) in EPS.items():
            rows = get(c, path.format(a=d.strftime("%d-%m-%Y"), b=e.strftime("%d-%m-%Y")), ref)
            print(kind, d, e, None if rows is None else len(rows), flush=True)
            if rows:
                out[kind].extend(rows)
        d = e + timedelta(days=1)
json.dump(out, open(OUT / "nse_results_raw.json", "w", encoding="utf-8"))
print("saved", {k: len(v) for k, v in out.items()})
