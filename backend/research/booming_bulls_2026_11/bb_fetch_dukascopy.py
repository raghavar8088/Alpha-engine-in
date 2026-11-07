"""Fetch Dukascopy one-minute BID candles for the two markets not on disk: US30 (USA30IDXUSD, for the
inside-candle strategy, kakFchv-ylo) and Apple (AAPLUSUSD, for the opening-range trap, T_VlPXyqj0U).

Source: the public datafeed, one LZMA file per UTC day: .../{SYM}/{YYYY}/{MM-1:02d}/{DD:02d}/BID_candles_min_1.bi5
Each record is 24 bytes '>5if': seconds from 00:00 UTC, open, close, low, high (integers x 0.001), volume.
Closed minutes are padded with flat zero-volume candles; they are dropped when the bars are built.
Weekdays only (the strategies trade the US cash session). The server throttles, so the fetch is
sequential at about 1.2 s between requests with a back-off from 20 s; each day is cached on disk, so the
run resumes where it stopped. Only BID is fetched (halving the requests); the ask is modelled with a
fixed spread in bb_markets.py, and the spread is stressed in the robustness checks.

    python -I bb_fetch_dukascopy.py [first=2024-01-01] [last=2026-10-31] [pace_s=1.2]
"""

from __future__ import annotations

import json
import lzma
import struct
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "dukascopy"
SYMBOLS = ("USA30IDXUSD", "AAPLUSUSD")
PACE_S = float(sys.argv[3]) if len(sys.argv) > 3 else 1.2   # seconds between requests


def url(sym: str, d: date) -> str:
    return f"https://datafeed.dukascopy.com/datafeed/{sym}/{d.year}/{d.month - 1:02d}/{d.day:02d}/BID_candles_min_1.bi5"


def fetch_day(sym: str, d: date) -> str:
    path = OUT / sym / f"{d.isoformat()}.bi5"
    if path.exists():
        return "cached"
    path.parent.mkdir(parents=True, exist_ok=True)
    wait = 20.0
    for attempt in range(6):
        try:
            req = urllib.request.Request(url(sym, d), headers={"User-Agent": "research-fetch/1.0"})
            raw = urllib.request.urlopen(req, timeout=60).read()
            if raw:
                lzma.decompress(raw)          # validate before caching
            path.write_bytes(raw)             # an empty file = no data that day (holiday)
            return "ok" if raw else "empty"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                path.write_bytes(b"")
                return "404"
            err = f"http {e.code}"
        except Exception as e:  # noqa: BLE001  (timeouts, resets)
            err = str(e)[:80]
        print(f"  {sym} {d} attempt {attempt + 1}: {err}; waiting {wait:.0f}s", flush=True)
        time.sleep(wait)
        wait = min(wait * 1.5, 300.0)
    return "failed"


def main() -> None:
    first = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2024, 1, 1)
    last = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2026, 10, 31)
    log = {"first": str(first), "last": str(last), "counts": {}}
    days = [first + timedelta(n) for n in range((last - first).days + 1)]
    days = [d for d in days if d.weekday() < 5]
    # newest first: if the run is cut short, the most recent (post-publication) span is complete
    for sym in SYMBOLS:
        counts: dict[str, int] = {}
        for k, d in enumerate(reversed(days)):
            status = fetch_day(sym, d)
            counts[status] = counts.get(status, 0) + 1
            if status != "cached":
                time.sleep(PACE_S)
            if k % 25 == 0:
                print(f"{sym} {k + 1}/{len(days)} {d} {status} {counts}", flush=True)
        log["counts"][sym] = counts
        (OUT / "fetch_log.json").write_text(json.dumps(log, indent=2))
    print("done", json.dumps(log["counts"]))


def load_minutes(sym: str):
    """All cached days of one symbol as arrays: UTC seconds, o, h, l, c, volume (closed minutes dropped)."""
    import numpy as np
    t, o, h, l, c, v = [], [], [], [], [], []
    for f in sorted((OUT / sym).glob("*.bi5")):
        raw = f.read_bytes()
        if not raw:
            continue
        data = lzma.decompress(raw)
        d0 = date.fromisoformat(f.stem)
        base = (d0 - date(1970, 1, 1)).days * 86400          # 00:00 UTC of that day
        for i in range(0, len(data) - 23, 24):
            s, op, cl, lo, hi, vol = struct.unpack(">5if", data[i:i + 24])
            if vol <= 0:
                continue
            t.append(base + s); o.append(op / 1000); c.append(cl / 1000); l.append(lo / 1000); h.append(hi / 1000); v.append(vol)
    return {k: np.asarray(a) for k, a in zip("tohlcv", (t, o, h, l, c, v))}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    main()
