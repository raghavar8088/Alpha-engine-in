"""Markets for the Booming Bulls "Crypto Trading" playlist strategies, in the Minutes layout of
../booming_bulls_2026_11/bb_markets.py (through yt_markets, so the YouTube study's engine runs them).

  XAUUSD, EURUSD, GBPUSD   the Booming Bulls caches (1-minute rows, 17:00 New York trading days)
  BTCUSD                   Binance BTCUSDT spot 1-minute klines (data.binance.vision), with the taker-buy volume
                           of every minute, so a candle's order-flow delta is real (2 x taker buy - volume).
                           Trading day = the UTC date. Fetch: python -I cp_markets.py fetch 2024-10 2026-10
"""

from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(RESEARCH / "youtube_top20_2026_11"))
sys.path.insert(0, str(RESEARCH / "booming_bulls_2026_11"))

import bb_markets as BM  # noqa: E402
import yt_markets as YM  # noqa: E402

BINANCE = HERE / "data" / "binance"
BTC_HALF = 0.00005          # half the bid-ask spread as a fraction of price (0.5 bp; BTCUSDT quotes a cent apart)
BTC_COST = YM.Cost(0.0, 0.0, 0.0, False, 1, pct_slip=0.0002, pct_comm=0.0005)   # 2 bp slippage + 5 bp taker fee a side
BM.COSTS.setdefault("BTCUSD", BM.CostModel(0.0, 0.0, 0.0))
YM.COSTS.setdefault("BTCUSD", BTC_COST)
YM.SPLITS.setdefault("BTCUSD", (date(2025, 6, 30), date(2025, 12, 31)))          # unused: nothing is chosen on splits here


def utc_day_key(t: np.ndarray) -> np.ndarray:
    return (t // 86400).astype(np.int64)


def btc_market(t, o, h, l, c, v, bv, name: str = "BTCUSD"):
    """A Mkt from Binance minutes. Rows must be sorted, unique and finite; `bv` (taker buy volume) is attached."""
    t = np.asarray(t, np.int64)
    keep = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c) & (h >= l)
    t, o, h, l, c, v, bv = (np.asarray(a)[keep] for a in (t, o, h, l, c, v, bv))
    order = np.argsort(t, kind="stable")
    t, o, h, l, c, v, bv = (a[order] for a in (t, o, h, l, c, v, bv))
    half = c * BTC_HALF
    m = BM._finish(name, t, o, h, l, c, half, v.astype(np.float32), utc_day_key(t), False)
    k = YM._as_mkt(m, name, name, BTC_COST)
    k.bv = np.asarray(bv, float)
    k.vol_all = np.asarray(v, float)
    return k


def _month_url(ym: str) -> str:
    return f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-{ym}.zip"


def fetch(first: str, last: str) -> None:
    BINANCE.mkdir(parents=True, exist_ok=True)
    y, mth = map(int, first.split("-"))
    y1, m1 = map(int, last.split("-"))
    while (y, mth) <= (y1, m1):
        ym = f"{y:04d}-{mth:02d}"
        path = BINANCE / f"BTCUSDT-1m-{ym}.zip"
        if not path.exists():
            req = urllib.request.Request(_month_url(ym), headers={"User-Agent": "research-fetch/1.0"})
            path.write_bytes(urllib.request.urlopen(req, timeout=120).read())
            print("fetched", ym, path.stat().st_size, flush=True)
        mth += 1
        if mth > 12:
            y, mth = y + 1, 1


def load_btc(first: str = "2024-10", last: str = "2026-10"):
    """Columns: open time, o, h, l, c, volume, close time, quote volume, trades, taker-buy base, taker-buy quote, ignore.
    From 2025 Binance writes spot timestamps in microseconds; both are read."""
    parts = []
    for f in sorted(BINANCE.glob("BTCUSDT-1m-*.zip")):
        ym = f.stem.split("-1m-")[1]
        if not (first <= ym <= last):
            continue
        with zipfile.ZipFile(f) as z:
            raw = z.read(z.namelist()[0])
        a = np.loadtxt(io.BytesIO(raw), delimiter=",", usecols=(0, 1, 2, 3, 4, 5, 9), ndmin=2)
        parts.append(a)
    a = np.concatenate(parts)
    t = a[:, 0].astype(np.int64)
    t = np.where(t > 10**14, t // 1_000_000, t // 1000)
    t, idx = np.unique(t, return_index=True)
    a = a[idx]
    return btc_market(t, a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5], a[:, 6])


def load(name: str):
    if name == "BTCUSD":
        return load_btc()
    return YM.load(name)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fetch":
        fetch(sys.argv[2], sys.argv[3])
    else:
        m = load_btc()
        print("BTCUSD rows", len(m.t), "days", m.n_days, str(m.date[0]), str(m.date[-1]), "taker share", round(float(m.bv.sum() / m.vol_all.sum()), 3))
