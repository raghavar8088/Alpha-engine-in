"""Download the free data this study runs on, politely, into ./data/raw/ (not committed).

  Dukascopy (Swiss bank, public datafeed, UTC timestamps, bid AND ask):
    XAUUSD hourly candles, one file a month    datafeed/XAUUSD/{YYYY}/{MM-1:02d}/{BID|ASK}_candles_hour_1.bi5  (from 2004)
    the CURRENT month has no hourly file yet,  datafeed/XAUUSD/{YYYY}/{MM-1:02d}/{DD:02d}/{BID|ASK}_candles_min_1.bi5
      so its days come from minute candles
    daily candles, one file a year (cross-check only)   datafeed/XAUUSD/{YYYY}/BID_candles_day_1.bi5
  Yahoo Finance chart API (independent cross-checks and the financing rate):
    GC=F  COMEX gold futures, continuous front month: daily since 2008, hourly for the last 730 days
    ^IRX  13-week US Treasury bill yield, % (FRED refuses connections from this machine)

Dukascopy throttles bursts (HTTP 503 / connection resets), so requests are sequential, paced,
and back off for a minute when refused. Files already on disk are not fetched again, except
the current month's minute files, which are re-read until the month closes.

    python xa_fetch.py            # everything
    python xa_fetch.py yahoo      # only the Yahoo series
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
DUKA = "https://datafeed.dukascopy.com/datafeed"
SYMBOL = "XAUUSD"
FIRST_YEAR = 2004            # six years of warm-up before the 2010 start (48-month rules need four)
ASK_FROM_YEAR = 2008         # warm-up years before this are fetched on the BID side only (indicators, never trades)
UA = {"User-Agent": "Mozilla/5.0 (research download; one request at a time)"}
PACE_S = 1.2

session = requests.Session()
session.headers.update(UA)


def _get(url: str, tries: int = 10) -> bytes | None:
    """The body, b'' for a 404 (file does not exist), None if it could not be fetched."""
    wait = 20.0
    for attempt in range(1, tries + 1):
        try:
            r = session.get(url, timeout=40)
            if r.status_code == 200:
                time.sleep(PACE_S)
                return r.content
            if r.status_code == 404:
                time.sleep(PACE_S)
                return b""
            reason = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            reason = type(exc).__name__
        print(f"    {reason} on {url.rsplit('/datafeed/', 1)[-1]} (try {attempt}); waiting {wait:.0f}s", flush=True)
        time.sleep(wait)
        wait = min(wait * 1.6, 180.0)
    return None


def _save(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(body)
    tmp.replace(path)


def fetch_dukascopy(today: date) -> dict:
    stats = {"hour_files": 0, "hour_missing": [], "minute_files": 0, "day_files": 0, "failed": []}
    months = []
    y, m = FIRST_YEAR, 1
    while (y, m) < (today.year, today.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for side in ("BID", "ASK"):
        for (y, m) in months:
            if side == "ASK" and y < ASK_FROM_YEAR:
                continue
            out = RAW / "dukascopy" / "hour" / side / f"{y}-{m:02d}.bi5"
            if out.exists() and out.stat().st_size > 0:
                stats["hour_files"] += 1
                continue
            body = _get(f"{DUKA}/{SYMBOL}/{y}/{m - 1:02d}/{side}_candles_hour_1.bi5")
            if body is None:
                stats["failed"].append(str(out.relative_to(RAW)))
            elif body == b"":
                stats["hour_missing"].append(f"{side} {y}-{m:02d}")
            else:
                _save(out, body)
                stats["hour_files"] += 1
        print(f"  {side} hourly: {stats['hour_files']} files so far", flush=True)
        # the current month, day by day from minute candles (weekends have no file worth reading)
        d = date(today.year, today.month, 1)
        while d < today:
            out = RAW / "dukascopy" / "minute" / side / f"{d.isoformat()}.bi5"
            done = out.exists() and out.stat().st_size > 0 and d < today - timedelta(days=1)
            if done:
                stats["minute_files"] += 1
            elif d.weekday() != 5:   # Saturday never trades; Sunday evening does
                body = _get(f"{DUKA}/{SYMBOL}/{d.year}/{d.month - 1:02d}/{d.day:02d}/{side}_candles_min_1.bi5")
                if body is None:
                    stats["failed"].append(str(out.relative_to(RAW)))
                elif body:
                    _save(out, body)
                    stats["minute_files"] += 1
            d += timedelta(days=1)
    for yr in range(FIRST_YEAR, today.year):
        out = RAW / "dukascopy" / "day" / f"BID-{yr}.bi5"
        if out.exists() and out.stat().st_size > 0:
            stats["day_files"] += 1
            continue
        body = _get(f"{DUKA}/{SYMBOL}/{yr}/BID_candles_day_1.bi5")
        if body:
            _save(out, body)
            stats["day_files"] += 1
        elif body is None:
            stats["failed"].append(str(out.relative_to(RAW)))
    return stats


def fetch_yahoo() -> dict:
    p1 = int(datetime(FIRST_YEAR, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(time.time())
    jobs = {
        "GC=F_1d.json": f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?period1={p1}&period2={p2}&interval=1d",
        "GC=F_1h.json": "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=730d&interval=1h",
        "IRX_1d.json": f"https://query1.finance.yahoo.com/v8/finance/chart/%5EIRX?period1={p1}&period2={p2}&interval=1d",
    }
    out = {}
    for name, url in jobs.items():
        body = _get(url, tries=4)
        if body:
            json.loads(body)          # must parse
            _save(RAW / "yahoo" / name, body)
            out[name] = len(body)
        else:
            out[name] = "FAILED"
    return out


if __name__ == "__main__":
    today = datetime.now(timezone.utc).date()
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    meta = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if what in ("all", "yahoo"):
        meta["yahoo"] = fetch_yahoo()
        print("yahoo:", meta["yahoo"], flush=True)
    if what in ("all", "dukascopy"):
        meta["dukascopy"] = fetch_dukascopy(today)
        d = meta["dukascopy"]
        print(f"dukascopy: {d['hour_files']} hourly, {d['minute_files']} minute, {d['day_files']} daily files; "
              f"missing {d['hour_missing']}; failed {d['failed']}", flush=True)
    (RAW).mkdir(parents=True, exist_ok=True)
    (RAW / f"fetch_{what}.json").write_text(json.dumps(meta, indent=1))
