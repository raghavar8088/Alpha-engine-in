"""Minute data for every market in the study, in one layout (Phase 6), plus bar building.

    python -I bb_markets.py            # builds data/cache/<MKT>.npz and prints a data-quality summary

Layout of a Minutes object (one row per minute that has a price):
    t (UTC seconds of the minute's start), o/h/l/c (mid; the index price for NIFTY/BANKNIFTY),
    half (half the bid-ask spread, price units), vol (volume weight; 1 where the source has none),
    ist (minutes since 00:00 IST), ny (minutes since 00:00 New York, DST-aware),
    day (trading-day index; rows of a day are contiguous), and per day: d0/d1 (row range, d1 exclusive),
    date (the trading day's date), prev_ok (the previous trading day is at most 4 calendar days back),
    excluded (a known feed defect: such days may build levels but their trades are not counted).

Trading days: NIFTY/BANKNIFTY = the 09:15-15:30 IST session; gold/FX = 17:00 New York to 17:00 New York
(TradingView's session breaks); NAS100/US30/AAPL = the 09:30-16:00 New York cash session.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I does not add the script's folder
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
CACHE = HERE / "data" / "cache"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

THIN = (date(2023, 2, 1), date(2023, 7, 31))     # HistData kept ~50% of minutes in this window, every symbol


@dataclass(frozen=True)
class CostModel:
    """Base costs. half_spread=None means the data carries a per-minute spread (gold)."""
    half_spread: float | None
    slip: float                  # price units a side, against us, on market fills
    commission: float            # price units per unit traded, a side
    futures_fees: bool = False   # NIFTY/BANKNIFTY: Angel One futures formula per lot on top
    lot: int = 1

    def scaled(self, spread_x: float = 1.0, slip_x: float = 1.0, comm_x: float = 1.0) -> "CostModel":
        return CostModel(None if self.half_spread is None else self.half_spread * spread_x, self.slip * slip_x,
                         self.commission * comm_x, self.futures_fees, self.lot)


COSTS = {
    "NIFTY": CostModel(0.0, 1.0, 0.0, True, 65),
    "BANKNIFTY": CostModel(0.0, 3.0, 0.0, True, 30),
    "XAUUSD": CostModel(None, 0.10, 0.035),
    "EURUSD": CostModel(0.00001, 0.00001, 0.000035),
    "GBPUSD": CostModel(0.00002, 0.00002, 0.000035),
    "NAS100": CostModel(0.5, 0.25, 0.0),
    "US30": CostModel(1.0, 0.5, 0.0),
    "AAPL": CostModel(0.025, 0.01, 0.0),
}
SPLITS = {   # (development end, validation end); the hold-out is everything after
    "NIFTY": (date(2021, 12, 31), date(2023, 12, 31)), "BANKNIFTY": (date(2021, 12, 31), date(2023, 12, 31)),
    "XAUUSD": (date(2019, 12, 31), date(2022, 12, 31)), "EURUSD": (date(2019, 12, 31), date(2022, 12, 31)),
    "GBPUSD": (date(2019, 12, 31), date(2022, 12, 31)), "NAS100": (date(2019, 12, 31), date(2022, 12, 31)),
    "US30": (date(2024, 12, 31), date(2025, 6, 30)), "AAPL": (date(2024, 12, 31), date(2025, 6, 30)),
}


@dataclass
class Minutes:
    name: str
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    half: np.ndarray
    vol: np.ndarray
    ist: np.ndarray
    ny: np.ndarray
    day: np.ndarray
    d0: np.ndarray
    d1: np.ndarray
    date: np.ndarray            # datetime64[D] per day
    prev_ok: np.ndarray
    excluded: np.ndarray
    cost: CostModel = field(default=None)

    @property
    def n_days(self) -> int:
        return len(self.d0)

    def day_date(self, d: int) -> date:
        return pd.Timestamp(self.date[d]).date()

    def split_of(self, d: int) -> str:
        dev_end, val_end = SPLITS[self.name]
        x = self.day_date(d)
        return "dev" if x <= dev_end else "val" if x <= val_end else "hold"


def _clocks(t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ist = (((t + 19800) // 60) % 1440).astype(np.int16)
    ts = pd.to_datetime(t, unit="s", utc=True).tz_convert("America/New_York")
    ny = (ts.hour.to_numpy() * 60 + ts.minute.to_numpy()).astype(np.int16)
    return ist, ny


def _finish(name: str, t, o, h, l, c, half, vol, day_key: np.ndarray, thin_applies: bool) -> Minutes:
    """day_key: int days since epoch per row (rows sorted by t). Builds the per-day index."""
    order = np.argsort(t, kind="stable")
    t, o, h, l, c, half, vol, day_key = (a[order] for a in (t, o, h, l, c, half, vol, day_key))
    keep = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c) & (h >= l)
    t, o, h, l, c, half, vol, day_key = (a[keep] for a in (t, o, h, l, c, half, vol, day_key))
    starts = np.flatnonzero(np.r_[True, day_key[1:] != day_key[:-1]])
    d0 = starts.astype(np.int64)
    d1 = np.r_[starts[1:], len(t)].astype(np.int64)
    dates = day_key[d0].astype("datetime64[D]")
    gap = np.r_[99, np.diff(day_key[d0])]
    prev_ok = gap <= 4
    day = np.repeat(np.arange(len(d0), dtype=np.int32), d1 - d0)
    if thin_applies:
        lo, hi = np.datetime64(THIN[0]), np.datetime64(THIN[1])
        excluded = (dates >= lo) & (dates <= hi)
    else:
        excluded = np.zeros(len(d0), bool)
    ist, ny = _clocks(t)
    return Minutes(name, t, o, h, l, c, half, vol, ist, ny, day, d0, d1, dates, prev_ok, excluded, COSTS[name])


# ── loaders ───────────────────────────────────────────────────────────────────────────

def _load_index(name: str) -> Minutes:
    sys.path.insert(0, str(RESEARCH / "liquidity_sweep_2026_11"))
    import ls_common as L  # noqa: E402  (sets up clean imports of the app's cleaner)
    days = L.load_minutes() if name == "NIFTY" else L.load_minutes_named(name)
    dates = np.array([np.datetime64(str(d)) for d in days.dates], dtype="datetime64[D]")
    n = len(dates)
    base = (dates.astype("datetime64[s]").astype(np.int64) + 9 * 3600 + 15 * 60 - 19800)  # 09:15 IST in UTC s
    t = (base[:, None] + 60 * np.arange(375)[None, :]).ravel()
    o, h, l, c = (np.asarray(a, float).ravel() for a in (days.o, days.h, days.l, days.c))
    key = np.repeat(dates.astype(np.int64), 375)
    z = np.zeros_like(o)
    return _finish(name, t, o, h, l, c, z, np.ones_like(o), key, False)


def _ny_roll_key(t: np.ndarray) -> np.ndarray:
    """17:00 New York roll: the trading day is the NY date of (t + 7 hours)."""
    ts = pd.to_datetime(t, unit="s", utc=True).tz_convert("America/New_York") + pd.Timedelta(hours=7)
    return ts.normalize().tz_localize(None).to_numpy().astype("datetime64[D]").astype(np.int64)


def _ny_date_key(t: np.ndarray) -> np.ndarray:
    ts = pd.to_datetime(t, unit="s", utc=True).tz_convert("America/New_York")
    return ts.normalize().tz_localize(None).to_numpy().astype("datetime64[D]").astype(np.int64)


def _gold_volume(t: np.ndarray) -> np.ndarray:
    """Dukascopy hourly tick volume spread evenly over the minutes present in that hour (proxy)."""
    bars = pd.read_pickle(RESEARCH / "xauusd_2026_10" / "data" / "bars.pkl")["H"]
    secs = bars.index.tz_convert("UTC").as_unit("s").asi8          # pandas 3 may store seconds, not ns
    hv = pd.Series(bars["v"].to_numpy(float), index=secs).groupby(level=0).sum()
    hour = (t // 3600) * 3600
    counts = pd.Series(1, index=hour).groupby(level=0).sum()
    v = hv.reindex(hour).to_numpy()
    n = counts.reindex(hour).to_numpy()
    out = np.where(np.isfinite(v) & (v > 0), v / n, np.nan)
    med = np.nanmedian(out)
    return np.where(np.isfinite(out), out, med).astype(np.float32)


def _load_gold() -> Minutes:
    z = np.load(RESEARCH / "xauusd_intraday_2026_10" / "data" / "minute.npz")
    t = z["t"].astype(np.int64)
    half = z["spread"].astype(float) / 2
    return _finish("XAUUSD", t, z["o"], z["h"], z["l"], z["c"], half, _gold_volume(t), _ny_roll_key(t), True)


def _load_fx(name: str) -> Minutes:
    z = np.load(RESEARCH / "xauusd_trader_style_2026_10" / "data" / f"{name}.npz")
    t = z["t"].astype(np.int64)
    half = np.full(len(t), COSTS[name].half_spread)
    return _finish(name, t, z["o"], z["h"], z["l"], z["c"], half, np.ones(len(t), np.float32), _ny_roll_key(t), True)


def _load_nas() -> Minutes:
    z = np.load(RESEARCH / "champions_intraday_2026_10" / "data" / "NSXUSD.npz")
    t = z["t"].astype(np.int64)
    half = np.full(len(t), COSTS["NAS100"].half_spread)
    return _finish("NAS100", t, z["o"], z["h"], z["l"], z["c"], half, np.ones(len(t), np.float32), _ny_date_key(t), True)


def _load_duka(name: str) -> Minutes:
    import bb_fetch_dukascopy as F
    sym = {"US30": "USA30IDXUSD", "AAPL": "AAPLUSUSD"}[name]
    m = F.load_minutes(sym)
    if len(m["t"]) == 0:
        raise FileNotFoundError(f"no cached Dukascopy minutes for {sym}")
    t = m["t"].astype(np.int64)
    _, ny = _clocks(t)
    keep = (ny >= 9 * 60 + 30) & (ny < 16 * 60)           # the cash session only
    t = t[keep]
    half_s = COSTS[name].half_spread
    bid = {k: m[k][keep] for k in "ohlc"}
    o, h, l, c = (bid[k] + half_s for k in "ohlc")         # BID + modelled half spread = mid
    return _finish(name, t, o, h, l, c, np.full(len(t), half_s), m["v"][keep].astype(np.float32), _ny_date_key(t), False)


LOADERS = {"NIFTY": lambda: _load_index("NIFTY"), "BANKNIFTY": lambda: _load_index("BANKNIFTY"),
           "XAUUSD": _load_gold, "EURUSD": lambda: _load_fx("EURUSD"), "GBPUSD": lambda: _load_fx("GBPUSD"),
           "NAS100": _load_nas, "US30": lambda: _load_duka("US30"), "AAPL": lambda: _load_duka("AAPL")}
_FIELDS = ("t", "o", "h", "l", "c", "half", "vol", "ist", "ny", "day", "d0", "d1", "date", "prev_ok", "excluded")


def load(name: str, rebuild: bool = False) -> Minutes:
    path = CACHE / f"{name}.npz"
    if path.exists() and not rebuild and name not in ("US30", "AAPL"):
        z = np.load(path)
        return Minutes(name, *(z[f] for f in _FIELDS), cost=COSTS[name])
    m = LOADERS[name]()
    if name not in ("US30", "AAPL"):
        CACHE.mkdir(parents=True, exist_ok=True)
        np.savez(path, **{f: getattr(m, f) for f in _FIELDS})
    return m


# ── bars ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Bars:
    tf: int
    day: np.ndarray       # trading-day index
    i0: np.ndarray        # first minute row
    i1: np.ndarray        # last minute row (the bar is known after this minute)
    t0: np.ndarray        # UTC seconds of the bar's grid start
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    ist0: np.ndarray      # bar grid start, minutes since 00:00 IST
    ny0: np.ndarray       # bar grid start, minutes since 00:00 New York
    b0: np.ndarray        # per day: first bar index
    b1: np.ndarray        # per day: one past the last bar index


def bars(m: Minutes, tf: int) -> Bars:
    """tf-minute bars that never cross a trading day. NIFTY's grid starts 09:15 IST; others 00:00 UTC."""
    if m.name in ("NIFTY", "BANKNIFTY"):
        slot = ((m.t + 19800 - (9 * 3600 + 15 * 60)) // 60) // tf
    else:
        slot = (m.t // 60) // tf
    key = m.day.astype(np.int64) * 10_000_000 + (slot - slot.min())
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], len(key)] - 1
    o = m.o[starts]
    c = m.c[ends]
    h = np.maximum.reduceat(m.h, starts)
    l = np.minimum.reduceat(m.l, starts)
    if m.name in ("NIFTY", "BANKNIFTY"):
        t0 = slot[starts] * tf * 60 - 19800 + (9 * 3600 + 15 * 60)
    else:
        t0 = slot[starts] * tf * 60
    day = m.day[starts]
    b0 = np.searchsorted(day, np.arange(m.n_days), "left")
    b1 = np.searchsorted(day, np.arange(m.n_days), "right")
    ist0, ny0 = _clocks(t0.astype(np.int64))
    return Bars(tf, day, starts.astype(np.int64), ends.astype(np.int64), t0.astype(np.int64), o, h, l, c, ist0, ny0, b0, b1)


