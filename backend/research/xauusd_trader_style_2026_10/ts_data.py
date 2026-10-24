"""Minute arrays for each market, in the layout of ../xauusd_intraday_2026_10/xi_data.py.

  XAUUSD   reused from ../xauusd_intraday_2026_10/data/minute.npz (mid = bid + half Dukascopy's quoted spread)
  XAGUSD, EURUSD, GBPUSD   HistData one-minute bids (New York time with daylight saving, as verified for
           gold), mid = bid + half the base spread of PREREGISTRATION.md; built into data/<SYM>.npz

    python ts_data.py           # builds the three markets and checks their clocks
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import io
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
GOLD = ROOT.parent / "xauusd_intraday_2026_10" / "data" / "minute.npz"
SPREAD = {"XAGUSD": 0.025, "EURUSD": 0.00002, "GBPUSD": 0.00004}


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


def build(sym: str) -> dict:
    m1 = _read(sym)
    ny = m1.index.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    keep = ~ny.isna()
    m1, ny = m1[keep], ny[keep]
    utc = ny.tz_convert("UTC")
    half = SPREAD[sym] / 2
    ny_min = (ny.hour * 60 + ny.minute).values
    sdate = np.array((ny + pd.Timedelta(hours=7)).date, dtype="datetime64[D]")
    dates, sess = np.unique(sdate, return_inverse=True)
    counts = np.bincount(sess)
    good = counts[sess] >= 120
    arrays = {"t": utc.values.astype("datetime64[s]").astype(np.int64)[good], "sm": ((ny_min - 1080) % 1440)[good].astype(np.int16),
              "o": m1["o"].values[good] + half, "h": m1["h"].values[good] + half, "l": m1["l"].values[good] + half, "c": m1["c"].values[good] + half,
              "spread": np.full(int(good.sum()), SPREAD[sym], dtype=np.float32)}
    used, new = np.unique(sess[good], return_inverse=True)
    arrays["sess"] = new.astype(np.int32)
    arrays["sess_date"] = dates[used]
    arrays["s_start"] = np.searchsorted(arrays["sess"], np.arange(len(used)), side="left")
    arrays["s_end"] = np.searchsorted(arrays["sess"], np.arange(len(used)), side="right")
    st, en = arrays["s_start"], arrays["s_end"]
    arrays["d_o"], arrays["d_c"] = arrays["o"][st], arrays["c"][en - 1]
    arrays["d_h"], arrays["d_l"] = np.maximum.reduceat(arrays["h"], st), np.minimum.reduceat(arrays["l"], st)
    np.savez(ROOT / "data" / f"{sym}.npz", **arrays)
    return arrays


def load(sym: str) -> dict:
    p = GOLD if sym == "XAUUSD" else ROOT / "data" / f"{sym}.npz"
    if sym != "XAUUSD" and not p.exists():
        build(sym)
    z = np.load(p)
    return {k: z[k] for k in z.files}


def clock_check(sym: str, D: dict) -> dict:
    """The weekly open should sit at about 17:00-18:00 New York in summer AND winter if the clock is
    New York time with daylight saving."""
    t = pd.to_datetime(D["t"][D["s_start"]], unit="s", utc=True).tz_convert("America/New_York")
    first = pd.Series(t.hour + t.minute / 60.0, index=t)
    sun = first[t.dayofweek == 6]
    summer = sun[sun.index.month.isin([6, 7, 8])].median()
    winter = sun[sun.index.month.isin([12, 1, 2])].median()
    return {"symbol": sym, "sessions": int(len(D["s_start"])), "first": str(t[0]), "last": str(pd.to_datetime(D["t"][-1], unit="s", utc=True)),
            "sunday_open_ny_hour_summer": float(summer), "sunday_open_ny_hour_winter": float(winter)}


if __name__ == "__main__":
    import json
    out = []
    for sym in ("XAGUSD", "EURUSD", "GBPUSD"):
        out.append(clock_check(sym, build(sym)))
        print(out[-1], flush=True)
    out.append(clock_check("XAUUSD", load("XAUUSD")))
    print(out[-1])
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "data_markets.json").write_text(json.dumps(out, indent=1))
