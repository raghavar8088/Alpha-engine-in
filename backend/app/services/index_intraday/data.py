"""Indian Index Intraday: 1-minute history as day x minute matrices, quality-checked.

Source: Angel One's ONE_MINUTE candles (backend/research/index_intraday_2026_10/ii_fetch.py, run on
the server into /data/intraday/idx1m; copied to the research folder's data/1m for the study).
Every series becomes, per trading day, the 375 session minutes 09:15 .. 15:29 IST:

    o, h, l, c, v : float arrays of shape (days, 375)

QUALITY (each rule counted and reported, never silent)
* A day is KEPT only if it is a normal session: its first minute is 09:15 and it has at least
  MIN_MINUTES of the 375 minutes. Muhurat / special / half sessions and broken downloads drop.
* A missing minute inside a kept day is a FLAT minute at the previous close (volume 0) — the
  index printed nothing new; no move is invented and none is hidden.
* Rows outside 09:15-15:29 are ignored (pre-open is folded into Angel's 09:15 bar already).
* PRICE SANITY: a print at or below zero (Angel's -0.01 placeholder: FINNIFTY, three days of
  August 2022), or — for an index or ETF — one more than 15% from its day's median close (stray
  opening prints in NIFTYBEES / BANKBEES / JUNIORBEES, 2020-21) is dropped like a missing minute.
  India VIX values Angel served divided by 100 (2016-01 .. 2016-09-08, 2021-03-01) are rescaled.
  The first research run used the data before these rules; it was re-run on the corrected data.

Bars of other lengths are built from the minutes, anchored at 09:15 within each day (never
across the overnight gap). 10m and 30m end in a shorter stub bar at 15:25 / 15:15.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

_RESEARCH = Path(__file__).resolve().parents[3] / "research" / "index_intraday_2026_10" / "data" / "1m"
# The server keeps the 1-minute history on its persistent volume; a research checkout keeps it next
# to the study scripts. IDX1M_DIR overrides both.
DATA = Path(os.getenv("IDX1M_DIR") or (_RESEARCH if _RESEARCH.exists() else "/data/intraday/idx1m"))
IST = timezone(timedelta(hours=5, minutes=30))
SESSION_MIN = 375                       # 09:15 .. 15:29
OPEN_MIN = 9 * 60 + 15
MIN_MINUTES = 360                       # a kept day has at least this many of the 375 minutes
MAX_DEVIATION = 0.15                    # an index / ETF print this far from its day's median is not real
VIX_SCALE_BELOW = 2.0                   # India VIX under 2 was served divided by 100


@dataclass
class Days:
    """One series as (days x 375) minute matrices."""
    name: str
    dates: np.ndarray                    # datetime64[D], one per kept day
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    quality: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.dates)

    def mask(self, start: str, end: str) -> np.ndarray:
        return (self.dates >= np.datetime64(start)) & (self.dates <= np.datetime64(end))

    def prev_close(self) -> np.ndarray:
        """The previous kept day's last close (NaN for the first)."""
        return np.r_[np.nan, self.c[:-1, -1]]

    def daily(self) -> dict:
        """Daily OHLC of each kept day."""
        return {"o": self.o[:, 0], "h": self.h.max(axis=1), "l": self.l.min(axis=1), "c": self.c[:, -1]}


def _read(name: str, since: date | None = None, until: date | None = None) -> np.ndarray:
    """Every row of a series as an (n, 6) array of ts, o, h, l, c, v — or, with `since` / `until`,
    only the files that can hold days in that span (files are named by the first day they cover;
    a 30-day window file starting up to 31 days earlier may still reach `since`). A row whose
    time or prices do not parse is skipped; a blank volume is 0."""
    files = sorted((DATA / name).glob("*.csv.gz"))
    if since is not None or until is not None:
        keep = []
        for f in files:
            try:
                first = date.fromisoformat(f.name[:10])
            except ValueError:
                keep.append(f)
                continue
            if (since is None or first >= since - timedelta(days=31)) and (until is None or first <= until):
                keep.append(f)
        files = keep
    parts = []
    for f in files:
        try:
            df = pd.read_csv(f, header=None, skiprows=1, usecols=range(6), on_bad_lines="skip")
        except (ValueError, OSError, pd.errors.EmptyDataError):
            continue
        a = df.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        a = a[~np.isnan(a[:, :5]).any(axis=1)]
        a[np.isnan(a[:, 5]), 5] = 0.0
        parts.append(a)
    return np.concatenate(parts) if parts else np.empty((0, 6))


