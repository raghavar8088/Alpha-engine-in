"""Gold strategy lab: loading and aligning the daily histories (see gl_fetch.py).

Every series is indexed by its trading DATE. The master calendar is the traded instrument's own
(GLD by default). A driver that closes after the gold market (the dollar index, Treasury
yields, gold vol) is LAGGED one day before a strategy may read it — `driver(name, lag=1)` — so
no rule can use a number that was not yet printed when its decision was made.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=None)
def load(name: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{name}_1d.csv.gz")
    d = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(None).dt.normalize()
    df = df.drop(columns=["ts"])
    df.index = pd.DatetimeIndex(d, name="date")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for c in ("open", "high", "low", "close", "adj_close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[(df["close"] > 0)]
    # A missing or broken open (Yahoo prints 0 or NaN on some futures days) becomes the
    # previous close: no gap is invented, and none is hidden in the intraday leg.
    bad_open = ~(df["open"] > 0)
    df.loc[bad_open, "open"] = df["close"].shift(1)[bad_open]
    df["high"] = df[["high", "open", "close"]].max(axis=1)
    df["low"] = df[["low", "open", "close"]].min(axis=1)
    return df.dropna(subset=["open", "close"])


def calendar(name: str = "GLD") -> pd.DatetimeIndex:
    return load(name).index


def driver(name: str, col: str = "close", lag: int = 1, on: pd.DatetimeIndex | None = None) -> pd.Series:
    """A driver series on the traded calendar, forward-filled, then lagged `lag` sessions."""
    on = calendar() if on is None else on
    s = load(name)[col].reindex(on.union(load(name).index)).ffill().reindex(on)
    return s.shift(lag)


def rf_daily(on: pd.DatetimeIndex | None = None) -> pd.Series:
    """The cash rate a day (13-week T-bill, ^IRX, % a year), lagged a day; 0 before it prints."""
    return (driver("IRX", lag=1, on=on) / 100.0 / 252.0).fillna(0.0).clip(lower=0.0)
