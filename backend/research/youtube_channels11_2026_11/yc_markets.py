"""Research data for the 11-channel study, in the layouts the paper desk uses:
  NIFTY, BANKNIFTY, XAUUSD, EURUSD, GBPUSD, NAS100   the Booming Bulls minute caches (yt_markets.load)
  BTCUSD                                             Binance BTCUSDT 1-minute klines (crypto_playlist_2026_11)
  ETHUSD                                             Binance ETHUSDT 1-minute klines (NJ-33's second coin), fetched here
                                                     from data.binance.vision:  python -I yc_markets.py fetch_eth 2026-07 2026-10
  NSE5 / NSE15                                       the 268-stock 5-minute store (yt_markets.nse_intraday)
  NSED                                               the YouTube study's NSE daily panel, with the bhavcopy turnover attached
  NIFTY_D                                            daily rows of NIFTY
and cut(m, last_row): the same market rebuilt from its rows up to last_row, for the truncation test."""

from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
for _p in (HERE, RESEARCH / "youtube_top20_2026_11", RESEARCH / "booming_bulls_2026_11", RESEARCH / "crypto_playlist_2026_11"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402

import bb_markets as BM  # noqa: E402
import cp_markets as CM  # noqa: E402
import yt_markets as YM  # noqa: E402

ETH_DIR = HERE / "data" / "binance_eth"
BM.COSTS.setdefault("ETHUSD", BM.CostModel(0.0, 0.0, 0.0))
YM.COSTS.setdefault("ETHUSD", CM.BTC_COST)
YM.SPLITS.setdefault("ETHUSD", YM.SPLITS["BTCUSD"])
NSED_FILE = RESEARCH / "youtube_top20_2026_11" / "data" / "nse_daily.npz"


def fetch_eth(first: str, last: str) -> None:
    ETH_DIR.mkdir(parents=True, exist_ok=True)
    y, mth = map(int, first.split("-"))
    y1, m1 = map(int, last.split("-"))
    while (y, mth) <= (y1, m1):
        ym = f"{y:04d}-{mth:02d}"
        path = ETH_DIR / f"ETHUSDT-1m-{ym}.zip"
        if not path.exists():
            url = f"https://data.binance.vision/data/spot/monthly/klines/ETHUSDT/1m/ETHUSDT-1m-{ym}.zip"
            req = urllib.request.Request(url, headers={"User-Agent": "research-fetch/1.0"})
            path.write_bytes(urllib.request.urlopen(req, timeout=120).read())
            print("fetched", ym, path.stat().st_size, flush=True)
        mth += 1
        if mth > 12:
            y, mth = y + 1, 1


def load_eth():
    parts = []
    for f in sorted(ETH_DIR.glob("ETHUSDT-1m-*.zip")):
        with zipfile.ZipFile(f) as z:
            raw = z.read(z.namelist()[0])
        parts.append(np.loadtxt(io.BytesIO(raw), delimiter=",", usecols=(0, 1, 2, 3, 4, 5, 9), ndmin=2))
    if not parts:
        return None
    a = np.concatenate(parts)
    t = a[:, 0].astype(np.int64)
    t = np.where(t > 10**14, t // 1_000_000, t // 1000)
    t, idx = np.unique(t, return_index=True)
    a = a[idx]
    return CM.btc_market(t, a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5], a[:, 6], name="ETHUSD")


_FULL: dict = {}


def full(name: str):
    if name not in _FULL:
        if name == "BTCUSD":
            _FULL[name] = CM.load_btc()
        elif name == "ETHUSD":
            _FULL[name] = load_eth()
        elif name == "NIFTY_D":
            _FULL[name] = YM.daily(full("NIFTY"))
        else:
            _FULL[name] = YM.load(name)
    return _FULL[name]


def window(name: str, days: int):
    """The last `days` trading days of a minute market (or all rows of a daily one)."""
    m = full(name)
    if m is None or name == "NIFTY_D":
        return m
    d0 = max(0, m.n_days - days)
    return cut(m, int(m.d1[m.n_days - 1]) - 1, first_row=int(m.d0[d0]))


def nse_pool(symbols: list[str], days: int):
    out = []
    for m in YM.nse_intraday(symbols):
        d0 = max(0, m.n_days - days)
        out.append(cut(m, int(m.d1[m.n_days - 1]) - 1, first_row=int(m.d0[d0])))
    return out


def nsed(limit: int | None = None, names: list[str] | None = None):
    YM.HERE = RESEARCH / "youtube_top20_2026_11"
    ms = YM.nse_daily()
    if names is not None:
        keep = set(names)
        ms = [m for m in ms if m.name in keep]
    elif limit is not None:
        ms = sorted(ms, key=lambda m: -float(np.nansum(m.liquid[-60:])))[:limit]
    import yc_run as R
    R.attach_value(ms, NSED_FILE)
    return ms


def cut(m, last_row: int, first_row: int = 0):
    """The market's rows first_row .. last_row rebuilt with the builder its kind uses (a partial day stays partial)."""
    a, k = first_row, last_row + 1
    if m.name in ("BTCUSD", "ETHUSD"):
        out = CM.btc_market(m.t[a:k], m.o[a:k], m.h[a:k], m.l[a:k], m.c[a:k], m.vol_all[a:k], m.bv[a:k], name=m.name)
        return out
    key = np.repeat(m.date.astype(np.int64), m.d1 - m.d0)[a:k]
    if getattr(m, "split_key", None) == "NSED" or m.name.endswith("_D"):
        return _cut_daily(m, a, k)
    mm = BM._finish(m.name, m.t[a:k], m.o[a:k], m.h[a:k], m.l[a:k], m.c[a:k], m.half[a:k], m.vol[a:k], key, False)
    out = YM._as_mkt(mm, m.name, getattr(m, "split_key", m.name), m.cost, getattr(m, "overnight", False))
    return out


def _cut_daily(m, a, k):
    """A daily market (one row a day) cut to rows a .. k-1, keeping its per-row extras."""
    n = k - a
    out = YM.Mkt(m.name, m.t[a:k], m.o[a:k], m.h[a:k], m.l[a:k], m.c[a:k], m.half[a:k], m.vol[a:k], m.ist[a:k], m.ny[a:k],
                 np.arange(n, dtype=np.int32), np.arange(n, dtype=np.int64), np.arange(1, n + 1, dtype=np.int64),
                 m.date[a:k], m.prev_ok[a:k], m.excluded[a:k], m.cost)
    out.split_key, out.overnight = m.split_key, True
    for extra in ("liquid", "value", "turnover20"):
        if hasattr(m, extra):
            setattr(out, extra, np.asarray(getattr(m, extra))[a:k])
    return out


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[1] == "fetch_eth":
        fetch_eth(sys.argv[2], sys.argv[3])
    else:
        for nm in ("NIFTY", "BANKNIFTY", "XAUUSD", "EURUSD", "GBPUSD", "NAS100", "BTCUSD", "ETHUSD"):
            mk = full(nm)
            print(nm, None if mk is None else (len(mk.t), mk.n_days, str(mk.date[0]), str(mk.date[-1])))
