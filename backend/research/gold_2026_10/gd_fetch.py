"""Fetch the gold histories the Gold Desk research runs on. Public endpoints only, no keys.

    python backend/research/gold_2026_10/gd_fetch.py [delta] [binance] [yahoo]

Writes into ./data (not committed):

  delta_<SYM>_1m.csv.gz       Delta India XAUTUSD / PAXGUSD perpetual 1m candles since launch
                              (XAUT 2026-04-17, PAXG 2026-02-19) — the desk's own venue.
  delta_<SYM>_funding.csv.gz  the venue's FUNDING:<SYM> series (hourly, % per interval).
  binance_PAXGUSDT_1m.csv.gz  Binance spot PAXG/USDT 1m since listing — a 24/7 gold token,
                              the longest public 1-minute gold record there is.
  yahoo_GC_1h.csv.gz          COMEX gold futures (GC=F) hourly, ~730 days (Yahoo's limit).
  yahoo_GC_1d.csv.gz          GC=F daily since 2000.   yahoo_INR_1d.csv.gz  USD/INR daily.

All timestamps are UTC epoch seconds of the bar OPEN.
"""

import csv
import gzip
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
DATA.mkdir(exist_ok=True)
DELTA = "https://api.india.delta.exchange"
UA = {"User-Agent": "gold-desk-research/1.0", "Accept": "application/json"}


def get_json(url: str, tries: int = 4) -> dict:
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read())
        except Exception as exc:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  retry {i + 1} {url[:90]}: {exc}")
            time.sleep(2 * (i + 1))
    return {}


def write_rows(path: Path, header: list[str], rows: list[tuple]) -> None:
    with gzip.open(path, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  wrote {path.name}: {len(rows):,} rows")


# ── Delta ────────────────────────────────────────────────────────────────────────


def delta_series(symbol: str, resolution: str, start: int, step_s: int) -> list[tuple]:
    """Walk forward from `start` in windows of 4000 candles (the venue's page size)."""
    out: dict[int, tuple] = {}
    end_all = int(time.time())
    t = start
    while t < end_all:
        t2 = min(t + step_s * 3990, end_all)
        body = get_json(f"{DELTA}/v2/history/candles?resolution={resolution}&symbol={symbol}&start={t}&end={t2}")
        for c in body.get("result") or []:
            out[int(c["time"])] = (int(c["time"]), c["open"], c["high"], c["low"], c["close"], c.get("volume") or 0)
        t = t2
        time.sleep(0.4)
    return [out[k] for k in sorted(out)]


def fetch_delta() -> None:
    for sym in ("XAUTUSD", "PAXGUSD"):
        prod = get_json(f"{DELTA}/v2/products/{sym}")["result"]
        launch = int(datetime.fromisoformat(prod["launch_time"].replace("Z", "+00:00")).timestamp())
        print(f"{sym}: launched {prod['launch_time']}, taker {prod['taker_commission_rate']}, "
              f"maker {prod['maker_commission_rate']}, contract {prod['contract_value']}")
        rows = delta_series(sym, "1m", launch - 3600, 60)
        write_rows(DATA / f"delta_{sym}_1m.csv.gz", ["ts", "open", "high", "low", "close", "volume"], rows)
        fund = delta_series(f"FUNDING:{sym}", "1h", launch - 3600, 3600)
        write_rows(DATA / f"delta_{sym}_funding.csv.gz", ["ts", "open", "high", "low", "close", "volume"], fund)
        (DATA / f"delta_{sym}_product.json").write_text(json.dumps(prod, indent=1))


# ── Binance ──────────────────────────────────────────────────────────────────────


def fetch_binance() -> None:
    rows: list[tuple] = []
    today = date.today()
    y, m = 2020, 8
    misses = 0
    while (y, m) < (today.year, today.month):
        url = (f"https://data.binance.vision/data/spot/monthly/klines/PAXGUSDT/1m/"
               f"PAXGUSDT-1m-{y}-{m:02d}.zip")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                blob = r.read()
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                name = z.namelist()[0]
                n0 = len(rows)
                for line in z.read(name).decode().splitlines():
                    p = line.split(",")
                    if not p or not p[0].isdigit():
                        continue
                    ts = int(p[0])
                    # Binance switched spot kline timestamps to MICROseconds from 2025-01-01.
                    ts = ts // 1_000_000 if ts > 10**14 else ts // 1000
                    rows.append((ts, p[1], p[2], p[3], p[4], p[5]))
                print(f"  {y}-{m:02d}: {len(rows) - n0:,}")
        except urllib.error.HTTPError as exc:
            misses += 1
            print(f"  {y}-{m:02d}: HTTP {exc.code}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
        time.sleep(0.2)
    # the current month, day by day
    d = date(today.year, today.month, 1)
    while d < today:
        url = (f"https://data.binance.vision/data/spot/daily/klines/PAXGUSDT/1m/"
               f"PAXGUSDT-1m-{d.isoformat()}.zip")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                blob = r.read()
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                for line in z.read(z.namelist()[0]).decode().splitlines():
                    p = line.split(",")
                    if p and p[0].isdigit():
                        ts = int(p[0])
                        ts = ts // 1_000_000 if ts > 10**14 else ts // 1000
                        rows.append((ts, p[1], p[2], p[3], p[4], p[5]))
        except urllib.error.HTTPError:
            pass
        d = date.fromordinal(d.toordinal() + 1)
    rows = sorted({r[0]: r for r in rows}.values())
    write_rows(DATA / "binance_PAXGUSDT_1m.csv.gz", ["ts", "open", "high", "low", "close", "volume"], rows)


# ── Yahoo ────────────────────────────────────────────────────────────────────────


def fetch_yahoo() -> None:
    import yfinance as yf

    def dump(ticker: str, period: str, interval: str, name: str) -> None:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
        if hasattr(df.columns, "levels"):
            df.columns = [c[0] for c in df.columns]
        rows = []
        for ts, r in df.iterrows():
            t = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
            rows.append((int(t.timestamp()), r["Open"], r["High"], r["Low"], r["Close"], r.get("Volume", 0)))
        write_rows(DATA / name, ["ts", "open", "high", "low", "close", "volume"], rows)

    dump("GC=F", "730d", "1h", "yahoo_GC_1h.csv.gz")
    dump("GC=F", "max", "1d", "yahoo_GC_1d.csv.gz")
    dump("INR=X", "max", "1d", "yahoo_INR_1d.csv.gz")
    dump("INR=X", "730d", "1h", "yahoo_INR_1h.csv.gz")


if __name__ == "__main__":
    which = set(sys.argv[1:]) or {"delta", "binance", "yahoo"}
    if "delta" in which:
        fetch_delta()
    if "yahoo" in which:
        fetch_yahoo()
    if "binance" in which:
        fetch_binance()
