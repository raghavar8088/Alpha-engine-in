"""Markets for the YouTube top-20 study, in the Minutes layout of ../booming_bulls_2026_11/bb_markets.py.

  NIFTY, BANKNIFTY, XAUUSD, EURUSD, GBPUSD, NAS100   the Booming Bulls caches (1-minute rows)
  SPX500                                            HistData SPXUSD regular session (1-minute rows)
  <X>_D                                             daily rows built from a minute market (overnight trades)
  NSE intraday stocks                               Angel 5-minute candles 2024-10 to 2026-11 for today's
                                                    268-stock liquid universe (D:/intraday_ai_data/intraday/5m)
  NSE daily stocks                                  bhavcopy 2011-06 to 2026-11, every EQ stock incl. delisted
                                                    (data/nse_daily.npz, split-adjusted), point-in-time liquid filter
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
sys.path.insert(0, str(RESEARCH / "booming_bulls_2026_11"))
import bb_markets as BM  # noqa: E402
from bb_markets import Bars, Minutes, bars, ema, rsi, sma, _finish, _clocks, _ny_date_key  # noqa: E402,F401

CACHE = HERE / "data" / "cache"


@dataclass(frozen=True)
class Cost:
    half_spread: float | None
    slip: float
    commission: float
    futures_fees: bool = False
    lot: int = 1
    pct_slip: float = 0.0
    pct_comm: float = 0.0

    def scaled(self, *_a, **_k):
        return self


STOCK_INTRADAY = Cost(0.0, 0.0, 0.0, False, 1, pct_slip=0.0002, pct_comm=0.0003)   # 2 bp slip + 3 bp fees a side
STOCK_DELIVERY = Cost(0.0, 0.0, 0.0, False, 1, pct_slip=0.0003, pct_comm=0.00115)  # 3 bp slip + 11.5 bp fees a side
COSTS = {**{k: Cost(v.half_spread, v.slip, v.commission, v.futures_fees, v.lot) for k, v in BM.COSTS.items()},
         "SPX500": Cost(0.25, 0.125, 0.0)}

SPLITS = {
    "NIFTY": (date(2021, 12, 31), date(2023, 12, 31)), "BANKNIFTY": (date(2021, 12, 31), date(2023, 12, 31)),
    "XAUUSD": (date(2019, 12, 31), date(2022, 12, 31)), "EURUSD": (date(2019, 12, 31), date(2022, 12, 31)),
    "GBPUSD": (date(2019, 12, 31), date(2022, 12, 31)), "NAS100": (date(2019, 12, 31), date(2022, 12, 31)),
    "SPX500": (date(2019, 12, 31), date(2022, 12, 31)),
    "NSE15": (date(2025, 6, 30), date(2025, 12, 31)),       # stocks intraday: 2024-10 .. 2026-11
    "NSED": (date(2019, 12, 31), date(2022, 12, 31)),       # stocks daily: 2011-06 .. 2026-11
}


class Mkt(Minutes):
    """Minutes plus the study's split table and an overnight flag."""

    split_key: str = ""
    overnight: bool = False

    def split_of(self, d: int) -> str:
        dev_end, val_end = SPLITS[self.split_key]
        x = self.day_date(d)
        return "dev" if x <= dev_end else "val" if x <= val_end else "hold"


def _as_mkt(m: Minutes, name: str, split_key: str, cost: Cost, overnight=False) -> Mkt:
    k = Mkt(name, m.t, m.o, m.h, m.l, m.c, m.half, m.vol, m.ist, m.ny, m.day, m.d0, m.d1, m.date, m.prev_ok,
            m.excluded, cost)
    k.split_key, k.overnight = split_key, overnight
    return k


_CACHE: dict = {}


def load(name: str) -> Mkt:
    if name in _CACHE:
        return _CACHE[name]
    if name.endswith("_D"):
        out = daily(load(name[:-2]))
    elif name == "SPX500":
        path = CACHE / "SPX500.npz"
        if path.exists():
            z = np.load(path)
            m = Minutes("SPX500", *(z[f] for f in BM._FIELDS), cost=None)
        else:
            z = np.load(RESEARCH / "champions_intraday_2026_10" / "data" / "SPXUSD.npz")
            t = z["t"].astype(np.int64)
            BM.COSTS["SPX500"] = BM.CostModel(0.25, 0.125, 0.0)
            m = _finish("SPX500", t, z["o"], z["h"], z["l"], z["c"], np.full(len(t), 0.25), np.ones(len(t), np.float32),
                        _ny_date_key(t), True)
            CACHE.mkdir(parents=True, exist_ok=True)
            np.savez(path, **{f: getattr(m, f) for f in BM._FIELDS})
        out = _as_mkt(m, "SPX500", "SPX500", COSTS["SPX500"])
    else:
        m = BM.load(name)
        out = _as_mkt(m, name, name, COSTS[name])
    _CACHE[name] = out
    return out