def ema(x: np.ndarray, n: int) -> np.ndarray:
    a = 2.0 / (n + 1)
    out = np.empty_like(x, dtype=float)
    s = x[0]
    for i, v in enumerate(x):
        s = a * v + (1 - a) * s if i else v
        out[i] = s
    return out


def sma(x: np.ndarray, n: int) -> np.ndarray:
    cs = np.cumsum(np.r_[0.0, x])
    out = np.full(len(x), np.nan)
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def rsi(x: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(x, prepend=x[0])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    a = 1.0 / n
    ru, rd = np.empty_like(x, dtype=float), np.empty_like(x, dtype=float)
    su = sd = 0.0
    for i in range(len(x)):
        su = (1 - a) * su + a * up[i]
        sd = (1 - a) * sd + a * dn[i]
        ru[i], rd[i] = su, sd
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100 - 100 / (1 + ru / rd)
    return np.where(rd == 0, 100.0, r)


def daily_ohlc(m: Minutes) -> dict[str, np.ndarray]:
    o = m.o[m.d0]
    c = m.c[m.d1 - 1]
    h = np.maximum.reduceat(m.h, m.d0)
    l = np.minimum.reduceat(m.l, m.d0)
    return {"o": o, "h": h, "l": l, "c": c}


def quality_report(m: Minutes) -> dict:
    per_day = m.d1 - m.d0
    return {"market": m.name, "days": int(m.n_days), "minutes": int(len(m.t)),
            "first": str(m.date[0]), "last": str(m.date[-1]),
            "median_minutes_per_day": int(np.median(per_day)),
            "days_under_50pct_of_median": int((per_day < 0.5 * np.median(per_day)).sum()),
            "excluded_days": int(m.excluded.sum()), "prev_gap_over_4d": int((~m.prev_ok).sum()),
            "median_half_spread": float(np.median(m.half)),
            "zero_range_minutes_pct": round(100 * float(np.mean(m.h == m.l)), 1)}


if __name__ == "__main__":
    import json
    names = sys.argv[1:] or ["NIFTY", "BANKNIFTY", "XAUUSD", "EURUSD", "GBPUSD", "NAS100"]
    out = {}
    for nm in names:
        mk = load(nm, rebuild=True)
        out[nm] = quality_report(mk)
        print(json.dumps(out[nm]), flush=True)
    (HERE / "results").mkdir(exist_ok=True)
    prev = {}
    qp = HERE / "results" / "data_quality.json"
    if qp.exists():
        prev = json.loads(qp.read_text())
    prev.update(out)
    qp.write_text(json.dumps(prev, indent=2))
