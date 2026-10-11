"""Shared loaders for the Gold Desk research: 1-minute histories -> the desk's bars.

Bars are built exactly the way the live desk builds them, so a pattern sees here what it
would see there:

  24/7 venues (Delta, Binance PAXG)  buckets anchored to UTC MIDNIGHT, the day is the UTC day
                                     (`gold_delta_feed.resample`), ts carried in UTC.
  MCX                                only minutes inside the MCX session; buckets anchored to
                                     the 09:00 IST open, the day is the IST trading date
                                     (`commodity_bars.resample`), ts carried in IST; 4h from 1h.

Nothing here touches the network or the database.
"""

from __future__ import annotations

import gzip
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(__file__).resolve().parent / "data"
for p in (ROOT / "backend", ROOT / "strategy-service", ROOT / "shared"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

IST = timezone(timedelta(hours=5, minutes=30))
TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "45m": 45, "1h": 60, "4h": 240, "1d": 1440}


class Bar:
    """The same six slots as `commodity_bars.Bar` / `gold_delta_feed.Bar`."""

    __slots__ = ("ts", "open", "high", "low", "close", "volume")

    def __init__(self, ts, o, h, l, c, v):
        self.ts, self.open, self.high, self.low, self.close, self.volume = ts, o, h, l, c, v


def load_1m(name: str) -> pd.DataFrame:
    """A 1m csv.gz from ./data as a DataFrame indexed by UTC timestamp."""
    df = pd.read_csv(DATA / name)
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    df = df.drop_duplicates("ts").set_index("ts").sort_index()
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df


# ── MCX session ──────────────────────────────────────────────────────────────────


def mcx_close_minutes(day_ist: pd.Timestamp) -> int:
    """Minutes after 09:00 IST at which that day's MCX session ends: 23:30 while the US is
    on daylight time, 23:55 while it is not (MCX follows the US close)."""
    try:
        from tradingai_shared.mcx_calendar import session_close
        t = session_close(day_ist.date())
        return (t.hour - 9) * 60 + t.minute
    except Exception:  # noqa: BLE001 - fall back to the US DST rule
        d = day_ist.date()
        # US DST: second Sunday of March .. first Sunday of November
        mar = datetime(d.year, 3, 8)
        dst_start = mar + timedelta(days=(6 - mar.weekday()) % 7)
        nov = datetime(d.year, 11, 1)
        dst_end = nov + timedelta(days=(6 - nov.weekday()) % 7)
        in_dst = dst_start.date() <= d < dst_end.date()
        return (23 - 9) * 60 + (30 if in_dst else 55)


def mcx_session_1m(df_utc: pd.DataFrame) -> pd.DataFrame:
    """Keep only the minutes MCX is open (weekday, 09:00 IST to the close). The index is
    converted to IST. Exchange holidays are not removed (the calendar file only covers
    2026); a holiday then reads as an ordinary session of the international price."""
    d = df_utc.copy()
    d.index = d.index.tz_convert(IST)
    mins = (d.index.hour * 60 + d.index.minute) - 9 * 60
    days = d.index.normalize()
    close_by_day = {day: mcx_close_minutes(day) for day in pd.unique(days)}
    close_m = np.array([close_by_day[x] for x in days])
    keep = (d.index.dayofweek < 5) & (mins >= 0) & (mins < close_m)
    return d[keep]


# ── resampling ───────────────────────────────────────────────────────────────────


def _agg(g: pd.DataFrame) -> pd.DataFrame:
    return g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})


def resample_utc(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """24/7: buckets anchored to UTC midnight (1440 divides by every TF used)."""
    m = TF_MIN[tf]
    if m == 1:
        return df[["open", "high", "low", "close", "volume"]]
    out = df.resample(f"{m}min", origin="start_day", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return out.dropna(subset=["open"])


def resample_mcx(df_ist: pd.DataFrame, tf: str) -> pd.DataFrame:
    """MCX: buckets of `tf` minutes since 09:00 IST of the bar's own date; 1d = the
    session; 4h built from 1h exactly as the store does (both anchor at 09:00)."""
    m = TF_MIN[tf]
    if m == 1:
        return df_ist[["open", "high", "low", "close", "volume"]]
    idx = df_ist.index
    day = idx.normalize()
    if m >= 1440:
        key = day
    else:
        mins = (idx.hour * 60 + idx.minute) - 9 * 60
        key = day + pd.to_timedelta(9 * 60 + (mins // m) * m, unit="min")
    g = df_ist.groupby(key)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum()})
    out.index.name = "ts"
    return out


def to_bars(df: pd.DataFrame, tz) -> list[Bar]:
    ts = df.index.tz_convert(tz).to_pydatetime()
    o, h, l, c, v = (df[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    return [Bar(ts[i], float(o[i]), float(h[i]), float(l[i]), float(c[i]), float(v[i]))
            for i in range(len(df))]