def daily(m: Mkt) -> Mkt:
    """One row per trading day (open, high, low, close of the session); trades may last many rows."""
    d0, d1 = m.d0, m.d1
    o = m.o[d0]
    c = m.c[d1 - 1]
    h = np.maximum.reduceat(m.h, d0)
    l = np.minimum.reduceat(m.l, d0)
    half = np.array([float(np.median(m.half[a:b])) for a, b in zip(d0, d1)])
    n = len(d0)
    t = m.t[d0]
    ist, ny = _clocks(t)
    k = Mkt(m.name + "_D", t, o, h, l, c, half, np.ones(n, np.float32), ist, ny, np.arange(n, dtype=np.int32),
            np.arange(n, dtype=np.int64), np.arange(1, n + 1, dtype=np.int64), m.date, m.prev_ok, m.excluded, m.cost)
    k.split_key, k.overnight = m.split_key, True
    return k


# ── NSE stocks ────────────────────────────────────────────────────────────────────────

def nse_intraday(symbols: list[str] | None = None) -> list[Mkt]:
    """5-minute rows per stock (Angel candles), 09:15-15:30 IST; IST-date trading days."""
    os.environ.setdefault("INTRADAY_DATA_DIR", "D:/intraday_ai_data/intraday")
    sys.path.insert(0, str(RESEARCH.parent))
    from app.services import intraday_store as S
    folder = Path(os.environ["INTRADAY_DATA_DIR"]) / "5m"
    names = symbols or sorted(p.stem for p in folder.glob("*.ibar"))
    out = []
    for sym in names:
        b = S.read_file(sym, "5m")
        if len(b) < 2000:
            continue
        t = np.frombuffer(b.t, dtype=np.int64).astype(np.int64) if not isinstance(b.t, np.ndarray) else b.t.astype(np.int64)
        o, h, l, c = (np.asarray(getattr(b, k), float) for k in ("o", "h", "l", "c"))
        v = np.asarray(b.v, float)
        ist_min = ((t + 19800) // 60) % 1440
        keep = (ist_min >= 9 * 60 + 15) & (ist_min < 15 * 60 + 30) & (h >= l) & (c > 0)
        t, o, h, l, c, v = (a[keep] for a in (t, o, h, l, c, v))
        key = ((t + 19800) // 86400).astype(np.int64)
        m = _finish_stock(sym, t, o, h, l, c, v, key)
        out.append(m)
    return out


def _finish_stock(sym, t, o, h, l, c, v, key) -> Mkt:
    BM.COSTS.setdefault(sym, BM.CostModel(0.0, 0.0, 0.0))
    m = _finish(sym, t, o, h, l, c, np.zeros(len(t)), v.astype(np.float32), key, False)
    k = _as_mkt(m, sym, "NSE15", STOCK_INTRADAY)
    return k


def nse_daily(min_turnover_cr: float = 10.0, min_price: float = 50.0):
    """Daily rows per stock from the bhavcopy (split-adjusted) and, per row, a point-in-time liquidity flag:
    the 20 previous sessions' mean turnover >= min_turnover_cr crore and the previous close >= min_price."""
    zf = np.load(HERE / "data" / "nse_daily.npz", allow_pickle=False)
    z = {k: zf[k] for k in zf.files}          # decompress each array once (npz access is lazy)
    code, names, dates = z["code"], z["names"], z["date"]
    starts = np.flatnonzero(np.r_[True, code[1:] != code[:-1]])
    ends = np.r_[starts[1:], len(code)]
    out = []
    for a, b in zip(starts, ends):
        if b - a < 260:
            continue
        sym = str(names[code[a]])
        o, h, l, c, val = (z[k][a:b].astype(float) for k in ("o", "h", "l", "c", "value"))
        dts = dates[a:b]
        cs = np.cumsum(np.r_[0.0, val])
        liq = np.zeros(b - a, bool)
        if b - a > 21:
            mean20 = (cs[20:-1] - cs[:-21]) / 20          # mean of the 20 rows before row i (i >= 20)
            liq[20:] = (mean20 >= min_turnover_cr * 1e7) & (c[19:-1] >= min_price)
        if not liq.any():
            continue
        t = (dts.astype("datetime64[s]").astype(np.int64) + 9 * 3600 + 15 * 60 - 19800)
        n = b - a
        ist, ny = _clocks(t)
        gap = np.r_[99, np.diff(dts.astype(np.int64))]
        k = Mkt(sym, t, o, h, l, c, np.zeros(n), np.ones(n, np.float32), ist, ny, np.arange(n, dtype=np.int32),
                np.arange(n, dtype=np.int64), np.arange(1, n + 1, dtype=np.int64), dts, gap <= 7, np.zeros(n, bool),
                STOCK_DELIVERY)
        k.split_key, k.overnight = "NSED", True
        k.liquid = liq
        out.append(k)
    return out
