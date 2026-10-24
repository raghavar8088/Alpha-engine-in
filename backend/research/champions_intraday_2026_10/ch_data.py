"""Minute arrays of each market's REGULAR session, in the layout of ../xauusd_intraday_2026_10/xi_data.py,
so that study's fill engine (xi_engine) runs unchanged.

  XAUUSD  gold: the COMEX day session 08:20-13:30 New York, cut from ../xauusd_intraday_2026_10/data/minute.npz
          (HistData one-minute bids; mid = bid + half the spread Dukascopy quoted that hour)
  SPXUSD  S&P 500: 09:30-16:00 New York        NSXUSD  Nasdaq 100: 09:30-16:00 New York
  GRXEUR  DAX: 09:00-17:30 Frankfurt
          HistData one-minute bars from 2010-11 (New York time with daylight saving, as verified for gold
          and checked again for each market in ch_checks.py); mid = price + half the base spread.
  WTI crude was fetched and dropped (ch_checks.py): HistData has no WTIUSD minutes for 2024 to May 2026,
  and its series jumps at monthly contract rolls (+35% over the weekend of 19 April 2020).

Per minute: t (UTC seconds), sess (session index), sm (minutes since the session's open), o/h/l/c, spread.
Per session: sess_date (the local calendar date), s_start/s_end, the session's o/h/l/c (d_*), and
reopen_jump: the price change across the market's last daily break before that session (for the roll check).
Sessions holding fewer than 60% of their minutes (holidays, half days, feed gaps) are dropped (80% would
also drop quiet days, which have fewer quoted minutes); prev_dropped marks a kept session whose weekday
predecessor was dropped. Two windows are cut out before anything else (EXCLUDE): every market from
2023-02-01 to 2023-07-31, where HistData thins the feed to about half its minutes, and the DAX from
2020-06-13 to 2023-12-03, where HistData's GRXEUR file holds Euro Stoxx 50 prices (about 3,100-4,400).

    python ch_data.py      # builds data/<SYM>.npz for the four HistData markets and data/XAUUSD.npz
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import io
import json
import zipfile
from dataclasses import dataclass

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
GOLD = ROOT.parent / "xauusd_intraday_2026_10" / "data" / "minute.npz"


@dataclass(frozen=True)
class Market:
    sym: str
    name: str
    tz: str
    open: tuple
    close: tuple
    half_spread: float          # added to HistData's price to make a mid (gold uses Dukascopy's quoted spread)

    @property
    def length(self) -> int:
        return (self.close[0] * 60 + self.close[1]) - (self.open[0] * 60 + self.open[1])


MARKETS = {
    "XAUUSD": Market("XAUUSD", "Gold", "America/New_York", (8, 20), (13, 30), 0.0),
    "SPXUSD": Market("SPXUSD", "S&P 500", "America/New_York", (9, 30), (16, 0), 0.125),
    "NSXUSD": Market("NSXUSD", "Nasdaq 100", "America/New_York", (9, 30), (16, 0), 0.25),
    "GRXEUR": Market("GRXEUR", "DAX", "Europe/Berlin", (9, 0), (17, 30), 0.5),
}
MIN_COVERAGE = 0.6
EXCLUDE = {"ALL": [("2023-02-01", "2023-07-31")], "GRXEUR": [("2020-06-13", "2023-12-03")]}


def _read(sym: str) -> pd.DataFrame:
    frames = []
    for p in sorted((ROOT / "data" / "raw" / sym.lower()).glob("*.zip")):
        z = zipfile.ZipFile(p)
        name = next(n for n in z.namelist() if n.endswith(".csv"))
        df = pd.read_csv(io.BytesIO(z.read(name)), sep=";", header=None, names=["ts", "o", "h", "l", "c", "v"])
        df.index = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S")
        frames.append(df[["o", "h", "l", "c"]])
    m1 = pd.concat(frames).sort_index()
    return m1[~m1.index.duplicated(keep="last")]


def _epoch(idx: pd.DatetimeIndex) -> np.ndarray:
    """UTC seconds, whatever the index's unit (pandas 3 keeps seconds or microseconds, not always nanoseconds)."""
    return idx.tz_convert("UTC").tz_localize(None).values.astype("datetime64[s]").astype(np.int64)