@lru_cache(maxsize=None)
def load(name: str) -> Days:
    return _build(name, _read(name))


def load_recent(name: str, days: int = 120) -> Days:
    """Only the last `days` calendar days (read from just the files that can hold them) — what
    the live engine needs for its indicators, in a fraction of the full load's time."""
    since = date.today() - timedelta(days=days)
    d = _build(name, _read(name, since))
    keep = d.dates >= np.datetime64(since)
    return Days(d.name, d.dates[keep], d.o[keep], d.h[keep], d.l[keep], d.c[keep], d.v[keep], d.quality)


def with_today(hist: Days, minutes: dict[int, tuple], day: date, upto_minute: int) -> Days:
    """`hist` plus today's session so far as one more row: minutes before `upto_minute` from
    `minutes` (epoch -> o, h, l, c, v; a missing one is flat at the previous close), every later
    minute NaN — so causal indicators and the families' scans see exactly what is known."""
    row = np.full((5, SESSION_MIN), np.nan)
    last = None
    base = int(datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST).timestamp())
    for m in range(min(upto_minute, SESSION_MIN)):
        bar = minutes.get(base + 60 * m)
        if bar is None:
            if last is None:
                continue
            row[:, m] = (last, last, last, last, 0.0)
        else:
            o, h, l, c, v = bar
            row[:, m] = (o, max(h, o, c), min(l, o, c), c, v)
            last = c
    dates = np.r_[hist.dates, np.array([np.datetime64(day.isoformat())])].astype("datetime64[D]")
    stack = lambda a, k: np.vstack([a, row[k][None, :]])  # noqa: E731
    return Days(hist.name, dates, stack(hist.o, 0), stack(hist.h, 1), stack(hist.l, 2), stack(hist.c, 3),
                stack(hist.v, 4), hist.quality)