def _reopen_jumps(utc: pd.DatetimeIndex, o: np.ndarray, c: np.ndarray, tz: str) -> pd.Series:
    """Price change across each daily break (a gap of 45 minutes to 20 hours in the minutes), keyed by the
    local date of the first minute after it. Weekend gaps are left out: real news moves prices over them."""
    t = _epoch(utc)
    gap = np.diff(t)
    k = np.flatnonzero((gap >= 45 * 60) & (gap <= 20 * 3600)) + 1
    jump = o[k] / c[k - 1] - 1.0
    local = utc[k].tz_convert(tz)
    return pd.Series(jump, index=pd.DatetimeIndex(local.date))


def _sessions(m: Market, utc: pd.DatetimeIndex, o, h, l, c, spread) -> dict:
    local = utc.tz_convert(m.tz)
    lm = (local.hour * 60 + local.minute).values
    a = m.open[0] * 60 + m.open[1]
    day = np.array(local.date, dtype="datetime64[D]")
    keep = (lm >= a) & (lm < a + m.length) & (local.dayofweek < 5)
    for lo, hi in EXCLUDE["ALL"] + EXCLUDE.get(m.sym, []):
        keep &= ~((day >= np.datetime64(lo)) & (day <= np.datetime64(hi)))
    dates = day[keep]
    sd, sess = np.unique(dates, return_inverse=True)
    counts = np.bincount(sess)
    good = counts[sess] >= MIN_COVERAGE * m.length
    idx = np.flatnonzero(keep)[good]
    used, new = np.unique(sess[good], return_inverse=True)
    D = {"t": _epoch(utc)[idx], "sm": (lm[idx] - a).astype(np.int16), "o": o[idx], "h": h[idx], "l": l[idx], "c": c[idx],
         "spread": np.asarray(spread, dtype=np.float32)[idx] if np.ndim(spread) else np.full(len(idx), spread, dtype=np.float32),
         "sess": new.astype(np.int32), "sess_date": sd[used]}
    n = len(used)
    D["s_start"] = np.searchsorted(D["sess"], np.arange(n), side="left")
    D["s_end"] = np.searchsorted(D["sess"], np.arange(n), side="right")
    st, en = D["s_start"], D["s_end"]
    D["d_o"], D["d_c"] = D["o"][st], D["c"][en - 1]
    D["d_h"], D["d_l"] = np.maximum.reduceat(D["h"], st), np.minimum.reduceat(D["l"], st)
    D["dropped_sessions"] = np.array(int(len(counts) - n))
    # the weekday session just before a kept one was dropped (or missing): its 'previous session' values are stale
    ok = counts >= MIN_COVERAGE * m.length
    D["prev_dropped"] = np.array([u == 0 or not ok[u - 1] for u in used], dtype=bool)
    return D


def build(sym: str) -> dict:
    m = MARKETS[sym]
    if sym == "XAUUSD":
        z = np.load(GOLD)
        utc = pd.DatetimeIndex(pd.to_datetime(z["t"], unit="s", utc=True))
        o, h, l, c, spread = z["o"], z["h"], z["l"], z["c"], z["spread"]
        # gold's daily break is 17:00-18:00 New York; the HistData bids with Dukascopy's spread are already mids
    else:
        m1 = _read(sym)
        ny = m1.index.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
        ok = ~ny.isna()
        m1, ny = m1[ok], ny[ok]
        utc = ny.tz_convert("UTC")
        o, h, l, c = (m1[k].to_numpy(copy=True) + m.half_spread for k in ("o", "h", "l", "c"))
        spread = 2 * m.half_spread
    D = _sessions(m, utc, o, h, l, c, spread)
    jumps = _reopen_jumps(utc, o, c, m.tz)
    last = jumps.groupby(level=0).last()
    D["reopen_jump"] = last.reindex(pd.DatetimeIndex(D["sess_date"].astype("datetime64[ns]"))).to_numpy(dtype=float)
    np.savez(ROOT / "data" / f"{sym}.npz", **D)
    return D


def load(sym: str) -> dict:
    p = ROOT / "data" / f"{sym}.npz"
    if not p.exists():
        build(sym)
    z = np.load(p)
    return {k: z[k] for k in z.files}


if __name__ == "__main__":
    out = {}
    for sym in MARKETS:
        D = build(sym)
        out[sym] = {"sessions": int(len(D["s_start"])), "first": str(D["sess_date"][0]), "last": str(D["sess_date"][-1]),
                    "minutes": int(len(D["t"])), "dropped_sessions": int(D["dropped_sessions"])}
        print(sym, out[sym], flush=True)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "data_markets.json").write_text(json.dumps(out, indent=1))