def _build(name: str, rows: np.ndarray) -> Days:
    """Rows -> kept days x 375 minutes. Of two rows for one minute the later in (ts, o, h, l, c, v)
    order wins; a missing minute is flat at the last printed close (volume 0)."""
    if rows is None or not len(rows):
        raise FileNotFoundError(f"no 1-minute data for {name} under {DATA}")
    ts = rows[:, 0].astype(np.int64)
    order = np.lexsort((rows[:, 5], rows[:, 4], rows[:, 3], rows[:, 2], rows[:, 1], ts))
    r, ts = rows[order], ts[order]
    local = ts + 19800                                    # IST seconds
    day = local // 86400                                  # the IST date, as days since 1970-01-01
    m = (local % 86400) // 60 - OPEN_MIN
    inside = (m >= 0) & (m < SESSION_MIN)
    outside = int((~inside).sum())
    r, day, m = r[inside], day[inside], m[inside]
    key = day * SESSION_MIN + m                           # sorted, so duplicates are adjacent
    last = np.r_[key[1:] != key[:-1], True] if len(key) else np.zeros(0, bool)
    r, day, m = r[last], day[last], m[last]
    days_seen = int(len(np.unique(day)))
    # Price sanity. Angel served India VIX divided by 100 for 2016-01-01 .. 2016-09-08 and on
    # 2021-03-01 (0.17 for 17): VIX has never traded below 8, so a value under 2 is rescaled.
    rescaled = 0
    if name == "INDIAVIX":
        small = (r[:, 1:5] > 0) & (r[:, 1:5] < VIX_SCALE_BELOW)
        rescaled = int(small.any(axis=1).sum())
        r[:, 1:5] = np.where(small, r[:, 1:5] * 100.0, r[:, 1:5])
    # A print at or below zero (Angel's -0.01 placeholder) is not a price; for an index or an index
    # ETF neither is one more than MAX_DEVIATION from its day's median close — index-wide circuit
    # breakers halt the market at 10/15/20% (stray opening prints in the ETFs). Such a row is
    # dropped: its minute is then missing (flat), and a day without a sane 09:15 is not kept.
    bad = (r[:, 1:5] <= 0).any(axis=1)
    if name != "INDIAVIX" and len(r):
        close = pd.Series(np.where(r[:, 4] > 0, r[:, 4], np.nan))
        med = close.groupby(day).transform("median").to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            dev = np.abs(r[:, 1:5] / med[:, None] - 1.0).max(axis=1)
        bad |= ~(dev <= MAX_DEVIATION)
    bad_prints = int(bad.sum())
    r, day, m = r[~bad], day[~bad], m[~bad]
    days_u, first_row, counts = np.unique(day, return_index=True, return_counts=True)
    has_open = m[first_row] == 0 if len(days_u) else np.zeros(0, bool)
    keep_day = has_open & (counts >= MIN_MINUTES)
    n = int(keep_day.sum())
    slot = np.full(len(days_u), -1)
    slot[keep_day] = np.arange(n)
    di = slot[np.searchsorted(days_u, day)]
    sel = di >= 0
    O, H, L, C, V = (np.full((n, SESSION_MIN), np.nan) for _ in range(5))
    present = np.zeros((n, SESSION_MIN), dtype=bool)
    rr, mm = di[sel], m[sel]
    for arr, col in ((O, 1), (H, 2), (L, 3), (C, 4), (V, 5)):
        arr[rr, mm] = r[sel, col]
    present[rr, mm] = True
    # a missing minute is flat at the close of the last minute that printed (minute 0 always did)
    src = np.where(present, np.arange(SESSION_MIN)[None, :], 0)
    np.maximum.accumulate(src, axis=1, out=src)
    flat = C[np.arange(n)[:, None], src]
    miss = ~present
    for arr in (O, H, L, C):
        arr[miss] = flat[miss]
    V[miss] = 0.0
    np.maximum(H, np.maximum(O, C), out=H)
    np.minimum(L, np.minimum(O, C), out=L)
    kept = days_u[keep_day].astype("datetime64[D]")
    q = {"rows": int(len(rows)), "outside_session": outside, "days_seen": days_seen, "days_kept": n,
         "bad_prints_dropped": bad_prints, "vix_rows_rescaled": rescaled,
         "dropped_no_0915": int((~has_open).sum()), "dropped_short": int((has_open & (counts < MIN_MINUTES)).sum()),
         "minutes_filled_flat": int(miss.sum()),
         "first": str(kept[0]) if n else None, "last": str(kept[-1]) if n else None}
    return Days(name, kept, O, H, L, C, V, q)


def bars(d: Days, tf: int) -> dict:
    """Session-anchored bars of `tf` minutes: arrays (days x nbars) plus each bar's minute span.
    `end[k]` is the index of the bar's LAST minute; a decision on bar k is known at minute end[k]+1."""
    if tf == 1:
        idx = np.arange(SESSION_MIN)
        return {"o": d.o, "h": d.h, "l": d.l, "c": d.c, "v": d.v, "start": idx, "end": idx}
    starts = np.arange(0, SESSION_MIN, tf)
    ends = np.minimum(starts + tf, SESSION_MIN) - 1
    o = d.o[:, starts]
    c = d.c[:, ends]
    h = np.stack([d.h[:, s:e + 1].max(axis=1) for s, e in zip(starts, ends)], axis=1)
    lo = np.stack([d.l[:, s:e + 1].min(axis=1) for s, e in zip(starts, ends)], axis=1)
    v = np.stack([d.v[:, s:e + 1].sum(axis=1) for s, e in zip(starts, ends)], axis=1)
    return {"o": o, "h": h, "l": lo, "c": c, "v": v, "start": starts, "end": ends}


def minute_of(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm) - OPEN_MIN


def align(a: Days, b: Days) -> tuple[np.ndarray, np.ndarray]:
    """Row indices of the days both series kept (for signal-on-index, fill-on-ETF tests)."""
    common, ia, ib = np.intersect1d(a.dates, b.dates, return_indices=True)
    return ia, ib
